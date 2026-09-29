"""Hand-verified tests for Module 18's OLS regression (Section 15.18).

AGENTS.md Section 21.2 Steps 4-5. The golden expected values below are computed
**independently of the implementation**, by exact rational arithmetic, and the
derivation is quoted beside them — because Section 21.2 warns that "a test
passing on the first attempt may be asserting whatever the code produced".

The two disciplines this file exists to protect, both from Section 15.18:

* **Mechanism first.** ``require_mechanism`` is a required argument, so the
  refusals are tested as hard as the successes: a regression that can be called
  without stating a hypothesis has lost the property that makes it auditable.
* **A low R-squared is information, not failure.** So there is a test that the
  weak-mechanism warning *fires*, and a **negative control** that it does *not*
  fire on a strong fit. Without the control the warning could be satisfied by
  always firing, which is the D-051 trap.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
import pytest

from macro_engine.config import get_settings
from macro_engine.models import econometrics as _econ
from macro_engine.models.contracts import ConfidenceInputs, ModelResult, compute_confidence
from macro_engine.models.econometrics import RegressionResult, run_regression

# `test_stationarity` is bound to a PRIVATE alias, never imported by bare name.
# Section 15.18-F mandates that name and it begins with `test_`, so
# `from ... import test_stationarity` makes pytest collect the MODEL FUNCTION as
# a test case — and it fails with a fixture error rather than anything naming the
# cause. Measured 2026-09-22: `ERROR tests/models/test_econometrics.py::test_stationarity`
# with no indication that the "test" was a model. Aliasing to `_stationarity`
# works because pytest's `python_functions = test*` does not match a leading
# underscore. Any future module exporting a `test_*` function needs the same.
_stationarity = _econ.test_stationarity

# Same reason, same alias. `test_cointegration` is mandated by Section 15.20-F
# and also begins with `test_`, so a bare-name import would make pytest collect
# the MODEL as a test case. See the note above.
_cointegration = _econ.test_cointegration

# `compute_pca` does NOT need an alias — its name does not begin with `test_` —
# but it is bound here anyway so this file has one spelling of every model under
# test, and so a future rename to a `test_*` name breaks in one place rather than
# silently re-collecting a model as a test (the failure mode O-117 records).
_pca = _econ.compute_pca


def _value(result: ModelResult) -> dict[str, Any]:
    """Narrow ``test_stationarity``'s ``value`` to a mapping, asserting not casting.

    The published dict is **mixed-type** — a verdict string, float statistics,
    int lags and bool flags — so ``tests.helpers.as_dict`` (which returns
    ``dict[str, float]``) does not fit it. Indexing ``result.value`` directly is
    a type error under ``--strict``, because the union includes
    ``float | str | bool | None``, and a ``cast`` would hide a result that
    returned a bare scalar where a mapping was promised. So the type is
    asserted, exactly as ``as_dict`` does.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value, got {type(value).__name__}"
    )
    return value


#: Comfortably above ``econometrics.mechanism_min_length``. Used wherever the
#: test is about the FIT rather than about the gate.
_MECHANISM = "A stated economic mechanism, present so the fit is not the test."


def _frame(values: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(values, dtype="float64")


# ---------------------------------------------------------------------------
# The golden case — exact rational arithmetic, no floating point in the
# expectation.
#
#   x = [0,0,0,0,0,1,1,1,1,1]        (five zeros, then five ones)
#   y = [1,2,3,2,4,6,7,8,9,7]
#
#   mean(x) = 1/2                        mean(y) = 49/10
#   Sxx = 5*(1/2)^2 + 5*(1/2)^2        = 5/2
#   Sxy = sum((xi - 1/2)(yi - 49/10))  = 25/2
#   beta  = Sxy / Sxx                  = (25/2) / (5/2)   = 5
#   alpha = mean(y) - beta*mean(x)     = 49/10 - 5/2       = 12/5
#   SST   = sum((yi - 49/10)^2)        = 729/10
#   SSE   = SST - beta*Sxy             = 729/10 - 125/2    = 52/5
#   R2    = 1 - SSE/SST                = 1 - (52/5)/(729/10) = 625/729
#   adjR2 = 1 - (1 - R2)*(n-1)/(n-p)   = 1 - (104/729)*(9/8) = 68/81
#
# A two-valued regressor is chosen deliberately: it makes every quantity above
# hand-checkable, which is the whole point of a golden test. Both values are
# exact in binary floating point, so `==` comparisons are legitimate here.
# ---------------------------------------------------------------------------
_GOLDEN_X = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0]
_GOLDEN_Y = [1.0, 2.0, 3.0, 2.0, 4.0, 6.0, 7.0, 8.0, 9.0, 7.0]
_GOLDEN_BETA_INTERCEPT = 12 / 5
_GOLDEN_BETA_SLOPE = 5.0
_GOLDEN_R_SQUARED = 625 / 729
_GOLDEN_ADJ_R_SQUARED = 68 / 81


def _golden_result() -> RegressionResult:
    return run_regression(
        pd.Series(_GOLDEN_Y, name="y"),
        _frame({"x": _GOLDEN_X}),
        _MECHANISM,
    )


def test_golden_case_matches_hand_calculation() -> None:
    """Every fitted quantity equals its independently derived exact value."""
    result = _golden_result()

    assert result.beta["const"] == pytest.approx(_GOLDEN_BETA_INTERCEPT)
    assert result.beta["x"] == pytest.approx(_GOLDEN_BETA_SLOPE)
    assert result.r_squared == pytest.approx(_GOLDEN_R_SQUARED)
    assert result.adj_r_squared == pytest.approx(_GOLDEN_ADJ_R_SQUARED)
    assert result.n_obs == 10


def test_golden_case_adj_r_squared_is_below_r_squared() -> None:
    """The adjustment must actually penalise, not be a copy of R-squared.

    A subclass that reported ``adj_r_squared = r_squared`` would pass every
    equality check above that did not name the field, and the two differ here
    by design (625/729 vs 68/81), so this pins the direction.
    """
    result = _golden_result()
    assert result.adj_r_squared < result.r_squared


def test_value_and_beta_are_the_same_mapping() -> None:
    """``value`` carries the primary output, so the base contract sees it too."""
    result = _golden_result()
    assert result.value == result.beta


def test_p_value_keys_match_beta_keys() -> None:
    """One p-value per coefficient, keyed identically.

    The values themselves are not hand-verified — they require the
    t-distribution's CDF — so only the structure and the sign of the claim are
    asserted here, and that limitation is stated rather than papered over.
    """
    result = _golden_result()
    assert set(result.p_values) == set(result.beta)
    assert all(0.0 <= p <= 1.0 for p in result.p_values.values())


def test_intercept_is_always_added_and_reported() -> None:
    """The intercept is added by the function and visible under 'const'."""
    result = _golden_result()
    assert "const" in result.beta


# ---------------------------------------------------------------------------
# Variance inflation factors — reported, never repaired.
# ---------------------------------------------------------------------------


def test_single_regressor_reports_no_vif() -> None:
    """``None``, not ``{}``: "not measured" must not read as "none found"."""
    assert _golden_result().multicollinearity_vif is None


def test_independent_regressors_report_vif_near_one() -> None:
    """Near-orthogonal regressors must not be flagged."""
    rng = np.random.default_rng(20)
    n = 60
    a = rng.normal(size=n)
    b = rng.normal(size=n)
    result = run_regression(
        pd.Series(1.0 + 2.0 * a + 0.5 * b, name="y"),
        _frame({"a": list(a), "b": list(b)}),
        _MECHANISM,
    )

    assert result.multicollinearity_vif is not None
    assert set(result.multicollinearity_vif) == {"a", "b"}
    assert all(value < 2.0 for value in result.multicollinearity_vif.values())


# ---------------------------------------------------------------------------
# Warning paths (Section 21.2 Step 5) — each with its negative control.
# ---------------------------------------------------------------------------


def test_low_r_squared_warns_as_information_not_failure() -> None:
    """A weak mechanism is reported, and the fit is still returned."""
    rng = np.random.default_rng(21)
    n = 60
    result = run_regression(
        pd.Series(rng.normal(size=n), name="y"),
        _frame({"x": list(rng.normal(size=n))}),
        _MECHANISM,
    )

    assert result.r_squared < get_settings().econometrics.low_r_squared_threshold.value
    assert any("WEAK MECHANISM" in w for w in result.warnings)
    # Section 15.18: this is information, not an error — the result exists.
    assert result.n_obs == n


def test_strong_fit_does_not_warn_about_weakness() -> None:
    """NEGATIVE CONTROL for the weak-mechanism warning.

    Without this, ``any("WEAK MECHANISM" ...)`` could be satisfied by a warning
    that always fires, which would pass the test above while detecting nothing.
    """
    rng = np.random.default_rng(22)
    n = 60
    x = rng.normal(size=n)
    result = run_regression(
        pd.Series(3.0 + 2.0 * x + rng.normal(scale=0.01, size=n), name="y"),
        _frame({"x": list(x)}),
        _MECHANISM,
    )

    assert result.r_squared > 0.99
    assert not any("WEAK MECHANISM" in w for w in result.warnings)


def test_perfect_fit_is_flagged_as_a_specification_error() -> None:
    """R-squared of exactly 1.0 is a red flag, not a triumph."""
    x = pd.Series([float(i) for i in range(1, 11)], name="x")
    result = run_regression(2.0 + 3.0 * x, x.to_frame(), _MECHANISM)

    assert result.r_squared == pytest.approx(1.0)
    assert any("PERFECT FIT" in w for w in result.warnings)


def test_noisy_fit_does_not_claim_a_perfect_fit() -> None:
    """NEGATIVE CONTROL for the perfect-fit warning."""
    assert not any("PERFECT FIT" in w for w in _golden_result().warnings)


def test_multicollinearity_is_disclosed_not_repaired() -> None:
    """Near-collinear regressors warn, and no column is dropped."""
    rng = np.random.default_rng(23)
    n = 60
    a = rng.normal(size=n)
    b = a + rng.normal(scale=0.01, size=n)
    result = run_regression(
        pd.Series(rng.normal(size=n), name="y"),
        _frame({"a": list(a), "b": list(b)}),
        _MECHANISM,
    )

    assert result.multicollinearity_vif is not None
    assert any("MULTICOLLINEARITY" in w for w in result.warnings)
    # Nothing was dropped: both coefficients are still reported.
    assert set(result.beta) == {"const", "a", "b"}


