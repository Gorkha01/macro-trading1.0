"""Module 9 — FX Carry / Parity: covered interest parity and its deviations.

Section 6.7 gives this module three functions. This file implements two of them,
:func:`cip_check` (D-108) and :func:`carry_score` (D-109); ``dollar_smile_regime``
will join them here. Section 6.7 also supplies a **reference implementation** for
each — so these are stubs to UPGRADE, not functions to invent — and the reference
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
    "FundingStressSide",
    "QuoteConvention",
    "StressSeverity",
    "carry_score",
    "cip_check",
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


# A guard on the module's own vocabulary, asserted at import: every declared
# day-count basis must have a length, or the conversion would KeyError at the
# first call rather than at load. `get_args` reads the type itself, so a member
# added to the Literal without a `_BASIS_DAYS` entry fails here.
assert set(get_args(DayCountBasis)) == set(_BASIS_DAYS), (
    "DayCountBasis and _BASIS_DAYS disagree about the permitted bases; a "
    "declared basis with no year length would raise KeyError inside cip_check."
)
