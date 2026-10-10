"""``data_layer/fx_futures_client.py`` — the FX-futures layer (Section 22.3).

What these tests are for
------------------------
``cip_check`` wants an OBSERVED FX forward and this installation has none:
re-measured 2026-10-10 across all 32 installed OpenBB providers the whole FX
surface is four routes and none is a forward/swap/basis. What IS reachable is
the CME FX futures complex via ``derivatives.futures.historical``.

**This module publishes a FUTURE and never a forward**, and most of these tests
exist to pin that distinction, because the failure mode is severe: a rolling
front-month future fed to ``cip_check`` as ``forward`` would produce a
plausible-looking wrong CIP deviation (the SEV-1 class, Section 21.0).

The tests assert, in the order the module's own docs raise them:

(a) **The frame shape is the CLIENT's, not the route's.** ``fetch_series``
    normalises every route — an OHLC one included — to the tidy 5-column frame,
    so ``value`` already holds the close. Measured live.
(b) **The route requires the CME ROOT, not the pair code.** Measured:
    ``EURUSD=F`` -> HTTP 204, ``6E=F`` -> HTTP 200. So the request must be built
    from the root.
(c) **A cross is REFUSED, not substituted.** A pair with neither leg USD
    (``EURGBP``) has no CME future; returning some USD future's series under its
    name is the silent-wrong-number defect. Measured: an earlier draft DID
    return the ``6E=F`` series for ``EURGBP``.
(d) **The ``USD/X`` pairs are the INVERSE of the future**, and ``pair_close``
    inverts so a consumer reads the pair's own convention. Verified: ``6J`` at
    0.006325 is USD-per-JPY, i.e. ``USDJPY`` ~ 158.1.
(e) **``is_forward`` is always False** and there is no ``forward`` accessor.
(f) **Corrupt rows are dropped, never repaired.**
(g) **The large-move detector reports what it measures** — a large move, NOT a
    roll (measured: the flagged days are real volatility, not a roll schedule).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import pytest

from macro_engine.data_layer.fx_futures_client import (
    FX_FUTURES_ROUTE_ENDPOINT,
    FXFuturesError,
    detect_large_moves,
    fetch_fx_futures,
)


def _tidy_frame(rows: list[tuple[object, object]]) -> pd.DataFrame:
    """The REAL shape ``fetch_series`` returns: tidy, 5 columns, RangeIndex.

    Measured live 2026-10-10 for ``derivatives.futures.historical`` / ``6E=F``:
    the client normalises the route's OHLC to this frame, so ``value`` holds the
    close. It is explicitly NOT an OHLC-indexed frame.

    The value type is ``object``, not ``float``: the corruption tests feed
    deliberately non-numeric values (a string, ``None``) to prove the drop
    guards fire, and a narrower annotation would only be silenced at the call
    site instead.
    """
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "value": [r[1] for r in rows],
            "series_id": "fx_futures_eurusd",
            "source": "openbb:package",
            "retrieved_at": "2026-10-10T00:00:00+00:00",
        }
    )


class _StubClient:
    """A client that returns a prepared frame, so no network is touched.

    Its ``fetch_series`` mirrors the real signature exactly (keyword-only, same
    parameter names) so it satisfies the production client structurally, and the
    test records the params so the ROOT (not the pair code) can be asserted.
    """

    def __init__(self, frame: pd.DataFrame | None = None, *, boom: bool = False) -> None:
        self._frame = frame
        self._boom = boom
        self.closed = False
        self.calls: list[dict[str, object]] = []

    def fetch_series(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        series_label: str,
    ) -> pd.DataFrame:
        from macro_engine.data_layer.openbb_client import OpenBBFetchError

        self.calls.append(
            {
                "provider": provider,
                "endpoint": endpoint,
                "params": params,
                "series_label": series_label,
            }
        )
        if self._boom:
            raise OpenBBFetchError("transport down")
        assert self._frame is not None
        return self._frame

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# (a) the tidy shape parses; the close survives as `value`
# ---------------------------------------------------------------------------


def test_the_tidy_frame_shape_parses_into_a_sorted_series() -> None:
    """The client's normalised shape is the contract, and it parses."""
    frame = _tidy_frame(
        [
            ("2026-10-09", 1.12055),
            ("2026-10-07", 1.1241),
            ("2026-10-08", 1.12125),
        ]
    )
    reading = fetch_fx_futures("EURUSD", client=_StubClient(frame))  # type: ignore[arg-type]
    assert reading is not None
    assert reading.observations == 3
    # Sorted, so `latest_*` is genuinely the latest regardless of row order.
    assert reading.first_date == date(2026, 10, 7)
    assert reading.latest_date == date(2026, 10, 9)
    assert reading.latest_close == pytest.approx(1.12055)


