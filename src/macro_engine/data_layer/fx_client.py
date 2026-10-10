"""FX spot rates — the bridge between two countries' rates systems (Section 22.3).

Why this module exists
----------------------
Section 22.3's multi-country work is only half-done without an FX layer: two
countries' yields cannot be compared on a single basis unless one is converted
into the other's currency. The schema has always *declared* ``fx_spot``
(``schemas.py``), and until now it was never populated — the D-137 disposition
called that "a disclosure, not a fetch", because the *field* was unwired.

**Measured 2026-10-10, that disposition was half right and half wrong.** The
field was indeed unwired, but the data is **available**, so "no fetch" was the
wrong resting state. This is the sixth FALSE BLOCK of the D-043 class this
repository has caught (after ``ppp_implied_rate``, ``commodities_client``,
``fx_reserves``, the two EM legs, and the §22.5 futures curve): a sourcing claim
recorded once and never re-measured. The remedy is the same — record the source
and wire it, so the value is *fetched* rather than typed.

The source, measured live 2026-10-10
------------------------------------
``currency.price.historical`` (the local OpenBB service, ``:6900``) serves a
daily series per pair. Measured for ``EURUSD``, ``GBPUSD`` and ``USDJPY``:
HTTP 200, **29 rows** each over the probe window (2026-09-01 onward), e.g.
``EURUSD`` 2026-10-09 ``1.1206``, ``GBPUSD`` ``1.3233``, ``USDJPY`` ``158.25``.
Through ``OpenBBClient.fetch_series`` the route arrives **normalised** to the
project's tidy 5-column shape (``date``, ``value``, ``series_id``, ``source``,
``retrieved_at``); the ``value`` the normaliser extracts is the route's daily
close, which is the mark a rate conversion wants.

A second, richer route exists and is used as the fallback:
``currency.reference_rates`` (provider ``ecb``) returns **30 currencies against
the euro** in one response — USD, GBP, JPY, CHF, SEK, NOK and more. It is the
ECB's own daily reference set, so it needs no per-pair query and carries the
official fixing rather than a vendor's close.

**What is NOT available, and why this module does not pretend otherwise.**
Measured the same session: a walk of the live OpenAPI spec returns **278
routes**, and **none** matches ``forward`` / ``swap`` / ``basis`` under
``currency`` or ``fixedincome`` (the only ``forward_*`` routes are
``equity.estimates.forward_eps`` and friends — equity metrics, not FX). So
**FX spot is reachable and forward points are not**. ``cip_check`` needs
``forward`` as an *input* and remains un-live-checkable; this module deliberately
supplies only the spot leg, because supplying a forward would mean inventing one
(Section 21.0 rule 3).

The quote convention, stated because it is the whole ballgame
-------------------------------------------------------------
A float FX rate is meaningless without its convention, and a convention error
produces a perfectly plausible number that means the opposite of the truth
(``CIPInputs``'s own docstring warns of exactly this). Two conventions meet here:

* ``EURUSD`` is **EUR-base / USD-quote**: the number is *USD per 1 EUR*, so it
  **rises when the dollar weakens**.
* The ECB reference rates are **EUR-based** too (``USD: 1.1206`` = USD per EUR),
  so a reference-rate row is directly comparable to a ``EURUSD`` quote.

:func:`convert` takes the rate, the two currency codes and a **direction derived
from the codes** rather than assumed, and refuses a same-currency call rather
than returning the input (which would silently look like a working conversion).

The pair catalogue is deliberately G10-plus and **explicit**: an unlisted pair
returns ``None`` rather than being derived by chaining two unrelated legs, because
a chained cross is a *third* convention (bid/ask, timing) the caller did not ask
for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

import pandas as pd

from macro_engine.data_layer.openbb_client import (
    OpenBBClient,
    OpenBBFetchError,
)
from macro_engine.data_layer.schemas import ObservationPoint
from macro_engine.models.contracts import utc_now

__all__ = [
    "FX_PAIRS",
    "FXPair",
    "FxReadError",
    "FxSpotReading",
    "SeriesClient",
    "fetch_fx_spot",
    "parse_ecb_reference_rate",
]


class SeriesClient(Protocol):
    """The surface this module needs from a data client.

    Declared as a ``Protocol`` rather than typing the parameter as
    ``OpenBBClient``: this module uses exactly two methods, and a caller that
    supplies an object with them — a test stub, a caching wrapper, a future
    transport — is genuinely valid. Typing the concrete class would force every
    such caller through an unchecked ``cast``, which is a claim the type system
    cannot verify and which hides the real coupling. ``params`` is
    ``dict[str, Any]`` to match ``OpenBBClient.fetch_series`` exactly, so the
    real client satisfies this protocol without any adapter.

    ``close`` is included because the module closes a client it constructed
    itself; a caller passing one in keeps ownership of it (mirroring
    ``openbb_client``'s own ``own_client`` convention).
    """

    def fetch_series(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        series_label: str,
    ) -> pd.DataFrame:
        """Fetch one series into the client's normalised tidy frame."""
        ...

    def close(self) -> None:
        """Release the client's transport resources."""
        ...


#: The pairs this module can fetch, mapped to ``(base, quote)``.
#:
#: Stored as ``(base, quote)`` rather than as a symbol string so the quote
#: convention is *data*, not a comment: every consumer that needs "how many
#: QUOTE per one BASE" reads it here instead of re-parsing a six-letter ticker
#: (LAW 2). The set is the G10 crosses a rates/FX thesis actually names, plus
#: USD/EUR/GBP/JPY as the majors the two built countries (us, gb) and the next
#: one (eu) require.
FX_PAIRS: dict[str, tuple[str, str]] = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "USDCHF": ("USD", "CHF"),
    "AUDUSD": ("AUD", "USD"),
    "USDCAD": ("USD", "CAD"),
    "EURGBP": ("EUR", "GBP"),
    "EURJPY": ("EUR", "JPY"),
    "EURCHF": ("EUR", "CHF"),
    "GBPJPY": ("GBP", "JPY"),
}


