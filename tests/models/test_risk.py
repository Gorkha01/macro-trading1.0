"""Hand-verified tests for Module 17-18 risk metrics, volatility, and portfolio variance.

AGENTS.md Section 9.1, Section 6.10, Section 15.20 part C, Section 11.1,
Section 21.2 Steps 4-5.

Section 11.1 mandates ``test_historical_var_matches_hand_calculation``.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pytest
from pydantic import ValidationError

from macro_engine.models.risk import (
    _Z_QUANTILES,
    ParametricVaRInputs,
    RealizedVolInputs,
    ReturnsInputs,
    TwoAssetPortfolioInputs,
    expected_shortfall,
    historical_var,
    marginal_risk_contributions,
    parametric_var,
    portfolio_volatility_n_asset,
    portfolio_volatility_two_asset,
    realized_vol_simple,
    z_score_for_confidence,
)
from tests.helpers import as_float

# Ten returns with one severe loss, ordered so the tail is unambiguous.
#
# Sorted: [-0.12, -0.02, -0.01, -0.005, 0.003, 0.005, 0.01, 0.01, 0.015, 0.02]
# At 95% confidence, fraction = 0.05, position = (10-1)*0.05 = 0.45
#   -> between index 0 (-0.12) and index 1 (-0.02), weight 0.45
#   -> quantile = -0.12*0.55 + -0.02*0.45 = -0.066 - 0.009 = -0.075
#   -> VaR (positive loss) = +0.075 = 7.5%
_HAND_RETURNS = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, -0.005, -0.12, 0.01, 0.003]


def test_historical_var_matches_hand_calculation() -> None:
    """Section 11.1's mandated VaR case.

    The interpolation is spelled out in the module-level comment above so the
    expected value is derived, not observed. Section 21.2 warns that a test
    which passes first try may be asserting whatever the code produced; a
    derivation in the test file is what distinguishes the two.
    """
    result = historical_var(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    assert as_float(result) == pytest.approx(7.5, abs=0.0001)


def test_historical_var_returns_a_positive_loss() -> None:
    """The sign convention, asserted explicitly.

    A VaR reported as a negative number would be read as a gain by every
    downstream consumer, and the sign is not recoverable from the magnitude.
    """
    result = historical_var(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    assert as_float(result) > 0, "losses are reported as positive numbers"
    assert "positive = loss" in result.context


def test_historical_var_at_99_percent_is_at_least_the_95_percent_figure() -> None:
    """A monotonicity guard rather than a value check.

    A deeper confidence level cannot report a smaller loss under the same
    estimator. This catches an inverted quantile fraction — the most likely
    way to get this function subtly wrong — without pinning a second value.
    """
    var_95 = historical_var(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    var_99 = historical_var(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.99))
    assert as_float(var_99) >= as_float(var_95)


def test_historical_var_warns_when_the_sample_is_too_small_for_the_confidence() -> None:
    """10 observations at 95% leaves 0.5 expected tail points.

    The warning path is exercised deliberately (Section 21.2 Step 5), and the
    confidence penalty that accompanies it is asserted so the two cannot drift
    apart — a warning that does not lower confidence is cosmetic.
    """
    from macro_engine.config import get_settings

    result = historical_var(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    assert any("tail" in warning.lower() for warning in result.warnings)

    settings = get_settings()
    penalised = settings.scalar("confidence.base") - settings.scalar(
        "confidence.data_quality_flag_penalty"
    )
    assert result.confidence == pytest.approx(penalised, abs=1e-9)


def test_historical_var_does_not_warn_when_the_tail_is_well_populated() -> None:
    """The negative case: 500 observations at 95% leaves 25 tail points.

    A warning that fires on the ordinary case is noise, and noise is how a real
    warning gets ignored. This asserts the guard is genuinely conditional
    rather than always-on.
    """
    from macro_engine.config import get_settings

    # Deterministic spread so the test does not depend on random state.
    returns = [((index % 20) - 10) / 100.0 for index in range(500)]
    result = historical_var(ReturnsInputs(returns=returns, confidence=0.95))
    assert not any("observations lie in the tail" in warning for warning in result.warnings)
    assert result.confidence == pytest.approx(get_settings().scalar("confidence.base"), abs=1e-9)


def test_expected_shortfall_matches_hand_calculation() -> None:
    """Only ONE return lies at or below the 95% quantile, and that is the point.

    Hand computation:
        quantile@95% = -0.075 (interpolated, not observed)
        tail returns = [-0.12]   <- only -0.12 is <= -0.075
                                    -0.02 is GREATER than -0.075, so it is
                                    inside the 95% body, not the tail
        mean         = -0.12
        ES (positive loss) = +12.0%

    An earlier version of this test asserted 7.0%, having wrongly averaged
    -0.12 and -0.02. The tail boundary excludes -0.02, and getting that wrong
    is easy precisely because a quantile that falls between two observations
    does not coincide with either. The implementation was right; the test was
    wrong. This is the mirror of Section 21.2's warning — a test can be wrong
    in the direction of asserting a plausible hand-calculation error.
    """
    result = expected_shortfall(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    assert as_float(result) == pytest.approx(12.0, abs=0.0001)


def test_expected_shortfall_exceeds_or_equals_var() -> None:
    """ES is the mean of losses beyond VaR, so it cannot be smaller than VaR.

    An inequality, not a value: it holds for any sample and therefore catches
    a mis-sliced tail without needing to know the sample.
    """
    var = historical_var(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    es = expected_shortfall(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    assert as_float(es) >= as_float(var)


def test_expected_shortfall_warns_on_a_heavy_tail() -> None:
    """ES/VaR > 1.5 triggers the heavy-tail warning.

    Sample chosen so the ratio is 12.0/7.5 = 1.6, clearing the threshold.
    """
    result = expected_shortfall(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    assert any("heavy relative to its boundary" in warning for warning in result.warnings)


def test_expected_shortfall_always_carries_the_sample_blindness_warning() -> None:
    """ES inherits historical_var's window blindness, and must say so."""
    result = expected_shortfall(ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95))
    assert any("same historical sample" in warning for warning in result.warnings)


