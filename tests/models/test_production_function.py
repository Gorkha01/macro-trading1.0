"""Hand-computed verification tests for models/production_function.py (Modules 3.5 / 7.2).

Two functions:

  potential_gdp_cobb_douglas(inputs) -> ModelResult; value is a float Y.
      Y = A * K^alpha * L^(1-alpha); alpha is read from config (0.3), NOT a
      signature default (LAW 1). The golden case A=1,K=100,L=100 is exact by
      construction (100^0.3 * 100^0.7 = 100^1.0 = 100.0) and is the real test of
      the exponent handling: applying alpha to L too gives 1000.0, a 10x error
      no plausibility range would catch.
      Second hand case A=20,K=40000,L=160000 (terms NOT chosen to cancel):
          K^0.3   = 24.022489
          L^0.7   = 4394.242173
          Y = 20 * 24.022489 * 4394.242173 = 2,111,212.66 (calculator-verified).
      Confidence = base 0.70 - unobservable 0.20 - heuristic 0.20 + 0
                 = 0.30 (clamped, rounded to 0.300).
      FiniteInputs (gt=0.0) rejects non-positive and non-finite inputs.

  growth_accounting_decomposition(labor_pct, prod_pct) -> ModelResult; value dict.
      total = labor + prod (both growth rates in %).
      productivity_share = round(prod/total, 3) if total != 0 else None  (None,
          never 0.0, when the ratio is undefined).
      Confidence = 0.70 - unobservable 0.20 - (heuristic 0.20 IFF share > 0.6).
      Warning paths (hand-traced):
        * share is not None and share > 0.6         -> "productivity dominates"
        * labor < 0 and prod > 0 and total > 0      -> "negative labor offset"
          (the `total > 0` guard matches the docstring's "only if productivity
          exceeds the decline"; WITHOUT it the warning falsely fires when
          total <= 0, e.g. labor=-0.5, prod=+0.5, which is the F-PRODFN-002 fix)
        * share is None                              -> "share undefined (sum=0)"
        * elif prod < 0 and labor > 0                -> "carried by headcount"
        * elif prod < 0 and labor < 0                -> "both negative"
"""

from __future__ import annotations

import math

import pytest

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.production_function import (
    PotentialGDPInputs,
    growth_accounting_decomposition,
    potential_gdp_cobb_douglas,
)


def _pot(A: float, K: float, L: float) -> ModelResult:
    return potential_gdp_cobb_douglas(PotentialGDPInputs(
        total_factor_productivity=A, capital_stock=K, labor_input=L
    ))


# --------------------------------------------------------------------------
# potential_gdp_cobb_douglas
# --------------------------------------------------------------------------

def test_golden_case_exact_by_construction():
    # 100^0.3 * 100^0.7 = 100^1.0 = 100.0 exactly (up to float rounding).
    res = _pot(1.0, 100.0, 100.0)
    assert res.value == pytest.approx(100.0, abs=1e-6)
    # alpha from config (0.3); alpha applied to K only, (1-alpha) to L only.
    assert res.value == pytest.approx(math.pow(100, 0.3) * math.pow(100, 0.7), rel=1e-9)


def test_alpha_not_applied_to_labor_too():
    # If alpha were wrongly applied to L as well: 100^0.3 * 100^0.3 = 100^0.6
    # ~ 15.85, not 100. The function must NOT collapse to that.
    res = _pot(1.0, 100.0, 100.0)
    assert res.value != pytest.approx(math.pow(100, 0.3) * math.pow(100, 0.3), rel=1e-3)


def test_second_hand_case_cancels_to_known_value():
    # Hand-verified with a calculator: A=20,K=40000,L=160000,alpha=0.3 -> 2,111,212.66
    res = _pot(20.0, 40000.0, 160000.0)
    assert res.value == pytest.approx(2_111_212.66, abs=10.0)
    cap = math.pow(40000, 0.3)
    lap = math.pow(160000, 0.7)
    assert res.value == pytest.approx(20.0 * cap * lap, rel=1e-6)


def test_potential_confidence_is_lowest_in_suite():
    # unobservable + heuristic, no independence credit -> 0.70 - 0.20 - 0.20 = 0.30
    res = _pot(1.0, 100.0, 100.0)
    assert res.confidence == pytest.approx(0.300, abs=1e-9)


def test_negative_inputs_rejected_by_finite_guard():
    with pytest.raises(Exception):
        potential_gdp_cobb_douglas(PotentialGDPInputs(
            total_factor_productivity=-1.0, capital_stock=100.0, labor_input=100.0
        ))


def test_zero_inputs_rejected_by_gt_constraint():
    with pytest.raises(Exception):
        potential_gdp_cobb_douglas(PotentialGDPInputs(
            total_factor_productivity=1.0, capital_stock=0.0, labor_input=100.0
        ))


