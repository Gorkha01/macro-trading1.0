"""Unit tests for ``volatility_target_scaling`` (Module 17.2 / Section 20.13, D-056).

Every expected value is hand-computed in the test that uses it.

Six specification defects are pinned here:

1. **Four of five declared ``RiskLimits`` are inert.** Section 20.13's body reads
   ``max_leverage`` and nothing else, while Section 17.3's prose claims sizing
   respects position, factor, drawdown and liquidity limits too.
2. **The golden test is a HIT, not a PARTITION.** ``test_vol_target_respects_hard_limits``
   is phrased about ``max_leverage`` alone, so it passes while four limits stay
   unenforced (lesson 49).
3. **``min()`` implements only an upper bound.** On the de-risking side — the
   side a vol target exists for — the ceiling cannot bind.
4. **``clipped_by_limits`` covers one side and reads as covering both.** A 75%
   cut reports ``clipped=False``.
5. **``current_gross_exposure``'s meaning is unstated**, and the spec's
   ``min(gross * scale, max_leverage)`` is only coherent under the multiple
   reading.
6. **A pre-existing leverage breach is reported as a vol-target adjustment.**

**A deliberate non-defect is pinned**: the base-state rule (lesson 5g) does not
apply, because the function's output is a *magnitude* rather than a label and
the probe measured a live clip rate of 0.0% — no state is modal by construction.

The mandatory golden test from Section 20.14 is present as
``test_vol_target_respects_hard_limits``.
"""

from __future__ import annotations

from typing import Any

import pytest

from macro_engine.config import RiskSettings, get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.portfolio import risk_budget
from macro_engine.portfolio.risk_budget import (
    RiskLimits,
    VolTargetInputs,
    volatility_target_scaling,
)

# The shipped policy. Built from config so a config change is visible here.
_LIMITS = RiskLimits.from_settings()


def _values_of(result: ModelResult) -> dict[str, Any]:
    """Narrow a ``ModelResult``'s published ``value`` to a dict for indexing.

    ``ModelResult.value`` is typed as a union (a result may carry a scalar), so
    indexing it needs a narrowing step. One helper rather than forty call sites,
    so the failure says so once. The assertion is the type system's
    requirement, not defensive noise: it would catch a change that made this
    function publish a scalar.
    """
    value = result.value
    assert isinstance(value, dict), (
        "volatility_target_scaling publishes a dict; a scalar would break every "
        "assertion in this file"
    )
    return value


def _scale(
    target: float = 0.10,
    current: float = 0.10,
    gross: float = 1.0,
    limits: RiskLimits | None = None,
) -> ModelResult:
    return volatility_target_scaling(
        VolTargetInputs(
            target_vol_annualized=target,
            current_portfolio_vol=current,
            current_gross_exposure=gross,
            limits=limits if limits is not None else _LIMITS,
        )
    )


def _values(
    target: float = 0.10,
    current: float = 0.10,
    gross: float = 1.0,
    limits: RiskLimits | None = None,
) -> dict[str, Any]:
    return _values_of(_scale(target, current, gross, limits))


# ---------------------------------------------------------------------------
# The mandatory Section 20.14 golden test
# ---------------------------------------------------------------------------


def test_vol_target_respects_hard_limits() -> None:
    """Section 20.14: engineer a scale that would exceed max_leverage; assert it clips.

    Hand-computed: target 0.10, current 0.05 -> scale 2.0. Gross 2.0 * 2.0 = 4.0
    requested, which is above the shipped 3.0 ceiling, so the final exposure is
    exactly 3.0 and the clip flag is set.
    """
    values = _values(target=0.10, current=0.05, gross=2.0)

    assert values["raw_scale"] == pytest.approx(2.0)
    assert values["requested_exposure"] == pytest.approx(4.0)
    assert values["final_exposure"] == pytest.approx(3.0)
    assert values["clipped_by_leverage_ceiling"] is True
    # The ceiling came from config, not from a literal in the function body.
    assert values["leverage_ceiling"] == pytest.approx(_LIMITS.max_leverage)


