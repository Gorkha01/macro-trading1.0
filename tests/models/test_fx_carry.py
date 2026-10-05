"""Hand-computed verification tests for models/fx_carry.py (Module 9).

Every expected value below is derived BY HAND from the documented formula and
``config/settings.yaml`` (read, not assumed):

  CIP:      F_imp = S * (1 + i_d*t/b) / (1 + i_f*t/b),  t = tenor_days
            deviation_pct = (F - F_imp) / F_imp * 100
            synthetic = (F/S)*(1 + i_f_p) - 1;  basis_period = synthetic - i_d_p
            identity: basis_period == (1 + i_d_p) * deviation_fraction  (EXACT)
  carry:    score = differential / max(realised_vol, floor)
  UIP:      expected_move = ((1 + i_d_p)/(1 + i_f_p) - 1) * 100
  PPP:      deviation_pct = (spot - ppp) / ppp * 100

Config read: fx_carry.notable_deviation_pct = 0.1, extreme = 0.5,
carry_vol_floor = 0.1, dollar_smile_vix_threshold = 25.0, sign_boundary = 0.0,
uip_reliability_cap = 0.15, ppp_reliability_cap = 0.2,
ppp_tactical_horizon_years = 3.0, ppp_implausible_deviation_pct = 100.0.

The five findings this file guards are F-FX-001..F-FX-006; see the test
docstrings for the exact reachability that makes each one a defect.
"""

from __future__ import annotations

import math

import pytest

import macro_engine.models.fx_carry as fx_carry
from macro_engine.models.fx_carry import (
    CarryScoreInputs,
    CIPInputs,
    DollarSmileInputs,
    PPPInputs,
    UIPInputs,
    carry_score,
    cip_check,
    dollar_smile_regime,
    ppp_valuation,
    uip_expected_move,
)


def _cip(*, forward: float, quote: str = "domestic_per_foreign") -> CIPInputs:
    return CIPInputs(
        spot=1.10,
        forward=forward,
        i_domestic_annualized=0.05,
        i_foreign_annualized=0.03,
        tenor_days=90,
        day_count_basis="actual_360",
        quote=quote,
    )


# ---------------------------------------------------------------------------
# cip_check
# ---------------------------------------------------------------------------
def test_cip_check_implied_forward_matches_the_identity():
    # F_imp = 1.10 * (1 + 0.05*0.25) / (1 + 0.03*0.25) = 1.10*1.0125/1.0075
    v = cip_check(_cip(forward=1.105)).value
    assert v["implied_forward"] == pytest.approx(1.10545906, abs=1e-8)
    assert v["i_domestic_period"] == pytest.approx(0.0125, abs=1e-9)
    assert v["i_foreign_period"] == pytest.approx(0.0075, abs=1e-9)
    assert v["day_count_basis_days"] == 360


def test_cip_check_deviation_and_basis_match_hand_arithmetic():
    # deviation = (1.105/1.1054590570... - 1)*100 = -0.041526%
    # synthetic = (1.105/1.10)*1.0075 - 1 = 0.0120795455
    # basis_period = 0.0120795455 - 0.0125 = -0.0004204545 -> -16.8182 bp
    v = cip_check(_cip(forward=1.105)).value
    assert v["deviation_pct"] == pytest.approx(-0.041526, abs=1e-5)
    assert v["synthetic_domestic_funding_rate_period"] == pytest.approx(0.01207955, abs=1e-8)
    assert v["domestic_funding_basis_bp_annualized"] == pytest.approx(-16.8182, abs=1e-3)


def test_cip_check_basis_identity_holds_between_two_published_keys():
    # basis_period == (1 + i_d_period) * deviation_fraction, EXACTLY.
    v = cip_check(_cip(forward=1.105)).value
    scale = v["tenor_days"] / v["day_count_basis_days"]
    basis_period = v["domestic_funding_basis_bp_annualized"] / 10_000.0 * scale
    deviation_fraction = v["deviation_pct"] / 100.0
    assert basis_period == pytest.approx(
        (1.0 + v["i_domestic_period"]) * deviation_fraction, abs=1e-8
    )


def test_cip_check_sign_convention_and_severity_bands():
    # forward ABOVE the implied one -> positive deviation -> domestic is the
    # expensive side. 1.107/1.105459 - 1 = +0.1394% -> NOTABLE (band 0.1..0.5).
    notable = cip_check(_cip(forward=1.107))
    assert notable.value["deviation_pct"] > 0.0
    assert notable.value["severity"] == "notable"
    assert notable.value["stressed_currency"] == "domestic"
    assert notable.direction == "domestic_funding_stress"
    assert len(notable.warnings) == 1
    # 1.12 -> +1.315% -> EXTREME
    extreme = cip_check(_cip(forward=1.12))
    assert extreme.value["severity"] == "extreme"
    # inside the notable band -> no side, no warning
    quiet = cip_check(_cip(forward=1.105))
    assert quiet.value["severity"] == "none"
    assert quiet.value["stressed_currency"] == "none"
    assert quiet.warnings == []


