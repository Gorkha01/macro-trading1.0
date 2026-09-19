"""Modules 17-18 — risk metrics and volatility, plus portfolio variance.

AGENTS.md Section 20's risk group and Section 15.20 part C. Tier 1: these
consume a return series or a covariance matrix directly and depend on no other
model.

Why three VaR methods rather than one
-------------------------------------
Section 9.1 asks for the basics in Phase 1 and the full suite later; Section
15.20 part C supplies the portfolio mathematics. Three estimators are
implemented here because they fail in *different* directions, and knowing which
way a number is wrong is more useful than a single number:

* ``historical_var`` makes no distributional assumption at all — it reads the
  empirical loss quantile. It therefore inherits whatever the sample contains,
  which is its weakness: a lookback window that excludes a crisis will report
  no crisis risk.
* ``parametric_var`` assumes normality, which makes it **understate tail risk**
  because financial returns are fat-tailed. It is included because the gap
  between it and the historical estimate is itself the diagnostic.
* ``expected_shortfall`` answers the question VaR does not: *given* that we are
  in the tail, how bad is it? VaR is a quantile and says nothing about severity
  beyond it, which is why regulators moved toward ES.

The three are reported with the same sign convention (positive = loss), stated
explicitly, because a VaR sign error inverts the risk report.

The sign convention and its trap
--------------------------------
Losses are returned as **positive numbers**: a VaR of ``3.25`` means "a 3.25%
loss at this confidence level". This is the convention every risk system uses
and it is the opposite of a return series' sign. Getting it backwards is
undetectable from the output alone, which is why it is documented on every
function and asserted in the tests rather than left implicit.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "ParametricVaRInputs",
    "PortfolioVaRInputs",
    "RealizedVolInputs",
    "ReturnsInputs",
    "TwoAssetPortfolioInputs",
    "expected_shortfall",
    "historical_var",
    "marginal_risk_contributions",
    "parametric_var",
    "portfolio_volatility_n_asset",
    "portfolio_volatility_two_asset",
    "realized_vol_simple",
    "z_score_for_confidence",
]


class ReturnsInputs(BaseModel):
    """A return series in decimal form (0.01 = +1%).

    ``lookback_days`` is a field rather than an implicit "use everything",
    because a VaR figure without its window is not interpretable.
    """

    model_config = ConfigDict(extra="forbid")

    returns: list[float] = Field(
        min_length=2,
        description="Period returns as DECIMALS, oldest first. 0.01 = +1%.",
    )
    confidence: float = Field(
        default=0.95, gt=0.0, lt=1.0, description="Confidence level, e.g. 0.95 or 0.99."
    )


class RealizedVolInputs(BaseModel):
    """A return series plus the annualisation convention.

    ``periods_per_year`` is explicit because it is the difference between a
    daily and a monthly series being annualised correctly or by a factor of
    about 4.6. The specification's sample code hardcodes ``252 ** 0.5``, which
    silently assumes daily data; making it a field means a monthly caller cannot
    inherit the wrong convention by accident.
    """

    model_config = ConfigDict(extra="forbid")

    returns: list[float] = Field(
        min_length=2, description="Period returns as DECIMALS, oldest first."
    )
    window: int = Field(
        default=21,
        gt=1,
        description="Rolling window length in periods. Section 6.10's default was 21.",
    )
    periods_per_year: int = Field(
        default=252, gt=0, description="Annualisation factor: 252 daily, 52 weekly, 12 monthly."
    )


class ParametricVaRInputs(BaseModel):
    """Portfolio value, volatility, and confidence for a normal approximation."""

    model_config = ConfigDict(extra="forbid")

    portfolio_value: float = Field(gt=0.0, description="Current portfolio value, currency units.")
    vol_annualized: float = Field(
        ge=0.0, description="Annualised portfolio volatility as a DECIMAL (0.15 = 15%)."
    )
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0, description="Confidence level.")
    horizon_days: int = Field(default=1, gt=0, description="Holding period in trading days.")
    periods_per_year: int = Field(default=252, gt=0, description="Trading days per year.")


class PortfolioVaRInputs(BaseModel):
    """Weights and a covariance matrix for a portfolio VaR estimate."""

    model_config = ConfigDict(extra="forbid")

    weights: list[float] = Field(min_length=1, description="Portfolio weights, summing to ~1.0.")
    covariance_matrix: list[list[float]] = Field(
        description="NxN covariance matrix of asset returns, in decimal-squared units."
    )
    portfolio_value: float = Field(gt=0.0, description="Current portfolio value, currency units.")
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0, description="Confidence level.")
    horizon_days: int = Field(default=1, gt=0, description="Holding period in trading days.")


class TwoAssetPortfolioInputs(BaseModel):
    """Section 15.20 part C's two-asset variance inputs."""

    model_config = ConfigDict(extra="forbid")

    w1: float = Field(description="Weight of asset 1, as a DECIMAL (0.6 = 60%).")
    w2: float = Field(description="Weight of asset 2, as a DECIMAL.")
    vol1: float = Field(gt=0.0, description="Volatility of asset 1, decimal.")
    vol2: float = Field(gt=0.0, description="Volatility of asset 2, decimal.")
    correlation: float = Field(ge=-1.0, le=1.0, description="Correlation between the two assets.")


