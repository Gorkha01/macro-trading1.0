"""Fresh test suite for src/macro_engine/models/risk.py.

Written from scratch (the prior suite was self-confirming and deleted). Every
golden number below was derived by hand and independently re-derived by
``.review-probe/risk_golden_probe.py`` against statistics.NormalDist / an
independent numpy reimplementation of the Monte Carlo pipeline.

Defects covered (mutation-proven, see .review-evidence/mutations.json):
  * F-RISK-001 — historical_var published ``-0.0`` (and "-0.0000% loss") when
    the 5th-percentile return is exactly 0, violating the "positive = loss"
    convention. Fixed with ``+ 0.0`` normalisation.
  * F-RISK-002 — expected_shortfall published ``-0.0`` in value and in the
    displayed VaR threshold under the same condition. Same fix.

Sign convention asserted everywhere: positive = loss.
"""

import math

import numpy as np
import pytest

from macro_engine.config import get_settings
from macro_engine.models.risk import (
    MonteCarloVaRInputs,
    ParametricVaRInputs,
    RealizedVolInputs,
    ReturnsInputs,
    TwoAssetPortfolioInputs,
    _quantile,
    expected_shortfall,
    historical_var,
    marginal_risk_contributions,
    monte_carlo_var,
    parametric_var,
    portfolio_volatility_n_asset,
    portfolio_volatility_two_asset,
    realized_vol_simple,
    z_score_for_confidence,
)


# ---------------------------------------------------------------------------
# z_score_for_confidence
# ---------------------------------------------------------------------------

def test_z_score_exact_tabulated_values():
    d = __import__("statistics").NormalDist(0, 1)
    for conf in (0.90, 0.95, 0.975, 0.99, 0.995, 0.999):
        assert z_score_for_confidence(conf) == pytest.approx(
            d.inv_cdf(conf), abs=1e-12
        )


def test_z_score_round_lookup_hits_exact_for_rounded_confidence():
    # confidence 0.95000001 rounds to the tabulated 0.95 key.
    assert z_score_for_confidence(0.95000001) == pytest.approx(
        z_score_for_confidence(0.95)
    )


def test_z_score_below_table_refuses_with_explanatory_message():
    with pytest.raises(ValueError) as exc:
        z_score_for_confidence(0.80)
    msg = str(exc.value)
    assert "below the tabulated minimum" in msg
    assert "Extend _Z_QUANTILES" in msg


def test_z_score_above_table_refuses():
    with pytest.raises(ValueError) as exc:
        z_score_for_confidence(0.9999)
    assert "exceeds the tabulated maximum" in str(exc.value)


def test_z_score_interpolates_linearly_between_points():
    # 0.925 is the midpoint of [0.90, 0.95]; linear interpolation only.
    z = z_score_for_confidence(0.925)
    lo, hi = z_score_for_confidence(0.90), z_score_for_confidence(0.95)
    assert z == pytest.approx((lo + hi) / 2, abs=1e-9)


def test_z_score_rejects_out_of_unit_interval():
    for bad in (0.0, 1.0, -0.1, 1.1):
        with pytest.raises(ValueError):
            z_score_for_confidence(bad)


# ---------------------------------------------------------------------------
# _quantile (module's numpy-'linear' equivalent)
# ---------------------------------------------------------------------------

def test_quantile_single_element():
    assert _quantile([3.0], 0.5) == 3.0


def test_quantile_empty_raises():
    with pytest.raises(ValueError):
        _quantile([], 0.5)


def test_quantile_endpoints():
    s = [0.0, 10.0, 20.0, 30.0]
    assert _quantile(s, 0.0) == 0.0
    assert _quantile(s, 1.0) == 30.0


def test_quantile_interpolates():
    assert _quantile([0.0, 10.0], 0.5) == pytest.approx(5.0)
    assert _quantile([0.0, 10.0, 20.0], 0.5) == pytest.approx(10.0)
    assert _quantile([0.0, 10.0, 20.0, 30.0], 0.25) == pytest.approx(7.5)


# ---------------------------------------------------------------------------
# historical_var
# ---------------------------------------------------------------------------