def test_cip_check_quote_inversion_round_trips():
    # A foreign_per_domestic quote is inverted before the identity, so a pair
    # quoted the other way with the reciprocal rates gives the SAME deviation.
    direct = cip_check(_cip(forward=1.105)).value
    inverted = cip_check(
        CIPInputs(
            spot=1.0 / 1.10,
            forward=1.0 / 1.105,
            i_domestic_annualized=0.05,
            i_foreign_annualized=0.03,
            tenor_days=90,
            quote="foreign_per_domestic",
        )
    ).value
    assert inverted["quote_was_inverted"] is True
    assert inverted["deviation_pct"] == pytest.approx(direct["deviation_pct"], abs=1e-4)


def test_cip_check_refuses_non_positive_exchange_rate():
    with pytest.raises(ValueError, match="strictly positive"):
        _cip(forward=0.0)


def test_cip_check_refuses_tenor_beyond_the_basis():
    with pytest.raises(ValueError, match="money-market year"):
        CIPInputs(
            spot=1.1,
            forward=1.1,
            i_domestic_annualized=0.05,
            i_foreign_annualized=0.03,
            tenor_days=400,
            day_count_basis="actual_360",
        )


def test_cip_check_refuses_period_rate_at_minus_100pct():
    # annualised -5.0 over a full year is a period rate of -500% < -100%.
    with pytest.raises(ValueError, match="-100%"):
        CIPInputs(
            spot=1.1,
            forward=1.1,
            i_domestic_annualized=0.05,
            i_foreign_annualized=-5.0,
            tenor_days=360,
        )


def test_cip_check_refuses_non_finite():
    with pytest.raises(ValueError, match="non-finite"):
        CIPInputs(
            spot=float("nan"),
            forward=1.1,
            i_domestic_annualized=0.05,
            i_foreign_annualized=0.03,
            tenor_days=90,
        )


def test_cip_check_negative_zero_publishes_positive_zero():
    # F-FX-002: a forward a hair BELOW the implied level makes the deviation (and
    # the basis, which is a tiny negative even at exact parity) round to -0.0.
    # The published values must be non-negative zeros.
    implied = 1.10 * (1.0 + 0.05 * 0.25) / (1.0 + 0.03 * 0.25)
    v = cip_check(_cip(forward=implied * (1.0 - 1e-12))).value
    assert repr(v["deviation_pct"]) == "0.0"
    assert repr(v["domestic_funding_basis_bp_annualized"]) == "0.0"
    assert "-0.0000" not in cip_check(_cip(forward=implied)).interpretation


def test_cip_check_sets_the_market_fx_source_family():
    # F-FX-004: its four siblings set MARKET_FX; cip_check did not.
    from macro_engine.models.contracts import EvidenceSourceFamily

    assert cip_check(_cip(forward=1.105)).source_family == EvidenceSourceFamily.MARKET_FX


# ---------------------------------------------------------------------------
# carry_score
# ---------------------------------------------------------------------------
def test_carry_score_ratio_hand_computed():
    # 0.02 / 0.12 = 0.166667 (floor 0.1 does not bind)
    v = carry_score(
        CarryScoreInputs(rate_differential_annualized=0.02, realized_vol_annualized=0.12)
    ).value
    assert v["score"] == pytest.approx(0.166667, abs=1e-6)
    assert v["effective_denominator"] == pytest.approx(0.12)
    assert v["volatility_floor_binding"] is False
    assert v["carry_outcome"] == "long_domestic"


def test_carry_score_floor_binds_and_warns():
    # 0.05 < floor 0.1, so the denominator is the FLOOR: 0.02/0.1 = 0.2
    res = carry_score(
        CarryScoreInputs(rate_differential_annualized=0.02, realized_vol_annualized=0.05)
    )
    assert res.value["score"] == pytest.approx(0.2)
    assert res.value["volatility_floor_binding"] is True
    assert len(res.warnings) == 1 and "FLOOR" in res.warnings[0]


def test_carry_score_outcome_labels():
    assert (
        carry_score(
            CarryScoreInputs(rate_differential_annualized=-0.02, realized_vol_annualized=0.12)
        ).value["carry_outcome"]
        == "long_foreign"
    )
    assert (
        carry_score(
            CarryScoreInputs(rate_differential_annualized=0.0, realized_vol_annualized=0.12)
        ).value["carry_outcome"]
        == "flat"
    )


def test_carry_score_refuses_non_positive_volatility():
    with pytest.raises(ValueError, match="strictly positive"):
        CarryScoreInputs(rate_differential_annualized=0.02, realized_vol_annualized=0.0)


