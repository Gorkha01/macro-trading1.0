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
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

if TYPE_CHECKING:
    from numpy.random import Generator

__all__ = [
    "MonteCarloVaRInputs",
    "ParametricVaRInputs",
    "PortfolioVaRInputs",
    "RealizedVolInputs",
    "ReturnsInputs",
    "StressCorrelationTransform",
    "TwoAssetPortfolioInputs",
    "expected_shortfall",
    "historical_var",
    "marginal_risk_contributions",
    "monte_carlo_var",
    "parametric_var",
    "portfolio_volatility_n_asset",
    "portfolio_volatility_two_asset",
    "realized_vol_simple",
    "z_score_for_confidence",
]


class ReturnsInputs(FiniteInputs):
    """A return series in decimal form (0.01 = +1%).

    ``lookback_days`` is a field rather than an implicit "use everything",
    because a VaR figure without its window is not interpretable.

    Inherits :class:`~macro_engine.models.contracts.FiniteInputs`, so a
    non-finite ELEMENT of ``returns`` is refused at construction (D-139b).
    Measured before the fix: ``historical_var(returns=[-0.05, nan, 0.01, 0.02,
    -0.03])`` published ``value=nan`` — a VaR of ``nan`` reached the risk report
    because ``sorted()`` places ``nan`` unpredictably and the loss quantile can
    land on it. A ``nan`` in a risk sample is not "missing": it silently
    corrupts the quantile, and the D-078 guard cannot fire downstream because
    the non-finiteness is already inside a list.
    """

    model_config = ConfigDict(extra="forbid")

    returns: list[float] = Field(
        min_length=2,
        description="Period returns as DECIMALS, oldest first. 0.01 = +1%.",
    )
    confidence: float = Field(
        default=0.95, gt=0.0, lt=1.0, description="Confidence level, e.g. 0.95 or 0.99."
    )


class RealizedVolInputs(FiniteInputs):
    """A return series plus the annualisation convention.

    ``periods_per_year`` is explicit because it is the difference between a
    daily and a monthly series being annualised correctly or by a factor of
    about 4.6. The specification's sample code hardcodes ``252 ** 0.5``, which
    silently assumes daily data; making it a field means a monthly caller cannot
    inherit the wrong convention by accident.

    Inherits ``FiniteInputs`` (D-139b): a non-finite return ELEMENT would
    otherwise pass straight into the variance and publish a ``nan`` volatility.
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


class ParametricVaRInputs(FiniteInputs):
    """Portfolio value, volatility, and confidence for a normal approximation.

    Inherits ``FiniteInputs`` (D-139b) for consistency with the estimators it
    is compared against; its scalar fields already carry ``gt``/``ge`` bounds
    that reject ``nan``, but ``+inf`` passes ``ge=0.0`` and would publish an
    infinite VaR, so the shared guard is the correct enclosure.
    """

    model_config = ConfigDict(extra="forbid")

    portfolio_value: float = Field(gt=0.0, description="Current portfolio value, currency units.")
    vol_annualized: float = Field(
        ge=0.0, description="Annualised portfolio volatility as a DECIMAL (0.15 = 15%)."
    )
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0, description="Confidence level.")
    horizon_days: int = Field(default=1, gt=0, description="Holding period in trading days.")
    periods_per_year: int = Field(default=252, gt=0, description="Trading days per year.")


class PortfolioVaRInputs(FiniteInputs):
    """Weights and a covariance matrix for a portfolio VaR estimate.

    Inherits ``FiniteInputs`` (D-139b), and this is the class that most needs
    the RECURSIVE branch: ``covariance_matrix`` is a ``list[list[float]]``, so a
    ``nan`` on a diagonal is an element of an element — a one-level scan sees a
    ``list`` there, not a ``float``, and would pass it. A ``nan`` variance then
    produces a ``nan`` portfolio volatility, which is exactly the silent hole in
    a risk budget the guard exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    weights: list[float] = Field(min_length=1, description="Portfolio weights, summing to ~1.0.")
    covariance_matrix: list[list[float]] = Field(
        description="NxN covariance matrix of asset returns, in decimal-squared units."
    )
    portfolio_value: float = Field(gt=0.0, description="Current portfolio value, currency units.")
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0, description="Confidence level.")
    horizon_days: int = Field(default=1, gt=0, description="Holding period in trading days.")


