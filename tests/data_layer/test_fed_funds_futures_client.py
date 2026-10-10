"""Tests for ``fed_funds_futures_client`` — the Section 22.5 data leg.

What these tests are for
------------------------
Section 22.5 obligates Phase 5+ to replace a PROXY with a "real
Fed-funds-futures-implied probability distribution". The source for that turns
out to exist on this installation (``derivatives.futures.curve``, symbol ``ZQ``,
provider ``yfinance``), and the probe in ``tools/probe_fed_funds_futures.py``
established both the route and its **own defect**:

**Six of the sixteen expirations the route returns carry a price near 47-48
instead of 95-96**, implying a ~52% policy rate. The six rows are the same on
every call (measured across three separate calls: min 47.64, max 96.12), so this
is source corruption, not a transient artifact. A reader that trusted the route
would publish a 52% market-implied policy path — Section 21.0's "plausible-looking
wrong number", the class this project treats as SEV-1.

Each hazard the fix must handle is asserted here, with the arithmetic derived BY
HAND so the test fails if the identity or the band silently changes:

(a) **The identity is ``implied_rate = settlement_offset - price``.** Hand-derived
    below against a fixed synthetic curve (price 96.12 → 3.88%, which is the
    MEASURED front-contract value) so mutating the subtraction or the offset
    fails a test rather than a review.
(b) **An implausible row is REJECTED, never clamped.** A 47.89 price implies
    52.11%; clamping it into the band would publish a number the source never
    sent. The test proves the row is absent from ``expirations`` AND named in
    ``rejected_detail`` — the two halves of "rejected", not just one.
(c) **A corruption produces a DEGRADED curve, not an exception.** Losing six of
    sixteen rows is publishable with disclosure; the tests assert the survivors
    and the count, so "reject the whole curve" is a different (wrong) behaviour.
(d) **Finite is checked FIRST, before the band.** ``nan`` fails every comparison,
    so a band written as ``if not (lo <= r <= hi)`` would admit it by luck on one
    spelling and reject it by luck on another (D-078).
(e) **The floor is enforced.** Fewer than ``min_expirations`` survivors is a
    FAILURE: one point is what the proxy this replaces already was.
(f) **Past-dated rows are dropped and counted SEPARATELY** from rejects, because
    "already expired" and "corrupt" are different facts about a missing row.
(g) **The module never opens its own HTTP connection.** It routes through the
    project's ``OpenBBClient`` (D-087.25), asserted on the AST.

The prices in the synthetic curve are the REAL ones captured 2026-10-10, so a
change in the source's behaviour is visible as a changed expectation.
"""

from __future__ import annotations

import ast
import inspect
import math
from datetime import date
from typing import Any

import pytest

import macro_engine.data_layer.fed_funds_futures_client as client_module
from macro_engine.config import get_settings
from macro_engine.data_layer.fed_funds_futures_client import (
    FUTURES_ROUTE_ENDPOINT,
    FedFundsFuturesCurve,
    FuturesCurveError,
    FuturesExpiration,
    _contract_month_end,
    _months_between,
    _parse_expiration,
    fetch_fed_funds_futures_curve,
)
from macro_engine.data_layer.openbb_client import OpenBBFetchError

#: The real ZQ curve captured 2026-10-10, exactly as the route returned it —
#: INCLUDING the six corrupt rows (prices near 47-48). The probe printed
#: min price 47.64 / max 96.12 on each of three calls.
_REAL_ROWS_2026_10_10: list[tuple[str, float]] = [
    ("2026-10", 96.12),
    ("2026-11", 95.98),
    ("2026-12", 95.88),
    ("2027-01", 95.87),
    ("2027-02", 47.89),  # corrupt → implies 52.11%
    ("2027-03", 95.79),
    ("2027-04", 47.74),  # corrupt
    ("2027-05", 95.72),
    ("2027-06", 47.80),  # corrupt
    ("2027-07", 95.66),
    ("2027-08", 95.62),
    ("2027-09", 47.64),  # corrupt
    ("2027-10", 47.68),  # corrupt
    ("2027-11", 95.55),
    ("2027-12", 47.68),  # corrupt
    ("2028-01", 95.31),
]

