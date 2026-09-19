"""Module 8.2 — auction demand as real-time evidence of duration demand.

Section 20.8's premise is sound and is the reason this function exists: an
auction is the one moment when the market must transact a known size at a
known time, so how well it clears is direct evidence about appetite for
duration rather than an inference from price. A weak or tailing auction
corroborates a term-premium-driven yield move; a strong one argues against it.

Four things had to be measured before the function could be written, and three
of them change what the inputs mean. See **D-036**.

**1. The tail input is MANUAL, not LIVE.** Section 21.1 names "TreasuryDirect
auction results API" as ``stop_through_bp``'s source. That route was inspected
column by column — all 91 columns on the ``note`` security type — and it
carries **no when-issued or expected-yield field**. The three yields it does
expose are within-auction statistics: ``high_yield - avg_median_yield`` is
between 0.0000 and 0.0011 on **every one of 703 auctions**, i.e. the median bid
and the clearing yield are the same number to a rounding error. A tail is not a
within-auction statistic — it compares the clearing yield with what the market
expected *before* the auction, which the Treasury does not publish. The caller
supplies the gap and the model marks it as manual entry.

**2. The sign convention is the trap.** ``stop_through_bp`` is
``(expected yield - clearing yield)``, so **negative means the auction cleared
above expectations** — a tail, which is weak. A caller who supplies the more
intuitive ``(clearing - expected)`` "yield surprise" would invert every verdict
silently, because both signs produce a plausible number. This is D-034's
failure mode (a sign-inverted term that was wrong on 414/414 observations
without raising an error), so the convention is stated in the field
description, published in ``value``, and warned about.

**3. The indirect share has two defensible bases and they differ by ~27pp.**
The feed exposes both ``indirect_bidder_accepted`` and
``indirect_bidder_tendered``. Measured over 703 note auctions: **54.9%** on the
accepted basis against **28.3%** on the tendered basis, largest single-row gap
**45.3pp**. This model takes the ACCEPTED basis, which is the market convention
(Treasury reports the indirect share of the amount awarded). A caller supplying
the other basis would move the flag by nine times the 3pp threshold it is
compared against.

**4. The trailing average must be grouped on the normalised tenor.** The feed's
``security_term`` splits one tenor across three labels — a 10-Year note appears
as ``"10-Year"``, ``"9-Year 11-Month"`` and ``"9-Year 10-Month"`` depending on
whether the auction is an original or a reopening — so grouping on the raw
string builds each average from a third of the history. Group on
``original_security_term``.

The function itself is a pure calculator over the five floats it is given: it
does not fetch, and it does not know where the numbers came from. That
separation is what lets the live check exercise the derivable inputs against
real auctions while stating plainly that it cannot derive the fifth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

if TYPE_CHECKING:
    from macro_engine.config import AuctionDemandSettings

__all__ = [
    "AuctionInputs",
    "AuctionVerdict",
    "auction_demand_signal",
]

#: The three verdicts, as a closed vocabulary rather than a bare ``str``.
#:
#: D-029's lesson: a ``str`` field lets a typo fall through to whichever branch
#: is written last, and ``extra="forbid"`` cannot catch it because the field
#: *is* provided. Typing it as a ``Literal`` makes the vocabulary the only
#: thing that can be produced.
AuctionVerdict = Literal[
    "WEAK_AUCTION_term_premium_pressure",
    "STRONG_AUCTION",
    "MIXED",
]


class AuctionInputs(BaseModel):
    """One auction, plus the trailing averages it is judged against.

    The trailing averages are supplied by the caller rather than computed here,
    because the window and the grouping are properties of the *history*, not of
    this auction — and because a function that both fetched its own comparison
    base and judged against it could not be validated on a fixed input.

    **``stop_through_bp`` is manual entry.** No route in this build publishes
    the when-issued yield a tail is measured against (D-036), so the caller
    supplies it from their own market data. The model says so in its output.
    """

    model_config = ConfigDict(extra="forbid")

    bid_to_cover: float = Field(
        gt=0.0,
        description=(
            "Total tendered divided by total accepted, as published. Must be "
            "positive — it is a ratio of two positive quantities, and is >= 1 "
            "in practice because tendered exceeds accepted."
        ),
    )
    bid_to_cover_trailing_avg: float = Field(
        gt=0.0,
        description=(
            "Mean bid-to-cover over the prior N auctions of the SAME normalised "
            "tenor. Must be positive: it is a divisor, and a zero here would "
            "make every auction look weak."
        ),
    )
    indirect_bidder_pct: float = Field(
        ge=0.0,
        le=100.0,
        description=(
            "Indirect bidders' share of the amount ACCEPTED, in percent. The "
            "accepted basis, not the tendered basis — the two differ by ~27pp "
            "on average (D-036)."
        ),
    )
    indirect_bidder_trailing_avg: float = Field(
        gt=0.0,
        description=(
            "Mean indirect share, same basis and same normalised tenor, over "
            "the prior N auctions. Must be positive: a zero would silently "
            "disable the fading flag, because no percentage is more than 3pp "
            "below zero."
        ),
    )
    stop_through_bp: float = Field(
        description=(
            "MANUAL ENTRY. Expected yield minus clearing yield, in basis "
            "points, so NEGATIVE means the auction cleared above expectations "
            "— a tail. Reversing this convention inverts every verdict while "
            "still producing a plausible number (D-036)."
        ),
    )


def auction_demand_signal(inputs: AuctionInputs) -> ModelResult:
    """Judge one auction's demand and say what it implies about duration demand.

    Section 20.8. Returns a three-way verdict from two comparisons, plus a
    separate flag for whether foreign (indirect) demand is fading, which the
    verdict deliberately does not fold in.

    Confidence is computed from the stated factors (Section 22.8), never
    asserted. Both thresholds are ``uncalibrated_illustrative``, so the model
    takes the heuristic penalty automatically through
    ``Settings.is_calibrated()`` — if a future phase calibrates them, the
    confidence rises without this function changing.
    """
    settings = _auction_settings()

    weak_bid_to_cover = inputs.bid_to_cover < (
        inputs.bid_to_cover_trailing_avg * settings.weak_bid_to_cover_ratio
    )
    # Negative stop-through is a tail by construction: the auction cleared at a
    # HIGHER yield than expected. See the field description and D-036.
    tailed = inputs.stop_through_bp < settings.tail_boundary_bp
    foreign_fading = inputs.indirect_bidder_pct < (
        inputs.indirect_bidder_trailing_avg - settings.indirect_fade_threshold_pp
    )

    verdict: AuctionVerdict
    if weak_bid_to_cover and tailed:
        verdict = "WEAK_AUCTION_term_premium_pressure"
    elif not weak_bid_to_cover and not tailed:
        verdict = "STRONG_AUCTION"
    else:
        verdict = "MIXED"

    warnings = [
        # Section 20.8's own warning, kept verbatim: it is the reason this
        # verdict must not be read as a structural conclusion from one print.
        "A single tailing auction can be a temporary liquidity artifact — require "
        "persistence before concluding structural demand shift.",
        # The manual-input disclosure. A reader comparing two runs of this
        # function must know which of the five numbers was typed by a human.
        "stop_through_bp is MANUAL ENTRY, not sourced: no route in this build "
        "publishes the when-issued yield a tail is measured against (D-036). The "
        "tailed flag is only as good as the operator's benchmark.",
        # The sign convention, because getting it wrong inverts the answer
        # without changing its plausibility (the D-034 failure mode).
        f"Sign convention: stop_through_bp is (expected - clearing), so a value "
        f"below {settings.tail_boundary_bp:.1f}bp is a TAIL. Read the published "
        f"'tailed' flag rather than the raw number.",
        # D-029: the flags travel with their own measured frequency.
        f"Both flags fire often. Over {settings.base_rates.auctions_measured} live "
        f"10-Year auctions, 'weak bid-to-cover' fired in "
        f"{settings.base_rates.weak_bid_to_cover_rate:.1%} of them and 'foreign "
        f"demand fading' in {settings.base_rates.foreign_fading_rate:.1%}. A flag "
        f"that fires this often is weak evidence on its own.",
    ]

    if verdict == "STRONG_AUCTION" and foreign_fading:
        # The verdict deliberately ignores the indirect share, so the one case
        # where that omission could mislead has to be said out loud.
        warnings.append(
            "The verdict is STRONG on price (bid-to-cover and tail) while "
            "indirect demand is fading. The verdict does not incorporate the "
            "indirect share, so 'STRONG_AUCTION' here means the auction cleared "
            "well, NOT that demand composition is healthy."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            # Both thresholds are uncalibrated_illustrative in settings.yaml, so
            # this reads True today and would read False if a later phase
            # calibrates them. Deriving it beats asserting it.
            is_heuristic_not_calibrated=not _thresholds_calibrated(),
            # All four sourced inputs come from one auction record. One source is
            # one family, not four corroborating ones.
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="auction_demand_signal",
        country="us",
        as_of=utc_now(),
        value={
            "verdict": verdict,
            # The components, published so the verdict can be RECOMPUTED from
            # the output rather than trusted (the D-009 cross-field identity).
            "weak_bid_to_cover": weak_bid_to_cover,
            "tailed": tailed,
            "foreign_demand_fading": foreign_fading,
            "bid_to_cover": round(inputs.bid_to_cover, 4),
            "bid_to_cover_trailing_avg": round(inputs.bid_to_cover_trailing_avg, 4),
            "indirect_bidder_pct": round(inputs.indirect_bidder_pct, 4),
            "indirect_bidder_trailing_avg": round(inputs.indirect_bidder_trailing_avg, 4),
            "stop_through_bp": round(inputs.stop_through_bp, 4),
            "stop_through_is_manual_entry": True,
            # The window is published because the caller computed the trailing
            # averages and a reader must be able to see what they were taken
            # over. It was previously a config leaf no code path read, which a
            # mutation sweep caught: changing it altered nothing observable.
            "trailing_window_auctions": settings.trailing_window_auctions,
            "weak_bid_to_cover_base_rate": settings.base_rates.weak_bid_to_cover_rate,
            "foreign_fading_base_rate": settings.base_rates.foreign_fading_rate,
            "auctions_measured": settings.base_rates.auctions_measured,
        },
        confidence=confidence,
        interpretation=(
            f"Auction: {verdict}" + (" | indirect-bidder share fading" if foreign_fading else "")
        ),
        context=(
            "Weak auctions corroborate term-premium-driven rather than "
            "expectations-driven yield moves (Module 8.2). The verdict uses "
            "bid-to-cover and the tail only; the indirect-bidder share is "
            "reported alongside it, not folded in."
        ),
        inputs_used=[
            "bid_to_cover",
            "bid_to_cover_trailing_avg",
            "indirect_bidder_pct",
            "indirect_bidder_trailing_avg",
            "stop_through_bp",
        ],
        warnings=warnings,
    )


def _thresholds_calibrated() -> bool:
    """Whether Module 8.2's decision thresholds are calibrated or placeholders.

    Both are ``uncalibrated_illustrative`` in ``settings.yaml``. Read through
    ``Settings.is_calibrated()`` rather than hardcoded so that calibrating them
    in a later phase raises this model's confidence without touching this file.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    return settings.is_calibrated(
        "auction_demand.weak_bid_to_cover_ratio_value"
    ) and settings.is_calibrated("auction_demand.indirect_fade_threshold_pp_value")


def _auction_settings() -> AuctionDemandSettings:
    """Read Module 8.2's thresholds and base rates. Lazy to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().auction_demand
