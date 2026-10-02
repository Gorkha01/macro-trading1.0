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

from macro_engine.models.econometrics import _estimate_half_life, compute_pca, run_regression

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
    z = np.array([1.1 ** t for t in range(50)], dtype=float)
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