def test_non_finite_inputs_rejected():
    with pytest.raises(Exception):
        potential_gdp_cobb_douglas(PotentialGDPInputs(
            total_factor_productivity=float("nan"), capital_stock=100.0, labor_input=100.0
        ))
    with pytest.raises(Exception):
        potential_gdp_cobb_douglas(PotentialGDPInputs(
            total_factor_productivity=float("inf"), capital_stock=100.0, labor_input=100.0
        ))


def test_inputs_used_lists_all_three_terms():
    res = _pot(1.0, 100.0, 100.0)
    assert set(res.inputs_used) == {
        "total_factor_productivity", "capital_stock", "labor_input"
    }


# --------------------------------------------------------------------------
# growth_accounting_decomposition
# --------------------------------------------------------------------------

def test_balanced_split_low_confidence_total():
    # labor 1.0, prod 1.0 -> total 2.0, share 0.5 (<= 0.6) -> no dominance warn.
    res = growth_accounting_decomposition(1.0, 1.0)
    v = res.value
    assert v["potential_growth"] == pytest.approx(2.0)
    assert v["productivity_share"] == 0.5
    assert v["labor_contribution_pp"] == 1.0
    assert v["productivity_contribution_pp"] == 1.0
    # unobservable only (no heuristic) -> 0.70 - 0.20 = 0.50
    assert res.confidence == pytest.approx(0.500, abs=1e-9)
    assert not any("dominates" in w for w in res.warnings)


def test_productivity_dominates_warns_and_lowers_confidence():
    # labor 0.4, prod 1.6 -> total 2.0, share 0.8 (> 0.6) -> dominance warn +
    # heuristic penalty -> 0.70 - 0.20 - 0.20 = 0.30.
    res = growth_accounting_decomposition(0.4, 1.6)
    assert res.value["productivity_share"] == 0.8
    assert res.confidence == pytest.approx(0.300, abs=1e-9)
    assert any("dominates" in w for w in res.warnings)


def test_zero_total_share_is_none_not_zero():
    # labor -0.5, prod +0.5 -> total 0 -> share None (undefined), warn "undefined".
    res = growth_accounting_decomposition(-0.5, 0.5)
    assert res.value["potential_growth"] == pytest.approx(0.0)
    assert res.value["productivity_share"] is None
    assert any("undefined" in w for w in res.warnings)
    # F-PRODFN-002 FIX: total==0 so the "positive growth rests on productivity"
    # claim must NOT appear here.
    assert not any("rests entirely on productivity" in w for w in res.warnings)
    # no dominance penalty (share is None) -> 0.50
    assert res.confidence == pytest.approx(0.500, abs=1e-9)


def test_negative_labor_with_positive_growth_warns():
    # labor -0.3, prod +0.8 -> total +0.5 > 0 -> "negative labor offset" warns.
    res = growth_accounting_decomposition(-0.3, 0.8)
    assert res.value["potential_growth"] == pytest.approx(0.5)
    assert any("rests entirely on productivity" in w for w in res.warnings)


def test_negative_labor_dominates_and_warns_both():
    # labor -0.3, prod +0.8 -> share 1.6 > 0.6 AND total > 0 -> BOTH warns.
    res = growth_accounting_decomposition(-0.3, 0.8)
    assert any("dominates" in w for w in res.warnings)
    assert any("rests entirely on productivity" in w for w in res.warnings)


def test_negative_labor_positive_prod_negative_total_no_false_positive():
    # labor -0.8, prod +0.3 -> total -0.5 <= 0 -> must NOT claim "positive growth".
    res = growth_accounting_decomposition(-0.8, 0.3)
    assert res.value["potential_growth"] == pytest.approx(-0.5)
    assert not any("rests entirely on productivity" in w for w in res.warnings)


def test_headcount_carries_when_productivity_negative():
    # labor +0.5, prod -0.3 -> total +0.2, share -1.5 (not > 0.6) ->
    # "carried by headcount" warn; no dominance penalty -> 0.50.
    res = growth_accounting_decomposition(0.5, -0.3)
    assert res.value["productivity_share"] == -1.5
    assert any("headcount" in w for w in res.warnings)
    assert res.confidence == pytest.approx(0.500, abs=1e-9)


def test_both_negative_is_contraction_not_offset():
    # labor -0.3, prod -0.4 -> total -0.7 -> "both negative" warn; share 0.571
    # (not > 0.6) -> no dominance penalty -> 0.50.
    res = growth_accounting_decomposition(-0.3, -0.4)
    assert res.value["potential_growth"] == pytest.approx(-0.7)
    assert any("BOTH terms are negative" in w for w in res.warnings)
    assert res.confidence == pytest.approx(0.500, abs=1e-9)