def test_the_ceiling_is_read_from_the_supplied_limits_not_a_literal() -> None:
    """A hardcoded 3.0 passes every test that uses the shipped config.

    Found by mutation ``M2.3``: no test in this file ever supplied a limits
    object whose ceiling differs from the shipped one, so ``ceiling = 3.0``
    survived the whole selection. A non-default value is the only way to
    distinguish a live read from a literal -- the same check the defect-class
    discipline prescribes for any contract parameter (grep for a call site
    supplying a non-default value, not merely a use).

    Hand-computed: target 0.10, current 0.05 -> scale 2.0. Gross 1.0 * 2.0 = 2.0,
    which is BELOW the shipped 3.0 ceiling and would not clip under the literal.
    With the supplied ceiling of 1.5 it clips to 1.5.
    """
    raised_ceiling = RiskLimits(
        max_position_pct_of_portfolio=0.15,
        max_factor_exposure_pct=0.30,
        max_leverage=1.5,
        min_liquidity_days_to_unwind=2,
    )
    values = _values(target=0.10, current=0.05, gross=1.0, limits=raised_ceiling)

    assert values["requested_exposure"] == pytest.approx(2.0)
    assert values["leverage_ceiling"] == pytest.approx(1.5), (
        "the ceiling must come from the supplied limits; the shipped 3.0 here "
        "means the function is reading a literal"
    )
    assert values["final_exposure"] == pytest.approx(1.5)
    assert values["clipped_by_leverage_ceiling"] is True

    # The mirror: the SAME inputs under the shipped 3.0 must not clip, so this
    # pair of assertions brackets the read on both sides.
    unchanged = _values(target=0.10, current=0.05, gross=1.0)
    assert unchanged["leverage_ceiling"] == pytest.approx(3.0)
    assert unchanged["clipped_by_leverage_ceiling"] is False


def test_the_golden_test_is_a_hit_not_a_partition() -> None:
    """Defect 2: the golden test names ONE limit and four stay unenforced.

    This is the lesson-49 distinction applied to Section 20.14 itself: N limits
    with 1 test is a hit. The companion assertion is that the untouched limits
    are *reported*, so "not tested" cannot be mistaken for "enforced".
    """
    values = _values()
    unenforced = values["limits_declared_but_not_enforced"]

    assert set(unenforced) == {
        "max_position_pct_of_portfolio",
        "max_factor_exposure_pct",
        "min_liquidity_days_to_unwind",
    }, (
        "exactly the limits Section 20.13 does not read must be named; a limit "
        "silently dropped from this list would be implied to be enforced"
    )
    # The golden test's limit is NOT in the unenforced list -- otherwise the
    # list would be a restatement of RiskLimits rather than a distinction.
    assert "max_leverage" not in unenforced


def test_every_risk_limit_field_is_either_enforced_or_disclosed() -> None:
    """The partition: each declared limit is enforced OR published as unenforced.

    Section 17.3 declares five fields and D-056 removes one
    (``max_drawdown_trigger_pct``), so four ship. Every one of the four must
    appear in exactly one of the two roles, and the two roles must not overlap.
    """
    shippable = set(RiskLimits.model_fields)
    values = _values()
    unenforced = set(values["limits_declared_but_not_enforced"])
    enforced = shippable - unenforced

    assert len(shippable) == 4, "O-45 resolution: the duplicate drawdown trigger is removed"
    assert enforced == {"max_leverage"}, (
        "exactly one limit is enforceable in terms of exposure alone"
    )
    # Partition, not overlap.
    assert enforced & unenforced == set()
    assert enforced | unenforced == shippable


# ---------------------------------------------------------------------------
# Defect 3 — the clip is one-sided and inert exactly when the risk is real
# ---------------------------------------------------------------------------


def test_the_clip_is_not_conditional_on_the_direction_of_scaling() -> None:
    """The ceiling binds on the DOWN side too, and no other test says so.

    Every other clipping test in this file scales **up** (``raw_scale > 1``), and
    every de-risking test happens to request an exposure well below the ceiling.
    So a version that applied ``min(scaled, ceiling)`` only when ``raw_scale >= 1``
    would pass the whole file -- and that version has the ceiling inert on
    exactly the path a vol target exists for. Found by mutation ``M3.2``; the
    test is written against the *implementation*'s structure rather than one
    input, because the gap is a missing partition and not a missing value.

    Hand-computed: target 0.10, current 0.40 -> scale 0.25 (a de-risking scale).
    Gross 20.0 * 0.25 = 5.0, which is above the 3.0 ceiling, so the clip MUST
    fire even though the book is being cut. The book was also already over the
    ceiling before scaling, so this pins both the clip and the attribution.
    """
    values = _values(target=0.10, current=0.40, gross=20.0)

    assert values["raw_scale"] == pytest.approx(0.25)
    assert values["raw_scale"] < 1.0, "the point is a DOWNWARD scale"
    # 20.0 * 0.25 = 5.0 requested, clipped to 3.0.
    assert values["requested_exposure"] == pytest.approx(5.0)
    assert values["final_exposure"] == pytest.approx(3.0)
    assert values["clipped_by_leverage_ceiling"] is True
    # The clip fired, and it fired on a de-risking scale -- which is the whole
    # reason this test exists.
    assert values["direction"] == "de-risk"