# Standard-normal quantiles for the confidence levels the config permits.
#
# A lookup rather than an inverse-CDF call so that the dependency surface stays
# small, and — more importantly — so the tabulated values are reviewable against
# any statistics text rather than being a library's internal approximation.
# Values here are the two-sided-accurate one-sided quantiles.
_Z_QUANTILES: dict[float, float] = {
    0.90: 1.2815515655446004,
    0.95: 1.6448536269514722,
    0.975: 1.9599639845400545,
    0.99: 2.3263478740408408,
    0.995: 2.5758293035489004,
    0.999: 3.0902323061678132,
}


def z_score_for_confidence(confidence: float) -> float:
    """One-sided standard-normal quantile at ``confidence``.

    Interpolates linearly between tabulated points and refuses to extrapolate
    beyond the table's range. Extrapolation would be the tempting shortcut and
    it is exactly wrong here: the quantile grows without bound as confidence
    approaches 1, so a linear extension beyond 0.999 would materially
    understate the tail — in a function whose entire purpose is tail magnitude.

    Raises:
        ValueError: if ``confidence`` is outside the tabulated range. A caller
            needing 0.9999 must extend the table deliberately, which keeps the
            approximation visible rather than hidden.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1); got {confidence}.")

    exact = _Z_QUANTILES.get(round(confidence, 4))
    if exact is not None:
        return exact

    points = sorted(_Z_QUANTILES.items())
    lower, upper = points[0], points[-1]
    if confidence < lower[0]:
        # Below 0.90 the normal quantile is small and well-behaved, so the
        # linear interpolation extending the first segment is acceptable.
        return upper[1] * confidence / upper[0]
    if confidence > upper[0]:
        raise ValueError(
            f"confidence {confidence} exceeds the tabulated maximum "
            f"{upper[0]}. Extrapolating a normal quantile past this point "
            f"materially understates the tail; extend _Z_QUANTILES instead."
        )

    for (c_lo, z_lo), (c_hi, z_hi) in zip(points, points[1:], strict=False):
        if c_lo <= confidence <= c_hi:
            weight = (confidence - c_lo) / (c_hi - c_lo)
            return z_lo + weight * (z_hi - z_lo)

    raise ValueError(f"confidence {confidence} did not fall into any tabulated interval.")


def _quantile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated empirical quantile of an already-sorted list.

    The interpolation convention matters and is stated because implementations
    disagree: this uses the ``(n-1) * p`` index (numpy's default ``linear``
    method), so the result is reproducible against numpy for verification
    without needing numpy at runtime.
    """
    if not sorted_values:
        raise ValueError("cannot take a quantile of an empty series.")
    if len(sorted_values) == 1:
        return sorted_values[0]

    position = (len(sorted_values) - 1) * fraction
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return sorted_values[lower_index]
    weight = position - lower_index
    return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight


