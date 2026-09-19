"""Section 6 release-date lookup — when a value became public.

The problem this solves
-----------------------
``ObservationPoint`` carries four timestamps that are NOT interchangeable:
``observation_date`` (what period the value describes), ``release_datetime``
(when it became public), ``vintage_datetime`` (which revision), and
``retrieved_at`` (when this process read it). Only the first and last are always
available.

That gap is not cosmetic. Section 6's point-in-time filter uses
``observation_date``, which is **sufficient but not sound**: a month's CPI is
stamped the 1st of that month but published around mid-*following*-month, so an
``as_of`` equal to the observation date admits a value that had not been
released yet. Until ``release_datetime`` is populated, a backtest can silently
use data from the future.

What was believed, and what is true
-----------------------------------
The 2026-09-19 audit concluded that no reachable route returns release dates,
and modelled the fields while leaving them ``None`` so the gap stayed visible.
That conclusion was **half right**:

* CONFIRMED — ``economy.calendar`` with ``provider=fred`` raises ``TimeoutError``
  consistently (many retries, so not a transient limit), and
  ``economy.fred_release_table`` returns a table of contents with no date field.
* MISSED — the endpoint accepts **four** providers and only ``fred`` was tried.
  ``fmp`` and ``tradingeconomics`` fail on missing credentials (a config gap).
  **``nasdaq`` works** and returns dated US releases, including the CPI, PCE and
  PPI prints this system consumes. Verified live 2026-09-20.

The earlier reading extrapolated from one provider to "no reachable route
exists" without enumerating the provider list — the same overstatement class
this audit exists to find.

The honest limitation
---------------------
The working route is INTERMITTENT and, as of the last live measurement, BLOCKED.

Measured 2026-09-20, first pass: **2 of 4** identical calls succeeded, the
failures returning a well-formed
``{"detail": "Nasdaq Error -> Economic Events Calendar: No record found."}``
with a fresh response ``id`` each time, so there is no caching to mask it. It is
also date-range sensitive.

Measured 2026-09-20, later the same session: after that testing volume the
upstream host began refusing every read. **The reason is now established
directly, and it is an edge/WAF block, not a code fault and not a Nasdaq data
problem:**

    $ curl -D- 'https://api.nasdaq.com/api/calendar/economicevents?date=2026-09-18'
    HTTP/1.1 403 Forbidden
    Server: AkamaiGHost
    Content-Type: text/html
    X-Reference-Error: 18.cc055a68.1789850159.1cdedae4
    <HTML><HEAD><TITLE>Access Denied</TITLE>...

``AkamaiGHost`` is Akamai's edge server and ``X-Reference-Error`` is its own
incident reference, so this is an infrastructure-level decision about this
client. The block is **host-wide, not endpoint-specific**: a nasdaq route
unrelated to the calendar (``equity/calendar/earnings``) fails identically.
``X-Reference-Error`` is the value Akamai support would ask for, so the block is
at least identifiable rather than anonymous.

**Three distinct failure signatures reach this module, and all three are
handled** — which matters, because only one of them is obvious:

1. ``{"detail": "Nasdaq Error -> ... No record found."}`` with **HTTP 200**.
   The provider's "no data" body. Passes ``raise_for_status()``.
2. **HTTP 500** from the local OpenBB server, with a JSON body that *names the
   real cause*: ``{"detail": "Unexpected Error -> ContentTypeError -> 403,
   message='Attempt to decode JSON with unexpected mimetype: text/html', ..."}``.
   This is the 403 above, surfacing through OpenBB as a 500. Anyone debugging
   only the status code would chase an OpenBB fault; the body says otherwise.
3. A transport error (connection refused, timeout, 403 passed straight through).

None of these is a code fault, and the correct response to all three is the
same. So the code path is implemented and exercised against the real provider's
**success** shape, while its failure behaviour is verified against all three
shapes above; whether it can read anything today depends on a third party's
edge rules.

So this module's contract is deliberately narrow and pessimistic:

* Retry the route, because its failures are transient.
* On exhaustion, return an EMPTY mapping — never a guessed or scheduled date.
* Never substitute an observation date for a release date. Those are different
  facts; conflating them is exactly the defect Section 6 prohibits.

A caller that gets an empty mapping must treat release timing as UNKNOWN, which
``ObservationPoint.has_known_release_timing`` already lets it ask for.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import httpx

from macro_engine.config import ReleaseCalendar, get_registry, get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "ReleaseCalendarError",
    "ReleaseDateIndex",
    "fetch_release_dates",
    "release_dates_for_series",
]


class ReleaseCalendarError(Exception):
    """Raised only for a misconfiguration, never for an unreachable route.

    A route that cannot be read is *not* an error condition here: it is the
    expected outcome roughly half the time, and the caller's correct response is
    to proceed with ``release_datetime=None``. Raising on it would push every
    snapshot build into a failure path for a fact the system is designed to
    tolerate. Misconfiguration (a disabled calendar, a missing event map) IS
    raised, because it is a defect that will never resolve on retry.
    """


@dataclass(frozen=True)
class ReleaseDateIndex:
    """Release datetimes keyed by registry series name.

    A per-series date can be ambiguous when a release has multiple rows at one
    timestamp (the provider publishes CPI YoY and CPI MoM under the same event
    name and the same instant). For a DATE lookup that is harmless — the
    timestamp is what is taken, not the row — so this index stores the
    **earliest** datetime seen for each series in the window, and records how
    many raw events backed it so ambiguity is visible rather than hidden.
    """

    dates: dict[str, datetime] = field(default_factory=dict)
    #: series name -> number of raw calendar events that matched it.
    match_counts: dict[str, int] = field(default_factory=dict)
    #: True when at least one request succeeded. False means "route unreadable",
    #: which is a DIFFERENT statement from "these series have no releases".
    route_read: bool = False

    def get(self, series: str) -> datetime | None:
        return self.dates.get(series)

    def __bool__(self) -> bool:
        return bool(self.dates)


def _calendar_config() -> ReleaseCalendar:
    return get_registry().release_calendar


def _build_query(cfg: ReleaseCalendar, *, as_of: date) -> dict[str, str]:
    start = as_of - timedelta(days=cfg.window_days_back)
    end = as_of + timedelta(days=cfg.window_days_forward)
    return {
        "provider": cfg.provider,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def _parse_event_datetime(raw: object) -> datetime | None:
    """Parse the provider's timestamp, returning ``None`` rather than guessing.

    The provider returns naive ISO strings (``2026-08-13T08:30:00``). A naive
    datetime is returned as-is rather than being localised: assigning a timezone
    would be an inference this module has no basis for, and an invented offset
    could move a release across a day boundary relative to ``as_of``.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def fetch_release_dates(
    *,
    as_of: date | None = None,
    client: httpx.Client | None = None,
    cfg: ReleaseCalendar | None = None,
) -> ReleaseDateIndex:
    """Read the release calendar once, with retries, returning an honest index.

    Parameters
    ----------
    as_of:
        The window is centred on this date. Defaults to today.
    client:
        Injected for tests. When ``None`` a client is built from settings, with
        **keep-alive disabled** — the local OpenBB server serves 404 on a reused
        connection (see ``openbb_client``'s note), so a pooled client would fail
        on every request after the first.
    cfg:
        Injected for tests; defaults to the loaded registry block.

    Returns
    -------
    ReleaseDateIndex
        ``route_read`` distinguishes "the route answered and these are the
        releases" from "the route could not be read". Both can carry an empty
        ``dates`` map, and conflating them would let a broken route look like a
        quiet calendar.
    """
    config = cfg or _calendar_config()
    if not config.enabled:
        raise ReleaseCalendarError(
            "release_calendar is disabled in config/series_registry.yaml; "
            "enable it before requesting release dates"
        )
    if not config.event_map:
        raise ReleaseCalendarError(
            "release_calendar.event_map is empty; there is no join from the "
            "provider's event names to registry series, so no date can be "
            "attributed to a series"
        )

    # Local calendar date, not UTC's. The window is a calendar-date window sent
    # to a provider that speaks local dates, so a UTC "today" would be yesterday
    # for part of every day in UTC-negative offsets — shifting the window off by
    # one for no benefit. DTZ011 wants an explicit tz; the explicit answer here
    # is "the process's local date", which ``datetime.now()`` with no tzinfo
    # expresses and which is correct precisely because this value is a DATE.
    today = as_of or datetime.now().astimezone().date()
    query = _build_query(config, as_of=today)
    url = f"/api/v1/{config.endpoint.replace('.', '/')}"

    owns_client = client is None
    if client is None:
        openbb = get_settings().openbb
        client = httpx.Client(
            base_url=openbb.base_url.rstrip("/"),
            timeout=openbb.timeout,
            verify=openbb.ssl_verify,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    # Case-insensitive join: the provider's capitalisation varies between rows
    # ("PCE price index" vs "PCE Price index"), and a case-sensitive match would
    # silently drop releases depending on which row arrived first.
    lookup = {name.strip().lower(): series for name, series in config.event_map.items()}

    dates: dict[str, datetime] = {}
    counts: dict[str, int] = {}

    try:
        for attempt in range(1, config.max_attempts + 1):
            try:
                resp = client.get(url, params=query)
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "release calendar attempt %s/%s failed: %s",
                    attempt,
                    config.max_attempts,
                    exc,
                )
                if attempt < config.max_attempts:
                    time.sleep(config.backoff_seconds * attempt)
                continue

            # The provider's failure is a WELL-FORMED body, not an HTTP error:
            # {"detail": "Nasdaq Error -> ...: No record found."}. So a 200 alone
            # does not mean the read succeeded and the results key must be
            # checked explicitly.
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list) or not results:
                logger.warning(
                    "release calendar attempt %s/%s returned no results",
                    attempt,
                    config.max_attempts,
                )
                if attempt < config.max_attempts:
                    time.sleep(config.backoff_seconds * attempt)
                continue

            for event in results:
                if not isinstance(event, dict):
                    continue
                series = lookup.get(str(event.get("event", "")).strip().lower())
                if series is None:
                    continue
                stamp = _parse_event_datetime(event.get("date"))
                if stamp is None:
                    continue
                counts[series] = counts.get(series, 0) + 1
                # Earliest wins: the first publication is when the value became
                # public. A later row at the same instant (a second unit of the
                # same release) must not move the date.
                if series not in dates or stamp < dates[series]:
                    dates[series] = stamp

            return ReleaseDateIndex(dates=dates, match_counts=counts, route_read=True)
    finally:
        if owns_client:
            client.close()

    # Every attempt failed. This is the documented ~50% case, not an exception:
    # return an index whose emptiness is LABELLED as an unread route.
    logger.warning(
        "release calendar unreadable after %s attempts; release_datetime will "
        "stay None for every series (release timing treated as UNKNOWN)",
        config.max_attempts,
    )
    return ReleaseDateIndex(dates={}, match_counts={}, route_read=False)


def release_dates_for_series(
    series: str,
    *,
    index: ReleaseDateIndex | None = None,
    as_of: date | None = None,
) -> datetime | None:
    """The release datetime for one series, or ``None`` when unknown.

    ``None`` genuinely means UNKNOWN and is never satisfiable by
    ``observation_date`` — Section 6's prohibition is on exactly that
    substitution, so this function has no fallback by design.
    """
    idx = index if index is not None else fetch_release_dates(as_of=as_of)
    return idx.get(series)