def test_independent_regressors_do_not_warn_about_collinearity() -> None:
    """NEGATIVE CONTROL for the multicollinearity warning."""
    rng = np.random.default_rng(24)
    n = 60
    a = rng.normal(size=n)
    b = rng.normal(size=n)
    result = run_regression(
        pd.Series(rng.normal(size=n), name="y"),
        _frame({"a": list(a), "b": list(b)}),
        _MECHANISM,
    )
    assert not any("MULTICOLLINEARITY" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# The mechanism gate — Section 15.18's ordering, enforced by the signature.
# ---------------------------------------------------------------------------


def test_mechanism_is_recorded_on_the_result() -> None:
    """The hypothesis is on the record, so a later data-mined fit is visible."""
    mechanism = "Higher real rates tighten financial conditions with a lag."
    result = run_regression(pd.Series(_GOLDEN_Y, name="y"), _frame({"x": _GOLDEN_X}), mechanism)
    assert any(mechanism in assumption for assumption in result.assumptions)


@pytest.mark.parametrize("mechanism", ["", "   ", "\n\t ", "because", "test"])
def test_insubstantial_mechanism_is_refused(mechanism: str) -> None:
    """The gate rejects blanks and placeholders."""
    with pytest.raises(ValueError, match="require_mechanism"):
        run_regression(pd.Series(_GOLDEN_Y, name="y"), _frame({"x": _GOLDEN_X}), mechanism)


def test_non_string_mechanism_is_refused() -> None:
    with pytest.raises(TypeError, match="require_mechanism"):
        run_regression(
            pd.Series(_GOLDEN_Y, name="y"),
            _frame({"x": _GOLDEN_X}),
            42,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Refusals — the function reports, it never repairs (Section 3).
# ---------------------------------------------------------------------------


def test_row_count_mismatch_is_refused() -> None:
    with pytest.raises(ValueError, match="same number of rows"):
        run_regression(pd.Series(_GOLDEN_Y, name="y"), _frame({"x": _GOLDEN_X[:5]}), _MECHANISM)


def test_index_mismatch_is_refused() -> None:
    """Same length, different labels — pairing by position would be an assumption."""
    x = pd.Series(_GOLDEN_X, index=range(100, 110), name="x")
    with pytest.raises(ValueError, match="identical index"):
        run_regression(pd.Series(_GOLDEN_Y, name="y"), x.to_frame(), _MECHANISM)


def test_non_finite_y_is_refused() -> None:
    y = pd.Series(_GOLDEN_Y, name="y")
    y.iloc[3] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        run_regression(y, _frame({"x": _GOLDEN_X}), _MECHANISM)


def test_non_finite_regressor_is_refused() -> None:
    x = _frame({"x": _GOLDEN_X})
    x.iloc[2, 0] = float("inf")
    with pytest.raises(ValueError, match="non-finite"):
        run_regression(pd.Series(_GOLDEN_Y, name="y"), x, _MECHANISM)


def test_constant_regressor_is_refused() -> None:
    """statsmodels would drop it silently; this refuses and says why."""
    with pytest.raises(ValueError, match="constant"):
        run_regression(
            pd.Series(_GOLDEN_Y, name="y"),
            _frame({"x": _GOLDEN_X, "k": [1.0] * 10}),
            _MECHANISM,
        )


def test_too_few_observations_is_refused() -> None:
    floor = int(get_settings().econometrics.min_observations.value)
    n = floor - 1
    with pytest.raises(ValueError, match="below the configured floor"):
        run_regression(
            pd.Series([1.0, 2.0, 3.0, 2.0, 4.0][:n], name="y"),
            _frame({"x": [0.0, 1.0, 2.0, 3.0, 4.0][:n]}),
            _MECHANISM,
        )


def test_degenerate_degrees_of_freedom_is_refused() -> None:
    """n <= parameters leaves no residual dof, so there is no fit to report."""
    n = 8
    regressors = {f"c{i}": [float(j + i) for j in range(n)] for i in range(n)}
    with pytest.raises(ValueError, match="Degenerate fit refused"):
        run_regression(
            pd.Series(range(n), dtype="float64", name="y"),
            _frame(regressors),
            _MECHANISM,
        )


def test_perfect_collinearity_is_refused() -> None:
    """Rank-deficient designs must refuse, not return solver artefacts.

    This is the case that a finiteness test on the VIF **misses**: measured
    2026-09-22, ``variance_inflation_factor`` returns a large FINITE number for
    a singular design and merely warns, so the detection has to be a rank check.
    """
    rng = np.random.default_rng(25)
    n = 40
    a = rng.normal(size=n)
    with pytest.raises(ValueError, match="rank-deficient"):
        run_regression(
            pd.Series(rng.normal(size=n), name="y"),
            _frame({"a": list(a), "b": [2.0 * value for value in a]}),
            _MECHANISM,
        )


def test_non_numeric_regressor_is_refused() -> None:
    with pytest.raises(ValueError, match="must be numeric"):
        run_regression(
            pd.Series(_GOLDEN_Y, name="y"),
            pd.DataFrame({"x": ["a"] * 10}),
            _MECHANISM,
        )


def test_boolean_y_is_refused() -> None:
    """A bool column is numeric to pandas; regressing on it is a mistake."""
    with pytest.raises(ValueError, match="must be numeric"):
        run_regression(pd.Series([True] * 10, name="y"), _frame({"x": _GOLDEN_X}), _MECHANISM)


def test_empty_regressor_frame_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one regressor"):
        run_regression(
            pd.Series(_GOLDEN_Y, name="y"),
            pd.DataFrame(index=range(10)),
            _MECHANISM,
        )


def test_a_column_named_const_is_refused() -> None:
    """The intercept's own name is reserved, because the collision is SILENT.

    Found in review, not by a test: a caller column named ``const`` collides with
    the intercept the function prepends, so the design matrix carries two columns
    of that name, ``fit.params`` comes back with a duplicated index, and the
    ``{name: value}`` comprehension building ``beta`` keeps only the last one. The
    fit then reports FEWER coefficients than the caller supplied and raises
    nothing at all — a wrong answer that looks complete.
    """
    rng = np.random.default_rng(31)
    n = 40
    x = pd.Series(rng.normal(size=n), name="x")
    y = pd.Series(rng.normal(size=n), name="y")

    with pytest.raises(ValueError, match="collides with the intercept"):
        run_regression(
            y,
            pd.DataFrame({"x": list(x), "const": list(rng.normal(size=n))}),
            _MECHANISM,
        )


def test_duplicate_regressor_names_are_refused() -> None:
    """A duplicated label must be a refusal, not a pandas AttributeError.

    Measured before the guard existed: ``X[name]`` returns a *DataFrame* when the
    name is duplicated, so the dtype check raised
    ``'DataFrame' object has no attribute 'dtype'`` from inside pandas — an
    exception that named neither the problem nor the column.
    """
    rng = np.random.default_rng(32)
    n = 40
    values = rng.normal(size=n)
    duplicated = pd.DataFrame({"a": values, "b": values})
    duplicated.columns = ["a", "a"]  # pandas permits a duplicated label

    with pytest.raises(ValueError, match="duplicate column name"):
        run_regression(
            pd.Series(rng.normal(size=n), name="y"),
            duplicated,
            _MECHANISM,
        )


def test_wrong_y_type_is_refused() -> None:
    with pytest.raises(TypeError, match="pandas Series"):
        run_regression([1.0, 2.0], _frame({"x": [1.0, 2.0]}), _MECHANISM)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Confidence and the reasoning-object fields (Sections 3 and 22.8).
# ---------------------------------------------------------------------------


def test_confidence_is_derived_not_asserted() -> None:
    """Confidence equals ``compute_confidence`` on the same stated factors.

    Asserted as an *equality with the derivation* rather than against a literal,
    so the test moves with the config instead of pinning today's number. The
    second assertion proves a penalty was applied at all — a model that leaned
    on an illustrative placeholder and reported the unpenalised base would pass
    the first check alone.
    """
    result = _golden_result()
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not get_settings().is_calibrated(
                "econometrics.low_r_squared_threshold"
            ),
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == expected
    assert result.confidence < get_settings().confidence.base.value


def test_limitations_name_the_untested_stationarity() -> None:
    """The spurious-regression caveat is standing, so it is a limitation."""
    result = _golden_result()
    assert any("Stationarity is NOT tested" in limitation for limitation in result.limitations)


def test_decision_prohibition_forbids_causal_and_sizing_readings() -> None:
    """Section 3's load-bearing field: what a consumer may NOT do.

    The assertion is on the **property** — every entry must actually forbid —
    rather than on the vocabulary. An earlier version checked only that the word
    "causal" appeared, and the mutation sweep's M15 replaced the prohibition
    with a PERMISSION ("Coefficients may be read as causal effects") which still
    contained the word and still passed. The mutation found the hole; checking
    for a negation is what closes it, because a description of a hazard is not a
    prohibition of it.
    """
    prohibitions = _golden_result().decision_prohibition

    for prohibition in prohibitions:
        lowered = prohibition.lower()
        assert any(negation in lowered for negation in ("do not", "must not", "never")), (
            f"a decision_prohibition that forbids nothing is a description, not a "
            f"prohibition: {prohibition!r}"
        )

    joined = " ".join(prohibitions).lower()
    assert "causal" in joined
    assert "size a position" in joined


def test_model_name_is_stable() -> None:
    assert _golden_result().model_name == "run_regression"


# ---------------------------------------------------------------------------
# test_stationarity (Section 15.18-F). The four verdicts.
#
# The fixtures below were found by PROBING, not by assuming, because the two
# tests do not behave the way a reader expects:
#   * a genuine random walk at n=200 can give ADF p = 0.037 — the test REJECTS
#     the unit root that is definitionally present (ADF's low power), so a
#     "random walk" fixture is not reliably a clean non-stationary case;
#   * KPSS's p-value is CLIPPED to [0.01, 0.10], so it is a bound;
#   * the two disagreement branches need deliberately constructed series.
# Every seed is fixed, so the verdicts are reproducible rather than incidental.
# ---------------------------------------------------------------------------


def _white_noise(n: int = 300, seed: int = 42) -> pd.Series:
    """Stationary by construction; both tests should agree."""
    return pd.Series(np.random.default_rng(seed).normal(size=n), name="white_noise")


def _random_walk(n: int = 300, seed: int = 42) -> pd.Series:
    """A unit root by construction; both tests should agree at this length."""
    return pd.Series(np.cumsum(np.random.default_rng(seed).normal(size=n)), name="random_walk")


def _conflicted(n: int = 300) -> pd.Series:
    """A slow sine: strongly mean-reverting AND strongly low-frequency.

    ADF sees the mean reversion and rejects a unit root; KPSS sees the
    low-frequency power and rejects stationarity. Neither is wrong — the series
    genuinely has both properties, which is why the conflict is informative
    rather than a bug to be resolved.
    """
    t = np.arange(n)
    return pd.Series(np.sin(2 * np.pi * t / 200), name="slow_sine")


def _low_power(n: int = 50, seed: int = 3) -> pd.Series:
    """A short random walk: too little data for either test to reject.

    The seed and length are not incidental. A fixture drawn from a *shared* RNG
    stream is not reproducible once anything upstream consumes that stream —
    the first draft of this helper reused a seed whose earlier draws had shifted
    it, and it silently produced `non_stationary` instead. Each helper here
    builds its own generator, and this pair was found by sweeping seeds rather
    than by taking the first candidate that happened to work.
    """
    return pd.Series(np.cumsum(np.random.default_rng(seed).normal(size=n)), name="short_walk")


def test_white_noise_reads_as_stationary() -> None:
    result = _stationarity(_white_noise())
    assert _value(result)["verdict"] == "stationary"
    assert _value(result)["adf_rejects_unit_root"] is True
    assert _value(result)["kpss_rejects_stationarity"] is False


def test_random_walk_reads_as_non_stationary() -> None:
    result = _stationarity(_random_walk())
    assert _value(result)["verdict"] == "non_stationary"
    assert _value(result)["adf_rejects_unit_root"] is False
    assert _value(result)["kpss_rejects_stationarity"] is True


def test_the_inverted_nulls_are_not_transposed() -> None:
    """ADF rejecting means STATIONARY; KPSS rejecting means NON-stationary.

    This is the single comparison a transposition would invert silently — both
    tests would still run, still return numbers, and every verdict would be
    wrong. Asserting the two booleans on the two fixtures above pins it, and
    this test names the direction explicitly so a future edit has to confront it.
    """
    stationary = _value(_stationarity(_white_noise()))
    unit_root = _value(_stationarity(_random_walk()))

    # ADF's H0 is a unit root, so a SMALL p-value is evidence FOR stationarity.
    assert stationary["adf_p_value"] < unit_root["adf_p_value"]
    # KPSS's H0 is stationarity, so a SMALL p-value is evidence AGAINST it.
    assert stationary["kpss_p_value"] > unit_root["kpss_p_value"]


def test_both_rejecting_is_reported_as_conflict() -> None:
    """Neither test is allowed to break the tie (Section 15.18)."""
    result = _stationarity(_conflicted())
    assert _value(result)["verdict"] == "inconclusive_conflict"
    assert _value(result)["adf_rejects_unit_root"] is True
    assert _value(result)["kpss_rejects_stationarity"] is True
    assert any("CONTRADICT" in w for w in result.warnings)


def test_neither_rejecting_is_reported_as_low_power_not_contradiction() -> None:
    """An absence of evidence is a DIFFERENT finding from a contradiction."""
    result = _stationarity(_low_power())
    assert _value(result)["verdict"] == "inconclusive_low_power"
    assert _value(result)["adf_rejects_unit_root"] is False
    assert _value(result)["kpss_rejects_stationarity"] is False
    assert any("NEITHER TEST REJECTS" in w for w in result.warnings)
    # The two inconclusive kinds must not be conflated.
    assert not any("CONTRADICT" in w for w in result.warnings)


def test_the_two_inconclusive_kinds_are_distinct_verdicts() -> None:
    """A classifier that answered 'inconclusive' for both would pass the two
    tests above; this one would not."""
    assert (
        _value(_stationarity(_conflicted()))["verdict"]
        != _value(_stationarity(_low_power()))["verdict"]
    )


def test_agreement_does_not_produce_an_inconclusive_warning() -> None:
    """NEGATIVE CONTROL: the inconclusive warnings must not fire on agreement."""
    for series in (_white_noise(), _random_walk()):
        result = _stationarity(series)
        assert not any(
            marker in w
            for w in result.warnings
            for marker in ("CONTRADICT", "NEITHER TEST REJECTS")
        )


def test_clipped_kpss_p_value_is_disclosed() -> None:
    """A clipped p-value is a BOUND and the result must say so.

    Both fixtures here sit at a table edge (0.10 and 0.01), so the disclosure
    must fire — and the flag must agree with the warning, not merely accompany it.
    """
    result = _stationarity(_white_noise())
    assert _value(result)["kpss_p_value_is_clipped"] is True
    assert any("BOUND, NOT A POINT ESTIMATE" in w for w in result.warnings)


def test_the_clip_flag_matches_the_disclosure() -> None:
    """The boolean and the warning are two spellings of one fact."""
    for series in (_white_noise(), _random_walk(), _conflicted(), _low_power()):
        result = _stationarity(series)
        flagged = _value(result)["kpss_p_value_is_clipped"]
        disclosed = any("BOUND, NOT A POINT ESTIMATE" in w for w in result.warnings)
        assert flagged == disclosed, f"clip flag {flagged} but disclosed {disclosed}"


def test_verdict_is_always_one_of_the_four() -> None:
    """A Literal-by-hand: no fixture may produce an unclassified verdict."""
    allowed = {
        "stationary",
        "non_stationary",
        "inconclusive_conflict",
        "inconclusive_low_power",
    }
    for series in (_white_noise(), _random_walk(), _conflicted(), _low_power()):
        assert _value(_stationarity(series))["verdict"] in allowed


def test_the_significance_level_used_is_published() -> None:
    """The verdict is only interpretable against the size it was judged at."""
    result = _stationarity(_white_noise())
    alpha = get_settings().econometrics.significance_level.value
    assert _value(result)["significance_level"] == alpha


def test_the_significance_level_is_read_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move the config and require the published size AND the verdict to follow.

    The first version of the test above compared against
    ``get_settings().econometrics.significance_level.value`` — which **is** 0.05 —
    so a hardcoded ``0.05`` inside the function satisfied it. The sweep's M28 did
    exactly that and **SURVIVED**. Changing the setting and asserting the result
    *moves* is what separates a derivation from a coincidence.

    The verdict assertion is the stronger half: at alpha = 0.20 both tests reject
    on white noise (ADF p = 0.0000, KPSS p = 0.1000), so a function that echoed
    the setting but compared against a literal would publish 0.20 beside a
    ``stationary`` verdict — a self-contradiction this test forbids.
    """
    settings = get_settings()
    monkeypatch.setattr(settings.econometrics.significance_level, "value", 0.20, raising=False)

    result = _stationarity(_white_noise())
    assert _value(result)["significance_level"] == 0.20
    assert _value(result)["verdict"] == "inconclusive_conflict"
    assert _value(result)["kpss_rejects_stationarity"] is True


def test_the_regression_type_used_is_named_in_the_context() -> None:
    """The deterministic-terms choice changes the answer, so it must be visible."""
    result = _stationarity(_white_noise())
    assert "constant only" in result.context or "constant and linear trend" in result.context


def test_stationarity_limitations_name_the_low_power_asymmetry() -> None:
    result = _stationarity(_white_noise())
    joined = " ".join(result.limitations)
    assert "LOW POWER" in joined
    assert "STRUCTURAL BREAK" in joined


def test_stationarity_forbids_breaking_the_tie() -> None:
    """Section 3's load-bearing field, on the discipline this function exists for."""
    prohibitions = _stationarity(_white_noise()).decision_prohibition
    assert any("inconclusive" in p.lower() for p in prohibitions)
    for prohibition in prohibitions:
        lowered = prohibition.lower()
        assert any(n in lowered for n in ("do not", "must not", "never"))


def test_a_rank_deficient_adf_design_is_disclosed() -> None:
    """statsmodels' SingularMatrixWarning must reach the consumer.

    A deterministic sine makes ADF's *internal* lag-augmented regression
    rank-deficient, so the statistic is computed from a degenerate design.
    statsmodels warns and returns a number anyway — which is exactly why the
    result has to carry the fact, or a reader takes a degenerate fit for an
    ordinary one.
    """
    result = _stationarity(_conflicted())
    assert _value(result)["adf_design_was_ill_conditioned"] is True
    assert any("RANK-DEFICIENT" in w for w in result.warnings)


def test_a_well_conditioned_adf_design_is_not_flagged() -> None:
    """NEGATIVE CONTROL for the ill-conditioning disclosure."""
    result = _stationarity(_white_noise())
    assert _value(result)["adf_design_was_ill_conditioned"] is False
    assert not any("RANK-DEFICIENT" in w for w in result.warnings)


# --- refusals -------------------------------------------------------------


def test_a_short_series_is_refused() -> None:
    floor = int(get_settings().econometrics.stationarity_min_observations.value)
    with pytest.raises(ValueError, match="below the configured floor"):
        _stationarity(pd.Series(np.arange(floor - 1, dtype="float64"), name="s"))


def test_a_constant_series_is_refused() -> None:
    """The refusal must be OURS, not statsmodels'.

    Matched on a phrase unique to this module's message. The first version
    matched the bare word ``constant`` — and the mutation sweep's M30, which
    deletes this guard entirely, **SURVIVED**, because statsmodels then raises
    its own ``ValueError: Invalid input, x is constant``. The test was passing on
    the library's error rather than on our refusal, which is the difference
    between testing our contract and testing someone else's.
    """
    with pytest.raises(ValueError, match="no dynamics to test"):
        _stationarity(pd.Series([3.0] * 100, name="s"))


def test_a_non_finite_series_is_refused() -> None:
    values = pd.Series(np.random.default_rng(9).normal(size=100), name="s")
    values.iloc[5] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        _stationarity(values)


def test_a_non_numeric_series_is_refused() -> None:
    with pytest.raises(ValueError, match="must be numeric"):
        _stationarity(pd.Series(["a"] * 100, name="s"))


def test_an_empty_series_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        _stationarity(pd.Series([], dtype="float64", name="s"))


def test_a_non_series_is_refused() -> None:
    with pytest.raises(TypeError, match="pandas Series"):
        _stationarity([1.0, 2.0, 3.0])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# test_cointegration (Section 15.18-F / 15.20-F). The three mandated extras,
# the two mandatory warnings, and every refusal.
#
# Every fixture below was MEASURED before it was asserted, with the fitted
# values written into the comments — the D-094 lesson is that a fixture chosen
# because it "should" behave a certain way is how a guard gets tested against
# the case it was not built for. The half-life fixtures in particular are the
# ones the aliasing boundary makes easy to get wrong (see `_estimate_half_life`).
# ---------------------------------------------------------------------------


def _coint_pair(
    n: int = 400,
    *,
    seed: int = 7,
    beta: float = 1.5,
    rho: float = 0.6,
) -> tuple[pd.Series, pd.Series]:
    """A pair that IS cointegrated: ``y = 2 + beta*x + AR(1) error``.

    ``x`` is a random walk (I(1)) and the error is mean-reverting, so ``y`` is
    I(1) too and the two share a stationary combination — the Granger
    representation the test presumes. ``rho = 0.6`` gives ``phi = rho - 1 = -0.4``,
    comfortably inside the estimator's valid range ``(-1, 0)``.

    Measured 2026-09-23 at the defaults: statistic ``-9.5187``, p ``0.0000``,
    ``is_cointegrated=True``, half-life ``1.8652`` periods, regime stability
    ``stable``. Only the QUALITATIVE facts are asserted in the tests, because the
    statistic itself is a property of these exact draws rather than of the
    construction — but the construction is what makes them hold.
    """
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(size=n))
    error = np.zeros(n)
    for t in range(1, n):
        error[t] = rho * error[t - 1] + rng.normal()
    y = 2.0 + beta * x + error
    index = pd.RangeIndex(n)
    return (
        pd.Series(y, index=index, name="y"),
        pd.Series(x, index=index, name="x"),
    )


def _independent_walks(n: int = 400, *, seed: int = 11) -> tuple[pd.Series, pd.Series]:
    """Two independent random walks: NO cointegration by construction.

    Measured 2026-09-23: statistic ``-1.3307``, p ``0.8203``,
    ``is_cointegrated=False``, regime stability ``absent_in_both_halves``.
    """
    rng = np.random.default_rng(seed)
    index = pd.RangeIndex(n)
    return (
        pd.Series(np.cumsum(rng.normal(size=n)), index=index, name="a"),
        pd.Series(np.cumsum(rng.normal(size=n)), index=index, name="b"),
    )


def _split_regime_pair(n: int = 600, *, seed: int = 0) -> tuple[pd.Series, pd.Series]:
    """Cointegrated in the FIRST half only: the engineered `unstable` case.

    The error is an AR(1) with ``rho = 0.5`` before the split and a pure random
    walk (``rho = 1.0``) after it, so the spread mean-reverts in one sub-period
    and not the other. Measured 2026-09-23 at seed 0: statistic ``-1.6556``,
    ``regime_stability='unstable'``. The seed is pinned because the verdict is a
    property of the draw — sweeping 30 seeds was how this one was found, not
    taken on the first attempt.
    """
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(size=n))
    error = np.zeros(n)
    for t in range(1, n):
        rho = 0.5 if t < n // 2 else 1.0
        error[t] = rho * error[t - 1] + rng.normal()
    y = 2.0 + 1.5 * x + error
    index = pd.RangeIndex(n)
    return (
        pd.Series(y, index=index, name="y"),
        pd.Series(x, index=index, name="x"),
    )


def _alternating_spread_pair(n: int = 400) -> tuple[pd.Series, pd.Series]:
    """A spread that alternates sign every period: ``phi <= -1``, refused.

    ``z_t = (+1, -1, +1, ...)`` is mean-zero and has NO memory, but its fitted
    AR(1) slope lands at ``phi = -2.0`` — outside ``(-1, 0)``. Measured
    2026-09-23: ``phi = -1.999965``, half-life refused. The naive formula would
    return ``0.3466`` periods, a number that LOOKS like a very fast reversion and
    is below the one-period resolution floor.
    """
    index = pd.RangeIndex(n)
    t = np.arange(n)
    x = pd.Series(np.cumsum(np.random.default_rng(5).normal(size=n)), index=index, name="x")
    alternation = np.where(t % 2 == 0, 1.0, -1.0)
    return pd.Series(x.to_numpy() + alternation, index=index, name="y"), x


# --- the three mandated extras --------------------------------------------


def test_the_spread_is_published_not_just_the_p_value() -> None:
    """Section 15.18-F's first requirement: the TRADABLE object is the spread.

    A test that returns only a statistic has thrown away the thing a convergence
    trade is actually built on, and a consumer who re-derives it will re-derive a
    different one (different residualisation, different deterministics).
    """
    y, x = _coint_pair()
    result = _cointegration(y, x)
    value = _value(result)
    spread = value["spread"]
    assert isinstance(spread, list)
    assert len(spread) == len(y)
    # A residual, not a copy of an input: it must be centred and much smaller
    # than the series it came from.
    assert abs(float(np.mean(spread))) < 1e-9
    assert float(np.std(spread)) < float(np.std(y.to_numpy()))
    # THE VERDICT ITSELF, on the fixture whose construction guarantees it. This
    # assertion was MISSING from the first draft, and M52 — the transposed
    # Johansen comparison — SURVIVED as a result: the suite asserted only that
    # `is_cointegrated` was a bool, never that it was the RIGHT bool, so a
    # mutation inverting every verdict had nothing to fail against.
    assert value["is_cointegrated"] is True


def test_a_non_cointegrated_pair_does_not_report_cointegration() -> None:
    """THE NEGATIVE VERDICT, and the reason M51/M52 need both poles.

    Asserting only the positive verdict would be satisfied by a function that
    always returned ``True``; asserting only the negative by one that always
    returned ``False``. Both are pinned, on fixtures whose construction makes the
    expected answer a property of the design rather than of the draw.
    """
    y, x = _independent_walks()
    value = _value(_cointegration(y, x))
    assert value["is_cointegrated"] is False


def test_the_johansen_verdict_is_the_right_way_round() -> None:
    """Johansen rejects when the statistic EXCEEDS its critical value.

    The comparison is the opposite of Engle-Granger's, so a mechanical copy of
    the sibling's ``<`` inverts every Johansen verdict while the function keeps
    running and every field stays well-formed. Measured 2026-09-23 on the
    cointegrated fixture: statistic ``159.67`` against a 5% threshold of
    ``15.49`` — so the two comparisons genuinely disagree here, which is what
    makes this fixture able to tell them apart.
    """
    y, x = _coint_pair()
    value = _value(_cointegration(y, x, method="johansen"))

    statistic = float(value["statistic"])
    criticals = value["critical_values"]
    assert isinstance(criticals, list)
    threshold = float(criticals[1])  # the 5% column
    assert statistic > threshold, (
        "fixture must sit above the 5% threshold so the two comparison directions disagree"
    )
    assert value["is_cointegrated"] is True


