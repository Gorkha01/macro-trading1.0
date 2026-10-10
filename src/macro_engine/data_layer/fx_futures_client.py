"""FX futures — the exchange-traded instrument nearest an FX forward (Section 22.3).

Why this module exists, and what it deliberately is NOT
-------------------------------------------------------
``cip_check`` wants an OBSERVED FX **forward** and this installation has none:
re-measured 2026-10-10 across all 32 installed OpenBB providers, the entire FX
surface is four routes (``currency.price.historical`` / ``reference_rates`` /
``search`` / ``snapshots``) and **not one** is a forward, a swap or a
cross-currency basis. The block is recorded at ``config/series_registry.yaml``
under ``fx_forward_rate``.

What *is* reachable is the **CME FX futures** complex, via
``derivatives.futures.historical`` with ``provider="yfinance"``. Measured
2026-10-10: six contracts answer (``6E=F`` EUR, ``6J=F`` JPY, ``6B=F`` GBP,
``6A=F`` AUD, ``6C=F`` CAD, ``6S=F`` CHF), each returning tens of observed OHLC
rows. A dated contract (``6EZ26``, ``6EM27``, ``6EH26``) returns **HTTP 204 —
empty** — so the only series this route publishes is the **rolling front-month**,
the provider's ``=F`` continuous contract.

⚠️ **A rolling front-month is NOT a forward, and this module never pretends it
is.** The ``=F`` series rolls from one contract month to the next on a schedule,
and at each roll the quoted price **jumps** to the new contract — a discontinuity
that is a *contract switch*, not a market move. Differencing a rolling series
against spot therefore produces a "forward point" that is really the sum of a
genuine basis and an unremovable roll artifact. Publishing that number under the
name "forward" (or feeding it to ``cip_check``) would be the plausible-looking
wrong number this project treats as SEV-1 (Section 21.0).

So this module publishes the future **as a future**: a rolling front-month
futures price, with the roll made visible and the dated-contract request refused.
It is the honest nearest instrument — useful for a carry/positioning read and for
a *bounded* cross-check — and it is explicitly NOT a substitute for the forward
``cip_check`` requires. The distinction is carried in the returned object
(``is_forward`` is False and there is no ``forward`` accessor) so a caller cannot
reach for one by accident.

The roll, and what this module can HONESTLY say about it
--------------------------------------------------------
The route gives no expiry and **no dated contract is reachable** (measured
2026-10-10: ``6EZ26``/``6EM27``/``6EH26`` all return HTTP 204, and the
``expiration`` parameter errors). So the roll dates are **not knowable from this
source**.

An earlier draft of this module called a rolling series' large one-day moves
"roll gaps" and published them as such. That was WRONG, and measuring it on the
live series showed why: for ``GBPUSD`` the flagged days were 2022-09-23 (the
gilt crisis), 2022-11-10 and other genuine volatility — **not** a quarterly roll
schedule. A large move and a roll are indistinguishable from returns alone, so a
"roll" label on that evidence is a **mis-description**: a field naming a
computation that did not happen (Lesson 2). It would have told a consumer the
series switches contract on those days when it mostly did not.

So this module does not claim to detect rolls. It reports ``large_moves`` — days
whose return exceeds a robust threshold — **as a data caveat**, and states
plainly in ``FXFuturesReading.warnings`` that the series is continuous, rolls on
a schedule the source does not disclose, and therefore contains discontinuities
that this module cannot separate from market moves.

Run the probe that established all of the above:
    uv run python tools/probe_fx_forward.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from macro_engine.config import get_settings
from macro_engine.data_layer.fx_client import FX_PAIRS
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError
from macro_engine.models.contracts import utc_now

__all__ = [
    "FX_FUTURES_ROUTE_ENDPOINT",
    "FXFuturesError",
    "FXFuturesReading",
    "LargeMove",
    "detect_large_moves",
    "fetch_fx_futures",
]

#: The OpenBB route family. A CONSTANT rather than a config leaf because it is
#: the route's PATH (part of the transport contract), not a tunable — the same
#: split ``fed_funds_futures_client`` draws. PUBLIC so a consumer can cite the
#: exact route in ``data_provenance`` (LAW 2: one canonical spelling).
FX_FUTURES_ROUTE_ENDPOINT = "derivatives.futures.historical"


class FXFuturesError(Exception):
    """The FX-futures series could not be read, or was too damaged to publish.

    Distinct from ``OpenBBFetchError`` so a caller can tell *the transport
    failed* from *the transport worked but the series was unusable* — the same
    split ``FuturesCurveError`` and ``CommodityReadError`` draw.
    """


@dataclass(frozen=True)
class LargeMove:
    """One day whose return is far from the series' own robust scale.

    **Deliberately NOT called a roll.** The source discloses no expiry, so a roll
    cannot be identified; a large move may be a roll OR a genuine market day, and
    the two are indistinguishable from returns alone. ``ret`` is the simple
    return on ``on``; ``threshold`` is the robust cutoff it exceeded. Both are
    carried so the reader sees how far out of line it was.
    """

    on: date
    ret: float
    threshold: float


@dataclass(frozen=True)
class FXFuturesReading:
    """A rolling front-month FX futures series, with its provenance and limits.

    **There is deliberately no ``forward`` accessor and no ``forward`` field.**
    The object names what it is — a *futures* reading — so a consumer that wants
    a forward is forced to notice it does not have one.

    ``is_forward`` is always ``False`` and is present as a named, testable
    statement of the invariant rather than as an omission: a caller that checks
    it gets a clear answer, where a missing attribute would raise an
    ``AttributeError`` that looks like a bug rather than a boundary.

    ``latest_close`` is the most recent observation's close, in the FUTURE's own
    units — always **USD per 1 unit of the foreign currency** (the CME FX quote
    convention). When the pair is ``USD/X`` the future is the INVERSE of the
    pair, and ``is_inverse`` is ``True`` so a consumer converts knowingly rather
    than by luck. ``large_moves`` names days whose return is far from the
    series' own robust scale — **as a caveat, not as rolls** (see the module
    docstring: the source discloses no expiry, so a roll cannot be identified).
    ``observations`` is the count of usable rows after corrupt rows were
    dropped, and ``rows_dropped`` counts the drops — so a short series can be
    told from a clean one.
    """

    symbol: str
    base: str
    quote: str
    root: str
    is_inverse: bool
    provider: str
    as_of: str
    latest_close: float
    latest_date: date
    first_date: date
    observations: int
    rows_dropped: int
    large_moves: tuple[LargeMove, ...]
    source: str
    retrieved_at: datetime

    @property
    def is_forward(self) -> bool:
        """ALWAYS ``False``. A rolling front-month future is not a forward.

        Present as an explicit, testable statement rather than an omission, so
        a caller that needs a forward can assert on it and get a boolean rather
        than discover the gap by ``AttributeError``.
        """
        return False

    @property
    def is_rolling(self) -> bool:
        """Always ``True`` — the ``=F`` series is the continuous front month."""
        return True

    @property
    def warnings(self) -> tuple[str, ...]:
        """The caveats a consumer must read before using this series.

        Published as a PROPERTY rather than stored so they cannot drift from the
        object's own fields: every statement is derived from this reading.
        """
        out = [
            "NOT a forward: this is a rolling front-month futures price. The "
            "=F series switches contract on a schedule the source does not "
            "disclose, so it contains price discontinuities that cannot be "
            "separated from market moves.",
            "Do NOT feed this to cip_check in place of an observed forward. "
            "Covered interest parity needs a DATED forward; a rolling series "
            "rolls mid-window and would produce a plausible wrong deviation.",
        ]
        if self.large_moves:
            out.append(
                f"{len(self.large_moves)} day(s) carry a return beyond the robust "
                f"threshold. Some are likely contract rolls and some are genuine "
                f"market moves; the source does not disclose which. They are "
                f"reported, never smoothed."
            )
        if self.is_inverse:
            out.append(
                f"The future is the INVERSE of {self.symbol}; use `pair_close` "
                f"for the pair's own convention rather than `latest_close`."
            )
        return tuple(out)

    @property
    def convention(self) -> str:
        """A one-line statement of what ``latest_close`` means.

        The future always quotes USD-per-foreign, so this says which currency is
        the foreign one and whether that is the pair's QUOTE (same direction) or
        its BASE (inverse) — the fact a consumer must not have to reconstruct.
        """
        foreign = self.base if self.quote == "USD" else self.quote
        direction = (
            f"same direction as {self.symbol}"
            if not self.is_inverse
            else f"INVERSE of {self.symbol}"
        )
        return f"USD per 1 {foreign} ({self.root}=F rolling front-month future; {direction})"

    @property
    def pair_close(self) -> float:
        """``latest_close`` expressed in the PAIR's own convention.

        Inverts when the future is the inverse of the pair, so a consumer that
        wants "units of ``quote`` per one ``base``" — the convention every other
        FX value in this system uses — reads it here instead of remembering to
        invert. The inversion is exact (``1/rate``) and the raw future price is
        retained on ``latest_close`` for audit.
        """
        return (1.0 / self.latest_close) if self.is_inverse else self.latest_close


def _resolve_pair(symbol: str) -> tuple[str, str] | None:
    """Resolve a pair code to ``(base, quote)`` from the canonical catalogue.

    Uses ``fx_client.FX_PAIRS`` — the SAME catalogue the spot client uses
    (LAW 2) — rather than a second copy under a different name, so a pair added
    for spot is immediately eligible here and the two cannot drift. The
    separators are tolerated exactly as the spot client tolerates them.
    """
    key = symbol.strip().upper().replace("/", "").replace("-", "")
    return FX_PAIRS.get(key)


def _resolve_futures(base: str, quote: str) -> tuple[str, bool] | None:
    """Resolve a pair to ``(cme_root, is_inverse)``, or ``None`` when unsupported.

    **The CME FX complex is USD-only, quoted as "USD per 1 foreign currency".**
    Verified for every reachable root 2026-10-10 by comparing each future's price
    to its spot pair's known convention:

        root  future price   pair      so the future quotes
        6E    1.1206         EURUSD    USD per EUR  (SAME direction as the pair)
        6J    0.00632        USDJPY    USD per JPY  (INVERSE of the pair)
        6B    1.3241         GBPUSD    USD per GBP  (same)
        6A    0.6982         AUDUSD    USD per AUD  (same)
        6C    0.7012         USDCAD    USD per CAD  (INVERSE: 1/1.4262)
        6S    1.2141         USDCHF    USD per CHF  (INVERSE: 1/0.8237)
        6N    0.5624         NZDUSD    USD per NZD  (same)
        6M    0.05420        USDMXN    USD per MXN  (INVERSE: 1/18.451)

    So there are exactly two supported shapes, and one REFUSAL:

    * ``X/USD`` (quote is USD) — the future is the SAME direction; the foreign
      currency is the pair's base. ``is_inverse = False``.
    * ``USD/X`` (base is USD) — the future is the INVERSE of the pair, because
      the future still quotes USD-per-X while the pair quotes X-per-USD. The
      foreign currency is the pair's QUOTE. ``is_inverse = True``.

    A pair with **neither leg USD** (a cross, e.g. ``EURGBP``) returns ``None``:
    there is **no CME future for it**, and returning some related USD future
    under the cross's name is EXACTLY the silent-wrong-number defect this project
    treats as SEV-1. Measured: before this rule existed the function returned the
    ``6E=F`` series for ``EURGBP`` (identical closes to ``EURUSD``), which is a
    wrong answer wearing a right-looking label.

    The root comes from ``fx_futures.cme_roots`` in config, because which
    currency a root tracks is a per-currency market fact, not a policy choice
    (LAW 1) — and the route requires the ROOT, not the pair code (measured:
    ``EURUSD=F`` -> HTTP 204, ``6E=F`` -> HTTP 200).
    """
    if quote == "USD":
        foreign, inverse = base, False
    elif base == "USD":
        foreign, inverse = quote, True
    else:
        return None  # a cross: no CME future exists, and we must not substitute one
    root = get_settings().fx_futures.cme_roots.get(foreign)
    if root is None:
        return None
    return (root, inverse)


def fetch_fx_futures(
    symbol: str,
    *,
    client: OpenBBClient | None = None,
    start_date: date | None = None,
) -> FXFuturesReading | None:
    """Fetch one pair's rolling front-month FX futures series.

    Parameters
    ----------
    symbol:
        A pair code (``"EURUSD"``, ``"eur/usd"``). An **unregistered** pair
        returns ``None`` rather than raising, because "this pair is not in the
        catalogue" and "the network is down" are different facts — the same
        distinction :func:`fetch_fx_spot` draws.
    start_date:
        Earliest observation to request. Defaults five years back.

    Returns
    -------
    FXFuturesReading | None
        ``None`` for an unregistered pair; otherwise the series.

    Raises
    ------
    FXFuturesError
        The registered pair's fetch failed, returned no usable rows, or the
        route answered with a dated-contract-shaped empty response.

    Notes
    -----
    **What is fetched is the ``=F`` continuous contract** (the provider's
    rolling front month). A DATED contract is not reachable on this route —
    measured 2026-10-10, dated CME FX tickers return HTTP 204 — so this function
    never attempts one and the caller cannot ask it to: an FX future for a
    specific value date is not what the route offers.
    """
    resolved = _resolve_pair(symbol)
    if resolved is None:
        return None
    base, quote = resolved
    canonical = f"{base}{quote}"
    futures = _resolve_futures(base, quote)
    if futures is None:
        # Either no CME future exists for this pair (a cross), or the foreign
        # currency has no mapped root. Both are UNREGISTERED for this layer, not
        # broken — returning None (the unregistered-pair contract) keeps "not in
        # the futures catalogue" distinct from "the fetch failed".
        return None
    root, is_inverse = futures
    provider = get_settings().fx_futures.provider

    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        try:
            frame = active.fetch_series(
                provider=provider,
                endpoint=FX_FUTURES_ROUTE_ENDPOINT,
                params={
                    "symbol": f"{root}=F",
                    "start_date": (start_date or date(2021, 1, 1)).isoformat(),
                },
                series_label=f"fx_futures_{canonical.lower()}",
            )
        except OpenBBFetchError as exc:
            raise FXFuturesError(
                f"FX futures series {root}=F (for {canonical}) could not be read via "
                f"{provider} on {FX_FUTURES_ROUTE_ENDPOINT}: {exc}"
            ) from exc
    finally:
        if own_client:
            active.close()

    points, rows_dropped = _clean_frame(frame)
    if not points:
        raise FXFuturesError(
            f"FX futures series {root}=F (for {canonical}) returned no usable "
            f"observations. An empty series is reported rather than returned as an "
            f"empty list, so a caller cannot mistake 'the fetch failed' for 'no data "
            f"this run' — the same distinction `fetch_fx_spot` draws."
        )

    closes = list(points)
    large_moves = detect_large_moves(
        closes, threshold_sigmas=get_settings().fx_futures.large_move_sigma
    )

    return FXFuturesReading(
        symbol=canonical,
        base=base,
        quote=quote,
        root=root,
        is_inverse=is_inverse,
        provider=provider,
        as_of=utc_now().date().isoformat(),
        latest_close=closes[-1][1],
        latest_date=closes[-1][0],
        first_date=closes[0][0],
        observations=len(closes),
        rows_dropped=rows_dropped,
        large_moves=large_moves,
        source=f"openbb:{FX_FUTURES_ROUTE_ENDPOINT} ({provider}, rolling front-month {root}=F)",
        retrieved_at=utc_now(),
    )


def _clean_frame(
    frame: pd.DataFrame | None,
) -> tuple[list[tuple[date, float]], int]:
    """Reduce the client's tidy frame to ``(kept_points, dropped_count)``.

    **The shape is measured, not assumed.** ``OpenBBClient.fetch_series`` returns
    the project's tidy 5-column frame (``date``/``value``/``series_id``/``source``
    ``/retrieved_at``) for EVERY route, an OHLC one included — the client
    normalises ``close`` into ``value``. So the ``value`` column already holds the
    close; this function selects nothing.

    A row is dropped — never repaired — when its date is unparseable, or its
    value is non-numeric, non-finite, or non-positive. A price of ``nan`` passes
    every comparison (D-078) and a zero or negative FX price is impossible, so
    neither may enter a return computation.

    **The dropped count is RETURNED, not discarded.** An earlier draft filtered
    the drops out inside this function, so the caller summed over an
    already-clean list and always reported ``rows_dropped = 0`` — a field
    claiming a count that could never be non-zero, which is the mis-description
    class (Lesson 2). Returning the count makes a short series distinguishable
    from a clean one.
    """
    kept: list[tuple[date, float]] = []
    dropped = 0
    if frame is None or getattr(frame, "empty", True):
        return (kept, dropped)
    columns = list(getattr(frame, "columns", []))
    if "date" not in columns or "value" not in columns:
        return (kept, dropped)

    for raw_date, raw_value in zip(frame["date"], frame["value"], strict=False):
        observed = _as_date(raw_date)
        if observed is None:
            dropped += 1
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if not math.isfinite(value) or value <= 0.0:
            dropped += 1
            continue
        kept.append((observed, value))
    kept.sort(key=lambda item: item[0])
    return (kept, dropped)


def detect_large_moves(
    closes: list[tuple[date, float]],
    *,
    threshold_sigmas: float,
) -> tuple[LargeMove, ...]:
    """Flag days whose return is far from the series' own ROBUST scale.

    **This reports large moves, NOT rolls.** A roll cannot be identified from
    this source (no expiry, no dated contract), and a large market move is
    indistinguishable from a roll by returns alone — measured 2026-10-10: on
    ``GBPUSD`` the flagged days were the Sep-2022 gilt crisis and other genuine
    volatility, not a quarterly schedule. Naming these "rolls" would be a
    mis-description, so the function and its return type say what they measure.

    The cutoff is **robust**: it uses the median absolute deviation (MAD) of the
    daily returns, scaled to a standard-deviation equivalent, rather than the
    ordinary standard deviation. Two reasons, both properties of a series that
    CONTAINS large moves:

    * an ordinary ``stdev`` is inflated BY the very outlier being hunted, so a
      large move raises the bar that would catch it — the detector blinds itself
      in proportion to the size of the thing it looks for;
    * the mean a ``stdev`` is taken about is dragged by the same outlier.

    The MAD-based scale resists both. The cutoff is ``threshold_sigmas`` robust
    sigmas above the median absolute return.

    Returns the moves in date order. **Does not modify the series**: a repaired
    series would be a fabrication (Section 21.0 rule 2), and a consumer needs to
    know the raw series contains large moves, not to have them smoothed away.

    A series with fewer than three points, or a zero robust scale (a perfectly
    flat series), returns no moves — there is nothing to compare against.
    """
    if len(closes) < 3:
        return ()
    rets: list[tuple[date, float]] = []
    for (_prev_date, prev), (cur_date, cur) in zip(closes, closes[1:], strict=False):
        if prev <= 0.0:
            continue
        rets.append((cur_date, (cur - prev) / prev))
    if len(rets) < 2:
        return ()

    values = sorted(abs(r) for _d, r in rets)
    median = _median(values)
    deviations = sorted(abs(v - median) for v in values)
    mad = _median(deviations)
    # 1.4826 scales a MAD to a standard-deviation equivalent for a normal
    # distribution, the standard consistency constant.
    robust_sigma = 1.4826 * mad
    if robust_sigma <= 0.0:
        return ()
    cutoff = threshold_sigmas * robust_sigma
    return tuple(
        LargeMove(on=on, ret=ret, threshold=cutoff) for on, ret in rets if abs(ret) > cutoff
    )


def _median(sorted_values: list[float]) -> float:
    """Median of an ALREADY-SORTED list; 0.0 for an empty one."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def _as_date(index_value: object) -> date | None:
    """Coerce a frame's ``date`` cell to a ``date``, or ``None`` when it is not one.

    Delivery-format tolerant rather than clever: a value that matches neither
    shape returns ``None`` and its row is dropped, which is preferable to
    guessing a date and mislabelling an observation.
    """
    if isinstance(index_value, datetime):
        return index_value.date()
    if isinstance(index_value, date):
        return index_value
    text = str(index_value).strip()
    if not text:
        return None
    head = text.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None