def test_the_ceiling_cannot_bind_on_the_de_risking_side() -> None:
    """Defect 3: at a vol spike the ceiling is far above the requested size.

    Hand-computed: target 0.10, current 0.40 -> scale 0.25. Gross 1.0 * 0.25 =
    0.25, which is below the 3.0 ceiling, so nothing clips. The mechanism is
    silent in the regime the function exists to handle.
    """
    values = _values(target=0.10, current=0.40, gross=1.0)

    assert values["raw_scale"] == pytest.approx(0.25)
    assert values["clipped_by_leverage_ceiling"] is False
    # ...and yet the book is cut by 75%, which the clip flag does not say.
    assert values["de_risking_fraction"] == pytest.approx(0.75)
    assert values["direction"] == "de-risk"


def test_a_deep_de_risking_is_reported_even_though_nothing_clips() -> None:
    """Defect 4: ``clipped=False`` must not read as "no constraint engaged".

    Hand-computed: target 0.10, current 4.00 -> scale 0.025, so the book goes to
    2.5% of its exposure. No ceiling binds. Under Section 20.13's published keys
    alone this result is indistinguishable from a book that did not move.
    """
    values = _values(target=0.10, current=4.0, gross=1.0)

    assert values["clipped_by_leverage_ceiling"] is False
    assert values["final_exposure"] == pytest.approx(0.025)
    assert values["de_risking_fraction"] == pytest.approx(0.975)
    assert values["direction"] == "de-risk"

    # The distinguishing key must be able to tell a still book from a cut one.
    still = _values(target=0.10, current=0.10, gross=1.0)
    assert still["de_risking_fraction"] == pytest.approx(0.0)
    assert still["clipped_by_leverage_ceiling"] is False
    assert still["de_risking_fraction"] != values["de_risking_fraction"]


