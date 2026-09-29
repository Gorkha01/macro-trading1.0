"""Section 6 release-calendar tests — the lookup, and its honesty on failure.

What these tests are for
------------------------
``release_calendar.py`` exists because Section 6 forbids substituting an
observation date for a release date. The dangerous failure mode is not a crash
— it is a module that quietly returns *a* date when it could not read one, so a
backtest believes it has point-in-time information it does not have. Every test
below is therefore aimed at one of three properties:

(a) a **successful** read populates the right series with the right datetime;
(b) an **unreadable** route yields NOTHING and says so (``route_read=False``),
    never a scheduled, guessed, or observation date;
(c) the retry **actually retries** — a single attempt against an intermittent
    route would turn the documented ~50% failure rate into an ~50% data gap.

These run against an injected mock client rather than the live route. That is
not a shortcut around a hard test: the live ``nasdaq`` route is INTERMITTENT and
was, at last measurement, returning HTTP 403 from an upstream IP block
(documented in the module docstring and in ``config/series_registry.yaml``).
A test whose result depends on a third party's rate limiting is a test people
learn to ignore, so the live shape is pinned here as a fixture instead. The
fixture bodies are the **verbatim** payload shapes captured from the real
provider on 2026-09-20, including its well-formed failure body.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pandas as pd
import pytest

from macro_engine.config import ReleaseCalendar
from macro_engine.data_layer.release_calendar import (
    ReleaseCalendarError,
    ReleaseDateIndex,
    fetch_release_dates,
    release_dates_for_series,
)
from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport
from macro_engine.models.contracts import utc_now

AS_OF = date(2026, 9, 20)

# ---------------------------------------------------------------------------
# Fixtures — the real provider shapes, captured 2026-09-20
# ---------------------------------------------------------------------------

#: A successful ``economy.calendar`` read. Real event names, real timestamps,
#: and deliberately including rows this system does NOT map (so the join is
#: exercised, not bypassed) plus a duplicate instant (CPI YoY and CPI MoM are
#: published together under one event name).
SUCCESS_PAYLOAD: dict[str, Any] = {
    "results": [
        {"date": "2026-08-13T08:30:00", "event": "CPI", "country": "United States"},
        {"date": "2026-08-13T08:30:00", "event": "Core CPI", "country": "United States"},
        {
            "date": "2026-08-27T08:30:00",
            "event": "Core PCE Price Index",
            "country": "United States",
        },
        {"date": "2026-09-02T10:00:00", "event": "JOLTS Job Openings", "country": "United States"},
        {"date": "2026-09-11T08:30:00", "event": "PPI", "country": "United States"},
        # Unmapped: must be skipped without error and without a date.
        {"date": "2026-09-15T08:30:00", "event": "Empire State Manufacturing Index"},
        # Unparseable timestamp: must be skipped, never defaulted to today.
        {"date": "not-a-date", "event": "CPI"},
        # Wrong type entirely: must be skipped.
        {"date": None, "event": "CPI"},
    ]
}

#: The provider's failure is a **200 with a well-formed body**, not an HTTP
#: error. Pinning this shape is the point: a naive implementation checks only
#: ``raise_for_status()`` and mistakes this for a successful empty calendar.
NO_RECORD_PAYLOAD: dict[str, Any] = {
    "detail": "Nasdaq Error -> Economic Events Calendar: No record found."
}


def _cfg(**overrides: Any) -> ReleaseCalendar:
    """A test config with a fast backoff, so retry tests do not sleep for real."""
    base: dict[str, Any] = {
        "enabled": True,
        "provider": "nasdaq",
        "endpoint": "economy.calendar",
        "max_attempts": 3,
        "backoff_seconds": 0.0,
        "window_days_back": 400,
        "window_days_forward": 45,
        "event_map": {
            "CPI": "cpi_headline",
            "Core CPI": "cpi_core",
            "Core PCE Price Index": "pce_core",
            "JOLTS Job Openings": "jolts_openings",
            "PPI": "ppi_headline",
        },
    }
    base.update(overrides)
    return ReleaseCalendar(**base)


def _client_returning(*responses: Any) -> MagicMock:
    """A mock ``httpx.Client`` that yields ``responses`` in order.

    Each item is either a payload dict (served as a 200 JSON response) or an
    exception instance (raised on the call). After the supplied items are
    exhausted the last one repeats, so a test asserting "retries N times" does
    not have to enumerate exactly N entries.
    """
    seq = list(responses)
    calls: list[tuple[str, dict[str, str]]] = []

    def _get(url: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        calls.append((url, dict(params or {})))
        item = seq[min(len(calls) - 1, len(seq) - 1)]
        if isinstance(item, Exception):
            raise item
        response = MagicMock(spec=httpx.Response)
        response.raise_for_status.return_value = None
        response.json.return_value = item
        return response

    client = MagicMock(spec=httpx.Client)
    client.get.side_effect = _get
    client.calls = calls
    return client


# ---------------------------------------------------------------------------
# (a) A successful read populates dates
# ---------------------------------------------------------------------------


def test_successful_read_populates_mapped_series_with_provider_datetimes() -> None:
    """Each mapped event lands on its series with the provider's own timestamp.

    Asserts exact datetimes, not merely "not None": a lookup that returned the
    wrong row's date would still populate every field and would still be a
    point-in-time violation.
    """
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(SUCCESS_PAYLOAD), cfg=_cfg())

    assert index.route_read is True
    assert index.get("cpi_headline") == datetime(2026, 8, 13, 8, 30)
    assert index.get("cpi_core") == datetime(2026, 8, 13, 8, 30)
    assert index.get("pce_core") == datetime(2026, 8, 27, 8, 30)
    assert index.get("jolts_openings") == datetime(2026, 9, 2, 10, 0)
    assert index.get("ppi_headline") == datetime(2026, 9, 11, 8, 30)
    assert bool(index) is True


def test_unmapped_events_are_skipped_not_guessed() -> None:
    """An event with no registry join produces no date, and does not raise.

    The provider publishes far more events than this system consumes. The
    contract is to ignore the rest — inventing a series key for an unrecognised
    event would attach a release date to the wrong subject.
    """
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(SUCCESS_PAYLOAD), cfg=_cfg())

    assert len(index.dates) == 5
    assert set(index.dates) == {
        "cpi_headline",
        "cpi_core",
        "pce_core",
        "jolts_openings",
        "ppi_headline",
    }


def test_malformed_timestamps_are_skipped_never_defaulted() -> None:
    """``"not-a-date"`` and ``None`` contribute no date — and no fallback.

    The tempting shortcut is to fall back to ``as_of`` or to today when a
    timestamp will not parse. That writes a wrong fact into a point-in-time
    field, which is worse than leaving it unknown.

    Note the shape of this test: it asserts that the bad rows produce **no
    entry at all**, via ``match_counts``, rather than only that the surviving
    date is unchanged. Asserting the date alone is not sufficient — a
    fallback-to-today implementation would write today's date, lose the
    earliest-wins comparison against 2026-08-13, and still leave the anchored
    assertion green (see ``test_unparseable_timestamp_produces_no_entry_for_
    the_event`` for the case that pins it directly).
    """
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(SUCCESS_PAYLOAD), cfg=_cfg())

    # The three bad CPI rows above must not have moved the CPI date off the
    # one well-formed CPI timestamp, nor added phantom entries.
    assert index.get("cpi_headline") == datetime(2026, 8, 13, 8, 30)
    # Exactly ONE CPI row parsed: the two malformed ones contributed nothing.
    # A fallback-to-today mutation makes this 3, which is the real assertion.
    assert index.match_counts["cpi_headline"] == 1
    assert AS_OF not in index.dates.values()
    assert datetime(2026, 9, 20) not in index.dates.values()


def test_unparseable_timestamp_produces_no_entry_for_the_event() -> None:
    """When EVERY timestamp for an event is malformed, the series gets NO date.

    This is the case a fallback-to-today implementation fails loudly and the
    previous test cannot catch, because there is no good row to win the
    earliest-wins comparison — so a fabricated date would be the only entry and
    would be visible. It pins the Section 6 rule at its sharpest point: an
    unparseable release time must yield UNKNOWN, never "today".
    """
    payload = {
        "results": [
            {"date": "not-a-date", "event": "CPI"},
            {"date": "", "event": "CPI"},
            {"date": None, "event": "PPI"},
            {"date": 20260911, "event": "PPI"},  # int, not str
        ]
    }
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(payload), cfg=_cfg())

    assert index.route_read is True  # the route answered...
    assert index.dates == {}  # ...but produced no datable release
    assert "cpi_headline" not in index.dates
    assert "ppi_headline" not in index.dates
    assert index.match_counts == {}


def test_duplicate_event_at_same_instant_records_earliest_and_counts() -> None:
    """Two rows at one instant yield one date and a visible match count.

    CPI and Core CPI share a publication instant but are distinct series here,
    so this also demonstrates the join is on event NAME, not on timestamp. The
    match count is retained so "one row" and "six rows" are distinguishable.
    """
    payload = {
        "results": [
            {"date": "2026-08-27T08:30:00", "event": "Core PCE Price Index"},
            # A later same-release row must not move the date backwards/forwards.
            {"date": "2026-08-27T08:30:00", "event": "Core PCE Price Index"},
        ]
    }
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(payload), cfg=_cfg())

    assert index.get("pce_core") == datetime(2026, 8, 27, 8, 30)
    assert index.match_counts["pce_core"] == 2


def test_earliest_publication_wins_when_rows_arrive_out_of_order() -> None:
    """The EARLIEST datetime is kept, regardless of the order rows arrive in.

    Distinguishing this from "last row wins" needs rows at *different*
    instants, which is why this test exists separately from the
    same-instant duplicate case above. The provider does not guarantee ordering
    across a window — a revised or re-published row can appear after the
    original — and the first publication is the instant the value became
    public, which is the fact this field is defined to carry. Both orderings
    are asserted, so neither "first wins" nor "last wins" passes by accident.
    """
    earlier = {"date": "2026-08-13T08:30:00", "event": "CPI"}
    later = {"date": "2026-08-20T08:30:00", "event": "CPI"}

    for rows, label in (([earlier, later], "ascending"), ([later, earlier], "descending")):
        index = fetch_release_dates(
            as_of=AS_OF, client=_client_returning({"results": rows}), cfg=_cfg()
        )
        assert index.get("cpi_headline") == datetime(2026, 8, 13, 8, 30), (
            f"earliest publication not kept for {label} input order"
        )
        assert index.match_counts["cpi_headline"] == 2


def test_event_name_join_is_case_insensitive() -> None:
    """Capitalisation drift between rows must not drop a release.

    The provider's own rows mix "PCE price index" and "PCE Price index" in the
    wild; a case-sensitive join would silently lose whichever form lost the
    race, producing a data gap that looks like a quiet calendar.
    """
    payload = {
        "results": [
            {"date": "2026-08-27T08:30:00", "event": "core pce price index"},
            {"date": "2026-09-11T08:30:00", "event": "  PPI  "},
        ]
    }
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(payload), cfg=_cfg())

    assert index.get("pce_core") == datetime(2026, 8, 27, 8, 30)
    assert index.get("ppi_headline") == datetime(2026, 9, 11, 8, 30)


def test_query_uses_the_configured_provider_and_window() -> None:
    """The request carries the configured provider and an as_of-centred window.

    Guards against the earlier defect class: the endpoint accepts four
    providers and hardcoding/omitting one is exactly how the original audit
    concluded the route was unreachable.
    """
    client = _client_returning(SUCCESS_PAYLOAD)
    fetch_release_dates(as_of=AS_OF, client=client, cfg=_cfg())

    url, params = client.calls[0]
    assert url == "/api/v1/economy/calendar"
    assert params["provider"] == "nasdaq"
    assert params["start_date"] == "2025-08-16"  # as_of - 400 days
    assert params["end_date"] == "2026-11-04"  # as_of + 45 days


# ---------------------------------------------------------------------------
# (b) Failure is honest — empty, labelled, and never fabricated
# ---------------------------------------------------------------------------


def test_well_formed_failure_body_is_not_mistaken_for_success() -> None:
    """A 200 carrying ``{"detail": ...}`` must read as failure, not as success.

    This is the single most important test in the file. ``raise_for_status()``
    passes on this response, so an implementation that trusts the status code
    reports ``route_read=True`` with an empty map — i.e. it claims "the
    calendar is quiet" when the truth is "the route refused". Those are
    different facts and only one of them is safe to backtest on.
    """
    index = fetch_release_dates(
        as_of=AS_OF, client=_client_returning(NO_RECORD_PAYLOAD), cfg=_cfg()
    )

    assert index.route_read is False
    assert index.dates == {}
    assert bool(index) is False
    assert index.get("cpi_headline") is None


def test_transport_failure_returns_empty_index_without_raising() -> None:
    """An unreachable route is the expected case, not an exception.

    Roughly half of live calls fail this way. Raising would push every snapshot
    build into a failure path for a fact the system is explicitly designed to
    tolerate, so the contract is an empty, labelled index.
    """
    index = fetch_release_dates(
        as_of=AS_OF,
        client=_client_returning(httpx.ConnectError("connection refused")),
        cfg=_cfg(),
    )

    assert index.route_read is False
    assert index.dates == {}
    assert index.match_counts == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"results": []},  # provider succeeded, genuinely no events in window
        {},  # no results key at all
        {"results": "not-a-list"},  # wrong type
        ["not-a-dict"],  # not even an object
    ],
)
def test_empty_or_malformed_payload_yields_empty_index(payload: Any) -> None:
    """Every degenerate shape degrades to an empty, unread-but-safe index.

    Note that ``{"results": []}`` is indistinguishable from a failure at this
    layer, and is deliberately treated as UNREAD rather than as "no releases".
    Erring toward "unknown" is the only choice consistent with Section 6: the
    opposite error silently asserts a quiet calendar.
    """
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(payload), cfg=_cfg())

    assert index.dates == {}
    assert bool(index) is False


#: The THIRD failure signature, captured live 2026-09-20. This is how the
#: upstream Akamai 403 actually presents itself through the local OpenBB server:
#: as an HTTP 500 carrying the real cause inside the JSON body. Reproduced here
#: because the earlier docstring described only the 403 itself, and a test suite
#: that does not exercise the shape the code will really meet is a suite that
#: agrees with its own assumptions rather than with reality.
OPENBB_500_PAYLOAD: dict[str, Any] = {
    "detail": (
        "Unexpected Error -> ContentTypeError -> 403, message='Attempt to decode JSON "
        "with unexpected mimetype: text/html', url='https://api.nasdaq.com/api/calendar/"
        "economicevents?date=2026-09-18'"
    )
}


def test_http_500_from_the_openbb_wrapper_degrades_cleanly() -> None:
    """A 500 whose body names an upstream 403 must degrade, not raise.

    This is the signature that actually occurs today, and it is the most
    misleading of the three: the status says "server error" while the body says
    "the upstream refused me". Either way it is not actionable in code, so the
    contract is to retry and then return an empty, labelled index. A module
    that propagated this would fail every snapshot build.
    """
    error = httpx.HTTPStatusError(
        "Server error '500 Internal Server Error'",
        request=httpx.Request("GET", "http://127.0.0.1:6900/api/v1/economy/calendar"),
        response=httpx.Response(500),
    )
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(error), cfg=_cfg())

    assert index.route_read is False
    assert index.dates == {}
    assert bool(index) is False


def test_http_500_body_naming_a_403_is_still_a_failure_not_a_success() -> None:
    """A 500 whose body *parses* must not be read as a result set.

    Guards the seam: if a future refactor dropped ``raise_for_status`` and
    trusted ``.json()``, this body would parse fine and yield an empty
    "successful" read — claiming a quiet calendar when the route was refused.
    """
    payload = OPENBB_500_PAYLOAD
    assert "results" not in payload  # the body genuinely carries no events
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(payload), cfg=_cfg())

    assert index.route_read is False
    assert index.dates == {}


def test_events_with_no_matching_series_but_successful_read_is_route_read() -> None:
    """A successful read with zero joins is read-but-empty, not unread.

    ``route_read`` must track whether the ROUTE answered, not whether the join
    produced anything — otherwise a calendar that legitimately has no CPI row
    in the window would be reported as a broken connection.
    """
    payload = {"results": [{"date": "2026-09-01T10:00:00", "event": "Something Unmapped"}]}
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(payload), cfg=_cfg())

    assert index.route_read is True
    assert index.dates == {}
    assert bool(index) is False


def test_release_dates_for_series_never_substitutes_a_placeholder() -> None:
    """The per-series helper returns exactly ``None`` when nothing was read.

    Section 6's prohibition is on substituting an observation date (or any
    placeholder) for a release date, so the helper has no fallback path by
    design.
    """
    index = ReleaseDateIndex(dates={}, match_counts={}, route_read=False)
    assert release_dates_for_series("cpi_headline", index=index) is None
    assert release_dates_for_series("does_not_exist", index=index) is None


def test_observation_date_is_never_used_as_the_release_date() -> None:
    """Explicitly pin the forbidden substitution using the real shapes.

    The provider's CPI row is dated 2026-08-13 (release) while the series'
    *observation* period would be 2026-08. Asserting the returned value is the
    release instant and not any month-start convention documents the
    distinction the whole module exists to protect.
    """
    index = fetch_release_dates(as_of=AS_OF, client=_client_returning(SUCCESS_PAYLOAD), cfg=_cfg())

    cpi = index.get("cpi_headline")
    assert cpi is not None
    assert cpi != datetime(2026, 8, 1)  # not the observation-period start
    assert cpi.date() > date(2026, 8, 1)  # publication follows the period


# ---------------------------------------------------------------------------
# (c) The retry actually retries
# ---------------------------------------------------------------------------


def test_retry_recovers_from_a_failure_that_a_single_attempt_would_miss() -> None:
    """One failure then a success must still yield dates.

    This is the test that justifies the retry's existence. The live route failed
    2 of 4 identical calls; without retry, half of all snapshot builds would
    silently lose release timing.
    """
    client = _client_returning(NO_RECORD_PAYLOAD, SUCCESS_PAYLOAD)
    index = fetch_release_dates(as_of=AS_OF, client=client, cfg=_cfg(max_attempts=3))

    assert len(client.calls) == 2
    assert index.route_read is True
    assert index.get("cpi_headline") == datetime(2026, 8, 13, 8, 30)


def test_exhaustion_uses_exactly_max_attempts_and_then_stops() -> None:
    """The route is tried ``max_attempts`` times — no more, no fewer.

    Both bounds matter: fewer means the retry budget is not honoured; more means
    an unattended build keeps hammering a rate-limited provider.
    """
    client = _client_returning(NO_RECORD_PAYLOAD)
    cfg = _cfg(max_attempts=4)
    index = fetch_release_dates(as_of=AS_OF, client=client, cfg=cfg)

    assert len(client.calls) == 4
    assert index.route_read is False


def test_retry_applies_increasing_backoff_between_attempts() -> None:
    """Sleep grows as ``backoff_seconds * attempt`` across attempts.

    Pinned because the shape matters: a constant, very short delay against a
    rate-limited host is indistinguishable from no retry at all. The values are
    asserted in order (1.5, 3.0, 4.5 — not paid after the final attempt).
    """
    client = _client_returning(NO_RECORD_PAYLOAD)
    cfg = _cfg(max_attempts=4, backoff_seconds=1.5)

    with pytest.MonkeyPatch.context() as mp:
        sleeps: list[float] = []
        mp.setattr(
            "macro_engine.data_layer.release_calendar.time.sleep",
            lambda seconds: sleeps.append(seconds),
        )
        fetch_release_dates(as_of=AS_OF, client=client, cfg=cfg)

    assert sleeps == [1.5, 3.0, 4.5]


def test_no_sleep_after_the_final_attempt() -> None:
    """A wasted sleep after the last failure only delays an already-failed build."""
    client = _client_returning(NO_RECORD_PAYLOAD)

    with pytest.MonkeyPatch.context() as mp:
        sleeps: list[float] = []
        mp.setattr(
            "macro_engine.data_layer.release_calendar.time.sleep",
            lambda seconds: sleeps.append(seconds),
        )
        fetch_release_dates(
            as_of=AS_OF, client=client, cfg=_cfg(max_attempts=1, backoff_seconds=2.0)
        )

    assert sleeps == []


# ---------------------------------------------------------------------------
# Misconfiguration — the only condition that raises
# ---------------------------------------------------------------------------


def test_disabled_calendar_raises_because_it_will_never_resolve() -> None:
    """A disabled calendar is a defect, so it raises rather than degrading.

    Contrast with an unreachable route, which degrades. The distinction is
    whether retrying could ever succeed: a config flag cannot change itself.
    """
    with pytest.raises(ReleaseCalendarError, match="disabled"):
        fetch_release_dates(
            as_of=AS_OF, client=_client_returning(SUCCESS_PAYLOAD), cfg=_cfg(enabled=False)
        )


def test_missing_event_map_raises_because_no_join_is_possible() -> None:
    """Without an event map there is no way to attribute a date to a series."""
    with pytest.raises(ReleaseCalendarError, match="event_map"):
        fetch_release_dates(
            as_of=AS_OF, client=_client_returning(SUCCESS_PAYLOAD), cfg=_cfg(event_map={})
        )


def test_misconfiguration_is_raised_before_any_network_call() -> None:
    """Config validation precedes I/O — a bad config must not cost a request."""
    client = _client_returning(SUCCESS_PAYLOAD)
    with pytest.raises(ReleaseCalendarError):
        fetch_release_dates(as_of=AS_OF, client=client, cfg=_cfg(enabled=False))

    assert client.calls == []


# ---------------------------------------------------------------------------
# Wiring: the index reaching ObservationPoint.release_datetime (Section 6)
# ---------------------------------------------------------------------------


def _frame_for(series_id: str, values: list[float]) -> pd.DataFrame:
    """A minimal frame in the shape ``OpenBBClient.fetch_series`` returns."""
    now = utc_now()
    return pd.DataFrame(
        {
            "date": [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)][: len(values)],
            "value": values,
            "series_id": series_id,
            "source": "fred:CPIAUCSL",
            "retrieved_at": [now] * len(values),
        }
    )


def test_points_carry_the_release_datetime_from_the_index() -> None:
    """A populated index reaches every point, and ``has_known_release_timing`` flips.

    This is the assertion that the section "wiring" actually happened. The
    module could be perfect and still be dead code if nothing consumed it, so
    the property that matters is ``has_known_release_timing`` — the exact flag a
    consumer asks for — becoming True.
    """
    from macro_engine.data_layer.snapshot_builder import _points_from_frame

    index = ReleaseDateIndex(
        dates={"cpi_headline": datetime(2026, 8, 13, 8, 30)},
        match_counts={"cpi_headline": 1},
        route_read=True,
    )
    points = _points_from_frame(
        _frame_for("cpi_headline", [1.0, 2.0, 3.0]),
        series_id="cpi_headline",
        fallback_source="fred:CPIAUCSL",
        release_index=index,
    )

    assert len(points) == 3
    assert all(p.release_datetime == datetime(2026, 8, 13, 8, 30) for p in points)
    assert all(p.has_known_release_timing for p in points)
    # observation_date is untouched and remains a DIFFERENT fact.
    assert [p.observation_date for p in points] == [
        date(2026, 6, 1),
        date(2026, 7, 1),
        date(2026, 8, 1),
    ]
    assert all(p.release_datetime != p.observation_date for p in points)


def test_points_leave_release_datetime_none_when_the_index_is_empty() -> None:
    """An empty index yields None — not an observation-date fallback.

    Both the "route unreadable" and the "series simply absent" cases must leave
    the field None. The forbidden behaviour is filling it with
    ``observation_date``, which would make ``has_known_release_timing`` True on
    the strength of a different fact.
    """
    from macro_engine.data_layer.snapshot_builder import _points_from_frame

    index = ReleaseDateIndex(dates={}, match_counts={}, route_read=False)
    points = _points_from_frame(
        _frame_for("cpi_headline", [1.0, 2.0]),
        series_id="cpi_headline",
        fallback_source="fred:CPIAUCSL",
        release_index=index,
    )

    assert all(p.release_datetime is None for p in points)
    assert not any(p.has_known_release_timing for p in points)


def test_points_leave_release_datetime_none_when_no_lookup_was_attempted() -> None:
    """Omitting the index entirely is also None — never a silent default."""
    from macro_engine.data_layer.snapshot_builder import _points_from_frame

    points = _points_from_frame(
        _frame_for("cpi_headline", [1.0]),
        series_id="cpi_headline",
        fallback_source="fred:CPIAUCSL",
    )

    assert points[0].release_datetime is None
    assert points[0].has_known_release_timing is False


def test_only_the_matching_series_gets_a_date() -> None:
    """A date for CPI must not leak onto an unmapped series.

    The failure this guards is a lookup keyed by something too loose (position,
    or a truthy-index check) that stamps every series in the snapshot with the
    same release instant — which would look plausible and be wrong everywhere
    except one series.
    """
    from macro_engine.data_layer.snapshot_builder import _points_from_frame

    index = ReleaseDateIndex(
        dates={"cpi_headline": datetime(2026, 8, 13, 8, 30)}, match_counts={}, route_read=True
    )

    mapped = _points_from_frame(
        _frame_for("cpi_headline", [1.0]),
        series_id="cpi_headline",
        fallback_source="fred:CPIAUCSL",
        release_index=index,
    )
    unmapped = _points_from_frame(
        _frame_for("unemployment_rate", [4.2]),
        series_id="unemployment_rate",
        fallback_source="fred:UNRATE",
        release_index=index,
    )

    assert mapped[0].release_datetime is not None
    assert unmapped[0].release_datetime is None


def test_empty_frame_returns_no_points_rather_than_one_fabricated_point() -> None:
    """An empty frame yields ``[]`` — not a point with a synthetic date."""
    from macro_engine.data_layer.snapshot_builder import _points_from_frame

    points = _points_from_frame(
        _frame_for("cpi_headline", []),
        series_id="cpi_headline",
        fallback_source="fred:CPIAUCSL",
        release_index=ReleaseDateIndex(
            dates={"cpi_headline": datetime(2026, 8, 13)}, route_read=True
        ),
    )

    assert points == []


def test_build_report_flags_release_timing_unknown_when_calendar_unread() -> None:
    """The build report must make an unread calendar visible as a flag.

    A consumer reading only ``data_quality_flags`` — which is the documented
    contract for "this snapshot has a gap" — must be able to see that release
    timing is unknown, rather than having to inspect the calendar object.

    The flag names the **source that went dark** rather than a generic
    "unreadable", because the per-series metadata route and the events calendar
    fail for entirely different reasons and send a reader to different places.
    When no source is recorded the fallback label keeps the flag well-formed.
    """
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    report = SnapshotBuildReport()
    report.release_calendar_read = False
    flags = report.as_flags()
    # Source unset -> generic label, never a half-built "…:" flag.
    assert "RELEASE_TIMING_UNKNOWN:source_unreadable" in flags

    report.release_timing_outage_source = "publication_dates"
    assert "RELEASE_TIMING_UNKNOWN:publication_dates" in report.as_flags()


def test_build_report_does_not_flag_when_the_calendar_was_read() -> None:
    """A successful read must not produce the "timing unknown" flag."""
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    report = SnapshotBuildReport()
    report.release_calendar_read = True
    assert not any(f.startswith("RELEASE_TIMING_UNKNOWN") for f in report.as_flags())


def test_build_report_does_not_flag_when_the_calendar_was_never_attempted() -> None:
    """``None`` (never attempted) is a config choice, so it raises no flag.

    This distinction is deliberate and load-bearing. ``release_calendar_read``
    has three states and they must not collapse:

        True  -> asked and answered    -> no flag
        False -> asked and unreadable  -> FLAG (timing is genuinely unknown)
        None  -> never asked           -> no flag (nothing is known to be wrong)

    Flagging ``None`` would put a permanent INFO line on every snapshot built
    with the calendar disabled, which trains a reader to ignore the flag list —
    the exact opposite of what the list is for.
    """
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    report = SnapshotBuildReport()
    assert report.release_calendar_read is None  # default, never attempted
    assert not any(f.startswith("RELEASE_TIMING_UNKNOWN") for f in report.as_flags())


def test_three_state_flag_matrix_is_exhaustively_pinned() -> None:
    """Pin all three states in one place so a refactor cannot collapse them."""
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    def flags_for(state: bool | None) -> list[str]:
        report = SnapshotBuildReport()
        report.release_calendar_read = state
        return report.as_flags()

    marker = "RELEASE_TIMING_UNKNOWN"
    assert not any(marker in f for f in flags_for(None))
    assert not any(marker in f for f in flags_for(True))
    assert any(marker in f for f in flags_for(False))


def test_build_report_flags_a_misconfigured_calendar() -> None:
    """A misconfiguration is surfaced as its own flag, distinct from unread."""
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    report = SnapshotBuildReport()
    report.release_calendar_note = "misconfigured: event_map is empty"
    flags = report.as_flags()

    assert any(f.startswith("RELEASE_CALENDAR_MISCONFIGURED") for f in flags)


# ---------------------------------------------------------------------------
# A total outage of the PRIMARY route must not read as "never asked"
# ---------------------------------------------------------------------------
#
# The defect this pins (review finding 3.4): the primary ``publication_dates``
# route is the one carrying 42/42 registry coverage. ``fetch_publication_dates``
# returns ``route_read=bool(dates)``, so when EVERY series exhausts its retry
# budget the index comes back with ``route_read=False`` — enabled, queried, and
# completely dead. The resolver only ever set ``release_calendar_read = True`` on
# the primary path, so that case left the flag at ``None``: no flag raised, and a
# snapshot whose release timing was unknown for all 42 series was flagged clean.
#
# The tests below drive ``_resolve_release_index`` with the fetchers stubbed, so
# they assert the RESOLVER's bookkeeping rather than any network behaviour. That
# is the layer that was wrong, and it is reachable without a live route.


def _stub_resolver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary: object | None,
    primary_enabled: bool = True,
    fallback: object | None = None,
    fallback_enabled: bool = False,
) -> SnapshotBuildReport:
    """Run ``_resolve_release_index`` against stubbed fetchers and registry."""
    from macro_engine.data_layer import snapshot_builder

    class _Block:
        def __init__(self, enabled: bool) -> None:
            self.enabled = enabled

    class _Registry:
        publication_dates = _Block(primary_enabled)
        release_calendar = _Block(fallback_enabled)

    monkeypatch.setattr(snapshot_builder, "get_registry", lambda: _Registry())
    monkeypatch.setattr(snapshot_builder, "fetch_publication_dates", lambda: primary, raising=False)
    monkeypatch.setattr(snapshot_builder, "fetch_release_dates", lambda: fallback, raising=False)

    report = snapshot_builder.SnapshotBuildReport()
    snapshot_builder._resolve_release_index(report)
    return report


def _dead_primary() -> object:
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex

    # What fetch_publication_dates returns when every series fails: empty dates,
    # route_read False. Enabled, asked, and silent.
    return ReleaseDateIndex(dates={}, match_counts={}, route_read=False)


def test_total_primary_outage_is_flagged_not_treated_as_never_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE regression: 0-of-42 from the primary route is an OUTAGE, not a config choice."""
    report = _stub_resolver(monkeypatch, primary=_dead_primary())

    assert report.release_calendar_read is False, (
        "a total outage of the primary release-timing route left the tri-state "
        "flag at None, so it was indistinguishable from 'nobody asked'"
    )
    assert report.release_timing_outage_source == "publication_dates"
    assert "RELEASE_TIMING_UNKNOWN:publication_dates" in report.as_flags()


