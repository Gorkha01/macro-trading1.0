"""Module 17's volatility models — the starter and its Phase 5+ GARCH upgrade.

Section 6.10 names this file as the home of the ``arch``/GARCH hook, and §4's
dependency table routes ``arch`` here:

    | `arch` | GARCH-family conditional volatility | `models/volatility.py` | 5+ |

**Why the starter does not live here.** The Phase 1 starter shipped as
``risk.realized_vol_simple`` rather than in this file, and it is re-exported
below rather than copied. LAW 2 is explicit — one canonical implementation per
quantity — and a second copy of the rolling standard deviation would be free to
drift from the first. This module therefore owns the *upgrade* and delegates the
*starter*, which is also the direction the spec's own comment points:
``volatility.py  # Module 17 (starter; arch/GARCH hook)``.

The two estimators answer different questions, and the distinction is the whole
reason this file exists:

* ``realized_vol_simple`` is **unconditional**. It measures the trailing sample
  and asserts nothing about the next period. Its own warning says so.
* ``garch_conditional_volatility`` is **conditional**. Volatility clusters —
  today's variance depends on yesterday's — and a GARCH model estimates that
  dependence in order to *forecast* the next period's variance.

Section 2.6 of ``docs/PHASE5_DEFERRED.md`` settles the naming: in this
specification "conditional forecast" **is** the GARCH item. They are one gap,
not two.

Units, derived by hand (LAW 3)
------------------------------
The chain is stated once here because every step is a place a silent factor
error can hide:

1. ``inputs.returns`` are **DECIMALS** (``0.01`` = +1%), matching
   ``RealizedVolInputs``.
2. ``arch_model(..., rescale=False)`` is passed the decimals **unchanged**, so
   the fitted ``omega``/``alpha``/``beta`` and the forecast ``variance`` are in
   **DECIMAL SQUARED**. ``rescale=True`` would silently divide the series by its
   own standard deviation and make every parameter uninterpretable against the
   input, so it is switched off explicitly. *Measured against the installed
   ``arch==8.0.0``: unit-variance returns return a forecast variance of ~1.02.*
3. ``sigma_period = sqrt(variance)`` — **DECIMAL per period**.
4. ``sigma_annual = sigma_period * sqrt(periods_per_year)`` — **DECIMAL per
   year**. The square-root-of-time scaling is the same convention
   ``realized_vol_simple`` uses.
5. ``value = sigma_annual * 100`` — **PERCENT**, which is the published unit for
   every volatility ``ModelResult`` in this project.

Step 2 is the one that would be wrong by a factor of 10,000 if ``rescale`` were
left at its default while the returns were passed as percent, and step 5 is the
one that would be wrong by 100 if the annualised decimal were published raw.
Both are asserted in ``tests/models/test_volatility.py``.
"""

from __future__ import annotations

import math
from typing import cast

import numpy as np
from arch import arch_model
from pydantic import ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import FiniteInputs, ModelResult, utc_now
from macro_engine.models.risk import RealizedVolInputs, realized_vol_simple

__all__ = [
    "GarchInputs",
    "RealizedVolInputs",
    "garch_conditional_volatility",
    "realized_vol_simple",
]


class GarchInputs(FiniteInputs):
    """A return series, its annualisation convention, and the forecast horizon.

    ``periods_per_year`` is a field for the same reason
    ``RealizedVolInputs`` makes it one: it is the difference between daily and
    monthly data being annualised correctly or by a factor of about 4.6, and a
    hardcoded ``252`` silently assumes daily.

    Inherits ``FiniteInputs``: a non-finite return ELEMENT would otherwise pass
    into the likelihood and produce a fitted parameter that is itself ``nan``,
    which publishes as a plausible-looking volatility.
    """

    model_config = ConfigDict(extra="forbid")

    returns: list[float] = Field(
        min_length=2, description="Period returns as DECIMALS, oldest first."
    )
    periods_per_year: int = Field(
        default=252, gt=0, description="Annualisation factor: 252 daily, 52 weekly, 12 monthly."
    )
    horizon: int = Field(
        default=1,
        gt=0,
        le=60,
        description=(
            "Periods ahead to forecast. 1 is the next period — the only horizon a "
            "GARCH(1,1) forecast has any claim to. Above 1 the forecast mean-reverts "
            "toward the unconditional variance, which is a model property, not data."
        ),
    )