def test_carry_score_refuses_non_finite():
    with pytest.raises(ValueError, match="non-finite"):
        CarryScoreInputs(rate_differential_annualized=float("inf"), realized_vol_annualized=0.1)


def test_carry_score_negative_zero_publishes_positive_zero():
    # F-FX-002: a differential a trillionth below zero rounds the score to -0.0.
    res = carry_score(
        CarryScoreInputs(rate_differential_annualized=-1e-12, realized_vol_annualized=0.12)
    )
    assert repr(res.value["score"]) == "0.0"
    assert "-0.0000" not in res.interpretation


# ---------------------------------------------------------------------------
# dollar_smile_regime
# ---------------------------------------------------------------------------
def _smile(vix: float, growth: float, rate: float):
    return dollar_smile_regime(
        DollarSmileInputs(vix_level=vix, us_growth_surprise=growth, us_vs_row_rate_diff=rate)
    )


def test_dollar_smile_left_when_vix_above_the_gate():
    res = _smile(26.0, -0.5, -0.5)
    assert res.value["side"] == "left"
    assert res.value["vix_above_threshold"] is True
    assert len(res.warnings) == 1 and "LEFT" in res.warnings[0]


def test_dollar_smile_right_when_both_signed_inputs_positive():
    res = _smile(20.0, 0.4, 0.3)
    assert res.value["side"] == "right"
    assert res.value["growth_above_boundary"] is True
    assert res.value["rate_above_boundary"] is True
    assert res.warnings == []


def test_dollar_smile_middle_and_the_neutral_case():
    # VIX exactly at the gate is NOT left; one input exactly zero is NOT right.
    res = _smile(25.0, 0.0, 0.3)
    assert res.value["side"] == "middle"
    assert res.value["vix_above_threshold"] is False
    assert res.value["is_neutral_input"] is True
    assert any("NEUTRAL" in w for w in res.warnings)
    # a middle limb reached by an outright NEGATIVE input is not "neutral"
    res2 = _smile(20.0, -0.4, 0.3)
    assert res2.value["side"] == "middle"
    assert res2.value["is_neutral_input"] is False


def test_dollar_smile_direction_is_unset():
    assert _smile(20.0, 0.4, 0.3).direction is None


def test_dollar_smile_refuses_non_finite():
    with pytest.raises(ValueError, match="non-finite"):
        DollarSmileInputs(vix_level=float("nan"), us_growth_surprise=0.0, us_vs_row_rate_diff=0.0)


# ---------------------------------------------------------------------------
# uip_expected_move
# ---------------------------------------------------------------------------
def test_uip_exact_ratio_hand_computed():
    # ((1.0125)/(1.0075) - 1)*100 = 0.496278%; the first-order form is 0.5%
    v = uip_expected_move(
        UIPInputs(i_domestic_annualized=0.05, i_foreign_annualized=0.03, tenor_days=90)
    ).value
    assert v["expected_move_pct"] == pytest.approx(0.496278, abs=1e-6)
    assert v["expected_move_simple_pct"] == pytest.approx(0.5, abs=1e-9)
    assert v["differential_period"] == pytest.approx(0.005, abs=1e-9)
    assert v["direction"] == "domestic_depreciation"


def test_uip_flat_case_warns():
    res = uip_expected_move(
        UIPInputs(i_domestic_annualized=0.03, i_foreign_annualized=0.03, tenor_days=90)
    )
    assert res.value["direction"] == "flat"
    assert res.value["expected_move_pct"] == 0.0
    assert len(res.warnings) == 1


def test_uip_confidence_is_the_configured_cap():
    res = uip_expected_move(
        UIPInputs(i_domestic_annualized=0.05, i_foreign_annualized=0.03, tenor_days=90)
    )
    assert res.confidence == pytest.approx(0.15)


def test_uip_refuses_tenor_beyond_the_basis():
    with pytest.raises(ValueError, match="money-market year"):
        UIPInputs(i_domestic_annualized=0.05, i_foreign_annualized=0.03, tenor_days=400)


def test_uip_negative_zero_publishes_positive_zero():
    # F-FX-002: a differential a hair below zero rounds both forms to -0.0.
    res = uip_expected_move(
        UIPInputs(i_domestic_annualized=0.03, i_foreign_annualized=0.03 + 1e-12, tenor_days=90)
    )
    assert repr(res.value["expected_move_pct"]) == "0.0"
    assert repr(res.value["expected_move_simple_pct"]) == "0.0"
    assert "-0.0000" not in res.interpretation


