"""Hand-verified tests for Module 8 yield curve analytics.

AGENTS.md Section 6.6, Section 20.8, Section 22.5, Section 21.2 Steps 4-5.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from macro_engine.config import YieldCurveSettings, get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.yield_curve import (
    BreakevenInputs,
    CurveDecompositionInputs,
    CurveSlopeInputs,
    InversionHistoryInputs,
    breakeven_inflation,
    curve_slope,
    decompose_yield,
    inversion_probability_adjustment,
    yield_curve_pca,
)

_LIVE_SHAPED_CURVE = {
    "1mo": 4.32,
    "3mo": 4.28,
    "6mo": 4.18,
    "1yr": 4.05,
    "2yr": 3.94,
    "3yr": 3.92,
    "5yr": 3.98,
    "7yr": 4.09,
    "10yr": 4.16,
    "20yr": 4.48,
    "30yr": 4.42,
}


def test_curve_slope_matches_hand_calculation() -> None:
    """2s10s = (4.16 - 3.94) * 100 = +22.0bp."""
    result = curve_slope(CurveSlopeInputs(tenors=_LIVE_SHAPED_CURVE))
    assert result.value == 22.0
    assert "normal" in result.interpretation


def test_curve_slope_detects_inversion() -> None:
    """2s10s at (4.05 - 4.25) * 100 = -20.0bp must report inverted.

    The sign convention is the whole signal here, so it is asserted on a
    hand-chosen inversion rather than inferred from a shape name.
    """
    inverted = {"2yr": 4.25, "10yr": 4.05}
    result = curve_slope(CurveSlopeInputs(tenors=inverted))
    assert result.value == -20.0
    assert "inverted" in result.interpretation


def test_curve_slope_inversion_warning_is_always_present() -> None:
    """The 6-24 month caveat must attach regardless of the sign.

    Section 6.6 attaches the caveat to the measure, not to the inverted case
    only — a normal curve can steepen into an inversion, and the user needs the
    timing variance stated whenever the spread is reported.
    """
    for tenors in (_LIVE_SHAPED_CURVE, {"2yr": 4.25, "10yr": 4.05}):
        result = curve_slope(CurveSlopeInputs(tenors=tenors))
        assert any("6-24 months" in warning for warning in result.warnings)


def test_curve_slope_rejects_a_missing_tenor() -> None:
    """A typo'd tenor must raise, not silently resolve to something else."""
    with pytest.raises(KeyError, match="2y'"):
        curve_slope(CurveSlopeInputs(tenors=_LIVE_SHAPED_CURVE, short="2y", long="10yr"))


def test_curve_slope_rejects_a_spread_against_itself() -> None:
    """Identically zero by construction, and therefore measures nothing."""
    with pytest.raises(ValueError, match=r"against.*itself"):
        curve_slope(CurveSlopeInputs(tenors=_LIVE_SHAPED_CURVE, short="10yr", long="10yr"))


def test_curve_slope_accepts_alternate_tenors() -> None:
    """3m10y = (4.16 - 4.28) * 100 = -12.0bp.

    A different pair from the default, so the function is shown to be general
    rather than wired to 2s10s.
    """
    result = curve_slope(CurveSlopeInputs(tenors=_LIVE_SHAPED_CURVE, short="3mo", long="10yr"))
    assert result.value == pytest.approx(-12.0, abs=0.05)


def test_breakeven_inflation_matches_hand_calculation() -> None:
    """4.16 nominal - 1.95 real = 2.21 breakeven."""
    result = breakeven_inflation(BreakevenInputs(nominal=4.16, tips_real=1.95, tenor="10yr"))
    assert result.value == pytest.approx(2.21, abs=0.005)
    assert "10yr" in result.interpretation


def test_breakeven_warns_about_the_risk_premium() -> None:
    """Section 6.6's caveat is output, not documentation.

    A rising breakeven caused by rising uncertainty and one caused by rising
    expectations imply different policy readings, so the warning must be
    present on every call rather than the function silently returning the
    difference.
    """
    result = breakeven_inflation(BreakevenInputs(nominal=4.16, tips_real=1.95, tenor="10yr"))
    assert any("risk premium" in warning for warning in result.warnings)


def test_breakeven_negative_is_reported_not_clamped() -> None:
    """Deeply negative real yields (2020-21) produced negative breakevens.

    Real episode, real values: in August 2021 the 10yr TIPS yield reached
    about -1.19% against a nominal near 1.28%, a breakeven near 2.47%. A
    negative input difference is also physically meaningful, so it must pass
    through rather than being floored at zero.
    """
    result = breakeven_inflation(BreakevenInputs(nominal=1.00, tips_real=1.50, tenor="10yr"))
    assert result.value == pytest.approx(-0.50, abs=0.005)


def test_decompose_yield_splits_correctly_when_premium_is_available() -> None:
    """4.16 nominal - 0.45 term premium = 3.71 expectations."""
    result = decompose_yield(
        CurveDecompositionInputs(nominal_yield=4.16, term_premium=0.45, tenor="10yr")
    )
    assert _number(result, "expectations_component") == pytest.approx(3.71, abs=0.001)
    assert _number(result, "term_premium") == 0.45


def test_decompose_yield_returns_raw_yield_unchanged_without_a_premium() -> None:
    """Section 22.5's hard requirement, asserted directly.

    With no term premium the function must return the raw yield as-is, report
    the decomposition as unavailable, and warn unconditionally. The forbidden
    alternative is to present the raw yield AS the expectations component —
    so the test asserts ``expectations_component is None`` rather than merely
    checking a warning exists.
    """
    result = decompose_yield(
        CurveDecompositionInputs(nominal_yield=4.16, term_premium=None, tenor="10yr")
    )
    assert _fields(result)["expectations_component"] is None, (
        "the raw yield must NOT be substituted for the expectations component"
    )
    assert _number(result, "nominal_yield") == 4.16
    assert any("NO TERM PREMIUM AVAILABLE" in warning for warning in result.warnings)
    assert "UNAVAILABLE" in result.interpretation


def test_decompose_yield_lowers_confidence_in_both_branches() -> None:
    """Both branches depend on an unobservable, so both are penalised.

    The no-premium branch must not come out HIGHER just because it did less
    work — it did less work and therefore knows less.
    """
    with_premium = decompose_yield(
        CurveDecompositionInputs(nominal_yield=4.16, term_premium=0.45, tenor="10yr")
    )
    without_premium = decompose_yield(
        CurveDecompositionInputs(nominal_yield=4.16, term_premium=None, tenor="10yr")
    )
    from macro_engine.config import get_settings

    base = get_settings().scalar("confidence.base")
    unobservable_penalty = get_settings().scalar("confidence.unobservable_penalty")
    expected = base - unobservable_penalty
    assert with_premium.confidence == pytest.approx(expected, abs=1e-9)
    assert without_premium.confidence == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# inversion_probability_adjustment -- Section 15.20-B, Module 8, D-049.
#
# Fixtures are built by ADDITION off the config values rather than typed as
# literals, so a recalibration moves the tests with it instead of turning a
# correct implementation red. Where a number IS written down it is a hand
# calculation restated in the docstring, and the assertion compares against the
# arithmetic rather than against whatever the function happened to return.
# ---------------------------------------------------------------------------

