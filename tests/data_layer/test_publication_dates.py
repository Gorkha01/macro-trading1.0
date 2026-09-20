"""Section 6 exact publication-date tests — ``last_updated`` per series.

What these tests are for
------------------------
``publication_dates.py`` reads each series' own ``last_updated`` metadata. The
dangerous failure mode is not a crash — it is a reader that accepts the WRONG
row, because ``search_type=series_id`` is a **prefix** search and the response
for ``UNRATE`` legitimately contains ``UNRATECTH``, ``UNRATECTL`` and others.
Attaching a sibling's publication time to ``UNRATE`` is a wrong fact rather than
a missing one: missing is recoverable, wrong is not.

So the tests target three properties:

(a) an **exact** ``series_id`` match is required — prefix siblings never qualify;
(b) the parse preserves the provider's **offset** rather than dropping it;
(c) failure yields an empty/absent entry and never a substituted date.

The payload shapes below are the real ones, captured from
``http://127.0.0.1:6901`` on 2026-09-20 — including the true prefix-sibling
crowding that made ``UNRATE`` unreadable at a low limit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from macro_engine.config import PublicationDates
from macro_engine.data_layer.publication_dates import (
    PublicationDateError,
    fetch_publication_dates,
)

# ---------------------------------------------------------------------------
# Real payload shapes, captured live 2026-09-20
# ---------------------------------------------------------------------------

#: The verbatim shape for CPIAUCSL. The offset (-05:00) is the provider's own
#: and must survive parsing.
CPIAUCSL_PAYLOAD: dict[str, Any] = {
    "results": [
        {
            "series_id": "CPIAUCSL",
            "title": "Consumer Price Index for All Urban Consumers: All Items",
            "observation_start": "1947-01-01",
            "observation_end": "2026-08-01",
            "frequency": "Monthly",
            "last_updated": "2026-09-11T08:37:49-05:00",
            "realtime_start": "2026-09-19",
            "realtime_end": "2026-09-19",
        }
    ]
}

#: The real crowding failure: 5 prefix siblings and NO exact `UNRATE` at a low
#: limit. This is what the exact-match rule and the high default limit exist to
#: survive.
UNRATE_CROWDED_PAYLOAD: dict[str, Any] = {
    "results": [
        {"series_id": "UNRATECTH", "last_updated": "2026-09-19T00:00:00-05:00"},
        {"series_id": "UNRATECTL", "last_updated": "2026-09-19T00:00:00-05:00"},
        {"series_id": "UNRATECTM", "last_updated": "2026-09-19T00:00:00-05:00"},
        {"series_id": "UNRATEMD", "last_updated": "2026-09-19T00:00:00-05:00"},
        {"series_id": "UNRATERH", "last_updated": "2026-09-19T00:00:00-05:00"},
    ]
}

#: The same query at limit=1000, where the exact row finally appears — among
#: its siblings, not instead of them.
UNRATE_RECOVERED_PAYLOAD: dict[str, Any] = {
    "results": [
        *UNRATE_CROWDED_PAYLOAD["results"],
        {"series_id": "UNRATE", "last_updated": "2026-09-04T08:27:31-05:00"},
    ]
}


def _cfg(**overrides: Any) -> PublicationDates:
    base: dict[str, Any] = {
        "enabled": True,
        "provider": "fred",
        "endpoint": "economy.fred_search",
        "search_type": "series_id",
        "limit": 1000,
        "max_attempts": 3,
        "backoff_seconds": 0.0,
    }
    base.update(overrides)
    return PublicationDates(**base)


def _client_returning(*responses: Any, per_symbol: dict[str, Any] | None = None) -> MagicMock:
    """A mock client serving ``responses`` in order, or per-query overrides.

    ``per_symbol`` lets a test key the payload on the ``query`` parameter, which
    is the only way to exercise a per-series route where different symbols
    legitimately return different shapes.
    """
    seq = list(responses)
    calls: list[tuple[str, dict[str, str]]] = []

    def _get(url: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        p = dict(params or {})
        calls.append((url, p))
        if per_symbol is not None:
            item = per_symbol.get(p.get("query", ""), {"results": []})
        else:
            item = seq[min(len(calls) - 1, len(seq) - 1)]
        if isinstance(item, Exception):
            raise item
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status.return_value = None
        resp.json.return_value = item
        return resp

    client = MagicMock(spec=httpx.Client)
    client.get.side_effect = _get
    client.calls = calls
    return client


def _one_series(monkeypatch: pytest.MonkeyPatch, symbol: str) -> None:
    """Restrict the registry to a single series, so a test is not 42 calls."""
    monkeypatch.setattr(
        "macro_engine.data_layer.publication_dates._resolve_series_symbols",
        lambda: {"test_series": symbol},
    )


# ---------------------------------------------------------------------------
# (a) Exact match is required
# ---------------------------------------------------------------------------


def test_exact_match_is_read_and_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact series' `last_updated` is read and becomes a datetime."""
    _one_series(monkeypatch, "CPIAUCSL")
    idx = fetch_publication_dates(client=_client_returning(CPIAUCSL_PAYLOAD), cfg=_cfg())

    assert idx.route_read is True
    stamp = idx.get("test_series")
    assert stamp == datetime(2026, 9, 11, 8, 37, 49, tzinfo=timezone(timedelta(hours=-5)))


