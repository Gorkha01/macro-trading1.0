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

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from pydantic import ConfigDict, Field
from statsmodels.stats.outliers_influence import variance_inflation_factor

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = ["RegressionResult", "run_regression"]

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
                is_heuristic_not_calibrated=not _thresholds_calibrated(),
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


def _thresholds_calibrated() -> bool:
    """Whether Module 18's acceptance thresholds are calibrated or placeholders.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated``. The R-squared
    floor is the one this function genuinely leans on — it is what turns a
    number into the judgement "weak" — so it is the one that is checked.
    """
    settings = get_settings()
    return settings.is_calibrated("econometrics.low_r_squared_threshold")