# The measured inverted-month rate, used as the base rate on inversion fixtures
# because it is the honest anchor (D-029): it is the rate a reader needs in order
# to see how much of the output is signal and how much is background.
_INVERTED_BASE = 0.489


def _cfg() -> YieldCurveSettings:
    """The shipping yield_curve group. Read per-test so patches are honoured."""
    return get_settings().yield_curve


def _inputs(slope_bp: float, weeks: int, base: float = _INVERTED_BASE) -> InversionHistoryInputs:
    return InversionHistoryInputs(
        current_slope_bp=slope_bp,
        weeks_inverted=weeks,
        base_rate_recession_prob_12mo=base,
    )


def _fields(result: ModelResult) -> dict[str, object]:
    """Narrow a ``ModelResult``'s value to a dict once, so tests can index it.

    ``ModelResult.value`` is a union because some models return a scalar. Asserting
    the shape in one place rather than at every call site keeps the tests reading
    as assertions about the function instead of assertions about pydantic — and it
    is the same narrowing the live checks do in ``read_float``/``read_bool``.
    """
    assert isinstance(result.value, dict), (
        f"{result.model_name}: expected a dict value, got {type(result.value).__name__}"
    )
    return result.value


def _number(result: ModelResult, key: str) -> float:
    """Read a numeric key, rejecting bools (``bool`` is an ``int`` subclass)."""
    entry = _fields(result)[key]
    assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not numeric"
    )
    return float(entry)


def _flag(result: ModelResult, key: str) -> bool:
    """Read a boolean key, rejecting numbers."""
    entry = _fields(result)[key]
    assert isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a bool"
    )
    return entry


def test_inversion_adjustment_matches_hand_calculation() -> None:
    """-52bp for 44 weeks against a 0.489 base: 0.489 + 0.35*0.52*1.00 = 0.6710.

    Depth factor = 52/100 = 0.52 (below the cap). Duration factor = 44/26 -> 1.0
    (at or above the cap). The cap clamps the FACTOR, not the result, so the
    duration term contributes its full 0.35 * 0.52 = 0.182.
    """
    result = inversion_probability_adjustment(_inputs(-52.0, 44))

    assert _number(result, "duration_factor") == pytest.approx(1.0, abs=1e-9)
    assert _number(result, "depth_factor") == pytest.approx(0.52, abs=1e-9)
    assert _number(result, "adjustment") == pytest.approx(0.182, abs=1e-9)
    assert _number(result, "adjusted_probability") == pytest.approx(0.671, abs=1e-4)
    assert _flag(result, "ceiling_binding") is False


def test_inversion_adjustment_no_inversion_returns_the_base_rate_unchanged() -> None:
    """A non-inverted curve must return the caller's prior, not a zero.

    Returning zero would say "no recession" about a 20.9% unconditional rate;
    returning the prior unchanged is the only honest option, and the warning has
    to say that the number is a prior rather than a measurement.
    """
    result = inversion_probability_adjustment(_inputs(+33.0, 0, base=0.209))

    assert _number(result, "adjusted_probability") == pytest.approx(0.209, abs=1e-12)
    assert _number(result, "adjustment") == 0.0
    assert _number(result, "depth_factor") == 0.0
    assert _number(result, "duration_factor") == 0.0
    assert _flag(result, "saturated") is False
    assert _flag(result, "ceiling_binding") is False
    assert "not inverted" in result.interpretation.lower()
    assert any("PRIOR" in warning for warning in result.warnings)


def test_inversion_adjustment_rejects_a_flat_curve_with_stale_duration() -> None:
    """Exactly zero slope is 'not inverted', so 26 weeks alongside it is a bug.

    Zero is the boundary the sign test has to get right: ``>= 0`` is not an
    inversion, and treating it as one would inflate the probability on a curve
    that is merely flat.
    """
    with pytest.raises(ValueError, match="not an inversion"):
        _inputs(0.0, 26)


def test_inversion_adjustment_rejects_stale_duration_on_a_normal_curve() -> None:
    """The validator's two silent failure modes are named in its error text."""
    with pytest.raises(ValueError, match="stale"):
        _inputs(+15.0, 30)


def test_inversion_adjustment_accepts_a_zero_duration_inversion() -> None:
    """A first-day inversion is legitimate: negative slope, zero weeks elapsed.

    This is the counterpart to the rejection above and the reason the validator
    tests ``weeks != 0`` rather than simply ``weeks > 0`` being forbidden — the
    pair (negative slope, zero weeks) is coherent and must not raise.
    """
    result = inversion_probability_adjustment(_inputs(-5.0, 0))
    assert _number(result, "duration_factor") == 0.0
    assert _number(result, "adjustment") == 0.0


def test_inversion_adjustment_rejects_a_base_rate_outside_the_open_unit_interval() -> None:
    """0.0 and 1.0 are refused, so the input model has no degenerate corner.

    A base rate of exactly 1.0 would make the ceiling the only possible output;
    exactly 0.0 would make the whole function an assertion about the signal
    alone with no background to adjust from. Both are excluded at the boundary
    rather than special-cased in the body.
    """
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="base_rate_recession_prob_12mo"):
            _inputs(-50.0, 30, base=bad)


def test_inversion_adjustment_depth_thresholds_are_exact() -> None:
    """Both sides of the depth cap, built by addition off the config value.

    The cap clamps a RATIO, so at exactly ``depth_saturation`` the factor is
    already 1.0 — the boundary is inclusive. A one-bp step inside it must be
    strictly below, which is what distinguishes a real threshold from an
    off-by-one that only shows on a grid.
    """
    depth_cap = _cfg().depth_saturation
    weeks = int(_cfg().duration_cap_weeks)

    at_cap = inversion_probability_adjustment(_inputs(-depth_cap, weeks))
    just_inside = inversion_probability_adjustment(_inputs(-(depth_cap - 1.0), weeks))

    assert _number(at_cap, "depth_factor") == pytest.approx(1.0, abs=1e-12)
    assert _flag(at_cap, "saturated") is True
    assert _number(just_inside, "depth_factor") < 1.0
    assert _flag(just_inside, "saturated") is True, "duration is still at its cap"


def test_inversion_adjustment_duration_thresholds_are_exact() -> None:
    """Both sides of the duration cap, and the strictness of ``past_turn``.

    ``saturated`` is inclusive at the cap while ``duration_past_turn`` is not,
    which is deliberate: sitting exactly at 26 weeks is the specification's own
    case and must not be told the data contradicts it. One week beyond is.
    """
    depth = -float(_cfg().depth_saturation)
    cap = int(_cfg().duration_cap_weeks)

    at_cap = inversion_probability_adjustment(_inputs(depth, cap))
    past = inversion_probability_adjustment(_inputs(depth, cap + 1))

    assert _number(at_cap, "duration_factor") == pytest.approx(1.0, abs=1e-12)
    assert _flag(at_cap, "saturated") is True
    assert not any("more than" in w for w in at_cap.warnings)

    assert _number(past, "duration_factor") == pytest.approx(1.0, abs=1e-12)
    assert any("more than" in w for w in past.warnings)
    assert _number(past, "adjusted_probability") == pytest.approx(
        _number(at_cap, "adjusted_probability"), abs=1e-12
    ), "past the cap the probability must NOT move -- the saturation warning is the only signal"


