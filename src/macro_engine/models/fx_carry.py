"""Module 9 — FX Carry / Parity: covered interest parity and its deviations.

Section 6.7 gives this module three functions, and all three now live here:
:func:`cip_check` (D-108), :func:`carry_score` (D-109) and
:func:`dollar_smile_regime` (D-110), which completes Module 9. Section 20.9
supplies a fourth, :func:`uip_expected_move` (D-112), whose reference
implementation is the one-line ``i_domestic - i_foreign`` and which is
deliberately NOT a deviation of the CIP identity — see its own docstring for
why the two are different functions even though they read the same two rates.
Section 6.7 also supplies a **reference implementation** for each — so these
are stubs to UPGRADE, not functions to invent — and the reference
implementation of :func:`cip_check` is the simplest possible form::

    implied_forward = spot * (1 + i_domestic) / (1 + i_foreign)
    deviation_pct   = (forward - implied_forward) / implied_forward * 100

with no bid/ask, no day-count, no settlement convention, no annualisation of
the rates, and a hardcoded ``confidence=0.7``. Every one of those is restored
here except bid/ask and settlement, which are disclosed in ``limitations``
rather than silently dropped.

The parity identity, derived rather than recalled
-------------------------------------------------
Covered interest parity states that a forward exchange rate is pinned by the
two interest rates, because otherwise a riskless round trip exists. Take one
unit of the DOMESTIC currency:

* **Direct route** — lend domestically at ``i_d``; at maturity you hold
  ``(1 + i_d)``.
* **Synthetic route** — buy foreign currency at the spot rate ``S`` (getting
  ``1 / S`` foreign per unit domestic), lend it at ``i_f`` (holding
  ``(1 + i_f) / S`` foreign), and sell the proceeds forward at ``F`` (holding
  ``F * (1 + i_f) / S`` domestic).

Both routes are riskless once the forward is dealt, so no-arbitrage forces them
to be equal::

    (1 + i_d) = F * (1 + i_f) / S        =>     F = S * (1 + i_d) / (1 + i_f)

which is the specification's formula. The rates must be the **period** rates
over the forward's own tenor, not annualised ones — the identity is a statement
about one horizon, and dividing two annualised rates is only correct if both
share the horizon the forward actually covers. That conversion is done here,
from annualised inputs, because that is what every data source publishes.

The sign, derived rather than recalled
--------------------------------------
The forward implied by parity is ``F_imp = S * (1 + i_d) / (1 + i_f)``, and the
published quantity is the OBSERVED forward's deviation from it::

    deviation_pct = (F - F_imp) / F_imp * 100

To read the sign, invert the parity identity into a **synthetic domestic
funding rate** — the rate you pay if you borrow foreign and convert the
proceeds into domestic currency today::

    (1 + i_d_synthetic) = (F / S) * (1 + i_f)
    =>  i_d_synthetic   = (F / S) * (1 + i_f) - 1

When the forward is exactly at parity this reproduces ``i_d``. When it is not::

    F = F_imp * (1 + dev)   =>   i_d_synthetic - i_d = (1 + i_d) * dev

so the **sign of the deviation is the sign of the synthetic-domestic minus
actual-domestic funding spread**, exactly. Positive means it costs *more* to
synthesize domestic funding through the FX swap than to borrow the domestic
currency directly — the domestic currency is the scarce side of the swap, which
is the "funding stress" the specification names. Negative means the foreign
currency is the scarce side. The relation ``basis_period = (1 + i_d) * dev`` is
an exact identity, not an approximation, and it is asserted in the test suite
between two published keys.

The stress bands are configured in ``config/settings.yaml`` under ``fx_carry``,
and the unit of those bands is the **forward deviation in percent**, not the
annualised basis the FX market quotes — the two differ by the tenor, and
conflating them rescales every verdict. See the YAML note.

Quote convention — the silent sign inversion
--------------------------------------------
``spot`` and ``forward`` are interpreted as **units of the domestic currency
per one unit of the foreign currency** (the domestic currency is the price
currency, e.g. ``EURUSD`` = 1.10 USD per EUR when the domestic currency is
USD). That is the convention the parity identity above is written in. The FX
market is not consistent about this: ``EURUSD`` is quoted USD-per-EUR while
``USDJPY`` is quoted JPY-per-USD, so a caller handling both cannot assume one.
The quote convention is therefore an explicit input, and a ``foreign_per_domestic``
quote is **inverted before the identity is applied** — the published deviation
is always in domestic-per-foreign space, so it is comparable across callers
rather than silently reversed.

Deliberately absent: any data fetching. Models consume aligned inputs
(Section 6) and the caller owns provenance; this module never reaches for a
provider.
"""

from __future__ import annotations

import math
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.data_layer.world_bank_client import fetch_ppp_implied_rate
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "CIPInputs",
    "CarryOutcome",
    "CarryScoreInputs",
    "DayCountBasis",
    "DollarSmileInputs",
    "DollarSmileSide",
    "FundingStressSide",
    "PPPInputs",
    "PPPStatus",
    "QuoteConvention",
    "StressSeverity",
    "UIPInputs",
    "carry_score",
    "cip_check",
    "dollar_smile_regime",
    "ppp_valuation",
    "uip_expected_move",
]

#: Money-market day-count bases, and the number of days each defines a year as.
#: The two members are the ones the major money markets actually use: USD and
#: EUR money markets are ACT/360, sterling and most sovereign markets ACT/365.
#: The mapping is the single source of the basis length, so a conversion and a
#: validation cannot disagree about how long a year is.
_BASIS_DAYS: dict[str, int] = {"actual_360": 360, "actual_365": 365}

#: The day-count basis the annualised rates are quoted on. A ``Literal`` rather
#: than a bare ``str`` so a typo is refused at construction instead of falling
#: through to an ``else`` and silently assuming ACT/360 (Section 21's rule).
DayCountBasis = Literal["actual_360", "actual_365"]

#: Which currency is the price currency of ``spot``/``forward``. See the module
#: docstring: the market quotes some pairs one way and some the other, so this
#: cannot be assumed.
QuoteConvention = Literal["domestic_per_foreign", "foreign_per_domestic"]

#: Which currency's funding is the expensive side of the swap. ``"none"`` when
#: the deviation is inside the configured notable band.
FundingStressSide = Literal["domestic", "foreign", "none"]

#: How far the deviation sits beyond the configured bands. ``"notable"`` is
#: ``|deviation|`` above ``fx_carry.notable_deviation_pct`` and at or below
#: ``fx_carry.extreme_deviation_pct``; ``"extreme"`` is above the latter.
StressSeverity = Literal["none", "notable", "extreme"]

#: Which side of the carry trade a positive score points at. A positive rate
#: differential means the domestic money market pays more, so the funded trade
#: is to LEND domestic and BORROW foreign — a long domestic-currency position
#: financed abroad. ``"flat"`` is an exactly zero differential, where there is
#: no carry to earn in either direction and the score is exactly zero.
CarryOutcome = Literal["long_domestic", "long_foreign", "flat"]

#: Which side of the **dollar smile** the inputs place the currency on.
#:
#: The smile is the U-shaped empirical relation between global risk appetite and
#: the dollar: USD strengthens at BOTH extremes and is weakest in the middle.
#: ``"left"`` is the risk-off/crisis limb (safe-haven demand), ``"right"`` is the
#: US-outperformance limb (a durable, rate/growth-driven bid), and ``"middle"``
#: is synchronized global growth, where diversification flows out of the dollar
#: dominate and it is typically weak. The three members are NOT ordered by
#: severity despite the model testing them most-severe-first: the left and right
#: limbs are both "USD strong" and are distinguished by WHY, which is what makes
#: the left limb reversal-prone and the right limb durable.
DollarSmileSide = Literal["left", "right", "middle"]

#: The label mix :func:`_dollar_smile_side` produces over the enumeration that
#: proves every branch reachable, as DECLARED CONSTANTS rather than values
#: recomputed at call time.
#:
#: **They are published because a classifier whose modal output is one label
#: reports construction rather than economics** (D-029/D-047), and this one is
#: close to that: on a uniform grid over the whole plausible domain the middle
#: limb is reached on about a third of the space and the right limb on well under
#: a tenth, because "both signed inputs strictly positive" is a much smaller
#: region than "either is not". A reader who sees only the label cannot tell that
#: from a finding.
#:
#: The enumeration is the 3 025-point grid the live check re-runs: ``vix_level``
#: at every 0.5 from 0 to 60 (121 points) crossed with both signed inputs drawn
#: from ``{-1.0, -1e-9, 0.0, +1e-9, +1.0}`` (25 points each). It is a
#: deliberate over-representation of near-zero inputs, which is the region the
#: zero-case decision is about; a coarser sign-only grid would hide it.
#:
#: **A share over an ENUMERABLE space is not a base rate over history**, and the
#: two can disagree in either direction (D-050 measured the same confusion
#: running the other way). These are properties of the partition and of the grid,
#: not occurrence frequencies, and the model says so in ``limitations``.
_DOLLAR_SMILE_BASE_RATES: dict[str, float] = {
    "left": 1750 / 3025,
    "right": 204 / 3025,
    "middle": 1071 / 3025,
}


