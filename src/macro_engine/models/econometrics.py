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
from typing import TypedDict

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.api.types import is_bool_dtype, is_numeric_dtype
from pydantic import ConfigDict, Field
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.sm_exceptions import (
    CollinearityWarning,
    InterpolationWarning,
    SingularMatrixWarning,
)
from statsmodels.tsa.stattools import adfuller, coint, kpss
from statsmodels.tsa.tsatools import add_trend

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = ["RegressionResult", "run_regression", "test_cointegration", "test_stationarity"]

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
        limitations=_cointegration_limitations(),
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
        result = adfuller(spread.to_numpy(), regression="n", autolag=_coint_autolag())

    ill_conditioned = any(issubclass(entry.category, SingularMatrixWarning) for entry in caught)
    statistic = float(result[0])
    p_value = float(result[1])
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

    return {
        "periods": round(-math.log(2.0) / phi, 8),
        "phi": round(phi, 8),
        "note": (
            f"AR(1) on the spread: phi = {phi:+.6f} (persistence rho = "
            f"{1.0 + phi:.6f}), so H = -ln(2)/phi = {-math.log(2.0) / phi:.4f} periods."
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
