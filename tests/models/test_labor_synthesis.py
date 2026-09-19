"""Module 6 tests — labor synthesis, claims significance, corroboration.

Section 11.1 mandates ``test_labor_tightness_score_weights``: "asserts NFP's
contribution coefficient is strictly lower than claims' and JOLTS', matching
the course's explicit lead/lag weighting."

Two of the tests here exist because of defects this module shipped with and
that no synthetic test caught. They are labelled D-022 and D-023 in
``docs/DECISIONS.md`` and they are the reason the claims tests assert *numbers*
rather than shapes.
"""

from __future__ import annotations

import math

import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.labor_synthesis import (
    ClaimsCorroborationInputs,
    ClaimsTrendInputs,
    InflationSubMeasures,
    LaborInputs,
    claims_corroboration,
    claims_trend_signal,
    inflation_breadth_score,
    labor_tightness_score,
)
from tests.helpers import as_bool, as_float, as_int

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

# A 13-week claims window, oldest first. Mean of the whole window is worked
# out in the tests rather than written down, so a typo here cannot make a
# test and an implementation agree on a wrong number.
_ICSA_13W = [
    210000.0,
    212000.0,
    225000.0,
    230000.0,
    227000.0,
    216000.0,
    217000.0,
    217000.0,
    209000.0,
    189000.0,
    198000.0,
    200000.0,
    212000.0,
]


def _window_mean(values: list[float]) -> float:
    return sum(values) / len(values)


# --------------------------------------------------------------------------
# labor_tightness_score
# --------------------------------------------------------------------------


def test_labor_tightness_score_matches_hand_calculation() -> None:
    """Section 6.4's worked example: +3.52 raw, reported as +3.5.

    Hand derivation, from the module docstring:
        claims_component = -(-0.4) * 2.0                        = +0.80
        jolts_component  = 0.5(3.0) + 0.5(60.0 - 50.0)          = +6.50
        nfp_component    = (180.0 - 150.0) / 10                 = +3.00
        score = 0.4(0.80) + 0.4(6.50) + 0.2(3.00)               = +3.52
    """
    result = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-0.4,
            jolts_openings_yoy_pct=3.0,
            jolts_quits_level_percentile=60.0,
            nfp_3m_avg=180.0,
        )
    )
    assert isinstance(result.value, float)
    assert result.value == pytest.approx(3.5, abs=1e-9)
    # The hand-derived components must be visible, so a reviewer can check the
    # derivation rather than trusting the total. +3.52 is the raw pre-rounding
    # value the module docstring documents; the context reports components to
    # 2dp, which is where each of those three numbers comes from.
    assert "claims +0.80" in result.context
    assert "JOLTS +6.50" in result.context
    assert "NFP +3.00" in result.context
    # And the raw total is recoverable from the components.
    raw = 0.4 * 0.80 + 0.4 * 6.50 + 0.2 * 3.00
    assert raw == pytest.approx(3.52, abs=1e-9)
    assert round(raw, 1) == result.value


def test_labor_tightness_score_weights() -> None:
    """Section 11.1's mandated test.

    NFP's contribution coefficient must be strictly LOWER than claims' and
    JOLTS'. The specification's lead/lag hierarchy says NFP is coincident and
    noisy, so equal weights would average a leading signal against a lagging
    one and produce something that leads nothing.

    Asserted two ways — structurally on the config, and behaviourally by
    measuring each block's marginal contribution to the score — because a
    config that is not what the code reads would satisfy only one of them.
    """
    weights = get_settings().labor.tightness_weights

    # Structural: the declared weights.
    assert weights.nfp_value < weights.claims_value
    assert weights.nfp_value < weights.jolts_value
    assert weights.total == pytest.approx(1.0, abs=1e-9)

    # Behavioural: perturb one block at a time from a zero-scoring baseline and
    # measure how much the score moves. The baseline is chosen so every
    # component contributes exactly zero, which makes each delta attributable
    # to the block that was perturbed.
    neutral = LaborInputs(
        initial_claims_4wk_avg_change_pct=0.0,
        jolts_openings_yoy_pct=0.0,
        jolts_quits_level_percentile=50.0,
        nfp_3m_avg=get_settings().labor.neutral_nfp_pace,
    )
    assert as_float(labor_tightness_score(neutral)) == pytest.approx(0.0, abs=1e-9)

    # A one-unit move in each block, in its own natural unit. The neutral
    # baseline scores exactly zero, so each delta IS the marginal contribution.
    claims_delta = as_float(
        labor_tightness_score(neutral.model_copy(update={"initial_claims_4wk_avg_change_pct": 1.0}))
    )
    nfp_delta = as_float(
        labor_tightness_score(
            neutral.model_copy(update={"nfp_3m_avg": get_settings().labor.neutral_nfp_pace + 10.0})
        )
    )
    assert abs(nfp_delta) < abs(claims_delta), (
        f"NFP's marginal contribution ({nfp_delta:+.4f}) must be strictly below "
        f"claims' ({claims_delta:+.4f})"
    )


