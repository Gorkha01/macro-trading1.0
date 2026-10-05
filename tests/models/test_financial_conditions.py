"""Hand-computed verification tests for models/financial_conditions.py (Module 12).

Weights from config/settings.yaml (verified by hand):
  policy_rate=0.25, credit_spread_hy=0.25, term_premium=0.20,
  equity_index=0.20, usd_index=0.10  (sum = 1.00)
equity_index is NEGATED (rising equity = looser conditions -> pushes index down).
standardization_window_years = 3, nfci_divergence_threshold = 1.0.
Weights are uncalibrated_illustrative -> confidence = 0.50.

Hand example: z = (value-mean)/std
  policy_rate:      (3-2)/1   = 1.0  -> +0.25 * 1.0 =  0.250
  credit_spread_hy: (5-3)/1   = 2.0  -> +0.25 * 2.0 =  0.500
  term_premium:     (0.2-0.1)/0.2 = 0.5 -> +0.20 * 0.5 =  0.100
  equity_index:     (110-100)/10 = 1.0 -> -0.20 * 1.0 = -0.200   (negated)
  usd_index:        (90-100)/10 = -1.0 -> +0.10 * -1.0 = -0.100
  fci = 0.250 + 0.500 + 0.100 - 0.200 - 0.100 = 0.550  (tighter_than_average)
"""

from __future__ import annotations

from typing import Any

import pytest

from macro_engine.models.financial_conditions import FCIComponent, FCIInputs, compute_fci


def _fci(**kw: Any) -> FCIInputs:
    base: dict[str, Any] = {
        "policy_rate": FCIComponent(value=3.0, mean=2.0, std=1.0),
        "credit_spread_hy": FCIComponent(value=5.0, mean=3.0, std=1.0),
        "term_premium": FCIComponent(value=0.2, mean=0.1, std=0.2),
        "equity_index": FCIComponent(value=110.0, mean=100.0, std=10.0),
        "usd_index": FCIComponent(value=90.0, mean=100.0, std=10.0),
        "standardization_window_years": 3,
    }
    base.update(kw)
    return FCIInputs(**base)


def test_fci_hand_computed_composite() -> None:
    res = compute_fci(_fci())
    assert res.value_dict()["fci"] == pytest.approx(0.55)
    assert res.value_dict()["tighter_than_average"] is True
    # Contributions by component.
    assert res.value_dict()["contributions"]["policy_rate"] == pytest.approx(0.25)
    assert res.value_dict()["contributions"]["credit_spread_hy"] == pytest.approx(0.50)
    assert res.value_dict()["contributions"]["term_premium"] == pytest.approx(0.10)
    assert res.value_dict()["contributions"]["equity_index"] == pytest.approx(-0.20)  # negated
    assert res.value_dict()["contributions"]["usd_index"] == pytest.approx(-0.10)
    # z-scores published.
    assert res.value_dict()["z_scores"]["policy_rate"] == pytest.approx(1.0)
    assert res.value_dict()["z_scores"]["credit_spread_hy"] == pytest.approx(2.0)
    assert res.value_dict()["z_scores"]["equity_index"] == pytest.approx(1.0)
    assert res.value_dict()["z_scores"]["usd_index"] == pytest.approx(-1.0)
    # equity_index is the only negated component.
    assert res.value_dict()["negated_components"] == ["equity_index"]


def test_looser_than_average_when_sum_negative() -> None:
    # policy 0 + credit 0 + term 0 + equity(-0.60) + usd(+0.10) = -0.50 < 0
    res = compute_fci(
        _fci(
            policy_rate=FCIComponent(value=2.0, mean=2.0, std=1.0),  # z=0 -> 0
            credit_spread_hy=FCIComponent(value=3.0, mean=3.0, std=1.0),  # z=0 -> 0
            term_premium=FCIComponent(value=0.1, mean=0.1, std=0.2),  # z=0 -> 0
            equity_index=FCIComponent(value=130.0, mean=100.0, std=10.0),  # z=3 -> -0.60 (negated)
            usd_index=FCIComponent(value=110.0, mean=100.0, std=10.0),  # z=1 -> +0.10 (NOT negated)
        )
    )
    assert res.value_dict()["fci"] == pytest.approx(-0.50)
    assert res.value_dict()["tighter_than_average"] is False


def test_non_finite_component_rejected() -> None:
    with pytest.raises(ValueError):
        compute_fci(_fci(policy_rate=FCIComponent(value=float("inf"), mean=2.0, std=1.0)))


def test_zero_std_rejected() -> None:
    with pytest.raises(ValueError):
        FCIComponent(value=3.0, mean=2.0, std=0.0)


def test_nfci_absent_warns() -> None:
    res = compute_fci(_fci())
    assert any("NFCI cross-check NOT PERFORMED" in w for w in res.warnings)
    assert res.value_dict()["nfci_cross_checked"] is False


def test_nfci_divergence_warns_when_large() -> None:
    res = compute_fci(_fci(nfci_value=-2.0))  # divergence = 0.55 - (-2.0) = 2.55 > 1.0
    assert res.value_dict()["nfci_cross_checked"] is True
    assert res.value_dict()["nfci_divergence"] == pytest.approx(2.55)
    assert any("diverges from NFCI" in w for w in res.warnings)


def test_confidence_is_heuristic_penalized() -> None:
    res = compute_fci(_fci())
    assert res.confidence == 0.50