class TwoAssetPortfolioInputs(FiniteInputs):
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
    beyond the table's range **in either direction**. Extrapolation would be the
    tempting shortcut and it is exactly wrong here.

    The refusal is symmetric and that symmetry is the point. Above the table the
    quantile grows without bound as confidence approaches 1, so a linear
    extension past 0.999 would materially understate the tail — in a function
    whose entire purpose is tail magnitude. Below the table the failure is the
    mirror image and just as severe: an earlier version of this function
    extended the *first* segment by scaling the **last** tabulated point
    (``3.0902 · c / 0.999``), which is the secant through the origin and the
    0.999 point rather than the 0.90→0.95 segment. That produced 2.7809 at
    ``confidence=0.899`` where the true normal quantile is 1.2759 — a 2.18x
    overstatement, discontinuous with the tabulated 1.2816 at exactly 0.90, and
    wrong in the same direction as the upper-boundary error it was written to
    avoid. A caller needing a quantile outside the table must extend the table
    deliberately, which keeps the approximation visible rather than hidden.
    (MEASURED 2026-09-29: the true quantile here is ``NormalDist().inv_cdf(0.899)
    = 1.275874`` and 2.7809/1.275874 = 2.1796, i.e. 2.18x. This docstring
    previously read "1.2789 ... a 2.17x" — both literals were wrong; 1.2789 is
    ``inv_cdf(0.8995)``, not ``inv_cdf(0.899)``. The guard
    ``test_the_below_table_refusal_reason_cites_a_measured_ratio`` recomputes
    these two numbers from the shipped constants.)

    Raises:
        ValueError: if ``confidence`` is outside the tabulated range, in either
            direction.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1); got {confidence}.")

    exact = _Z_QUANTILES.get(round(confidence, 4))
    if exact is not None:
        return exact

    points = sorted(_Z_QUANTILES.items())
    lower, upper = points[0], points[-1]
    if confidence < lower[0]:
        # Refused rather than extrapolated, for the same reason as the upper
        # bound: a linear extension of a convex-in-the-tail quantile carries no
        # guarantee of accuracy, and the earlier attempt to extend it was wrong
        # by more than a factor of two (see the docstring). Extending the table
        # with a real quantile is the honest fix, not extrapolating this one.
        raise ValueError(
            f"confidence {confidence} is below the tabulated minimum "
            f"{lower[0]}. Extrapolating a normal quantile below this point is "
            f"not accurate — the quantile is convex in the tail, so a linear "
            f"extension understates or overstates it depending on direction. "
            f"Extend _Z_QUANTILES with a real quantile instead."
        )
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

    # §22.8: the floor is read from config, not a body literal. It decides BOTH
    # the warning and the published confidence, so a hardcoded value here would
    # silently lower a model result (the D-131 / D-128-Card-19 class).
    min_tail_observations = get_settings().risk.historical_var_min_tail_observations

    observations = len(inputs.returns)
    # Sample size is a first-class confidence determinant here: a 30-observation
    # 99% VaR is being read off the 0.3rd observation, which is not an estimate
    # so much as an extrapolation from one point.
    effective_tail_observations = observations * (1.0 - inputs.confidence)
    warnings: list[str] = []
    if effective_tail_observations < min_tail_observations:
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
            data_quality_flags_present=effective_tail_observations < min_tail_observations,
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
    # §22.8: the heaviness threshold is a config policy number, not a literal.
    heavy_tail_ratio = get_settings().risk.expected_shortfall_heavy_tail_ratio
    warnings: list[str] = []
    if severity_ratio is not None and severity_ratio > heavy_tail_ratio:
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
    # §22.8: the overweight multiple is a config policy number, not a literal.
    overweight_multiple = get_settings().risk.risk_contribution_overweight_multiple
    over_contributing = [
        f"asset {i} (weight {weights[i]:.2%}, risk share {shares[i]:.2%})"
        for i in range(n)
        if weights[i] > 0 and shares[i] > weights[i] * overweight_multiple
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


# ===========================================================================
# Section 17.1 — Monte Carlo VaR (Module 17, Tier 5)
#
# The Tier-5 REPLACEMENT for the three Tier-1 estimators above (Section 21.3,
# D-096). Phase 5+ builds the sophisticated version and **deletes nothing**, so
# `historical_var`, `parametric_var` and `expected_shortfall` all still ship;
# this is the fourth estimator, and the only one that can price a JOINT move.
# ===========================================================================


class StressCorrelationTransform(Protocol):
    """Structural view of ``portfolio/risk_budget.py``'s ``stress_correlations``.

    Declared as a ``Protocol`` rather than imported so the dependency runs
    ``portfolio → models`` (the permitted direction) and not the reverse. The
    layer rule is mechanical: ``models/`` is the lower layer and may **not**
    import ``portfolio/``, and this function needs the *production* stress
    definition rather than a copy of it.

    **Receiving it rather than restating it is the D-046/D-058 repair, and the
    reason is not legality.** A restated stress rule cannot disagree with the
    original, so it can never find the original wrong. The production rule has
    a non-obvious branch — a genuinely NEGATIVE correlation is preserved rather
    than forced positive, because "correlations converge toward 1" is a claim
    about the upper tail and a plain ``max(rho, stress)`` would silently turn a
    hedge into the stressed book's largest source of contagion. A local copy
    here would be free to miss that, and the two would then disagree about what
    a stress IS while both reporting a number called ``var_stressed``.

    The signature is the smallest surface this function actually uses: it calls
    with the keyword ``only_correlations_that_rise`` bound, because whether a
    hedge is preserved is a property of the caller's hypothesis rather than of
    the matrix.
    """

    def __call__(
        self,
        covariance_matrix: list[list[float]],
        stressed_correlation: float,
        *,
        only_correlations_that_rise: bool = ...,
    ) -> list[list[float]]:
        """Return ``covariance_matrix`` with its correlations stressed."""
        ...


class MonteCarloVaRInputs(FiniteInputs):
    """A multi-factor book and the two regimes to simulate it under.

    The specification's outline takes a ``scenario_generator`` callable
    (Section 17.1) — an opaque object this module cannot validate, cannot
    publish the inputs of, and cannot guarantee draws *correlated* shocks from.
    It is replaced here by the book's own parameters, because the whole point
    of the function is that the shocks are joint: a caller supplying a
    generator could hand in one that draws each factor independently, and the
    result would be a confident number with no correlation in it at all.

    Units and basis — stated because two bare float lists cannot reveal them:

    * ``factor_volatilities`` are **ANNUALISED DECIMALS** (``0.15`` = 15% per
      year). They are scaled DOWN to ``horizon_days`` internally by
      ``sqrt(horizon_days / periods_per_year)``.
    * ``weights`` are **signed fractions of capital** (``0.6`` = +60%, ``-0.4``
      = a 40% short). Unlike :class:`PortfolioVaRInputs` they are NOT required
      to sum to 1.0: a book with a short leg and a cash position has weights
      summing to less than one, and a long/short book can sum to zero while
      carrying real risk. Requiring a sum of 1.0 here would make a market-neutral
      book unrepresentable — the failure D-055 found in a different form.
    * ``factor_volatilities`` and the two correlation matrices are in the SAME
      PERIOD as each other; the horizon is applied once, to both regimes.

    **⚠️ This docstring said the OPPOSITE in the first draft** — *"per-period
    DECIMALS (0.01 = 1% per day), NOT annualised"* — and the field description
    repeated it. The code has always annualised (``horizon_scale =
    sqrt(horizon_days / periods_per_year)``), so the prose was wrong. **No unit
    test could see it:** every test supplies annualised numbers and cross-checks
    against an analytic that annualises on the SAME assumption, so the two routes
    agree with each other and both disagree with the prose. Only the live check —
    a run on real data, cross-checked against ``parametric_var`` — exposed it, at
    **≈ sqrt(252) x** (a daily-decimal reading gave 0.0312% against an analytic
    0.4946%; the annualised reading gave 0.4956% against 0.4947%, **0.0009 pp**).
    A docstring is a citation, and a citation is a claim.

    ``factor_volatilities`` may contain a ZERO (an instrument with no
    simulated risk, e.g. a cash leg). That is legal and is handled: its
    correlation with everything is undefined and is treated as zero, which is
    the same convention ``stress_correlations`` uses.
    """

    model_config = ConfigDict(extra="forbid")

    weights: list[float] = Field(
        min_length=1,
        description="Signed exposures as fractions of capital. Need not sum to 1.0.",
    )
    factor_volatilities: list[float] = Field(
        min_length=1,
        description=(
            "ANNUALISED volatility per factor, as a decimal. 0.15 = 15%/yr. "
            "Scaled down to horizon_days by sqrt(horizon_days/periods_per_year)."
        ),
    )
    normal_correlations: list[list[float]] = Field(
        description="NxN correlation matrix for the normal regime, from the sample.",
    )
    portfolio_value: float = Field(
        gt=0.0, description="Current portfolio value, in currency units."
    )
    confidence: float = Field(
        default=0.95,
        gt=0.0,
        lt=1.0,
        description="Confidence level. A higher level must give a LARGER loss.",
    )
    horizon_days: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Holding period in trading days. None -> settings.risk.monte_carlo."
            "horizon_days. Scaled onto the shock vector by sqrt(time)."
        ),
    )
    n_sims: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Draws per regime. None -> settings.risk.monte_carlo.n_sims. The "
            "realised count is published so the choice is visible."
        ),
    )
    seed: int | None = Field(
        default=None,
        description=(
            "RNG seed. None -> settings.risk.monte_carlo.seed. The seed actually "
            "used is published, so any result can be reproduced from its output."
        ),
    )
    periods_per_year: int = Field(
        default=252,
        gt=0,
        description=(
            "Trading days per year, used as the sqrt-time annualisation base. "
            "Matches ParametricVaRInputs deliberately: two estimators in one "
            "module that annualised over different bases would disagree by a "
            "constant no reader could see."
        ),
    )

    @model_validator(mode="after")
    def _validate_book_and_matrix(self) -> MonteCarloVaRInputs:
        """Shape, symmetry, diagonal, and feasibility checks.

        These duplicate the *shape* checks in
        :func:`_validate_weights_and_covariance` deliberately rather than
        calling it: that helper consumes a covariance matrix, and this model
        receives a CORRELATION matrix plus separate volatilities. Reusing it
        would mean building a covariance matrix to validate the correlation
        matrix, which is a restatement in the wrong basis. The two functions
        share a contract, not a representation.

        What is checked, and why each one is a real failure rather than
        defensive noise:

        * **Rectangular and n x n** — a ragged matrix otherwise reaches the
          Cholesky factor and dies in the library, naming no input.
        * **Symmetric** — a correlation is symmetric by definition, and an
          asymmetric one is a transcription error. The quantity computed from
          it is not a correlation matrix.
        * **Unit diagonal** — the diagonal of a *correlation* matrix is 1 by
          definition. A diagonal of 0.04 is a COVARIANCE matrix handed to a
          correlation parameter, which is the D-054 unit-convention error in a
          new place: the simulation would still run and the factor risk would
          be understated by the volatility scale.
        * **Diagonal entries within [-1, 1] for the cross terms** — the
          triangle must be a legal correlation.
        * **Non-negative volatilities** and matching lengths.
        """
        n = len(self.weights)
        if len(self.factor_volatilities) != n:
            raise ValueError(
                f"weights has {n} entries but factor_volatilities has "
                f"{len(self.factor_volatilities)}. Both describe the same factors."
            )
        if len(self.normal_correlations) != n:
            raise ValueError(
                f"weights has {n} entries but normal_correlations has "
                f"{len(self.normal_correlations)} rows."
            )
        for index, row in enumerate(self.normal_correlations):
            if len(row) != n:
                raise ValueError(
                    f"normal_correlations row {index} has {len(row)} entries; "
                    f"a {n}-factor correlation matrix must be {n}x{n}."
                )
        for i in range(n):
            diagonal = self.normal_correlations[i][i]
            if abs(diagonal - 1.0) > 1e-9:
                raise ValueError(
                    f"normal_correlations[{i}][{i}] is {diagonal}. The diagonal "
                    f"of a CORRELATION matrix is 1.0 by definition; a small "
                    f"diagonal is a COVARIANCE matrix passed as a correlation "
                    f"matrix, which would understate the factor risk by its "
                    f"volatility scale."
                )
        for i in range(n):
            for j in range(i + 1, n):
                a = self.normal_correlations[i][j]
                b = self.normal_correlations[j][i]
                if abs(a - b) > 1e-12:
                    raise ValueError(
                        f"normal_correlations is not symmetric — [{i}][{j}]={a} "
                        f"but [{j}][{i}]={b}. A correlation matrix is symmetric "
                        f"by definition; this is a transcription error."
                    )
                for value in (a, b):
                    if not -1.0 <= value <= 1.0:
                        raise ValueError(
                            f"normal_correlations contains {value}, outside "
                            f"[-1, 1]. A correlation cannot exceed 1 in "
                            f"magnitude."
                        )
        for index, vol in enumerate(self.factor_volatilities):
            if vol < 0.0:
                raise ValueError(
                    f"factor_volatilities[{index}] is {vol}; a volatility cannot be negative."
                )
        return self

    @property
    def correlation_names(self) -> list[str]:
        """The factor labels, used in warnings and the published per-factor map."""
        return [f"factor_{index}" for index in range(len(self.weights))]