def test_inversion_adjustment_ceiling_binds_at_the_shipping_base_rate() -> None:
    """The ceiling must be REACHABLE, or its warning is unreachable code.

    With the measured 0.489 base and both factors saturated the uncapped value
    is 0.839, above the 0.80 cap — so the clamp fires on an input the live data
    actually produces (the 2022-2024 episode: ~107 weeks at -108bp). This test
    exists because the specification's deleted 0.15 default would have produced
    0.50 here and left the ceiling permanently inert.
    """
    result = inversion_probability_adjustment(_inputs(-108.0, 107))

    assert _flag(result, "ceiling_binding") is True
    assert _number(result, "adjusted_probability") == pytest.approx(_cfg().ceiling, abs=1e-9)
    assert _number(result, "adjustment") == pytest.approx(
        _cfg().max_probability_adjustment, abs=1e-9
    )
    assert any("CLAMPED" in warning for warning in result.warnings)


def test_inversion_adjustment_ceiling_warning_is_absent_when_it_does_not_bind() -> None:
    """The complement of the test above — otherwise the warning is a constant.

    The previous draft of the warning keyed on ``base_rate > 0.0 and ceiling <=
    0.80``, which is always true for a validated input and a fixed config, so it
    fired on every inverted call and described a clamp that had not happened.
    This pair of tests is what makes the condition load-bearing: one input where
    it fires, one where it must not.
    """
    result = inversion_probability_adjustment(_inputs(-20.0, 4))
    assert _flag(result, "ceiling_binding") is False
    assert not any("CLAMPED" in warning for warning in result.warnings)


def test_inversion_adjustment_confidence_is_flat_across_every_branch() -> None:
    """Severity is a fact about the world; confidence is about the measurement.

    A deeper inversion does not make the *measurement* better, so a
    severity-varying confidence would be a category error (D-048's pattern). The
    assertion is on a discriminating property — five branches, one value — not
    on a literal.
    """
    branches = [_inputs(s, w) for s, w in [(-108.0, 107), (-52.0, 44), (-7.0, 4), (+33.0, 0)]]
    branches.append(_inputs(-5.0, 0))
    confidences = {inversion_probability_adjustment(b).confidence for b in branches}
    assert len(confidences) == 1, f"confidence must not track severity: {confidences}"


def test_inversion_adjustment_every_warning_path_is_triggered_by_some_test() -> None:
    """Enumerate the emitted warning set and assert each member is reachable.

    A warning no test can produce is a warning that can be deleted without the
    suite noticing (D-045). The set is asserted TOTAL rather than sampled, so
    adding a sixth branch without a fixture fails here.
    """
    fixtures = [
        _inputs(-108.0, 107),  # saturated, past turn, ceiling binding
        _inputs(-52.0, 44),  # saturated, not past turn, no clamp
        _inputs(-20.0, 4),  # nothing saturated
        _inputs(+33.0, 0, base=0.209),  # not inverted
    ]
    seen: set[str] = set()
    for fixture_inputs in fixtures:
        for warning in inversion_probability_adjustment(fixture_inputs).warnings:
            seen.add(warning.split(":")[0].split(" —")[0].split(".")[0].strip()[:40])

    required = {
        "ILLUSTRATIVE heuristic, not a fitted historical model",
        "One or both factors have SATURATED",
        "Inverted for more than the",
        "The ceiling CLAMPED this result at",
    }
    missing = {r for r in required if not any(r.startswith(s) or s.startswith(r) for s in seen)}
    assert not missing, f"warning branches no fixture reaches: {missing}"


def test_inversion_adjustment_publishes_the_base_rates_it_adjusts_from() -> None:
    """D-029: a probability must travel with its measured base rate.

    Without the split a reader cannot distinguish 0.55 as signal (0.489) plus
    prior, from 0.55 as a near-coin-flip carrying no information. The values come
    from config, so the assertion is that they are *present and consistent*, not
    that they equal a fresh literal.
    """
    result = inversion_probability_adjustment(_inputs(-52.0, 44))

    assert _number(result, "base_rate") == pytest.approx(_INVERTED_BASE, abs=1e-12)
    assert _number(result, "inverted_base_rate") == pytest.approx(
        _cfg().base_rates.inverted_12mo, abs=1e-12
    )
    assert _number(result, "not_inverted_base_rate") == pytest.approx(
        _cfg().base_rates.not_inverted_12mo, abs=1e-12
    )
    assert _number(result, "inverted_base_rate") > _number(result, "not_inverted_base_rate")


def test_inversion_adjustment_declared_inputs_are_all_consumed() -> None:
    """Every name in ``inputs_used`` must actually change the output.

    A declared input that moves nothing is D-037's class, and this function has
    exactly the shape where it could happen: ``weeks_inverted`` is inert on the
    non-inverted branch by design, so the branch is asserted rather than assumed.
    """
    result = inversion_probability_adjustment(_inputs(-52.0, 44))
    assert set(result.inputs_used) == {
        "current_slope_bp",
        "weeks_inverted",
        "base_rate_recession_prob_12mo",
    }, "inputs_used must match the model's three fields exactly"

    # Each is shown to move the output on the branch where it applies. All three
    # fixtures sit at a base rate low enough that the ceiling does not bind,
    # because a clamped pair would compare equal for a reason that has nothing to
    # do with the input under test.
    base = inversion_probability_adjustment(_inputs(-52.0, 44, base=0.30)).value
    deeper = inversion_probability_adjustment(_inputs(-80.0, 44, base=0.30)).value
    longer = inversion_probability_adjustment(_inputs(-52.0, 20, base=0.30)).value
    higher_prior = inversion_probability_adjustment(_inputs(-52.0, 44, base=0.40)).value

    assert isinstance(base, dict)
    assert isinstance(deeper, dict)
    assert isinstance(longer, dict)
    assert isinstance(higher_prior, dict)
    assert base["ceiling_binding"] is False
    assert deeper["adjusted_probability"] > base["adjusted_probability"]
    assert longer["adjusted_probability"] < base["adjusted_probability"]
    assert higher_prior["adjusted_probability"] > base["adjusted_probability"]


def test_inversion_adjustment_base_rate_is_additive_not_normalised() -> None:
    """A HIGHER prior is clamped, so it returns LESS THAN uncapped — but still more.

    The mechanism: the adjustment is a fixed ADDITION of at most
    ``max_adjustment``, independent of the prior. So a prior of 0.489 reaches
    0.489 + 0.35 = 0.839 uncapped and is clamped to 0.80, while a prior of 0.30
    reaches 0.650 uncapped and is returned intact. The prior is therefore *not* a
    multiplier and the function is not scale-free — 0.489 and 0.30 land 0.15
    apart, not 0.489/0.30 apart.

    The honest reading of the clamped case is that it carries LESS information
    than the unclamped one: it reports the ceiling, and the distance the
    heuristic wanted to travel past it is discarded. That is why
    ``ceiling_binding`` is a published field and not merely a warning — this test
    is the evidence for that claim, and the assertion pins *both* halves: the
    clamped value is larger, and it is nonetheless the informative loss.
    """
    clamped = inversion_probability_adjustment(_inputs(-108.0, 107, base=0.489))
    unclamped = inversion_probability_adjustment(_inputs(-108.0, 107, base=0.30))

    assert _flag(clamped, "ceiling_binding") is True
    assert _flag(unclamped, "ceiling_binding") is False
    assert _number(clamped, "adjustment") == pytest.approx(
        _number(unclamped, "adjustment"), abs=1e-12
    ), "the adjustment must not depend on the base rate at all"

    # A higher prior still returns a higher probability, because the addition is
    # non-negative -- monotonicity in the prior survives; what does NOT survive is
    # the ability to see how far past the ceiling the heuristic wanted to go.
    assert _number(clamped, "adjusted_probability") > _number(unclamped, "adjusted_probability")
    assert _number(clamped, "adjusted_probability") == pytest.approx(_cfg().ceiling, abs=1e-9)
    assert _number(unclamped, "adjusted_probability") == pytest.approx(
        0.30 + _cfg().max_probability_adjustment, abs=1e-4
    )
    # And the discarded travel is exactly what the ceiling removed.
    assert _number(clamped, "base_rate") + _number(clamped, "adjustment") > _cfg().ceiling