def test_de_risking_fraction_is_zero_when_levering_up() -> None:
    """It is a *de-risking* magnitude, so it floors at zero rather than going negative.

    Hand-computed: target 0.10, current 0.05 -> scale 2.0, i.e. the book grows.
    A signed "change" would report -1.0 here; the published key is the fraction
    of risk removed, and none was.
    """
    values = _values(target=0.10, current=0.05, gross=0.5)

    assert values["raw_scale"] == pytest.approx(2.0)
    assert values["direction"] == "lever up"
    assert values["de_risking_fraction"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Defect 6 — a pre-existing breach is not a vol signal
# ---------------------------------------------------------------------------


def test_a_pre_existing_leverage_breach_is_attributed_not_silent() -> None:
    """Defect 6: a book already above the ceiling is cut, and the cause is named.

    Hand-computed: gross 5.0 (already above the 3.0 ceiling), scale 1.0 (vol at
    target) -> requested 5.0, final 3.0. Section 20.13 reports this as an
    ordinary vol-target adjustment with no warning. The cut is correct; reading
    it as a vol signal is not.
    """
    result = _scale(target=0.10, current=0.10, gross=5.0)
    values = _values_of(result)

    assert values["raw_scale"] == pytest.approx(1.0)
    assert values["clipped_by_leverage_ceiling"] is True
    assert values["pre_existing_leverage_breach"] is True

    joined = " ".join(result.warnings)
    assert "ALREADY above" in joined, "the breach must be attributed in a warning"
    assert "not a vol-target adjustment" in joined


def test_a_breach_correction_does_not_claim_the_vol_target_clipped_it() -> None:
    """The two clip causes are mutually exclusive in the warnings.

    A pre-existing breach and a vol-target overshoot can both produce
    ``clipped=True``, and only one of them is the vol target's doing. They must
    not both be reported for a single result.
    """
    breach = _scale(target=0.10, current=0.10, gross=5.0)
    overshoot = _scale(target=0.10, current=0.05, gross=2.0)

    breach_text = " ".join(breach.warnings)
    overshoot_text = " ".join(overshoot.warnings)

    assert "ALREADY above" in breach_text
    assert "vol target alone would size" not in breach_text, (
        "a breach correction must not also report a vol-target overshoot"
    )
    assert "ALREADY above" not in overshoot_text
    assert "vol target alone would size" in overshoot_text


def test_a_breach_at_or_below_the_ceiling_is_not_flagged() -> None:
    """The breach test is strict, matching the ceiling's own comparison.

    At gross exactly 3.0 the book is AT the ceiling, which the ceiling permits,
    so it is not a breach. The clip test is ``final < scaled`` on the same
    boundary and is likewise false.
    """
    values = _values(target=0.10, current=0.10, gross=3.0)

    assert values["final_exposure"] == pytest.approx(3.0)
    assert values["pre_existing_leverage_breach"] is False
    assert values["clipped_by_leverage_ceiling"] is False


# ---------------------------------------------------------------------------
# Defect 5 — the exposure reading the arithmetic depends on
# ---------------------------------------------------------------------------


def test_gross_exposure_scales_the_size_not_the_volatility() -> None:
    """Defect 5: the identity realised_vol == target_vol holds for EVERY gross.

    This is what fixes the reading. Under the multiple reading, scaling exposure
    by ``target/current`` makes the book's expected vol equal the target
    regardless of how big the book was. If ``gross`` instead scaled the vol, the
    realised vol would be ``gross * target`` and a vol target would be
    meaningless for any book that is not exactly 1.0x.
    """
    for gross in (0.5, 1.0, 2.0, 3.0):
        target, current = 0.10, 0.20
        result = _scale(target=target, current=current, gross=gross)
        values = _values_of(result)

        scale = values["raw_scale"]
        realised = current * scale  # the book's vol after scaling
        assert realised == pytest.approx(target), (
            f"at gross={gross} the scaled book's vol must be the target; got {realised}"
        )
        # And the requested exposure IS gross scaled -- the two readings differ.
        assert values["requested_exposure"] == pytest.approx(gross * target / current)


def test_the_requested_exposure_is_a_multiple_not_a_notional() -> None:
    """The ceiling comparison is only coherent because this is a multiple.

    Comparing a notional against ``max_leverage`` would be a unit error of the
    D-054 kind. The published key is bounded by the ceiling on exactly the
    multiples basis.
    """
    values = _values(target=0.10, current=0.05, gross=2.0)

    assert values["requested_exposure"] > values["leverage_ceiling"]
    assert values["final_exposure"] <= values["leverage_ceiling"]


# ---------------------------------------------------------------------------
# Direction and the reflexive warning
# ---------------------------------------------------------------------------


def test_direction_partitions_the_scale_axis() -> None:
    """``de-risk`` / ``hold`` / ``lever up`` must be a partition, not a hit.

    Three states with three tests would be a hit (lesson 49). The partition
    claim is that the three are exhaustive and mutually exclusive across a sweep
    that crosses both boundaries.
    """
    seen: dict[str, int] = {"de-risk": 0, "hold": 0, "lever up": 0}
    for current in (0.04, 0.05, 0.08, 0.10, 0.125, 0.20, 0.40):
        values = _values(target=0.10, current=current, gross=1.0)
        seen[values["direction"]] += 1

    assert all(count > 0 for count in seen.values()), (
        f"every direction must be reachable across the sweep; got {seen}"
    )
    # At scale exactly 1.0 the direction is `hold`, not one of the other two.
    exact = _values(target=0.10, current=0.10, gross=1.0)
    assert exact["direction"] == "hold"
    assert exact["raw_scale"] == pytest.approx(1.0)


def test_the_reflexive_warning_fires_below_the_configured_threshold() -> None:
    """Section 20.13's economic content, keyed on config rather than a literal.

    Hand-computed against the shipped threshold 0.8: a scale of 0.8 (current vol
    0.125 = target/0.8) does NOT warn because the comparison is strict, and 0.76
    (current vol ~0.1316) does.
    """
    threshold = get_settings().risk.reflexivity_scale_threshold
    assert threshold == pytest.approx(0.8), "fixture assumes the shipped threshold"

    at_threshold = _scale(target=0.10, current=0.125)
    below = _scale(target=0.10, current=0.132)

    assert _values_of(at_threshold)["raw_scale"] == pytest.approx(0.8, abs=1e-9)
    assert "reflexivity" not in " ".join(at_threshold.warnings), (
        "0.8 is not BELOW 0.8; the spec's comparison is strict"
    )
    assert "reflexivity" in " ".join(below.warnings)


def test_the_reflexive_warning_is_absent_when_levering_up() -> None:
    """The warning is about *de-risking* into a spike, so it cannot fire on a rise."""
    rising = _scale(target=0.10, current=0.05)

    assert _values_of(rising)["raw_scale"] == pytest.approx(2.0)
    assert "reflexivity" not in " ".join(rising.warnings)


def test_the_threshold_is_read_from_config_not_hardcoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hardcoded 0.8 would pass every other test in this file.

    The threshold is a *policy* number, so it must survive a config change. This
    moves the leaf and asserts the function's behaviour moves with it. The
    discriminating case is the one that **flips**: scale 0.625 warns under the
    shipped 0.8 and must fall silent under the moved 0.5. A test that only
    checked the still-warning case would pass with the literal hardcoded.
    """
    settings = get_settings()
    moved_risk = settings.risk.model_copy(
        update={
            "vol_target_reflexivity_scale": settings.risk.vol_target_reflexivity_scale.model_copy(
                update={"value": 0.5}
            )
        }
    )
    monkeypatch.setattr(
        "macro_engine.portfolio.risk_budget.get_settings",
        lambda: settings.model_copy(update={"risk": moved_risk}),
    )

    # Confirm the monkeypatch actually reached the function before asserting on
    # its behaviour -- otherwise a bad target path fails as a *behaviour* change
    # and reads like a real defect. The read goes through the module under test
    # (`risk_budget.get_settings`), not this file's own import: patching
    # rebinds the name in `risk_budget`, so the unpatched import would still
    # return the shipped 0.8 and the check would be worthless.
    # `get_settings` is an imported name rather than a declared export, so
    # `attr-defined` is the expected strict-mode complaint for reading it here.
    patched = risk_budget.get_settings  # type: ignore[attr-defined]
    assert patched().risk.reflexivity_scale_threshold == pytest.approx(0.5)

    # scale 0.625 (target 0.10, current 0.16): above 0.5 -> silent, where the
    # shipped 0.8 would have warned. This is the flip.
    assert "reflexivity" not in " ".join(_scale(target=0.10, current=0.16).warnings)
    # scale 0.4 (target 0.10, current 0.25): below 0.5 -> warns, same as before.
    assert "reflexivity" in " ".join(_scale(target=0.10, current=0.25).warnings)
    # scale 0.5 exactly: the comparison is strict `<`, so the boundary itself is
    # silent. Pinning this keeps a future `<=` from silently widening the guard.
    assert "reflexivity" not in " ".join(_scale(target=0.10, current=0.20).warnings)


# ---------------------------------------------------------------------------
# Contract, confidence, and the deliberate non-defect
# ---------------------------------------------------------------------------


def test_the_published_keys_are_exactly_the_documented_set() -> None:
    """A published-key rename is silent; this pins the vocabulary."""
    values = _values()

    assert set(values) == {
        "raw_scale",
        "requested_exposure",
        "final_exposure",
        "clipped_by_leverage_ceiling",
        "pre_existing_leverage_breach",
        "de_risking_fraction",
        "direction",
        "leverage_ceiling",
        "limits_declared_but_not_enforced",
    }


def test_the_published_floats_are_rounded_to_the_project_precision() -> None:
    """Unrounded floats make the value map unstable; nothing else checks it.

    Found by mutation ``M6.2``, which dropped one ``round(..., 6)`` and survived
    because every other assertion uses ``pytest.approx``. The input here is
    chosen to produce a **repeating** decimal -- 0.10 / 0.30 is 0.3333... -- so
    an unrounded value is not equal to its own 6-decimal form. Pinning the
    rounding as a *property* (``value == round(value, 6)``) rather than against
    a hand-typed constant keeps the test from becoming a second source of truth
    for the arithmetic.
    """
    values = _values(target=0.10, current=0.30, gross=1.0)

    for key in ("raw_scale", "requested_exposure", "final_exposure", "de_risking_fraction"):
        value = values[key]
        assert isinstance(value, float), f"{key} should publish a float"
        assert value == round(value, 6), (
            f"{key} = {value!r} is not rounded to 6 decimals -- the published "
            f"map would differ across platforms and runs"
        )
    # And confirm the fixture really is a repeating decimal, so the assertion
    # above is not vacuous.
    assert round(0.10 / 0.30, 6) != 0.10 / 0.30


def test_the_scale_is_identically_one_when_vol_is_at_target() -> None:
    """The no-op case: at target the book does not move, whatever its size.

    Hand-computed: scale 1.0 at any gross, so exposure is unchanged and nothing
    clips (unless the book was already breaching, which is the separate case).
    """
    for gross in (0.5, 1.0, 2.0):
        values = _values(target=0.10, current=0.10, gross=gross)

        assert values["raw_scale"] == pytest.approx(1.0)
        assert values["final_exposure"] == pytest.approx(gross)
        assert values["de_risking_fraction"] == pytest.approx(0.0)
        assert values["clipped_by_leverage_ceiling"] is False


def test_confidence_is_computed_not_asserted() -> None:
    """Section 22.8: a hardcoded confidence would survive every other test.

    The stated facts are no data-quality flags, the heuristic marker set (the
    target is a policy number, not a fitted estimate) and no unobservable
    dependence, so the value is the base less the heuristic penalty.
    """
    result = _scale()

    assert 0.0 < result.confidence <= 1.0
    assert result.confidence == pytest.approx(0.5), (
        "base 0.7 less the 0.2 heuristic penalty -- the project's midpoint"
    )


def test_the_function_never_places_an_order() -> None:
    """Section 1.1: this is a reasoning layer. The result reports a size.

    The system's whole scoping claim is that it does not execute. A published
    key that reads like an instruction would be the tell, so the vocabulary is
    checked for it.
    """
    values = _values()
    forbidden = ("order", "execute", "send", "place", "trade_id")

    for key in values:
        assert not any(word in key.lower() for word in forbidden), (
            f"published key {key!r} reads like an execution instruction"
        )


def test_the_context_states_the_limits_are_not_all_enforced() -> None:
    """The limitation is in the context, not only in a published list.

    A consumer reading `context` alone must learn that four declared limits are
    unenforced, or the prose implies a guarantee the function does not make.
    """
    result = _scale()

    assert "unforced" in result.context.lower() or "unenforced" in result.context.lower()
    assert "leverage ceiling" in result.context.lower()


def test_the_limits_declared_but_not_enforced_is_a_copy_not_an_alias() -> None:
    """Mutating the published list must not mutate the policy object.

    ``unread_by_vol_targeting`` builds a fresh list, so a consumer that sorts or
    pops the published value cannot corrupt the shared ``RiskLimits`` instance.
    """
    limits = RiskLimits.from_settings()
    values = _values(limits=limits)
    published = values["limits_declared_but_not_enforced"]

    assert published is not limits.unread_by_vol_targeting
    published.append("sentinel")
    assert "sentinel" not in limits.unread_by_vol_targeting


def test_inputs_used_names_the_raw_inputs_not_the_published_keys() -> None:
    """D-055's discipline: ``inputs_used`` names inputs, not outputs."""
    result = _scale()

    assert result.inputs_used == [
        "target_vol_annualized",
        "current_portfolio_vol",
        "current_gross_exposure",
    ]
    values = _values_of(result)
    assert not (set(result.inputs_used) & set(values)), (
        "an input that is also a published key means the list reports outputs"
    )


def test_the_base_state_failure_does_not_apply_here() -> None:
    """Lesson 5g is a hypothesis about the next function, not a specification.

    D-047/D-053 found classifiers whose own thresholds made the uninformative
    label modal. This function publishes a **magnitude**, not a label, so there
    is no "uninformative" value to be modal -- ``hold`` is the correct answer
    exactly when vol is at target and not otherwise.

    The recording matters because an unrecorded non-application is
    indistinguishable from an oversight. The evidence is the live probe: over
    575 real sessions the leverage ceiling bound **0.0%** of days while the
    reflexivity warning fired 11.3%, so neither the clip flag nor the warning is
    a constant.
    """
    scale = _values(target=0.10, current=0.10, gross=1.0)

    assert scale["direction"] == "hold"
    assert scale["de_risking_fraction"] == pytest.approx(0.0)
    # And `hold` is not modal across the swept axis: only the exact-target point
    # produces it.
    directions = {
        _values(target=0.10, current=c)["direction"] for c in (0.05, 0.08, 0.10, 0.15, 0.30)
    }
    assert directions == {"de-risk", "hold", "lever up"}
    assert len(directions) > 1, "a single modal label would be the base-state failure"


# ---------------------------------------------------------------------------
# Input validation and the boundary conventions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("current", [0.0, -0.01, -1.0])
def test_a_non_positive_current_vol_is_rejected(current: float) -> None:
    """It is the denominator, so the spec's own guard is on this input."""
    with pytest.raises(ValueError, match="current_portfolio_vol"):
        VolTargetInputs(
            target_vol_annualized=0.10,
            current_portfolio_vol=current,
            current_gross_exposure=1.0,
            limits=_LIMITS,
        )


@pytest.mark.parametrize("target", [0.0, -0.01])
def test_a_non_positive_target_vol_is_rejected(target: float) -> None:
    """A zero target says "hold no risk", which is an exit, not a scaling."""
    with pytest.raises(ValueError, match="target_vol_annualized"):
        VolTargetInputs(
            target_vol_annualized=target,
            current_portfolio_vol=0.10,
            current_gross_exposure=1.0,
            limits=_LIMITS,
        )


@pytest.mark.parametrize("gross", [0.0, -1.0])
def test_a_non_positive_gross_exposure_is_rejected(gross: float) -> None:
    """Zero gross is an empty book and negative gross is a data error."""
    with pytest.raises(ValueError, match="current_gross_exposure"):
        VolTargetInputs(
            target_vol_annualized=0.10,
            current_portfolio_vol=0.10,
            current_gross_exposure=gross,
            limits=_LIMITS,
        )


def test_the_input_models_forbid_extra_fields() -> None:
    """``extra="forbid"`` is load-bearing on both models.

    A typo'd kwarg would otherwise be silently ignored and the caller would read
    a result computed from the defaults.
    """
    with pytest.raises(ValueError, match="extra_forbidden"):
        VolTargetInputs(  # type: ignore[call-arg]
            target_vol_annualized=0.10,
            current_portfolio_vol=0.10,
            current_gross_exposure=1.0,
            limits=_LIMITS,
            target_vol_annualised=0.20,  # typos: British spelling
        )

    with pytest.raises(ValueError, match="extra_forbidden"):
        RiskLimits(  # type: ignore[call-arg]
            max_position_pct_of_portfolio=0.15,
            max_factor_exposure_pct=0.30,
            max_leverage=3.0,
            min_liquidity_days_to_unwind=2,
            max_drawdown_trigger_pct=0.10,  # the field O-45 removed
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_position_pct_of_portfolio", 15.0),
        ("max_factor_exposure_pct", 30.0),
    ],
)
def test_a_percent_written_into_a_fraction_field_is_rejected(field: str, value: float) -> None:
    """A percent in a fraction field is refused -- by the FIELD BOUND first.

    Section 17.3's fields end in ``_pct`` and hold **fractions**. Written as
    percents they are not merely wrong, they are **unreachable** -- a 1500%
    position limit never binds, so the constraint becomes inert and every
    sizing decision looks compliant. That is the D-054 failure direction, and a
    magnitude bound is what makes the convention checkable at all.

    **There are two layers and this test pins the one that actually fires.**
    ``RiskLimits`` carries ``le=1.0`` on both fraction fields, and pydantic
    validates field bounds before ``config.py``'s ``_reject_percent_in_fraction_field``
    model validator runs. So the message is pydantic's
    ``less_than_equal``, not the validator's prose. Asserting on the prose
    here would be asserting on a layer that is **unreachable from this
    input** -- the same class of mistake the second half of this test guards
    against. The validator is still load-bearing: it covers the *settings*
    leaves, which are bare ``CalibratedValue`` floats with no bound of their
    own (see ``test_a_percent_in_the_settings_leaf_is_rejected_by_the_validator``).
    """
    kwargs: dict[str, Any] = {
        "max_position_pct_of_portfolio": 0.15,
        "max_factor_exposure_pct": 0.30,
        "max_leverage": 3.0,
        "min_liquidity_days_to_unwind": 2,
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match="less_than_equal"):
        RiskLimits(**kwargs)


