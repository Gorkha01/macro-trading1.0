"""Module 13-adjacent — the forward catalyst calendar (Section 16.4, D-065).

``next_catalyst_calendar`` answers a single question for the thesis: **what
scheduled, official event could move the gap I am trading, and when.** It fills
``TradeIdea.catalysts``, and Section 16.4 is emphatic about where the dates may
come from:

    "MUST pull from FRED release/dates + federalreserve.gov RSS (Section 8,
    matching the companion data-pipeline project's rule) — NEVER a third-party
    calendar."

The sample in Section 16.4 returns three hardcoded **strings** — *"Next CPI
release (FRED release/dates)"* — which names the source but carries no date. A
catalyst with no date is not a catalyst: the entire point of a calendar is to
say *when*. Everything below is about turning those three names into three
dated, measured answers.

What the two sources actually are, measured (D-065)
---------------------------------------------------
**FRED.** ``https://fred.stlouisfed.org/releases/calendar?po=1&ptic=0&vs=..&ve=..&rid=..``
returns a JSON envelope ``{"pager": "<html table>", "ptic": N}``. There is **no
structured JSON event list** — the events are an HTML table inside a JSON
string. Three measured facts about it:

1. **``ptic`` is a pagination TOTAL, not an event count.** A 120-day unfiltered
   window returns ``ptic=2806`` while the first page holds **50 rows**. An
   implementation that reports ``ptic`` as the number of catalysts is off by a
   factor of ~56, and one that assumes the single page is the whole calendar
   sees 1.8% of it. This function therefore reads only the **``rid``-filtered**
   path, where ``ptic`` is 3-4 and the page genuinely is the whole answer.
2. **Without ``rid`` it is one HTTP request per calendar day.** 90 days = 90
   requests, which reliably times out. With ``rid`` it is one paginated call.
   The cost asymmetry is why this function never issues an unfiltered request.
3. **The event date is a human string, not a field.** The table header reads
   ``"Friday October 02, 2026"`` with the event name in an ``<a>`` beneath it.
   The date must be parsed.

**federalreserve.gov.** The Fed's own FOMC calendar page carries the meetings as
structured markup — ``fomc-meeting__month`` → ``"October"`` and
``fomc-meeting__date`` → ``"27-28"`` — grouped under a ``"2026 FOMC Meetings"``
heading, with ``*`` marking a meeting that carries a **Summary of Economic
Projections** (Section 16.4's "dot plot").

Three source defects, measured, that shape this code (D-065)
------------------------------------------------------------
**1. FRED's FOMC release is not a meeting calendar.** Release id **101**,
"FOMC Press Release", returns a row for **every single calendar day** — the
2026-09-19 .. 2026-11-07 window returned 50 consecutive daily rows. An
implementation that read ``rid=101`` and reported "the next FOMC" would report
**tomorrow, every day, forever**. It is a *press-release* feed, not a *meeting*
schedule, and the distinction is exactly the one Section 16.4 draws when it
names ``federalreserve.gov`` as the FOMC source. FOMC dates therefore come from
the Fed, never from FRED.

**2. Flattening the Fed's HTML to text creates phantom meetings.** Stripping
tags from the 2027 panel yields ``"January 26-27 ... September 14-15* ...
Note: A two-day meeting is scheduled for January ..."`` — and a regex over that
flat text matches the trailing note as a *second* January meeting. Measured: the
flat-text parse produced **2027-01-26 and 2027-01-27 as two separate meetings**
from one. The structured markup has no such ambiguity, so the parser reads
``fomc-meeting__month``/``fomc-meeting__date`` and never a flattened panel.

   **D-086 supersedes this entire hazard.** The Fed is no longer scraped:
``economy/fomc_documents`` on the local OpenBB service returns
``date``/``doc_type``/``doc_format``/``url`` as **fields**, so both the meeting
date and the dot-plot flag arrive typed. The parser above is gone, and with it
the possibility of a phantom meeting — there is no markup left to mis-read.
The historical note is kept because the *reason* the scrape existed (FRED's
FOMC release is a press-release feed, not a meeting calendar) is still why the
catalyst is sourced from the Fed rather than from FRED.

**3. A cross-month range must not be split.** The Fed writes some meetings as
a single month with a day range (``"January" 26-27``). A naive "month + first
day" read would silently drop the second day of every two-day meeting; the
meeting is dated by its **last** day here, which is when the decision lands.

What this function will not do
------------------------------
**It will not invent a date.** Every returned string contains a real date
parsed from the named source. If a source yields nothing forward, that catalyst
is **omitted** rather than emitted as a dateless placeholder — the sample's
``"Next CPI release (FRED release/dates)"`` is precisely the output this
function refuses to produce, because it reads as a scheduled event while
carrying no schedule.

**It will not silently return an empty list when every source failed.** An
empty calendar is a legitimate answer only when the sources were reached and
had nothing; if every source errored, the caller gets an exception. A thesis
whose calendar is empty because the network was down is worse than one with no
calendar, because the emptiness is indistinguishable from "no catalysts" (the
silence failure mode, D-054).

Why the transport is ``httpx`` with a pinned ``curl/8.0`` UA (D-065, corrected by D-087.25)
-------------------------------------------------------------------------------------------
Measured on this host, 2026-09-19, all against the same working URL:

======================================  ==========  ============================
client                                  result      note
======================================  ==========  ============================
``curl`` (CLI)                          **200**     the endpoint is fine
``httpx``, HTTP/1.1, UA ``curl/8.0``    **200**     what this module uses
``urllib.request``                      dropped     ``RemoteDisconnected``
``aiohttp`` (what OpenBB uses)          dropped     ``TimeoutError``
======================================  ==========  ============================

**The two right-hand "dropped" cells were re-measured on 2026-09-21 and DO NOT
REPRODUCE (D-087.25).** ``aiohttp`` reaches this endpoint in **~0.1 s** and
``urllib`` in **~0.15 s**; neither is filtered. The client library was never the
discriminator. **The User-Agent is:**

===============================  ==========================
User-Agent sent                  result
===============================  ==========================
``curl/8.0``                     **200 in ~0.2 s**
``python-httpx/...`` (default)   **200 in ~0.2 s**
a real browser UA (Chrome etc.)  **HANGS — every time**
``""`` (empty)                   **HANGS — every time**
===============================  ==========================

FRED's releases-calendar page serves a **tool-like** UA and stalls a
**browser-like or absent** one (a true read timeout: the connection is
established and the body never begins). That is why ``obb.economy.calendar``
times out here on **every** path including the single-call ``release_id`` one —
``openbb_core.provider.utils.client.get_user_agent()`` returns
``random.choice`` of seven **real browser** UA strings and applies it
unconditionally, with no supported override (D-087.25).

**So the pinned UA is the load-bearing part, not the choice of library.**
``httpx`` is still what this module uses (it is already a project dependency —
``data_layer/openbb_client.py`` uses it for the local-API path), but had it been
``aiohttp`` **with this UA** it would work equally. ``tools/
fred_calendar_diagnosis.py`` reproduces the whole matrix on demand.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from zoneinfo import ZoneInfo

import httpx

from macro_engine.config import get_settings
from macro_engine.models.contracts import utc_now

__all__ = [
    "CatalystSourceError",
    "next_catalyst_calendar",
]

logger = logging.getLogger(__name__)

#: The FRED releases-calendar JSON endpoint. The three query parameters that
#: matter: ``ptic=0`` (no importance filter), ``vs``/``ve`` (the window), and
#: ``rid`` (the release id — the ONLY filter that does not cost one request per
#: day).
_FRED_CALENDAR_URL = (
    "https://fred.stlouisfed.org/releases/calendar?po=1&ptic=0&vs={start}&ve={end}&rid={rid}"
)

#: The STRUCTURED FOMC document command's path on the local OpenBB service (D-086).
#: Returns ``date``/``doc_type``/``doc_format``/``url`` as fields, so the meeting
#: date and the dot-plot flag are both read rather than parsed out of markup.
#: ``provider=federal_reserve`` is required; ``year=`` is the only filter that
#: actually bites (measured — see ``_fetch_fed_fomc_meetings``).
#:
#: **The host is NOT part of this constant, and that is the fix (O-113).** This
#: used to be the full absolute URL with ``127.0.0.1:6901`` baked in, and the
#: port was the **dead** one — so the FOMC catalyst returned HTTP 502 on every
#: call while ``:6900`` served the same command (34 rows). Hard-coding the host
#: also made the module blind to ``settings.openbb.base_url`` and to the
#: ``OPENBB_API_URL`` override, which is exactly how a deployment or a port
#: change turns a working feature into a silent outage. The base is resolved from
#: config at call time by :func:`_fomc_documents_url`.
_FOMC_DOCUMENTS_PATH = "/api/v1/economy/fomc_documents"


def _fomc_documents_url(base: str | None = None) -> str:
    """The FOMC documents endpoint, rebased on the configured OpenBB base URL.

    ``base`` is accepted for tests; production callers pass nothing and get
    ``settings.openbb.base_url``. Deriving the URL rather than storing it keeps
    **one** source of truth for the host, so a port change is a config edit and
    not a code change — the O-111 lesson (*a check that does not ask is a check
    that cannot answer*) applied to the fetch itself.
    """
    if base is None:
        base = get_settings().openbb.base_url
    return f"{base.rstrip('/')}{_FOMC_DOCUMENTS_PATH}"


#: The ``User-Agent`` is what makes the endpoint respond, and it is the ONLY
#: part of this pair that is load-bearing (corrected by D-087.25). The original
#: note blamed urllib's and aiohttp's TLS/HTTP fingerprint; re-measured
#: 2026-09-21, **both reach FRED in ~0.1-0.15 s**, and what actually
#: distinguishes a working request from a hanging one is a **tool-like** UA
#: versus a **browser-like or empty** one. ``curl/8.0`` is the measured-good
#: value; do not "modernise" it to a browser string.
_REQUEST_HEADERS = {
    "Accept": "application/json, text/html;q=0.9",
    "User-Agent": "curl/8.0",
}

#: FRED's table date header: ``"Friday October 02, 2026"``.
_FRED_DATE_RE = re.compile(r">(\w+day (\w+) (\d{1,2}), (\d{4}))<")

#: The event name inside a date group: ``<a href="/release?rid=10">Consumer
#: Price Index</a>``.
_FRED_EVENT_RE = re.compile(r'<a href="/release\?rid=(\d+)">([^<]+)</a>')

#: NOTE (D-086): the two FOMC HTML regexes that used to live here
#: (`_FED_MONTH_RE` for the month/day cells, `_FED_YEAR_RE` for the year
#: panels) were removed with the scrape they served. The Fed's calendar page is
#: no longer fetched at all — see `_fetch_fed_fomc_meetings`, which reads
#: `economy/fomc_documents` and takes the date and the dot-plot flag as typed
#: fields. Deleting them rather than leaving them defined-and-unused is the
#: point: a regex that nothing calls still reads as a live parser to the next
#: reader, and this module has already been burned once by a parser that could
#: not be trusted (defect 2 in the docstring above).

_MONTHS: dict[str, int] = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


class CatalystSourceError(RuntimeError):
    """Raised when **every** configured catalyst source failed to answer.

    Not the same as "no catalysts". A source that answers and has no forward
    event yields nothing; only a source that cannot be reached raises, and only
    when no source at all produced a date. The distinction is what keeps an
    empty calendar from meaning two different things (D-054).
    """


#: The timezone the catalysts are scheduled in. Every event this function
#: returns is a **US** release or meeting, and both sources publish their dates
#: in US calendar terms. Using UTC's date instead would roll the calendar over
#: up to a day early during the US evening, so a release scheduled for tomorrow
#: would be filtered out as "today" — an off-by-one that only shows up for a few
#: hours each day, which is the worst kind. ``zoneinfo`` is stdlib (3.9+) and
#: carries the DST rules, so the boundary is correct in both halves of the year.
_US_EASTERN = ZoneInfo("America/New_York")


def _us_calendar_today() -> date:
    """Today's date **as the US calendar sees it**.

    Deliberately not ``utc_now().date()``: the two disagree for several hours
    daily, and every date this module handles is a US-scheduled one.
    """
    return utc_now().astimezone(_US_EASTERN).date()


def _http_get(url: str, *, timeout: float) -> str:
    """One GET over HTTP/1.1, returning decoded text.

    HTTP/1.1 is forced rather than negotiated: FRED answers HTTP/1.1 and drops
    the HTTP/2 preface (measured). Raises ``httpx.HTTPError``.
    """
    with httpx.Client(http2=False, timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=_REQUEST_HEADERS)
        response.raise_for_status()
        return response.text


def _fetch_fred_release(
    release_id: int, *, start: date, end: date, timeout: float
) -> list[tuple[date, str]]:
    """Forward events for one FRED release id, as ``[(date, name), ...]``.

    Uses the ``rid``-filtered path exclusively: it is **one** paginated request
    for the whole window, whereas the unfiltered path issues one request per
    calendar day and times out. The ``ptic`` field is deliberately **not** read;
    it is a pagination total (measured 2806 for a window whose first page holds
    50 rows), not the event count.
    """
    url = _FRED_CALENDAR_URL.format(start=start.isoformat(), end=end.isoformat(), rid=release_id)
    payload = json.loads(_http_get(url, timeout=timeout))

    # Guard the body SHAPE before touching it. The per-release handler in
    # `next_catalyst_calendar` catches `(httpx.HTTPError, TimeoutError,
    # ValueError)`, so anything else escaping here aborts the WHOLE calendar
    # instead of failing this one release. MEASURED 2026-10-06: a JSON list body
    # raised `AttributeError: 'list' object has no attribute 'get'`, which that
    # handler does not catch. The FOMC reader already guards the same shape
    # (`if isinstance(payload, dict) else None`), so this is the missing half of
    # one rule rather than a new one.
    if not isinstance(payload, dict):
        raise ValueError(
            f"FRED releases calendar for rid={release_id} returned "
            f"{type(payload).__name__}, not the documented object carrying a "
            f"'pager' member"
        )

    events: list[tuple[date, str]] = []
    current: date | None = None
    # The "pager" member is the HTML table. Split on row openers and carry the
    # most recent date-header forward to the event rows beneath it.
    for row in re.split(r"<tr[^>]*>", payload.get("pager", "")):
        header = _FRED_DATE_RE.search(row)
        if header and "colspan" in row:
            month = _MONTHS.get(header.group(2))
            if month is None:
                # An unrecognised month is a PARSE failure of this source, so it
                # is raised as a ValueError for the caller's per-release handler
                # rather than escaping as a `KeyError` (F-CAT-001, measured:
                # `KeyError: 'Fooary'`).
                raise ValueError(
                    f"unrecognised month {header.group(2)!r} in a FRED date header "
                    f"({header.group(1)!r})"
                )
            current = date(int(header.group(4)), month, int(header.group(3)))
            continue
        event = _FRED_EVENT_RE.search(row)
        if event and current is not None:
            events.append((current, event.group(2).strip()))
    return events


def _fetch_fed_fomc_meetings(
    *, timeout: float, as_of: date | None = None
) -> list[tuple[date, bool]]:
    """Forward FOMC meetings as ``[(last_day, has_projections), ...]``.

    **D-086: this reads a STRUCTURED COMMAND, not the Fed's HTML.** Measured
    live 2026-09-21 against the same local OpenBB service the rest of the data
    layer uses:

    ``economy/fomc_documents?provider=federal_reserve`` returns rows carrying
    ``date``, ``doc_type``, ``doc_format`` and ``url`` as **fields**. The
    meeting date is the ``monetary_policy`` row's date, and the dot-plot flag
    is the presence of a ``projections`` row on that same date.

    Why this replaced the scrape (the scrape is strictly worse, not merely
    less tidy):

    * **The flag was being re-derived.** The Fed's markup encodes "has
      projections" as a trailing ``*`` on the day range (``"27-28*"``), which
      the old parser had to strip and interpret. The command returns
      ``doc_type='projections'`` as a typed field — the fact itself, not a
      markup convention standing in for it.
    * **The history is deeper and cleaner.** The scrape parsed meetings back to
      2021; the command carries **5837 rows back to 1959**, of which 88 are
      ``monetary_policy``. More history is not automatically wanted, but it
      means the *forward* filter below is what bounds the result, rather than
      the source's own reach.
    * **One less HTML parser, two fewer regexes, and the phantom-meeting
      hazard disappears.** Defect 2 above (a flattened panel inventing a
      second January meeting) is structurally impossible when the dates arrive
      as typed fields.

    **``year`` is the filter that works, and it is the ONLY one.** Measured:
    ``year=2026`` returns 34 rows (the whole 2026 document set);
    ``start_date=2026-01-01`` and ``limit=50`` are **silently ignored** and
    both return all 5837 rows. That is the same accept-and-ignore class as the
    ``realtime_start`` decoy documented in ``docs/OPENBB_UTILIZATION_AUDIT.md``
    §5.3, so this function asks for the years it needs and then applies its own
    date bound locally — a filter that is *verified* to bite rather than one
    that is merely *written*.

    Falls back to the previous years' worth of documents when the window spans
    a year boundary, because a December ``as_of`` with a 90-day horizon needs
    the *next* year's calendar, which does not exist yet and must not be
    fabricated.

    **An unpublished year is a 404, not an empty set (measured 2026-09-22).**
    The comment that used to sit here claimed *"asking for a year the Fed has
    not published returns an empty set rather than an error, which is the
    correct reading."* That is **false**, and it was never measured:

    ===========================  =========  ==============================
    request                      status     body
    ===========================  =========  ==============================
    ``year=2025`` (published)    **200**    the 2025 document set
    ``year=2026`` (published)    **200**    the 2026 document set
    ``year=2027`` (not yet)      **404**    ``{"detail":"Not Found"}``
    ``year=2030`` (not yet)      **404**    ``{"detail":"Not Found"}``
    ``year=notayear`` (invalid)  **404**    ``{"detail":"Not Found"}``
    ===========================  =========  ==============================

    Repeated identically on re-request, so the 404 is deterministic rather than
    a flaky edge. **404 is the service's single way of saying "no such document
    set"** — it does not distinguish *unpublished* from *invalid*, which is fine
    here because both mean "this year contributes no rows".

    **Why the distinction matters rather than being cosmetic.** A 404 raises
    ``HTTPStatusError`` from ``raise_for_status()``, so before this fix every
    December run logged ``FOMC documents for 2027 failed: ...`` at **WARNING** —
    byte-identical in shape to the dead-port outage that cost this project hours
    (D-087.10/.13). **An expected absence reported as a failure is how a real
    failure gets ignored**: a reader who sees that warning every December for a
    reason that is normal learns to skip it, and then skips the one that is not.
    So a 404 is now ``INFO`` — the year is simply not published yet — while
    everything else (5xx, a transport error, malformed JSON, an empty body)
    stays ``WARNING``, because those *are* failures.
    """
    today = as_of or _us_calendar_today()
    # Ask for this year and the next: a horizon that crosses a year boundary
    # needs both. The next year is usually UNPUBLISHED and answers 404, which
    # is the ordinary case rather than a fault -- see the module note above.
    years = sorted({today.year, today.year + 1})

    rows: list[dict[str, object]] = []
    documents_url = _fomc_documents_url()
    for year in years:
        url = f"{documents_url}?provider=federal_reserve&year={year}"
        try:
            body = _http_get(url, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                # The Fed publishes one document set per year. A year it has
                # not published yet (or a malformed one) answers 404, which is
                # an EXPECTED ABSENCE, not a failure. Logging it at WARNING
                # would put a normal December event in the same channel as a
                # real outage, which is how a real outage gets ignored.
                logger.info("FOMC documents for %s not published yet (404)", year)
            else:
                logger.warning("FOMC documents for %s failed: %s", year, exc)
            continue
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("FOMC documents for %s failed: %s", year, exc)
            continue

        # Parse separately from the fetch so that a truncated body is reported
        # as what it is (a malformed response) rather than as a transport
        # failure, and so that an empty body cannot reach `json.loads` at all.
        if not body.strip():
            logger.warning("FOMC documents for %s returned an empty body", year)
            continue
        try:
            payload = json.loads(body)
        except ValueError as exc:
            logger.warning("FOMC documents for %s returned malformed JSON: %s", year, exc)
            continue

        results = payload.get("results") if isinstance(payload, dict) else None
        if isinstance(results, list):
            rows.extend(results)

    by_date: dict[date, bool] = {}
    for row in rows:
        raw_date = row.get("date")
        doc_type = str(row.get("doc_type") or "")
        if raw_date is None:
            continue
        try:
            when = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        if doc_type == "monetary_policy":
            # A meeting exists at this date. `or` rather than assignment so a
            # projections row seen FIRST is not cleared by the policy row.
            by_date[when] = by_date.get(when, False)
        elif doc_type == "projections":
            by_date[when] = True

    return sorted(by_date.items())


def next_catalyst_calendar(as_of: date | None = None) -> list[str]:
    """The forward official calendar, as dated strings (Section 16.4).

    Returns one entry per catalyst that a source could date within
    ``[as_of, as_of + horizon_days]``, earliest first. A catalyst whose source
    answered but had no event in the window is omitted; if **no** source
    answered, raises ``CatalystSourceError`` so that an unreachable calendar
    cannot read as an empty one.

    The horizon bounds the result **locally** as well as the request, because a
    source that ignores the window returns rows a request parameter cannot
    un-return.
    """
    settings = get_settings().catalyst_calendar
    today = as_of or _us_calendar_today()
    # The horizon is applied TWICE, deliberately. Once as a request parameter
    # (the source is asked for a bounded window, which keeps the payload small)
    # and once as a LOCAL filter below. The second is not redundant: a source
    # that ignores or mis-handles the window returns everything it has, and a
    # request parameter cannot un-return a row. Measured while testing this
    # increment: a one-day horizon still received a 60-day event because only the
    # request was bounded. A horizon that bounds the request but not the result is
    # a horizon that does not bound anything.
    horizon_ordinal = today.toordinal() + int(settings.horizon_days.value)
    horizon = date.fromordinal(horizon_ordinal)
    timeout = float(settings.http_timeout_seconds.value)

    entries: list[tuple[date, str]] = []
    answered = 0

    # --- Catalyst 1: CPI, from the FRED releases calendar (rid=10). ---------
    releases = (
        ("CPI", settings.cpi_id, "Consumer Price Index"),
        ("NFP", settings.nfp_id, "Employment Situation"),
        ("PCE", settings.pce_id, "Personal Income and Outlays"),
    )
    for label, rid, expected_name in releases:
        try:
            events = _fetch_fred_release(rid, start=today, end=horizon, timeout=timeout)
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            logger.warning("catalyst source FRED rid=%s (%s) failed: %s", rid, label, exc)
            continue
        answered += 1
        forward = [(d, n) for d, n in events if today <= d <= horizon]
        # Each release should carry exactly one release name; a mismatched name
        # means the release id points somewhere else (FRED renumbers releases),
        # which must be loud rather than silently relabelled.
        if forward and not any(expected_name.lower() in n.lower() for _, n in forward):
            logger.warning(
                "FRED rid=%s was configured as %s but returned %r",
                rid,
                label,
                sorted({n for _, n in forward}),
            )
        if forward:
            when = min(forward)[0]
            entries.append((when, f"{label} release ({expected_name}) — {when.isoformat()}"))

    # --- Catalyst 4: the next FOMC meeting, from the Fed. ------------------
    # D-086: sourced from the structured `economy/fomc_documents` command on the
    # local OpenBB service rather than by scraping the Fed's calendar HTML. The
    # `answered` accounting is unchanged in spirit — a command that returned is
    # an answered source, and one that raised is not — but it now counts a
    # command that was reached rather than an HTML page that downloaded.
    try:
        meetings = _fetch_fed_fomc_meetings(timeout=timeout, as_of=as_of)
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning("catalyst source economy/fomc_documents failed: %s", exc)
        meetings = []
    else:
        # An EMPTY history is not an answered source. The command is reachable
        # and returned nothing, which would make `answered += 1` claim coverage
        # this run did not have — the same conflation (reachable-but-empty vs
        # never-attempted) that D-085 fixed in the release-calendar path.
        if meetings:
            answered += 1
        else:
            logger.warning(
                "economy/fomc_documents returned no dated FOMC documents; "
                "not counted as an answered source"
            )
        forward_meetings = [(d, proj) for d, proj in meetings if today <= d <= horizon]
        if forward_meetings:
            when, has_projections = min(forward_meetings)
            detail = " + projections" if has_projections else ""
            entries.append((when, f"FOMC meeting{detail} — {when.isoformat()}"))

    if answered == 0:
        raise CatalystSourceError(
            "no catalyst source answered: FRED (rid "
            f"{settings.cpi_id}/{settings.nfp_id}/{settings.pce_id}) and "
            f"{_fomc_documents_url()} all failed. An empty calendar here would be "
            "indistinguishable from a genuinely quiet calendar, so it is an error "
            "rather than a silent []."
        )

    entries.sort(key=lambda pair: pair[0])
    return [text for _, text in entries]