def test_labor_tightness_score_sign_convention() -> None:
    """Rising claims must LOWER the score; the multiplier carries the sign."""
    base = LaborInputs(
        initial_claims_4wk_avg_change_pct=0.0,
        jolts_openings_yoy_pct=0.0,
        jolts_quits_level_percentile=50.0,
        nfp_3m_avg=150.0,
    )
    tighter = base.model_copy(update={"initial_claims_4wk_avg_change_pct": -2.0})
    looser = base.model_copy(update={"initial_claims_4wk_avg_change_pct": +2.0})
    assert as_float(labor_tightness_score(tighter)) > 0.0
    assert as_float(labor_tightness_score(looser)) < 0.0
    # And symmetric, because the multiplier is a scalar.
    assert as_float(labor_tightness_score(tighter)) == pytest.approx(
        -as_float(labor_tightness_score(looser)), abs=1e-9
    )


def test_quits_percentile_is_centred_on_fifty() -> None:
    """A market mid-range contributes zero, not fifty (the centring offset).

    Without centring, the JOLTS term would carry a constant `+25`-ish offset
    unrelated to current conditions, and every score would be shifted upward.
    """
    at_middle = LaborInputs(
        initial_claims_4wk_avg_change_pct=0.0,
        jolts_openings_yoy_pct=0.0,
        jolts_quits_level_percentile=50.0,
        nfp_3m_avg=150.0,
    )
    assert as_float(labor_tightness_score(at_middle)) == pytest.approx(0.0, abs=1e-9)

    at_edge = at_middle.model_copy(update={"jolts_quits_level_percentile": 100.0})
    # 0.4 weight * 0.5 multiplier * 50 percentile points = +10.0
    assert as_float(labor_tightness_score(at_edge)) == pytest.approx(10.0, abs=1e-9)


def test_labor_tightness_score_clamps_and_warns() -> None:
    """A composite of unbounded inputs must still land in [-100, +100]."""
    extreme = LaborInputs(
        initial_claims_4wk_avg_change_pct=-500.0,
        jolts_openings_yoy_pct=1000.0,
        jolts_quits_level_percentile=100.0,
        nfp_3m_avg=100000.0,
    )
    result = labor_tightness_score(extreme)
    assert as_float(result) == pytest.approx(100.0, abs=1e-9)
    assert any("clamped" in warning for warning in result.warnings)

    # The floor too, so the clamp is proven two-sided.
    floor = extreme.model_copy(
        update={
            "initial_claims_4wk_avg_change_pct": 500.0,
            "jolts_openings_yoy_pct": -1000.0,
            "jolts_quits_level_percentile": 0.0,
            "nfp_3m_avg": -100000.0,
        }
    )
    assert as_float(labor_tightness_score(floor)) == pytest.approx(-100.0, abs=1e-9)


def test_no_clamp_warning_when_within_range() -> None:
    """The clamp warning must be conditional, or it warns always and is ignored."""
    result = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-0.4,
            jolts_openings_yoy_pct=3.0,
            jolts_quits_level_percentile=60.0,
            nfp_3m_avg=180.0,
        )
    )
    assert not any("clamped" in warning for warning in result.warnings)