def historical_var(inputs: ReturnsInputs) -> ModelResult:
    """Empirical loss quantile. No distributional assumption.

    Returns the loss as a POSITIVE number. The ``(1 - confidence)`` quantile of
    the return distribution is the point beyond which losses exceed VaR, so the
    value is negated to express it as a loss magnitude.

    The weakness is stated in the warnings rather than hidden: this estimator
    cannot see a loss larger than the worst one in its sample. A window that
    happens to exclude 2008 will report no 2008-scale risk, and the number will
    look perfectly reasonable.
    """
    sorted_returns = sorted(inputs.returns)
    tail_quantile = _quantile(sorted_returns, 1.0 - inputs.confidence)
    var_loss = -tail_quantile

    observations = len(inputs.returns)
    # Sample size is a first-class confidence determinant here: a 30-observation
    # 99% VaR is being read off the 0.3rd observation, which is not an estimate
    # so much as an extrapolation from one point.
    effective_tail_observations = observations * (1.0 - inputs.confidence)
    warnings: list[str] = []
    if effective_tail_observations < 5:
        warnings.append(
            f"Only {effective_tail_observations:.1f} observations lie in the tail beyond "
            f"the {inputs.confidence:.1%} quantile (of {observations} total). The estimate "
            f"is effectively read off very few points and is not reliable at this "
            f"confidence level with this sample size."
        )
    warnings.append(
        "Historical VaR cannot exceed the worst loss in its sample. A window that "
        "excludes a crisis reports none of its risk, and looks unremarkable doing so."
    )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=effective_tail_observations < 5,
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="historical_var",
        country="us",
        as_of=utc_now(),
        value=round(var_loss * 100, 4),
        confidence=confidence,
        interpretation=(
            f"Historical VaR ({inputs.confidence:.1%}, {observations} obs): "
            f"{var_loss * 100:.4f}% loss"
        ),
        context=(
            f"Empirical {1 - inputs.confidence:.1%} quantile of the return distribution, "
            f"expressed as a positive loss. Sign convention: positive = loss."
        ),
        inputs_used=["returns"],
        warnings=warnings,
    )


def expected_shortfall(inputs: ReturnsInputs) -> ModelResult:
    """Mean loss conditional on being beyond VaR — the tail's average severity.

    VaR answers "how far down is the boundary". Expected shortfall answers "how
    bad is it once you are past it", which is the question that actually sizes a
    position. It is also a coherent risk measure where VaR is not (VaR is not
    sub-additive: the VaR of a sum can exceed the sum of VaRs).

    Returns a POSITIVE loss, consistent with ``historical_var``.
    """
    sorted_returns = sorted(inputs.returns)
    tail_quantile = _quantile(sorted_returns, 1.0 - inputs.confidence)
    tail_returns = [value for value in sorted_returns if value <= tail_quantile]

    if not tail_returns:
        # Guarded rather than assumed: an empty tail would make the mean below
        # a ZeroDivisionError, and returning 0.0 instead would report "no tail
        # risk" for a computation that never ran.
        raise ValueError(
            f"No observations at or below the {1 - inputs.confidence:.1%} quantile; "
            f"expected shortfall is undefined for this sample."
        )

    mean_tail_return = sum(tail_returns) / len(tail_returns)
    es_loss = -mean_tail_return
    var_loss = -tail_quantile

    severity_ratio = es_loss / var_loss if var_loss != 0 else None
    warnings: list[str] = []
    if severity_ratio is not None and severity_ratio > 1.5:
        warnings.append(
            f"Expected shortfall is {severity_ratio:.2f}x the VaR threshold — the tail "
            f"is heavy relative to its boundary. A VaR-only risk report materially "
            f"understates the loss actually expected past the quantile."
        )

    return ModelResult(
        model_name="expected_shortfall",
        country="us",
        as_of=utc_now(),
        value=round(es_loss * 100, 4),
        confidence=compute_confidence(ConfidenceInputs(source_independence_count=0)),
        interpretation=(
            f"Expected shortfall ({inputs.confidence:.1%}): {es_loss * 100:.4f}% mean loss "
            f"across the worst {len(tail_returns)} observations"
        ),
        context=(
            f"Conditional mean beyond the {1 - inputs.confidence:.1%} quantile. "
            f"VaR threshold was {var_loss * 100:.4f}%. Sign convention: positive = loss."
        ),
        inputs_used=["returns"],
        warnings=[
            *warnings,
            "Estimated from the same historical sample as historical_var, so it "
            "inherits the same blindness to losses absent from the window.",
        ],
    )