# ---------------------------------------------------------------------------
# (b) the route needs the CME ROOT, not the pair code
# ---------------------------------------------------------------------------


def test_the_request_uses_the_cme_root_not_the_pair_code() -> None:
    """MEASURED: ``EURUSD=F`` -> HTTP 204; ``6E=F`` -> HTTP 200.

    The route rejects the pair code, so the assembled ``symbol`` must be the
    root. This is a real mover: reverting to ``f"{pair}=F"`` makes every fetch a
    204 and the whole layer dark.
    """
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12), ("2026-10-08", 1.11)]))
    fetch_fx_futures("EURUSD", client=stub)  # type: ignore[arg-type]
    assert stub.calls, "the client must have been called"
    sent = stub.calls[0]["params"]
    assert isinstance(sent, dict)
    assert sent["symbol"] == "6E=F", f"expected the CME root, got {sent['symbol']!r}"
    assert stub.calls[0]["endpoint"] == FX_FUTURES_ROUTE_ENDPOINT


def test_an_unmapped_pair_returns_none_without_a_fetch() -> None:
    """A pair whose foreign currency has no root is UNREGISTERED, not broken."""
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12)]))
    # SEK is not in the spot catalogue at all -> None before any fetch.
    assert fetch_fx_futures("EURSEK", client=stub) is None  # type: ignore[arg-type]
    assert stub.calls == []


# ---------------------------------------------------------------------------
# (c) a CROSS is refused, never substituted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cross", ["EURGBP", "EURJPY", "GBPJPY"])
def test_a_cross_returns_none_and_never_substitutes(cross: str) -> None:
    """No CME future exists for a non-USD cross; returning one is a wrong answer.

    MEASURED: an earlier draft returned the ``6E=F`` (EURUSD) series for
    ``EURGBP`` — identical closes under a different pair's name. The refusal is
    the fix, and this test is its proof.

    **The stub frame is a decoy, not data.** If the refusal were removed the
    function would resolve the cross's BASE to that base's root and reach the
    transport, so the test asserts the transport is never called. A test that
    only checked ``is None`` on a stub that always returns a frame would pass
    under the substitution defect — this one cannot.
    """
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12), ("2026-10-08", 1.11)]))
    assert fetch_fx_futures(cross, client=stub) is None  # type: ignore[arg-type]
    assert stub.calls == [], "a cross must not reach the transport at all"


def test_a_pair_whose_foreign_currency_has_no_root_returns_none() -> None:
    """A catalogue pair with no mapped CME root is UNREGISTERED, not broken.

    The two refusal sites are distinct: ``_resolve_pair`` (the pair is not in
    ``FX_PAIRS``) and ``_resolve_futures`` (the pair IS catalogued but its
    foreign currency has no root). Only the first is exercised by
    ``test_an_unmapped_pair_returns_none_without_a_fetch``. This test pins the
    SECOND, by removing a currency from the root map and asserting the function
    still returns ``None`` AND never reaches the transport — a mutant that
    substitutes the currency code for the missing root would send ``EUR=F`` and
    the stub would answer, so the assertion on ``calls`` is what kills it.
    """
    from macro_engine.config import get_settings

    settings = get_settings().fx_futures
    # `cme_roots` builds a FRESH dict each call, so popping from it would not
    # hide anything — the mutation must land on the underlying value object.
    original = settings.cme_roots_value
    assert "GBP" in settings.cme_roots, "this test needs a catalogue currency"
    reduced = {k: v for k, v in original.value.items() if k != "GBP"}
    settings.cme_roots_value = original.model_copy(update={"value": reduced})
    try:
        stub = _StubClient(_tidy_frame([("2026-10-09", 1.27), ("2026-10-08", 1.26)]))
        assert fetch_fx_futures("GBPUSD", client=stub) is None  # type: ignore[arg-type]
        assert stub.calls == [], "an unmapped root must not reach the transport"
    finally:
        settings.cme_roots_value = original