def test_primary_outage_does_not_report_release_timing_as_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And it must not claim a source answered, either."""
    report = _stub_resolver(monkeypatch, primary=_dead_primary())

    assert report.release_source is None
    assert report.release_calendar_series == 0


def test_a_partial_primary_read_is_not_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One series answering is a successful read, not a 100% failure.

    ``route_read`` is True when *any* series was read, and that is the honest
    signal for a per-series route: a single symbol FRED does not carry must not
    mark the whole snapshot's release timing as unknown.
    """
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex

    partial = ReleaseDateIndex(
        dates={"cpi_headline": datetime(2026, 8, 12)},
        match_counts={"cpi_headline": 1},
        route_read=True,
    )
    report = _stub_resolver(monkeypatch, primary=partial)

    assert report.release_calendar_read is True
    assert report.release_source == "publication_dates"
    assert report.release_calendar_series == 1
    assert report.release_timing_outage_source is None
    assert not any(f.startswith("RELEASE_TIMING_UNKNOWN") for f in report.as_flags())


def test_primary_never_attempted_still_raises_no_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled primary keeps the flag at None — the config-choice case.

    This is the state it is legitimate for ``None`` to represent, and it must not
    be collateral damage from the fix above.
    """
    report = _stub_resolver(monkeypatch, primary=None, primary_enabled=False)

    assert report.release_calendar_read is None
    assert report.release_timing_outage_source is None
    assert not any(f.startswith("RELEASE_TIMING_UNKNOWN") for f in report.as_flags())


def test_a_dead_fallback_names_itself_as_the_outage_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback path already set False; it must now also name the source."""
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex

    dead_calendar = ReleaseDateIndex(dates={}, match_counts={}, route_read=False)
    report = _stub_resolver(
        monkeypatch,
        primary=None,
        primary_enabled=False,
        fallback=dead_calendar,
        fallback_enabled=True,
    )

    assert report.release_calendar_read is False
    assert report.release_timing_outage_source == "release_calendar"
    assert "RELEASE_TIMING_UNKNOWN:release_calendar" in report.as_flags()