def test_labor_tightness_always_warns_about_nfp_weighting() -> None:
    """A reader who sees a strong payroll print must be told to discount it."""
    result = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=0.0,
            jolts_openings_yoy_pct=0.0,
            jolts_quits_level_percentile=50.0,
            nfp_3m_avg=350.0,
        )
    )
    assert any("revised" in warning and "NFP" in warning for warning in result.warnings)


# --------------------------------------------------------------------------
# claims_trend_signal
# --------------------------------------------------------------------------


def test_claims_windows_are_derived_from_one_series() -> None:
    """D-022, guard one: the input carries one series, not two windows.

    The original signature took a weekly series *and* a trailing average, which
    is how a 4-week mean came to be subtracted from a 13-week mean. Taking one
    series makes a caller unable to supply windows that disagree.
    """
    fields = set(ClaimsTrendInputs.model_fields)
    assert fields == {"weekly_initial_claims"}, (
        f"ClaimsTrendInputs must take exactly the raw series; found {fields}. "
        f"A second window field reintroduces D-022."
    )


def test_claims_baseline_is_the_leading_quarter_of_the_window() -> None:
    """D-024: the baseline is the window's FIRST four weeks.

    The baseline must be the leading quarter rather than the window mean,
    because only a full 4-week span disjoint from the latest reading is
    equally smoothed. The pre-D-022 defect divided by the week immediately
    before the latest reading; a later attempt divided by the 13-week mean.
    Neither compares like with like.
    """
    window = _ICSA_13W
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))

    expected_baseline = round(sum(window[:4]) / 4.0, 1)
    assert as_float(result, key="trailing_4wk_avg") == pytest.approx(expected_baseline, abs=1e-9)

    # NOT the mean of the window's last four observations (the pre-D-022 bug),
    # and NOT the window mean (the pre-D-024 shape).
    wrong_recent = sum(window[-4:]) / 4.0
    wrong_mean = _window_mean(window)
    assert wrong_recent != pytest.approx(expected_baseline, abs=1.0), (
        "fixture is degenerate: the leading and trailing quarters coincide, so "
        "this test could pass against the pre-D-022 implementation."
    )
    assert wrong_mean != pytest.approx(expected_baseline, abs=1.0)
    assert as_float(result, key="trailing_4wk_avg") != pytest.approx(wrong_recent, abs=1.0)
    assert as_float(result, key="trailing_4wk_avg") != pytest.approx(wrong_mean, abs=1.0)


def test_claims_current_reading_is_the_latest_quarter_of_the_window() -> None:
    """D-024, guard two: the current reading is the window's LAST 4 weeks.

    Direction of the slice is the whole defect. The window is oldest-first, so
    the latest reading is at the END. Taking the leading quarter as the
    "current" reading reports the state of the market a quarter ago and
    inverts the sign on a trending series.
    """
    window = _ICSA_13W
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))
    assert as_float(result, key="latest_4wk_avg") == pytest.approx(sum(window[-4:]) / 4.0, abs=1e-9)
    assert as_int(result, key="window_weeks") == 13


def test_claims_percent_above_is_consistent_with_the_two_reported_windows() -> None:
    """D-024, guard three: the reported percent must follow from the two windows.

    This is the cross-field identity that a mis-derived window breaks. It is
    the claims analogue of the nominal/real/deflator check: three values that
    must satisfy a relation no mis-slicing can preserve.

    Compared at the *precision the value is reported to*, not at full float
    precision: `pct_above_trailing` is rounded to 3dp as an output convention,
    so recomputing from the two rounded windows cannot reproduce more digits
    than that. Asserting tighter would be testing the rounding.
    """
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=_ICSA_13W))
    latest = as_float(result, key="latest_4wk_avg")
    trailing = as_float(result, key="trailing_4wk_avg")
    expected = (latest - trailing) / trailing
    assert as_float(result, key="pct_above_trailing") == pytest.approx(expected, abs=1e-3)
    # The rounding convention itself, asserted explicitly.
    assert as_float(result, key="pct_above_trailing") == round(expected, 3)