def test_z_score_lookup_matches_published_quantiles() -> None:
    """The three conventional one-sided normal quantiles.

    Values are the standard tabulated figures, asserted to six decimals, so a
    transcription error in the table is caught rather than propagated into
    every parametric VaR.
    """
    assert z_score_for_confidence(0.90) == pytest.approx(1.281552, abs=1e-6)
    assert z_score_for_confidence(0.95) == pytest.approx(1.644854, abs=1e-6)
    assert z_score_for_confidence(0.99) == pytest.approx(2.326348, abs=1e-6)


def test_z_score_refuses_to_extrapolate_beyond_the_table() -> None:
    """Extrapolating a normal quantile understates the tail.

    In a function whose entire purpose is tail magnitude, that is the wrong
    direction to be approximately right in — so it raises instead. The test
    asserts the refusal, not a fallback value.
    """
    with pytest.raises(ValueError, match="exceeds the tabulated maximum"):
        z_score_for_confidence(0.9999)


def test_z_score_refuses_to_extrapolate_below_the_table() -> None:
    """The lower refusal is symmetric with the upper one, and it has to be.

    An earlier version of this function extended the FIRST segment by scaling
    the LAST tabulated point — ``3.0902 * c / 0.999`` — which is the secant
    through the origin and the 0.999 point, not the 0.90->0.95 segment. At
    ``confidence=0.899`` it returned 2.7809 where the true normal quantile is
    1.2759: a 2.18x overstatement, in the same direction as the upper-boundary
    error the refusal exists to prevent. The interpolation loop below the table
    was never exercised because the tabulated points (0.90/0.95/0.99) and the
    upper boundary were the only confidences any test used, so the branch
    survived to feed ``parametric_var`` with a doubled z. Asserting the refusal
    pins the behaviour at the value that used to be wrong.

    ⚠️ The two literals above are MEASURED, not recalled (D-131). This docstring
    previously read "1.2789 ... 2.17x"; 1.2789 is ``NormalDist().inv_cdf(0.8995)``,
    not ``inv_cdf(0.899)``. ``test_the_below_table_refusal_cites_measured_numbers``
    recomputes both from ``NormalDist`` so a future edit cannot silently re-drift.
    """
    for confidence in (0.899, 0.85, 0.80, 0.50):
        with pytest.raises(ValueError, match="below the tabulated minimum"):
            z_score_for_confidence(confidence)


def test_the_below_table_refusal_cites_measured_numbers() -> None:
    """The docstring's 1.2759 / 2.18x must be the MEASURED values (Class G, D-131).

    A decision-record docstring is a citation, and the citation here was wrong:
    it read "1.2789 ... a 2.17x overstatement". ``NormalDist().inv_cdf(0.899)``
    is 1.2759 (1.2789 is ``inv_cdf(0.8995)``), so the ratio is 2.18x. This guard
    recomputes BOTH numbers from the shipped constants — the ``_Z_QUANTILES``
    top point and the ``0.90`` knot — so the prose cannot drift from the code
    again. It is a mover, not a pinner: it would fail on the old literals.
    """
    top_confidence, top_z = max(_Z_QUANTILES.items())
    probe = 0.899
    old_extrapolation = top_z * probe / top_confidence

    true_quantile = NormalDist().inv_cdf(probe)
    assert old_extrapolation == pytest.approx(2.7809, abs=5e-5), old_extrapolation
    assert true_quantile == pytest.approx(1.2759, abs=5e-5), true_quantile
    assert old_extrapolation / true_quantile == pytest.approx(2.18, abs=5e-3)

    # And the tabulated points themselves are real quantiles, not approximations:
    # every shipped z is the normal quantile to floating-point (D-131).
    normal = NormalDist()
    for confidence, z in _Z_QUANTILES.items():
        assert z == pytest.approx(normal.inv_cdf(confidence), abs=1e-12), confidence


def test_z_score_is_continuous_at_the_tabulated_boundaries() -> None:
    """No jump between a tabulated point and an interpolated neighbour.

    The defect above was a discontinuity, not just an error: ``z(0.90)`` was
    1.2816 while ``z(0.899)`` was 2.7809. A piecewise-linear interpolation is
    continuous by construction, so the property to pin is that stepping a tiny
    distance across a knot changes the value by no more than that segment's own
    slope times the step. An absolute tolerance will not do: the top segment
    (0.995->0.999) is legitimately steep at 0.129 per 0.001, so anything tight
    enough to catch a real jump would also flag the honest slope there.

    Every tabulated point is tested on both sides; the segment on each side
    supplies its own bound, and confidences below the minimum are refused.
    """
    points = sorted(_Z_QUANTILES.items())
    for index, (c, _z) in enumerate(points):
        for delta in (1e-4, 1e-6):
            for neighbour in (index - 1, index + 1):
                if not 0 <= neighbour < len(points):
                    continue
                n_c, n_z = points[neighbour]
                if abs(n_c - c) < 1e-12:
                    continue
                # Slope of the segment this step moves along, in z per unit c.
                slope = abs(n_z - _z) / abs(n_c - c)
                bound = slope * delta * 1.5  # 1.5x headroom for float noise
                if neighbour < index:
                    gap = abs(z_score_for_confidence(c - delta) - z_score_for_confidence(c))
                else:
                    gap = abs(z_score_for_confidence(c + delta) - z_score_for_confidence(c))
                assert gap <= bound, (
                    f"discontinuity at {c} moving toward {n_c} "
                    f"(delta={delta}, gap={gap}, bound={bound})"
                )

    # The minimum is the knot the original defect sat on, and it is the one
    # place a ``c - delta`` probe cannot reach because the value below it must
    # either continue the first segment smoothly or be refused. Both are
    # acceptable; a third outcome — a large jump to an unrelated value — is what
    # the old ``3.0902 * c / 0.999`` formula did (1.2816 at 0.90, 2.7809 at
    # 0.899). Assert that the step across the minimum is either a refusal or
    # small, which is exactly the choice the fix makes explicit.
    c_min, z_min = points[0]
    for delta in (1e-4, 0.001):
        try:
            below = z_score_for_confidence(c_min - delta)
        except ValueError:
            continue  # refused: the honest behaviour
        assert abs(below - z_min) <= 1e-2, (
            f"discontinuity below the tabulated minimum {c_min}: "
            f"z({c_min})={z_min} but z({c_min - delta})={below}"
        )