def test_the_published_spread_is_the_series_the_statistic_used() -> None:
    """Section 9's first question: SAME BASIS, measured rather than assumed.

    The statistic is an ADF applied to ``coint``'s residual. This re-derives the
    residual the way the reporting code claims to, applies the same ADF, and
    requires the two numbers to agree — so a future edit that changes the
    residualisation (a different `add_trend`, a different `prepend`) cannot keep
    the statistic and publish a different spread.

    **The tolerance is 1e-6, and that is a measurement rather than a convenience.**
    The identity itself is EXACT: measured 2026-09-23, the re-derived ADF equals
    ``coint``'s ``coint_t`` to ``0.00e+00`` for both deterministic-terms settings.
    But the PUBLISHED statistic passes through ``round(value, 6)`` in
    ``_cointegration_value``, so comparing a full-precision re-derivation against
    the published field shows the ROUNDING, not a basis mismatch — the first draft
    of this test asserted ``< 1e-10`` and failed by ``1.7e-07``, which is
    ``0.5 * 10**-6`` to within the spread of the rounding. Asserting at the
    published precision is what tests the shared basis; asserting tighter tests
    the rounding, which is not the property in question.
    """
    from statsmodels.tsa.stattools import adfuller

    y, x = _coint_pair()
    value = _value(_cointegration(y, x))

    beta = value["hedge_ratio"]
    spread = np.asarray(value["spread"], dtype="float64")
    trend = value["trend"]
    assert isinstance(trend, str)
    assert isinstance(beta, float)

    # Re-build the residual from the SAME design the implementation uses, and
    # require it to reproduce the published spread — the unrounded half of the
    # identity.
    #
    # `beta` is re-fit here rather than taken from the published `hedge_ratio`,
    # because that field passes through `round(..., 6)`: reconstructing from it
    # differs from the published spread by ~5e-6, which measures the ROUNDING and
    # not the residualisation. The published value is asserted separately, below.
    import statsmodels.api as sm
    from statsmodels.tsa.tsatools import add_trend

    design = add_trend(x.to_numpy().reshape(-1, 1), trend=trend, prepend=False)
    fitted = sm.OLS(y.to_numpy(), design).fit()
    reconstructed = y.to_numpy() - fitted.fittedvalues
    assert np.allclose(reconstructed, spread, atol=1e-9), (
        "the published spread is not the residual of the same design the "
        "implementation claims to use"
    )
    # `add_trend(prepend=False)` places the REGRESSOR column FIRST and the
    # deterministic terms after it, so the x coefficient is params[0] under both
    # 'c' and 'ct'. Reading params[1] gave 1.2693 against the published 1.4827
    # (the constant), and params[-1] the same — which is how the ordering was
    # pinned. This is the same trap `_engle_granger_spread` documents in its own
    # comment, and the assertion below is what would catch an inverted index.
    assert beta == pytest.approx(float(fitted.params[0]), abs=1e-6)

    # `result_object=True` because statsmodels has announced the plain tuple's
    # length changes in 0.16 (or after July 2027); the un-pinned form emits a
    # FutureWarning, which `-W error` would turn into a failure.
    rederived = float(
        adfuller(
            spread,
            regression="n",
            autolag=_econ._coint_autolag(),
            result_object=True,
        ).statistic
    )
    assert abs(rederived - float(value["statistic"])) < 1e-6, (
        "the published spread does not reproduce the published statistic: "
        f"re-derived ADF {rederived!r} vs statistic {value['statistic']!r}"
    )


def test_the_half_life_matches_the_derived_estimator() -> None:
    """Section 15.18-F's second requirement, checked against the FORMULA.

    ``H = -ln(2) / phi`` where ``phi`` is the AR(1) slope of the spread. The
    expectation is computed here from the published ``phi`` — so this test would
    catch a half-life that was hardcoded, or computed as ``ln(2)/rho`` (the
    common error: using persistence rather than its complement).

    The tolerance is the PUBLISHED precision (``round(..., 6)``), matching the
    shared-basis test: asserting at 1e-9 fails by ``8e-9`` on the rounding itself,
    which measures ``_cointegration_value`` rather than the estimator.
    """
    y, x = _coint_pair()
    value = _value(_cointegration(y, x))

    phi = value["half_life_phi"]
    periods = value["half_life_periods"]
    assert isinstance(phi, float)
    assert isinstance(periods, float)

    assert -1.0 < phi < 0.0, f"fixture must sit in the valid range, got phi={phi}"
    assert periods == pytest.approx(-math.log(2.0) / phi, abs=1e-6)

    # The two ways to get this wrong, excluded explicitly. Both are checked at a
    # LOOSER tolerance than the identity above, because they are wrong by a
    # factor, not by a rounding step.
    rho = 1.0 + phi
    assert abs(rho) > 0.1, "fixture must separate rho from phi enough to distinguish"
    assert periods != pytest.approx(math.log(2.0) / abs(rho), rel=1e-3), (
        "half-life looks like ln(2)/|rho| — persistence used where its complement belongs"
    )
    assert periods == pytest.approx(math.log(2.0) / (-phi), abs=1e-6), (
        "the derivation gives -ln(2)/phi, which equals +ln(2)/(-phi) only "
        "because phi < 0 — the sign path must hold"
    )


def test_the_half_life_floor_is_ln2() -> None:
    """The limiting case: ``phi -> -1+`` gives ``H -> ln 2``, the floor.

    The alternating fixture reaches ``phi = -1.999965`` — *below* -1 — so it is
    refused rather than reported. This test pins the FLOOR by constructing a
    spread whose fitted slope approaches -1 from above, which is the boundary the
    refusal exists to protect.
    """
    # rho = 0.05 -> phi = -0.95, near the boundary but inside it.
    y, x = _coint_pair(n=600, seed=3, rho=0.05)
    value = _value(_cointegration(y, x))
    phi = value["half_life_phi"]
    periods = value["half_life_periods"]
    assert isinstance(phi, float)
    assert isinstance(periods, float)
    assert -1.0 < phi < 0.0
    # Approaching the boundary the half-life must approach ln(2) from ABOVE.
    assert periods > math.log(2.0)
    if phi < -0.9:
        assert periods < 1.0


def test_an_unestimable_half_life_is_refused_not_faked() -> None:
    """The aliasing boundary: ``phi <= -1`` means the spread alternates, not reverts.

    A guard that returned ``-ln(2)/phi`` here would publish ``0.3466`` periods — a
    plausible-looking, very fast reversion for a series with no memory at all. The
    refusal is the point, and the note must NAME the boundary so the reader learns
    which precondition failed.
    """
    y, x = _alternating_spread_pair()
    value = _value(_cointegration(y, x))

    assert value["half_life_periods"] is None
    phi = value["half_life_phi"]
    assert isinstance(phi, float)
    assert phi <= -1.0, f"the fixture must sit outside the valid range, got {phi}"
    note = str(value["half_life_note"])
    assert "-1" in note and "alternat" in note.lower()


def test_the_naive_half_life_is_not_reported_for_an_alternating_spread() -> None:
    """NEGATIVE CONTROL for the refusal: the wrong number must be ABSENT.

    Without this, a guard that returned the naive value AND also set the note
    would not be distinguished from a guard that refused.
    """
    y, x = _alternating_spread_pair()
    value = _value(_cointegration(y, x))
    phi = value["half_life_phi"]
    assert isinstance(phi, float)
    naive = -math.log(2.0) / phi  # positive here because phi < 0
    assert value["half_life_periods"] != pytest.approx(naive, rel=1e-6)


def _non_reverting_pair(n: int = 120, *, seed: int = 4) -> tuple[pd.Series, pd.Series]:
    """A spread that ACCUMULATES: the error is explosive (``rho = 1.02``).

    Measured 2026-09-23: ``phi = +0.0083``, so the half-life formula would return
    ``-83.2`` periods — a finite, plausible-magnitude number that is not a time.
    """
    rng = np.random.default_rng(seed)
    index = pd.RangeIndex(n)
    x = pd.Series(np.cumsum(rng.normal(size=n)), index=index, name="x")
    error = np.zeros(n)
    for t in range(1, n):
        error[t] = 1.02 * error[t - 1] + rng.normal()
    return pd.Series(2.0 + 1.5 * x.to_numpy() + error, index=index, name="y"), x


def test_a_non_reverting_spread_gets_no_half_life() -> None:
    """The OTHER refusal: ``phi >= 0`` — the spread accumulates, so H is no time.

    A negative half-life is not a fast reversion, it is not a time at all — and
    the number is finite and plausible in magnitude, so it would sit in the
    published JSON unnoticed if the gate were removed.

    **This test was MISSING from the first draft and M36 SURVIVED as a result.**
    The aliasing case (``phi <= -1``) was covered; the opposite boundary — for a
    spread that does not revert at all — was not. Two boundaries need two tests:
    having either alone leaves the other free to be deleted.
    """
    y, x = _non_reverting_pair()
    result = _cointegration(y, x)
    value = _value(result)

    assert value["half_life_periods"] is None
    phi = value["half_life_phi"]
    assert isinstance(phi, float)
    assert phi >= 0.0, f"the fixture must fit a non-negative slope, got {phi}"
    note = str(value["half_life_note"])
    assert "non-negative" in note
    assert "does not mean-revert" in note
    # The naive formula's output must be ABSENT, not merely annotated.
    assert value["half_life_periods"] != pytest.approx(-math.log(2.0) / phi, rel=1e-6)


def test_the_two_half_life_refusals_are_distinct() -> None:
    """Two boundaries, two diagnoses — ``phi >= 0`` is not ``phi <= -1``.

    Collapsing them into one message would tell a reader that a non-reverting
    spread "alternates sign", which is a different finding.
    """
    accumulating = _value(_cointegration(*_non_reverting_pair()))["half_life_note"]
    alternating = _value(_cointegration(*_alternating_spread_pair()))["half_life_note"]
    assert str(accumulating) != str(alternating)
    assert "non-negative" in str(accumulating)
    assert "alternat" in str(alternating).lower()


def test_the_johansen_n_obs_is_the_input_length_not_the_spread_length() -> None:
    """``n_obs`` on the Johansen path, where the spread does NOT exist.

    Johansen publishes no normalised spread, so an implementation reporting the
    spread's length would publish ``n_obs = 0`` beside a statistic computed from
    hundreds of rows — a wrong number that looks like a missing one. This was a
    real defect, fixed before commit; **M53 SURVIVED** because the only ``n_obs``
    assertion was on an Engle-Granger fixture, where the spread's length and the
    input's are the same number.
    """
    y, x = _coint_pair()
    value = _value(_cointegration(y, x, method="johansen"))
    assert value["spread"] == [], "Johansen publishes no spread, by design"
    assert value["n_obs"] == len(y)


def test_the_unusable_half_life_tier_is_documented_unreachable() -> None:
    """The ``H >= n`` tier is NOT reachable through this API, and that is recorded.

    ``_half_life_disclosure`` has two tiers: ``H >= n`` ("cannot be distinguished
    from no reversion") and ``H > n/4`` ("weakly identified"). Only the second is
    reachable **through the public function**, and this test records the
    measurement rather than fabricating a fixture for the first. The first tier is
    covered UNIT-wise by the two tests below, which is the honest way to exercise
    a branch the integration path cannot produce.

    **The measurement.** ``H >= n`` requires ``phi >= -ln(2)/n``, i.e. the fitted
    AR(1) slope must be TINY. Swept 2026-09-23:

    * independent random walks, ``n`` from 100 to 3200, four seeds each — the
      ratio ``H/n`` *shrinks* with ``n`` (mean 0.14 at n=100, 0.05 at n=3200) and
      the worst observed was ``0.39`` (n=800, seed 14). Never reached 1.0;
    * AR(1) errors with ``rho`` from 0.9995 to 0.99999, ``n`` up to 8000 — never
      reached 1.0, because a longer sample estimates ``phi`` more precisely and
      the estimator is consistent;
    * ``y = x + z`` with an EXACT mean-reverting ``z`` at ``kappa`` down to
      0.0005, ``n`` from 60 to 200 — the fitted ``phi`` came out 3-10x larger in
      magnitude than the tier requires, because the first-step residual is
      dominated by the regression rather than by the injected deviation.

    The tier is therefore **dead in practice but not in principle**: nothing in
    the estimator forbids a small fitted ``phi`` — a future data source at a
    different cadence would reach it — so removing the branch would be wrong. It
    stays, its mutations are swept (M40 survived the integration suite, which is
    why these unit tests exist), and here is what the integration path can pin:
    that a fixture between a quarter and the full sample fires ONE tier and not
    the other, so the two are distinct code paths and not one collapsed branch.
    """
    y, x = _coint_pair(n=400, seed=1, rho=0.9995)
    result = _cointegration(y, x)
    value = _value(result)
    periods = value["half_life_periods"]
    n_obs = value["n_obs"]
    assert isinstance(periods, float)
    assert isinstance(n_obs, int)

    assert float(n_obs) / 4.0 < periods < float(n_obs), (
        f"this fixture is meant to sit in the quarter tier, got H={periods} of {n_obs}"
    )
    assert any("EXCEEDS A QUARTER OF THE SAMPLE" in w for w in result.warnings)
    assert not any("LONGER THAN THE SAMPLE" in w for w in result.warnings)


def test_the_unusable_tier_fires_at_the_unit_level() -> None:
    """The ``H >= n`` branch, exercised directly because the API cannot reach it.

    A half-life of 150 periods from a 100-observation window is arithmetically
    correct and, practically, indistinguishable from no reversion. The disclosure
    must fire and must say WHICH tier it is — a function that emitted the
    quarter-sample text here would understate the problem by an order of magnitude.
    """
    disclosure = _econ._half_life_disclosure(
        {"periods": 150.0, "phi": -0.00462, "note": "synthetic"},
        100,
    )
    assert disclosure is not None
    assert "LONGER THAN THE SAMPLE" in disclosure
    assert "150.0" in disclosure
    assert "100" in disclosure


def test_the_unit_level_tiers_do_not_overlap() -> None:
    """``H >= n``, ``n/4 < H < n``, and ``H <= n/4`` are three disjoint outcomes.

    Exercised at the unit level so all three are covered without needing an
    integration fixture for each. ``None`` (no half-life at all) is a FOURTH
    outcome and must produce no disclosure — there is nothing to disclose.
    """

    def disclose(periods: float | None, n_obs: int) -> str | None:
        return _econ._half_life_disclosure(
            {"periods": periods, "phi": -0.01, "note": "synthetic"},
            n_obs,
        )

    unusable = disclose(150.0, 100)  # H >= n
    quarter = disclose(50.0, 100)  # n/4 < H < n
    fine = disclose(10.0, 100)  # H <= n/4
    missing = disclose(None, 100)  # no half-life

    assert unusable is not None and "LONGER THAN THE SAMPLE" in unusable
    assert quarter is not None and "QUARTER OF THE SAMPLE" in quarter
    assert fine is None
    assert missing is None


def test_a_short_half_life_is_not_disclosed() -> None:
    """NEGATIVE CONTROL: a well-resolved half-life must produce NO disclosure.

    Without this, a disclosure that always fired would pass the test above. The
    cointegrated fixture's half-life is ``1.87`` against 400 rows — three orders
    of magnitude inside the threshold.
    """
    y, x = _coint_pair()
    result = _cointegration(y, x)
    assert not any("HALF-LIFE" in w and "SAMPLE" in w for w in result.warnings)


# --- the regime-stability check -------------------------------------------


def test_regime_stability_supports_a_stable_pair() -> None:
    """Both halves must independently reject for the `stable` verdict."""
    y, x = _coint_pair()
    value = _value(_cointegration(y, x))
    assert value["regime_stability"] == "stable"
    assert value["regime_stability_agreement"] is True


def test_regime_stability_detects_an_engineered_break() -> None:
    """The `unstable` verdict: one half cointegrates, the other does not."""
    y, x = _split_regime_pair()
    result = _cointegration(y, x)
    value = _value(result)
    assert value["regime_stability"] == "unstable"
    assert value["regime_stability_agreement"] is False
    assert any("REGIME INSTABILITY" in w for w in result.warnings)


def test_regime_stability_reports_absence_in_both_halves() -> None:
    """`absent_in_both_halves` is a DIFFERENT finding from `unstable`.

    A classifier that said "not stable" for both would pass the two tests above
    taken together with this one only if it also returned the same string — which
    is what this asserts against.
    """
    y, x = _independent_walks()
    result = _cointegration(y, x)
    value = _value(result)
    assert value["regime_stability"] == "absent_in_both_halves"
    assert any("NOT REPRODUCED BY EITHER HALF" in w for w in result.warnings)
    # The two findings must not collapse into one label.
    assert value["regime_stability"] != "unstable"


def test_a_short_sample_reports_not_tested_rather_than_stable() -> None:
    """An UNTESTED half is an absence of information, not evidence of stability.

    A 100-row sample splits into two 50-row halves, below the 60-observation
    floor, so neither half is tested. Measured 2026-09-23: the full-sample test
    still rejects (``-5.8713``, p ``0.0000``) and the verdict is ``not_tested``.

    The `agreement` flag is **False** here even though nothing disagreed. This
    test pins that, because it is a genuine ambiguity in the published shape: a
    consumer cannot distinguish "we did not run it" from "they disagreed" without
    reading the verdict. The warning text must therefore carry the distinction —
    which is what the second assertion checks.
    """
    y, x = _coint_pair(n=100)
    result = _cointegration(y, x)
    value = _value(result)

    assert value["regime_stability"] == "not_tested"
    assert value["n_obs"] == 100
    assert any("NOT TESTED" in w for w in result.warnings)


def test_regime_stability_verdict_is_always_one_of_the_four() -> None:
    """A Literal-by-hand: no fixture may produce an unclassified verdict."""
    allowed = {"stable", "unstable", "absent_in_both_halves", "not_tested"}
    fixtures = (
        _coint_pair(),
        _independent_walks(),
        _split_regime_pair(),
        _coint_pair(n=100),
    )
    for y, x in fixtures:
        assert _value(_cointegration(y, x))["regime_stability"] in allowed


# --- the two MANDATORY warnings -------------------------------------------


def test_both_mandatory_warnings_fire_on_every_call() -> None:
    """Section 15.18-F makes these unconditional — not conditions of this run.

    Two very different results are checked: a pair that cointegrates and a pair
    that does not. Both must carry both warnings, or a consumer could obtain a
    result that lacks a mandated caveat by choosing a different pair.
    """
    for y, x in (_coint_pair(), _independent_walks()):
        for method in ("engle_granger", "johansen"):
            result = _cointegration(y, x, method=method)
            joined = " ".join(result.warnings)
            assert "BACKWARD-LOOKING" in joined
            assert "MULTIPLE TESTING" in joined.upper() or "MULTIPLE-TESTING" in joined


def test_the_mandatory_warnings_come_first() -> None:
    """Ordering is part of the contract: a truncating consumer must not drop them."""
    y, x = _independent_walks()  # the fixture with the most run-specific warnings
    warnings_ = _cointegration(y, x).warnings
    assert "BACKWARD-LOOKING" in warnings_[0]
    assert "MULTIPLE" in warnings_[1].upper()


def test_the_backward_looking_warning_names_ltcm() -> None:
    """The warning cites the case it is drawn from, not an abstraction."""
    assert "LTCM" in _cointegration(*_coint_pair()).warnings[0]