# ===========================================================================
# Helpers the Monte Carlo estimator is built from.
# ===========================================================================


def _correlation_to_covariance(
    correlations: list[list[float]], volatilities: list[float]
) -> list[list[float]]:
    """``Cov[i][j] = rho[i][j] * sigma_i * sigma_j``.

    Kept separate from the Cholesky step because the STRESS path needs the
    covariance form: ``stress_correlations`` (the production implementation the
    Protocol stands for) takes a covariance matrix and returns one, so the
    stressed volatilities must already be folded in as a diagonal scale before
    the correlations are stressed. Building the covariance matrix once, then
    stressing the correlations *within it*, is what lets the volatility
    multiple and the correlation stress COMPOSE instead of replacing each
    other — the difference between the measured 1.199x and the measured 2.989x
    stress response (see the YAML note).
    """
    n = len(volatilities)
    return [
        [correlations[i][j] * volatilities[i] * volatilities[j] for j in range(n)] for i in range(n)
    ]


def _cholesky_factor(covariance: list[list[float]], regime: str) -> list[list[float]]:
    """Lower-triangular ``L`` with ``L @ L.T == covariance``.

    Fails loudly rather than repairing. A non-positive-definite matrix means the
    inputs describe a joint distribution that cannot exist, and the two standard
    "fixes" — nearest-PSD projection, eigenvalue flooring — both CHANGE the risk
    being measured while leaving the output labelled with the caller's numbers.
    That is a silent failure surface, so the refusal is the contract.

    The library's ``LinAlgError`` names no input, so it is caught and re-raised
    with the regime label and the practical cause. A correlation matrix is
    non-PSD exactly when its cross terms are jointly infeasible rather than
    individually illegal (three factors pairwise correlated at 0.9 is the
    standard example); a reader otherwise receives "Matrix is not positive
    definite" with no pointer to which of the two regimes was at fault.
    """
    import numpy as np

    try:
        return cast(
            "list[list[float]]",
            np.linalg.cholesky(np.asarray(covariance, dtype=float)).tolist(),
        )
    except np.linalg.LinAlgError as error:
        raise ValueError(
            f"The {regime} correlation matrix is not a valid joint "
            f"distribution — its covariance form is not positive definite, so "
            f"no set of correlated shocks with these correlations exists. This "
            f"is a property of the inputs, not a numerical tolerance: cross "
            f"terms that are individually legal can still be jointly "
            f"infeasible. Underlying error: {error}"
        ) from error