def test_z_score_rejects_an_impossible_confidence() -> None:
    with pytest.raises(ValueError, match=r"must be in \(0, 1\)"):
        z_score_for_confidence(1.0)


def test_parametric_var_matches_hand_calculation() -> None:
    """VaR = z * sigma * sqrt(h/252) * V

    Hand computation at 95%, sigma=0.15, h=1, V=1,000,000:
        z            = 1.6448536269514722
        sqrt(1/252)  = 0.0629940788...
        sigma_h      = 0.15 * 0.0629940788 = 0.0094491118...
        var_fraction = 1.6448536269514722 * 0.0094491118 = 0.0154945...
        var_amount   = 0.0154945 * 1,000,000 = 15,494.55...
        var_pct      = 1.5494... -> 1.5495 when rounded to 4dp
    """
    result = parametric_var(
        ParametricVaRInputs(
            portfolio_value=1_000_000.0,
            vol_annualized=0.15,
            confidence=0.95,
            horizon_days=1,
        )
    )
    assert isinstance(result.value, dict)

    z = 1.6448536269514722
    expected_fraction = z * 0.15 * math.sqrt(1 / 252)
    assert result.value["var_pct"] == pytest.approx(expected_fraction * 100, abs=0.0001)
    assert result.value["var_amount"] == pytest.approx(expected_fraction * 1_000_000.0, abs=0.01)
    assert float(result.value["var_amount"]) > 0
    assert result.value["z_score"] == pytest.approx(z, abs=1e-6)


def test_parametric_var_scales_with_the_square_root_of_horizon() -> None:
    """A 4-day horizon must give exactly twice the 1-day figure.

    sqrt(4) = 2. Asserting the exact factor rather than two values proves the
    time scaling is present and correctly applied; a value check on each would
    pass even if only one were right.
    """
    one_day = parametric_var(
        ParametricVaRInputs(
            portfolio_value=1_000_000.0, vol_annualized=0.15, confidence=0.95, horizon_days=1
        )
    )
    four_day = parametric_var(
        ParametricVaRInputs(
            portfolio_value=1_000_000.0, vol_annualized=0.15, confidence=0.95, horizon_days=4
        )
    )
    assert isinstance(one_day.value, dict)
    assert isinstance(four_day.value, dict)
    assert four_day.value["var_amount"] == pytest.approx(
        float(one_day.value["var_amount"]) * 2.0, abs=0.01
    )


def test_parametric_var_always_warns_about_fat_tails() -> None:
    """The normality caveat is present at every horizon, not just multi-day."""
    result = parametric_var(
        ParametricVaRInputs(
            portfolio_value=1_000_000.0, vol_annualized=0.15, confidence=0.95, horizon_days=1
        )
    )
    assert any("fat-tailed" in warning for warning in result.warnings)
    assert not any("sqrt(time)" in warning for warning in result.warnings), (
        "the sqrt-time caveat should not fire at a 1-day horizon"
    )


def test_parametric_var_warns_about_sqrt_time_beyond_one_day() -> None:
    """The multi-day caveat is conditional on horizon, and fires when it should."""
    result = parametric_var(
        ParametricVaRInputs(
            portfolio_value=1_000_000.0, vol_annualized=0.15, confidence=0.95, horizon_days=10
        )
    )
    assert any("sqrt(time)" in warning for warning in result.warnings)


def test_realized_vol_matches_hand_calculation() -> None:
    """Population stdev of [0.01, -0.01, 0.02, -0.02] with ddof=1:

    mean = 0.0
    squared deviations = [1e-4, 1e-4, 4e-4, 4e-4] -> sum = 1e-3
    variance (ddof=1) = 1e-3 / 3 = 0.00033333...
    stdev = 0.018257418583505537
    annualised = 0.018257419 * sqrt(252) = 0.289817...
    -> 28.9817% when rounded to 4dp
    """
    result = realized_vol_simple(
        RealizedVolInputs(returns=[0.01, -0.01, 0.02, -0.02], window=4, periods_per_year=252)
    )
    expected = math.sqrt(1e-3 / 3) * math.sqrt(252) * 100
    assert as_float(result) == pytest.approx(expected, abs=0.0001)


