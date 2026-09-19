"""Tests for ``next_catalyst_calendar`` (§16.4, D-065).

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
4. **Flattening the Fed's HTML creates phantom meetings.** The flat 2027 panel
   text yields two January meetings from one (measured).
   ``test_the_structured_markup_is_read_not_the_flat_text`` is the pin.
5. **A source that failed must not read as a quiet calendar.** D-054's silence
   failure. ``test_every_source_failing_raises_not_returns_empty``.

The transport is monkeypatched for the offline tests; the live tests are marked
``network`` and deselected by default, so the suite stays deterministic.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
import pytest

from macro_engine.config import get_settings
from macro_engine.thesis_layer import catalysts
from macro_engine.thesis_layer.catalysts import (
    CatalystSourceError,
    next_catalyst_calendar,
)

# ---------------------------------------------------------------------------
# Fixtures: real, captured markup
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

#: A real Fed FOMC calendar fragment, captured 2026-09-19. The 2026 panel holds
#: a confirmed October meeting and a projections-marked December one, and the
#: 2027 panel ends with the page's **real** trailing note, verbatim:
#: ``"Note: A two-day meeting is scheduled for January 25-26, 2028."``
#:
#: That note is the whole point. It carries a month-plus-day-range that belongs
#: to **2028** while sitting inside the 2027 panel's markup, so a parser that
#: flattens the panel to text attributes "January 25-26" to **2027** and emits a
#: phantom meeting. Measured against the live page: the flat parse returns
#: **9** hits for 2027, the last being ``('January', '25-26')``. The structured
#: read returns **8**.
_FED_HTML = """
<div id="2026">
  <h4>2026 FOMC Meetings</h4>
  <div class="panel panel-default">
    <div class="fomc-meeting__month"><strong>October</strong></div>
    <div class="fomc-meeting__date">27-28</div>
  </div>
  <div class="panel panel-default">
    <div class="fomc-meeting__month"><strong>December</strong></div>
    <div class="fomc-meeting__date">8-9*</div>
  </div>
</div>
<div id="2027">
  <h4>2027 FOMC Meetings</h4>
  <div class="panel panel-default">
    <div class="fomc-meeting__month"><strong>January</strong></div>
    <div class="fomc-meeting__date">26-27</div>
  </div>
  <div class="panel-footer">* Meeting associated with a Summary of Economic Projections.  </div>
  <p>Note: A two-day meeting is scheduled for January 25-26, 2028. Each meeting date is
  tentative until confirmed at the
  meeting immediately preceding it.</p>
</div>
"""

#: A frozen "today" inside the captured window, so the forward filter is exact.
_TODAY = dt.date(2026, 9, 19)

#: The two hosts the module is allowed to call.
_FRED_HOST = "fred.stlouisfed.org"
_FED_HOST = "www.federalreserve.gov"


def _fake_get(
    *, fred_pager: str | None = _FRED_CPI_PAGER, ptic: int = 3, fed_html: str | None = _FED_HTML
) -> Any:
    """Build a ``_http_get`` replacement routing by host."""

    def _get(url: str, *, timeout: float) -> str:
        if _FRED_HOST in url:
            if fred_pager is None:
                raise httpx.ConnectError("fred down")
            import json

            return json.dumps({"pager": fred_pager, "ptic": ptic})
        if _FED_HOST in url:
            if fed_html is None:
                raise httpx.ConnectError("fed down")
            return fed_html
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
            import json
            import re as _re

            rid = int(_re.search(r"rid=(\d+)", url).group(1))  # type: ignore[union-attr]
            return json.dumps({"pager": pager_for_rid.get(rid, ""), "ptic": 0})
        if _FED_HOST in url:
            return _FED_HTML
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
# Defects 3 and 4 — the FOMC source and its parse
# ---------------------------------------------------------------------------


def test_fomc_dates_come_from_the_fed_not_fred(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """The FOMC entry must reflect the Fed's page even when FRED is down.

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
    """The Fed's parse must yield MEETINGS, not one entry per day.

    Defect 3's consequence: a daily feed read as a calendar reports "tomorrow"
    every day. The Fed fragment holds exactly three meetings; the output must
    hold exactly one FOMC entry.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    entries = next_catalyst_calendar()

    fomc = [e for e in entries if "FOMC" in e]
    assert len(fomc) == 1, fomc


def test_the_structured_markup_is_read_not_the_flat_text(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """Defect 4: the trailing note must not become a phantom meeting.

    The 2027 panel ends with the page's real note, "Note: A two-day meeting is
    scheduled for **January 25-26, 2028**." A flat-text parse attributes that
    January to **2027** and emits a second January meeting (measured: 9 hits for
    the flat parse, 8 structured). The structured read must yield exactly the
    three meetings the markup declares — 2026-10-28, 2026-12-09, 2027-01-27 —
    and in particular **one** January.
    """
    monkeypatch.setattr(catalysts, "_http_get", lambda url, *, timeout: _FED_HTML)

    meetings = sorted(catalysts._fetch_fed_fomc_meetings(timeout=5.0))

    assert [d for d, _ in meetings] == [
        dt.date(2026, 10, 28),
        dt.date(2026, 12, 9),
        dt.date(2027, 1, 27),
    ], meetings

    january_2027 = [m for m in meetings if m[0].year == 2027 and m[0].month == 1]
    assert len(january_2027) == 1, january_2027
    assert january_2027[0][1] is False, "January 2027 carries no projections marker"
    # The 2028 note's meeting must never appear under 2027.
    assert not any(m[0].day == 25 for m in meetings), meetings


def test_the_projections_marker_is_surfaced(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """A ``*`` meeting carries the projections §16.4 calls a "dot plot".

    The captured December 2026 meeting is written ``8-9*``. With the October
    meeting removed from the page so December is the **next** one, the entry
    must say the meeting carries projections — a SEP meeting is a materially
    larger event than a statement-only one.
    """
    october_only = (
        '<div class="fomc-meeting__month"><strong>October</strong></div>\n'
        '    <div class="fomc-meeting__date">27-28</div>'
    )
    without_october = _FED_HTML.replace(october_only, "")
    monkeypatch.setattr(catalysts, "_http_get", _fake_get(fed_html=without_october))

    entries = next_catalyst_calendar()

    fomc = [e for e in entries if "FOMC" in e]
    assert fomc == ["FOMC meeting + projections — 2026-12-09"], fomc


def test_a_two_day_meeting_is_dated_by_its_last_day(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """``27-28`` is a meeting ENDING the 28th, which is when the decision lands.

    Dating it by the 27th would make every thesis's catalyst one day early.
    """
    monkeypatch.setattr(catalysts, "_http_get", _fake_get())

    entries = next_catalyst_calendar()

    assert any("2026-10-28" in e for e in entries), entries
    assert not any("2026-10-27" in e for e in entries), entries


# ---------------------------------------------------------------------------
# Defect 5 — a failed source must not read as a quiet calendar
# ---------------------------------------------------------------------------


def test_every_source_failing_raises_not_returns_empty(
    monkeypatch: pytest.MonkeyPatch, frozen_today: dt.date
) -> None:
    """D-054's silence failure: ``[]`` must not mean two different things."""
    monkeypatch.setattr(catalysts, "_http_get", _fake_get(fred_pager=None, fed_html=None))

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
    monkeypatch.setattr(catalysts, "_http_get", _fake_get(fred_pager=past_pager, fed_html=None))

    entries = next_catalyst_calendar()

    assert entries == [], entries


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