def test_claims_sign_follows_the_direction_of_the_series() -> None:
    """D-024, guard four: the SIGN must match a direction known independently.

    This is the assertion that caught three successive wrong implementations.
    A shape-only test passed all of them. Building a series whose direction is
    known *before* the code runs, and asserting the sign against it, fails
    immediately on any slicing that reports a stale quarter.

    A rising series (deteriorating labor market) must report a POSITIVE percent;
    a falling series (improving) must report a NEGATIVE one.
    """
    rising = [200000.0 * (1.02**index) for index in range(13)]
    falling = [200000.0 * (0.98**index) for index in range(13)]

    rising_result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=rising))
    falling_result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=falling))

    rising_pct = as_float(rising_result, key="pct_above_trailing")
    falling_pct = as_float(falling_result, key="pct_above_trailing")

    assert rising_pct > 0.0, (
        "a rising claims series is a DETERIORATING labor market and must report "
        "a positive reading; a negative value means the comparison is reporting "
        "the prior quarter instead of the current one (D-024). The leading-"
        f"quarter-against-mean slicing produces {rising_pct}."
    )
    assert falling_pct < 0.0, (
        "a falling claims series is an IMPROVING labor market and must report "
        f"a negative reading; got {falling_pct}."
    )
    # The contrast must be substantial, not a marginal sign flip.
    assert as_float(rising_result, key="pct_above_trailing") > 0.05


def test_claims_slow_drift_fails_magnitude_not_persistence() -> None:
    """A sustained but small rise is one of the two noises the rule must reject.

    With the D-024 slicing a uniformly-rising series produces a LARGE percent —
    the whole quarter's drift lands in the difference. To isolate the magnitude
    condition the series must rise, but gently enough that three months of drift
    stays inside the 5% bar, so +0.1%/week compounding to roughly +1.2%.
    """
    settings = get_settings().labor.claims
    threshold = settings.pct_above_trailing

    window = [200000.0 * (1.001**index) for index in range(13)]
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))

    assert as_float(result, key="pct_above_trailing") > 0.0, (
        "the series rises, so the reading must be positive (D-024)"
    )
    assert as_float(result, key="pct_above_trailing") < threshold
    assert as_bool(result, key="magnitude_met") is False
    assert as_bool(result, key="is_signal") is False
    assert "slow drift" in result.interpretation.lower()


def test_claims_single_week_spike_fails_persistence() -> None:
    """A big jump that was not sustained is the other noise the rule must reject.

    The live ICSA run produced a shape where the magnitude cleared the bar and
    the verdict turned on persistence. A rule with only a magnitude test would
    have called it a deterioration.

    The move must be in the **final week only**. A spike sustained for three
    weeks still lifts the 4-week moving average three times in a row and
    satisfies the persistence test — correctly, because a three-week move *is*
    sustained. Only a genuine one-week event fails it.
    """
    # Ten flat weeks, then a jump in the very last week. The moving average
    # rises exactly once, so persistence (3 weeks) is not met; the latest
    # 4-week average is nonetheless far above the leading quarter.
    window = [200000.0] * 12 + [260000.0]
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))
    assert as_int(result, key="consecutive_weeks_rising") == 1
    assert as_bool(result, key="magnitude_met") is True
    assert as_float(result, key="pct_above_trailing") > 0.05
    assert as_bool(result, key="persistence_met") is False
    assert as_bool(result, key="is_signal") is False
    assert "not sustained" in result.interpretation


def test_claims_genuine_deterioration_requires_both_conditions() -> None:
    """The only branch that may return is_signal is both-conditions-met."""
    # A sustained rise over the whole window: every 4-week average is higher
    # than the one before, and the latest quarter sits well above the leading.
    window = [200000.0 * (1.02**index) for index in range(13)]
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))
    settings = get_settings().labor.claims
    assert as_int(result, key="consecutive_weeks_rising") >= settings.consecutive_weeks
    assert as_float(result, key="pct_above_trailing") > settings.pct_above_trailing
    assert as_bool(result, key="persistence_met") is True
    assert as_bool(result, key="magnitude_met") is True
    assert as_bool(result, key="is_signal") is True
    assert "GENUINE" in result.interpretation