def test_the_field_bound_is_the_first_of_two_layers() -> None:
    """The model bound fires; the settings validator is a second, later layer.

    A defect here would be a **removed** bound, and that is what this asserts
    against: ``le=1.0`` is what makes the ``_pct``-holding-a-fraction convention
    checkable without a comment. ``1.01`` is chosen just above the bound so the
    failure is unambiguous.

    The two layers cover **different objects**. ``RiskLimits``'s fields carry
    bounds of their own, so pydantic refuses a percent there before any model
    validator runs. The ``config/settings.yaml`` leaves are bare
    ``CalibratedValue`` floats with no bound, so the percent is refused by
    ``RiskSettings._reject_percent_in_fraction_field`` instead -- and that is
    the layer that names the unit in its message. Asserting one without the
    other would leave half the guard unverified.
    """
    with pytest.raises(ValueError, match="less_than_equal"):
        RiskLimits(
            max_position_pct_of_portfolio=1.01,
            max_factor_exposure_pct=0.30,
            max_leverage=3.0,
            min_liquidity_days_to_unwind=2,
        )

    # The same 100x mistake reaching the settings leaf. `model_copy` does NOT
    # re-validate in pydantic v2, so the check goes through `model_validate` on
    # a rebuilt dict -- that is the path that runs a model validator.
    settings = get_settings()
    percent_leaf = settings.risk.max_position_pct_of_portfolio.model_copy(update={"value": 15.0})
    with pytest.raises(ValueError, match="FRACTIONS"):
        RiskSettings.model_validate(
            {**settings.risk.model_dump(), "max_position_pct_of_portfolio": percent_leaf}
        )


