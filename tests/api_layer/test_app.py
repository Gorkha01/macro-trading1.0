"""``api_layer/app.py`` — the factory, the router set, CORS and the lifespan.

MEASURED 2026-10-06: ``grep -rn "FastAPI\\|TestClient\\|create_app" tests/`` returned
**zero** matches — no test in the repository built an app at all, so neither the
router set nor the CORS pairing nor the lifespan was pinned. (The module's
``_lifespan`` docstring justified its own placement with '~20 tests that build an
app object and never serve it'; the real count was 0. See F-APP-002.)

Also pinned here: ``F-APP-001``, the docstring's router arithmetic.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.middleware.cors import CORSMiddleware

from macro_engine.api_layer import app as app_module

_EXPECTED_PATHS = {
    "/health",
    "/thesis/{country}",
    "/thesis/{country}/stream",
    "/query",
    "/dashboard_data",
}


def _paths(app: Any) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def _stub_settings(monkeypatch: pytest.MonkeyPatch, *, origins: list[str]) -> None:
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda *a, **k: SimpleNamespace(api=SimpleNamespace(cors_origins=origins)),
    )


# ---------------------------------------------------------------------------
# the router set
# ---------------------------------------------------------------------------


def test_the_app_exposes_every_endpoint_the_layer_defines() -> None:
    app = app_module.create_app()
    assert _paths(app) >= _EXPECTED_PATHS


def test_the_stream_router_is_mounted_under_the_thesis_prefix() -> None:
    """An endpoint not included is an endpoint that 404s (the module docstring's own point)."""
    app = app_module.create_app()
    assert "/thesis/{country}/stream" in _paths(app)


def test_the_version_comes_from_the_single_definition() -> None:
    """A version that disagrees between /health and /openapi.json is a version nobody trusts."""
    from macro_engine.api_layer import routes_health

    app = app_module.create_app()
    assert app.version == routes_health.SERVICE_VERSION


def test_the_router_arithmetic_the_docstring_states() -> None:
    """(F-APP-001) The §8.1 sample's four routers INCLUDE the query router.

    The docstring named both the streaming and the query router as additions and
    said neither appears in the sample — but the sample mounts ``routes_query``,
    and four plus two additions is six, not the five the app has. Measured against
    ``AGENTS.md`` §8.1.
    """
    source = Path(inspect.getfile(app_module)).read_text(encoding="utf-8")
    assert "the additions are the streaming router" not in source
    assert "IS one of the §8.1 four" in source
    # ...and the claim the docstring now makes is the true one:
    assert len([line for line in source.splitlines() if "include_router" in line]) == 5


# ---------------------------------------------------------------------------
# CORS: the pair, not the value
# ---------------------------------------------------------------------------


def test_cors_is_absent_when_no_origins_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-op middleware that rewrites every request's headers is pure surface area."""
    _stub_settings(monkeypatch, origins=[])
    app = app_module.create_app()
    assert not any(getattr(m, "cls", None) is CORSMiddleware for m in app.user_middleware)


def test_cors_is_attached_when_origins_are_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch, origins=["http://localhost:3000"])
    app = app_module.create_app()
    cors = [m for m in app.user_middleware if getattr(m, "cls", None) is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origins"] == ["http://localhost:3000"]
    # Section 8.4: no authentication, so credentials would be a cookie nothing checks.
    assert cors[0].kwargs["allow_credentials"] is False


# ---------------------------------------------------------------------------
# the lifespan
# ---------------------------------------------------------------------------


def test_the_lifespan_installs_the_logging_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Section 10.3's JSON logging is applied when the app is SERVED, not on import."""
    from fastapi.testclient import TestClient

    calls: list[int] = []
    monkeypatch.setattr(app_module, "configure_logging", lambda *a, **k: calls.append(1))

    app = app_module.create_app()
    assert calls == [], "importing/building must not touch the process's logging config"
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert calls == [1], "the lifespan must install it exactly once, when served"


def test_building_the_app_does_not_configure_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """``app = create_app()`` runs at IMPORT, so a construction side effect would be global."""
    calls: list[int] = []
    monkeypatch.setattr(app_module, "configure_logging", lambda *a, **k: calls.append(1))
    app_module.create_app()
    app_module.create_app()
    assert calls == []


def test_the_lifespan_note_does_not_claim_a_test_count() -> None:
    """(F-APP-002) It justified the placement with a count of app-building tests.

    MEASURED 2026-10-06: ``grep -rn "FastAPI\\|TestClient\\|create_app" tests/`` matched
    nothing, so the real count was zero — and the hazard it was standing in for is
    import-time, not test-time.
    """
    source = Path(inspect.getfile(app_module)).read_text(encoding="utf-8")
    assert "~20 tests" not in source
    assert "the real count was zero" in source
