"""``models/fx_conversion.py`` — the bridge between two countries' numbers.

What these tests are for
------------------------
This module is three lines of arithmetic and one convention, and the convention is
the whole ballgame: a direction error produces a perfectly plausible number that
means the opposite of the truth. So the tests are built around the properties a
wrong implementation **fails**, not around the happy path a right one passes:

* the **round trip** is exact — a reciprocal placed on the wrong side passes a
  one-directional test and fails this;
* the **direction is derived from the codes**, so the same rate converts both
  ways without a flag, and a cross is refused rather than chained;
* the **refusals** are all cases that would otherwise yield a number: same
  currency, a zero/negative/nan rate, a non-finite amount, and a pair mismatch.

The worked example throughout is ``EURUSD = 1.12``, i.e. **1.12 USD per 1 EUR**,
chosen because the direction is checkable by hand: 100 EUR must become 112 USD.
"""

from __future__ import annotations

import math

import pytest

from macro_engine.models.fx_conversion import (
    FxConversionError,
    FxRate,
    convert,
)


def _eurusd(rate: float = 1.12) -> FxRate:
    return FxRate(base="EUR", quote="USD", rate=rate)


# ---------------------------------------------------------------------------
# the arithmetic, both directions, hand-checkable
# ---------------------------------------------------------------------------


def test_base_to_quote_multiplies() -> None:
    """100 EUR at 1.12 USD/EUR is 112 USD — the base leg times the rate."""
    assert convert(100.0, frm="EUR", to="USD", rate=_eurusd()) == pytest.approx(112.0)


def test_quote_to_base_divides() -> None:
    """112 USD at 1.12 USD/EUR is 100 EUR — the quote leg divided by the rate."""
    assert convert(112.0, frm="USD", to="EUR", rate=_eurusd()) == pytest.approx(100.0)


def test_the_round_trip_is_exact() -> None:
    """A reciprocal on the wrong side passes one direction and fails this."""
    rate = _eurusd(1.1234567)
    there = convert(1_000_000.0, frm="EUR", to="USD", rate=rate)
    back = convert(there, frm="USD", to="EUR", rate=rate)
    assert back == pytest.approx(1_000_000.0, rel=1e-12)


def test_a_rising_rate_weakens_the_base_currency() -> None:
    """The sign a reader must never have to guess.

    ``EURUSD`` rising means each euro buys MORE dollars, i.e. the dollar is
    weaker. So a fixed euro amount converts to a LARGER dollar amount.
    """
    weak_dollar = convert(100.0, frm="EUR", to="USD", rate=_eurusd(1.20))
    strong_dollar = convert(100.0, frm="EUR", to="USD", rate=_eurusd(1.05))
    assert weak_dollar > strong_dollar


def test_the_inverse_pair_gives_the_inverse_result() -> None:
    """The same market is expressible as EURUSD or USDEUR; both must agree.

    USDEUR = 1/1.12 means 1/1.12 USD... no: **EUR per USD**, so converting
    112 USD to EUR with USDEUR divides by 1/1.12 — the same 100 EUR. This pins
    that the two representations of one market are consistent.
    """
    direct = convert(112.0, frm="USD", to="EUR", rate=_eurusd(1.12))
    inverse = convert(112.0, frm="USD", to="EUR", rate=FxRate("USD", "EUR", 1 / 1.12))
    assert direct == pytest.approx(inverse)


# ---------------------------------------------------------------------------
# the refusals — every one of these would otherwise produce a number
# ---------------------------------------------------------------------------


def test_a_same_currency_conversion_is_refused() -> None:
    """It is a no-op; a caller routing it here expected a rate to do something."""
    with pytest.raises(FxConversionError, match=r"convert .* to itself|to itself"):
        convert(100.0, frm="EUR", to="EUR", rate=_eurusd())


def test_a_pair_mismatch_is_refused_as_a_cross() -> None:
    """EUR->JPY with an EURUSD rate is a CROSS, not a conversion."""
    with pytest.raises(FxConversionError, match="CROSS"):
        convert(100.0, frm="EUR", to="JPY", rate=_eurusd())


def test_a_unrelated_pair_is_refused() -> None:
    with pytest.raises(FxConversionError, match="CROSS"):
        convert(100.0, frm="GBP", to="USD", rate=_eurusd())


def test_a_non_finite_amount_is_refused() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(FxConversionError, match="not finite"):
            convert(bad, frm="EUR", to="USD", rate=_eurusd())


def test_a_zero_rate_is_refused_at_construction() -> None:
    with pytest.raises(FxConversionError, match="not strictly positive"):
        FxRate("EUR", "USD", 0.0)


def test_a_negative_rate_is_refused_at_construction() -> None:
    with pytest.raises(FxConversionError, match="not strictly positive"):
        FxRate("EUR", "USD", -1.2)


def test_a_nan_rate_is_refused_at_construction() -> None:
    """A nan rate passes every comparison (D-078), so it is refused where it enters."""
    with pytest.raises(FxConversionError, match="not finite"):
        FxRate("EUR", "USD", float("nan"))


def test_a_same_currency_rate_is_refused_at_construction() -> None:
    with pytest.raises(FxConversionError, match="same currency"):
        FxRate("EUR", "EUR", 1.0)


# ---------------------------------------------------------------------------
# the convention is data on the object, not a comment
# ---------------------------------------------------------------------------


def test_the_convention_reads_correctly() -> None:
    assert _eurusd().convention == "USD per 1 EUR"
    assert FxRate("USD", "JPY", 158.0).convention == "JPY per 1 USD"


def test_the_codes_are_normalised_to_upper_case() -> None:
    rate = FxRate("eur", "usd", 1.12)
    assert rate.base == "EUR"
    assert rate.quote == "USD"
    # And conversion still works with mixed-case request codes.
    assert convert(100.0, frm="eur", to="usd", rate=rate) == pytest.approx(112.0)


def test_a_rate_is_immutable() -> None:
    """Frozen, so a conversion cannot be mutated mid-flight by a caller.

    ``dataclasses.FrozenInstanceError`` is asserted specifically rather than a
    blind ``Exception``: a blind catch passes on ANY failure — including the
    attribute not existing — so it would not pin immutability at all.
    """
    import dataclasses

    rate = _eurusd()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rate.rate = 2.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# the identity that a wrong implementation violates: linearity
# ---------------------------------------------------------------------------


def test_conversion_is_linear_in_the_amount() -> None:
    """Doubling the amount doubles the result — a plausible-looking bug (an
    additive offset, a fixed spread) would break this while passing the single
    worked example above."""
    rate = _eurusd(1.12)
    one = convert(100.0, frm="EUR", to="USD", rate=rate)
    two = convert(200.0, frm="EUR", to="USD", rate=rate)
    assert two == pytest.approx(2 * one)
    assert convert(0.0, frm="EUR", to="USD", rate=rate) == pytest.approx(0.0)
    assert math.isfinite(convert(1e12, frm="EUR", to="USD", rate=rate))
