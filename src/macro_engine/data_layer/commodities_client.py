"""Oil-market observables behind ``oil_balance_signal`` (Section 6.8, Module 10).

Why this module exists
----------------------
Section 6.8 gives ``oil_balance_signal`` two inputs —
``inventory_change_weekly`` and ``opec_spare_capacity_proxy`` — and names **no
source** for either. ``config/series_registry.yaml`` had no entry, so under
Section 21.1's default rule (*"any input not listed above is BLOCKED by
default"*) both would read as BLOCKED. Measured 2026-09-29, that reading is
**false**: both are reachable through this installation's OpenBB service on the
``commodity`` route family.

This is the **fifth FALSE BLOCK** this repository has caught, after
``ppp_implied_rate`` (D-115/D-117), ``fx_reserves_usd_bn`` (D-118) and the two
EM-vulnerability legs (D-119) — the same D-043 class: a sourcing claim recorded
in a document and never re-measured. The remedy is the same: record the source
and wire it, so the value is *fetched* rather than typed.

The two series, measured 2026-09-29
-----------------------------------
**Inventories** — ``commodity.petroleum_status_report``, ``category=balance_sheet``,
``table=stocks``. This is the EIA Weekly Petroleum Status Report's stock table,
weekly back to **1982-08-20** (2 295 dates). The row the model wants is
``WCESTUS1``, *"Weekly U.S. Ending Stocks excluding SPR of Crude Oil"*, in
**Thousand Barrels**:

* latest observation **2026-09-18 = 426 398** kb
* prior week **2026-09-11 = 423 429** kb
* so the most recent week was a **+2 969 kb build** (inventory rose)

⚠️ **THIS ROUTE RETURNS MANY SYMBOLS IN ONE RESPONSE — 19 of them — AND THE
SYMBOL MUST BE SELECTED BY NAME.** Measured: the ``stocks`` table carries
``WCRSTUS1``, ``WCESTUS1``, ``WCSSTUS1`` (SPR), jet fuel, distillate, residual
and more. ``OpenBBClient.fetch_series`` would collapse them into one date/value
frame and hand back whichever row it saw last; this module therefore goes
through :meth:`OpenBBClient.fetch_records` and filters ``symbol == WCESTUS1``
itself. The symbol column is the whole reason the record-level route exists.

**Spare capacity** — ``commodity.short_term_energy_outlook``, ``table=03d``.
This is the EIA Short-Term Energy Outlook's *World Crude Oil Production* table,
monthly. The series is ``COPS_OPEC``, *"OPEC Total Spare Crude Oil Production
Capacity"*, in **million barrels per day**:

* latest observation **2026-09-01 = 0.02** mb/d
* (0.02 is not a typo — measured live; the STEO carries a near-zero OPEC spare
  figure at this vintage, which is itself the "tight" reading the model reports)

⚠️ **THIS SERIES CARRIES A PROJECTION TAIL AND THE TAIL MUST BE DISCARDED.**
``COPS_OPEC`` runs monthly to **2027-12-01**; the 15 values from 2026-10-01
onward are STEO **forecasts**, not measurements. A "latest value" fetch that
took the last row would report a *projection* as though it were an observation —
the vintage trap D-116 recorded for the IMF ``PPPEX`` series. The client
therefore clips to observations ``<= as_of`` and **counts what it dropped**, so
the disclosure can state how much of the tail was projection.

Why not the ``_R05``/``_ROT`` variants
--------------------------------------
``table=03d`` also carries ``COPS_OPEC_R05`` (*"OPEC **Middle East** Surplus
Crude Oil Production Capacity"*) and ``COPS_OPEC_ROT`` (*"OPEC **Other** Spare
..."*). Both are NARROWER than the total: ``_R05`` is the Middle-East component
and ``_ROT`` the non-Middle-East remainder. Section 6.8 says "OPEC spare
capacity", so the total ``COPS_OPEC`` is the correct series and the two
components are not substitutes. Measured: ``_R05`` = 2.35 and ``_ROT`` = 0.03 at
2027-12-01, summing to the ``COPS_OPEC`` total — which is how the split was
identified rather than assumed.

What this module is NOT
-----------------------
It is not a vintage client. Like ``reserves_client`` and ``world_bank_client``,
it returns the **latest published revision** with its observation date attached
and makes no claim about what was in force on an earlier date. ``alfred_client``
remains the engine's one point-in-time route, and no EIA series implements it.

Transport
---------
This module does **not** open its own HTTP connection. It goes through the
project's own ``OpenBBClient``, which already owns the base URL, the retry
policy and the pinned User-Agent (D-087.25). Re-implementing any of that here
would create a second, silently divergent route to the same host — the exact
shape D-087.25 was written to eliminate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError

logger = logging.getLogger(__name__)

__all__ = [
    "INVENTORY_SOURCE_UNIT",
    "INVENTORY_SYMBOL",
    "SPARE_CAPACITY_SOURCE_UNIT",
    "SPARE_CAPACITY_SYMBOL",
    "CommodityReadError",
    "InventoryReading",
    "SpareCapacityReading",
    "fetch_crude_inventories",
    "fetch_opec_spare_capacity",
]

#: The EIA symbol for weekly U.S. ending stocks of crude oil EXCLUDING the SPR,
#: in Thousand Barrels. Named here so the model's selection and this module's
#: filter cannot drift apart. ``WCRSTUS1`` (including SPR) is a DIFFERENT series
#: that shares the same table; the exclusion is the model's intent (Section
#: 6.8's "inventory" is the commercial stock that reflects supply/demand).
INVENTORY_SYMBOL = "WCESTUS1"

#: The EIA symbol for OPEC total spare crude oil production capacity, in
#: million barrels per day. This is the TOTAL; ``COPS_OPEC_R05`` and
#: ``COPS_OPEC_ROT`` are its Middle-East and Other components (see the module
#: docstring) and are not substitutes.
SPARE_CAPACITY_SYMBOL = "COPS_OPEC"

#: The unit each route returns ``value`` in, as reported by the provider and
#: named here so the model's declared unit and this reading cannot drift.
INVENTORY_SOURCE_UNIT = "thousand_barrels"
SPARE_CAPACITY_SOURCE_UNIT = "million_barrels_per_day"

#: The PPS stock table and the STEO production table are the two routes. Named
#: as constants so the endpoint, the table id and the category travel together
#: with the symbol they select.
_PPS_ENDPOINT = "commodity.petroleum_status_report"
_PPS_PROVIDER = "eia"
_PPS_CATEGORY = "balance_sheet"
_PPS_TABLE = "stocks"

_STEO_ENDPOINT = "commodity.short_term_energy_outlook"
_STEO_PROVIDER = "eia"
_STEO_TABLE = "03d"

#: How many prior years form the seasonal baseline for the inventory deviation.
#: Section 6.8's input comment says *"+/- vs 5yr seasonal avg"*, so this is 5.
#: Named rather than inlined because the deviation's meaning depends on it: a
#: reader must be able to see that "vs seasonal" means "vs the same week in each
#: of the prior five years", not some other window.
_SEASONAL_BASELINE_YEARS = 5


class CommodityReadError(Exception):
    """A commodity fetch failed, or the requested symbol was not present.

    Distinct from ``OpenBBFetchError`` so the model can distinguish *the
    transport failed* (this class) from *the transport worked but the table did
    not contain the symbol* (also this class, but with a different message) —
    both are fatal to the signal, and the message says which happened.
    """


@dataclass(frozen=True)
class InventoryReading:
    """The crude-stock LEVEL, its week-over-week change, and its seasonal gap.

    ``level_thousand_barrels`` is the source's own unit (thousands).

    ``change_weekly_thousand_barrels`` is ``latest - prior``, **signed**: a
    positive number is a BUILD and a negative number is a DRAW. It is ``None`` —
    never ``0.0`` — when the series has fewer than two observations, because a
    zero change reads as "flat", which is an assertion the data would not make.
    This is the *week-over-week* change and is NOT what Section 6.8's
    ``inventory_change_weekly`` means (see ``seasonal_deviation_thousand_barrels``).

    ``seasonal_deviation_thousand_barrels`` is **Section 6.8's
    ``inventory_change_weekly``**: the level *minus* the mean level for the same
    week-of-year over the prior ``seasonal_baseline_years`` years — "+/- vs 5yr
    seasonal avg", in the specification's own words. It is ``None`` when the
    series does not span enough years to form the baseline; a seasonal deviation
    cannot be computed from a short history and is not defaulted to zero.
    ``seasonal_baseline_years`` records how many prior years the baseline
    actually used, so a reader can see the depth of the comparison.
    """

    symbol: str
    level_thousand_barrels: float
    change_weekly_thousand_barrels: float | None
    seasonal_deviation_thousand_barrels: float | None
    seasonal_baseline_years: int
    observation_date: str
    source_unit: str
    observation_count: int


@dataclass(frozen=True)
class SpareCapacityReading:
    """OPEC spare capacity, an OBSERVATION, with the projection tail dropped.

    ``spare_capacity_mbd`` is the latest observation at or before ``as_of``, in
    million barrels per day. ``projection_rows_dropped`` is how many
    future-dated STEO rows were discarded to obtain it — recorded rather than
    hidden, because a reader must be able to see that the series carries
    forecasts and that this module did not use them.
    """

    symbol: str
    spare_capacity_mbd: float
    observation_date: str
    source_unit: str
    observation_count: int
    projection_rows_dropped: int


def fetch_crude_inventories(
    *,
    as_of: date,
    client: OpenBBClient | None = None,
) -> InventoryReading:
    """Fetch the latest weekly crude-stock level and its week-over-week change.

    Selects ``WCESTUS1`` **by symbol** from the PPS ``stocks`` table, orders the
    rows by date, and takes the latest observation and the one before it. Raises
    :class:`CommodityReadError` when the fetch fails, the symbol is absent, or
    there are fewer than two observations (a single point cannot yield the
    week-over-week change the model's input contract requires).

    ``as_of`` clips any row dated after the caller's clock. The PPS series ends
    at a past observation in every measurement so far, but the clip is applied
    for the same reason the STEO one is: a route that later begins carrying a
    forward estimate must not have it silently adopted as a measurement.
    """
    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        records = active.fetch_records(
            provider=_PPS_PROVIDER,
            endpoint=_PPS_ENDPOINT,
            params={"category": _PPS_CATEGORY, "table": _PPS_TABLE},
            series_label="crude_inventories",
        )
    except OpenBBFetchError as exc:
        raise CommodityReadError(f"crude-inventory fetch failed: {exc}") from exc
    finally:
        if own_client:
            active.close()

    selected = [r for r in records if r.get("symbol") == INVENTORY_SYMBOL]
    if not selected:
        present = sorted({str(r.get("symbol")) for r in records})
        raise CommodityReadError(
            f"the stocks table did not contain {INVENTORY_SYMBOL!r} among its "
            f"{len(records)} rows; symbols present: {present}. Refusing rather "
            f"than selecting a neighbouring series by position."
        )

    # Parse and sort by date so `[-1]` is the latest OBSERVATION rather than the
    # last row the provider emitted. The provider returns ascending, but row
    # order is not a documented contract and a reversed response would silently
    # make "latest" mean "oldest".
    parsed: list[tuple[date, float]] = []
    for row in selected:
        when = _parse_date(row.get("date"), context=f"{INVENTORY_SYMBOL} inventory row")
        if when > as_of:
            continue
        value = _parse_value(row.get("value"), context=f"{INVENTORY_SYMBOL} inventory row @ {when}")
        parsed.append((when, value))

    if len(parsed) < 2:
        raise CommodityReadError(
            f"{INVENTORY_SYMBOL} yielded {len(parsed)} usable observation(s) at or "
            f"before {as_of}; at least two are required so the week-over-week "
            f"change is a measurement rather than an assumption."
        )
    parsed.sort(key=lambda pair: pair[0])

    latest_date, latest_value = parsed[-1]
    _, prior_value = parsed[-2]

    seasonal_deviation, baseline_years = _seasonal_deviation(
        parsed, latest_date, latest_value, years=_SEASONAL_BASELINE_YEARS
    )

    return InventoryReading(
        symbol=INVENTORY_SYMBOL,
        level_thousand_barrels=latest_value,
        change_weekly_thousand_barrels=latest_value - prior_value,
        seasonal_deviation_thousand_barrels=seasonal_deviation,
        seasonal_baseline_years=baseline_years,
        observation_date=latest_date.isoformat(),
        source_unit=INVENTORY_SOURCE_UNIT,
        observation_count=len(parsed),
    )


def _seasonal_deviation(
    parsed: list[tuple[date, float]],
    latest_date: date,
    latest_value: float,
    *,
    years: int,
) -> tuple[float | None, int]:
    """``latest - mean(same week-of-year over the prior ``years`` years)``.

    Section 6.8 declares its inventory input as *"barrels, +/- vs 5yr seasonal
    avg"*, so the quantity the model consumes is a **seasonal deviation**, not
    the raw level and not the week-over-week change. This computes it from the
    full weekly history the PPS route returns (measured back to 1982).

    The baseline is the mean of the observations whose **ISO week** matches the
    latest observation's week, one per calendar year, for the ``years`` calendar
    years *preceding* the latest one. ISO week-numbering year is used rather
    than ``date.year`` so the turn of the year does not split one week across
    two "years" — the standard seasonality pitfall this exists to avoid.

    Returns ``(deviation, baseline_years_used)``. The deviation is ``None`` when
    **no** prior year has a matching week (the series is too short), never
    ``0.0``: a zero deviation means "exactly on the seasonal norm", which is a
    real and meaningful reading, so a default of zero would be indistinguishable
    from an uncomputed one. ``baseline_years_used`` is how many of the requested
    years actually contributed, so a thin baseline is visible rather than
    silently accepted.
    """
    latest_week = latest_date.isocalendar()
    by_iso_year: dict[int, float] = {}
    for when, value in parsed:
        if when >= latest_date:
            continue
        iso = when.isocalendar()
        if iso.week == latest_week.week and iso.year != latest_week.year:
            # One observation per ISO year; if a year somehow carries two rows in
            # the same week (it should not, weekly data), the later replaces the
            # earlier and the replacement is counted once.
            by_iso_year[iso.year] = value

    # The `years` ISO years immediately PRECEDING the latest one.
    wanted = {latest_week.year - offset for offset in range(1, years + 1)}
    present = sorted(year for year in wanted if year in by_iso_year)
    if not present:
        return None, 0
    baseline = sum(by_iso_year[year] for year in present) / len(present)
    return latest_value - baseline, len(present)


def fetch_opec_spare_capacity(
    *,
    as_of: date,
    client: OpenBBClient | None = None,
) -> SpareCapacityReading:
    """Fetch OPEC total spare capacity, discarding the projection tail.

    Selects ``COPS_OPEC`` from STEO table ``03d`` and keeps only observations
    **at or before ``as_of``**. The dropped future-dated rows are counted and
    returned, because Section 6.8's input must be an OBSERVATION: the STEO
    genuinely publishes forecasts (measured to 2027-12) and a "latest value"
    fetch that took the last row would report a projection as a measurement —
    the D-116 vintage trap.

    Raises :class:`CommodityReadError` when the fetch fails, the symbol is
    absent, or no observation is at or before ``as_of`` (a real possibility if
    the caller's clock is before the series' first point, in which case there is
    no observation to report — not a zero).
    """
    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        records = active.fetch_records(
            provider=_STEO_PROVIDER,
            endpoint=_STEO_ENDPOINT,
            params={"table": _STEO_TABLE, "symbol": SPARE_CAPACITY_SYMBOL},
            series_label="opec_spare_capacity",
        )
    except OpenBBFetchError as exc:
        raise CommodityReadError(f"OPEC spare-capacity fetch failed: {exc}") from exc
    finally:
        if own_client:
            active.close()

    selected = [r for r in records if r.get("symbol") == SPARE_CAPACITY_SYMBOL]
    if not selected:
        present = sorted({str(r.get("symbol")) for r in records})
        raise CommodityReadError(
            f"STEO table {_STEO_TABLE} did not contain {SPARE_CAPACITY_SYMBOL!r} "
            f"among its {len(records)} rows; symbols present: {present}."
        )

    observed: list[tuple[date, float]] = []
    projection_rows_dropped = 0
    for row in selected:
        when = _parse_date(row.get("date"), context=f"{SPARE_CAPACITY_SYMBOL} STEO row")
        if when > as_of:
            projection_rows_dropped += 1
            continue
        value = _parse_value(row.get("value"), context=f"{SPARE_CAPACITY_SYMBOL} STEO row @ {when}")
        observed.append((when, value))

    if not observed:
        raise CommodityReadError(
            f"{SPARE_CAPACITY_SYMBOL} had no observation at or before {as_of} "
            f"({projection_rows_dropped} future-dated projection rows were present "
            f"but discarded). A projected value is not an observation; there is "
            f"nothing to report rather than a zero to invent."
        )
    observed.sort(key=lambda pair: pair[0])

    latest_date, latest_value = observed[-1]
    return SpareCapacityReading(
        symbol=SPARE_CAPACITY_SYMBOL,
        spare_capacity_mbd=latest_value,
        observation_date=latest_date.isoformat(),
        source_unit=SPARE_CAPACITY_SOURCE_UNIT,
        observation_count=len(observed),
        projection_rows_dropped=projection_rows_dropped,
    )


def _parse_date(raw: object, *, context: str) -> date:
    """Parse a provider date into a ``datetime.date``.

    The two commodity routes were measured returning ISO ``YYYY-MM-DD`` strings;
    the parse is explicit rather than ``fromisoformat`` alone so a future
    timestamp-bearing value (``2026-09-18T00:00:00``) is handled by taking the
    date part, and a genuinely unparseable value raises with the context rather
    than a bare ``ValueError``.
    """
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        raise CommodityReadError(
            f"{context}: empty date. A row without a date cannot be ordered and is refused."
        )
    head = text.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError as exc:
        raise CommodityReadError(f"{context}: unparseable date {raw!r}.") from exc


def _parse_value(raw: object, *, context: str) -> float:
    """Coerce a provider value to a finite float, or refuse.

    A missing or non-finite value is refused rather than repaired to zero: zero
    is a legitimate inventory level and a legitimate spare-capacity figure, so a
    repaired zero would be indistinguishable from a real one (the D-078 class —
    a null that travels as a value).
    """
    if raw is None:
        raise CommodityReadError(
            f"{context}: value is null. Refusing rather than treating a missing value as zero."
        )
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise CommodityReadError(f"{context}: value {raw!r} is not numeric.") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise CommodityReadError(
            f"{context}: value {raw!r} is non-finite; a non-finite observation is never repaired."
        )
    return value
