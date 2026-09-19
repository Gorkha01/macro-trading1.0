"""Tests for ``ProductionUniverse`` -- the production execution boundary (Section 22.12).

**These are the class's first tests.** D-058's probe found ``ProductionUniverse``
had zero tests and zero callers (P8) while Section 22.12 makes it the boundary
every published instrument must pass: ``select_instrument`` refuses to emit a
name the matcher rejects, and ``TradeIdea`` refuses a non-sentinel instrument
that is out of universe. A boundary with no tests is a claim, not a guarantee.

The tests live in ``tests/thesis_layer/`` rather than beside the router because
the universe is a *thesis-layer* concept -- the vocabulary belongs above the
models layer, which is why the router receives it as an argument instead of
importing it. Three behaviour changes were made by D-058 and each is pinned here
rather than only through the router:

1. Currency pairs are matched as a unit (``"EURUSD spot"`` and ``"EUR/USD spot"``
   are both FX), and a six-letter word that merely *begins* with a currency code
   is **not** a pair.
2. The curve-shape vocabulary (``steepener``/``flattener``/``duration-weighted``/
   ``curve``) is admitted as rates, because the specification's own curve
   instrument named none of the words the universe recognised.
3. The ``NONE`` sentinel is matched case-insensitively, so ``"none"`` and
   ``"NONE"`` mean the same thing.

Which **category** a string belongs to is asserted alongside whether it is
permitted, because the category is what lets a rejection explain itself.
"""

from __future__ import annotations

import pytest

from macro_engine.thesis_layer.schemas import (
    NO_PRODUCTION_INSTRUMENT,
    ProductionUniverse,
)

UNIVERSE = ProductionUniverse()


# ---------------------------------------------------------------------------
# Rates / FX / equity: the three production categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instrument",
    [
        "UST 2yr note futures",
        "UST cash (2yr, 5yr, 10yr, 30yr)",
        "SOFR futures",
        "Fed funds futures",
        "TIPS cash and breakevens",
    ],
)
def test_rates_instruments_are_admitted(instrument: str) -> None:
    """The declared rates list is permitted by construction."""
    assert UNIVERSE.category_for(instrument) == "rates"
    assert UNIVERSE.permits(instrument)


@pytest.mark.parametrize(
    "instrument",
    [
        "G10 FX spot",
        "G10 FX forwards",
        "EURUSD spot",
        "EUR/USD spot",
        "usdjpy forward",
    ],
)
def test_fx_instruments_are_admitted(instrument: str) -> None:
    """FX is one of the three production categories, so real pairs must pass.

    ``"EURUSD spot"`` was **rejected** by the shipped universe (probe P9): the
    keyword ``"eur"`` does not match the token ``"eurusd"`` under a whole-token
    comparison. A production category that rejects its own instruments is the
    failure direction this whole increment exists to close.
    """
    assert UNIVERSE.category_for(instrument) == "fx"
    assert UNIVERSE.permits(instrument)


@pytest.mark.parametrize("instrument", ["Broad equity indices (ES, NQ, RTY)", "ES futures"])
def test_equity_instruments_are_admitted(instrument: str) -> None:
    assert UNIVERSE.category_for(instrument) == "equity"
    assert UNIVERSE.permits(instrument)


@pytest.mark.parametrize(
    "instrument",
    [
        "US HY credit index",
        "CDX IG 5yr",
        "EM sovereign bond",
        "Gold futures",
        "WTI crude futures",
        "Copper futures",
    ],
)
def test_out_of_universe_instruments_are_rejected(instrument: str) -> None:
    """Credit, EM and commodities are modelled but never executable (§22.12).

    Each of these is a real instrument the *analytical* universe covers and the
    production universe does not, which is the distinction Section 22.12 exists
    to draw.
    """
    assert UNIVERSE.category_for(instrument) is None
    assert not UNIVERSE.permits(instrument)


def test_excluded_vocabulary_is_checked_before_the_category_keywords() -> None:
    """A name matching BOTH an exclusion and a category must be rejected.

    ``"commodity index futures"`` is the case that pins the *ordering*: it
    contains the equity keyword ``"index futures"`` and the exclusion keyword
    ``"commodity"``, so whichever check runs first decides the verdict. If the
    category keywords ran first, a commodity index future would be admitted as a
    broad equity index — a false permit, in the permissive direction this whole
    function guards against.

    This replaces an earlier version of this test that used ``"US HY credit
    index"`` and claimed the equity keyword would otherwise win: it does not,
    because the equity keyword is the *phrase* ``"equity index"`` and that
    string contains only ``"credit index"``. The docstring was a claim the sweep
    falsified (``M8.5`` survived), so the fixture was replaced with one where the
    claim is actually true.
    """
    assert "index futures" in "commodity index futures"
    assert UNIVERSE.category_for("commodity index futures") is None
    assert not UNIVERSE.permits("commodity index futures")


