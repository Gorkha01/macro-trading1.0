"""Module 18 — Quantitative Tools: OLS with a mandatory mechanism gate.

Section 15.18 gives this module one ordering that governs everything else in
it: **mechanism first, statistics second.** A regression here is not a search
procedure. It is the measurement of a relationship the analyst already had a
reason to expect, and its output is evidence about *that* hypothesis — not a
licence to keep fitting until something clears a threshold. ``run_regression``
therefore makes the hypothesis a **required argument**: a caller that cannot
state what mechanism it is testing cannot call the function at all.

Three further disciplines from Section 15.18 are encoded rather than left to
the caller's memory:

* **A low R-squared is reported as information, not failure.** The dangerous
  reading is the opposite one — a high R-squared over a spurious level
  regression, which *looks* like confirmation. This function cannot test for
  that (``test_stationarity`` does), so it states the gap in ``limitations``
  instead of implying the check has been done.
* **Non-stationary level regression is spurious.** That caveat holds on every
  call, so it is a *limitation*, not a *warning*. A warning that fires every
  time is noise, and noise is how a real warning gets ignored.
* **Multicollinearity is disclosed, never repaired.** Which of two collinear
  regressors to drop is an economic judgement. This function reports the
  variance inflation factors and does not choose.

Deliberately absent: any data fetching. Models consume aligned inputs
(Section 6) and the caller owns provenance; this module never reaches for a
provider, and it raises rather than repairing an input it cannot use.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from pydantic import ConfigDict, Field
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.sm_exceptions import InterpolationWarning, SingularMatrixWarning
from statsmodels.tsa.stattools import adfuller, kpss

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = ["RegressionResult", "run_regression", "test_stationarity"]

#: The name ``statsmodels`` gives the intercept it prepends. Named once here so
#: the VIF loop and the reporting code cannot disagree about which column to
#: exclude — the same "one spelling" discipline the series registry applies to
#: provider routes.
_INTERCEPT_NAME = "const"


class RegressionResult(ModelResult):
    """A ``ModelResult`` narrowed to a fitted OLS regression.

    ``value`` is a ``dict[str, float]`` — the coefficient map, identical to
    ``beta``. It is carried on both because they answer different questions: a
    consumer that reads only the base contract still sees the primary output,
    while a consumer that wants the fit statistics gets them typed rather than
    having to re-derive them from a loose dict.

    ``multicollinearity_vif`` is ``None`` for a single-regressor fit, where the
    statistic is identically 1.0 and therefore carries no information. That is
    a deliberate ``None`` rather than a fabricated ``{}``: Section 3 requires
    an absent justification to be *visible*, and an empty dict reads as "no
    collinearity found" when the truth is "not measured".
    """

    model_config = ConfigDict(extra="forbid")

    beta: dict[str, float] = Field(
        description=(
            "Fitted coefficients, keyed by regressor name, including the "
            "intercept under 'const'. These are ASSOCIATIONS under the fitted "
            "model, not causal effects."
        )
    )
    r_squared: float = Field(
        description=(
            "Share of the variance in y explained by the regressors. Reported "
            "as information in both directions: a LOW value is a humility "
            "signal about the mechanism, and a value at 1.0 is more likely a "
            "specification error than a discovery."
        )
    )
    adj_r_squared: float = Field(
        description=(
            "R-squared penalised for the number of regressors; the honest figure "
            "when comparing fits of different size."
        )
    )
    p_values: dict[str, float] = Field(
        description=(
            "Two-sided p-value per coefficient, keyed as ``beta`` is. A small "
            "p-value is evidence against the null of no association under the "
            "model's assumptions — it is not a measure of economic importance, "
            "and with enough observations a trivial effect is significant."
        )
    )
    n_obs: int = Field(
        description=(
            "Usable rows the fit consumed. Never the number passed in if any were "
            "dropped — nothing is dropped."
        )
    )
    multicollinearity_vif: dict[str, float] | None = Field(
        default=None,
        description=(
            "Variance inflation factor per non-intercept regressor, or None for "
            "a single-regressor fit where the statistic is identically 1.0."
        ),
    )


def run_regression(
    y: pd.Series,
    X: pd.DataFrame,  # noqa: N803 - the name is fixed by AGENTS.md Section 15.18's signature
    require_mechanism: str,
) -> RegressionResult:
    """Fit OLS of ``y`` on ``X``, gated on a stated economic mechanism.

    ``require_mechanism`` is a mandatory free-text field documenting the
    mechanism hypothesised **before** fitting. It is not decoration and it is
    not validated for content — no function can tell a good mechanism from a
    bad one, and pretending otherwise would be worse than useless. What it does
    is put the hypothesis **on the record before the p-value exists**, which is
    the only thing that makes a later data-mined fit visible as such. A caller
    that cannot articulate a mechanism should not be running the regression.

    An intercept is always added. It is reported under ``'const'`` so a caller
    can see it rather than infer it.

    **Raises** rather than repairs, on every input defect: mismatched lengths or
    indexes, non-numeric columns, non-finite values, a constant regressor, too
    few observations, or fewer residual degrees of freedom than parameters.
    Section 3's rule is that a system which cannot say "I don't know" will
    fabricate; silently dropping a row or a column changes ``n_obs`` and
    therefore changes the answer, so this function refuses instead.

    Returns a :class:`RegressionResult` whose ``warnings`` report conditions of
    *this* run and whose ``limitations`` state what the fit cannot tell you
    even when it succeeded.
    """
    mechanism = _validate_mechanism(require_mechanism)
    y_f, x_frame = _prepare_observations(y, X)
    settings = get_settings()

    design = sm.add_constant(x_frame, has_constant="add")
    n_obs = len(y_f)
    n_params = int(design.shape[1])

    # Derived, never configured: residual degrees of freedom must be positive or
    # there is no fit to report. This is arithmetic, so it is computed here
    # rather than hidden behind a tunable that could be set to zero.
    if n_obs <= n_params:
        raise ValueError(
            f"Degenerate fit refused: {n_obs} observations against {n_params} "
            f"parameters (including the intercept) leaves no residual degrees of "
            f"freedom. Supply more rows or fewer regressors; this function will "
            f"not fit a saturated system and report its coefficients as if they "
            f"were estimated."
        )

    design_values = design.to_numpy(dtype=float)

    # Perfect collinearity leaves the coefficients unidentified, so this is a
    # refusal rather than a warning. The detector is `matrix_rank` (SVD-based)
    # and NOT the variance inflation factor, because that is the trap: for a
    # singular design `variance_inflation_factor` returns a very LARGE FINITE
    # number and emits a conditioning warning — it does not return inf. A
    # finiteness test on the VIF therefore passes exactly the case it was
    # written to catch. Measured 2026-09-22: `b == 2*a` produced a finite VIF
    # and no exception until this check was added.
    rank = int(np.linalg.matrix_rank(design_values))
    if rank < n_params:
        raise ValueError(
            f"The design matrix is rank-deficient: {n_params} columns but rank "
            f"{rank}. At least one regressor is an exact linear combination of the "
            f"others, so no unique coefficient vector exists and any values returned "
            f"would be an artefact of the solver. Drop the redundant regressor(s) — "
            f"which one is redundant is an economic judgement this function will not "
            f"make for you."
        )

    fit = sm.OLS(y_f, design).fit()

    beta = {str(name): float(value) for name, value in fit.params.items()}
    p_values = {str(name): float(value) for name, value in fit.pvalues.items()}
    r_squared = float(fit.rsquared)
    adj_r_squared = float(fit.rsquared_adj)

    vif = _variance_inflation_factors(design) if x_frame.shape[1] > 1 else None

    warnings = _collect_warnings(
        r_squared=r_squared,
        vif=vif,
        low_r_squared_threshold=float(settings.econometrics.low_r_squared_threshold.value),
        vif_concern_threshold=float(settings.econometrics.vif_concern_threshold.value),
    )

    residual_dof = n_obs - n_params
    return RegressionResult(
        model_name="run_regression",
        country="us",
        as_of=utc_now(),
        value=beta,
        beta=beta,
        r_squared=r_squared,
        adj_r_squared=adj_r_squared,
        p_values=p_values,
        n_obs=n_obs,
        multicollinearity_vif=vif,
        confidence=compute_confidence(
            ConfidenceInputs(
                # Inputs are observed (both sides are supplied series), so no
                # unobservable is declared. The one penalty this model earns is
                # the heuristic one: the R-squared floor it judges "weak"
                # against is an uncalibrated placeholder, and leaning on a
                # placeholder must cost confidence rather than inherit its
                # apparent precision (Section 22.8).
                is_heuristic_not_calibrated=not _r_squared_floor_is_calibrated(),
                # A single dataset supplies every input: y and each regressor
                # come from the same sample, so there is no independent
                # corroboration to credit (Module 13's family census).
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        ),
        interpretation=(
            f"OLS fit of {y.name if y.name is not None else 'y'} on "
            f"{', '.join(str(c) for c in x_frame.columns)} explains {r_squared:.1%} of "
            f"the variation ({n_obs} observations, {residual_dof} residual degrees "
            f"of freedom). Mechanism under test: {mechanism}"
        ),
        context=(
            f"R-squared {r_squared:.4f}, adjusted {adj_r_squared:.4f}; "
            f"n = {n_obs}, parameters = {n_params} (intercept included), "
            f"residual dof = {residual_dof}. "
            + (
                "Variance inflation factors: "
                + ", ".join(f"{name} {value:.2f}" for name, value in sorted(vif.items()))
                + "."
                if vif
                else "Single regressor, so no variance inflation factor is reported."
            )
        ),
        inputs_used=[
            f"y:{y.name if y.name is not None else 'unnamed'}",
            *(f"X:{name}" for name in x_frame.columns),
        ],
        warnings=warnings,
        assumptions=[f"Mechanism hypothesised before fitting: {mechanism}"],
        limitations=_limitations(),
        decision_prohibition=[
            "Do not read a fitted coefficient as a causal effect. OLS on "
            "observational macro data identifies a conditional association under "
            "this model's assumptions, not an effect.",
            "Do not size a position from a regression whose stationarity has not "
            "been established by test_stationarity. Two independent random walks "
            "regress to a significant coefficient with high probability — the "
            "spurious regression that Section 15.18 names first.",
        ],
    )


def test_stationarity(series: pd.Series) -> ModelResult:
    """Test a series for a unit root, running ADF **and** KPSS.

    ``value`` is a ``dict``: ``verdict`` (see below), both tests' statistics and
    p-values, and the two rejection booleans they were derived from.

    **Why both tests, and why neither is allowed to break the tie.** ADF's null
    is *a unit root*; KPSS's null is *stationarity*. The nulls are **inverted**,
    so the two tests are not two opinions about one hypothesis — they are
    independent pieces of evidence, and a series is only confidently classified
    when they **agree**. Section 15.18 states the discipline directly:
    disagreement is itself informative (inconclusive), *"not something to resolve
    by picking the convenient one"*. So the four outcomes are:

    ``"stationary"``
        ADF rejects the unit root and KPSS does not reject stationarity. Both
        agree.
    ``"non_stationary"``
        ADF fails to reject and KPSS rejects. Both agree on a unit root.
    ``"inconclusive_conflict"``
        **Both reject.** The tests contradict each other — the usual causes are
        fractional integration or a structural break, either of which satisfies
        one null and violates the other.
    ``"inconclusive_low_power"``
        **Neither rejects.** Not a contradiction: there is simply not enough
        information to distinguish, and ADF's well-known low power against a
        near-unit-root alternative is the common reason.

    **KPSS's p-value is CLIPPED, and that is disclosed rather than hidden.**
    statsmodels reads it from a look-up table covering ``[0.01, 0.10]``, so a
    statistic outside that range returns the nearest boundary and emits an
    ``InterpolationWarning``. A returned ``0.01`` means *"at most 0.01"* and
    ``0.10`` means *"at least 0.10"* — **bounds, not point estimates**. The
    clipping does not change the reject/not-reject decision at the conventional
    sizes, but it does mean the number must not be reported as an exact p-value,
    so the result says so whenever it happens.

    **Raises** rather than repairs, on every input defect, exactly as
    :func:`run_regression` does: a non-numeric or non-finite series, one shorter
    than ``econometrics.stationarity_min_observations``, or one that is constant.
    """
    y, name = _prepare_series(series)
    settings = get_settings()
    econometrics = settings.econometrics

    alpha = float(econometrics.significance_level.value)
    regression = str(econometrics.adf_regression)

    adf_statistic, adf_p_value, adf_used_lag, adf_nobs, adf_ill_conditioned = _run_adf(
        y,
        regression=regression,
        autolag=str(econometrics.adf_autolag),
    )
    kpss_statistic, kpss_p_value, kpss_lags, kpss_clipped = _run_kpss(
        y,
        regression=regression,
        nlags=str(econometrics.kpss_nlags),
    )

    # THE INVERTED NULLS. ADF rejecting is evidence FOR stationarity; KPSS
    # rejecting is evidence AGAINST it. Writing these as two named booleans
    # rather than inlining the comparisons is what keeps the inversion legible —
    # a single transposed `<` here would silently invert every verdict the
    # function ever produces, and the two tests would still appear to work.
    adf_rejects_unit_root = adf_p_value < alpha
    kpss_rejects_stationarity = kpss_p_value < alpha

    if adf_rejects_unit_root and not kpss_rejects_stationarity:
        verdict = "stationary"
    elif not adf_rejects_unit_root and kpss_rejects_stationarity:
        verdict = "non_stationary"
    elif adf_rejects_unit_root and kpss_rejects_stationarity:
        verdict = "inconclusive_conflict"
    else:
        verdict = "inconclusive_low_power"

    warnings = _stationarity_warnings(
        verdict=verdict,
        alpha=alpha,
        adf_p_value=adf_p_value,
        kpss_p_value=kpss_p_value,
        kpss_clipped=kpss_clipped,
        adf_ill_conditioned=adf_ill_conditioned,
    )

    return ModelResult(
        model_name="test_stationarity",
        country="us",
        as_of=utc_now(),
        value={
            "verdict": verdict,
            "adf_statistic": round(adf_statistic, 6),
            "adf_p_value": round(adf_p_value, 6),
            "adf_used_lag": adf_used_lag,
            "adf_rejects_unit_root": adf_rejects_unit_root,
            "adf_design_was_ill_conditioned": adf_ill_conditioned,
            "kpss_statistic": round(kpss_statistic, 6),
            "kpss_p_value": round(kpss_p_value, 6),
            "kpss_lags": kpss_lags,
            "kpss_rejects_stationarity": kpss_rejects_stationarity,
            "kpss_p_value_is_clipped": kpss_clipped,
            "significance_level": alpha,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not _r_squared_floor_is_calibrated(),
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        ),
        interpretation=_stationarity_interpretation(verdict, name, alpha),
        context=(
            f"ADF ({regression}) statistic {adf_statistic:+.4f}, p = {adf_p_value:.4f} "
            f"({adf_used_lag} lag(s), {adf_nobs} obs) — H0 is a unit root. "
            f"KPSS ({regression}) statistic {kpss_statistic:+.4f}, "
            f"p = {kpss_p_value:.4f}"
            + (" (CLIPPED — a bound, not a point estimate)" if kpss_clipped else "")
            + f" ({kpss_lags} lag(s)) — H0 is stationarity. "
            f"Both judged at alpha = {alpha}. "
            f"Deterministic terms: '{regression}' "
            f"({'constant only' if regression == 'c' else 'constant and linear trend'})."
        ),
        inputs_used=[f"series:{name}"],
        warnings=warnings,
        limitations=_stationarity_limitations(),
        decision_prohibition=[
            "Do not treat a `stationary` verdict as a property of the economic "
            "relationship. This tests ONE series over ONE window; a unit root is "
            "a statement about the sample, and a series that is stationary inside "
            "this window may not be outside it.",
            "Do not resolve an `inconclusive_*` verdict by preferring whichever "
            "test suits the conclusion. Section 15.18 requires disagreement to be "
            "reported, and the two nulls are inverted so that one test's "
            "rejection is the other's non-rejection.",
            "Do not difference a series on the strength of `non_stationary` alone. "
            "Differencing discards the level information that cointegration "
            "depends on — the same discipline `test_cointegration` will rely on.",
        ],
    )


def _run_adf(
    y: pd.Series,
    *,
    regression: str,
    autolag: str,
) -> tuple[float, float, int, int, bool]:
    """Run ADF and return ``(statistic, p_value, used_lag, nobs, ill_conditioned)``.

    ``nobs`` is the number of observations the test actually used, which is
    **not** ``len(y)`` — the augmented lags consume rows, and reporting the
    input length as though it were the sample would overstate the evidence.

    ``ill_conditioned`` records whether statsmodels raised
    ``SingularMatrixWarning`` while selecting the lag, i.e. its **internal**
    lag-augmented regression was rank-deficient. The test still returns a
    statistic, and that is exactly why it must be disclosed: the number came from
    a degenerate regression, and a consumer who cannot see that would read it as
    an ordinary result. Measured 2026-09-22: a deterministic sine triggers it
    (the lagged differences are collinear with the deterministic pattern).

    ``result_object=True`` for the same reason ``_run_kpss`` passes it:
    statsmodels has announced the plain tuple's length changes in 0.16 (or after
    July 2027), so ``result[1]`` would keep working today and break on an upgrade
    with no test failing. **Note the field rename that goes with the switch:**
    the tuple's third element is ``usedlag``, but the result object calls the
    same quantity ``lags``. A mechanical ``result[2] -> result.usedlag``
    translation raises ``AttributeError``; it was caught by probing the object
    rather than by assuming the mapping.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = adfuller(y, regression=regression, autolag=autolag, result_object=True)

    ill_conditioned = any(issubclass(entry.category, SingularMatrixWarning) for entry in caught)
    return (
        float(result.statistic),
        float(result.pvalue),
        int(result.lags),
        int(result.nobs),
        ill_conditioned,
    )


