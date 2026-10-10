"""FX conversion — the bridge that makes two countries comparable (Section 22.3).

Why this is a module and not a line of arithmetic
-------------------------------------------------
Section 22.3's four-layer bar puts **FX between layer 3 (instruments) and layer 4
(cross-country reasoning)**. Without it, "UST 10y is 4.3% and Bunds are 2.4%, so
the spread is 1.9%" is a sentence that compares two numbers **measured in
different currencies on different bases** and calls the difference meaningful.
A cross-country thesis needs both legs in ONE currency first.

That conversion is three lines of arithmetic and one convention, which is exactly
the shape LAW 2 says must have **one** implementation: a rate is only
interpretable with its quote direction, and a direction error yields a plausible
number that means the opposite of the truth (``CIPInputs``'s own warning). So it
lives here, once, hand-derived both ways, with the convention named.

The arithmetic, hand-derived both directions
--------------------------------------------
A pair ``(base, quote)`` with rate ``r`` means **``r`` units of ``quote`` per one
unit of ``base``** — so ``EURUSD = 1.12`` is *1.12 USD per 1 EUR*.

* **Converting an amount FROM the base TO the quote** (EUR -> USD): each euro is
  worth ``r`` dollars, so

      amount_quote = amount_base * r          # 100 EUR * 1.12 = 112 USD

  A rising ``EURUSD`` therefore makes the *same* euro amount buy *more* dollars,
  which is the dollar weakening — the sign a reader must never have to guess.

* **Converting an amount FROM the quote TO the base** (USD -> EUR): each dollar
  is worth ``1/r`` euros, so

      amount_base = amount_quote / r          # 112 USD / 1.12 = 100 EUR

The two are exact inverses, and :func:`convert` asserts that round-trip in its
own test rather than trusting it — a reciprocal placed on the wrong side passes
a one-directional test and fails the round trip.

A rate must be **strictly positive**: ``1/r`` divides, so a zero rate is a
ZeroDivisionError and a negative one would flip the sign of a currency amount.
Both are refused here rather than producing an infinity or a sign-inverted
number three modules downstream (D-078's class).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "FxConversionError",
    "FxRate",
    "convert",
]


class FxConversionError(Exception):
    """A conversion was asked for that cannot be performed honestly.

    Raised for: a same-currency conversion (which is a no-op the caller should
    not have routed here), an unknown/absent pair, a non-positive or non-finite
    rate, and a non-finite amount. Each is a *refusal*, not a silent pass-through,
    because every one of them would otherwise produce a number that looks fine.
    """


@dataclass(frozen=True)
class FxRate:
    """One rate, with the pair it belongs to and the direction made explicit.

    ``base``/``quote`` are ISO-4217 alpha-3 codes and ``rate`` is *units of
    ``quote`` per one unit of ``base``*. Storing the two codes rather than a
    symbol string means :func:`convert` never re-parses a ticker to learn the
    direction — the direction is data on the object (the same reason
    ``FX_PAIRS`` maps to a tuple rather than a six-letter string).
    """

    base: str
    quote: str
    rate: float

    def __post_init__(self) -> None:
        base = self.base.strip().upper()
        quote = self.quote.strip().upper()
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "quote", quote)
        if base == quote:
            raise FxConversionError(
                f"an FX rate for {base}/{quote} is the same currency on both "
                f"sides. Its rate is 1.0 by construction, so a pair object here "
                f"is a caller error, not a rate."
            )
        if not math.isfinite(self.rate):
            raise FxConversionError(
                f"the {base}/{quote} rate is {self.rate!r}, which is not finite. "
                f"A nan passes every comparison (D-078), so it would flow through "
                f"the conversion and poison the result silently."
            )
        if self.rate <= 0.0:
            raise FxConversionError(
                f"the {base}/{quote} rate is {self.rate}, which is not strictly "
                f"positive. Converting the other direction divides by it, so a "
                f"zero is a ZeroDivisionError and a negative value flips the "
                f"sign of a currency amount."
            )

    @property
    def convention(self) -> str:
        """What one unit of :attr:`rate` means, in words."""
        return f"{self.quote} per 1 {self.base}"


def convert(
    amount: float,
    *,
    frm: str,
    to: str,
    rate: FxRate,
) -> float:
    """Convert ``amount`` from currency ``frm`` to currency ``to`` using ``rate``.

    Parameters
    ----------
    amount:
        A quantity in ``frm``. Must be finite (a ``nan`` or ``inf`` would flow
        through untouched — D-078).
    frm, to:
        ISO-4217 alpha-3 codes. They must **differ**, and the pair ``(frm, to)``
        must be **the rate's own pair in one of its two orders** — i.e. either
        ``frm == rate.base and to == rate.quote``, or the reverse. Any other
        combination raises: converting EUR to JPY with an ``EURUSD`` rate is a
        **cross**, not a conversion, and a cross carries bid/ask and timing
        conventions the caller did not supply.

    Returns
    -------
    float
        The amount in ``to``.

    Raises
    ------
    FxConversionError
        Same-currency request, a pair that is not this rate's, a non-finite
        amount, or an invalid rate (the latter raised at :class:`FxRate`
        construction).

    Notes
    -----
    The direction is **derived from the codes**, never passed as a flag. A
    ``forward: bool`` parameter would let a caller convert USD->EUR with a EURUSD
    rate by flipping the flag, which is exactly the class of error that produces
    a plausible answer with the wrong sign.
    """
    frm_code = frm.strip().upper()
    to_code = to.strip().upper()

    if frm_code == to_code:
        raise FxConversionError(
            f"convert() was asked to convert {frm_code} to itself. This is a "
            f"no-op; a caller that routes it here expected a rate to do "
            f"something, and returning the input unchanged would hide the "
            f"mistake."
        )
    if not math.isfinite(amount):
        raise FxConversionError(f"the amount to convert is {amount!r}, which is not finite.")

    if frm_code == rate.base and to_code == rate.quote:
        # Base -> quote: each base unit is `rate` quote units.
        return amount * rate.rate
    if frm_code == rate.quote and to_code == rate.base:
        # Quote -> base: each quote unit is `1/rate` base units.
        return amount / rate.rate

    raise FxConversionError(
        f"convert() was given {frm_code}->{to_code} but the rate is for "
        f"{rate.base}/{rate.quote} ({rate.convention}). These are not the same "
        f"pair, so this is a CROSS, not a conversion — and a cross has its own "
        f"bid/ask and timing conventions that this rate does not carry. Supply "
        f"the direct pair's rate rather than chaining two unrelated legs."
    )