# ---------------------------------------------------------------------------
# (d) USD/X pairs are the INVERSE of the future
# ---------------------------------------------------------------------------


def test_a_usd_base_pair_reports_the_inverse_and_converts() -> None:
    """``6J`` quotes USD-per-JPY; ``USDJPY`` is JPY-per-USD, so it INVERTS.

    MEASURED: ``6J=F`` last = 0.006325 = USD per JPY, i.e. ``USDJPY`` ~ 158.1.
    ``pair_close`` must therefore return 1/0.006325 and ``is_inverse`` must be
    True, so a consumer converts knowingly rather than by luck.
    """
    stub = _StubClient(_tidy_frame([("2026-10-09", 0.006325), ("2026-10-08", 0.00633)]))
    reading = fetch_fx_futures("USDJPY", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.is_inverse is True
    assert reading.root == "6J"
    assert reading.latest_close == pytest.approx(0.006325)
    # 1 / 0.006325 = 158.10...
    assert reading.pair_close == pytest.approx(158.1027667, abs=1e-4)
    assert "INVERSE" in reading.convention


def test_a_usd_quote_pair_is_the_same_direction() -> None:
    """``6E`` quotes USD-per-EUR, the SAME direction as ``EURUSD``."""
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12055), ("2026-10-08", 1.12125)]))
    reading = fetch_fx_futures("EURUSD", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.is_inverse is False
    assert reading.root == "6E"
    # Same direction, so pair_close == latest_close (no inversion).
    assert reading.pair_close == pytest.approx(1.12055)
    assert "same direction" in reading.convention


def test_the_convention_names_the_foreign_currency_for_both_shapes() -> None:
    """``convention`` must name the currency the future actually quotes.

    The future always quotes USD-per-FOREIGN, and which leg is foreign flips
    between ``X/USD`` (foreign = base) and ``USD/X`` (foreign = quote). The line
    exists so a consumer need not reconstruct it, so naming the WRONG leg is a
    mis-description even though every other field stays correct — which is why
    both shapes are pinned here. A mutant that swaps the two legs still prints
    "INVERSE" for USDJPY (the direction is computed separately), so only
    asserting the CURRENCY catches it.
    """
    eurusd = fetch_fx_futures(
        "EURUSD",
        client=_StubClient(_tidy_frame([("2026-10-09", 1.12055)])),  # type: ignore[arg-type]
    )
    assert eurusd is not None
    assert "USD per 1 EUR" in eurusd.convention

    usdjpy = fetch_fx_futures(
        "USDJPY",
        client=_StubClient(_tidy_frame([("2026-10-09", 0.006325)])),  # type: ignore[arg-type]
    )
    assert usdjpy is not None
    # The future quotes USD-per-JPY, so the foreign leg is JPY, NOT USD.
    assert "USD per 1 JPY" in usdjpy.convention
    assert "USD per 1 USD" not in usdjpy.convention


# ---------------------------------------------------------------------------
# (e) it is NEVER a forward
# ---------------------------------------------------------------------------


def test_the_reading_is_never_a_forward_and_says_so() -> None:
    """The central invariant: a rolling front-month future is not a forward.

    ``is_forward`` is always False, there is NO ``forward`` field or accessor,
    and the warnings name the two hazards a consumer must not walk into.
    """
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12), ("2026-10-08", 1.11)]))
    reading = fetch_fx_futures("EURUSD", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.is_forward is False
    assert reading.is_rolling is True
    # There must be no `forward` attribute at all — a caller cannot reach for one.
    assert not hasattr(reading, "forward")
    blob = " ".join(reading.warnings)
    assert "NOT a forward" in blob
    assert "cip_check" in blob


# ---------------------------------------------------------------------------
# (f) corrupt rows are dropped, never repaired
# ---------------------------------------------------------------------------


def test_non_finite_and_non_positive_rows_are_dropped_and_counted() -> None:
    """A nan passes every comparison (D-078); a zero FX price is impossible.

    Both are DROPPED and COUNTED, never repaired to a number: a shorter series
    is recoverable, an invented value is a wrong answer.
    """
    frame = _tidy_frame(
        [
            ("2026-10-09", 1.12055),
            ("2026-10-08", float("nan")),
            ("2026-10-07", 0.0),
            ("2026-10-06", -1.0),
            ("2026-10-05", float("inf")),
            ("2026-10-04", 1.1150),
        ]
    )
    reading = fetch_fx_futures("EURUSD", client=_StubClient(frame))  # type: ignore[arg-type]
    assert reading is not None
    assert reading.observations == 2, "only the two finite positive rows survive"
    assert reading.rows_dropped == 4
    assert reading.latest_close == pytest.approx(1.12055)


def test_an_unconvertible_value_and_an_unparseable_date_are_each_dropped_and_counted() -> None:
    """The OTHER two drop sites, each counted at its OWN guard.

    ``test_non_finite_and_non_positive_rows_are_dropped_and_counted`` covers only
    the finiteness/positivity guard. Two more branches drop a row: a value that
    cannot be floated at all, and a date that cannot be coerced. Each has its own
    ``dropped += 1``, and a mutant that removes EITHER still shortens the series
    — only the COUNT distinguishes "dropped with a reason" from "silently gone".
    The rows are interleaved so the count is the sum of two distinct sites
    (2 unconvertible + 1 bad date = 3), which a single-site counter cannot fake.
    """
    frame = _tidy_frame(
        [
            ("2026-10-09", 1.12055),
            ("2026-10-08", "not-a-number"),  # 1: unconvertible value
            ("2026-10-07", None),  # 2: unconvertible value
            ("not-a-date", 1.1300),  # 3: unparseable date
            ("2026-10-04", 1.1150),
        ]
    )
    reading = fetch_fx_futures("EURUSD", client=_StubClient(frame))  # type: ignore[arg-type]
    assert reading is not None
    assert reading.observations == 2, "only the two clean rows survive"
    assert reading.rows_dropped == 3, "both drop sites must be counted"


def test_an_all_corrupt_series_raises_rather_than_reading_as_no_data() -> None:
    """An empty result is a FAILURE, not an empty series."""
    frame = _tidy_frame([("2026-10-09", float("nan")), ("2026-10-08", 0.0)])
    with pytest.raises(FXFuturesError, match="no usable observations"):
        fetch_fx_futures("EURUSD", client=_StubClient(frame))  # type: ignore[arg-type]


def test_a_transport_failure_raises_fxfutures_error() -> None:
    """The transport's failure is translated, not leaked raw."""
    with pytest.raises(FXFuturesError, match="could not be read"):
        fetch_fx_futures("EURUSD", client=_StubClient(boom=True))  # type: ignore[arg-type]


def test_the_client_is_closed_when_it_constructed_one() -> None:
    """Ownership: a client this function built is closed; one passed in is NOT."""
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12), ("2026-10-08", 1.11)]))
    fetch_fx_futures("EURUSD", client=stub)  # type: ignore[arg-type]
    assert stub.closed is False, "a caller-supplied client stays the caller's to close"