#: The six rows the plausibility band must kill, and only those.
_CORRUPT_EXPIRATIONS = ("2027-02", "2027-04", "2027-06", "2027-09", "2027-10", "2027-12")


def _rows(
    prices: list[tuple[str, float]],
    *,
    retrieved_at: str = "2026-10-10T00:00:00+00:00",
) -> list[dict[str, Any]]:
    """A ``derivatives.futures.curve``-shaped record list.

    The real route returns one row per expiration with an ``expiration`` of
    ``YYYY-MM`` and a ``price`` in index points. ``raw`` rows are passed through
    untouched so a caller can plant a non-finite or non-numeric value.
    """
    return [
        {"expiration": expiration, "price": price, "retrieved_at": retrieved_at}
        for expiration, price in prices
    ]


class _StubClient:
    """An ``OpenBBClient`` stand-in returning canned records or raising."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._records = records
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def fetch_records(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._records is not None
        return self._records

    def close(self) -> None:
        self.closed = True


#: Every test reads the curve as of this date, so ``months_ahead`` is fixed and
#: hand-derivable rather than dependent on the day the suite runs.
_AS_OF = date(2026, 10, 10)


def _curve_from(
    prices: list[tuple[str, float]] | None = None,
    *,
    as_of: date = _AS_OF,
) -> FedFundsFuturesCurve:
    """Fetch against the real default row set (or a supplied one)."""
    rows = _rows(prices) if prices is not None else _rows(_REAL_ROWS_2026_10_10)
    return fetch_fed_funds_futures_curve(as_of=as_of, client=_StubClient(rows))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (a) The identity: implied_rate = settlement_offset - price, hand-derived
# ---------------------------------------------------------------------------
def test_implied_rate_is_offset_minus_price_hand_derived() -> None:
    """The contract's settlement identity, checked against hand arithmetic.

    A 30-Day Fed Funds future settles to ``100 - <the contract month's average
    effective funds rate>``, so ``implied_rate = 100 - price``. Hand values:

        price 96.12 → 100 - 96.12 = 3.88%   (the measured front contract)
        price 95.98 → 100 - 95.98 = 4.02%
        price 95.31 → 100 - 95.31 = 4.69%   (the measured far end)

    The offset is read from config, NOT assumed to be 100, so this test also
    fails if the leaf and the code disagree.
    """
    offset = get_settings().market_implied_futures.settlement_offset
    assert offset == 100.0, "the settlement offset leaf moved; re-derive these hand values"

    curve = _curve_from()
    by_expiration = {e.expiration: e for e in curve.expirations}

    assert by_expiration["2026-10"].implied_rate_pct == pytest.approx(100.0 - 96.12)
    assert by_expiration["2026-10"].implied_rate_pct == pytest.approx(3.88)
    assert by_expiration["2026-11"].implied_rate_pct == pytest.approx(4.02)
    assert by_expiration["2028-01"].implied_rate_pct == pytest.approx(4.69)

    # The trace field must equal the price it was computed from — the auditable
    # link from the published rate back to what the source sent.
    for expiration in curve.expirations:
        assert expiration.price == pytest.approx(expiration.raw_price)
        assert expiration.implied_rate_pct == pytest.approx(offset - expiration.price)


def test_the_identity_holds_for_every_surviving_row_not_just_the_front() -> None:
    """A front-only check would pass a mutation that broke later rows."""
    offset = get_settings().market_implied_futures.settlement_offset
    curve = _curve_from()
    assert len(curve.expirations) == 10  # 16 returned - 6 corrupt
    for expiration in curve.expirations:
        assert expiration.implied_rate_pct == pytest.approx(offset - expiration.raw_price)


# ---------------------------------------------------------------------------
# (b) The plausibility guard: REJECT, never CLAMP
# ---------------------------------------------------------------------------
def test_the_six_corrupt_rows_are_rejected_never_clamped() -> None:
    """The headline hazard: a ~52% implied policy rate must not be published.

    A 47.89 price implies ``100 - 47.89 = 52.11%``, impossible against a ~4%
    target range. The row must be **absent** from the accepted set (rejected,
    not clamped into the band, which would publish a value the source never
    sent) and **named** in ``rejected_detail`` (so the disclosure is
    actionable rather than a bare count).
    """
    curve = _curve_from()
    accepted = {e.expiration for e in curve.expirations}

    for corrupt in _CORRUPT_EXPIRATIONS:
        assert corrupt not in accepted, f"{corrupt} was published despite implying ~52%"

    assert curve.rows_rejected == 6
    assert curve.rows_returned == 16
    detail = " ".join(curve.rejected_detail)
    for corrupt in _CORRUPT_EXPIRATIONS:
        assert corrupt in detail, f"{corrupt} was rejected silently, without being named"

    # The detail must name the IMPLIED rate, not just the price: a reader needs
    # to see why it was implausible, and 52 is the number that says so.
    assert "52.11" in detail or "52.26" in detail or "52.32" in detail or "52.36" in detail


def test_no_surviving_row_lies_outside_the_configured_band() -> None:
    """The band, read from config, must hold over the whole accepted set.

    Also the MUTANT CATCHER: deleting the band check republishes the six ~52%
    rows, every one of which fails this assertion.
    """
    settings = get_settings().market_implied_futures
    low, high = settings.plausible_rate_min, settings.plausible_rate_max
    curve = _curve_from()
    for expiration in curve.expirations:
        assert low <= expiration.implied_rate_pct <= high, (
            f"{expiration.expiration} implies {expiration.implied_rate_pct:.2f}%, "
            f"outside the configured band [{low}, {high}]"
        )


def test_a_clamped_row_would_be_detectable_by_its_price_round_trip() -> None:
    """Kills the "clamp into the band" alternative explicitly.

    If the loader clamped, the clamped row's implied rate would be the band
    edge while its price still said 47.89 — the round trip would break. Since
    the identity is asserted for every survivor (in the identity test above),
    no survivor can be a clamped corrupt row. This test states the invariant
    directly so the intent is not merely implied.
    """
    curve = _curve_from()
    for expiration in curve.expirations:
        # A clamped-corrupt row would be at the band edge with a price near 48.
        assert not (expiration.raw_price < 90.0 and expiration.implied_rate_pct > 0.0), (
            "a sub-90 price survived: it was clamped rather than rejected"
        )


def test_the_near_and_far_rates_match_the_hand_computed_survivors() -> None:
    """``near_rate_pct`` / ``far_rate_pct`` are the front and back of the PATH.

    Hand-derived from the surviving rows: the front survivor is 2026-10 at
    3.88% and the far is 2028-01 at 4.69%.
    """
    curve = _curve_from()
    assert curve.near_rate_pct == pytest.approx(3.88)
    assert curve.far_rate_pct == pytest.approx(4.69)


def test_the_path_slope_is_far_minus_near_in_basis_points() -> None:
    """The quantity the proxy structurally could not produce.

    Hand arithmetic: (4.69 - 3.88) * 100 = 81bp, rounded to +80/+81 by
    construction. Measured +80bp; the exact value is 81.0 because the hand
    values above round. Derived from the raw prices:
    ( (100-95.31) - (100-96.12) ) * 100 = (4.69 - 3.88)*100 = 81.0bp.
    """
    curve = _curve_from()
    expected = (curve.far_rate_pct - curve.near_rate_pct) * 100.0
    assert curve.path_slope_bp == pytest.approx(expected)
    assert curve.path_slope_bp == pytest.approx(81.0)
    # Positive = the market prices HIKES, which a single yield cannot express.
    assert curve.path_slope_bp > 0


# ---------------------------------------------------------------------------
# (d) Finiteness is checked FIRST (D-078)
# ---------------------------------------------------------------------------
def test_a_non_finite_price_is_rejected_and_named() -> None:
    """``nan``/``inf`` must be refused explicitly, before the band comparison.

    A band written as ``if not (lo <= r <= hi)`` admits ``nan`` on one spelling
    and refuses it on another; the module checks finiteness first so the outcome
    does not depend on the comparison's good fortune.

    The assertion pins WHICH guard fired, not merely that the row vanished.
    There are two finiteness guards — one on the raw price, one on the implied
    rate — and with a finite offset the second would catch everything the first
    does (``100 - nan`` is ``nan``). Asserting only the count therefore lets the
    first guard be deleted without a failure, which is a gap this test closes:
    the message must say the **PRICE** was non-finite, because that is the fact
    the first guard establishes and the second cannot.
    """
    rows = _rows([("2026-10", 96.12), ("2026-11", float("nan"))])
    rows.append({"expiration": "2026-12", "price": float("inf")})
    rows.append({"expiration": "2027-01", "price": 95.87})
    rows.append({"expiration": "2027-03", "price": 95.79})
    curve = fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient(rows))  # type: ignore[arg-type]

    assert curve.rows_rejected == 2
    assert [e.expiration for e in curve.expirations] == ["2026-10", "2027-01", "2027-03"]
    detail = " ".join(curve.rejected_detail)
    assert "non-finite price" in detail, (
        "the row must be rejected on the PRICE guard, not only on the implied-rate "
        "guard that would catch the same row by accident"
    )
    assert "non-finite implied rate" not in detail, (
        "a non-finite raw price reached the subtraction; the first guard is not "
        "firing and the rejection now depends on the second"
    )
    assert "2026-11" in detail and "2026-12" in detail


def test_a_non_numeric_price_is_rejected_and_named() -> None:
    rows = _rows([("2026-10", 96.12)])
    rows.append({"expiration": "2026-11", "price": "n/a"})
    rows.append({"expiration": "2026-12", "price": None})
    rows.append({"expiration": "2027-01", "price": 95.87})
    rows.append({"expiration": "2027-03", "price": 95.79})
    curve = fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient(rows))  # type: ignore[arg-type]

    assert curve.rows_rejected == 2
    assert curve.rows_returned == 5
    detail = " ".join(curve.rejected_detail)
    assert "non-numeric" in detail


def test_a_nan_never_reaches_the_accepted_set() -> None:
    """Belt and braces: no accepted rate is ever non-finite."""
    rows = _rows([("2026-10", 96.12), ("2026-11", float("nan"))])
    rows.append({"expiration": "2026-12", "price": 95.88})
    rows.append({"expiration": "2027-01", "price": 95.87})
    curve = fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient(rows))  # type: ignore[arg-type]
    for expiration in curve.expirations:
        assert math.isfinite(expiration.implied_rate_pct)
        assert math.isfinite(expiration.price)


# ---------------------------------------------------------------------------
# (e) The floor is enforced
# ---------------------------------------------------------------------------
def test_fewer_survivors_than_the_floor_is_a_failure_not_a_short_path() -> None:
    """One point is what the proxy this replaces already was; refusing is honest.

    Three rows: two corrupt, one clean → one survivor, below the configured
    floor (3). The module raises rather than publishing a point as a path.
    """
    settings = get_settings().market_implied_futures
    assert settings.min_expirations == 3
    rows = _rows([("2026-10", 96.12), ("2026-11", 47.89), ("2026-12", 47.74)])
    with pytest.raises(FuturesCurveError, match=r"below the configured floor"):
        fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient(rows))  # type: ignore[arg-type]


def test_zero_survivors_names_what_was_rejected() -> None:
    """An all-corrupt curve must say WHY, not just that it failed."""
    rows = _rows([("2026-10", 47.89), ("2026-11", 47.74), ("2026-12", 47.80)])
    with pytest.raises(FuturesCurveError, match=r"no plausible expiration survived"):
        fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient(rows))  # type: ignore[arg-type]


def test_exactly_the_floor_survivors_is_accepted() -> None:
    """The boundary is INCLUSIVE: ``min_expirations`` survivors must pass.

    A mutation of ``<`` to ``<=`` would reject exactly this curve, so the test
    pins the boundary from the passing side.
    """
    rows = _rows([("2026-10", 96.12), ("2026-11", 95.98), ("2026-12", 95.88)])
    curve = fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient(rows))  # type: ignore[arg-type]
    assert len(curve.expirations) == 3
    assert curve.has_path is True


# ---------------------------------------------------------------------------
# (f) Past-dated rows are dropped and counted SEPARATELY
# ---------------------------------------------------------------------------
def test_a_past_dated_expiration_is_dropped_and_counted_separately() -> None:
    """'Already expired' and 'corrupt' are different facts about a missing row.

    As of 2026-10-15, a 2026-09 contract's month has ENDED, so it carries no
    forward information — dropped, counted in ``rows_dropped_past``, and NOT
    conflated with ``rows_rejected``.
    """
    rows = _rows(
        [
            ("2026-08", 96.20),  # past: month ended before 2026-10-15
            ("2026-09", 96.15),  # past
            ("2026-10", 96.12),  # CURRENT month, still trading → kept
            ("2026-11", 95.98),
            ("2026-12", 95.88),
            ("2027-01", 95.87),
        ]
    )
    curve = fetch_fed_funds_futures_curve(as_of=date(2026, 10, 15), client=_StubClient(rows))  # type: ignore[arg-type]

    assert curve.rows_dropped_past == 2
    assert curve.rows_rejected == 0
    assert curve.rows_returned == 6
    assert curve.expirations[0].expiration == "2026-10", (
        "the current month's contract must be KEPT — its month has not ended"
    )


def test_the_current_month_contract_survives_mid_month() -> None:
    """The month-END comparison must keep the contract that is still trading."""
    rows = _rows([("2026-10", 96.12), ("2026-11", 95.98), ("2026-12", 95.88)])
    curve = fetch_fed_funds_futures_curve(as_of=date(2026, 10, 31), client=_StubClient(rows))  # type: ignore[arg-type]
    assert "2026-10" in {e.expiration for e in curve.expirations}


# ---------------------------------------------------------------------------
# Empty and transport-failure paths
# ---------------------------------------------------------------------------
def test_an_empty_curve_is_a_failed_read_never_a_flat_path() -> None:
    with pytest.raises(FuturesCurveError, match=r"empty curve is a failed read"):
        fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient([]))  # type: ignore[arg-type]


def test_a_transport_failure_becomes_a_futures_curve_error() -> None:
    """The message must say WHICH happened: transport vs unusable curve."""
    stub = _StubClient(error=OpenBBFetchError("boom"))
    with pytest.raises(FuturesCurveError, match=r"fetch failed"):
        fetch_fed_funds_futures_curve(as_of=_AS_OF, client=stub)  # type: ignore[arg-type]


def test_the_route_and_symbol_are_the_configured_ones() -> None:
    """The call must use the config symbol/provider and the canonical route."""
    stub = _StubClient(_rows(_REAL_ROWS_2026_10_10))
    fetch_fed_funds_futures_curve(as_of=_AS_OF, client=stub)  # type: ignore[arg-type]
    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert call["endpoint"] == FUTURES_ROUTE_ENDPOINT
    assert call["params"] == {"symbol": get_settings().market_implied_futures.symbol}
    assert call["provider"] == get_settings().market_implied_futures.provider


def test_the_caller_owned_client_is_not_closed() -> None:
    """An injected client belongs to the caller; the loader must not close it."""
    stub = _StubClient(_rows(_REAL_ROWS_2026_10_10))
    fetch_fed_funds_futures_curve(as_of=_AS_OF, client=stub)  # type: ignore[arg-type]
    assert stub.closed is False


# ---------------------------------------------------------------------------
# The curve's own refusal contracts
# ---------------------------------------------------------------------------
def _empty_curve() -> FedFundsFuturesCurve:
    return FedFundsFuturesCurve(
        symbol="ZQ",
        provider="yfinance",
        settlement_offset=100.0,
        as_of="2026-10-10",
        expirations=(),
        rows_returned=0,
        rows_rejected=0,
        rows_dropped_past=0,
        rejected_detail=(),
        source_retrieved_at="2026-10-10T00:00:00+00:00",
    )


def test_near_rate_on_an_empty_curve_raises_rather_than_returning_zero() -> None:
    with pytest.raises(FuturesCurveError, match=r"no near rate"):
        _ = _empty_curve().near_rate_pct


def test_slope_needs_two_points_and_says_so() -> None:
    one = FedFundsFuturesCurve(
        symbol="ZQ",
        provider="yfinance",
        settlement_offset=100.0,
        as_of="2026-10-10",
        expirations=(FuturesExpiration("2026-10", 96.12, 3.88, 0, 96.12),),
        rows_returned=1,
        rows_rejected=0,
        rows_dropped_past=0,
        rejected_detail=(),
        source_retrieved_at="2026-10-10T00:00:00+00:00",
    )
    assert one.has_path is False
    with pytest.raises(FuturesCurveError, match=r"slope needs at least two"):
        _ = one.path_slope_bp


# ---------------------------------------------------------------------------
# The pure helpers, hand-derived
# ---------------------------------------------------------------------------
def test_months_between_is_calendar_month_arithmetic() -> None:
    """Hand values, both directions.

    (2028-2026)*12 + (1-10)  = 24 - 9 = 15   → Jan 2028 is 15 months out
    (2027-2026)*12 + (2-10)  = 12 - 8 =  4   → Feb 2027 is  4 months out
    (2026-2026)*12 + (10-10) =  0           → the same month is 0
    (2026-2026)*12 + (9-10)  = -1           → Sep 2026 is 1 month PAST
    """
    assert _months_between(date(2026, 10, 10), date(2028, 1, 1)) == 15
    assert _months_between(date(2026, 10, 10), date(2027, 2, 1)) == 4
    assert _months_between(date(2026, 10, 10), date(2026, 9, 1)) == -1
    assert _months_between(date(2026, 10, 10), date(2026, 10, 1)) == 0
    assert _months_between(date(2026, 10, 10), date(2026, 11, 1)) == 1


def test_contract_month_end_handles_december_and_leap_february() -> None:
    assert _contract_month_end(date(2026, 12, 1)) == date(2026, 12, 31)
    assert _contract_month_end(date(2026, 1, 1)) == date(2026, 1, 31)
    assert _contract_month_end(date(2028, 2, 1)) == date(2028, 2, 29)  # leap year
    assert _contract_month_end(date(2026, 2, 1)) == date(2026, 2, 28)


def test_parse_expiration_rejects_malformed_input_without_raising() -> None:
    assert _parse_expiration("2026-10") == date(2026, 10, 1)
    assert _parse_expiration("2026-10-15") == date(2026, 10, 1)  # full date tolerated
    for bad in ("", "  ", "2026", "2026-13", "not-a-month", None):
        assert _parse_expiration(bad) is None


def test_a_malformed_expiration_is_counted_not_fatal() -> None:
    """One bad row must not abort an otherwise-usable curve."""
    rows = _rows([("2026-10", 96.12), ("2026-11", 95.98), ("2026-12", 95.88), ("nonsense", 95.8)])
    curve = fetch_fed_funds_futures_curve(as_of=_AS_OF, client=_StubClient(rows))  # type: ignore[arg-type]
    assert curve.rows_rejected == 1
    assert "unparseable expiration" in " ".join(curve.rejected_detail)
    assert len(curve.expirations) == 3


# ---------------------------------------------------------------------------
# (g) The route: no private HTTP, no second client
# ---------------------------------------------------------------------------
def test_the_module_never_imports_httpx_or_requests_directly() -> None:
    """It must route through ``OpenBBClient``, not open its own connection.

    Asserted on the AST so a future "helpful" direct call fails a test rather
    than review (D-087.25's lesson).
    """
    tree = ast.parse(inspect.getsource(client_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "httpx" not in imported
    assert "requests" not in imported
    assert "aiohttp" not in imported


def test_the_module_never_reads_the_raw_http_handle() -> None:
    source = inspect.getsource(client_module)
    assert "_http" not in source


def test_the_route_constant_matches_the_probed_route() -> None:
    """The route is a CONSTANT (transport contract), not a config leaf."""
    assert FUTURES_ROUTE_ENDPOINT == "derivatives.futures.curve"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