# ---------------------------------------------------------------------------
# ppp_valuation
# ---------------------------------------------------------------------------
def test_ppp_deviation_and_status_hand_computed():
    # (1.20 - 1.10)/1.10*100 = 9.0909% -> overvalued
    over = ppp_valuation(PPPInputs(spot_rate=1.20, ppp_implied_rate=1.10, horizon_years=5.0))
    assert over.value["deviation_pct"] == pytest.approx(9.09, abs=1e-6)
    assert over.value["status"] == "overvalued"
    assert over.value["ratio"] == pytest.approx(1.090909, abs=1e-6)
    assert over.confidence == pytest.approx(0.2)
    # (1.05 - 1.10)/1.10*100 = -4.5455% -> undervalued
    under = ppp_valuation(PPPInputs(spot_rate=1.05, ppp_implied_rate=1.10, horizon_years=5.0))
    assert under.value["deviation_pct"] == pytest.approx(-4.55, abs=1e-6)
    assert under.value["status"] == "undervalued"
    # exact tie -> at_parity, its own member
    par = ppp_valuation(PPPInputs(spot_rate=1.10, ppp_implied_rate=1.10, horizon_years=5.0))
    assert par.value["status"] == "at_parity"
    assert par.value["deviation_pct"] == 0.0


def test_ppp_tactical_horizon_and_implausible_warnings():
    # horizon 1.0 < tactical 3.0 -> the no-tactical-timing warning fires
    short = ppp_valuation(PPPInputs(spot_rate=1.20, ppp_implied_rate=1.10, horizon_years=1.0))
    assert any("MULTI-YEAR" in w for w in short.warnings)
    # an overvaluation read short is the textbook misuse -> a SECOND warning
    assert any("overvalued, read at" in w for w in short.warnings)
    # |deviation| > 100% -> the data-check warning
    wide = ppp_valuation(PPPInputs(spot_rate=2.30, ppp_implied_rate=1.10, horizon_years=5.0))
    assert any("UNIT OR CONVENTION ERROR" in w for w in wide.warnings)


def test_ppp_negative_zero_publishes_positive_zero():
    # F-FX-002: a spot within 0.005% of the PPP level rounds to -0.0 while the
    # status reads 'undervalued'.
    res = ppp_valuation(
        PPPInputs(spot_rate=1.10 * (1.0 - 1e-9), ppp_implied_rate=1.10, horizon_years=5.0)
    )
    assert res.value["status"] == "undervalued"
    assert repr(res.value["deviation_pct"]) == "0.0"


def test_ppp_refuses_non_positive_implied_rate():
    with pytest.raises(ValueError):
        PPPInputs(spot_rate=1.10, ppp_implied_rate=-1.0, horizon_years=5.0)


def test_ppp_refuses_a_malformed_fetch_request():
    # the rate omitted is the FETCH path, so BOTH ISO3 codes are required
    with pytest.raises(ValueError, match="BOTH"):
        PPPInputs(spot_rate=1.10, horizon_years=5.0, domestic_iso3="DEU")


def test_ppp_inputs_used_names_the_iso_pair_on_the_fetch_path(monkeypatch):
    # F-FX-005: on the fetch path the ISO pair IS an input, so it must be named.
    monkeypatch.setattr(
        fx_carry,
        "fetch_ppp_implied_rate",
        lambda domestic, foreign: (1.10, f"vintage: {domestic}/{foreign}"),
    )
    res = ppp_valuation(
        PPPInputs(spot_rate=1.20, horizon_years=5.0, domestic_iso3="DEU", foreign_iso3="USA")
    )
    joined = " ".join(res.inputs_used)
    assert "DEU" in joined and "USA" in joined
    assert any("FETCHED" in lim for lim in res.limitations)


# ---------------------------------------------------------------------------
# Module-level guards for F-FX-001 / F-FX-003 / F-FX-006
# ---------------------------------------------------------------------------
def test_module_docstring_names_ppp_and_its_fetch():
    # F-FX-001: the module docstring claimed "this module never reaches for a
    # provider" and omitted ppp_valuation, which DOES fetch.
    doc = fx_carry.__doc__ or ""
    assert "ppp_valuation" in doc
    assert "never reaches for a provider" not in doc
    assert "FETCHED" in doc


def test_uip_warnings_has_no_unread_parameter():
    # F-FX-003: `_uip_warnings` accepted `expected_move_pct` and never read it.
    import inspect

    params = list(inspect.signature(fx_carry._uip_warnings).parameters)
    assert "expected_move_pct" not in params


def test_uip_direction_is_exported():
    # F-FX-006: every other module Literal is in __all__; UIPDirection was not.
    assert "UIPDirection" in fx_carry.__all__


def test_positive_zero_helper_maps_only_negative_zero():
    assert repr(fx_carry._positive_zero(-0.0)) == "0.0"
    assert repr(fx_carry._positive_zero(0.0)) == "0.0"
    assert fx_carry._positive_zero(-1e-6) == -1e-6
    assert fx_carry._positive_zero(0.5) == 0.5
    assert math.copysign(1.0, fx_carry._positive_zero(-0.0)) == 1.0