# ---------------------------------------------------------------------------
# (g) the large-move detector reports what it MEASURES
# ---------------------------------------------------------------------------


def test_detect_large_moves_flags_an_extreme_day() -> None:
    """A one-day move far beyond the robust scale is flagged; ordinary days are not.

    The series is NOISY (real FX returns are), so the robust scale is the typical
    ~0.3% daily wiggle; the single ~5% jump stands ~6+ robust sigmas out and is
    the only day flagged. A deterministic ramp is deliberately avoided: constant
    returns give a near-zero MAD, which would make every day an "outlier" — a
    property of the ramp, not of a market series.
    """
    import random

    rng = random.Random(20261010)
    price = 1.10
    _base = date(2026, 1, 1)
    closes: list[tuple[date, float]] = [(_base, price)]
    for i in range(1, 40):
        price *= 1.0 + rng.uniform(-0.003, 0.003)
        closes.append((_base + timedelta(days=i), price))
    # One genuine shock day: +5%, far outside the ~0.3% noise band.
    closes.append((date(2026, 2, 10), closes[-1][1] * 1.05))

    moves = detect_large_moves(closes, threshold_sigmas=6.0)
    assert [m.on for m in moves] == [date(2026, 2, 10)]
    assert moves[0].ret == pytest.approx(0.05, abs=1e-9)


