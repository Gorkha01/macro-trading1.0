"""Tests for Module 9's ``intervention_capacity`` (Section 20.9).

The function is short and its content is a DOCTRINE, so the hazards are not
arithmetic ones. They are:

* **the direction branch.** Section 20.9's reference implementation ends in a
  bare ``else``, so every unrecognised direction silently takes the
  reserve-constrained branch. The tests therefore pin the refusal AND check that
  each accepted direction produces its OWN label — a fixture set that only ever
  exercises one direction would let a branch bug survive (the D-050 class).
* **the reserve unit.** The reachable series publishes MILLIONS and the model's
  contract is BILLIONS, so the conversion is asserted against a hand-computed
  value rather than against the code's own expression.
* **the confidence.** It is the PRODUCT of a computed value and a config cap, so
  both factors must be shown to move the published number. A test that only
  checked the cap would pass on a build where the computed half was dead code.
* **the refusal.** A strengthening verdict with no reserve stock must raise, not
  publish a null — the "null that travels as a value" shape.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, InterventionSettings, get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.intervention import (
    INTERVENTION_DIRECTIONS,
    InterventionCapacityInputs,
    intervention_capacity,
)

#: The weakening label Section 22.11 mandates. Written out here rather than
#: imported from the module's own constant so the assertion cannot pass by
#: reading the value under test (the `C6b` / D-050 defect).
_WEAKEN_LABEL = "MECHANICALLY_UNCONSTRAINED_COST_BOUNDED"

#: The strengthening label Section 20.9 supplies, retained verbatim.
_STRENGTHEN_LABEL = "RESERVE_CONSTRAINED_breakable"


def _settings_with(**values: object) -> InterventionSettings:
    """A settings object seeded from the SHIPPED block (D-114's structural fix).

    The four ``_fx_carry_settings`` helpers went stale four times because they
    hand-listed their fields; D-114 fixed that by seeding from
    ``dict(get_settings().fx_carry)``. The same rule applies here: a new leaf
    must not be able to make this fixture stale, so the base is the shipped
    block and only the named leaves are overridden.
    """
    base = dict(get_settings().intervention.model_dump())
    base.update(values)
    return InterventionSettings.model_validate(base)


def _inputs(**overrides: object) -> InterventionCapacityInputs:
    """An input model on the weakening path, with every override optional."""
    base: dict[str, object] = {
        "country": "jp",
        "direction": "weaken_own_currency",
        "fx_reserves_usd_bn": 1083.42,
    }
    base.update(overrides)
    return InterventionCapacityInputs.model_validate(base)


def _value(result: ModelResult) -> dict[str, object]:
    """The result's ``value`` as a mapping.

    Asserted rather than cast: the model promises a structured decomposition, so
    a bare scalar here is a contract violation and should fail loudly. Distinct
    from ``tests.helpers.as_dict``, which narrows a NESTED ``dict[str, float]``
    entry — this value is a flat mapping of mixed types (a label string, three
    numbers-or-None), which that helper's return type does not describe.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value, got {type(value).__name__}"
    )
    return value


# ---------------------------------------------------------------------------
# The direction -> label mapping. Section 20.9's bare `else` is the defect.
# ---------------------------------------------------------------------------


def test_each_direction_produces_its_own_label() -> None:
    """The two directions must not share a label, in either direction.

    This is the test Section 20.9's bare ``else`` would fail in one half: with
    ``strengthen`` mapped by equality and everything else falling into the
    weakening branch, a typo produces a weakening verdict. Both directions are
    exercised here so the mapping is pinned from both sides.
    """
    weaken = intervention_capacity(_inputs(direction="weaken_own_currency"))
    strengthen = intervention_capacity(
        _inputs(direction="strengthen_own_currency", fx_reserves_usd_bn=1083.42)
    )
    assert _value(weaken)["capacity"] == _WEAKEN_LABEL
    assert _value(strengthen)["capacity"] == _STRENGTHEN_LABEL


def test_an_unrecognised_direction_is_refused_not_defaulted() -> None:
    """A misspelt direction must raise, never take the other branch.

    Section 20.9's implementation has a documented-choice ``else``, so this is
    the exact input that reaches the wrong verdict there. The refusal is
    Pydantic's, from the ``Literal``, and the message must name the offending
    field rather than merely reporting a validation failure.
    """
    with pytest.raises(ValidationError, match="direction"):
        _inputs(direction="weakon_own_currency")


