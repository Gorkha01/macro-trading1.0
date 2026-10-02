"""Hand-computed verification tests for models/ppi_pipeline.py (Module 5.4).

Config (config/settings.yaml, verified by hand):
  inflation.pipeline_gradient_tolerance   = 0.1  (dead band, pp)
  inflation.pipeline_base_rate.strict_descending = 0.3
  inflation.pipeline_base_rate.crude_above_final = 0.442
Confidence = compute_confidence(is_heuristic_not_calibrated=True,
depends_on_unobservable=True) = 0.70 - 0.20 - 0.20 = 0.30.

Logic: upstream_building = crude > intermediate > final (spec's test, unchanged).
within_band = |crude-inter|<=0.1 AND |inter-final|<=0.1.
gradient_direction: within_band -> building_within_tolerance (if building) else
flat_within_tolerance; elif building -> building_upstream; elif crude<inter<final
-> passing_through_downstream; else non_monotonic.
pass_through = "muted" if demand=="weak" or margin=="compressing" else "fuller"
(depends ONLY on the two assessments, never on the gradient).
"""

from __future__ import annotations

import pytest

from macro_engine.models.ppi_pipeline import PPIPipelineInputs, ppi_pipeline_signal


def _ppi(**kw) -> PPIPipelineInputs:
    base = dict(
        crude_stage_yoy_pct=13.06,
        intermediate_stage_yoy_pct=11.53,
        final_demand_yoy_pct=5.41,
        corporate_margin_trend="expanding",
        demand_condition="neutral",
    )
    base.update(kw)
    return PPIPipelineInputs(**base)


def test_building_upstream():
    res = ppi_pipeline_signal(_ppi())
    assert res.value["upstream_pressure_building"] is True
    assert res.value["gradient_direction"] == "building_upstream"
    assert res.value["stage_spread_pp"] == pytest.approx(7.65)  # 13.06 - 5.41
    # demand neutral + margin expanding -> not absorbing -> fuller
    assert res.value["expected_pass_through"] == "fuller"
    assert res.value["base_rate_strict_descending"] == pytest.approx(0.3)
    assert res.value["base_rate_crude_above_final"] == pytest.approx(0.442)
    assert res.confidence == 0.30


def test_passing_through_downstream():
    res = ppi_pipeline_signal(_ppi(crude_stage_yoy_pct=1.0, intermediate_stage_yoy_pct=2.0, final_demand_yoy_pct=3.0, demand_condition="weak"))
    assert res.value["upstream_pressure_building"] is False
    assert res.value["gradient_direction"] == "passing_through_downstream"
    assert res.value["stage_spread_pp"] == pytest.approx(-2.0)
    # weak demand -> absorbing -> muted (pass-through ignores the gradient)
    assert res.value["expected_pass_through"] == "muted"


def test_building_within_tolerance():
    # strictly ordered but tiny gaps -> within band
    res = ppi_pipeline_signal(_ppi(crude_stage_yoy_pct=2.06, intermediate_stage_yoy_pct=2.05, final_demand_yoy_pct=2.04))
    assert res.value["upstream_pressure_building"] is True
    assert res.value["gradient_direction"] == "building_within_tolerance"


def test_flat_within_tolerance():
    res = ppi_pipeline_signal(_ppi(crude_stage_yoy_pct=2.0, intermediate_stage_yoy_pct=2.0, final_demand_yoy_pct=2.0))
    assert res.value["upstream_pressure_building"] is False
    assert res.value["gradient_direction"] == "flat_within_tolerance"


def test_non_monotonic():
    res = ppi_pipeline_signal(_ppi(crude_stage_yoy_pct=3.0, intermediate_stage_yoy_pct=1.0, final_demand_yoy_pct=2.0))
    assert res.value["upstream_pressure_building"] is False
    assert res.value["gradient_direction"] == "non_monotonic"


def test_pass_through_ignores_gradient_margin_compressing():
    # building gradient but margin compressing -> muted (absorption overrides)
    res = ppi_pipeline_signal(_ppi(corporate_margin_trend="compressing", demand_condition="strong"))
    assert res.value["upstream_pressure_building"] is True
    assert res.value["expected_pass_through"] == "muted"
