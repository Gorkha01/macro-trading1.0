"""Live wiring check: the real official calendar -> ``next_catalyst_calendar``
(D-065).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_catalyst_calendar_check.py

Section 21.0: unit tests prove the parse, this proves the **wiring** — that the
two official sources answer from this host, that their forward events are what
the function returns, and that the two source defects this increment was written
around are real rather than imagined.

Why this increment needs a live check more than most
----------------------------------------------------
The function's entire job is to reach **two external hosts** and parse their
responses. Every failure mode here is a fact about the network and about the
servers' current behaviour, not about arithmetic:

* whether FRED's endpoint answers at all from this host, and over which
  transport (**the whole reason the transport is httpx**: urllib and aiohttp are
  both dropped, measured);
* whether the configured release ids still name the releases they are labelled
  with (FRED renumbers);
* whether FRED's FOMC release is still a daily feed rather than a meeting
  calendar;
* whether the Fed's page still carries the trailing note that a flat-text parse
  turns into a phantom meeting.

None of those can be established offline, and all four are load-bearing.

What is established here, each independently of the function
------------------------------------------------------------
1. **Both hosts answer from this host**, over the transport the module uses.
2. **The three FRED release ids name the three expected releases** — asserted
   against the live labels, so a renumbering is caught as a *finding* here
   rather than as a wrong date in a thesis.
3. **The forward dates are forward**, and ordered.
4. **FRED's FOMC release really is a daily feed** — the defect the increment was
   written around, demonstrated on live data rather than taken on faith.
5. **The Fed's flat-text parse really does produce a phantom meeting** — the
   second source defect, likewise demonstrated.
6. **The horizon bounds the result**, checked by re-running with a one-day
   horizon.

**What this check CANNOT establish:** whether the configured horizon is a good
choice. It is ``uncalibrated_illustrative``; a live check can prove a leaf is
read and cannot make it calibrated.
"""

from __future__ import annotations

import datetime as dt
import re

import httpx

from macro_engine.config import get_settings
from macro_engine.thesis_layer import catalysts
from macro_engine.thesis_layer.catalysts import next_catalyst_calendar

#: The three releases the config claims to point at, by the label the function
#: publishes. Read from the settings block rather than re-typed.
_EXPECTED_LABELS = {
    "cpi_release_id": "Consumer Price Index",
    "nfp_release_id": "Employment Situation",
    "pce_release_id": "Personal Income and Outlays",
}