def test_the_direction_vocabulary_is_fully_covered_by_the_fixtures() -> None:
    """Every declared direction has a fixture, so none is untested.

    A guard against the fixture set drifting behind the vocabulary: if a third
    direction is added to ``INTERVENTION_DIRECTIONS``, this fails until a fixture
    exists for it. Without it, a new direction could ship with no branch and no
    test — the "looks complete" failure in the test suite itself.

    The ORDER is asserted too, not just the membership. A set comparison passed
    on a swapped tuple (``I2a``), and the tuple is a PUBLISHED constant: a
    caller that does ``INTERVENTION_DIRECTIONS[0]`` gets the strengthening
    member today, so reversing it is a behaviour change a membership check
    cannot see.
    """
    assert INTERVENTION_DIRECTIONS == (
        "strengthen_own_currency",
        "weaken_own_currency",
    )


# ---------------------------------------------------------------------------
# The reserve unit. Millions in, billions out, asserted by hand.
# ---------------------------------------------------------------------------


def test_the_reserve_input_is_published_in_billions_unchanged() -> None:
    """A caller-supplied stock is published as given, in billions."""
    result = intervention_capacity(_inputs(fx_reserves_usd_bn=169.3557))
    assert _value(result)["reserves_usd_bn"] == pytest.approx(169.3557, rel=1e-9)


def test_the_fetched_stock_is_converted_from_millions_to_billions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fetched reading in MILLIONS is divided by 1000, not passed through.

    The conversion is the whole reason the client returns the source unit: the
    series reads 1083420.49 (millions), which is 1083.42 billions, and a build
    that skipped the division would publish a stock 1000x too large while every
    number still looked like a reserve figure.

    ⚠️ **This test patches ``fetch_reserves`` — the CLIENT — not
    ``_fetch_reserves_bn``.** The first version patched the model's own helper
    and supplied the already-divided value (``1083420.49 / 1000.0``), which
    meant the MODEL's division line was never executed: a build that dropped
    ``/ MILLIONS_PER_BILLION`` published the same number and the test passed.
    That is the ``C6b`` / D-050 defect in its textbook form — **the test
    reproduced the code's own expression instead of measuring the code's
    output**. Patching at the client boundary forces the division to happen in
    the code under test, and the rescaling below (§ the second half) proves the
    divisor is load-bearing by moving it.
    """
    from macro_engine.data_layer.reserves_client import ReservesReading

    def _reading(mn: float) -> ReservesReading:
        return ReservesReading(
            symbol="TRESEGJPM052N",
            country_label="japan",
            reserves_usd_mn=mn,
            observation_date="2026-08-01",
            change_12m_pct=-11.98,
            source_unit="millions of USD",
            observation_count=843,
        )

    monkeypatch.setattr(
        "macro_engine.models.intervention.fetch_reserves",
        lambda country: _reading(1083420.49),
    )
    result = intervention_capacity(
        InterventionCapacityInputs(
            country="jp", direction="strengthen_own_currency", fx_reserves_usd_bn=None
        )
    )
    assert _value(result)["reserves_usd_bn"] == pytest.approx(1083.42049, rel=1e-9)

    # The divisor is load-bearing: move the CLIENT's constant and the published
    # figure must move with it. This is the perturbation that kills a mutant
    # which changed or removed the division — a value-comparison alone cannot,
    # because a mutant and the shipped code both produce "a number".
    monkeypatch.setattr(
        "macro_engine.models.intervention.MILLIONS_PER_BILLION",
        500.0,
    )
    rescaled = intervention_capacity(
        InterventionCapacityInputs(
            country="jp", direction="strengthen_own_currency", fx_reserves_usd_bn=None
        )
    )
    assert _value(rescaled)["reserves_usd_bn"] == pytest.approx(1083420.49 / 500.0, rel=1e-9)


def test_the_fetched_burn_rate_is_adopted_only_when_the_stock_is_also_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fetched burn rate reaches the published field — but only on the fetch path.

    **I3c's guard, and a design boundary the first draft of this test got
    wrong.** The burn rate has two sources: the caller's field and the fetched
    reading. The fetched one is adopted ONLY when the caller supplied no STOCK
    either, because the stock and its burn rate are two facts about ONE series:

    * a caller who supplies **no stock** gets the whole fetched reading — level
      and burn — from one series, and the fallback adopts the burn;
    * a caller who supplies a **stock** is asserting they have their own source,
      so adopting a burn from a *different* series would pair two vintages. The
      model leaves the burn at ``None`` and discloses it, rather than silently
      mixing sources — the same "a dead fallback reads exactly like a live
      fetch" hazard the module docstring names.

    The first version of this test asserted the burn *was* fetched while a stock
    was supplied, which the code does not do. That was **the test being wrong,
    not the code**: the correct behaviour is per-series provenance, and the test
    now pins BOTH halves so neither can drift.
    """
    from macro_engine.data_layer.reserves_client import ReservesReading

    def _reading() -> ReservesReading:
        return ReservesReading(
            symbol="TRESEGJPM052N",
            country_label="japan",
            reserves_usd_mn=1083420.49,
            observation_date="2026-08-01",
            change_12m_pct=-11.98,
            source_unit="millions of USD",
            observation_count=843,
        )

    monkeypatch.setattr(
        "macro_engine.models.intervention.fetch_reserves",
        lambda country: _reading(),
    )

    # Half 1: no stock supplied -> the whole reading is fetched, burn included.
    fetched = intervention_capacity(
        InterventionCapacityInputs(
            country="jp", direction="strengthen_own_currency", fx_reserves_usd_bn=None
        )
    )
    assert _value(fetched)["reserves_change_12m_pct"] == pytest.approx(-11.98, rel=1e-12)

    # Half 2: a supplied stock does NOT borrow a burn rate from the live series.
    supplied = intervention_capacity(_inputs(fx_reserves_usd_bn=1083.42))
    assert _value(supplied)["reserves_change_12m_pct"] is None
    assert any("UNKNOWN" in w for w in supplied.warnings)

    # Half 3: a caller-supplied burn rate is used as given, never overwritten.
    explicit = intervention_capacity(
        _inputs(fx_reserves_usd_bn=1083.42, reserves_change_12m_pct=+3.5)
    )
    assert _value(explicit)["reserves_change_12m_pct"] == pytest.approx(3.5, rel=1e-12)