def test_realized_vol_uses_the_unbiased_estimator() -> None:
    """ddof=1 vs ddof=0 differ by sqrt(n/(n-1)); at n=4 that is 15%.

    Asserted as a distinction test: if the implementation used ddof=0 this
    would fail by a wide margin. The difference is negligible at 252
    observations and material at 4, which is why making the convention explicit
    matters for verification against an external implementation.
    """
    returns = [0.01, -0.01, 0.02, -0.02]
    result = realized_vol_simple(RealizedVolInputs(returns=returns, window=4, periods_per_year=252))
    mean = sum(returns) / len(returns)
    ddof0 = math.sqrt(sum((r - mean) ** 2 for r in returns) / len(returns)) * math.sqrt(252) * 100
    assert as_float(result) != pytest.approx(ddof0, abs=0.0001)
    assert as_float(result) > ddof0


def test_realized_vol_is_flat_across_a_constant_series() -> None:
    """Zero variance must give exactly zero, not a tiny positive residual."""
    result = realized_vol_simple(
        RealizedVolInputs(returns=[0.01] * 10, window=10, periods_per_year=252)
    )
    assert as_float(result) == pytest.approx(0.0, abs=1e-9)


def test_realized_vol_uses_only_the_trailing_window() -> None:
    """A violent early history must not affect a short trailing window.

    This is the guard that catches using the whole series instead of the
    window: the two differ enormously here, and a test on the full-series
    answer would not notice.
    """
    calm_tail = [0.001, -0.001, 0.002, -0.002]
    wild_history = [0.15, -0.15, 0.20, -0.20, 0.10, -0.10]
    result = realized_vol_simple(
        RealizedVolInputs(returns=[*wild_history, *calm_tail], window=4, periods_per_year=252)
    )
    expected_calm = math.sqrt(sum((r - 0.0) ** 2 for r in calm_tail) / 3) * math.sqrt(252) * 100
    assert as_float(result) == pytest.approx(expected_calm, abs=0.001)
    assert as_float(result) < 30.0, "the wild history must not leak into the window"


def test_realized_vol_rejects_a_window_longer_than_the_series() -> None:
    with pytest.raises(ValueError, match="at least one full window"):
        realized_vol_simple(
            RealizedVolInputs(returns=[0.01, 0.02], window=10, periods_per_year=252)
        )


def test_realized_vol_respects_the_annualisation_factor() -> None:
    """A monthly series must not be annualised by sqrt(252).

    The specification's sample code hardcodes 252, silently assuming daily
    data. This asserts the factor is honoured: monthly and daily annualisation
    of the same returns differ by sqrt(252/12) = sqrt(21) ~ 4.58x.
    """
    returns = [0.01, -0.01, 0.02, -0.02, 0.015, -0.005]
    daily = realized_vol_simple(RealizedVolInputs(returns=returns, window=6, periods_per_year=252))
    monthly = realized_vol_simple(RealizedVolInputs(returns=returns, window=6, periods_per_year=12))
    # Tolerance 1e-4 rather than 1e-6: both results are rounded to 4 decimal
    # places in percent before the division, so the ratio inherits that
    # rounding. Asserting tighter would test the rounding, not the factor.
    assert as_float(daily) / as_float(monthly) == pytest.approx(math.sqrt(252 / 12), abs=1e-4)


def test_portfolio_volatility_two_asset_matches_hand_calculation() -> None:
    """Section 15.20 part C's formula, verified by hand.

    w1=0.6, w2=0.4, s1=0.20, s2=0.10, rho=0.5:
        var = 0.36*0.04 + 0.16*0.01 + 2*0.6*0.4*0.5*0.20*0.10
            = 0.0144 + 0.0016 + 0.0048 = 0.0208
        vol = sqrt(0.0208) = 0.1442220500...  -> 0.144222
    """
    result = portfolio_volatility_two_asset(
        TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=0.20, vol2=0.10, correlation=0.5)
    )
    assert as_float(result) == pytest.approx(0.144222, abs=1e-6)


def test_portfolio_volatility_at_rho_one_equals_the_weighted_sum() -> None:
    """The boundary where diversification vanishes.

    A genuine identity, and the strongest single check on the cross term: at
    rho = 1 the formula must collapse exactly to w1*s1 + w2*s2. If the cross
    term were dropped, doubled, or mis-signed, this would fail.
    """
    result = portfolio_volatility_two_asset(
        TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=0.20, vol2=0.10, correlation=1.0)
    )
    assert as_float(result) == pytest.approx(0.16, abs=1e-9)
    assert "weighted sum of parts 16.0000%" in result.interpretation


def test_portfolio_volatility_decreases_monotonically_as_correlation_falls() -> None:
    """Less correlation must mean less portfolio volatility, always.

    Asserted across the full range rather than at one point, because the
    direction of the cross-term's sign is the entire economic content of the
    formula and a single sample could pass with a subtly wrong coefficient.
    """
    volatilities = []
    for rho in (1.0, 0.75, 0.5, 0.25, 0.0, -0.25, -0.5):
        result = portfolio_volatility_two_asset(
            TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=0.20, vol2=0.10, correlation=rho)
        )
        volatilities.append(as_float(result))

    for earlier, later in zip(volatilities, volatilities[1:], strict=False):
        assert later < earlier, "portfolio volatility must fall as correlation falls"


def test_portfolio_volatility_reports_the_diversification_benefit() -> None:
    """The benefit must appear in the interpretation, not just the value.

    The weighted sum of parts is 0.6*0.20 + 0.4*0.10 = 0.16, and the portfolio
    volatility at rho=0.5 is 0.144222, so the benefit is 0.015778.
    """
    result = portfolio_volatility_two_asset(
        TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=0.20, vol2=0.10, correlation=0.5)
    )
    assert "diversification benefit" in result.interpretation
    assert "1.5778%" in result.interpretation


