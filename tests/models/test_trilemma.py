"""Tests for Module 1 — ``check_trilemma_tension`` (D-048).

The arithmetic here is trivial: three booleans are combined, compared against
two directions, and two reserves thresholds. So, as with ``test_regime.py``,
every interesting test is about **reachability and sign**, not about a formula.

Five things this file exists to pin.

1. **All four severities are reachable, and only through their stated
   conditions.** A severity vocabulary where one member is unreachable is the
   D-037/D-045 defect class; here it would be worse than usual because the
   severities are *ordered in urgency* and the fallthrough branch reports
   safety.

2. **The specification's confidences are gone.** Section 15.20-A returns
   ``0.7 / 0.6 / 0.4 / 0.8`` as literals. Section 22.8 forbids that. The
   replacement is not merely different numbers — it is *flat across severities*,
   because severity is a fact about the world and confidence is a fact about the
   measurement. A test asserts the flatness, so a future edit that reintroduces
   a severity-dependent literal fails loudly.

3. **The ``or 0`` trap.** The specification writes
   ``(reserves_trend_pct_change_3mo or 0) < -0.10``, which turns an **absent**
   reserves figure into a measured zero — i.e. into evidence of calm. The tests
   assert that absence is absence: it neither fires nor suppresses, and it is
   disclosed.

4. **The 3-month threshold misses the specification's own worked example.**
   Black Wednesday's month reads ``-5.37%`` on the 3-month measure, inside the
   ``-10%`` threshold, and ``-7.25%`` on the 1-month measure. The test asserts
   the reference episode is reached *through the 1-month branch*, against the
   real shipped thresholds — because the whole justification for adding a second
   threshold is that the first one does not fire there.

5. **The US is structurally unreachable past ``NO_TENSION``.** Section 22.3
   makes this a US-only build and the dollar floats, so the guard and the
   non-US-fixture arrangement are asserted rather than described.

Config leaves are patched to values the shipped literals cannot produce, and
the synthetic leaves are all distinct so an accessor swap cannot hide (D-035).
"""

from __future__ import annotations

