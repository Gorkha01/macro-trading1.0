"""Hand-computed verification tests for models/credit_spread.py (Module 8.3).

Thresholds from config/settings.yaml (verified by hand):
  equity_vol_spike_threshold_pct = 20.0   (technical if vol change > 20.0)
  differentiation_threshold_bp    = 5.0    (diagnostic only: parallel if |HY-IG| <= 5)
  change_window_days             = 5
Both decision thresholds are uncalibrated_illustrative -> confidence = 0.50.

Logic under test:
  fundamental      = default_rate_trend == "rising"
  technical        = equity_vol_change_pct > 20.0        (NOT ANDed with trend anymore)
  widening         = hy_spread_change_bp > 0.0
  FUNDAMENTAL / TECHNICAL / BOTH / UNCLEAR / NO_WIDENING  (all five reachable)
"""

from __future__ import annotations

import pytest

from macro_engine.models.credit_spread import CreditSpreadInputs, credit_spread_attribution


def _cs(**kw) -> CreditSpreadInputs:
    base = dict(
        hy_spread_bp=400.0,
        hy_spread_change_bp=20.0,
        ig_spread_change_bp=15.0,
        equity_vol_change_pct=5.0,
        default_rate_trend="stable",
    )
    base.update(kw)
    return CreditSpreadInputs(**base)


def test_no_widening_branch():
    res = credit_spread_attribution(_cs(hy_spread_change_bp=-10.0))
    assert res.value["attribution"] == "NO_WIDENING"
    assert res.value["expected_durability"] == "not_applicable"
    assert res.value["widening_observed"] is False
    assert "no widening to attribute" in res.interpretation


def test_fundamental_attribution():
    res = credit_spread_attribution(_cs(default_rate_trend="rising", equity_vol_change_pct=5.0))
    assert res.value["attribution"] == "FUNDAMENTAL"
    assert res.value["expected_durability"] == "sticky_slow_to_reverse"
    assert res.value["fundamental"] is True
    assert res.value["technical"] is False


def test_technical_attribution():
    res = credit_spread_attribution(_cs(default_rate_trend="falling", equity_vol_change_pct=30.0))
    assert res.value["attribution"] == "TECHNICAL_RISK_AVERSION"
    assert res.value["expected_durability"] == "can_snap_back_sharply"
    assert res.value["fundamental"] is False
    assert res.value["technical"] is True


def test_both_attribution_reachable():
    # The BOTH branch is reachable once the spec's mutual-exclusion AND is dropped.
    res = credit_spread_attribution(_cs(default_rate_trend="rising", equity_vol_change_pct=30.0))
    assert res.value["attribution"] == "BOTH"
    assert res.value["expected_durability"] == "elevated_concern"
    assert res.value["fundamental"] is True
    assert res.value["technical"] is True


def test_unclear_when_neither():
    res = credit_spread_attribution(_cs(default_rate_trend="stable", equity_vol_change_pct=5.0))
    assert res.value["attribution"] == "UNCLEAR"
    assert res.value["expected_durability"] == "investigate"


def test_parallel_widening_diagnostic():
    res = credit_spread_attribution(_cs(hy_spread_change_bp=20.0, ig_spread_change_bp=18.0))
    # |20 - 18| = 2.0 <= 5.0 -> parallel
    assert res.value["hy_minus_ig_change_bp"] == pytest.approx(2.0)
    assert res.value["widenings_are_parallel"] is True
    assert any("moved within" in w for w in res.warnings)


def test_change_window_and_confidence():
    res = credit_spread_attribution(_cs())
    assert res.value["change_window_days"] == 5
    assert res.value["default_rate_trend"] == "stable"
    assert res.confidence == 0.50
