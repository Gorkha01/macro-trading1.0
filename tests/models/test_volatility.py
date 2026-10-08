"""Tests for the Phase 5+ GARCH conditional-volatility forecast.

Every assertion is a BEHAVIOUR (a published value, a refusal, a warning), never
the presence of a line of source — the project's rule, learned three times.

The series is simulated from KNOWN parameters with a seeded generator, so the
fitted values can be checked against something other than the code under test.
"""

from __future__ import annotations

import math
from typing import cast

import numpy as np
import pytest
from arch import arch_model

from macro_engine.models.volatility import GarchInputs, garch_conditional_volatility

#: True data-generating parameters, in decimal^2 (daily).
_TRUE_OMEGA = 4e-6
_TRUE_ALPHA = 0.08
_TRUE_BETA = 0.90
_TRUE_PERSISTENCE = _TRUE_ALPHA + _TRUE_BETA  # 0.98


def _garch_series(
    n: int = 3000,
    *,
    omega: float = _TRUE_OMEGA,
    alpha: float = _TRUE_ALPHA,
    beta: float = _TRUE_BETA,
    seed: int = 7,
) -> list[float]:
    """Simulate a GARCH(1,1) return series with known parameters.

    Deterministic: a seeded generator, so the same list every run and the fitted
    values are comparable against fixed expectations.
    """
    rng = np.random.default_rng(seed)
    sigma2 = np.empty(n)
    eps = np.empty(n)
    sigma2[0] = omega / (1.0 - alpha - beta)
    for t in range(1, n):
        eps[t - 1] = math.sqrt(sigma2[t - 1]) * rng.standard_normal()
        sigma2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sigma2[t - 1]
    return [float(x) for x in eps[: n - 1]]


def _independent_annualised_pct(returns: list[float], *, periods: int, horizon: int) -> float:
    """Recompute the published quantity straight from `arch`, with no shared code.

    This is the units cross-check: if the model's own chain (sqrt, then
    sqrt(periods), then x100) is wrong, this disagrees with it.
    """
    fit = arch_model(
        np.asarray(returns, dtype=float),
        mean="Constant",
        vol="GARCH",
        p=1,
        q=1,
        dist="normal",
        rescale=False,
    ).fit(disp="off")
    variance = float(
        cast("float", fit.forecast(horizon=horizon, reindex=False).variance.iloc[-1].iloc[-1])
    )
    return math.sqrt(variance) * math.sqrt(periods) * 100.0


# ---------------------------------------------------------------------------
# Units — the failure mode a fitted model hides
# ---------------------------------------------------------------------------
def test_published_value_matches_an_independent_recompute_of_the_units_chain() -> None:
    """DECIMALS in -> variance in decimal^2 -> annualised decimal -> PERCENT.

    Four unit conversions stand between the input and the published number, and
    two of them would be wrong by a factor of 100 or 10,000 if the flags were
    left at their defaults. This pins the whole chain against a recompute that
    shares no code with the model.
    """
    returns = _garch_series()
    out = garch_conditional_volatility(GarchInputs(returns=returns, periods_per_year=252))
    expected = _independent_annualised_pct(returns, periods=252, horizon=1)
    assert out.value == pytest.approx(expected, abs=1e-4)
    assert out.unit == "percent"


def test_the_annualisation_factor_is_a_mover_not_a_restatement() -> None:
    """Doubling periods_per_year must scale the result by sqrt(2), not 2 and not 1.

    A test that only checked a plausible-looking percentage would pass with the
    square-root omitted. The ratio is the assertion.

    Tolerance is ``rel=1e-5`` rather than 1e-6 because the model publishes
    ``round(value, 4)`` — measured, the ratio of two 4-dp values carries ~1.7e-6
    of rounding error, which is the published contract rather than a defect.
    """
    returns = _garch_series()
    daily = garch_conditional_volatility(GarchInputs(returns=returns, periods_per_year=252))
    weekly = garch_conditional_volatility(GarchInputs(returns=returns, periods_per_year=504))
    assert cast("float", weekly.value) / cast("float", daily.value) == pytest.approx(
        math.sqrt(2.0), rel=1e-5
    )


# ---------------------------------------------------------------------------
# Estimation — does it recover what was simulated?
# ---------------------------------------------------------------------------
def test_fitted_persistence_recovers_the_simulated_parameter() -> None:
    """The fit must find the dependence that is actually in the data.

    A GARCH model that returned the unconditional variance would still produce a
    plausible number. The persistence is the quantity that distinguishes a real
    conditional fit from a constant, so it is what is asserted — against the
    KNOWN 0.98, not against whatever the fit happens to say.
    """
    out = garch_conditional_volatility(GarchInputs(returns=_garch_series()))
    measured = float(out.context.split("persistence=")[1].split(")")[0])
    assert measured == pytest.approx(_TRUE_PERSISTENCE, abs=0.02)