def test_detect_large_moves_is_robust_to_the_outlier_it_hunts() -> None:
    """The scale is a MAD, not a stdev — the outlier must not mask itself.

    **This is the mover proof for the CHOICE of scale, and it must make the two
    scales DIVERGE, not merely flag the shock.** A series that contains a large
    move proves nothing on its own: an ordinary stdev of the SAME returns may
    still let the move clear the bar. So the series uses a TIGHT noise band
    (~0.1%) with one ~20% shock, which lifts a stdev far more than a MAD, and
    the test then asserts the *cutoff* sits below an ordinary stdev — the direct
    discriminator. Asserting only "the shock is flagged" would pass under both
    scales.
    """
    import random

    rng = random.Random(7)
    _base = date(2026, 1, 1)
    returns = [rng.uniform(-0.001, 0.001) for _ in range(40)]
    price = 1.10
    closes: list[tuple[date, float]] = [(_base, price)]
    for i, r in enumerate(returns, start=1):
        price *= 1.0 + r
        closes.append((_base + timedelta(days=i), price))
    closes.append((date(2026, 2, 20), closes[-1][1] * 1.20))

    moves = detect_large_moves(closes, threshold_sigmas=6.0)
    assert [m.on for m in moves] == [date(2026, 2, 20)], (
        "the MAD scale keeps the ~1e-3 noise band, so the +20% day is the only one flagged"
    )
    # The direct discriminator: an ordinary stdev of these absolute returns is
    # far larger than the MAD-derived scale the function uses, so a stdev-based
    # cutoff would sit well ABOVE the MAD-based one. Assert the gap.
    abs_rets = [*sorted(abs(r) for r in returns), 0.20]
    n = len(abs_rets)
    mean = sum(abs_rets) / n
    stdev = (sum((v - mean) ** 2 for v in abs_rets) / n) ** 0.5
    cutoff = moves[0].threshold
    assert cutoff < stdev, (
        f"the cutoff ({cutoff}) must sit BELOW an ordinary stdev ({stdev}); "
        f"a stdev-based scale would put the cutoff near {6.0 * stdev}"
    )


def test_detect_large_moves_returns_nothing_for_a_flat_series() -> None:
    """A perfectly flat series has a zero robust scale; there is nothing to flag."""
    closes = [(date(2026, 1, i + 1), 100.0) for i in range(5)]
    assert detect_large_moves(closes, threshold_sigmas=6.0) == ()


def test_detect_large_moves_needs_three_points() -> None:
    """Fewer than three points cannot define a scale."""
    assert (
        detect_large_moves([(date(2026, 1, 1), 1.0), (date(2026, 1, 2), 2.0)], threshold_sigmas=6.0)
        == ()
    )


def test_detect_large_moves_flags_a_crash_as_well_as_a_spike() -> None:
    """The test is SIGN-AGNOSTIC: a large DOWN move must be flagged too.

    A crash is the day a data caveat matters most, so a detector that reads only
    ``ret > cutoff`` silently drops every negative outlier. The earlier tests all
    use a positive shock, so they pass under such a mutant; this one plants a
    NEGATIVE shock and asserts it is reported. (The boundary itself, ``>`` vs
    ``>=``, is deliberately not asserted: the two differ only at exact
    floating-point equality, which is unobservable and therefore untestable.)
    """
    import random

    rng = random.Random(31337)
    _base = date(2026, 1, 1)
    price = 1.10
    closes: list[tuple[date, float]] = [(_base, price)]
    for i in range(1, 40):
        price *= 1.0 + rng.uniform(-0.003, 0.003)
        closes.append((_base + timedelta(days=i), price))
    # A crash day: -7%, far outside the noise band.
    closes.append((date(2026, 2, 10), closes[-1][1] * 0.93))

    moves = detect_large_moves(closes, threshold_sigmas=6.0)
    assert [m.on for m in moves] == [date(2026, 2, 10)], (
        "a large NEGATIVE move must be flagged; the test is sign-agnostic"
    )
    assert moves[0].ret < 0.0


