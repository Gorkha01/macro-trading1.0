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

``test_cointegration`` is the third and most demanding of the module's
functions. Section 15.18-F requires more of it than of either predecessor: it
must return the **spread series**, the spread's **estimated half-life of mean
reversion**, and a **regime-stability check** alongside the test statistic — and
it must carry two warnings on every call, one about the method (cointegration is
a backward-looking estimate that breaks in regime change, LTCM) and one that is
a **counting obligation** rather than a sentence (multiple pairwise tests
without a multiple-testing correction reject at roughly the nominal rate per
test, so a family of ``m`` tests carries a family-wise error rate near
``1 - (1 - alpha)**m``).

The half-life is **derived here, not recalled**. The spread ``z`` is the
cointegrating residual; its mean reversion is estimated from an AR(1) written
with the *difference* on the left,

    dz_t = phi * z_{t-1} + eps_t,

whose continuous-time analogue ``dz/dt = -kappa * z`` has ``phi = -kappa`` and
therefore a half-life ``H = ln(2) / kappa = -ln(2) / phi``. The derivation, its
sign check, its limiting behaviour and the aliasing boundary are written out at
:func:`_estimate_half_life`, because a formula quoted without them is the kind
of number that looks complete.

Deliberately absent: any data fetching. Models consume aligned inputs
(Section 6) and the caller owns provenance; this module never reaches for a
provider, and it raises rather than repairing an input it cannot use.
"""

from __future__ import annotations

import math
import warnings
from typing import Any, NamedTuple, TypedDict

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from pydantic import ConfigDict, Field
from scipy.stats import norm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.sm_exceptions import (
    CollinearityWarning,
    InterpolationWarning,
    SingularMatrixWarning,
)
from statsmodels.tsa.statespace.mlemodel import MLEModel
from statsmodels.tsa.stattools import adfuller, coint, kpss
from statsmodels.tsa.tsatools import add_trend

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "RegressionResult",
    "compute_pca",
    "kalman_latent_state",
    "run_regression",
    "test_cointegration",
    "test_stationarity",
]

#: The name ``statsmodels`` gives the intercept it prepends. Named once here so
#: the VIF loop and the reporting code cannot disagree about which column to
#: exclude — the same "one spelling" discipline the series registry applies to
#: provider routes.
_INTERCEPT_NAME = "const"


class _HalfLife(TypedDict):
    """The half-life estimate, as a typed shape rather than a bag of ``object``.

    ``periods`` and ``phi`` are BOTH optional, and the distinction between the
    two kinds of absence is carried by ``note`` rather than by a sentinel: this
    structure reports *"there is no half-life, and here is why"* — the reason is
    the finding, so it is a required field rather than a debug string. A
    ``TypedDict`` (not a Pydantic model) because this never crosses an I/O
    boundary and never needs validation; the strict-typing value is that the
    caller cannot read ``phi`` as a ``str`` without mypy saying so.
    """

    periods: float | None
    phi: float | None
    note: str


class _HalfSample(TypedDict):
    """One half of the regime-stability split."""

    label: str
    n_obs: int
    is_cointegrated: bool | None
    p_value: float | None
    refused: str | None


class _RegimeStability(TypedDict):
    """The regime-stability check's outcome, including why it did not run."""

    verdict: str
    agreement: bool
    split_index: int
    first_half: _HalfSample | None
    second_half: _HalfSample | None
    note: str


class _MultipleTesting(TypedDict):
    """The multiple-testing correction, computed rather than narrated."""

    family_size: int
    family_wise_error_rate: float
    corrected_size: float


class _SpreadReading(TypedDict):
    """ADF on the reconstructed spread — supporting evidence, not the verdict."""

    statistic: float
    p_value: float
    is_stationary: bool
    design_was_ill_conditioned: bool


#: ``coint`` returns three critical values ordered most-severe first, so a
#: three-tuple names the ordering rather than leaving it to a comment.
_Criticals = tuple[float, float, float]


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
        # --- Section 3/4 reasoning object (D-132) ---------------------------
        # Added by D-132: `data_provenance` and `decision_relevance` were
        # published by NONE of this module's five functions, and `unit` was
        # absent here specifically. What a coefficient is measured in, and what
        # downstream gate consumes it, are the two things a reader cannot
        # recover from the numbers — and every field defaults to an honest
        # "not supplied", so the omission was invisible.
        #
        # `direction` is deliberately LEFT UNSET: `value` is a coefficient MAP,
        # so there is no single direction the output moves in — the sign is per
        # regressor, and inventing one direction would assert an ordering the
        # estimator does not have (the same reasoning `dollar_smile_regime`
        # gives for its categorical partition).
        unit=(
            "coefficient units are (unit of y) per (unit of the named regressor); "
            "value is the coefficient map, keyed by regressor name"
        ),
        warnings=warnings,
        assumptions=[f"Mechanism hypothesised before fitting: {mechanism}"],
        data_provenance=[
            "y and every column of X are SERIES SUPPLIED BY THE CALLER, aligned "
            "and date-matched by the caller. Section 15.18 makes this module "
            "fetch nothing, so it cannot verify the vintages, the alignment, or "
            "that either side is actually the quantity its name claims.",
            "A single dataset supplies every input: y and each regressor come "
            "from the same sample, so there is no independent corroboration to "
            "credit and `source_independence_count` is 0 (Module 13's census).",
        ],
        limitations=_limitations(),
        decision_relevance=(
            "Section 15.18's mechanism gate: the measurement step a stated "
            "economic hypothesis must clear BEFORE a thesis may lean on it. It "
            "carries the mechanism under test onto the record (in "
            "`assumptions`), so a later reader can see whether the relationship "
            "was hypothesised or data-mined. Its verdict is conditioned by "
            "`test_stationarity` — a fit on non-stationary levels is spurious — "
            "and it is the estimator `test_cointegration`'s Engle-Granger step "
            "reuses."
        ),
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
                # F-EC-003: the heuristic flag must be computed from the leaves
                # THIS function reads. It previously called
                # `_r_squared_floor_is_calibrated()`, which reads
                # `econometrics.low_r_squared_threshold` — a leaf
                # `test_stationarity` never consumes — so a placeholder elsewhere
                # in the module priced this verdict's confidence. The dedicated
                # helper reads `significance_level` and
                # `stationarity_min_observations` (both `conventional` today), so
                # no penalty is applied and the confidence is 0.70, not 0.50.
                is_heuristic_not_calibrated=not _stationarity_thresholds_calibrated(),
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
        # --- Section 3/4 reasoning object (D-132) ---------------------------
        # D-132: this function published NONE of `unit`, `direction`,
        # `assumptions`, `data_provenance` or `decision_relevance` — five of the
        # seven fields — while its siblings published most of them. A verdict
        # like `inconclusive_low_power` is uninterpretable without knowing that
        # it is a SAMPLE property, on which data, under what nulls.
        unit=(
            "categorical (stationarity verdict label: 'stationary' | "
            "'non_stationary' | 'inconclusive_conflict' | 'inconclusive_low_power')"
        ),
        # `direction` is deliberately LEFT UNSET: the value is a verdict, and
        # two of the four verdicts are inconclusive — there is no direction the
        # output moves in that a "stationary vs not" flag could honestly carry.
        assumptions=[
            "The series is a SINGLE, correctly-ordered time series at a constant "
            "frequency. Neither test can see a gap, a duplicated period, or an "
            "irregular spacing — the verdict is a statement about the sample as "
            "ordered, not about an economic quantity.",
            "ADF's null is a unit root and KPSS's null is stationarity — the two "
            "nulls are INVERTED, so agreement (not the size of either p-value) is "
            "what a confident verdict rests on.",
            "The deterministic specification is the same for both tests and is "
            "the configured `adf_regression` ('c' = constant only, or 'ct' = "
            "constant and linear trend). A trend-stationary series tested under "
            "'c' is the textbook false non-rejection.",
            "The lag selection is the configured rule (`adf_autolag` for ADF; "
            "KPSS's own `nlags`), and the p-values are read at the configured "
            "`significance_level`.",
        ],
        data_provenance=[
            f"series:{name} — SUPPLIED BY THE CALLER as an already-aligned "
            f"pandas Series. This module fetches nothing (Section 6/15.18), so it "
            f"cannot verify the series' definition, vintage, or frequency.",
        ],
        warnings=warnings,
        limitations=_stationarity_limitations(),
        decision_relevance=(
            "Section 15.18's stationarity gate, and the precondition "
            "`run_regression` names in its own prohibitions: a significant "
            "coefficient on a non-stationary level regression is the spurious "
            "regression the module exists to refuse. A `non_stationary` verdict "
            "is the trigger for the difference/cointegrate decision that "
            "`test_cointegration` resolves — differencing discards the level "
            "information cointegration depends on, which is why this verdict must "
            "be read before either is chosen."
        ),
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