def test_the_multiple_testing_warning_quotes_computed_counts() -> None:
    """The COUNTING obligation — a number, not an adjective.

    ``1 - (1 - alpha)^m`` and ``1 - (1 - alpha)^(1/m)`` at the configured size and
    family must appear in the published fields, and the warning must quote them.
    Asserting only that the warning "mentions" multiple testing would pass on a
    sentence with no arithmetic in it, which is exactly what Section 15.18-F
    rules out.
    """
    alpha = float(get_settings().econometrics.significance_level.value)
    family = int(get_settings().econometrics.assumed_test_family_size.value)
    y, x = _coint_pair()
    result = _cointegration(y, x)
    value = _value(result)

    assert value["family_size_assumed"] == family
    assert value["family_wise_error_rate"] == pytest.approx(1 - (1 - alpha) ** family)
    assert value["corrected_per_test_size"] == pytest.approx(1 - (1 - alpha) ** (1 / family))

    warning = next(w for w in result.warnings if "MULTIPLE" in w.upper())
    assert f"{value['family_wise_error_rate']:.4f}" in warning
    assert f"{value['corrected_per_test_size']:.8f}" in warning


def test_the_multiple_testing_count_follows_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move the family size and require the published counts to MOVE.

    Without this the fields could be computed at import time from a literal, and
    the test above — which reads the same config — would not notice. M11 of the
    sweep is the corresponding mutation: hardcode the family size.
    """
    settings = get_settings()
    monkeypatch.setattr(settings.econometrics.assumed_test_family_size, "value", 40, raising=False)
    alpha = float(settings.econometrics.significance_level.value)

    value = _value(_cointegration(*_coint_pair()))
    assert value["family_size_assumed"] == 40
    assert value["family_wise_error_rate"] == pytest.approx(1 - (1 - alpha) ** 40)
    assert value["corrected_per_test_size"] == pytest.approx(1 - (1 - alpha) ** (1 / 40))
    # A larger family must RAISE the family-wise rate: a sign check, because a
    # reciprocal error would keep the number plausible.
    assert float(value["family_wise_error_rate"]) > 0.80


def test_the_family_size_is_published_as_an_assumption() -> None:
    """The number is unverifiable here and the warning must say so."""
    warning = next(w for w in _cointegration(*_coint_pair()).warnings if "MULTIPLE" in w.upper())
    assert "ASSUMPTION" in warning


# --- the method split -----------------------------------------------------


def test_johansen_reports_no_p_value_rather_than_inventing_one() -> None:
    """Johansen's statistic has no closed-form p-value; ``nan`` beats a guess."""
    y, x = _coint_pair()
    result = _cointegration(y, x, method="johansen")
    value = _value(result)

    assert value["method"] == "johansen"
    assert value["p_value"] != value["p_value"], "p_value must be NaN on this path"
    assert any("NO P-VALUE" in w for w in result.warnings)
    # The verdict is still available, from the critical values.
    assert isinstance(value["is_cointegrated"], bool)


def test_johansen_does_not_normalise_a_hedge_ratio() -> None:
    """On a pair Johansen estimates a VECTOR; publishing one slope would mislead."""
    value = _value(_cointegration(*_coint_pair(), method="johansen"))
    assert value["hedge_ratio"] is None
    assert value["spread"] == []
    assert value["half_life_periods"] is None


def test_johansen_does_not_leak_statsmodels_warnings() -> None:
    """The fourth silent failure: an UNCAPTURED library warning escaping the API.

    ``coint_johansen`` emits four ``ComplexWarning``s from its internal
    eigendecomposition on EVERY call. Left uncaptured they escape to the caller —
    so a consumer running under ``-W error`` gets an exception raised out of this
    model function, and one running normally sees statsmodels' advice attributed
    to the module's own output.

    Measured 2026-09-23: the warnings fire at every sample size (n = 60 … 1600) and
    NEVER coincide with a non-finite statistic, so they are library noise and not
    a signal about the pair. This test requires (a) nothing escapes and (b) the
    capture is DISCLOSED, because suppressing a warning while saying nothing is
    the trap the disclosure exists to avoid.
    """
    y, x = _coint_pair()
    with warnings.catch_warnings(record=True) as escaped:
        warnings.simplefilter("always")
        result = _cointegration(y, x, method="johansen")

    assert [w.category.__name__ for w in escaped] == [], (
        f"statsmodels warnings escaped the model function: {[str(w.message) for w in escaped]}"
    )
    value = _value(result)
    assert value["discarded_imaginary_warnings"] > 0
    assert any("COMPLEX RESIDUE" in w for w in result.warnings)


def test_johansen_does_not_raise_under_warning_as_error() -> None:
    """The consequence of the leak, stated as the behaviour it broke.

    Under ``-W error`` the leaked ``ComplexWarning`` became a raised exception on
    every Johansen call — so a consumer could not use this method at all. This is
    the test that would have failed before the fix.
    """
    y, x = _coint_pair()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = _cointegration(y, x, method="johansen")
    assert _value(result)["method"] == "johansen"


def test_the_engle_granger_path_does_not_claim_a_discarded_residue() -> None:
    """NEGATIVE CONTROL: the field is present on both paths and is ZERO here."""
    y, x = _coint_pair()
    with warnings.catch_warnings(record=True) as escaped:
        warnings.simplefilter("always")
        result = _cointegration(y, x)

    assert [w.category.__name__ for w in escaped] == []
    assert _value(result)["discarded_imaginary_warnings"] == 0
    assert not any("COMPLEX RESIDUE" in w for w in result.warnings)


def test_a_bad_method_name_is_refused() -> None:
    y, x = _coint_pair()
    with pytest.raises(ValueError, match="method must be one of"):
        _cointegration(y, x, method="granger")


def test_a_non_string_method_is_refused() -> None:
    y, x = _coint_pair()
    with pytest.raises(TypeError, match="must be a string"):
        _cointegration(y, x, method=5)  # type: ignore[arg-type]


# --- confidence and provenance --------------------------------------------


def test_the_cointegration_confidence_is_derived_not_asserted() -> None:
    """The confidence must equal what ``compute_confidence`` gives, not a literal.

    Named with the ``cointegration`` qualifier rather than the bare
    ``test_confidence_is_derived_not_asserted`` it started as: that name was
    already taken by ``run_regression``'s guard above, and pytest keeps only the
    LAST definition of a duplicated name, so the earlier test was silently
    dropped from the run. Four other names in this section collided the same way
    (all five against the older ``test_stationarity`` refusals) and ruff's F811
    is what surfaced it — a green suite that had quietly LOST five guards is
    precisely the failure this project's gates exist to catch.
    """
    y, x = _coint_pair()
    result = _cointegration(y, x)
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _econ._cointegration_thresholds_calibrated(),
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == expected


def test_both_series_are_recorded_as_inputs() -> None:
    """Section 9: the result must name what it consumed."""
    y, x = _coint_pair()
    result = _cointegration(y, x)
    assert "y:y" in result.inputs_used
    assert "x:x" in result.inputs_used


def test_the_verdict_is_reflected_in_the_interpretation() -> None:
    """A reader who sees only the prose must not be told the opposite."""
    rejected = _cointegration(*_coint_pair())
    not_rejected = _cointegration(*_independent_walks())
    assert "cointegrat" in rejected.interpretation.lower()
    assert rejected.interpretation != not_rejected.interpretation


def test_limitations_name_the_backward_looking_and_untested_preconditions() -> None:
    result = _cointegration(*_coint_pair())
    joined = " ".join(result.limitations)
    assert "I(1)" in joined, "the i(1) precondition must be stated"
    assert "not" in joined.lower()


def test_decision_prohibition_forbids_sizing_and_family_selection() -> None:
    """Section 3's load-bearing field on the disciplines this function risks."""
    prohibitions = _cointegration(*_coint_pair()).decision_prohibition
    joined = " ".join(prohibitions).lower()
    assert "half-life" in joined or "half life" in joined
    assert "family" in joined or "multiple" in joined
    for prohibition in prohibitions:
        lowered = prohibition.lower()
        assert any(n in lowered for n in ("do not", "must not", "never"))


def test_model_name_is_stable_for_cointegration() -> None:
    assert _cointegration(*_coint_pair()).model_name == "test_cointegration"


# --- the collinearity guard ----------------------------------------------


def test_a_near_collinear_pair_is_refused() -> None:
    """Silent failure #1: ``coint_t = -inf`` with ``p = 0.0`` and only a warning.

    An infinitely significant result from a degenerate first-step regression. It
    LOOKS like the strongest possible evidence of cointegration. The refusal must
    be OURS, matched on a phrase unique to this module — the D-094 lesson is that
    matching a phrase statsmodels could also raise tests the library, not us.
    """
    rng = np.random.default_rng(3)
    n = 300
    index = pd.RangeIndex(n)
    x = pd.Series(np.cumsum(rng.normal(size=n)), index=index, name="x")
    y = pd.Series(
        2.0 + 1.5 * x.to_numpy() + 1e-13 * rng.normal(size=n),
        index=index,
        name="y",
    )
    with pytest.raises(ValueError, match="rank-deficient"):
        _cointegration(y, x)


def test_a_well_conditioned_pair_is_not_flagged_as_collinear() -> None:
    """NEGATIVE CONTROL: the guard must not fire on an ordinary pair.

    A guard that refused everything would pass the test above. The boundary was
    measured against statsmodels' own: at ``R^2 = 0.99997`` the library returns a
    finite statistic and this function must not refuse; only at
    ``R^2 = 0.99999999`` does ``coint_t`` go to ``-inf``.
    """
    rng = np.random.default_rng(3)
    n = 300
    index = pd.RangeIndex(n)
    x = pd.Series(np.cumsum(rng.normal(size=n)), index=index, name="x")
    y = pd.Series(2.0 + 1.5 * x.to_numpy() + 0.05 * rng.normal(size=n), index=index, name="y")
    value = _value(_cointegration(y, x))
    assert math.isfinite(float(value["statistic"]))


# --- refusals -------------------------------------------------------------


def test_a_row_count_mismatch_is_refused() -> None:
    y, x = _coint_pair()
    with pytest.raises(ValueError, match="same number of rows"):
        _cointegration(y, x.iloc[:200])


def test_an_index_mismatch_is_refused() -> None:
    """Same length, different labels: pairing by position would be an assumption."""
    y, x = _coint_pair()
    relabelled = pd.Series(x.to_numpy(), index=pd.RangeIndex(1, len(x) + 1), name="x")
    with pytest.raises(ValueError, match="identical index"):
        _cointegration(y, relabelled)


def test_a_constant_series_is_refused_by_cointegration() -> None:
    """Names the qualifier because ``test_a_constant_series_is_refused`` is
    already ``test_stationarity``'s — a duplicate name is silently shadowed."""
    y, _ = _coint_pair()
    flat = pd.Series([1.0] * len(y), index=y.index, name="flat")
    with pytest.raises(ValueError, match="no variation to co-move with"):
        _cointegration(y, flat)


def test_a_non_finite_series_is_refused_by_cointegration() -> None:
    y, x = _coint_pair()
    with pytest.raises(ValueError, match="non-finite"):
        _cointegration(y, x.where(x.index != 5))


def test_a_non_numeric_series_is_refused_by_cointegration() -> None:
    y, _ = _coint_pair()
    text = pd.Series(["a"] * len(y), index=y.index, name="t")
    with pytest.raises(ValueError, match="must be numeric"):
        _cointegration(y, text)


def test_a_short_pair_is_refused_at_the_cointegration_floor() -> None:
    """The floor is ``cointegration_min_observations``, NOT the stationarity one.

    Engle-Granger spends the sample twice, so the floor is deliberately higher —
    a test that used the sibling's floor would pass at 30 rows and be wrong.
    """
    floor = int(get_settings().econometrics.cointegration_min_observations.value)
    stationary_floor = int(get_settings().econometrics.stationarity_min_observations.value)
    assert floor > stationary_floor, "the cointegration floor must be the higher one"

    y, x = _coint_pair(n=floor - 1)
    with pytest.raises(ValueError, match="below the configured floor"):
        _cointegration(y, x)


def test_a_non_series_is_refused_by_cointegration() -> None:
    y, _ = _coint_pair()
    with pytest.raises(TypeError, match="pandas Series"):
        _cointegration(y, [1.0] * len(y))  # type: ignore[arg-type]


def test_pair_order_is_preserved_not_sorted() -> None:
    """``coint(y, x) != coint(x, y)``, so the two sides are NOT interchangeable.

    Swapping them regresses a different variable on a different one, which gives a
    different residual and a different statistic. A helper that "normalised" the
    argument order would silently change the answer.
    """
    y, x = _coint_pair()
    forward = _value(_cointegration(y, x))
    reverse = _value(_cointegration(x, y))
    assert forward["statistic"] != reverse["statistic"]
    assert forward["hedge_ratio"] != reverse["hedge_ratio"]


# --- the config route that makes two guards unreachable --------------------


def test_the_nan_critical_value_route_is_closed_at_the_config() -> None:
    """Two guards are defence-in-depth, and this is what makes them so.

    ``_run_engle_granger`` refuses a non-finite p-value and non-finite critical
    values. Probed 2026-09-23, the ONLY way to reach either is ``trend="n"``:
    ``coint(..., trend="n")`` returns ``critical_values = [nan, nan, nan]`` (the
    2010 MacKinnon table has no entry for that case). **Both mutations for those
    guards SURVIVED the sweep (M34, M35)** — and for the right reason: the value
    is excluded at the config layer, so the failure cannot be reached through the
    public API at all.

    So this test guards the GUARD-RAISING ROUTE rather than the guard. If ``"n"``
    were ever added to the permitted set — a reasonable-looking change, since
    statsmodels accepts it — M34 and M35 would become live and the sweep would
    have to catch them. Until then they are inert **by construction**, which is
    the honest classification rather than a hole.
    """
    from macro_engine.config import get_settings

    settings = get_settings().econometrics
    assert settings.cointegration_trend in {"c", "ct"}, (
        "the configured deterministic terms must not be 'n'"
    )

    # The exclusion, exercised through the validator. NOTE the level: this is a
    # pydantic `model_validator(mode="after")`, so it runs at CONSTRUCTION and NOT
    # on a later attribute assignment — setting `settings.cointegration_trend =
    # "n"` raises nothing, which is how the first draft of this test failed. The
    # validator is what the config loader calls, so constructing is what tests it.
    import pydantic

    with pytest.raises((ValueError, pydantic.ValidationError), match="must be one of"):
        type(settings).model_validate(
            {
                **{name: getattr(settings, name) for name in type(settings).model_fields},
                "cointegration_trend": "n",
            }
        )


def test_the_non_finite_guards_fire_when_the_route_is_reached() -> None:
    """M34/M35's guards, exercised DIRECTLY because the public path cannot reach them.

    Both mutations SURVIVED the integration suite, and the survival is honest:
    ``coint`` only returns a non-finite p-value or ``[nan, nan, nan]`` critical
    values under ``trend="n"``, which ``econometrics.cointegration_trend``
    excludes at load. So a fixture cannot be built through ``test_cointegration``.

    A permanent survivor is still a hole, though — the guards are real code that
    protects the published verdict if the config ever changes, and an untested
    guard is one nobody knows is broken. So the route is reached the way a caller
    would reach it if the exclusion were lifted: by calling ``_run_engle_granger``
    with ``trend="n"`` explicitly. The guards are asserted to refuse, which is what
    M34 and M35 remove.

    This is the same technique used for the ``H >= n`` disclosure tier: when the
    integration path provably cannot produce a state, test the function that
    handles the state and say in the test why.
    """
    from macro_engine.models import econometrics as _module

    rng = np.random.default_rng(1)
    n = 300
    index = pd.RangeIndex(n)
    x = pd.Series(np.cumsum(rng.normal(size=n)), index=index, name="x")
    y = pd.Series(2.0 + 1.5 * x.to_numpy() + rng.normal(size=n), index=index, name="y")

    # Probe what statsmodels actually returns on this route, so the assertion is
    # against measured behaviour rather than an assumption about NaN handling.
    from statsmodels.tsa.stattools import coint

    raw = coint(y.to_numpy(), x.to_numpy(), trend="n", autolag=_econ._coint_autolag())
    assert not all(math.isfinite(value) for value in raw.critical_values), (
        "the premise of this test is that trend='n' yields non-finite criticals; "
        f"statsmodels returned {raw.critical_values!r}"
    )

    with pytest.raises(ValueError, match="non-finite"):
        _module._run_engle_granger(y, x, trend="n", alpha=0.05)


# ===========================================================================
# compute_pca — Section 15.20-F's fourth function
# ===========================================================================

#: A three-factor yield panel, generated deterministically. The generator is the
#: KEY to these tests: it builds the panel from known level/slope/curvature
#: shocks, so a test can assert that the recovered components correspond to the
#: shocks it constructed rather than accepting whatever the decomposition
#: returned. The names are real tenor labels so a failure message reads like a
#: curve problem.
_PCA_TENORS = ["3mo", "2yr", "5yr", "10yr", "30yr"]
#: The true factor loadings. Columns are level, slope, curvature; rows are
#: tenors. Signs are chosen so PC1 is all-one, PC2 runs front-to-back and PC3
#: has a single interior peak -- the textbook yield-curve shape.
_PCA_TRUE_LOADINGS = np.array(
    [
        [1.0, -1.4, 0.6],
        [1.0, -0.7, -0.4],
        [1.0, 0.0, -0.6],
        [1.0, 0.7, -0.4],
        [1.0, 1.4, 0.6],
    ]
)


def _pca_panel(*, n: int = 260, seed: int = 17) -> pd.DataFrame:
    """A deterministic daily-change panel with three known factors.

    Factor variances descend steeply (the real shape of a curve: the level moves
    most, then the slope, then curvature), which is what makes the component
    ORDERING predictable and therefore assertable.
    """
    rng = np.random.default_rng(seed)
    level = rng.normal(0.0, 0.050, size=n)
    slope = rng.normal(0.0, 0.028, size=n)
    curvature = rng.normal(0.0, 0.014, size=n)
    idiosyncratic = rng.normal(0.0, 0.003, size=(n, len(_PCA_TENORS)))
    values = (
        np.outer(level, _PCA_TRUE_LOADINGS[:, 0])
        + np.outer(slope, _PCA_TRUE_LOADINGS[:, 1])
        + np.outer(curvature, _PCA_TRUE_LOADINGS[:, 2])
        + idiosyncratic
    )
    return pd.DataFrame(values, columns=_PCA_TENORS)


def _pca_result(**kwargs: Any) -> ModelResult:
    return _pca(_pca_panel(**kwargs), 3)


def _loadings(result: ModelResult, component: str) -> dict[str, float]:
    """Extract one component's loadings, asserting the nesting is real."""
    value = _value(result)
    loadings = value["loadings"]
    assert isinstance(loadings, dict)
    component_map = loadings[component]
    assert isinstance(component_map, dict)
    return {str(name): float(loading) for name, loading in component_map.items()}


# --- the report Section 15.20-F demands -----------------------------------


def test_pca_publishes_eigenvalues_ratios_and_loadings() -> None:
    """The three things the signature says it returns must all be present.

    Asserted field-by-field rather than by spot-checking one, because the
    failure this guards against is a result that publishes *some* of the
    report — a caller that gets loadings but no ratios has a chart of arbitrary
    scale, and one that gets ratios but no loadings cannot identify a factor.
    """
    value = _value(_pca_result())
    for key in (
        "eigenvalues",
        "explained_variance_ratios",
        "cumulative_explained_variance",
        "loadings",
        "n_obs",
        "n_variables",
        "standardisation",
        "sign_rule",
    ):
        assert key in value, f"value is missing {key!r}: {sorted(value)}"