def test_the_unit_field_names_billions() -> None:
    """The published unit names the scale, so a reader is not left to infer it."""
    result = intervention_capacity(_inputs())
    assert result.unit == "usd_billions"


# ---------------------------------------------------------------------------
# The confidence: a PRODUCT, and both factors must move it.
# ---------------------------------------------------------------------------


def test_the_confidence_is_the_computed_value_times_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The published confidence is exactly ``computed * cap``, both measured.

    Both factors are read from their own producers here — ``compute_confidence``
    for the input half and the settings' property for the method half — so the
    test cannot pass by reproducing the model's own expression.
    """
    settings = get_settings().intervention
    expected_computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=not settings.reliability_cap_is_calibrated,
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    result = intervention_capacity(_inputs(fx_reserves_usd_bn=100.0))
    assert result.confidence == pytest.approx(
        expected_computed * settings.reliability_value, rel=1e-12
    )


def test_a_fetched_reserve_gives_a_higher_confidence_than_a_supplied_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The input-quality half is load-bearing, not scaffolding.

    This is the test a ``min()`` implementation FAILS. The computed value is
    fractionally above the cap, so ``min(computed, cap)`` publishes the cap on
    both paths and the two origins become indistinguishable. Under the shipped
    product they must differ, and a fetched reading must be the higher one — the
    same ordering ``ppp_valuation`` records for its fetched versus typed legs.

    **The fetched value is also asserted EXACTLY**, against a recomputation that
    names ``source_independence_count=1``. Without that, ``I5e`` (which sets the
    count to 0 on the fetched path) survived: an ordering assertion still holds
    if the fetched count is wrong, because the flag difference alone keeps
    fetched above supplied. The exact form pins the count to the number that
    produces it.
    """
    monkeypatch.setattr(
        "macro_engine.models.intervention._fetch_reserves_bn",
        lambda country: (1083.42, -11.98, "FETCHED — test double"),
    )
    fetched = intervention_capacity(
        InterventionCapacityInputs(
            country="jp", direction="strengthen_own_currency", fx_reserves_usd_bn=None
        )
    )
    supplied = intervention_capacity(_inputs(fx_reserves_usd_bn=1083.42))
    assert fetched.confidence > supplied.confidence

    # The fetched run contributes ONE independent family and carries NO
    # data-quality flag (the data is measured, not typed); the supplied run is
    # the mirror image. Both are recomputed here rather than read off the model.
    settings = get_settings().intervention
    expected_fetched = (
        compute_confidence(
            ConfidenceInputs(
                data_quality_flags_present=False,
                is_heuristic_not_calibrated=not settings.reliability_cap_is_calibrated,
                source_independence_count=1,
                depends_on_unobservable=False,
            )
        )
        * settings.reliability_value
    )
    assert fetched.confidence == pytest.approx(expected_fetched, rel=1e-12)