# 10-return sample; sorted 5th percentile (fraction 0.05, position 0.45) is
# -0.0455 -> VaR loss 4.55%. Hand-derived.
_HV_SAMPLE = [
    -0.05, 0.01, 0.02, -0.03, 0.04,
    -0.01, 0.03, -0.02, 0.00, -0.04,
]


def test_historical_var_golden_value():
    res = historical_var(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.95))
    assert res.value == 4.55


def test_historical_var_sign_convention_positive_is_loss():
    res = historical_var(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.95))
    assert res.value > 0
    assert "loss" in res.interpretation


def test_historical_var_always_warns_about_crisis_blindness():
    res = historical_var(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.95))
    assert any(
        "cannot exceed the worst loss" in w or "excludes a crisis" in w
        for w in res.warnings
    )


def test_historical_var_warns_when_tail_too_thin():
    # 10 obs * (1 - 0.99) = 0.1 tail observations, below the configured floor.
    res = historical_var(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.99))
    assert any("Only 0.1" in w for w in res.warnings)


def test_historical_var_rejects_non_finite_element():
    # FiniteInputs refuses a nan ELEMENT (D-139b).
    with pytest.raises(Exception):
        historical_var(ReturnsInputs(returns=[-0.05, float("nan"), 0.01]))


def test_historical_var_requires_at_least_two_returns():
    with pytest.raises(Exception):
        historical_var(ReturnsInputs(returns=[0.01]))


def test_historical_var_negative_zero_publishes_zero():
    """F-RISK-001: a tail quantile return of exactly 0 must publish +0.0, not -0.0."""
    returns_21 = [
        -0.05, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08,
        0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19,
    ]
    res = historical_var(ReturnsInputs(returns=returns_21, confidence=0.95))
    # Strict: negative zero must not survive into the published value.
    assert repr(res.value) == "0.0"
    assert "-0.0000" not in res.interpretation
    assert "0.0000% loss" in res.interpretation


# ---------------------------------------------------------------------------
# expected_shortfall
# ---------------------------------------------------------------------------

def test_expected_shortfall_golden_value():
    res = expected_shortfall(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.95))
    # Only -0.05 lies at/below the 5th percentile -> ES = 5.0%.
    assert res.value == 5.0


def test_expected_shortfall_exceeds_var():
    es = expected_shortfall(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.95))
    hv = historical_var(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.95))
    assert es.value >= hv.value


def test_expected_shortfall_value_is_dict_free_float():
    res = expected_shortfall(ReturnsInputs(returns=_HV_SAMPLE, confidence=0.95))
    assert isinstance(res.value, float)


def test_expected_shortfall_negative_zero_publishes_zero():
    """F-RISK-002: zero tail losses must publish +0.0 in value and threshold."""
    returns_21 = [
        0.0, 0.0, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07,
        0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18,
    ]
    res = expected_shortfall(ReturnsInputs(returns=returns_21, confidence=0.95))
    assert repr(res.value) == "0.0"
    assert "-0.0000" not in res.interpretation
    assert "-0.0000" not in res.context
    assert "VaR threshold was 0.0000%" in res.context


# ---------------------------------------------------------------------------
# parametric_var
# ---------------------------------------------------------------------------

def test_parametric_var_golden_value():
    res = parametric_var(ParametricVaRInputs(
        portfolio_value=1_000_000, vol_annualized=0.20,
        confidence=0.99, horizon_days=10, periods_per_year=252,
    ))
    assert res.value["var_pct"] == pytest.approx(9.2684, abs=1e-4)
    assert res.value["var_amount"] == pytest.approx(92683.92, abs=1e-2)
    assert res.value["z_score"] == pytest.approx(2.326348, abs=1e-6)