class CIPInputs(BaseModel):
    """The two FX rates and the two money-market rates of one covered swap.

    Units and basis — stated because four bare floats cannot reveal them, and a
    parity check is exactly where a unit or quote-convention error produces a
    perfectly plausible number that means the opposite of the truth:

    * ``spot`` / ``forward`` are exchange rates in the ``quote`` convention,
      strictly positive, and both must be for the SAME currency pair.
    * ``i_domestic_annualized`` / ``i_foreign_annualized`` are **ANNUALISED
      DECIMALS** (``0.04`` = 4% per year), the unit every data source publishes
      money-market rates in. They are converted to the forward's own period
      internally, by simple interest at ``tenor_days / basis_days`` — the
      money-market convention, and the reason ``tenor_days`` and
      ``day_count_basis`` are required rather than optional. Passing a
      **period** rate here would understate or overstate the implied forward by
      the whole tenor, and nothing in the arithmetic would complain.
    * ``tenor_days`` is the forward's tenor in ACTUAL days. The two rates must
      cover the same horizon; a 3-month forward priced off an overnight rate is
      a different, wrong calculation.

    Three refusals, all of them domain guards on inputs that are arithmetically
    representable but economically meaningless: a non-finite value (``nan``
    passes no comparison, so a plausibility check built from comparisons would
    let it through — D-078), a non-positive exchange rate (a price cannot be
    zero or negative), and a period rate at or below ``-100%`` (``1 + i`` would
    be zero or negative, so the parity ratio would divide by zero or invert
    sign). The tenor is additionally bounded by the day-count basis, because
    simple-interest conversion stops being correct beyond one money-market year.
    """

    model_config = ConfigDict(extra="forbid")

    spot: float = Field(
        description="Spot exchange rate in the ``quote`` convention. Strictly positive.",
    )
    forward: float = Field(
        description=(
            "Forward exchange rate for the SAME pair and the SAME quote "
            "convention as ``spot``. Strictly positive."
        ),
    )
    i_domestic_annualized: float = Field(
        description=(
            "Domestic money-market rate over the forward's tenor, ANNUALISED "
            "DECIMAL (0.04 = 4%/yr). Converted internally to the period rate."
        ),
    )
    i_foreign_annualized: float = Field(
        description=(
            "Foreign money-market rate over the forward's tenor, ANNUALISED "
            "DECIMAL. Must be the same tenor as ``i_domestic_annualized``."
        ),
    )
    tenor_days: int = Field(
        ge=1,
        description=(
            "The forward's tenor in ACTUAL days. The rates are scaled to this "
            "horizon, and it must not exceed the day-count basis."
        ),
    )
    day_count_basis: DayCountBasis = Field(
        default="actual_360",
        description=(
            "Money-market day-count basis of the two rates: 'actual_360' "
            "(USD/EUR) or 'actual_365' (GBP and most sovereign markets)."
        ),
    )
    quote: QuoteConvention = Field(
        default="domestic_per_foreign",
        description=(
            "Which currency is the price currency of spot/forward. "
            "'domestic_per_foreign' (e.g. EURUSD for a USD-domestic caller) is "
            "the convention the parity identity is written in; "
            "'foreign_per_domestic' (e.g. USDJPY for a USD-domestic caller) is "
            "inverted before the identity is applied."
        ),
    )

    @model_validator(mode="after")
    def _validate_domain(self) -> CIPInputs:
        """Refuse an input that is representable but not an FX or rate quote.

        Each bound closes a way the arithmetic could return a confident number
        from an input that has no meaning, and each is a distinct branch rather
        than one broad check, because they fail differently:

        * **Non-finite** — ``nan`` fails every comparison, so a guard written as
          ``if x <= 0`` never fires for it and the parity ratio returns ``nan``,
          which then travels into the deviation. ``inf`` *passes* ``> 0``, so it
          needs the explicit finiteness test (D-078).
        * **Non-positive rate** — a zero or negative exchange rate is not a
          price. It would make ``forward / spot`` sign-flip and the deviation
          meaningless while still returning a number.
        * **Period rate at or below -100%** — ``1 + i`` at or below zero makes
          the parity ratio divide by zero or invert its sign. Checked on the
          PERIOD rate, not the annualised one, because the annualised value can
          be a perfectly ordinary number while the period value is not — the
          conversion is what makes it unreachable.
        * **Tenor beyond the basis** — simple interest is exact only to one
          money-market year; beyond it the correct conversion compounds, and
          this function does not implement that. Refusing is the honest choice:
          a compounded figure computed with a simple formula is a wrong number
          that looks right.
        """
        for name in ("spot", "forward", "i_domestic_annualized", "i_foreign_annualized"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(
                    f"{name} is {value!r}, which is not finite. A non-finite input "
                    f"cannot be classified: every comparison a plausibility check "
                    f"is made of returns False for nan, so it would reach the "
                    f"arithmetic and produce a non-finite deviation that looks like "
                    f"an answer (D-078)."
                )
        for name in ("spot", "forward"):
            value = getattr(self, name)
            if value <= 0.0:
                raise ValueError(
                    f"{name} is {value}; an exchange rate must be strictly "
                    f"positive. A non-positive rate would sign-flip the parity "
                    f"ratio while still returning a number."
                )

        basis_days = _BASIS_DAYS[self.day_count_basis]
        if self.tenor_days > basis_days:
            raise ValueError(
                f"tenor_days is {self.tenor_days} against a "
                f"{self.day_count_basis} year of {basis_days} days. Simple-interest "
                f"conversion is exact only up to one money-market year; a longer "
                f"tenor needs compounding, which this function does not implement. "
                f"Refusing rather than returning a number computed with the wrong "
                f"convention."
            )

        scale = self.tenor_days / basis_days
        for name in ("i_domestic_annualized", "i_foreign_annualized"):
            period = getattr(self, name) * scale
            if 1.0 + period <= 0.0:
                raise ValueError(
                    f"{name} is {getattr(self, name)} annualised, which is "
                    f"{period} over {self.tenor_days} days on "
                    f"{self.day_count_basis}. A period rate at or below -100% makes "
                    f"the parity ratio divide by zero or invert its sign."
                )
        return self


def _cip_bands_are_calibrated() -> bool:
    """Whether the ONE leaf :func:`cip_check` leans on is calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` (negated by the
    caller). The notable band is the leaf that turns a number into the judgement
    "funding stress", so it is the one that costs confidence while it is a
    placeholder — which it is today, deliberately, because calibrating it needs
    a forward series this installation cannot reach.

    **Named for the leaf it reads, not for the section it lives in.** It was
    ``_thresholds_are_calibrated`` (plural, and generic) until this module gained
    a second function with its own threshold — at which point the name was
    ambiguous in exactly the way `_r_squared_floor_is_calibrated`'s docstring in
    ``models/econometrics.py`` warns about: a reader adding a threshold would
    reasonably assume the generic helper already covered it. The two functions
    are priced on DIFFERENT leaves, so they need different helpers with names
    that say which.
    """
    settings = get_settings()
    return settings.is_calibrated("fx_carry.notable_deviation_pct")


def _dollar_smile_thresholds_are_calibrated() -> bool:
    """Whether the TWO leaves :func:`dollar_smile_regime` leans on are calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` (negated by the
    caller). **Both** leaves cost confidence, because both are judgements rather
    than measurements: the VIX gate decides which limb a crisis reading lands on,
    and the sign boundary decides whether an input establishes US
    outperformance. A calibration of either alone would still leave the label
    resting on a placeholder, so this helper reads both and reports calibrated
    only when neither is a placeholder.

    Deliberately separate from :func:`_cip_bands_are_calibrated` and
    :func:`_carry_floor_is_calibrated`, for the reason the first of those
    docstrings gives: a generic ``_thresholds_are_calibrated`` would let a
    future calibration of one function's leaf silently change another's
    confidence.
    """
    settings = get_settings()
    return settings.is_calibrated("fx_carry.dollar_smile_vix_threshold") and settings.is_calibrated(
        "fx_carry.dollar_smile_sign_boundary"
    )


def _carry_floor_is_calibrated() -> bool:
    """Whether the ONE leaf :func:`carry_score` leans on is calibrated.

    Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` (negated by the
    caller). The volatility floor is the leaf that decides whether the published
    score is a carry-to-vol ratio or a carry-over-the-floor number, so it is the
    one that costs confidence while it is a placeholder.

    Deliberately separate from :func:`_cip_bands_are_calibrated` even though the
    two currently read the same answer: they price different judgements on
    different leaves, and conflating them would mean a future calibration of one
    silently changed the other's confidence.
    """
    settings = get_settings()
    return settings.is_calibrated("fx_carry.carry_vol_floor")


def _stress_labels(
    deviation_pct: float,
    *,
    notable_pct: float,
    extreme_pct: float,
) -> tuple[StressSeverity, FundingStressSide]:
    """Map the deviation onto the configured bands and the funding side.

    Two orthogonal labels rather than one five-member vocabulary, because the
    magnitude and the sign answer different questions: how far from parity the
    forward sits, and which currency is the expensive side of the swap. The
    ``"none"`` side coincides with the ``"none"`` severity by construction —
    inside the notable band there is no side to name.

    The comparison is **strictly greater** at both boundaries, matching
    Section 6.7's own ``abs(deviation_pct) > 0.1``: a deviation exactly equal to
    the configured band is inside it, so the band is the largest deviation that
    is still reported as quiet.
    """
    magnitude = abs(deviation_pct)
    if magnitude > extreme_pct:
        severity: StressSeverity = "extreme"
    elif magnitude > notable_pct:
        severity = "notable"
    else:
        severity = "none"

    if magnitude <= notable_pct:
        side: FundingStressSide = "none"
    elif deviation_pct > 0.0:
        side = "domestic"
    else:
        side = "foreign"
    return severity, side


def _cip_warnings(
    *,
    severity: StressSeverity,
    side: FundingStressSide,
    deviation_pct: float,
    basis_bp_annualized: float,
    notable_pct: float,
    extreme_pct: float,
    tenor_days: int,
) -> list[str]:
    """The conditions of THIS run, in severity order.

    A warning is a condition, not a standing caveat — the caveats that hold on
    every call (no bid/ask, no settlement modelling, no balance-sheet cost) are
    ``limitations`` instead. Nothing is emitted when the forward sits inside the
    notable band, because a warning that fires on every ordinary call is noise,
    and noise is how a real warning gets ignored.
    """
    warnings: list[str] = []
    if severity == "extreme":
        warnings.append(
            f"CIP deviation {deviation_pct:+.4f}% is beyond the extreme band "
            f"({extreme_pct}%), an annualised funding basis of "
            f"{basis_bp_annualized:+.1f}bp at {tenor_days} days. A dislocation of "
            f"this width has historically accompanied an outright funding squeeze "
            f"in {side} currency rather than a liquidity premium — the class the "
            f"2008 and March-2020 episodes belong to."
        )
    elif severity == "notable":
        warnings.append(
            f"CIP deviation {deviation_pct:+.4f}% exceeds the notable band "
            f"({notable_pct}%), an annualised funding basis of "
            f"{basis_bp_annualized:+.1f}bp at {tenor_days} days. The FX swap "
            f"market is pricing a funding premium in {side} currency, so the "
            f"deviation is a stress reading rather than an arbitrage."
        )
    return warnings


def _cip_limitations() -> list[str]:
    """What this result cannot tell you, on every call.

    Distinct from ``warnings``, which report a condition of this run. These hold
    whatever the numbers are, and the first three are the reason a non-zero
    deviation is not a trade.
    """
    return [
        "Bid/ask is NOT modelled. The deviation is computed from single "
        "mid prices, so a deviation smaller than the pair's spot and forward "
        "spread is not executable — it is inside the cost of doing the round "
        "trip, not a profit.",
        "Settlement and value dates are NOT modelled. A real FX swap's spot and "
        "forward legs settle on different dates, so the rates must cover the "
        "exact value-date period; a tenor mismatch of even a day moves the "
        "implied forward, and this function assumes the caller supplied "
        "matched dates.",
        "No credit, balance-sheet, or regulatory cost is modelled. Covered "
        "parity is an arbitrage only for an unconstrained balance sheet; since "
        "2008 the residual deviation largely prices the cost of funding and "
        "intermediation, so a non-zero reading is evidence about those costs "
        "rather than a riskless opportunity.",
        "The period conversion is SIMPLE interest over tenor_days / basis_days, "
        "the money-market convention, and is refused beyond one money-market "
        "year rather than approximated.",
        "The two rates must be for the forward's EXACT tenor. A rate "
        "interpolated from neighbouring tenors introduces an error this "
        "function cannot see and does not correct.",
        "One pair, one tenor, one date. No term structure of the basis, no "
        "history, and no comparison against the pair's own normal level — a "
        "deviation of 0.3% is meaningful or not only against that pair's "
        "distribution, which is not available here.",
        "The notable and extreme bands are uncalibrated placeholders "
        "(``fx_carry`` in settings.yaml). They decide a reporting label, not a "
        "probability, and the label is priced into this result's confidence.",
        "Provenance is the caller's. This model does not fetch and cannot "
        "verify the observation dates of the rates and rates it was handed.",
    ]


def cip_check(inputs: CIPInputs) -> ModelResult:
    """Measure a forward's deviation from covered interest parity.

    ``value`` is a ``dict`` carrying the deviation and the components it was
    derived from, so every published number can be recomputed from the output
    alone:

    ``deviation_pct``
        ``(F - F_implied) / F_implied * 100``, in domestic-per-foreign space.
        **Positive means the domestic currency is the expensive side of the
        swap** — the sign is the sign of the synthetic-domestic minus actual-
        domestic funding spread, exactly (see the module docstring).
    ``implied_forward``
        ``S * (1 + i_d) / (1 + i_f)`` on the period rates.
    ``i_domestic_period`` / ``i_foreign_period``
        The annualised inputs converted to the forward's own horizon.
    ``synthetic_domestic_funding_rate_period``
        ``(F / S) * (1 + i_f) - 1`` — the rate a domestic borrower pays by
        synthesizing the loan through the swap.
    ``domestic_funding_basis_bp_annualized``
        ``(i_d_synthetic - i_d)`` annualised, in basis points. The quantity the
        FX market quotes as the cross-currency basis. It satisfies
        ``basis_period == (1 + i_d_period) * deviation_fraction`` exactly.
    ``severity`` / ``stressed_currency``
        The configured band, and which currency's funding is expensive.

    The function refuses rather than repairs: every domain defect (non-finite,
    non-positive rate, period rate at or below ``-100%``, a tenor beyond one
    money-market year) is rejected at construction by :class:`CIPInputs`, so a
    result that exists is a result whose inputs were admissible.
    """
    settings = get_settings()
    fx_carry = settings.fx_carry
    notable_pct = fx_carry.notable_threshold_pct
    extreme_pct = fx_carry.extreme_threshold_pct

    basis_days = _BASIS_DAYS[inputs.day_count_basis]
    period_scale = inputs.tenor_days / basis_days
    i_domestic_period = inputs.i_domestic_annualized * period_scale
    i_foreign_period = inputs.i_foreign_annualized * period_scale

    # THE QUOTE CONVENTION. The parity identity is written in domestic-per-
    # foreign space, so a foreign-per-domestic quote is inverted here, once, and
    # everything downstream works in one space. Inverting AFTER the identity
    # would be a different (and wrong) calculation — the deviation is not
    # symmetric under quote inversion, because its denominator changes.
    inverted = inputs.quote == "foreign_per_domestic"
    if inverted:
        spot = 1.0 / inputs.spot
        forward = 1.0 / inputs.forward
    else:
        spot = inputs.spot
        forward = inputs.forward

    implied_forward = spot * (1.0 + i_domestic_period) / (1.0 + i_foreign_period)
    deviation_fraction = (forward - implied_forward) / implied_forward
    deviation_pct = deviation_fraction * 100.0

    # The synthetic domestic funding rate and the basis. Derived from the same
    # three quantities as the deviation, but through the OTHER side of the
    # identity — which is what makes `basis_period == (1 + i_d) * deviation` an
    # identity between two independently published keys rather than a
    # restatement of one.
    synthetic_domestic_period = (forward / spot) * (1.0 + i_foreign_period) - 1.0
    basis_period = synthetic_domestic_period - i_domestic_period
    basis_bp_annualized = basis_period / period_scale * 10_000.0

    severity, side = _stress_labels(deviation_pct, notable_pct=notable_pct, extreme_pct=extreme_pct)

    if side == "domestic":
        side_phrase = "domestic-currency funding is the expensive side"
    elif side == "foreign":
        side_phrase = "foreign-currency funding is the expensive side"
    else:
        side_phrase = "neither currency's funding is materially expensive"

    return ModelResult(
        model_name="cip_deviation",
        country="us",
        as_of=utc_now(),
        value={
            "deviation_pct": round(deviation_pct, 6),
            "implied_forward": round(implied_forward, 8),
            "observed_forward": round(forward, 8),
            "spot": round(spot, 8),
            "i_domestic_annualized": inputs.i_domestic_annualized,
            "i_foreign_annualized": inputs.i_foreign_annualized,
            "i_domestic_period": round(i_domestic_period, 8),
            "i_foreign_period": round(i_foreign_period, 8),
            "synthetic_domestic_funding_rate_period": round(synthetic_domestic_period, 8),
            "domestic_funding_basis_bp_annualized": round(basis_bp_annualized, 4),
            "tenor_days": inputs.tenor_days,
            "day_count_basis": inputs.day_count_basis,
            "day_count_basis_days": basis_days,
            "quote_convention": inputs.quote,
            "normalized_to": "domestic_per_foreign",
            "quote_was_inverted": inverted,
            "severity": severity,
            "stressed_currency": side,
            "notable_threshold_pct": notable_pct,
            "extreme_threshold_pct": extreme_pct,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not _cip_bands_are_calibrated(),
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        ),
        interpretation=(f"CIP deviation {deviation_pct:+.4f}% ({severity}); {side_phrase}."),
        context=(
            f"Spot {spot:.6f} and forward {forward:.6f} (domestic per foreign"
            + (
                f"; input quote '{inputs.quote}' inverted)"
                if inverted
                else f"; input quote '{inputs.quote}')"
            )
            + f". Parity-implied forward {implied_forward:.6f}. "
            f"{inputs.tenor_days}-day rates on {inputs.day_count_basis}: domestic "
            f"{inputs.i_domestic_annualized * 100:+.4f}%/yr -> "
            f"{i_domestic_period * 100:+.6f}% over the period, foreign "
            f"{inputs.i_foreign_annualized * 100:+.4f}%/yr -> "
            f"{i_foreign_period * 100:+.6f}% over the period. Synthetic domestic "
            f"funding {synthetic_domestic_period * 100:+.6f}% against actual "
            f"{i_domestic_period * 100:+.6f}% -> basis "
            f"{basis_bp_annualized:+.2f}bp annualised. Bands: notable above "
            f"{notable_pct}%, extreme above {extreme_pct}%."
        ),
        unit="percent",
        direction=(
            "domestic_funding_stress"
            if side == "domestic"
            else "foreign_funding_stress"
            if side == "foreign"
            else "none"
        ),
        inputs_used=[
            "spot",
            "forward",
            "i_domestic_annualized",
            "i_foreign_annualized",
            "tenor_days",
            "day_count_basis",
            "quote",
        ],
        assumptions=[
            "Both rates are money-market rates for the SAME tenor as the "
            "forward, and both are for the same currency pair as spot/forward.",
            "Interest accrues as simple interest over tenor_days / basis_days, "
            "the money-market convention, which the input model enforces as a "
            "bound rather than approximating.",
            "The forward is a deliverable outright for the same value dates as "
            "the spot leg plus the stated tenor.",
        ],
        warnings=_cip_warnings(
            severity=severity,
            side=side,
            deviation_pct=deviation_pct,
            basis_bp_annualized=basis_bp_annualized,
            notable_pct=notable_pct,
            extreme_pct=extreme_pct,
            tenor_days=inputs.tenor_days,
        ),
        limitations=_cip_limitations(),
        decision_relevance=(
            "Module 9's FX-parity input to the thesis layer. The deviation and "
            "the funding basis are the funding-stress read a carry or dollar "
            "view is conditioned on — whether the FX swap market is pricing a "
            "currency shortage — and the stressed currency names which side. "
            "Script-only today: no OpenBB route on this installation returns FX "
            "forward points (see the fx_forward_rate entry in "
            "series_registry.yaml), so the caller supplies the forward and the "
            "live check is the only consumer until a forward source exists."
        ),
        decision_prohibition=[
            "Do NOT treat a non-zero deviation as an arbitrage. Covered parity "
            "is free only for an unconstrained balance sheet; the residual "
            "prices funding, credit and intermediation costs, and executing the "
            "round trip consumes them.",
            "Do NOT read the severity as a probability. It is a reporting band "
            "over two uncalibrated thresholds, not a likelihood of a funding "
            "event.",
            "Do NOT size a position on the deviation alone. It carries no "
            "bid/ask, no settlement-date check and no history, and a deviation "
            "inside the pair's spread is not executable.",
        ],
    )


class CarryScoreInputs(BaseModel):
    """A currency pair's carry and the volatility that comes with it.

    **The one thing that must be right, and the one the specification leaves
    unstated: BOTH FIELDS ARE ANNUALISED DECIMALS, and they must share that
    unit.** The output is a RATIO, so it is dimensionless only if the numerator
    and the denominator are the same kind of number. A rate differential in
    PERCENT divided by a volatility in DECIMALS is 100x too large and is still a
    perfectly plausible-looking score — the same silent class D-106 found in a
    docstring whose unit was backwards, and the reason ``rate_differential`` is
    named ``rate_differential_annualized`` here rather than carrying the
    specification's bare name.

    The two are also required to share a HORIZON, which annualisation gives
    them: the carry earned over a period is ``(i_domestic - i_foreign) * t`` and
    the volatility over that period is ``sigma * sqrt(t)``, so their ratio is
    ``(i_d - i_f) / sigma * sqrt(t)`` — still horizon-dependent. Annualising BOTH
    is what makes the published score comparable across tenors, and it is why
    the differential is annualised rather than the raw per-period spread.

    Domain guards, all at construction: non-finite values are refused (``nan``
    fails every comparison, so a ``<=`` guard never fires for it — D-078), and
    ``realized_vol_annualized`` must be strictly POSITIVE. A zero or negative
    volatility is not a volatility: zero makes the ratio undefined and a
    negative one flips the score's sign, which would report a carry as its
    opposite.
    """

    model_config = ConfigDict(extra="forbid")

    rate_differential_annualized: float = Field(
        description=(
            "Domestic minus foreign money-market rate, ANNUALISED DECIMAL "
            "(0.02 = a 2%/yr differential). Named for the unit because the "
            "specification's bare ``rate_differential`` does not state one, and "
            "the ratio is dimensionless only if this matches the volatility's."
        ),
    )
    realized_vol_annualized: float = Field(
        description=(
            "Realised volatility of the pair's return series, ANNUALISED DECIMAL "
            "(0.08 = 8%/yr). Strictly positive. This is an INPUT, not something "
            "this model fetches or estimates — `realized_vol_simple` in "
            "``models/risk.py`` is the project's estimator for it, and it "
            "publishes PERCENT, so a caller wiring the two together must divide "
            "by 100."
        ),
    )

    @model_validator(mode="after")
    def _validate_domain(self) -> CarryScoreInputs:
        """Refuse an input that is representable but is not a rate or a volatility.

        Two branches, each closing a distinct way the ratio returns a confident
        number from an input that has no meaning:

        * **Non-finite** — ``nan`` fails every comparison, so ``if vol <= 0``
          never fires for it and the score comes back ``nan``; ``inf`` PASSES
          ``> 0`` and needs the explicit finiteness test.
        * **Non-positive volatility** — zero divides by zero, and a negative one
          makes the denominator negative, so a positive carry would be published
          as a negative score with the wrong direction label attached.
        """
        for name in ("rate_differential_annualized", "realized_vol_annualized"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(
                    f"{name} is {value!r}, which is not finite. A non-finite input "
                    f"cannot be classified: every comparison a plausibility check "
                    f"is made of returns False for nan, so it would reach the "
                    f"arithmetic and produce a non-finite score (D-078)."
                )
        if self.realized_vol_annualized <= 0.0:
            raise ValueError(
                f"realized_vol_annualized is {self.realized_vol_annualized}; a "
                f"volatility must be strictly positive. Zero makes the carry-to-vol "
                f"ratio undefined, and a negative value would flip the sign of the "
                f"score and report a positive carry as a negative one."
            )
        return self


def _carry_outcome(rate_differential_annualized: float) -> CarryOutcome:
    """Which side of the trade a positive rate differential points at.

    The carry trade is funded in the low-yielding currency and lent in the
    high-yielding one. A POSITIVE differential therefore means lending domestic
    and borrowing foreign — a long domestic-currency position financed abroad —
    and a negative one is the mirror. The exactly-zero case is its own label
    rather than being absorbed into either side: a zero differential is not a
    small carry, it is the absence of one, and the score is exactly zero there.

    Deriving the label from the sign rather than from the score keeps the two
    consistent by construction: the denominator is strictly positive (the input
    model refuses a non-positive volatility and the floor is configured
    positive), so ``sign(score) == sign(differential)`` always.
    """
    if rate_differential_annualized > 0.0:
        return "long_domestic"
    if rate_differential_annualized < 0.0:
        return "long_foreign"
    return "flat"


def _carry_warnings(
    *,
    floor_binds: bool,
    realized_vol_annualized: float,
    volatility_floor: float,
    score: float,
) -> list[str]:
    """The conditions of THIS run.

    One branch, and it is the condition that changes what the published number
    MEANS rather than merely how large it is: when the floor binds, the
    denominator is not the realised volatility, so the score is no longer a
    carry-to-vol ratio. A reader who could not see that would compare it against
    a score produced without the floor and read a difference in estimand as a
    difference in attractiveness.

    Nothing is emitted when the floor does not bind: the standing caveats (no
    tail risk, no costs, a backward-looking denominator) hold on every call and
    are ``limitations``, and a warning that fires on every ordinary call is
    noise.
    """
    if not floor_binds:
        return []
    return [
        f"The realised volatility {realized_vol_annualized:.6f} is below the "
        f"configured floor {volatility_floor:.6f}, so the published score "
        f"{score:+.6f} is carry divided by the FLOOR rather than by the realised "
        f"volatility. It is NOT a carry-to-vol ratio in this run and must not be "
        f"compared against one that is — the floor CAPS the score, so a pair with "
        f"genuinely low volatility is reported as less attractive than its own "
        f"realised volatility implies."
    ]


def _carry_limitations() -> list[str]:
    """What this result cannot tell you, on every call.

    Distinct from ``warnings``, which report a condition of this run. The first
    entry is the one that matters most and is Section 6.7's own disclosure,
    moved here from the specification's ``warnings`` list: it holds on every
    call, so it is a limitation and not a condition.
    """
    return [
        "TAIL AND CRASH RISK ARE NOT CAPTURED, and this is the limitation that "
        "matters most. The carry trade earns a small steady premium and loses "
        "heavily in a dislocation — the peso problem, or the specification's own "
        "phrase, 'nickels in front of a steamroller'. A SYMMETRIC realised-"
        "volatility estimate cannot see skew, so the score OVERSTATES the "
        "risk-adjusted attractiveness of the position it describes.",
        "The denominator is REALISED volatility, so it is backward-looking. It is "
        "not a forecast, and a conditional volatility model is a separate Tier-5 "
        "item (the GARCH family that replaces `realized_vol_simple`).",
        "The numerator is the EX-ANTE CARRY, not a realised excess return, so the "
        "score is a Sharpe-LIKE ratio rather than a Sharpe ratio.",
        "No attractiveness band is applied. Section 6.7 prints the score without "
        "a threshold and this model does not invent one: whether 0.8 is "
        "attractive against 1.2 is a judgement that needs the pair's own history, "
        "which is not an input here.",
        "A positive score is NOT a prediction. UIP says the carry should be "
        "arbitraged away and the forward-premium puzzle says it historically has "
        "not been — both are statements about realised history, and neither makes "
        "the score a forecast.",
        "No transaction costs, bid/ask, funding constraints or balance-sheet cost "
        "are modelled. Executing the carry consumes all of them, and they are "
        "widest exactly when the carry is.",
        "One pair, one window, one date. There is no cross-sectional comparison "
        "and no history, so the score cannot be read as high or low without an "
        "external reference.",
        "The independence count is NOT computable from this result. The two rate "
        "legs come from separate money-market production processes (a US Treasury "
        "bill and a euro-area interbank fixing) and the evidence-family "
        "vocabulary names neither separately, so `source_family` carries the "
        "FX-market tag only and `source_families` is left empty rather than "
        "asserting a single-family claim.",
        "The volatility floor is an uncalibrated placeholder, and when it binds "
        "the estimand changes — see `volatility_floor_binding` and the warning it "
        "raises.",
    ]


def carry_score(inputs: CarryScoreInputs) -> ModelResult:
    """Carry per unit of realised volatility — the carry trade's Sharpe-like ratio.

    ``value`` is a ``dict`` carrying the score and every component it was
    derived from, so each published number can be recomputed from the output
    alone:

    ``score``
        ``rate_differential_annualized / effective_denominator``. Its SIGN is
        the direction of the trade, not a quality ranking: a negative score is
        the same trade the other way round.
    ``effective_denominator``
        ``max(realized_vol_annualized, volatility_floor)`` — the number actually
        divided into the differential, which is the realised volatility unless
        ``volatility_floor_binding`` is true.
    ``volatility_floor_binding``
        Whether the floor was substituted. **When it is true the score is
        carry-over-the-floor, not carry-over-vol**, so it is not comparable with
        a score produced without it.
    ``carry_outcome``
        ``"long_domestic"`` (lend domestic, borrow foreign), ``"long_foreign"``,
        or ``"flat"`` for an exactly zero differential.

    **Why the ratio is the right shape, derived rather than asserted.** The
    funded trade's excess return over the foreign funding rate is the carry plus
    the currency's move, ``(i_d - i_f) + r_fx``. Its volatility is approximately
    the pair's own volatility, because the carry leg is near-constant over the
    horizon. So ``(i_d - i_f) / sigma`` is the trade's ex-ante Sharpe-like ratio
    — which is what makes the score interpretable at all, and what makes the
    floor's effect on it worth disclosing: dividing by a floor instead of by
    sigma is no longer that ratio.

    The function refuses rather than repairs. A non-finite input or a
    non-positive volatility is rejected at construction by
    :class:`CarryScoreInputs`, so a result that exists is a result whose inputs
    were admissible.
    """
    settings = get_settings()
    fx_carry = settings.fx_carry
    volatility_floor = fx_carry.volatility_floor

    differential = inputs.rate_differential_annualized
    realized_vol = inputs.realized_vol_annualized

    floor_binds = realized_vol < volatility_floor
    denominator = volatility_floor if floor_binds else realized_vol
    score = differential / denominator
    outcome = _carry_outcome(differential)

    if outcome == "long_domestic":
        outcome_phrase = "lend domestic, borrow foreign"
    elif outcome == "long_foreign":
        outcome_phrase = "lend foreign, borrow domestic"
    else:
        outcome_phrase = "no carry in either direction"

    if floor_binds:
        denominator_phrase = (
            f"the realised volatility {realized_vol:.6f} is below the "
            f"{volatility_floor:.6f} floor, so the denominator is the FLOOR"
        )
    else:
        denominator_phrase = f"carry per unit of realised volatility {realized_vol:.6f}"

    return ModelResult(
        model_name="carry_score",
        country="us",
        as_of=utc_now(),
        value={
            "score": round(score, 6),
            "rate_differential_annualized": round(differential, 8),
            "realized_vol_annualized": round(realized_vol, 8),
            "effective_denominator": round(denominator, 8),
            "volatility_floor": volatility_floor,
            "volatility_floor_binding": floor_binds,
            "carry_outcome": outcome,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not _carry_floor_is_calibrated(),
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        ),
        unit="dimensionless (annualised carry per unit of annualised volatility)",
        direction=outcome,
        interpretation=(
            f"Carry-to-vol score {score:+.4f} ({outcome}: {outcome_phrase}); {denominator_phrase}."
        ),
        context=(
            f"Rate differential {differential:+.6f} annualised (domestic minus "
            f"foreign) over realised volatility {realized_vol:.6f} annualised. "
            f"Both are ANNUALISED DECIMALS, which is what makes the ratio "
            f"dimensionless and comparable across tenors. Effective denominator "
            f"{denominator:.6f}."
            + (
                f" The configured floor {volatility_floor:.6f} is in force, so the "
                f"score is capped and is not carry-over-realised-vol."
                if floor_binds
                else ""
            )
            + " UIP predicts this carry is arbitraged away; historically it is not "
            "(the forward-premium puzzle), which is why the score exists — but a "
            "positive score is not a forecast."
        ),
        inputs_used=[
            "rate_differential_annualized",
            "realized_vol_annualized",
        ],
        assumptions=[
            "Both inputs are ANNUALISED DECIMALS for the SAME currency pair and the "
            "same horizon; the ratio is dimensionless only if they are.",
            "The differential is the MONEY-MARKET differential of the pair's two "
            "currencies, not a bond-yield or policy-rate differential — the carry "
            "trade is funded in the money market.",
            "`realized_vol_annualized` is the realised volatility of that pair's "
            "return series over a window the caller chose, annualised by the same "
            "convention as the differential.",
        ],
        source_family=EvidenceSourceFamily.MARKET_FX,
        warnings=_carry_warnings(
            floor_binds=floor_binds,
            realized_vol_annualized=realized_vol,
            volatility_floor=volatility_floor,
            score=score,
        ),
        limitations=_carry_limitations(),
        decision_relevance=(
            "Module 9's carry read. Pairs with `cip_check`, which reports whether "
            "the funding leg is being priced as stressed, and with "
            "`dollar_smile_regime`, which conditions whether a carry is durable or "
            "reversal-prone. Script-only today: no snapshot field carries a rate "
            "differential or an FX realised volatility, so the caller supplies "
            "both and the live check is the only consumer until one does."
        ),
        decision_prohibition=[
            "Do NOT size on the score alone. It carries no tail risk, no "
            "transaction cost and no history, and the trades it ranks most "
            "attractive are exactly the ones whose losses are absent from the "
            "realised-volatility window.",
            "Do NOT read a high score as a forecast that the carry will be earned. "
            "The forward-premium puzzle is a statement about realised history, not "
            "a model of the future.",
            "Do NOT compare a score produced with `volatility_floor_binding` set "
            "against one produced without it. They divide by different quantities, "
            "so the difference is an artefact of the floor rather than a "
            "difference in attractiveness.",
        ],
    )


class DollarSmileInputs(BaseModel):
    """The three signed/level inputs Section 6.7's dollar-smile classifier reads.

    **Every field's UNIT is stated here, because the same three bare floats can
    be read several ways and two of the readings move a threshold without
    raising:**

    * ``vix_level`` is a **VIX INDEX LEVEL**, in the index's own points. CBOE's
      VIX is quoted in annualised percentage points, so a reading of ``25`` means
      roughly 25 %/yr implied. It is **not** a decimal and **not** a percent
      fraction: a caller wiring in a volatility estimator from this project gets
      a *decimal* from ``models/risk.py``'s ``realized_vol_simple`` (which in
      fact publishes **percent**, a third unit), and any of those spellings puts
      the reading on the wrong side of every plausible gate.
    * ``us_growth_surprise`` is a **signed surprise**, in the growth series' own
      percentage points — the actual less the consensus, so **exactly zero is
      the genuinely neutral value** and is reached whenever a release lands on
      consensus. A **nowcast is not a consensus** (see the ``inflation_surprise``
      entry in ``config/series_registry.yaml``), so this is a caller-supplied
      quantity on this installation, not something the model fetches.
    * ``us_vs_row_rate_diff`` is a **signed rate differential** in the caller's
      rate unit, date-matched to the surprise above. Only its SIGN is consumed.

    Two refusals, both closing a way a confident label could be produced from an
    input that carries no information. **Non-finite is the important one, and the
    probe measured why**: with the specification's bare comparisons, ``nan``
    fails ``> threshold`` and falls through to the **middle** label — a
    confident "synchronized global growth" claim produced by a missing value —
    while ``+inf`` passes ``> threshold`` and is reported as a full-blown
    **left** crisis. Neither raises, and both look exactly like an ordinary
    classification (D-078's class, in a classifier rather than an arithmetic
    function).

    There is deliberately **no** guard on the sign of any input: a negative
    ``us_growth_surprise`` is the ordinary "US disappointed" reading, not a
    defect.
    """

    model_config = ConfigDict(extra="forbid")

    vix_level: float = Field(
        description=(
            "The VIX INDEX LEVEL in the index's own points (25 means roughly "
            "25 %/yr implied). NOT a decimal, NOT a percent fraction."
        ),
    )
    us_growth_surprise: float = Field(
        description=(
            "US growth surprise in the growth series' own percentage points: "
            "actual less consensus. Exactly 0.0 is the neutral value."
        ),
    )
    us_vs_row_rate_diff: float = Field(
        description=(
            "US less rest-of-world money-market rate differential, in the "
            "caller's rate unit, date-matched to the surprise. Only the sign "
            "is consumed."
        ),
    )

    @model_validator(mode="after")
    def _validate_domain(self) -> DollarSmileInputs:
        """Refuse a non-finite input, because it produces a confident LABEL.

        One branch, and it is the branch the probe justified: a bare ``nan``
        reaches the middle label and a bare ``inf`` reaches the left one, so an
        unguarded classifier answers a missing value with a regime claim. The
        message names the measured consequence rather than the mere fact, because
        the consequence is what makes the guard load-bearing.

        No sign or range guard is added: unlike an exchange rate or a
        volatility, a negative surprise and a negative differential are ordinary
        readings, and a VIX level far above or below the gate is exactly what the
        gate exists to classify.
        """
        for name in ("vix_level", "us_growth_surprise", "us_vs_row_rate_diff"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(
                    f"{name} is {value!r}, which is not finite. This classifier "
                    f"returns a confident LABEL for any input, so a non-finite "
                    f"value would be published as a regime claim: nan fails every "
                    f"'>' comparison and falls through to the middle "
                    f"'synchronized global growth' label, and +inf passes the VIX "
                    f"gate and is reported as a full left-limb crisis. Neither "
                    f"raises on its own (D-078)."
                )
        return self


def _dollar_smile_side(
    vix_level: float,
    us_growth_surprise: float,
    us_vs_row_rate_diff: float,
    *,
    vix_threshold: float,
    sign_boundary: float,
) -> DollarSmileSide:
    """Map the three inputs onto the dollar smile's three limbs.

    The order is Section 6.7's own — **most-severe-first** — and it is load-
    bearing rather than cosmetic: a crisis reading with strong US data is
    classified as the left limb, because the safe-haven bid is what is driving
    the currency and the data is not what the market is trading. Reordering
    ``_dollar_smile_side`` so the growth branch is tested first would silently
    relabel every such reading as durable US outperformance.

    Every branch is reachable, and that was **measured rather than assumed**
    (D-050's hazard, which this classifier's shape is the textbook example of).
    Enumerating the space on the shipped thresholds:

    ==================  ==============================
    region              side
    ==================  ==============================
    ``vix > 25.0``      ``left`` (all growth/diff signs)
    ``vix <= 25.0``     ``right`` iff **both** inputs are strictly positive
    ``vix <= 25.0``     ``middle`` otherwise — including either input at 0.0
    ==================  ==============================

    **The left gate does NOT make the branches behind it unreachable**, because
    the VIX input is a continuous level rather than a flag: the space below the
    gate is the whole ``vix <= 25`` half-plane, and both inner labels are
    produced inside it. That is the difference between this classifier and the
    D-050 case it superficially resembles.

    :param sign_boundary: the value each signed input must **strictly exceed**.
        Ships at ``0.0``, which is the specification's own ``> 0`` and which
        gives the **zero case to the middle branch** — a neutral input is not
        evidence of US outperformance.
    """
    if vix_level > vix_threshold:
        return "left"
    if us_growth_surprise > sign_boundary and us_vs_row_rate_diff > sign_boundary:
        return "right"
    return "middle"


def _dollar_smile_is_neutral(us_growth_surprise: float, us_vs_row_rate_diff: float) -> bool:
    """Whether an exactly-neutral signed input is among the middle branch's causes.

    A middle label has two very different causes and a reader cannot tell them
    apart from the label: the inputs may point *against* US outperformance (a
    negative surprise, a negative differential), or one of them may be sitting
    at **exactly zero**, which is the absence of a signal rather than a signal
    against. The second cause matters because a surprise series prints exactly
    ``0.0`` whenever a release lands on consensus — it is a value real data
    takes, not a mathematical edge case (D-040's class).

    Derived from the same expression the classifier uses rather than restated,
    so the two cannot disagree about which values are neutral: a value is
    neutral exactly when it fails ``> 0.0`` by equality.
    """
    return us_growth_surprise == 0.0 or us_vs_row_rate_diff == 0.0


def _dollar_smile_limitations(
    *,
    vix_threshold: float,
    sign_boundary: float,
    base_rates: dict[str, float],
) -> list[str]:
    """What this result cannot tell you, on every call.

    Distinct from ``warnings``, which report a condition of this run. The first
    entry is Section 6.7's own disclosure — *"the thresholds are qualitative …
    refine against history before trusting at size"* — and it belongs HERE
    rather than in ``warnings``: a warning is a condition of *this* run, and that
    sentence holds on every run. (D-109 made the same move for the specification's
    "steamroller" sentence.)
    """
    return [
        "THE THRESHOLDS ARE QUALITATIVE AND UNCALIBRATED, and this is the "
        "limitation that matters most. Section 6.7 says so in its own words — "
        "'refine thresholds against history before trusting at size' — and both "
        f"leaves ship as placeholders: the VIX gate {vix_threshold} and the sign "
        f"boundary {sign_boundary}. The label is a REPORTING category, never a "
        "probability, and it is priced into this result's confidence.",
        "The label is a CATEGORY, not a position, a forecast or a magnitude. "
        "Nothing here sizes anything, and 'right (US outperformance)' does not "
        "mean the dollar will appreciate — it names which limb of the smile the "
        "current inputs sit on and what that limb's historical character is.",
        "There are only THREE limbs and no magnitude within a limb. A VIX of "
        "25.1 and a VIX of 80 produce the same label and the same interpretation "
        "text, because the classifier is a partition of the input space rather "
        "than a function of distance from a boundary.",
        "The left limb's label asserts that USD strength is 'reversal-prone' and "
        "the right limb's that it is 'durable'. Both are EMPIRICAL "
        "regularities about past episodes, not properties of the inputs — no "
        "data in this result supports either claim, and a limb can persist for "
        "years in either direction.",
        "A US growth SURPRISE requires a consensus forecast, and this "
        "installation cannot reach one — `series_registry.yaml`'s "
        "`inflation_surprise` entry records the same block, because a nowcast is "
        "not a consensus. The surprise is therefore a CALLER-SUPPLIED input on "
        "this build, and this model neither fetches it nor can verify its "
        "vintage or its definition of consensus.",
        "The three inputs must be DATE-MATCHED and the two signed ones must be "
        "on a scale the caller is willing to compare. Only the sign of the "
        "signed inputs is consumed, so a unit mismatch between them cannot flip "
        "a label — but a STALE surprise paired with a current VIX can put the "
        "reading on the wrong limb, and nothing here can detect that.",
        "One reading, one date. There is no smoothing, no hysteresis and no "
        "persistence requirement, so a single release printing at exactly "
        "consensus moves the label to the middle and the next day's print can "
        "move it back. Section 6.7's model is a snapshot classifier and this "
        "function does not add the state that would stabilise it.",
        f"The base rates travel with the result: over this build's enumeration "
        f"the middle limb is reachable on {base_rates['middle']:.1%} of the "
        f"space, the left on {base_rates['left']:.1%} and the right on "
        f"{base_rates['right']:.1%}. A share over an ENUMERABLE space is not a "
        f"base rate over history — the inputs are correlated in practice and a "
        f"uniform grid over-represents the mixed combinations the economy "
        f"rarely produces — so neither number should be read as an occurrence "
        f"frequency.",
        "Provenance is the caller's. This model does not fetch and cannot verify "
        "the observation dates or the construction of the three inputs.",
    ]


def _dollar_smile_warnings(
    *,
    side: DollarSmileSide,
    vix_level: float,
    us_growth_surprise: float,
    us_vs_row_rate_diff: float,
    vix_threshold: float,
) -> list[str]:
    """The conditions of THIS run, in severity order.

    Two branches, and each reports something a reader could not recover from the
    label alone: which branch fired and why (D-094's rule — a classifier's
    output must travel with the inputs that produced it), and, for the middle
    limb, whether it was reached by a NEUTRAL input or by an outright negative
    one. A warning that fired on every ordinary call would be noise, so the
    right limb emits nothing — it is the one limb whose own name is its reason.
    """
    warnings: list[str] = []
    if side == "left":
        warnings.append(
            f"VIX {vix_level:.2f} is above the configured gate {vix_threshold}, so "
            f"the dollar is classified on the smile's LEFT (risk-off/crisis) limb "
            f"regardless of the growth surprise "
            f"({us_growth_surprise:+.4f}) and the rate differential "
            f"({us_vs_row_rate_diff:+.4f}). USD strength in this state is read as "
            f"safe-haven demand rather than as US outperformance, which is the "
            f"part that is reversal-prone — but the growth and rate inputs were "
            f"NOT what decided the label, so a later VIX fall will reclassify "
            f"without either of them changing."
        )
    elif side == "middle" and _dollar_smile_is_neutral(us_growth_surprise, us_vs_row_rate_diff):
        warnings.append(
            f"The middle 'synchronized global growth' label was reached with a "
            f"NEUTRAL input — growth surprise {us_growth_surprise:+.4f}, rate "
            f"differential {us_vs_row_rate_diff:+.4f} — because a value at "
            f"exactly {0.0} does not exceed the sign boundary. Zero is the ABSENCE "
            f"of a US-outperformance signal, not evidence against one: a release "
            f"landing on consensus prints exactly this, and the specification's "
            f"'> 0' test cannot distinguish the two. Do not read this label as "
            f"the inputs opposing USD strength."
        )
    return warnings


def dollar_smile_regime(inputs: DollarSmileInputs) -> ModelResult:
    """Classify the dollar smile's limb from VIX, a growth surprise and a rate gap.

    ``value`` is a ``dict`` carrying the label and every quantity the label was
    derived from, so the branch that fired can be reconstructed from the output
    alone — which is the whole discipline for a classifier, because a threshold
    classifier returns a confident category for **every** input, including the
    ones it cannot distinguish:

    ``side``
        ``"left"`` (risk-off/crisis), ``"right"`` (US outperformance) or
        ``"middle"`` (synchronized global growth).
    ``is_neutral_input``
        Whether an exactly-zero signed input is among the middle limb's causes.
        False whenever the label is not ``"middle"``, and false for a middle
        limb reached by inputs that point *against* US outperformance — those
        two causes are different claims and the label cannot hold both.
    ``vix_above_threshold`` / ``growth_above_boundary`` / ``rate_above_boundary``
        The three comparisons, published so a reader can see WHICH gate fired
        without re-deriving it from the inputs and the thresholds.
    ``vix_threshold`` / ``sign_boundary``
        The configured leaves the comparisons were made against, so a label can
        be re-derived from the result after either leaf moves.

    **The input is a model rather than three positional floats, deliberately.**
    ``vix_level``, a growth surprise and a rate differential are three bare
    numbers whose units are unrecoverable, and two of the three plausible
    readings of ``vix_level`` move the gate by 100x without raising anything.
    Section 6.7 declares them as three function parameters; a unit-contract
    that no signature can carry belongs in a type that can, and
    :class:`DollarSmileInputs` is where the four guard branches live.

    **``confidence`` is computed, not hardcoded.** Section 6.7's reference
    implementation carries ``confidence=0.4`` with a comment; Section 22.8
    forbids a hardcoded confidence, and the value is derived from the stated
    fact that both thresholds are uncalibrated placeholders. ``direction`` is
    left unset on purpose: the label is a **categorical member of a three-way
    partition**, and no member of it is a direction — ``"left"`` and ``"right"``
    both describe USD strength and are distinguished by cause, so a
    ``direction`` field would have to invent an ordering the model does not have.

    The function refuses rather than repairs: a non-finite input is rejected at
    construction by :class:`DollarSmileInputs`, so a result that exists is a
    result whose inputs carried information.
    """
    settings = get_settings()
    fx_carry = settings.fx_carry
    vix_threshold = fx_carry.dollar_smile_vix_level
    sign_boundary = fx_carry.dollar_smile_sign_boundary_value

    vix_level = inputs.vix_level
    growth = inputs.us_growth_surprise
    rate_diff = inputs.us_vs_row_rate_diff

    vix_above = vix_level > vix_threshold
    growth_above = growth > sign_boundary
    rate_above = rate_diff > sign_boundary

    side = _dollar_smile_side(
        vix_level,
        growth,
        rate_diff,
        vix_threshold=vix_threshold,
        sign_boundary=sign_boundary,
    )
    # `is_neutral_input` is only meaningful on the middle limb: on either of the
    # other two the label is not the middle one, and a zero input had no say.
    is_neutral = side == "middle" and _dollar_smile_is_neutral(growth, rate_diff)

    if side == "left":
        side_phrase = (
            "left — risk-off/crisis: USD strength likely safe-haven driven and reversal-prone"
        )
    elif side == "right":
        side_phrase = (
            "right — US outperformance: USD strength likely durable and rate/growth-driven"
        )
    elif is_neutral:
        side_phrase = (
            "middle — synchronized global growth: USD likely weak, but a signed "
            "input is exactly neutral, so this limb was NOT chosen on evidence "
            "against US outperformance"
        )
    else:
        side_phrase = (
            "middle — synchronized global growth: USD likely weak, diversification flows dominate"
        )

    if side == "left":
        because = f"VIX {vix_level:.2f} above the {vix_threshold} gate"
    elif side == "right":
        because = (
            f"VIX {vix_level:.2f} at or below the {vix_threshold} gate with BOTH "
            f"signed inputs above {sign_boundary}"
        )
    elif is_neutral:
        because = (
            f"VIX {vix_level:.2f} at or below the {vix_threshold} gate and a "
            f"signed input at exactly {sign_boundary}"
        )
    else:
        because = (
            f"VIX {vix_level:.2f} at or below the {vix_threshold} gate and the "
            f"signed inputs not both above {sign_boundary}"
        )

    return ModelResult(
        model_name="dollar_smile_regime",
        country="us",
        as_of=utc_now(),
        value={
            "side": side,
            "is_neutral_input": is_neutral,
            "vix_level": round(vix_level, 6),
            "us_growth_surprise": round(growth, 6),
            "us_vs_row_rate_diff": round(rate_diff, 6),
            "vix_above_threshold": vix_above,
            "growth_above_boundary": growth_above,
            "rate_above_boundary": rate_above,
            "vix_threshold": vix_threshold,
            "sign_boundary": sign_boundary,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not _dollar_smile_thresholds_are_calibrated(),
                source_independence_count=0,
                depends_on_unobservable=False,
            )
        ),
        unit="categorical (dollar smile limb: 'left' | 'right' | 'middle')",
        interpretation=f"Dollar smile {side}: {side_phrase} — {because}.",
        context=(
            f"VIX index level {vix_level:.2f} against a gate of {vix_threshold} "
            f"(strictly greater is the left limb, so a reading of exactly "
            f"{vix_threshold} is not left). US growth surprise "
            f"{growth:+.6f} and US-less-rest-of-world rate differential "
            f"{rate_diff:+.6f} against a sign boundary of {sign_boundary} "
            f"(strictly greater is required, so a signed input of exactly "
            f"{sign_boundary} does not establish US outperformance and the zero "
            f"case therefore belongs to the middle limb). Branch tests: "
            f"vix_above={vix_above}, growth_above={growth_above}, "
            f"rate_above={rate_above}. Section 6.7's smile: USD strengthens at "
            f"both extremes of global risk appetite and is weakest in the middle."
        ),
        inputs_used=[
            "vix_level",
            "us_growth_surprise",
            "us_vs_row_rate_diff",
        ],
        assumptions=[
            "`vix_level` is a VIX INDEX LEVEL in the index's own points (25 means "
            "roughly 25 %/yr implied) — not a decimal and not a percent fraction.",
            "`us_growth_surprise` is a signed surprise in the growth series' own "
            "percentage points (actual less consensus), so exactly 0.0 is its "
            "neutral value.",
            "`us_vs_row_rate_diff` is a signed US-less-rest-of-world rate "
            "differential in the caller's rate unit, date-matched to the surprise "
            "above. Only its sign is consumed.",
            "The three inputs describe the SAME date, and the state they describe "
            "is stationary over the horizon the label is used for — no smoothing "
            "or persistence rule is applied.",
        ],
        source_family=EvidenceSourceFamily.MARKET_FX,
        warnings=_dollar_smile_warnings(
            side=side,
            vix_level=vix_level,
            us_growth_surprise=growth,
            us_vs_row_rate_diff=rate_diff,
            vix_threshold=vix_threshold,
        ),
        limitations=_dollar_smile_limitations(
            vix_threshold=vix_threshold,
            sign_boundary=sign_boundary,
            base_rates=_DOLLAR_SMILE_BASE_RATES,
        ),
        decision_relevance=(
            "Module 9's regime-conditioning read, and the third and final "
            "function of Module 9. It supersedes NOTHING named — Phases 0-4 built "
            "no regime-conditioning model for the dollar — and it now FEEDS two "
            "existing results: it conditions the carry read `carry_score` "
            "produces, because a carry earned on the smile's LEFT limb is the "
            "safe-haven-driven, reversal-prone version while the same carry on "
            "the RIGHT limb is the durable one; and it pairs with `cip_check`'s "
            "funding-stress reading, since a left-limb classification and a "
            "notable CIP deviation are two independent descriptions of the same "
            "risk-off state. Script-only today: the growth surprise needs a "
            "consensus forecast this installation cannot reach, so the caller "
            "supplies it and the live check is the only consumer."
        ),
        decision_prohibition=[
            "Do NOT read the label as a trade or a forecast. It names which limb "
            "of an empirical relation the inputs sit on; it says nothing about "
            "when or whether the dollar moves, and 'right (US outperformance)' is "
            "not a long-dollar recommendation.",
            "Do NOT size on the limb. The thresholds are uncalibrated "
            "placeholders, the partition has no magnitude within a limb, and a "
            "reversal-prone limb can persist for years.",
            "Do NOT treat a middle label as evidence against USD strength when "
            "`is_neutral_input` is true. That label was reached because an input "
            "sat exactly at zero — the absence of a signal — and the "
            "specification's '> 0' test cannot tell that apart from a negative "
            "reading.",
        ],
    )


#: Which WAY uncovered interest parity predicts the domestic currency moves,
#: derived from the sign of the interest differential.
#:
#: UIP says the HIGHER-yielding currency is expected to DEPRECIATE — the forward
#: premium is the market's compensation for holding the lower-yielding one. So a
#: POSITIVE differential (domestic pays more) predicts domestic depreciation, and
#: a negative one predicts appreciation. ``"flat"`` is an exactly zero
#: differential, where the parity prediction is no move at all — its own label
#: rather than being absorbed into either direction, because "the benchmark
#: expects nothing" is a different statement from "the benchmark expects a small
#: move".
#:
#: The label is derived from the SIGN of the PUBLISHED period expectation rather
#: than from the differential directly, so the two cannot disagree: the
#: period scaling is strictly positive (tenor_days >= 1), so
#: ``sign(expected) == sign(differential)`` always — and deriving from the
#: published quantity means the label is reproducible from the output alone.
UIPDirection = Literal["domestic_depreciation", "domestic_appreciation", "flat"]

#: Which side of purchasing-power parity the spot rate sits on. A spot ABOVE the
#: PPP-implied rate (``deviation_pct > 0``) means the currency buys less
#: domestically than the price levels imply — ``"overvalued"``. ``"at_parity"``
#: is an exact tie, which is a real possibility on a supplied factor and is
#: published as its own member rather than rounded into one of the two sides.
PPPStatus = Literal["overvalued", "undervalued", "at_parity"]

#: The provenance sentence used when the PPP leg was SUPPLIED by the caller
#: (the deterministic override) rather than fetched. A constant so the caller-
#: supplied and fetched paths disclose in the same place with the same weight —
#: an override must not be quieter than a fetch.
_PPP_PROVENANCE_SUPPLIED = (
    "The PPP leg was SUPPLIED by the caller rather than fetched, so its "
    "provenance is unknown to this result."
)

#: The quote conventions a PPP pair may share. Deliberately the same members as
#: ``QuoteConvention``, but asserted against it at import below rather than
#: aliased: the two are the same SET and must stay so, and a divergence would
#: mean a PPP input the FX validity guard would reject.
_QUOTE_CONVENTIONS = frozenset(get_args(QuoteConvention))


class UIPInputs(BaseModel):
    """The two money-market rates and the horizon of an uncovered-parity
    expectation.

    **The unit question is the same one Section 6.7's other FX functions face,
    and the answer is the same: BOTH RATES ARE ANNUALISED DECIMALS**
    (``0.04`` = 4 %/yr), which is what every data source publishes. They are
    converted to the expectation's own horizon internally, by simple interest at
    ``tenor_days / basis_days`` — the money-market convention
    :class:`CIPInputs` already uses, and the reason ``tenor_days`` is required
    rather than defaulted.

    **Why the horizon is required at all, when the specification omits it.** The
    specification writes ``expected = i_domestic - i_foreign`` and stops there.
    That is a ONE-YEAR expectation, silently: a differential of 3 % is a 3 %
    expected depreciation over a year, not over three months. A carry trade
    expresses a view over its OWN tenor, so the quantity that is comparable to
    the trade's expected return is the PERIOD expectation, and the conversion is
    what makes this function's output comparable with :func:`carry_score`'s
    (both then speak about the same horizon). The specification's bare
    subtraction is exactly the ``tenor_days == basis_days`` case, so the shipped
    behaviour at one year matches the reference implementation verbatim.

    Three refusals, each closing a way the arithmetic returns a confident number
    from an input that has no meaning:

    * **Non-finite** — ``nan`` fails every comparison, so a guard built from
      comparisons never fires for it and the expectation is published as ``nan``
      (D-078). ``inf`` passes ``> 0`` and needs the explicit test.
    * **Period rate at or below -100 %** — the exact expectation is built from
      ``(1 + i_d t) / (1 + i_f t)``, so a foreign period rate of exactly -100 %
      divides by zero. Checked on the PERIOD rate rather than the annualised one,
      because a perfectly ordinary annualised value can convert to an
      unreachable period value — the conversion is what makes it reachable.
    * **Tenor beyond the basis** — simple-interest conversion is exact only to one
      money-market year; beyond it the correct conversion compounds, and this
      function does not implement that. Refusing is the honest choice: a
      compounded figure computed with a simple formula is a wrong number that
      looks right.
    """

    model_config = ConfigDict(extra="forbid")

    i_domestic_annualized: float = Field(
        description=(
            "Domestic money-market rate over the expectation's horizon, "
            "ANNUALISED DECIMAL (0.04 = 4%/yr). Converted internally to the "
            "period rate."
        ),
    )
    i_foreign_annualized: float = Field(
        description=(
            "Foreign money-market rate over the expectation's horizon, "
            "ANNUALISED DECIMAL. Must be the same tenor as "
            "``i_domestic_annualized``."
        ),
    )
    tenor_days: int = Field(
        ge=1,
        description=(
            "The horizon the expectation is stated over, in ACTUAL days. The "
            "rates are scaled to this horizon, and it must not exceed the "
            "day-count basis."
        ),
    )
    day_count_basis: DayCountBasis = Field(
        default="actual_360",
        description=(
            "Money-market day-count basis of the two rates: 'actual_360' "
            "(USD/EUR) or 'actual_365' (GBP and most sovereign markets)."
        ),
    )

    @model_validator(mode="after")
    def _validate_domain(self) -> UIPInputs:
        """Refuse an input that is representable but is not a rate quote.

        Each bound is a distinct branch rather than one broad check, because
        they fail differently:

        * **Non-finite** — ``nan`` fails every comparison, so ``if x <= 0`` never
          fires for it and ``nan`` travels into the published expectation;
          ``inf`` passes ``> 0`` and needs the explicit finiteness test (D-078).
        * **Tenor beyond the basis** — simple interest is exact only to one
          money-market year; a longer tenor needs compounding, which this
          function does not implement.
        * **Period rate at or below -100 %** — ``1 + i_f t`` at or below zero
          makes the exact ratio divide by zero or invert sign. Checked on the
          PERIOD rate, because the annualised value can be an ordinary number
          while the period value is not.
        """
        for name in ("i_domestic_annualized", "i_foreign_annualized"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(
                    f"{name} is {value!r}, which is not finite. A non-finite input "
                    f"cannot be converted to a period rate: every comparison a "
                    f"plausibility check is made of returns False for nan, so it "
                    f"would reach the arithmetic and produce a non-finite "
                    f"expectation that looks like an answer (D-078)."
                )

        basis_days = _BASIS_DAYS[self.day_count_basis]
        if self.tenor_days > basis_days:
            raise ValueError(
                f"tenor_days is {self.tenor_days} against a "
                f"{self.day_count_basis} year of {basis_days} days. Simple-interest "
                f"conversion is exact only up to one money-market year; a longer "
                f"tenor needs compounding, which this function does not implement. "
                f"Refusing rather than returning a number computed with the wrong "
                f"convention."
            )

        scale = self.tenor_days / basis_days
        for name in ("i_domestic_annualized", "i_foreign_annualized"):
            period = getattr(self, name) * scale
            if 1.0 + period <= 0.0:
                raise ValueError(
                    f"{name} is {getattr(self, name)} annualised, which is "
                    f"{period} over {self.tenor_days} days on "
                    f"{self.day_count_basis}. A period rate at or below -100% makes "
                    f"the parity ratio divide by zero or invert its sign."
                )
        return self


def _uip_direction(expected_move_pct: float) -> UIPDirection:
    """Which way UIP predicts the domestic currency moves, from the expectation.

    Derived from the SIGN of the published period expectation rather than from
    the raw differential, so the label and the number cannot disagree — the
    period scaling is strictly positive (``tenor_days >= 1``), so the two signs
    are identical, and deriving from the published quantity keeps the label
    reproducible from the output alone.

    UIP's content is that the HIGHER-yielding currency is expected to
    **depreciate**: the forward premium compensates the holder of the lower-
    yielding currency for the expected loss. So a positive expectation (domestic
    pays more, expected to weaken) is ``"domestic_depreciation"``.
    """
    if expected_move_pct > 0.0:
        return "domestic_depreciation"
    if expected_move_pct < 0.0:
        return "domestic_appreciation"
    return "flat"


def _uip_limitations() -> list[str]:
    """What this result cannot tell you, on every call.

    Distinct from ``warnings``, which report a condition of this run. The first
    entry is the specification's own standing caveat — *"Do NOT use as a point
    forecast. Its empirical failure is the carry premium"* — moved here from the
    specification's ``warnings`` list for the reason D-109 and D-111 give: it
    holds on every call, so it is a limitation and not a condition of this run.
    """
    return [
        "THE MODEL IS KNOWN TO FAIL EMPIRICALLY, and this is the limitation that "
        "matters most — it is what the function IS, not a caveat on it. UIP is "
        "rejected by the data: the higher-yielding currency historically does NOT "
        "depreciate by the interest differential (the forward-premium puzzle), "
        "and the carry trade's entire edge is the gap between this benchmark and "
        "realised returns. The number published here is the BENCHMARK THAT FAILS, "
        "and it must never be read as a forecast.",
        "It is a first-order approximation of a parity condition. The exact "
        "statement is that the expected spot change equals the forward premium, "
        "``(1 + i_d t) / (1 + i_f t) - 1``, which differs from "
        "``i_d - i_f`` by a term of order ``i_f * (i_d - i_f)``. At the "
        "differentials a G10 carry trade actually runs the difference is a "
        "fraction of a basis point and cannot change the sign, but it is a "
        "second-order error and this function does not correct it.",
        "Expected spot changes are UNOBSERVABLE. No data series prints the "
        "market's expected future spot rate, so UIP is a hypothesis about a "
        "quantity that cannot be measured — which is the structural reason it "
        "can fail for decades without being refuted, and the reason its "
        "confidence is capped far below the other Module 9 models'.",
        "The horizon conversion is SIMPLE interest over tenor_days / basis_days, "
        "the money-market convention, and is refused beyond one money-market "
        "year rather than approximated. The expectation is therefore "
        "horizon-scaled exactly as the money-market rates are, which is what "
        "makes it comparable with a carry computed over the same tenor.",
        "No forward rate is consulted, and this is deliberate. UIP is a "
        "statement about the EXPECTED SPOT move derived from the two rates, not "
        "the TRADED forward. The traded forward is :func:`cip_check`'s input, and "
        "comparing the two is a genuine test of the parity condition — but the "
        "comparison is the caller's to make, and this function does not fetch the "
        "forward.",
        "Both rates must be for the SAME horizon and the SAME currency pair, and "
        "the caller owns provenance. A rate interpolated from neighbouring tenors "
        "introduces an error this function cannot see and does not correct.",
        "The independence count is NOT computable from this result. The two rate "
        "legs come from separate money-market production processes and the "
        "evidence-family vocabulary names neither separately, so `source_family` "
        "carries the FX-market tag only and `source_families` is left empty "
        "rather than asserting a single-family claim.",
        "Provenance is the caller's. This model does not fetch and cannot verify "
        "the observation dates of the two rates it was handed.",
    ]


def _uip_warnings(
    *,
    direction: UIPDirection,
    differential_annualized: float,
    expected_move_pct: float,
    tenor_days: int,
) -> list[str]:
    """The conditions of THIS run.

    One branch, and it is the condition that changes what the published number
    means rather than merely how large it is: the ``"flat"`` case, where the two
    rates are equal and the benchmark predicts no move. A reader who saw only the
    number could read ``0.0000`` as "the benchmark was computed and came out
    small" rather than "the benchmark is exactly zero because the inputs are
    equal", and those are different statements.

    Nothing is emitted otherwise. The standing caveat — that the whole model
    fails empirically — holds on every call and is a ``limitation``, and a
    warning that fired on every call would be noise.
    """
    if direction != "flat":
        return []
    return [
        f"The two money-market rates are equal ({differential_annualized:+.6f} "
        f"annualised), so the UIP benchmark predicts an EXACTLY zero move over "
        f"{tenor_days} days. This is the absence of a UIP prediction, not a small "
        f"one: it says the parity condition has no directional content for this "
        f"pair at this tenor, and a carry trade funded here would have no "
        f"benchmark to beat rather than a tiny one."
    ]


def uip_expected_move(inputs: UIPInputs) -> ModelResult:
    """The uncovered-interest-parity benchmark expected spot move.

    ``value`` is a ``dict`` carrying the expected move and every quantity it was
    derived from, so each published number can be recomputed from the output
    alone:

    ``expected_move_pct``
        The period expected spot change in percent. **Positive means UIP
        predicts DOMESTIC DEPRECIATION** — the higher-yielding currency weakens,
        which is the parity condition's content. Computed as
        ``((1 + i_d t) / (1 + i_f t) - 1) * 100``, the exact ratio; the
        specification's ``(i_d - i_f) * 100`` is its first-order form and agrees
        to a fraction of a basis point at G10 differentials.
    ``expected_move_simple_pct``
        The specification's own first-order form, ``(i_d - i_f) * t * 100``,
        published beside the exact one so the approximation's size is visible
        rather than asserted. The two are equal only when ``i_f t == 0``.
    ``i_domestic_period`` / ``i_foreign_period``
        The annualised inputs converted to the expectation's own horizon.
    ``differential_annualized`` / ``differential_period``
        The rate gap in both units — the annualised figure the specification
        works in, and the period figure the expectation actually uses.
    ``direction``
        ``"domestic_depreciation"``, ``"domestic_appreciation"`` or ``"flat"``.

    **Why this is a DIFFERENT FUNCTION from :func:`cip_check`, and not the same
    parity relation read forward — established before the arithmetic was
    written.** The two read the same two rates and rest on the same no-arbitrage
    family, so the question is real and this is the answer:

    * :func:`cip_check` takes a **TRADED FORWARD** as an input and measures how
      far that observed price has departed from the parity-implied one. Its
      output is a **DEVIATION** — a measurement of a live market dislocation,
      positive when the domestic currency is the scarce side of the swap. The
      forward is data.
    * :func:`uip_expected_move` consults **NO forward at all**. It takes only the
      two rates and converts the parity relation into a statement about the
      **EXPECTED FUTURE SPOT** rate. Its output is a **PREDICTION** — the
      benchmark a carry trade is a bet against.

    They are related, and the relation is exactly the point: CIP rearranged gives
    the forward premium ``F/S - 1 = (i_d - i_f) / (1 + i_f)``, and UIP asserts
    the **expected spot change equals that premium**. So UIP is CIP's forward
    premium read as a forecast of the spot rate — and the empirical fact that
    spot does NOT move that way is the forward-premium puzzle, i.e. exactly the
    failure this model exists to make explicit. **One measures a price, the other
    predicts a price; the identity that ties them is the hypothesis that fails.**
    Superseding would require the two to answer the same question, and they do
    not: ``cip_check``'s answer is 'how dislocated is the traded forward today',
    and this one's is 'what would the spot rate do if parity held'.

    **``confidence`` is a model-specific cap, NOT ``compute_confidence()``.** The
    standard remedy for a hardcoded confidence is to derive it from stated
    factors (Section 22.8), and this function deliberately does not: its inputs
    are observable and its arithmetic is exact, so NO reliability factor is
    impaired. What makes it nearly worthless is that the **hypothesis fails
    empirically**, and ``compute_confidence`` has no factor for "the method is
    known to be false". The value is read from
    ``fx_carry.uip_reliability_cap`` and is the specification's own deliberately
    low ``0.15``. See the leaf's note.
    """
    settings = get_settings()
    fx_carry = settings.fx_carry
    reliability = fx_carry.uip_reliability_value

    basis_days = _BASIS_DAYS[inputs.day_count_basis]
    period_scale = inputs.tenor_days / basis_days
    i_domestic_period = inputs.i_domestic_annualized * period_scale
    i_foreign_period = inputs.i_foreign_annualized * period_scale

    differential_annualized = inputs.i_domestic_annualized - inputs.i_foreign_annualized
    differential_period = differential_annualized * period_scale

    # The EXACT parity ratio, and the specification's first-order form beside it.
    # The exact form is published because it is the one that is actually correct
    # at any differential; the simple form is published because it is the one
    # Section 6.7 writes, and a reader comparing this output against the
    # specification must be able to see that the difference is second-order
    # rather than a defect.
    exact_ratio = (1.0 + i_domestic_period) / (1.0 + i_foreign_period)
    expected_move_fraction = exact_ratio - 1.0
    expected_move_pct = expected_move_fraction * 100.0
    expected_move_simple_pct = differential_period * 100.0

    direction = _uip_direction(expected_move_pct)

    if direction == "domestic_depreciation":
        direction_phrase = "the higher-yielding domestic currency is expected to DEPRECIATE"
    elif direction == "domestic_appreciation":
        direction_phrase = "the higher-yielding foreign currency is expected to appreciate"
    else:
        direction_phrase = "no expected move — the two rates are equal"

    return ModelResult(
        model_name="uip_expected_move",
        country="us",
        as_of=utc_now(),
        value={
            "expected_move_pct": round(expected_move_pct, 6),
            "expected_move_simple_pct": round(expected_move_simple_pct, 6),
            "i_domestic_annualized": inputs.i_domestic_annualized,
            "i_foreign_annualized": inputs.i_foreign_annualized,
            "i_domestic_period": round(i_domestic_period, 8),
            "i_foreign_period": round(i_foreign_period, 8),
            "differential_annualized": round(differential_annualized, 8),
            "differential_period": round(differential_period, 8),
            "tenor_days": inputs.tenor_days,
            "day_count_basis": inputs.day_count_basis,
            "day_count_basis_days": basis_days,
            "direction": direction,
        },
        confidence=reliability,
        unit="percent (expected spot change over the stated tenor)",
        direction=direction,
        interpretation=(
            f"UIP benchmark: {expected_move_pct:+.4f}% expected spot move over "
            f"{inputs.tenor_days} days — {direction_phrase}. This is the "
            f"BENCHMARK A CARRY TRADE BETS AGAINST, not a forecast; UIP fails "
            f"empirically (the forward-premium puzzle) and that failure is the "
            f"carry edge."
        ),
        context=(
            f"Domestic {inputs.i_domestic_annualized * 100:+.4f}%/yr and foreign "
            f"{inputs.i_foreign_annualized * 100:+.4f}%/yr are ANNUALISED "
            f"DECIMALS, converted to a {inputs.tenor_days}-day horizon on "
            f"{inputs.day_count_basis}: domestic "
            f"{i_domestic_period * 100:+.6f}%, foreign "
            f"{i_foreign_period * 100:+.6f}% over the period. The exact parity "
            f"ratio (1+i_d t)/(1+i_f t) gives {expected_move_pct:+.6f}%; Section "
            f"6.7's first-order form (i_d - i_f)*t gives "
            f"{expected_move_simple_pct:+.6f}%, a difference of "
            f"{expected_move_simple_pct - expected_move_pct:+.6f}pp — "
            f"second-order in the differential. Confidence is a model-specific "
            f"cap ({reliability}), not a computed penalty: this model's inputs "
            f"are observable and its arithmetic is exact, and what is unreliable "
            f"is the HYPOTHESIS."
        ),
        inputs_used=[
            "i_domestic_annualized",
            "i_foreign_annualized",
            "tenor_days",
            "day_count_basis",
        ],
        assumptions=[
            "Both rates are ANNUALISED DECIMALS for the SAME currency pair and "
            "the SAME horizon, and `tenor_days` is that horizon.",
            "The differential is the MONEY-MARKET differential of the pair's two "
            "currencies, not a bond-yield or policy-rate differential — UIP is "
            "stated on money-market rates.",
            "Interest accrues as simple interest over tenor_days / basis_days, "
            "the money-market convention, which the input model enforces as a "
            "bound rather than approximating.",
            "The parity condition ties the expected spot change to the interest "
            "differential — the hypothesis this benchmark states and the one the "
            "forward-premium puzzle rejects.",
        ],
        source_family=EvidenceSourceFamily.MARKET_FX,
        warnings=_uip_warnings(
            direction=direction,
            differential_annualized=differential_annualized,
            expected_move_pct=expected_move_pct,
            tenor_days=inputs.tenor_days,
        ),
        limitations=_uip_limitations(),
        decision_relevance=(
            "Module 9's parity benchmark, and the theoretical foundation of the "
            "carry trade — but in the NEGATIVE sense: it exists so a carry view "
            "can be stated explicitly as a bet AGAINST it. It reads the same two "
            "rates as `cip_check` and computes a DIFFERENT quantity: `cip_check` "
            "measures a traded forward's deviation from parity (a dislocation), "
            "while this predicts the expected spot move (a benchmark). It "
            "therefore supersedes NOTHING and is not superseded; it pairs with "
            "`carry_score`, whose whole content is that this benchmark's failure "
            "is the carry premium, and with `cip_check`, since the forward "
            "premium this model predicts is the very quantity `cip_check` "
            "measures the market's price of. Script-only today: no snapshot field "
            "carries a foreign money-market rate, so the caller supplies both "
            "rates and the live check is the only consumer until one does."
        ),
        decision_prohibition=[
            "Do NOT use this as a point forecast. UIP fails empirically; the "
            "number is the benchmark a carry trade bets against, and reading it "
            "as a prediction of the spot rate inverts the model's entire purpose "
            "(Section 6.7).",
            "Do NOT size on the expected move. It carries no uncertainty band, no "
            "horizon beyond the stated tenor, and no adjustment for the "
            "well-documented failure — a position sized to it would be sized to a "
            "hypothesis the data reject.",
            "Do NOT read the confidence as comparable with `cip_check`'s or "
            "`carry_score`'s. It is deliberately far lower because the METHOD is "
            "discredited rather than the data; the two facts are not on one "
            "scale.",
        ],
    )


class PPPInputs(BaseModel):
    """A spot exchange rate and the PPP-implied rate it is measured against.

    **The unit question is the one every FX function in this module faces, and
    it is answered by ORDER rather than by a flag: both rates are the SAME
    quote convention, and the deviation's SIGN is what carries the verdict.**
    ``CIPInputs`` makes the quote convention an explicit input because a
    transposed pair silently inverts a sign there; here the sign is not the
    output's only content — both levels are published, so a caller can see the
    convention from the numbers — and the convention itself does not change
    ``overvalued``/``undervalued`` as it is computed, only which of the two
    currencies the sentence names. It is therefore NOT a required input, and the
    published ``quote`` records what the numbers mean.

    **Why a PPP conversion factor is now a FETCHED input rather than a manual one.**
    Until D-117 this docstring read *"the PPP-implied rate is NOT observable in a
    market … Section 21.1 marks ``ppp_implied_rate`` BLOCKED → MANUAL … there is
    no clean free API."* **That premise was measured false** (the D-043
    FALSE-BLOCK class): ``docs/PLAN_ppp_source.md`` found the World Bank REST API
    reachable at indicator ``PA.NUS.PPP``, the same *"direct, not OpenBB"* route
    Section 21.1 already sanctions for ``current_account_pct_gdp``. The input is
    therefore **fetched** — ``data_layer/world_bank_client.py`` — and the
    **fetch is the only path**: there is no manual fallback to go stale beside
    it (the two-paths-for-one-number ambiguity Section 21.1 exists to remove).

    **The fetch is NOT a vintage read, and the distinction is load-bearing.**
    The World Bank offers no point-in-time selector; ``lastupdated`` is a
    PUBLICATION date. That was measured against all four free sources the
    operator named — **not one** has a point-in-time selector — so the ALFRED
    capability remains FRED-only. The fetched value is a **disclosed vintage**,
    and the disclosure is published in ``limitations`` on every call.

    **The estimand is a RATIO, not a factor.** ``PA.NUS.PPP`` is LCU per
    international $, so the PPP-implied level is
    ``factor(domestic) / factor(foreign)``. The euro leg is **Germany** — the
    World Bank's EMU aggregate measures **0 points**, so the substitute is a
    **decision, not a constant** (``PLAN_ppp_source.md`` §4 step 1), recorded in
    the registry with its justification.

    **The spot rate IS observable** and comes from a live FX series; the
    asymmetry is the whole point of the function, and the fetched leg's vintage
    is disclosed in ``limitations`` rather than hidden.

    **The horizon is required, and this is the function's central discipline.**
    The specification computes a bare deviation and stops. But PPP is a
    **multi-year** anchor: the deviation from it is not a signal about the next
    quarter, and a caller that reads one without the other has matched the tool
    to the wrong trade. So the horizon over which the thesis is stated is an
    input, and the model REFUSES a short horizon rather than publishing a
    confident number at a timescale at which the relationship has no content.

    Two refusals, each closing a way the arithmetic returns a confident number
    from an input that has no meaning:

    * **Non-finite** — ``nan`` fails every comparison, so a guard built from
      comparisons never fires for it and the deviation is published as ``nan``
      while the ``status`` branch falls to ``undervalued`` (D-078: a bare
      ``nan`` would reach the arithmetic and the label would be a lie). ``inf``
      passes ``> 0`` and needs the explicit finiteness test.
    * **Non-positive PPP-implied rate** — the deviation divides by it, so a zero
      raises ``ZeroDivisionError`` and a negative inverts the sign of every
      result. A negative price level is not a quote.

    **The horizon refusal is deliberately NOT here, and that is a decision.**
    A short horizon is a property of the THESIS, not of the quote — a 3-month
    PPP deviation is a perfectly well-defined number, it is only a useless one.
    So it is reported as a **warning** rather than refused: refusing would make
    the function unusable for the one thing it can legitimately do at short
    horizons (report that the deviation exists and is uninformative), and
    Section 21.4's discipline is to disclose rather than to forbid. The
    distinction is between an input that has no meaning (refused) and a
    meaningful input whose output must not be over-read (warned).
    """

    model_config = ConfigDict(extra="forbid")

    spot_rate: float = Field(
        description=(
            "The observed spot exchange rate, in the SAME quote convention as "
            "``ppp_implied_rate``. LIVE — a market price."
        ),
    )
    ppp_implied_rate: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "The PPP-implied rate for the same pair. **Optional since D-117**: "
            "when omitted, ``ppp_valuation`` FETCHES it from the World Bank "
            "(indicator ``PA.NUS.PPP``) using ``domestic_iso3`` / ``foreign_iso3``. "
            "When supplied, it is used verbatim — so a test, or a replay against "
            "a recorded value, is deterministic and offline. Supplying it is the "
            "override; omitting it is the live path. Must be > 0 when supplied."
        ),
    )
    domestic_iso3: str | None = Field(
        default=None,
        description=(
            "ISO3 code of the DOMESTIC leg, used when ``ppp_implied_rate`` is "
            "omitted. For a 'domestic per foreign' quote (USD per EUR) this is "
            "the base of the level (EUR -> 'DEU' is the euro container; see the "
            "registry's ``ppp_conversion_factor_eur``)."
        ),
    )
    foreign_iso3: str | None = Field(
        default=None,
        description=(
            "ISO3 code of the FOREIGN leg, used when ``ppp_implied_rate`` is "
            "omitted. For a 'domestic per foreign' quote this is the numeraire "
            "('USA' for a USD-quoted pair, whose factor is definitionally 1)."
        ),
    )
    horizon_years: float = Field(
        gt=0.0,
        description=(
            "The horizon the caller's thesis is stated over, in YEARS. PPP is a "
            "multi-year anchor; a horizon under "
            "``fx_carry.ppp_tactical_horizon_years`` triggers the "
            "no-tactical-timing warning."
        ),
    )
    quote: str = Field(
        default="domestic_per_foreign",
        description=(
            "The quote convention both rates share: 'domestic_per_foreign' "
            "(e.g. 1.14 USD per EUR) or 'foreign_per_domestic' (e.g. 147 JPY "
            "per USD). Recorded so the deviation's sign is interpretable."
        ),
    )

    @model_validator(mode="after")
    def _validate_domain(self) -> PPPInputs:
        """Refuse an input that is representable but is not a price quote.

        Branches, and they fail differently:

        * **Non-finite** — ``nan`` fails every comparison, so ``if x <= 0``
          never fires for it; the deviation would be published as ``nan`` and
          the ``status`` branch, which is a comparison, would silently take the
          ``undervalued`` arm. ``inf`` passes ``> 0`` and needs the explicit
          finiteness test (D-078).
        * **Non-positive PPP-implied rate** — it is the deviation's denominator.
          A zero raises ``ZeroDivisionError``; a negative inverts every sign.
          The ``gt=0.0`` field bound already covers this for a finite value, so
          this branch exists for the ``nan``/``inf`` cases the bound cannot see
          — which is the point of validating rather than trusting the bound.
        * **The rate XOR the pair** — since D-117 the rate is OPTIONAL and the
          model can FETCH it. Supplying neither leaves no estimator; supplying
          an incomplete pair leaves an unanswerable fetch. **Both are refused
          here rather than at fetch time**, so a caller learns the request is
          malformed before any network call, and the failure is the same
          offline as online.
        """
        for name in ("spot_rate", "horizon_years"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(
                    f"{name} is {value!r}, which is not finite. A non-finite input "
                    f"cannot form a deviation: every comparison a plausibility check "
                    f"is made of returns False for nan, so it would reach the "
                    f"arithmetic and produce a non-finite value that looks like an "
                    f"answer (D-078)."
                )

        if self.ppp_implied_rate is None:
            # The fetch path. Both legs are required, and each must be a
            # plausible ISO3 -- validated here so an incomplete request fails
            # identically offline and online.
            if self.domestic_iso3 is None or self.foreign_iso3 is None:
                raise ValueError(
                    "ppp_implied_rate was omitted (the fetch path), so BOTH "
                    "domestic_iso3 and foreign_iso3 must be supplied. Supplying "
                    "neither leaves no estimator; supplying one leaves an "
                    "unanswerable fetch. Pass ppp_implied_rate directly for a "
                    "deterministic offline call, or pass the pair to fetch it."
                )
        else:
            if not math.isfinite(self.ppp_implied_rate):
                raise ValueError(
                    f"ppp_implied_rate is {self.ppp_implied_rate!r}, which is not "
                    f"finite. A non-finite input cannot form a deviation: every "
                    f"comparison a plausibility check is made of returns False for "
                    f"nan, so it would reach the arithmetic and produce a "
                    f"non-finite value that looks like an answer (D-078)."
                )
            if self.ppp_implied_rate <= 0.0:
                raise ValueError(
                    f"ppp_implied_rate is {self.ppp_implied_rate}, which is not a "
                    f"price level. The deviation divides by it, so a zero raises "
                    f"ZeroDivisionError and a negative inverts the sign of every "
                    f"result — an 'undervaluation' would be reported for an "
                    f"overvaluation."
                )

        if self.quote not in _QUOTE_CONVENTIONS:
            raise ValueError(
                f"quote is {self.quote!r}; must be one of {sorted(_QUOTE_CONVENTIONS)}."
            )
        return self


def _ppp_status(deviation_pct: float) -> PPPStatus:
    """Which side of PPP the spot rate sits on, from the deviation's sign.

    Derived from the SIGN of the published deviation rather than from a fresh
    comparison of the two levels, so the label and the number cannot disagree —
    the same discipline ``_uip_direction`` follows. A spot ABOVE the PPP-implied
    rate (``deviation_pct > 0``) means the currency is **overvalued** relative to
    purchasing power: it buys less domestically than the price levels imply.
    """
    if deviation_pct > 0.0:
        return "overvalued"
    if deviation_pct < 0.0:
        return "undervalued"
    return "at_parity"


def _ppp_limitations(ppp_vintage: str | None) -> list[str]:
    """The function's standing limitations, published on EVERY call.

    Structurally constant except for one interpolated fact, ``ppp_vintage`` —
    the provenance of the PPP leg. It is a parameter rather than a constant
    since D-117 because the leg is **fetched**, and its freshness is a real
    property of the call: the published figure, its year, and its publication
    date. A constant string here would be a disclosure that discloses nothing
    (the D-110 class: a caveat that CAN be an assertion SHOULD be).

    When ``ppp_vintage`` is ``None`` the leg was supplied by the caller
    (the deterministic/offline override) and the text says so, rather than
    pretending a provenance it cannot know.
    """
    if ppp_vintage is None:
        vintage_clause = (
            "The PPP-implied rate was SUPPLIED BY THE CALLER rather than "
            "fetched, so its vintage is unknown to this result. Section 21.1 "
            "sources this input from the World Bank REST API (indicator "
            "PA.NUS.PPP); a caller that overrides it takes responsibility for "
            "the figure's provenance."
        )
    else:
        vintage_clause = (
            f"The PPP-implied rate is FETCHED, not a market price, and is a "
            f"DISCLOSED VINTAGE rather than a point-in-time vintage: the World "
            f"Bank REST API offers no point-in-time selector, so this is the "
            f"latest published revision. {ppp_vintage}"
        )
    return [
        vintage_clause,
        "PPP is a MULTI-YEAR anchor. A deviation from it is NOT a signal about "
        "the next quarter: deviations persist for years, and the relationship "
        "carries no timing information at any horizon a trader acts on. The "
        "warning fires automatically below the configured tactical horizon.",
        "The two rates must share ONE quote convention, and the convention is "
        "carried in the input rather than inferred. A caller that passes a "
        "consistently transposed pair gets a deviation that is wrong in "
        "magnitude and whose ``status`` may be wrong in sign.",
        "Absolute PPP is the version measured here — the ratio of price levels. "
        "It is the version most strongly rejected empirically; relative PPP "
        "(the CHANGE in the ratio) is better behaved and is not what this "
        "computes.",
        "No uncertainty band, no confidence interval, and no adjustment for the "
        "Balassa-Samuelson effect (richer countries' price levels are "
        "systematically higher, so a rich-country currency reads as persistently "
        "'overvalued' by construction).",
    ]


def _ppp_warnings(
    *,
    status: PPPStatus,
    deviation_pct: float,
    horizon_years: float,
    tactical_horizon_years: float,
) -> list[str]:
    """The warning paths, each of which a test must be able to trigger.

    Three conditions, and the first is the one the specification names:

    * **a tactical horizon** — the caller's thesis is shorter than PPP can
      speak to. This is Section 6.7's "NEVER use PPP for tactical timing" made
      operational: the threshold is a config leaf, so the warning fires on a
      DATE-like comparison of the stated horizon rather than on a bare literal.
    * **an overvaluation at a tactical horizon** — the same fact, stated as the
      specific error 6.7 warns about, because "the currency is 30 % overvalued"
      read at three months is the single most common misuse of this model.
    * **a deviation large enough to be a data check** — a >100 % deviation is
      more often a unit or convention error (a transposed pair, a rate passed
      where a level was expected) than a genuine market state, so it is
      surfaced rather than published silently.
    """
    warnings: list[str] = []
    if horizon_years < tactical_horizon_years:
        warnings.append(
            f"The stated horizon ({horizon_years} years) is shorter than PPP's "
            f"tactical minimum ({tactical_horizon_years} years). PPP is a "
            f"MULTI-YEAR anchor and this deviation carries NO timing "
            f"information at this horizon — do not act on it (Section 6.7: "
            f"'NEVER use PPP for tactical timing')."
        )
    if status == "overvalued" and horizon_years < tactical_horizon_years:
        warnings.append(
            f"{deviation_pct:+.1f}% overvalued, read at {horizon_years} years. "
            f"An overvaluation is the textbook mean-reversion story AND the "
            f"textbook way to lose money: it can persist for a decade and "
            f"widen. Matching the tool's horizon to the trade's horizon is the "
            f"discipline (Module 9.2)."
        )
    if abs(deviation_pct) > 100.0:
        warnings.append(
            f"The deviation is {deviation_pct:+.1f}%, beyond any plausible "
            f"purchasing-power gap. A four-figure deviation is far more often a "
            f"UNIT OR CONVENTION ERROR than a market state — check that both "
            f"rates share one quote convention and that neither is a rate "
            f"passed where a level was expected."
        )
    return warnings


def ppp_valuation(inputs: PPPInputs) -> ModelResult:
    """How far the spot rate sits from the purchasing-power-parity rate.

    Module 9.2. PPP is a **MULTI-YEAR anchor, never a timing tool**: the
    deviation is real and the discipline is to refuse to let it be read at a
    horizon it cannot speak to.

    ``value`` publishes, so every number can be recomputed from the output
    alone:

    ``deviation_pct``
        ``(spot - ppp_implied) / ppp_implied * 100`` — the specification's own
        formula, positive when the spot rate is ABOVE the PPP-implied rate.
    ``status``
        ``"overvalued"``, ``"undervalued"`` or ``"at_parity"``.
    ``spot_rate`` / ``ppp_implied_rate`` / ``quote``
        The two inputs and their shared convention, so the sign is readable
        without the caller's context.
    ``horizon_years`` / ``tactical_horizon_years``
        The stated horizon and the configured threshold, so a reader can see
        whether and why the no-tactical-timing warning fired.
    ``ratio``
        ``spot / ppp_implied`` — the same information as ``deviation_pct`` in
        ratio form, published because it is the natural way to state a PPP gap.

    **``confidence`` is a model-specific cap, NOT ``compute_confidence()``.**
    The standard remedy for a low hardcoded confidence is to derive it from
    stated factors (Section 22.8), and this function deliberately does not — the
    PRE ``uip_expected_move`` precedent, and for the same reason: the inputs are
    as reliable as their sources (the spot leg is a live price; the PPP leg is a
    manual vintage), but no reliability factor captures what is wrong here, which
    is that **absolute PPP is the version of the relationship most strongly
    rejected by the data**. ``compute_confidence()`` has no factor for "the
    method is empirically weak". The value is read from
    ``fx_carry.ppp_reliability_cap``, the specification's own deliberately low
    ``0.2``.

    **Supersession: this is a DIFFERENT function from anything in the module.**
    ``cip_check``/``uip_expected_move`` are INTEREST-parity relations between two
    money-market rates; this is a PRICE-LEVEL relation between a market rate and
    a constructed level. It shares no input with them and answers a different
    question — 'is the currency cheap in purchasing-power terms' rather than
    'what do the two currencies' interest rates imply'. It supersedes nothing
    and is superseded by nothing. Module 9's `ppp_valuation` and
    `intervention_capacity` are its neighbours in Section 20.9; the latter is
    built separately.
    """
    settings = get_settings()
    fx_carry = settings.fx_carry
    reliability = fx_carry.ppp_reliability_value
    tactical_horizon_years = fx_carry.ppp_tactical_horizon_value

    # --- resolve the PPP leg: fetch it, or take the caller's override -------
    # The fetch is the ONLY live path (the operator's D-117 decision): there is
    # no manual fallback to drift beside it. A caller MAY override with an
    # explicit rate, which is what keeps unit tests deterministic and offline.
    ppp_implied_rate = inputs.ppp_implied_rate
    ppp_vintage: str | None = None
    if ppp_implied_rate is None:
        # Validated in `_validate_domain`: both legs are present here.
        if inputs.domestic_iso3 is None or inputs.foreign_iso3 is None:  # pragma: no cover
            raise ValueError(
                "ppp_implied_rate is None but the pair is incomplete; "
                "_validate_domain should have refused this input."
            )
        ppp_implied_rate, ppp_vintage = fetch_ppp_implied_rate(
            inputs.domestic_iso3, inputs.foreign_iso3
        )

    deviation_pct = (inputs.spot_rate - ppp_implied_rate) / ppp_implied_rate * 100.0
    ratio = inputs.spot_rate / ppp_implied_rate
    status = _ppp_status(deviation_pct)

    if status == "overvalued":
        status_phrase = (
            "the spot rate is ABOVE the PPP-implied rate, so the currency is "
            "OVERvalued in purchasing-power terms"
        )
    elif status == "undervalued":
        status_phrase = (
            "the spot rate is BELOW the PPP-implied rate, so the currency is "
            "UNDERvalued in purchasing-power terms"
        )
    else:
        status_phrase = "the spot rate equals the PPP-implied rate, so the currency is AT PARITY"

    return ModelResult(
        model_name="ppp_valuation",
        country="global",
        as_of=utc_now(),
        value={
            "deviation_pct": round(deviation_pct, 2),
            "ratio": round(ratio, 6),
            "status": status,
            "spot_rate": inputs.spot_rate,
            "ppp_implied_rate": ppp_implied_rate,
            "quote": inputs.quote,
            "horizon_years": inputs.horizon_years,
            "tactical_horizon_years": tactical_horizon_years,
        },
        confidence=reliability,
        unit="percent deviation of the spot rate from the PPP-implied rate",
        interpretation=(
            f"{abs(deviation_pct):.1f}% {status} vs PPP — {status_phrase}. "
            f"MULTI-YEAR anchor only: a PPP deviation is not a signal about the "
            f"next quarter (Module 9.2)."
        ),
        context=(
            f"Spot {inputs.spot_rate} against a PPP-implied "
            f"{ppp_implied_rate} ({inputs.quote}), quoted as a "
            f"{ratio:.6f} ratio and a {deviation_pct:+.2f}% deviation, over a "
            f"{inputs.horizon_years}-year thesis against a "
            f"{tactical_horizon_years}-year tactical minimum. "
            f"{_PPP_PROVENANCE_SUPPLIED if ppp_vintage is None else ppp_vintage} "
            f"It is a constructed price level, not an observed market price, and "
            f"it is revised. Confidence is a model-specific cap "
            f"({reliability}), not a computed penalty: what is unreliable is "
            f"that ABSOLUTE PPP is the version of the relationship most "
            f"strongly rejected empirically, and no input-reliability factor "
            f"captures that."
        ),
        inputs_used=["spot_rate", "ppp_implied_rate", "horizon_years", "quote"],
        assumptions=[
            "Both rates share ONE quote convention, carried in `quote`; the "
            "deviation's sign and the status label are read under it.",
            "The PPP-implied rate is an ABSOLUTE-PPP conversion factor (a ratio "
            "of price levels), not a relative-PPP change forecast.",
            "The spot rate is a market price and is contemporaneous with the "
            "call; the PPP factor has its own, older, vintage that this result "
            "carries only as a disclosure.",
            "No adjustment is made for the Balassa-Samuelson effect — richer "
            "countries' price levels are systematically higher, so a "
            "rich-country currency reads as persistently overvalued by "
            "construction.",
        ],
        source_family=EvidenceSourceFamily.MARKET_FX,
        warnings=_ppp_warnings(
            status=status,
            deviation_pct=deviation_pct,
            horizon_years=inputs.horizon_years,
            tactical_horizon_years=tactical_horizon_years,
        ),
        limitations=_ppp_limitations(ppp_vintage),
        decision_relevance=(
            "Module 9's price-level anchor, and the counterpart to its "
            "interest-parity relations: `cip_check` and `uip_expected_move` "
            "answer 'what do two interest rates imply', while this answers 'is "
            "the currency cheap in purchasing-power terms'. It shares NO input "
            "with them — the relationship is between a market rate and a "
            "constructed price level — so it supersedes NOTHING and pairs with "
            "nothing in the parity family. It is a YEARS-horizon valuation "
            "input, useful for asking whether a long-lived trade is swimming "
            "with or against a valuation gap, and useless as a timing signal. "
            "Script-only today: no snapshot field carries a PPP conversion "
            "factor, so the live check supplies the manual leg with a declared "
            "vintage until a source exists."
        ),
        decision_prohibition=[
            "Do NOT use this for tactical timing. PPP is a MULTI-YEAR anchor and "
            "deviations persist for YEARS; the warning fires automatically below "
            "the configured tactical horizon, and ignoring it is the single most "
            "common misuse of this model (Section 6.7: 'NEVER use PPP for "
            "tactical timing').",
            "Do NOT treat the manual PPP leg as an observed price. It is a "
            "constructed, low-frequency, REVISED conversion factor, and a "
            "different vintage can move the deviation materially — the "
            "limitations say so on every call.",
            "Do NOT read the confidence as comparable with an "
            "interest-parity function's. It is a model-specific cap because the "
            "METHOD (absolute PPP) is empirically weak, which is a different "
            "statement from the inputs being noisy.",
            "Do NOT implement a valuation-gap trade on the deviation alone. Mean "
            "reversion is not scheduled: the gap can persist and widen for a "
            "decade, so a position sized to the gap is a position sized to an "
            "assumption about WHEN, which this model does not make.",
        ],
    )


# A guard on the module's own vocabulary, asserted at import: every declared
# day-count basis must have a length, or the conversion would KeyError at the
# first call rather than at load. `get_args` reads the type itself, so a member
# added to the Literal without a `_BASIS_DAYS` entry fails here.
assert set(get_args(DayCountBasis)) == set(_BASIS_DAYS), (
    "DayCountBasis and _BASIS_DAYS disagree about the permitted bases; a "
    "declared basis with no year length would raise KeyError inside cip_check."
)
