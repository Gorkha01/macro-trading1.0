"""Fresh, self-verifying tests for macro_engine.models.labor_synthesis.

Written during the line-by-line review campaign. Every arithmetic value is
derived by hand from the Section 6 config leaves (see the module docstrings and
config/settings.yaml) so the tests are independent of the implementation and
would catch a regression in either the formula OR the config wiring.

Key config (config/settings.yaml -> labor.*):
  tightness_weights:    claims 0.4, jolts 0.4, nfp 0.2   (sum = 1.0)
  tightness_scaling:    claims_multiplier -2.0 (INVERTS the sign),
                        jolts_openings_multiplier 0.5,
                        jolts_quits_multiplier 0.5, quits_centering 50.0,
                        nfp_divisor 10.0
  neutral_nfp_pace      150.0
  claims:               consecutive_weeks 3, pct_above_trailing 0.05
  beveridge tolerance   0.5pp  (read live in tests)
  revisions:            misleading_net -50.0
  ahe_distortion:       low_wage_decline -1.0, eci_divergence 0.75
"""

import math

import pytest

from macro_engine.config import get_settings
from macro_engine.models.labor_synthesis import (
    AHEDistortionInputs,
    BeveridgeInputs,
    ClaimsCorroborationInputs,
    ClaimsTrendInputs,
    InflationSubMeasures,
    LaborInputs,
    RevisionInputs,
    TwoSurveyInputs,
    ahe_composition_flag,
    beveridge_curve_position,
    claims_corroboration,
    claims_trend_signal,
    inflation_breadth_score,
    labor_tightness_score,
    nfp_revision_adjusted_read,
    two_survey_divergence,
)


# --------------------------------------------------------------------------
# labor_tightness_score
# --------------------------------------------------------------------------
def test_labor_tightness_known_value_section_6_4() -> None:
    """Hand calc from the docstring: score must be +3.5."""
    res = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-0.4,
            jolts_openings_yoy_pct=3.0,
            jolts_quits_level_percentile=60.0,
            nfp_3m_avg=180.0,
        )
    )
    # claims = -2.0 * -0.4 = 0.8; jolts = 0.5*3 + 0.5*(60-50) = 6.5;
    # nfp = (180-150)/10 = 3.0; raw = 0.4*0.8 + 0.4*6.5 + 0.2*3.0 = 3.52
    assert res.value == pytest.approx(3.5, abs=1e-9)
    assert (res.direction or "").startswith("tightening")
    assert "tightening" in res.interpretation


def test_labor_tightness_small_positive_scores_as_balanced_not_tightening() -> None:
    """F-LAB-001 regression: a score in (0, 0.05) rounds to value 0.0. It must
    NOT publish a tightening direction — 0.0 means 'at the balanced level'."""
    res = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-0.05,  # claims_component = +0.1
            jolts_openings_yoy_pct=0.0,
            jolts_quits_level_percentile=50.0,
            nfp_3m_avg=150.0,
        )
    )
    # raw = 0.4 * (-2.0 * -0.05) = 0.04 -> rounds to 0.0
    assert res.value == 0.0
    # Direction and interpretation MUST agree with the published value: neutral.
    assert res.direction == "neutral: at the balanced level"
    assert "neutral" in res.interpretation


def test_labor_tightness_zero_is_consistent_across_fields() -> None:
    """F-LAB-001 regression: exactly-balanced inputs must not leak a 'loosening'
    interpretation next to a 'neutral' direction (the 3-state vs 2-state split
    that disagreed on the -0.0 case)."""
    res = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=0.0,
            jolts_openings_yoy_pct=0.0,
            jolts_quits_level_percentile=50.0,
            nfp_3m_avg=150.0,
        )
    )
    assert res.value == 0.0
    assert res.direction == "neutral: at the balanced level"
    assert "neutral" in res.interpretation
    # The sign word used in the interpretation must match the direction sentence.
    assert "loosening" not in res.interpretation


def test_labor_tightness_clamps_at_ceiling_and_floor() -> None:
    high = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-100.0,
            jolts_openings_yoy_pct=1000.0,
            jolts_quits_level_percentile=100.0,
            nfp_3m_avg=500.0,
        )
    )
    assert high.value == 100.0
    assert (high.direction or "").startswith("tightening")

    low = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=100.0,
            jolts_openings_yoy_pct=-1000.0,
            jolts_quits_level_percentile=0.0,
            nfp_3m_avg=-500.0,
        )
    )
    assert low.value == -100.0
    assert (low.direction or "").startswith("loosening")


def test_labor_tightness_rejects_nan_inputs() -> None:
    """FiniteInputs must refuse non-finite inputs rather than publish nan."""

    with pytest.raises(ValueError):
        labor_tightness_score(
            LaborInputs(
                initial_claims_4wk_avg_change_pct=float("nan"),
                jolts_openings_yoy_pct=3.0,
                jolts_quits_level_percentile=60.0,
                nfp_3m_avg=180.0,
            )
        )