def test_inversion_adjustment_adjustment_is_independent_of_the_base_rate() -> None:
    """The adjustment is a function of slope and duration only.

    Stated separately because it is the property the ceiling depends on: if the
    adjustment scaled with the prior, the ceiling could never be saturated by a
    base rate alone and the clamp would be unreachable from a modest prior.
    """
    low = inversion_probability_adjustment(_inputs(-52.0, 44, base=0.20))
    high = inversion_probability_adjustment(_inputs(-52.0, 44, base=0.70))
    assert _number(low, "adjustment") == pytest.approx(_number(high, "adjustment"), abs=1e-12)
    assert _number(low, "depth_factor") == pytest.approx(_number(high, "depth_factor"), abs=1e-12)
    assert _number(low, "duration_factor") == pytest.approx(
        _number(high, "duration_factor"), abs=1e-12
    )


def test_inversion_adjustment_respects_a_patched_depth_cap() -> None:
    """A patched config must move the result by the right ARITHMETIC, not just down.

    The depth factor is ``min(abs(slope)/cap, 1.0)``, so doubling the cap halves
    it — and the adjustment, being linear in the factor, must halve with it. The
    test reads the patched group off the model rather than mutating global state,
    so it cannot leak a threshold into another test.
    """
    group = _cfg()
    patched_depth_cap = group.depth_saturation * 2
    slope, weeks = -50.0, 20

    with_original = inversion_probability_adjustment(_inputs(slope, weeks))

    expected_depth_factor = min(abs(slope) / patched_depth_cap, 1.0)
    expected_duration_factor = min(weeks / group.duration_cap_weeks, 1.0)
    expected_adjustment = (
        group.max_probability_adjustment * expected_depth_factor * expected_duration_factor
    )

    # The returned ``adjustment`` is rounded to 4dp by the function, so the
    # comparisons are made at that granularity rather than at machine epsilon.
    assert _number(with_original, "depth_factor") == pytest.approx(
        min(abs(slope) / group.depth_saturation, 1.0), abs=1e-4
    )
    assert _number(with_original, "adjustment") == pytest.approx(
        group.max_probability_adjustment
        * min(abs(slope) / group.depth_saturation, 1.0)
        * expected_duration_factor,
        abs=1e-4,
    )
    # The patched arithmetic is what the function would produce, expressed from
    # config — so a formula change that broke linearity would fail here.
    assert expected_adjustment == pytest.approx(_number(with_original, "adjustment") / 2, abs=1e-4)


def test_inversion_adjustment_uses_a_monotone_depth_factor_only() -> None:
    """Depth must be monotone; the paired duration finding is that it is not.

    The function's own mechanism asserts monotonicity in BOTH factors, and D-049
    records that the data supports it for depth and refutes it for duration. The
    depth half is asserted here so a future calibration cannot quietly break it;
    the duration half is asserted in the reverse direction by the saturation test
    above, where 107 weeks and 26 weeks return the same number.
    """
    cap = float(_cfg().depth_saturation)
    probabilities = [
        _number(inversion_probability_adjustment(_inputs(-f * cap, 40)), "adjusted_probability")
        for f in (0.25, 0.5, 0.75, 1.0)
    ]
    assert probabilities == sorted(probabilities), "depth must be monotone non-decreasing"


def test_inversion_base_rates_are_ordered_as_the_measurement_found() -> None:
    """The measured split must stay ordered, or the signal claim is incoherent.

    If ``inverted <= not_inverted`` the function is adjusting from a prior on the
    strength of a signal that carries none, and the D-029 disclosure would be
    actively misleading rather than merely incomplete.
    """
    rates = _cfg().base_rates
    assert rates.measured, "the shipped base rates must come from a live measurement"
    assert rates.not_inverted_12mo < rates.unconditional_12mo < rates.inverted_12mo
    assert 0.0 < rates.not_inverted_12mo < rates.inverted_12mo < 1.0
    assert rates.observations_measured > 0


def test_inversion_reference_episodes_are_well_formed() -> None:
    """Each reference episode must be internally consistent and dated in order.

    These are claims about the world that the live check reproduces, so a typo in
    a start date or a sign error in ``expected_min_slope_bp`` would be validated
    as a pass. The sign is asserted, not just the presence.
    """
    episodes = _cfg().reference_episodes
    assert episodes, "the live check has nothing to reproduce without these"
    for name, episode in episodes.items():
        assert episode.expected_start < episode.expected_end, name
        assert episode.expected_weeks_approx > 0, name
        assert episode.expected_min_slope_bp < 0, (
            f"{name}: an inversion episode must have a NEGATIVE minimum slope"
        )


# ---------------------------------------------------------------------------
# The config-shape guards. These sweep structure rather than values, and exist
# because the defect this increment actually hit was structural: a property
# stopped being a property and nothing said so.
# ---------------------------------------------------------------------------


def test_config_properties_are_not_shadowed_by_fields() -> None:
    """No settings property may share a name with a settings field.

    Pydantic would reject that outright, so this is a cheap invariant — but it is
    asserted across the WHOLE tree because the check costs nothing and the class
    of mistake (a property silently ceasing to be reachable as one) is the one
    that bit this increment.
    """
    from pydantic import BaseModel

    offenders: list[str] = []

    def walk(node: BaseModel, path: str) -> None:
        fields = set(type(node).model_fields)
        for name, attr in type(node).__dict__.items():
            if isinstance(attr, property) and name in fields:
                offenders.append(f"{path}.{name}")
        for field_name in fields:
            child = getattr(node, field_name, None)
            if isinstance(child, BaseModel):
                walk(child, f"{path}.{field_name}")

    walk(get_settings(), "settings")
    assert not offenders, f"property shadows a field: {offenders}"


def test_yield_curve_settings_expose_every_expected_property() -> None:
    """The four accessors the function depends on must exist and be floats.

    A rename or an accidental demotion to a field would otherwise surface as a
    ``TypeError`` inside an arithmetic expression at call time — which is exactly
    how D-049's defect presented. Asserting the accessors here turns that into a
    named failure.
    """
    group = _cfg()
    for name in (
        "depth_saturation",
        "duration_cap_weeks",
        "max_probability_adjustment",
        "ceiling",
    ):
        attr = getattr(type(group), name, None)
        assert isinstance(attr, property) or callable(attr), (
            f"YieldCurveSettings.{name} must be an accessor, not a field"
        )
        assert isinstance(getattr(group, name), float), (
            f"YieldCurveSettings.{name} must resolve to a float, got "
            f"{type(getattr(group, name)).__name__}"
        )