def test_parametric_var_sqrt_time_scaling():
    one = parametric_var(ParametricVaRInputs(
        portfolio_value=1_000_000, vol_annualized=0.20, confidence=0.99,
        horizon_days=1, periods_per_year=252,
    ))
    ten = parametric_var(ParametricVaRInputs(
        portfolio_value=1_000_000, vol_annualized=0.20, confidence=0.99,
        horizon_days=10, periods_per_year=252,
    ))
    # 10-day VaR should be sqrt(10) x the 1-day VaR (independent returns).
    # Both amounts are stored rounded to 2 dp, so compare the ratio (robust to
    # the rounding of each) and the exact formula against the rounded 10-day one.
    ratio = ten.value["var_amount"] / one.value["var_amount"]
    assert ratio == pytest.approx(math.sqrt(10), abs=5e-3)
    z = z_score_for_confidence(0.99)
    expected_amount = z * 0.20 * math.sqrt(10 / 252) * 1_000_000
    assert ten.value["var_amount"] == pytest.approx(expected_amount, abs=0.01)


def test_parametric_var_warns_on_sqrt_time_when_horizon_gt_1():
    res = parametric_var(ParametricVaRInputs(
        portfolio_value=1_000_000, vol_annualized=0.20, confidence=0.99,
        horizon_days=10, periods_per_year=252,
    ))
    assert any("sqrt" in w.lower() for w in res.warnings)


def test_parametric_var_warns_on_normal_assumption():
    res = parametric_var(ParametricVaRInputs(
        portfolio_value=1_000_000, vol_annualized=0.20, confidence=0.95,
        horizon_days=1, periods_per_year=252,
    ))
    assert any("fat-tailed" in w.lower() or "normal" in w.lower() for w in res.warnings)


# ---------------------------------------------------------------------------
# realized_vol_simple
# ---------------------------------------------------------------------------

_RV_21 = [
    0.01, -0.02, 0.015, -0.005, 0.0, 0.03, -0.01, 0.02,
    0.012, -0.008, 0.005, 0.0, -0.015, 0.02, 0.01, -0.01,
    0.008, -0.02, 0.014, 0.0, 0.005,
]


def test_realized_vol_golden_value():
    res = realized_vol_simple(RealizedVolInputs(
        returns=_RV_21, window=21, periods_per_year=252
    ))
    assert res.value == pytest.approx(21.6377, abs=1e-4)


def test_realized_vol_ddof1_not_ddof0():
    # ddof=1 std of the sample; a ddof=0 computation would differ materially.
    res = realized_vol_simple(RealizedVolInputs(
        returns=_RV_21, window=21, periods_per_year=252
    ))
    n = len(_RV_21)
    mean = sum(_RV_21) / n
    var_ddof1 = sum((x - mean) ** 2 for x in _RV_21) / (n - 1)
    expected = math.sqrt(var_ddof1) * math.sqrt(252) * 100
    assert res.value == pytest.approx(expected, abs=1e-4)


def test_realized_vol_window_larger_than_series_raises():
    with pytest.raises(ValueError):
        realized_vol_simple(RealizedVolInputs(
            returns=_RV_21[:10], window=21, periods_per_year=252
        ))


# ---------------------------------------------------------------------------
# portfolio_volatility_two_asset
# ---------------------------------------------------------------------------

def test_two_asset_golden_value():
    res = portfolio_volatility_two_asset(TwoAssetPortfolioInputs(
        w1=0.6, w2=0.4, vol1=0.15, vol2=0.25, correlation=0.3
    ))
    assert res.value == pytest.approx(0.153297, abs=1e-6)


def test_two_asset_no_diversification_at_rho_1():
    res = portfolio_volatility_two_asset(TwoAssetPortfolioInputs(
        w1=0.6, w2=0.4, vol1=0.15, vol2=0.25, correlation=1.0
    ))
    # At rho=1 the cross term makes it exactly the weighted sum of parts.
    assert res.value == pytest.approx(0.6 * 0.15 + 0.4 * 0.25, abs=1e-9)


def test_two_asset_diversification_benefit_positive_for_rho_below_1():
    res = portfolio_volatility_two_asset(TwoAssetPortfolioInputs(
        w1=0.6, w2=0.4, vol1=0.15, vol2=0.25, correlation=0.3
    ))
    weighted = 0.6 * 0.15 + 0.4 * 0.25
    assert res.value < weighted  # diversification reduced risk


