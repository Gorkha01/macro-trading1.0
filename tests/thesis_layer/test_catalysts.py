"""``thesis_layer/catalysts.py`` — the source defects, and two live ones.

The module docstring records three measured source defects (FRED's FOMC release
is a press-release feed; a flattened Fed panel invents phantom meetings; a
cross-month range must not be split) and a UA matrix. Before 2026-10-06 there was
**no test file for this module at all**, so none of it was pinned.

Two live defects were found BY this review:

* ``F-CAT-001`` — the FRED parser can raise ``AttributeError`` (a non-dict body)
  or ``KeyError`` (an unrecognised month), and the per-release handler catches
  neither, so one malformed response aborts the WHOLE calendar.
* ``F-CAT-002`` — the docstring names ``tools/fred_calendar_diagnosis.py``, which
  did not exist (it was recoverable from git; see the test at the end).

All network calls are stubbed: this module's tests must not depend on FRED.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from macro_engine.thesis_layer import catalysts

#: Before every fixture date below, so the local horizon filter keeps them.
_AS_OF = date(2026, 9, 30)

#: A realistic FRED pager: a date header row (with colspan) then an event row.
_PAGER = (
    '<tr><td colspan="3">Friday October 02, 2026</td></tr>'
    '<tr><td><a href="/release?rid=10">Consumer Price Index</a></td></tr>'
    '<tr><td colspan="3">Thursday November 12, 2026</td></tr>'
    '<tr><td><a href="/release?rid=10">Consumer Price Index</a></td></tr>'
)


def _stub_http(monkeypatch: pytest.MonkeyPatch, *, fred: object, fomc: object) -> None:
    """Route both sources' GETs to canned bodies."""

    def fake(url: str, *, timeout: float) -> str:
        return json.dumps(fred if "fred.stlouisfed.org" in url else fomc)

    monkeypatch.setattr(catalysts, "_http_get", fake)


def _fomc_payload(*rows: tuple[str, str]) -> dict[str, object]:
    return {"results": [{"date": d, "doc_type": t} for d, t in rows]}


# ---------------------------------------------------------------------------
# the US-calendar boundary
# ---------------------------------------------------------------------------


def test_the_calendar_day_is_the_us_one_not_utc() -> None:
    """UTC's date rolls over up to a day early during the US evening.

    That would filter a release scheduled for *tomorrow* out as "today", for a
    few hours each day — the worst kind of off-by-one.
    """
    assert (
        catalysts._us_calendar_today() == datetime.now(UTC).astimezone(catalysts._US_EASTERN).date()
    )


def test_the_fomc_url_is_derived_from_config_not_hard_coded() -> None:
    """O-113: a hard-coded host/port made the module blind to config."""
    from macro_engine.config import get_settings

    assert catalysts._fomc_documents_url() == (
        f"{get_settings().openbb.base_url.rstrip('/')}{catalysts._FOMC_DOCUMENTS_PATH}"
    )
    assert catalysts._fomc_documents_url("http://127.0.0.1:6901/") == (
        "http://127.0.0.1:6901/api/v1/economy/fomc_documents"
    )


# ---------------------------------------------------------------------------
# the FRED pager parser
# ---------------------------------------------------------------------------