def _simulate_regime_pnls(
    *,
    factor_loadings: list[float],
    covariance: list[list[float]],
    n_sims: int,
    horizon_scale: float,
    rng: Generator,
    regime: str,
) -> list[float]:
    """Draw ``n_sims`` joint factor shocks; return FRACTIONAL portfolio P&L.

    The unit is the **fraction of portfolio value** the book gains or loses,
    not a currency amount. That choice is deliberate: the caller turns it into
    an amount by multiplying by ``portfolio_value`` exactly once, and the
    quantile/ES helpers then return the same "percent loss" quantity that
    :func:`historical_var` does. Simulating amounts here and *also* multiplying
    by the value later is the double-scaling bug this signature prevents.

    The mechanism, stated because the correlation is the whole point:

    1. Draw an ``n_sims x n`` block of i.i.d. standard normals ``Z``.
    2. ``S = Z @ L.T``, where ``L`` is the Cholesky factor of the covariance
       matrix. Then ``Cov(S) == L @ L.T == covariance`` — the induced
       correlation is the requested one to floating-point, which is exactly
       what an independent-shock-per-factor generator would fail to give.
    3. Factor shocks ``dF = S * sqrt(horizon)``. The sqrt-time scale is applied
       to every FACTOR, not to the final P&L, so the horizon scales the joint
       structure consistently with the marginals.
    4. Portfolio return ``dP = loadings . dF``.

    Sign: ``dP`` is in return space, so **negative means a loss**. It is
    converted to the positive-loss convention once, at the end of
    :func:`monte_carlo_var`, where the single conversion is visible.
    """
    import numpy as np

    loadings = np.asarray(factor_loadings, dtype=float)
    factor = _cholesky_factor(covariance, regime)
    z = rng.standard_normal((n_sims, loadings.size))
    # Z @ L.T induces Cov == L @ L.T == covariance.
    correlated = z @ np.asarray(factor, dtype=float).T
    factor_pnl = correlated * horizon_scale
    return cast("list[float]", (factor_pnl @ loadings).tolist())