def test_cointegration(
    y: pd.Series,
    x: pd.Series,
    method: str = "engle_granger",
) -> ModelResult:
    """Test ``y`` and ``x`` for cointegration, returning the SPREAD and more.

    Section 15.18-F requires three things beside the test statistic, and this
    function returns all three as first-class fields rather than as prose:

    * **the spread series** — ``value['spread']``, the estimated cointegrating
      residual ``z_t = y_t - alpha - beta * x_t``. It is published because a
      cointegration test that returns only a p-value has thrown away the object
      the trade is actually built on: the tradable thing is the spread, and a
      consumer who has to re-derive it will re-derive a *different* one. The
      series published here is **provably the same series the statistic was
      computed from** — the reporting code re-builds the residual from the
      design ``coint`` uses internally, and a test asserts the re-derived ADF
      statistic equals ``coint``'s to 1e-10. Same basis, measured rather than
      assumed (Section 9's first question).
    * **the half-life of mean reversion** — ``value['half_life_periods']``, from
      an AR(1) on the spread. Derived; see :func:`_estimate_half_life`.
    * **a regime-stability check** — ``value['regime_stability']``, from
      re-testing the relationship on the first and second halves of the sample
      separately. Only the **support** of the two sub-samples is compared, never
      their p-values: two half-sample p-values cannot be compared with each
      other at the full-sample size, and only the **support** is a property that
      is comparable across windows.

    ``method`` selects the test. ``"engle_granger"`` runs the two-step
    Engle-Granger procedure (regress ``y`` on ``x``, then ADF the residual) via
    ``statsmodels.tsa.stattools.coint``. ``"johansen"`` runs Johansen's
    trace/maximum-eigenvalue test via ``statsmodels.tsa.vector_ar.vecm``. The
    two are **not interchangeable** and the result says which ran: Engle-Granger
    assumes a **single** cointegrating vector and imposes it as the regression
    residual, while Johansen estimates the number of vectors. On a pair the two
    agree about the count; on the *estimate* they can differ, and Engle-Granger's
    two-step residual is the more fragile of the two because every error from
    step one is carried into step two unpenalised.

    **Two warnings fire on EVERY call**, because Section 15.18-F makes them
    mandatory rather than conditional — both are properties of the method, not
    conditions of this run, so a consumer must never be able to obtain a result
    that lacks them:

    (a) **Cointegration is a BACKWARD-LOOKING estimate that breaks in regime
        change.** The statistic describes the sample, and the relationship it
        measures is exactly the kind that fails at the moment it is most
        depended on — LTCM's convergence trades were built on spreads that had
        been stationary for years and stopped being so when the régime changed.
        A spread that has never broken is not evidence that it cannot.
    (b) **Multiple pairwise tests need a multiple-testing correction.** This
        function tests **one** pair and therefore cannot know the size of the
        family it belongs to; the count-inflation it warns about is a
        family-level property. The corrected size for each test in a family of
        ``m`` is ``1 - (1 - alpha) ** (1 / m)``, and the family-wise error rate
        is ``1 - (1 - alpha) ** m``. Both are **computed and printed with the
        stated family size**, never asserted as a sentence, because the number
        is the obligation.

    **Raises** rather than repairs, on every input defect, as its siblings do:
    wrong types, mismatched lengths or indexes, non-numeric or non-finite
    values, a constant series, or too few observations.

    **Three silent-failure paths were found by probing ``coint`` before writing
    this**, and every one of them returns a plausible-looking number without
    raising. All three are refused or disclosed:

    1. On near-collinear series ``coint`` returns ``coint_t = -inf`` with
       ``pvalue = 0.0`` — an infinitely significant result from a degenerate
       regression — and only emits a ``CollinearityWarning``. Measured
       2026-09-23 on ``y = 2*x + tiny noise``: ``CointResult(coint_t=-inf,
       pvalue=0.0, ...)``. An ``-inf`` statistic would sail through any
       finiteness check applied to the *p-value* alone, so this refuses.
    2. With ``trend="n"`` the critical values come back as ``[nan, nan, nan]``
       (the 2010 table is unavailable for that case), and **every comparison
       against NaN is False** — so a ranking against the critical values reports
       "cannot reject" for any statistic whatsoever. Measured live. The setting
       is validated at config load, and the critical values are checked for
       finiteness here as well.
    3. The half-life estimator is **only valid for** ``-1 < phi < 0``. Outside
       it the fitted slope is a plausible *positive* number (measured: a
       strongly alternating spread fits ``phi = -1.48`` and yields a naive
       "half-life" of 0.468 periods). See :func:`_estimate_half_life`.
    """
    selection = _validate_cointegration_method(method)
    y_series, x_series = _prepare_pair(y, x)
    settings = get_settings()
    econometrics = settings.econometrics

    alpha = float(econometrics.significance_level.value)
    trend = str(econometrics.cointegration_trend)

    discarded_imaginary = 0
    if selection == "johansen":
        (
            statistic,
            p_value,
            critical_values,
            is_rejected,
            discarded_imaginary,
        ) = _run_johansen(y_series, x_series, alpha=alpha)
        beta = math.nan  # Johansen estimates a vector, not a normalised slope
        spread = pd.Series(dtype="float64", name="spread")
    else:
        outcome = _run_engle_granger(y_series, x_series, trend=trend, alpha=alpha)
        statistic, p_value, critical_values, is_rejected = outcome
        beta, spread = _engle_granger_spread(y_series, x_series, trend=trend)

    # The ADF the cointegration test applies to the residual has no constant
    # and no trend BY CONSTRUCTION (the residual is already demeaned by the
    # first-step regression), unlike `test_stationarity`, which tests a raw
    # series. So the "stationary" half of the pair is asked for differently
    # here, and the difference is stated rather than glossed: this is a
    # *supporting* reading, not the verdict, which is what the p-value gives.
    spread_reading = _spread_stationarity(spread) if selection == "engle_granger" else None

    half_life = _estimate_half_life(spread if selection == "engle_granger" else None)

    stability = _regime_stability(
        y_series,
        x_series,
        method=selection,
        trend=trend,
        alpha=alpha,
        split_fraction=float(econometrics.regime_stability_split_fraction.value),
        minimum=float(econometrics.cointegration_min_observations.value),
    )

    multiple_testing = _multiple_testing_summary(
        alpha=alpha,
        family_size=int(econometrics.assumed_test_family_size.value),
    )

    warnings_ = _cointegration_warnings(
        method=selection,
        is_rejected=is_rejected,
        spread_reading=spread_reading,
        half_life=half_life,
        stability=stability,
        multiple_testing=multiple_testing,
        alpha=alpha,
        n_obs=len(y_series),
        discarded_imaginary=discarded_imaginary,
    )

    return ModelResult(
        model_name="test_cointegration",
        country="us",
        as_of=utc_now(),
        value=_cointegration_value(
            method=selection,
            statistic=statistic,
            p_value=p_value,
            critical_values=critical_values,
            is_rejected=is_rejected,
            alpha=alpha,
            trend=trend,
            n_obs=len(y_series),
            beta=beta,
            spread=spread,
            spread_reading=spread_reading,
            half_life=half_life,
            stability=stability,
            multiple_testing=multiple_testing,
            discarded_imaginary=discarded_imaginary,
        ),
        unit="dimensionless (test statistic)",
        direction=None,
        confidence=compute_confidence(
            ConfidenceInputs(
                # The cointegration thresholds are conventional (a 5% size, a
                # 30-observation floor), but the TWO thresholds that shape the
                # *derived* quantities — the half-life's usability bound and the
                # regime-stability split — are decisions this build made and are
                # not calibrated against realised spread behaviour. That is
                # enough to earn the heuristic penalty (Section 22.8), and it is
                # claimed rather than avoided.
                is_heuristic_not_calibrated=not _cointegration_thresholds_calibrated(),
                # One dataset supplies both series, so there is no independent
                # corroboration to credit.
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        ),
        interpretation=_cointegration_interpretation(
            str(y_series.name), str(x_series.name), selection, is_rejected, alpha, p_value
        ),
        context=(
            f"{selection} statistic {statistic:+.4f}, p = {p_value:.4f}, judged at "
            f"alpha = {alpha}. Deterministic terms: '{trend}' "
            f"({'constant only' if trend == 'c' else 'constant and linear trend'}). "
            f"Observations: {len(y_series)}. "
            f"Critical values (1%/5%/10%): "
            + ", ".join(f"{value:+.4f}" for value in critical_values)
            + ". Regime stability: "
            + str(stability["verdict"])
            + ". Half-life: "
            + (
                f"{half_life['periods']:.4f} periods"
                if half_life["periods"] is not None
                else "NOT ESTIMATED"
            )
            + "."
        ),
        inputs_used=[f"y:{y_series.name}", f"x:{x_series.name}"],
        warnings=warnings_,
        assumptions=[
            "Both series are treated as integrated of order 1, I(1) — the "
            "Granger-representation condition the test presumes. This is NOT "
            "tested here; run test_stationarity on each level first.",
            f"The relationship is estimated with deterministic terms '{trend}'.",
        ],
        # --- Section 3/4 reasoning object (D-132) ---------------------------
        # D-132: `data_provenance` and `decision_relevance` were published by no
        # function in this module; the direction is left unset because the value
        # is a test verdict (reject/fail-to-reject), not a signed quantity.
        data_provenance=[
            "y and x are SERIES SUPPLIED BY THE CALLER, already aligned and "
            "date-matched. This module fetches nothing, so it cannot verify "
            "either level's definition or vintage, and the whole test is only as "
            "meaningful as the two series being the economic quantities their "
            "names claim.",
            "Both legs come from the same sample, so `source_independence_count` "
            "is 0 — a cointegrating relationship between two series from one "
            "dataset has no independent corroboration to credit (Module 13).",
        ],
        limitations=_cointegration_limitations(),
        decision_relevance=(
            "Section 15.18's cointegration gate, and the resolution of the "
            "difference-versus-cointegrate choice `test_stationarity` leaves "
            "open: two I(1) series that are cointegrated must NOT be differenced "
            "independently, because differencing discards the level information "
            "the equilibrium relationship lives in. It replaces the plain "
            "regression for a pair, and its published spread and half-life are "
            "the mean-reversion inputs a pairs thesis is conditioned on."
        ),
        decision_prohibition=[
            "Do not read a rejected null as a tradable spread. This statistic "
            "describes the sample window; it is not a forecast that the spread "
            "will converge in future. LTCM's convergence trades were built on "
            "spreads that had been stationary for years.",
            "Do not run a family of pairwise tests at the same alpha and keep "
            "the significant ones. Without the multiple-testing correction "
            "described above, a family of m tests rejects at roughly m*alpha "
            "under the global null — the significant pair you keep is exactly "
            "the one you looked hardest for.",
            "Do not size a position from the half-life without checking it "
            "against the sampling interval. A half-life at or below one period "
            "cannot be resolved by data at this cadence, and the estimator "
            "refuses to report one below the derived floor for that reason.",
        ],
    )


def _cointegration_value(
    *,
    method: str,
    statistic: float,
    p_value: float,
    critical_values: _Criticals,
    is_rejected: bool,
    alpha: float,
    trend: str,
    n_obs: int,
    beta: float,
    spread: pd.Series,
    spread_reading: _SpreadReading | None,
    half_life: _HalfLife,
    stability: _RegimeStability,
    multiple_testing: _MultipleTesting,
    discarded_imaginary: int = 0,
) -> dict[str, object]:
    """Assemble the published ``value`` — the report Section 15.18-F demands.

    The dict is deliberately **mixed-type** (strings, floats, bools, a nested
    mapping and the spread as a list of floats), because the three mandated
    extras are structurally different objects from the statistic. ``None`` is
    used where a quantity genuinely does not exist — Johansen has no normalised
    slope on a pair, and a half-life is unavailable when the spread does not
    mean-revert — rather than a fabricated ``0.0`` that reads as an estimate.
    """
    payload: dict[str, object] = {
        "method": method,
        "statistic": round(statistic, 6),
        "p_value": round(p_value, 6),
        "critical_values": [round(value, 6) for value in critical_values],
        "is_cointegrated": is_rejected,
        "significance_level": alpha,
        "trend": trend,
        "hedge_ratio": (None if math.isnan(beta) else round(beta, 6)),
        "spread": [float(value) for value in spread.to_numpy()],
        # `n_obs` is the number of rows the TEST consumed, which is the input
        # length -- NOT `len(spread)`, which is zero on the Johansen path that
        # produces no normalised spread. Reporting the spread's length as the
        # sample would publish `n_obs = 0` beside a statistic computed from
        # hundreds of rows: a wrong number that looks like a missing one.
        "n_obs": n_obs,
        # The half-life is a nested mapping rather than a bare float because its
        # ABSENCE and its REFUSAL are different findings: `periods=None` with
        # `phi>=0` says "the spread does not revert", while a missing key would
        # say nothing at all.
        "half_life_periods": half_life["periods"],
        "half_life_phi": half_life["phi"],
        "half_life_note": half_life["note"],
        "regime_stability": stability["verdict"],
        "regime_stability_agreement": stability["agreement"],
        # D-139d: the sub-sample detail was COMPUTED and then DROPPED, while the
        # docstring promised "the two sub-sample p-values are reported so a
        # reader can see them" and a warning pointed at `regime_stability` on
        # the value — a field that held only a verdict string. The evidence a
        # reader is told exists must actually be published.
        "regime_stability_split_index": stability["split_index"],
        "regime_stability_first_half": stability["first_half"],
        "regime_stability_second_half": stability["second_half"],
        "regime_stability_note": stability["note"],
        # Published so the disclosure in the warnings has a number to point at.
        # Zero on the Engle-Granger path, which never calls the eigendecomposition
        # that emits it — so the field is present on both paths and its value
        # distinguishes them, rather than the key silently appearing only for one.
        "discarded_imaginary_warnings": discarded_imaginary,
    }

    if spread_reading is not None:
        payload["spread_adf_statistic"] = spread_reading["statistic"]
        payload["spread_adf_p_value"] = spread_reading["p_value"]
        payload["spread_is_stationary"] = spread_reading["is_stationary"]

    payload["family_size_assumed"] = multiple_testing["family_size"]
    payload["family_wise_error_rate"] = multiple_testing["family_wise_error_rate"]
    payload["corrected_per_test_size"] = multiple_testing["corrected_size"]
    return payload


def compute_pca(daily_changes: pd.DataFrame, n_components: int = 3) -> ModelResult:
    """Principal components of a panel of DAILY CHANGES, with its loadings.

    Section 15.20-F's signature. Three things about it are load-bearing, and
    each is enforced here rather than left to the caller:

    **1. DAILY CHANGES, never raw levels.** This is the specification's most
    emphatic instruction about the function ("levels are trend-dominated and
    produce a misleading PC1") and it is the one thing the function cannot
    verify for itself: a level panel and a change panel are both plausible
    floating-point frames, and the level one yields a beautiful PC1 that
    explains 99% of the variance and means nothing — it is a time trend. So the
    discipline is stated as an **assumption with the arithmetic that makes it
    checkable**, plus a warning whenever the panel's own shape *suggests* the
    caller passed levels (see ``_pca_panel_suspicion``). It is a warning and not
    a refusal because a strongly-trending change panel is a real thing.

    **2. The decomposition route is measured, not assumed.** Section 4 lists
    ``scikit-learn`` against this function, but the decision recorded in D-099
    is that **``numpy.linalg.eigh`` on the covariance reproduces sklearn's PCA
    to machine precision for this spec, so the dependency is not taken.** That
    is a claim about agreement, and it was measured against a real
    ``scikit-learn`` install before this function was written: ratios agree to
    ``1.5e-16``, loadings to ``6.2e-17``, eigenvalues to ``2.6e-18``. Two
    details of sklearn's behaviour are what the comparison surfaced, and both
    are reproduced here deliberately:

    * **The sign rule.** ``eigh``'s eigenvector signs are LAPACK-arbitrary, so
      the same input can return ``v`` or ``-v`` across builds and platforms.
      sklearn's ``svd_flip`` normalises this by making the **largest-magnitude
      loading in each component POSITIVE**, and that is a *convention*, not
      mathematics: a component and its negation describe the same factor. This
      function applies the same rule so its output is comparable with sklearn's
      and reproducible run-to-run. The rule is stated in the output rather than
      left implicit, because a negative loading sign in a *chart* is exactly how
      a level factor gets read as a slope factor.
    * **The normalisation.** ``explained_variance_ratio_`` divides by the total
      variance, and the total is the **unbiased** ``1/(n-1)`` sum — the
      denominator ``np.cov`` uses, which is *not* the biased ``1/n`` that
      sklearn's own source suggests at a glance. Measured ratio agreement
      ``0.9999999999999994``. Using ``1/n`` here would bias every published
      ratio by ``(n-1)/n`` — invisible at ``n = 500`` (0.2%) and a real error at
      ``n = 30``.

    **3. Components are NEVER auto-labelled level/slope/curvature.** The
    specification forbids it and gives the reason: the labels are an
    *interpretation* of the loadings, and an interpretation is a claim about
    the data that this function is not entitled to make on the caller's behalf.
    A PC1 whose loadings are all the same sign *is* a level shock, but so is a
    PC1 on a panel where every tenor moved for an unrelated reason, and only a
    reader who has looked at the loadings can tell the difference. So the result
    publishes the loadings and, in ``decision_prohibition``, forbids the
    labelling — the same discipline that makes ``curve_slope`` refuse to call
    its own spread a recession signal.

    **Three silent-failure paths were found by probing ``eigh`` before writing
    this**, and every one returns a plausible, complete-looking output without
    raising:

    1. **A rank-deficient panel produces NEGATIVE eigenvalues.** Measured
       2026-09-23 on a duplicated column, on a perfectly collinear column
       (``b = 2a``), and on a constant column: the most negative eigenvalue runs
       to ``-1.69e-15``, and on the perfectly-collinear case the *published
       ratio itself* prints ``-0.000000000000``. A negative explained variance
       is incoherent — a variance cannot be negative — and the ratios still sum
       to exactly 1.0, so the output looks complete while carrying a
       contradiction. ``np.linalg.matrix_rank`` identifies the cause, so a
       rank-deficient panel is **refused**, exactly as ``run_regression``
       refuses a rank-deficient design.
    2. **``n_components`` out of range fails silently or cryptically.** Asking
       for more components than the panel has columns (5 from 4 tenors) has no
       meaning, and asking for zero or fewer has none either; the sliced
       matrices would be shorter than the caller expects, or empty, and the
       result would still be well-formed. Both are refused with the number
       named.
    3. **A non-finite panel propagates NaN into every eigenvalue and every
       loading** rather than raising, so a single NaN yields a full set of
       ``nan`` components that render as a blank chart rather than as an error.
       Refused, as the module's siblings refuse it.

    Returns a ``ModelResult`` whose ``value`` carries ``eigenvalues``,
    ``explained_variance_ratios``, ``cumulative_explained_variance``,
    ``loadings`` (a ``{component: {tenor: loading}}`` map), the ``sign_rule``
    applied, the ``standardisation`` used, and ``n_obs`` /
    ``n_variables``. ``None`` is never substituted for a quantity that exists;
    where something does not exist (a refused component index) the call raises
    rather than publishing a placeholder.
    """
    settings = get_settings()
    econometrics = settings.econometrics

    panel, column_names = _prepare_panel(daily_changes)
    n_obs, n_variables = panel.shape

    # `n_components` is validated BEFORE the decomposition, and against the
    # panel's width rather than a literal: the number of components a panel can
    # support is a property of the panel, so a fixed bound here would be wrong
    # for a 2-tenor panel and wrong the other way for a 12-tenor one.
    components = _validate_component_count(n_components, n_variables)

    standardisation = str(econometrics.pca_standardisation)
    # A constant series is refused BEFORE standardisation, so the check governs
    # both routes rather than only the correlation one. This is not tidiness: on
    # the candidate `covariance` route a non-zero constant column passes the
    # rank check downstream, because `matrix_rank`'s tolerance is RELATIVE to
    # the matrix's largest singular value and a small constant column is
    # swamped by the others. Measured 2026-09-23: a column of `4.2` repeated 200
    # times sailed through the covariance route and was decomposed as a fourth
    # independent direction, returning a `-0.0` loading. See
    # :func:`_refuse_constant_series`.
    _refuse_constant_series(panel, column_names)
    matrix = _standardise_panel(panel, column_names, standardisation)

    # Rank is checked on the matrix actually decomposed, so the refusal names
    # the same object the eigenvalues come from. This is the guard for silent
    # failure #1: a rank-deficient matrix is the *cause* of the negative
    # eigenvalue, and checking it here means the published variance can never be
    # negative by construction rather than by a finiteness test on the output.
    rank = int(np.linalg.matrix_rank(matrix))
    if rank < n_variables:
        raise ValueError(
            f"The panel is rank-deficient: {n_variables} columns but rank {rank} "
            f"under {standardisation!r} standardisation. At least one series is an "
            f"exact linear combination of the others (a duplicated tenor, a constant "
            f"column, or two tenors that move in lockstep), so it contributes no "
            f"independent variation. The eigendecomposition of such a covariance "
            f"returns a NEGATIVE eigenvalue -- measured at -1.69e-15 on a collinear "
            f"panel, with the published ratio printing -0.000000000000 while the "
            f"ratios still sum to 1.0. A negative variance is incoherent, so this "
            f"refuses rather than publishing it. Drop the redundant series."
        )

    eigenvalues, loadings = _decompose(matrix)

    # The sign rule, applied before anything reads the loadings, so every
    # published figure is under one convention. See the docstring: signs are a
    # CHOICE, and sklearn's is the largest-|loading| element positive.
    loadings = _apply_sign_rule(loadings)

    total_variance = float(eigenvalues.sum())
    ratios = eigenvalues / total_variance

    published = _pca_value(
        eigenvalues=eigenvalues,
        ratios=ratios,
        loadings=loadings,
        column_names=column_names,
        n_obs=n_obs,
        n_variables=n_variables,
        components=components,
        standardisation=standardisation,
    )

    warnings_ = _pca_warnings(
        eigenvalues=eigenvalues,
        ratios=ratios,
        n_obs=n_obs,
        panel=panel,
        standardisation=standardisation,
        near_zero_threshold=float(econometrics.pca_near_zero_tolerance.value),
    )
    suspicion = _pca_panel_suspicion(panel)
    if suspicion is not None:
        warnings_.append(suspicion)

    return ModelResult(
        model_name="compute_pca",
        country="us",
        as_of=utc_now(),
        value=published,
        unit="dimensionless (variance ratios); loadings dimensionless",
        direction=None,
        confidence=compute_confidence(
            ConfidenceInputs(
                # Two decisions shape the *published* numbers and neither is
                # calibrated: the standardisation choice (which changes the
                # loadings by up to 0.28 on a heteroskedastic panel -- measured)
                # and the near-zero tolerance that decides when a component is
                # reported as carrying no variance. Claiming the penalty is the
                # honest reading of Section 22.8.
                is_heuristic_not_calibrated=not _pca_choices_calibrated(),
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        ),
        interpretation=(
            f"{components} principal component(s) of {n_variables} series over "
            f"{n_obs} observations explain "
            f"{float(ratios[:components].sum()):.1%} of the panel's variance "
            f"(PC1 {float(ratios[0]):.1%}). Components are identified by their "
            f"loadings, not by their order — see `loadings`; this function does "
            f"not label them."
        ),
        context=(
            f"Standardisation: {standardisation}. Eigenvalues: "
            + ", ".join(f"{value:.6g}" for value in eigenvalues[:components])
            + ". Explained-variance ratios: "
            + ", ".join(f"{value:.4%}" for value in ratios[:components])
            + f". Sign convention: largest-|loading| element positive (sklearn's "
            f"`svd_flip` rule), applied because eigenvector signs are otherwise "
            f"arbitrary. Sample: {n_obs} rows, {n_variables} series."
        ),
        inputs_used=[f"daily_changes:{name}" for name in column_names],
        warnings=warnings_,
        assumptions=[
            "The input is DAILY CHANGES, not levels. This function cannot verify "
            "that, and a level panel yields a PC1 that is a time trend dressed as "
            "a factor; run a stationarity test on each level first.",
            "The input is a returns-style panel where a linear combination is "
            "meaningful. This is true of a yield curve's changes and false of, "
            "say, a panel of unrelated price changes whose scale differences "
            "dominate.",
            f"Components are computed on the {standardisation!r} matrix, and the "
            f"loadings are interpreted under that choice. The covariance route "
            f"weights each series by its own variance; the correlation route "
            f"gives every series equal weight regardless of scale.",
        ],
        # --- Section 3/4 reasoning object (D-132) ---------------------------
        # D-132: `data_provenance` and `decision_relevance` were published by no
        # function in this module. `direction` is left unset: a component is a
        # DIRECTION in the panel's own space, but the published quantity is the
        # set of components and their shares — a single `direction` field would
        # have to pick one component and assert it, which the estimator does not.
        data_provenance=[
            "The panel is a DataFrame of DAILY CHANGES SUPPLIED BY THE CALLER "
            "with one column per series. This module fetches nothing, so it "
            "cannot verify the panel really holds changes (see "
            "`_pca_panel_suspicion`, which only scores the shape), nor the "
            "definition or vintage of any column.",
            "All columns come from the same panel, so `source_independence_count` "
            "is 0 — the components are a description of ONE dataset, not a "
            "relationship corroborated across independent sources (Module 13).",
        ],
        limitations=_pca_limitations(),
        decision_relevance=(
            "Section 15.20-F's factor-extraction step. It is the dimensional "
            "reduction a multi-series view is built on — how many independent "
            "moves actually drive a panel, and what each is made of — and its "
            "published ratios are the share-of-variance evidence a factor thesis "
            "cites. It supersedes nothing: it describes structure in a panel "
            "rather than testing a hypothesis about it, so it PAIRS with the "
            "hypothesis tests (a regression on the extracted components still "
            "needs its mechanism gate)."
        ),
        decision_prohibition=[
            "MUST NOT label the components level/slope/curvature, or any other "
            "name. The labels are an interpretation of the loadings, and an "
            "interpretation is a claim about the data — a PC1 with same-sign "
            "loadings is consistent with a level shock and with many other "
            "things. Read the loadings and make the claim yourself, in the "
            "thesis, where it can be argued with (Section 15.20-F).",
            "MUST NOT be used as a signal on its own. A principal component is a "
            "direction of maximum variance, not a forecast and not a value "
            "signal: the largest variance can be the largest NOISE. Section "
            "18.3's discipline — mechanism first — applies here as it does to "
            "every other function in this module.",
            "MUST NOT be read across two PCA fits as though the components were "
            "the same factor. Component 1 in one window is defined by that "
            "window's covariance; after a regime change the ordering and the "
            "loadings both move, and comparing 'PC1 then' with 'PC1 now' without "
            "comparing the loadings is comparing two different objects. This is "
            "the same backward-looking hazard test_cointegration warns about.",
        ],
    )


def _prepare_panel(panel: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Validate the daily-change panel, or raise. Every check a refusal.

    Mirrors ``_prepare_observations``' discipline for the same reason: dropping
    a row or a column to make a bad panel fit changes ``n_obs`` (and, here, the
    *number of series*, which changes every loading) without recording it, and
    the result would then be a claim about a panel the caller never supplied.

    Returns the float64 matrix and the column names separately rather than a
    single frame, because the decomposition needs the array and the reporting
    needs the names, and reading names off a numpy array is how a labelling
    error gets in.
    """
    if not isinstance(panel, pd.DataFrame):
        raise TypeError(f"daily_changes must be a pandas DataFrame, got {type(panel).__name__}.")

    if panel.shape[1] == 0:
        raise ValueError(
            "daily_changes must have at least one series column; it has none. A "
            "panel with no columns has no covariance to decompose."
        )
    # Two series are the minimum for a component that differs from either one:
    # the PCA of a single series returns that series as PC1 with a ratio of
    # 1.0, which is arithmetically correct and carries no information. Refused
    # with the reason rather than reported as a degenerate result.
    if panel.shape[1] < 2:
        raise ValueError(
            f"daily_changes has {panel.shape[1]} series, but a principal component "
            f"of a single series is that series — one component with a ratio of 1.0 "
            f"and nothing decomposed. Supply at least two series."
        )

    # Duplicated names, checked for the same reason `_prepare_observations`
    # checks them: the loadings map is keyed by series name, so two series
    # sharing a name would silently overwrite one another and the published
    # panel would have fewer series than the caller supplied.
    duplicated = sorted({str(name) for name in panel.columns[panel.columns.duplicated()]})
    if duplicated:
        raise ValueError(
            f"daily_changes has duplicate column name(s) {duplicated}. The loadings "
            f"are keyed by series name, so one series would overwrite another and "
            f"the result would describe fewer series than you supplied. Rename them."
        )

    for name in panel.columns:
        if is_bool_dtype(panel[name].dtype) or not is_numeric_dtype(panel[name].dtype):
            raise ValueError(
                f"Series {name!r} must be numeric, got dtype {panel[name].dtype}. "
                f"Encode or drop categorical columns explicitly so the panel you "
                f"decompose is the panel you intend."
            )

    values = panel.astype("float64").to_numpy()

    if not bool(np.isfinite(values).all()):
        offending = [
            str(name)
            for name, column in zip(panel.columns, values.T, strict=True)
            if not bool(np.isfinite(column).all())
        ]
        raise ValueError(
            f"daily_changes contains non-finite values (NaN or inf) in {offending}. "
            f"A single NaN propagates into every eigenvalue and every loading, so the "
            f"whole result would be NaN and would render as a blank chart rather than "
            f"as an error. Clean or impute explicitly."
        )

    minimum_observations = float(get_settings().econometrics.pca_min_observations.value)
    if len(values) < minimum_observations:
        raise ValueError(
            f"{len(values)} observations is below the configured floor of "
            f"{minimum_observations:.0f} (econometrics.pca_min_observations). A "
            f"covariance estimated on very few rows is dominated by sampling noise, "
            f"and the leading eigenvalue of a noise covariance is spuriously large "
            f"(the Marchenko-Pastur effect), so a small panel reports a confident PC1 "
            f"that is mostly estimation error."
        )

    return values, [str(name) for name in panel.columns]


def _validate_component_count(n_components: int, n_variables: int) -> int:
    """Validate the requested component count against the panel's width.

    Checked here rather than left to the slice, because both failure modes are
    silent: asking for more components than exist yields a shorter list than the
    caller's loop expects, and asking for fewer than one yields an empty one —
    and in both cases the surrounding ``ModelResult`` is still well-formed, so
    the caller gets a complete-looking object describing a request that could
    not be honoured (silent failure #2).
    """
    if isinstance(n_components, bool) or not isinstance(n_components, int):
        raise TypeError(
            f"n_components must be an int, got {type(n_components).__name__}. A "
            f"float would be silently truncated by the index arithmetic."
        )
    if n_components < 1:
        raise ValueError(
            f"n_components must be at least 1, got {n_components}. Zero components "
            f"is a request for no output, which is not a PCA."
        )
    if n_components > n_variables:
        raise ValueError(
            f"n_components={n_components} exceeds the number of series "
            f"({n_variables}), which is the maximum number of components a panel of "
            f"that width can have. Asking for {n_components} would return a shorter "
            f"list than you asked for without saying so."
        )
    return n_components


def _refuse_constant_series(panel: np.ndarray, column_names: list[str]) -> None:
    """Refuse any series with no variation, on EVERY route.

    **A MEASURED near-miss, and the reason this is its own function.** The
    obvious test — ``series.std() == 0.0`` — does not fire. Summing a constant
    column's squared deviations in floating point yields a tiny **non-zero**
    spread: measured ``8.9e-16`` for a column of ``4.2`` repeated 200 times. Two
    separate guards were then defeated by the same residue:

    * On the **correlation** route, dividing by that residue scales the column to
      ``~1e16``, which swamps ``matrix_rank``'s relative tolerance — so the rank
      check does not catch it either. Measured: the "constant" series came back
      with a loading of ``-0.0`` and a variance ratio of ``0.0`` while the result
      still claimed ``n_variables = 4`` in its context string.
    * On the **covariance** route there is no division, but the same relative
      tolerance means a *small* constant column is invisible beside the others.
      Measured on the same ``4.2`` column: the rank check passed and the panel
      decomposed as though it had four independent directions.

    Both are this project's signature failure shape — a wrong answer that looks
    complete — and both are caught by comparing each series' spread against a
    tolerance *relative to that series' own scale*, which is what "constant"
    actually means for floating-point data.

    **The relative/absolute distinction is load-bearing, and the sweep proved
    it.** M66 replaces the relative tolerance above with a fixed one
    (``eps * 100 = 2.22e-14``) and it **SURVIVED** the first run of the
    mutation suite: every constant in the tests at that time (``4.2``, ``0.0``,
    ``-3.0``) leaves a residue small enough that a fixed epsilon catches it too,
    so no test could tell the two apart. Measured 2026-09-23, the residue is
    **not monotone in magnitude** — it depends on how ``c - mean`` rounds at
    that scale — so the magnitudes that defeat a fixed epsilon are specific
    ones and have to be found by measurement rather than by choosing "large"
    values:

        const 4.2      residue 7.1e-14   above 2.22e-14 -> defeats the fixed test
        const 271.83   residue 1.1e-13   clearly above  -> defeats it
        const 314.16   residue 4.3e-14   above          -> defeats it
        const 1e6      residue exactly 0               -> does NOT defeat it

    ``test_the_constant_refusal_is_scale_relative_not_absolute`` now carries the
    magnitudes that are **proven** to kill M66 (verified by applying the mutant
    by hand and watching that test fail), which is what makes M66 killed rather
    than merely survived. The lesson generalises: a guard whose tolerance is
    *relative* can only be proven relative by a case where the relative and
    absolute answers DIVERGE — agreeing on the easy magnitudes proves nothing.
    """
    scale = np.abs(panel).max(axis=0)
    deviations = panel.std(axis=0, ddof=1)
    # `np.maximum(scale, 1.0)` keeps the comparison defined for an all-zero
    # column, whose scale is 0: it has deviations of exactly 0.0 and is caught
    # by the same test rather than needing a special case.
    tolerance = np.finfo(float).eps * np.maximum(scale, 1.0) * 100.0
    # `<= tolerance` is NOT redundant with `deviations == 0.0`, and that is the
    # whole point of this function: a bare `std == 0` test does not fire on a
    # constant column (measured 8.9e-16 for 4.2 repeated 200 times).
    constant = [index for index in range(panel.shape[1]) if deviations[index] <= tolerance[index]]
    if constant:
        names = [column_names[index] for index in constant]
        raise ValueError(
            f"Series {names} are constant across the sample (their standard "
            f"deviation is at or below floating-point noise for their own scale), so "
            f"they carry no variation to decompose. A bare `std == 0` test does NOT "
            f"catch this: summing a constant column's deviations leaves a tiny "
            f"non-zero residue (measured 8.9e-16), which defeats the correlation "
            f"route's division AND the rank check's relative tolerance — the series "
            f"would be decomposed as an independent direction and return a loading of "
            f"-0.0. Remove it."
        )


def _standardise_panel(
    panel: np.ndarray, column_names: list[str], standardisation: str
) -> np.ndarray:
    """Apply the configured standardisation, or raise on an unknown choice.

    The choice is consequential and therefore explicit. Measured 2026-09-23 on a
    five-tenor panel with the front end moving most (the normal shape of a yield
    curve): the covariance route and the correlation route disagree by **0.28**
    on PC1's loadings and **invert their ordering** — covariance puts the 3mo
    first (`-0.589` vs the 30yr's `-0.200`), correlation puts the 5yr first. Both
    are legitimate answers to different questions, so the route is published on
    the result and a reader is never left to assume which one they are holding.

    ``column_names`` is threaded in purely for the error messages: the caller's
    labels are what make a refusal actionable, and reading them off the array is
    impossible.
    """
    if standardisation == "covariance":
        return panel
    if standardisation == "correlation":
        means = panel.mean(axis=0)
        deviations = panel.std(axis=0, ddof=1)
        return (panel - means) / deviations
    raise ValueError(
        f"Unknown pca_standardisation {standardisation!r}. Permitted values are "
        f"'covariance' (decompose the raw second moments) and 'correlation' "
        f"(standardise each series to unit variance first)."
    )


def _decompose(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Eigendecompose the covariance, returning eigenvalues and loadings in order.

    ``np.linalg.eigh`` rather than ``eig``: the covariance is symmetric by
    construction, and ``eigh`` exploits that to return **real** eigenvalues and
    an orthonormal basis. ``eig`` on the same input can return complex values
    with tiny imaginary parts, which is how a caller ends up publishing a
    complex "variance" — the same class of leak ``coint_johansen`` was found to
    produce (M49/M50).

    The eigenvalues come back in ASCENDING order from LAPACK, so they are
    reversed here; the loadings columns are reordered with them by the same
    index array, because reordering one without the other silently pairs each
    variance with the wrong factor — a wrong answer that looks complete.
    """
    covariance = np.cov(matrix, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    return eigenvalues[order], eigenvectors[:, order]


def _apply_sign_rule(loadings: np.ndarray) -> np.ndarray:
    """Make the largest-magnitude loading in each component positive.

    sklearn's ``svd_flip`` convention, reproduced so this function's output is
    comparable with sklearn's and reproducible across LAPACK builds. The sign of
    an eigenvector is arbitrary — ``v`` and ``-v`` describe the same direction —
    so without a rule the same panel can produce ``[1, 1, 1]`` or ``[-1, -1, -1]``
    on two machines, and a chart of the second reads as the opposite factor.

    ``argmax`` resolves a tied maximum by **position** (the first occurrence),
    which is a determinism hazard in principle and stable in practice: it is the
    same choice on every run for a given input, so the convention is at least
    reproducible. Measured on an all-equal vector ``[-0.5, -0.5, -0.5, -0.5]``:
    the rule flips all four to positive, and on a tie with mixed signs
    ``[1, -1, 0.1, 0]`` it leaves them alone because index 0 already wins.
    """
    signed = loadings.copy()
    for position in range(signed.shape[1]):
        component = signed[:, position]
        pivot = int(np.argmax(np.abs(component)))
        if component[pivot] < 0.0:
            signed[:, position] = -component
    return signed


def _pca_value(
    *,
    eigenvalues: np.ndarray,
    ratios: np.ndarray,
    loadings: np.ndarray,
    column_names: list[str],
    n_obs: int,
    n_variables: int,
    components: int,
    standardisation: str,
) -> dict[str, object]:
    """Assemble the published ``value`` — the report Section 15.20-F demands.

    The dict is deliberately mixed-type, as ``_cointegration_value``'s is: the
    payload is a list of floats, a mapping of mappings, and ints, because the
    five things the specification asks for are structurally different objects.

    ``loadings`` is published as ``{component: {series: loading}}`` — nested and
    named — rather than as a bare matrix. A matrix's rows and columns are
    positional, so a consumer that transposes it (or reads it column-major)
    silently gets each series' loadings on the wrong component and a chart that
    looks entirely plausible. Naming both axes makes the transposition
    unrepresentable.
    """
    payload: dict[str, object] = {
        # Every eigenvalue is published, not only the requested components: the
        # ratios are only interpretable against the full spectrum (the tail is
        # what tells a reader the panel is nearly rank-deficient), and truncating
        # it would hide the evidence for the near-zero warning.
        "eigenvalues": [round(float(value), 12) for value in eigenvalues],
        "explained_variance_ratios": [round(float(value), 12) for value in ratios],
        "cumulative_explained_variance": [
            round(float(ratios[: position + 1].sum()), 12) for position in range(len(ratios))
        ],
        "loadings": {
            f"PC{position + 1}": {
                name: round(float(loadings[index, position]), 12)
                for index, name in enumerate(column_names)
            }
            for position in range(len(column_names))
        },
        "n_components": components,
        "n_components_explained_variance": round(float(ratios[:components].sum()), 12),
        "n_obs": n_obs,
        "n_variables": n_variables,
        "standardisation": standardisation,
        # The convention is published with the numbers it governs, because a
        # loadings sign is not self-describing: a reader who does not know the
        # rule cannot tell a level factor from its negation.
        "sign_rule": "largest_absolute_loading_positive (sklearn svd_flip convention)",
    }
    return payload


def _pca_warnings(
    *,
    eigenvalues: np.ndarray,
    ratios: np.ndarray,
    n_obs: int,
    panel: np.ndarray,
    standardisation: str,
    near_zero_threshold: float,
) -> list[str]:
    """Conditions of THIS run, as distinct from the standing limitations.

    Every warning here is reachable and mutation-tested. The near-zero check is
    the one that earns its place: a component whose variance is numerically zero
    is reported with a ratio near 0.0, and a consumer reading "PC4 explains
    0.0001% of variance" may take that as a weak factor rather than as
    "this panel has fewer independent directions than I supplied series".
    """
    warnings_: list[str] = []

    # The tail of the spectrum. A ratio at or below the tolerance means the
    # direction carries no variation at all -- which on a yield panel is either
    # a redundant tenor or a genuine structural fact (two tenors pegged to each
    # other), and both are worth saying out loud rather than leaving the reader
    # to notice a small number.
    tail = [
        (position + 1, float(ratio))
        for position, ratio in enumerate(ratios)
        if float(ratio) <= near_zero_threshold
    ]
    for position, ratio in tail:
        warnings_.append(
            f"PC{position} explains {ratio:.3e} of the panel's variance, at or below "
            f"the configured near-zero tolerance ({near_zero_threshold:g}). The panel "
            f"has fewer independent directions of variation than it has series — a "
            f"tenor may be redundant with another, or the sample may be too short for "
            f"the number of series. This component is a numerical residual, not a "
            f"factor."
        )

    # The boundary is a RATIO of rows to columns, and it is MEASURED rather than
    # felt. Simulating pure noise (so the true PC1 share is exactly 1/k = 0.20
    # for five columns) over 500 draws per length, recorded 2026-09-23: the
    # sample PC1 share sits at a median 0.396 on 10 rows, 0.355 on 15, 0.335 on
    # 20, 0.320 on 25, 0.308 on 30, 0.282 on 50, 0.275 on 60 and 0.235 on 260 --
    # i.e. the noise floor is still visibly above the asymptote at 60 rows and
    # only settles past ~200.
    #
    # **Ten rows per series is the boundary, and this warning is UNREACHABLE for
    # a five-column panel at the configured floor.** That is stated rather than
    # hidden: `pca_min_observations` is 60, so a five-tenor curve has at least 12
    # rows per series, and `60 < 10 * 5` is false. The inflation at twelve rows
    # per series is +0.075 above the asymptote -- real, but small enough that the
    # panel is usable, so the floor is left where it is and the constraint is
    # recorded in `_pca_limitations` instead of being papered over with a
    # threshold that fires on a legal panel. The warning is live for a WIDER
    # panel, which is where the ratio actually gets thin: 20 series need 200 rows
    # to clear it, and 60 rows is well inside the region.
    n_variables = len(eigenvalues)
    if n_obs < _THIN_PANEL_ROWS_PER_SERIES * n_variables:
        warnings_.append(
            f"Only {n_obs} observations for {n_variables} series "
            f"({n_obs / n_variables:.1f} rows per series, below the "
            f"{_THIN_PANEL_ROWS_PER_SERIES}-per-series boundary). The leading "
            f"eigenvalue of a sample covariance is biased UPWARD when the ratio of "
            f"rows to columns is small (the Marchenko-Pastur effect): on pure noise "
            f"with this many columns, PC1's share is expected near "
            f"{_expected_noise_pc1_share(n_obs, n_variables):.3f} rather than the "
            f"asymptotic {1.0 / n_variables:.3f}, so PC1's published share is partly "
            f"estimation error. Treat the ratios as an upper bound and extend the "
            f"window before relying on them."
        )

    # The levels-instead-of-changes hazard, made visible. See
    # `_pca_panel_suspicion`, which decides the condition; the wording lives here
    # with the other warnings so every message a caller can receive is in one
    # place.
    if float(ratios[0]) > 0.95:
        warnings_.append(
            f"PC1 explains {float(ratios[0]):.1%} of the variance. On a panel of "
            f"daily changes that is high enough to be worth checking the input is "
            f"changes and not LEVELS: an un-differenced level panel is dominated by "
            f"its time trend, and its PC1 is that trend rather than a factor, "
            f"routinely clearing 95%. The inspection is the caller's; this function "
            f"cannot distinguish the two cases."
        )

    if standardisation == "covariance" and n_variables > 1:
        scales = panel.std(axis=0, ddof=1)
        if float(scales.max()) > 10.0 * float(scales.min()):
            warnings_.append(
                f"The series' standard deviations span a factor of "
                f"{float(scales.max() / scales.min()):.1f} (max {float(scales.max()):.4g}, "
                f"min {float(scales.min()):.4g}) and the covariance route weights each "
                f"series by its own variance. On a panel with this much scale "
                f"dispersion, PC1 is substantially 'which series is noisiest' rather "
                f"than a common factor. Use the correlation route if equal weighting "
                f"is what you intend."
            )

    return warnings_


def _pca_panel_suspicion(panel: np.ndarray) -> str | None:
    """A warning when the panel's own shape suggests it is levels, not changes.

    Section 15.20-F's instruction — *daily changes, never raw levels* — is the
    one part of the contract this function cannot verify. But it can notice the
    signature: a level panel has a near-unit-root autocorrelation, so the lag-1
    autocorrelation of its columns sits close to 1.0, while a genuine change
    series is close to 0 (yield changes are mildly negatively autocorrelated, if
    anything).

    **The cutoff is length-aware, and it has to be.** A fixed threshold was tried
    first and measured against the wrong population: at ``0.95`` a *level* series
    is missed **88.6%** of the time at ``n = 60`` and **63.6%** at ``n = 100`` —
    i.e. the naive threshold fails exactly where a caller is most likely to have
    grabbed levels by mistake, and only works past ~500 rows. Measured over 2 000
    simulated walks at each length, the boundary ``1 - 2.5/sqrt(n)`` separates the
    two populations with a **0.00% false-positive rate on changes at every
    length** and a **0.00-1.25% false-negative rate on levels** (worst case
    ``n = 60``). The derivation is the one the arithmetic suggests: the sample
    lag-1 of a random walk has a downward bias of order ``1/sqrt(n)``, so the
    boundary has to move with the sample rather than sit at a constant.

    This is a **heuristic on the shape of the input**, not a test of the caller's
    intent, and the wording says so. It returns ``None`` when the panel looks
    like changes, so the warning is absent rather than asserting the input is
    correct.
    """
    n_obs = panel.shape[0]
    if n_obs < 3:
        return None
    # The measured boundary. `n_obs` is at least the configured
    # `pca_min_observations` (60) by this point, so the square root is safe and
    # the threshold is comfortably inside (0, 1).
    cutoff = 1.0 - 2.5 / math.sqrt(n_obs)
    for position in range(panel.shape[1]):
        column = panel[:, position]
        centred = column - column.mean()
        denominator = float((centred * centred).sum())
        if denominator == 0.0:
            continue
        lag_one = float((centred[:-1] * centred[1:]).sum()) / denominator
        if lag_one > cutoff:
            return (
                f"Column {position + 1} has a lag-1 autocorrelation of {lag_one:.4f}, "
                f"above the {cutoff:.4f} boundary for {n_obs} observations, which is "
                f"the signature of a LEVEL series rather than a series of changes "
                f"(yield changes are close to serially uncorrelated). Check that "
                f"`daily_changes` really holds differences: this function cannot "
                f"verify it, and a level panel's components describe a time trend."
            )
    return None


def _expected_noise_pc1_share(n_obs: int, n_variables: int) -> float:
    """The PC1 share a PURE-NOISE panel of this shape produces, MEASURED.

    This exists so the thin-panel warning can print a number instead of the word
    "biased": a reader told "PC1 is inflated here" has no way to judge by how
    much, and *"the noise floor on this panel is 0.28"* is a fact they can check
    the reported 0.41 against.

    **The value is interpolated through measurements, not derived from a law.**
    Two candidates were tried and both were rejected for being *wrong in a
    specific direction*:

    * The **Marchenko-Pastur** estimator ``(1 + sqrt(k/n))**2 / k`` is the
      asymptotic *upper edge* of the largest eigenvalue's support, not its
      median — measured against five columns it predicts 0.450 where the median
      is 0.335. Publishing it would have **overstated** the bias by 0.11, which
      is the opposite of the error a disclosure should make.
    * A **least-squares fit** of the form ``1/k + a*(k/n)`` through the same
      points under-predicts every one of them by ~0.03, so it is not the
      measured quantity either.

    So the numbers below ARE the measurement. Each is the median PC1 share of
    500 standardised pure-noise draws with that many rows and columns (recorded
    2026-09-23), and a value between two table entries is linearly interpolated.
    Outside the table the nearest entry is used at the short end and the
    asymptotic ``1/k`` at the long end, which is where the measured values are
    already converging (0.235 at 260 rows against an asymptote of 0.200).

    The table is for the **column count it was measured at**. A panel with a
    different width falls back to the asymptotic share, because inventing a
    scaling law from one column count is the error this function exists to
    avoid.
    """
    if n_variables != _NOISE_FLOOR_COLUMNS:
        return 1.0 / float(n_variables)

    points = _NOISE_FLOOR_PC1_SHARE
    if n_obs <= points[0][0]:
        return points[0][1]
    if n_obs >= points[-1][0]:
        # Past the last measurement the floor has nearly reached 1/k, and the
        # measured 0.235 at 260 rows is already close to it; interpolating
        # toward the asymptote is a shorter extrapolation than any fitted line.
        return 1.0 / float(n_variables)

    for (left_n, left_share), (right_n, right_share) in zip(points, points[1:], strict=False):
        if left_n <= n_obs <= right_n:
            weight = (n_obs - left_n) / (right_n - left_n)
            return left_share + weight * (right_share - left_share)
    # Unreachable: the branches above cover every input. Kept so the function has
    # no implicit `None` return, which would surface as a formatting error inside
    # a warning string rather than as a refusal.
    return 1.0 / float(n_variables)


#: Rows-per-series below which the Marchenko-Pastur inflation of PC1 is disclosed.
#: Measured; see the comment at its use in `_pca_warnings` for the numbers and
#: for why this warning cannot fire on a five-column panel at the config floor.
_THIN_PANEL_ROWS_PER_SERIES = 10

#: The column count `_NOISE_FLOOR_PC1_SHARE` was measured at. A panel of a
#: different width gets the asymptotic share instead of a scaled guess.
_NOISE_FLOOR_COLUMNS = 5

#: ``(n_obs, median PC1 share)`` for standardised PURE-NOISE panels of five
#: columns, each entry the median of 500 draws. Measured 2026-09-23. The
#: asymptote is ``1/5 = 0.200``, so the distance from it IS the small-sample
#: inflation a reader needs to discount.
_NOISE_FLOOR_PC1_SHARE: tuple[tuple[int, float], ...] = (
    (10, 0.3958),
    (15, 0.3543),
    (20, 0.3349),
    (25, 0.3199),
    (30, 0.3083),
    (50, 0.2815),
    (60, 0.2750),
    (100, 0.2564),
    (260, 0.2346),
)


def _pca_limitations() -> list[str]:
    """What a PCA cannot tell you, on every call.

    Standing caveats, distinct from ``warnings`` (a condition of this run). The
    specification's auto-labelling prohibition lives in ``decision_prohibition``
    instead: it is a restriction on use, not a limit on what the numbers say.
    """
    return [
        "PRINCIPAL COMPONENTS ARE NOT ECONOMIC FACTORS. A component is a "
        "direction of maximum variance in THIS sample. Nothing in the "
        "computation identifies it as a level, a slope, a growth shock or "
        "anything else — the loading pattern is a description of the direction, "
        "and naming it is a separate claim the analyst makes. Two panels with "
        "the same components can have entirely different economic causes.",
        "COMPONENTS ARE SAMPLE-SPECIFIC AND NOT COMPARABLE ACROSS WINDOWS. The "
        "basis is the sample covariance, so it changes when the sample changes; "
        "the ordering can swap and the loadings rotate between two windows of "
        "the same series. Comparing 'PC1 then' with 'PC1 now' without comparing "
        "the loadings compares different objects.",
        "THE DECOMPOSITION ASSUMES LINEARITY AND A SINGLE REGIME. PCA finds "
        "linear directions; a relationship that is nonlinear, or one that "
        "differs across regimes, is not recovered. This is the same "
        "backward-looking hazard `test_cointegration` warns about, stated here "
        "as a standing limit because it holds on every call.",
        "THE EIGENVALUES ARE ESTIMATED, NOT OBSERVED, AND ARE BIASED IN SMALL "
        "SAMPLES. The sample covariance's leading eigenvalue is inflated when "
        "the number of rows is not large relative to the number of columns, so "
        "even a matrix of pure noise reports a confident-looking PC1. The "
        "row-to-column warning fires when the ratio is thin; it cannot correct "
        "the bias.",
        "VARIANTS OF THE INPUT CHANGE THE ANSWER BY CONSTRUCTION. The "
        "standardisation choice and the sample window both shape the components, "
        "and neither is uniquely correct. The result names the standardisation "
        "it used; it does not and cannot privilege it over the alternative.",
        "THE SMALL-SAMPLE DISCLOSURE DOES NOT COVER A NARROW PANEL. The "
        "Marchenko-Pastur warning fires below ten rows per series, but "
        "pca_min_observations (60) admits a five-tenor panel at twelve rows per "
        "series, where the measured noise floor is +0.075 above the 1/k "
        "asymptote -- real but modest. So a five-tenor curve can reach this "
        "function with the inflation present and no warning: the floor, not the "
        "disclosure, is what governs that case. Measured 2026-09-23.",
    ]


def _pca_choices_calibrated() -> bool:
    """Whether the threshold shaping ``compute_pca``'s DISCLOSURE is calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` (negated by the
    caller).

    Named for the leaf it reads, as :func:`_r_squared_floor_is_calibrated` is,
    because the name is load-bearing: a reader who added a second illustrative
    PCA threshold would otherwise assume this helper already covered it.

    The two candidates are not equally priceable, and the distinction matters.
    ``pca_near_zero_tolerance`` is a genuine placeholder — a variance ratio is
    "numerically zero" only relative to a threshold nobody has calibrated — so it
    is a ``CalibratedValue`` and it costs confidence. ``pca_standardisation`` is
    a **choice between two well-defined quantities**, not a quantity with a
    truth value, so wrapping it in the envelope would pose a question the
    envelope cannot answer ("is 'correlation' a fact, a convention, or a
    placeholder?"). It is therefore a plain ``str`` leaf, and the reasoning that
    would have gone in a ``note`` lives in ``settings.yaml`` beside it — the same
    split the module's sibling leaves already use.

    The threshold is ``uncalibrated_illustrative`` today, so this returns
    ``False`` and the caller applies the penalty.
    """
    return get_settings().is_calibrated("econometrics.pca_near_zero_tolerance")


# ---------------------------------------------------------------------------
# Kalman filter (Section 15.20-F) — the module's unobservable-state estimator
# ---------------------------------------------------------------------------

#: The three observation equations the table below can build. The design matrix
#: is the only part of a specification that is not fixed by the state dimension,
#: so it is named here rather than inferred from the panel's width at the point
#: of use.
_KALMAN_DESIGN_UNIT = "unit"
_KALMAN_DESIGN_LEVEL = "level"
_KALMAN_DESIGN_REGRESSOR = "regressor"


class _KalmanSpec(NamedTuple):
    """One supported state-space specification, held as DATA rather than as branches.

    ``transition`` and ``state_names`` fix the state equation; ``design_kind``
    fixes the observation equation. Keeping the three specifications in ONE
    table is what lets the refusal enumerate the admissible set from the same
    object the constructor reads — a threshold whose attainable values are never
    enumerated is how a dead branch survives (the D-047 lesson).

    A ``NamedTuple`` rather than a Pydantic model because this never crosses an
    I/O boundary and never needs validating; the strict-typing value is that a
    reader cannot pass a ``str`` where a matrix belongs without mypy saying so.
    """

    name: str
    state_names: tuple[str, ...]
    transition: tuple[tuple[float, ...], ...]
    variance_names: tuple[str, ...]
    design_kind: str


#: The admissible ``(n_columns, state_dim)`` space, and ONLY this space. Each
#: entry is one of Section 15.20-F's three named uses of this function:
#:
#: * ``local_level`` — a latent LEVEL: r*, or any slow-moving unobservable read
#:   through a noisy proxy. ``y_t = mu_t + eps_t``, ``mu_t = mu_{t-1} + eta_t``.
#: * ``local_linear_trend`` — a latent level that is ALLOWED to drift:
#:   potential GDP, whose level has a trend the level-only model must otherwise
#:   absorb into its own variance (measured: a deterministic trend drove
#:   ``sigma2.level`` to 1.09 on a series whose true level variance was 0.25).
#:   ``F = [[1, 1], [0, 1]]`` — the slope feeds the level.
#: * ``time_varying_hedge_ratio`` — a latent regression COEFFICIENT, which is
#:   the formal machinery for a cointegrated pair's time-varying hedge ratio.
#:   ``y_t = beta_t * x_t + eps_t``, ``beta_t = beta_{t-1} + eta_t``.
#:
#: Deliberately ABSENT: a time-varying intercept (``alpha_t`` beside ``beta_t``).
#: Section 15.20-F does not name it, and a configuration nothing specifies is a
#: configuration nothing can be held to. A caller who needs one is asking for a
#: fourth specification, which is a decision rather than a parameter.
_KALMAN_SPECS: dict[tuple[int, int], _KalmanSpec] = {
    (1, 1): _KalmanSpec(
        name="local_level",
        state_names=("level",),
        transition=((1.0,),),
        variance_names=("level",),
        design_kind=_KALMAN_DESIGN_UNIT,
    ),
    (1, 2): _KalmanSpec(
        name="local_linear_trend",
        state_names=("level", "slope"),
        transition=((1.0, 1.0), (0.0, 1.0)),
        variance_names=("level", "slope"),
        design_kind=_KALMAN_DESIGN_LEVEL,
    ),
    (2, 1): _KalmanSpec(
        name="time_varying_hedge_ratio",
        state_names=("beta",),
        transition=((1.0,),),
        variance_names=("beta",),
        design_kind=_KALMAN_DESIGN_REGRESSOR,
    ),
}


class _KalmanStateModel(MLEModel):
    """A linear Gaussian state-space model with EXPLICIT matrices.

    Section 15.18 gives this module one ordering that governs everything in it —
    mechanism first, statistics second — and for a Kalman filter the mechanism
    *is* the state-space specification. So the matrices are written down here
    and published on every result, rather than inferred by a convenience class:
    a reader can check the model against the economics, and a test can assert
    the matrix that was actually filtered.

    **Why not ``UnobservedComponents``.** The structural convenience class was
    probed first and REJECTED on measurement, twice, for two different silent
    failures — see :func:`kalman_latent_state`'s docstring for the numbers. Both
    returned a complete-looking result that described a different model from the
    one the caller asked for. Explicit matrices remove the class of defect
    rather than one instance of it.

    **Why ``approximate_diffuse`` and not ``diffuse``.** Measured 2026-09-23:
    the exact-diffuse route REMOVES the diffuse component from
    ``filtered_state_cov``, so a state the first observation does not identify
    reports a standard error of exactly ``0.0``. On a local linear trend the
    slope came back as ``0.0 +- 0.0`` — the observation reads ``[1, 0]`` and
    carries no slope information — where the honest answer is the declared
    prior's scale. The same fit under ``approximate_diffuse`` reported
    ``1000.0``, which is ``sqrt(kappa)``. The filtered states were identical
    between the two routes; only the published uncertainty differed, which is
    exactly the shape of failure this project treats as its signature.
    """

    def __init__(
        self,
        endog: np.ndarray,
        *,
        spec: _KalmanSpec,
        design: np.ndarray,
        diffuse_scale: float,
    ) -> None:
        k_states = len(spec.state_names)
        super().__init__(endog, k_states=k_states, k_posdef=k_states)
        self["design"] = design
        self["transition"] = np.array(spec.transition, dtype=float)
        self["selection"] = np.eye(k_states)
        self.ssm.initialize_approximate_diffuse(diffuse_scale)
        self._variance_names = spec.variance_names

    @property
    def param_names(self) -> list[str]:
        return [f"sigma2.{name}" for name in self._variance_names] + ["sigma2.irregular"]

    @property
    def start_params(self) -> list[float]:
        """All ones, because the optimizer works in the square-root space.

        A start of ``1.0`` is therefore a standard deviation of ``1.0`` for
        every variance, which is the only neutral choice available without
        reading the data — and reading the data here would make the fit depend
        on a quantity the caller never sees.
        """
        return [1.0] * (len(self._variance_names) + 1)

    def transform_params(self, unconstrained: np.ndarray) -> np.ndarray:
        """Square the optimizer's parameters so every variance stays positive.

        NOT optional. ``MLEModel``'s base implementation is the IDENTITY, so
        without this the optimizer is free to explore negative variances and
        does: measured 2026-09-23, a local linear trend fitted with the base
        ``untransform_params`` returned ``sigma2.slope = -3.24`` and a
        standard-error array of ``nan`` from the second observation onward.
        Every published field was then ``nan`` while the fit itself reported no
        error. This is the "declared but not enforced" shape in the one place
        where the library cannot supply the constraint for you.
        """
        return np.asarray(unconstrained) ** 2

    def untransform_params(self, constrained: np.ndarray) -> np.ndarray:
        """The inverse of :meth:`transform_params`, used to place ``start_params``."""
        return np.asarray(constrained) ** 0.5

    def update(self, params: Any, **kwargs: Any) -> np.ndarray:
        """Write the estimated variances into the state and observation covariances.

        ``fit`` calls this with params that are ALREADY transformed (the base
        signature's ``transformed=True`` default), so no transform is applied
        here — ``super().update`` is called for its fixed-parameter handling and
        to keep one definition of what "the current params" means.
        """
        constrained = np.asarray(super().update(params, **kwargs))
        for index in range(len(self._variance_names)):
            self["state_cov", index, index] = constrained[index]
        self["obs_cov", 0, 0] = constrained[-1]
        return constrained


def kalman_latent_state(observations: pd.DataFrame, state_dim: int = 1) -> ModelResult:
    """Filter an unobservable state out of a noisy series, with its uncertainty band.

    Section 15.20-F's signature. The specification names three uses — ``r*``,
    potential GDP, and a cointegrated pair's time-varying hedge ratio — and all
    three are latent states of a linear Gaussian state-space model, so all three
    are one mechanism with three specifications:

    ==================  ==========  =========================  =====================
    ``observations``    ``state``   specification              Section 15.20-F use
    ==================  ==========  =========================  =====================
    1 column            1           ``local_level``            r*, a latent level
    1 column            2           ``local_linear_trend``     potential GDP
    2 columns           1           ``time_varying_hedge_ratio`` hedge ratio
    ==================  ==========  =========================  =====================

    The state-space matrices are written out in :class:`_KalmanStateModel` and
    published as ``model_spec``, because the specification IS the mechanism and
    Section 15.18 requires the mechanism to be stated rather than implied. Any
    other combination is REFUSED with the admissible set named, so a caller
    cannot silently get a different model from the one they asked for.

    **1. The state is an ESTIMATE and its band is part of the answer, not
    decoration.** The specification is emphatic ("the filtered state is an
    estimate, never to be presented as observed truth"), and the band is what
    makes that operational: every published state carries a standard error and
    an interval derived from it, at a configured coverage. A state without its
    band would be a point estimate of a quantity nobody can observe.

    **2. FILTERED, not smoothed — and the difference is published.** The
    filtered state at ``t`` uses observations ``1..t``, which is what a real-time
    estimate may use. The smoothed state uses the whole sample and is therefore
    LOOK-AHEAD-BIASED for any decision taken at ``t``. The result publishes both
    and the measured revision between them, because a reader who does not know
    how much the estimate will be revised cannot judge whether to act on it.
    Measured 2026-09-23 on a 200-observation local level: the largest revision
    was 1.5x-3.0x the state's own median standard error, and for a local linear
    trend's SLOPE it ran 3.2x-27.1x. A slope estimated in real time is
    materially less trustworthy than its band alone suggests, and that is a
    measurement rather than a caveat.

    **3. Three silent-failure paths were found by probing ``statsmodels`` BEFORE
    this function was written, and every one of them returns a plausible,
    complete-looking result.** They are why the model is built from explicit
    matrices rather than from the structural convenience class:

    * **``UnobservedComponents(y, level=True)`` fits a DETERMINISTIC level, not
      a random walk.** ``stochastic_level`` defaults to ``False``, so the "level"
      is a constant and the function reports the sample mean with a band
      narrower than any observation — ``102.33 +- 0.18`` on a random walk whose
      level moved over several units. ``level='rwalk'`` is the other half of the
      trap: it drops the irregular component, so the state equals the
      observation and the band collapses to exactly ``0.0``. Measured both.
    * **``UnobservedComponents(..., mle_regression=False)`` does NOT give a
      time-varying coefficient.** The coefficient's process variance is not
      estimated, so its state covariance is ``[[0.]]`` and the filter returns a
      RECURSIVE OLS estimate that converges to the full-sample constant.
      Measured on a series with a genuinely drifting beta: the reported beta at
      the final observation was ``0.4793`` against a true ``0.4267`` — and
      ``0.4793`` is exactly the full-sample OLS coefficient, with a standard
      error of ``0.0023`` that makes the wrong answer look precise.
    * **A missing parameter transform yields NEGATIVE variances.** See
      :meth:`_KalmanStateModel.transform_params`: the base implementation is the
      identity, so an unconstrained fit returned ``sigma2.slope = -3.24`` and
      ``nan`` bands without raising.

    **4. A collapsed band is DISCLOSED, not warned about — and that was a
    measurement.** When the model estimates the observation-noise variance at
    (near) zero it is asserting that the data are noise-free, and the band then
    measures only the state's own innovation uncertainty and collapses: measured
    2026-09-23 on a random walk observed with ``sigma = 0.01``, a CONVERGED fit
    published ``102.8486 +- 0.0000377``. A warning was written for it and then
    REMOVED, because no threshold separates that case from a well-specified one.
    Measured over 10 seeds at each noise level, ``median(se)/median|state|``
    spanned ``3.1e-8`` to ``1.8e-3`` for noise-free samples — overlapping the
    well-specified range — and ``sigma2.irregular/var(y)`` spanned ``5.5e-12``
    to ``2.7e-2`` at zero noise and is specification-dependent besides, since a
    pair's ``var(y)`` is dominated by the regressor. **An unreliable warning is
    worse than a disclosed limitation**, because it teaches the reader to ignore
    it; so the behaviour is a ``limitation`` and ``sigma2.irregular`` is
    published for the reader to judge.

    **5. The series is NORMALISED before fitting, and the scale factors are
    published.** The state-space model is invariant under rescaling in exact
    arithmetic; the OPTIMIZER is not, because ``start_params`` is ``1.0`` while
    the likelihood is evaluated at the series' own magnitude. Measured
    2026-09-23, ONE local level fitted at six scales and reported as
    ``sigma2.level / scale**2``: ``0.3139`` at scale 1, ``0.3238`` at ``1e-3``,
    ``46.16`` at ``1e3``, ``2.663`` at ``1e6`` and ``0.02625`` at ``1e9`` — a
    **147x spread** between two fits of the same data. So the band, and every
    warning that reads it, depended on the caller's choice of UNITS: one
    degenerate series reported a relative band of ``2.05e-8`` in its own units
    and ``4.89e-2`` a hundred-fold scaled. Normalising first removes it
    entirely (measured after the fix: ``0.313922`` at every scale from ``1e-9``
    to ``1e9``), and ``series_scales`` / ``state_scales`` are published so a
    reader can convert between a normalised fit and their own units.

    Returns a ``ModelResult`` whose ``value`` carries the filtered path, its
    standard error, the band's bounds and coverage, the latest estimate with its
    band, the smoothed path's endpoint and the measured revision, the estimated
    variances, the fit's likelihood and information criteria, and the
    initialization used. ``direction`` is ``None``: a level is not a directional
    signal. ``confidence`` is priced with ``depends_on_unobservable=True`` —
    Section 21.4 item 13's exact case, since ``r*`` and potential GDP are
    unobservable by nature — and with the heuristic penalty when the disclosure
    thresholds are uncalibrated.
    """
    settings = get_settings()
    econometrics = settings.econometrics

    panel, column_names = _prepare_kalman_observations(observations)
    n_obs, n_columns = panel.shape
    spec = _select_kalman_model(n_columns, state_dim)

    # The series is normalised before fitting and converted back afterwards. The
    # model is scale-invariant and the OPTIMIZER is not, so without this the
    # published band depends on the caller's choice of units -- see
    # `_kalman_series_scales` for the measured 147x spread on one series.
    scale_y, scale_x = _kalman_series_scales(panel)
    normalised = panel.copy()
    normalised[:, 0] = panel[:, 0] / scale_y
    if n_columns > 1:
        normalised[:, 1] = panel[:, 1] / scale_x
    design = _kalman_design(spec, normalised)

    diffuse_scale = float(econometrics.kalman_diffuse_scale.value)
    model = _KalmanStateModel(
        normalised[:, 0],
        spec=spec,
        design=design,
        diffuse_scale=diffuse_scale,
    )

    # statsmodels emits its own `ConvergenceWarning` from inside `fit`. Captured
    # rather than allowed to escape, for the reason D-097 recorded about
    # `coint_johansen`: a library warning that escapes a function becomes an
    # EXCEPTION under `-W error`, so a correct call would raise while every
    # published field stayed correct. It is not swallowed — the message is
    # republished as this function's own warning below.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = model.fit(
            disp=False,
            maxiter=int(econometrics.kalman_max_iterations.value),
            # A DERIVATIVE-FREE optimizer by default: the likelihood is flat in
            # the variance parameters, so gradient information is unreliable.
            # Measured 2026-09-23 over 20 simulated pairs, counting fits whose
            # optimizer failed its own convergence test: lbfgs 4/20, bfgs 12/20,
            # Nelder-Mead 0/20. The gradient methods sat at the optimum without
            # knowing it -- see `kalman_optimizer` in settings.yaml.
            method=str(econometrics.kalman_optimizer),
        )
    convergence_messages = [
        str(entry.message) for entry in caught if "converge" in str(entry.message).lower()
    ]

    retvals = getattr(results, "mle_retvals", None) or {}
    converged = bool(retvals.get("converged", False))

    # The fitted quantities are in NORMALISED units; every published one is
    # converted back here, once, from the same factor array.
    state_scales = _kalman_state_scales(spec, scale_y, scale_x)

    # `errstate` around the rescaling because an OVERFLOWED fit emits numpy's
    # per-operation warnings for each of these multiplies, and the guard
    # immediately below then raises with a message naming the cause. Those
    # warnings are redundant noise on a path that errors anyway -- and under
    # `-W error` they would PRE-EMPT that message (D-097's lesson about a library
    # warning escaping a function). The guard is not silenced; only the
    # arithmetic that feeds it.
    with np.errstate(invalid="ignore", over="ignore"):
        filtered = np.asarray(results.filtered_state, dtype=float) * state_scales[:, None]
        smoothed = np.asarray(results.smoothed_state, dtype=float) * state_scales[:, None]
        standard_error = (
            _state_standard_errors(np.asarray(results.filtered_state_cov)) * state_scales[:, None]
        )

    # NO SILENT PATH: a non-finite state or band is refused rather than
    # published. A `nan` in a band renders as a gap in a chart and as a
    # comparison that is always False, so it would look like missing data
    # rather than like a failure.
    for label, array in (
        ("filtered_state", filtered),
        ("smoothed_state", smoothed),
        ("filtered_state_std_error", standard_error),
    ):
        if not bool(np.isfinite(array).all()):
            raise ValueError(
                f"The Kalman filter produced non-finite values in {label} for the "
                f"{spec.name!r} specification on {n_obs} observations. A non-finite "
                f"state or band is not a result: it renders as a gap rather than as "
                f"an error, and every comparison against it is False. This usually "
                f"means the input series has a scale that overflows the filter's "
                f"arithmetic; check the series' units before retrying."
            )

    coverage = float(econometrics.kalman_band_coverage.value)
    z_multiplier = float(norm.ppf(0.5 + coverage / 2.0))
    lower = filtered - z_multiplier * standard_error
    upper = filtered + z_multiplier * standard_error

    fitted = np.asarray(results.params, dtype=float)
    variances = {
        f"sigma2.{name}": float(fitted[index] * state_scales[index] ** 2)
        for index, name in enumerate(spec.variance_names)
    }
    # The irregular variance is the observation noise on the dependent series, so
    # it carries `scale_y**2` and NOT a state scale -- the distinction matters
    # for the pair specification, where the two differ.
    variances["sigma2.irregular"] = float(fitted[-1] * scale_y**2)

    published = _kalman_value(
        spec=spec,
        column_names=column_names,
        filtered=filtered,
        smoothed=smoothed,
        standard_error=standard_error,
        lower=lower,
        upper=upper,
        coverage=coverage,
        z_multiplier=z_multiplier,
        variances=variances,
        n_obs=n_obs,
        converged=converged,
        diffuse_scale=diffuse_scale,
        series_scales=(scale_y, scale_x),
        state_scales=state_scales,
        log_likelihood=float(results.llf),
        aic=float(results.aic),
        bic=float(results.bic),
    )

    warnings_ = _kalman_warnings(
        spec=spec,
        filtered=filtered,
        standard_error=standard_error,
        smoothed=smoothed,
        variances=variances,
        n_obs=n_obs,
        converged=converged,
        convergence_messages=convergence_messages,
    )

    latest = published["latest"]
    assert isinstance(latest, dict)  # narrowed for mypy; the shape is built above
    latest_level = latest[spec.state_names[0]]
    assert isinstance(latest_level, dict)
    revision_units = published["revision_in_band_units"]
    assert isinstance(revision_units, dict)

    return ModelResult(
        model_name="kalman_latent_state",
        country="us",
        as_of=utc_now(),
        value=published,
        unit=(
            "state units: a level is in the dependent series' units, a slope in "
            "those units per observation, and a beta in dependent-per-regressor "
            "units; standard errors and band bounds share the state's units"
        ),
        direction=None,
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not _kalman_thresholds_calibrated(),
                source_independence_count=0,
                # Section 21.4 item 13's exact case, and the ONLY setting of this
                # flag in the module that is not a judgement call: `r*` and
                # potential GDP are unobservable by nature, so the quantity this
                # function estimates is not merely estimated imperfectly -- it
                # cannot be observed at all.
                depends_on_unobservable=True,
            )
        ),
        interpretation=(
            f"Kalman filter ({spec.name!r}) on {n_obs} observations of "
            f"{', '.join(column_names)}. The latest FILTERED estimate of "
            f"{spec.state_names[0]!r} is "
            f"{float(latest_level['state']):.6g} with a {coverage:.0%} band of "
            f"[{float(latest_level['lower']):.6g}, "
            f"{float(latest_level['upper']):.6g}]. This is an estimate of an "
            f"unobservable state, not an observation: the band is the model's "
            f"own uncertainty and is only as good as the model."
        ),
        context=(
            f"Specification {spec.name!r}; state = {list(spec.state_names)}; "
            f"initialization = approximate_diffuse (scale {diffuse_scale:g}); "
            f"estimated variances = "
            + ", ".join(f"{name}={value:.6g}" for name, value in variances.items())
            + f"; log-likelihood {float(results.llf):.4f}, AIC "
            f"{float(results.aic):.4f}, BIC {float(results.bic):.4f} over "
            f"{len(variances)} parameters; converged = {converged}. Largest "
            f"filtered-vs-smoothed revision: "
            + ", ".join(
                f"{name} = {float(revision_units[name]):.3f}x its median band"
                for name in spec.state_names
            )
            + ". The smoothed state uses the whole sample and is look-ahead-"
            "biased for any decision taken in real time."
        ),
        inputs_used=_kalman_inputs_used(spec, column_names),
        warnings=warnings_,
        assumptions=_kalman_assumptions(spec, column_names),
        # --- Section 3/4 reasoning object (D-132) ---------------------------
        # D-132: `data_provenance` and `decision_relevance` were published by no
        # function in this module. `direction` is left unset: the state is a
        # LEVEL (r*, potential GDP) or a ratio, and the filter reports a path
        # with a band — it does not move the underlying quantity in one
        # direction, so a `direction` field would be a claim the estimator does
        # not make.
        data_provenance=[
            "`observations` is a DataFrame SUPPLIED BY THE CALLER, one column "
            "per observed series, already aligned and date-ordered. This module "
            "fetches nothing, so it cannot verify the definition or vintage of "
            "any column, and the latent state is only as meaningful as the "
            "observed series being the quantity the specification presumes.",
            "Every observed column comes from the same dataset, so "
            "`source_independence_count` is 0 — the state estimate is fitted to "
            "ONE sample and has no independent corroboration to credit "
            "(Module 13).",
        ],
        limitations=_kalman_limitations(),
        decision_relevance=(
            "Section 15.20-F's unobservable-state estimator, and the one place "
            "the build reads an unobservable directly: r*, potential GDP, and a "
            "cointegrated pair's time-varying hedge ratio are its three named "
            "uses, so it is the input a Taylor-rule gap, an output-gap measure, "
            "or a dynamic-hedge thesis consumes. Its published band and the "
            "filtered-vs-smoothed distinction are part of that consumption — the "
            "filtered state is the real-time one and the smoothed state is "
            "look-ahead-biased."
        ),
        decision_prohibition=[
            "MUST NOT present the filtered state as observed truth, and MUST NOT "
            "drop the band when reporting it. `r*`, potential GDP and a "
            "time-varying hedge ratio are unobservable by nature; the filter "
            "estimates them and the band states how well. A point estimate "
            "quoted without its band converts a model output into a fact "
            "(Section 15.20-F).",
            "MUST NOT use the SMOOTHED state for a real-time decision. The "
            "smoothed state at `t` is computed from observations after `t`, so "
            "using it in a backtest or a live signal imports look-ahead bias "
            "directly. The result publishes both; the filtered one is the only "
            "one a real-time decision may read.",
            "MUST NOT compare a state across two fits as though it were the same "
            "quantity. The state is defined by the specification and the "
            "estimated variances, and both move with the sample and with the "
            "chosen `state_dim`. A level from a local-level fit and a level from "
            "a local-linear-trend fit are different estimates of different "
            "models, and neither is comparable with the other's band.",
        ],
    )


def _prepare_kalman_observations(
    observations: pd.DataFrame,
) -> tuple[np.ndarray, list[str]]:
    """Validate the observation panel, or raise. Every check a refusal.

    Mirrors ``_prepare_panel``'s discipline for the same reason: silently
    dropping a row changes ``n_obs``, and the fit's variances are estimated from
    it, so the result would then be a claim about a sample the caller never
    supplied.

    The column-count bound is a REFUSAL rather than a generalisation because the
    three specifications are the specification's three named uses. A panel of
    five tenors is not an unobservable state — it is a factor decomposition, and
    ``compute_pca`` is the function for it.
    """
    if not isinstance(observations, pd.DataFrame):
        raise TypeError(
            f"observations must be a pandas DataFrame, got {type(observations).__name__}."
        )

    n_columns = observations.shape[1]
    if n_columns == 0:
        raise ValueError(
            "observations must have at least one column; it has none. A state-space "
            "model needs something to observe."
        )
    if n_columns > 2:
        raise ValueError(
            f"observations has {n_columns} columns, but this function estimates a "
            f"latent LEVEL from one series or a latent RELATIONSHIP between two "
            f"(dependent first, regressor second). A wider panel is a factor "
            f"decomposition, which is `compute_pca`'s job, not a single latent state."
        )

    duplicated = sorted(
        {str(name) for name in observations.columns[observations.columns.duplicated()]}
    )
    if duplicated:
        raise ValueError(
            f"observations has duplicate column name(s) {duplicated}. The states are "
            f"reported by name, so a duplicated label would describe the same state "
            f"twice. Rename them."
        )

    for name in observations.columns:
        if is_bool_dtype(observations[name].dtype) or not is_numeric_dtype(
            observations[name].dtype
        ):
            raise ValueError(
                f"Column {name!r} must be numeric, got dtype "
                f"{observations[name].dtype}. Encode or drop categorical columns "
                f"explicitly so the panel you filter is the panel you intend."
            )

    values = observations.astype("float64").to_numpy()

    if not bool(np.isfinite(values).all()):
        offending = [
            str(name)
            for name, column in zip(observations.columns, values.T, strict=True)
            if not bool(np.isfinite(column).all())
        ]
        raise ValueError(
            f"observations contains non-finite values (NaN or inf) in {offending}. A "
            f"single NaN propagates through the Kalman recursion into every later "
            f"state and every band bound, so the result would be non-finite from that "
            f"row onward while the fit itself reported no error. Clean or impute "
            f"explicitly."
        )

    minimum_observations = float(get_settings().econometrics.kalman_min_observations.value)
    if len(values) < minimum_observations:
        raise ValueError(
            f"{len(values)} observations is below the configured floor of "
            f"{minimum_observations:.0f} (econometrics.kalman_min_observations). The "
            f"variances that set the band are ESTIMATED, and they are downward-biased "
            f"on short samples: measured 2026-09-23 on a local level whose true "
            f"sigma2.level was 0.25, the median estimate was 0.15 at n=30 and 0.21 at "
            f"n=60. An underestimated state variance understates the state's "
            f"movement, so a short sample reports a confident state that is too "
            f"smooth."
        )

    _refuse_constant_kalman_series(values, [str(name) for name in observations.columns])

    return values, [str(name) for name in observations.columns]


def _refuse_constant_kalman_series(panel: np.ndarray, column_names: list[str]) -> None:
    """Refuse any series with no variation, on a tolerance RELATIVE to its scale.

    **Why a refusal and not a warning.** A constant series has no latent state to
    estimate: the level model's state IS the constant, and a pair's coefficient
    is identified only up to the scale of a regressor that never moves. This was
    first left to the ``not time-varying`` warning, and **a live check falsified
    that rationale** (D-101): on a constant series the state variance collapses
    to ``1e-12`` but the BAND collapses further (``1.65e-09``), so the warning's
    drift-to-band ratio came back as ``6055`` and did not fire. The warning
    compares the state's movement with the uncertainty about it, and both
    collapse together — which is exactly why the check cannot see this case.

    **``std() == 0.0`` does not fire.** Summing a constant column's squared
    deviations in floating point leaves a tiny non-zero residue — measured
    ``8.9e-16`` for a column of ``4.2`` repeated 200 times (D-100) — so a bare
    zero test passes a constant series straight through.

    **The tolerance is FULLY relative, which differs from ``compute_pca``'s
    guard on purpose.** That one reads ``eps * maximum(scale, 1.0) * 100``, so
    below scale 1 it is effectively ABSOLUTE at ``2.22e-14`` and refuses a series
    whose variation is small in absolute terms but large relative to its own
    scale — measured 2026-09-23, a series at scale ``1e-9`` varying by ``1e-6`` of
    that scale has a standard deviation of ``2.9e-16``, which is **ten orders of
    magnitude above the floating-point noise** yet is refused by the sibling's
    form while this one accepts it. The sibling's form is recorded as its own
    issue rather than changed here.

    **The divergent case for THIS form is therefore a tiny-scale series that
    genuinely moves**, and it is what the test drives: a guard whose tolerance is
    relative can only be shown to be relative by a case where a relative and an
    absolute rule DISAGREE (D-100's rule). Note that the opposite direction does
    NOT exist for the residue itself — numpy's ``std`` returns exactly ``0`` for
    a constant array at every magnitude measured from ``4.2`` to ``1e12``, so the
    residue never grows with the series' scale.
    """
    scale = np.abs(panel).max(axis=0)
    deviations = panel.std(axis=0, ddof=1)
    tolerance = np.finfo(float).eps * scale * 100.0
    constant = [
        name for index, name in enumerate(column_names) if deviations[index] <= tolerance[index]
    ]
    if constant:
        raise ValueError(
            f"Series {constant} have no variation, so there is no latent state to "
            f"estimate from them. A constant level series IS its own level, and a "
            f"coefficient estimated against a regressor that never moves is "
            f"identified only up to that regressor's scale — the fit would return a "
            f"confident number describing nothing. A bare `std() == 0` test does not "
            f"catch this (a constant column leaves a floating-point residue of about "
            f"8.9e-16), which is why the tolerance here is relative to each series' "
            f"own scale. Supply a series that moves."
        )


def _select_kalman_model(n_columns: int, state_dim: int) -> _KalmanSpec:
    """Pick the specification for ``(n_columns, state_dim)``, or refuse.

    The refusal enumerates the admissible set from ``_KALMAN_SPECS`` rather than
    restating it, so the message cannot drift from the table that governs it —
    the same "one spelling" discipline the series registry applies to routes.
    """
    if isinstance(state_dim, bool) or not isinstance(state_dim, int):
        raise TypeError(
            f"state_dim must be an int, got {type(state_dim).__name__}. The state "
            f"dimension selects the specification from a table keyed by exact "
            f"integers, so a non-integer (and a bool, which is an int subclass and "
            f"would otherwise reach the table as 0 or 1) silently selects no "
            f"specification at all."
        )

    spec = _KALMAN_SPECS.get((n_columns, state_dim))
    if spec is None:
        supported = "; ".join(
            f"{columns} column(s) x state_dim={dim} -> {entry.name}"
            for (columns, dim), entry in sorted(_KALMAN_SPECS.items())
        )
        raise ValueError(
            f"No specification for {n_columns} column(s) with state_dim={state_dim}. "
            f"The admissible combinations are: {supported}. Each is one of Section "
            f"15.20-F's named uses of this function; anything else is a different "
            f"state-space model, and inventing one here would publish a state whose "
            f"meaning nothing specifies."
        )
    return spec


def _kalman_design(spec: _KalmanSpec, panel: np.ndarray) -> np.ndarray:
    """Build the observation matrix ``H_t``, shaped ``(1, k_states, n_obs)``.

    Time-varying for the regression specification, because the regressor enters
    the DESIGN rather than the data: ``y_t = beta_t * x_t + eps_t`` is linear in
    the STATE ``beta_t`` for every ``t``, which is what lets the Kalman filter
    estimate a drifting coefficient at all.
    """
    n_obs = panel.shape[0]
    design = np.zeros((1, len(spec.state_names), n_obs), dtype=float)

    if spec.design_kind == _KALMAN_DESIGN_UNIT:
        design[0, 0, :] = 1.0
    elif spec.design_kind == _KALMAN_DESIGN_LEVEL:
        # `y_t = level_t + eps_t`: the observation reads the level and NOT the
        # slope. That is why the slope is the state an unidentified-at-t=0 prior
        # leaves wide, and why the level is not.
        design[0, 0, :] = 1.0
    else:
        design[0, 0, :] = panel[:, 1]

    return design


def _state_standard_errors(covariance: np.ndarray) -> np.ndarray:
    """Diagonal standard errors of a ``(k, k, n)`` covariance array, as ``(k, n)``.

    ``np.diagonal`` on a 3-D array does not return the shape a reader expects —
    it moves the diagonal to the LAST axis, giving ``(n, k)`` — which silently
    transposes the array. Measured while probing: a "standard error" line printed
    180 numbers where two were intended, and every one of them was plausible.
    Indexing the diagonal explicitly is the one spelling that cannot be misread.
    """
    index = np.arange(covariance.shape[0])
    return np.sqrt(covariance[index, index, :])


def _kalman_series_scales(panel: np.ndarray) -> tuple[float, float]:
    """Per-column standard deviations, with a ``1.0`` fallback for a flat column.

    **WHY THE SERIES IS NORMALISED BEFORE FITTING.** The state-space model is
    invariant under rescaling in exact arithmetic — multiply ``y`` by ``c`` and
    every state and standard error multiplies by ``c`` while every variance
    multiplies by ``c**2``. The OPTIMIZER is not. Measured 2026-09-23 on ONE
    local level fitted at six scales, reporting ``sigma2.level / scale**2``:
    ``0.3139`` at scale 1, ``0.3238`` at ``1e-3``, ``46.16`` at ``1e3``,
    ``2.663`` at ``1e6`` and ``0.02625`` at ``1e9`` — a **147x spread** between
    the ``1e-3`` and ``1e3`` fits of the same series. The cause is that the
    likelihood is evaluated at the series' own magnitude while ``start_params``
    is ``1.0``, so at scale ``1e6`` the optimizer begins eleven orders of
    magnitude from the optimum and stops wherever its step control gives up.

    The consequence is not academic: the band, and therefore the warnings that
    read it, depended on the caller's choice of UNITS. Measured on one
    degenerate series: the relative band ratio was ``2.05e-8`` at scale 1 and
    ``4.89e-2`` at ``1e4``, so the same data reported a degenerate band in
    billions and a healthy one in units of a hundred.

    Normalising first makes the numerical problem identical at every scale, and
    the published quantities are converted back in
    :func:`_kalman_state_scales`. So the fix changes the arithmetic not at all
    and the numerics entirely — which is why the returned scale is a NUMBER the
    result publishes rather than a hidden constant.
    """
    scales: list[float] = []
    for column in panel.T:
        spread = float(np.std(column))
        # A flat column has no scale to normalise by. 1.0 leaves it flat, and
        # the degenerate-variance warnings are what report the consequence --
        # refusing here instead would replace a diagnosed result with an error.
        scales.append(spread if spread > 0.0 else 1.0)
    return scales[0], scales[1] if len(scales) > 1 else 1.0


def _kalman_state_scales(spec: _KalmanSpec, scale_y: float, scale_x: float) -> np.ndarray:
    """The factor converting each NORMALISED state back into the caller's units.

    A level and a slope both carry the dependent series' units — a slope is a
    level per observation, and the observation index does not scale — so both
    are multiplied by ``scale_y``.

    A coefficient does NOT. ``y = beta * x`` gives ``beta`` dependent-per-
    regressor units, so normalising both series moves it by ``scale_y /
    scale_x``. Getting this wrong would be invisible for a pair whose two legs
    happen to share a scale, which is exactly the case a test must not use.
    """
    if spec.design_kind == _KALMAN_DESIGN_REGRESSOR:
        return np.array([scale_y / scale_x])
    return np.full(len(spec.state_names), scale_y)


def _kalman_inputs_used(spec: _KalmanSpec, column_names: list[str]) -> list[str]:
    """Name each column by the ROLE it played, not merely by its label.

    The pair specification's column order is a convention ("dependent first,
    regressor second"), and a convention recorded only in prose is one a caller
    can violate without anything objecting. Naming the role in ``inputs_used``
    puts the convention in the result, where it can be checked.
    """
    if spec.design_kind == _KALMAN_DESIGN_REGRESSOR:
        return [
            f"dependent:{column_names[0]}",
            f"regressor:{column_names[1]}",
        ]
    return [f"observed:{column_names[0]}"]


def _kalman_assumptions(spec: _KalmanSpec, column_names: list[str]) -> list[str]:
    """What the model takes as given, on every call."""
    shared = [
        "The innovations are Gaussian and the state equation is LINEAR. The "
        "band is a normal-theory interval, so a series with jumps, structural "
        "breaks or heavy tails gets a band that is too narrow precisely when it "
        "matters. The filter reports the interval the model implies, not a "
        "distribution-free one.",
        "The estimated variances are treated as KNOWN when the band is computed. "
        "They are themselves maximum-likelihood estimates, so the published band "
        "understates the total uncertainty: it conditions on the point estimates "
        "rather than integrating over their sampling error.",
    ]
    if spec.design_kind == _KALMAN_DESIGN_REGRESSOR:
        return [
            f"{column_names[0]!r} is the DEPENDENT series and {column_names[1]!r} "
            f"is the REGRESSOR, in that column order. The roles are not "
            f"interchangeable: swapping them estimates the reciprocal "
            f"relationship, which is a different quantity.",
            "The relationship is PROPORTIONAL through the origin — there is no "
            "intercept, so a pair with a persistent level offset will attribute "
            "it to the coefficient. A time-varying intercept is not a supported "
            "specification here (see `_KALMAN_SPECS`).",
            *shared,
        ]
    return [
        "The series is a LEVEL, not a change. This is the same discipline "
        "`compute_pca` enforces in the opposite direction: a stationary "
        "difference passed here is filtered as though it were a level, and the "
        "resulting state is the level of a difference series, which means "
        "nothing.",
        *shared,
    ]


def _kalman_limitations() -> list[str]:
    """What a Kalman filter cannot tell you, on every call.

    Standing caveats, distinct from ``warnings`` (a condition of this run).
    """
    return [
        "THE STATE IS UNOBSERVABLE AND THE BAND IS MODEL-DEPENDENT. `r*`, "
        "potential GDP and a time-varying hedge ratio cannot be measured, so no "
        "data can confirm the filter's answer directly. A different "
        "specification, a different sample or a different variance estimate "
        "gives a different state — the band reflects the model's own "
        "uncertainty and not the disagreement between models, which is larger.",
        "THE EARLIEST OBSERVATIONS ARE DOMINATED BY THE PRIOR. The state is "
        "initialized approximately diffuse at the configured scale, so the first "
        "observations' bands reflect the initial uncertainty rather than the "
        "data, and a state the first observation does not identify (a local "
        "linear trend's slope, whose observation design is [1, 0]) carries that "
        "prior's scale as its band for the first step. Measured 2026-09-23: a "
        "slope band of 1000.0 at the first observation, 1.42 at the second and "
        "0.0958 at its median. Read the path's head as a burn-in.",
        "THE STATE INNOVATION VARIANCE IS DOWNWARD-BIASED IN SMALL SAMPLES, AND "
        "AN UNDERESTIMATED VARIANCE MAKES THE STATE TOO SMOOTH. Measured "
        "2026-09-23 over 40 draws of a local level whose true `sigma2.level` was "
        "0.25: the median estimate was 0.15 at n=30, 0.21 at n=60 and 0.24 at "
        "n=100. The bias is toward a state that moves LESS than the truth, so "
        "the failure direction is false stability rather than false volatility.",
        "A LEVEL-ONLY MODEL ABSORBS A TREND INTO ITS OWN VARIANCE. With no trend "
        "term the random-walk level must track any deterministic drift, so "
        "`sigma2.level` measures the trend as well as the level's own movement. "
        "Measured 2026-09-23: a series with a deterministic slope drove "
        "`sigma2.level` to 1.09 against a true level variance of 0.25. Use the "
        "local linear trend specification when a trend is plausible, and read a "
        "large level variance as a possible missing trend term.",
        "`sigma2.level` AND `sigma2.slope` ARE WEAKLY IDENTIFIED TOGETHER. A "
        "local linear trend must attribute the observed movement between the "
        "level's own innovations and the slope's, and the data often cannot "
        "separate them: measured 2026-09-23, a slope whose true variance was "
        "0.0025 was estimated at 0.00043 on one fit and 0.00058 on another. "
        "Read the two variances jointly, and prefer the level-only "
        "specification when the slope's variance is estimated at the boundary.",
        "THE BAND IS A PREDICTION INTERVAL FOR THE STATE, NOT FOR THE SERIES. "
        "It describes where the unobservable state lies, not where the next "
        "observation will fall: a forecast interval must add the observation "
        "noise. A consumer that reads the state band as a forecast band "
        "understates the spread by the irregular variance.",
        "THE FILTER IS NOT A FORECAST. A random-walk state's best prediction "
        "next period is its current value, so the filtered state at the end of "
        "the sample carries no information about where the state will go; it "
        "says where it is estimated to BE. Any forward-looking use needs a model "
        "of the state's own drift, which this function does not fit.",
        "WHEN THE OBSERVATION-NOISE VARIANCE IS ESTIMATED NEAR ZERO THE BAND "
        "COLLAPSES, AND IT IS THEN NOT AN UNCERTAINTY ABOUT THE REAL QUANTITY. "
        "The model has assumed the data are observed without error, so the band "
        "measures only the state's own innovation uncertainty. Measured "
        "2026-09-23: a CONVERGED fit of a random walk observed with sigma=0.01 "
        "published `102.8486 +- 0.0000377`. That is not precision; it is a model "
        "that has stopped allowing for measurement error. `sigma2.irregular` is "
        "published on every result so a reader can see which regime the fit is "
        "in -- and no WARNING accompanies it, because no threshold separates the "
        "case: measured over 10 seeds per noise level, `median(se)/median|state|` "
        "spanned 3.1e-8 to 1.8e-3 for noise-free samples, overlapping the "
        "well-specified range, and `sigma2.irregular/var(y)` is "
        "specification-dependent because a pair's var(y) is dominated by the "
        "regressor. An unreliable warning is worse than a disclosed limitation.",
        "THE FIT IS NUMERICALLY SCALE-SENSITIVE, WHICH IS WHY THE SERIES IS "
        "NORMALISED BEFORE FITTING. The model is invariant under rescaling in "
        "exact arithmetic but the optimizer is not, and before the normalisation "
        "the same series fitted at scale 1e-3 and at 1e3 returned "
        "`sigma2.level/scale**2` of 0.3238 and 46.16 -- a 147x spread driven "
        "purely by the caller's choice of units. The normalisation removes it "
        "(measured: 0.313922 at every scale from 1e-9 to 1e9), and the scale "
        "factors are published as `series_scales` and `state_scales` so two fits "
        "can be compared knowingly. A reader who rescales the input themselves "
        "should expect the same answer, not a different one.",
    ]


def _kalman_thresholds_calibrated() -> bool:
    """Whether the thresholds shaping ``kalman_latent_state``'s DISCLOSURE are calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` (negated by the
    caller).

    Both are judgements rather than facts: the drift ratio at which a state stops
    counting as time-varying, and the revision multiple above which a real-time
    estimate is called materially revised. Each was PLACED by measurement (the
    drift ratio separates 0.025 from 7.02; the revision multiple sits above the
    level model's measured maximum) but a placement is not a calibration, so
    each is ``uncalibrated_illustrative`` today and the caller applies the
    penalty.

    A third leaf — a relative floor for a "degenerate band" — was removed
    because its measurement showed it could not separate the cases it existed
    for. See the note beside branch 2 of :func:`_kalman_warnings`; a dead
    threshold left here would be the D-047 class of config value that nothing
    reads.
    """
    settings = get_settings()
    return settings.is_calibrated(
        "econometrics.kalman_min_state_drift_ratio"
    ) and settings.is_calibrated("econometrics.kalman_max_revision_ratio")


def _kalman_value(
    *,
    spec: _KalmanSpec,
    column_names: list[str],
    filtered: np.ndarray,
    smoothed: np.ndarray,
    standard_error: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    coverage: float,
    z_multiplier: float,
    variances: dict[str, float],
    n_obs: int,
    converged: bool,
    diffuse_scale: float,
    series_scales: tuple[float, float],
    state_scales: np.ndarray,
    log_likelihood: float,
    aic: float,
    bic: float,
) -> dict[str, object]:
    """Assemble the published ``value``, with every band derived from one source.

    ``lower`` and ``upper`` are computed once, in the caller, from the same
    ``standard_error`` array the result publishes. Recomputing them here would
    give a second derivation of the same quantity, which is how two published
    numbers start disagreeing.
    """
    state_paths: dict[str, list[float]] = {}
    error_paths: dict[str, list[float]] = {}
    lower_paths: dict[str, list[float]] = {}
    upper_paths: dict[str, list[float]] = {}
    latest: dict[str, dict[str, float]] = {}
    smoothed_latest: dict[str, float] = {}
    revisions: dict[str, float] = {}
    per_state_scale: dict[str, float] = {}
    prior_error: dict[str, float] = {}

    for index, name in enumerate(spec.state_names):
        state = filtered[index, :]
        error = standard_error[index, :]
        state_paths[name] = [float(value) for value in state]
        error_paths[name] = [float(value) for value in error]
        lower_paths[name] = [float(value) for value in lower[index, :]]
        upper_paths[name] = [float(value) for value in upper[index, :]]
        latest[name] = {
            "state": float(state[-1]),
            "std_error": float(error[-1]),
            "lower": float(lower[index, -1]),
            "upper": float(upper[index, -1]),
        }
        smoothed_latest[name] = float(smoothed[index, -1])
        per_state_scale[name] = float(state_scales[index])
        # The initial prior's scale in the CALLER's units, which is what a
        # reader needs to recognise a prior-dominated head in the path: the
        # first observation's band equals this whenever the observation does
        # not identify the state.
        prior_error[name] = float(np.sqrt(diffuse_scale) * state_scales[index])
        # The revision expressed in the state's OWN band units, because a raw
        # difference in the state's units cannot be judged without knowing the
        # band -- and the band is what the reader is about to trust.
        median_error = float(np.median(error))
        revisions[name] = (
            float(np.max(np.abs(state - smoothed[index, :])) / median_error)
            if median_error > 0.0
            else float("inf")
        )

    return {
        "model_spec": spec.name,
        "state_names": list(spec.state_names),
        "series": list(column_names),
        "n_obs": int(n_obs),
        "n_columns": len(column_names),
        "state_dim": len(spec.state_names),
        "filtered_state": state_paths,
        "filtered_state_std_error": error_paths,
        "band_lower": lower_paths,
        "band_upper": upper_paths,
        "band_coverage": float(coverage),
        "band_z": float(z_multiplier),
        "latest": latest,
        "smoothed_latest": smoothed_latest,
        "revision_in_band_units": revisions,
        "estimated_variances": dict(variances),
        "log_likelihood": float(log_likelihood),
        "aic": float(aic),
        "bic": float(bic),
        "n_parameters": len(variances),
        "converged": bool(converged),
        "initialization": "approximate_diffuse",
        "diffuse_scale": float(diffuse_scale),
        "prior_standard_error": prior_error,
        # The normalisation is PUBLISHED rather than hidden, because it is the
        # only part of the computation that depends on the series' units -- and
        # a reader comparing two fits needs it to know they are comparable.
        "series_scales": {
            name: float(scale) for name, scale in zip(column_names, series_scales, strict=False)
        },
        "state_scales": per_state_scale,
    }


def _kalman_warnings(
    *,
    spec: _KalmanSpec,
    filtered: np.ndarray,
    standard_error: np.ndarray,
    smoothed: np.ndarray,
    variances: dict[str, float],
    n_obs: int,
    converged: bool,
    convergence_messages: list[str],
) -> list[str]:
    """Every condition of THIS run that a reader must know before using the state.

    Three branches, each measured before it was written, each with a test that
    drives it. A branch that fires on every call would be noise and is therefore
    a ``limitation`` instead — the standing caveats live in
    :func:`_kalman_limitations`. A branch that fires UNRELIABLY is worse than
    either, which is why the degenerate-band warning was measured and removed;
    see the note beside branch 2.
    """
    econometrics = get_settings().econometrics
    emitted: list[str] = []

    if not converged:
        detail = f" ({convergence_messages[0]})" if convergence_messages else ""
        emitted.append(
            f"MAXIMUM LIKELIHOOD DID NOT CONVERGE{detail}. The variances and "
            f"therefore the entire band are the optimizer's last iterate rather "
            f"than a maximum of the likelihood, so the band is not an estimate of "
            f"anything. Treat the state as indicative only, and check whether the "
            f"series is degenerate (constant, or observed without noise)."
        )

    for index, name in enumerate(spec.state_names):
        variance = float(variances.get(f"sigma2.{name}", 0.0))
        error = standard_error[index, :]
        median_error = float(np.median(error))

        # Branch 1: the state does not actually vary. The random walk's typical
        # excursion over the sample is sqrt(n * sigma2); comparing it with the
        # filter's own band asks whether the estimated movement is larger than
        # the uncertainty about it. Measured separation 2026-09-23: 0.025 for a
        # genuinely constant coefficient against 7.02 at the minimum for one
        # that moves, so the configured 1.0 sits in a wide empty gap.
        drift = math.sqrt(max(n_obs * variance, 0.0))
        if median_error > 0.0:
            ratio = drift / median_error
            if ratio <= float(econometrics.kalman_min_state_drift_ratio.value):
                emitted.append(
                    f"{name!r} IS NOT TIME-VARYING on this sample: its estimated "
                    f"innovation variance is {variance:.3g}, so the state's whole "
                    f"excursion over {n_obs} observations is {drift:.6g} against a "
                    f"median band of {median_error:.6g} ({ratio:.3f}x). The fit has "
                    f"collapsed the state to a constant, so 'time-varying' "
                    f"describes the specification and not the estimate -- read "
                    f"`latest` as a fixed coefficient and do not interpret its "
                    f"path as movement."
                )

        # Branch 2: the real-time estimate is materially revised with hindsight.
        # Measured 2026-09-23 across 25 draws: a level model's largest revision
        # ran 1.54x-2.96x its median band and a trend model's SLOPE ran
        # 3.19x-27.05x, so the configured multiple sits above the stable case.
        #
        # NOTE the branch that is NOT here. A "degenerate band" warning was
        # written, MEASURED and REMOVED: when the model drives the observation
        # variance to (near) zero the band collapses, and a converged fit was
        # observed publishing `102.8486 +- 0.0000377`. But no threshold
        # separates that case from a well-specified one. Measured 2026-09-23
        # over 10 seeds at each noise level, `median(se) / median|state|` spanned
        # 3.1e-8 to 1.8e-3 for noise-free-to-noisy samples and 5.0e-3 to 6.7e-3
        # only at the largest noise; the alternative `sigma2.irregular /
        # var(y)` spanned 5.5e-12 to 2.7e-2 at zero noise -- overlapping the
        # noisy samples -- and is specification-dependent, because a pair's
        # var(y) is dominated by the regressor. A warning that fires unreliably
        # is worse than none: it teaches the reader to ignore it. The behaviour
        # is DISCLOSED instead (see `_kalman_limitations`), and the quantity a
        # reader needs to judge it -- `sigma2.irregular` -- is published.
        if median_error > 0.0:
            revision = float(np.max(np.abs(filtered[index, :] - smoothed[index, :])) / median_error)
            if revision > float(econometrics.kalman_max_revision_ratio.value):
                emitted.append(
                    f"THE REAL-TIME ESTIMATE OF {name!r} IS MATERIALLY REVISED: the "
                    f"filtered path differs from the smoothed path by up to "
                    f"{revision:.1f}x its median band, so later observations move "
                    f"this state by more than its own stated uncertainty. The "
                    f"filtered value is still the only one a real-time decision may "
                    f"use -- the smoothed one sees the future -- but a state this "
                    f"unstable should not be treated as a settled reading."
                )

    return emitted


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


def _stationarity_thresholds_calibrated() -> bool:
    """Whether the thresholds ``test_stationarity`` leans on are calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` (negated by the
    caller).

    ``test_stationarity`` reads exactly two configurable thresholds: the size at
    which BOTH tests are judged (``significance_level``) and the observation
    floor below which it refuses (``stationarity_min_observations``). Both are
    ``conventional`` today, so this returns ``True`` and the caller applies NO
    heuristic penalty — the function leans on no illustrative placeholder.

    A dedicated helper rather than reusing ``_r_squared_floor_is_calibrated``,
    which reads ``econometrics.low_r_squared_threshold`` — a leaf this function
    never consumes. Wiring the flag to that helper would make a future
    recalibration of the R-squared floor silently move the stationarity
    confidence (and leave it untouched if a stationarity leaf were made
    illustrative), which is the "coupling nobody asked for" the sibling
    helper's docstring names. It is also the mirror image of D-139's
    ``_cip_bands_are_calibrated`` finding, where a helper read the WRONG leaves
    for its function: here the flag must be computed from the leaves THIS
    function reads, and from no others (AGENTS.md §22.8: confidence is computed
    from stated factors).
    """
    settings = get_settings()
    return settings.is_calibrated("econometrics.significance_level") and settings.is_calibrated(
        "econometrics.stationarity_min_observations"
    )


def _cointegration_thresholds_calibrated() -> bool:
    """Whether the two thresholds shaping ``test_cointegration``'s DERIVATIONS are calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` (negated by the
    caller).

    Distinct from :func:`_r_squared_floor_is_calibrated` even though the two
    currently read the same underlying answer, because they answer different
    questions about different leaves: that one prices the R-squared JUDGEMENT,
    this one prices the **split fraction** and the **assumed family size** —
    the two numbers that decide when the regime-stability check fires and how
    large a correction the multiple-testing warning prints. Conflating them
    would mean a future recalibration of the R-squared floor silently changed
    the cointegration confidence, which is a coupling nobody asked for.

    The cointegration thresholds are ``uncalibrated_illustrative`` today, so
    this returns ``False`` and the caller applies the penalty.
    """
    settings = get_settings()
    return settings.is_calibrated(
        "econometrics.regime_stability_split_fraction"
    ) and settings.is_calibrated("econometrics.assumed_test_family_size")


def _validate_cointegration_method(method: str) -> str:
    """Return the requested method, or raise naming the permitted set.

    Validated here rather than passed through, because ``statsmodels`` has no
    common argument and an unrecognised string would be silently accepted by a
    ``==`` chain and then take the ``else`` branch — i.e. an unknown method
    would quietly run Engle-Granger and report it under its own name.
    """
    permitted = frozenset({"engle_granger", "johansen"})
    if not isinstance(method, str):
        raise TypeError(
            f"method must be a string naming the cointegration test, got {type(method).__name__}."
        )
    if method not in permitted:
        raise ValueError(
            f"method must be one of {sorted(permitted)}, got {method!r}. The two "
            f"are not interchangeable — Engle-Granger assumes a single "
            f"cointegrating vector and Johansen estimates the count — so an "
            f"unknown name must refuse rather than default to one of them."
        )
    return method


def _prepare_pair(y: pd.Series, x: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Validate and align the two sides of a cointegration test, or raise.

    Mirrors :func:`_prepare_observations`'s discipline — refuse, never repair —
    with three additions specific to a two-series test:

    * **Both series are validated, not just ``y``.** A regression has one
      dependent variable and the asymmetry is real; a cointegration test treats
      the pair as a relationship, and validating only one side would let a
      non-finite ``x`` reach the estimator.
    * **The index must be identical, and that is the whole alignment rule.**
      Intersecting two differently-indexed series would change the sample
      silently, and a cointegration statistic is a statement about its sample.
    * **The order of the pair is preserved, not sorted.** ``coint(y, x)`` and
      ``coint(x, y)`` are *not* the same test in finite samples (the
      normalisation differs), so the caller's ordering is respected and
      reported. This is why the function does not "helpfully" put them in a
      canonical order.

    Returns float64 copies so the estimator cannot be perturbed by the caller's
    dtypes.
    """
    for label, series in (("y", y), ("x", x)):
        if not isinstance(series, pd.Series):
            raise TypeError(f"{label} must be a pandas Series, got {type(series).__name__}.")

    if len(y) != len(x):
        raise ValueError(
            f"y and x must have the same number of rows: y has {len(y)}, x has "
            f"{len(x)}. Align them explicitly — this function will not intersect "
            f"them silently, because a cointegration statistic is a statement "
            f"about its sample."
        )
    if not y.index.equals(x.index):
        raise ValueError(
            "y and x must share an identical index. They are the same length but "
            "labelled differently, so pairing them by position would be an "
            "alignment assumption this function is not entitled to make."
        )

    for label, series in (("y", y), ("x", x)):
        if is_bool_dtype(series.dtype) or not is_numeric_dtype(series.dtype):
            raise ValueError(f"{label} must be numeric, got dtype {series.dtype}.")

    y_float = y.astype("float64")
    x_float = x.astype("float64")

    for label, series in (("y", y_float), ("x", x_float)):
        if not bool(np.isfinite(series.to_numpy()).all()):
            raise ValueError(
                f"{label} contains non-finite values (NaN or inf). Clean or impute "
                f"them explicitly: dropping those rows here would change the window "
                f"without recording it."
            )
        if math.isclose(float(series.max()), float(series.min()), rel_tol=0.0, abs_tol=0.0):
            raise ValueError(
                f"{label} is constant across the sample. A constant series has no "
                f"variation to co-move with, and the first-step regression would be "
                f"rank-deficient — the cointegration statistic from it would mean "
                f"nothing."
            )

    minimum = int(get_settings().econometrics.cointegration_min_observations.value)
    if len(y_float) < minimum:
        raise ValueError(
            f"{len(y_float)} observations is below the configured floor of {minimum} "
            f"(econometrics.cointegration_min_observations). The Engle-Granger "
            f"procedure spends observations twice — once on the first-step "
            f"regression, once on the residual ADF, which also augments with its own "
            f"lags — so a shorter sample cannot support the statistic."
        )

    y_named = y_float.rename(str(y.name) if y.name is not None else "y")
    x_named = x_float.rename(str(x.name) if x.name is not None else "x")
    return y_named, x_named


def _run_engle_granger(
    y: pd.Series,
    x: pd.Series,
    *,
    trend: str,
    alpha: float,
) -> tuple[float, float, _Criticals, bool]:
    """Run Engle-Granger and return ``(statistic, p, criticals, is_rejected)``.

    ``result_object`` is **not** passed, and that is a measured decision rather
    than an oversight. The habit learned on ``adfuller`` and ``kpss`` — pass
    ``result_object=True`` because statsmodels has deprecated the tuple — does
    **not** transfer here: probing ``statsmodels.tsa.stattools.coint`` on
    2026-09-23 showed its signature is
    ``(y0, y1, trend, method, maxlag, autolag, return_results)`` — there is no
    ``result_object`` argument at all, and passing one raises
    ``TypeError: coint() got an unexpected keyword argument``. The returned
    ``CointResult`` names its fields ``coint_t`` / ``pvalue`` / ``critical_values``,
    *not* ``stat`` / ``crit``. **A mechanical translation from the ADF habit
    would have raised on the first call; probing the object is what caught it.**

    The three silent-failure paths this guard exists for are documented on the
    public function. They are refused here rather than warned about, because in
    all three cases statsmodels returns a **number** and the number is wrong:

    * a non-finite statistic means the first-step regression was rank-deficient
      (probed: near-collinear series give ``coint_t = -inf`` with
      ``pvalue = 0.0`` and only a ``CollinearityWarning``);
    * a NaN critical value means every comparison against it is ``False``, so
      the verdict would silently become "cannot reject" whatever the statistic;
    * a non-finite p-value is not a decision at all.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = coint(y.to_numpy(), x.to_numpy(), trend=trend, autolag=_coint_autolag())

    collinear = any(issubclass(entry.category, CollinearityWarning) for entry in caught)

    statistic = float(result.coint_t)
    p_value = float(result.pvalue)
    critical_values: _Criticals = (
        float(result.critical_values[0]),
        float(result.critical_values[1]),
        float(result.critical_values[2]),
    )

    if collinear or not math.isfinite(statistic):
        raise ValueError(
            f"The Engle-Granger first-step regression was rank-deficient: the pair "
            f"is (near-)perfectly collinear, so statsmodels returned "
            f"coint_t = {statistic!r} with p = {p_value!r} and only warned. That is "
            f"an infinitely significant result from a degenerate fit — it LOOKS like "
            f"the strongest possible evidence of cointegration and is the least "
            f"reliable. Check that y and x are not the same series (or a transform "
            f"of one another) before testing them for cointegration."
        )
    if not math.isfinite(p_value):
        raise ValueError(
            f"The cointegration test returned a non-finite p-value ({p_value!r}) "
            f"with statistic {statistic!r}. There is no decision to report."
        )
    if not all(math.isfinite(value) for value in critical_values):
        raise ValueError(
            f"The cointegration test returned non-finite critical values "
            f"{critical_values!r}. Every comparison against a NaN is False, so a "
            f"verdict derived from them would read 'cannot reject' regardless of "
            f"the statistic. This is what statsmodels returns for a deterministic-"
            f"terms setting whose 2010 look-up table is unavailable — the setting is "
            f"validated at config load for exactly this reason."
        )

    # `coint` reports the ADF statistic on the residual, whose 1%/5%/10% critical
    # values are the LAST THREE, so a rejection at `alpha` is "the statistic is
    # more negative than the critical value for that size". Written as an
    # explicit index lookup rather than a comparison chain because a transposed
    # `<` would invert every verdict while leaving the function running.
    position = _significance_position(alpha)
    is_rejected = statistic < critical_values[position]
    return statistic, p_value, critical_values, is_rejected


def _significance_position(alpha: float) -> int:
    """Map a size to its index in ``coint``'s 1%/5%/10% critical-value triple.

    The table is ordered most-severe first: index 0 is 1%, 1 is 5%, 2 is 10%.
    A size more extreme than 1% uses the 1% value (the strictest available
    comparison) and a size looser than 10% uses the 10% value — disclosed
    rather than silently clamped, since the returned critical triple is
    published beside the verdict so a consumer can see which was applied.
    """
    if alpha <= 0.01:
        return 0
    if alpha <= 0.05:
        return 1
    return 2


def _coint_autolag() -> str:
    """statsmodels' own accepted spelling for ``coint``'s lag selection.

    A separate constant because the two functions spell the same quantity
    differently: ``adfuller`` takes ``"AIC"`` while ``coint`` validates against
    ``("aic", "bic", "t-stat")`` — lowercase. Passing the configured
    ``adf_autolag`` ("AIC") straight through raises
    ``ValueError: Value AIC not in ...``. Probed 2026-09-23; the mapping is
    lowercased for the same reason the setting exists, so the two cannot drift.
    """
    return str(get_settings().econometrics.adf_autolag).lower()


def _engle_granger_spread(
    y: pd.Series,
    x: pd.Series,
    *,
    trend: str,
) -> tuple[float, pd.Series]:
    """Reconstruct the spread ``coint`` tests, and return ``(beta, spread)``.

    **This is the shared-basis requirement, discharged by rebuilding rather than
    by assuming.** ``coint`` returns only the statistic, so the spread it tested
    is not directly available; the design it uses internally is reproduced here
    from its source (``add_trend(y1, trend=trend, prepend=False)`` then
    ``OLS(y0, xx)``). Verified 2026-09-23: the ADF statistic computed on this
    reconstruction equals ``coint``'s ``coint_t`` to within 1e-10 for both
    ``'c'`` and ``'ct'``, so the published spread is provably the series the
    reported statistic was computed from — not a lookalike that happens to use
    the same data.

    Note the spread is the residual of a regression that **includes the
    deterministic terms**, so ``beta`` here is the slope on ``x`` under that same
    specification. Reporting a spread from a differently-specified regression
    than the one the p-value came from is precisely the mismatch Section 9
    warns about: the two would share a sample and nothing else.
    """
    design = add_trend(x.to_numpy().reshape(-1, 1), trend=trend, prepend=False)
    fit = sm.OLS(y.to_numpy(), design).fit()
    spread = pd.Series(
        [float(value) for value in fit.resid],
        index=y.index,
        name=f"spread({y.name}~{x.name})",
    )
    # With prepend=False the regressor column is FIRST and the deterministic
    # terms follow, so the hedge ratio is params[0] under both 'c' and 'ct'.
    beta = float(fit.params[0])
    return beta, spread


def _spread_stationarity(spread: pd.Series) -> _SpreadReading:
    """ADF the reconstructed spread with **no** constant and **no** trend.

    Deliberately not ``test_stationarity``. That function tests a raw series and
    includes a constant, which is right for a level and **wrong** for a
    cointegrating residual: the residual is already demeaned by the first-step
    regression, so re-centring it would fit one more parameter against the same
    data. This mirrors what ``coint`` does internally
    (``regression="n"``), which is what makes the two readings comparable.

    Reported as **supporting evidence, never as the verdict** — the verdict is
    the p-value, which carries the correct (non-standard) distribution. ADF on
    the residual uses ordinary ADF critical values, so its p-value is
    **too small**; that is exactly the pre-test bias Engle-Granger is criticised
    for, and it is stated in the limitations rather than corrected here.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # F-EC-004: `result_object=True` for the SAME reason `_run_adf` passes it.
        # statsmodels has announced the plain tuple's length/layout changes in 0.16
        # (or after July 2027), so indexing `result[0]`/`result[1]` keeps working
        # today and would break on an upgrade with no test failing. The result
        # object is the explicitly stable surface. Behaviour is IDENTICAL on the
        # pinned statsmodels (0.15) — this is a hardening, not a value change.
        result = adfuller(
            spread.to_numpy(),
            regression="n",
            autolag=_coint_autolag(),
            result_object=True,
        )

    ill_conditioned = any(issubclass(entry.category, SingularMatrixWarning) for entry in caught)
    statistic = float(result.statistic)
    p_value = float(result.pvalue)
    return {
        "statistic": round(statistic, 6),
        "p_value": round(p_value, 6),
        "is_stationary": p_value < float(get_settings().econometrics.significance_level.value),
        "design_was_ill_conditioned": ill_conditioned,
    }


def _estimate_half_life(spread: pd.Series | None) -> _HalfLife:
    """Estimate the spread's half-life of mean reversion from an AR(1). DERIVED.

    **The derivation, written out rather than recalled.** The spread is the
    cointegrating residual ``z``. Model its reversion as a discrete AR(1)
    written with the *difference* on the left:

        dz_t = z_t - z_{t-1} = phi * z_{t-1} + eps_t

    * ``phi < 0`` — mean reversion: a positive deviation is followed by a fall.
    * ``phi = 0`` — a random walk: the spread does not revert at all.
    * ``phi > 0`` — the spread *accumulates* deviation. There is no half-life.

    The continuous-time analogue is ``dz/dt = -kappa * z``, whose solution is
    ``z(t) = z(0) * exp(-kappa * t)``. The half-life ``H`` solves
    ``exp(-kappa * H) = 1/2``, so ``H = ln(2) / kappa``. One discrete step is one
    period, so ``dz`` per period ``= -kappa * z`` gives ``phi = -kappa``, and

        H = ln(2) / (-phi) = -ln(2) / phi.

    **Sign check.** ``phi < 0`` gives ``H > 0``, a positive finite half-life.
    ``phi > 0`` gives ``H < 0``, which is not a time — so it is refused, not
    reported.

    **Limiting behaviour.**
    ``phi -> 0-`` gives ``H -> +inf`` (no reversion; a slower and slower return).
    ``phi -> -1+`` gives ``H -> ln(2) = 0.693``, the **floor**: a process that
    alternates sign every period has reverted inside one sampling interval, and
    one period is the shortest interval the data can express.

    **The aliasing boundary, and why it is a refusal.** ``phi = rho - 1`` where
    ``rho`` is the AR(1) persistence, so the discrete process is stationary iff
    ``-2 < phi < 0``. For ``phi <= -1`` we have ``rho <= 0``: the spread
    **alternates sign every period**, and ``H`` computed from the formula falls
    *below* the floor. Measured 2026-09-23, simulating ``z_t = rho*z_{t-1}+e``
    and fitting this estimator: ``rho = -0.5`` (``phi = -1.5``) fits
    ``phi = -1.481`` and yields a naive ``H = 0.468`` periods; ``rho = -1`` fits
    ``-1.9999`` and yields ``0.347``. Those are **arithmetically correct and
    meaningless**: a number below one period cannot be resolved by the sampling
    interval, and reporting it invites precisely the mistake of sizing a trade
    on it. So ``phi <= -1`` is refused with the reason, exactly as ``phi >= 0``
    is. (The estimator itself is unbiased across the whole valid range: the same
    probe recovers ``rho = 0.95`` to ``-0.047``, ``rho = 0.5`` to ``-0.484``,
    and the hand case ``rho = 0.5`` at ``n = 20000`` to ``-0.49965147`` against
    a true ``-0.5``, an error of 0.07%.)

    **Confirmation against a hand-computed case.** For ``phi = -0.5`` the
    derivation gives ``H = -ln(2)/(-0.5) = 2*ln(2) = 1.38629436...``. A series
    simulated with exactly ``rho = 0.5`` and fitted here returns
    ``H = 1.38726137`` — the estimator agrees with the closed form to 0.07%,
    which is sampling error, not bias. The test file pins this case.

    The regression **includes an intercept**. Without it the fit is biased when
    the spread's mean is non-zero, which is the normal case; measured on the
    same simulation, dropping the intercept moves the fitted ``phi`` from
    ``-0.4996`` to ``-0.4979`` — small here, but it is a bias with no benefit,
    and the spread's mean is a free parameter of the model rather than a fact
    known to be zero.

    ``None`` input — Johansen, which does not normalise a single spread — yields
    the same shape with a note saying so, so the consumer's code path is the
    same in both cases and a missing estimate cannot be confused with a refused
    one.
    """
    if spread is None or len(spread) < 3:
        return {
            "periods": None,
            "phi": None,
            "note": (
                "No half-life was estimated: this method does not produce a single "
                "normalised spread to fit an AR(1) to."
                if spread is None
                else "No half-life was estimated: the spread is too short to lag."
            ),
        }

    values = spread.to_numpy()
    lagged = values[:-1]
    differences = np.diff(values)

    # The intercept is carried so a spread with a non-zero mean is not forced
    # through the origin; see the docstring. `add_constant` is not used so the
    # slope's index is explicit and cannot be reordered by a statsmodels change.
    design = np.column_stack([np.ones_like(lagged), lagged])
    fit = sm.OLS(differences, design).fit()
    phi = float(fit.params[1])

    if not math.isfinite(phi):
        return {
            "periods": None,
            "phi": None,
            "note": (
                "No half-life was estimated: the AR(1) slope on the spread is "
                "non-finite, so the mean-reversion regression is degenerate."
            ),
        }
    if phi >= 0.0:
        return {
            "periods": None,
            "phi": round(phi, 8),
            "note": (
                f"No half-life: the AR(1) slope phi = {phi:+.6f} is non-negative, so "
                f"the spread does not mean-revert. phi = 0 is a random walk (no "
                f"reversion at all) and phi > 0 means the spread ACCUMULATES "
                f"deviation. A half-life computed from it would be negative, which is "
                f"not a time."
            ),
        }
    if phi <= -1.0:
        return {
            "periods": None,
            "phi": round(phi, 8),
            "note": (
                f"No half-life: the AR(1) slope phi = {phi:+.6f} is at or below -1, "
                f"i.e. the fitted persistence rho = 1 + phi = {1.0 + phi:+.6f} is at "
                f"or below zero. The spread ALTERNATES SIGN every period, and the "
                f"formula would return a half-life below one period — a number "
                f"smaller than the sampling interval can resolve. Reported as "
                f"unestimable rather than as a fast reversion."
            ),
        }

    half_life = -math.log(2.0) / phi
    periods = round(half_life, 8)
    # The half-life must be resolvable by the sample. A half-life longer than the
    # entire series is indistinguishable from no reversion at all (Section 15.18:
    # a number the data cannot span is not a time the data can observe). The
    # arithmetic-trend edge fits phi to a value a hair below zero
    # (floating-point), so the strict `phi >= 0` test above lets it through to an
    # astronomically large but finite H; refusing on the sample-length bound
    # catches exactly that case without a magic epsilon on the sign test, and
    # matches the rationale of `_half_life_disclosure`.
    if periods > len(values):
        return {
            "periods": None,
            "phi": round(phi, 8),
            "note": (
                f"No half-life: the AR(1) slope phi = {phi:+.6f} implies "
                f"H = -ln(2)/phi = {half_life:.4f} periods, which is LONGER than the "
                f"{len(values)}-observation sample it was estimated from. A half-life "
                f"the data cannot span is not estimable -- it is indistinguishable from "
                f"no reversion -- so it is refused rather than returned as a finite "
                f"number that looks complete."
            ),
        }
    return {
        "periods": periods,
        "phi": round(phi, 8),
        "note": (
            f"AR(1) on the spread: phi = {phi:+.6f} (persistence rho = "
            f"{1.0 + phi:.6f}), so H = -ln(2)/phi = {half_life:.4f} periods."
        ),
    }


def _half_life_disclosure(half_life: _HalfLife, n_obs: int) -> str | None:
    """Whether a RETURNED half-life is longer than the sample it was estimated from.

    The mirror image of the ``phi <= -1`` refusal, and it exists for the same
    reason. A near-unit-root spread fits a small negative ``phi`` and the formula
    returns a large but perfectly FINITE number — measured 2026-09-23, a pure
    random walk of 300 points fitted ``phi = -0.0061`` and reported
    ``H = 112.96`` periods. That number is arithmetically correct and, for any
    practical purpose, **indistinguishable from no reversion**: the sample is 300
    observations and the estimate claims a half-life of 113 of them, so the
    spread would have to run for a third of its own history to give back half a
    deviation. Nothing about the returned figure says so, which is exactly the
    "number that looks complete" this project treats as the primary failure mode.

    This **discloses rather than refuses**. The low-``phi`` case is a continuum
    and a hard cutoff would manufacture a discontinuity in a quantity that has
    none; ``phi >= 0`` and ``phi <= -1`` are the two genuine boundaries (the sign
    flips, and the sampling resolution runs out), so those refuse and this warns.
    """
    periods = half_life["periods"]
    if periods is None:
        return None
    if float(periods) >= float(n_obs):
        return (
            f"THE REPORTED HALF-LIFE ({float(periods):.1f} periods) IS LONGER THAN "
            f"THE SAMPLE IT WAS ESTIMATED FROM ({n_obs} observations). The estimate is "
            f"a large but finite number, so it passes every arithmetic check — and it "
            f"is not usable. A spread whose implied half-life exceeds the window "
            f"cannot be distinguished from one that does not revert at all: no "
            f"convergence trade can be sized on a horizon the sample could not "
            f"observe. The fitted phi is {half_life['phi']!r}, i.e. near a unit root."
        )
    if float(periods) > float(n_obs) / 4.0:
        return (
            f"THE REPORTED HALF-LIFE ({float(periods):.1f} periods) EXCEEDS A QUARTER "
            f"OF THE SAMPLE ({n_obs} observations). It is estimable but large: the "
            f"implied convergence horizon is a substantial fraction of the window, so "
            f"the estimate rests on very few independent deviations being observed to "
            f"completion. Treat the horizon as weakly identified rather than as a "
            f"measured time."
        )
    return None


def _run_johansen(
    y: pd.Series,
    x: pd.Series,
    *,
    alpha: float,
) -> tuple[float, float, _Criticals, bool, int]:
    """Run Johansen's trace test, returning the ENGLE-GRANGER shape plus a count.

    Returns the same four-tuple shape as :func:`_run_engle_granger` plus a FIFTH
    element, ``discarded_imaginary``: the number of ``ComplexWarning``s
    statsmodels emitted from its internal eigendecomposition. The count is
    returned rather than dropped because the caller discloses it — a captured
    warning that nothing reads is a disclosure that only looks handled.

    The quantities are **not** the same kind of object and
    the result says so: Johansen reports the trace statistic for the hypothesis
    "no cointegrating vector" (``r = 0``) against its own critical values, and on
    a **pair** there is at most one vector, so ``r = 0`` versus ``r <= 1`` is the
    whole of the inference.

    ``p_value`` is **not computed**, and is reported as ``nan`` rather than as an
    approximation. Johansen's statistic is compared against a simulated
    critical-value table, not against a distribution with a closed-form CDF;
    statsmodels exposes no p-value for it, and interpolating one from the three
    published sizes would be inventing a number. So the verdict is derived from
    the **critical values** (the comparison that is actually available) and the
    p-value field is left non-finite, disclosed in the warnings and never
    presented as a decision input. The unit assertions in the tests pin this.

    The design carries a constant (``det_order=0``) and one lag
    (``k_ar_diff=1``), matching the ``'c'`` deterministic terms the
    Engle-Granger path uses so the two methods are tested under the same
    specification. Johansen's lag argument counts **differences**, not levels,
    which is the opposite convention to ``adfuller``'s — a substitution that
    would silently under-specify the VECM.
    """
    # Imported here rather than at module scope: `vecm` pulls in a significant
    # part of statsmodels, and `run_regression`/`test_stationarity` — the
    # module's other two functions — do not need it.
    from statsmodels.tsa.vector_ar.vecm import coint_johansen

    # The warnings ARE captured, and the capture is DISCLOSED rather than
    # swallowed. This reverses an earlier decision, and the reason is measured:
    # probing on 2026-09-23 showed `coint_johansen` emits FOUR `ComplexWarning`s
    # ("Casting complex values to real discards the imaginary part", from its own
    # `np.linalg.eig` call) on **every** call, at every sample size tried
    # (n = 60 … 1600) — it is unconditional library noise, not a signal about
    # this pair. Left uncaptured it escapes to whoever called the model function:
    # a consumer running with `-W error` gets an exception raised out of
    # `test_cointegration` on every Johansen call, and a reader sees statsmodels'
    # internal advice attributed to this module. Swallowing it silently would be
    # the OTHER error — the one the previous comment here warned about, where a
    # disclosure "comes to look handled when it is not". So it is captured, the
    # count is carried on the result, and the limitation says what it means.
    #
    # Measured 2026-09-23 across 40 seeds at n = 200: the warning fires every
    # time and the statistic is non-finite NONE of the time — so the warning is
    # NOT a proxy for a bad fit, and it is not used as one.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = coint_johansen(
            np.column_stack([y.to_numpy(), x.to_numpy()]),
            det_order=0,
            k_ar_diff=1,
        )

    discarded_imaginary = sum(
        1 for entry in caught if issubclass(entry.category, np.exceptions.ComplexWarning)
    )

    # The trace statistic for r = 0 is element 0; its critical values are the
    # first row of cvt, whose three columns are the 90%, 95% and 99% tables.
    statistic = float(result.lr1[0])
    thresholds: _Criticals = (
        float(result.cvt[0][0]),
        float(result.cvt[0][1]),
        float(result.cvt[0][2]),
    )

    if not math.isfinite(statistic) or not all(math.isfinite(value) for value in thresholds):
        raise ValueError(
            f"Johansen's trace test returned non-finite output (statistic "
            f"{statistic!r}, critical values {thresholds!r}). There is no verdict "
            f"to derive from it."
        )

    # cvt columns are ordered 90%, 95%, 99% — so a 5% test reads column 1 and a
    # 1% test reads column 2. Indexed explicitly for the same reason the
    # Engle-Granger path is: a transposed comparison inverts every verdict while
    # the function keeps running.
    position = _johansen_significance_position(alpha)
    is_rejected = statistic > thresholds[position]
    return statistic, math.nan, thresholds, is_rejected, discarded_imaginary


def _johansen_significance_position(alpha: float) -> int:
    """Map a size to its index in ``cvt``'s 90%/95%/99% columns.

    The ordering is the reverse of Engle-Granger's: Johansen's statistic is
    rejected when it is **larger** than the critical value, and the columns run
    from the loosest size (90%, index 0) to the strictest (99%, index 2). A size
    looser than 10% uses index 0 and one stricter than 1% uses index 2, which is
    a clamp — but unlike the Engle-Granger path this test only ASKS whether a
    relationship exists at all, so a clamp cannot change a published p-value,
    because none is published.
    """
    if alpha <= 0.01:
        return 2
    if alpha <= 0.05:
        return 1
    return 0


def _regime_stability(
    y: pd.Series,
    x: pd.Series,
    *,
    method: str,
    trend: str,
    alpha: float,
    split_fraction: float,
    minimum: float,
) -> _RegimeStability:
    """Re-test the relationship on the two halves of the sample. Section 15.18-F.

    **What this check can and cannot establish, stated first.** It compares the
    two sub-samples' **support for cointegration** — did the same test reject in
    both halves? — and nothing else. It is **not** a structural-break test:
    detecting a break needs a test whose null is "no break" (Chow, Bai-Perron,
    Gregory-Hansen), and none is run here. What this does is the cheap,
    honest version: if the relationship is absent in one half, the full-sample
    statistic is an average over two different worlds, and that is exactly the
    failure mode Section 15.18-F's first mandatory warning describes.

    **Why only the SUPPORT is compared and never the two p-values.** A
    half-sample test is not a test at the full-sample size, and neither half's
    p-value is comparable to the other's or to the full sample's — the
    statistics have different null distributions at different sample lengths.
    Comparing them numerically would be the Section 9 basis error in its purest
    form: same statistic name, different sample, different distribution.
    Comparing the **support** is a property that is comparable across windows,
    because a rejection is a rejection under each window's own critical values.
    The two sub-sample p-values are **reported** so a reader can see them, but
    no arithmetic is done on them.

    A half smaller than the configured minimum is **not tested**, and the
    verdict says ``"not_tested"`` rather than guessing — an untested half is an
    absence of information, not evidence of stability.
    """
    split_at = math.floor(len(y) * split_fraction)
    if split_at < minimum or (len(y) - split_at) < minimum:
        return {
            "verdict": "not_tested",
            "agreement": False,
            "split_index": split_at,
            "first_half": None,
            "second_half": None,
            "note": (
                f"Regime stability was NOT tested: a split at {split_fraction:.0%} "
                f"would leave a half of {min(split_at, len(y) - split_at)} "
                f"observations, below the configured floor of {minimum:.0f}. An "
                f"untested half is an absence of information, not evidence that the "
                f"relationship is stable."
            ),
        }

    halves: list[_HalfSample] = []
    for label, frame in (
        ("first_half", y.iloc[:split_at]),
        ("second_half", y.iloc[split_at:]),
    ):
        other = x.iloc[:split_at] if label == "first_half" else x.iloc[split_at:]
        try:
            if method == "johansen":
                rejected = _run_johansen(frame, other, alpha=alpha)[3]
                p_value: float | None = None
            else:
                output = _run_engle_granger(frame, other, trend=trend, alpha=alpha)
                rejected = output[3]
                p_value = round(float(output[1]), 6)
        except ValueError as exc:
            halves.append(
                {
                    "label": label,
                    "n_obs": len(frame),
                    "is_cointegrated": None,
                    "p_value": None,
                    "refused": str(exc),
                }
            )
            continue
        halves.append(
            {
                "label": label,
                "n_obs": len(frame),
                "is_cointegrated": rejected,
                "p_value": p_value,
                "refused": None,
            }
        )

    refused = [entry for entry in halves if entry["refused"] is not None]
    supports = [entry["is_cointegrated"] for entry in halves]

    if refused or any(value is None for value in supports):
        verdict = "not_tested"
        agreement = False
        note = (
            "Regime stability could not be evaluated: at least one half-sample "
            "failed its own validation, so no comparison is available. The half "
            "that did run is reported, but a verdict needs both."
        )
    elif supports[0] and supports[1]:
        verdict = "stable"
        agreement = True
        note = (
            "Both halves independently support cointegration, so the full-sample "
            "rejection is not an artefact of one sub-period. This is SUPPORT, not "
            "proof of stability: two halves agreeing is weaker than a break test, "
            "and a break that falls near the split point is invisible to it."
        )
    elif not supports[0] and not supports[1]:
        verdict = "absent_in_both_halves"
        agreement = True
        note = (
            "NEITHER half supports cointegration, yet the full-sample test is "
            "reported beside this. A full-sample rejection that neither half "
            "reproduces is the clearest possible sign that the statistic is driven "
            "by the time-average rather than by a relationship — treat the "
            "full-sample result as unreliable."
        )
    else:
        verdict = "unstable"
        agreement = False
        note = (
            "THE TWO HALVES DISAGREE: the relationship is supported in one "
            "sub-period and not the other. The full-sample statistic is an average "
            "over two different regimes, which is precisely the failure Section "
            "15.18-F's first warning describes — this is the LTCM shape in a "
            "two-way split."
        )

    return {
        "verdict": verdict,
        "agreement": agreement,
        "split_index": split_at,
        "first_half": halves[0],
        "second_half": halves[1],
        "note": note,
    }


def _multiple_testing_summary(*, alpha: float, family_size: int) -> _MultipleTesting:
    """The multiple-testing obligation, COMPUTED rather than narrated.

    Section 15.18-F makes this a counting obligation, so the counts are produced
    here. For a family of ``m`` independent tests each at size ``alpha``, under
    the global null that **no pair is cointegrated**:

    * ``P(at least one false positive) = 1 - (1 - alpha)**m`` — the family-wise
      error rate (Sidak's exact form for independent tests).
    * the per-test size that holds the family-wise rate at ``alpha`` is
      ``1 - (1 - alpha)**(1/m)``.

    At ``alpha = 0.05`` and ``m = 10`` those are ``0.4013`` and ``0.005116`` —
    i.e. **a 40% chance of at least one spurious "cointegrated" pair** from a
    universe of ten series with no true relationship anywhere in it. That is the
    number that makes the warning checkable, and it is why the warning quotes a
    figure rather than an adjective.

    **``family_size`` is an assumption, not a measurement, and it is published as
    such.** This function tests ONE pair and has no way to know how many the
    caller has run or intends to run. The configured value is a stated default
    the caller is expected to override; the field name is
    ``family_size_assumed`` so a consumer cannot mistake it for a count of tests
    actually performed here.

    The formula is the **independent**-test form. Pairwise tests over a universe
    share series and are therefore correlated, which makes ``1 - (1-alpha)**m``
    an **upper bound** on the true family-wise rate — the correlation reduces
    it. So the correction is conservative in the safe direction, and the
    limitations say so rather than implying the bound is exact.
    """
    if family_size < 1:
        raise ValueError(
            f"econometrics.assumed_test_family_size must be at least 1, got "
            f"{family_size}. A family of zero tests has no error rate to correct."
        )
    family_wise = 1.0 - (1.0 - alpha) ** family_size
    corrected = 1.0 - (1.0 - alpha) ** (1.0 / family_size)
    return {
        "family_size": family_size,
        "family_wise_error_rate": round(min(1.0, family_wise), 8),
        "corrected_size": round(corrected, 8),
    }


def _cointegration_warnings(
    *,
    method: str,
    is_rejected: bool,
    spread_reading: _SpreadReading | None,
    half_life: _HalfLife,
    stability: _RegimeStability,
    multiple_testing: _MultipleTesting,
    alpha: float,
    n_obs: int,
    discarded_imaginary: int,
) -> list[str]:
    """The conditions of *this* run — PLUS the two warnings that fire on every run.

    **The ordering is deliberate and is part of the contract.** The two
    Section 15.18-F warnings come FIRST, unconditionally, because they are
    properties of the method rather than conditions of the run: a consumer must
    never be able to obtain a result that lacks them, and putting them first
    means a downstream truncation or a "show the top warning" UI cannot drop
    them. The run-specific conditions follow.

    This is the one place in the module where a warning is unconditional, and
    the distinction from the limitations convention is worth stating: the
    standing caveats in ``_cointegration_limitations`` are things the result
    **cannot** tell you; these two are things the result **actively invites you
    to get wrong**, so they belong where a consumer already looks for signal.
    """
    family_size = multiple_testing["family_size"]
    family_wise = multiple_testing["family_wise_error_rate"]
    corrected = multiple_testing["corrected_size"]

    found: list[str] = [
        # (a) MANDATORY, every call.
        "COINTEGRATION IS A BACKWARD-LOOKING ESTIMATE THAT BREAKS IN REGIME "
        "CHANGE. This statistic describes the sample window it was computed on; "
        "it is not a forecast that the spread will converge in future. The trades "
        "for which this warning matters most are precisely the ones built on long, "
        "clean histories — LTCM's convergence trades rested on spreads that had "
        "been stationary for years and stopped being so when the regime turned. A "
        "spread that has never broken is not evidence that it cannot break; it is "
        "evidence that the sample predates the break.",
        # (b) MANDATORY, every call — and a COUNTING obligation, not a string.
        f"MULTIPLE PAIRWISE TESTS NEED A MULTIPLE-TESTING CORRECTION. Section "
        f"15.18-F requires this warning on every call because the correction is a "
        f"property of the FAMILY, not of this pair — this function tests one pair "
        f"and cannot see the others. Stated at alpha = {alpha:.4f} and an assumed "
        f"family of {family_size} tests: under the global null (no pair "
        f"cointegrated) the family-wise error rate is 1 - (1 - {alpha:.4f})^"
        f"{family_size} = {family_wise:.4f}, so the chance of at least one "
        f"spurious 'cointegrated' pair is {family_wise:.1%}. Holding that at "
        f"{alpha:.4f} requires a per-test size of "
        f"1 - (1 - {alpha:.4f})^(1/{family_size}) = {corrected:.8f}. "
        f"THE FAMILY SIZE IS AN ASSUMPTION THIS FUNCTION CANNOT VERIFY — override "
        f"it with your real count of tests before using the corrected size. And "
        f"do not rank a family of pairs by p-value and keep the smallest: that is "
        f"selection on the statistic, and it rejects at roughly the nominal rate "
        f"per test regardless of whether any relationship exists.",
    ]

    if method == "johansen":
        found.append(
            "JOHANSEN REPORTS NO P-VALUE: the statistic is compared against a "
            "simulated critical-value table, not against a distribution with a "
            "closed-form CDF, so `p_value` is reported as non-finite rather than "
            "interpolated from the three published sizes. The verdict "
            "(`is_cointegrated`) is derived from the critical values — the "
            "comparison that is actually available — and is the field to read. "
            "Do not treat the non-finite p-value as a missing-input error."
        )
        if discarded_imaginary > 0:
            # Disclosed because it was CAPTURED. Suppressing a warning and saying
            # nothing is the failure this replaces: the number is on the record,
            # and the interpretation is stated rather than left to the reader.
            found.append(
                f"JOHANSEN'S EIGENDECOMPOSITION DISCARDED COMPLEX RESIDUE "
                f"({discarded_imaginary} ComplexWarnings from statsmodels' "
                f"internal `np.linalg.eig`). This is UNCONDITIONAL statsmodels "
                f"behaviour — it fires on every Johansen call, at every sample "
                f"size, including on well-conditioned pairs — and measured "
                f"2026-09-23 it never coincided with a non-finite statistic. It is "
                f"disclosed so that it is not mistaken for a defect in THIS pair, "
                f"and because a warning that escapes this function would be raised "
                f"as an error under `-W error`. It is not a signal about the fit "
                f"and must not be read as one."
            )

    if stability["verdict"] == "unstable":
        found.append(
            "REGIME INSTABILITY DETECTED in the sample itself: the two halves "
            "disagree about whether the pair is cointegrated (see "
            "`regime_stability` on the value). The full-sample statistic is an "
            "average over two different relationships. This is the two-way "
            "version of the backward-looking warning above, found IN this window "
            "rather than left as a caveat about future windows."
        )
    elif stability["verdict"] == "absent_in_both_halves":
        found.append(
            "THE FULL-SAMPLE RESULT IS NOT REPRODUCED BY EITHER HALF. Neither "
            "sub-period independently supports cointegration, so the full-sample "
            "statistic is being driven by the time-average across the split "
            "rather than by a relationship that holds in either part. Treat the "
            "full-sample verdict as unreliable."
        )
    elif stability["verdict"] == "not_tested":
        found.append(
            "REGIME STABILITY WAS NOT TESTED — the configured split would leave a "
            "sub-sample below the configured observation floor. This is an "
            "absence of information, not evidence of stability; the full-sample "
            "rejection stands unqualified by any sub-period check."
        )

    if half_life["periods"] is None:
        found.append(
            f"NO HALF-LIFE IS REPORTED. {half_life['note']} Without it there is no "
            f"estimate of how long a convergence trade would take, which is the "
            f"quantity the horizon of any such trade is set against."
        )
    else:
        disclosure = _half_life_disclosure(half_life, int(n_obs))
        if disclosure is not None:
            found.append(disclosure)

    if spread_reading is not None:
        if not spread_reading["is_stationary"]:
            found.append(
                f"THE SPREAD DID NOT READ AS STATIONARY under its own ADF "
                f"(statistic {spread_reading['statistic']:+.4f}, p = "
                f"{spread_reading['p_value']:.4f}). The verdict above should be "
                f"consistent with that — if the cointegration test rejects but the "
                f"spread does not read stationary, one of the two is being driven "
                f"by the deterministic terms, and the rejection is not corroborated."
            )
        if spread_reading["design_was_ill_conditioned"]:
            found.append(
                "THE SPREAD'S ADF REGRESSION WAS RANK-DEFICIENT (statsmodels "
                "raised SingularMatrixWarning). The statistic was still produced, "
                "from a degenerate design — reported rather than withheld, but it "
                "is not an ordinary result."
            )

    if not is_rejected:
        found.append(
            f"NO COINTEGRATION DETECTED at alpha = {alpha:.4f}. This is not "
            f"evidence that the pair is independent: failing to reject is an "
            f"absence of evidence, and the Engle-Granger procedure has LOW POWER "
            f"against a slowly-reverting alternative — a genuine but weak "
            f"relationship in a short sample reads exactly like no relationship."
        )

    return found


def _cointegration_interpretation(
    y_name: str,
    x_name: str,
    method: str,
    is_rejected: bool,
    alpha: float,
    p_value: float,
) -> str:
    """Plain-language meaning of the verdict, naming both series and the method."""
    label = "Engle-Granger" if method == "engle_granger" else "Johansen"
    if is_rejected:
        p_description = (
            f"p = {p_value:.4f}" if math.isfinite(p_value) else "via the critical values"
        )
        return (
            f"{label}: '{y_name}' and '{x_name}' ARE cointegrated at alpha = "
            f"{alpha:.4f} ({p_description}). Their levels share a common "
            f"stochastic trend, so a linear combination of them is stationary — the "
            f"spread published here. A rejection says the spread's deviations have "
            f"been bounded over THIS window; it does not say how long they take to "
            f"close, which is what the half-life estimates, nor that the "
            f"relationship survives a regime change."
        )
    if not math.isfinite(p_value):
        return (
            f"{label}: no cointegration is detected between '{y_name}' and "
            f"'{x_name}' at alpha = {alpha:.4f} (the trace statistic did not exceed "
            f"its critical value). This is an absence of evidence, not evidence of "
            f"independence."
        )
    return (
        f"{label}: no cointegration is detected between '{y_name}' and '{x_name}' at "
        f"alpha = {alpha:.4f} (p = {p_value:.4f}). Failing to reject is an absence "
        f"of evidence, not evidence that the pair is independent — the procedure has "
        f"low power against a slowly-reverting spread."
    )


def _cointegration_limitations() -> list[str]:
    """What a cointegration verdict cannot tell you, on every call.

    Standing caveats, distinct from ``warnings`` (a condition of this run).
    Section 15.18-F's two mandatory warnings live in the warnings list instead:
    they are hazards the result invites rather than limits on what it says.
    """
    return [
        "I(1) IS ASSUMED, NOT TESTED. The procedure presumes both series are "
        "integrated of order one and that a Granger representation exists. An "
        "I(0) series tested for cointegration with an I(1) series, or two series "
        "of different integration orders, is a specification error this test "
        "cannot detect. Run test_stationarity on each level first.",
        "ENGLE-GRANGER'S TWO-STEP ESTIMATE IS BIASED TOWARDS FINDING "
        "COINTEGRATION. The residual it ADFs is estimated rather than observed, "
        "and the first step is chosen to make that residual as small as "
        "possible — so the residual inherits an artificially low variance and the "
        "reported support overstates the evidence. The ADF p-value on the spread "
        "published here carries ordinary ADF critical values and is therefore too "
        "small; the `coint` p-value, which uses the correct non-standard "
        "distribution, is the one to read.",
        "ONLY A PAIR IS TESTED. On more than two series, a pair that tests as "
        "cointegrated may be an artefact of a relationship with a third series "
        "that is not in the test. Multi-series systems need a vector method "
        "(Johansen), and even then the COUNT of cointegrating vectors matters as "
        "much as their existence.",
        "THE MULTIPLE-TESTING CORRECTION ASSUMES INDEPENDENT TESTS. Pairwise "
        "tests over a shared universe are positively correlated, which makes the "
        "family-wise rate reported here an UPPER BOUND rather than an exact "
        "figure. It is conservative in the safe direction, but it is a bound.",
        "THE REGIME-STABILITY CHECK IS A TWO-WAY SPLIT, NOT A BREAK TEST. It "
        "compares the two halves' support for cointegration; it cannot locate a "
        "break, cannot see one that falls near the split point, and cannot "
        "distinguish a gradual decay of the relationship from a single shift. "
        "Detecting a break needs a test whose null is 'no break' (Chow, "
        "Bai-Perron, Gregory-Hansen), none of which is run here.",
        "COINTEGRATION IS NOT AN ECONOMIC MECHANISM. Two series can share a "
        "stochastic trend for reasons with no economic content — a common "
        "deflator, a shared accounting identity, or a third driver neither "
        "series names. The test measures a statistical property of the sample; "
        "Section 15.18's mechanism-first ordering applies here exactly as it "
        "does to run_regression.",
    ]