def test_two_asset_rho_minus_1_lowers_vol():
    res = portfolio_volatility_two_asset(TwoAssetPortfolioInputs(
        w1=0.6, w2=0.4, vol1=0.15, vol2=0.25, correlation=-1.0
    ))
    # (0.6*0.15 - 0.4*0.25)^2 = (0.09 - 0.10)^2 = 0.0001 -> sqrt = 0.01
    assert res.value == pytest.approx(0.01, abs=1e-9)


# ---------------------------------------------------------------------------
# portfolio_volatility_n_asset
# ---------------------------------------------------------------------------

_N_W = [0.5, 0.3, 0.2]
_N_COV = [
    [0.04, 0.01, 0.0],
    [0.01, 0.09, 0.02],
    [0.0, 0.02, 0.16],
]


def test_n_asset_golden_value():
    res = portfolio_volatility_n_asset(_N_W, _N_COV)
    qf = sum(
        _N_W[i] * _N_COV[i][j] * _N_W[j]
        for i in range(3) for j in range(3)
    )
    assert res.value == pytest.approx(round(math.sqrt(qf), 6), abs=1e-6)


def test_n_asset_rejects_asymmetric_matrix():
    bad = [[0.04, 0.02, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.16]]
    with pytest.raises(ValueError):
        portfolio_volatility_n_asset(_N_W, bad)


def test_n_asset_rejects_weights_not_summing_to_one():
    with pytest.raises(ValueError):
        portfolio_volatility_n_asset([0.5, 0.3, 0.4], _N_COV)


def test_n_asset_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        portfolio_volatility_n_asset(_N_W, [[0.04, 0.01], [0.01, 0.09]])


def test_n_asset_rejects_negative_diagonal():
    bad = [[0.04, 0.01, 0.0], [0.01, -0.09, 0.02], [0.0, 0.02, 0.16]]
    with pytest.raises(ValueError):
        portfolio_volatility_n_asset(_N_W, bad)


# ---------------------------------------------------------------------------
# marginal_risk_contributions
# ---------------------------------------------------------------------------

def test_marginal_risk_shares_golden():
    res = marginal_risk_contributions(_N_W, _N_COV)
    shares = res.value["risk_contribution_pct"]
    assert shares == pytest.approx(
        [38.461538, 36.120401, 25.41806], abs=1e-4
    )


def test_marginal_risk_shares_sum_to_100():
    res = marginal_risk_contributions(_N_W, _N_COV)
    assert sum(res.value["risk_contribution_pct"]) == pytest.approx(100.0, abs=1e-6)


def test_marginal_risk_contributions_sum_to_variance_euler():
    # Unnormalised contributions must sum to the portfolio VARIANCE (Euler),
    # not the volatility. This is the property the module asserts internally.
    res = marginal_risk_contributions(_N_W, _N_COV)
    contribs = res.value["risk_contributions"]
    variance = sum(
        _N_W[i] * _N_COV[i][j] * _N_W[j]
        for i in range(3) for j in range(3)
    )
    assert sum(contribs) == pytest.approx(variance, abs=1e-9)


def test_marginal_risk_flags_overcontributing_position():
    res = marginal_risk_contributions(
        [0.9, 0.05, 0.05],
        [[0.04, 0.03, 0.0], [0.03, 0.09, 0.0], [0.0, 0.0, 0.16]],
    )
    assert any("risk" in w.lower() and "notional" in w.lower() for w in res.warnings)


def test_marginal_risk_rejects_zero_variance_portfolio():
    with pytest.raises(ValueError):
        marginal_risk_contributions([0.5, 0.5], [[0.0, 0.0], [0.0, 0.0]])


# ---------------------------------------------------------------------------
# monte_carlo_var  (cross-checked against an independent numpy reimplementation)
# ---------------------------------------------------------------------------

def _corr_to_cov(corr, vols):
    n = len(vols)
    return [[corr[i][j] * vols[i] * vols[j] for j in range(n)] for i in range(n)]