def _run_kpss(
    y: pd.Series,
    *,
    regression: str,
    nlags: str,
) -> tuple[float, float, int, bool]:
    """Run KPSS and return ``(statistic, p_value, lags, p_value_is_clipped)``.

    ``result_object=True`` is passed **deliberately**. statsmodels has announced
    that the plain tuple's length and layout change in 0.16 (or after July 2027),
    and that the current tuple *silently drops* ``lags`` when ``store=True`` —
    so indexing ``result[1]`` would keep working today and break on an upgrade
    with no test failing. The result object is the explicitly stable surface.

    The ``InterpolationWarning`` is **captured rather than suppressed**: it is
    the only authoritative signal that the p-value is a table-boundary value
    rather than a computed one, and comparing the p-value against 0.01/0.10
    instead would be guessing at the table's range.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = kpss(y, regression=regression, nlags=nlags, result_object=True)

    clipped = any(issubclass(entry.category, InterpolationWarning) for entry in caught)
    return float(result.statistic), float(result.pvalue), int(result.lags), clipped


def _stationarity_warnings(
    *,
    verdict: str,
    alpha: float,
    adf_p_value: float,
    kpss_p_value: float,
    kpss_clipped: bool,
    adf_ill_conditioned: bool,
) -> list[str]:
    """The conditions of *this* run that a consumer must know about."""
    found: list[str] = []

    if adf_ill_conditioned:
        found.append(
            "ADF'S INTERNAL REGRESSION WAS RANK-DEFICIENT during lag selection "
            "(statsmodels raised SingularMatrixWarning). The statistic and p-value "
            "were still produced, from a degenerate design — they are reported "
            "rather than withheld, but they are not an ordinary result and should "
            "not be relied on without inspecting the series' deterministic structure."
        )

    if kpss_clipped:
        found.append(
            f"KPSS p-VALUE IS A BOUND, NOT A POINT ESTIMATE: it is {kpss_p_value:.4f}, "
            f"which is the edge of the look-up table's range [0.01, 0.10]. The true "
            f"p-value is "
            f"{'at least 0.10' if kpss_p_value >= 0.10 else 'at most 0.01'}. "
            f"The reject/not-reject decision at alpha = {alpha} is unaffected, but "
            f"the number must not be quoted as an exact p-value."
        )

    if verdict == "inconclusive_conflict":
        found.append(
            f"THE TWO TESTS CONTRADICT EACH OTHER (ADF p = {adf_p_value:.4f} rejects a "
            f"unit root; KPSS p = {kpss_p_value:.4f} rejects stationarity, both at "
            f"alpha = {alpha}). This is a real finding, not a tie to be broken: it is "
            f"the signature of fractional integration or a structural break, either of "
            f"which can satisfy one null while violating the other. Section 15.18 "
            f"requires it be reported as inconclusive."
        )

    if verdict == "inconclusive_low_power":
        found.append(
            f"NEITHER TEST REJECTS (ADF p = {adf_p_value:.4f}, KPSS p = "
            f"{kpss_p_value:.4f}, alpha = {alpha}), so the series is neither "
            f"confirmed stationary nor confirmed to have a unit root. This is not a "
            f"contradiction — it is an absence of evidence, and ADF's low power "
            f"against a near-unit-root alternative is the usual cause. Do not read it "
            f"as support for either."
        )

    return found


def _stationarity_interpretation(verdict: str, name: str, alpha: float) -> str:
    """Plain-language meaning of the verdict, naming the series."""
    readings = {
        "stationary": (
            f"ADF and KPSS AGREE that '{name}' is stationary: ADF rejects a unit root "
            f"and KPSS does not reject stationarity, both at alpha = {alpha}."
        ),
        "non_stationary": (
            f"ADF and KPSS AGREE that '{name}' has a unit root: ADF fails to reject "
            f"one and KPSS rejects stationarity, both at alpha = {alpha}."
        ),
        "inconclusive_conflict": (
            f"INCONCLUSIVE — the two tests CONTRADICT each other on '{name}': ADF "
            f"rejects a unit root while KPSS rejects stationarity. Reported as "
            f"inconclusive rather than resolved by choosing a test."
        ),
        "inconclusive_low_power": (
            f"INCONCLUSIVE — NEITHER test rejects on '{name}', so there is not enough "
            f"information to classify it. An absence of evidence, not evidence of "
            f"stationarity."
        ),
    }
    return readings[verdict]


def _stationarity_limitations() -> list[str]:
    """What a stationarity verdict cannot tell you, on every call."""
    return [
        "ADF has LOW POWER against a near-unit-root alternative, so 'fails to "
        "reject' is much weaker evidence than 'rejects'. A series can carry a unit "
        "root and still fail to be detected, especially in a short sample.",
        "Both tests use ASYMPTOTIC critical values. On a short series the reported "
        "p-value is a small-sample approximation whose error neither test discloses.",
        "A STRUCTURAL BREAK is read as a unit root by ADF and as non-stationarity "
        "by KPSS. Neither test distinguishes 'this series is a random walk' from "
        "'this series is stationary around a level that moved once' — and those "
        "imply opposite things for a relative-value trade.",
        "Stationarity is not a property of the economic relationship, only of this "
        "series over this window. A verdict says nothing about whether a mechanism "
        "connects two series, which is what test_cointegration is for.",
    ]


def _prepare_series(series: pd.Series) -> tuple[pd.Series, str]:
    """Validate a single series for a stationarity test, or raise.

    Separate from ``_prepare_observations`` because the requirements differ in
    one direction that matters: a stationarity test needs **far more rows** than
    a regression (``stationarity_min_observations``, 30, against
    ``min_observations``, 8), because both tests' critical values are asymptotic.
    Sharing one floor would let a 9-row series reach a test that cannot support
    it.
    """
    if not isinstance(series, pd.Series):
        raise TypeError(f"series must be a pandas Series, got {type(series).__name__}.")
    if series.empty:
        raise ValueError("series is empty; there is nothing to test.")
    if is_bool_dtype(series.dtype) or not is_numeric_dtype(series.dtype):
        raise ValueError(f"series must be numeric, got dtype {series.dtype}.")

    values = series.astype("float64")
    if not bool(np.isfinite(values.to_numpy()).all()):
        raise ValueError(
            "series contains non-finite values (NaN or inf). Clean or impute them "
            "explicitly: dropping those rows here would change the sample without "
            "recording it."
        )

    minimum = int(get_settings().econometrics.stationarity_min_observations.value)
    if len(values) < minimum:
        raise ValueError(
            f"{len(values)} observations is below the configured floor of {minimum} "
            f"(econometrics.stationarity_min_observations). ADF's and KPSS's critical "
            f"values are asymptotic, so a shorter series would be judged against a "
            f"small-sample approximation whose error neither test reports."
        )

    if math.isclose(float(values.max()), float(values.min()), rel_tol=0.0, abs_tol=0.0):
        raise ValueError(
            "series is constant across the sample, so it has no dynamics to test: "
            "ADF and KPSS are both degenerate on a constant series and would return "
            "statistics that mean nothing."
        )

    return values, (str(series.name) if series.name is not None else "unnamed")


def _validate_mechanism(mechanism: str) -> str:
    """Return the stripped mechanism, or raise if it is not substantive.

    The floor is a **length** check, not a quality judgement — it cannot tell a
    sound mechanism from a confident wrong one, and it does not try. It rejects
    the empty string, whitespace, and placeholders, which is the whole of what
    is mechanically checkable. The field's real work is evidentiary: it exists
    so the hypothesis is dated before the fit.
    """
    if not isinstance(mechanism, str):
        raise TypeError(
            f"require_mechanism must be a string stating the hypothesised mechanism, "
            f"got {type(mechanism).__name__}."
        )

    minimum = int(get_settings().econometrics.mechanism_min_length.value)
    stripped = mechanism.strip()
    if len(stripped) < minimum:
        raise ValueError(
            f"require_mechanism must state the economic mechanism hypothesised BEFORE "
            f"fitting (Section 15.18: mechanism first, statistics second). Got "
            f"{len(stripped)} characters after stripping, minimum {minimum}. "
            f"A caller that cannot articulate a mechanism should not be running the "
            f"regression."
        )
    return stripped


def _prepare_observations(
    y: pd.Series,
    X: pd.DataFrame,  # noqa: N803 - kept consistent with the public signature's mandated name
) -> tuple[pd.Series, pd.DataFrame]:
    """Validate and normalise the two sides of the regression, or raise.

    Returns float64 copies so the fit cannot be perturbed by the caller's
    dtypes (an ``int8`` column and an ``object`` column that looks numeric are
    both real ways to get a wrong answer from correct-looking input).

    Every check here is a refusal, never a repair. The alternative — dropping
    the offending rows — is the failure this project records as *"flag, don't
    fix"*: it changes ``n_obs`` without saying so, and a regression reported
    over a silently different sample is a claim the caller cannot audit.
    """
    if not isinstance(y, pd.Series):
        raise TypeError(f"y must be a pandas Series, got {type(y).__name__}.")
    if not isinstance(X, pd.DataFrame):
        raise TypeError(f"X must be a pandas DataFrame, got {type(X).__name__}.")

    if X.shape[1] == 0:
        raise ValueError("X must have at least one regressor column; it has none.")

    # Column NAMES are validated before anything reads a column, because both
    # failure modes below are silent rather than loud — and one of them loses a
    # coefficient without any error at all.
    #
    # (1) A duplicated name makes ``X[name]`` return a DataFrame rather than a
    #     Series, so the dtype and finiteness checks raise an AttributeError from
    #     inside pandas instead of a refusal that names the problem. Measured
    #     2026-09-22: `pd.DataFrame(..., columns=['a','a'])` produced
    #     "'DataFrame' object has no attribute 'dtype'".
    # (2) A column literally named ``const`` collides with the intercept this
    #     function prepends. Measured: the design matrix then carries TWO
    #     ``const`` columns, statsmodels returns a params Series with a
    #     duplicated index, and the ``{name: value}`` comprehension that builds
    #     ``beta`` keeps only the last — so the fit reported **fewer coefficients
    #     than the caller supplied, silently**. The VIF loop skips every
    #     ``const``, so the caller's real regressor also lost its collinearity
    #     report. That is the worst shape this project recognises: a wrong answer
    #     that looks complete.
    duplicated_names = sorted({str(name) for name in X.columns[X.columns.duplicated()]})
    if duplicated_names:
        raise ValueError(
            f"X has duplicate column name(s) {duplicated_names}. A duplicated label "
            f"makes `X[name]` return a DataFrame rather than a Series, and the "
            f"coefficient map is keyed by name — so one regressor would overwrite "
            f"another and the fit would report fewer coefficients than you supplied. "
            f"Rename them distinctly."
        )
    if _INTERCEPT_NAME in {str(name) for name in X.columns}:
        raise ValueError(
            f"X contains a column named {_INTERCEPT_NAME!r}, which collides with the "
            f"intercept this function prepends. The design matrix would hold two "
            f"columns of that name and the coefficient map would silently keep only "
            f"one of them. Rename the regressor."
        )

    if len(y) != len(X):
        raise ValueError(
            f"y and X must have the same number of rows: y has {len(y)}, X has {len(X)}. "
            f"Align them explicitly — this function will not intersect them silently."
        )
    if not y.index.equals(X.index):
        raise ValueError(
            "y and X must share an identical index. They are the same length but "
            "labelled differently, so pairing them by position would be an assumption "
            "about alignment that this function is not entitled to make."
        )
    if is_bool_dtype(y.dtype) or not is_numeric_dtype(y.dtype):
        raise ValueError(f"y must be numeric, got dtype {y.dtype}.")

    for name in X.columns:
        if is_bool_dtype(X[name].dtype) or not is_numeric_dtype(X[name].dtype):
            raise ValueError(
                f"Regressor {name!r} must be numeric, got dtype {X[name].dtype}. "
                f"Encode categoricals explicitly so the encoding is reviewable."
            )

    y_f = y.astype("float64")
    x_frame = X.astype("float64")

    if not bool(np.isfinite(y_f.to_numpy()).all()):
        raise ValueError(
            "y contains non-finite values (NaN or inf). Clean or impute them "
            "explicitly: dropping those rows here would change n_obs without "
            "recording it."
        )
    non_finite_columns = [
        str(name)
        for name in x_frame.columns
        if not bool(np.isfinite(x_frame[name].to_numpy()).all())
    ]
    if non_finite_columns:
        raise ValueError(
            f"Regressor(s) {non_finite_columns} contain non-finite values (NaN or inf). "
            f"Clean or impute them explicitly."
        )

    minimum_observations = int(get_settings().econometrics.min_observations.value)
    if len(y_f) < minimum_observations:
        raise ValueError(
            f"{len(y_f)} observations is below the configured floor of "
            f"{minimum_observations} (econometrics.min_observations). A fit on fewer "
            f"points can be arithmetically legal and statistically meaningless, and no "
            f"degrees-of-freedom check will say so."
        )

    constant_columns = [
        str(name)
        for name in x_frame.columns
        if math.isclose(
            float(x_frame[name].max()),
            float(x_frame[name].min()),
            rel_tol=0.0,
            abs_tol=0.0,
        )
    ]
    if constant_columns:
        raise ValueError(
            f"Regressor(s) {constant_columns} are constant across the sample and "
            f"therefore carry no information. Remove them: statsmodels would drop "
            f"such a column silently, and the resulting fit would report fewer "
            f"coefficients than the caller supplied without saying why."
        )

    return y_f, x_frame


def _variance_inflation_factors(design: pd.DataFrame) -> dict[str, float]:
    """VIF per non-intercept regressor, from the design matrix.

    ``VIF_j = 1 / (1 - R2_j)`` where ``R2_j`` comes from regressing regressor
    ``j`` on the others. The intercept is excluded because including it
    inflates every factor by a constant and makes the textbook cutoff of 10
    meaningless — a detail that is easy to get wrong and produces plausible
    numbers when you do.

    Every factor returned here is finite **by construction**, not by a check:
    ``run_regression`` refuses a rank-deficient design before this is called,
    and a full-rank design has ``R2_j < 1`` strictly, so ``VIF_j`` cannot
    diverge. A guard on the output would be unreachable code, which this
    project counts as a defect class rather than as defence in depth.
    """
    values = design.to_numpy(dtype=float)
    factors: dict[str, float] = {}
    for position, name in enumerate(design.columns):
        if str(name) == _INTERCEPT_NAME:
            continue
        factors[str(name)] = float(variance_inflation_factor(values, position))
    return factors


def _collect_warnings(
    *,
    r_squared: float,
    vif: dict[str, float] | None,
    low_r_squared_threshold: float,
    vif_concern_threshold: float,
) -> list[str]:
    """The conditions of *this* run that a consumer must know about.

    Kept separate from ``_limitations`` on purpose: these fire only when the
    fit actually exhibits the condition, so a reader can treat their presence
    as signal. Conditions that hold on every call belong in the limitations.
    """
    warnings: list[str] = []

    if r_squared < low_r_squared_threshold:
        warnings.append(
            f"WEAK MECHANISM, NOT A FAILED FIT: R-squared is {r_squared:.4f}, below "
            f"the configured floor of {low_r_squared_threshold:.4f}. The regressors "
            f"explain little of the variation in y. Section 15.18 treats this as a "
            f"humility signal about the mechanism rather than an error — the "
            f"coefficients are still the best linear estimates available, but a "
            f"consumer should not read this fit as corroboration."
        )

    # A perfect fit is not a triumph. On observational macro data it is almost
    # always a specification error: y regressed on a transform of itself, a
    # leakage from the future, or a tautological regressor.
    if math.isclose(r_squared, 1.0, rel_tol=0.0, abs_tol=1e-12):
        warnings.append(
            "PERFECT FIT (R-squared = 1.0) — treat as a specification error until "
            "proven otherwise. An exact linear relationship in observational macro "
            "data normally means a regressor is a transform of y, or carries "
            "information from the future. Check the construction of every column "
            "before using this result."
        )

    if vif:
        concerning = sorted(
            ((name, value) for name, value in vif.items() if value > vif_concern_threshold),
            key=lambda item: item[1],
            reverse=True,
        )
        if concerning:
            detail = ", ".join(f"{name} ({value:.1f})" for name, value in concerning)
            warnings.append(
                f"MULTICOLLINEARITY: variance inflation factor above "
                f"{vif_concern_threshold:.1f} for {detail}. Those coefficients are "
                f"jointly unstable — small changes in the sample move them a lot, and "
                f"their individual p-values understate the uncertainty. The fit as a "
                f"whole is unaffected. This function does not drop a column, because "
                f"which regressor is redundant is an economic judgement."
            )

    return warnings


def _limitations() -> list[str]:
    """What this result cannot tell you, even when the fit succeeded.

    Standing caveats, so they are stated on every call rather than triggered by
    one. The first is the module's own first discipline and the reason
    ``test_stationarity`` exists beside this function.
    """
    return [
        "Stationarity is NOT tested here. Regressing one non-stationary level on "
        "another produces a significant coefficient and a high R-squared from two "
        "independent random walks (spurious regression). Run test_stationarity on "
        "both sides first; Section 15.18 requires it before a level regression is "
        "trusted.",
        "OLS is linear and tests no omitted-variable hypothesis. A coefficient "
        "significant here may be standing in for a correlated driver that is not "
        "in the design matrix.",
        "Every input comes from one sample, so nothing in this result is "
        "independently corroborated — agreement between regressors is not "
        "agreement between sources.",
    ]


def _r_squared_floor_is_calibrated() -> bool:
    """Whether the ONE threshold this function leans on is calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated``.

    Named for the single leaf it reads rather than for the config section it
    lives in, because the name is load-bearing: an earlier version was called
    ``_thresholds_calibrated`` (plural) while checking exactly one leaf, and a
    future reader who added a second illustrative threshold would reasonably
    assume the helper already covered it. The R-squared floor is the leaf that
    matters here — it is what turns a number into the judgement "weak" — so it
    is the one that costs confidence when it is a placeholder.
    """
    settings = get_settings()
    return settings.is_calibrated("econometrics.low_r_squared_threshold")
