"""Hand-computed verification tests for models/yield_curve.py.

Config values (config/settings.yaml::yield_curve) used below:
  depth_saturation_bp       = 100.0
  duration_saturation_cap    = 26.0   (property duration_cap_weeks)
  max_adjustment            = 0.35    (property max_probability_adjustment)
  probability_ceiling       = 0.80    (property ceiling)
  confidence base/penalties: 0.70 - 0.20 (heuristic) - 0.20 (unobservable)
"""

from __future__ import annotations

import pytest

from macro_engine.models.contracts import ConfidenceInputs
from macro_engine.models.yield_curve import (
    BreakevenInputs,
    CurveDecompositionInputs,
    CurveSlopeInputs,
    InversionHistoryInputs,
    breakeven_inflation,
    curve_slope,
    decompose_yield,
    inversion_probability_adjustment,
)


# ---------------------------------------------------------------------------
# curve_slope — units and sign (LAW 3)
# ---------------------------------------------------------------------------
def test_curve_slope_inverted_gives_negative_bp():
    # 10yr 4.05, 2yr 4.25 -> (4.05 - 4.25)*100 = -20.0 bp, inverted
    out = curve_slope(CurveSlopeInputs(tenors={"2yr": 4.25, "10yr": 4.05}))
    assert out.value == pytest.approx(-20.0)
    assert "inverted" in out.direction


def test_curve_slope_normal_positive_bp():
    out = curve_slope(CurveSlopeInputs(tenors={"2yr": 4.0, "10yr": 4.5}))
    assert out.value == pytest.approx(50.0)
    assert out.direction.startswith("normal")


def test_curve_slope_flat_is_zero():
    out = curve_slope(CurveSlopeInputs(tenors={"2yr": 4.0, "10yr": 4.0}))
    assert out.value == pytest.approx(0.0)
    assert out.direction.startswith("flat")


def test_curve_slope_rejects_missing_tenor():
    with pytest.raises(KeyError):
        curve_slope(CurveSlopeInputs(tenors={"2yr": 4.0}, short="2yr", long="10yr"))


def test_curve_slope_rejects_equal_tenors():
    with pytest.raises(ValueError):
        curve_slope(CurveSlopeInputs(tenors={"2yr": 4.0}, short="2yr", long="2yr"))


# ---------------------------------------------------------------------------
# breakeven_inflation — nominal minus TIPS real
# ---------------------------------------------------------------------------
def test_breakeven_is_nominal_minus_real():
    # 4.25 - 1.75 = 2.50
    out = breakeven_inflation(BreakevenInputs(nominal=4.25, tips_real=1.75, tenor="10yr"))
    assert out.value == pytest.approx(2.50)
    # arithmetic only -> confidence 0.70
    assert out.confidence == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# decompose_yield — nominal = expectations + term premium
# ---------------------------------------------------------------------------
def test_decompose_with_term_premium_subtracts():
    out = decompose_yield(
        CurveDecompositionInputs(nominal_yield=4.25, term_premium=0.4, tenor="10yr")
    )
    assert out.value["expectations_component"] == pytest.approx(3.85)
    assert out.value["term_premium"] == pytest.approx(0.4)
    assert out.confidence == pytest.approx(0.50)  # depends_on_unobservable


def test_decompose_without_term_premium_returns_raw_with_warning():
    out = decompose_yield(CurveDecompositionInputs(nominal_yield=4.25, term_premium=None, tenor="10yr"))
    assert out.value["expectations_component"] is None
    assert out.value["term_premium"] is None
    assert any("NO TERM PREMIUM" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# inversion_probability_adjustment — depth * duration * max, capped
# ---------------------------------------------------------------------------
def test_inversion_adjustment_hand_computed():
    # slope -50bp, 13 weeks, base 0.209
    # depth_factor = min(50/100,1)=0.5 ; duration_factor = min(13/26,1)=0.5
    # adjustment = 0.35 * 0.5 * 0.5 = 0.0875
    # uncapped = 0.209 + 0.0875 = 0.2965 ; ceiling 0.80 -> not binding
    inp = InversionHistoryInputs(
        current_slope_bp=-50.0, weeks_inverted=13, base_rate_recession_prob_12mo=0.209
    )
    out = inversion_probability_adjustment(inp)
    assert out.value["depth_factor"] == pytest.approx(0.5)
    assert out.value["duration_factor"] == pytest.approx(0.5)
    assert out.value["adjustment"] == pytest.approx(0.0875)
    assert out.value["adjusted_probability"] == pytest.approx(0.2965)
    assert out.value["ceiling_binding"] is False
    assert out.value["saturated"] is False
    assert out.confidence == pytest.approx(0.50)  # heuristic placeholder


def test_inversion_adjustment_ceiling_binds_when_saturated():
    # slope -200bp, 52 weeks -> both factors saturate at 1.0
    # adjustment = 0.35 ; uncapped = 0.489 + 0.35 = 0.839 ; ceiling 0.80 binds
    inp = InversionHistoryInputs(
        current_slope_bp=-200.0, weeks_inverted=52, base_rate_recession_prob_12mo=0.489
    )
    out = inversion_probability_adjustment(inp)
    assert out.value["depth_factor"] == pytest.approx(1.0)
    assert out.value["duration_factor"] == pytest.approx(1.0)
    assert out.value["adjustment"] == pytest.approx(0.35)
    assert out.value["adjusted_probability"] == pytest.approx(0.80)
    assert out.value["ceiling_binding"] is True
    assert out.value["saturated"] is True


def test_inversion_adjustment_not_inverted_returns_base():
    # positive slope -> no adjustment; weeks_inverted must be 0 (validator)
    inp = InversionHistoryInputs(
        current_slope_bp=20.0, weeks_inverted=0, base_rate_recession_prob_12mo=0.209
    )
    out = inversion_probability_adjustment(inp)
    assert out.value["adjusted_probability"] == pytest.approx(0.209)
    assert out.value["adjustment"] == pytest.approx(0.0)


def test_inversion_adjustment_rejects_stale_duration():
    with pytest.raises(ValueError):
        InversionHistoryInputs(
            current_slope_bp=20.0, weeks_inverted=5, base_rate_recession_prob_12mo=0.209
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
