"""Tests for ``next_catalyst_calendar`` (§16.4, D-065, D-086).

The defects this file exists to pin
-----------------------------------
1. **The sample returns dateless strings.** §16.4 returns
   ``"Next CPI release (FRED release/dates)"`` — it names the source and omits
   the schedule. ``test_every_entry_carries_a_real_date`` is the pin: a
   catalyst with no date is not a catalyst.
2. **``ptic`` is a pagination total, not an event count.** Measured 2806 for a
   window whose first page holds 50 rows. ``test_ptic_is_never_read_as_a_count``
   is the pin.
3. **FRED's FOMC release is a daily feed, not a meeting calendar.** ``rid=101``
   returns a row for *every* calendar day, so a reader that used it would
   report the next FOMC as *tomorrow, forever*.
   ``test_fomc_dates_come_from_the_fed_not_fred`` and
   ``test_a_daily_feed_would_be_rejected_as_a_meeting_calendar`` are the pins.
4. **Flattening unstructured text creates phantom meetings.** This defect was
   originally pinned against the Fed's HTML calendar panel (the 2027 panel's
   trailing "January 25-26, 2028" note produced a phantom 2027 January
   meeting). **D-086 replaced that source with the structured
   ``economy/fomc_documents`` command**, so the markup is gone — but the
   *class* of defect did not go away, it moved. The pins are now
   ``test_meeting_dates_come_from_the_typed_field_not_the_url`` (the date must
   be read from the ``date`` field, not inferred from the document URL, which
   also carries dates for projections and minutes) and
   ``test_the_projections_marker_comes_from_a_document_not_a_suffix`` (the
   dot-plot flag comes from a ``projections`` row, not from a ``*`` convention
   on a day range).
5. **A source that failed must not read as a quiet calendar.** D-054's silence
   failure. ``test_every_source_failing_raises_not_returns_empty``.
6. **A reachable-but-empty FOMC source is not an answered source.** D-085's
   conflation class, applied to the new command.
   ``test_a_reachable_but_empty_fomc_source_is_not_an_answered_source``.
7. **An expected absence was reported as a failure (O-111's neighbour).**
   Measured 2026-09-22: an unpublished ``year=`` answers **404**, not an empty
   results list, so ``raise_for_status()`` raised and every December run logged
   ``FOMC documents for 2027 failed`` at WARNING — the same shape as a real
   outage. The fixture that should have caught this encoded the *intended*
   ``{"results": []}`` rather than the *measured* 404, which is exactly how it
   survived. The pins are
   ``test_an_unpublished_year_is_an_expected_absence``,
   ``test_a_genuine_fomc_failure_is_still_loud`` (the negative control), and
   ``test_an_empty_or_malformed_fomc_body_does_not_crash``.

The transport is monkeypatched for the offline tests; the live tests are marked
``network`` and deselected by default, so the suite stays deterministic.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from macro_engine.config import get_settings
from macro_engine.thesis_layer import catalysts
from macro_engine.thesis_layer.catalysts import (
    CatalystSourceError,
    next_catalyst_calendar,
)

# ---------------------------------------------------------------------------
# Fixtures: real, captured payloads
# ---------------------------------------------------------------------------

#: A real FRED ``pager`` for rid=10 (CPI), captured 2026-09-19 and trimmed to
#: the three forward events. Note ``ptic`` = **3** here (the filtered path),
#: which is the only path this function may use.
_FRED_CPI_PAGER = (
    '    <div>\n    <table class="table table-condensed table-standard-theme">\n'
    "        <tbody>\n"
    '            <tr class="odd">\n    <td text-align="left" colspan="2">\n'
    '        <span style="font-weight: bold;">Wednesday October 14, 2026</span>'
    ' <span style="float: right; font-weight: bold;">Updated</span>    </td>\n</tr>\n'
    '    <tr>\n    <td nowrap style="width:5%; text-align:right">\n'
    '          8:30 am      </td>\n    <td text-align="left">\n'
    '        <a href="/release?rid=10">Consumer Price Index</a>\n'
    '                    <i class="fa fa-check fa-lg"></i>\n    </td>\n</tr>\n'
    '            <tr class="odd">\n    <td text-align="left" colspan="2">\n'
    '        <span style="font-weight: bold;">Tuesday November 10, 2026</span>    </td>\n</tr>\n'
    '    <tr>\n    <td nowrap style="width:5%; text-align:right">\n'
    '          8:30 am      </td>\n    <td text-align="left">\n'
    '        <a href="/release?rid=10">Consumer Price Index</a>\n    </td>\n</tr>\n'
    '            <tr class="odd">\n    <td text-align="left" colspan="2">\n'
    '        <span style="font-weight: bold;">Thursday December 10, 2026</span>    </td>\n</tr>\n'
    '    <tr>\n    <td nowrap style="width:5%; text-align:right">\n'
    '          8:30 am      </td>\n    <td text-align="left">\n'
    '        <a href="/release?rid=10">Consumer Price Index</a>\n    </td>\n</tr>\n'
    "        </tbody>\n    </table>\n    </div>\n"
)

#: A real ``economy/fomc_documents`` response for ``year=2026``, shaped exactly
#: as measured live 2026-09-21: rows carry ``date``/``doc_type``/``doc_format``/
#: ``url`` as typed fields. Trimmed to the three 2026 meetings this suite needs,
#: with the December meeting carrying BOTH a ``monetary_policy`` row and a
#: ``projections`` row — which is the shape that encodes §16.4's "dot plot".
#:
#: The URLs deliberately carry *different* dates from the ``date`` field (a real
#: property of the Fed's document paths: minutes and projections are posted on
#: their own URLs), so a reader that parsed the date out of the URL instead of
#: reading the field would attribute the wrong day. That is defect 4's pin.
_FOMC_2026 = {
    "results": [
        {
            "date": "2026-10-28",
            "doc_type": "monetary_policy",
            "doc_format": "html",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm",
        },
        {
            "date": "2026-12-09",
            "doc_type": "monetary_policy",
            "doc_format": "html",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261209a.htm",
        },
        {
            "date": "2026-12-09",
            "doc_type": "projections",
            "doc_format": "pdf",
            "url": "https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl20261209.pdf",
        },
    ]
}

#: A captured ``year=2027`` response: one January meeting with no projections.
#: Kept separate so the year-boundary path is exercised.
#:
#: **This was 404 in production when it was captured (measured 2026-09-22).**
#: The Fed publishes one document set per calendar year, and as of the capture
#: date the 2027 set did not exist yet. The live response was
#: ``404 {"detail":"Not Found"}``. The fixture below is deliberately kept in a
#: shape that a *published* year would have, purely so that
#: ``test_the_year_boundary_is_crossed`` can prove the second request is issued
#: and its rows are read; the **absence** case is pinned separately by
#: ``test_an_unpublished_year_is_an_expected_absence``. Encoding only the
#: published shape here is what let the 404 defect hide: the fixture asserted
#: the behaviour the code intended (``{"results": []}``) rather than the one the
#: service actually returns.
_FOMC_2027 = {
    "results": [
        {
            "date": "2027-01-27",
            "doc_type": "monetary_policy",
            "doc_format": "html",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20270127a.htm",
        },
    ]
}

#: A frozen "today" inside the captured window, so the forward filter is exact.
_TODAY = dt.date(2026, 9, 19)

#: The two hosts the module is allowed to call. NOTE (D-086): the Fed host is
#: the local OpenBB service now — the FOMC source is the local OpenBB command,
#: not `www.federalreserve.gov`. FRED is still read directly by `httpx` (its
#: OpenBB alternative is broken by a transport-fingerprint block, §5.3 of the
#: audit), so both hosts remain, but only one of them is a scrape.
_FRED_HOST = "fred.stlouisfed.org"

#: **The FOMC host is DERIVED, never spelled out (O-113).** It used to be the
#: literal `"127.0.0.1:6901/api/v1/economy/fomc_documents"` — the *dead* port —
#: and the source hard-coded the same literal, so the stub matched the bug
#: exactly and the test passed while production 502'd on every call. A test that
#: reproduces the implementation's mistake instead of the contract is worse than
#: no test: it converts an outage into a green check.
#:
#: Reading the path from the module under test and the host from config means
#: the stub tracks whatever the code actually calls. If the code regresses to a
#: literal host, `test_the_fomc_fetch_derives_its_host_from_config` fails.
_FOMC_HOST = f"{urlparse(catalysts._fomc_documents_url()).netloc}{catalysts._FOMC_DOCUMENTS_PATH}"


def _fomc_payload_for_year(year: int) -> dict[str, Any]:
    """The captured FOMC document set for one year, or an empty one."""
    if year == 2026:
        return _FOMC_2026
    if year == 2027:
        return _FOMC_2027
    return {"results": []}


def _fake_get(
    *,
    fred_pager: str | None = _FRED_CPI_PAGER,
    ptic: int = 3,
    fomc: dict[int, dict[str, Any]] | None = None,
    fomc_error: bool = False,
) -> Any:
    """Build a ``_http_get`` replacement routing by host.

    ``fomc`` overrides the per-year document sets; ``fomc_error`` makes the
    FOMC command raise, which is how the "every source failed" path is reached
    now that FRED and the FOMC command are the two sources.
    """

    def _get(url: str, *, timeout: float) -> str:
        if _FRED_HOST in url:
            if fred_pager is None:
                raise httpx.ConnectError("fred down")
            return json.dumps({"pager": fred_pager, "ptic": ptic})
        if _FOMC_HOST in url:
            if fomc_error:
                raise httpx.ConnectError("fomc documents down")
            year = 0
            for token in url.split("&"):
                if token.startswith("year="):
                    year = int(token.removeprefix("year="))
            if fomc is not None:
                return json.dumps(fomc.get(year, {"results": []}))
            return json.dumps(_fomc_payload_for_year(year))
        raise AssertionError(f"unexpected URL: {url}")

    return _get


def _fake_get_by_rid(pager_for_rid: dict[int, str]) -> Any:
    """A ``_http_get`` whose FRED pager depends on the requested ``rid``.

    Needed to test the name guard honestly: every configured id must return its
    **own** release name, so a single fixed pager cannot distinguish "the guard
    is silent on correct data" from "the guard never fires".
    """

    def _get(url: str, *, timeout: float) -> str:
        if _FRED_HOST in url:
            import re as _re

            rid = int(_re.search(r"rid=(\d+)", url).group(1))  # type: ignore[union-attr]
            return json.dumps({"pager": pager_for_rid.get(rid, ""), "ptic": 0})
        if _FOMC_HOST in url:
            year = 0
            for token in url.split("&"):
                if token.startswith("year="):
                    year = int(token.removeprefix("year="))
            return json.dumps(_fomc_payload_for_year(year))
        raise AssertionError(f"unexpected URL: {url}")

    return _get


def _pager_with_name(name: str) -> str:
    """A one-event CPI-shaped pager whose event is named ``name``."""
    return _FRED_CPI_PAGER.replace("Consumer Price Index", name)


@pytest.fixture
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> dt.date:
    """Pin the module's "today" to the captured day.

    Patches ``_us_calendar_today``, which is the single place the module reads
    the clock. An earlier version of this fixture patched a ``datetime`` name in
    the module instead, which **silently stopped working** when the module moved
    to ``utc_now``: the patch applied to nothing, the tests still passed because
    the fixture date happened to equal the real date, and they would have begun
    failing the next day. The ``assert`` below makes the patch's effect visible
    rather than assumed.
    """
    monkeypatch.setattr(catalysts, "_us_calendar_today", lambda: _TODAY)
    assert catalysts._us_calendar_today() == _TODAY, "the clock patch did not take"
    return _TODAY


# ---------------------------------------------------------------------------
# Defect 1 — every entry carries a real date
# ---------------------------------------------------------------------------


def test_the_pinned_clock_actually_reaches_the_function(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """The fixture's patch must be observable from the function, not assumed.

    A test suite whose clock fixture silently stops applying still passes on the
    day it is written and fails later, which is the worst failure shape. This
    asserts the seam directly: with the pinned clock the calendar is built as of
    the captured day, and re-pinning it to a later day changes the output.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    as_captured = next_catalyst_calendar()
    assert any("2026-10-14" in e for e in as_captured), as_captured

    later = dt.date(2026, 11, 1)
    monkeypatch.setattr(catalysts, "_us_calendar_today", lambda: later)
    as_later = next_catalyst_calendar()

    assert as_captured != as_later, "moving the clock changed nothing"
    assert not any("2026-10-14" in e for e in as_later), as_later