@pytest.mark.parametrize("value", [2.0, 3.0, 9.0])
def test_a_value_just_above_one_is_rejected_by_the_validator(value: float) -> None:
    """The BAND, not the extreme. Found by mutation ``CX3``.

    ``15.0`` is rejected by any bound from 1.0 to 14.0, so a test using only
    ``15.0`` cannot tell the validator's threshold from a loosened one. Widening
    the guard to ``<= 10.0`` -- which still rejects ``15.0`` and so *looks* alive
    -- survived the whole selection. These values sit in ``(1.0, 10.0)``, where
    only the correct ``<= 1.0`` bound rejects them.

    ``2.0``/``3.0`` are also the magnitudes a percent-written-as-a-fraction
    actually produces for a plausible policy (a "200% position limit"), which is
    why the band matters more than the extreme.
    """
    settings = get_settings()
    over_one = settings.risk.max_factor_exposure_pct.model_copy(update={"value": value})
    with pytest.raises(ValueError, match="FRACTIONS"):
        RiskSettings.model_validate(
            {**settings.risk.model_dump(), "max_factor_exposure_pct": over_one}
        )


def test_the_fraction_bound_admits_exactly_one() -> None:
    """``1.0`` is a legal limit, so the bound is ``le`` rather than ``lt``.

    A book permitted to be fully concentrated in one position is a real policy,
    and refusing it would make that policy unrepresentable. This is the same
    boundary reasoning as D-054's ``risk_reduction_pct le=1.0``.
    """
    limits = RiskLimits(
        max_position_pct_of_portfolio=1.0,
        max_factor_exposure_pct=1.0,
        max_leverage=1.0,
        min_liquidity_days_to_unwind=0,
    )
    assert limits.max_position_pct_of_portfolio == pytest.approx(1.0)
    assert limits.min_liquidity_days_to_unwind == 0