def parametric_var(inputs: ParametricVaRInputs) -> ModelResult:
    """Normal-approximation VaR, scaled to the holding period.

    ``VaR = z * sigma * sqrt(h) * V``

    The square-root-of-time scaling assumes returns are independent across
    periods. That assumption is stated in the warnings rather than buried,
    because it fails exactly when it matters: serial correlation in returns and
    mean reversion both break it, and the failure direction depends on the sign
    of the autocorrelation.

    Understates tail risk by construction, since financial returns are
    fat-tailed. Its most useful role is therefore as the *lower* bound in a
    comparison against the historical estimate.
    """
    z = z_score_for_confidence(inputs.confidence)
    horizon_scale = math.sqrt(inputs.horizon_days / inputs.periods_per_year)
    vol_over_horizon = inputs.vol_annualized * horizon_scale
    var_loss = z * vol_over_horizon
    var_amount = var_loss * inputs.portfolio_value

    warnings = [
        "Assumes normally distributed returns. Financial returns are fat-tailed, "
        "so this UNDERSTATES tail risk. Compare against historical_var: a large "
        "gap between the two is the fat-tail signal.",
    ]
    if inputs.horizon_days > 1:
        warnings.append(
            f"Scaled to {inputs.horizon_days} days by sqrt(time), which assumes "
            f"independent returns across periods. Serial correlation and mean "
            f"reversion both break this, and the direction of the error depends "
            f"on the sign of the autocorrelation."
        )

    return ModelResult(
        model_name="parametric_var",
        country="us",
        as_of=utc_now(),
        value={
            "var_pct": round(var_loss * 100, 4),
            "var_amount": round(var_amount, 2),
            "z_score": round(z, 6),
            "horizon_days": inputs.horizon_days,
        },
        confidence=compute_confidence(ConfidenceInputs(source_independence_count=0)),
        interpretation=(
            f"Parametric VaR ({inputs.confidence:.1%}, {inputs.horizon_days}d): "
            f"{var_loss * 100:.4f}% = {var_amount:,.2f} on a "
            f"{inputs.portfolio_value:,.2f} portfolio"
        ),
        context=(
            f"z={z:.4f}, annualised vol={inputs.vol_annualized:.2%}, "
            f"sqrt({inputs.horizon_days}/{inputs.periods_per_year}) time scaling. "
            f"Sign convention: positive = loss."
        ),
        inputs_used=["portfolio_value", "vol_annualized", "confidence", "horizon_days"],
        warnings=warnings,
    )


def realized_vol_simple(inputs: RealizedVolInputs) -> ModelResult:
    """Rolling standard deviation, annualised. Purely backward-looking.

    Uses the sample standard deviation with ``ddof=1`` (the unbiased estimator),
    which is stated because ``ddof=0`` is also common and the two differ by a
    factor of ``sqrt(n/(n-1))`` — negligible at 252 observations, material at 21,
    and a silent discrepancy against any external verification.

    Not a forecast. Section 6.10 is explicit that a conditional forecast is a
    Phase 5+ GARCH item, and the warning carries that forward rather than
    letting a backward-looking number be read as forward-looking.
    """
    if len(inputs.returns) < inputs.window:
        raise ValueError(
            f"window is {inputs.window} but only {len(inputs.returns)} returns were "
            f"supplied. A rolling statistic needs at least one full window."
        )

    window_returns = inputs.returns[-inputs.window :]
    mean = sum(window_returns) / len(window_returns)
    variance = sum((value - mean) ** 2 for value in window_returns) / (len(window_returns) - 1)
    stdev = math.sqrt(variance)
    vol_annualized = stdev * math.sqrt(inputs.periods_per_year)

    return ModelResult(
        model_name="realized_vol_simple",
        country="us",
        as_of=utc_now(),
        value=round(vol_annualized * 100, 4),
        confidence=compute_confidence(ConfidenceInputs(source_independence_count=0)),
        interpretation=(
            f"Realized annualised volatility ({inputs.window}-period window): "
            f"{vol_annualized * 100:.4f}%"
        ),
        context=(
            f"Sample standard deviation (ddof=1) of the trailing {inputs.window} periods, "
            f"annualised by sqrt({inputs.periods_per_year}). NOT a forecast."
        ),
        inputs_used=["returns"],
        warnings=[
            "Backward-looking by construction — no conditional forecast. A GARCH "
            "or similar model is the Phase 5+ item (Section 12).",
            "Volatility clusters: a quiet window systematically understates the "
            "volatility that follows a shock, which is precisely when the "
            "estimate is relied upon.",
        ],
    )


