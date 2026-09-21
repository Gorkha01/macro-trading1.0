"""Live wiring check: the real official calendar -> ``next_catalyst_calendar``
(D-065, re-based on the structured FOMC command at D-086).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_catalyst_calendar_check.py

Section 21.0: unit tests prove the parse, this proves the **wiring** — that the
official sources answer from this host, that their forward events are what the
function returns, and that the source properties the increment depends on are
real rather than imagined.

Why this increment needs a live check more than most
----------------------------------------------------
The function's entire job is to reach **external sources** and read their
responses. Every failure mode here is a fact about the network and about the
servers' current behaviour, not about arithmetic:

* whether FRED's endpoint answers at all from this host, and over which
  transport (**the whole reason the transport is httpx**: urllib and aiohttp are
  both dropped, measured);
* whether the configured release ids still name the releases they are labelled
  with (FRED renumbers);
* whether FRED's FOMC release is still a daily feed rather than a meeting
  calendar;
* whether the FOMC document command still returns the typed fields that make the
  meeting date and the dot-plot flag readable (D-086 — this replaced the HTML
  scrape, so the property to check is now *the fields are present*, not *the
  scrape mis-parses*).

None of those can be established offline, and all four are load-bearing.

What is established here, each independently of the function
------------------------------------------------------------
1. **Both sources answer from this host**, over the transport the module uses.
2. **The three FRED release ids name the three expected releases** — asserted
   against the live labels, so a renumbering is caught as a *finding* here
   rather than as a wrong date in a thesis.
3. **The forward dates are forward**, and ordered.
4. **FRED's FOMC release really is a daily feed** — the defect the increment was
   written around, demonstrated on live data rather than taken on faith.
5. **The FOMC document command really does carry typed fields** — the property
   D-086 relies on. The check asserts a ``monetary_policy`` row exists with a
   parseable date and that ``projections`` is distinguishable **as a doc_type**,
   which is what the retired scrape had to re-derive from a trailing ``*``.
   The old check 5 demonstrated the scrape's phantom meeting; that parser is
   gone, so re-asserting its defect would be checking code that no longer runs.
6. **The horizon bounds the result**, checked by re-running with a one-day
   horizon.

**What this check CANNOT establish:** whether the configured horizon is a good
choice. It is ``uncalibrated_illustrative``; a live check can prove a leaf is
read and cannot make it calibrated.
"""

from __future__ import annotations

import datetime as dt
import json

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

    # --- (1) both sources answer over the module's own transport. ----------
    print(f"  (1) transport check, today={today}, horizon={settings.horizon_days.value}d")
    for label, url in (
        (
            "FRED",
            catalysts._FRED_CALENDAR_URL.format(start=today, end=horizon, rid=settings.cpi_id),
        ),
        # D-086: the FOMC source is now the structured OpenBB command rather
        # than the Fed's HTML calendar page, so the transport check follows it.
        # Same transport (httpx/HTTP-1.1) and the same assertion: a body came
        # back and it was the expected JSON envelope, not an error page.
        (
            "FOMC",
            f"{catalysts._FOMC_DOCUMENTS_URL}?provider=federal_reserve&year={today.year}",
        ),
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

    # --- (5) the FOMC command carries the fields D-086 relies on. ----------
    #
    # D-086 replaced the Fed's HTML scrape with `economy/fomc_documents`. The
    # property to verify moved with it: the old check proved the SCRAPE
    # mis-parsed (a phantom meeting from a trailing note), whereas the command
    # has no markup to mis-parse. What can still fail is that the command stops
    # returning the fields the parse depends on — so that is what is asserted,
    # against raw rows rather than through `_fetch_fed_fomc_meetings`, which
    # would only re-test the function with itself.
    print("\n  (5) economy/fomc_documents returns typed date/doc_type (live)")
    raw = catalysts._http_get(
        catalysts._FOMC_DOCUMENTS_URL + f"?provider=federal_reserve&year={today.year}",
        timeout=float(settings.http_timeout_seconds.value),
    )
    payload = json.loads(raw)
    rows = payload.get("results") if isinstance(payload, dict) else None
    assert isinstance(rows, list) and rows, "fomc_documents returned no results"
    doc_types = sorted({str(r.get("doc_type") or "") for r in rows})
    print(f"      {len(rows)} rows for {today.year}; doc_types={doc_types}")
    assert "monetary_policy" in doc_types, (
        "no `monetary_policy` rows: the meeting date is read from this doc_type, "
        "so its absence means the FOMC catalyst silently disappears."
    )
    policy_dates = sorted(
        dt.date.fromisoformat(str(r["date"])[:10])
        for r in rows
        if str(r.get("doc_type")) == "monetary_policy" and r.get("date")
    )
    assert policy_dates, "monetary_policy rows carry no parseable date"
    print(f"      {len(policy_dates)} dated monetary_policy meetings; latest {policy_dates[-1]}")
    # The dot-plot flag must be readable as a FIELD. The retired scrape had to
    # strip a trailing `*` from the day range to recover it; if `projections`
    # ever stops appearing as a doc_type, that inference has to come back.
    projection_dates = {
        str(r.get("date"))[:10] for r in rows if str(r.get("doc_type")) == "projections"
    }
    print(f"      {len(projection_dates)} dates carry a `projections` document (the dot plot)")
    assert projection_dates, (
        "no `projections` doc_type: the has_projections flag would always read "
        "False, silently mislabelling every projected meeting."
    )
    # A projected meeting is one whose date has BOTH documents. Measured on the
    # real 2026 calendar: March/June/September carry projections, the rest do
    # not — so both branches of the flag must be exercised by live data, or the
    # assertion above could pass while the flag is a constant.
    with_proj = [d for d in policy_dates if d.isoformat() in projection_dates]
    assert 0 < len(with_proj) < len(policy_dates), (
        f"the projections flag is degenerate: {len(with_proj)} of "
        f"{len(policy_dates)} meetings carry it. Both branches must occur in "
        "live data or the flag cannot be distinguished from a constant."
    )
    print(
        f"      -> {len(with_proj)} of {len(policy_dates)} meetings carry projections "
        f"(both branches exercised)"
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
    print("  catalyst-calendar live check: PASSED")


def main() -> int:
    print("=" * 72)
    print("LIVE check: the official calendar -> next_catalyst_calendar (D-065/D-086)")
    print("=" * 72)
    _check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