def test_a_dead_primary_does_not_shadow_a_working_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the calendar answers and metadata does not, timing IS known.

    The outage flag exists to say "we asked and learned nothing". A working
    fallback means we did learn something, so marking the flag False here would
    be a false alarm — and a false alarm on a flag list is how the list stops
    being read.
    """
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex

    working_fallback = ReleaseDateIndex(
        dates={"cpi_headline": datetime(2026, 8, 13)},
        match_counts={"cpi_headline": 1},
        route_read=True,
    )
    report = _stub_resolver(
        monkeypatch,
        primary=_dead_primary(),
        fallback=working_fallback,
        fallback_enabled=True,
    )

    assert report.release_source == "release_calendar"
    assert report.release_calendar_read is True
    assert not any(f.startswith("RELEASE_TIMING_UNKNOWN") for f in report.as_flags())


# ---------------------------------------------------------------------------
# The registry's shipped block
# ---------------------------------------------------------------------------


def test_shipped_registry_block_is_loadable_and_joins_real_event_names() -> None:
    """The committed config must load with a usable join out of the box.

    Guards the seam between the YAML block and this module: a block that parses
    but whose event names do not match the provider's would look correct and
    silently map nothing.
    """
    from macro_engine.config import get_registry

    cfg = get_registry().release_calendar
    assert cfg.provider == "nasdaq"
    assert cfg.endpoint == "economy.calendar"
    assert cfg.max_attempts > 0
    assert cfg.window_days_back > 0
    # The macro prints this system actually consumes must be mapped.
    for event in ("CPI", "Core CPI", "Core PCE Price Index", "PPI", "JOLTS Job Openings"):
        assert event in cfg.event_map, f"{event!r} missing from event_map"
    assert cfg.event_map["CPI"] == "cpi_headline"


def test_every_shipped_event_map_target_is_a_real_registry_series() -> None:
    """Every join target must RESOLVE, not merely exist as a string.

    Audit finding R-1, Class C/E (2026-09-29). The test above asserts the event
    *names* are present — which four dead rows passed. But the value of each row
    is a **registry series key**, and ``build_snapshot`` reads the release index
    by that key (``release_index.get(series_id)``). So a target that is not in
    ``registry.series`` is unreachable: the calendar matches the event, the index
    carries the date, and no observation ever reads it — silently.

    This test pins the SHIPPED config so the four phantom rows
    (``ppi_core``/``nfp``/``gdp_deflator``/``industrial_production``) cannot
    return; the validator in ``SeriesRegistry`` is what refuses them at load.
    """
    from macro_engine.config import get_registry

    registry = get_registry()
    targets = set(registry.release_calendar.event_map.values())
    unknown = sorted(targets - set(registry.series))
    assert not unknown, (
        f"release_calendar.event_map joins to series that do not exist in the "
        f"registry: {unknown}. A release date attributed to a nonexistent series "
        f"is unreachable, so the join is dead."
    )


def test_the_registry_refuses_an_event_map_join_to_a_missing_series() -> None:
    """The validator FIRES — the killer half of finding R-1.

    Without this, the guard above is only a snapshot assertion: it would pass on
    a config that still shipped the defect-free map while the validator sat
    unreachable. So the validator is driven directly, with a dead join planted
    into an otherwise-valid registry, and both the refusal and the message that
    NAMES the offending target are asserted.
    """
    import yaml

    from macro_engine.config import SeriesRegistry

    root = Path(__file__).resolve().parent.parent.parent
    raw = yaml.safe_load((root / "config" / "series_registry.yaml").read_text(encoding="utf-8"))
    raw["release_calendar"]["event_map"]["Core PPI"] = "ppi_core"

    with pytest.raises(ValueError, match="ppi_core"):
        SeriesRegistry.model_validate(raw)


def test_the_validator_accepts_a_join_to_a_series_that_exists() -> None:
    """The validator is not a blanket refusal — a legitimate new row passes.

    The negative control: a join to a declared series must load. Without it, a
    validator that rejected every map would satisfy the firing test above while
    breaking the feature.
    """
    import yaml

    from macro_engine.config import SeriesRegistry

    root = Path(__file__).resolve().parent.parent.parent
    raw = yaml.safe_load((root / "config" / "series_registry.yaml").read_text(encoding="utf-8"))
    raw["release_calendar"]["event_map"]["Producer Price Index"] = "ppi"

    validated = SeriesRegistry.model_validate(raw)
    assert validated.release_calendar.event_map["Producer Price Index"] == "ppi"