def test_pca_ratios_sum_to_one() -> None:
    """The explained-variance ratios are shares of one total, so they sum to 1.

    A derivation check, not a tautology: the ratios would still look plausible
    if the total were taken over the WRONG number of eigenvalues (only the
    requested components, say), and this is the assertion that catches it.
    """
    value = _value(_pca_result())
    ratios = value["explained_variance_ratios"]
    assert isinstance(ratios, list)
    assert math.isclose(sum(ratios), 1.0, rel_tol=0.0, abs_tol=1e-12), (
        f"ratios sum to {sum(ratios)!r}, not 1.0"
    )


def test_pca_eigenvalues_are_all_positive_and_descending() -> None:
    """Every eigenvalue is a variance, so none may be negative, and the order is by size.

    This is the assertion that would have caught silent failure #1 if the rank
    guard were absent — and it is kept *alongside* the guard, because a guard and
    a test that check the same property from different directions fail
    differently: the guard names the cause, this names the symptom.
    """
    value = _value(_pca_result())
    eigenvalues = value["eigenvalues"]
    assert isinstance(eigenvalues, list)
    assert all(float(value_) >= 0.0 for value_ in eigenvalues), (
        f"a negative variance was published: {eigenvalues!r}"
    )
    assert eigenvalues == sorted(eigenvalues, reverse=True), (
        f"eigenvalues are not in descending order: {eigenvalues!r}"
    )


def test_pca_recovers_the_level_factor_first() -> None:
    """PC1 on a curve panel is the factor the generator built with the largest variance.

    The assertion is on the **loading pattern** rather than on a label, which is
    the whole discipline Section 15.20-F demands: a level factor has loadings of
    the same sign on every tenor. The test therefore verifies the components are
    recoverable from the loadings without the function ever naming them.
    """
    loadings = _loadings(_pca_result(), "PC1")
    assert all(loading > 0.0 for loading in loadings.values()), (
        f"PC1's loadings do not share a sign, so there is no level-shaped factor: {loadings}"
    )


def test_pca_orders_components_by_variance_not_by_tenor() -> None:
    """The component ORDER tracks the factor variances, which the generator fixes.

    Independent of the loadings: it asserts the eigenvalues, which descend
    steeply because the generator's factor variances do (0.050^2, 0.028^2,
    0.014^2). A decomposition that returned them unsorted, or paired a variance
    with the wrong factor, fails here.
    """
    value = _value(_pca_result())
    ratios = value["explained_variance_ratios"]
    assert isinstance(ratios, list)
    assert float(ratios[0]) > 0.60, (
        f"the level factor should dominate this panel; PC1 is only {float(ratios[0]):.3f}"
    )
    assert ratios[0] > ratios[1] > ratios[2], f"ordering lost: {ratios}"


def test_pca_loadings_are_unit_norm() -> None:
    """Each component is a unit vector — the definition, checked rather than assumed.

    An eigenvector of a covariance matrix is normalised by LAPACK, but the sign
    rule MULTIPLIES a column by -1, so a sign-rule bug that dropped the norm (or
    scaled by the wrong factor) would leave every loading plausible and the
    components non-orthonormal. This is the cheap invariant that catches it.
    """
    result = _pca_result()
    for position in range(1, 4):
        loadings = _loadings(result, f"PC{position}")
        norm = math.sqrt(sum(loading**2 for loading in loadings.values()))
        assert math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-9), (
            f"PC{position} has norm {norm!r}, not 1.0"
        )


def test_pca_components_are_orthogonal() -> None:
    """Successive components are orthogonal — a property the sign rule preserves.

    Orthogonality is what makes "PC2 is variance PC1 does not explain" true. A
    transposed loadings matrix, or one whose columns were reordered separately
    from its eigenvalues, breaks it while leaving every published number in
    range.
    """
    result = _pca_result()
    vectors = [
        np.array(list(_loadings(result, f"PC{position}").values())) for position in range(1, 4)
    ]
    for left in range(len(vectors)):
        for right in range(left + 1, len(vectors)):
            dot = float(np.dot(vectors[left], vectors[right]))
            assert math.isclose(dot, 0.0, rel_tol=0.0, abs_tol=1e-9), (
                f"PC{left + 1} and PC{right + 1} are not orthogonal: inner product {dot!r}"
            )


def test_pca_cumulative_variance_is_the_running_sum() -> None:
    """The cumulative series is the prefix sum of the ratios, to full precision."""
    value = _value(_pca_result())
    ratios = [float(x) for x in value["explained_variance_ratios"]]
    cumulative = [float(x) for x in value["cumulative_explained_variance"]]
    expected = [sum(ratios[: position + 1]) for position in range(len(ratios))]
    for got, want in zip(cumulative, expected, strict=True):
        assert math.isclose(got, want, rel_tol=0.0, abs_tol=1e-12), (
            f"cumulative {got!r} != prefix sum {want!r}"
        )
    assert math.isclose(cumulative[-1], 1.0, rel_tol=0.0, abs_tol=1e-12)


def test_pca_n_components_share_is_the_prefix_sum() -> None:
    """``n_components_explained_variance`` is the first-k share, not the total."""
    value = _value(_pca_result())
    ratios = [float(x) for x in value["explained_variance_ratios"]]
    share = float(value["n_components_explained_variance"])
    assert math.isclose(share, sum(ratios[:3]), rel_tol=0.0, abs_tol=1e-12), (
        f"the 3-component share {share!r} is not the sum of the first three ratios"
    )
    assert share < 1.0 + 1e-12


# --- the sign rule: a CONVENTION, and the test that proves it fires --------


def test_pca_sign_rule_makes_the_largest_loading_positive() -> None:
    """Every component's largest-|loading| element is positive. sklearn's rule."""
    result = _pca_result()
    for position in range(1, 4):
        loadings = _loadings(result, f"PC{position}")
        values = list(loadings.values())
        pivot = int(np.argmax(np.abs(values)))
        assert values[pivot] > 0.0, (
            f"PC{position}'s largest-magnitude loading is {values[pivot]!r}, not positive; "
            f"the svd_flip convention was not applied: {loadings}"
        )


def test_pca_sign_rule_is_deterministic_under_negation() -> None:
    """Negating the whole panel must not change a single published loading.

    **This is the test that proves the sign rule does something.** Eigenvector
    signs are LAPACK-arbitrary, so without the rule the same panel can come back
    as ``v`` or ``-v``; negating the input flips the covariance's off-diagonal
    structure in a way that can flip an ``eigh`` sign, and the rule has to
    absorb it. Measured: the two results are byte-identical, which is what makes
    this a real assertion rather than a tautology.
    """
    panel = _pca_panel()
    forward = _pca(panel, 3)
    negated = _pca(-panel, 3)
    for position in range(1, 4):
        assert _loadings(forward, f"PC{position}") == _loadings(negated, f"PC{position}"), (
            f"PC{position}'s loadings changed when the panel was negated, so the "
            f"sign convention is not absorbing the arbitrary eigenvector sign"
        )


def test_pca_sign_rule_is_named_in_the_output() -> None:
    """The convention is published, because a loading sign is not self-describing."""
    value = _value(_pca_result())
    assert "largest_absolute_loading_positive" in str(value["sign_rule"])


# --- the normalisation: the measured 1/(n-1) divisor -----------------------


def test_pca_uses_the_unbiased_covariance_divisor() -> None:
    """The ratios match a hand-built ``np.cov`` decomposition, not a ``1/n`` one.

    **This pins the measurement D-099 recorded.** sklearn's
    ``explained_variance_ratio_`` divides by the total that ``np.cov`` produces
    (the ``1/(n-1)`` sum), not the biased ``1/n`` total its own source suggests
    at a glance; measured agreement ``0.9999999999999994``. The two differ by
    ``(n-1)/n``, which is 0.4% at ``n = 260`` — small enough to pass a loose
    comparison and large enough to be a real bias. So the expectation is built
    independently from ``np.cov`` and compared at 1e-12.
    """
    panel = _pca_panel()
    result = _pca(panel, 3)
    value = _value(result)

    matrix = panel.to_numpy(dtype=float)
    means = matrix.mean(axis=0)
    standardised = (matrix - means) / matrix.std(axis=0, ddof=1)
    expected = np.linalg.eigvalsh(np.cov(standardised, rowvar=False))
    expected = np.sort(expected)[::-1] / expected.sum()

    published = [float(x) for x in value["explained_variance_ratios"]]
    for got, want in zip(published, expected, strict=True):
        assert math.isclose(got, float(want), rel_tol=0.0, abs_tol=1e-12), (
            f"ratio {got!r} does not match the np.cov expectation {float(want)!r}; the "
            f"normalisation divisor is wrong (sklearn uses 1/(n-1), not 1/n)"
        )


def test_pca_eigenvalues_match_the_covariance_spectrum() -> None:
    """The published eigenvalues ARE the covariance's, independently computed."""
    panel = _pca_panel()
    result = _pca(panel, 3)
    value = _value(result)

    matrix = panel.to_numpy(dtype=float)
    standardised = (matrix - matrix.mean(axis=0)) / matrix.std(axis=0, ddof=1)
    expected = np.sort(np.linalg.eigvalsh(np.cov(standardised, rowvar=False)))[::-1]

    published = [float(x) for x in value["eigenvalues"]]
    for got, want in zip(published, expected, strict=True):
        assert math.isclose(got, float(want), rel_tol=1e-9, abs_tol=1e-12), (
            f"eigenvalue {got!r} != {float(want)!r}"
        )


# --- the standardisation choice, measured as consequential -----------------


def test_pca_publishes_the_standardisation_it_used() -> None:
    """A reader is never left to assume which route produced the loadings."""
    value = _value(_pca_result())
    assert value["standardisation"] in {"covariance", "correlation"}


def test_the_two_routes_disagree_materially_on_a_heteroskedastic_panel() -> None:
    """The covariance/correlation choice changes PC1's loadings — measured, then pinned.

    D-099 recorded the measurement (0.28 apart, ordering inverted) as the reason
    the route is a published config leaf rather than an implicit default. This
    test holds the measurement still: if a future change made the two routes
    agree, the *reason* for the leaf would have evaporated and the record would be
    stale, so the test fails and forces the decision to be re-examined.

    **The covariance route is computed here rather than by calling
    ``compute_pca`` twice**, because the public function reads its route from
    config and both calls would therefore take the SAME route — which is exactly
    the mistake this test made on its first run: it compared correlation with
    correlation and reported a difference of exactly 0.0. The route under test is
    reached by re-building its standardised matrix and decomposing it, and the
    public function is then used as the ORACLE for the route it is configured
    with, which is the only claim it can support.
    """
    matrix = _pca_panel().to_numpy(dtype=float)
    # Match the measurement's shape: a curve whose front end moves most.
    scales = np.array([1.90, 1.30, 1.00, 0.85, 0.70])
    heteroskedastic = matrix * scales

    def pc1_abs_loadings(candidate: np.ndarray) -> np.ndarray:
        """|PC1 loadings| under the covariance route, computed step by step."""
        passed = _econ._apply_sign_rule(_econ._decompose(candidate)[1])
        return np.abs(passed[:, 0])

    covariance_route = pc1_abs_loadings(heteroskedastic)

    # The configured route, through the public function — asserted to BE the
    # correlation route so this comparison cannot silently become self-to-self
    # again.
    settings = get_settings()
    assert settings.econometrics.pca_standardisation == "correlation", (
        "this test compares the covariance route against the configured one and "
        f"assumes the configuration is 'correlation'; it is "
        f"{settings.econometrics.pca_standardisation!r}"
    )
    standardised = (heteroskedastic - heteroskedastic.mean(axis=0)) / heteroskedastic.std(
        axis=0, ddof=1
    )
    configured_route = np.abs(
        np.array(
            list(
                _loadings(
                    _pca(pd.DataFrame(heteroskedastic, columns=_PCA_TENORS), 3), "PC1"
                ).values()
            ),
            dtype=float,
        )
    )

    # The public function's output equals the correlation-route decomposition,
    # so the route identity is measured rather than assumed.
    assert np.allclose(configured_route, pc1_abs_loadings(standardised), atol=1e-12), (
        "the configured route's loadings do not match a hand-computed correlation "
        "decomposition, so the route being tested is not the one assumed"
    )

    assert np.abs(covariance_route - configured_route).max() > 0.05, (
        "the covariance and correlation routes no longer disagree on PC1's "
        "loadings — the measurement that justifies the pca_standardisation leaf "
        "has changed and the record needs re-examining"
    )

    # And the DISAGREEMENT IS AN ORDERING INVERSION, which is the part that makes
    # the choice dangerous rather than merely different: the tenor the covariance
    # route loads most heavily is not the one the correlation route does.
    assert int(np.argmax(covariance_route)) != int(np.argmax(configured_route)), (
        f"both routes now load PC1 most heavily on "
        f"{_PCA_TENORS[int(np.argmax(covariance_route))]}, so the inversion the "
        f"measurement recorded is gone: covariance {covariance_route}, "
        f"correlation {configured_route}"
    )


# --- refusals: silent failures #1, #2, #3 ---------------------------------


def test_a_rank_deficient_panel_is_refused() -> None:
    """Silent failure #1's guard: a duplicated series cannot be decomposed.

    Without this refusal the covariance's eigendecomposition returns a NEGATIVE
    eigenvalue, and the ``explained_variance_ratios`` still sum to 1.0, so the
    result looks complete while publishing a negative variance.
    """
    frame = _pca_panel()
    frame["2yr"] = frame["3mo"]  # an exact duplicate
    with pytest.raises(ValueError, match="rank-deficient"):
        _pca(frame, 3)


def test_a_perfectly_collinear_panel_is_refused() -> None:
    """``b = 2a`` is rank-deficient too — the shape that produced -1.69e-15."""
    frame = _pca_panel()
    frame["5yr"] = 2.0 * frame["3mo"]
    with pytest.raises(ValueError, match="rank-deficient"):
        _pca(frame, 3)


def test_a_constant_series_is_refused_by_pca() -> None:
    """A flat series carries no variance, and ``std == 0`` would not catch it.

    The name carries the ``_by_pca`` suffix because O-117 is a live hazard, not
    a closed one: four ``test_cointegration`` tests once reused
    ``test_stationarity``'s names, Python bound each module-level name to its
    LAST definition, and the sweep's M2/M30/M32 were reported as surviving for a
    whole increment because they were being killed (or not) by tests that no
    longer covered the mutated path. The same collision reappeared here when
    this test was first written as ``test_a_constant_series_is_refused`` --
    a duplicate of the ``test_stationarity`` guard at line 762 -- which made the
    stationarity guard's coverage DEAD while looking present. ``ruff``'s F811
    is the standing guard; the suffix is what keeps the two names distinguishable
    when a reader greps for either.

    The column is a NON-ZERO constant (``4.2``) deliberately: the measured
    near-miss is that its floating-point spread is ``8.9e-16`` rather than
    ``0.0``, so both a naive equality test and the rank check's relative
    tolerance let it through.
    """
    frame = _pca_panel()
    frame["10yr"] = 4.2
    with pytest.raises(ValueError, match="constant"):
        _pca(frame, 3)


def test_an_all_zero_series_is_refused() -> None:
    """The all-zero column is the same defect with a zero scale."""
    frame = _pca_panel()
    frame["30yr"] = 0.0
    with pytest.raises(ValueError, match="constant"):
        _pca(frame, 3)


def test_the_constant_series_refusal_names_the_offending_series() -> None:
    """A refusal that does not name the column is not actionable."""
    frame = _pca_panel()
    frame["5yr"] = -3.0
    with pytest.raises(ValueError, match=r"\['5yr'\]"):
        _pca(frame, 3)


# The tolerance must be RELATIVE to each series' own scale. The three tests
# above all use a constant whose floating-point residue happens to be small
# (4.2 -> ~9e-16, 0.0 -> exactly 0.0, -3.0 -> exactly 0.0), so they are all
# satisfied by an ABSOLUTE epsilon as well -- which is why the mutation sweep's
# M66 (tolerance reverted to a fixed threshold) initially SURVIVED.
#
# Measured 2026-09-23, and the WEIRDNESS IS THE POINT. A constant column's
# floating-point residue is not monotone in its magnitude: it depends on how
# `c - mean` rounds at that particular scale. So the magnitudes that defeat an
# absolute `eps * 100 = 2.22e-14` are specific ones, not "large" ones:
#
#     const 4.2     residue 7.1e-14   above 2.22e-14 -> defeats the absolute test
#     const 42.0    residue 7.1e-14   (same magnitude, same conclusion)
#     const 271.83  residue 1.1e-13   clearly above -> DEFEATS it (this is the killer)
#     const 314.16  residue 4.3e-14   above -> defeats it
#     const 1e6     residue exactly 0 -> does NOT defeat it
#
# So the parametrisation below is chosen for the ones that are PROVEN to kill
# it -- verified by applying the M66 mutant by hand and observing this test
# fail -- rather than for the ones that look large. `42.0` is retained in the
# first case as the plausible-value case, and its assertion is honest either
# way: it is refused under the real (relative) guard, which is what is being
# tested here. The mutation sweep is what proves the relative/absolute
# distinction is load-bearing, and it is run separately.
@pytest.mark.parametrize("constant", [42.0, 271.8281828459045, 314.1592653589793])
def test_the_constant_refusal_is_scale_relative_not_absolute(constant: float) -> None:
    """A constant is refused whatever its magnitude, relative to its own scale.

    ``42.0`` is the plausible-value case -- a 42-week series, a parity level, a
    fixed spread. The other two are the magnitudes whose residues are measured
    to exceed an absolute epsilon, so they are the ones that make this test
    falsify a fixed-threshold guard rather than merely agree with it.
    """
    frame = _pca_panel()
    frame["10yr"] = constant
    with pytest.raises(ValueError, match="constant"):
        _pca(frame, 3)