def test_permits_rejects_the_sentinel_only_when_category_for_agrees() -> None:
    """``permits`` and ``category_for`` must not disagree about the sentinel.

    ``permits`` is the method callers actually use, and it has its own
    case-insensitive comparison in addition to delegating to
    ``category_for``. The two are mutated independently (``M8.3`` / ``M8.4`` in
    the D-058 sweep), so each needs its own assertion: if only the delegation
    were tested, a case-sensitive *first* check would be invisible because the
    delegation would rescue it.
    """
    # Directly exercise permits with the case variants, so its own comparison is
    # load-bearing rather than shadowed by the delegation.
    for spelling in ("NONE", "none", "None", " none "):
        assert UNIVERSE.permits(spelling), spelling
        assert UNIVERSE.category_for(spelling) == "none", spelling


def test_a_six_letter_word_beginning_with_a_currency_code_is_not_a_pair() -> None:
    """``"europe equity"`` must NOT be admitted as FX.

    The currency-pair match requires **both** halves of a six-character token to
    be G10 codes. A bare three-letter prefix test admits ``europe`` (``eur`` +
    ``ope``) — a false permit in the permissive direction, which is this
    function's whole failure mode. Caught during D-058 development and pinned
    here so the loose form cannot come back.
    """
    assert UNIVERSE.category_for("europe equity") != "fx"


def test_curve_shape_vocabulary_is_admitted_as_rates() -> None:
    """Section 22.3.1's own curve instruments must pass the universe matcher.

    Probe P1/P2: ``steepener``, ``flattener``, ``duration-weighted`` and
    ``curve`` appeared in **no** keyword set, so the specification's curve
    instrument failed the check it was written to satisfy.
    """
    for instrument in (
        "Duration-weighted 2y/10y UST steepener",
        "Duration-weighted 5y/30y UST flattener",
        "2s10s curve steepener",
        "3-leg butterfly",
    ):
        assert UNIVERSE.category_for(instrument) == "rates", instrument


@pytest.mark.parametrize("sentinel", ["NONE", "none", " None ", "NoNe"])
def test_the_sentinel_is_matched_case_insensitively(sentinel: str) -> None:
    """``"NONE"`` and ``"none"`` must both be permitted.

    The shipped comparison was exact, so ``"none"`` was treated as an
    unrecognised instrument string — a one-character difference deciding whether
    the system reported "no trade" or "out of universe" (probe P10).
    """
    assert UNIVERSE.permits(sentinel)
    assert UNIVERSE.category_for(sentinel) == "none"


def test_the_sentinel_constant_matches_the_router_expectation() -> None:
    """The universe's sentinel and the router's analytical sentinel are distinct.

    Two modules name "no production instrument" in two different registers, and
    they must not be confused: ``NO_PRODUCTION_INSTRUMENT`` ("NONE") is what
    ``TradeIdea`` writes when a thesis has no expression at all, while
    ``ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT`` is the router's statement that a
    *specific thesis family* can never be a trade. If the router ever returned
    the bare ``"NONE"``, ``TradeIdea`` would accept it as a no-trade rather than
    reporting an analytical-only thesis — a silent downgrade of the answer.
    """
    from macro_engine.models.instrument_selection import (
        ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    )

    assert NO_PRODUCTION_INSTRUMENT == "NONE"
    assert ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT != NO_PRODUCTION_INSTRUMENT
    # The bare sentinel is permitted (it is a valid answer); the analytical-only
    # string is not an instrument at all and must not be admitted as one.
    assert UNIVERSE.permits(NO_PRODUCTION_INSTRUMENT)
    assert not UNIVERSE.permits(ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT)


def test_an_empty_instrument_is_not_permitted() -> None:
    """The empty string is not an instrument and not the sentinel."""
    assert not UNIVERSE.permits("")
    assert not UNIVERSE.permits("   ")
    assert UNIVERSE.category_for("") is None