# --------------------------------------------------------------------------
# claims_trend_signal
# --------------------------------------------------------------------------
def _weekly(rising_tail: int, base: float = 200.0, n: int = 13) -> list[float]:
    """Build an n-week oldest-first series. `rising_tail` weeks at the end are
    ramped up so the 4-wk MA is sustained-rising and the latest 4-wk mean
    clearly exceeds the trailing baseline."""
    series = [base] * n
    for i in range(rising_tail):
        series[-(i + 1)] = base * 1.10  # ~+10% at the end
    return series


def test_claims_trend_signal_detects_sustained_deterioration() -> None:
    weekly = _weekly(rising_tail=4)
    res = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=weekly))
    v = res.value_dict()
    assert v["persistence_met"] is True
    assert v["magnitude_met"] is True
    assert v["is_signal"] is True
    assert v["consecutive_weeks_rising"] >= 3


def test_claims_trend_signal_one_week_spike_is_not_signal() -> None:
    weekly = [200.0] * 12 + [260.0]  # single spike, no sustained rise
    res = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=weekly))
    v = res.value_dict()
    assert v["magnitude_met"] is True
    assert v["persistence_met"] is False
    assert v["is_signal"] is False


def test_claims_trend_signal_rejects_short_series() -> None:
    with pytest.raises(ValueError):
        claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=[200.0] * 12))


def test_claims_trend_signal_rejects_nonpositive() -> None:
    with pytest.raises(ValueError):
        claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=[200.0] * 12 + [0.0]))


def test_claims_trend_signal_pct_above_trailing_not_negative_zero() -> None:
    """F-LAB-003: a near-flat reading must not publish -0.0%."""
    weekly = [200.0001] * 9 + [200.0] * 4  # latest 4 slightly below baseline
    res = claims_trend_signal(ClaimsTrendInputs(weekly_initial_claims=weekly))
    pct = res.value_dict()["pct_above_trailing"]
    # F-LAB-003: a near-flat reading must not publish a negative-zero artifact.
    assert not (math.copysign(1.0, pct) < 0 and pct == 0.0), (
        f"negative-zero pct_above_trailing: {pct!r}"
    )


# --------------------------------------------------------------------------
# claims_corroboration
# --------------------------------------------------------------------------
def test_claims_corroboration_genuine_downturn() -> None:
    res = claims_corroboration(
        ClaimsCorroborationInputs(initial_claims_signal=True, continuing_claims_rising=True)
    )
    assert res.value == "genuine_downturn_signal"


def test_claims_corroboration_churn() -> None:
    res = claims_corroboration(
        ClaimsCorroborationInputs(initial_claims_signal=True, continuing_claims_rising=False)
    )
    assert res.value == "churn_not_downturn"


def test_claims_corroboration_no_signal() -> None:
    res = claims_corroboration(
        ClaimsCorroborationInputs(initial_claims_signal=False, continuing_claims_rising=True)
    )
    assert res.value == "no_signal"


# --------------------------------------------------------------------------
# two_survey_divergence
# --------------------------------------------------------------------------
def test_two_survey_participation_driven() -> None:
    res = two_survey_divergence(
        TwoSurveyInputs(
            nfp_change_thousands=200.0,
            household_employment_change_thousands=150.0,
            unemployment_rate_change_pp=0.1,
            participation_rate_change_pp=0.2,
        )
    )
    assert res.value == "PARTICIPATION_DRIVEN_not_weakness"


def test_two_survey_genuine_divergence() -> None:
    res = two_survey_divergence(
        TwoSurveyInputs(
            nfp_change_thousands=200.0,
            household_employment_change_thousands=150.0,
            unemployment_rate_change_pp=0.1,
            participation_rate_change_pp=-0.1,
        )
    )
    assert res.value == "GENUINE_DIVERGENCE_investigate"


def test_two_survey_broad_weakening() -> None:
    res = two_survey_divergence(
        TwoSurveyInputs(
            nfp_change_thousands=-100.0,
            household_employment_change_thousands=-80.0,
            unemployment_rate_change_pp=0.2,
            participation_rate_change_pp=0.0,
        )
    )
    assert res.value == "BROAD_WEAKENING"


def test_two_survey_consistent_strength() -> None:
    res = two_survey_divergence(
        TwoSurveyInputs(
            nfp_change_thousands=200.0,
            household_employment_change_thousands=150.0,
            unemployment_rate_change_pp=-0.1,
            participation_rate_change_pp=0.1,
        )
    )
    assert res.value == "CONSISTENT_STRENGTH"
    assert "Payrolls rose" in res.interpretation


def test_two_survey_consistent_weakness_is_not_strength() -> None:
    """F-LAB-002 regression: payrolls DOWN and unemployment DOWN must NOT be
    reported as CONSISTENT_STRENGTH with a false 'Payrolls rose' claim. It is a
    distinct CONSISTENT_WEAKNESS verdict whose wording is accurate."""
    res = two_survey_divergence(
        TwoSurveyInputs(
            nfp_change_thousands=-100.0,
            household_employment_change_thousands=-80.0,
            unemployment_rate_change_pp=-0.2,
            participation_rate_change_pp=-0.2,
        )
    )
    assert res.value == "CONSISTENT_WEAKNESS"
    assert "Payrolls rose" not in res.interpretation
    assert "fell" in res.interpretation