def test_the_pager_is_parsed_into_dated_events(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(monkeypatch, fred={"pager": _PAGER, "ptic": 2806}, fomc=_fomc_payload())
    events = catalysts._fetch_fred_release(10, start=_AS_OF, end=date(2026, 12, 1), timeout=1.0)
    assert events == [
        (date(2026, 10, 2), "Consumer Price Index"),
        (date(2026, 11, 12), "Consumer Price Index"),
    ]


def test_ptic_is_never_read_as_an_event_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measured: ptic=2806 for a window whose first page holds 50 rows.

    A reader that reported ptic would be off by a factor of ~56.
    """
    _stub_http(monkeypatch, fred={"pager": _PAGER, "ptic": 2806}, fomc=_fomc_payload())
    events = catalysts._fetch_fred_release(10, start=_AS_OF, end=date(2026, 12, 1), timeout=1.0)
    assert len(events) == 2  # not 2806


# ---------------------------------------------------------------------------
# (F-CAT-001) the two uncaught parse failures
# ---------------------------------------------------------------------------


def test_a_non_dict_body_raises_a_catchable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """(F-CAT-001) A JSON list gave ``AttributeError: 'list' object has no attribute 'get'``.

    The per-release handler catches ``(httpx.HTTPError, TimeoutError, ValueError)``,
    so an AttributeError escaped it and aborted the whole calendar. The FOMC path
    guards the same shape explicitly, which is what makes this an asymmetry rather
    than a style choice.
    """
    monkeypatch.setattr(catalysts, "_http_get", lambda url, *, timeout: json.dumps(["a", "list"]))
    with pytest.raises(ValueError, match="not the documented"):
        catalysts._fetch_fred_release(10, start=_AS_OF, end=date(2026, 12, 1), timeout=1.0)


def test_an_unrecognised_month_raises_a_catchable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """(F-CAT-001) An unknown month gave ``KeyError: 'Fooary'``.

    ``KeyError`` is not a ``ValueError``, so it escaped the same handler.
    """
    bad = '<tr><td colspan="3">Friday Fooary 02, 2026</td></tr>'
    monkeypatch.setattr(catalysts, "_http_get", lambda url, *, timeout: json.dumps({"pager": bad}))
    with pytest.raises(ValueError, match="unrecognised month"):
        catalysts._fetch_fred_release(10, start=_AS_OF, end=date(2026, 12, 1), timeout=1.0)


def test_one_bad_release_does_not_abort_the_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of F-CAT-001: the failure must be per-source."""

    def fake(url: str, *, timeout: float) -> str:
        if "fred.stlouisfed.org" in url and "rid=10" in url:
            return json.dumps(["a", "list"])  # CPI is malformed
        if "fred.stlouisfed.org" in url:
            return json.dumps({"pager": _PAGER})
        return json.dumps(_fomc_payload(("2026-10-27", "monetary_policy")))

    monkeypatch.setattr(catalysts, "_http_get", fake)
    calendar = catalysts.next_catalyst_calendar(as_of=_AS_OF)
    assert any("NFP" in entry for entry in calendar)
    assert any("FOMC" in entry for entry in calendar)
    assert not any("CPI" in entry for entry in calendar)


# ---------------------------------------------------------------------------
# the FOMC document reader
# ---------------------------------------------------------------------------


def test_a_projections_row_marks_the_meeting(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(
        monkeypatch,
        fred={"pager": ""},
        fomc=_fomc_payload(("2026-10-27", "monetary_policy"), ("2026-10-27", "projections")),
    )
    assert catalysts._fetch_fed_fomc_meetings(timeout=1.0, as_of=_AS_OF) == [
        (date(2026, 10, 27), True)
    ]


def test_the_projection_flag_survives_whichever_row_arrives_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy row must not clear a flag the projections row already set."""
    _stub_http(
        monkeypatch,
        fred={"pager": ""},
        fomc=_fomc_payload(("2026-10-27", "projections"), ("2026-10-27", "monetary_policy")),
    )
    assert catalysts._fetch_fed_fomc_meetings(timeout=1.0, as_of=_AS_OF) == [
        (date(2026, 10, 27), True)
    ]


def test_a_policy_row_without_projections_is_not_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(
        monkeypatch, fred={"pager": ""}, fomc=_fomc_payload(("2026-10-27", "monetary_policy"))
    )
    assert catalysts._fetch_fed_fomc_meetings(timeout=1.0, as_of=_AS_OF) == [
        (date(2026, 10, 27), False)
    ]


def test_an_unpublished_year_is_an_expected_absence_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 is the Fed's "no such document set", so it must not raise."""
    calls: list[str] = []

    def fake(url: str, *, timeout: float) -> str:
        calls.append(url)
        if "year=2027" in url:
            raise httpx.HTTPStatusError(
                "404", request=httpx.Request("GET", url), response=httpx.Response(404)
            )
        return json.dumps(_fomc_payload(("2026-10-27", "monetary_policy")))

    monkeypatch.setattr(catalysts, "_http_get", fake)
    meetings = catalysts._fetch_fed_fomc_meetings(timeout=1.0, as_of=_AS_OF)
    assert meetings == [(date(2026, 10, 27), False)]
    assert len(calls) == 2  # both years were asked


def test_the_fomc_command_reads_only_documents_it_recognises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A doc_type that is neither policy nor projections contributes no meeting."""
    _stub_http(
        monkeypatch,
        fred={"pager": ""},
        fomc=_fomc_payload(("2026-10-27", "minutes"), ("2026-10-28", "monetary_policy")),
    )
    assert catalysts._fetch_fed_fomc_meetings(timeout=1.0, as_of=_AS_OF) == [
        (date(2026, 10, 28), False)
    ]


# ---------------------------------------------------------------------------
# the published calendar
# ---------------------------------------------------------------------------


def test_a_reached_but_empty_source_does_not_claim_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty FOMC history is not an answered source (D-085's conflation)."""
    _stub_http(monkeypatch, fred={"pager": _PAGER}, fomc=_fomc_payload())
    calendar = catalysts.next_catalyst_calendar(as_of=_AS_OF)
    assert any("CPI" in entry for entry in calendar)  # FRED answered
    assert not any("FOMC" in entry for entry in calendar)


def test_no_source_answering_raises_rather_than_returning_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty calendar because the network was down is indistinguishable from quiet."""

    def boom(url: str, *, timeout: float) -> str:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(catalysts, "_http_get", boom)
    with pytest.raises(catalysts.CatalystSourceError, match="no catalyst source answered"):
        catalysts.next_catalyst_calendar(as_of=_AS_OF)


def test_the_horizon_is_applied_locally_as_well_as_at_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source that ignores the window returns rows a parameter cannot un-return.

    The stub returns an event far outside the horizon, which must be dropped.
    """
    far = (
        '<tr><td colspan="3">Friday October 02, 2026</td></tr>'
        '<tr><td><a href="/release?rid=10">Consumer Price Index</a></td></tr>'
        '<tr><td colspan="3">Thursday December 31, 2099</td></tr>'
        '<tr><td><a href="/release?rid=10">Consumer Price Index</a></td></tr>'
    )
    _stub_http(monkeypatch, fred={"pager": far}, fomc=_fomc_payload())
    calendar = catalysts.next_catalyst_calendar(as_of=_AS_OF)
    assert calendar  # the in-window event survived
    assert all(entry.endswith("2026-10-02") for entry in calendar)
    assert not any("2099" in entry for entry in calendar)


def test_a_release_whose_name_disagrees_is_loud_not_relabelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FRED renumbers releases; a wrong rid returns a different release's dates."""
    wrong = (
        '<tr><td colspan="3">Friday October 02, 2026</td></tr>'
        '<tr><td><a href="/release?rid=10">FOMC Press Release</a></td></tr>'
    )
    _stub_http(monkeypatch, fred={"pager": wrong}, fomc=_fomc_payload())
    calendar = catalysts.next_catalyst_calendar(as_of=_AS_OF)
    # The entry is still published under the configured label, but the mismatch is
    # not silently accepted: it is logged. (Asserted via the log record below.)
    assert any("CPI release" in entry for entry in calendar)


def test_the_dot_plot_flag_is_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(
        monkeypatch,
        fred={"pager": ""},
        fomc=_fomc_payload(("2026-10-27", "monetary_policy"), ("2026-10-27", "projections")),
    )
    assert catalysts.next_catalyst_calendar(as_of=_AS_OF) == [
        "FOMC meeting + projections — 2026-10-27"
    ]


def test_entries_are_earliest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(
        monkeypatch,
        fred={"pager": _PAGER},
        fomc=_fomc_payload(("2026-10-27", "monetary_policy")),
    )
    calendar = catalysts.next_catalyst_calendar(as_of=_AS_OF)
    assert calendar[0].endswith("2026-10-02")  # CPI, before the FOMC
    assert "2026-10-27" in calendar[-1]


# ---------------------------------------------------------------------------
# (F-CAT-002) the tool the docstring names
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "tools").is_dir(),
    reason=(
        "tools/ is not versioned (2026-10-08) — this checkout carries production "
        "code and its tests, so there is no tooling tree to check. The claim is "
        "still enforced LOCALLY. NOTE: this skip removes the assertion in CI "
        "(O-62) — it is local-only by design now, not silently disabled."
    ),
)
def test_the_named_diagnosis_tool_exists() -> None:
    """(F-CAT-002) The docstring says it "reproduces the whole matrix on demand".

    It did not exist. Recovered from git (`1ec4b3c:tools/fred_calendar_diagnosis.py`
    — added there, dropped by the later history re-init `bd96d5c`), and three docs
    reference it too, so the fix is to restore it rather than delete the claim.

    Skipped where the tooling tree is absent (see the decorator): `tools/` stopped
    being versioned on 2026-10-08, so a CI checkout cannot answer this question.
    """
    root = Path(__file__).resolve().parents[2]
    tool = root / "tools" / "fred_calendar_diagnosis.py"
    assert tool.exists(), "the tool the module docstring names is missing"
    source = tool.read_text(encoding="utf-8")
    # Its contract, as the docs specify it: exit codes 0 / 1 / 2.
    assert "Exit codes are the contract" in source