def test_large_moves_are_reported_never_called_rolls() -> None:
    """The reading reports large moves, and the type/field name says MOVE.

    MEASURED 2026-10-10: the flagged days on the live ``GBPUSD`` series were the
    Sep-2022 gilt crisis and other genuine volatility — NOT a quarterly roll
    schedule. A "roll" label would be a mis-description (Lesson 2), so the field
    is ``large_moves`` and the dataclass has no ``roll`` field.
    """
    import random

    rng = random.Random(99)
    price = 1.10
    _base = date(2026, 1, 1)
    rows: list[tuple[object, float]] = [(_base, price)]
    for i in range(1, 40):
        price *= 1.0 + rng.uniform(-0.003, 0.003)
        rows.append((_base + timedelta(days=i), price))
    rows.append((date(2026, 2, 10), rows[-1][1] * 1.05))
    reading = fetch_fx_futures("EURUSD", client=_StubClient(_tidy_frame(rows)))  # type: ignore[arg-type]
    assert reading is not None
    assert len(reading.large_moves) == 1
    assert not hasattr(reading, "roll_gaps")


def test_a_series_with_large_moves_carries_the_caveat() -> None:
    """The reading must WARN that a discontinuity was seen and NOT smoothed.

    ``warnings`` is derived from the reading's own fields, so a series WITH a
    large move must carry the notice and a series without one must not. A mutant
    that never emits the branch leaves the series published with its largest
    day invisible — the reader sees a clean series that is not one. Both states
    are asserted, so a mutant that ALWAYS emits it is caught too.
    """
    import random

    rng = random.Random(4242)
    price = 1.10
    _base = date(2026, 1, 1)
    rows: list[tuple[object, float]] = [(_base, price)]
    for i in range(1, 40):
        price *= 1.0 + rng.uniform(-0.003, 0.003)
        rows.append((_base + timedelta(days=i), price))
    rows.append((date(2026, 2, 10), rows[-1][1] * 1.05))

    with_move = fetch_fx_futures("EURUSD", client=_StubClient(_tidy_frame(rows)))  # type: ignore[arg-type]
    assert with_move is not None
    assert with_move.large_moves, "the shock day must be flagged"
    assert any("beyond the robust threshold" in w for w in with_move.warnings), (
        "a flagged day must be disclosed in warnings"
    )

    quiet = fetch_fx_futures(
        "EURUSD",
        client=_StubClient(_tidy_frame([("2026-10-09", 1.12), ("2026-10-08", 1.11)])),  # type: ignore[arg-type]
    )
    assert quiet is not None
    assert quiet.large_moves == ()
    assert not any("beyond the robust threshold" in w for w in quiet.warnings)


# ---------------------------------------------------------------------------
# the config boundary (both new leaves are load-bearing)
# ---------------------------------------------------------------------------


def test_cme_roots_cover_the_enabled_catalogue() -> None:
    """Every foreign currency the roots claim must map to a 2-char-ish root.

    A malformed map makes every pair a 204, so the shape is asserted rather than
    assumed. The CONTENT (which root tracks which currency) is verified live by
    ``tools/probe_fx_forward.py``.
    """
    from macro_engine.config import get_settings

    roots = get_settings().fx_futures.cme_roots
    assert roots, "the root map must not be empty"
    for currency, root in roots.items():
        assert currency.isalpha() and currency.isupper(), f"bad currency code {currency!r}"
        assert root.isalnum(), f"bad root {root!r}"


def test_the_provider_is_configured() -> None:
    """The provider is a leaf, not a literal."""
    from macro_engine.config import get_settings

    assert get_settings().fx_futures.provider == "yfinance"
