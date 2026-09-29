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
from datetime import date

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
#: series is monthly (measured), so twelve steps back is one year. Named rather
#: than inlined so the lag and its justification travel together.
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
        if prior != 0.0:
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


def _as_iso_date(index_value: object) -> str:
    """Render a pandas index entry as an ISO date string.

    The index type varies by route (``DatetimeIndex`` here, and D-117 measured a
    bare ``datetime.date`` on a sibling path), so the conversion is defensive
    and the ``date`` parts are taken explicitly rather than by ``str()`` — a
    ``str()`` of a Timestamp carries a time and a timezone, which would make two
    dates for the same observation compare unequal.
    """
    if isinstance(index_value, date):
        return index_value.isoformat()
    # pandas Timestamp and anything else carrying the three attributes.
    year = getattr(index_value, "year", None)
    month = getattr(index_value, "month", None)
    day = getattr(index_value, "day", None)
    if year is None or month is None or day is None:  # pragma: no cover
        return str(index_value)
    return f"{year:04d}-{month:02d}-{day:02d}"