def garch_conditional_volatility(inputs: GarchInputs) -> ModelResult:
    """GARCH(p, q) conditional-variance forecast, annualised, in PERCENT.

    The Phase 5+ replacement for the backward-looking starter. Section 6.10 and
    §2.6 of ``docs/PHASE5_DEFERRED.md``: a "conditional forecast" and "the GARCH
    item" are the same obligation.

    **What is estimated.** A constant mean, a GARCH(p, q) conditional variance
    and normal errors — ``arch_model``'s default specification, with ``p`` and
    ``q`` read from config so a caller wanting GARCH(2, 1) does not edit code:

        r_t     = mu + e_t
        sigma2_t = omega + sum(alpha_i e^2_{t-i}) + sum(beta_j sigma2_{t-j})
        e_t     = sigma_t * z_t,   z_t ~ N(0, 1)

    **What is published.** The ``horizon``-step-ahead conditional volatility,
    annualised and expressed in percent, on the same basis as
    ``realized_vol_simple`` so the two are directly comparable.

    **What is refused, rather than warned about.** A series shorter than
    ``volatility.min_observations`` raises. A maximum-likelihood fit on a short
    sample produces standard errors larger than its point estimate, and a
    volatility number with no data behind it is worse than no number — the
    Section 21.4 rule that the system says "unavailable" instead of guessing.

    **What is warned about, because the fit is still informative.**

    * Normal errors are an assumption, not a measurement. Financial returns are
      leptokurtic, so the fitted likelihood understates tail risk.
    * ``alpha`` and ``beta`` are themselves ESTIMATES with error, and the
      published volatility is a nonlinear function of them.
    * ``alpha + beta >= persistence_ceiling`` means the conditional variance is
      non-stationary (IGARCH): the unconditional variance does not exist and the
      forecast diverges with horizon, so the number is not an estimate of a
      stable quantity.
    * A ``horizon`` above 1 mean-reverts toward that unconditional variance —
      which the fit does not establish when persistence is at the ceiling.
    """
    settings = get_settings().volatility

    if len(inputs.returns) < settings.min_observations_value:
        raise ValueError(
            f"GARCH needs at least {settings.min_observations_value} return "
            f"observations (volatility.min_observations); got {len(inputs.returns)}. "
            "A maximum-likelihood fit below that floor publishes a point estimate "
            "whose standard error exceeds it, so this refuses rather than warns "
            "(Section 21.4: say unavailable, do not guess)."
        )

    # `rescale=False` is load-bearing — see the module docstring, step 2. The
    # default (True) divides the series by its own standard deviation, which
    # makes every fitted parameter uninterpretable against the input units.
    model = arch_model(
        np.asarray(inputs.returns, dtype=float),
        mean="Constant",
        vol="GARCH",
        p=settings.garch_p_value,
        q=settings.garch_q_value,
        dist="normal",
        rescale=False,
    )
    fit = model.fit(disp="off")
    forecast = fit.forecast(horizon=inputs.horizon, reindex=False)

    # The forecast DataFrames are indexed by observation and carry one column
    # per step ahead, named `h.1` … `h.N`. The last row is the forecast made
    # from the final observation, which is the only one that is a forecast.
    variance_row = forecast.variance.iloc[-1]
    # `.iloc` is typed as a broad union (it can return a scalar, a Series, a
    # dict, ...). This call site knows it is the single `h.N` cell, so the cast
    # is asserted rather than assumed — `float()` on a Series raises, which is
    # the failure this would produce if the shape ever changed.
    variance = float(cast("float", variance_row.iloc[-1]))
    if not math.isfinite(variance) or variance < 0.0:
        raise ValueError(
            f"the GARCH fit produced a non-finite or negative forecast variance "
            f"({variance!r}) at horizon {inputs.horizon}. The fit did not converge "
            f"to a usable conditional variance, so no volatility can be published "
            f"from it."
        )

    sigma_period = math.sqrt(variance)
    sigma_annual = sigma_period * math.sqrt(inputs.periods_per_year)
    value_pct = sigma_annual * 100.0

    params = {str(k): float(v) for k, v in fit.params.items()}
    alpha = sum(v for k, v in params.items() if k.startswith("alpha"))
    beta = sum(v for k, v in params.items() if k.startswith("beta"))
    persistence = alpha + beta

    warnings = [
        "Normal errors are an ASSUMPTION, not a measurement. Financial returns "
        "are leptokurtic, so this fit understates tail risk and its likelihood "
        "is not the true one.",
        "alpha and beta are ESTIMATES with standard errors of their own, and the "
        "published volatility is a nonlinear function of them — the interval "
        "around this number is wider than the number suggests.",
    ]
    if persistence >= settings.persistence_ceiling_value:
        warnings.append(
            f"NON-STATIONARY: alpha + beta = {persistence:.4f} >= "
            f"{settings.persistence_ceiling_value}. The conditional variance is "
            "an IGARCH process — the unconditional variance does not exist and "
            "the forecast diverges with horizon, so this number is not an "
            "estimate of a stable quantity."
        )
    if inputs.horizon > 1:
        warnings.append(
            f"horizon={inputs.horizon}: beyond one step the GARCH forecast "
            "mean-reverts toward the unconditional variance. That reversion is a "
            "property of the MODEL, not a measurement of the data, so the longer "
            "the horizon the more of this number is the specification's assumption."
        )

    return ModelResult(
        model_name="garch_conditional_volatility",
        country="us",
        as_of=utc_now(),
        value=round(value_pct, 4),
        confidence=settings.confidence_value,
        interpretation=(
            f"GARCH({settings.garch_p_value}, {settings.garch_q_value}) conditional "
            f"volatility, {inputs.horizon}-period-ahead, annualised: "
            f"{value_pct:.4f}%"
        ),
        context=(
            f"Maximum-likelihood fit over {len(inputs.returns)} returns "
            f"(alpha={alpha:.4f}, beta={beta:.4f}, persistence={persistence:.4f}), "
            f"forecast variance in decimal^2, annualised by "
            f"sqrt({inputs.periods_per_year}). CONDITIONAL — unlike "
            f"realized_vol_simple this asserts something about the next period."
        ),
        inputs_used=["returns"],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percent",
        direction=(
            "a forward-looking conditional volatility estimate: the fitted "
            "variance depends on the previous shock and the previous variance"
        ),
        assumptions=[
            "The conditional variance follows GARCH(p, q) with a constant mean. "
            "That is a specification choice; an asymmetric (GJR/EGARCH) process "
            "or a non-constant mean would fit the same data differently.",
            "Errors are normally distributed, which the data are not.",
            "The parameters are constant over the estimation sample — no "
            "structural break, no regime change inside the window.",
            "Returns are DECIMALS and are passed to the fit UNSCALED "
            "(rescale=False), so the fitted parameters and the forecast variance "
            "are in the input's own squared units.",
        ],
        data_provenance=[
            "returns — supplied by the CALLER, not fetched. This module has no "
            "data-layer dependency: it is a pure estimator over whatever series "
            "the caller holds.",
        ],
    )