def test_portfolio_volatility_rejects_an_infeasible_covariance() -> None:
    """A hand-edited correlation outside [-1, 1] must be refused.

    The field constraint catches rho=1.5 before it reaches the arithmetic, so
    this asserts the constraint rather than a negative-variance branch.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=0.20, vol2=0.10, correlation=1.5)


def test_portfolio_volatility_warns_about_crisis_correlation() -> None:
    """Section 15.20 part C's LTCM lesson must be output on every call."""
    result = portfolio_volatility_two_asset(
        TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=0.20, vol2=0.10, correlation=0.5)
    )
    assert any("crisis" in warning for warning in result.warnings)
    assert any("LTCM" in warning for warning in result.warnings)


def test_all_risk_confidences_are_computed_not_literal() -> None:
    """Section 22.8: every confidence in this module comes from the formula."""
    from macro_engine.config import get_settings

    settings = get_settings()
    base = settings.scalar("confidence.base")
    penalty = settings.scalar("confidence.data_quality_flag_penalty")

    # The 500-observation series has a well-populated tail, so no penalty.
    well_populated = [((index % 20) - 10) / 100.0 for index in range(500)]
    assert historical_var(ReturnsInputs(returns=well_populated)).confidence == pytest.approx(
        base, abs=1e-9
    )
    assert expected_shortfall(ReturnsInputs(returns=well_populated)).confidence == pytest.approx(
        base, abs=1e-9
    )
    assert portfolio_volatility_two_asset(
        TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=0.2, vol2=0.1, correlation=0.5)
    ).confidence == pytest.approx(base, abs=1e-9)

    # The small sample carries the flag penalty. 0.7 - 0.25 = 0.45.
    assert historical_var(ReturnsInputs(returns=_HAND_RETURNS)).confidence == pytest.approx(
        base - penalty, abs=1e-9
    )


# ---------------------------------------------------------------------------
# n-asset portfolio variance and risk contribution (Section 15.20 part C)
# ---------------------------------------------------------------------------

# Hand-worked three-asset example.
#
#   w     = [0.50,  0.30,  0.20]
#   Sigma = [[0.0400, 0.0000, 0.0100],
#            [0.0000, 0.0900, 0.0000],
#            [0.0100, 0.0000, 0.0625]]
#
#   Sigma @ w = [0.04*0.50 + 0.01*0.20,         = 0.0200 + 0.0020 = 0.0220
#                0.09*0.30,                                = 0.0270
#                0.01*0.50 + 0.0625*0.20]       = 0.0050 + 0.0125 = 0.0175
#
#   variance  = 0.50*0.0220 + 0.30*0.0270 + 0.20*0.0175
#             = 0.01100 + 0.00810 + 0.00350 = 0.02260
#   vol       = sqrt(0.02260) = 0.1503329637837290...
#
#   rc_i      = w_i * (Sigma @ w)_i
#             = [0.50*0.0220, 0.30*0.0270, 0.20*0.0175]
#             = [0.01100, 0.00810, 0.00350]        sums to 0.02260 = variance
#   shares    = [0.4867256637168141, 0.3584070796460177, 0.1548672566371681]
_HAND_WEIGHTS = [0.50, 0.30, 0.20]
_HAND_COVARIANCE = [
    [0.0400, 0.0000, 0.0100],
    [0.0000, 0.0900, 0.0000],
    [0.0100, 0.0000, 0.0625],
]
_HAND_VOL_N_ASSET = 0.15033296378372907


def test_portfolio_volatility_n_asset_matches_hand_calculation() -> None:
    """Every digit below was computed by hand before the function existed.

    The tolerance is ``1e-6`` rather than machine epsilon because Section 15.20
    part C mandates ``round(vol_p, 6)`` for the returned value — the function
    deliberately reports a volatility to six decimal places. A tighter
    assertion would be testing the rounding boundary rather than the arithmetic.
    """
    result = portfolio_volatility_n_asset(_HAND_WEIGHTS, _HAND_COVARIANCE)
    assert isinstance(result.value, float)
    assert result.value == pytest.approx(_HAND_VOL_N_ASSET, abs=1e-6)
    assert result.model_name == "portfolio_volatility_n_asset"


def test_portfolio_volatility_n_asset_reduces_to_the_two_asset_formula() -> None:
    """The 2x2 case must agree with the closed-form two-asset function.

    This is the identity that proves the matrix form is the same quantity
    rather than merely a similar one. rho = 0.5, s1 = 20%, s2 = 10%
    gives cov12 = 0.5 * 0.20 * 0.10 = 0.01.
    """
    vol1, vol2, rho = 0.20, 0.10, 0.5
    covariance = [[vol1**2, rho * vol1 * vol2], [rho * vol1 * vol2, vol2**2]]

    matrix_result = portfolio_volatility_n_asset([0.6, 0.4], covariance)
    closed_form = portfolio_volatility_two_asset(
        TwoAssetPortfolioInputs(w1=0.6, w2=0.4, vol1=vol1, vol2=vol2, correlation=rho)
    )
    assert isinstance(matrix_result.value, float)
    assert isinstance(closed_form.value, float)
    assert matrix_result.value == pytest.approx(closed_form.value, abs=1e-12)


def test_portfolio_volatility_n_asset_rejects_an_asymmetric_matrix() -> None:
    """An asymmetric matrix is a transcription error, not a covariance matrix."""
    broken = [
        [0.0400, 0.0100, 0.0100],
        [0.0200, 0.0900, 0.0000],  # [1][0] != [0][1]
        [0.0100, 0.0000, 0.0625],
    ]
    with pytest.raises(ValueError, match=r"not symmetric"):
        portfolio_volatility_n_asset([0.5, 0.3, 0.2], broken)