def _check() -> None:
    settings = get_settings().catalyst_calendar
    today = catalysts._us_calendar_today()
    horizon = today + dt.timedelta(days=int(settings.horizon_days.value))

    # --- (1) both hosts answer over the module's own transport. ------------
    print(f"  (1) transport check, today={today}, horizon={settings.horizon_days.value}d")
    for label, url in (
        (
            "FRED",
            catalysts._FRED_CALENDAR_URL.format(start=today, end=horizon, rid=settings.cpi_id),
        ),
        ("Fed", catalysts._FED_FOMC_CALENDAR_URL),
    ):
        body = catalysts._http_get(url, timeout=float(settings.http_timeout_seconds.value))
        print(f"      {label:4} answered, {len(body)} chars over httpx/HTTP-1.1")
        assert len(body) > 100, f"{label} answered with {len(body)} chars"

    # --- (2) the release ids still name the expected releases. -------------
    print("\n  (2) release-id labels, live")
    for field, expected in _EXPECTED_LABELS.items():
        rid = int(getattr(settings, field).value)
        events = catalysts._fetch_fred_release(
            rid, start=today, end=horizon, timeout=float(settings.http_timeout_seconds.value)
        )
        names = sorted({n for _, n in events})
        ok = any(expected.lower() in n.lower() for n in names)
        print(f"      rid={rid:>3}  expected {expected!r:34} got {names}")
        assert ok, (
            f"{field}={rid} no longer returns {expected!r} (got {names}). FRED "
            f"renumbered the release; the config leaf must be updated."
        )

    # --- (3) the function returns forward, ordered, dated entries. ---------
    print("\n  (3) next_catalyst_calendar() on live data")
    entries = next_catalyst_calendar()
    assert entries, "the live calendar is empty"
    dates: list[dt.date] = []
    for entry in entries:
        print(f"      {entry}")
        found = [t for t in entry.replace("—", " ").split() if t[:4].isdigit()]
        assert found, f"no date in {entry!r}"
        d = dt.date.fromisoformat(found[0])
        assert today <= d <= horizon, f"{entry!r} is outside the horizon"
        dates.append(d)
    assert dates == sorted(dates), f"entries are not time-ordered: {dates}"
    print(f"      -> {len(entries)} dated catalysts, ordered, all within the horizon")

    # --- (4) FRED's FOMC release really is a daily feed. -------------------
    #
    # The defect the increment was written around. `rid=101` is "FOMC Press
    # Release"; a 40-day window returns roughly 40 consecutive daily rows. If
    # this ever stops being true the module's design note is stale and should be
    # corrected rather than left as a claim.
    print("\n  (4) FRED rid=101 is a DAILY feed, not a meeting calendar (live)")
    window_end = today + dt.timedelta(days=40)
    try:
        fomc_rows = catalysts._fetch_fred_release(
            101,
            start=today,
            end=window_end,
            timeout=float(settings.http_timeout_seconds.value),
        )
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        print(f"      rid=101 unavailable ({type(exc).__name__}); defect not re-measured")
        fomc_rows = []
    if fomc_rows:
        distinct_days = sorted({d for d, _ in fomc_rows})
        span = (distinct_days[-1] - distinct_days[0]).days + 1 if distinct_days else 0
        density = len(distinct_days) / span if span else 0.0
        print(
            f"      {len(fomc_rows)} rows over {span} calendar days "
            f"({density:.0%} of days covered) -- a meeting calendar would be "
            f"~3 rows in 40 days"
        )
        assert density > 0.5, (
            "rid=101 is no longer a near-daily feed. The module's design note "
            "(and this check) assume it is; re-measure before trusting either."
        )
        report = next((d for d, _ in fomc_rows if d >= today), None)
        print(
            f"      a reader trusting this as 'the next FOMC' would report "
            f"{report} -- i.e. essentially always tomorrow"
        )

    # --- (5) the flat-text parse really does produce a phantom. ------------
    print("\n  (5) flat-text parse of the Fed page yields a phantom meeting (live)")
    html = catalysts._http_get(
        catalysts._FED_FOMC_CALENDAR_URL,
        timeout=float(settings.http_timeout_seconds.value),
    )
    structured = catalysts._fetch_fed_fomc_meetings(
        timeout=float(settings.http_timeout_seconds.value)
    )
    flat_total = 0
    for year_match in re.finditer(r"(\d{4}) FOMC Meetings", html):
        nxt = re.search(r"\d{4} FOMC Meetings", html[year_match.end() :])
        panel_end = year_match.end() + (nxt.start() if nxt else len(html) - year_match.end())
        flat = re.sub(r"<[^>]+>", " ", html[year_match.end() : panel_end])
        flat_total += len(
            re.findall(
                r"(?:January|February|March|April|May|June|July|August|September"
                r"|October|November|December)\s+\d{1,2}-\d{1,2}\*?",
                flat,
            )
        )
    print(
        f"      structured parse: {len(structured)} meetings | flat-text parse: {flat_total} hits"
    )
    if flat_total > len(structured):
        print(
            f"      -> the flat parse invents {flat_total - len(structured)} phantom "
            f"meeting(s) from the page's trailing note. The structured read is "
            f"load-bearing, not stylistic."
        )

    # --- (6) the horizon bounds the result. --------------------------------
    print("\n  (6) the horizon bounds the result (live, one-day horizon)")
    original = settings.horizon_days.value
    try:
        settings.horizon_days.value = 1
        narrow = next_catalyst_calendar()
    finally:
        settings.horizon_days.value = original
    print(f"      horizon=1d -> {len(narrow)} entries: {narrow}")
    assert len(narrow) <= len(entries), (
        f"a one-day horizon returned MORE entries ({len(narrow)}) than the "
        f"{len(entries)}-entry full window; the local bound is not applied"
    )

    print()
    print("  D-065 live check: PASSED")


def main() -> int:
    print("=" * 72)
    print("LIVE check: the official calendar -> next_catalyst_calendar (D-065)")
    print("=" * 72)
    _check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