def test_the_cap_perturbation_moves_the_published_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-050's leaf-perturbation guard: perturb the SHIPPED leaf, never compare a literal.

    The defect this closes is the `C6b` class — a mutation that writes the
    shipped value back survives because the test compared the value against
    itself. Here the cap leaf is monkeypatched to an arbitrary value and the
    published confidence must move with it.
    """
    sentinel = 0.037
    perturbed = _settings_with(
        reliability_cap=CalibratedValue(
            value=sentinel,
            calibration_status="uncalibrated_illustrative",
            note="perturbation",
        )
    )
    monkeypatch.setattr(
        "macro_engine.models.intervention.get_settings",
        lambda: _StubSettings(perturbed),
    )
    result = intervention_capacity(_inputs(fx_reserves_usd_bn=100.0))
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=perturbed.reliability_cap_is_calibrated is False,
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == pytest.approx(computed * sentinel, rel=1e-12)
    assert result.confidence < computed, "the cap must bind strictly below the computed half"


class _StubSettings:
    """A settings object exposing only ``intervention``, for the cap perturbation."""

    def __init__(self, intervention: InterventionSettings) -> None:
        self.intervention = intervention


# ---------------------------------------------------------------------------
# The refusal. A strengthening verdict without a stock is not made.
# ---------------------------------------------------------------------------


def test_strengthening_without_reserves_refuses_rather_than_publishing_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claim cannot be supported, so it is not made.

    Section 20.9 publishes ``reserves_usd_bn: None`` beside a 0.7-confidence
    verdict. That is the silent shape: the result LOOKS complete and carries a
    null where its central quantity should be. The model refuses instead.
    """
    monkeypatch.setattr(
        "macro_engine.models.intervention._fetch_reserves_bn",
        lambda country: (None, None, "NOT AVAILABLE — test double"),
    )
    with pytest.raises(ValueError, match="strengthen_own_currency"):
        intervention_capacity(
            InterventionCapacityInputs(
                country="de", direction="strengthen_own_currency", fx_reserves_usd_bn=None
            )
        )