def test_portfolio_volatility_n_asset_rejects_a_shape_mismatch() -> None:
    with pytest.raises(ValueError, match=r"Both describe the same assets"):
        portfolio_volatility_n_asset([0.5, 0.5], _HAND_COVARIANCE)


def test_portfolio_volatility_n_asset_rejects_a_non_square_row() -> None:
    ragged = [[0.04, 0.0, 0.01], [0.0, 0.09], [0.01, 0.0, 0.0625]]
    with pytest.raises(ValueError, match=r"must be 3x3"):
        portfolio_volatility_n_asset([0.5, 0.3, 0.2], ragged)


def test_portfolio_volatility_n_asset_rejects_unnormalised_weights() -> None:
    """Weights summing to 3 describe three portfolios, not one."""
    with pytest.raises(ValueError, match=r"weights sum to"):
        portfolio_volatility_n_asset([1.5, 0.9, 0.6], _HAND_COVARIANCE)


def test_portfolio_volatility_n_asset_rejects_a_negative_variance_diagonal() -> None:
    broken = [[-0.04, 0.0, 0.01], [0.0, 0.09, 0.0], [0.01, 0.0, 0.0625]]
    with pytest.raises(ValueError, match=r"cannot be negative"):
        portfolio_volatility_n_asset([0.5, 0.3, 0.2], broken)


def test_portfolio_volatility_n_asset_raises_a_named_error_on_an_infeasible_matrix() -> None:
    """A non-PSD matrix must raise a message, never a bare math domain error.

    Correlations specified independently can form an impossible combination.
    ``math.sqrt`` of the resulting negative quadratic form would raise
    ``ValueError: math domain error``, naming no input — a puzzle rather than a
    diagnosis. The function checks first so the caller learns which input set
    is at fault.

    Note the weights. A non-positive-definite matrix has *some* direction with a
    negative quadratic form, but it is frequently not a long-only direction —
    an earlier version of this test used all-positive weights and the form came
    out positive, so the test silently failed to exercise the guard. A
    long/short book is a legitimate portfolio for this system, and
    ``[1.5, -0.5]`` (net long, sums to 1.0) is the direction that exposes it.
    """
    # Two assets with implied correlation 0.08/sqrt(0.04*0.04) = 2.0 — impossible.
    infeasible = [[0.04, 0.08], [0.08, 0.04]]
    with pytest.raises(ValueError, match=r"positive semi-definite"):
        portfolio_volatility_n_asset([1.5, -0.5], infeasible)


def test_marginal_risk_contributions_matches_hand_calculation() -> None:
    result = marginal_risk_contributions(_HAND_WEIGHTS, _HAND_COVARIANCE)
    assert isinstance(result.value, dict)
    contributions = result.value["risk_contributions"]
    assert contributions == pytest.approx([0.01100, 0.00810, 0.00350], abs=1e-10)

    shares = result.value["risk_contribution_pct"]
    assert shares == pytest.approx(
        [48.67256637168141, 35.84070796460177, 15.48672566371681], abs=1e-6
    )
    # ``portfolio_volatility`` is rounded to 10dp by the function, so the
    # tolerance must accommodate that rounding rather than exceed it.
    assert result.value["portfolio_volatility"] == pytest.approx(_HAND_VOL_N_ASSET, abs=1e-10)


def test_marginal_risk_contributions_sum_to_one_hundred_percent() -> None:
    """The defining property: the shares are a partition of total risk."""
    result = marginal_risk_contributions(_HAND_WEIGHTS, _HAND_COVARIANCE)
    assert isinstance(result.value, dict)
    shares = result.value["risk_contribution_pct"]
    assert sum(shares) == pytest.approx(100.0, abs=1e-9)


def test_marginal_risk_contributions_sum_to_the_portfolio_volatility() -> None:
    """Euler's theorem, asserted directly on the unnormalised contributions.

    RC sums to ``sigma_p``, not to 1, before normalisation. If the matrix is not
    positive semi-definite this identity breaks, and that is exactly the
    condition the function guards — so the test asserts the identity holds for a
    valid matrix.
    """
    result = marginal_risk_contributions(_HAND_WEIGHTS, _HAND_COVARIANCE)
    assert isinstance(result.value, dict)
    contributions = result.value["risk_contributions"]
    assert sum(contributions) == pytest.approx(_HAND_VOL_N_ASSET**2, abs=1e-12)


def test_risk_weights_diverge_from_dollar_weights() -> None:
    """Module 17.1's central claim, demonstrated rather than asserted in prose.

    Asset 1 is 50% of the notional but under half the risk here; asset 2 is 30%
    of notional and 35.8% of risk. The point is that they are simply different
    quantities — a book sized on dollars is not budgeted on risk.
    """
    result = marginal_risk_contributions(_HAND_WEIGHTS, _HAND_COVARIANCE)
    assert isinstance(result.value, dict)
    shares = result.value["risk_contribution_pct"]
    assert shares[1] > _HAND_WEIGHTS[1] * 100  # 35.84% of risk from 30% of notional
    assert shares[2] < _HAND_WEIGHTS[2] * 100  # 15.49% of risk from 20% of notional


def test_marginal_risk_contributions_warns_when_a_position_over_contributes() -> None:
    """A position contributing >125% of its notional share is the finding."""
    # Asset 0 has four times the volatility of asset 1 at equal weight.
    covariance = [[0.1600, 0.0], [0.0, 0.0100]]
    result = marginal_risk_contributions([0.5, 0.5], covariance)
    assert any("more risk" in warning for warning in result.warnings)
    assert any("Dollar weights and RISK weights" in warning for warning in result.warnings)