def test_claims_slow_drift_branch_states_direction_when_below_baseline() -> None:
    """D-023: the wording must not say "only X above" when X is negative.

    The pre-fix string read "the LEVEL is only -3.1% above the trailing
    average, below the 5.0% bar" — "only ... above" alongside a negative sign
    and a directional "below". A reader skimming it draws the wrong conclusion
    about direction, and direction in a nowcast is the whole message.
    """
    # Falling overall, so the latest quarter is BELOW the prior quarter, but
    # with the last weeks ticking up to reach the persistence branch.
    window = [
        210000.0,
        210000.0,
        209000.0,
        208000.0,
        206000.0,
        204000.0,
        202000.0,
        200000.0,
        199000.0,
        199000.0,
        200000.0,
        202000.0,
        204000.0,
    ]
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))
    assert as_float(result, key="pct_above_trailing") < 0.0, (
        "fixture must produce a negative reading for this test to bite"
    )
    interpretation = result.interpretation
    assert "below" in interpretation.lower()
    # The contradictory construction must be gone.
    assert "only -" not in interpretation
    assert "only +-" not in interpretation


def test_claims_identity_holds_across_signs() -> None:
    """The cross-field identity must hold for rises, falls and a flat series."""
    for scale in (0.98, 1.0, 1.02):
        window = [200000.0 * (scale**index) for index in range(13)]
        result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))
        latest = as_float(result, key="latest_4wk_avg")
        trailing = as_float(result, key="trailing_4wk_avg")
        assert as_float(result, key="pct_above_trailing") == pytest.approx(
            (latest - trailing) / trailing, abs=1e-3
        )


def test_claims_flat_series_produces_no_signal() -> None:
    """A perfectly flat series is the zero case: no rise, no magnitude."""
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=[200000.0] * 13))
    assert as_float(result, key="pct_above_trailing") == pytest.approx(0.0, abs=1e-9)
    assert as_int(result, key="consecutive_weeks_rising") == 0
    assert as_bool(result, key="magnitude_met") is False
    assert as_bool(result, key="is_signal") is False


def test_claims_magnitude_threshold_is_strictly_greater_than() -> None:
    """The magnitude bar is exclusive: exactly at the threshold is NOT met.

    Found by mutation testing. Changing ``>`` to ``>=`` on the magnitude
    comparison survived the entire suite, which means no test pinned the
    boundary. Section 22.4's ``is_meaningful`` uses the same strictly-greater
    convention, so this is a project-wide rule and needs its own assertion.

    The fixture lands exactly on the threshold: nine flat weeks at 200,000
    (so the leading quarter is 200,000), then four weeks at
    200,000 * (1 + threshold), so the latest quarter sits exactly at the bar.
    """
    threshold = get_settings().labor.claims.pct_above_trailing
    target_latest = 200000.0 * (1.0 + threshold)

    window = [200000.0] * 9 + [target_latest] * 4
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))

    assert as_float(result, key="latest_4wk_avg") == pytest.approx(target_latest, abs=1e-6)
    assert as_float(result, key="trailing_4wk_avg") == pytest.approx(200000.0, abs=1e-6)
    # Exactly at the bar: must NOT be met, because the comparison is strict.
    assert as_float(result, key="pct_above_trailing") == pytest.approx(
        round(threshold, 3), abs=1e-3
    )
    assert as_bool(result, key="magnitude_met") is False, (
        f"a reading exactly at the {threshold:.1%} threshold must not satisfy a "
        f"strictly-greater comparison"
    )

    # And just above it must be met, so the assertion cannot pass merely by
    # never firing.
    above = [200000.0] * 9 + [200000.0 * (1.0 + threshold * 1.10)] * 4
    above_result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=above))
    assert as_bool(above_result, key="magnitude_met") is True