def test_a_conditional_forecast_differs_from_the_unconditional_volatility() -> None:
    """The whole point of the upgrade: it is NOT `realized_vol_simple`.

    Section 2.6 of PHASE5_DEFERRED.md — "conditional forecast" IS the GARCH
    item. If this number always equalled the unconditional variance, the
    function would be a more expensive spelling of the starter.
    """
    returns = _garch_series()
    out = garch_conditional_volatility(GarchInputs(returns=returns))
    unconditional = math.sqrt(_TRUE_OMEGA / (1.0 - _TRUE_PERSISTENCE)) * math.sqrt(252) * 100
    # The simulated path ends above its long-run level (recent shocks are
    # elevated), so the conditional forecast must sit ABOVE it — and must not be
    # within rounding of it.
    assert cast("float", out.value) > unconditional + 0.5


# ---------------------------------------------------------------------------
# Refusals — Section 21.4: say unavailable, do not guess
# ---------------------------------------------------------------------------
def test_a_short_series_is_refused_not_warned_about() -> None:
    """Below the sample floor the model raises, naming the config leaf."""
    with pytest.raises(ValueError, match=r"min_observations|at least"):
        garch_conditional_volatility(GarchInputs(returns=_garch_series(n=120)))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_return_is_refused_at_construction(bad: float) -> None:
    """Inherited `FiniteInputs`: a non-finite ELEMENT never reaches the fit.

    Measured reason: a `nan` in the likelihood produces a `nan` parameter, which
    publishes as a plausible-looking volatility.
    """
    returns = _garch_series(n=300)
    returns[10] = bad
    with pytest.raises(Exception, match=r"finite|non-finite|nan|inf"):
        GarchInputs(returns=returns)


# ---------------------------------------------------------------------------
# Warnings — each reachable branch asserted, per the project's convention
# ---------------------------------------------------------------------------
def test_a_near_integrated_series_fires_the_non_stationarity_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """alpha + beta >= the ceiling means the forecast is not an estimate of anything.

    ⚠️ **This branch is exercised through CONFIG, and the reason is a measured
    property of the estimator — recorded here because it is a real limitation.**

    The first version of this test simulated a series at a TRUE persistence of
    0.9995 and expected the fit to reproduce it. It does not. Measured on three
    simulated series (true sums 0.9800, 0.9900, 0.9995), the maximum-likelihood
    fit reported **0.9800 every time**, redistributing the weight between alpha
    and beta (0.10/0.88, 0.05/0.93, 0.20/0.78) rather than raising their sum. On
    near-integrated data the likelihood surface is flat in the sum, so the fit
    is not identified and **the non-stationarity check has limited power against
    a genuinely near-integrated process.**

    That is a property of GARCH MLE, not of this wrapper — and it means the
    branch cannot be reached reliably from a simulated series. Since the ceiling
    IS a config leaf, the branch is exercised by moving the leaf, which is how a
    caller would reach it in practice.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        type(settings.volatility),
        "persistence_ceiling_value",
        property(lambda _self: 0.5),
    )
    out = garch_conditional_volatility(GarchInputs(returns=_garch_series()))
    assert any("NON-STATIONARY" in w for w in out.warnings)


def test_a_horizon_above_one_discloses_that_the_reversion_is_the_model() -> None:
    """Longer horizons are more assumption and less measurement."""
    returns = _garch_series()
    one = garch_conditional_volatility(GarchInputs(returns=returns, horizon=1))
    five = garch_conditional_volatility(GarchInputs(returns=returns, horizon=5))
    assert not any("horizon=5" in w for w in one.warnings)
    assert any("horizon=5" in w for w in five.warnings)
    # Mean reversion toward the unconditional level: the 5-step forecast sits
    # between the 1-step forecast and the unconditional volatility.
    assert cast("float", five.value) < cast("float", one.value)


def test_the_normal_errors_assumption_is_always_disclosed() -> None:
    """The fit is still informative, so it warns rather than refusing."""
    out = garch_conditional_volatility(GarchInputs(returns=_garch_series()))
    assert any("Normal errors" in w for w in out.warnings)
    assert any("ESTIMATES" in w for w in out.warnings)


def test_the_starter_is_re_exported_not_duplicated() -> None:
    """LAW 2 — one canonical implementation of the rolling standard deviation."""
    from macro_engine.models import risk, volatility

    assert volatility.realized_vol_simple is risk.realized_vol_simple
    assert volatility.RealizedVolInputs is risk.RealizedVolInputs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