def test_prefix_sibling_is_never_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response full of prefix siblings yields NO entry for the series.

    This is the central correctness test. Every row here shares the ``UNRATE``
    prefix and carries a valid `last_updated`, so an implementation that took
    "the first result" or matched by prefix would return a date — the wrong
    date, for a different series. The correct behaviour is to return nothing.
    """
    _one_series(monkeypatch, "UNRATE")
    idx = fetch_publication_dates(
        client=_client_returning(UNRATE_CROWDED_PAYLOAD), cfg=_cfg(limit=5)
    )

    assert idx.get("test_series") is None
    assert idx.dates == {}
    assert idx.route_read is False


def test_exact_row_is_found_among_its_siblings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact row wins even when surrounded by prefix siblings.

    Proves the rule is equality, not "the first" and not "the shortest": the
    match here is the 6th row, and the 5 rows before it all carry dates.
    """
    _one_series(monkeypatch, "UNRATE")
    idx = fetch_publication_dates(
        client=_client_returning(UNRATE_RECOVERED_PAYLOAD), cfg=_cfg(limit=1000)
    )

    assert idx.get("test_series") == datetime(
        2026, 9, 4, 8, 27, 31, tzinfo=timezone(timedelta(hours=-5))
    )


def test_a_sibling_date_is_never_used_as_a_fallback_for_the_exact_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Critically: no "close enough" fallback when the exact row is absent.

    The tempting shortcut is to fall back to the nearest prefix match so the
    field is *populated*. That is precisely the failure this module must not
    have, so it is pinned explicitly rather than left implied.
    """
    _one_series(monkeypatch, "GDP")
    payload = {
        "results": [
            {"series_id": "GDPPOT", "last_updated": "2026-02-27T15:05:28-06:00"},
            {"series_id": "NGDPPOT", "last_updated": "2026-02-27T15:05:28-06:00"},
        ]
    }
    idx = fetch_publication_dates(client=_client_returning(payload), cfg=_cfg())

    assert idx.get("test_series") is None
    assert all(
        v != datetime(2026, 2, 27, 15, 5, 28, tzinfo=timezone(timedelta(hours=-6)))
        for v in idx.dates.values()
    )


# ---------------------------------------------------------------------------
# (b) The provider's offset is preserved
# ---------------------------------------------------------------------------


def test_provider_offset_is_preserved_not_normalised() -> None:
    """-05:00 survives parsing, because it is the source's own statement.

    Re-normalising to UTC would still compare equal under ``==`` for an aware
    datetime, so the assertion checks ``utcoffset()`` and ``hour`` directly —
    the fields a naive normalisation would actually change.
    """
    from macro_engine.data_layer.publication_dates import _extract_exact

    stamp = _extract_exact("CPIAUCSL", CPIAUCSL_PAYLOAD)
    assert stamp is not None
    assert stamp.utcoffset() == timedelta(hours=-5)
    assert stamp.hour == 8  # not 13 (the UTC-normalised equivalent)
    assert stamp.tzinfo is not None  # never naive


def test_unparseable_timestamp_yields_none_not_a_default() -> None:
    """A malformed stamp produces None — never today, never as_of."""
    from macro_engine.data_layer.publication_dates import _extract_exact

    for bad in ("not-a-date", "", "   ", None, 20260911):
        payload = {"results": [{"series_id": "X", "last_updated": bad}]}
        assert _extract_exact("X", payload) is None


def test_missing_last_updated_key_yields_none() -> None:
    """A row without the field is not a match, even if the series_id is right."""
    from macro_engine.data_layer.publication_dates import _extract_exact

    assert _extract_exact("X", {"results": [{"series_id": "X"}]}) is None


# ---------------------------------------------------------------------------
# (c) Failure is honest
# ---------------------------------------------------------------------------


def test_other_series_failures_do_not_lose_a_good_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """This route is per-series, so one failure must not void the whole read.

    ``route_read`` is True when at least one series was read — the honest signal
    for a per-series route, where "some failed" and "the route is down" are
    different statements.
    """
    monkeypatch.setattr(
        "macro_engine.data_layer.publication_dates._resolve_series_symbols",
        lambda: {"good": "AAA", "bad": "BBB"},
    )
    client = _client_returning(
        per_symbol={
            "AAA": {"results": [{"series_id": "AAA", "last_updated": "2026-09-01T00:00:00-05:00"}]},
            "BBB": {"results": []},
        }
    )
    idx = fetch_publication_dates(client=client, cfg=_cfg())

    assert idx.route_read is True
    assert idx.get("good") is not None
    assert idx.get("bad") is None


def test_transport_failure_returns_empty_index_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable route degrades to an empty index, never an exception."""
    _one_series(monkeypatch, "CPIAUCSL")
    idx = fetch_publication_dates(
        client=_client_returning(httpx.ConnectError("refused")), cfg=_cfg()
    )

    assert idx.route_read is False
    assert idx.dates == {}
    assert idx.get("test_series") is None