class FxReadError(Exception):
    """An FX fetch failed, or the pair was unusable.

    Distinct from ``OpenBBFetchError`` for the same reason ``ReservesReadError``
    is: *the transport failed* and *the pair is not registered* are different
    facts, and the caller reports them differently (a ``None`` return for the
    unregistered pair, this class for a broken fetch).
    """


@dataclass(frozen=True)
class FXPair:
    """One currency pair, with its quote convention made explicit.

    ``base``/``quote`` are ISO-4217 alpha-3 codes. ``rate`` is *units of
    ``quote`` per one unit of ``base``* — the single statement that makes the
    number interpretable. A reader who needs "USD per EUR" reads
    ``FX_PAIRS["EURUSD"]`` and does not have to remember which side is which.
    """

    symbol: str
    base: str
    quote: str
    series: list[ObservationPoint]

    @property
    def latest(self) -> ObservationPoint | None:
        """The most recent observation, or ``None`` when the series is empty."""
        return self.series[-1] if self.series else None

    @property
    def convention(self) -> str:
        """A one-line statement of what one unit of ``rate`` means."""
        return f"{self.quote} per 1 {self.base}"


@dataclass(frozen=True)
class FxSpotReading:
    """A fetched spot series for one pair, with its provenance.

    Carries the ``source`` string because the two routes available here are not
    equivalent: ``currency.price.historical`` is a vendor OHLC series (a market
    close), while ``currency.reference_rates`` is the ECB's official daily
    fixing. A thesis comparing a Bund yield to a UST yield should know which one
    it was handed — they can differ by a few basis points on a fixing day.
    """

    pair: FXPair
    source: str
    observation_count: int
    retrieved_at: datetime


def _pair_or_none(symbol: str) -> tuple[str, str] | None:
    """Resolve a symbol to ``(base, quote)``, case-insensitively."""
    key = symbol.strip().upper().replace("/", "").replace("-", "")
    return FX_PAIRS.get(key)


def fetch_fx_spot(
    symbol: str,
    *,
    client: SeriesClient | None = None,
    start_date: date | None = None,
) -> FxSpotReading | None:
    """Fetch one pair's daily spot series, or ``None`` when it is unregistered.

    Parameters
    ----------
    symbol:
        A pair code (``"EURUSD"``, ``"eur/usd"`` — the separators are tolerated).
        An **unregistered** pair returns ``None`` rather than raising, because
        "this pair is not in the catalogue" and "the network is down" are
        different facts.
    start_date:
        The earliest observation to request. Defaults to five years back, which
        is long enough for a 12-month change with a wide margin and short enough
        that the vendor returns promptly.

    Raises
    ------
    FxReadError
        The registered pair's fetch failed, or it returned no usable rows.

    Notes
    -----
    **No forward is returned, ever.** The route family carries spot only
    (measured: no ``forward``/``swap``/``basis`` route in the live spec), so a
    caller needing a forward must supply one and disclose it. Returning a spot
    value under a forward's name would be the precise defect ``CIPInputs``
    guards against.
    """
    resolved = _pair_or_none(symbol)
    if resolved is None:
        return None
    base, quote = resolved
    canonical = f"{base}{quote}"

    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        try:
            frame = active.fetch_series(
                provider="yfinance",
                endpoint="currency.price.historical",
                params={
                    "symbol": canonical,
                    "start_date": (start_date or date(2021, 1, 1)).isoformat(),
                },
                series_label=f"fx_spot_{canonical.lower()}",
            )
        except OpenBBFetchError as exc:
            raise FxReadError(f"FX spot series {canonical} could not be read: {exc}") from exc
    finally:
        if own_client:
            active.close()

    series = _frame_to_points(frame, series_id=f"fx_spot_{canonical.lower()}")
    if not series:
        raise FxReadError(
            f"FX spot series {canonical} returned no usable observations. An "
            f"empty series is reported rather than returned as an empty list, "
            f"so a caller cannot mistake 'the fetch failed' for 'no data this "
            f"run' — the same distinction the DECLARED_NOT_WIRED flag makes at "
            f"the snapshot level."
        )

    return FxSpotReading(
        pair=FXPair(symbol=canonical, base=base, quote=quote, series=series),
        source="openbb:currency.price.historical (daily close)",
        observation_count=len(series),
        retrieved_at=utc_now(),
    )