def test_the_leverage_ceiling_admits_exactly_one() -> None:
    """``1.0x`` is a legal ceiling (an unlevered book), so ``ge=1.0``.

    A ceiling below 1.0x describes a net-cash book rather than a leverage limit,
    which is a different policy object.
    """
    limits = RiskLimits(
        max_position_pct_of_portfolio=0.15,
        max_factor_exposure_pct=0.30,
        max_leverage=1.0,
        min_liquidity_days_to_unwind=2,
    )
    assert limits.max_leverage == pytest.approx(1.0)

    with pytest.raises(ValueError, match="greater_than_equal"):
        RiskLimits(
            max_position_pct_of_portfolio=0.15,
            max_factor_exposure_pct=0.30,
            max_leverage=0.5,
            min_liquidity_days_to_unwind=2,
        )


def test_the_shipped_config_parses_through_the_policy_constructor() -> None:
    """The config block has a consumer, so the shipped file is exercised.

    D-054's defect survived because nothing read the file through its accessor.
    ``from_settings`` is the first genuine consumer of these four leaves, and
    this asserts the shipped values rather than a fixture.
    """
    limits = RiskLimits.from_settings()

    assert limits.max_position_pct_of_portfolio == pytest.approx(0.15)
    assert limits.max_factor_exposure_pct == pytest.approx(0.30)
    assert limits.max_leverage == pytest.approx(3.0)
    assert limits.min_liquidity_days_to_unwind == 2