def test_weakening_without_reserves_proceeds_and_discloses_the_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A weakening verdict does not NEED the stock, so it proceeds — disclosed.

    The negative control for the refusal above: the same missing reserve must
    NOT raise on this path, and the absence must appear as a warning rather than
    as a silent None. Both halves are asserted, so a build that raised on every
    direction would fail here.
    """
    monkeypatch.setattr(
        "macro_engine.models.intervention._fetch_reserves_bn",
        lambda country: (None, None, "NOT AVAILABLE — test double"),
    )
    result = intervention_capacity(
        InterventionCapacityInputs(
            country="de", direction="weaken_own_currency", fx_reserves_usd_bn=None
        )
    )
    assert _value(result)["capacity"] == _WEAKEN_LABEL
    assert _value(result)["reserves_usd_bn"] is None
    assert any("DEPLETION RATE" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Domain guards on the input model.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0.0, -1.0, -1083.42])
def test_a_non_positive_reserve_stock_is_refused(bad: float) -> None:
    """Zero is not a stock and a negative one inverts the reading."""
    with pytest.raises(ValidationError, match="strictly positive"):
        _inputs(fx_reserves_usd_bn=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_reserve_stock_is_refused(bad: float) -> None:
    """``nan`` must be REFUSED, not guarded — it fails every comparison (D-078).

    The negative control for the positivity guard: a ``<= 0`` test alone lets
    ``nan`` through, since ``nan <= 0`` is False and ``nan > 0`` is also False.
    """
    with pytest.raises(ValidationError, match="finite"):
        _inputs(fx_reserves_usd_bn=bad)


@pytest.mark.parametrize("field", ["reserves_to_gdp_pct", "reserves_change_12m_pct"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_optional_field_is_refused(field: str, bad: float) -> None:
    """The other two optional numerics get the same finiteness guard."""
    with pytest.raises(ValidationError, match="finite"):
        _inputs(**{field: bad})


def test_an_unknown_input_key_is_refused() -> None:
    """``extra="forbid"`` — a misspelled field must not be silently ignored."""
    with pytest.raises(ValidationError):
        _inputs(reserve_usd_bn=10.0)


def test_the_published_burn_rate_echoes_the_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """``reserves_change_12m_pct`` is published, not nulled or constant.

    **I7c's guard.** The published field is what a downstream reader (and
    ``check_trilemma_tension``'s "reserves are burning" clause) keys on, so a
    build that nulled it or hardcoded a value would hide the one signal this
    function adds. A distinct, non-round figure is used so a constant cannot
    coincide with it.
    """
    result = intervention_capacity(_inputs(reserves_change_12m_pct=-7.31))
    assert _value(result)["reserves_change_12m_pct"] == pytest.approx(-7.31, rel=1e-12)


def test_the_published_direction_echoes_the_input() -> None:
    """``direction`` is published, not a constant.

    **I7d's guard.** Section 20.9's reference implementation publishes the
    capacity label but not the direction it was derived from, so a caller cannot
    check the derivation. This model publishes both; a build that pinned the
    direction to one literal would make the label un-auditable while every
    other field still looked right.
    """
    weaken = intervention_capacity(_inputs(direction="weaken_own_currency"))
    assert _value(weaken)["direction"] == "weaken_own_currency"
    strengthen = intervention_capacity(
        _inputs(direction="strengthen_own_currency", fx_reserves_usd_bn=100.0)
    )
    assert _value(strengthen)["direction"] == "strengthen_own_currency"


# ---------------------------------------------------------------------------
# The burn warning. Section 20.9 has no counterpart, so it is pinned hard.
# ---------------------------------------------------------------------------


def test_the_burn_warning_is_direction_independent_and_fires_on_both_paths() -> None:
    """A reserve decline is a fact about the world, not about the direction.

    The first draft of the model gated this warning behind the
    reserve-constrained branch, and the boundary test below caught it. The
    reason it is wrong: a bank defending by WEAKENING its currency can also be
    spending reserves (the SNB's 2015 expansion is the model's own cited
    example), so gating the alert suppressed the depletion signal on the
    direction whose failure this function calls cost-driven. Both branches are
    asserted, so a build that re-gates it fails here.
    """
    alert = get_settings().intervention.burn_alert_value
    for direction in ("strengthen_own_currency", "weaken_own_currency"):
        result = intervention_capacity(
            _inputs(
                direction=direction,
                fx_reserves_usd_bn=100.0,
                reserves_change_12m_pct=-alert - 1.0,
            )
        )
        assert any("BURNING" in w for w in result.warnings), direction


def test_the_burn_warning_fires_at_or_below_the_alert_threshold() -> None:
    """A decline at the threshold fires it; the boundary is inclusive."""
    alert = get_settings().intervention.burn_alert_value
    fires = intervention_capacity(_inputs(reserves_change_12m_pct=-alert))
    silent = intervention_capacity(_inputs(reserves_change_12m_pct=-alert + 0.01))
    assert any("BURNING" in w for w in fires.warnings)
    assert not any("BURNING" in w for w in silent.warnings)


def test_the_burn_warning_names_the_trilemma_pairing_on_a_strengthening_defence() -> None:
    """The burn message's BRANCH is correct, and the text distinguishes the cases.

    **I6d/I6e's guard.** The burn warning appends a *different* tail depending on
    the direction: a reserve-constrained defence gets the ``CRITICAL_PEG_STRESS``
    pairing that Section 20.9 names, a cost-bounded one gets the
    depletion-is-a-fact-of-the-world text. The first version of this file only
    asserted ``"BURNING" in w``, so inverting the branch condition (``I6d``) or
    swapping the message body (``I6e``) both survived. Both tails are asserted
    here, in both directions, so each is pinned to its own case.
    """
    alert = get_settings().intervention.burn_alert_value
    strengthen = intervention_capacity(
        _inputs(
            direction="strengthen_own_currency",
            fx_reserves_usd_bn=100.0,
            reserves_change_12m_pct=-alert - 1.0,
        )
    )
    weak = intervention_capacity(
        _inputs(
            direction="weaken_own_currency",
            reserves_change_12m_pct=-alert - 1.0,
        )
    )
    strong_burn = next(w for w in strengthen.warnings if "BURNING" in w)
    weak_burn = next(w for w in weak.warnings if "BURNING" in w)
    assert "CRITICAL_PEG_STRESS" in strong_burn
    assert "CRITICAL_PEG_STRESS" not in weak_burn
    # And the weakening tail is its own claim, not silence.
    assert "depletion is a fact about the reserve position" in weak_burn


def test_the_burn_warning_does_not_fire_on_reserve_accumulation() -> None:
    """A RISING stock is not a burn — the sign must be handled, not ignored.

    Without this, a build that dropped the sign (comparing the unsigned change
    against the alert) would warn "reserves are burning" on a country whose
    reserves are growing, which is a plausible-looking inversion of the one
    signal this function adds.
    """
    alert = get_settings().intervention.burn_alert_value
    result = intervention_capacity(_inputs(reserves_change_12m_pct=+alert + 5.0))
    assert not any("BURNING" in w for w in result.warnings)


def test_an_absent_burn_rate_is_disclosed_and_never_treated_as_zero() -> None:
    """A missing change warns; it must not read as "stable".

    ``None`` and ``0.0`` are different statements and only one of them is true
    when the change is unknown.
    """
    result = intervention_capacity(_inputs(reserves_change_12m_pct=None))
    assert any("UNKNOWN" in w for w in result.warnings)
    assert _value(result)["reserves_change_12m_pct"] is None


# ---------------------------------------------------------------------------
# Provenance and the reasoning contract.
# ---------------------------------------------------------------------------


def test_a_supplied_reserve_is_disclosed_as_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typed number must never read like a measured one (D-117's rule).

    The disclosure must DISCRIMINATE: the fetched path says FETCHED and the
    supplied path says SUPPLIED, and this test asserts both halves so neither can
    be made to read like the other.
    """
    supplied = intervention_capacity(_inputs(fx_reserves_usd_bn=100.0))
    assert any("SUPPLIED BY THE CALLER" in p for p in supplied.data_provenance)

    monkeypatch.setattr(
        "macro_engine.models.intervention._fetch_reserves_bn",
        lambda country: (100.0, None, "FETCHED — test double"),
    )
    fetched = intervention_capacity(
        InterventionCapacityInputs(
            country="jp", direction="strengthen_own_currency", fx_reserves_usd_bn=None
        )
    )
    assert any("FETCHED" in p for p in fetched.data_provenance)
    assert not any("SUPPLIED" in p for p in fetched.data_provenance)


