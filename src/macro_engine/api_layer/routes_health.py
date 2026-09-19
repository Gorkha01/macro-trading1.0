"""``/health`` — liveness, and the honest version of it (Section 8.2, D-070).

Section 8.2's sample returns ``{"status": "ok", ...}`` unconditionally. That is a
*process* check: it answers "is this program running", which is never the
question a caller has. The question is "can this service produce a thesis", and
the things that stop it are all upstream — an unreachable OpenBB provider, an
unverified series, a missing config file.

So this endpoint reports both, and keeps them **distinguishable**:

============  ====================================================================
``status``    ``"ok"`` always, when the process is up. Liveness.
``ready``     whether a snapshot is available right now — and the app is honest
              about the cost of asking, which is why it is not free.
============  ====================================================================

``ready`` is checked **without building a snapshot**. Building takes 9.5s
in-process and 223.6s over the local OpenBB API (measured, and recorded in
``config/settings.yaml``), so a health check that built one would be a health
check that takes four minutes and is load-bearing on the provider it is supposed
to be diagnosing. Instead it reports:

* whether a snapshot is already cached, and how old it is,
* and — when none is — that it *can* be built, without doing it.

A caller that wants the expensive answer asks ``?deep=true``, which runs the
build. That splits the two questions a health check is asked ("are you up" and
"can you actually work") into two calls with two costs, rather than guessing
which one the caller wanted and being wrong slowly.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings

router = APIRouter(tags=["health"])

#: The version string Section 8.1 puts on the app. A module constant rather than
#: a literal in two places (the app factory reads it too), because a version that
#: disagrees between ``/health`` and ``/openapi.json`` is a version nobody trusts.
SERVICE_NAME = "macro-reasoning-engine"
SERVICE_VERSION = "1.0.0"


class HealthResponse(BaseModel):
    """Liveness, readiness, and the security posture the caller is talking to."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description='Always "ok" when the process is up.')
    service: str
    version: str
    ready: bool = Field(
        description=(
            "Whether a snapshot is available to build a thesis from. False does NOT "
            "mean the service is broken — it means no snapshot is cached yet, which "
            "is the normal state after a restart."
        )
    )
    ready_reason: str
    cached_snapshot: bool
    cached_age_hours: float | None = None
    cached_is_stale: bool | None = None
    country: str
    loopback_only: bool = Field(
        description=(
            "Section 8.4's safety property, exposed rather than inferred from the "
            "host string. False means the service is reachable off this machine, "
            "and there is no authentication anywhere — so the bind address is the "
            "access control."
        )
    )
    implemented_countries: list[str]
    deep_check: bool


@router.get("/health", response_model=HealthResponse)
async def health(
    deep: bool = Query(
        default=False,
        description=(
            "Run a real snapshot build to prove the data path works. Costs ~10s "
            "in-process or ~220s over the local OpenBB API (measured), so it is "
            "opt-in rather than the default."
        ),
    ),
) -> HealthResponse:
    """Report liveness, and readiness as cheaply as the question allows."""
    settings = get_settings()

    if not deep:
        # The cheap path still reports what it CAN know for free: whether a
        # snapshot is sitting in the cache, and how old it is. Answering with a
        # bare "ok" while a stale snapshot is cached would be the shallowest
        # possible version of this endpoint — and the caller's next call IS the
        # thesis endpoint, which would serve that snapshot.
        from macro_engine.api_layer.snapshot_provider import cached_snapshot_provenance

        cached = cached_snapshot_provenance("us")
        if cached is None:
            ready_reason = (
                "the service is up and the thesis path is routable, but no snapshot "
                "is cached yet — the first /thesis call will build one (~10s "
                "in-process or ~220s over the local OpenBB API, measured)"
            )
        elif cached.age_exceeds_max:
            ready_reason = (
                f"a cached snapshot exists but is {cached.age_hours:.1f}h old, beyond "
                f"the configured {cached.max_age_hours:.1f}h limit; it will be served "
                f"with a STALE disclosure"
            )
        else:
            ready_reason = f"a cached snapshot is available, {cached.age_hours:.1f}h old"
        return HealthResponse(
            status="ok",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            ready=True,
            ready_reason=ready_reason,
            cached_snapshot=cached is not None,
            cached_age_hours=cached.age_hours if cached else None,
            cached_is_stale=cached.age_exceeds_max if cached else None,
            country="us",
            loopback_only=settings.api.loopback_only,
            implemented_countries=list(settings.country.implemented),
            deep_check=False,
        )

    # The deep path. Imported here so that the shallow path — the one a
    # supervisor polls — cannot be broken by a data-layer import fault.
    from macro_engine.api_layer.snapshot_provider import SnapshotUnavailableError, get_snapshot

    try:
        _snapshot, provenance = get_snapshot("us", force_refresh=True)
    except SnapshotUnavailableError as exc:
        return HealthResponse(
            status="degraded",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            ready=False,
            ready_reason=f"the data path is not working: {exc}",
            cached_snapshot=False,
            country="us",
            loopback_only=settings.api.loopback_only,
            implemented_countries=list(settings.country.implemented),
            deep_check=True,
        )

    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        ready=True,
        ready_reason=(
            f"a snapshot built successfully in {provenance.build_seconds:.1f}s: "
            f"{len(provenance.succeeded_fields)} field(s) fetched, "
            f"{len(provenance.failed_fields)} failed"
        ),
        cached_snapshot=True,
        cached_age_hours=provenance.age_hours,
        cached_is_stale=provenance.age_exceeds_max,
        country="us",
        loopback_only=settings.api.loopback_only,
        implemented_countries=list(settings.country.implemented),
        deep_check=True,
    )