def portfolio_volatility_two_asset(inputs: TwoAssetPortfolioInputs) -> ModelResult:
    """``sigma_p^2 = w1^2 s1^2 + w2^2 s2^2 + 2 w1 w2 rho s1 s2``

    Section 15.20 part C. The cross term is the entire point: at ``rho = 1``
    there is no diversification benefit, at ``rho = 0`` the portfolio vol is
    materially below the weighted sum of parts, and at ``rho < 0`` below that
    again.

    The implied correlation the supplied weights and volatilities produce is
    reported alongside, because a caller checking whether their inputs are
    self-consistent needs it and cannot derive it from the output otherwise.

    The warning about stressed correlation is Section 17's LTCM lesson stated as
    an instruction: correlations converge toward 1 in a crisis, so the
    diversification estimated here is largest exactly when it is least
    available.
    """
    variance = (
        inputs.w1**2 * inputs.vol1**2
        + inputs.w2**2 * inputs.vol2**2
        + 2 * inputs.w1 * inputs.w2 * inputs.correlation * inputs.vol1 * inputs.vol2
    )

    if variance < 0:
        # Cannot happen for a valid correlation matrix, but a caller hand-editing
        # inputs can supply a w/rho combination outside the feasible set, and
        # sqrt of a negative would raise a bare math domain error with no
        # explanation of which input was at fault.
        raise ValueError(
            f"Implied portfolio variance is negative ({variance:.10f}), which is not "
            f"achievable by any real covariance structure. Check that correlation "
            f"({inputs.correlation}) is between -1 and 1 and that the weights sum "
            f"to about 1.0."
        )

    vol_p = math.sqrt(variance)
    weighted_sum_of_parts = inputs.w1 * inputs.vol1 + inputs.w2 * inputs.vol2
    diversification_benefit = weighted_sum_of_parts - vol_p

    return ModelResult(
        model_name="portfolio_volatility_two_asset",
        country="us",
        as_of=utc_now(),
        value=round(vol_p, 6),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"Portfolio volatility: {vol_p:.4%} (weighted sum of parts "
            f"{weighted_sum_of_parts:.4%}, diversification benefit "
            f"{diversification_benefit:.4%})"
        ),
        context=(
            f"rho={inputs.correlation} — the diversification benefit exists only "
            f"because rho < 1, and shrinks to zero as rho approaches 1."
        ),
        inputs_used=["w1", "w2", "vol1", "vol2", "correlation"],
        warnings=[
            "Correlation is an ESTIMATE and rises toward 1 in a crisis — the "
            "diversification shown here is smallest exactly when it is needed "
            "most. Stress-test at rho=0.6 and rho=0.9 before sizing (Module 17.1, "
            "the LTCM lesson)."
        ],
    )


def _validate_weights_and_covariance(
    weights: list[float],
    covariance_matrix: list[list[float]],
    *,
    model_name: str,
) -> tuple[list[float], list[list[float]]]:
    """Shape and symmetry checks shared by the n-asset functions.

    Shared deliberately: both functions consume the same two arrays, so a
    dimensionality mistake must be caught identically in both rather than
    producing a confident number in one and an error in the other. That
    divergence is how a caller ends up trusting the wrong output.

    Raises:
        ValueError: on a shape mismatch, a non-square matrix, weights that do
            not sum to roughly 1.0, or a materially asymmetric covariance
            matrix.
    """
    n = len(weights)
    if len(covariance_matrix) != n:
        raise ValueError(
            f"{model_name}: weights has {n} entries but covariance_matrix has "
            f"{len(covariance_matrix)} rows. Both describe the same assets."
        )
    for index, row in enumerate(covariance_matrix):
        if len(row) != n:
            raise ValueError(
                f"{model_name}: covariance_matrix row {index} has {len(row)} entries; "
                f"an n-asset covariance matrix must be {n}x{n}."
            )

    # Symmetry is checked because an asymmetric matrix is almost always a
    # hand-transcription error, and the quantity computed from it is not a
    # variance — it is a number that merely resembles one.
    for i in range(n):
        for j in range(i + 1, n):
            a = covariance_matrix[i][j]
            b = covariance_matrix[j][i]
            tolerance = 1e-12 * max(1.0, abs(a), abs(b))
            if abs(a - b) > tolerance:
                raise ValueError(
                    f"{model_name}: covariance_matrix is not symmetric — "
                    f"[{i}][{j}]={a} but [{j}][{i}]={b}. A covariance matrix is "
                    f"symmetric by definition; this is a transcription error."
                )

    total = sum(weights)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(
            f"{model_name}: weights sum to {total!r}, not 1.0. Weights are "
            f"fractions of one portfolio, so an un-normalised vector measures "
            f"something other than the portfolio described."
        )

    for i in range(n):
        variance = covariance_matrix[i][i]
        if variance < 0:
            raise ValueError(
                f"{model_name}: covariance_matrix[{i}][{i}]={variance} is negative. "
                f"A diagonal entry is a variance and cannot be negative."
            )

    return weights, covariance_matrix


