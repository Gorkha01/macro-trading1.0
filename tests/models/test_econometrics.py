"""Hand-computed verification tests for models/econometrics.py (Module 17).

Every expected value below is derived BY HAND from the formula and config/settings.yaml
(read, not assumed):

  OLS:            y = a + b*x  -> beta['const']=a, beta['x']=b, R^2 exact for perfect fit
  confidence:     base 0.70 - heuristic_penalty 0.20 (low_r_squared_threshold is
                  uncalibrated_illustrative) = 0.50; no unobservable, source_indep 0
  half-life:      AR(1) dz = phi*z_{t-1} + e  ->  H = -ln(2)/phi
                  phi=-0.5  ->  H = 2*ln(2) = 1.38629...
  econometrics.min_observations = 8          (degenerate/saturated fit refusal)
  regime.boundaries: phi >= 0 (no reversion) and phi <= -1 (aliasing) are refused

These are REAL-WORLD checks: the OLS coefficients and the half-life derivation are
verified against their closed forms, not against a mirror of the code.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from macro_engine.config import get_settings
from macro_engine.models.econometrics import (
    _cointegration_thresholds_calibrated,
    _estimate_half_life,
    _half_life_disclosure,
    _multiple_testing_summary,
    _pca_choices_calibrated,
    _pca_panel_suspicion,
    _pca_warnings,
    _stationarity_thresholds_calibrated,
    compute_pca,
    kalman_latent_state,
    run_regression,
)
from macro_engine.models.econometrics import (
    # Aliased: the module's own functions are literally named ``test_*``, so a
    # bare import would make pytest collect them as tests of THIS module.
    test_cointegration as cointegration,
)
from macro_engine.models.econometrics import test_stationarity as stationarity

MECHANISM = "a clearly stated economic mechanism for the regression under test here"


# ---------------------------------------------------------------------------
# run_regression — OLS hand-computed
# ---------------------------------------------------------------------------
def test_run_regression_ols_perfect_fit():
    # y = 1 + 2*x exactly, over 8 points (>= min_observations=8).
    x = list(range(8))
    y = [1.0 + 2.0 * xi for xi in x]
    res = run_regression(
        pd.Series(y, name="y"),
        pd.DataFrame({"x": x}),
        require_mechanism=MECHANISM,
    )
    assert res.beta["const"] == pytest.approx(1.0, abs=1e-6)
    assert res.beta["x"] == pytest.approx(2.0, abs=1e-6)
    assert res.r_squared == pytest.approx(1.0, abs=1e-9)
    assert res.n_obs == 8
    # confidence: 0.70 - 0.20 (heuristic, R^2 floor uncalibrated) = 0.50
    assert res.confidence == 0.50


def test_run_regression_requires_mechanism():
    y = [1.0 + 2.0 * xi for xi in range(8)]
    with pytest.raises(ValueError, match="require_mechanism"):
        run_regression(
            pd.Series(y, name="y"),
            pd.DataFrame({"x": list(range(8))}),
            require_mechanism="short",  # < mechanism_min_length (20)
        )


def test_run_regression_refuses_below_min_observations():
    # 4 rows < min_observations (8).
    with pytest.raises(ValueError, match="observations is below the configured floor"):
        run_regression(
            pd.Series([1.0, 2.0, 3.0, 4.0], name="y"),
            pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0]}),
            require_mechanism=MECHANISM,
        )


def test_run_regression_refuses_degenerate_fit():
    # 8 rows, 8 regressors -> n_params = 9 (const + 8), n_obs=8 <= 9.
    n = 8
    cols = {f"a{i}": [float(j) + 0.1 * i for j in range(n)] for i in range(n)}
    with pytest.raises(ValueError, match="Degenerate fit refused"):
        run_regression(
            pd.Series([float(j) for j in range(n)], name="y"),
            pd.DataFrame(cols),
            require_mechanism=MECHANISM,
        )


def test_run_regression_refuses_rank_deficient():
    # 9 rows, two identical regressor columns -> rank < n_params.
    n = 9
    a = list(range(n))
    with pytest.raises(ValueError, match="rank-deficient"):
        run_regression(
            pd.Series([float(j) for j in range(n)], name="y"),
            pd.DataFrame({"a": a, "b": list(a)}),  # b is an exact copy of a
            require_mechanism=MECHANISM,
        )


def test_run_regression_refuses_mismatched_length():
    with pytest.raises(ValueError, match="same number of rows"):
        run_regression(
            pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], name="y"),
            pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}),
            require_mechanism=MECHANISM,
        )


def test_run_regression_refuses_duplicate_column_name():
    n = 8
    # A dict collapses duplicate keys; build the 2-col frame with explicit labels.
    df = pd.DataFrame(
        np.array([list(range(n)), list(range(n))]).T,
        columns=["x", "x"],
    )
    with pytest.raises(ValueError, match="duplicate column name"):
        run_regression(
            pd.Series([float(j) for j in range(n)], name="y"),
            df,
            require_mechanism=MECHANISM,
        )


def test_run_regression_refuses_non_finite_y():
    y = [1.0, 2.0, 3.0, float("nan"), 5.0, 6.0, 7.0, 8.0]
    with pytest.raises(ValueError, match="non-finite"):
        run_regression(
            pd.Series(y, name="y"),
            pd.DataFrame({"x": list(range(8))}),
            require_mechanism=MECHANISM,
        )


# ---------------------------------------------------------------------------
# _estimate_half_life — H = -ln(2)/phi, derived; refusals at the boundaries
# ---------------------------------------------------------------------------
def test_half_life_none_spread_is_refused_not_silent():
    hl = _estimate_half_life(None)
    assert hl["periods"] is None
    assert hl["phi"] is None
    assert "Johansen" in hl["note"] or "normalised" in hl["note"]


def test_half_life_too_short_is_refused():
    hl = _estimate_half_life(pd.Series([1.0, 2.0]))
    assert hl["periods"] is None


def test_half_life_non_negative_phi_refused():
    # Geometric growth z_t = 1.1^t -> dz = 0.1*z_{t-1}, so phi = 0.1 > 0:
    # the spread ACCUMULATES deviation, which has no half-life and must be refused.
    z = np.array([1.1**t for t in range(50)], dtype=float)
    hl = _estimate_half_life(pd.Series(z))
    assert hl["periods"] is None
    assert hl["phi"] is not None
    assert hl["phi"] > 0


def test_half_life_alternating_phi_refused():
    # Perfect alternation -> rho = -1, phi <= -1, below the sampling floor.
    hl = _estimate_half_life(pd.Series([(-1.0) ** t for t in range(50)]))
    assert hl["periods"] is None


def test_half_life_sample_length_bound_refused():
    # A perfectly straight spread fits phi to a value a hair below zero
    # (floating-point), which slips past `phi >= 0` and would otherwise return a
    # half-life of ~5e17 periods. The sample-length guard must refuse it.
    hl = _estimate_half_life(pd.Series(np.arange(50.0)))
    assert hl["periods"] is None
    assert "LONGER than the" in hl["note"]


def test_half_life_closed_form_phi_minus_half():
    # Simulate z_t = 0.5*z_{t-1} + e (rho=0.5 -> phi=-0.5 -> H=2*ln2=1.38629).
    rng = np.random.default_rng(20260929)
    n = 20000
    z = np.zeros(n)
    e = rng.standard_normal(n)
    for t in range(1, n):
        z[t] = 0.5 * z[t - 1] + e[t]
    hl = _estimate_half_life(pd.Series(z))
    assert hl["periods"] is not None
    # phi should be approximately -0.5, half-life approximately 1.386.
    assert hl["phi"] == pytest.approx(-0.5, abs=0.01)
    assert hl["periods"] == pytest.approx(-math.log(2.0) / (-0.5), abs=0.03)


# ---------------------------------------------------------------------------
# compute_pca — sign-rule convention, unit-norm loadings, ratio sum, refusals
# ---------------------------------------------------------------------------
def _three_var_panel(seed: int = 1, n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.standard_normal(n),
            "b": rng.standard_normal(n),
            "c": rng.standard_normal(n),
        }
    )


def test_pca_sign_rule_makes_largest_abs_loading_positive():
    res = compute_pca(_three_var_panel(), n_components=3)
    loadings = res.value["loadings"]
    for pc in ("PC1", "PC2", "PC3"):
        vals = list(loadings[pc].values())
        idx = int(np.argmax(np.abs(vals)))
        assert vals[idx] > 0, f"{pc} max-|loading| element should be positive"


def test_pca_loadings_are_unit_norm():
    res = compute_pca(_three_var_panel(), n_components=3)
    loadings = res.value["loadings"]
    for pc in ("PC1", "PC2", "PC3"):
        norm = math.sqrt(sum(v * v for v in loadings[pc].values()))
        assert norm == pytest.approx(1.0, abs=1e-6)


def test_pca_explained_variance_ratios_sum_to_one():
    res = compute_pca(_three_var_panel(), n_components=3)
    ratios = res.value["explained_variance_ratios"]
    assert sum(ratios) == pytest.approx(1.0, abs=1e-9)
    # cumulative is monotonic and ends at 1.0
    cum = res.value["cumulative_explained_variance"]
    assert cum[-1] == pytest.approx(1.0, abs=1e-9)
    assert cum[0] <= cum[1] <= cum[2]


def test_pca_n_components_explained_variance_matches_first_components():
    res = compute_pca(_three_var_panel(), n_components=2)
    ratios = res.value["explained_variance_ratios"]
    assert res.value["n_components_explained_variance"] == pytest.approx(sum(ratios[:2]), abs=1e-9)


def test_pca_refuses_more_components_than_variables():
    with pytest.raises(ValueError, match="component"):
        compute_pca(_three_var_panel(), n_components=4)


def test_pca_refuses_zero_components():
    with pytest.raises(ValueError, match="component"):
        compute_pca(_three_var_panel(), n_components=0)


def test_pca_refuses_constant_column():
    df = _three_var_panel()
    df["d"] = 4.2  # a constant column
    with pytest.raises(ValueError):
        compute_pca(df, n_components=3)


def test_pca_refuses_rank_deficient_panel():
    df = _three_var_panel()
    df["dup"] = df["a"]  # exact duplicate column -> rank-deficient
    with pytest.raises(ValueError, match="rank-deficient"):
        compute_pca(df, n_components=3)


def test_pca_refuses_non_finite_panel():
    df = _three_var_panel()
    df.iloc[0, 0] = float("nan")
    with pytest.raises(ValueError):
        compute_pca(df, n_components=3)


# ===========================================================================
# test_stationarity — the inverted ADF/KPSS nulls, the four verdicts, and the
# two disclosures (KPSS clipping, ADF rank-deficiency).
#
# Every fixture below was found by sweeping seeds rather than by taking the
# first candidate that produced the desired verdict: D-094 measured that a
# genuine random walk can *reject* a unit root (ADF low power), so a "random
# walk" fixture is not reliably non-stationary. The seeds are pinned, and each
# asserted verdict was re-measured before being written down.
# ===========================================================================
def _white_noise(n: int = 400, seed: int = 0) -> pd.Series:
    return pd.Series(np.random.default_rng(seed).normal(0, 1, n), name="wn")


def _random_walk(n: int = 400, seed: int = 1) -> pd.Series:
    return pd.Series(np.cumsum(np.random.default_rng(seed).normal(0, 1, n)), name="rw")


def _ar1(rho: float, n: int, seed: int) -> pd.Series:
    """A stationary AR(1): z_t = rho*z_{t-1} + e_t, with no leading NaN."""
    rng = np.random.default_rng(seed)
    z = np.zeros(n)
    e = rng.normal(0, 1, n)
    for t in range(1, n):
        z[t] = rho * z[t - 1] + e[t]
    return pd.Series(z, name="ar")


def test_stationarity_white_noise_reads_stationary():
    v = stationarity(_white_noise()).value
    assert v["verdict"] == "stationary"
    assert v["adf_rejects_unit_root"] is True
    assert v["kpss_rejects_stationarity"] is False


def test_stationarity_random_walk_reads_non_stationary():
    v = stationarity(_random_walk()).value
    assert v["verdict"] == "non_stationary"
    assert v["adf_rejects_unit_root"] is False
    assert v["kpss_rejects_stationarity"] is True


def test_stationarity_persistent_ar_reads_inconclusive_low_power():
    # AR(0.9) is stationary but ADF's low power against a near-unit-root
    # alternative leaves BOTH tests failing to reject: an absence of evidence,
    # not evidence of stationarity. Measured seed 10 at n=120.
    v = stationarity(_ar1(0.9, 120, 10)).value
    assert v["verdict"] == "inconclusive_low_power"
    assert v["adf_rejects_unit_root"] is False
    assert v["kpss_rejects_stationarity"] is False


def test_stationarity_conflicting_tests_read_inconclusive_conflict():
    # A more persistent sample of the SAME process makes both tests reject —
    # the signature of fractional integration or a structural break. The two
    # inconclusive kinds must stay distinct. Measured seed 10 at n=400.
    v = stationarity(_ar1(0.9, 400, 10)).value
    assert v["verdict"] == "inconclusive_conflict"
    assert v["adf_rejects_unit_root"] is True
    assert v["kpss_rejects_stationarity"] is True


def test_stationarity_publishes_both_statistics_lags_and_size():
    v = stationarity(_white_noise()).value
    for key in (
        "adf_statistic",
        "adf_p_value",
        "adf_used_lag",
        "kpss_statistic",
        "kpss_p_value",
        "kpss_lags",
        "significance_level",
    ):
        assert key in v
    assert v["significance_level"] == float(get_settings().econometrics.significance_level.value)


def test_stationarity_kpss_clipping_is_disclosed():
    # White noise drives the KPSS statistic into the look-up table's upper edge,
    # so its p-value is a BOUND (0.10), not a point estimate. The result must
    # say so; comparing the number against 0.01/0.10 would be guessing.
    res = stationarity(_white_noise())
    assert res.value["kpss_p_value_is_clipped"] is True
    assert res.value["kpss_p_value"] == pytest.approx(0.10)
    assert any("BOUND, NOT A POINT ESTIMATE" in w for w in res.warnings)


def test_stationarity_adf_ill_conditioning_is_disclosed():
    # A deterministic sine makes ADF's internal lag-augmented regression
    # rank-deficient (statsmodels raises SingularMatrixWarning) while still
    # returning a statistic — exactly why it must be disclosed.
    t = np.linspace(0, 20 * np.pi, 400)
    res = stationarity(pd.Series(np.sin(t), name="sine"))
    assert res.value["adf_design_was_ill_conditioned"] is True
    assert any("RANK-DEFICIENT" in w for w in res.warnings)


def test_stationarity_agreement_emits_no_inconclusive_warning():
    # Negative control: on a clean stationary series neither inconclusive
    # warning may fire (the ill-conditioning and clip disclosures are separate).
    res = stationarity(_white_noise())
    assert not any("CONTRADICT" in w for w in res.warnings)
    assert not any("NEITHER TEST REJECTS" in w for w in res.warnings)


def test_stationarity_refuses_constant():
    with pytest.raises(ValueError, match="constant"):
        stationarity(pd.Series([4.2] * 400, name="c"))


def test_stationarity_refuses_too_short():
    with pytest.raises(ValueError, match="below the configured floor"):
        stationarity(pd.Series(np.arange(10.0), name="short"))


def test_stationarity_refuses_non_finite():
    bad = _white_noise()
    bad.iloc[3] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        stationarity(bad)


def test_stationarity_refuses_non_numeric():
    with pytest.raises(ValueError, match="numeric"):
        stationarity(pd.Series(["a"] * 40, name="text"))


def test_stationarity_refuses_empty():
    with pytest.raises(ValueError, match="empty"):
        stationarity(pd.Series([], dtype="float64", name="empty"))


def test_stationarity_refuses_non_series():
    with pytest.raises(TypeError, match="pandas Series"):
        stationarity([1.0, 2.0, 3.0])  # type: ignore[arg-type]


def test_stationarity_direction_is_unset_and_unit_is_categorical():
    res = stationarity(_white_noise())
    assert res.direction is None
    assert "categorical" in res.unit
    assert len(res.assumptions) >= 3
    assert len(res.limitations) >= 3
    assert res.data_provenance  # D-132: provenance must be published


# ---------------------------------------------------------------------------
# F-EC-003: the confidence's heuristic flag must be computed from the leaves
# THIS function reads.
# ---------------------------------------------------------------------------
def test_stationarity_confidence_carries_no_heuristic_penalty():
    # test_stationarity leans on no `uncalibrated_illustrative` leaf (both
    # significance_level and stationarity_min_observations are `conventional`),
    # so §22.8 requires the flag be False and the confidence be the base 0.70.
    # Before F-EC-003 the flag was wired to `_r_squared_floor_is_calibrated()`
    # — which reads `low_r_squared_threshold`, a leaf this function never
    # consumes — so the confidence was 0.70 - 0.20 = 0.50.
    res = stationarity(_white_noise())
    base = get_settings().confidence.values["base"]
    assert res.confidence == pytest.approx(float(base), abs=1e-9)
    assert res.confidence == pytest.approx(0.70, abs=1e-9)


def test_stationarity_calibration_helper_reads_the_stationarity_leaves():
    # If the helper read the R-squared leaf instead (the pre-fix coupling),
    # this would return False while `expected` is True — a real discriminator,
    # because `low_r_squared_threshold` is `uncalibrated_illustrative`.
    settings = get_settings()
    expected = bool(
        settings.is_calibrated("econometrics.significance_level")
        and settings.is_calibrated("econometrics.stationarity_min_observations")
    )
    assert bool(_stationarity_thresholds_calibrated()) is expected
    assert expected is True  # both leaves are `conventional` today


# ===========================================================================
# test_cointegration — the SPREAD, the half-life, the regime-stability check,
# the two mandatory warnings, and the three refused silent-failure paths.
# ===========================================================================
def _cointegrated_pair(n: int = 400, seed: int = 42) -> tuple[pd.Series, pd.Series]:
    """y = 2*x + AR(1)-persistent spread, so the half-life is ESTIMABLE.

    The spread is an AR(1) with rho = 0.8, i.e. fitted phi ~ -0.2 and a
    half-life near ln(2)/0.2 = 3.466 periods. An iid-noise spread (rho = 0)
    would fit phi <= -1 and be refused, which is a different test.
    """
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(0, 1, n))
    spread = np.zeros(n)
    e = rng.normal(0, 1, n)
    for t in range(1, n):
        spread[t] = 0.8 * spread[t - 1] + e[t]
    y = 2.0 * x + spread
    idx = pd.date_range("2000-01-01", periods=n, freq="D")
    return pd.Series(y, index=idx, name="y"), pd.Series(x, index=idx, name="x")


def _independent_pair(n: int = 300, seed: int = 99) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2000-01-01", periods=n, freq="D")
    y = pd.Series(np.cumsum(rng.normal(0, 1, n)), index=idx, name="y")
    x = pd.Series(np.cumsum(rng.normal(0, 1, n)), index=idx, name="x")
    return y, x


def test_cointegration_rejects_a_cointegrated_pair():
    y, x = _cointegrated_pair()
    v = cointegration(y, x).value
    assert v["is_cointegrated"] is True
    assert v["method"] == "engle_granger"
    assert v["statistic"] < v["critical_values"][1]  # beyond the 5% critical value
    assert v["n_obs"] == 400


def test_cointegration_hedge_ratio_recovers_the_true_slope():
    y, x = _cointegrated_pair()
    v = cointegration(y, x).value
    # True beta is 2.0; the first-step regression recovers it to sampling error.
    assert v["hedge_ratio"] == pytest.approx(2.0, abs=0.1)


def test_cointegration_spread_is_the_series_the_statistic_came_from():
    # Section 9's shared-basis requirement: the published spread must be the
    # residual coint tested, not a lookalike. Both statistics round to 6 dp,
    # and the raw values agree to 1e-10.
    y, x = _cointegrated_pair()
    v = cointegration(y, x).value
    assert len(v["spread"]) == 400
    assert v["spread_adf_statistic"] == pytest.approx(v["statistic"], abs=1e-6)
    assert v["spread_is_stationary"] is True


def test_cointegration_half_life_matches_the_closed_form():
    y, x = _cointegrated_pair()
    v = cointegration(y, x).value
    phi = v["half_life_phi"]
    assert phi is not None and -1.0 < phi < 0.0
    # H = -ln(2)/phi, and the estimate should be near the true 3.466 periods.
    assert v["half_life_periods"] == pytest.approx(-math.log(2.0) / phi, abs=1e-6)
    assert v["half_life_periods"] == pytest.approx(3.466, abs=0.6)


def test_cointegration_does_not_reject_independent_walks():
    y, x = _independent_pair()
    v = cointegration(y, x).value
    assert v["is_cointegrated"] is False
    assert v["p_value"] > 0.05


def test_cointegration_mandatory_warnings_fire_on_every_call():
    # §15.18-F makes BOTH warnings unconditional, and their ORDER is part of the
    # contract: a "top warning" UI must not be able to drop them.
    for y, x in (_cointegrated_pair(), _independent_pair()):
        w = cointegration(y, x).warnings
        assert "BACKWARD-LOOKING" in w[0]
        assert "MULTIPLE-TESTING CORRECTION" in w[1]


def test_cointegration_multiple_testing_numbers_are_sidak():
    alpha, m = 0.05, 10
    mt = _multiple_testing_summary(alpha=alpha, family_size=m)
    assert mt["family_wise_error_rate"] == pytest.approx(1 - (1 - alpha) ** m, abs=1e-8)
    assert mt["corrected_size"] == pytest.approx(1 - (1 - alpha) ** (1 / m), abs=1e-8)
    # The documented figures: 1 - 0.95**10 = 0.40126306, and the Sidak size.
    assert mt["family_wise_error_rate"] == pytest.approx(0.40126306, abs=1e-8)
    assert mt["corrected_size"] == pytest.approx(0.0051162, abs=1e-8)


def test_cointegration_publishes_the_assumed_family_size():
    y, x = _cointegrated_pair()
    v = cointegration(y, x).value
    assert v["family_size_assumed"] == int(
        get_settings().econometrics.assumed_test_family_size.value
    )
    assert v["family_wise_error_rate"] == pytest.approx(0.40126306, abs=1e-8)


def test_cointegration_regime_stability_is_stable_for_a_solid_pair():
    y, x = _cointegrated_pair()
    v = cointegration(y, x).value
    assert v["regime_stability"] == "stable"
    assert v["regime_stability_agreement"] is True
    # D-139d: the sub-sample detail must be published, not dropped.
    assert v["regime_stability_split_index"] == 200
    assert v["regime_stability_first_half"] is not None
    assert v["regime_stability_second_half"] is not None


def test_cointegration_refuses_near_collinear_pair():
    # coint returns coint_t = -inf with p = 0.0 on a degenerate fit — the
    # strongest-looking and least reliable result — so it must refuse.
    _, x = _cointegrated_pair()
    y_exact = 2.0 * x
    with pytest.raises(ValueError, match="rank-deficient"):
        cointegration(y_exact, x)


def test_cointegration_refuses_unknown_method():
    y, x = _cointegrated_pair()
    with pytest.raises(ValueError, match="must be one of"):
        cointegration(y, x, method="granger")


def test_cointegration_refuses_non_string_method():
    y, x = _cointegrated_pair()
    with pytest.raises(TypeError, match="must be a string"):
        cointegration(y, x, method=True)  # type: ignore[arg-type]


def test_cointegration_refuses_too_few_observations():
    y, x = _cointegrated_pair()
    with pytest.raises(ValueError, match="below the configured floor"):
        cointegration(y.iloc[:40], x.iloc[:40])


def test_cointegration_refuses_mismatched_index():
    y, x = _cointegrated_pair()
    with pytest.raises(ValueError, match="identical index"):
        cointegration(y, x.reset_index(drop=True))


def test_cointegration_refuses_mismatched_length():
    y, x = _cointegrated_pair()
    with pytest.raises(ValueError, match="same number of rows"):
        cointegration(y, x.iloc[:-1])


def test_cointegration_refuses_non_finite():
    y, x = _cointegrated_pair()
    x = x.copy()
    x.iloc[5] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        cointegration(y, x)


def test_cointegration_refuses_constant_series():
    y, _ = _cointegrated_pair()
    x_const = pd.Series(np.ones(len(y)), index=y.index, name="x")
    with pytest.raises(ValueError, match="constant"):
        cointegration(y, x_const)


def test_cointegration_refuses_non_series():
    y, x = _cointegrated_pair()
    with pytest.raises(TypeError, match="pandas Series"):
        cointegration(list(y), x)  # type: ignore[arg-type]


def test_cointegration_johansen_publishes_no_spread_or_hedge():
    y, x = _cointegrated_pair()
    v = cointegration(y, x, method="johansen").value
    assert v["method"] == "johansen"
    assert v["is_cointegrated"] is True
    # Johansen estimates a VECTOR, not a normalised slope, so there is no
    # single spread — and None must not be confused with a zero.
    assert v["hedge_ratio"] is None
    assert v["spread"] == []
    assert v["half_life_periods"] is None
    assert v["n_obs"] == 400  # the test's rows, NOT len(spread) == 0


def test_cointegration_johansen_warns_that_it_reports_no_p_value():
    y, x = _cointegrated_pair()
    res = cointegration(y, x, method="johansen")
    assert math.isnan(res.value["p_value"])
    assert any("JOHANSEN REPORTS NO P-VALUE" in w for w in res.warnings)


def test_cointegration_direction_is_unset():
    y, x = _cointegrated_pair()
    res = cointegration(y, x)
    assert res.direction is None
    assert "dimensionless" in res.unit


# ===========================================================================
# kalman_latent_state — the three specifications, the published band, the
# filtered-vs-smoothed distinction, and the refusals.
# ===========================================================================
def _level_series(n: int = 150, seed: int = 20) -> np.ndarray:
    """A random-walk level observed with noise: the local-level use case."""
    rng = np.random.default_rng(seed)
    level = np.cumsum(rng.normal(0, 0.5, n))
    return level + rng.normal(0, 1.0, n)


def _level_frame(n: int = 150, seed: int = 20) -> pd.DataFrame:
    return pd.DataFrame({"obs": _level_series(n, seed)})


def _hedge_frame(n: int = 150, seed: int = 20) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, n)
    beta = np.linspace(0.2, 1.8, n)  # a large, clean drift
    y = beta * x + rng.normal(0, 0.05, n)
    return pd.DataFrame({"dep": y, "reg": x}), beta


def test_kalman_local_level_recovers_a_level_with_a_band():
    v = kalman_latent_state(_level_frame(), state_dim=1).value
    assert v["model_spec"] == "local_level"
    assert v["state_names"] == ["level"]
    assert v["converged"] is True
    assert v["estimated_variances"]["sigma2.level"] == pytest.approx(0.378891, abs=1e-5)
    assert v["estimated_variances"]["sigma2.irregular"] == pytest.approx(0.798983, abs=1e-5)
    latest = v["latest"]["level"]
    assert latest["std_error"] > 0.0
    assert latest["lower"] < latest["state"] < latest["upper"]


def test_kalman_local_linear_trend_has_two_states():
    v = kalman_latent_state(_level_frame(), state_dim=2).value
    assert v["model_spec"] == "local_linear_trend"
    assert v["state_names"] == ["level", "slope"]
    assert v["state_dim"] == 2
    # The slope's design is [1, 0], so it carries no information at t=0 and its
    # first band reflects the prior's scale — the reason approximate_diffuse is
    # used instead of the exact-diffuse route.
    assert v["filtered_state_std_error"]["slope"][0] == pytest.approx(
        v["prior_standard_error"]["slope"], rel=1e-6
    )


def test_kalman_time_varying_hedge_ratio_tracks_a_drifting_beta():
    frame, beta_true = _hedge_frame()
    res = kalman_latent_state(frame, state_dim=1)
    v = res.value
    assert v["model_spec"] == "time_varying_hedge_ratio"
    assert v["converged"] is True
    beta_hat = np.array(v["filtered_state"]["beta"])
    # A drifting coefficient is RECOVERED, not collapsed to the OLS constant.
    assert np.mean(np.abs(beta_hat - beta_true)) < 0.1
    assert v["estimated_variances"]["sigma2.beta"] > 0.0
    assert v["state_scales"]["beta"] != v["series_scales"]["dep"]  # beta units differ


def test_kalman_band_matches_the_configured_coverage():
    v = kalman_latent_state(_level_frame(), state_dim=1).value
    coverage = float(get_settings().econometrics.kalman_band_coverage.value)
    z = float(norm.ppf(0.5 + coverage / 2.0))
    assert v["band_coverage"] == pytest.approx(coverage)
    assert v["band_z"] == pytest.approx(z, abs=1e-9)
    latest = v["latest"]["level"]
    assert latest["lower"] == pytest.approx(latest["state"] - z * latest["std_error"], abs=1e-9)
    assert latest["upper"] == pytest.approx(latest["state"] + z * latest["std_error"], abs=1e-9)


def test_kalman_prior_standard_error_is_sqrt_diffuse_scale():
    v = kalman_latent_state(_level_frame(), state_dim=1).value
    kappa = float(get_settings().econometrics.kalman_diffuse_scale.value)
    scale = v["series_scales"]["obs"]
    assert v["prior_standard_error"]["level"] == pytest.approx(math.sqrt(kappa) * scale, rel=1e-9)
    assert v["initialization"] == "approximate_diffuse"
    assert v["diffuse_scale"] == pytest.approx(kappa)


def test_kalman_is_scale_invariant():
    # The model is invariant under rescaling; the OPTIMIZER is not, which is why
    # the series is normalised before fitting. After the fix the fitted variance
    # per unit^2 is identical at scale 1 and scale 1e6 (before: a 147x spread).
    base = _level_series()
    a = kalman_latent_state(pd.DataFrame({"obs": base}), state_dim=1).value
    b = kalman_latent_state(pd.DataFrame({"obs": base * 1e6}), state_dim=1).value
    ra = a["estimated_variances"]["sigma2.level"] / a["series_scales"]["obs"] ** 2
    rb = b["estimated_variances"]["sigma2.level"] / b["series_scales"]["obs"] ** 2
    assert ra == pytest.approx(rb, rel=1e-4)


def test_kalman_publishes_both_filtered_and_smoothed():
    v = kalman_latent_state(_level_frame(), state_dim=2).value
    # The smoothed path sees the whole sample and is look-ahead-biased; the
    # revision between the two is published so a real-time reader can judge it.
    assert "slope" in v["smoothed_latest"]
    assert "slope" in v["revision_in_band_units"]
    assert v["revision_in_band_units"]["slope"] > 0.0
    assert len(v["filtered_state"]["level"]) == v["n_obs"]
    assert len(v["band_lower"]["level"]) == v["n_obs"]


def test_kalman_warns_when_a_state_is_not_time_varying():
    # A genuinely constant coefficient: the MLE drives sigma2.beta to ~0 and the
    # state collapses, so "time-varying" describes the SPECIFICATION and not the
    # estimate. The result must say so.
    rng = np.random.default_rng(20)
    x = rng.normal(0, 1, 150)
    y = 0.5 * x + rng.normal(0, 0.05, 150)
    res = kalman_latent_state(pd.DataFrame({"dep": y, "reg": x}), state_dim=1)
    assert any("IS NOT TIME-VARYING" in w for w in res.warnings)


def test_kalman_confidence_takes_both_penalties():
    # base 0.70 - heuristic 0.20 - unobservable 0.20 = 0.30. The unobservable
    # penalty is §21.4 item 13's exact case: r* and potential GDP cannot be
    # observed, so the state is unobservable by nature.
    res = kalman_latent_state(_level_frame(), state_dim=1)
    assert res.confidence == pytest.approx(0.30, abs=1e-9)


def test_kalman_direction_is_unset():
    res = kalman_latent_state(_level_frame(), state_dim=1)
    assert res.direction is None
    assert "state units" in res.unit


def test_kalman_refuses_unknown_specification():
    frame, _ = _hedge_frame()
    with pytest.raises(ValueError, match="No specification"):
        kalman_latent_state(frame, state_dim=2)  # 2 columns x state_dim=2 is unlisted


def test_kalman_refuses_too_many_columns():
    rng = np.random.default_rng(1)
    df = pd.DataFrame(rng.normal(0, 1, (80, 3)))
    with pytest.raises(ValueError, match="columns"):
        kalman_latent_state(df, state_dim=1)


def test_kalman_refuses_constant_series():
    with pytest.raises(ValueError, match="no variation"):
        kalman_latent_state(pd.DataFrame({"obs": np.ones(150)}), state_dim=1)


def test_kalman_refuses_non_finite():
    frame = _level_frame()
    frame.iloc[0, 0] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        kalman_latent_state(frame, state_dim=1)


def test_kalman_refuses_duplicate_columns():
    df = pd.DataFrame(np.random.default_rng(1).normal(0, 1, (80, 2)), columns=["a", "a"])
    with pytest.raises(ValueError, match="duplicate column name"):
        kalman_latent_state(df, state_dim=1)


def test_kalman_refuses_too_few_observations():
    with pytest.raises(ValueError, match="below the configured floor"):
        kalman_latent_state(pd.DataFrame({"obs": np.arange(30.0)}), state_dim=1)


def test_kalman_refuses_non_dataframe():
    with pytest.raises(TypeError, match="pandas DataFrame"):
        kalman_latent_state([1.0, 2.0, 3.0])  # type: ignore[arg-type]


def test_kalman_refuses_bool_state_dim():
    with pytest.raises(TypeError, match="must be an int"):
        kalman_latent_state(_level_frame(), state_dim=True)


def test_kalman_refuses_non_int_state_dim():
    with pytest.raises(TypeError, match="must be an int"):
        kalman_latent_state(_level_frame(), state_dim=1.5)  # type: ignore[arg-type]


# ===========================================================================
# F-EC-005 + the config-leaf conversions. The four bare thresholds
# (`> 0.95`, `> 10.0 *`, `/ 4.0`, the `2.5`) now come from config, and the PCA
# constant-guard is FULLY relative. Each helper takes its threshold as a
# PARAMETER, so "behaviour follows the configured value" is directly testable.
# ===========================================================================
def test_pca_constant_guard_accepts_a_tiny_scale_moving_series():
    # F-EC-005: a series at scale 1e-9 varying by 1e-6 of that scale has a std of
    # ~1e-15, which the OLD `eps*maximum(scale, 1.0)*100` form (effectively
    # absolute at 2.22e-14 below scale 1) wrongly refused. The fully-relative form
    # accepts it, matching `_refuse_constant_kalman_series`.
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            "a": rng.normal(0, 1, 200),
            "b": 1e-9 * (1.0 + 1e-6 * rng.normal(0, 1, 200)),
        }
    )
    res = compute_pca(df, n_components=2)  # must NOT raise
    assert res.value["n_variables"] == 2


def test_pca_constant_guard_still_refuses_a_constant_column_at_every_scale():
    rng = np.random.default_rng(4)
    for const in (0.0, 1e-9, 0.5, 4.2, 1e6):
        df = pd.DataFrame({"a": rng.normal(0, 1, 200), "b": np.full(200, const)})
        with pytest.raises(ValueError, match="constant"):
            compute_pca(df, n_components=2)


def test_pca_level_suspicion_warning_follows_the_configured_share():
    rng = np.random.default_rng(5)
    common = {
        "eigenvalues": np.array([60.0, 25.0, 15.0]),
        "ratios": np.array([0.60, 0.25, 0.15]),
        "n_obs": 200,
        "panel": rng.normal(0, 1, (200, 3)),
        "standardisation": "correlation",
        "near_zero_threshold": 1e-8,
        "scale_dispersion_ratio": 10.0,
    }
    # PC1 = 0.60: trips at a 0.50 configured share, silent at the shipped 0.95.
    low = _pca_warnings(level_suspicion_pc1_share=0.50, **common)
    high = _pca_warnings(level_suspicion_pc1_share=0.95, **common)
    assert any("levels-suspicion" in w for w in low)
    assert not any("levels-suspicion" in w for w in high)


def test_pca_scale_dispersion_warning_follows_the_configured_ratio():
    rng = np.random.default_rng(6)
    common = {
        "eigenvalues": np.array([70.0, 30.0]),
        "ratios": np.array([0.70, 0.30]),
        "n_obs": 200,
        "panel": np.column_stack([rng.normal(0, 1, 200), rng.normal(0, 5, 200)]),
        "standardisation": "covariance",
        "near_zero_threshold": 1e-8,
        "level_suspicion_pc1_share": 0.95,
    }
    # std spread is ~5x: fires at a 2x configured ratio, not at the shipped 10x.
    low = _pca_warnings(scale_dispersion_ratio=2.0, **common)
    high = _pca_warnings(scale_dispersion_ratio=10.0, **common)
    assert any("noisiest" in w for w in low)
    assert not any("noisiest" in w for w in high)


def test_pca_panel_suspicion_follows_the_configured_coefficient():
    rng = np.random.default_rng(7)
    levels = np.cumsum(rng.normal(0, 1, (200, 2)), axis=0)  # near-unit-root columns
    # A levels panel's lag-1 is ~0.999. The shipped coefficient (2.5) gives a
    # boundary 1 - 2.5/sqrt(200) = 0.823 -> fires; a tiny coefficient makes the
    # boundary ~1.0 -> silent.
    assert _pca_panel_suspicion(levels, autocorr_coefficient=2.5) is not None
    assert _pca_panel_suspicion(levels, autocorr_coefficient=0.01) is None


def test_half_life_disclosure_follows_the_configured_fraction():
    hl = {"periods": 30.0, "phi": -0.02, "note": "x"}
    # 30 periods is above a quarter of 100 (25) but below half (50).
    fired = _half_life_disclosure(hl, 100, sample_fraction=0.25)
    assert fired is not None and "25%" in fired
    assert _half_life_disclosure(hl, 100, sample_fraction=0.50) is None


def test_pca_calibration_helper_reads_all_four_pca_leaves():
    settings = get_settings()
    expected = all(
        settings.is_calibrated(f"econometrics.{leaf}")
        for leaf in (
            "pca_near_zero_tolerance",
            "pca_level_suspicion_pc1_share",
            "pca_scale_dispersion_ratio",
            "pca_level_suspicion_autocorr_coefficient",
        )
    )
    assert bool(_pca_choices_calibrated()) is expected
    assert expected is False  # all four are uncalibrated_illustrative today


def test_cointegration_calibration_helper_reads_all_three_leaves():
    settings = get_settings()
    expected = all(
        settings.is_calibrated(f"econometrics.{leaf}")
        for leaf in (
            "regime_stability_split_fraction",
            "assumed_test_family_size",
            "cointegration_half_life_sample_fraction",
        )
    )
    assert bool(_cointegration_thresholds_calibrated()) is expected
    assert expected is False


def test_new_threshold_leaves_are_read_from_config():
    # LAW-1 "provable live": the shipped values are the ones the module reads.
    ec = get_settings().econometrics
    assert float(ec.pca_level_suspicion_pc1_share.value) == pytest.approx(0.95)
    assert float(ec.pca_scale_dispersion_ratio.value) == pytest.approx(10.0)
    assert float(ec.pca_level_suspicion_autocorr_coefficient.value) == pytest.approx(2.5)
    assert float(ec.cointegration_half_life_sample_fraction.value) == pytest.approx(0.25)
