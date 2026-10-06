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

Gold drivers (the second household, added by ``gold_driver_attribution``)
-------------------------------------------------------------------------
Appendix D's ``GoldDriverInputs`` names three inputs and no source. Two are LIVE
on the ``fred`` route (``DFII10`` real yield, ``VIXCLS`` crisis level, both in a
section further down this file) and one — ``central_bank_net_purchases_trend`` —
is a **measured, CONFIRMED block**: the World Bank registers ``FI.RES.GOLD.CD``
as *"Gold Holdings at London market price"* but it returns **no data points** and
carries no ``lastupdated``, so it is a registered-but-empty indicator rather than
a source. That leg is published as MANUAL with a discriminating disclosure.

⚠️ **BOTH LIVE GOLD LEGS SHARE ONE PROVIDER (FRED).** Their independence count is
ONE family, not two — the model discloses this rather than inflating its own
confidence from a leg count.

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
from datetime import date, datetime
from typing import Any

from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError

logger = logging.getLogger(__name__)

__all__ = [
    "BASIS_POINTS_PER_PERCENT",
    "INVENTORY_SOURCE_UNIT",
    "INVENTORY_SYMBOL",
    "REAL_YIELD_SOURCE_UNIT",
    "REAL_YIELD_SYMBOL",
    "SPARE_CAPACITY_SOURCE_UNIT",
    "SPARE_CAPACITY_SYMBOL",
    "VIX_SOURCE_UNIT",
    "VIX_SYMBOL",
    "CommodityReadError",
    "InventoryReading",
    "RealYieldReading",
    "SpareCapacityReading",
    "VixReading",
    "fetch_crude_inventories",
    "fetch_opec_spare_capacity",
    "fetch_real_yield",
    "fetch_vix_level",
    "real_yield_change_bp",
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
    """Parse a provider date into a ``datetime.date`` — ALWAYS a real date.

    The two commodity routes were measured returning ISO ``YYYY-MM-DD`` strings;
    the parse is explicit rather than ``fromisoformat`` alone so a future
    timestamp-bearing value (``2026-09-18T00:00:00``) is handled by taking the
    date part, and a genuinely unparseable value raises with the context rather
    than a bare ``ValueError``.

    **The type-dispatch order below is load-bearing (R-5).** This helper
    originally led with ``if isinstance(raw, date): return raw`` — which is the
    ``datetime``-is-a-``date`` trap fixed in ``openbb_client.to_observation_date``
    (R-4), repeated in a sibling module. ``pd.Timestamp`` and ``datetime`` are
    BOTH ``date`` subclasses, so that branch returned them unchanged and the
    ``-> date`` contract was violated. It is reachable, not theoretical:
    ``OpenBBClient._coerce_records`` converts a DataFrame-shaped payload with
    ``to_dict(orient="records")``, and a datetime column becomes ``Timestamp``
    values (measured). Those rows reach this function at the two
    ``fetch_records`` call sites (inventories, spare capacity).

    The two measured consequences of letting one through:

    * ``when > as_of`` raises ``TypeError: Cannot compare Timestamp with
      datetime.date`` — an uncaught crash carrying a pandas message instead of
      this module's own ``CommodityReadError``; and
    * ``observation_date=when.isoformat()`` publishes ``'2026-09-18T00:00:00'``
      rather than ``'2026-09-18'`` — a wrong-shape provenance fact.

    So the most-derived type is tested FIRST and collapsed via ``.date()``,
    exactly as ``openbb_client``/``snapshot_builder`` do.
    """
    # ``pd.Timestamp`` is checked before ``date`` because it subclasses
    # ``datetime``, which subclasses ``date`` -- testing the broad type first is
    # what let the defect through.
    #
    # Order: collapse a bare ``datetime`` (and ``pd.Timestamp``, which IS one),
    # then any other date-LIKE value that exposes ``.date()``, then the plain
    # ``date``, then a string. Nothing here imports pandas/numpy: this module
    # deliberately owns no transport and no frame library, so the check is by
    # capability rather than by type.
    #
    # ``np.datetime64`` — the measured carrier from a pandas round-trip — is NOT
    # an example of the ``.date()`` branch. Measured: it exposes no ``.date``
    # attribute at all, so it falls through to the STRING parse below, where
    # ``str()`` renders the bare date. An earlier version of this comment named
    # it as the ``.date()`` example, which would have sent a reader looking for a
    # branch that never runs for it. The string fallback is what makes it work,
    # which is why the test asserts the OUTCOME rather than the branch.
    if isinstance(raw, datetime):
        return raw.date()
    if not isinstance(raw, date):
        # A date-like carrier that exposes ``.date()``. NOTE: ``np.datetime64``
        # is NOT one of them — measured, it has no ``.date`` attribute — so it
        # reaches the string parse below instead; see the block comment above.
        collapse = getattr(raw, "date", None)
        if callable(collapse):
            collapsed = collapse()
            if isinstance(collapsed, date):
                return collapsed
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


# =============================================================================
# Gold drivers (Section 6.8's Module 10, Appendix D — ``gold_driver_attribution``)
# =============================================================================
#
# Appendix D's ``GoldDriverInputs`` declares three fields and names no source:
#
#     real_yield_change_bp            PRIMARY driver, 10yr TIPS yield change
#     central_bank_net_purchases_trend  "rising" | "flat" | "falling"
#     crisis_indicator                bool — VIX spike / credit blowout
#
# Under Section 21.1's default rule all three would read as BLOCKED. MEASURED
# 2026-09-27, the first TWO are LIVE through this installation's ``fred`` route
# and the third is GENUINELY BLOCKED — and the difference matters, because this
# is the first increment where the honest answer is a MIX rather than "all live"
# (D-120) or "one confirmed block" (D-119).
#
# The two live legs — measured 2026-09-27
# ----------------------------------------
# **Real yield** — ``economy.fred_series``, ``symbol=DFII10``, *"Market Yield on
# U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment
# Basis, Inflation-Indexed"* — the 10-Year TIPS yield, in PER CENT:
#
#   * 5 937 observations; latest **2026-09-24 = 2.85** (prior 2026-09-23 = 2.76)
#
# **Crisis indicator** — ``economy.fred_series``, ``symbol=VIXCLS``, the CBOE
# Volatility Index (a LEVEL, in index points, not a percentage):
#
#   * 9 279 observations; latest **2026-09-22 = 14.21**
#
# ⚠️ **THE TWO LEGS ARE THE *SAME* PROVIDER, WHICH IS A DISCLOSURE, NOT A
# DETAIL.** Both come from FRED, so their ``source_independence_count`` is ONE
# family even when both are fetched. A model that counted "two legs fetched" as
# two independent sources would overstate its own confidence; the model passes
# the honest count and the docstring says why.
#
# The blocked leg — MEASURED, not inherited
# -----------------------------------------
# ``central_bank_net_purchases_trend`` is a DISCRETE trend label ("rising" /
# "flat" / "falling") over central-bank net gold purchases. Unlike the five FALSE
# blocks this repository has caught, this one was PROBED and CONFIRMED, so it is
# the **second CONFIRMED block** (after ``usd_denominated_debt_share``, D-119) —
# and it is confirmed for a subtler reason than "no such series":
#
#   * The World Bank DOES publish ``FI.RES.GOLD.CD`` in its indicator catalogue
#     (*"Gold Holdings at London market price (US$ end period)"*) — it appears in
#     the **29 544-entry** catalogue listing (measured 2026-09-27 via
#     ``api.worldbank.org/v2/indicator``), so a name-grep finds it and calls it a
#     source. **But the DATA route refuses it:** requesting
#     ``/country/USA/indicator/FI.RES.GOLD.CD`` returns message **id=175
#     "The indicator was not found. It may have been deleted or archived."**,
#     with no rows at all — for ``USA`` and for the ``WLD`` aggregate alike.
#     **"In the catalogue" and "serves data" are DIFFERENT claims**, and this
#     indicator satisfies only the first. (A working control, ``FI.RES.TOTL.CD``,
#     returns populated points from the same route and the same caller.)
#   * The client's own error for this case names a missing ``lastupdated`` date —
#     that is the SYMPTOM the client detects, not the cause: the
#     ``/indicator/`` metadata route carries no ``lastupdated`` for a *working*
#     indicator either (measured: ``FI.RES.TOTL.CD`` also reports
#     ``lastupdated=None`` there). The decisive evidence is the data route's
#     id-175 refusal, which ``scripts/live_gold_driver_check.py`` section 2
#     re-measures on every run.
#   * ``FI.RES.TOTL.GD.ZS`` is **not a valid indicator id at all** — it is absent
#     from the catalogue and the API rejects the id — so it is not a fallback
#     either.
#   * Even had ``FI.RES.GOLD.CD`` carried data, it is a **USD VALUE at London
#     market price**, not a physical tonnage and not a NET PURCHASE flow: a rise
#     in it would conflate a price move with a buying decision. Deriving a
#     "purchases trend" from it would be a category error, which the model's
#     docstring records rather than silently performing.
#
# So the leg is published as a MANUAL input with a discriminating disclosure, and
# the model's confidence prices that: a caller-supplied trend is not a fetched
# one, and the published number says so.

#: The FRED symbol for the 10-Year TIPS real yield, in PER CENT.
REAL_YIELD_SYMBOL = "DFII10"

#: The FRED symbol for the CBOE Volatility Index (a LEVEL in index points).
VIX_SYMBOL = "VIXCLS"

#: The unit each route returns ``value`` in, named so the model's declared unit
#: and this reading cannot drift apart. FRED serves both series in the units the
#: provider publishes; neither is converted here.
REAL_YIELD_SOURCE_UNIT = "percent"
VIX_SOURCE_UNIT = "index_points"

#: The FRED route both legs go through. Named as a constant so the provider and
#: the endpoint travel together — and so the model can state, in one place, that
#: the two legs share a provider (the independence disclosure above).
_FRED_ENDPOINT = "economy.fred_series"
_FRED_PROVIDER = "fred"


@dataclass(frozen=True)
class RealYieldReading:
    """A TIPS real-yield observation, plus the prior point needed for a CHANGE.

    ``yield_percent`` is the level the provider publishes (PER CENT), NOT the
    change. The change is computed by :func:`real_yield_change_bp`, because
    Appendix D's input is a *change in basis points* and the conversion from
    percentage-point levels to basis points is a claim that should be visible
    (D-118's dead-constant lesson) rather than implicit in the fetch.

    ``prior_observation_date`` / ``prior_yield_percent`` are ``None`` — never
    ``0.0`` — when the series carries fewer than two observations, because a
    fabricated zero prior would make a CHANGE read as a LEVEL (the D-078 class).
    """

    symbol: str
    observation_date: str
    yield_percent: float
    prior_observation_date: str | None
    prior_yield_percent: float | None
    source_unit: str = REAL_YIELD_SOURCE_UNIT
    observation_count: int = 0


@dataclass(frozen=True)
class VixReading:
    """A VIX observation — the level, in index points, at the as-of date."""

    symbol: str
    observation_date: str
    level: float
    source_unit: str = VIX_SOURCE_UNIT
    observation_count: int = 0


#: Basis points per percentage point. Named because Appendix D's input is in bp
#: while the FRED series is in per cent; the conversion is a multiplication by
#: this constant, which is the D-118 lesson applied (a conversion the reader can
#: find, not a magic 100 inlined at the call site).
BASIS_POINTS_PER_PERCENT = 100.0


def fetch_real_yield(
    *,
    as_of: date,
    client: OpenBBClient | None = None,
) -> RealYieldReading:
    """Fetch the latest 10-Year TIPS real yield at or before ``as_of``.

    Returns a :class:`RealYieldReading` carrying the latest observation AND the
    one before it, because Appendix D's input is a change. The series is clipped
    to observations at or before ``as_of`` so a caller controlling the as-of date
    gets a deterministic answer — the O-134 lesson (a test whose verdict depends
    on the wall clock is a clock, not a test) applied to the fetch itself.

    Raises :class:`CommodityReadError` when the transport fails, the series is
    empty, the frame lacks the client's tidy ``date``/``value`` columns, or no
    observation falls at or before ``as_of``.
    """
    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        frame = active.fetch_series(
            provider=_FRED_PROVIDER,
            endpoint=_FRED_ENDPOINT,
            params={"symbol": REAL_YIELD_SYMBOL},
            series_label="gold_real_yield",
        )
    except OpenBBFetchError as exc:
        raise CommodityReadError(
            f"real-yield series {REAL_YIELD_SYMBOL} could not be read: {exc}"
        ) from exc
    finally:
        if own_client:
            active.close()

    observed = _observed_pairs(
        frame,
        symbol=REAL_YIELD_SYMBOL,
        as_of=as_of,
        label="real-yield",
    )
    if not observed:
        raise CommodityReadError(
            f"real-yield series {REAL_YIELD_SYMBOL} had no observation at or "
            f"before {as_of.isoformat()}."
        )

    latest_date, latest_value = observed[-1]
    if len(observed) >= 2:
        prior_date, prior_value = observed[-2]
        prior_iso: str | None = prior_date.isoformat()
        prior_val: float | None = prior_value
    else:
        prior_iso = None
        prior_val = None

    return RealYieldReading(
        symbol=REAL_YIELD_SYMBOL,
        observation_date=latest_date.isoformat(),
        yield_percent=latest_value,
        prior_observation_date=prior_iso,
        prior_yield_percent=prior_val,
        observation_count=len(observed),
    )


def fetch_vix_level(
    *,
    as_of: date,
    client: OpenBBClient | None = None,
) -> VixReading:
    """Fetch the latest CBOE VIX level at or before ``as_of``.

    The VIX is a LEVEL in index points (not a percentage), and it is the raw
    material for Appendix D's ``crisis_indicator``. This function returns the
    level; the THRESHOLD that turns a level into a boolean is a model decision
    and lives in config, not here — so a reader can find the number that makes
    the indicator fire without reading a fetch (the same split the oil client
    uses between a reading and a threshold).

    Raises :class:`CommodityReadError` on the same conditions as
    :func:`fetch_real_yield`.
    """
    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        frame = active.fetch_series(
            provider=_FRED_PROVIDER,
            endpoint=_FRED_ENDPOINT,
            params={"symbol": VIX_SYMBOL},
            series_label="gold_crisis_vix",
        )
    except OpenBBFetchError as exc:
        raise CommodityReadError(f"VIX series {VIX_SYMBOL} could not be read: {exc}") from exc
    finally:
        if own_client:
            active.close()

    observed = _observed_pairs(
        frame,
        symbol=VIX_SYMBOL,
        as_of=as_of,
        label="VIX",
    )
    if not observed:
        raise CommodityReadError(
            f"VIX series {VIX_SYMBOL} had no observation at or before {as_of.isoformat()}."
        )

    latest_date, latest_value = observed[-1]
    return VixReading(
        symbol=VIX_SYMBOL,
        observation_date=latest_date.isoformat(),
        level=latest_value,
        observation_count=len(observed),
    )


def real_yield_change_bp(reading: RealYieldReading) -> float | None:
    """The change in the TIPS real yield, in BASIS POINTS, or ``None``.

    Appendix D's ``real_yield_change_bp`` is *"10yr TIPS yield change"* — a
    CHANGE, in basis points. The FRED series reports LEVELS in per cent, so this
    performs the conversion explicitly:

        change_bp = (latest_percent - prior_percent) * BASIS_POINTS_PER_PERCENT

    Returns ``None`` when the reading carries no prior observation, because a
    change from a fabricated zero prior is not a change (D-078's class). The
    caller decides whether that absence is fatal — the same split the oil model
    uses for its two legs.
    """
    if reading.prior_yield_percent is None:
        return None
    return (reading.yield_percent - reading.prior_yield_percent) * BASIS_POINTS_PER_PERCENT


def _observed_pairs(
    frame: Any,
    *,
    symbol: str,
    as_of: date,
    label: str,
) -> list[tuple[date, float]]:
    """Reduce a tidy ``date``/``value`` frame to sorted pairs at or before ``as_of``.

    Shared by both gold legs so the clipping rule is stated once. Both the
    ordering and the clip matter, and for different reasons:

    * **Ordering** — ``iloc[-1]`` must be the latest OBSERVATION, not the last
      row the provider happened to emit. FRED returns ascending order, but the
      sort is cheap and a reversed response would silently turn "latest" into
      "oldest".
    * **Clip** — an observation dated after ``as_of`` is excluded, matching the
      oil client's projection-tail discipline. FRED series carry no forecast
      tail, but a caller passing an as-of in the past must get the answer that
      was true then, not the newest row.
    """
    if frame is None or getattr(frame, "empty", True):
        raise CommodityReadError(f"{label} series {symbol} returned no observations.")
    if "date" not in frame.columns or "value" not in frame.columns:
        raise CommodityReadError(
            f"{label} series {symbol} returned an unexpected frame shape "
            f"(columns: {sorted(frame.columns)}); expected the client's tidy "
            "`date`/`value` columns. Refusing rather than guessing which column "
            "is the value."
        )

    cleaned = frame.loc[:, ["date", "value"]].dropna(subset=["value"])
    if cleaned.empty:
        raise CommodityReadError(f"{label} series {symbol} returned only missing values.")

    pairs: list[tuple[date, float]] = []
    for raw_date, raw_value in zip(
        cleaned["date"].tolist(), cleaned["value"].tolist(), strict=True
    ):
        when = _parse_date(raw_date, context=f"{symbol} {label} row")
        if when > as_of:
            continue
        pairs.append((when, _parse_value(raw_value, context=f"{symbol} {label} row @ {when}")))
    pairs.sort(key=lambda item: item[0])
    return pairs


# =========================================================================
# Module 10.3 — the metals complex (copper / iron ore / aluminum)
#
# Section 21.1 (``AGENTS.md:5395``) tags these three inputs
# **LIVE/BLOCKED**: *"Copper & aluminum via IBKR/yfinance futures; iron ore
# has no clean free source — likely BLOCKED, document"*. Section 21.4's
# Loophole Ledger repeats it as item 8: *"Iron ore prices — no clean free
# source"*.
#
# MEASURED 2026-09-27: the whole trio is **LIVE**, and the block is the
# repository's **SEVENTH FALSE BLOCK** (D-043's class, after
# ``ppp_implied_rate`` x2, ``fx_reserves_usd_bn``, the two EM-vulnerability
# legs, the two oil legs and the gold real-yield/VIX pair). The model's own
# docstring records it; this comment records the MEASUREMENT.
#
#   * **The deciding route is FRED ``economy.fred_series``**, the SAME route the
#     gold legs already use — no new endpoint, no new OpenBB command. The
#     authority's IBKR/yfinance suggestion was not needed and was NOT taken: a
#     futures quote is a different estimand from the IMF benchmark price, and
#     the FRED series carry a documented monthly vintage.
#   * **All three symbols resolve through ``fred_search`` with identical
#     semantics** (measured, not assumed): ``PCOPPUSDM`` / ``PIORECRUSDM`` /
#     ``PALUMUSDM`` are each *"Global price of <metal>"*, **U.S. Dollars per
#     Metric Ton**, **Monthly**, source **IMF Primary Commodity Prices**,
#     last observation **2026-07-01**. The unit is read FROM THE PROVIDER'S
#     OWN METADATA (a ``*USDM`` suffix means monthly USD-per-metric-ton; the
#     search result claiming "USD per pound" for copper is WRONG and would have
#     been the D-106 unit trap).
#   * **The control is ``DCOILWTICO``, from the same route and caller.** It
#     returns 2 926 rows over 2015-2026; each metals leg returns 139 rows over
#     the same window. A probe with NO working control would not have been
#     evidence (the D-121 lesson).
#   * **The spec's ``*_change_pct`` inputs are DERIVED, not published.** No
#     FRED series publishes the percent change, so the client differences the
#     two most recent monthly vintages — the same shape as the gold real-yield
#     leg, and the reason a reading carries BOTH the latest and prior level.
#
# A reading is a CHANGE in PER CENT (not a level), because the specification's
# own field names say ``_change_pct``; the level is carried too so a consumer
# can see what the change was taken FROM.

#: The FRED symbols for the three metals, each a monthly benchmark price in
#: U.S. Dollars per Metric Ton (IMF Primary Commodity Prices, via FRED).
COPPER_SYMBOL = "PCOPPUSDM"
IRON_ORE_SYMBOL = "PIORECRUSDM"
ALUMINUM_SYMBOL = "PALUMUSDM"

#: The unit all three series are published in. Named once so the model's
#: declared unit and this reading cannot drift apart.
METALS_SOURCE_UNIT = "usd_per_metric_ton"


@dataclass(frozen=True)
class MetalChangeReading:
    """A metal's latest benchmark price plus the prior point needed for a CHANGE.

    ``level`` is the price the provider publishes (U.S. Dollars per Metric Ton),
    NOT the change. ``change_pct`` is the percent change from the prior monthly
    vintage to the latest — the specification's ``*_change_pct`` input.

    ``prior_observation_date`` / ``prior_level`` are ``None`` — never ``0.0`` —
    when the series carries fewer than two observations, because a fabricated
    zero prior would make a CHANGE read as a LEVEL (the D-078 class), and a
    ``0.0`` prior would then divide-by-zero or produce an infinite percent.

    ``change_unavailable_reason`` explains WHY ``change_pct`` is ``None``, so a
    consumer's disclosure can state the actual cause instead of guessing one.
    There are two distinct causes and they were previously indistinguishable to
    a caller: too few observations, and a prior observation of exactly zero.
    """

    symbol: str
    observation_date: str
    level: float
    prior_observation_date: str | None
    prior_level: float | None
    change_pct: float | None
    source_unit: str = METALS_SOURCE_UNIT
    observation_count: int = 0
    change_unavailable_reason: str | None = None


def fetch_metal_change(
    symbol: str,
    *,
    as_of: date,
    label: str,
    client: OpenBBClient | None = None,
) -> MetalChangeReading:
    """Fetch a metal's latest benchmark price and the percent change from its prior.

    Returns a :class:`MetalChangeReading` carrying the latest observation, the
    one before it, and the percent change between them. The series is clipped to
    observations at or before ``as_of`` so a caller controlling the as-of date
    gets a deterministic answer — the O-134 lesson applied to the fetch.

    ``label`` names the metal in error messages (``copper`` / ``iron_ore`` /
    ``aluminum``) so a failure identifies WHICH leg died rather than reporting a
    bare symbol.

    Raises :class:`CommodityReadError` when the transport fails, the series is
    empty, the frame lacks the client's tidy ``date``/``value`` columns, or no
    observation falls at or before ``as_of``.
    """
    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        frame = active.fetch_series(
            provider=_FRED_PROVIDER,
            endpoint=_FRED_ENDPOINT,
            params={"symbol": symbol},
            series_label=f"metals_{label}",
        )
    except OpenBBFetchError as exc:
        raise CommodityReadError(f"{label} price series {symbol} could not be read: {exc}") from exc
    finally:
        if own_client:
            active.close()

    observed = _observed_pairs(frame, symbol=symbol, as_of=as_of, label=f"{label} price")
    if not observed:
        raise CommodityReadError(
            f"{label} price series {symbol} had no observation at or before {as_of.isoformat()}."
        )

    latest_date, latest_value = observed[-1]
    reason: str | None = None
    if len(observed) >= 2:
        prior_date, prior_value = observed[-2]
        prior_iso: str | None = prior_date.isoformat()
        prior_val: float | None = prior_value
        change_pct = _percent_change(latest_value, prior_value)
        if change_pct is None:
            # The change is undefined, but the LEVEL above is still a valid
            # measurement — so the reading is returned with the reason attached
            # rather than the whole leg being thrown away.
            reason = (
                f"{symbol} has a prior observation of exactly 0.0 "
                f"({prior_date.isoformat()}), so the percent change is undefined."
            )
    else:
        prior_iso = None
        prior_val = None
        change_pct = None
        reason = (
            f"{symbol} returned {len(observed)} observation(s) at or before "
            f"{as_of.isoformat()}, fewer than the two needed to form a change."
        )

    return MetalChangeReading(
        symbol=symbol,
        observation_date=latest_date.isoformat(),
        level=latest_value,
        prior_observation_date=prior_iso,
        prior_level=prior_val,
        change_pct=change_pct,
        observation_count=len(observed),
        change_unavailable_reason=reason,
    )


def _percent_change(latest: float, prior: float) -> float | None:
    """The percent change from ``prior`` to ``latest``, or ``None`` if undefined.

    A ``prior`` of exactly zero returns ``None`` rather than ``inf``/``nan``.
    ``None`` is the shape this module ALREADY uses for an unknown change —
    ``MetalChangeReading.change_pct`` is ``float | None``, and a series with
    fewer than two observations yields ``None`` — and it is what
    ``reserves_client`` reports for the same condition, so the two clients now
    agree. ``_resolve_metal_leg`` in the model already renders a ``None`` change
    as NOT AVAILABLE with a disclosure.

    It previously RAISED. That was defensible on its own terms — the docstring
    argued a silent ``inf`` would make every model branch false — but it was
    inconsistent in two directions: with this same reading's other unknown case,
    and with the sibling client. Raising also discarded the LEVEL, which is
    still a valid measurement: the change is unknown, the price is not.
    """
    if prior == 0.0:
        return None
    return (latest - prior) / prior * 100.0


def fetch_copper_change(*, as_of: date, client: OpenBBClient | None = None) -> MetalChangeReading:
    """Fetch global copper price and its percent change (``PCOPPUSDM``)."""
    return fetch_metal_change(COPPER_SYMBOL, as_of=as_of, label="copper", client=client)


def fetch_iron_ore_change(*, as_of: date, client: OpenBBClient | None = None) -> MetalChangeReading:
    """Fetch global iron-ore price and its percent change (``PIORECRUSDM``).

    The authority tags this leg *"no clean free source — likely BLOCKED"*
    (Section 21.1, ``AGENTS.md:5395``); measured 2026-09-27 it is **LIVE** and
    the tag is the repository's **seventh FALSE BLOCK**. This docstring names
    the fact so the next reader does not re-trust the tag.
    """
    return fetch_metal_change(IRON_ORE_SYMBOL, as_of=as_of, label="iron_ore", client=client)


def fetch_aluminum_change(*, as_of: date, client: OpenBBClient | None = None) -> MetalChangeReading:
    """Fetch global aluminum price and its percent change (``PALUMUSDM``)."""
    return fetch_metal_change(ALUMINUM_SYMBOL, as_of=as_of, label="aluminum", client=client)