# --------------------------------------------------------------------------
# beveridge_curve_position
# --------------------------------------------------------------------------
def test_beveridge_outward_shift() -> None:
    tol = get_settings().beveridge.shift_tolerance_pp
    hist = 4.8
    res = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=hist + tol + 0.2,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=hist,
        )
    )
    assert res.value_dict()["verdict"] == "OUTWARD_SHIFT_structural_mismatch"
    assert res.value_dict()["shift_pp"] > tol


def test_beveridge_on_curve() -> None:
    hist = 4.8
    res = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=hist,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=hist,
        )
    )
    assert res.value_dict()["verdict"] == "ON_CURVE_cyclical"
    assert res.value_dict()["shift_pp"] == pytest.approx(0.0, abs=1e-9)


def test_beveridge_inward_shift() -> None:
    tol = get_settings().beveridge.shift_tolerance_pp
    hist = 4.8
    res = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=hist - tol - 0.2,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=hist,
        )
    )
    assert res.value_dict()["verdict"] == "INWARD_SHIFT_improved_matching"
    assert res.value_dict()["shift_pp"] < -tol


# --------------------------------------------------------------------------
# ahe_composition_flag
# --------------------------------------------------------------------------
def test_ahe_distortion_flagged() -> None:
    res = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=8.0,
            eci_growth_yoy_pct=2.5,
            low_wage_sector_employment_change_pct=-12.0,
        )
    )
    assert res.value_dict()["distortion_flagged"] is True
    assert res.value_dict()["ahe_minus_eci_pp"] == pytest.approx(5.5, abs=1e-9)


def test_ahe_no_distortion() -> None:
    res = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=3.5,
            eci_growth_yoy_pct=3.3,
            low_wage_sector_employment_change_pct=1.2,
        )
    )
    assert res.value_dict()["distortion_flagged"] is False


def test_ahe_distortion_eci_unavailable() -> None:
    res = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=8.0,
            eci_growth_yoy_pct=None,
            low_wage_sector_employment_change_pct=-12.0,
        )
    )
    assert res.value_dict()["distortion_flagged"] is True
    assert res.value_dict()["ahe_minus_eci_pp"] is None


# --------------------------------------------------------------------------
# nfp_revision_adjusted_read
# --------------------------------------------------------------------------
def test_nfp_revision_misleading_headline() -> None:
    res = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=250.0,
            prior_month_revision=-120.0,
            two_months_ago_revision=-80.0,
        )
    )
    assert res.value_dict()["net_revisions"] == pytest.approx(-200.0, abs=1e-9)
    assert res.value_dict()["revision_adjusted"] == pytest.approx(50.0, abs=1e-9)
    # A positive headline with large net downward revisions must raise the
    # "masked" warning (the misleading read is conveyed via warnings).
    assert any("masked" in w.lower() for w in res.warnings)


def test_nfp_revision_negative_headline_not_misleading() -> None:
    res = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=-100.0,
            prior_month_revision=-50.0,
            two_months_ago_revision=-50.0,
        )
    )
    assert res.value_dict()["net_revisions"] == pytest.approx(-100.0, abs=1e-9)
    assert res.value_dict()["revision_adjusted"] == pytest.approx(-200.0, abs=1e-9)
    # Negative headline + negative revisions is NOT a misleading beat; the
    # "masked" warning must be absent.
    assert not any("masked" in w.lower() for w in res.warnings)


# --------------------------------------------------------------------------
# inflation_breadth_score
# --------------------------------------------------------------------------
def test_inflation_breadth_convergent_rising() -> None:
    res = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
    )
    assert res.value == pytest.approx(0.2, abs=1e-9)
    assert (res.direction or "").startswith("rising")


def test_inflation_breadth_divergent() -> None:
    res = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=-0.1, pce_core_mom=0.1)
    )
    assert (res.direction or "").startswith("CONFLICTED")
    assert res.value == pytest.approx(0.0667, abs=1e-4)


def test_inflation_breadth_flat() -> None:
    res = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.0, cpi_core_mom=0.0, pce_core_mom=0.0)
    )
    assert res.value == 0.0
    assert (res.direction or "").startswith("flat")


def test_inflation_breadth_one_sign_with_zeros() -> None:
    res = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.0, pce_core_mom=0.0)
    )
    assert (res.direction or "").startswith("convergent")
    assert res.value == pytest.approx(0.0667, abs=1e-4)


def test_inflation_breadth_value_not_negative_zero() -> None:
    """F-LAB-003: an offsetting set of tiny readings must not publish -0.0."""
    res = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.001, cpi_core_mom=0.001, pce_core_mom=-0.002)
    )
    val = res.value_float()
    assert not (math.copysign(1.0, val) < 0 and val == 0.0)