def _uniform_stress(corr, target):
    n = len(corr)
    out = [[1.0 if i == j else corr[i][j] for j in range(n)] for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            r = max(corr[i][j], target)
            out[i][j] = r
            out[j][i] = r
    return out


def _ref_simulate(cov, weights, n_sims, hscale, seed):
    L = np.linalg.cholesky(np.asarray(cov, float))
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_sims, len(weights)))
    correlated = z @ L.T
    factor_pnl = correlated * hscale
    return (factor_pnl @ np.asarray(weights, float)).tolist()


def _ref_loss_quantile(pnls, conf):
    ordered = sorted(pnls)
    pos = (len(ordered) - 1) * (1.0 - conf)
    lo = math.floor(pos); hi = math.ceil(pos)
    if lo == hi:
        q = ordered[lo]
    else:
        w = pos - lo
        q = ordered[lo] * (1 - w) + ordered[hi] * w
    return -q


def _ref_es(pnls, var_loss):
    tail = [v for v in pnls if v <= -var_loss]
    if not tail:
        tail = [min(pnls)]
    return -sum(tail) / len(tail)


def _ref_diversification_ratio(weights, cov):
    w = np.asarray(weights, float); m = np.asarray(cov, float)
    sigma = np.sqrt(np.diag(m))
    standalone = float(np.sum(np.abs(w) * sigma))
    if standalone == 0.0:
        return 1.0
    var = float(w @ m @ w)
    return math.sqrt(max(var, 0.0)) / standalone


_MC_cfg = dict(
    weights=[0.6, 0.4],
    factor_volatilities=[0.18, 0.12],
    normal_correlations=[[1.0, 0.5], [0.5, 1.0]],
    portfolio_value=1_000_000.0,
    confidence=0.95,
    horizon_days=10,
    n_sims=5000,
    seed=42,
    periods_per_year=252,
)
_MC_stress_target = 0.9


def test_monte_carlo_matches_independent_reimplementation():
    svm = get_settings().risk.monte_carlo.stressed_volatility_multiplier
    res = monte_carlo_var(
        MonteCarloVaRInputs(**_MC_cfg), stressed_correlation=_MC_stress_target
    )
    v = res.value

    hscale = math.sqrt(_MC_cfg["horizon_days"] / _MC_cfg["periods_per_year"])
    normal_cov = _corr_to_cov(_MC_cfg["normal_correlations"], _MC_cfg["factor_volatilities"])
    stressed_vols = [x * svm for x in _MC_cfg["factor_volatilities"]]
    stressed_cov = _corr_to_cov(
        _uniform_stress(_MC_cfg["normal_correlations"], _MC_stress_target), stressed_vols
    )
    npn = _ref_simulate(normal_cov, _MC_cfg["weights"], _MC_cfg["n_sims"], hscale, _MC_cfg["seed"])
    spn = _ref_simulate(stressed_cov, _MC_cfg["weights"], _MC_cfg["n_sims"], hscale, _MC_cfg["seed"])
    var_n = _ref_loss_quantile(npn, _MC_cfg["confidence"])
    var_s = _ref_loss_quantile(spn, _MC_cfg["confidence"])
    es_n = _ref_es(npn, var_n)
    es_s = _ref_es(spn, var_s)

    assert v["var_normal_pct"] == pytest.approx(var_n * 100, abs=1e-4)
    assert v["var_stressed_pct"] == pytest.approx(var_s * 100, abs=1e-4)
    assert v["es_normal_pct"] == pytest.approx(es_n * 100, abs=1e-4)
    assert v["es_stressed_pct"] == pytest.approx(es_s * 100, abs=1e-4)
    assert v["stressed_to_normal_ratio"] == pytest.approx(var_s / var_n, abs=1e-4)
    assert v["diversification_ratio_normal"] == pytest.approx(
        _ref_diversification_ratio(_MC_cfg["weights"], normal_cov), abs=1e-4
    )


def test_monte_carlo_is_reproducible_with_fixed_seed():
    a = monte_carlo_var(
        MonteCarloVaRInputs(**_MC_cfg), stressed_correlation=_MC_stress_target
    )
    b = monte_carlo_var(
        MonteCarloVaRInputs(**_MC_cfg), stressed_correlation=_MC_stress_target
    )
    assert a.value["var_normal_pct"] == b.value["var_normal_pct"]
    assert a.value["seed"] == _MC_cfg["seed"]


