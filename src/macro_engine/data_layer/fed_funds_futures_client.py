"""Fed-funds-futures-implied policy path — the Section 22.5 data leg.

Why this module exists
----------------------
``AGENTS.md`` Section 22.5 obligates Phase 5+ to **REPLACE**
``derive_market_implied_policy_path`` with *"a real Fed-funds-futures-implied
probability distribution (Section 4/16's original intent)"*. Section 16's own
comment hedged the feasibility in the specification's words:

    "a full Fed-funds-futures-based implied path is Phase 5+, requires a futures
     data source OpenBB may or may not expose cleanly; document as a known
     limitation if not"

**Measured 2026-10-10: the source exists on this installation.** The route is
``derivatives.futures.curve`` with ``symbol="ZQ"`` and ``provider="yfinance"``,
and it returns the **30-Day Federal Funds futures** term structure. The earlier
"needs data" reading was wrong because the D-108 route inventory had been
grepped for ``forward|swap|basis`` and never for ``futur``.

The contract, and why it is the right one
-----------------------------------------
A 30-Day Fed Funds future is the **only** futures contract that settles directly
to the policy rate: its final settlement price is
``100 - <the contract month's average effective federal funds rate>``. So the
market-implied average policy rate for that month is

    implied_rate = settlement_offset - price

with ``settlement_offset = 100`` from config (LAW 1). **Verified three ways
2026-10-10:** the front contract (2026-10) implied **3.88%**, which EQUALS the
measured ``DFF`` and ``EFFR`` (both 3.880) and sits INSIDE the 3.75-4.00% target
range (``DFEDTARL``/``DFEDTARU``).

What this gives that the proxy could not
----------------------------------------
The proxy was ONE number — a single point on the short end, which cannot
represent a sloped path. The futures curve is a **path**: measured 2026-10-10 it
rose monotonically from 3.88% (2026-10) to 4.69% (2028-01). Section 22.5 wanted
exactly this, because the horizon mismatch it set out to fix is a statement
about the path's SHAPE.

⚠️ The source's own defect, and the guard it forces
---------------------------------------------------
**Six of the sixteen expirations the route returned carry a price near 47-48
instead of 95-96**, implying a ~52% policy rate:

    2027-02 (47.89)  2027-04 (47.74)  2027-06 (47.80)
    2027-09 (47.64)  2027-10 (47.68)  2027-12 (47.68)

This is source corruption, not a market view — a 52% implied policy rate is
impossible against a 4% target range. It is **deterministic**: the same six rows
appeared on three separate calls (min price 47.64, max 96.12 every time), so it
will not fix itself and is not a transient network artifact.

A reader that trusted the route would publish a **52% market-implied policy
path** — the "plausible-looking wrong number" class this project treats as
SEV-1 (Section 21.0). This module therefore **REJECTS** each implausible
expiration rather than clamping it (clamping would fabricate a value inside the
band while the source said something else) and **counts what it dropped**, so
the disclosure can state how much of the curve was corrupt.

Run the probe that established all of the above:
    uv run python tools/probe_fed_funds_futures.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError

__all__ = [
    "FUTURES_ROUTE_ENDPOINT",
    "FedFundsFuturesCurve",
    "FuturesCurveError",
    "FuturesExpiration",
    "fetch_fed_funds_futures_curve",
]

#: The OpenBB route family. A CONSTANT rather than a config leaf because it is
#: the route's PATH (part of the transport contract, like the FRED endpoint), not
#: a tunable. The symbol and provider, which a deployment may change, ARE leaves
#: (`market_implied_futures.symbol_value` / `.provider_value`).
#:
#: PUBLIC (no leading underscore) because the model layer cites it in
#: ``data_provenance`` so a reader can re-run the exact read — LAW 2: one
#: canonical spelling of the route, not a second literal in the consumer.
FUTURES_ROUTE_ENDPOINT = "derivatives.futures.curve"

#: The months per year used to turn an expiration date into a horizon and to
#: truncate the published path. A calendar constant, not a model parameter.
_MONTHS_PER_YEAR = 12


class FuturesCurveError(Exception):
    """The futures curve could not be read, or was too damaged to publish.

    Distinct from ``OpenBBFetchError`` so a caller can tell *the transport
    failed* from *the transport worked but the curve was unusable* — the same
    split ``CommodityReadError`` draws. Both are fatal to the path; the message
    says which happened.
    """


@dataclass(frozen=True)
class FuturesExpiration:
    """One futures expiration and the policy rate it implies.

    ``price`` is the contract's quoted price (the source's own unit — index
    points, ``100 - rate``). ``implied_rate_pct`` is
    ``settlement_offset - price``, in **percent** — the average effective funds
    rate the market prices for ``expiration``'s contract month.

    ``months_ahead`` is the horizon from the caller's ``as_of`` to the contract
    month, **signed**: negative would mean an expiration in the past, which the
    loader never emits (it filters to the future), so a negative value here is a
    defect rather than stale data.

    ``raw_price`` is carried alongside for exactly one purpose: an auditable
    trace from the published rate back to the number the source sent, so a
    reader can re-derive the identity rather than trusting it.
    """

    expiration: str
    price: float
    implied_rate_pct: float
    months_ahead: int
    raw_price: float


@dataclass(frozen=True)
class FedFundsFuturesCurve:
    """The fed-funds-futures-implied policy path, with its own audit trail.

    ``expirations`` is ordered by ``months_ahead`` ASCENDING and holds only the
    expirations that passed the plausibility band.

    ``rows_returned`` / ``rows_rejected`` / ``rows_dropped_past`` are all
    recorded rather than summarised into one "n" — the whole reason this object
    exists rather than a bare dict is that the source's corruption must be
    **visible**, and three different causes of a missing row (corrupt,
    past-dated, non-finite) must be distinguishable after the fact.

    ``near_rate_pct`` is the FRONT expiration's implied rate: Section 16.2's Q6
    market leg for the CURRENT period, which is what lets the gap be computed
    over one horizon instead of the proxy's horizon mismatch.
    """

    symbol: str
    provider: str
    settlement_offset: float
    as_of: str
    expirations: tuple[FuturesExpiration, ...]
    rows_returned: int
    rows_rejected: int
    rows_dropped_past: int
    rejected_detail: tuple[str, ...]
    source_retrieved_at: str

    @property
    def has_path(self) -> bool:
        """Whether enough plausible expirations survive to call this a PATH."""
        return len(self.expirations) >= get_settings().market_implied_futures.min_expirations

    @property
    def near_rate_pct(self) -> float:
        """The front expiration's implied rate — the CURRENT-period market leg."""
        if not self.expirations:
            raise FuturesCurveError(
                "no plausible expiration survives, so there is no near rate. "
                "A caller must check `has_path` before reading this."
            )
        return self.expirations[0].implied_rate_pct

    @property
    def far_rate_pct(self) -> float:
        """The furthest expiration's implied rate — the far end of the path."""
        if not self.expirations:
            raise FuturesCurveError("no plausible expiration survives, so there is no far rate.")
        return self.expirations[-1].implied_rate_pct

    @property
    def path_slope_bp(self) -> float:
        """Far minus near, in BASIS POINTS. Positive = the market prices HIKES.

        This is the quantity the proxy structurally could not produce, and the
        reason Section 22.5 wanted the replacement: a single yield has no slope.
        In ``bp`` so it is comparable with the gap's own unit.
        """
        if len(self.expirations) < 2:
            raise FuturesCurveError(
                "a slope needs at least two plausible expirations; this curve "
                "has fewer, so `has_path` is False and no slope exists."
            )
        return (self.far_rate_pct - self.near_rate_pct) * 100.0


