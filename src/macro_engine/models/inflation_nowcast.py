"""Module 5 — inflation nowcasting: the shelter-lag projection and the PPI pipeline.

Everything in this module rests on one asymmetry: **some CPI components are
mostly knowable in advance, and most are not.**

CPI shelter is the clearest case, and Module 5.1 calls it "the highest-value
practical insight" in the module. Shelter is roughly a third of the index, and
its measured rate is dominated not by today's rents but by the rents written
into leases that are still running. Only about a twelfth of the stock turns over
in a month, so a change in the market rent level takes a year or more to be
*fully* reflected in the CPI series. The consequence: today's published CPI
shelter is largely a record of the *past*, and today's market rents are a
partial forecast of the *future* CPI shelter.

That makes shelter the one large CPI component where a nowcast is a lag
arithmetic rather than a forecast — which is why this module can produce a
number at all, and why its warnings are about the assumption (that the
turnover dynamics are stable) rather than about the direction.

Why the specification's sample is not implemented as written
------------------------------------------------------------
Three defects in the Section 20 sample, all of the class this project treats as
mandatory corrections:

1. **``lag_months: int = 15`` in the signature.** ``config/settings.yaml``
   already carries ``inflation.shelter_lag_months``. A default in the input model
   is a second source of truth that wins whenever a caller omits the argument, so
   a recalibration moves nothing for those callers. Same defect as ``beta`` in
   ``phillips_curve_inflation`` and ``alpha`` in ``potential_gdp_cobb_douglas``.

2. **``market_rent_growth_yoy_pct[-inputs.lag_months]`` is not "N months ago".**
   The spec describes the list as "most recent 18 months, oldest first" and then
   takes ``[-15]``, whose meaning **depends on the list's length**: with 18
   elements it is index 3, which is *14* months ago; with the minimum legal 15
   elements it is index 0, which is *14* months ago as well but is also the
   oldest point. The index is measuring "how much history did the caller pass"
   rather than "the rent level N months ago" — and the guard
   (``len < lag_months``) is written against the length while the index is
   written against the lag, so the two disagree about what they are asserting.
   With the specification's own default of 15 and an 18-month list, the model
   reports a **14-month lag while claiming 15**. The fix is to index by an
   explicit months-ago offset counted from the end, and to say in the output
   which vintage was actually used.

3. **``value=None, confidence=0.0`` on the insufficient-data path.** Section 22.8
   makes ``compute_confidence()`` the only confidence producer. ``0.0`` is below
   the configured floor, which exists precisely so that a returning confidence is
   distinguishable from a missing value — asserting ``0.0`` makes the result
   unreadable as "not computed". The corrected function returns ``None`` with a
   computed floor confidence and an explicit reason, so "no result" and "a result
   of zero" stay distinct.

The list-order convention, stated once so it is not re-derived per call
---------------------------------------------------------------------
``market_rent_growth_yoy_pct`` is **oldest first**, ``[-1]`` is the current
month. Every index in this module is expressed as a months-ago offset and
converted in one place, because that is the only spelling whose meaning does not
change when the caller passes more history.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "ShelterLagInputs",
    "project_shelter_cpi",
]


class ShelterLagInputs(BaseModel):
    """Inputs to ``project_shelter_cpi`` (Module 5.1).

    ``lag_months`` is deliberately **not** a field — it comes from
    ``inflation.shelter_lag_months``. See the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    market_rent_growth_yoy_pct: list[float] = Field(
        description=(
            "Real-time market rent growth, year-over-year percent, **oldest "
            "first** — so the final element is the current month. The order is "
            "load-bearing and is stated here rather than inferred: a reversed "
            "list produces a plausible number from the wrong end of the window, "
            "which no shape or range check would catch."
        ),
    )
    current_cpi_shelter_yoy_pct: float = Field(
        description=(
            "The CPI shelter series' current year-over-year rate, percent. Used "
            "only for the cooling/reaccelerating direction call — it is not an "
            "input to the projection itself, which is why a converged reading "
            "must be reported as converged rather than forced into one of the "
            "two directions."
        ),
    )