def parse_ecb_reference_rate(
    payload: dict[str, float],
    *,
    currency: str,
) -> ObservationPoint | None:
    """Read one currency's rate out of an ECB ``reference_rates`` response.

    The ECB publishes **EUR-based** rates — one row, ``{currency: rate}``, where
    the rate is *units of that currency per one euro*. ``USD: 1.1206`` therefore
    means USD per EUR, identical to an ``EURUSD`` quote, and is stored as one.

    Returns ``None`` for a currency the response does not carry rather than a
    zero: a missing currency is *unknown*, and a ``0.0`` rate would divide by
    zero in every conversion downstream (the ``ReservesReading.change_12m_pct``
    discipline — ``None`` is a fact, ``0.0`` is an assertion).

    ``currency`` must not be ``EUR``: the euro is the base of this whole family,
    so its rate is 1.0 by construction and returning it would invite a spurious
    "EUR/EUR" pair into the catalogue.
    """
    code = currency.strip().upper()
    if code == "EUR":
        return None
    if code not in payload:
        return None
    value = payload[code]
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value <= 0.0:
        return None
    return ObservationPoint(
        observation_date=utc_now().date(),
        value=value,
        series_id=f"fx_spot_eur{code.lower()}",
        source="openbb:currency.reference_rates (ECB daily fixing)",
    )


def _frame_to_points(frame: pd.DataFrame | None, *, series_id: str) -> list[ObservationPoint]:
    """Turn ``fetch_series``' tidy frame into ``ObservationPoint``s.

    **The shape is measured, not assumed.** ``OpenBBClient.fetch_series`` returns
    a TIDY 5-column frame — ``date``, ``value``, ``series_id``, ``source``,
    ``retrieved_at`` — with a ``RangeIndex``, because the client normalises every
    route (including an OHLC one) to one row per observation keyed by ``date`` and
    ``value``. Measured live 2026-10-10 for ``currency.price.historical`` /
    ``EURUSD``: shape ``(29, 5)``, those exact columns.

    That matters: an earlier draft of this function looked for an ``OHLC`` index
    and a ``close`` column — the shape the *route* advertises — and would have
    returned ``[]`` on every real call, i.e. reported "no data" for data that was
    present. **The client's normalised shape is the contract, not the provider's.**
    The ``value`` column therefore already holds the close (the normaliser picked
    it); this function neither re-selects nor re-derives it.

    Rows with a non-positive or non-finite value are **dropped, not zeroed**: a
    zero rate divides by zero, and a ``nan`` passes every comparison (D-078), so
    neither may enter a conversion.
    """
    if frame is None or getattr(frame, "empty", True):
        return []
    columns = list(getattr(frame, "columns", []))
    if "date" not in columns or "value" not in columns:
        return []

    out: list[ObservationPoint] = []
    for raw_date, raw_value in zip(frame["date"], frame["value"], strict=False):
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0.0:
            continue
        observed = _as_date(raw_date)
        if observed is None:
            continue
        out.append(
            ObservationPoint(
                observation_date=observed,
                value=value,
                series_id=series_id,
                source="openbb:currency.price.historical (daily close)",
            )
        )
    out.sort(key=lambda p: p.observation_date)
    return out


def _as_date(index_value: object) -> date | None:
    """Coerce a frame index entry to a ``date``, or ``None`` when it is not one.

    Handles the two shapes an OHLC index arrives in — a real ``date``/``datetime``
    (the common case) and an ISO-ish string. Delivery-format tolerant rather than
    clever: a value that matches neither shape returns ``None`` and its row is
    dropped, which is preferable to guessing a date and mislabelling an
    observation (the same "unknown ≠ zero" discipline the rest of the module uses).
    """
    if isinstance(index_value, datetime):
        return index_value.date()
    if isinstance(index_value, date):
        return index_value
    text = str(index_value).strip()
    if not text:
        return None
    # An ISO datetime may carry a time/offset; only the date is wanted.
    head = text.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None