def _months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``, signed.

    Month arithmetic rather than 30-day division: a contract month is a calendar
    month, and ``(end.year - start.year) * 12 + (end.month - start.month)`` is
    the definition a desk uses. Dividing day counts by 30.44 would put a
    month-end expiration in the wrong month for part of every year.
    """
    return (end.year - start.year) * _MONTHS_PER_YEAR + (end.month - start.month)


def _parse_expiration(raw: object) -> date | None:
    """Parse the route's ``expiration`` field, which is ``YYYY-MM``.

    Returns ``None`` rather than raising so a single malformed row is COUNTED as
    rejected instead of aborting a curve that is otherwise usable — the same
    per-row tolerance the plausibility filter applies.
    """
    text = str(raw).strip()
    if not text:
        return None
    # The route emits "YYYY-MM"; tolerate a full date by truncating to the month.
    parts = text.split("-")
    if len(parts) < 2:
        return None
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (1 <= month <= 12):
        return None
    try:
        return date(year, month, 1)
    except ValueError:
        return None


def _contract_month_end(expiration: date) -> date:
    """Last day of the expiration's month, used for the horizon comparison."""
    if expiration.month == 12:
        next_month = date(expiration.year + 1, 1, 1)
    else:
        next_month = date(expiration.year, expiration.month + 1, 1)
    return next_month.fromordinal(next_month.toordinal() - 1)