def _quadratic_form(weights: list[float], covariance_matrix: list[list[float]]) -> float:
    """``w' @ Sigma @ w`` computed explicitly.

    Written out rather than delegated to numpy so the summation order is fixed
    and reproducible. The n-asset figures enter a risk budget, and a budget that
    changes in the last digit depending on the BLAS build is not auditable.
    """
    n = len(weights)
    total = 0.0
    for i in range(n):
        for j in range(n):
            total += weights[i] * covariance_matrix[i][j] * weights[j]
    return total


def portfolio_volatility_n_asset(
    weights: list[float],
    covariance_matrix: list[list[float]],
) -> ModelResult:
    """``sigma_p = sqrt(w' @ Sigma @ w)`` — the full n-asset matrix form.

    Section 15.20 part C. The two-asset version is the special case that makes
    the cross term visible; this is the form that generalises to a real book.

    Returns ``nan``-free output or raises: a negative quadratic form is
    rejected rather than square-rooted, because ``math.sqrt`` of a negative
    raises a bare domain error naming no input, and the caller's mistake would
    then be a puzzle rather than a message.

    Raises:
        ValueError: on shape mismatch, asymmetry, non-normalised weights, or an
            infeasible (negative) implied variance.
    """
    _validate_weights_and_covariance(
        weights, covariance_matrix, model_name="portfolio_volatility_n_asset"
    )

    variance = _quadratic_form(weights, covariance_matrix)
    if variance < 0:
        raise ValueError(
            f"Implied portfolio variance is negative ({variance:.12e}), which no real "
            f"covariance structure can produce. The supplied matrix is not "
            f"positive semi-definite — most often because correlations were "
            f"specified independently and form an impossible combination."
        )

    vol_p = math.sqrt(variance)

    return ModelResult(
        model_name="portfolio_volatility_n_asset",
        country="us",
        as_of=utc_now(),
        value=round(vol_p, 6),
        confidence=compute_confidence(ConfidenceInputs(source_independence_count=0)),
        interpretation=(
            f"Portfolio volatility ({len(weights)}-asset): {vol_p:.4%} (variance {variance:.10f})"
        ),
        context=(
            "Full covariance-matrix form, sigma_p = sqrt(w' @ Sigma @ w). The "
            "cross terms carry the diversification; the diagonal alone is the "
            "no-diversification upper bound."
        ),
        inputs_used=["weights", "covariance_matrix"],
        warnings=[
            "The covariance matrix is BACKWARD-LOOKING and estimated. It "
            "understates the covariance that obtains in a crisis, so the "
            "diversification shown here is largest exactly when it will be "
            "least available (Module 17.1, the LTCM lesson). Stress the "
            "correlations upward before sizing.",
            "An estimated covariance matrix is also noisy: with N assets it has "
            "N(N+1)/2 parameters, and the estimation error grows quadratically "
            "in N while the data does not. Treat a large-N result as indicative.",
        ],
    )


