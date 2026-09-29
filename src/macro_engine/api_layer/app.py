"""The FastAPI application factory (Section 8.1, D-070).

The spec's sample, and the two changes it needs
-----------------------------------------------
Section 8.1's ``create_app()`` includes four routers. The shipped one includes
five — the additions are the streaming router from §8.3 and the query router,
both of which the spec defines in its own sections and neither of which appears
in the §8.1 sample. (The query router IS in the §8.1 import list; the streaming
router is not. So the sample silently omits §8.3's endpoint from the app it
builds, which is not a stylistic omission — an endpoint not included is an
endpoint that 404s.)

The second change is CORS, and it is not cosmetic
------------------------------------------------
§8.4 says "``CORSMiddleware`` configured permissively for local Workspace
connection only". Those two clauses are a **pair**: permissive origins are safe
*because* the bind is loopback-only, and neither is safe alone. The middleware
here is configured from ``settings.api.cors_origins``, and ``ApiSettings``
refuses to load a permissive origin list alongside a non-loopback host — so the
pair cannot be broken by editing one config value and forgetting the other.

CORS is attached **only when it is needed**. A loopback-only service with the
same origin list Starlette's default middleware would add is a no-op, and a no-op
middleware that rewrites every request's headers is pure surface area. When
origins are configured it is applied; the validator above guarantees that case
implies a loopback bind.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from macro_engine.api_layer import (
    reasoning_stream,
    routes_dashboard,
    routes_health,
    routes_query,
    routes_thesis,
)
from macro_engine.config import get_settings
from macro_engine.data_layer.logging_json import configure_logging

__all__ = ["create_app"]


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Apply the configured logging tree once, when the service starts.

    Section 10.3 mandates structured JSON logging, and ``config/logging.yaml``
    implements it — but measured 2026-09-29 the mandate was **declared and not in
    effect**: ``configure_logging()`` (the only function that applies the YAML)
    had **zero callers** anywhere in the repo, uvicorn was not started with
    ``--log-config``, and this module had no startup hook, so the JSON formatter
    never ran. A structured-logging spec whose formatter is never installed is a
    spec that produces unstructured logs during exactly the incident it was
    written for.

    It is called in the **lifespan** rather than at ``create_app()`` time on
    purpose: ``create_app`` is called by ~20 tests that build an app object and
    never serve it, and applying a process-global logging config as a side effect
    of construction would mutate the test process's root logger. The lifespan
    runs only when the app is actually served (uvicorn, or ``TestClient`` used as
    a context manager), which is the moment the config is meant to take effect.

    A missing/invalid ``config/logging.yaml`` raises here (``configure_logging``
    refuses rather than falling back to ``basicConfig``) — startup fails loudly
    rather than serving with untrustworthy logs.
    """
    configure_logging()
    yield


def create_app() -> FastAPI:
    """Build the application. Called once at import time, and by tests.

    A factory rather than a module-level ``app`` alone, so a test can build an
    app **after** overriding config and have the CORS middleware and router set
    reflect the override. A singleton built at import would freeze whatever the
    first import saw, and a config test against it would pass or fail depending
    on test order.
    """
    settings = get_settings()

    app = FastAPI(
        title="Macro Reasoning Engine",
        version=routes_health.SERVICE_VERSION,
        description=(
            "Institutional macro thesis synthesis backend — see MODULE_MAPPING.md. "
            "US-only through Phase 4 (Section 22.3). This service produces a "
            "MacroThesis; it does not place orders and it does not manage positions."
        ),
        lifespan=_lifespan,
    )

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    app.include_router(routes_health.router)
    app.include_router(routes_thesis.router, prefix="/thesis")
    app.include_router(reasoning_stream.router, prefix="/thesis")
    app.include_router(routes_query.router)
    app.include_router(routes_dashboard.router)

    return app


#: The module-level app, for ``uvicorn macro_engine.api_layer.app:app``.
#:
#: ``allow_credentials`` is False and stays False. The service has no
#: authentication (§8.4), so credentials would be a cookie the browser sends and
#: nothing checks — and Starlette rejects ``allow_origins=["*"]`` combined with
#: credentials anyway, which would turn a config mistake into a startup failure
#: far from its cause.
app = create_app()