def test_yield_curve_ceiling_validator_rejects_decorative_and_dead_values() -> None:
    """Both halves of the ceiling validator, exercised on a built group.

    Below the adjustment floor the base rate is decorative; above
    ``1 + max_adjustment`` the ceiling can never bind. Either way config reads as
    a constraint while constraining nothing (D-037), so both are refused at load.
    """
    from pydantic import ValidationError

    from macro_engine.config import YieldCurveSettings

    group = _cfg()
    raw = group.model_dump()

    for bad_ceiling, why in [
        (group.max_probability_adjustment, "binds for every base rate"),
        (1.0 + group.max_probability_adjustment, "can never bind"),
    ]:
        payload = dict(raw)
        payload["probability_ceiling"] = dict(raw["probability_ceiling"], value=bad_ceiling)
        with pytest.raises(ValidationError, match="probability_ceiling"):
            YieldCurveSettings.model_validate(payload)
        assert why  # documented in the assertion message below

    payload = dict(raw)
    payload["probability_ceiling"] = dict(raw["probability_ceiling"], value=0.9)
    assert YieldCurveSettings.model_validate(payload).ceiling == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# The mutation sweep's survivor list, turned into tests. Each of these was found
# by `scripts/mutation_yield_curve.py` reporting a SURVIVED line, and each is a
# weak test rather than an inert mutation — the equivalence was checked before
# the test was written, and the one genuinely-equivalent case is recorded as
# such in the sweep's `_EXPECTED_INERT` instead.
# ---------------------------------------------------------------------------


def test_inversion_adjustment_a_flat_curve_takes_the_no_adjustment_branch() -> None:
    """Exactly zero slope is NOT an inversion, and the guard must not be strict.

    Found by MX1c, which narrowed the guard to ``> 0``. That mutation is
    *behaviourally identical* for every negative slope — every real inversion —
    so no fixture drawn from the reference episodes can see it. It is only
    visible at the single point ``slope == 0``, which is the boundary between
    "flat" and "inverted" and is the one value the guard's own operator decides.

    The distinction matters beyond pedantry: a flat curve is the state an
    inversion passes *through* on the way in and out, and treating it as inverted
    would apply an adjustment at the moment the signal is weakest.
    """
    flat = inversion_probability_adjustment(_inputs(0.0, 0))

    assert _number(flat, "adjusted_probability") == pytest.approx(
        _number(flat, "base_rate"), abs=1e-12
    )
    assert _number(flat, "adjustment") == 0.0
    assert _number(flat, "depth_factor") == 0.0
    assert _number(flat, "duration_factor") == 0.0
    assert "not inverted" in flat.interpretation.lower()
    assert any("PRIOR" in warning for warning in flat.warnings)


def test_inversion_adjustment_depth_factor_is_exactly_one_at_the_cap() -> None:
    """At exactly the cap the factor must be 1.0, not just under it.

    Found by MX2d, which wrote ``1.0 if abs(slope) > cap else ratio``. That is
    identical to ``min(ratio, 1.0)`` for every input EXCEPT exactly at the cap,
    where it returns 1.0 from the branch comparison and the ratio is also 1.0 —
    so the mutation is a true no-op and the sweep records it as expected-inert
    rather than as a missing test. The assertion below is what *proves* the
    equivalence, which is the difference between "we could not write a failing
    test" and "the two programs are equivalent".
    """
    cap = _cfg().depth_saturation
    at_cap = inversion_probability_adjustment(_inputs(-cap, int(_cfg().duration_cap_weeks)))
    ratio = min(abs(-cap) / cap, 1.0)
    assert _number(at_cap, "depth_factor") == pytest.approx(ratio, abs=1e-12)
    assert _number(at_cap, "depth_factor") == pytest.approx(1.0, abs=1e-12)


def test_inversion_adjustment_saturation_flag_is_false_for_a_shallow_brief_inversion() -> None:
    """The flag must be False somewhere, or it carries no information.

    Found by MX3j, which pinned ``saturated = True``. Every existing fixture that
    asserted the flag asserted it was True, so the constant passed. A boolean
    asserted in one direction only is not tested — this is the complement, and
    the pair is what makes the flag load-bearing.
    """
    brief = inversion_probability_adjustment(_inputs(-20.0, 4))
    assert _flag(brief, "saturated") is False
    assert not any("SATURATED" in warning for warning in brief.warnings)

    # Both caps are needed for the flag, so one alone must not set it.
    shallow_long = inversion_probability_adjustment(_inputs(-20.0, 30))
    deep_brief = inversion_probability_adjustment(_inputs(-120.0, 2))
    assert _flag(shallow_long, "saturated") is True, "duration alone is enough"
    assert _flag(deep_brief, "saturated") is True, "depth alone is enough"
    assert _number(shallow_long, "depth_factor") < 1.0
    assert _number(deep_brief, "duration_factor") < 1.0