def test_marginal_risk_contributions_is_silent_when_risk_matches_notional() -> None:
    """No warning when the book is risk-balanced, so the warning means something."""
    # Identical, uncorrelated assets at equal weight contribute equally.
    covariance = [[0.0400, 0.0], [0.0, 0.0400]]
    result = marginal_risk_contributions([0.5, 0.5], covariance)
    assert not any("materially more risk" in warning for warning in result.warnings)


def test_marginal_risk_contributions_rejects_a_zero_volatility_portfolio() -> None:
    """Risk shares of nothing are undefined; ``nan`` would be a silent hole."""
    with pytest.raises(ValueError, match=r"undefined when"):
        marginal_risk_contributions([0.5, 0.5], [[0.0, 0.0], [0.0, 0.0]])


def test_n_asset_confidences_come_from_the_formula() -> None:
    """Section 22.8 — no hardcoded confidence in the new functions either."""
    from macro_engine.config import get_settings

    base = get_settings().scalar("confidence.base")
    vol_result = portfolio_volatility_n_asset(_HAND_WEIGHTS, _HAND_COVARIANCE)
    rc_result = marginal_risk_contributions(_HAND_WEIGHTS, _HAND_COVARIANCE)
    assert vol_result.confidence == pytest.approx(base, abs=1e-9)
    assert rc_result.confidence == pytest.approx(base, abs=1e-9)


# ---------------------------------------------------------------------------
# D-131 — the three Tier-1 WARNING thresholds are config leaves, not literals.
#
# Each guard below is a MOVER, not a pinner (D-031): the shipped leaf value
# EQUALS the old literal (5.0 / 1.5 / 1.25), so a test against a fixed input
# would pass on both the literal and the leaf. The only discriminating test
# monkeypatches the leaf and asserts the published behaviour follows it.
# ---------------------------------------------------------------------------


def test_the_sample_size_floor_is_taken_from_config_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`historical_var_min_tail_observations` must drive BOTH the warning and the flag.

    The literal it replaces (``5``) gated the tail warning AND
    ``ConfidenceInputs.data_quality_flags_present`` — so it decided the published
    CONFIDENCE, which is the §22.8 violation. Moving the leaf to 0.4 (below the
    0.5 tail count of the 10-observation fixture) must silence BOTH the warning
    and the confidence penalty; the shipped 5.0 fires both. A literal read would
    fail the moved-leaf half. The patch idiom is D-128's
    ``test_the_disclosure_follows_a_moved_leaf``: monkeypatch ``get_settings``
    in the module rather than mutating the cached singleton.
    """
    import macro_engine.models.risk as module
    from macro_engine.config import get_settings

    settings = get_settings()
    fixture = ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95)  # 0.5 tail obs

    shipped = historical_var(fixture)
    assert any("tail" in w.lower() for w in shipped.warnings)
    penalised = settings.scalar("confidence.base") - settings.scalar(
        "confidence.data_quality_flag_penalty"
    )
    assert shipped.confidence == pytest.approx(penalised, abs=1e-9)

    def _patched(floor: float) -> object:
        moved_risk = settings.risk.model_copy(
            update={
                "historical_var_min_tail_observations_value": (
                    settings.risk.historical_var_min_tail_observations_value.model_copy(
                        update={"value": floor}
                    )
                )
            }
        )
        return settings.model_copy(update={"risk": moved_risk})

    # Move the leaf below the fixture's tail count: BOTH must go quiet.
    monkeypatch.setattr(module, "get_settings", lambda: _patched(0.4))
    moved = historical_var(fixture)
    assert not any("few points" in w for w in moved.warnings), (
        "the tail warning fired below its configured floor — the code is not reading the leaf"
    )
    assert moved.confidence == pytest.approx(settings.scalar("confidence.base"), abs=1e-9), (
        "the confidence penalty survived a floor below the tail count — the leaf is not taken"
    )


def test_the_heavy_tail_threshold_is_taken_from_config_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`expected_shortfall_heavy_tail_ratio` must drive the warning.

    The 10-observation fixture has ES/VaR = 1.6 (> shipped 1.5 ⇒ warns). Raising
    the leaf to 5.0 must silence it; a literal read would keep warning.
    """
    import macro_engine.models.risk as module
    from macro_engine.config import get_settings

    settings = get_settings()
    fixture = ReturnsInputs(returns=_HAND_RETURNS, confidence=0.95)

    assert any("heavy relative to its boundary" in w for w in expected_shortfall(fixture).warnings)

    def _patched(ratio: float) -> object:
        moved_risk = settings.risk.model_copy(
            update={
                "expected_shortfall_heavy_tail_ratio_value": (
                    settings.risk.expected_shortfall_heavy_tail_ratio_value.model_copy(
                        update={"value": ratio}
                    )
                )
            }
        )
        return settings.model_copy(update={"risk": moved_risk})

    monkeypatch.setattr(module, "get_settings", lambda: _patched(5.0))
    moved = expected_shortfall(fixture)
    assert not any("heavy relative to its boundary" in w for w in moved.warnings), (
        "the heavy-tail warning fired above its configured threshold — the leaf is not taken"
    )