def test_the_removed_drawdown_trigger_is_absent_from_the_contract() -> None:
    """O-45 resolution: there is exactly ONE drawdown trigger in the system.

    D-054's ladder governs (``risk.drawdown_thresholds.tiers``, whose first rung
    is 10% expressed as the percent ``10.0``). Section 17.3 also declared
    ``max_drawdown_trigger_pct = 0.10`` -- the same trigger, in the fraction
    convention, with no stated precedence. Two configured triggers that can
    disagree is the D-037 class, and this function's signature has no drawdown
    input, so the duplicate is unreachable rather than merely unused.
    """
    assert "max_drawdown_trigger_pct" not in RiskLimits.model_fields

    # The surviving authority is the ladder, and its first rung is the same
    # trigger the removed field described -- so nothing was lost.
    first_rung_pct = min(t.drawdown_pct for t in get_settings().risk.drawdown_tiers)
    assert first_rung_pct == pytest.approx(10.0)
    assert first_rung_pct / 100.0 == pytest.approx(0.10)


def test_the_model_identity_is_the_function_it_claims_to_be() -> None:
    """``model_name`` is what a downstream consumer keys on."""
    result = _scale()

    assert result.model_name == "volatility_target_scaling"
    assert result.country == "us"
    assert result.as_of.tzinfo is not None, "utc_now() must yield a tz-aware datetime"