def _loss_quantile(pnls: list[float], confidence: float, sorted_ascending: bool = False) -> float:
    """Positive-loss VaR from a simulated P&L sample.

    Uses the module's own :func:`_quantile` (the ``(n-1)*p`` linear
    interpolation that matches numpy's ``'linear'`` method one-for-one, verified
    in the tests) so the simulated estimator and the empirical one share a
    quantile definition. Two VaR numbers computed with different quantile
    conventions would differ for a reason no caller could see, and the
    normal-vs-stressed comparison this function exists to make would silently
    acquire a second, methodological difference.
    """
    ordered = sorted(pnls) if not sorted_ascending else pnls
    return -_quantile(ordered, 1.0 - confidence)


def _expected_shortfall_from_pnls(pnls: list[float], var_loss: float) -> float:
    """Mean loss beyond the VaR boundary, in the positive-loss convention.

    Matches :func:`expected_shortfall`'s definition (the mean of the returns at
    or below the ``(1 - confidence)`` quantile) so the simulated ES and the
    empirical ES are the same quantity. The tail set is selected on the
    RETURN-space P&L: everything at or below ``-var_loss``.
    """
    tail = [value for value in pnls if value <= -var_loss]
    if not tail:
        # A VaR read off an interpolated quantile can sit strictly between two
        # draws, leaving no observation at or below it. The nearest draw is the
        # honest tail at these sizes; this cannot happen for historical_var, but
        # it can here, and returning 0.0 would report a severity of zero at the
        # exact moment the tail is empty of information.
        tail = [min(pnls)]
    return -sum(tail) / len(tail)