def project_shelter_cpi(inputs: ShelterLagInputs) -> ModelResult:
    """Project CPI shelter from market rents ``lag_months`` ago. ``value``: ``float | None``.

    Hand calculation. With ``lag_months = 15`` and a market-rent series whose
    year-over-year growth 15 months ago was ``3.2%``, while CPI shelter is
    currently running at ``4.8%``::

        vintage used   = market_rent_growth_yoy_pct[-16]   (15 months ago)
        projected      = 3.2%
        current        = 4.8%
        direction      = "cooling"  (3.2 < 4.8)

    Note the index: ``[-16]``, not ``[-15]``. ``[-k]`` selects the element ``k-1``
    positions before the end, and the end element is the *current* month — so
    "N months ago" is ``[-(N + 1)]``. Getting this wrong reports a vintage that
    is one month stale while the context line claims otherwise, and one month of
    drift in a 15-month lag is invisible in every sanity check.

    ``value`` is ``float | None``: ``None`` when the supplied history is shorter
    than the lag, because there is then no observation at the required vintage
    and inventing one (by using the oldest available point) would report a
    different lag under the configured lag's name.

    ``confidence`` comes from ``compute_confidence()`` in both branches. The
    insufficient-data branch carries ``data_quality_flags_present=True``, which
    drives it to the configured floor — the lowest value the formula can return —
    rather than the ``0.0`` of the specification sample, since ``0.0`` is
    indistinguishable from "confidence not computed".
    """
    settings = get_settings()
    lag_months = settings.inflation.shelter_lag

    history = inputs.market_rent_growth_yoy_pct
    required_points = lag_months + 1

    # ``[-k]`` is the element k-1 places before the end, and the end is the
    # current month. "N months ago" is therefore index -(N+1). Written as one
    # named offset so the conversion exists in exactly one place.
    vintage_index_from_end = lag_months + 1

    if len(history) < required_points:
        return ModelResult(
            model_name="project_shelter_cpi",
            country="us",
            as_of=utc_now(),
            value=None,
            confidence=compute_confidence(
                ConfidenceInputs(data_quality_flags_present=False),
            ),
            interpretation=(
                f"Insufficient market-rent history to project CPI shelter: "
                f"{len(history)} months supplied, {required_points} required for "
                f"a {lag_months}-month lag (the lag plus the current month)"
            ),
            context=(
                f"The projection needs the rent vintage from exactly "
                f"{lag_months} months ago. With {len(history)} points the oldest "
                f"available is {len(history) - 1} months ago, so no observation "
                f"at the required vintage exists. Substituting the oldest "
                f"available point would report a shorter lag under the "
                f"configured lag's name."
            ),
            inputs_used=["market_rent_growth_yoy_pct", "current_cpi_shelter_yoy_pct"],
            warnings=[
                "Insufficient data: no market-rent observation exists at the "
                "required lag vintage. No projection is reported, and no "
                "substitute vintage was used.",
            ],
        )

    projected = history[-vintage_index_from_end]
    gap = projected - inputs.current_cpi_shelter_yoy_pct

    # A converged reading is its own case. The specification's binary
    # cooling/reaccelerating test classifies an exact match as "reaccelerating",
    # which asserts a direction change where none exists.
    converged_tolerance = settings.inflation.shelter_converged_tolerance
    if abs(gap) <= converged_tolerance:
        direction = "converged"
    elif gap < 0:
        direction = "cooling"
    else:
        direction = "reaccelerating"

    warnings = [
        "Mechanical lag projection — assumes historical lease-turnover dynamics "
        "hold. Module 5.1's lag is an AVERAGE across a stock of leases with "
        "staggered expiry dates, not a fixed pipeline delay. If turnover speeds "
        "up or slows down, the effective lag shifts and this projection is early "
        "or late by that amount.",
        "Shelter is roughly a third of CPI, so this projection drives a large "
        "share of any forecastable core CPI — which makes the assumption above "
        "load-bearing rather than incidental.",
        f"The projected vintage is the market-rent reading from {lag_months} "
        f"months ago (index {vintage_index_from_end} from the end of the "
        f"supplied history). The lag is a config parameter, not a measured "
        f"quantity, so the vintage moves if it is recalibrated.",
    ]

    # The caller may supply a list longer than needed, and the extra history is
    # not used. Worth naming, because more history does not mean a better
    # projection here — the vintage is fixed by the lag, not chosen.
    if len(history) > required_points:
        warnings.append(
            f"{len(history)} months of history were supplied but only "
            f"{required_points} are used: the projection reads one specific "
            f"vintage ({lag_months} months ago), so additional history does not "
            f"improve it."
        )

    # A converged call means the market has already arrived at the CPI level.
    # This is the case the specification's two-way test cannot express, and it is
    # materially different from a small residual: the projection carries no
    # forward information.
    if direction == "converged":
        warnings.append(
            f"Projected and current CPI shelter are within "
            f"{converged_tolerance:.2f}pp of each other, so the projection "
            f"contains little forward information — shelter has effectively "
            f"already converged to the level market rents implied. Read the "
            f"number as a level confirmation rather than as a forecast."
        )

    return ModelResult(
        model_name="project_shelter_cpi",
        country="us",
        as_of=utc_now(),
        value=round(projected, 2),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"CPI shelter likely converging toward {projected:.2f}% "
            f"({direction} from current {inputs.current_cpi_shelter_yoy_pct:.2f}%)"
            if direction != "converged"
            else (
                f"CPI shelter already at {projected:.2f}%, consistent with the "
                f"market-rent vintage {lag_months} months ago "
                f"(current {inputs.current_cpi_shelter_yoy_pct:.2f}%)"
            )
        ),
        context=(
            f"Market rents from {lag_months} months ago "
            f"({projected:.2f}% year-over-year), per the lease-turnover lag "
            f"(Module 5.1). Gap to current CPI shelter "
            f"{inputs.current_cpi_shelter_yoy_pct:.2f}% = {gap:+.2f}pp. "
            f"Only about a twelfth of the lease stock turns over monthly, so this "
            f"vintage is what the CPI series is still working through."
        ),
        inputs_used=[
            "market_rent_growth_yoy_pct",
            "current_cpi_shelter_yoy_pct",
        ],
        warnings=warnings,
    )