def test_retry_recovers_from_a_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """One failure then success still yields the date, and retry is used."""
    _one_series(monkeypatch, "CPIAUCSL")
    client = _client_returning({"results": []}, CPIAUCSL_PAYLOAD)
    idx = fetch_publication_dates(client=client, cfg=_cfg(max_attempts=3))

    assert len(client.calls) == 2
    assert idx.get("test_series") is not None


def test_exhaustion_uses_max_attempts_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly ``max_attempts`` requests, then stop — no unbounded retrying."""
    _one_series(monkeypatch, "CPIAUCSL")
    client = _client_returning({"results": []})
    idx = fetch_publication_dates(client=client, cfg=_cfg(max_attempts=2))

    assert len(client.calls) == 2
    assert idx.route_read is False


def test_missing_exact_row_in_a_full_response_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NON-EMPTY response without the exact row must NOT be retried.

    Retrying cannot change a well-formed answer that lacks the row, so a retry
    here is pure latency. The payload is deliberately non-empty — an empty
    result set is a DIFFERENT case (transient blank) and must retry, which
    ``test_empty_result_set_is_retried`` pins separately.
    """
    _one_series(monkeypatch, "UNRATE")
    client = _client_returning(UNRATE_CROWDED_PAYLOAD)
    fetch_publication_dates(client=client, cfg=_cfg(max_attempts=5))

    assert len(client.calls) == 1


def test_empty_result_set_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """An EMPTY result set is transient, so it must consume the retry budget.

    This is the bug the tests above caught in the first implementation: an empty
    set was treated identically to "the row is absent", which skipped the entire
    retry budget and turned a transient blank into a permanent gap.
    """
    _one_series(monkeypatch, "CPIAUCSL")
    client = _client_returning({"results": []})
    fetch_publication_dates(client=client, cfg=_cfg(max_attempts=4))

    assert len(client.calls) == 4


def test_empty_then_populated_response_recovers_within_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient blank followed by a real response yields the date."""
    _one_series(monkeypatch, "CPIAUCSL")
    client = _client_returning({"results": []}, {"results": []}, CPIAUCSL_PAYLOAD)
    idx = fetch_publication_dates(client=client, cfg=_cfg(max_attempts=3))

    assert len(client.calls) == 3
    assert idx.get("test_series") is not None
    assert idx.route_read is True


def test_disabled_source_raises_because_no_retry_can_fix_it() -> None:
    """A disabled source is a defect, not an availability problem."""
    with pytest.raises(PublicationDateError, match="disabled"):
        fetch_publication_dates(client=_client_returning(CPIAUCSL_PAYLOAD), cfg=_cfg(enabled=False))


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


def test_request_carries_the_exact_lookup_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request must use series_id search at the configured limit.

    Both parameters are load-bearing: `full_text` does not reliably surface an
    exact symbol, and a low limit loses it to prefix siblings.
    """
    _one_series(monkeypatch, "CPIAUCSL")
    client = _client_returning(CPIAUCSL_PAYLOAD)
    fetch_publication_dates(client=client, cfg=_cfg(limit=1000))

    url, params = client.calls[0]
    assert url == "/api/v1/economy/fred_search"
    assert params["provider"] == "fred"
    assert params["query"] == "CPIAUCSL"
    assert params["search_type"] == "series_id"
    assert params["limit"] == "1000"


# ---------------------------------------------------------------------------
# The registry's shipped block
# ---------------------------------------------------------------------------


def test_shipped_publication_dates_block_is_enabled_and_sane() -> None:
    """The committed config must be the primary source, enabled out of the box."""
    from macro_engine.config import get_registry

    cfg = get_registry().publication_dates
    assert cfg.enabled is True
    assert cfg.provider == "fred"
    assert cfg.search_type == "series_id"
    assert cfg.limit >= 1000  # high enough to survive prefix crowding
    assert cfg.max_attempts > 0


def test_shipped_calendar_is_disabled_now_that_metadata_covers_it() -> None:
    """The calendar is retained as a documented fallback, not the default.

    Leaving it enabled would spend 5 retries per build on an edge-blocked route
    while adding nothing the metadata source lacks. This pins that decision so a
    future edit that re-enables it is a deliberate act.
    """
    from macro_engine.config import get_registry

    calendar = get_registry().release_calendar
    assert calendar.enabled is False
    # ...but it must remain fully configured for a one-flag re-enable.
    assert calendar.provider == "nasdaq"
    assert calendar.event_map, "event_map must stay populated for re-enabling"
