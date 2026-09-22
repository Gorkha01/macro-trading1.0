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

import numpy as np
import pandas as pd
import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.econometrics import RegressionResult, run_regression

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