def test_claims_rejects_a_short_series() -> None:
    """13 weeks is the minimum the window requires; 12 must be rejected.

    The rejection happens at the *contract* boundary — ``min_length=13`` on the
    field — rather than inside the function, which is the right layer for it:
    an input that cannot satisfy the model's definition should not be
    constructible. The in-function guard exists for callers that bypass the
    model (raw dicts, deserialised payloads), so both are tested.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="at least 13 items"):
        ClaimsTrendInputs(weekly_initial_claims=[200000.0] * 12)


def test_claims_function_guard_covers_a_bypassed_contract() -> None:
    """The in-function guard must hold even if the model is bypassed."""
    short = ClaimsTrendInputs.model_construct(weekly_initial_claims=[200000.0] * 12)
    with pytest.raises(ValueError, match="At least 13 weekly observations"):
        claims_trend_signal(short)


def test_claims_rejects_non_positive_levels() -> None:
    """A zero or negative level makes the percent comparison undefined."""
    window = [200000.0] * 12 + [0.0]
    with pytest.raises(ValueError, match="must be positive"):
        claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=window))


def test_claims_ignores_earlier_history_without_error() -> None:
    """A longer series is accepted; only its last 13 weeks form the window.

    A caller holding a full FRED history should not have to slice it, and
    slicing it wrongly is precisely how D-022 arose.
    """
    long_series = [300000.0] * 40 + _ICSA_13W
    from_long = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=long_series))
    from_window = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=_ICSA_13W))
    assert as_float(from_long, key="trailing_4wk_avg") == as_float(
        from_window, key="trailing_4wk_avg"
    )
    assert as_float(from_long, key="latest_4wk_avg") == as_float(from_window, key="latest_4wk_avg")
    assert as_int(from_long, key="window_weeks") == 13


def test_claims_confidence_is_equal_in_both_branches() -> None:
    """Uncalibrated thresholds do not become better-evidenced by turning positive.

    A confidence that rose with severity would make the model's most alarming
    reading also its most confident one.
    """
    spiking = [240000.0, 238000.0, 236000.0, 234000.0] + [200000.0] * 9
    calm = [200000.0] * 13
    spiking_result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=spiking))
    calm_result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=calm))
    assert as_bool(spiking_result, key="is_signal") is False
    assert as_bool(calm_result, key="is_signal") is False
    assert spiking_result.confidence == calm_result.confidence


def test_claims_always_discloses_uncalibrated_thresholds() -> None:
    result = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=_ICSA_13W))
    assert any("Phase 5+" in warning for warning in result.warnings)


# --------------------------------------------------------------------------
# claims_corroboration
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("initial", "continuing", "expected"),
    [
        (True, True, "genuine_downturn_signal"),
        (True, False, "churn_not_downturn"),
        (False, True, "no_signal"),
        (False, False, "no_signal"),
    ],
)
def test_claims_corroboration_verdicts(initial: bool, continuing: bool, expected: str) -> None:
    """All four input combinations, including the two that collapse together.

    ``no_signal`` is reachable two ways and deliberately not distinguished:
    without a deterioration in initial claims there is nothing to corroborate,
    and whether continuing claims happen to be rising is not evidence either
    way. Reporting those as one verdict rather than two is the point.
    """
    result = claims_corroboration(
        ClaimsCorroborationInputs(
            initial_claims_signal=initial, continuing_claims_rising=continuing
        )
    )
    assert result.value == expected


def test_claims_corroboration_confidence_is_identical_across_branches() -> None:
    """Three boolean verdicts are not better evidenced because one is alarming.

    Asserted as a set of one, not as pairwise equality against a reference:
    a pairwise test would pass if two branches agreed and the third differed,
    which is the failure mode this guards.
    """
    confidences = {
        claims_corroboration(
            ClaimsCorroborationInputs(
                initial_claims_signal=initial, continuing_claims_rising=continuing
            )
        ).confidence
        for initial in (True, False)
        for continuing in (True, False)
    }
    assert len(confidences) == 1, (
        f"confidence must not vary with the verdict's severity; saw {confidences}"
    )


def test_claims_corroboration_explains_the_churn_distinction() -> None:
    """The churn branch must say WHY it is not a downturn, not just that it isn't."""
    churn = claims_corroboration(
        ClaimsCorroborationInputs(initial_claims_signal=True, continuing_claims_rising=False)
    )
    assert "re-employment" in churn.context or "between jobs" in churn.context
    # And must disclose the publication-lag caveat, since continuing claims
    # arrive a week later and a fresh deterioration may not yet show.
    assert any("lagging" in warning or "delay" in warning for warning in churn.warnings)