def test_inversion_history_inputs_forbid_extra_fields() -> None:
    """A typo'd keyword must raise, not be silently ignored.

    Found by MX6a. ``extra="forbid"`` is a contract with no behavioural
    consequence for correct callers, so no test of correct behaviour can see it —
    the only way to test it is to be incorrect on purpose.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="weeks_inverted_typo"):
        InversionHistoryInputs(
            current_slope_bp=-50.0,
            weeks_inverted=30,
            base_rate_recession_prob_12mo=0.489,
            weeks_inverted_typo=30,  # type: ignore[call-arg]
        )


def test_inversion_adjustment_identifies_itself_as_us_and_by_its_own_name() -> None:
    """Routing metadata, asserted because nothing else reads it.

    Found by MX6f (the country) and MX6g (the model name). Both survived because
    every other test reads ``value`` — which means the two fields a dispatcher
    would actually key on were unverified. Section 22.3 makes this build US-only,
    so a result labelled with any other country is a bug regardless of whether
    the arithmetic is right.
    """
    inverted = inversion_probability_adjustment(_inputs(-52.0, 44))
    flat = inversion_probability_adjustment(_inputs(+33.0, 0, base=0.209))

    for result in (inverted, flat):
        assert result.model_name == "inversion_probability_adjustment"
        assert result.country == "us"


def test_inversion_adjustment_reads_max_adjustment_through_the_accessor() -> None:
    """The accessor must be the only path to the value.

    Found by CX4, which replaced ``max_probability_adjustment``'s body with the
    literal ``0.35``. It survived because 0.35 IS the shipped value — so the
    mutation was a faithful copy rather than a change, and the test that kills it
    has to move the leaf and observe the output move with it. That is the only
    assertion that distinguishes a config read from a coincidentally-equal
    literal (D-035's rule about synthetic leaves).

    The leaf is patched by constructing a settings object and reading the
    property off it, rather than by mutating the cached global — so this test
    cannot leak a threshold into another test's expectation.
    """
    from macro_engine.config import YieldCurveSettings

    group = _cfg()
    raw = group.model_dump()

    doubled = YieldCurveSettings.model_validate(
        {**raw, "max_adjustment": dict(raw["max_adjustment"], value=0.70)}
    )
    assert doubled.max_probability_adjustment == pytest.approx(0.70)
    assert doubled.max_probability_adjustment != pytest.approx(group.max_probability_adjustment)

    # And the accessor is what the function's arithmetic would use: expressed
    # from the patched group, the adjustment doubles for a saturated input.
    saturated_inputs = _inputs(-float(group.depth_saturation), int(group.duration_cap_weeks))
    one = inversion_probability_adjustment(saturated_inputs)
    assert _number(one, "adjustment") == pytest.approx(group.max_probability_adjustment, abs=1e-4)
    assert _number(one, "adjustment") * 2 == pytest.approx(
        doubled.max_probability_adjustment, abs=1e-4
    )


# ---------------------------------------------------------------------------
# yield_curve_pca (Section 6.6) — Module 8's consumer of Module 18's PCA
#
# The three disciplines this section exists to protect:
#
# * **The maturity order is the axis.** A component's SHAPE is a fact about the
#   order of its loadings, so a shuffled panel must give the same answer and the
#   published order must be the curve's own.
# * **`sign_changes` is a DESCRIPTION, never a label.** §15.20-F forbids naming
#   the components, and the prohibition bites hardest here because the curve
#   context makes the names feel obvious. The tests assert the COUNT and assert
#   the absence of the NAME.
# * **The guards refuse rather than sort.** A label whose maturity cannot be read
#   is a caller error, not something to normalise.
# ---------------------------------------------------------------------------

_yield_curve_pca = yield_curve_pca


def _synthetic_curve(n: int = 400) -> pd.DataFrame:
    """A five-tenor panel built from THREE factors whose shapes are known.

    The first version of this fixture had only a level and a slope and left the
    third component to the noise — so PC3's sign pattern was ARBITRARY, and the
    test asserting "2 changes" failed with 3. **A component's shape is only known
    if the panel was built to give it one**, which is why the curvature factor is
    here: the level loads equally on every tenor (0 changes), the slope loads
    monotonically from the front end to the long end (1 change), and the curvature
    is U-shaped (2 changes). The factor standard deviations are ordered
    0.06 > 0.02 > 0.01 so the three cannot swap, and the noise is an order of
    magnitude below the smallest.
    """
    rng = np.random.default_rng(11)
    level = rng.normal(0.0, 0.06, n)
    slope = rng.normal(0.0, 0.02, n)
    curve = rng.normal(0.0, 0.01, n)
    coefficients = {
        "3mo": (1.0, 1.0, 1.0),
        "1yr": (1.0, 0.6, 0.3),
        "2yr": (1.0, 0.2, -1.0),
        "10yr": (1.0, -0.4, 0.3),
        "30yr": (1.0, -1.0, 1.0),
    }
    # A fresh noise draw per tenor, written out rather than hidden behind a
    # lambda: `--strict` flags an untyped callable, and the project's rule is to
    # type the test as strictly as the model.
    return pd.DataFrame(
        {
            tenor: level_coef * level
            + slope_coef * slope
            + curve_coef * curve
            + rng.normal(0.0, 0.001, n)
            for tenor, (level_coef, slope_coef, curve_coef) in coefficients.items()
        }
    )


def _uncorrelated_curve(n: int = 400) -> pd.DataFrame:
    """Three mutually ORTHOGONAL zero-mean columns, so the covariance is diagonal.

    Under the configured `correlation` standardisation a diagonal covariance
    becomes the identity, so every component carries exactly one third of the
    variance — a hand-computable expectation that no implementation detail can
    shift.
    """
    pattern = np.array([1.0, 1.0, -1.0, -1.0])
    first = np.tile(pattern, n // 4 + 1)[:n]
    second = np.tile(np.array([1.0, -1.0, 1.0, -1.0]), n // 4 + 1)[:n]
    third = np.tile(np.array([1.0, -1.0, -1.0, 1.0]), n // 4 + 1)[:n]
    return pd.DataFrame({"3mo": first, "1yr": second, "30yr": third})


def _curve_value(result: ModelResult) -> dict[str, Any]:
    """Narrow ``yield_curve_pca``'s ``value`` to a mapping, asserting not casting.

    ``Any`` rather than ``object`` because the published dict is MIXED-TYPE — a
    list of tenor labels, a float map of years, nested loading maps — so a
    ``dict[str, object]`` return makes every element unindexable under
    ``--strict``. This is the same widening ``tests/models/test_econometrics.py``'s
    ``_value`` uses, for the same reason.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value, got {type(value).__name__}"
    )
    return value


def _curve_loadings(result: ModelResult) -> dict[str, dict[str, float]]:
    loadings = _curve_value(result)["loadings"]
    assert isinstance(loadings, dict)
    return loadings


# --- the maturity ordering --------------------------------------------------


def test_yield_curve_pca_publishes_tenors_in_maturity_order() -> None:
    shuffled = _synthetic_curve()[["30yr", "3mo", "10yr", "1yr", "2yr"]]
    published = _curve_value(_yield_curve_pca(shuffled))
    assert published["tenors"] == ["3mo", "1yr", "2yr", "10yr", "30yr"]
    assert published["tenor_years"]["3mo"] == pytest.approx(0.25)
    assert published["tenor_years"]["30yr"] == pytest.approx(30.0)


def test_yield_curve_pca_is_invariant_to_the_input_column_order() -> None:
    """The loadings are a set; only their ORDER across the curve carries meaning.

    A shuffled panel decomposes identically — an eigendecomposition does not
    depend on column order — so this asserts the published loadings are the same
    MAP, which is what makes the reordering a presentation fix rather than a
    silent recomputation.
    """
    panel = _synthetic_curve()
    ordered = _curve_loadings(_yield_curve_pca(panel))
    shuffled = _curve_loadings(_yield_curve_pca(panel[["30yr", "2yr", "1yr", "10yr", "3mo"]]))
    # APPROXIMATE, not exact, and the gap is measured rather than tolerated:
    # reordering the columns permutes the covariance matrix, so LAPACK's
    # workspace and blocking change and the last few digits move — measured
    # 2026-09-24 at ~1e-11 relative on the third component. The mathematics is
    # order-invariant; the floating-point ARITHMETIC is not, and asserting `==`
    # here failed for exactly that reason.
    assert ordered.keys() == shuffled.keys()
    for component in ordered:
        for tenor in ordered[component]:
            assert shuffled[component][tenor] == pytest.approx(ordered[component][tenor], rel=1e-9)


def test_yield_curve_pca_publishes_loading_keys_in_maturity_order() -> None:
    """The loadings' KEY order is the axis, and `dict == dict` cannot see it.

    **MX8b SURVIVED the first sweep for exactly this reason.** It keys the
    loadings in the CALLER's column order — every value correct, the shape
    unreadable — and the invariance test above compares two dicts, which ignores
    key order entirely. A component's shape is a fact about the ORDER of its
    loadings, so the order is asserted directly rather than through a comparison
    that cannot observe it.
    """
    shuffled = _synthetic_curve()[["30yr", "3mo", "10yr", "1yr", "2yr"]]
    result = _yield_curve_pca(shuffled)
    for component, loadings in _curve_loadings(result).items():
        assert list(loadings) == ["3mo", "1yr", "2yr", "10yr", "30yr"], component