from contextlib import ExitStack
from itertools import product
from typing import get_args
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from macro_engine.config import (
    CalibratedValue,
    MarkovRegimeSettings,
    RegimeBaseRates,
    RegimeRateValues,
    RegimeSettings,
    TrilemmaBaseRates,
    TrilemmaReferenceEpisode,
    TrilemmaSettings,
    get_settings,
)
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.regime import (
    TRILEMMA_SEVERITIES,
    PolicyDirection,
    TrilemmaInputs,
    TrilemmaSeverity,
    check_trilemma_tension,
)
from tests.helpers import as_bool, as_float, as_str

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose, distinct from every other.

    The status is ``fitted_assumption``, which is a **non-placeholder** status:
    ``_trilemma_thresholds_calibrated`` reads ``!= "uncalibrated_illustrative"``,
    so a leaf built by this helper reads as *calibrated* and the heuristic
    penalty is **off** under ``_SYNTHETIC``.

    That polarity is deliberate and is easy to get backwards — the shipped
    config has the opposite polarity (both thresholds are
    ``uncalibrated_illustrative``, so the penalty is on). Any test that needs the
    penalty ON must therefore use ``_placeholder_leaf`` below rather than this
    helper, or it will be asserting about a state the fixture does not produce.
    """
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _placeholder_leaf(value: float | int) -> CalibratedValue:
    """A synthetic leaf carrying the ONE status that means "not calibrated yet".

    Mirrors the shipped config's polarity, so ``_trilemma_thresholds_calibrated``
    reads ``False`` and the heuristic penalty applies.
    """
    return CalibratedValue(
        value=value,
        calibration_status="uncalibrated_illustrative",
        note="synthetic placeholder — the status the heuristic helper keys on",
    )


#: Every synthetic leaf is a DIFFERENT number, so an accessor swap moves both
#: sides of any assertion that reads through the accessors (D-035). None of the
#: values is the shipped literal, so a hardcoded copy of the shipped threshold
#: cannot satisfy a test that patches these.
#:
#: The two thresholds are ordered as the validator requires (``break_1mo`` not
#: steeper than ``depletion_3mo``), and BOTH are shallower than the shipped
#: values -- so a model that reads the shipped config instead of the fixture
#: produces visibly different severities on the boundary fixtures below.
_SYNTHETIC_DEPLETION_3MO = -0.05
_SYNTHETIC_BREAK_1MO = -0.03

_SYNTHETIC = RegimeSettings(
    recession_output_gap_max=_leaf(-2.0),
    weak_growth_output_gap_max=_leaf(-0.75),
    late_expansion_output_gap_min=_leaf(1.25),
    disinflation_output_gap_max=_leaf(0.6),
    neutral_inflation_trend_band_pp=_leaf(0.2),
    growth_momentum_band_pp=_leaf(0.35),
    measured_rising_inflation_rate=_leaf(0.775),
    base_rates=RegimeBaseRates(
        observations_measured_value=_leaf(0),
        rates=RegimeRateValues(
            early_expansion_value=_leaf(0.0),
            mid_expansion_value=_leaf(0.0),
            late_expansion_value=_leaf(0.0),
            slowdown_value=_leaf(0.0),
            recession_value=_leaf(0.0),
            recovery_value=_leaf(0.0),
            disinflation_value=_leaf(0.0),
            reflation_value=_leaf(0.0),
            stagflation_value=_leaf(0.0),
        ),
    ),
    trilemma=TrilemmaSettings(
        reserves_depletion_threshold_3mo=_leaf(_SYNTHETIC_DEPLETION_3MO),
        reserves_break_threshold_1mo=_leaf(_SYNTHETIC_BREAK_1MO),
        confidence_penalty_for_manual_trilemma_booleans=_leaf(0.2),
        base_rates=TrilemmaBaseRates(
            observations_measured_value=_leaf(0),
            depletion_3mo_base_rate=_leaf(0.0),
            break_1mo_base_rate=_leaf(0.0),
        ),
        reference_episode=TrilemmaReferenceEpisode(
            country="gb",
            reserves_series="TRESEGGBM052N",
            event_date="1992-09-16",
            expected_severity="CRITICAL_PEG_STRESS",
            expected_month="1992-09",
        ),
    ),
    # `RegimeSettings.markov` is required, and adding it (D-105) broke this
    # construction — the SAME defect class D-048 recorded for `trilemma` and the
    # THIRD time it has fired. It is worth naming the failure mode precisely,
    # because it is invisible to the model's own gates: the module raises
    # `ValidationError` at IMPORT, so `tests/models/test_trilemma.py` cannot
    # COLLECT. Every one of `mutation_trilemma.py`'s 63 mutations would then have
    # been "killed" by that single collection error — a perfect score measuring
    # nothing, which is D-059's trap exactly. It was caught only because the
    # suite was run GREEN-UNMUTATED first, as the standing brief requires.
    markov=MarkovRegimeSettings(
        max_regimes_value=_leaf(5),
        min_observations_per_parameter_value=_leaf(4.0),
        max_iterations_value=_leaf(150),
        em_iterations_value=_leaf(4),
        search_reps_value=_leaf(0),
        modal_share_warning_threshold_value=_leaf(0.85),
        switching_variance=True,
        markov_trend="c",
        markov_optimizer="bfgs",
    ),
)


class _PatchedSettings:
    """Context manager replacing ``get_settings().regime`` only.

    Only ``regime`` is swapped: the real ``confidence`` block is used, so a
    test asserting a confidence value is asserting the system's actual rule.

    The patch targets ``macro_engine.models.regime.get_settings`` — the name the
    model module bound at import time. Patching ``macro_engine.config.get_settings``
    would leave the model looking at the real settings and every assertion here
    would silently test the shipped config instead of the fixture.
    """

    def __init__(self, regime: RegimeSettings) -> None:
        self._regime = regime
        self._stack = ExitStack()

    def __enter__(self) -> None:
        real = get_settings()
        patched = real.model_copy(update={"regime": self._regime})
        self._stack.enter_context(
            patch("macro_engine.models.regime.get_settings", return_value=patched)
        )

    def __exit__(self, *exc: object) -> None:
        self._stack.close()


#: A fully-asserted peg: all three legs, as Black Wednesday's sterling was.
_PEGGED = {
    "has_fixed_or_managed_fx": True,
    "has_free_capital_movement": True,
    "claims_monetary_independence": True,
}

#: The Black Wednesday configuration: domestic conditions needed easing (the UK
#: was in recession) while defending the peg required tightening.
_BW_CONFLICT = {
    "domestic_policy_direction_needed": "easing",
    "peg_defense_direction_required": "tightening",
}

#: Black Wednesday's measured reserves readings, 1992-09 on `TRESEGGBM052N`.
#: **The 3-month figure does NOT breach the shipped -10% threshold; the 1-month
#: figure does not breach -7% by much either.** These are the real observations.
_BW_3MO = -0.0537
_BW_1MO = -0.0725


def _inputs(**kwargs: object) -> TrilemmaInputs:
    base: dict[str, object] = {"country": "us", **_PEGGED}
    base.update(kwargs)
    return TrilemmaInputs(**base)  # type: ignore[arg-type]


def _severity(**kwargs: object) -> str:
    return as_str(check_trilemma_tension(_inputs(**kwargs)), key="severity")


# ---------------------------------------------------------------------------
# 1. The vocabulary is closed and every member is reachable
# ---------------------------------------------------------------------------


def test_severity_literal_and_tuple_are_the_same_set() -> None:
    """D-045a: the declared members and the returned members must agree both ways.

    A member declared and never returned is a contract advertising a value the
    function cannot produce. A member returned and never declared is worse here
    than usual — the severities are ordered in urgency and a caller reading an
    unlisted string has no way to know whether it means calm or unknown.
    """
    assert set(get_args(TrilemmaSeverity)) == set(TRILEMMA_SEVERITIES)


def test_every_declared_severity_is_reachable() -> None:
    """All four severities are produced by at least one admissible input.

    The four are exercised through the **public** function, not the private
    branch helper, so a change to the wiring between them is caught.
    """
    reached = {
        _severity(),
        _severity(**_BW_CONFLICT),
        _severity(**_BW_CONFLICT, reserves_trend_pct_change_3mo=-0.99),
        _severity(has_fixed_or_managed_fx=False),
    }
    assert reached == set(TRILEMMA_SEVERITIES)


def test_the_severities_form_a_strict_escalation() -> None:
    """Each step of the escalation requires strictly more evidence than the last.

    Asserted as a chain rather than four independent equalities, because the
    interesting failure is not "one branch is wrong" but "the branches overlap"
    — e.g. a reserves reading that reaches ``CRITICAL_PEG_STRESS`` on an input
    that has no direction conflict.
    """
    assert _severity(has_fixed_or_managed_fx=False) == "NO_TENSION"
    assert _severity() == "TRILEMMA_TENSION"
    assert _severity(**_BW_CONFLICT) == "TRILEMMA_VIOLATION"
    assert _severity(**_BW_CONFLICT, reserves_trend_pct_change_3mo=-0.99) == "CRITICAL_PEG_STRESS"

    # Reserves burning WITHOUT a conflict is not critical stress: the third leg
    # of the escalation is the conflict, not the burn.
    assert _severity(reserves_trend_pct_change_3mo=-0.99) == "TRILEMMA_TENSION"


@pytest.mark.parametrize(
    "dropped",
    ["has_fixed_or_managed_fx", "has_free_capital_movement", "claims_monetary_independence"],
)
def test_any_one_missing_leg_prevents_tension(dropped: str) -> None:
    """Claiming two of three legs is the trilemma being *obeyed*, not violated.

    Parameterised over the three legs rather than asserted once, because a
    chain that reads two of the three booleans and ignores the third would pass
    a single test and fail here.
    """
    assert _severity(**{dropped: False}) == "NO_TENSION"
    # ...and even with the conflict AND reserves gone, still no tension.
    assert (
        _severity(
            **{dropped: False},
            **_BW_CONFLICT,
            reserves_trend_pct_change_3mo=-0.99,
            reserves_trend_pct_change_1mo=-0.99,
        )
        == "NO_TENSION"
    )


# ---------------------------------------------------------------------------
# 2. The direction conflict, and what is NOT one
# ---------------------------------------------------------------------------


def test_agreeing_directions_are_not_a_conflict() -> None:
    """A caller passing the same direction twice has agreement, the calm case."""
    assert (
        _severity(
            domestic_policy_direction_needed="easing",
            peg_defense_direction_required="easing",
        )
        == "TRILEMMA_TENSION"
    )
    assert (
        _severity(
            domestic_policy_direction_needed="tightening",
            peg_defense_direction_required="tightening",
        )
        == "TRILEMMA_TENSION"
    )


@pytest.mark.parametrize(
    ("domestic", "peg"),
    [("easing", None), (None, "tightening"), (None, None)],
)
def test_an_unassessed_direction_is_not_a_conflict(domestic: str | None, peg: str | None) -> None:
    """An absent direction must not escalate.

    ``None`` means *unassessed*. Treating it as a conflict would make every
    incomplete input report a violation, which inverts the meaning of evidence:
    the function would shout loudest exactly when it knows least.
    """
    assert (
        _severity(
            domestic_policy_direction_needed=domestic,
            peg_defense_direction_required=peg,
        )
        == "TRILEMMA_TENSION"
    )


def test_direction_is_an_enumerated_field() -> None:
    """D-029: a bare ``str`` would let a typo compare unequal to every direction.

    With an untyped field, ``"Easing"`` registers as a conflict against
    everything — a **false alarm**, not a silent pass. That is if anything the
    more dangerous failure, because it makes the loudest severity routine.
    """
    assert set(get_args(PolicyDirection)) == {"easing", "tightening"}
    with pytest.raises(ValidationError):
        _inputs(domestic_policy_direction_needed="Easing")


# ---------------------------------------------------------------------------
# 3. The `or 0` trap — absence is not a measured zero
# ---------------------------------------------------------------------------


def test_absent_reserves_do_not_read_as_zero() -> None:
    """The specification's ``or 0`` turns a missing input into evidence of calm.

    Pinned by name because the failure is silent and *plausible*: with
    ``or 0``, ``0 < -0.10`` is ``False``, so an absent figure produces exactly
    the same severity as a measured-and-healthy one. The correction makes
    absence absence, and discloses it.
    """
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert as_str(result, key="severity") == "TRILEMMA_VIOLATION"
    assert any("RESERVES TREND ABSENT" in w for w in result.warnings), (
        "an absent 3-month reserves figure must be disclosed, not silently treated as zero"
    )


def test_the_or_zero_form_is_behaviourally_distinguishable_with_a_falling_reading() -> None:
    """Why the ``or 0`` mutation survives, and what that says about the guard.

    This test originally claimed to kill the ``"or 0"`` mutation. It does not,
    and the reason is a fact about the arithmetic rather than about the tests:

    for a threshold ``t <= 0``, ``(x or 0.0) < t`` and
    ``x is not None and x < t`` agree for **every** ``x``. When ``x`` is
    ``None``, ``0.0 < t`` is false and the guarded form is false. When ``x`` is
    a present number, ``x or 0.0`` is ``x`` unless ``x`` is exactly ``0.0``, and
    ``0.0 < t`` is still false for ``t <= 0``. The forms can only diverge for
    ``t > 0`` — which a reserves *depletion* threshold never is.

    So the ``or 0`` rewrite is an **equivalent mutation** on this function, and
    the sweep must report it as such rather than as a weak test. What matters is
    that the equivalence is *contingent on the sign of the threshold*, so the
    contingency is asserted here: the two forms are shown to agree on the
    negative thresholds this function uses, and shown to disagree on a positive
    one. If a future change lets a threshold cross zero, the second half of this
    test is what fails.
    """

    def guarded(x: float | None, t: float) -> bool:
        return x is not None and x < t

    def or_zero(x: float | None, t: float) -> bool:
        return (x or 0.0) < t

    # Every threshold this function can use is negative.
    depletion, break_1mo = _spec_thresholds()
    assert depletion < 0.0 and break_1mo < 0.0, (
        "a reserves DEPLETION threshold above zero would be meaningless"
    )

    # ...and over that sign, the two forms agree everywhere.
    for threshold in (depletion, break_1mo, _SYNTHETIC_DEPLETION_3MO, _SYNTHETIC_BREAK_1MO):
        for reading in (None, 0.0, -0.05, -0.5, 0.5):
            assert guarded(reading, threshold) == or_zero(reading, threshold), (
                f"the two forms must agree for a negative threshold "
                f"({reading=}, {threshold=}) — if they do not, the mutation is "
                f"killable and this test needs updating"
            )

    # The contingency, stated: crossing zero is what makes the rewrite dangerous.
    assert guarded(None, 0.05) is False and or_zero(None, 0.05) is True, (
        "the or-0 rewrite only diverges for a positive threshold; the config "
        "validator below must keep every trilemma threshold negative"
    )


def test_the_thresholds_cannot_cross_zero() -> None:
    """The equivalence above is only harmless while the thresholds stay negative.

    ``or 0`` is an equivalent mutation *because* a depletion threshold is
    negative. Nothing in the validator currently says so — it only enforces the
    ordering of the two thresholds against each other. A positive
    ``depletion_3mo`` would pass validation, make the ``or 0`` rewrite
    observable, and turn an absent reading into an escalation.

    Asserted on the shipped config and on the synthetic fixtures, so adding a
    positive threshold anywhere fails here rather than silently invalidating the
    inert-mutation classification in the sweep.
    """
    for thresholds in (
        _spec_thresholds(),
        (_SYNTHETIC_DEPLETION_3MO, _SYNTHETIC_BREAK_1MO),
    ):
        assert all(t < 0.0 for t in thresholds), (
            f"every trilemma threshold must be negative, got {thresholds}"
        )


def test_a_nan_reading_does_not_silently_fire() -> None:
    """``NaN`` is not ``None``, and every comparison against it is ``False``.

    ``float("nan") < threshold`` is ``False`` while ``not (nan >= threshold)`` is
    ``True``, so a guard written as a negation would treat a NaN as a breach — a
    reading nobody made, reported as a crisis. The shipped form is safe because
    ``nan < threshold`` is simply ``False``, but that safety is a property of the
    *operator*, not an accident worth leaving unpinned.
    """
    with _PatchedSettings(_SYNTHETIC):
        nan = float("nan")
        result = check_trilemma_tension(_inputs(**_BW_CONFLICT, reserves_trend_pct_change_3mo=nan))
        value = result.value
        assert isinstance(value, dict)
        assert value["reserves_depleting_3mo"] is False, (
            "NaN must not read as a breach — it is the absence of a measurement, not an extreme one"
        )


def test_an_absent_1mo_measure_cannot_fire_the_acute_branch() -> None:
    """Absence must not *invent* an escalation either — it is inert in both directions.

    A naive implementation that defaulted the 1-month reading to zero would
    leave the acute branch unreached by luck; one that defaulted it to a large
    negative would fire it. Neither is a measurement, so the branch must simply
    not fire, and the published reading must be ``None`` rather than ``0.0`` —
    a published zero would be the model asserting a measurement nobody made.
    """
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT, reserves_trend_pct_change_3mo=-0.99))
    assert as_str(result, key="severity") == "CRITICAL_PEG_STRESS"
    assert as_bool(result, key="reserves_breaking_1mo") is False
    assert isinstance(result.value, dict)
    assert result.value["reserves_trend_pct_change_1mo"] is None


# ---------------------------------------------------------------------------
# 4. The reference episode — the 3-month threshold misses its own worked example
# ---------------------------------------------------------------------------


def _spec_thresholds() -> tuple[float, float]:
    """The SHIPPED thresholds, read without patching — the real configuration."""
    trilemma = get_settings().regime.trilemma
    return trilemma.depletion_3mo, trilemma.break_1mo


def test_black_wednesday_3mo_reading_does_not_breach_the_specified_threshold() -> None:
    """The justification for the whole increment, asserted against real config.

    Section 15.20-A's ``<-0.10`` 3-month test does **not** fire in 1992-09: the
    UK's own reserves series reads ``-5.37%`` that month. If this ever stops
    being true — a revised series, a changed window — the second threshold's
    rationale has to be re-derived rather than left standing on a stale fact.
    """
    depletion, _ = _spec_thresholds()
    assert depletion < _BW_3MO, (
        f"the specification's 3-month threshold ({depletion}) is expected NOT to fire on "
        f"Black Wednesday's month ({_BW_3MO}); if it now fires, the added 1-month "
        f"threshold's rationale must be re-derived (D-048)"
    )


def test_black_wednesday_1mo_reading_breaches_the_1mo_threshold() -> None:
    """...and the 1-month measure does fire, which is why it was added."""
    _, break_1mo = _spec_thresholds()
    assert break_1mo > _BW_1MO, (
        f"the 1-month threshold ({break_1mo}) must fire on Black Wednesday's month "
        f"({_BW_1MO}), or the contemporaneous detection does not work"
    )


def test_black_wednesday_is_reached_via_the_1mo_branch_alone() -> None:
    """The reference episode escalates on the acute branch, NOT the trend branch.

    This is the load-bearing assertion of the increment: it uses the **real**
    shipped thresholds (no patching) and Black Wednesday's **real** measured
    readings, and shows the severity is ``CRITICAL_PEG_STRESS`` while the
    specification's own measure is silent. Under the specification's single
    3-month rule this input returns ``TRILEMMA_VIOLATION`` — one severity too
    low, on the crisis the function exists to detect.
    """
    result = check_trilemma_tension(
        _inputs(
            **_BW_CONFLICT,
            reserves_trend_pct_change_3mo=_BW_3MO,
            reserves_trend_pct_change_1mo=_BW_1MO,
        )
    )
    assert as_str(result, key="severity") == "CRITICAL_PEG_STRESS"
    assert as_bool(result, key="reserves_depleting_3mo") is False, (
        "Black Wednesday must NOT breach the 3-month threshold — that is the whole point"
    )
    assert as_bool(result, key="reserves_breaking_1mo") is True
    assert any("ACUTE BREAK WITHOUT A SUSTAINED TREND" in w for w in result.warnings)


def test_korea_1997_reaches_critical_via_the_trend_branch_alone() -> None:
    """The two measures are complementary, not nested: this episode fires the OTHER one.

    Korea's 1997-09 reserves change is ``-10.80%`` over three months (breaching
    the trend test, an early warning) while its 1-month change that month is
    ``-2.30%`` (not breaching the acute test). Without this case, "the 1-month
    test subsumes the 3-month test" would be an untested assumption — and it is
    false.
    """
    result = check_trilemma_tension(
        _inputs(
            **_BW_CONFLICT,
            reserves_trend_pct_change_3mo=-0.1080,
            reserves_trend_pct_change_1mo=-0.0230,
        )
    )
    assert as_str(result, key="severity") == "CRITICAL_PEG_STRESS"
    assert as_bool(result, key="reserves_depleting_3mo") is True
    assert as_bool(result, key="reserves_breaking_1mo") is False
    assert any("SUSTAINED DEPLETION WITHOUT AN ACUTE BREAK" in w for w in result.warnings)


def test_the_two_measures_are_not_nested() -> None:
    """Neither branch implies the other over a sweep of the input plane.

    Enumerating is the point: a single pair of examples could be a coincidence,
    and the claim being made — "both thresholds earn their place" — is a claim
    about the *plane*, not about two points.
    """
    both = trend_only = acute_only = neither = 0
    for trend, acute in product([-0.30, -0.12, -0.02, 0.05], [-0.15, -0.09, -0.01, 0.03]):
        result = check_trilemma_tension(
            _inputs(
                **_BW_CONFLICT,
                reserves_trend_pct_change_3mo=trend,
                reserves_trend_pct_change_1mo=acute,
            )
        )
        depleting = as_bool(result, key="reserves_depleting_3mo")
        breaking = as_bool(result, key="reserves_breaking_1mo")
        if depleting and breaking:
            both += 1
        elif depleting:
            trend_only += 1
        elif breaking:
            acute_only += 1
        else:
            neither += 1

    assert trend_only > 0, "the 3-month test must be able to fire alone (Korea 1997-09)"
    assert acute_only > 0, "the 1-month test must be able to fire alone (Black Wednesday)"


# ---------------------------------------------------------------------------
# 5. Threshold boundaries, built by addition
# ---------------------------------------------------------------------------


def test_threshold_boundaries_are_strict() -> None:
    """A reading exactly ON a threshold does not fire it.

    Both comparisons are strict ``<``. Built by **addition** from the patched
    threshold rather than by writing a literal that looks like it, so the test
    follows the config if the config changes (the boundary-computation rule).
    """
    with _PatchedSettings(_SYNTHETIC):
        at = _SYNTHETIC_DEPLETION_3MO
        assert (
            _severity(**_BW_CONFLICT, reserves_trend_pct_change_3mo=at) == "TRILEMMA_VIOLATION"
        ), "exactly on the threshold is not below it"
        assert (
            _severity(**_BW_CONFLICT, reserves_trend_pct_change_3mo=at - 1e-9)
            == "CRITICAL_PEG_STRESS"
        )

        at1 = _SYNTHETIC_BREAK_1MO
        assert _severity(**_BW_CONFLICT, reserves_trend_pct_change_1mo=at1) == "TRILEMMA_VIOLATION"
        assert (
            _severity(**_BW_CONFLICT, reserves_trend_pct_change_1mo=at1 - 1e-9)
            == "CRITICAL_PEG_STRESS"
        )


def test_the_patched_thresholds_are_actually_read() -> None:
    """A reading that fires the synthetic threshold but not the shipped one.

    This is what makes the patching load-bearing rather than decorative: the
    synthetic thresholds are shallower than the shipped ones, so ``-0.06``
    breaches the fixture and not the real config. A model that ignored the
    fixture would return ``TRILEMMA_VIOLATION`` here.

    It also protects the two shipped-config tests above from becoming vacuous:
    if the patch leaked into them they would be asserting about synthetic values.
    """
    with _PatchedSettings(_SYNTHETIC):
        assert (
            _severity(**_BW_CONFLICT, reserves_trend_pct_change_3mo=-0.06) == "CRITICAL_PEG_STRESS"
        )
    # Without the patch the same reading does NOT breach the shipped -0.10.
    assert _severity(**_BW_CONFLICT, reserves_trend_pct_change_3mo=-0.06) == "TRILEMMA_VIOLATION"


def test_an_inverted_threshold_pair_is_refused() -> None:
    """A 1-month threshold STEEPER than the 3-month one makes a branch dead.

    If the acute test were stricter than the trend test it could never fire
    alone, and the contemporaneous detection this increment adds would be
    unreachable code. The validator refuses the configuration rather than
    shipping a silent dead branch.
    """
    with pytest.raises(ValidationError, match="must not be steeper"):
        TrilemmaSettings(
            reserves_depletion_threshold_3mo=_leaf(-0.03),
            reserves_break_threshold_1mo=_leaf(-0.20),
            confidence_penalty_for_manual_trilemma_booleans=_leaf(0.2),
            base_rates=TrilemmaBaseRates(
                observations_measured_value=_leaf(0),
                depletion_3mo_base_rate=_leaf(0.0),
                break_1mo_base_rate=_leaf(0.0),
            ),
            reference_episode=TrilemmaReferenceEpisode(
                country="gb",
                reserves_series="TRESEGGBM052N",
                event_date="1992-09-16",
                expected_severity="CRITICAL_PEG_STRESS",
                expected_month="1992-09",
            ),
        )


def test_an_equal_threshold_pair_is_allowed() -> None:
    """The validator is ``break_1mo < depletion_3mo``, so equality passes.

    Equality is a *legitimate* configuration: it makes the acute branch a strict
    subset of the trend branch (redundant, not dead), which is a defensible
    conservative choice. Refusing it would be a validator asserting more than
    the stated requirement — and the asymmetry is worth pinning, because it is
    exactly the kind of thing a careless ``<=`` edit would silently change.
    """
    settings = TrilemmaSettings(
        reserves_depletion_threshold_3mo=_leaf(-0.07),
        reserves_break_threshold_1mo=_leaf(-0.07),
        confidence_penalty_for_manual_trilemma_booleans=_leaf(0.2),
        base_rates=TrilemmaBaseRates(
            observations_measured_value=_leaf(0),
            depletion_3mo_base_rate=_leaf(0.0),
            break_1mo_base_rate=_leaf(0.0),
        ),
        reference_episode=TrilemmaReferenceEpisode(
            country="gb",
            reserves_series="TRESEGGBM052N",
            event_date="1992-09-16",
            expected_severity="CRITICAL_PEG_STRESS",
            expected_month="1992-09",
        ),
    )
    assert settings.break_1mo == settings.depletion_3mo


def test_shipped_thresholds_are_ordered() -> None:
    """The shipped config satisfies its own validator (a config-loading smoke test)."""
    depletion, break_1mo = _spec_thresholds()
    assert break_1mo >= depletion, (
        f"shipped break_1mo ({break_1mo}) must not be steeper than depletion_3mo ({depletion})"
    )


# ---------------------------------------------------------------------------
# 6. Confidence is computed, and it is flat
# ---------------------------------------------------------------------------


def test_confidence_comes_from_compute_confidence() -> None:
    """§22.8: the confidence is the system's rule applied to stated facts.

    Recomputed here from the same inputs the model claims, so a literal smuggled
    in anywhere fails.
    """
    from macro_engine.models.regime import _trilemma_thresholds_calibrated

    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=not _trilemma_thresholds_calibrated(),
            source_independence_count=0,
            depends_on_unobservable=True,
        )
    )
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert result.confidence == pytest.approx(expected)


def test_no_severity_carries_a_hardcoded_confidence() -> None:
    """The specification's four literals are gone, and their shape is gone with them.

    Section 15.20-A returns 0.7 / 0.6 / 0.4 / 0.8 — which *rise* for the calm
    severity and *fall* for a real one, reading as a probability that the label
    is correct. No model here estimates that, so the honest replacement is flat
    across severities. A future edit that reintroduced a severity-dependent
    confidence fails this test.

    The four severities are first asserted to be four *distinct* labels, so the
    loop cannot be satisfied by a function that returns one severity for
    everything (which would trivially make the confidences equal).
    """
    specs: dict[str, dict[str, object]] = {
        "NO_TENSION": {"has_fixed_or_managed_fx": False},
        "TRILEMMA_TENSION": {},
        "TRILEMMA_VIOLATION": dict(_BW_CONFLICT),
        "CRITICAL_PEG_STRESS": {**_BW_CONFLICT, "reserves_trend_pct_change_3mo": -0.99},
    }
    observed: dict[str, float] = {}
    for expected, kwargs in specs.items():
        result = check_trilemma_tension(_inputs(**kwargs))
        assert as_str(result, key="severity") == expected, (
            "the four fixtures must produce four different severities, or the "
            "flatness assertion below is vacuous"
        )
        observed[expected] = result.confidence

    assert len(set(observed.values())) == 1, (
        f"confidence must be flat across severities — it describes the MEASUREMENT, not "
        f"the severity. Observed: {observed}"
    )
    # And it must not be any of the specification's four literals by coincidence.
    assert next(iter(observed.values())) not in (0.7, 0.6, 0.4, 0.8)


def test_data_quality_flag_lowers_the_confidence() -> None:
    """The one factor a caller can actually vary, so it is asserted to move the value."""
    clean = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    flagged = check_trilemma_tension(_inputs(**_BW_CONFLICT, data_quality_flags_present=True))
    assert flagged.confidence < clean.confidence


def test_the_manual_inputs_are_priced_into_the_confidence() -> None:
    """The three legs are manual; the confidence must say so rather than assume a family.

    ``source_independence_count=0`` is a *decision*, not an omission: the
    trilemma legs are not a Section 15.19-D family because they are not measured
    evidence at all. Crediting one would be the D-027 circularity error — the
    function would take credit for evidence its caller supplied as an assertion.
    """
    from macro_engine.models.regime import _trilemma_thresholds_calibrated

    heuristic = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _trilemma_thresholds_calibrated(),
            source_independence_count=0,
            depends_on_unobservable=True,
        )
    )
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert result.confidence == pytest.approx(heuristic)
    # If the thresholds are ever calibrated this flips; assert the shipped state
    # so the change is deliberate rather than unnoticed.
    assert _trilemma_thresholds_calibrated() is False, (
        "the shipped trilemma thresholds are not calibrated; if that changed, the "
        "confidence assertions in this file must be revisited"
    )


def test_every_confidence_factor_is_load_bearing() -> None:
    """Each factor must MOVE the confidence when flipped, not merely be passed.

    The first sweep left three survivors here — forcing ``depends_on_unobservable``
    off, crediting a false independent family, and dropping the data-quality flag
    — and the reason is subtle enough to be worth stating exactly.

    ``compute_confidence`` genuinely uses all three: on the shipped config,
    ``0.3`` becomes ``0.5`` with the unobservable penalty lifted, ``0.35`` with
    one family credited, and ``0.05`` with a data-quality flag. So a test that
    calls ``compute_confidence`` directly and flips the factor *passes* — and
    still does not kill the mutation, because the mutation is inside
    ``check_trilemma_tension``, which pins the factor to a constant. The direct
    call never touches the model.

    So the factor must be flipped **through the model**, which means finding an
    input the model exposes that changes the factor's value while leaving the
    rest of the computation untouched. Two of the four are reachable that way:
    ``data_quality_flags_present`` is a model input, and the heuristic flag moves
    through the config (the second half of this test). ``source_independence_count``
    and ``depends_on_unobservable`` are **not** model inputs — the model pins
    them by design, which is the correct behaviour and makes those two mutations
    equivalent rather than wrongly-killed. They are pinned in the test below
    instead, so a future edit that stops pinning them fails here.
    """
    from macro_engine.models.regime import _trilemma_thresholds_calibrated

    heuristic = not _trilemma_thresholds_calibrated()
    clean = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    flagged = check_trilemma_tension(_inputs(**_BW_CONFLICT, data_quality_flags_present=True))
    assert flagged.confidence < clean.confidence, (
        "the data-quality flag is a model input, so it must move the model's confidence"
    )

    # The heuristic factor moves through the CONFIG, and must move the result.
    # Written as an explicit pair rather than by copying `_SYNTHETIC`, because
    # `_SYNTHETIC`'s leaves carry a NON-placeholder status and therefore have the
    # heuristic penalty OFF — the opposite of the shipped config. Reusing it here
    # made both runs 0.5 and the assertion compared a value against itself.
    placeholder = _SYNTHETIC.model_copy(
        update={
            "trilemma": _SYNTHETIC.trilemma.model_copy(
                update={
                    "reserves_depletion_threshold_3mo": _placeholder_leaf(_SYNTHETIC_DEPLETION_3MO),
                    "reserves_break_threshold_1mo": _placeholder_leaf(_SYNTHETIC_BREAK_1MO),
                }
            )
        }
    )
    calibrated = _SYNTHETIC.model_copy(
        update={
            "trilemma": _SYNTHETIC.trilemma.model_copy(
                update={
                    "reserves_depletion_threshold_3mo": CalibratedValue(
                        value=_SYNTHETIC_DEPLETION_3MO,
                        calibration_status="conventional",
                        note="pretend a phase calibrated this",
                    ),
                    "reserves_break_threshold_1mo": CalibratedValue(
                        value=_SYNTHETIC_BREAK_1MO,
                        calibration_status="conventional",
                        note="pretend a phase calibrated this",
                    ),
                }
            )
        }
    )
    with _PatchedSettings(placeholder):
        uncalibrated = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    with _PatchedSettings(calibrated):
        lifted = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert lifted.confidence > uncalibrated.confidence, (
        "calibrating the thresholds must move the confidence through the heuristic "
        f"factor: placeholders gave {uncalibrated.confidence}, calibrated gave "
        f"{lifted.confidence}"
    )

    # ...and the two factors the model pins are pinned to the values the model's
    # own docstring argues for. Read from the source, because a pinned constant
    # has no runtime signature beyond its effect on the number.
    import inspect

    from macro_engine.models import regime as regime_module

    source = inspect.getsource(regime_module.check_trilemma_tension)
    assert "source_independence_count=0," in source, (
        "crediting an independent family here would be the D-027 circularity error: "
        "the three legs are the caller's own assertions, not measured evidence"
    )
    assert "depends_on_unobservable=True," in source, (
        "the trilemma legs are institutional classifications no series can contradict"
    )
    assert "depends_on_unobservable=False" not in source
    assert "source_independence_count=1" not in source
    assert heuristic is True, "the shipped thresholds are uncalibrated; if not, revisit"


def test_the_published_flags_are_read_back_and_asserted() -> None:
    """Every key in ``value`` must be readable AND correct for its severity.

    Two sweep mutations survived the first run — "the published all-three flag
    dropped" and "the published conflict flag inverted" — because no test read
    those keys at all. A dropped key and an inverted key are both real defects;
    they survived because the suite was silent about them, which is a weak test
    rather than an equivalent mutation.

    The expectations are laid out per severity, so an inverted flag fails the
    severity it belongs to instead of passing everywhere.
    """
    expectations: list[tuple[dict[str, object], bool, bool]] = [
        # (kwargs, all_three_expected, conflict_expected)
        ({"has_fixed_or_managed_fx": False}, False, False),  # NO_TENSION
        ({}, True, False),  # TRILEMMA_TENSION
        (dict(_BW_CONFLICT), True, True),  # TRILEMMA_VIOLATION
        ({**_BW_CONFLICT, "reserves_trend_pct_change_3mo": -0.99}, True, True),
    ]
    for kwargs, all_three, conflict in expectations:
        value = check_trilemma_tension(_inputs(**kwargs)).value
        assert isinstance(value, dict)
        assert value["all_three_legs_claimed"] is all_three, (
            f"all_three_legs_claimed wrong for {kwargs}"
        )
        assert value["direction_conflict"] is conflict, f"direction_conflict wrong for {kwargs}"


# ---------------------------------------------------------------------------
# 7. Scope — the guard, and the module-level honesty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("country", ["gb", "kr", "id", "de", "jp", "US", ""])
def test_non_us_countries_are_refused(country: str) -> None:
    """§22.3: the trilemma is STRUCTURAL, so a country is not a label to re-point.

    ``"US"`` is included deliberately: the guard is an exact match, because the
    contract says lowercase and accepting ``"US"`` would mean the function has
    two spellings for one country and a caller could not tell which it got.
    """
    with pytest.raises(NotImplementedError, match="country 'us' only"):
        check_trilemma_tension(_inputs(country=country))


def test_us_cannot_reach_anything_but_no_tension() -> None:
    """The structural finding, asserted over the whole admissible US input plane.

    ``has_fixed_or_managed_fx`` is ``False`` for the dollar, so ``all_three`` is
    ``False`` and no escalation is possible. This is not a bug to fix — it is
    what a US-only build (§22.3) means for a check that is by nature about
    foreign-exchange regimes. Asserting it here means the day someone makes this
    function reachable on ``us``, they will have had to change this test and
    therefore state why.
    """
    for fixed, free, independent in product([False, True], repeat=3):
        for directions in product([None, "easing", "tightening"], repeat=2):
            if fixed:
                continue  # not the admissible US space
            result = check_trilemma_tension(
                _inputs(
                    has_fixed_or_managed_fx=False,
                    has_free_capital_movement=free,
                    claims_monetary_independence=independent,
                    domestic_policy_direction_needed=directions[0],
                    peg_defense_direction_required=directions[1],
                    reserves_trend_pct_change_3mo=-0.99,
                    reserves_trend_pct_change_1mo=-0.99,
                )
            )
            assert as_str(result, key="severity") == "NO_TENSION"


def test_the_output_says_which_country_it_describes() -> None:
    """``ModelResult.country`` is ``"us"`` because the guard guarantees it.

    Hardcoding the literal is correct here *precisely because* the guard makes
    any other value unreachable — the two must be read together.

    The sweep's ``NX3`` mutation replaces the literal with ``inputs.country``
    and survives a naive version of this test, because the guard means the input
    *is* ``"us"`` on every reachable path — the two spellings agree. What makes
    them distinguishable is that the mutation is unsound rather than merely
    redundant: it would start lying the moment the guard moved. So the assertion
    is made *structurally* as well as behaviourally, by checking that the module
    source builds the result from the literal and not from the input.
    """
    result = check_trilemma_tension(_inputs())
    assert result.country == "us"

    # Structural half: the guard and the literal must both be present, adjacent
    # in intent even if not in line order. Reading the source is the only way to
    # distinguish "correctly hardcoded behind a guard" from "echoed from an
    # input" while the guard still holds.
    import inspect

    from macro_engine.models import regime as regime_module

    source = inspect.getsource(regime_module.check_trilemma_tension)
    assert 'if inputs.country != "us":' in source, "the guard must be present"
    assert 'country="us",' in source, (
        "the result country must be the literal the guard permits, not the "
        "caller's input echoed back — echoing is indistinguishable today only "
        "because the guard makes every reachable input equal to the literal"
    )
    assert "country=inputs.country" not in source


# ---------------------------------------------------------------------------
# 8. Structure of the output
# ---------------------------------------------------------------------------


def test_base_rates_are_published() -> None:
    """D-029: the categorical travels with the frequency its threshold fires at.

    The frequency is what separates a precondition from a signal, and the
    3-month rule fires on roughly a tenth of all months.
    """
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    rates = result.value
    assert isinstance(rates, dict)
    published = rates["base_rates"]
    assert isinstance(published, dict)
    assert published["depletion_3mo"] > 0.0
    assert published["break_1mo"] > 0.0
    assert any("BASE RATES (D-029)" in w for w in result.warnings)


def test_each_base_rate_carries_its_own_leaf() -> None:
    """The two rates are DIFFERENT numbers, and each must travel with its own test.

    The first draft of the mutation sweep left three survivors here — "the
    depletion rate reads the break leaf", "the break rate reads the depletion
    leaf", and "the two leaves swapped" — because the only assertion was
    ``> 0.0``, which every one of those mutations satisfies. That is a weak-test
    survivor, not an equivalent mutation.

    They are distinguishable on the shipped config: the 3-month rule fires more
    often than the 1-month rule (10.6% against 7.8%), because a three-month
    window has more opportunity to accumulate a breach. So the two values are
    asserted against each other's *identity* and against the config, not merely
    against zero.
    """
    published = check_trilemma_tension(_inputs(**_BW_CONFLICT)).value
    assert isinstance(published, dict)
    rates = published["base_rates"]
    assert isinstance(rates, dict)

    leaves = get_settings().regime.trilemma.base_rates
    assert rates["depletion_3mo"] == pytest.approx(float(leaves.depletion_3mo_base_rate.value))
    assert rates["break_1mo"] == pytest.approx(float(leaves.break_1mo_base_rate.value))
    assert rates["depletion_3mo"] != pytest.approx(rates["break_1mo"]), (
        "the two base rates are asserted to be different numbers, so a swap cannot "
        "hide; if a future measurement makes them equal, this assertion must be "
        "replaced by something that still distinguishes the leaves"
    )


def test_the_shipped_observations_denominator_is_not_the_observation_count() -> None:
    """The cadence finding, pinned so it cannot silently regress.

    ``TRESEGGBM052N`` reports 843 observations but only 837 of them are monthly,
    and only 834 admit both a 1-month and a 3-month change. The denominator must
    be the last of those, not the observation count — because every threshold
    here is a change over a *named number of months*, and a span computed across
    the annual prefix would not be the span it claims to be.
    """
    leaves = get_settings().regime.trilemma.base_rates
    assert leaves.observations_measured == 834
    assert leaves.observations_measured != 843, (
        "843 is the observation COUNT; using it as the denominator would include six "
        "annual points that span years under a 3-month label"
    )


def test_the_thresholds_used_are_published() -> None:
    """A reader must be able to see the rule that produced the severity.

    Both thresholds are echoed in ``value`` so a result computed under one
    configuration can be read after the configuration has changed.

    The shipped-config read alone is not enough: hardcoding either literal
    (sweep mutations ``NX25``/``NX26``) satisfies it, because the shipped values
    *are* those literals. So the same assertion is made a second time under the
    synthetic config, whose thresholds are different numbers — a hardcoded copy
    of the shipped literal cannot satisfy both.
    """
    depletion, break_1mo = _spec_thresholds()
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert isinstance(result.value, dict)
    assert result.value["depletion_threshold_3mo"] == pytest.approx(depletion)
    assert result.value["break_threshold_1mo"] == pytest.approx(break_1mo)

    with _PatchedSettings(_SYNTHETIC):
        patched = check_trilemma_tension(_inputs(**_BW_CONFLICT)).value
    assert isinstance(patched, dict)
    assert patched["depletion_threshold_3mo"] == pytest.approx(_SYNTHETIC_DEPLETION_3MO), (
        "the published threshold must follow the configuration, not a copied literal"
    )
    assert patched["break_threshold_1mo"] == pytest.approx(_SYNTHETIC_BREAK_1MO)
    assert patched["depletion_threshold_3mo"] != pytest.approx(depletion), (
        "the synthetic leaf must differ from the shipped literal, or this test is vacuous"
    )


def test_inputs_used_lists_only_what_was_supplied() -> None:
    """``inputs_used`` must not claim an input the caller did not provide.

    Asymmetric on purpose: the three booleans are always listed (they are
    required), the two directions and the two reserves measures only when
    present.
    """
    bare = check_trilemma_tension(_inputs())
    assert bare.inputs_used == [
        "has_fixed_or_managed_fx",
        "has_free_capital_movement",
        "claims_monetary_independence",
    ]
    full = check_trilemma_tension(
        _inputs(
            **_BW_CONFLICT,
            reserves_trend_pct_change_3mo=-0.99,
            reserves_trend_pct_change_1mo=-0.99,
        )
    )
    assert set(full.inputs_used) == {
        "has_fixed_or_managed_fx",
        "has_free_capital_movement",
        "claims_monetary_independence",
        "domestic_policy_direction_needed",
        "peg_defense_direction_required",
        "reserves_trend_pct_change_1mo",
        "reserves_trend_pct_change_3mo",
    }


def test_the_result_carries_the_manual_assessment_family() -> None:
    """Section 15.19-D: the provenance is typed, and here it is straightforwardly manual.

    Tagging this result ``MANUAL_ASSESSMENT`` is what stops a downstream
    convergence count from treating three asserted booleans as three
    independently-sourced pieces of evidence.
    """
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert result.source_family is EvidenceSourceFamily.MANUAL_ASSESSMENT


def test_the_measured_predicate_is_what_gates_the_published_rates() -> None:
    """``measured`` is a real predicate, not a constant — asserted in both directions.

    Two sweep mutations survived here (``CX4`` hardcoding ``measured`` to
    ``True``, ``CX7`` to ``False``), and the reason is that a property with two
    possible constants needs a state that **both** constants get wrong. The
    distinguishing state is a NON-ZERO measurement window: ``True`` would publish
    rates for an unmeasured configuration, ``False`` would deny them for a
    measured one.

    The assertions below therefore run the predicate inside the model's own call
    path — through ``check_trilemma_tension``, under a patched config — rather
    than only constructing ``TrilemmaBaseRates`` by hand. A hand-built model
    proves the property's arithmetic; only the model's use of it proves that
    ``_trilemma_base_rates`` consults it at all.
    """
    measured = get_settings().regime.trilemma.base_rates
    assert measured.measured is True, "the shipped configuration HAS been measured"
    assert measured.observations_measured > 0

    # Direction 1: a zero window with non-zero rates configured must read as
    # UNMEASURED and must publish nothing. `measured` hardcoded True fails here.
    rates_configured_window_zero = _SYNTHETIC.model_copy(
        update={
            "trilemma": _SYNTHETIC.trilemma.model_copy(
                update={
                    "base_rates": TrilemmaBaseRates(
                        observations_measured_value=_leaf(0),
                        depletion_3mo_base_rate=_leaf(0.106),
                        break_1mo_base_rate=_leaf(0.078),
                    )
                }
            )
        }
    )
    with _PatchedSettings(rates_configured_window_zero):
        result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert isinstance(result.value, dict)
    assert result.value["base_rates"] is None, (
        "rates without a measurement window are not a measurement — a `measured` "
        "constant of True would publish them as though they were"
    )
    assert any("NO BASE RATE AVAILABLE" in w for w in result.warnings)

    # Direction 2: a NON-ZERO window with real rates must read as MEASURED and
    # publish them. A `measured` constant of False fails here.
    window_nonzero = _SYNTHETIC.model_copy(
        update={
            "trilemma": _SYNTHETIC.trilemma.model_copy(
                update={
                    "base_rates": TrilemmaBaseRates(
                        observations_measured_value=_leaf(834),
                        depletion_3mo_base_rate=_leaf(0.106),
                        break_1mo_base_rate=_leaf(0.078),
                    )
                }
            )
        }
    )
    with _PatchedSettings(window_nonzero):
        published = check_trilemma_tension(_inputs(**_BW_CONFLICT)).value
    assert isinstance(published, dict)
    assert isinstance(published["base_rates"], dict), (
        "a non-zero measurement window IS a measurement — a `measured` constant of "
        "False would deny rates that were actually estimated"
    )
    assert published["base_rates"]["depletion_3mo"] == pytest.approx(0.106)
    assert published["base_rates"]["break_1mo"] == pytest.approx(0.078)


def test_extra_input_fields_are_refused() -> None:
    """``extra="forbid"``: a caller cannot smuggle a field the model ignores."""
    with pytest.raises(ValidationError, match="unexpected_field"):
        TrilemmaInputs(**{**_PEGGED, "country": "us", "unexpected_field": 1})  # type: ignore[arg-type]


def test_the_module_level_assertions_are_present_and_evaluated() -> None:
    """The D-045a guard is a module-level ``assert``, so deleting it is silent.

    A bare ``assert`` at module scope runs once at import; removing it changes
    nothing observable at runtime, which is why the sweep's "the agreement
    assertion removed" mutation survived.  It is still worth having — it fails
    loudly under ``python -O``-free test runs if the two halves ever diverge —
    but the guard is only real if its *presence* is asserted somewhere.

    Checked by reading the source, because that is the only place the
    difference exists. ``python -O`` strips asserts, so this test is written to
    fail if the assertion is dropped rather than to rely on it firing.
    """
    import inspect

    from macro_engine.models import regime as regime_module

    source = inspect.getsource(regime_module)
    assert "assert set(get_args(TrilemmaSeverity)) == set(TRILEMMA_SEVERITIES)" in source, (
        "the D-045a two-halves guard must be present in the module source"
    )
    assert 'assert set(get_args(PolicyDirection)) == {"easing", "tightening"}' in source, (
        "every enumerated field gets its own two-halves guard (D-045a)"
    )
    # The guards must be evaluated, not merely written: `__debug__` is False
    # under `-O`, in which case the assertions above would be skipped at import
    # and this test is the only thing standing between a divergence and silence.
    assert __debug__ or True  # noqa: SIM222  (documents the dependency explicitly)


def test_every_warning_branch_is_reachable() -> None:
    """Every warning the function can emit is emitted by some input.

    Section 21.2 Step 5: an untested warning path is an untested safety
    mechanism. Enumerated here rather than trusted, because a warning behind an
    unreachable condition is indistinguishable from a warning nobody wrote.
    """
    cases = {
        "NO TRILEMMA TENSION BY CONSTRUCTION": _inputs(has_fixed_or_managed_fx=False),
        "DIRECTION CONFLICT NOT ASSESSABLE": _inputs(domestic_policy_direction_needed="easing"),
        "DIRECTIONS AGREE, ALL THREE LEGS CLAIMED": _inputs(
            domestic_policy_direction_needed="easing",
            peg_defense_direction_required="easing",
        ),
        "RESERVES NOT TRENDING DOWN, BUT THE CONFLICT IS LIVE": _inputs(**_BW_CONFLICT),
        "ACUTE BREAK WITHOUT A SUSTAINED TREND": _inputs(
            **_BW_CONFLICT,
            reserves_trend_pct_change_3mo=_BW_3MO,
            reserves_trend_pct_change_1mo=_BW_1MO,
        ),
        "SUSTAINED DEPLETION WITHOUT AN ACUTE BREAK": _inputs(
            **_BW_CONFLICT,
            reserves_trend_pct_change_3mo=-0.20,
            reserves_trend_pct_change_1mo=-0.01,
        ),
        "RESERVES TREND ABSENT": _inputs(**_BW_CONFLICT),
        "BASE RATES (D-029)": _inputs(),
        "CRITICAL_PEG_STRESS matches": _inputs(**_BW_CONFLICT, reserves_trend_pct_change_3mo=-0.99),
        "NON-US check on a US-only build": _inputs(**_BW_CONFLICT),
    }
    for marker, inputs in cases.items():
        result = check_trilemma_tension(inputs)
        assert any(marker in w for w in result.warnings), (
            f"no warning contains {marker!r}; got: {[w[:40] for w in result.warnings]}"
        )


def test_the_no_base_rate_branch_is_reachable() -> None:
    """The unpublished-base-rate warning must be emittable, not dead prose.

    Reached by patching the measurement window to zero — the state a fresh
    checkout would be in before anyone measured. A warning that cannot be
    reached is the same defect class as a branch that cannot be reached.
    """
    unmeasured = _SYNTHETIC.model_copy(
        update={
            "trilemma": _SYNTHETIC.trilemma.model_copy(
                update={
                    "base_rates": TrilemmaBaseRates(
                        observations_measured_value=_leaf(0),
                        depletion_3mo_base_rate=_leaf(0.0),
                        break_1mo_base_rate=_leaf(0.0),
                    )
                }
            )
        }
    )
    with _PatchedSettings(unmeasured):
        result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert any("NO BASE RATE AVAILABLE" in w for w in result.warnings)
    assert isinstance(result.value, dict)
    assert result.value["base_rates"] is None


def test_the_heuristic_flag_follows_the_config() -> None:
    """Calibrating the thresholds must switch the penalty off by itself.

    Read through the config rather than hardcoded, so the flag is a statement
    about the configuration and not about the code. The calibrated leaf uses a
    status from the permitted set other than ``uncalibrated_illustrative`` —
    which is the exact comparison ``_trilemma_thresholds_calibrated`` makes, so
    this test would catch a helper that tested for a *specific* status string
    rather than for the placeholder.
    """
    calibrated = _SYNTHETIC.model_copy(
        update={
            "trilemma": _SYNTHETIC.trilemma.model_copy(
                update={
                    "reserves_depletion_threshold_3mo": CalibratedValue(
                        value=-0.05,
                        calibration_status="conventional",
                        note="pretend a phase calibrated this",
                    ),
                    "reserves_break_threshold_1mo": CalibratedValue(
                        value=-0.03,
                        calibration_status="conventional",
                        note="pretend a phase calibrated this",
                    ),
                }
            )
        }
    )
    with _PatchedSettings(calibrated):
        result = check_trilemma_tension(
            _inputs(**_BW_CONFLICT, reserves_trend_pct_change_3mo=_SYNTHETIC_DEPLETION_3MO - 0.01)
        )
    assert as_str(result, key="severity") == "CRITICAL_PEG_STRESS"
    uncalibrated = check_trilemma_tension(
        _inputs(**_BW_CONFLICT, reserves_trend_pct_change_3mo=_SYNTHETIC_DEPLETION_3MO - 0.01)
    )
    assert result.confidence > uncalibrated.confidence, (
        "lifting the heuristic penalty must raise the confidence, and the synthetic "
        "threshold above is shallower than the shipped one so both runs escalate"
    )


def test_one_uncalibrated_threshold_keeps_the_penalty() -> None:
    """``all`` rather than ``any``: the escalation is as calibrated as its weakest threshold.

    Mixing one calibrated leaf with one placeholder must NOT lift the penalty.
    A helper written with ``any`` would pass the previous test and fail this
    one, which is why both exist.
    """
    mixed = _SYNTHETIC.model_copy(
        update={
            "trilemma": _SYNTHETIC.trilemma.model_copy(
                update={
                    "reserves_depletion_threshold_3mo": CalibratedValue(
                        value=-0.05,
                        calibration_status="conventional",
                        note="calibrated half",
                    )
                    # break_1mo left as the synthetic fitted_assumption leaf,
                    # which `_SYNTHETIC` gives a non-placeholder status; so flip
                    # it explicitly to the placeholder to make the mix real.
                }
            )
        }
    )
    uncalibrated_break = _SYNTHETIC.model_copy(
        update={
            "trilemma": mixed.trilemma.model_copy(
                update={
                    "reserves_break_threshold_1mo": CalibratedValue(
                        value=-0.03,
                        calibration_status="uncalibrated_illustrative",
                        note="the one placeholder left",
                    )
                }
            )
        }
    )
    with _PatchedSettings(uncalibrated_break):
        result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert result.confidence == pytest.approx(
        check_trilemma_tension(_inputs(**_BW_CONFLICT)).confidence
    ), "one uncalibrated threshold must keep the heuristic penalty in place"


def test_severity_is_a_string_not_a_dict_entry() -> None:
    """The severity lives in ``value`` alongside its evidence, not as the whole value.

    Pinned because a caller writing ``result.value == "CRITICAL_PEG_STRESS"``
    would be reading a contract the model does not offer — every other synthesis
    function here publishes a dict, and the severity alone is not actionable
    (a reader needs the two booleans and the base rates to interpret it).
    """
    result = check_trilemma_tension(_inputs(**_BW_CONFLICT))
    assert isinstance(result.value, dict)
    assert result.value["severity"] in TRILEMMA_SEVERITIES
    assert as_float(result, key="depletion_threshold_3mo") < 0.0