def test_monte_carlo_stress_increases_loss():
    res = monte_carlo_var(
        MonteCarloVaRInputs(**_MC_cfg), stressed_correlation=_MC_stress_target
    )
    v = res.value
    assert v["var_stressed_pct"] > v["var_normal_pct"]
    assert v["stressed_to_normal_ratio"] > 1.0


def test_monte_carlo_diversification_ratio_in_unit_interval():
    res = monte_carlo_var(
        MonteCarloVaRInputs(**_MC_cfg), stressed_correlation=_MC_stress_target
    )
    v = res.value
    assert 0.0 < v["diversification_ratio_normal"] <= 1.0
    assert 0.0 < v["diversification_ratio_stressed"] <= 1.0


def test_monte_carlo_requires_stress_target():
    with pytest.raises(ValueError):
        monte_carlo_var(MonteCarloVaRInputs(**_MC_cfg))


def test_monte_carlo_requires_correlation_target_with_transform():
    def fake_transform(cov, target, *, only_correlations_that_rise=False):
        return cov
    with pytest.raises(ValueError):
        monte_carlo_var(
            MonteCarloVaRInputs(**_MC_cfg),
            stress_correlations=fake_transform,
        )


def test_monte_carlo_prunes_zero_volatility_factor():
    cfg = dict(_MC_cfg)
    cfg["factor_volatilities"] = [0.18, 0.0]  # second factor is dead weight
    res = monte_carlo_var(
        MonteCarloVaRInputs(**cfg), stressed_correlation=_MC_stress_target
    )
    assert any("zero volatility" in w.lower() and "dropped" in w.lower()
               for w in res.warnings)


def test_monte_carlo_all_zero_vol_raises():
    cfg = dict(_MC_cfg)
    cfg["factor_volatilities"] = [0.0, 0.0]
    with pytest.raises(ValueError):
        monte_carlo_var(
            MonteCarloVaRInputs(**cfg), stressed_correlation=_MC_stress_target
        )


def test_monte_carlo_rejects_non_psd_correlation_matrix():
    cfg = dict(_MC_cfg)
    # Pairwise-infeasible correlations (det < 0) -> Cholesky fails -> refused.
    cfg["normal_correlations"] = [
        [1.0, 0.9, 0.9],
        [0.9, 1.0, -0.9],
        [0.9, -0.9, 1.0],
    ]
    cfg["factor_volatilities"] = [0.18, 0.12, 0.10]
    with pytest.raises(ValueError):
        monte_carlo_var(
            MonteCarloVaRInputs(**cfg), stressed_correlation=0.9
        )


def test_monte_carlo_rejects_non_unit_diagonal():
    cfg = dict(_MC_cfg)
    cfg["normal_correlations"] = [[0.5, 0.5], [0.5, 1.0]]
    with pytest.raises(ValueError):
        MonteCarloVaRInputs(**cfg)


def test_monte_carlo_rejects_asymmetric_correlation():
    cfg = dict(_MC_cfg)
    cfg["normal_correlations"] = [[1.0, 0.4], [0.6, 1.0]]
    with pytest.raises(ValueError):
        MonteCarloVaRInputs(**cfg)


def test_monte_carlo_rejects_offdiagonal_outside_unit_interval():
    cfg = dict(_MC_cfg)
    cfg["normal_correlations"] = [[1.0, 1.5], [1.5, 1.0]]
    with pytest.raises(ValueError):
        MonteCarloVaRInputs(**cfg)


def test_monte_carlo_rejects_negative_volatility():
    cfg = dict(_MC_cfg)
    cfg["factor_volatilities"] = [-0.18, 0.12]
    with pytest.raises(ValueError):
        MonteCarloVaRInputs(**cfg)


def test_monte_carlo_rejects_ragged_correlation_matrix():
    cfg = dict(_MC_cfg)
    cfg["normal_correlations"] = [[1.0, 0.5], [0.5, 1.0, 0.0]]
    with pytest.raises(ValueError):
        MonteCarloVaRInputs(**cfg)