def test_the_constant_refusal_fires_on_both_standardisation_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard sits BEFORE standardisation, so it governs covariance too.

    This is the half the covariance route would otherwise lose: checked after
    standardisation, the covariance route has no division to amplify the
    residue and the column is invisible beside the larger ones. The route is
    switched here through the real settings tree rather than by calling the
    private helper, so the guard's position relative to standardisation is
    what is actually under test.
    """
    settings = get_settings()
    for route in ("correlation", "covariance"):
        monkeypatch.setattr(settings.econometrics, "pca_standardisation", route, raising=False)
        frame = _pca_panel()
        frame["10yr"] = 42.0
        with pytest.raises(ValueError, match="constant"):
            _pca(frame, 3)


def test_low_variance_but_genuine_series_is_not_refused() -> None:
    """The constant guard must not fire on a series that merely moves little.

    The tolerance is relative to each series' own scale, so a genuinely small
    series survives. Without this test, tightening the tolerance to catch more
    constants would silently start refusing valid panels — a false refusal is a
    defect in the opposite direction from a false acceptance, and this project
    treats both as failures.
    """
    frame = _pca_panel()
    rng = np.random.default_rng(4)
    frame["30yr"] = rng.normal(0.0, 1e-6, size=len(frame))
    result = _pca(frame, 3)
    assert result.model_name == "compute_pca"


@pytest.mark.parametrize("requested", [6, 99])
def test_too_many_components_is_refused(requested: int) -> None:
    """Silent failure #2: asking for more components than the panel has series.

    The panel has five tenors, so the maximum is five; anything ABOVE that must
    be refused rather than silently truncated to a shorter list than the
    caller's loop expects. Five itself is legal and is covered separately — a
    bound test that includes its own boundary in the refusal set asserts the
    wrong thing.
    """
    with pytest.raises(ValueError, match="exceeds the number of series"):
        _pca(_pca_panel(), requested)


@pytest.mark.parametrize("requested", [0, -1, -3])
def test_fewer_than_one_component_is_refused(requested: int) -> None:
    """A request for no output is not a PCA."""
    with pytest.raises(ValueError, match="at least 1"):
        _pca(_pca_panel(), requested)


def test_a_float_component_count_is_refused() -> None:
    """``2.0`` would be silently truncated by the index arithmetic."""
    with pytest.raises(TypeError, match="must be an int"):
        _pca(_pca_panel(), 2.0)  # type: ignore[arg-type]


def test_the_exact_component_count_is_permitted() -> None:
    """Asking for exactly the panel's width is legal, not off-by-one."""
    result = _pca(_pca_panel(), len(_PCA_TENORS))
    value = _value(result)
    assert value["n_components"] == 5
    assert isinstance(value["loadings"], dict)
    assert len(value["loadings"]) == 5


@pytest.mark.parametrize(
    "requested",
    [1, 2, 3, 4, 5],
)
def test_every_permitted_component_count_works(requested: int) -> None:
    """Every legal count produces a well-formed result — the bound is not racy."""
    result = _pca(_pca_panel(), requested)
    value = _value(result)
    assert value["n_components"] == requested
    ratios = value["explained_variance_ratios"]
    assert isinstance(ratios, list)
    assert math.isclose(sum(ratios), 1.0, rel_tol=0.0, abs_tol=1e-12)


def test_a_non_finite_panel_is_refused() -> None:
    """Silent failure #3: a NaN propagates into every eigenvalue and loading."""
    frame = _pca_panel()
    frame.iloc[7, 1] = math.nan
    with pytest.raises(ValueError, match="non-finite"):
        _pca(frame, 3)


def test_the_non_finite_refusal_names_the_offending_series() -> None:
    """The refusal must name the column, not just say 'a value is NaN'."""
    frame = _pca_panel()
    frame.iloc[3, 2] = math.inf
    with pytest.raises(ValueError, match="5yr"):
        _pca(frame, 3)


def test_a_non_numeric_series_is_refused_by_pca() -> None:
    """An object column that looks numeric is a real way to get a wrong answer.

    Suffixed for the same O-117 reason as ``test_a_constant_series_is_refused_by_pca``:
    the unsuffixed name is already owned by the ``test_stationarity`` guard.
    """
    frame = _pca_panel()
    frame["2yr"] = ["x"] * len(frame)
    with pytest.raises(ValueError, match="must be numeric"):
        _pca(frame, 3)


def test_a_bool_series_is_refused() -> None:
    """Booleans are numeric in numpy's eyes and not a price series."""
    frame = _pca_panel()
    frame["2yr"] = True
    with pytest.raises(ValueError, match="must be numeric"):
        _pca(frame, 3)


def test_a_non_frame_is_refused() -> None:
    """A bare ndarray has no column names, and the loadings are keyed by them."""
    with pytest.raises(TypeError, match="must be a pandas DataFrame"):
        _pca(_pca_panel().to_numpy(), 3)  # type: ignore[arg-type]


def test_a_single_series_is_refused() -> None:
    """One series has no component to find; its PC1 is itself with a ratio of 1.0."""
    frame = _pca_panel()[["2yr"]]
    with pytest.raises(ValueError, match="at least two series"):
        _pca(frame, 1)


def test_an_empty_frame_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one series column"):
        _pca(pd.DataFrame(), 3)


def test_duplicate_series_names_are_refused() -> None:
    """The loadings map is keyed by name, so a duplicate silently overwrites."""
    frame = _pca_panel()
    frame.columns = ["a", "a", "c", "d", "e"]
    with pytest.raises(ValueError, match="duplicate column name"):
        _pca(frame, 3)


def test_a_short_panel_is_refused_at_the_floor() -> None:
    """Below ``pca_min_observations`` the covariance is mostly sampling noise."""
    with pytest.raises(ValueError, match="below the configured floor"):
        _pca(_pca_panel(n=40), 3)


# --- the near-zero disclosure ---------------------------------------------


def test_a_redundant_series_is_disclosed_rather_than_silently_reported() -> None:
    """A component with essentially no variance is flagged as a numerical residual.

    A panel with five series where one is nearly a combination of the others
    yields an eigenvalue at the noise floor. The rank check refuses the EXACT
    case; this is the nearly-exact case, which is legal and over-confident at
    the same time, so it is disclosed.
    """
    frame = _pca_panel()
    rng = np.random.default_rng(9)
    frame["30yr"] = frame["3mo"] + rng.normal(0.0, 1e-11, size=len(frame))
    result = _pca(frame, 3)
    assert any("near-zero tolerance" in warning for warning in result.warnings), (
        f"a near-zero component was not disclosed: {result.warnings}"
    )


def test_a_full_rank_panel_has_no_near_zero_warning() -> None:
    """The disclosure must not fire on a healthy panel — a warning that always fires is noise."""
    result = _pca_result()
    assert not any("near-zero tolerance" in warning for warning in result.warnings), (
        f"a healthy panel was flagged as nearly rank-deficient: {result.warnings}"
    )


def _thin_panel(*, n: int = 70, k: int = 20, seed: int = 31) -> pd.DataFrame:
    """A WIDE panel with few rows per series, so the inflation warning is reachable.

    Five columns cannot reach the warning at all: the configured floor is 60 rows
    and ``60 < 10 * 5`` is false, so a five-tenor curve is admitted at twelve rows
    per series with the inflation present and undisclosed. Twenty columns need
    200 rows to clear the boundary, so 70 rows is comfortably inside the region
    the disclosure covers — and this is the panel shape where the ratio actually
    gets thin in practice.
    """
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 0.05, size=n)
    values = np.outer(factor, np.ones(k)) + rng.normal(0.0, 0.01, size=(n, k))
    return pd.DataFrame(values, columns=[f"t{index:02d}" for index in range(k)])


def test_a_thin_panel_warns_about_the_leading_eigenvalue_bias() -> None:
    """Few rows per series inflate PC1, and the result says so with a number.

    Twenty series on 70 rows is 3.5 rows per series — well inside the region the
    disclosure covers. The warning must carry the measured noise floor rather
    than only the word "biased": a reader told PC1 is inflated has no way to
    judge by how much.
    """
    result = _pca(_thin_panel(), 3)
    assert any("Marchenko-Pastur" in warning for warning in result.warnings), (
        f"the small-sample bias was not disclosed on 70 rows x 20 series: {result.warnings}"
    )
    assert any("rows per series" in warning for warning in result.warnings), (
        f"the disclosure gave no noise-floor number to compare against: {result.warnings}"
    )


def test_the_narrow_panel_case_is_documented_as_uncovered() -> None:
    """The five-tenor case cannot reach the warning, and the limits say so.

    This is the honest half of the decision to leave ``pca_min_observations`` at
    60 rather than raise it: at twelve rows per series the inflation is +0.075
    above the asymptote, which is real but small enough to admit the panel. The
    test asserts the user-facing consequence — a five-column panel at the floor
    gets NO warning — so that if someone later changes the floor or the boundary,
    the documented gap is re-examined rather than silently closed or widened.
    """
    result = _pca(_pca_panel(n=60), 3)
    assert not any("Marchenko-Pastur" in warning for warning in result.warnings), (
        "a five-column panel at the floor now reaches the inflation warning, so the "
        f"documented gap no longer exists: {result.warnings}"
    )
    joined = " ".join(result.limitations)
    assert "DOES NOT COVER A NARROW PANEL" in joined, (
        "the uncovered case is no longer documented in the limitations"
    )


def test_the_noise_floor_rises_as_the_panel_thins() -> None:
    """The published noise floor falls as rows per series rises.

    A derivation check on the interpolation table: on a THINNER panel the noise
    floor must be HIGHER, since the small-sample inflation grows as rows per
    series falls. An interpolation that ran the wrong way — or a table entered in
    the wrong order — would still print a plausible number inside a warning.
    """
    thin = _econ._expected_noise_pc1_share(60, 5)
    middling = _econ._expected_noise_pc1_share(130, 5)
    wide = _econ._expected_noise_pc1_share(500, 5)
    assert thin > middling > wide, (thin, middling, wide)
    assert wide == 1.0 / 5.0, "past the last measurement the floor is the 1/k asymptote"
    assert thin < 1.0


def test_the_noise_floor_is_interpolated_not_stepped() -> None:
    """A value between two table entries lies between them — interpolated, not rounded.

    Stepping to the nearest entry would report the same floor for two panels of
    visibly different width, which is the kind of plausible-looking imprecision
    this project's disclosures are supposed to avoid.
    """
    below = _econ._expected_noise_pc1_share(60, 5)
    between = _econ._expected_noise_pc1_share(80, 5)
    above = _econ._expected_noise_pc1_share(100, 5)
    assert below > between > above, (below, between, above)


def test_the_noise_floor_falls_back_to_the_asymptote_for_another_width() -> None:
    """The table was measured at five columns, so another width gets 1/k, not a guess.

    A scaling law derived from one column count would be the error the table
    exists to avoid, so the fallback is deliberately unconditional.
    """
    assert _econ._expected_noise_pc1_share(60, 3) == 1.0 / 3.0
    assert _econ._expected_noise_pc1_share(60, 11) == 1.0 / 11.0


def test_a_wide_panel_does_not_warn_about_the_bias() -> None:
    """260 rows for 5 series is 52 rows per series, comfortably past the threshold."""
    result = _pca(_pca_panel(n=260), 3)
    assert not any("Marchenko-Pastur" in warning for warning in result.warnings)


def test_a_level_like_column_triggers_the_changes_warning() -> None:
    """The levels-instead-of-changes hazard, made visible from the panel's shape.

    Section 15.20-F says 'daily changes, never levels' and this function cannot
    verify it — but a level series has a near-unit lag-1 autocorrelation, which
    is measurable. This test builds a column that walks (a level) among genuine
    changes and asserts the warning fires.
    """
    frame = _pca_panel()
    rng = np.random.default_rng(12)
    frame["30yr"] = np.cumsum(rng.normal(0.0, 0.01, size=len(frame)))
    result = _pca(frame, 3)
    assert any("lag-1 autocorrelation" in warning for warning in result.warnings), (
        f"a level-like column was not flagged: {result.warnings}"
    )


def test_a_genuine_change_panel_does_not_trigger_the_levels_warning() -> None:
    """The signature test must not fire on real differences."""
    result = _pca_result()
    assert not any("lag-1 autocorrelation" in warning for warning in result.warnings)


def test_a_dominant_pc1_warns_about_a_possible_trend() -> None:
    """PC1 above 95% is worth a levels check even without an autocorrelation tell."""
    frame = _pca_panel()
    rng = np.random.default_rng(21)
    # A single dominant common factor plus near-constant idiosyncratic terms.
    factor = rng.normal(0.0, 0.05, size=len(frame))
    for tenor in _PCA_TENORS:
        frame[tenor] = factor + rng.normal(0.0, 0.0008, size=len(frame))
    result = _pca(frame, 3)
    assert any("checking the input is changes" in warning for warning in result.warnings), (
        f"a >95% PC1 did not prompt a levels check: {result.warnings}"
    )


def test_the_scale_dispersion_warning_fires_on_the_covariance_route() -> None:
    """The covariance route on a scale-dispersed panel weights by variance, and says so.

    Exercised by calling the warning builder directly with ``standardisation=
    "covariance"``, because the configured route is ``correlation`` and the
    warning is unreachable through the public API at that setting. This is the
    same technique the file already uses for the NaN-critical-value route: when
    the configured path provably cannot produce a state, test the function that
    handles the state and say in the test why.
    """
    matrix = _pca_panel().to_numpy(dtype=float)
    matrix = matrix * np.array([50.0, 1.0, 1.0, 1.0, 1.0])
    warnings_ = _econ._pca_warnings(
        eigenvalues=np.array([1.0, 1.0, 1.0, 1.0, 1.0]),
        ratios=np.array([0.2, 0.2, 0.2, 0.2, 0.2]),
        n_obs=len(matrix),
        panel=matrix,
        standardisation="covariance",
        near_zero_threshold=1e-8,
    )
    assert any("scale dispersion" in warning or "noisiest" in warning for warning in warnings_), (
        f"the covariance route did not disclose its variance weighting: {warnings_}"
    )


def test_the_scale_dispersion_warning_is_silent_on_the_correlation_route() -> None:
    """The correlation route gives every series equal weight, so the caveat does not apply."""
    matrix = _pca_panel().to_numpy(dtype=float)
    matrix = matrix * np.array([50.0, 1.0, 1.0, 1.0, 1.0])
    warnings_ = _econ._pca_warnings(
        eigenvalues=np.array([1.0, 1.0, 1.0, 1.0, 1.0]),
        ratios=np.array([0.2, 0.2, 0.2, 0.2, 0.2]),
        n_obs=len(matrix),
        panel=matrix,
        standardisation="correlation",
        near_zero_threshold=1e-8,
    )
    assert not any("noisiest" in warning for warning in warnings_)


# --- the reasoning object --------------------------------------------------


def test_pca_confidence_is_derived_not_asserted() -> None:
    """Section 22.8: the confidence comes from ``compute_confidence``, never a literal."""
    result = _pca_result()
    settings = get_settings()
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not settings.is_calibrated(
                "econometrics.pca_near_zero_tolerance"
            ),
            source_independence_count=0,
            depends_on_unobservable=False,
        )
    )
    assert result.confidence == expected
    assert result.confidence < 1.0


def test_pca_limitations_forbid_a_factor_reading() -> None:
    """The standing limits must say a component is not an economic factor."""
    result = _pca_result()
    joined = " ".join(result.limitations).lower()
    assert "not economic factors" in joined
    assert "sample-specific" in joined


def test_pca_decision_prohibition_forbids_auto_labelling() -> None:
    """Section 15.20-F's explicit prohibition, on the result rather than in prose."""
    result = _pca_result()
    joined = " ".join(result.decision_prohibition).lower()
    assert "must not label the components level/slope/curvature" in joined
    assert "must not be used as a signal on its own" in joined
    assert "read across two pca fits" in joined


def test_pca_records_the_daily_changes_assumption() -> None:
    """The one instruction the function cannot verify is stated as an assumption."""
    result = _pca_result()
    joined = " ".join(result.assumptions).lower()
    assert "daily changes, not levels" in joined


def test_pca_declares_its_standardisation_assumption() -> None:
    result = _pca_result()
    joined = " ".join(result.assumptions)
    assert "correlation" in joined


def test_pca_model_name_is_stable() -> None:
    """A stable identifier is the MLflow key and must not drift."""
    assert _pca_result().model_name == "compute_pca"


def test_pca_names_its_inputs_by_series() -> None:
    """``inputs_used`` names each series, so provenance is per-column."""
    result = _pca_result()
    for tenor in _PCA_TENORS:
        assert f"daily_changes:{tenor}" in result.inputs_used


def test_pca_interpretation_reports_the_component_share() -> None:
    """The interpretation carries the number, not only a sentence."""
    result = _pca_result()
    assert "principal component" in result.interpretation
    assert "%" in result.interpretation


def test_pca_does_not_label_its_components_in_the_interpretation() -> None:
    """The prohibition applies to this function's OWN prose too.

    A function that forbids labelling in ``decision_prohibition`` while its own
    ``interpretation`` says "the level factor" has contradicted itself, and the
    prose is what a reader actually sees first.
    """
    result = _pca_result()
    lowered = result.interpretation.lower()
    for label in ("level factor", "slope factor", "curvature factor"):
        assert label not in lowered, (
            f"the interpretation auto-labelled a component as {label!r}: {result.interpretation}"
        )


def test_pca_context_names_the_standardisation_and_sign_rule() -> None:
    """The context is where a reader learns which conventions produced the numbers."""
    result = _pca_result()
    assert "Standardisation:" in result.context
    assert "Sign convention:" in result.context


# ---------------------------------------------------------------------------
# Kalman filter (Section 15.20-F) — Module 18 #5
#
# Three disciplines this section exists to protect:
#
# * **The state-space specification IS the mechanism.** Section 15.18 requires
#   the mechanism to be stated before the statistics, so the matrices are
#   asserted directly rather than inferred from the output.
# * **The band is part of the answer.** Every state carries a standard error,
#   and the two hand-derived identities below (an identified state's first
#   standard error is sqrt(sigma2.irregular); an unidentified one's is
#   sqrt(kappa)) are what prove the band is computed rather than decorated.
# * **A warning that fires unreliably is worse than none.** The negative
#   controls below are as load-bearing as the positive ones: without them a
#   branch could be satisfied by always firing, which is the D-051 trap.
# ---------------------------------------------------------------------------

_kalman = _econ.kalman_latent_state

_KALMAN_N = 200


def _kalman_level_series() -> np.ndarray:
    """A random walk observed with noise — the r* / potential-GDP shape."""
    rng = np.random.default_rng(0)
    return np.cumsum(rng.normal(0.0, 0.5, _KALMAN_N)) + 100.0 + rng.normal(0.0, 1.0, _KALMAN_N)


def _kalman_trend_series() -> np.ndarray:
    """A level that drifts, so the slope state is genuinely non-zero."""
    rng = np.random.default_rng(1)
    slope = np.cumsum(rng.normal(0.0, 0.05, _KALMAN_N)) + 0.3
    return np.cumsum(slope) + 100.0 + rng.normal(0.0, 1.0, _KALMAN_N)


def _kalman_pair() -> tuple[np.ndarray, np.ndarray]:
    """``(dependent, regressor)`` with a genuinely drifting hedge ratio."""
    rng = np.random.default_rng(2)
    x = np.cumsum(rng.normal(0.0, 0.5, _KALMAN_N)) + 50.0
    beta = 0.5 + np.cumsum(rng.normal(0.0, 0.05, _KALMAN_N))
    return beta * x + rng.normal(0.0, 1.0, _KALMAN_N), x


def _kalman_level_result() -> ModelResult:
    return _kalman(pd.DataFrame({"level_series": _kalman_level_series()}))


def _kalman_trend_result() -> ModelResult:
    return _kalman(pd.DataFrame({"gdp": _kalman_trend_series()}), state_dim=2)


def _kalman_pair_result() -> ModelResult:
    dependent, regressor = _kalman_pair()
    return _kalman(pd.DataFrame({"y_leg": dependent, "x_leg": regressor}))