def fetch_fed_funds_futures_curve(
    *,
    as_of: date,
    client: OpenBBClient | None = None,
) -> FedFundsFuturesCurve:
    """Read the ZQ curve and return the policy path it implies.

    Every row is put through three filters, and **each has its own counter**
    because the three causes mean different things:

    1. **Past-dated** — an expiration whose contract month has already ended
       carries no forward information. Counted in ``rows_dropped_past``.
    2. **Non-finite or unparseable** — a price of ``nan`` fails EVERY comparison,
       so a filter written as ``if not (lo <= rate <= hi): reject`` would let it
       through if the band test short-circuited (D-078's class). Checked first,
       explicitly. Counted in ``rows_rejected``.
    3. **Implausible** — outside the config band. This is the filter that exists
       for the measured corruption: six real rows imply a ~52% policy rate.
       Counted in ``rows_rejected`` with the row named in ``rejected_detail``.

    Raises :class:`FuturesCurveError` when the fetch fails, the response has no
    usable rows, or fewer than ``min_expirations`` plausible expirations survive.
    It does NOT raise for a merely-degraded curve: a curve with some corrupt rows
    is still informative, and the rejections are published rather than hidden.
    """
    settings = get_settings().market_implied_futures
    symbol = settings.symbol
    provider = settings.provider

    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        records = active.fetch_records(
            provider=provider,
            endpoint=FUTURES_ROUTE_ENDPOINT,
            params={"symbol": symbol},
            series_label=f"fed_funds_futures_curve:{symbol}",
        )
    except OpenBBFetchError as exc:
        raise FuturesCurveError(
            f"fed-funds-futures curve fetch failed for {symbol} via {provider} "
            f"on {FUTURES_ROUTE_ENDPOINT}: {exc}"
        ) from exc
    finally:
        if own_client:
            active.close()

    if not records:
        raise FuturesCurveError(
            f"the {FUTURES_ROUTE_ENDPOINT} route returned no records for {symbol}. An "
            f"empty curve is a failed read, never a flat path."
        )

    offset = settings.settlement_offset
    low, high = settings.plausible_rate_min, settings.plausible_rate_max
    accepted: list[FuturesExpiration] = []
    rejected_detail: list[str] = []
    rows_rejected = 0
    rows_dropped_past = 0
    source_retrieved_at = ""

    for record in records:
        expiration = _parse_expiration(record.get("expiration"))
        if expiration is None:
            rows_rejected += 1
            rejected_detail.append(f"unparseable expiration {record.get('expiration')!r}")
            continue

        raw_price = record.get("price")
        try:
            price = float(raw_price)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            rows_rejected += 1
            rejected_detail.append(f"{expiration:%Y-%m}: non-numeric price {raw_price!r}")
            continue

        # FINITENESS FIRST. A `nan` price makes `offset - price` nan, and every
        # band comparison against nan is False — so a naive `if low <= r <= high`
        # rejects it by luck, while a filter written the other way round would
        # admit it. D-078: guard the value, not the comparison's good fortune.
        if not math.isfinite(price):
            rows_rejected += 1
            rejected_detail.append(f"{expiration:%Y-%m}: non-finite price {price!r}")
            continue

        implied_rate = offset - price
        if not math.isfinite(implied_rate):
            rows_rejected += 1
            rejected_detail.append(
                f"{expiration:%Y-%m}: non-finite implied rate {implied_rate!r} from price {price!r}"
            )
            continue

        # A contract month that has already ENDED carries no forward
        # information. Compared on the month END so the current month's
        # contract (still trading) is kept.
        if _contract_month_end(expiration) < as_of:
            rows_dropped_past += 1
            continue

        if not (low <= implied_rate <= high):
            rows_rejected += 1
            rejected_detail.append(
                f"{expiration:%Y-%m}: implied rate {implied_rate:.2f}% outside the "
                f"plausible band [{low:.2f}, {high:.2f}] (price {price:.2f})"
            )
            continue

        accepted.append(
            FuturesExpiration(
                expiration=f"{expiration.year:04d}-{expiration.month:02d}",
                price=price,
                implied_rate_pct=implied_rate,
                months_ahead=_months_between(as_of, expiration),
                raw_price=price,
            )
        )

        retrieved = record.get("retrieved_at") or record.get("date")
        if retrieved and not source_retrieved_at:
            source_retrieved_at = str(retrieved)

    accepted.sort(key=lambda item: (item.months_ahead, item.expiration))

    if not accepted:
        raise FuturesCurveError(
            f"no plausible expiration survived for {symbol}: {len(records)} rows "
            f"returned, {rows_rejected} rejected, {rows_dropped_past} past-dated. "
            f"Rejections: {'; '.join(rejected_detail[:6])}"
        )

    if len(accepted) < settings.min_expirations:
        raise FuturesCurveError(
            f"only {len(accepted)} plausible expiration(s) survived for {symbol}, "
            f"below the configured floor of {settings.min_expirations}. A single "
            f"point is not a path — it is what the proxy this replaces already "
            f"was — so refusing is correct. Rejections: {'; '.join(rejected_detail[:6])}"
        )

    return FedFundsFuturesCurve(
        symbol=symbol,
        provider=provider,
        settlement_offset=offset,
        as_of=as_of.isoformat(),
        expirations=tuple(accepted),
        rows_returned=len(records),
        rows_rejected=rows_rejected,
        rows_dropped_past=rows_dropped_past,
        rejected_detail=tuple(rejected_detail),
        source_retrieved_at=source_retrieved_at or datetime.now(UTC).isoformat(),
    )
