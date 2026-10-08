"""F-OBB-001 — the OpenBB path must not emit a URL-embedded credential.

OpenBB's FRED provider builds request URLs with the key INLINE
(``openbb_fred/utils/fred_base.py:27``, ``.../series.py:135``) and
``openbb_core``'s ``helpers.make_request`` does **no** redaction — it passes the
URL straight to ``requests``. Its rate limiter redacts, but only for its own log
line. So an exception from the package path can carry the live key in its text,
and ``OpenBBClient``'s two public fetch methods log and re-raise provider
exceptions verbatim.

``alfred_client`` redacts BY VALUE because it holds the key; this module never
reads it (it is OpenBB's), so a PATTERN is the only guard available.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from macro_engine.data_layer.openbb_client import (
    OpenBBClient,
    OpenBBClientConfig,
    OpenBBFetchError,
    _redact_credentials,
)

#: Shaped like the real thing: a requests/httpx error quoting the full URL.
_LEAKY = (
    "HTTPSConnectionPool(host='api.stlouisfed.org', port=443): Max retries exceeded "
    "with url: /fred/series/observations?series_id=CPIAUCSL&api_key=SECRETKEY123"
    "&file_type=json (Caused by NewConnectionError(...))"
)
#: The sentinel this test searches for. Not a credential — a string that must
#: never survive the redaction.
_SECRET = "SECRETKEY123"  # noqa: S105 - a marker, not a secret


def _explode(*_args: object, **_kwargs: object) -> object:
    raise httpx.ConnectError(_LEAKY)


def _client() -> OpenBBClient:
    return OpenBBClient(OpenBBClientConfig(max_retries=1, backoff_seconds=0.0))


def test_a_provider_exception_never_carries_the_credential(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Both fetch methods log AND re-raise the provider exception."""
    client = _client()
    # Both paths fail, so the cross-path fallback fires too — three emit sites.
    monkeypatch.setattr(client, "_fetch_via_local_api", _explode)
    monkeypatch.setattr(client, "_fetch_via_package", _explode)

    with caplog.at_level(logging.WARNING), pytest.raises(OpenBBFetchError) as exc:
        client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": "CPIAUCSL"},
            series_label="cpi_headline",
        )

    assert _SECRET not in caplog.text, "the credential reached the log"
    assert _SECRET not in str(exc.value), "the credential reached the exception"
    assert "***REDACTED***" in caplog.text
    assert "***REDACTED***" in str(exc.value)


def test_the_fetch_records_path_is_redacted_too(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client = _client()
    monkeypatch.setattr(client, "_fetch_records_via_local_api", _explode)
    monkeypatch.setattr(client, "_fetch_records_via_package", _explode)

    with caplog.at_level(logging.WARNING), pytest.raises(OpenBBFetchError) as exc:
        client.fetch_records(
            provider="eia",
            endpoint="commodity.petroleum_status_report",
            params={"table": "stocks"},
            series_label="crude_inventory_weekly",
        )

    assert _SECRET not in caplog.text
    assert _SECRET not in str(exc.value)


def test_the_redaction_is_pattern_based_and_leaves_ordinary_text_alone() -> None:
    """This module never holds the key, so it cannot redact by value."""
    assert (
        _redact_credentials("url?series_id=X&api_key=abc123&file_type=json")
        == "url?series_id=X&api_key=***REDACTED***&file_type=json"
    )
    # Also stops at a quote, so an embedded URL inside a repr is covered.
    assert _redact_credentials("'api_key=abc123'") == "'api_key=***REDACTED***'"
    assert _redact_credentials("no credential here") == "no credential here"
    assert _redact_credentials("") == ""


def test_keep_alive_is_disabled_on_the_http_client() -> None:
    """F-OBB-002: an untested configuration claim.

    ``__init__`` documents a measured defect — a reused connection gets 200 then
    404 forever against the local OpenBB service — and pins
    ``max_keepalive_connections=0`` as the fix. Nothing asserted it, so removing
    the line would have failed no test while restoring the 200/404/404 behaviour.

    The limit is not exposed on ``httpx.Client``; it lives on the transport's
    connection pool, so the private chain is the only way to observe it. If httpx
    relocates it this fails loudly, which is the right outcome for a claim this
    load-bearing.
    """
    client = _client()
    try:
        pool = client._http._transport._pool  # type: ignore[attr-defined]
        assert pool._max_keepalive_connections == 0
    finally:
        client.close()