def test_claims_corroboration_no_signal_is_not_evidence_of_stability() -> None:
    """Absence of evidence is stated as such, not read as a healthy labor market."""
    none_result = claims_corroboration(
        ClaimsCorroborationInputs(initial_claims_signal=False, continuing_claims_rising=False)
    )
    assert "absence of evidence" in none_result.context


# --------------------------------------------------------------------------
# inflation_breadth_score
# --------------------------------------------------------------------------


def test_inflation_breadth_convergent_when_all_positive() -> None:
    """Hand calculation: (0.2 + 0.3 + 0.1) / 3 = +0.2."""
    result = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
    )
    assert result.value == pytest.approx(0.2, abs=1e-9)
    assert "Convergent" in result.interpretation
    assert "rising" in result.interpretation


def test_inflation_breadth_convergent_when_all_negative() -> None:
    """The sign test is two-sided: all-falling is convergence too."""
    result = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=-0.2, cpi_core_mom=-0.3, pce_core_mom=-0.1)
    )
    assert result.value == pytest.approx(-0.2, abs=1e-9)
    assert "Convergent" in result.interpretation
    assert "falling" in result.interpretation


def test_inflation_breadth_divergent_when_signs_mixed() -> None:
    result = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=-0.1)
    )
    assert "Divergent" in result.interpretation
    assert any("investigate" in warning for warning in result.warnings)


def test_inflation_breadth_confidence_follows_convergence() -> None:
    """Convergent must not be scored below divergent — it is the stronger reading."""
    breadth = get_settings().inflation.breadth
    convergent = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
    )
    divergent = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=-0.1)
    )
    assert convergent.confidence == breadth.convergent
    assert divergent.confidence == breadth.divergent
    assert convergent.confidence > divergent.confidence


def test_inflation_breadth_is_a_sign_test_and_says_so() -> None:
    """Three measures at +0.01% must read as convergent; the disclosure is what
    stops that from being mistaken for evidence of breadth."""
    tiny = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.01, cpi_core_mom=0.01, pce_core_mom=0.01)
    )
    assert "Convergent" in tiny.interpretation
    assert any("SIGN test" in warning or "sign test" in warning for warning in tiny.warnings)
    assert any("Phase 5+" in warning for warning in tiny.warnings)


def test_inflation_breadth_average_is_reported_for_magnitude_context() -> None:
    """The sign test hides magnitude, so the average must be readable.

    Divergent readings are averaged anyway (a limitation, not a feature); the
    interpretation must show the number so a reader can judge whether the
    average describes anything.
    """
    result = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.5, cpi_core_mom=0.4, pce_core_mom=-0.45)
    )
    assert result.value == pytest.approx(0.15, abs=1e-9)
    assert "+0.15" in result.interpretation


# --------------------------------------------------------------------------
# Shared contract conformance
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        labor_tightness_score(
            LaborInputs(
                initial_claims_4wk_avg_change_pct=-0.4,
                jolts_openings_yoy_pct=3.0,
                jolts_quits_level_percentile=60.0,
                nfp_3m_avg=180.0,
            )
        ),
        claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=_ICSA_13W)),
        claims_corroboration(
            ClaimsCorroborationInputs(initial_claims_signal=True, continuing_claims_rising=False)
        ),
        inflation_breadth_score(
            InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
        ),
    ],
)
def test_every_module_6_result_conforms_to_the_contract(result: ModelResult) -> None:
    """Section 22.9's value union, and the fields every result must carry."""
    assert isinstance(result, ModelResult)
    assert result.country == "us"
    assert result.as_of.tzinfo is not None
    assert result.as_of.utcoffset() is not None
    assert 0.0 <= result.confidence <= 1.0
    assert result.interpretation
    assert result.context
    assert result.inputs_used
    assert result.warnings

    allowed = (float, int, str, bool, dict, list, type(None))
    assert isinstance(result.value, allowed), f"unexpected value type {type(result.value)}"
    if isinstance(result.value, float):
        assert math.isfinite(result.value)