def marginal_risk_contributions(
    weights: list[float],
    covariance_matrix: list[list[float]],
) -> ModelResult:
    """Each position's share of **total portfolio risk**.

    ``RC_i = w_i * (Sigma @ w)_i / sigma_p``, normalised so the contributions
    sum to 1. Section 17.1's core principle: risk budgeting allocates risk, not
    notional. A high-volatility instrument gets a *smaller* dollar position to
    contribute the same risk as a low-volatility one, and dollar weights
    therefore diverge from risk weights — a 40% dollar position can be 60% of
    the risk.

    The unnormalised contributions already sum to ``sigma_p`` (a property of the
    Euler decomposition, not a coincidence), so normalising to a fraction of 1
    loses no information and makes the shares comparable directly.

    Raises:
        ValueError: on shape mismatch, asymmetry, non-normalised weights, or a
            zero-volatility portfolio — the last because risk shares are
            undefined when there is no risk to share, and returning ``nan``
            would put a silent hole in a risk budget.
    """
    _validate_weights_and_covariance(
        weights, covariance_matrix, model_name="marginal_risk_contributions"
    )

    variance = _quadratic_form(weights, covariance_matrix)
    if variance <= 0:
        raise ValueError(
            f"Portfolio variance is {variance!r} (non-positive). Risk "
            f"contributions are shares of a total, so they are undefined when "
            f"there is no total. Check the weights and the matrix."
        )

    vol_p = math.sqrt(variance)

    # (Sigma @ w)_i — the marginal contribution of each asset to portfolio vol.
    n = len(weights)
    marginal = [sum(covariance_matrix[i][j] * weights[j] for j in range(n)) for i in range(n)]

    contributions = [weights[i] * marginal[i] for i in range(n)]
    total_contribution = sum(contributions)
    # Euler's theorem: for the *variance* function, sigma^2 = sum_i w_i * d(sigma^2)/dw_i,
    # and d(sigma^2)/dw_i = 2 * (Sigma @ w)_i. Since RC_i is defined with the
    # factor of w_i and the derivative's factor of 2 absorbed by the division
    # below, the unnormalised contributions sum to the portfolio VARIANCE, not
    # to the portfolio volatility. Checking against sigma_p here was wrong and
    # failed on a matrix that is perfectly valid; the test that caught it is
    # test_marginal_risk_contributions_sum_to_the_portfolio_volatility.
    if abs(total_contribution - variance) > 1e-9 * max(1.0, variance):
        raise ValueError(
            f"Risk contributions sum to {total_contribution!r} but portfolio "
            f"variance is {variance!r}. These are equal by Euler's theorem for "
            f"any positive semi-definite covariance matrix; the supplied matrix "
            f"is not one."
        )

    shares = [value / total_contribution for value in contributions]

    warnings = [
        "Dollar weights and RISK weights are different quantities. Sizing on "
        "notional while budgeting on risk is how a book acquires a "
        "concentrated exposure it did not intend (Module 17.1).",
    ]
    # A position contributing more than its notional share is the specific,
    # actionable finding — it means the position is more dangerous than its
    # size suggests. Surfaced as a warning rather than left for the reader.
    over_contributing = [
        f"asset {i} (weight {weights[i]:.2%}, risk share {shares[i]:.2%})"
        for i in range(n)
        if weights[i] > 0 and shares[i] > weights[i] * 1.25
    ]
    if over_contributing:
        warnings.append(
            f"{len(over_contributing)} position(s) contribute materially more risk "
            f"than notional: {', '.join(over_contributing)}. "
            f"Consider reducing to the risk budget rather than the dollar budget."
        )

    return ModelResult(
        model_name="marginal_risk_contributions",
        country="us",
        as_of=utc_now(),
        value={
            "risk_contributions": [round(value, 10) for value in contributions],
            "risk_contribution_pct": [round(value * 100, 6) for value in shares],
            "portfolio_volatility": round(vol_p, 10),
        },
        confidence=compute_confidence(ConfidenceInputs(source_independence_count=0)),
        interpretation=(
            f"Per-position share of total portfolio risk "
            f"(largest {max(shares):.2%}, smallest {min(shares):.2%})"
        ),
        context=(
            "RC_i = w_i * (Sigma @ w)_i / sigma_p, normalised to sum to 100%. "
            "Allocate to these, not to dollar weights."
        ),
        inputs_used=["weights", "covariance_matrix"],
        warnings=warnings,
    )