def test_the_overweight_multiple_is_taken_from_config_not_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`risk_contribution_overweight_multiple` must drive the over-contribution flag.

    Asset 0 has 4x the vol of asset 1 at equal weight, so its risk share is 4x
    its notional share (> shipped 1.25 ⇒ warns). Raising the leaf to 5.0 must
    silence it; a literal read would keep warning.
    """
    import macro_engine.models.risk as module
    from macro_engine.config import get_settings

    settings = get_settings()
    covariance = [[0.1600, 0.0], [0.0, 0.0100]]

    assert any(
        "materially more risk" in w
        for w in marginal_risk_contributions([0.5, 0.5], covariance).warnings
    )

    def _patched(multiple: float) -> object:
        moved_risk = settings.risk.model_copy(
            update={
                "risk_contribution_overweight_multiple_value": (
                    settings.risk.risk_contribution_overweight_multiple_value.model_copy(
                        update={"value": multiple}
                    )
                )
            }
        )
        return settings.model_copy(update={"risk": moved_risk})

    monkeypatch.setattr(module, "get_settings", lambda: _patched(5.0))
    moved = marginal_risk_contributions([0.5, 0.5], covariance)
    assert not any("materially more risk" in w for w in moved.warnings), (
        "the over-contribution flag fired above its configured multiple — the leaf is not taken"
    )


# ===========================================================================
# D-139b — the finiteness guard for LIST and NESTED-LIST inputs
#
# The repo-wide finiteness sweep in tests/models/test_finite_inputs_repo_wide.py
# probes the FIRST float field of each input group. For a group whose first
# float field is a ``list[float]`` (``ReturnsInputs.returns``), replacing the
# whole field with a scalar ``nan`` is refused because it is no longer a list —
# a ValidationError for the WRONG reason, which the sweep reads as "guarded".
# Measured 2026-09-30: historical_var(returns=[-0.05, nan, 0.01, 0.02, -0.03])
# published value=nan. These tests pin the real guard.
# ===========================================================================


def test_a_nan_inside_the_returns_list_is_refused() -> None:
    """A nan ELEMENT of ``returns`` must be refused at construction (D-139b)."""
    with pytest.raises(ValidationError) as excinfo:
        ReturnsInputs(returns=[-0.05, math.nan, 0.01, 0.02, -0.03])
    assert "finite" in str(excinfo.value).lower()


def test_an_inf_inside_the_returns_list_is_refused() -> None:
    """``inf`` is the other half of the class — it inverts signs under subtraction."""
    for bad in (math.inf, -math.inf):
        with pytest.raises(ValidationError):
            ReturnsInputs(returns=[0.01, bad])


def test_a_nan_return_would_have_published_a_nan_var() -> None:
    """The measured consequence: a nan in the sample reaches the quantile.

    This is the end-to-end effect the input guard prevents. Stated as a test
    over ``_quantile`` (which is what ``historical_var`` reads) rather than over
    the now-guarded input, because the input can no longer be constructed with a
    nan — the point is that WITHOUT the guard this is what would ship.
    """
    from macro_engine.models.risk import _quantile

    # sorted() places nan last, so the 0.05 quantile of a contaminated sample
    # can select it; the VaR is then nan, published as a "risk number".
    contaminated = [-0.05, math.nan, 0.01, 0.02, -0.03]
    quantile = _quantile(sorted(contaminated), 0.05)
    assert math.isnan(quantile), (
        "the premise of the guard no longer holds: a nan element must reach the "
        "quantile for the input refusal to be load-bearing"
    )


def test_realized_vol_refuses_a_nan_return() -> None:
    """``RealizedVolInputs`` inherits the guard (D-139b)."""
    with pytest.raises(ValidationError):
        RealizedVolInputs(returns=[0.01, math.nan, 0.02])


def test_portfolio_var_refuses_a_nan_in_the_nested_covariance_matrix() -> None:
    """The RECURSIVE branch: a nan inside ``list[list[float]]`` is refused.

    This is the case a one-level scan misses — an element of the matrix is a
    ``list``, not a ``float`` — and it is the one that matters most, because a
    nan covariance diagonal yields a nan portfolio volatility.
    """
    from macro_engine.models.risk import PortfolioVaRInputs

    with pytest.raises(ValidationError) as excinfo:
        PortfolioVaRInputs(
            weights=[1.0],
            covariance_matrix=[[math.nan]],
            portfolio_value=100.0,
        )
    # The error must name the CELL, not merely the field.
    assert "covariance_matrix[0][0]" in str(excinfo.value)


def test_monte_carlo_refuses_a_nan_off_diagonal_correlation() -> None:
    """``MonteCarloVaRInputs`` refuses a nested nan in ``normal_correlations``."""
    from macro_engine.models.risk import MonteCarloVaRInputs

    with pytest.raises(ValidationError) as excinfo:
        MonteCarloVaRInputs(
            weights=[1.0, -0.5],
            factor_volatilities=[0.1, 0.2],
            normal_correlations=[[1.0, math.nan], [math.nan, 1.0]],
            portfolio_value=100.0,
        )
    assert "normal_correlations[0][1]" in str(excinfo.value)


def test_parametric_var_refuses_an_infinite_volatility() -> None:
    """``+inf`` passes ``ge=0.0``, so only the shared guard catches it (D-139b)."""
    with pytest.raises(ValidationError):
        ParametricVaRInputs(portfolio_value=100.0, vol_annualized=math.inf)


def test_valid_list_and_matrix_inputs_still_construct() -> None:
    """The positive control: the recursive walk must not reject finite data."""
    from macro_engine.models.risk import MonteCarloVaRInputs, PortfolioVaRInputs

    assert ReturnsInputs(returns=[0.01, -0.02]).returns == [0.01, -0.02]
    assert RealizedVolInputs(returns=[0.01, -0.02]).window == 21
    assert PortfolioVaRInputs(
        weights=[1.0], covariance_matrix=[[0.04]], portfolio_value=100.0
    ).weights == [1.0]
    assert MonteCarloVaRInputs(
        weights=[1.0, -0.5],
        factor_volatilities=[0.1, 0.2],
        normal_correlations=[[1.0, 0.2], [0.2, 1.0]],
        portfolio_value=100.0,
    ).weights == [1.0, -0.5]