def test_the_source_family_distinguishes_fetched_from_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module 13's independence tag follows the same split."""
    supplied = intervention_capacity(_inputs(fx_reserves_usd_bn=100.0))
    assert supplied.source_family is EvidenceSourceFamily.MANUAL_ASSESSMENT

    monkeypatch.setattr(
        "macro_engine.models.intervention._fetch_reserves_bn",
        lambda country: (100.0, None, "FETCHED — test double"),
    )
    fetched = intervention_capacity(
        InterventionCapacityInputs(
            country="jp", direction="strengthen_own_currency", fx_reserves_usd_bn=None
        )
    )
    assert fetched.source_family is EvidenceSourceFamily.IMF


def test_a_missing_reserves_to_gdp_is_disclosed() -> None:
    """The unscaled stock is a limitation the result states."""
    result = intervention_capacity(_inputs(reserves_to_gdp_pct=None))
    assert any("not supplied" in a for a in result.assumptions)


def test_a_missing_reserves_to_gdp_reads_as_unscaled() -> None:
    """D-139: the absence of the ratio yields the UNSCALED verdict, not silence."""
    result = intervention_capacity(_inputs(reserves_to_gdp_pct=None))
    assert _value(result)["reserves_scale"] == "UNSCALED"


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(1.0, "THIN"), (19.9, "THIN"), (20.0, "AMPLE"), (35.0, "AMPLE")],
)
def test_the_reserves_scale_verdict_is_computed_from_the_ratio(ratio: float, expected: str) -> None:
    """D-139: `reserves_to_gdp_pct` is CONSUMED, not merely echoed.

    Before this fix the field description claimed it was "used as an AMPLE/THIN
    scale" while no code path read it — a phantom input. The boundary is the
    configured threshold (20% by default), inclusive on the AMPLE side, which is
    why 20.0 must read AMPLE and 19.9 must read THIN: a reader who cannot see
    which side a boundary value falls on cannot check the verdict.
    """
    result = intervention_capacity(_inputs(reserves_to_gdp_pct=ratio))
    assert _value(result)["reserves_scale"] == expected