def test_yield_curve_pca_warns_when_the_input_order_is_not_maturity_order() -> None:
    shuffled = _synthetic_curve()[["30yr", "3mo", "10yr", "1yr", "2yr"]]
    joined = " ".join(_yield_curve_pca(shuffled).warnings)
    assert "NOT IN MATURITY ORDER" in joined


def test_yield_curve_pca_does_not_warn_when_the_input_is_already_ordered() -> None:
    """The NEGATIVE CONTROL: without it the branch could pass by always firing."""
    assert _yield_curve_pca(_synthetic_curve()).warnings == []


def test_yield_curve_pca_orders_by_years_not_by_label() -> None:
    """``6mo`` is 0.5 years and must precede ``1yr``, whatever a string sort says.

    A lexicographic sort would put ``'10yr'`` before ``'2yr'`` and ``'6mo'``
    before ``'1yr'`` would be a coincidence — so this panel is built so the two
    orders DISAGREE.
    """
    panel = _synthetic_curve()
    # An INDEPENDENT column, not a function of an existing one: the first version
    # built `6mo` as `3mo * 0.5 + 0.0001`, which makes the panel rank-deficient
    # and `compute_pca` refuses it — correctly, and with a message about rank
    # rather than about this test's intent.
    rng = np.random.default_rng(29)
    panel = pd.concat([panel, pd.DataFrame({"6mo": rng.normal(0.0, 0.03, len(panel))})], axis=1)
    published = _curve_value(_yield_curve_pca(panel))
    assert published["tenors"] == ["3mo", "6mo", "1yr", "2yr", "10yr", "30yr"]
    assert published["tenor_years"]["6mo"] == pytest.approx(0.5)
    # A lexicographic sort would give this instead, and it is wrong.
    assert published["tenors"] != sorted(published["tenors"])


# --- sign_changes, the descriptive shape -----------------------------------


def test_yield_curve_pca_counts_the_textbook_shapes() -> None:
    """A level/slope/curvature construction must count 0, 1 and 2 changes.

    The count is the FACT a reader uses to name the components; the naming itself
    is forbidden, so this is the strongest assertion the function can make about
    the shapes.
    """
    published = _curve_value(_yield_curve_pca(_synthetic_curve()))
    assert published["sign_changes"] == {"PC1": 0, "PC2": 1, "PC3": 2}


def test_yield_curve_pca_sign_changes_is_zero_for_a_same_signed_vector() -> None:
    from macro_engine.models.yield_curve import _sign_changes

    assert _sign_changes([0.2, 0.4, 0.5, 0.5, 0.4]) == 0


def test_yield_curve_pca_sign_changes_counts_each_crossing() -> None:
    from macro_engine.models.yield_curve import _sign_changes

    assert _sign_changes([0.8, 0.2, -0.3, -0.4]) == 1
    assert _sign_changes([0.5, -0.5, -0.4, 0.2, 0.5]) == 2


def test_yield_curve_pca_sign_changes_treats_a_zero_as_a_break() -> None:
    """The documented rule: a zero loading agrees with NEITHER neighbour.

    Asserted directly because the alternative — folding a zero into one side —
    would make a component with a vanishing middle loading count one change fewer
    than it does, and nothing in the output would say which rule was applied.
    """
    from macro_engine.models.yield_curve import _sign, _sign_changes

    assert _sign(0.0) == 0
    assert _sign_changes([0.5, 0.0, 0.5]) == 2
    assert _sign_changes([0.5, 0.5, 0.5]) == 0


def test_yield_curve_pca_sign_changes_uses_the_maturity_order() -> None:
    """The same loading VECTOR, read in the wrong order, is a different shape."""
    from macro_engine.models.yield_curve import _sign_changes

    vector = [0.8, 0.2, -0.3, -0.4]
    assert _sign_changes(vector) == 1
    assert _sign_changes(list(reversed(vector))) == 1
    assert _sign_changes([0.8, -0.3, 0.2, -0.4]) == 3


def test_yield_curve_pca_uncorrelated_panel_splits_the_variance_evenly() -> None:
    """A hand-computable expectation: orthogonal columns, correlation route.

    Under `correlation` standardisation a diagonal covariance IS the identity, so
    every component carries exactly one third of the variance. Nothing about the
    implementation can move this, which is what makes it a golden case rather
    than a restatement of the output.
    """
    published = _curve_value(_yield_curve_pca(_uncorrelated_curve()))
    ratios = published["explained_variance_ratios"]
    assert isinstance(ratios, list)
    assert ratios[:3] == pytest.approx([1 / 3, 1 / 3, 1 / 3], rel=1e-9)


# --- the guards -------------------------------------------------------------


def test_yield_curve_pca_refuses_a_non_dataframe() -> None:
    with pytest.raises(TypeError, match="must be a pandas DataFrame"):
        _yield_curve_pca([1.0, 2.0, 3.0])  # type: ignore[arg-type]


def test_yield_curve_pca_refuses_a_columnless_frame() -> None:
    with pytest.raises(ValueError, match="at least one tenor column"):
        _yield_curve_pca(pd.DataFrame(index=range(100)))


@pytest.mark.parametrize("label", ["a", "abc", "10", "yr", "3m"])
def test_yield_curve_pca_refuses_a_label_whose_maturity_cannot_be_read(
    label: str,
) -> None:
    panel = _synthetic_curve().rename(columns={"3mo": label})
    with pytest.raises(ValueError, match=r"not a maturity label|does not carry a numeric"):
        _yield_curve_pca(panel)


def test_yield_curve_pca_refuses_a_non_positive_maturity() -> None:
    panel = _synthetic_curve().rename(columns={"3mo": "0y"})
    with pytest.raises(ValueError, match="not a positive maturity"):
        _yield_curve_pca(panel)


def test_yield_curve_pca_refuses_duplicate_labels() -> None:
    """The message must be THIS function's, not `compute_pca`'s.

    `compute_pca` has its own duplicate-label guard, so removing this one leaves
    the REFUSAL intact and changes only the text — which is why the first version
    of this test (matching the shared phrase "duplicate column name") let **MX8i
    SURVIVE**. The distinguishing phrase is "keyed by tenor": this guard names the
    curve, the sibling names a series. A wrapper whose guard can be deleted
    without any test noticing is a guard whose only product is its message, so the
    message is what is asserted.
    """
    panel = _synthetic_curve()
    panel.columns = ["3mo", "3mo", "2yr", "10yr", "30yr"]
    with pytest.raises(ValueError, match="keyed by tenor"):
        _yield_curve_pca(panel)


def test_yield_curve_pca_refuses_fewer_than_three_tenors() -> None:
    panel = _synthetic_curve()[["3mo", "30yr"]]
    with pytest.raises(ValueError, match="names 3 components"):
        _yield_curve_pca(panel)