def _kalman_paths(result: ModelResult, key: str) -> dict[str, list[float]]:
    """Narrow one of the published path mappings, asserting not casting."""
    published = _value(result)[key]
    assert isinstance(published, dict)
    return published


# --- the specification table and the matrices ------------------------------


def test_kalman_local_level_is_the_declared_specification() -> None:
    published = _value(_kalman_level_result())
    assert published["model_spec"] == "local_level"
    assert published["state_names"] == ["level"]
    assert published["state_dim"] == 1


def test_kalman_trend_is_the_level_slope_specification() -> None:
    published = _value(_kalman_trend_result())
    assert published["model_spec"] == "local_linear_trend"
    assert published["state_names"] == ["level", "slope"]


def test_kalman_hedge_ratio_is_the_regression_specification() -> None:
    published = _value(_kalman_pair_result())
    assert published["model_spec"] == "time_varying_hedge_ratio"
    assert published["state_names"] == ["beta"]


def test_kalman_trend_transition_matrix_is_the_level_slope_coupling() -> None:
    """``F = [[1, 1], [0, 1]]``: the slope feeds the level, not the reverse.

    Asserted on the MATRIX rather than on the output, because a transposed
    transition is still a well-formed filter producing a plausible path — the
    defect would be a level that ignores its own slope, which no output check
    would name.
    """
    spec = _econ._KALMAN_SPECS[(1, 2)]
    model = _econ._KalmanStateModel(
        np.array([1.0, 2.0, 3.0]),
        spec=spec,
        design=np.zeros((1, 2, 3)),
        diffuse_scale=1.0e6,
    )
    assert np.array_equal(np.asarray(model["transition"]), np.array([[1.0, 1.0], [0.0, 1.0]]))


def test_kalman_local_level_transition_is_a_random_walk() -> None:
    spec = _econ._KALMAN_SPECS[(1, 1)]
    model = _econ._KalmanStateModel(
        np.array([1.0, 2.0, 3.0]),
        spec=spec,
        design=np.zeros((1, 1, 3)),
        diffuse_scale=1.0e6,
    )
    assert np.array_equal(np.asarray(model["transition"]), np.array([[1.0]]))


def test_kalman_hedge_ratio_design_is_the_regressor_path() -> None:
    """The regressor enters the DESIGN, which is what makes beta a state at all."""
    spec = _econ._KALMAN_SPECS[(2, 1)]
    panel = np.column_stack([np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0])])
    design = _econ._kalman_design(spec, panel)
    assert design.shape == (1, 1, 3)
    assert np.array_equal(design[0, 0, :], np.array([4.0, 5.0, 6.0]))


def test_kalman_trend_design_reads_the_level_and_not_the_slope() -> None:
    """``[1, 0]`` — which is exactly why the slope is unidentified at t = 0."""
    spec = _econ._KALMAN_SPECS[(1, 2)]
    panel = np.array([[1.0], [2.0], [3.0]])
    design = _econ._kalman_design(spec, panel)
    assert np.array_equal(design[0, 0, :], np.ones(3))
    assert np.array_equal(design[0, 1, :], np.zeros(3))


def test_kalman_first_filtered_state_is_the_ratio_at_the_first_observation() -> None:
    """A hand-derivable identity: with an uninformative prior, beta_0 = y_0 / x_0.

    Nothing about the filter is needed to predict this, so it is a genuine check
    on the design matrix and the initialization together rather than a
    restatement of the output.
    """
    dependent, regressor = _kalman_pair()
    result = _kalman_pair_result()
    beta_path = _kalman_paths(result, "filtered_state")["beta"]
    assert beta_path[0] == pytest.approx(float(dependent[0] / regressor[0]), rel=1e-9)


# --- the band --------------------------------------------------------------


def test_kalman_band_bounds_are_the_state_plus_minus_z_times_the_error() -> None:
    """The published bounds must BE the identity, not merely near it."""
    published = _value(_kalman_trend_result())
    z = published["band_z"]
    state = _kalman_paths(_kalman_trend_result(), "filtered_state")
    error = _kalman_paths(_kalman_trend_result(), "filtered_state_std_error")
    lower = _kalman_paths(_kalman_trend_result(), "band_lower")
    upper = _kalman_paths(_kalman_trend_result(), "band_upper")
    for name in ("level", "slope"):
        for index in (0, 5, 99, _KALMAN_N - 1):
            expected_lower = state[name][index] - z * error[name][index]
            assert lower[name][index] == pytest.approx(expected_lower, rel=1e-12)
            assert upper[name][index] == pytest.approx(
                state[name][index] + z * error[name][index], rel=1e-12
            )


def test_kalman_band_z_is_the_normal_quantile_of_the_configured_coverage() -> None:
    """The multiplier is DERIVED from the coverage, not a recalled 1.96."""
    from scipy.stats import norm

    published = _value(_kalman_level_result())
    coverage = published["band_coverage"]
    assert published["band_z"] == pytest.approx(float(norm.ppf(0.5 + coverage / 2.0)), rel=1e-12)
    assert coverage == get_settings().econometrics.kalman_band_coverage.value


def test_kalman_band_coverage_is_read_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move the coverage and require the published multiplier AND band to follow.

    A test asserting ``band_z == 1.96`` passes whether the multiplier is derived
    from the coverage or hardcoded, so the setting is moved to a value no literal
    can produce (0.80 -> z = 1.281552).
    """
    settings = get_settings()
    monkeypatch.setattr(settings.econometrics.kalman_band_coverage, "value", 0.80, raising=False)
    published = _value(_kalman_level_result())
    assert published["band_coverage"] == 0.80
    assert published["band_z"] == pytest.approx(1.2815515655446004, rel=1e-12)
    error = _kalman_paths(_kalman_level_result(), "filtered_state_std_error")["level"]
    lower = _kalman_paths(_kalman_level_result(), "band_lower")["level"]
    state = _kalman_paths(_kalman_level_result(), "filtered_state")["level"]
    assert lower[-1] == pytest.approx(state[-1] - published["band_z"] * error[-1])


def test_kalman_every_state_carries_a_positive_band() -> None:
    """The specification forbids presenting the state as observed truth."""
    for result in (_kalman_level_result(), _kalman_trend_result(), _kalman_pair_result()):
        for name, path in _kalman_paths(result, "filtered_state_std_error").items():
            assert min(path) > 0.0, f"{name} has a non-positive standard error"


# --- the initialization, and why exact-diffuse was rejected ----------------


def test_kalman_initialization_is_approximate_diffuse() -> None:
    published = _value(_kalman_level_result())
    assert published["initialization"] == "approximate_diffuse"
    assert published["diffuse_scale"] == pytest.approx(1.0e6)


def test_kalman_an_unidentified_state_carries_the_prior_scale() -> None:
    """The trend's slope at t=0 has NO information, so its band IS the prior.

    Hand-derived: the observation design is ``[1, 0]``, so the first update
    leaves the slope's covariance at its prior value ``kappa``. Its standard
    error is therefore ``sqrt(kappa) * state_scale``, and this is the assertion
    that the published band reflects the prior instead of collapsing to zero.
    """
    result = _kalman_trend_result()
    published = _value(result)
    slope_error = _kalman_paths(result, "filtered_state_std_error")["slope"][0]
    expected = float(np.sqrt(published["diffuse_scale"])) * published["state_scales"]["slope"]
    assert slope_error == pytest.approx(expected, rel=1e-6)
    assert slope_error > 1.0


def test_kalman_an_identified_state_carries_the_observation_noise() -> None:
    """The LEVEL at t=0 IS identified, so its band is sqrt(sigma2.irregular).

    The complement of the test above, and the reason the two are separate: the
    initialization's effect is STATE-DEPENDENT, so a single assertion cannot
    distinguish "the prior is handled correctly" from "every band is inflated".
    """
    result = _kalman_trend_result()
    published = _value(result)
    level_error = _kalman_paths(result, "filtered_state_std_error")["level"][0]
    # The published `sigma2.irregular` is ALREADY in the caller's units -- the
    # normalisation is undone before publication -- so the identity needs no
    # further rescaling. Multiplying by the state's scale again is the error
    # this comment exists to prevent: it failed by a factor of the series'
    # standard deviation when first written.
    expected = float(np.sqrt(published["estimated_variances"]["sigma2.irregular"]))
    assert level_error == pytest.approx(expected, rel=1e-5)


def test_kalman_the_exact_diffuse_route_reports_a_zero_band() -> None:
    """The measurement that decided the initialization, reproduced as a test.

    ``initialize_diffuse`` REMOVES the diffuse component from
    ``filtered_state_cov``, so the slope — which the first observation does not
    identify — reports a standard error of exactly ``0.0`` while the filtered
    STATES are unchanged. That is a zero-width band on an unobservable state,
    which is the precise opposite of Section 15.20-F's requirement. If a future
    statsmodels release changes this, the test fails and the decision is
    revisited rather than silently invalidated.
    """
    spec = _econ._KALMAN_SPECS[(1, 2)]
    series = _kalman_trend_series()
    panel = series.reshape(-1, 1)
    design = _econ._kalman_design(spec, panel)

    approximate = _econ._KalmanStateModel(series, spec=spec, design=design, diffuse_scale=1.0e6)
    exact = _econ._KalmanStateModel(series, spec=spec, design=design, diffuse_scale=1.0e6)
    exact.ssm.initialize_diffuse()

    approximate_fit = approximate.fit(disp=False, maxiter=200)
    exact_fit = exact.fit(disp=False, maxiter=200)

    index = np.arange(2)
    approximate_error = np.sqrt(np.asarray(approximate_fit.filtered_state_cov)[index, index, :])
    exact_error = np.sqrt(np.asarray(exact_fit.filtered_state_cov)[index, index, :])

    # The slope is unidentified at t = 0: the honest band is the prior's scale,
    # the exact-diffuse band is zero.
    assert approximate_error[1, 0] > 1.0
    assert exact_error[1, 0] == pytest.approx(0.0, abs=1e-12)


# --- the normalisation ------------------------------------------------------


def test_kalman_the_fit_is_scale_invariant() -> None:
    """The same series in different UNITS must give the same answer.

    Before the series was normalised this test's subject failed badly: measured
    2026-09-23, ``sigma2.level / scale**2`` was 0.3238 at scale 1e-3 and 46.16
    at 1e3 — a **147x** spread on identical data, because ``start_params`` is
    1.0 while the likelihood is evaluated at the series' own magnitude.

    The tolerance is 1e-6 rather than exact because the normalised problem is
    the SAME up to the optimizer's stopping rule, not bit-for-bit: measured
    across these five scales the worst disagreement is 1.8e-7 relative, which is
    nine orders of magnitude tighter than the defect it replaces.
    """
    series = _kalman_level_series()
    base = _value(_kalman_level_result())["estimated_variances"]
    for scale in (1e-6, 1e-3, 1e3, 1e6, 1e9):
        moved = _value(_kalman(pd.DataFrame({"s": series * scale})))["estimated_variances"]
        assert moved["sigma2.level"] / scale**2 == pytest.approx(base["sigma2.level"], rel=1e-6), (
            f"sigma2.level is not scale-invariant at scale {scale}"
        )
        assert moved["sigma2.irregular"] / scale**2 == pytest.approx(
            base["sigma2.irregular"], rel=1e-6
        )


def test_kalman_the_series_and_state_scales_are_published() -> None:
    """The normalisation is the only unit-dependent step, so it must be visible."""
    result = _kalman_pair_result()
    published = _value(result)
    dependent, regressor = _kalman_pair()
    assert published["series_scales"]["y_leg"] == pytest.approx(float(np.std(dependent)), rel=1e-12)
    assert published["series_scales"]["x_leg"] == pytest.approx(float(np.std(regressor)), rel=1e-12)
    # A coefficient carries dependent-per-regressor units, so its factor is the
    # RATIO of the two series' scales -- not either one alone.
    assert published["state_scales"]["beta"] == pytest.approx(
        float(np.std(dependent)) / float(np.std(regressor)), rel=1e-12
    )


def test_kalman_a_level_and_a_slope_share_the_dependent_series_scale() -> None:
    """Both carry the dependent series' units; a slope is a level per observation."""
    published = _value(_kalman_trend_result())
    assert published["state_scales"]["level"] == pytest.approx(
        published["state_scales"]["slope"], rel=1e-12
    )


# --- the warning branches ---------------------------------------------------


def test_kalman_a_non_converged_fit_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive the optimizer to a stop, and require BOTH the flag and the warning.

    The construction is a config perturbation rather than a pathological series,
    for a measured reason: with the derivative-free optimizer the constant
    series that used to fail now CONVERGES, so a data-driven fixture would be a
    claim about scipy's simplex rather than about this function. Starving the
    iteration budget is deterministic and also proves the leaf is read.

    The variance assertion is the point of the warning: at ``maxiter=1`` the fit
    reports ``sigma2.level = 6.13`` against the converged ``0.3139``, so a
    non-converged fit is not a slightly-off answer.
    """
    settings = get_settings()
    monkeypatch.setattr(settings.econometrics.kalman_max_iterations, "value", 1, raising=False)
    result = _kalman_level_result()
    assert _value(result)["converged"] is False
    assert "DID NOT CONVERGE" in " ".join(result.warnings)
    assert _value(result)["estimated_variances"]["sigma2.level"] > 1.0


def test_kalman_a_collapsed_state_warns_it_is_not_time_varying() -> None:
    """A constant coefficient: 'time-varying' describes the spec, not the estimate."""
    rng = np.random.default_rng(5)
    x = np.cumsum(rng.normal(0.0, 0.5, _KALMAN_N)) + 50.0
    y = 0.5 * x + rng.normal(0.0, 1.0, _KALMAN_N)
    result = _kalman(pd.DataFrame({"y_leg": y, "x_leg": x}))
    joined = " ".join(result.warnings)
    assert "IS NOT TIME-VARYING" in joined
    assert _value(result)["estimated_variances"]["sigma2.beta"] == pytest.approx(0.0, abs=1e-6)


def test_kalman_a_materially_revised_state_warns() -> None:
    """A trend's slope is the state whose real-time estimate moves most."""
    result = _kalman_trend_result()
    joined = " ".join(result.warnings)
    assert "MATERIALLY REVISED" in joined
    revision = _value(result)["revision_in_band_units"]
    assert revision["slope"] > get_settings().econometrics.kalman_max_revision_ratio.value


def test_kalman_a_well_specified_fit_emits_no_warning() -> None:
    """The NEGATIVE CONTROL: without it, a branch could pass by always firing."""
    assert _kalman_level_result().warnings == []
    assert _kalman_pair_result().warnings == []


def test_kalman_the_drift_ratio_is_read_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move the ratio to a value no healthy fit can clear, and require the warning.

    The discriminating half: at the shipped 1.0 a healthy level does NOT warn
    (asserted above), so a function comparing against a literal would fail here
    rather than pass everywhere.
    """
    settings = get_settings()
    monkeypatch.setattr(
        settings.econometrics.kalman_min_state_drift_ratio, "value", 1.0e9, raising=False
    )
    result = _kalman_level_result()
    assert "IS NOT TIME-VARYING" in " ".join(result.warnings)


def test_kalman_the_revision_ratio_is_read_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        settings.econometrics.kalman_max_revision_ratio, "value", 0.0, raising=False
    )
    result = _kalman_level_result()
    assert "MATERIALLY REVISED" in " ".join(result.warnings)


def test_kalman_the_not_time_varying_test_is_scale_invariant() -> None:
    """The DIVERGENT CASE for a relative guard, per D-100's rule.

    A tolerance expressed as ``drift / median_error`` can only be shown to be
    relative by a case where a relative and an absolute rule DISAGREE. Scaling
    the series moves ``drift`` and ``median_error`` together, so the relative
    ratio is unchanged and the verdict must be unchanged too — while an absolute
    ``drift <= constant`` rule would flip, because ``drift`` scales with the
    series. Both directions are exercised: a tiny scale (where an absolute rule
    would fire) and a huge one (where it would not).
    """
    rng = np.random.default_rng(5)
    x = np.cumsum(rng.normal(0.0, 0.5, _KALMAN_N)) + 50.0
    y = 0.5 * x + rng.normal(0.0, 1.0, _KALMAN_N)

    verdicts = []
    for scale in (1e-6, 1.0, 1e6):
        result = _kalman(pd.DataFrame({"y_leg": y * scale, "x_leg": x * scale}))
        verdicts.append("IS NOT TIME-VARYING" in " ".join(result.warnings))

    assert verdicts == [True, True, True], (
        f"the collapsed-state verdict changed with the series' units: {verdicts}"
    )


def test_every_kalman_warning_branch_is_triggered_by_some_test() -> None:
    """A branch with no test is deletable, so the branches are enumerated here.

    A PARTITION rather than a hit: each marker is distinct, and each is asserted
    to be reached. Adding a fourth branch without a test fails this.

    The convergence branch is driven through the builder directly rather than
    through a fit, and that is deliberate: with the derivative-free optimizer the
    constant series that used to fail now converges, so no data fixture reliably
    produces it. Passing ``converged=False`` is the branch's actual precondition,
    which is what a partition guard should assert.
    """
    markers = {
        "converged": "DID NOT CONVERGE",
        "not_time_varying": "IS NOT TIME-VARYING",
        "materially_revised": "MATERIALLY REVISED",
    }
    triggered: set[str] = set()

    synthetic = _econ._kalman_warnings(
        spec=_econ._KALMAN_SPECS[(1, 1)],
        filtered=np.array([[1.0, 2.0]]),
        standard_error=np.array([[0.1, 0.1]]),
        smoothed=np.array([[1.0, 2.0]]),
        variances={"sigma2.level": 0.01, "sigma2.irregular": 1.0},
        n_obs=2,
        converged=False,
        convergence_messages=[],
    )

    rng = np.random.default_rng(5)
    x = np.cumsum(rng.normal(0.0, 0.5, _KALMAN_N)) + 50.0
    collapsed = _kalman(
        pd.DataFrame({"y_leg": 0.5 * x + rng.normal(0.0, 1.0, _KALMAN_N), "x_leg": x})
    )

    for emitted in (synthetic, collapsed.warnings, _kalman_trend_result().warnings):
        for warning in emitted:
            for label, marker in markers.items():
                if marker in warning:
                    triggered.add(label)

    assert triggered == set(markers), f"untested warning branches: {set(markers) - triggered}"


# --- refusals ---------------------------------------------------------------


def test_kalman_refuses_a_non_dataframe() -> None:
    with pytest.raises(TypeError, match="must be a pandas DataFrame"):
        _kalman([1.0, 2.0, 3.0])  # type: ignore[arg-type]


@pytest.mark.parametrize("state_dim", [1.5, "1", None])
def test_kalman_refuses_a_non_integer_state_dimension(state_dim: Any) -> None:
    with pytest.raises(TypeError, match="state_dim must be an int"):
        _kalman(pd.DataFrame({"s": _kalman_level_series()}), state_dim=state_dim)


def test_kalman_refuses_a_boolean_state_dimension() -> None:
    """``bool`` is an ``int`` subclass, so it would reach the table as 0 or 1."""
    with pytest.raises(TypeError, match="state_dim must be an int"):
        _kalman(pd.DataFrame({"s": _kalman_level_series()}), state_dim=True)


def test_kalman_refuses_a_columnless_frame() -> None:
    with pytest.raises(ValueError, match="at least one column"):
        _kalman(pd.DataFrame(index=range(100)))


def test_kalman_refuses_a_wide_panel_and_names_the_sibling_function() -> None:
    """A panel of tenors is a factor decomposition, which is `compute_pca`'s job."""
    frame = pd.DataFrame(
        {"a": _kalman_level_series(), "b": _kalman_level_series(), "c": _kalman_level_series()}
    )
    with pytest.raises(ValueError, match="compute_pca"):
        _kalman(frame)