def test_the_ample_threshold_is_read_from_config_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-139 MOVER test: the AMPLE/THIN boundary is a leaf-read.

    A ratio of 12.5% is THIN at the default 20% boundary. Moving the boundary
    DOWN to 10% must flip the same input to AMPLE. A literal boundary in the
    body would leave the verdict unchanged — which is exactly the difference
    the test exists to catch.
    """
    settings = get_settings().intervention
    monkeypatch.setattr(settings.reserves_to_gdp_ample_threshold_pct, "value", 10.0, raising=False)
    result = intervention_capacity(_inputs(reserves_to_gdp_pct=12.5))
    assert _value(result)["reserves_scale"] == "AMPLE", (
        "the AMPLE boundary did not follow the moved config leaf; a 12.5% ratio "
        "at a 10% boundary must read AMPLE"
    )


def test_the_scale_verdict_does_not_change_the_capacity_label() -> None:
    """D-139: the scale is a DISCLOSURE, never a gate on the capacity label.

    The label is decided by the direction's MECHANICS — a finite stock is finite
    whether or not it looks small next to GDP. A THIN stock and an AMPLE one must
    still carry the same direction-derived label, or the scale has smuggled a
    second, undocumented decision rule into the model.
    """
    thin = intervention_capacity(
        _inputs(
            direction="strengthen_own_currency", fx_reserves_usd_bn=100.0, reserves_to_gdp_pct=1.0
        )
    )
    ample = intervention_capacity(
        _inputs(
            direction="strengthen_own_currency", fx_reserves_usd_bn=100.0, reserves_to_gdp_pct=50.0
        )
    )
    assert _value(thin)["reserves_scale"] == "THIN"
    assert _value(ample)["reserves_scale"] == "AMPLE"
    assert _value(thin)["capacity"] == _value(ample)["capacity"], (
        "the capacity label must be direction-derived only; the scale verdict must not alter it"
    )


def test_the_result_names_its_inputs_and_model() -> None:
    """The reasoning contract: the model is identifiable and lists its inputs."""
    result = intervention_capacity(_inputs(reserves_to_gdp_pct=5.1))
    assert result.model_name == "intervention_capacity"
    assert result.country == "jp"
    assert "reserves_to_gdp_pct" in result.inputs_used
    assert _value(result)["reserves_to_gdp_pct"] == pytest.approx(5.1)


def test_the_weakening_warning_never_claims_permanence() -> None:
    """Section 22.11's whole point: "unlimited" must not read as risk-free."""
    result = intervention_capacity(_inputs(direction="weaken_own_currency"))
    joined = " ".join(result.warnings)
    assert "COST" in joined
    assert "SNB 2015" in joined


def test_the_strengthening_warning_names_the_trilemma_pairing() -> None:
    """The integration edge: Section 20.9 pairs this with check_trilemma_tension."""
    result = intervention_capacity(
        _inputs(direction="strengthen_own_currency", fx_reserves_usd_bn=100.0)
    )
    assert any("check_trilemma_tension" in w for w in result.warnings)