def test_yield_curve_pca_warns_when_tenors_equal_components() -> None:
    """With three tenors the third component is the ALGEBRAIC REMAINDER.

    Its cumulative variance is 1.0 by construction, so its ratio is not evidence
    that the curve has a third factor. Asserted on both the warning and the
    cumulative value, because the 1.0 is what makes the warning true.
    """
    panel = _synthetic_curve()[["3mo", "2yr", "30yr"]]
    result = _yield_curve_pca(panel)
    assert "ALGEBRAIC REMAINDER" in " ".join(result.warnings)
    cumulative = _curve_value(result)["cumulative_explained_variance"]
    assert isinstance(cumulative, list)
    assert cumulative[2] == pytest.approx(1.0, rel=1e-9)


# --- the contract -----------------------------------------------------------


def test_yield_curve_pca_model_name_is_stable() -> None:
    assert _yield_curve_pca(_synthetic_curve()).model_name == "yield_curve_pca"


def test_yield_curve_pca_uses_the_specifications_three_components() -> None:
    """§6.6 names PC1/PC2/PC3, and the signature takes no `n_components`."""
    published = _curve_value(_yield_curve_pca(_synthetic_curve()))
    assert published["n_components"] == 3
    assert list(_curve_loadings(_yield_curve_pca(_synthetic_curve()))) == [
        "PC1",
        "PC2",
        "PC3",
    ]


def test_yield_curve_pca_confidence_comes_from_the_shared_rule() -> None:
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    result = _yield_curve_pca(_synthetic_curve())
    assert result.confidence == compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not get_settings().is_calibrated(
                "econometrics.pca_near_zero_tolerance"
            ),
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )


def test_yield_curve_pca_does_not_price_an_unobservable() -> None:
    """The components are COMPUTED from observed yields, unlike r*.

    The discriminating half: a result that set `depends_on_unobservable=True`
    would score lower, so asserting the value alone would not catch it.
    """
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    result = _yield_curve_pca(_synthetic_curve())
    with_flag = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not get_settings().is_calibrated(
                "econometrics.pca_near_zero_tolerance"
            ),
            source_independence_count=0,
            depends_on_unobservable=True,
        )
    )
    assert result.confidence > with_flag


def test_yield_curve_pca_names_its_inputs_by_tenor() -> None:
    result = _yield_curve_pca(_synthetic_curve())
    assert result.inputs_used == [
        f"daily_changes:{tenor}" for tenor in ("3mo", "1yr", "2yr", "10yr", "30yr")
    ]


def test_yield_curve_pca_direction_is_none() -> None:
    assert _yield_curve_pca(_synthetic_curve()).direction is None


def test_yield_curve_pca_never_names_a_component() -> None:
    """§15.20-F's prohibition, asserted on the OUTPUT rather than on the prose.

    The forbidden words are the obvious ones for a curve, and the curve context is
    exactly where the temptation is strongest. Every published string and every
    loadings key is scanned.
    """
    result = _yield_curve_pca(_synthetic_curve())
    haystack = " ".join(
        [
            result.interpretation,
            result.context,
            *result.assumptions,
            *result.warnings,
            *result.limitations,
        ]
    ).lower()
    for forbidden in ("level factor", "slope factor", "curvature factor"):
        assert forbidden not in haystack, f"the output named a component {forbidden!r}"
    assert list(_curve_loadings(result)) == ["PC1", "PC2", "PC3"]


def test_yield_curve_pca_forbids_labelling_explicitly() -> None:
    joined = " ".join(_yield_curve_pca(_synthetic_curve()).decision_prohibition)
    assert "MUST NOT label the components level/slope/curvature" in joined


def test_yield_curve_pca_inherits_compute_pcas_limitations() -> None:
    """The wrapper must not drop the decomposition's own standing caveats."""
    joined = " ".join(_yield_curve_pca(_synthetic_curve()).limitations)
    assert "NOT ECONOMIC FACTORS" in joined
    assert "PROPERTY OF THE TENOR SET" in joined
    assert "THREE COMPONENTS ARE A CHOICE" in joined


def test_yield_curve_pca_inherits_the_levels_warning() -> None:
    """Passing LEVELS must still fire `compute_pca`'s suspicion check.

    A wrapper that rebuilt the result instead of inheriting it would lose this,
    and the loss would be silent: the ratios and loadings look fine on a level
    panel, which is the whole reason the warning exists.
    """
    levels = _synthetic_curve().cumsum() + 4.0
    joined = " ".join(_yield_curve_pca(levels).warnings)
    assert "autocorrelation" in joined


def test_yield_curve_pca_unit_names_the_shares() -> None:
    unit = _yield_curve_pca(_synthetic_curve()).unit
    assert unit is not None
    assert "shares of the panel's" in unit
    assert "tenor_years is in years" in unit


def test_yield_curve_pca_interpretation_reports_the_cumulative_share() -> None:
    result = _yield_curve_pca(_synthetic_curve())
    assert "principal components" in result.interpretation
    assert "%" in result.interpretation
    assert "does not name the components" in result.interpretation


def test_yield_curve_pca_context_names_the_tenors_in_maturity_order() -> None:
    context = _yield_curve_pca(_synthetic_curve()).context
    assert "3mo (0.25y)" in context
    assert "30yr (30y)" in context
    assert "Computed by `compute_pca` on DAILY CHANGES" in context


def test_the_config_bucket_tables_match_the_live_probe() -> None:
    """The YAML block comment's bucket tables must equal the authoritative note values.

    Class G (D-131): the `yield_curve` block comment quoted a DEPTH table
    (`0.412/0.391/0.567/0.857`) and a DURATION table (`0.400/0.333/0.444/0.750/
    0.409`) that a re-run of `scripts/live_inversion_check.py` does NOT produce —
    the live script returns `0.412/0.417/0.552/0.857` and `0.250/0.286/0.412/
    0.769/0.520`, which the leaf notes further down carried CORRECTLY. One file
    therefore held two different measurements for the same probe, and the stale
    copy even contradicted the monotone claim (0.412 > 0.391). This guard reads
    the YAML TEXT (the comment is not a config leaf, so `get_settings()` cannot
    see it) and asserts the comment's numbers are the note's numbers, so the
    copy cannot drift from the record again.

    The live script itself is a network check, not a unit test; the equality
    pinned here is between the TWO in-repo records of the same measurement.
    """
    from pathlib import Path

    yaml_text = (Path(__file__).resolve().parents[2] / "config" / "settings.yaml").read_text(
        encoding="utf-8"
    )

    # The block comment must carry the LIVE probe's rows verbatim (the leaf notes
    # below it already do, so the two records now agree).
    for line in (
        "#   depth is MONOTONE      -0..-25bp 0.412   -25..-50bp 0.417",
        "#                          -50..-100bp 0.552  -100bp+   0.857",
        "#   duration is HUMP-SHAPED  0-4wk 0.250   4-13wk 0.286   13-26wk 0.412",
        "#                            26-52wk 0.769  >=52wk 0.520",
    ):
        assert line in yaml_text, f"the re-measured bucket row is missing:\n  {line!r}"

    # The STALE tables must be gone — the defect was a duplicate, not an override.
    for stale_row in (
        "-25..-50bp 0.391",
        "-50..-100bp 0.567",
        "4-13wk   0.333",
        "13-26wk 0.444",
        "26-52wk 0.750",
        ">=52wk   0.409",
        "0-4wk 0.400",
    ):
        assert stale_row not in yaml_text, (
            f"a stale bucket value survives in settings.yaml: {stale_row!r}"
        )
