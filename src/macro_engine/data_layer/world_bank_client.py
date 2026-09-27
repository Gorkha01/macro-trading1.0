"""World Bank PPP conversion factors — the reachable, NON-vintage route to a PPP-implied rate.

Why this module exists
----------------------
Section 21.1 marked ``ppp_implied_rate`` **BLOCKED → MANUAL** on the premise
*"OECD publishes PPP conversion factors; no clean free API."* A 2026-09-27
re-probe (``docs/PLAN_ppp_source.md``) measured that premise and found it
**factually wrong** — the D-043 "FALSE BLOCK" class:

* **OpenBB** — 0 of 278 paths expose PPP (measured against ``/openapi.json``).
* **FRED** — the conventional conversion-factor IDs (``PPPTTL``, ``PA.NUS.PPP``,
  ``PPPGDP``) return **empty**. PPP-derived series exist (e.g. ``MEXPPPSH``) but
  they are *shares of world PPP*, not a conversion factor.
* **World Bank REST** — **reachable**. Indicator ``PA.NUS.PPP`` (*"PPP conversion
  factor, GDP (LCU per international $)"*) returns annual points for member
  countries.

This module is that third route, made concrete. It is **the same "direct, not
OpenBB" one Section 21.1 already sanctions for ``current_account_pct_gdp``**, so
it introduces no new class of dependency.

What this module is NOT — and the distinction is load-bearing
-------------------------------------------------------------
**It is NOT a vintage client, and it must never be mistaken for one.** The engine
already has exactly one vintage-capable route (``alfred_client.py``), whose
contract is a **point-in-time selector** — ``realtime_start == realtime_end ==
as_of`` returns *the values in force on that date*. The World Bank REST API has
**no such selector**: it returns the latest published revision, and its
``lastupdated`` field is a **publication** date, not a vintage handle.

That limitation was measured against all four free sources the operator named
(World Bank / IMF / OECD / Eurostat — ``docs/PLAN_ppp_source.md`` §6), and **not
one** implements a point-in-time selector. Two of the near-misses are instructive
and are recorded so nobody repeats them:

* **IMF ``PPPEX``** carries the *exact estimand name* ("Implied PPP conversion
  rate") but its values are **WEO projections through 2031**, and its
  ``?version=`` parameter is **silently absorbed** — the read is corrupted while
  HTTP 200 is returned. That is **O-6's defect reproduced on a different host**.
* **OECD** ``DSD_PPP`` has a real conversion factor and the only published
  ``EU27_2020`` aggregate, but its ``updatedAfter`` filter answers *"what changed
  since T"*, **not** *"what was true at T"*.

So this route serves a **disclosed, fetched vintage** — the current published
figure with its publication date attached — and the models layer says exactly
that. It does not claim to answer a vintage question.

The unit, and why the ratio is the estimand
-------------------------------------------
``PA.NUS.PPP`` is denominated **LCU per international $**. For a pair quoted
domestic-per-foreign, the PPP-implied rate is therefore the **ratio of the two
countries' factors**:

    PPP-implied (domestic per foreign) = factor(domestic) / factor(foreign)

The international-dollar denominator cancels, which is why the raw factors are
NOT the estimand and must not be passed through directly. For EURUSD with the
USA as the foreign leg, ``factor(USA) == 1`` by construction (measured: the
series is exactly ``1`` on every year), so the ratio reduces to the euro leg's
factor — **but the code performs the division rather than assuming the 1**, so a
future non-USD base does not silently change the estimand.

The euro-container decision
---------------------------
The World Bank's **EMU aggregate returns 0 points** (measured). A "USD per EUR at
PPP" leg therefore has **no single official value**, and the substitute is a
**decision, not a constant** (``PLAN_ppp_source.md`` §4 step 1). The operator
directed **DEU** — the euro area's largest economy, and the leg D-114's declared
``0.72`` already matched (World Bank DEU 2025 = ``0.709983``, within **1.4 %**).
It is recorded in the registry as ``ppp_conversion_factor_eur`` with its
justification, so the choice is auditable rather than buried in a literal.

Transport
---------
``httpx`` with the same pinned ``curl/8.0`` User-Agent ``alfred_client.py`` and
``thesis_layer/catalysts.py`` use (D-065, corrected by D-087.25): the variable
that bites is tool-like versus browser-like, not the client library. Kept
identical deliberately — a second, different UA in the same codebase is a second
unexplained variable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "CURRENT_ACCOUNT_PCT_GDP_INDICATOR",
    "IndicatorReading",
    "PPPFactor",
    "RESERVES_TOTAL_USD_INDICATOR",
    "SHORT_TERM_EXTERNAL_DEBT_USD_INDICATOR",
    "WorldBankError",
    "WorldBankReadError",
    "WorldBankUnavailableError",
    "fetch_indicator_reading",
    "fetch_ppp_conversion_factor",
    "fetch_ppp_implied_rate",
    "implied_rate_from_factors",
    "reserves_to_short_term_debt",
]

#: The provenance string this route stamps onto what it returns. Kept as an
#: independent literal rather than imported from a sibling client's private
#: constants — the same reasoning ``alfred_client.ROUTE_NAME`` records: a
#: rename over there must not silently change provenance over here, and a guard
#: test asserts the route names are distinct.
ROUTE_NAME = "world_bank_direct"

#: The World Bank's host. Absolute, so the absence of any OpenBB host in this
#: module is visible at a glance.
WORLD_BANK_HOST = "https://api.worldbank.org"

#: The base URL for a single country/indicator series. `{iso3}` and `{indicator}`
#: are filled per request; `per_page=100` clears the maximum series length
#: measured (66 rows, 36 non-null).
WORLD_BANK_SERIES_URL = (
    f"{WORLD_BANK_HOST}/v2/country/{{iso3}}/indicator/{{indicator}}?format=json&per_page=100"
)

#: The indicator this module fetches: "PPP conversion factor, GDP (LCU per
#: international $)". Named once; the registry points at this same code.
PPP_CONVERSION_FACTOR_INDICATOR = "PA.NUS.PPP"

#: "Current account balance (% of GDP)". The first of
#: ``em_vulnerability_checklist``'s two reachable legs (D-119). Section 21.1
#: lists it LIVE on the same *"direct, not OpenBB"* route as the PPP factor, so
#: this module is its third consumer rather than a new dependency class.
CURRENT_ACCOUNT_PCT_GDP_INDICATOR = "BN.CAB.XOKA.GD.ZS"

#: "Total reserves (includes gold, current US$)". The NUMERATOR of
#: ``reserves_to_short_term_external_debt``. Denominated in **current USD**, not
#: millions — unlike ``reserves_client``'s FRED series, so the two routes to a
#: reserve stock do NOT share a unit and must never be substituted for one
#: another (D-116's lesson: a unit is not a label).
RESERVES_TOTAL_USD_INDICATOR = "FI.RES.TOTL.CD"

#: "Short-term external debt on residual maturity basis (current US$)". The
#: DENOMINATOR of ``reserves_to_short_term_external_debt``. Both legs are
#: current USD, so the ratio is a pure number — no unit conversion is needed and
#: none is performed.
SHORT_TERM_EXTERNAL_DEBT_USD_INDICATOR = "DT.DOD.DSTC.CD"

#: Measured-good UA (D-087.25). Identical to `alfred_client._REQUEST_HEADERS`
#: on purpose — see the module docstring.
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "curl/8.0",
}

#: Retry budget for a transient read failure. The World Bank API is public and
#: unauthenticated, so a failure is transport, not credentials; a small budget
#: is enough and keeps a live check fast.
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 1.5


class WorldBankError(Exception):
    """Base for every failure this module raises.

    A distinct root so a caller can handle a World Bank read without catching a
    sibling client's transport error — ``OpenBBFetchError`` and
    ``AlfredVintageError`` are different contracts with different behaviours.
    """


class WorldBankUnavailableError(WorldBankError):
    """The route cannot serve this request at all, and retrying will not help.

    Raised for a malformed ISO3 code, an unknown indicator, or a response whose
    shape is not the World Bank's — the cases where a retry would repeat the
    same defect. **Deliberately fatal rather than degrading**, following the
    ``VintageUnavailableError`` precedent: a caller must not receive a
    plausible-looking empty frame in place of a definite failure.
    """


class WorldBankReadError(WorldBankError):
    """A transient failure: transport, status, or an unparseable body.

    Retryable, and retried internally. Raised only after the budget is spent.
    """


@dataclass(frozen=True)
class PPPFactor:
    """One country's PPP conversion factor as the World Bank published it.

    Carries the three facts a caller needs to judge whether the number is
    usable, rather than the number alone:

    * ``iso3`` / ``indicator`` — WHAT was read, so a wrong-leg error is visible.
    * ``year`` — the observation period, which is an ANNUAL label, not a date.
    * ``value`` — the factor, in LCU per international $.
    * ``last_updated`` — the **publication** date of the series. **This is what
      makes the value a disclosed vintage rather than a live price**, and it is
      the field a caller must surface rather than swallow.
    """

    iso3: str
    indicator: str
    year: int
    value: float
    last_updated: date

    @property
    def vintage_label(self) -> str:
        """A one-line provenance string for ``limitations`` and log output."""
        return (
            f"World Bank {self.indicator} ({self.iso3}), {self.year} figure, "
            f"published {self.last_updated.isoformat()}"
        )


@dataclass(frozen=True)
class IndicatorReading:
    """One country's reading of one World Bank indicator, as published.

    The general sibling of :class:`PPPFactor`. Kept as a SEPARATE type rather
    than widening ``PPPFactor``'s name: the two carry identical fields today, but
    ``PPPFactor``'s docstring and its ``value`` unit ("LCU per international $")
    are specific to the PPP estimand, and a shared class would mean a future
    unit-bearing field on one silently changing the other. A rename with no
    behavioural difference is cheaper than a type whose meaning depends on which
    caller is asking.

    Carries what a caller needs to judge usability rather than the number alone:
    ``iso3``/``indicator`` say WHAT was read (making a wrong-country error
    visible), ``year`` is the observation period — an ANNUAL label, not a date —
    ``value`` is the published reading in the indicator's own unit, and
    ``last_updated`` is the publication date, which is what makes the figure a
    **disclosed vintage rather than a live price**.
    """

    iso3: str
    indicator: str
    year: int
    value: float
    last_updated: date

    @property
    def vintage_label(self) -> str:
        """A one-line provenance string for ``limitations`` and log output."""
        return (
            f"World Bank {self.indicator} ({self.iso3}), {self.year} figure, "
            f"published {self.last_updated.isoformat()}"
        )


def _parse_iso3(iso3: str) -> str:
    """Normalise and validate an ISO3 country code.

    The World Bank's API is case-insensitive but path-segment sensitive: a
    lowercase or padded code returns an empty payload rather than an error
    (measured), which would look like "no data" instead of "bad input". So the
    code is upper-cased, stripped, and length-checked here — refusing a
    malformed argument loudly beats returning an empty series quietly.
    """
    code = iso3.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise WorldBankUnavailableError(
            f"iso3 must be a 3-letter country code, got {iso3!r}. The World Bank "
            f"API answers a malformed code with an empty payload rather than an "
            f"error, so this is validated here to keep 'bad input' distinct from "
            f"'no data'."
        )
    return code


def _parse_payload(body: Any, *, iso3: str, indicator: str) -> tuple[list[Any], date]:
    """Extract the rows and the ``lastupdated`` date from a World Bank response.

    The response is a **two-element list**: ``[metadata, rows]``. Both a missing
    second element and a non-list body are shape failures — the World Bank
    returns a one-element list for an unknown indicator and an HTML error page
    for a malformed URL, and neither must be silently treated as "no data".
    """
    if not isinstance(body, list) or len(body) < 1:
        raise WorldBankUnavailableError(
            f"World Bank response for {iso3}/{indicator} is not the documented "
            f"[metadata, rows] list (got {type(body).__name__}). A shape change "
            f"here must fail loudly rather than read as an empty series."
        )
    meta = body[0]
    if not isinstance(meta, dict):
        raise WorldBankUnavailableError(
            f"World Bank metadata for {iso3}/{indicator} is not an object "
            f"(got {type(meta).__name__})"
        )
    raw_updated = meta.get("lastupdated") or meta.get("lastUpdated")
    if not isinstance(raw_updated, str):
        raise WorldBankUnavailableError(
            f"World Bank metadata for {iso3}/{indicator} carries no "
            f"'lastupdated' date. The publication date is what makes this value "
            f"a disclosed vintage; without it the read must fail, not proceed."
        )
    try:
        last_updated = date.fromisoformat(raw_updated)
    except ValueError as exc:
        raise WorldBankUnavailableError(
            f"World Bank 'lastupdated' {raw_updated!r} is not an ISO date"
        ) from exc

    rows = body[1] if len(body) > 1 else []
    if rows is None:
        # The documented shape for "valid request, no rows" is a 2-element list
        # whose second element is null. That is an honest empty read.
        rows = []
    if not isinstance(rows, list):
        raise WorldBankUnavailableError(
            f"World Bank rows for {iso3}/{indicator} are not a list (got {type(rows).__name__})"
        )
    return rows, last_updated


def _parse_rows_to_reading(
    iso3: str,
    indicator: str,
    rows: list[Any],
    last_updated: date,
) -> IndicatorReading:
    """Select the newest populated YEAR from parsed rows and build a reading.

    Split out of the transport path at D-119 so the row-selection rule — the
    part that is a fact about the DATA rather than about HTTP — can be exercised
    against fabricated rows without patching a network client. The rule is the
    same one the PPP route has always used: rows arrive newest-first but that
    order is not a documented contract, so the newest non-null YEAR is selected
    explicitly, and a null value is a suppressed observation rather than a zero.
    """
    populated: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_value = row.get("value")
        raw_year = row.get("date")
        if raw_value is None or raw_year is None:
            continue
        try:
            year = int(str(raw_year))
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        populated.append((year, value))

    if not populated:
        raise WorldBankUnavailableError(
            f"World Bank returned no populated {indicator} points for {iso3}. "
            f"This is a genuine empty series (the EMU aggregate measures 0 "
            f"points), not a transport failure — a caller must not read it as a "
            f"value."
        )

    year, value = max(populated, key=lambda pair: pair[0])
    return IndicatorReading(
        iso3=iso3,
        indicator=indicator,
        year=year,
        value=value,
        last_updated=last_updated,
    )


def fetch_ppp_conversion_factor(
    iso3: str,
    *,
    indicator: str = PPP_CONVERSION_FACTOR_INDICATOR,
    timeout: float = 30.0,
) -> PPPFactor:
    """Fetch the LATEST published PPP conversion factor for one country.

    *Latest*, not a vintage: the World Bank REST API offers no point-in-time
    selector (see the module docstring). The returned ``PPPFactor.last_updated``
    is the publication date, and a caller must disclose it.

    Raises ``WorldBankUnavailableError`` for a malformed argument or an
    unusable response, and ``WorldBankReadError`` for a transport failure after
    the retry budget. **Never returns an empty result in place of a failure** —
    an empty series means the country genuinely has no published points, which
    for the EMU aggregate is the measured truth.

    Since D-119 this delegates to :func:`_fetch_latest_reading`, which holds the
    retry budget, the newest-year selection, and the empty-versus-failed
    distinction. Those are facts about the World Bank API rather than about the
    PPP estimand, and one definition is what keeps a second caller from drifting
    from this one.
    """
    reading = _fetch_latest_reading(iso3, indicator, timeout=timeout)
    return PPPFactor(
        iso3=reading.iso3,
        indicator=reading.indicator,
        year=reading.year,
        value=reading.value,
        last_updated=reading.last_updated,
    )


def implied_rate_from_factors(domestic: PPPFactor, foreign: PPPFactor) -> float:
    """The PPP-implied rate (domestic per foreign) from two conversion factors.

    The estimand, written once so it cannot be restated differently elsewhere.
    The factors are **LCU per international $**, so dividing cancels the
    international dollar and leaves the bilateral level:

        domestic per foreign = factor(domestic) / factor(foreign)

    **The division is performed, never assumed.** For a USD-base pair
    ``factor(USA) == 1`` and the ratio equals the domestic factor, but reading
    the identity rather than repeating it is what keeps a future non-USD base
    from silently changing the estimand (the D-109 class of defect: a value that
    means something different once an assumption moves).
    """
    if foreign.value == 0.0:
        raise WorldBankUnavailableError(
            f"PPP conversion factor for {foreign.iso3} is zero, so the implied "
            f"rate is undefined. A zero factor is not a price level."
        )
    return domestic.value / foreign.value


def fetch_ppp_implied_rate(
    domestic_iso3: str,
    foreign_iso3: str,
    *,
    indicator: str = PPP_CONVERSION_FACTOR_INDICATOR,
    timeout: float = 30.0,
) -> tuple[float, str]:
    """Fetch the PPP-implied rate for a pair, with its freshness as a warning.

    Returns ``(implied_rate, disclosure)``. The disclosure names **both** legs'
    figures and publication dates, because a PPP-implied rate is a statement
    about two countries and a single date cannot describe it: the two series are
    refreshed independently and the legs may be a year apart.

    **A year mismatch between the legs is not an error — it is a fact that must
    be disclosed.** The World Bank publishes each country on its own schedule,
    so the freshest available pair can mix years; silently pairing them would
    hide a real vintage gap. The disclosure names both years so a caller can see
    it.
    """
    domestic = fetch_ppp_conversion_factor(domestic_iso3, indicator=indicator, timeout=timeout)
    foreign = fetch_ppp_conversion_factor(foreign_iso3, indicator=indicator, timeout=timeout)
    rate = implied_rate_from_factors(domestic, foreign)
    disclosure = (
        f"PPP-implied rate from the World Bank ({indicator}), fetched as a "
        f"disclosed vintage, NOT a live price and NOT a point-in-time vintage: "
        f"{domestic.iso3} {domestic.value} ({domestic.year}) / "
        f"{foreign.iso3} {foreign.value} ({foreign.year}); "
        f"published {domestic.last_updated.isoformat()} and "
        f"{foreign.last_updated.isoformat()} respectively."
    )
    return rate, disclosure


def _fetch_latest_reading(
    iso3: str,
    indicator: str,
    *,
    timeout: float,
) -> IndicatorReading:
    """Fetch the LATEST populated point of one indicator, with retries.

    The shared transport/staleness core behind :func:`fetch_indicator_reading`
    and (via the same shape) ``fetch_ppp_conversion_factor``. Extracted at D-119
    when a second caller appeared: the retry budget, the "newest non-null YEAR
    selected explicitly rather than by position" rule, and the
    empty-series-versus-transport-failure distinction are all facts about the
    World Bank API, and two copies of a fact drift.

    ``indicator`` is passed as an argument rather than defaulted, so this helper
    can never be called without the caller naming which series it wanted — the
    defect class where a default silently substitutes one series for another.
    """
    code = _parse_iso3(iso3)
    url = WORLD_BANK_SERIES_URL.format(iso3=code, indicator=indicator)

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=timeout, http2=False) as client:
                response = client.get(url, headers=_REQUEST_HEADERS)
            if response.status_code != 200:
                raise WorldBankReadError(
                    f"World Bank returned HTTP {response.status_code} for {code}/{indicator}"
                )
            body = json.loads(response.text)
            rows, last_updated = _parse_payload(body, iso3=code, indicator=indicator)
        except (httpx.HTTPError, json.JSONDecodeError, WorldBankReadError) as exc:
            last_exc = exc
            logger.warning(
                "World Bank read for %s/%s attempt %s/%s failed: %s",
                code,
                indicator,
                attempt,
                _MAX_ATTEMPTS,
                exc,
            )
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_BACKOFF_SECONDS * attempt)
            continue
        break
    else:
        raise WorldBankReadError(
            f"World Bank read for {code}/{indicator} failed after "
            f"{_MAX_ATTEMPTS} attempts: {last_exc}"
        )

    return _parse_rows_to_reading(code, indicator, rows, last_updated)


def fetch_indicator_reading(
    iso3: str,
    indicator: str,
    *,
    timeout: float = 30.0,
) -> IndicatorReading:
    """Fetch the latest published reading of any World Bank indicator.

    *Latest*, not a vintage: the World Bank REST API offers no point-in-time
    selector (the module docstring records the measurement), so the result is a
    **disclosed vintage** and a caller must surface ``last_updated``.

    Public because ``em_vulnerability_checklist`` (D-119) needs three unrelated
    indicators and had no reason to reach a private helper. Raises the same two
    errors as :func:`fetch_ppp_conversion_factor`, on the same
    empty-versus-failed distinction.
    """
    return _fetch_latest_reading(iso3, indicator, timeout=timeout)


def reserves_to_short_term_debt(iso3: str, *, timeout: float = 30.0) -> tuple[float, str]:
    """Reserves divided by short-term external debt, plus its disclosure.

    The second of ``em_vulnerability_checklist``'s reachable checks. Section
    21.1 calls this input **DERIVED** — *"IMF reserves / World Bank ST external
    debt"* — and DERIVED means the division is **performed here, never assumed**
    (D-109). Both legs are the World Bank's own current-USD series, so the ratio
    is a pure number and **no unit conversion happens**; that is a property of
    these two indicators, not a general rule, which is why the units are named
    on the disclosure.

    Returns ``(ratio, disclosure)``. The disclosure names both legs' values,
    years and publication dates, because the ratio is a statement about two
    independently-refreshed series and a single date cannot describe it — the
    same reasoning as :func:`fetch_ppp_implied_rate`.

    A **zero denominator raises** rather than returning infinity: a short-term
    external debt of zero makes the ratio undefined, and an infinite ratio would
    read as "perfectly covered" to any caller that compared it against 1.0.
    """
    reserves = fetch_indicator_reading(iso3, RESERVES_TOTAL_USD_INDICATOR, timeout=timeout)
    short_term = fetch_indicator_reading(
        iso3, SHORT_TERM_EXTERNAL_DEBT_USD_INDICATOR, timeout=timeout
    )
    if short_term.value == 0.0:
        raise WorldBankUnavailableError(
            f"Short-term external debt for {short_term.iso3} is zero, so the "
            f"reserves-to-ST-debt ratio is undefined. A zero denominator is not "
            f"'perfectly covered' and must not be read as an infinite ratio."
        )
    ratio = reserves.value / short_term.value
    disclosure = (
        f"Reserves / short-term external debt from the World Bank, fetched as "
        f"a disclosed vintage, NOT a live price and NOT a point-in-time vintage: "
        f"reserves {reserves.value} ({reserves.year}, "
        f"{RESERVES_TOTAL_USD_INDICATOR}) / ST debt {short_term.value} "
        f"({short_term.year}, {SHORT_TERM_EXTERNAL_DEBT_USD_INDICATOR}); "
        f"published {reserves.last_updated.isoformat()} and "
        f"{short_term.last_updated.isoformat()} respectively. Both legs are "
        f"current USD, so no unit conversion is performed."
    )
    return ratio, disclosure
