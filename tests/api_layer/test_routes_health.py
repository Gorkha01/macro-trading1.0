"""``api_layer/routes_health.py`` — the liveness/readiness split, and two live defects.

The endpoint had no test file. Its module docstring states a deliberate split —
``status`` is LIVENESS ("always ok when the process is up"), ``ready`` is
readiness ("whether a snapshot is available right now") — and neither half was
pinned by a test, which is how both drifted.

Live defects found BY this review:

* ``F-HLT-001`` — the deep path returned ``status="degraded"``, a third value the
  table and the field description both deny.
* ``F-HLT-002`` — the shallow path returned ``ready=True`` unconditionally, so the
  only ``False`` a caller could ever see was the one cause the field description
  says it does *not* mean.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from macro_engine.api_layer import routes_health as rh
from macro_engine.api_layer.snapshot_provider import (
    SnapshotProvenance,
    SnapshotUnavailableError,
)

AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


def _provenance(*, age_hours: float = 0.5, exceeds: bool = False) -> SnapshotProvenance:
    return SnapshotProvenance(
        country="us",
        as_of=AS_OF,
        generated_at=AS_OF,
        age_hours=age_hours,
        age_exceeds_max=exceeds,
        max_age_hours=24.0,
        from_cache=True,
        requested_fields=["a", "b"],
        succeeded_fields=["a", "b"],
        failed_fields={},
        data_quality_flag_count=0,
        build_seconds=4.0,
    )


def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rh,
        "get_settings",
        lambda *a, **k: SimpleNamespace(
            api=SimpleNamespace(loopback_only=True),
            country=SimpleNamespace(implemented=["us"]),
        ),
    )


def _stub_cached(monkeypatch: pytest.MonkeyPatch, value: SnapshotProvenance | None) -> list[str]:
    calls: list[str] = []

    def fake(country: str = "us") -> SnapshotProvenance | None:
        calls.append(country)
        return value

    monkeypatch.setattr("macro_engine.api_layer.snapshot_provider.cached_snapshot_provenance", fake)
    return calls


# ---------------------------------------------------------------------------
# (F-HLT-002) ready means "a snapshot is available right now"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_cached_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """(F-HLT-002) The table defines `ready` as "available right now".

    MEASURED 2026-10-06: this path returned ``ready=True`` while its own reason
    said "no snapshot is cached yet", so the field's description ("False … means
    no snapshot is cached yet, which is the normal state after a restart")
    described a state the code could not produce.
    """
    _stub_settings(monkeypatch)
    _stub_cached(monkeypatch, None)
    response = await rh.health(False)
    assert response.ready is False
    assert response.cached_snapshot is False
    assert response.cached_age_hours is None
    assert response.cached_is_stale is None
    assert "no snapshot is cached yet" in response.ready_reason
    # Liveness is untouched: the process answered.
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_a_fresh_cached_snapshot_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch)
    _stub_cached(monkeypatch, _provenance(age_hours=0.5))
    response = await rh.health(False)
    assert response.ready is True
    assert response.cached_snapshot is True
    assert response.cached_age_hours == pytest.approx(0.5)
    assert response.cached_is_stale is False
    assert "a cached snapshot is available" in response.ready_reason


@pytest.mark.asyncio
async def test_a_stale_cached_snapshot_is_ready_and_says_it_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ready-but-stale is its own state: the thesis will be served WITH a disclosure."""
    _stub_settings(monkeypatch)
    _stub_cached(monkeypatch, _provenance(age_hours=30.0, exceeds=True))
    response = await rh.health(False)
    assert response.ready is True
    assert response.cached_is_stale is True
    assert "STALE disclosure" in response.ready_reason


@pytest.mark.asyncio
async def test_the_cheap_path_never_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A health check that built a snapshot would be load-bearing on the provider."""
    _stub_settings(monkeypatch)
    calls = _stub_cached(monkeypatch, None)

    def boom(*a: Any, **k: Any) -> object:
        raise AssertionError("the shallow path must not build a snapshot")

    monkeypatch.setattr("macro_engine.api_layer.snapshot_provider.get_snapshot", boom)
    response = await rh.health(False)
    assert calls == ["us"]
    assert response.deep_check is False


# ---------------------------------------------------------------------------
# (F-HLT-001) the deep path keeps the split
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_deep_build_is_not_ready_but_still_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-HLT-001) ``status`` is LIVENESS; the diagnosis belongs in ``ready_reason``.

    MEASURED 2026-10-06: this path returned ``status="degraded"``, which both the
    table ("'ok' always, when the process is up") and the field description
    ("Always 'ok' when the process is up") deny — so a supervisor keying on
    ``status`` would have restarted a healthy process over a data problem.
    """
    _stub_settings(monkeypatch)

    def boom(country: str, force_refresh: bool = False) -> object:
        raise SnapshotUnavailableError("no source answered")

    monkeypatch.setattr("macro_engine.api_layer.snapshot_provider.get_snapshot", boom)
    response = await rh.health(True)
    assert response.status == "ok"
    assert response.ready is False
    assert response.deep_check is True
    assert "the data path is not working" in response.ready_reason


@pytest.mark.asyncio
async def test_the_deep_path_forces_a_refresh_and_reports_the_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_settings(monkeypatch)
    seen: list[tuple[str, bool]] = []

    def fake(country: str, force_refresh: bool = False) -> tuple[object, SnapshotProvenance]:
        seen.append((country, force_refresh))
        return object(), _provenance(age_hours=0.0)

    monkeypatch.setattr("macro_engine.api_layer.snapshot_provider.get_snapshot", fake)
    response = await rh.health(True)
    assert seen == [("us", True)], "a deep check must not be served from the cache"
    assert response.status == "ok"
    assert response.ready is True
    assert "built successfully in 4.0s" in response.ready_reason
    assert "2 field(s) fetched, 0 failed" in response.ready_reason


# ---------------------------------------------------------------------------
# the posture fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_security_posture_is_reported_not_inferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 8.4: there is no auth, so the bind address IS the access control."""
    _stub_settings(monkeypatch)
    _stub_cached(monkeypatch, None)
    response = await rh.health(False)
    assert response.loopback_only is True
    assert response.implemented_countries == ["us"]
    assert response.service == rh.SERVICE_NAME
    assert response.version == rh.SERVICE_VERSION


def test_the_service_identity_is_a_single_definition() -> None:
    """A version that disagrees between /health and /openapi.json is a version nobody trusts."""
    assert rh.SERVICE_NAME == "macro-reasoning-engine"
    assert rh.SERVICE_VERSION == "1.0.0"