def test_the_confidence_stays_inside_the_unit_interval() -> None:
    """Whatever the product yields, ModelResult's own constraint must hold.

    A cap and a computed value both inside [0, 1] multiply to something inside
    it, so this can only fail if one of them escapes — which is the check's
    purpose.
    """
    result = intervention_capacity(_inputs(fx_reserves_usd_bn=100.0))
    assert 0.0 <= result.confidence <= 1.0
    assert not math.isnan(result.confidence)


# ---------------------------------------------------------------------------
# The config block. Each accessor reads its OWN leaf, and the validators fire.
#
# ⚠️ These four tests close the ``N*`` survivors, and the reason they were
# missing is worth recording: the model-side tests exercise the config ONLY
# through the shipped default values, where a cross-wired accessor is invisible.
# ``N3a`` (the burn accessor returning the RELIABILITY cap) survived because no
# test read ``burn_alert_value`` against a value only that leaf can produce;
# ``N1b`` (``reliability_cap_is_calibrated`` hardcoded True) survived because the
# shipped leaf IS uncalibrated, so the constant coincided with the truth. Both
# are the D-050 class: a comparison the shipped value happens to satisfy.
# ---------------------------------------------------------------------------


def test_the_reliability_calibration_flag_follows_its_leaf() -> None:
    """``reliability_cap_is_calibrated`` reads the LEAF, not a constant.

    ``N1b``'s guard. The shipped cap is ``uncalibrated_illustrative``, so a
    build that returned ``True`` unconditionally agreed with the truth and
    survived. The fix pins the flag against a leaf that is KNOWN uncalibrated
    and one that is KNOWN calibrated, so either constant form fails.
    """
    shipped = get_settings().intervention
    # The shipped leaf's real status, read from the leaf itself.
    assert shipped.reliability_cap_is_calibrated is shipped.reliability_cap.is_trustworthy
    assert shipped.reliability_cap_is_calibrated is False, (
        "the shipped cap is documented as uncalibrated_illustrative; if that "
        "changed, this test's premise moved and should be re-derived"
    )

    calibrated = _settings_with(
        reliability_cap=CalibratedValue(
            value=0.12,
            calibration_status="conventional",
            note="test: a trustworthy cap",
        )
    )
    assert calibrated.reliability_cap_is_calibrated is True


def test_the_burn_alert_accessor_reads_its_own_leaf() -> None:
    """``burn_alert_value`` returns the burn leaf, not a sibling's.

    ``N3a``'s guard: the accessor returning ``reliability_cap.value`` survived
    because nothing asserted the burn threshold against a value the reliability
    cap cannot also produce. The perturbation below sets the two leaves to
    DISTINCT sentinels, so a cross-wired accessor publishes the wrong one.
    """
    perturbed = _settings_with(
        reliability_cap=CalibratedValue(
            value=0.011, calibration_status="uncalibrated_illustrative", note="cap sentinel"
        ),
        burn_alert_pct=CalibratedValue(
            value=42.5, calibration_status="uncalibrated_illustrative", note="burn sentinel"
        ),
    )
    assert perturbed.burn_alert_value == pytest.approx(42.5)
    assert perturbed.reliability_value == pytest.approx(0.011)


def test_the_cap_outside_the_unit_interval_is_refused() -> None:
    """``N4a``'s guard: a cap above 1 (or below 0) is a config error, not a
    runtime one.

    The validator is what turns the defect into a load-time failure. Without a
    test that drives it, ``if False:`` replaces it unnoticed and the error
    surfaces at the first call instead.
    """
    for bad in (1.2, -0.1):
        with pytest.raises(ValidationError, match="confidence must lie inside"):
            _settings_with(
                reliability_cap=CalibratedValue(
                    value=bad, calibration_status="uncalibrated_illustrative", note="bad cap"
                )
            )


def test_a_non_positive_burn_alert_is_refused() -> None:
    """``N4b``'s guard: a zero alert would fire unconditionally, a negative one
    never.

    Both are dead vocabulary (D-037's class), so the validator refuses them at
    load rather than shipping a threshold that cannot mean what it says.
    """
    for bad in (0.0, -1.0):
        with pytest.raises(ValidationError, match="burn_alert_pct"):
            _settings_with(
                burn_alert_pct=CalibratedValue(
                    value=bad, calibration_status="uncalibrated_illustrative", note="bad alert"
                )
            )