@pytest.mark.parametrize(("columns", "state_dim"), [(1, 3), (2, 2), (1, 0), (2, 3)])
def test_kalman_refuses_an_unspecified_combination(columns: int, state_dim: int) -> None:
    """The refusal enumerates the admissible set rather than restating it."""
    series = _kalman_level_series()
    frame = pd.DataFrame({f"c{index}": series for index in range(columns)})
    with pytest.raises(ValueError, match="admissible combinations are"):
        _kalman(frame, state_dim=state_dim)


def test_kalman_refuses_duplicate_column_names() -> None:
    series = _kalman_level_series()
    frame = pd.DataFrame(np.column_stack([series, series]), columns=["s", "s"])
    with pytest.raises(ValueError, match="duplicate column name"):
        _kalman(frame)


@pytest.mark.parametrize("column", [list("abcdefghij" * 20), [True] * _KALMAN_N])
def test_kalman_refuses_a_non_numeric_column(column: list[Any]) -> None:
    with pytest.raises(ValueError, match="must be numeric"):
        _kalman(pd.DataFrame({"s": column}))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_kalman_refuses_a_non_finite_value(bad: float) -> None:
    series = _kalman_level_series()
    series[5] = bad
    with pytest.raises(ValueError, match="non-finite values"):
        _kalman(pd.DataFrame({"s": series}))


def test_kalman_refuses_a_sample_below_the_configured_floor() -> None:
    floor = get_settings().econometrics.kalman_min_observations.value
    with pytest.raises(ValueError, match="below the configured floor"):
        _kalman(pd.DataFrame({"s": _kalman_level_series()[: int(floor) - 1]}))


# --- the ModelResult contract ----------------------------------------------


def test_kalman_model_name_is_stable() -> None:
    assert _kalman_level_result().model_name == "kalman_latent_state"


def test_kalman_confidence_comes_from_the_shared_rule() -> None:
    """The computed value is pinned against ``compute_confidence``, not a literal."""
    result = _kalman_level_result()
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
            depends_on_unobservable=True,
        )
    )
    assert result.confidence == expected


def test_kalman_confidence_prices_the_unobservable_dependence() -> None:
    """The flag is not decoration: the field exists for exactly this quantity.

    Asserted by its DISCRIMINATING property — the result is strictly lower than
    the same computation without the flag — because the computed value could
    otherwise coincide with a literal.
    """
    result = _kalman_level_result()
    without = compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True))
    assert result.confidence < without


def test_kalman_the_heuristic_penalty_follows_the_thresholds_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calibrate the two judgement thresholds and require the confidence to rise."""
    settings = get_settings()
    before = _kalman_level_result().confidence
    for leaf in ("kalman_min_state_drift_ratio", "kalman_max_revision_ratio"):
        monkeypatch.setattr(
            getattr(settings.econometrics, leaf),
            "calibration_status",
            "conventional",
            raising=False,
        )
    assert _kalman_level_result().confidence > before


def test_kalman_names_its_inputs_by_role_for_a_pair() -> None:
    """The column ORDER is a convention, so it is published rather than assumed."""
    result = _kalman_pair_result()
    assert result.inputs_used == ["dependent:y_leg", "regressor:x_leg"]


def test_kalman_names_its_input_by_role_for_a_single_series() -> None:
    assert _kalman_level_result().inputs_used == ["observed:level_series"]


def test_kalman_direction_is_none_because_a_level_is_not_a_signal() -> None:
    assert _kalman_level_result().direction is None


def test_kalman_unit_names_the_state_units() -> None:
    """`unit` is optional on `ModelResult`, so its PRESENCE is part of the check.

    A state without a declared unit is a number whose meaning a reader must
    guess: the level, the slope and the beta each carry a different one.
    """
    unit = _kalman_level_result().unit
    assert unit is not None
    assert "state units" in unit
    assert "per observation" in unit


def test_kalman_discloses_that_the_state_is_unobservable() -> None:
    joined = " ".join(_kalman_level_result().limitations)
    assert "UNOBSERVABLE" in joined


def test_kalman_discloses_the_collapsed_band_with_its_measurement() -> None:
    """The warning that was removed must still reach the reader as a limitation."""
    joined = " ".join(_kalman_level_result().limitations)
    assert "COLLAPSES" in joined
    assert "no threshold separates" in joined


def test_kalman_discloses_the_normalisation() -> None:
    joined = " ".join(_kalman_level_result().limitations)
    assert "SCALE-SENSITIVE" in joined
    assert "147x" in joined


def test_kalman_discloses_the_prior_dominated_head() -> None:
    joined = " ".join(_kalman_level_result().limitations)
    assert "DOMINATED BY THE PRIOR" in joined


def test_kalman_forbids_presenting_the_state_as_observed_truth() -> None:
    joined = " ".join(_kalman_level_result().decision_prohibition)
    assert "observed truth" in joined


def test_kalman_forbids_the_smoothed_state_in_real_time() -> None:
    joined = " ".join(_kalman_level_result().decision_prohibition)
    assert "SMOOTHED state" in joined
    assert "look-ahead" in joined


def test_kalman_publishes_the_smoothed_path_for_the_revision() -> None:
    """The look-ahead disclosure needs both sides, so the smoothed value travels."""
    published = _value(_kalman_trend_result())
    smoothed = published["smoothed_latest"]
    assert isinstance(smoothed, dict)
    assert set(smoothed) == {"level", "slope"}
    assert all(np.isfinite(value) for value in smoothed.values())


def test_kalman_assumes_a_level_not_a_change_for_a_single_series() -> None:
    joined = " ".join(_kalman_level_result().assumptions)
    assert "LEVEL, not a change" in joined


def test_kalman_states_the_pair_column_order_convention() -> None:
    joined = " ".join(_kalman_pair_result().assumptions)
    assert "DEPENDENT" in joined and "REGRESSOR" in joined


def test_kalman_publishes_no_non_finite_value() -> None:
    """A `nan` renders as a gap, so it is refused rather than published."""
    for result in (_kalman_level_result(), _kalman_trend_result(), _kalman_pair_result()):
        for key in (
            "filtered_state",
            "filtered_state_std_error",
            "band_lower",
            "band_upper",
        ):
            for name, path in _kalman_paths(result, key).items():
                assert all(np.isfinite(value) for value in path), f"{key}[{name}]"


def test_kalman_interpretation_names_the_specification_and_the_band() -> None:
    result = _kalman_level_result()
    assert "local_level" in result.interpretation
    assert "band of" in result.interpretation
    assert "%" in result.interpretation


def test_kalman_context_names_the_specification_and_convergence() -> None:
    context = _kalman_level_result().context
    assert "Specification 'local_level'" in context
    assert "converged = True" in context
    assert "approximate_diffuse" in context


# --- the config, and its cross-checks --------------------------------------


def test_the_kalman_parameter_constant_matches_the_specification_table() -> None:
    """``config._KALMAN_MAX_PARAMETERS`` is a COPY, so it is pinned to its source.

    ``config`` may not import ``models`` — the dependency runs the other way — so
    the constant is duplicated there. A duplicated constant with no pin is one
    that rots silently (the D-047 class), so this recounts it from the model's
    own table and fails if the two disagree.
    """
    from macro_engine.config import _KALMAN_MAX_PARAMETERS

    largest = max(
        len(spec.variance_names) + 1  # + sigma2.irregular
        for spec in _econ._KALMAN_SPECS.values()
    )
    assert largest == _KALMAN_MAX_PARAMETERS


def test_the_kalman_observation_floor_exceeds_the_parameter_count() -> None:
    """A likelihood with fewer rows than estimated variances is not identified."""
    import pydantic

    from macro_engine.config import _KALMAN_MAX_PARAMETERS

    settings = get_settings().econometrics
    assert float(settings.kalman_min_observations.value) > _KALMAN_MAX_PARAMETERS
    with pytest.raises((ValueError, pydantic.ValidationError), match="must exceed"):
        type(settings).model_validate(
            {
                **{name: getattr(settings, name) for name in type(settings).model_fields},
                "kalman_min_observations": settings.kalman_min_observations.model_copy(
                    update={"value": 3}
                ),
            }
        )


def test_the_kalman_band_coverage_must_be_an_open_interval() -> None:
    """At 1.0 the normal quantile is infinite, so the band would be `inf`."""
    import pydantic

    settings = get_settings().econometrics
    assert 0.0 < float(settings.kalman_band_coverage.value) < 1.0
    with pytest.raises((ValueError, pydantic.ValidationError), match="strictly inside"):
        type(settings).model_validate(
            {
                **{name: getattr(settings, name) for name in type(settings).model_fields},
                "kalman_band_coverage": settings.kalman_band_coverage.model_copy(
                    update={"value": 1.0}
                ),
            }
        )


def test_the_kalman_optimizer_is_in_the_permitted_set() -> None:
    settings = get_settings().econometrics
    assert settings.kalman_optimizer in {"nm", "powell", "lbfgs", "bfgs"}


def test_the_kalman_optimizer_is_refused_when_unrecognised() -> None:
    """An unrecognised method would reach scipy, naming neither the setting nor the file."""
    import pydantic

    settings = get_settings().econometrics
    with pytest.raises((ValueError, pydantic.ValidationError), match="must be one of"):
        type(settings).model_validate(
            {
                **{name: getattr(settings, name) for name in type(settings).model_fields},
                "kalman_optimizer": "gradient-descent",
            }
        )


def test_the_kalman_optimizer_is_read_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move the optimizer to a gradient method and require the fit to change.

    The measurement behind the default: gradient methods sit at the optimum
    without satisfying their own stopping rule on this flat likelihood, so the
    published variances move slightly. A hardcoded ``"nm"`` would not follow.
    """
    settings = get_settings()
    before = _value(_kalman_level_result())["estimated_variances"]["sigma2.level"]
    monkeypatch.setattr(settings.econometrics, "kalman_optimizer", "lbfgs", raising=False)
    after = _value(_kalman_level_result())["estimated_variances"]["sigma2.level"]
    assert after == pytest.approx(before, rel=1e-3)
    assert after != before


def test_kalman_refuses_a_non_finite_filter_output() -> None:
    """The OUTPUT guard, reached by an overflow rather than by a bad input.

    A series at scale ``1e300`` is a legal float and passes every INPUT check,
    and the filter's own arithmetic then overflows, so the state comes back
    ``inf``. That is the case the guard exists for: a non-finite band renders as
    a gap in a chart and compares ``False`` against everything, so it would look
    like missing data rather than like a failure.

    The boundary is measured rather than assumed: ``1e150`` is finite and returns
    ``sigma2.level = 2.39e299``, while ``1e300`` overflows. The message is matched
    on "produced non-finite" to distinguish this guard from the INPUT check, which
    raises "observations contains non-finite values" when the series itself has
    already overflowed (at ``1e308``).
    """
    series = _kalman_level_series() * 1e300
    assert bool(np.isfinite(series).all()), "the input must be finite for this test"
    with pytest.raises(ValueError, match="produced non-finite values"):
        _kalman(pd.DataFrame({"s": series}))


def test_kalman_refuses_a_series_with_no_variation() -> None:
    """A constant series has no latent state to estimate, so it is REFUSED.

    This was originally left to the ``not time-varying`` WARNING, and a live run
    falsified that rationale (D-101): on a constant series the state variance
    collapses to ``1e-12`` but the BAND collapses further (``1.65e-09``), so the
    warning's drift-to-band ratio came back as **6055** and did not fire. The
    warning compares the state's movement with the uncertainty about it, and both
    collapse together — which is exactly why it cannot see this case.
    """
    with pytest.raises(ValueError, match="no variation"):
        _kalman(pd.DataFrame({"s": np.full(120, 7.0)}))


def test_kalman_refuses_a_constant_regressor() -> None:
    """The refusal covers every column, not only the dependent series.

    A coefficient estimated against a regressor that never moves is identified
    only up to that regressor's scale, so the fit returns a confident number
    describing nothing.
    """
    rng = np.random.default_rng(4)
    dependent = np.cumsum(rng.normal(0.0, 0.5, _KALMAN_N)) + 100.0
    with pytest.raises(ValueError, match="no variation"):
        _kalman(pd.DataFrame({"y_leg": dependent, "x_leg": np.full(_KALMAN_N, 5.0)}))


def test_kalman_the_constant_refusal_is_scale_relative_not_absolute() -> None:
    """The DIVERGENT CASE for the relative tolerance, per D-100's rule.

    A relative tolerance can only be shown to be relative by a case where a
    relative and an absolute rule DISAGREE. Both directions are exercised here:

    * a constant series is refused at **every** magnitude, including ``1e6``,
      where an absolute tolerance would have to be huge to fire; and
    * a series at scale ``1e-9`` that genuinely MOVES by ``1e-6`` of its own
      scale — a standard deviation of ``2.9e-16``, ten orders of magnitude above
      the floating-point noise — is **accepted**. An absolute tolerance of
      ``2.22e-14`` (which is what ``compute_pca``'s ``maximum(scale, 1.0)`` form
      reduces to below scale 1) would refuse it.

    Measured 2026-09-23. The opposite direction does NOT exist for the residue
    itself: numpy's ``std`` returns exactly ``0`` for a constant array at every
    magnitude from ``4.2`` to ``1e12``, so the residue never grows with scale.
    """
    for magnitude in (0.0, 7.0, 1e6):
        with pytest.raises(ValueError, match="no variation"):
            _kalman(pd.DataFrame({"s": np.full(120, magnitude)}))

    # A tiny scale with a variation that is LARGE relative to it but small in
    # absolute terms -- the divergent case, and the magnitudes are MEASURED
    # rather than chosen. The two tolerances are:
    #
    #   relative  eps * scale * 100      = 2.22e-23  for scale 1e-9
    #   absolute  eps * maximum(scale,1) * 100 = 2.22e-14  (the sibling's form)
    #
    # so the standard deviation must lie BETWEEN them. `linspace(0, 1e-9)` does
    # NOT: its standard deviation is 2.9e-10, far above both, which is why the
    # first version of this test let M108 SURVIVE. A base of 1e-9 with a 1e-15
    # ramp gives 2.9e-16 -- ten orders of magnitude above the floating-point
    # noise, and inside the gap.
    varying = np.full(_KALMAN_N, 1e-9) + np.linspace(0.0, 1e-15, _KALMAN_N)
    deviation = float(np.std(varying, ddof=1))
    relative_tolerance = float(np.finfo(float).eps * np.abs(varying).max() * 100.0)
    absolute_tolerance = float(np.finfo(float).eps * 1.0 * 100.0)
    assert relative_tolerance < deviation <= absolute_tolerance, (
        f"the divergent case needs relative_tol < std <= absolute_tol, got "
        f"{relative_tolerance!r} < {deviation!r} <= {absolute_tolerance!r}"
    )
    result = _kalman(pd.DataFrame({"s": varying}))
    assert _value(result)["n_obs"] == _KALMAN_N


# ---------------------------------------------------------------------------
# Section 3-4 reasoning object, module-wide (D-132)
# ---------------------------------------------------------------------------
#
# Before D-132, `data_provenance` and `decision_relevance` were published by
# NONE of this module's five functions, `unit` was absent from two, and
# `assumptions` from one. Every field on `ModelResult` defaults to an honest
# "not supplied", so a model that omits them does NOT fail validation — the
# omission is invisible to every gate, which is exactly why it survived. This
# test is the mover's structural half: it asserts POPULATED-ness (not prose),
# so a blanking edit fails here.

#: The six Section 3-4 fields every econometrics result must populate. The
#: SEVENTH, `direction`, is deliberately EXCLUDED: each of these five values is
#: a coefficient map, a verdict, a test result, a set of components, or a state
#: path — none has a single direction the output moves in, so `direction`
#: left unset is the honest value and asserting it would be wrong.
_ECONOMETRICS_REASONING_FIELDS = (
    "unit",
    "assumptions",
    "data_provenance",
    "limitations",
    "decision_relevance",
    "decision_prohibition",
)


def _all_five_results() -> list[tuple[str, ModelResult]]:
    """One result per public function, built from the file's own fixtures."""
    return [
        ("run_regression", _golden_result()),
        ("test_stationarity", _stationarity(_white_noise())),
        ("test_cointegration", _cointegration(*_coint_pair())),
        ("compute_pca", _pca_result()),
        ("kalman_latent_state", _kalman_level_result()),
    ]


def test_every_result_populates_the_reasoning_object_d132() -> None:
    """Every one of the five functions publishes all six applicable fields."""
    for name, result in _all_five_results():
        for field in _ECONOMETRICS_REASONING_FIELDS:
            value = getattr(result, field)
            if isinstance(value, str):
                assert value.strip(), f"{name}.{field} is blank (D-132)"
            else:
                assert value, f"{name}.{field} is empty (D-132)"

        # `direction` is the deliberate seventh: it must be None here, because
        # no value in this module has a single direction. Asserted so a future
        # edit that invents one is a conscious choice rather than a default.
        assert result.direction is None, (
            f"{name} set a `direction`; the module's values are maps/verdicts/"
            f"sets/paths that have no single direction (D-132). If a real "
            f"direction now exists, update this assertion and say why."
        )


def test_the_provenance_names_the_supplied_series_d132() -> None:
    """`data_provenance` must say WHERE the inputs came from, not just restate them.

    Section 4 wants the SOURCES, complementing `inputs_used`'s field names. A
    placeholder that echoed the field names would satisfy a only non-empty check,
    so this asserts the caller-supplied disclosure is actually present.
    """
    for name, result in _all_five_results():
        joined = " ".join(result.data_provenance).lower()
        assert "caller" in joined or "supplied" in joined, (
            f"{name}.data_provenance does not disclose that the inputs are "
            f"caller-supplied (D-132); got {result.data_provenance!r}"
        )


def test_the_decision_relevance_names_a_downstream_consumer_d132() -> None:
    """`decision_relevance` must name what the output is FOR (Section 3).

    A value that only restated the model name would pass a non-empty check. This
    asserts the relevance text reaches a real consumer — a Section reference, a
    sibling model, or a named gate.
    """
    for name, result in _all_five_results():
        relevance = result.decision_relevance or ""
        assert len(relevance) > 40, f"{name}.decision_relevance is too thin (D-132)"
        lowered = relevance.lower()
        assert any(
            marker in lowered
            for marker in ("section", "gate", "test_stationarity", "run_regression", "module 13")
        ), f"{name}.decision_relevance names no downstream consumer (D-132)"
