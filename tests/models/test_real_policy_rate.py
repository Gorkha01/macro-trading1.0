"""Hand-computed verification tests for models/real_policy_rate.py (Module 3.6).

r_real = i - pi  (ex-post Fisher decomposition, both terms observed).
Confidence is compute_confidence() with NO penalty flags -> equals the configured
base (0.70). Verified by hand from contracts.compute_confidence and
config.confidence.values.base.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.models.real_policy_rate import (
    RealPolicyRateInputs,
    real_policy_rate,
)


def test_positive_real_rate():
    res = real_policy_rate(
        RealPolicyRateInputs(nominal_policy_rate=5.0, inflation_rate=2.0)
    )
    # 5.0 - 2.0 = 3.0, rounded to 3 dp.
    assert res.value == pytest.approx(3.0)
    assert "real policy rate is +3.00%" in res.interpretation
    # No penalty flags set -> confidence == configured base.
    assert res.confidence == pytest.approx(0.70)
    assert res.inputs_used == ["nominal_policy_rate", "inflation_rate"]


def test_negative_real_rate():
    res = real_policy_rate(
        RealPolicyRateInputs(nominal_policy_rate=1.0, inflation_rate=3.0)
    )
    # 1.0 - 3.0 = -2.0.
    assert res.value == pytest.approx(-2.0)
    assert "real policy rate is -2.00%" in res.interpretation
    assert res.confidence == pytest.approx(0.70)


def test_zero_real_rate_and_confidence_is_base():
    settings = get_settings()
    base = settings.confidence.values["base"]
    res = real_policy_rate(
        RealPolicyRateInputs(nominal_policy_rate=4.0, inflation_rate=4.0)
    )
    assert res.value == pytest.approx(0.0)
    # +0.00% formatting.
    assert "real policy rate is +0.00%" in res.interpretation
    assert res.confidence == pytest.approx(round(base, 3))


def test_pi_target_appears_in_warning():
    pi_target = get_settings().policy.pi_target_value
    res = real_policy_rate(
        RealPolicyRateInputs(nominal_policy_rate=2.0, inflation_rate=2.0)
    )
    assert any(f"{pi_target:.1f}" in w for w in res.warnings)


def test_non_finite_inputs_rejected():
    with pytest.raises(ValueError):
        RealPolicyRateInputs(nominal_policy_rate=float("nan"), inflation_rate=2.0)
    with pytest.raises(ValueError):
        RealPolicyRateInputs(nominal_policy_rate=2.0, inflation_rate=float("inf"))
