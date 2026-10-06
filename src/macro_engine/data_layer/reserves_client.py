"""FX reserve stocks — the observable behind ``intervention_capacity``.

Why this module exists
----------------------
Section 20.9 gives ``intervention_capacity`` an input model with
``fx_reserves_usd_bn`` and ``reserves_to_gdp_pct`` but names **no source** for
either, and ``config/series_registry.yaml`` had **no entry** — which under
Section 21.1's default rule (*"any input not listed above is BLOCKED by
default"*) would make both **BLOCKED**. Measured 2026-09-27, that reading is
**false**: the BIS/IMF reserve series are reachable through this installation's
OpenBB service.

This is the **fourth FALSE BLOCK** this repository has caught, after
``ppp_implied_rate`` (O-3, closed by D-115/D-117). The class is D-043's: a
*sourcing claim* recorded in a document and never re-measured, which then reads
exactly like a measured constraint. The correct response is to record the source
and wire it, so the value can be fetched rather than typed.

The series, measured 2026-09-27
-------------------------------
``economy.fred_series`` serves **"Total Reserves excluding Gold"** for each
country, monthly, in **millions of US dollars**:

* ``TRESEGJPM052N`` — Japan, 843 observations, latest 2026-08-01
* ``TRESEGGBM052N`` — United Kingdom, 843 observations, latest 2026-08-01
* ``TRESEGCNM052N`` — China, 563 observations, latest 2026-06-01

**The unit is the trap and it is named everywhere it appears.** ``TRESEGJPM052N``
reads ``1083420.49``, which is USD 1.083 **trillion** — the number is in millions,
and a reader who takes it at face value is off by 1000x. Both the source unit and
the fact that no conversion was applied are named on the returned disclosure, and
the **model performs the conversion** (``models/intervention.py`` divides by
``MILLIONS_PER_BILLION``), deliberately *not* here: a client that returns a
pre-converted number hides which unit it read, and with a factor of 1000 between
the two units the conversion is exactly where a defect would hide. A 1000x error
in a reserve stock produces a plausible-looking figure at either scale, which is
the silent class the registry's ``source_units`` field exists to prevent.

What this module is NOT
-----------------------
It is not a vintage client. Like ``world_bank_client``, it returns the **latest
published revision** with its observation date attached and makes no claim about
what was in force on an earlier date. The engine's one point-in-time route
remains ``alfred_client.py``, whose contract is the ``realtime_start ==
realtime_end == as_of`` selector — and which no reserve source implements.

Transport
---------
This module does **not** open its own HTTP connection. It goes through the
project's own ``OpenBBClient``, which already owns the base URL, the retry
policy, the pinned ``curl/8.0`` User-Agent (D-087.25) and the forward-dated
guard (O-7). Re-implementing any of that here would create a second, silently
divergent route to the same host — the exact shape D-087.25 was written to
eliminate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError

logger = logging.getLogger(__name__)

__all__ = [
    "MILLIONS_PER_BILLION",
    "RESERVE_SERIES",
    "ReservesReadError",
    "ReservesReading",
    "fetch_reserves",
]

#: Country -> the FRED series for "Total Reserves excluding Gold" (USD MILLIONS).
#:
#: Kept as a literal map rather than registry entries because the lookup key is a
#: **country code** and the value is a **series**, which the registry's
#: ``series`` map is not shaped for (its keys are the ENGINE's field names, one
#: per snapshot field). The registry carries the *field* (``fx_reserves_usd_bn``,
#: see ``series_registry.yaml``) and this map carries the *per-country symbol*,
#: the same split the PPP client uses for its ``iso3`` legs.
#:
#: Only the countries whose series were **measured reachable** are listed. An
#: unlisted country returns ``None`` from :func:`fetch_reserves` rather than a
#: guess, so an unreachable country is disclosed as unavailable instead of
#: silently borrowing a neighbour's series.
RESERVE_SERIES: dict[str, tuple[str, str]] = {
    # alpha-2 and alpha-3 both accepted; the model passes whatever the caller
    # used, and the lookup is case-insensitive.
    "jp": ("TRESEGJPM052N", "japan"),
    "jpn": ("TRESEGJPM052N", "japan"),
    "gb": ("TRESEGGBM052N", "united_kingdom"),
    "gbr": ("TRESEGGBM052N", "united_kingdom"),
    "uk": ("TRESEGGBM052N", "united_kingdom"),
    "cn": ("TRESEGCNM052N", "china"),
    "chn": ("TRESEGCNM052N", "china"),
}

#: The unit the PROVIDER returns a reserve stock in, as declared on the reading.
#: The engine's own unit is ``billions`` and the conversion is performed by the
#: MODEL (``models/intervention.py``), not here — see the class docstring on
#: ``ReservesReading`` for why the source unit is what crosses this boundary.
SOURCE_UNIT = "millions of USD"

#: The divisor between the source unit (millions) and the engine's unit
#: (billions), named rather than typed as a bare ``1000.0`` in the model's
#: conversion expression — a mutation that changes the exponent then has to
#: change THIS constant, which is a difference a test can see. It is the single
#: source of truth for the 1000x step, imported by the model so the two cannot
#: drift apart; the sweep's ``I9a``/``I9b`` mutations pin the model's use of it
#: and ``R6a`` pins the value here.
MILLIONS_PER_BILLION = 1000.0

#: How many monthly observations the twelve-month change is measured over. The
#: series is monthly **from ~1956** (measured: TRESEGJPM052N has 843 observations
#: with six non-monthly steps at its 1950-55 head), so twelve steps back is one
#: year for any recent window — and the span is now MEASURED at the call site
#: rather than assumed. Named rather than inlined so the lag and its
#: justification travel together.
_CHANGE_LAG_MONTHS = 12


class ReservesReadError(Exception):
    """A reserve fetch failed, or the series was unusable.

    Distinct from ``OpenBBFetchError`` so the model can distinguish *the
    transport failed* (this class) from *the country is not registered* (a
    ``None`` return), and report each differently. Both are non-fatal to a
    weakening verdict and both are fatal to a strengthening one.
    """


@dataclass(frozen=True)
class ReservesReading:
    """One country's reserve stock, with everything needed to audit it.

    ``reserves_usd_mn`` is in the **source's own unit** (millions). The model
    converts. Deliberately *not* pre-converted here: a client that returns a
    converted number hides which unit it read, and the two units differ by a
    factor of 1000, so the conversion is a place a defect can hide. Keeping the
    source unit on this object means the conversion is a single, visible line in
    the model — not spread across two modules.
    """

    symbol: str
    country_label: str
    reserves_usd_mn: float
    observation_date: str
    change_12m_pct: float | None
    source_unit: str
    observation_count: int


def fetch_reserves(
    country: str,
    *,
    client: OpenBBClient | None = None,
) -> ReservesReading | None:
    """Fetch a country's total reserves, or ``None`` when it has no series.

    Returns the reading **in the source's millions**, with the twelve-month
    change computed when the series is long enough. Raises
    :class:`ReservesReadError` when the fetch itself fails — a missing
    registration is the ``None`` return, not an exception, because *"this country
    is not in the map"* and *"the network is down"* are different facts and the
    caller reports them differently.

    The change is ``None`` — never ``0.0`` — when there are too few observations.
    A zero would read as *"reserves are stable"*, which is an assertion the data
    does not make; ``None`` reads as *"unknown"*, which is true.
    """
    key = country.strip().lower()
    entry = RESERVE_SERIES.get(key)
    if entry is None:
        logger.info(
            "fetch_reserves: no reserve series registered for %r (registered: %s)",
            country,
            sorted(RESERVE_SERIES),
        )
        return None
    symbol, country_label = entry

    own_client = client is None
    active = client if client is not None else OpenBBClient()
    try:
        frame = active.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": symbol},
            series_label=f"fx_reserves_{key}",
        )
    except OpenBBFetchError as exc:
        raise ReservesReadError(
            f"reserve series {symbol} for {country!r} could not be read: {exc}"
        ) from exc
    finally:
        if own_client:
            active.close()

    if frame.empty:
        raise ReservesReadError(
            f"reserve series {symbol} for {country!r} returned no observations. "
            "An empty response is not 'zero reserves' — it is a failed read and "
            "is treated as one."
        )

    # The client returns a TIDY frame — one row per observation, with `date` and
    # `value` as COLUMNS (measured: shape (843, 5), columns `date`, `value`,
    # `series_id`, `source`, `retrieved_at`) — not a series indexed by date.
    # Reading `frame.iloc[:, 0]` would therefore pick up the DATE column, which
    # is the defect this comment exists to prevent: `float()` on it raises, but a
    # route that returned dates as integer epochs would instead have published a
    # reserve stock in 1970. The column is selected BY NAME so the two can never
    # be confused.
    if "date" not in frame.columns or "value" not in frame.columns:
        raise ReservesReadError(
            f"reserve series {symbol} for {country!r} returned an unexpected "
            f"frame shape (columns: {sorted(frame.columns)}); expected the "
            "client's tidy `date`/`value` columns. Refusing rather than guessing "
            "which column is the value."
        )

    # Drop rows whose value is missing before ordering, then sort by date so
    # `iloc[-1]` is the latest OBSERVATION rather than the last row the provider
    # happened to emit. FRED returns ascending order, but the guard is cheap and
    # a reversed response would silently turn "latest" into "oldest".
    cleaned = frame.loc[:, ["date", "value"]].dropna(subset=["value"])
    cleaned = cleaned.sort_values("date")
    if cleaned.empty:
        raise ReservesReadError(
            f"reserve series {symbol} for {country!r} returned only missing values."
        )

    values = cleaned["value"].astype(float).to_numpy()
    dates = [_as_iso_date(d) for d in cleaned["date"].tolist()]

    last_value = float(values[-1])
    observation_date = dates[-1]

    change_12m_pct: float | None = None
    if len(values) > _CHANGE_LAG_MONTHS:
        prior = float(values[-(_CHANGE_LAG_MONTHS + 1)])
        # The lag is a COUNT of observations, and it equals twelve months only
        # while the series is contiguous monthly. Measured on TRESEGJPM052N:
        # 843 observations with SIX non-monthly steps at the 1950-55 head, so
        # the series is monthly only from ~1956 — "the series is monthly" is
        # true of today's window, not of the series. Nothing checked that, and a
        # missing RECENT month (FRED's ".", dropped by the `dropna` above) would
        # silently make this a 13-month change published as `change_12m_pct`.
        # The span is therefore measured, and a non-12-month span reports the
        # change as UNKNOWN — the same stance the too-few-observations case
        # takes, and for the same reason: a zero or a mislabelled window is an
        # assertion the data does not make.
        span = _month_ordinal(dates[-1]) - _month_ordinal(dates[-(_CHANGE_LAG_MONTHS + 1)])
        if span != _CHANGE_LAG_MONTHS:
            logger.info(
                "fetch_reserves: %s spans %s month(s) between the last value and "
                "the %s-th back, not %s; the change is reported as unknown rather "
                "than as a %s-month figure.",
                symbol,
                span,
                _CHANGE_LAG_MONTHS,
                _CHANGE_LAG_MONTHS,
                _CHANGE_LAG_MONTHS,
            )
        elif prior != 0.0:
            change_12m_pct = (last_value - prior) / prior * 100.0
        else:
            # A zero prior is not a basis for a percentage change. Disclosed as
            # unknown rather than raising: a country whose reserves were fully
            # depleted a year ago is a real case, and the LEVEL is still valid.
            logger.info(
                "fetch_reserves: %s has a zero value 12 months back; the change "
                "is reported as unknown rather than as an infinite percentage.",
                symbol,
            )

    return ReservesReading(
        symbol=symbol,
        country_label=country_label,
        reserves_usd_mn=last_value,
        observation_date=observation_date,
        change_12m_pct=change_12m_pct,
        source_unit=SOURCE_UNIT,
        observation_count=int(values.size),
    )


def _month_ordinal(iso_date: str) -> int:
    """A ``YYYY-MM-DD`` string as a month ordinal (``year * 12 + month``).

    Exists so the twelve-month change can MEASURE its own span rather than trust
    that twelve observations are twelve months. Reuses ``_as_iso_date``'s output,
    so every date carrier is already collapsed to a bare date by the time this
    runs.
    """
    year, month = iso_date.split("-", 2)[:2]
    return int(year) * 12 + int(month)


def _as_iso_date(index_value: object) -> str:
    """Render a date-like value as a bare ISO date string (``YYYY-MM-DD``).

    The index type varies by route (``DatetimeIndex`` here, and D-117 measured a
    bare ``datetime.date`` on a sibling path), so the conversion is defensive
    and the ``date`` parts are taken explicitly rather than by ``str()`` — a
    ``str()`` of a Timestamp carries a time and a timezone, which would make two
    dates for the same observation compare unequal.

    **A ``pd.Timestamp`` must therefore be collapsed BEFORE ``isoformat`` is
    called**, and that is what R-6 fixed. The original code led with
    ``if isinstance(index_value, date): return index_value.isoformat()`` — and
    because ``pd.Timestamp`` (and ``datetime``) are ``date`` subclasses, a
    Timestamp took that branch and ``Timestamp.isoformat()`` produced
    ``'2026-09-18T00:00:00'``, i.e. exactly the time-bearing string this
    docstring says it exists to avoid. Measured, not assumed.

    It is **not reachable through today's wiring** — ``reserves_client`` calls
    ``fetch_series``, whose normalized ``date`` column holds real
    ``datetime.date`` objects (measured: ``sort_values`` and ``tolist`` preserve
    them) — so this is a latent defect, not a live one, and it is fixed anyway
    because the two routes differ only in a call the module above could change.
    A date-bearing carrier is collapsed by ``.date()`` first; a plain string is
    passed through; anything with ``year``/``month``/``day`` is formatted
    explicitly.
    """
    # Collapse any date-bearing carrier (Timestamp, datetime) to a plain date
    # so `.isoformat()` cannot attach a time. The `datetime` type is tested
    # FIRST because it (and `pd.Timestamp`) are `date` subclasses: a plain
    # `isinstance(x, date)` test is True for all three and cannot distinguish
    # them, which is exactly how the defect hid.
    if isinstance(index_value, datetime):
        return index_value.date().isoformat()
    collapse = getattr(index_value, "date", None)
    if callable(collapse) and not isinstance(index_value, date):
        collapsed = collapse()
        if isinstance(collapsed, date):
            return collapsed.isoformat()
    if isinstance(index_value, date):
        return index_value.isoformat()
    # Everything else: a value carrying year/month/day, OR an ISO-ish string.
    # `numpy.datetime64` is the measured carrier that reaches here (it has no
    # `.date()`, `.year`, or `.isoformat` with a bare date) -- taking the first
    # whitespace/`T`-delimited token drops any time part, so it renders bare
    # rather than leaking `'2026-09-18T13:45:00'`.
    year = getattr(index_value, "year", None)
    month = getattr(index_value, "month", None)
    day = getattr(index_value, "day", None)
    if year is not None and month is not None and day is not None:
        return f"{year:04d}-{month:02d}-{day:02d}"
    head = str(index_value).strip().split("T", 1)[0].split(" ", 1)[0]
    return head