def _diversification_ratio(factor_loadings: list[float], covariance: list[list[float]]) -> float:
    """``sigma_p / sum_i |w_i| sigma_i`` — the LTCM tell, on the FACTOR book.

    Bounded in ``(0, 1]`` for a non-degenerate book. It equals 1 when every
    factor is perfectly correlated (no diversification exists to lose) and
    falls toward 0 as the book's risks offset. The interesting quantity in
    Section 18.2 is the *change* in this ratio between the normal and stressed
    regimes: a crisis that raises correlations drives it toward 1, which is the
    correlation breakdown itself rather than a symptom of it.

    ``sum |w_i| sigma_i`` is the fully-correlated (worst-case) portfolio
    volatility, so the ratio is the fraction of that bound actually realized.
    """
    import numpy as np

    weights = np.asarray(factor_loadings, dtype=float)
    matrix = np.asarray(covariance, dtype=float)
    sigma = np.sqrt(np.diag(matrix))
    standalone = float(np.sum(np.abs(weights) * sigma))
    if standalone == 0.0:
        return 1.0
    variance = float(weights @ matrix @ weights)
    return math.sqrt(max(variance, 0.0)) / standalone


def _uniform_correlation_stress(
    correlations: list[list[float]], target: float
) -> list[list[float]]:
    """Raise every cross-correlation toward ``target``; keep the diagonal at 1.

    A FALLBACK, and labelled as one. It exists because the transform is
    received rather than imported, so a caller that has no transform still gets
    a defined stressed regime — but this rule does not preserve a negative
    correlation the way the production rule does, and the difference is warned
    at the call site. Uniformly raising a hedge's correlation is exactly the
    mistake Section 18.2 warns about, so this path must never be silent.

    ``max(rho, target)`` and NOT ``min``: the stress RAISES a correlation
    toward the target and never *lowers* one. An earlier ``min`` read
    "raise ... toward target" as "cap at target", so a book at ``rho = 0.3``
    under a ``0.9`` stress kept ``0.3`` (no stress applied at all) and an
    already-correlated pair at ``rho = 0.95`` was *lowered* to ``0.9``. A
    "stress" that leaves a normal book unstressed and de-risks a correlated
    one is the opposite of the LTCM lesson; ``max`` is the honest reading of
    the digest's own call-site contract ("a uniform correlation target of
    {target} was applied").
    """
    if not -1.0 <= target <= 1.0:
        raise ValueError(
            f"stressed_correlation={target} is outside [-1, 1], so it is not a "
            f"correlation. A correlation cannot exceed 1 in magnitude."
        )
    n = len(correlations)
    out = [[1.0 if i == j else correlations[i][j] for j in range(n)] for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            raised = max(correlations[i][j], target)
            out[i][j] = raised
            out[j][i] = raised
    return out


def monte_carlo_var(
    inputs: MonteCarloVaRInputs,
    *,
    stress_correlations: StressCorrelationTransform | None = None,
    stressed_correlation: float | None = None,
) -> ModelResult:
    """Section 17.1's Monte Carlo VaR — the Tier-5 replacement, and the LTCM rule.

    Why this supersedes the three Tier-1 estimators
    ------------------------------------------------
    ``historical_var``, ``parametric_var`` and ``expected_shortfall`` each price
    a **single** distribution. None can answer the question Section 18.2
    actually asks: *how much worse is the same book when its correlations break
    down*. This function simulates the book under TWO joint distributions — the
    sample's correlation matrix and a stressed one — and reports both. Per
    D-096 nothing is deleted: this is a fourth route, and the only one that can
    price a joint move at all.

    The mechanism, stated
    ---------------------
    1. Each regime's covariance is built from the SAME factor volatilities and
       the regime's correlation matrix (``_correlation_to_covariance``).
    2. Under stress the volatilities are scaled by
       ``settings.risk.monte_carlo.stressed_volatility_multiplier`` **before**
       the correlations are stressed, and the transform is applied to the
       resulting covariance matrix by the RECEIVED production rule
       (``stress_correlations``), never by a local copy.
    3. Each regime's portfolio P&L is drawn by ``_simulate_regime_pnls`` — a
       Cholesky-correlated joint normal, sqrt-time scaled.
    4. VaR and ES are read off each sample in the positive-loss convention
       through the module's own quantile rule.

    Why the volatility multiple is in the stress (measured, not assumed)
    -------------------------------------------------------------------
    The specification's prose mandates a correlation stress and says nothing
    about volatility. Measured on a two-leg convergence book, a
    correlation-only stress moves 95% VaR by **1.199x**; the volatility term
    together with it moves it **2.989x**. Volatility is the larger of the two,
    and omitting it understates the very crisis the function exists to price by
    roughly a factor of 2.5. It is therefore a configured leaf, not an
    implementation detail — see ``config/settings.yaml``.

    Why this is the LTCM detection rule
    -----------------------------------
    Section 18.2 names *this* function as the system's LTCM early warning: a
    large normal-vs-stressed gap is the correlation-breakdown signal, published
    as an explicit ratio so no caller recomputes it (and so no caller
    recomputes it DIFFERENTLY).

    Reproducibility
    ---------------
    The seed actually used is published in the value. An unseeded Monte Carlo
    estimate is not a risk number — it moves every run (measured: the same
    input returned 1.616866 / 1.678676 / 1.674093 across three runs), and a
    number that changes without its inputs changing cannot be reconciled
    against a later one.

    Refusals and warnings
    ---------------------
    * A non-positive-definite regime matrix is REFUSED (see
      ``_cholesky_factor``), not repaired.
    * ``n_sims * (1 - confidence)`` below ``min_tail_draws`` is warned: the
      quantile is being read off too few draws to be an estimate.
    * A zero factor volatility is warned: the book claims a factor that moves
      nothing, so it carries diversification it does not have.
    * A stressed-book diversification ratio above
      ``stress_diversification_warning`` is warned: most of the book's apparent
      risk reduction came from the assumption that just broke.
    * The fallback uniform correlation stress is warned whenever it is used.
    """
    settings = get_settings().risk.monte_carlo
    import numpy as np

    n_sims = inputs.n_sims if inputs.n_sims is not None else settings.n_sims
    seed = inputs.seed if inputs.seed is not None else settings.seed
    horizon_days = inputs.horizon_days if inputs.horizon_days is not None else settings.horizon_days
    horizon_scale = math.sqrt(horizon_days / inputs.periods_per_year)

    warnings: list[str] = []

    # --- factor census: prune factors that cannot move ---------------------
    # A zero-volatility factor makes the covariance matrix SINGULAR (its row
    # and column are all zeros), and a Cholesky factor requires STRICTLY
    # positive definite. Leaving it in would therefore refuse a perfectly
    # legitimate book — a hedge leg currently at zero exposure — with a
    # message about an invalid joint distribution, which is not what the
    # book is. It is pruned instead, because by construction it contributes
    # nothing to any loss, and the pruning is warned so the caller knows the
    # book it supplied is not the book that was simulated.
    live = [i for i, vol in enumerate(inputs.factor_volatilities) if vol != 0.0]
    if len(live) < len(inputs.factor_volatilities):
        dropped = [
            inputs.correlation_names[i]
            for i in range(len(inputs.factor_volatilities))
            if i not in live
        ]
        warnings.append(
            f"Factor(s) {', '.join(dropped)} have zero volatility and were "
            f"DROPPED before simulation: they contribute nothing to any loss "
            f"by construction, and leaving a zero row in the covariance matrix "
            f"makes it singular (no Cholesky factor exists). The reported "
            f"results describe a {len(live)}-factor book, not the "
            f"{len(inputs.factor_volatilities)}-factor book supplied."
        )
    if not live:
        raise ValueError(
            "Every factor volatility is zero, so there is no risk to "
            "simulate. A zero-volatility book has zero VaR at every "
            "confidence level, which is a statement about the inputs rather "
            "than a risk estimate."
        )

    # --- the normal regime -------------------------------------------------
    normal_vols = [inputs.factor_volatilities[i] for i in live]
    weights = [inputs.weights[i] for i in live]
    correlations = [[inputs.normal_correlations[i][j] for j in live] for i in live]
    normal_cov = _correlation_to_covariance(correlations, normal_vols)

    # --- the stressed regime ----------------------------------------------
    # Volatility first, then the correlation stress on the resulting matrix, so
    # the two compose (see the measured note above).
    stressed_vols = [vol * settings.stressed_volatility_multiplier for vol in normal_vols]
    stressed_cov_pre = _correlation_to_covariance(correlations, stressed_vols)

    if stress_correlations is None:
        if stressed_correlation is None:
            raise ValueError(
                "stress_correlations was not supplied and no "
                "stressed_correlation target was given, so the stressed regime "
                "would differ from the normal one only by the volatility "
                "multiple. Pass the production stress transform (from "
                "portfolio/risk_budget.py) — a correlation-breakdown warning "
                "that does not actually break any correlation is the LTCM "
                "failure mode, not its detection."
            )
        stressed_cov = _correlation_to_covariance(
            _uniform_correlation_stress(correlations, stressed_correlation),
            stressed_vols,
        )
        warnings.append(
            f"No stress_correlations transform was supplied, so a uniform "
            f"correlation target of {stressed_correlation} was applied to every "
            f"off-diagonal entry instead (a pair already above the target is left "
            f"at its sampled value; nothing is lowered). The production rule "
            f"preserves genuinely NEGATIVE correlations (hedges); this fallback "
            f"does not, so a hedged book's stressed loss is overstated here."
        )
    else:
        if stressed_correlation is None:
            raise ValueError(
                "stress_correlations was supplied but stressed_correlation was "
                "not. The transform needs the target level to raise "
                "correlations to; without it there is no stress to apply."
            )
        stressed_cov = stress_correlations(
            stressed_cov_pre, stressed_correlation, only_correlations_that_rise=True
        )

    # Two generators from ONE seed, so both regimes are driven by the same
    # random numbers. Using one generator twice would make the stressed sample
    # depend on how many draws the normal sample consumed; matched streams make
    # the comparison a comparison of DISTRIBUTIONS rather than of draws.
    normal_pnls = _simulate_regime_pnls(
        factor_loadings=weights,
        covariance=normal_cov,
        n_sims=n_sims,
        horizon_scale=horizon_scale,
        rng=np.random.default_rng(seed),
        regime="normal",
    )
    stressed_pnls = _simulate_regime_pnls(
        factor_loadings=weights,
        covariance=stressed_cov,
        n_sims=n_sims,
        horizon_scale=horizon_scale,
        rng=np.random.default_rng(seed),
        regime="stressed",
    )

    # --- read the risk measures off each sample ----------------------------
    var_normal_loss = _loss_quantile(normal_pnls, inputs.confidence)
    var_stressed_loss = _loss_quantile(stressed_pnls, inputs.confidence)
    es_normal_loss = _expected_shortfall_from_pnls(normal_pnls, var_normal_loss)
    es_stressed_loss = _expected_shortfall_from_pnls(stressed_pnls, var_stressed_loss)

    div_normal = _diversification_ratio(weights, normal_cov)
    div_stressed = _diversification_ratio(weights, stressed_cov)

    # --- the LTCM gap, published as a ratio --------------------------------
    # Guarded rather than divided: a non-positive normal VaR makes the ratio
    # meaningless, and silently returning inf/nan would report a correlation
    # breakdown that may not exist.
    if var_normal_loss > 0.0:
        ratio = var_stressed_loss / var_normal_loss
    else:
        ratio = float("nan")
        warnings.append(
            f"The normal-regime VaR at {inputs.confidence:.1%} is "
            f"{var_normal_loss:.6g}, so the stressed-to-normal ratio is "
            f"undefined and reported as absent. Do not read a "
            f"correlation-breakdown signal from it."
        )

    # --- tail census -------------------------------------------------------
    tail_draws = settings.tail_draws_for(n_sims, inputs.confidence)
    if tail_draws < settings.min_tail_draws:
        warnings.append(
            f"Only {tail_draws:.1f} of {n_sims} draws are expected beyond the "
            f"{inputs.confidence:.1%} quantile (floor "
            f"{settings.min_tail_draws:.0f}). The quantile is being read off "
            f"too few points to be an estimate rather than an extrapolation."
        )

    # --- diversification warning ------------------------------------------
    if div_stressed > settings.stress_diversification_warning:
        warnings.append(
            f"The stressed book's diversification ratio is {div_stressed:.4f}, "
            f"above the {settings.stress_diversification_warning} warning level "
            f"(1.0 = no diversification at all). Most of the book's apparent "
            f"risk reduction came from the correlation assumption that just "
            f"broke — the Section 18.2 pattern."
        )

    warnings.append(
        "The normal-vs-stressed VaR gap is the LTCM correlation-breakdown "
        "signal (Section 18.2): a large ratio means the book's risk depends on "
        "correlations holding."
    )

    # --- confidence --------------------------------------------------------
    # Heuristic marker: the stress definitions are illustrative thresholds, not
    # calibrated crisis parameters (Section 15.19/20). The tail census is the
    # data-quality fact, stated rather than felt (Section 22.8).
    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=tail_draws < settings.min_tail_draws,
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="monte_carlo_var",
        country="us",
        as_of=utc_now(),
        value={
            "var_normal_pct": round(var_normal_loss * 100, 4),
            "var_stressed_pct": round(var_stressed_loss * 100, 4),
            "var_normal_amount": round(var_normal_loss * inputs.portfolio_value, 2),
            "var_stressed_amount": round(var_stressed_loss * inputs.portfolio_value, 2),
            "es_normal_pct": round(es_normal_loss * 100, 4),
            "es_stressed_pct": round(es_stressed_loss * 100, 4),
            "stressed_to_normal_ratio": (None if math.isnan(ratio) else round(ratio, 6)),
            "diversification_ratio_normal": round(div_normal, 6),
            "diversification_ratio_stressed": round(div_stressed, 6),
            "n_sims": n_sims,
            "seed": seed,
            "confidence": inputs.confidence,
            "horizon_days": horizon_days,
        },
        confidence=confidence,
        interpretation=(
            f"Monte Carlo VaR ({inputs.confidence:.1%}, {horizon_days}d, "
            f"{n_sims} sims): normal "
            f"{var_normal_loss * inputs.portfolio_value:,.2f}, stressed "
            f"{var_stressed_loss * inputs.portfolio_value:,.2f} on a "
            f"{inputs.portfolio_value:,.2f} book"
        ),
        context=(
            f"Joint normal draws via Cholesky, two correlation regimes. "
            f"Stressed regime applies a "
            f"{settings.stressed_volatility_multiplier:.2f}x volatility "
            f"multiple AND a correlation stress. Diversification ratio "
            f"{div_normal:.4f} -> {div_stressed:.4f}. "
            f"Sign convention: positive = loss. Seed {seed}."
        ),
        inputs_used=[
            "weights",
            "factor_volatilities",
            "normal_correlations",
            "portfolio_value",
            "confidence",
        ],
        warnings=warnings,
    )