def test_every_entry_carries_a_real_date(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """The pin for defect 1: no entry is a dateless source citation.

    §16.4's sample returns three strings that name a source and omit the
    schedule. Every string this function returns must contain an ISO date that
    parses — the sample's output would fail this test.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    entries = next_catalyst_calendar()

    assert entries, "expected at least one catalyst"
    for entry in entries:
        parsed = [tok for tok in entry.replace("—", " ").split() if tok[:4].isdigit()]
        assert parsed, f"no date in {entry!r}"
        assert dt.date.fromisoformat(parsed[0]), f"unparseable date in {entry!r}"


def test_entries_are_ordered_earliest_first(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A calendar whose order is not time order is not a calendar."""
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    entries = next_catalyst_calendar()
    dates = [
        dt.date.fromisoformat(tok)
        for e in entries
        for tok in e.replace("—", " ").split()
        if tok[:4].isdigit()
    ]

    assert dates == sorted(dates)


def test_forward_only_events_are_returned(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A past release must not appear as a catalyst.

    The captured CPI pager's first event is 2026-10-14. Asking as of a date
    AFTER it must drop it, which is what makes the filter real rather than a
    pass-through of whatever the source returned.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    entries = next_catalyst_calendar(as_of=dt.date(2026, 11, 1))

    assert not any("2026-10-14" in e for e in entries), entries
    assert any("2026-11-10" in e for e in entries), entries


def test_the_horizon_bounds_what_is_returned(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """The configured horizon must actually bound the window.

    The captured pager holds three CPI events spanning 2026-10-14 to 2026-12-10.
    With a one-day horizon only the first can survive, and with a 60-day horizon
    only those inside 60 days can. Without this the horizon leaf is never read
    and a zero horizon is indistinguishable from a working one.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())
    settings = get_settings().catalyst_calendar
    monkeypatch.setattr(settings.horizon_days, "value", 1, raising=False)

    entries = next_catalyst_calendar()

    cpi = [e for e in entries if "CPI" in e]
    assert cpi == [], f"a 1-day horizon reached {cpi}"

    monkeypatch.setattr(settings.horizon_days, "value", 60, raising=False)
    entries = next_catalyst_calendar()
    cpi = [e for e in entries if "CPI" in e]

    assert any("2026-10-14" in e for e in cpi), cpi
    assert not any("2026-12-10" in e for e in cpi), f"a 60-day horizon reached {cpi}"


# ---------------------------------------------------------------------------
# Defect 2 — ptic is a pagination total, never a count
# ---------------------------------------------------------------------------


def test_ptic_is_never_read_as_a_count(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A ptic far larger than the rows must not change the output.

    Measured: an unfiltered FRED window returns ``ptic=2806`` while the page
    holds 50 rows. Here ``ptic`` is inflated to 2806 against a 3-event pager;
    if the code read it as an event count the output would change. It must not.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get(ptic=2806))

    entries = next_catalyst_calendar()

    assert sum("CPI release" in e for e in entries) == 1


# ---------------------------------------------------------------------------
# Defects 3 and 4 — the FOMC source and its read
# ---------------------------------------------------------------------------


def test_fomc_dates_come_from_the_fed_not_fred(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """The FOMC entry must survive FRED being down entirely.

    Defect 3: FRED's FOMC release is a daily press-release feed. If FOMC dates
    came from FRED, killing FRED would kill the FOMC entry. They must survive.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get(fred_pager=None))

    entries = next_catalyst_calendar()

    assert any("FOMC" in e for e in entries), entries
    assert any("2026-10-28" in e for e in entries), entries


def test_a_daily_feed_would_be_rejected_as_a_meeting_calendar(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """The FOMC read must yield MEETINGS, not one entry per row of a feed.

    Defect 3's consequence: a daily feed read as a calendar reports "tomorrow"
    every day. The captured 2026 document set holds three rows describing two
    meetings (October and December — December carries both a policy and a
    projections document). The output must hold exactly one FOMC entry, and it
    must be the October meeting, not a December document row.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    entries = next_catalyst_calendar()

    fomc = [e for e in entries if "FOMC" in e]
    assert len(fomc) == 1, fomc
    assert "2026-10-28" in fomc[0], fomc


def test_meeting_dates_come_from_the_typed_field_not_the_url(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """Defect 4, re-pointed: the date must be READ, not inferred.

    The old pin caught a parser that flattened markup and invented a meeting.
    The equivalent hazard on the structured source is a reader that derives the
    date from the document ``url`` instead of the ``date`` field — the Fed's
    paths are date-stamped too, and (as captured here) a projections URL is not
    guaranteed to carry the meeting's day. Here the ``date`` fields say
    October 28 / December 9 while every ``url`` carries 2026-01-01. A reader
    that trusted the URL would report January.

    The assertion is therefore two-sided: the returned meeting is the
    ``date``-field's October 28, and January never appears at all.
    """
    url_decoy = {
        "results": [
            {**row, "url": f"https://example.invalid/monetary20260101a-{i}.htm"}
            for i, row in enumerate(_FOMC_2026["results"])
        ]
    }
    monkeypatch.setattr(catalysts, "_http_get", _fake_get(fomc={2026: url_decoy, 2027: url_decoy}))

    meetings = sorted(catalysts._fetch_fed_fomc_meetings(timeout=5.0, as_of=_TODAY))

    assert [d for d, _ in meetings] == [dt.date(2026, 10, 28), dt.date(2026, 12, 9)], meetings
    assert not any(d.month == 1 for d, _ in meetings), (
        "a date was inferred from the document URL instead of read from the field"
    )


def test_the_projections_marker_comes_from_a_document_not_a_suffix(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """The dot-plot flag is a ``projections`` DOCUMENT, not a markup convention.

    Defect 4's other half. The old source encoded "has projections" as a
    trailing ``*`` on the day range (``"27-28*"``), which the parser had to
    strip and interpret — a markup convention standing in for the fact. The
    command returns the fact: a ``projections`` row on the same date.

    Here October has a policy document only and December has both, so the
    projection flag must be attached to December and NOT to October.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    meetings = dict(catalysts._fetch_fed_fomc_meetings(timeout=5.0, as_of=_TODAY))

    assert meetings[dt.date(2026, 10, 28)] is False, "October carries no projections document"
    assert meetings[dt.date(2026, 12, 9)] is True, "December carries a projections document"


def test_the_projections_flag_survives_a_later_policy_row(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """Row order must not decide the flag.

    ``by_date[when] = by_date.get(when, False)`` (rather than ``= False``) exists
    for exactly one reason: a ``projections`` row seen **before** the
    ``monetary_policy`` row for the same date must not be cleared by it. The
    captured payload lists policy first, so order never bites in the other tests
    — this one reverses the two rows, which is the only arrangement in which the
    ``or`` semantics is observable.

    Without this, ``by_date[when] = False`` passes the whole suite (verified by
    mutation: the mutant survived before this test existed).
    """
    reversed_rows = {
        "results": [
            # projections FIRST, policy second — the order the `or` protects.
            {
                "date": "2026-12-09",
                "doc_type": "projections",
                "doc_format": "pdf",
                "url": "https://example.invalid/proj.pdf",
            },
            {
                "date": "2026-12-09",
                "doc_type": "monetary_policy",
                "doc_format": "html",
                "url": "https://example.invalid/policy.htm",
            },
        ]
    }
    monkeypatch.setattr(
        catalysts, "_http_get", _fake_get(fomc={2026: reversed_rows, 2027: {"results": []}})
    )

    meetings = dict(catalysts._fetch_fed_fomc_meetings(timeout=5.0, as_of=_TODAY))

    assert meetings[dt.date(2026, 12, 9)] is True, (
        "a projections row listed before the policy row was cleared by it"
    )


def test_the_projections_marker_is_surfaced(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A meeting with a projections document says so in the entry text.

    With the October meeting removed from the payload so December is the
    **next** one, the entry must say the meeting carries projections — a SEP
    meeting is a materially larger event than a statement-only one.
    """
    december_only = {"results": [r for r in _FOMC_2026["results"] if r["date"] == "2026-12-09"]}
    monkeypatch.setattr(
        catalysts, "_http_get", _fake_get(fomc={2026: december_only, 2027: {"results": []}})
    )

    entries = next_catalyst_calendar()

    fomc = [e for e in entries if "FOMC" in e]
    assert fomc == ["FOMC meeting + projections — 2026-12-09"], fomc


def test_a_two_day_meeting_is_dated_by_its_last_day(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A meeting is dated by the day it ENDS.

    ``27-28`` is a meeting ending the 28th, which is when the decision lands.
    Dating it by the 27th would make every thesis's catalyst one day early.

    The structured command returns a single date per document, so the
    "last day" is now the only date — and the check is that the entry carries
    the meeting's date and not the day before it.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    entries = next_catalyst_calendar()

    assert any("2026-10-28" in e for e in entries), entries
    assert not any("2026-10-27" in e for e in entries), entries


def test_the_year_boundary_is_crossed(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A horizon crossing New Year must ask for NEXT year's documents.

    Measured shape of the command: it takes a single ``year`` and returns that
    year's documents, so a December ``as_of`` with a horizon reaching into
    January must issue **two** requests or it silently truncates at December 31.

    The assertion is directly on ``_fetch_fed_fomc_meetings`` rather than on the
    rendered calendar, because the rendered calendar returns only the *next*
    meeting — December 9 is nearer than January 27, so it would mask whether the
    2027 request was made at all. Pinning it here is what makes "two requests
    were issued" visible; a one-year implementation returns December alone and
    fails this test.

    The frozen clock is 2026-09-19, so ``as_of`` is passed explicitly to move the
    window; the horizon is left at its configured 120 days, which on 2026-12-01
    reaches 2027-03-31 and therefore contains the January meeting.
    """
    requested: list[str] = []

    def _recording(url: str, *, timeout: float) -> str:
        requested.append(url)
        return str(_fake_get()(url, timeout=timeout))

    monkeypatch.setattr(catalysts, "_http_get", _recording)

    meetings = catalysts._fetch_fed_fomc_meetings(timeout=5.0, as_of=dt.date(2026, 12, 1))

    assert dt.date(2027, 1, 27) in dict(meetings), meetings
    years = sorted({int(u.split("year=")[1]) for u in requested})
    assert years == [2026, 2027], f"the 2027 request was never issued: {requested}"


# ---------------------------------------------------------------------------
# The year-boundary 404 — an expected absence must not be logged as a failure
# ---------------------------------------------------------------------------


def _make_status_error(status: int) -> httpx.HTTPStatusError:
    """An ``HTTPStatusError`` carrying a real ``status_code``.

    The handler branches on ``exc.response.status_code``, so a mock without a
    response object would test the exception's name rather than the branch that
    matters. Built from an actual ``httpx.Response`` so the attribute path the
    production code reads is the one exercised.
    """
    request = httpx.Request("GET", "http://127.0.0.1:6901/api/v1/economy/fomc_documents")
    response = httpx.Response(status, request=request, text='{"detail":"Not Found"}')
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


def test_an_unpublished_year_is_an_expected_absence(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date, caplog: pytest.LogCaptureFixture
) -> None:
    """A 404 for next year's document set must NOT be reported as a failure.

    Measured live 2026-09-22: ``economy/fomc_documents?provider=federal_reserve
    &year=N`` answers **200** for a published year and **404
    ``{"detail":"Not Found"}``** for one the Fed has not published yet. Because
    ``_http_get`` calls ``raise_for_status()``, every December run crossed the
    year boundary, hit that 404, and logged ``FOMC documents for 2027 failed``
    at **WARNING** — byte-identical in shape to the dead-port outage that cost
    this project hours (D-087.10/.13).

    That is the defect this test pins: a normal event sharing a channel with a
    real outage teaches a reader to skip the channel, and then skip the one
    warning that mattered. A 404 must therefore be quiet (at most INFO), while
    the current year's meetings must still be returned intact.

    The clock is frozen to 2026-09-19 and ``as_of`` moved to 2026-12-01, so the
    window crosses the boundary exactly as a December run would.
    """

    def _get(url: str, *, timeout: float) -> str:
        if _FRED_HOST in url:
            raise httpx.ConnectError("fred down")
        if _FOMC_HOST in url:
            year = int(url.split("year=")[1])
            if year == 2027:
                # Exactly what the live service answers for an unpublished year.
                raise _make_status_error(404)
            return json.dumps(_FOMC_2026)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(catalysts, "_http_get", _get)

    with caplog.at_level("INFO"):
        meetings = dict(catalysts._fetch_fed_fomc_meetings(timeout=5.0, as_of=dt.date(2026, 12, 1)))

    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], f"an expected absence was reported as a failure: {warnings}"

    # The absence must be VISIBLE at INFO, not silently dropped: a reader must
    # be able to tell "not published yet" from "never asked".
    notes = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("2027" in m and "404" in m for m in notes), notes

    # And the published year's rows must survive the absent one.
    assert dt.date(2026, 12, 9) in meetings, meetings


def test_a_genuine_fomc_failure_is_still_loud(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date, caplog: pytest.LogCaptureFixture
) -> None:
    """The 404 branch must not swallow real failures (the negative control).

    Without this, "make 404 quiet" could be satisfied by making *everything*
    quiet — a guard that passes by never firing. A 500 is a failure, and the
    distinction is the whole point of the fix.
    """

    def _get(url: str, *, timeout: float) -> str:
        if _FRED_HOST in url:
            raise httpx.ConnectError("fred down")
        if _FOMC_HOST in url:
            raise _make_status_error(503)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(catalysts, "_http_get", _get)

    with caplog.at_level("INFO"):
        catalysts._fetch_fed_fomc_meetings(timeout=5.0, as_of=dt.date(2026, 12, 1))

    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("503" in w for w in warnings), warnings


def test_an_empty_or_malformed_fomc_body_does_not_crash(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date, caplog: pytest.LogCaptureFixture
) -> None:
    """A truncated body must be reported, never handed to ``json.loads`` raw.

    The publish transition is the realistic window: the Fed's year endpoint can
    answer 200 with an empty or partially-written body. ``json.loads("")``
    raises ``ValueError``, which the old handler caught only incidentally (it
    was sharing a clause with the transport errors); the empty body was then
    indistinguishable from a transport fault. Both must be WARNING, and neither
    may take down the caller.
    """

    def _get(url: str, *, timeout: float) -> str:
        if _FRED_HOST in url:
            raise httpx.ConnectError("fred down")
        if _FOMC_HOST in url:
            return "" if url.split("year=")[1] == "2027" else json.dumps(_FOMC_2026)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(catalysts, "_http_get", _get)

    with caplog.at_level("INFO"):
        meetings = dict(catalysts._fetch_fed_fomc_meetings(timeout=5.0, as_of=dt.date(2026, 12, 1)))

    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("empty body" in w for w in warnings), warnings
    assert dt.date(2026, 10, 28) in meetings, meetings


# ---------------------------------------------------------------------------
# Defect 5 — a failed source must not read as a quiet calendar
# ---------------------------------------------------------------------------


def test_every_source_failing_raises_not_returns_empty(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """D-054's silence failure: ``[]`` must not mean two different things."""
    monkeypatch.setattr(catalysts, "_http_get", _fake_get(fred_pager=None, fomc_error=True))

    with pytest.raises(CatalystSourceError):
        next_catalyst_calendar()


def test_a_quiet_but_reachable_source_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A source that answers with nothing forward is NOT an error.

    The distinction the previous test makes: unreachable raises, reachable-but-
    empty does not. Here the pager holds only past events.
    """
    past_pager = _FRED_CPI_PAGER.replace("2026", "2020")
    monkeypatch.setattr(
        catalysts,
        "_http_get",
        _fake_get(fred_pager=past_pager, fomc={2026: {"results": []}, 2027: {"results": []}}),
    )

    entries = next_catalyst_calendar()

    assert entries == [], entries


# ---------------------------------------------------------------------------
# Defect 6 — a reachable-but-empty FOMC source is not an answered source
# ---------------------------------------------------------------------------


def test_a_reachable_but_empty_fomc_source_is_not_an_answered_source(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """D-085's conflation class, applied to the new command.

    If the FOMC command answers with an empty document set and FRED is down,
    then *nothing* produced a date. Counting the empty answer as an answered
    source would make ``next_catalyst_calendar`` return ``[]`` — claiming a
    quiet calendar on a run where no source had any coverage at all. It must
    raise instead.
    """
    monkeypatch.setattr(
        catalysts,
        "_http_get",
        _fake_get(
            fred_pager=None,
            fomc={2026: {"results": []}, 2027: {"results": []}},
        ),
    )

    with pytest.raises(CatalystSourceError):
        next_catalyst_calendar()


# ---------------------------------------------------------------------------
# The release-id / name agreement guard
# ---------------------------------------------------------------------------


def test_a_mislabelled_release_id_warns(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date, caplog: pytest.LogCaptureFixture
) -> None:
    """An id pointing at another release must be loud, not silently relabelled.

    FRED renumber releases; a stale id returns a different release's dates
    under the configured label. Here each of the three configured ids answers
    with its own correct name EXCEPT the CPI slot, which returns the Employment
    Situation — so exactly one warning must fire, and it must name CPI.
    """
    settings = get_settings().catalyst_calendar
    pages = {
        settings.cpi_id: _pager_with_name("Employment Situation"),  # deliberately wrong
        settings.nfp_id: _pager_with_name("Employment Situation"),
        settings.pce_id: _pager_with_name("Personal Income and Outlays"),
    }
    monkeypatch.setattr(catalysts, "_http_get", _fake_get_by_rid(pages))

    with caplog.at_level("WARNING"):
        next_catalyst_calendar()

    mismatches = [r.message for r in caplog.records if "configured as" in r.message]
    assert len(mismatches) == 1, mismatches
    assert "configured as CPI" in mismatches[0], mismatches


def test_a_correctly_labelled_calendar_is_silent(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date, caplog: pytest.LogCaptureFixture
) -> None:
    """The guard must be silent on correct data.

    A warning that fires on every healthy run is noise that teaches readers to
    ignore it — the exact cost of the first version of this guard, which
    compared the abbreviation ``"CPI"`` against the full name and warned on
    every call (caught while probing, D-065).
    """
    settings = get_settings().catalyst_calendar
    pages = {
        settings.cpi_id: _pager_with_name("Consumer Price Index"),
        settings.nfp_id: _pager_with_name("Employment Situation"),
        settings.pce_id: _pager_with_name("Personal Income and Outlays"),
    }
    monkeypatch.setattr(catalysts, "_http_get", _fake_get_by_rid(pages))

    with caplog.at_level("WARNING"):
        next_catalyst_calendar()

    assert [r.message for r in caplog.records if "configured as" in r.message] == []


# ---------------------------------------------------------------------------
# Config invariants
# ---------------------------------------------------------------------------


def test_release_ids_are_distinct() -> None:
    """Two catalysts on one id publish it twice and drop one."""
    from pydantic import ValidationError

    from macro_engine.config import CatalystCalendarSettings

    settings = get_settings().catalyst_calendar
    payload = settings.model_dump()
    payload["nfp_release_id"] = payload["cpi_release_id"]

    with pytest.raises(ValidationError, match="distinct"):
        CatalystCalendarSettings(**payload)


def test_the_configured_ids_are_the_measured_ones() -> None:
    """Pin the three measured ids so a silent edit is visible in a diff.

    Measured 2026-09-19 against live FRED: CPI=10, NFP=50, PCE=54.
    """
    settings = get_settings().catalyst_calendar

    assert (settings.cpi_id, settings.nfp_id, settings.pce_id) == (10, 50, 54)


def test_the_fomc_fetch_derives_its_host_from_config() -> None:
    """The FOMC endpoint must follow config, not a literal host (O-113).

    The defect this pins: the module stored the full absolute URL with the
    **dead** port ``6901`` baked in, and ``6901`` answered ``502`` on every data
    call while the configured port served the same command with 34 rows. Nothing
    failed, because the *test* stubbed the same dead literal — the stub agreed
    with the bug.

    So this asserts the two properties that make that impossible:
    1. the URL is a **function of** the configured base (change the base, the
       URL moves);
    2. no port or host literal survives in the module's URL constants.
    """
    default_url = catalysts._fomc_documents_url()
    assert default_url.startswith(get_settings().openbb.base_url.rstrip("/")), (
        f"the FOMC URL {default_url!r} does not derive from the configured base "
        f"{get_settings().openbb.base_url!r} — a literal host has crept back in"
    )
    assert default_url.endswith(catalysts._FOMC_DOCUMENTS_PATH)

    # Rebasing must actually move the URL: an implementation that ignored its
    # argument (or read config regardless) would pass the check above by
    # coincidence whenever the two happened to agree.
    rebased = catalysts._fomc_documents_url("http://example.invalid:9999/")
    assert rebased == "http://example.invalid:9999/api/v1/economy/fomc_documents"

    # And the constant must be the PATH, not an absolute URL — this is the
    # regression that produced the outage, caught at the source.
    assert catalysts._FOMC_DOCUMENTS_PATH.startswith("/")
    assert "://" not in catalysts._FOMC_DOCUMENTS_PATH
    assert not hasattr(catalysts, "_FOMC_DOCUMENTS_URL"), (
        "the absolute-URL constant is back — derive from config instead"
    )

    # The stub the offline tests route on is derived from the same call, so the
    # suite cannot agree with a dead port again. If someone re-pins it by hand
    # to a literal, this fails.
    derived_host = f"{urlparse(default_url).netloc}{catalysts._FOMC_DOCUMENTS_PATH}"
    assert derived_host == _FOMC_HOST


# ---------------------------------------------------------------------------
# Live (deselected by default)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_calendar_returns_forward_dates() -> None:
    """Against the real sources. Deselected unless ``-m live``."""
    entries = next_catalyst_calendar()

    assert entries, "the live sources returned nothing forward"
    dates = [
        dt.date.fromisoformat(t)
        for e in entries
        for t in e.replace("—", " ").split()
        if t[:4].isdigit()
    ]
    assert all(d >= catalysts._us_calendar_today() for d in dates), entries
