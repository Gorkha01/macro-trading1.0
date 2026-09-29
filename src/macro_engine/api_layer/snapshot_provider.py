"""Where a snapshot comes from, and how old it is allowed to be (D-070).

The one decision this module makes
----------------------------------
Section 8.2's sample calls ``fetch_full_snapshot(client, country)`` inside the
request handler. Measured: that function does not exist anywhere in the tree, and
the real entry point is ``build_snapshot(country=..., client=..., fields=...,
persist=...)`` returning ``(snapshot, report)`` — with the report deliberately
**not optional**, because "a caller that ignores it cannot tell a complete
snapshot from a half-empty one" (its own docstring).

More importantly, a build is *slow*. Measured and recorded in
``config/settings.yaml``: a first build is **~46-81s** (cold start dominates)
and a subsequent one **~4s** — so a build time quoted without its thermal state
is ambiguous rather than merely imprecise (D-087.19). A Workspace UI polls; a
request-per-build endpoint would make the thesis unreachable in practice, and the
temptation would then be to cache it *silently*.

So this module caches **and says so**. Every response carries a
``SnapshotProvenance`` naming:

* whether the snapshot was freshly built or reused,
* its ``as_of`` and how old that is,
* whether that age exceeds ``api.snapshot_max_age_hours``,
* the build report's outcome — requested, succeeded, failed, skipped,
* the snapshot's own ``data_quality_flags`` count.

The rule this enforces is the D-069 lesson in the cache position: **a cached
answer with no age attached is a claim about the present made from the past.**
A caller that cannot see the age cannot decide whether to trust it, and the
failure is invisible because the payload is byte-identical either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.data_layer.schemas import MacroDataSnapshot
from macro_engine.models.contracts import utc_now

__all__ = [
    "SnapshotProvenance",
    "SnapshotUnavailableError",
    "cached_snapshot_provenance",
    "get_snapshot",
    "reset_cache",
]


class SnapshotUnavailableError(RuntimeError):
    """A snapshot could not be produced, and the reason is not this code's fault.

    The API maps this to **502**. The distinction from ``OrchestrationError``
    (also 502, but a different remedy) is in the message: this one means the
    *source* did not answer, and the caller's action is to retry or inspect the
    provider. ``OrchestrationError`` means the source answered but the data was
    unusable, and the action is to inspect the series.

    Both are 502 rather than 500 because neither is a bug here — and neither is
    ever mapped onto a ``WATCH`` thesis, which Section 16.3 forbids: a stand-down
    says "the models agree there is no edge", not "we could not read the inputs".
    """


class SnapshotProvenance(BaseModel):
    """What the caller is entitled to know about the snapshot it was served.

    Carried on every response rather than logged, because the two failure modes
    it prevents are both silent:

    * **Stale served as fresh.** A snapshot built at 09:00 and served at 09:00
      tomorrow is a thesis about yesterday. ``age_hours`` /
      ``age_exceeds_max`` make that visible.
    * **Partial served as complete.** A build that failed four of seventeen
      series still returns a snapshot whose empty fields look like zeros to a
      reader who never sees the report. ``failed_fields`` is that report.
    """

    model_config = ConfigDict(extra="forbid")

    country: str
    as_of: datetime = Field(description="The snapshot's own timestamp, not the response's.")
    generated_at: datetime
    age_hours: float = Field(ge=0.0, description="How old ``as_of`` was when served.")
    age_exceeds_max: bool = Field(
        description="True when age_hours > api.snapshot_max_age_hours — reported, not refused."
    )
    max_age_hours: float
    from_cache: bool = Field(description="False on a fresh build.")
    requested_fields: list[str] = Field(default_factory=list)
    succeeded_fields: list[str] = Field(default_factory=list)
    failed_fields: dict[str, str] = Field(
        default_factory=dict,
        description="field -> reason. Non-empty means a partial snapshot, not an error.",
    )
    skipped_unverified_fields: list[str] = Field(default_factory=list)
    data_quality_flag_count: int = Field(ge=0)
    build_seconds: float | None = Field(
        default=None,
        description="Wall time of the build that produced this snapshot, when one was run.",
    )

    def warnings(self) -> list[str]:
        """The disclosure lines a consumer should surface, in severity order.

        Returned as a method rather than pre-rendered strings so a caller that
        wants only the stale condition can ask for it, and so the wording lives
        beside the fields it is about.
        """
        messages: list[str] = []
        if self.failed_fields:
            messages.append(
                f"SNAPSHOT PARTIAL: {len(self.failed_fields)} of "
                f"{len(self.requested_fields)} field(s) failed to fetch "
                f"({sorted(self.failed_fields)}). Absent series are not zeros "
                f"(Section 21.4); a model reading one of them refused rather than "
                f"substituting."
            )
        if self.skipped_unverified_fields:
            messages.append(
                f"SNAPSHOT SKIPPED: {len(self.skipped_unverified_fields)} field(s) "
                f"are not registry-verified ({sorted(self.skipped_unverified_fields)}) "
                f"and were not fetched."
            )
        if self.age_exceeds_max:
            messages.append(
                f"SNAPSHOT STALE: as_of {self.as_of.isoformat()} is "
                f"{self.age_hours:.1f}h old, beyond the configured "
                f"{self.max_age_hours:.1f}h limit. The thesis describes the world as "
                f"of that timestamp, not now."
            )
        if self.data_quality_flag_count:
            messages.append(
                f"SNAPSHOT FLAGGED: {self.data_quality_flag_count} data-quality "
                f"flag(s) on the snapshot. NOTE: these flags are NOT applied as a "
                f"confidence penalty automatically — compute_confidence() reads each "
                f"model's OWN data_quality_flags_present input, which no model "
                f"populates from this snapshot-level list (Section 5.4 / 22.8). A "
                f"consumer that must degrade confidence on a flagged snapshot has to "
                f"do so explicitly."
            )
        if self.from_cache:
            messages.append(
                f"SNAPSHOT REUSED: built {self.age_hours:.1f}h ago and served from "
                f"cache (api.memoize_snapshots). Attached because a cached answer "
                f"without its age is indistinguishable from a fresh one."
            )
        return messages


@dataclass
class _CacheEntry:
    snapshot: MacroDataSnapshot
    provenance: SnapshotProvenance


# Module-level because the service is a single process by design (Section 8.4:
# loopback-only, no auth, one local Workspace consumer). A multi-worker
# deployment would give each worker its own cache — which is a *performance*
# difference, not a correctness one, since every entry is self-describing via
# its provenance. That property is deliberate: it means scaling out cannot make
# a stale snapshot look fresh.
_CACHE: dict[str, _CacheEntry] = {}


def reset_cache() -> None:
    """Drop every cached snapshot. Exists so tests are order-independent."""
    _CACHE.clear()


def cached_snapshot_provenance(country: str = "us") -> SnapshotProvenance | None:
    """The provenance of a cached snapshot, re-aged to *now*, or ``None``.

    Exists so ``/health`` can answer "is anything cached, and is it stale"
    **without building**. The re-aging is the same correction ``get_snapshot``
    makes: the stored provenance describes the build, and a served provenance
    must describe the serving. Returning the stored object would report a
    day-old snapshot as zero hours old, because it was zero hours old when it
    was written.
    """
    entry = _CACHE.get(country)
    if entry is None:
        return None
    now = utc_now()
    settings = get_settings()
    age = _age_hours(entry.snapshot.as_of, now)
    return entry.provenance.model_copy(
        update={
            "generated_at": now,
            "age_hours": age,
            "age_exceeds_max": age > settings.api.snapshot_max_age_hours,
            "from_cache": True,
        }
    )


def _provenance_from_report(
    snapshot: MacroDataSnapshot,
    *,
    report: object,
    from_cache: bool,
    build_seconds: float | None,
    generated_at: datetime,
) -> SnapshotProvenance:
    """Build the provenance from a ``SnapshotBuildReport`` without importing it.

    The report is read **duck-typed** (``getattr`` with defaults) rather than
    imported and typed, for one reason: this module must stay usable when only a
    persisted frame is available, where there is no report at all. Importing the
    class would make the report a requirement of every path, and the path that
    has none would have to invent an empty one — which reads as "nothing failed",
    the opposite of the truth.
    """
    settings = get_settings()
    age = _age_hours(snapshot.as_of, generated_at)
    max_age = settings.api.snapshot_max_age_hours
    requested = list(getattr(report, "requested", []) or [])
    succeeded = list(getattr(report, "succeeded", []) or [])
    failed = dict(getattr(report, "failed", {}) or {})
    skipped = list(getattr(report, "skipped_unverified", []) or [])
    return SnapshotProvenance(
        country=snapshot.country,
        as_of=snapshot.as_of,
        generated_at=generated_at,
        age_hours=age,
        age_exceeds_max=age > max_age,
        max_age_hours=max_age,
        from_cache=from_cache,
        requested_fields=requested,
        succeeded_fields=succeeded,
        failed_fields=failed,
        skipped_unverified_fields=skipped,
        data_quality_flag_count=len(snapshot.data_quality_flags),
        build_seconds=build_seconds,
    )


def _age_hours(as_of: datetime, now: datetime) -> float:
    """Hours between the snapshot's timestamp and now, floored at zero.

    Floored because a clock skew that puts ``as_of`` slightly ahead of ``now``
    would otherwise produce a negative age, and a negative age silently passes
    any ``age > max_age`` check — the exact comparison the staleness disclosure
    is built on.
    """
    as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    now_utc = now if now.tzinfo else now.replace(tzinfo=UTC)
    seconds = (now_utc - as_of_utc).total_seconds()
    return max(0.0, seconds / 3600.0)


def get_snapshot(
    country: str = "us",
    *,
    force_refresh: bool = False,
) -> tuple[MacroDataSnapshot, SnapshotProvenance]:
    """Return a snapshot and its provenance, building one only if needed.

    Parameters
    ----------
    country:
        Only ``"us"`` is implemented (Section 22.3); ``build_snapshot`` raises
        for anything else, and that ``NotImplementedError`` is deliberately not
        caught here so the API can map it to 501 rather than 502.
    force_refresh:
        Bypass the cache. The API exposes this so an operator can demand a fresh
        read after fixing a provider, without restarting the service.

    Returns
    -------
    (snapshot, provenance)
        The provenance is **not optional** — the same contract
        ``build_snapshot`` makes about its report, and for the same reason.

    Raises
    ------
    SnapshotUnavailableError
        The build ran and did not produce a usable snapshot, or no snapshot could
        be loaded and building is what failed. Never returns a partially-empty
        snapshot dressed as a complete one: the provenance carries the partial
        state, and only a *wholly* failed build raises.

    Notes
    -----
    A **partial** build does not raise. That is deliberate and it is the same
    judgement ``output_gap_from_snapshot`` makes: a snapshot missing four series
    is still a real snapshot, and the orchestration will refuse at the specific
    field it needs. Raising here would replace a precise refusal ("``pce_core`` is
    empty") with a vague one ("the snapshot is unavailable"), which is worse for
    the caller and hides which series the provider is failing on.
    """
    settings = get_settings()
    now = utc_now()

    if settings.api.memoize_snapshots and not force_refresh:
        cached = _CACHE.get(country)
        if cached is not None:
            # Re-stamp the age: the entry was built once, but every response must
            # describe how old it was *when served*. Reusing the original
            # provenance would freeze the age at the moment of the build and make
            # an hours-old snapshot report zero age forever.
            refreshed = cached.provenance.model_copy(
                update={
                    "generated_at": now,
                    "age_hours": _age_hours(cached.snapshot.as_of, now),
                    "age_exceeds_max": _age_hours(cached.snapshot.as_of, now)
                    > settings.api.snapshot_max_age_hours,
                    "from_cache": True,
                }
            )
            return cached.snapshot, refreshed

    snapshot, provenance = _build(country=country, now=now)
    if settings.api.memoize_snapshots:
        _CACHE[country] = _CacheEntry(snapshot=snapshot, provenance=provenance)
    return snapshot, provenance


def _build(
    *,
    country: str,
    now: datetime,
) -> tuple[MacroDataSnapshot, SnapshotProvenance]:
    """Run the real build and translate its failures.

    Imported inside the function so that importing this module — which every
    router does at startup — does not drag the OpenBB client in. That keeps the
    app importable (and therefore the ``/health`` endpoint answerable) even when
    the data layer's optional dependencies are missing, which is exactly the
    situation a health check exists to report.
    """
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    started = utc_now()
    try:
        snapshot, report = build_snapshot(country=country)
    except NotImplementedError:
        # Section 22.3: a country-label failure is the caller's, and the API
        # maps it to 501. Re-raised untouched rather than wrapped, so the type
        # survives to the handler.
        raise
    except Exception as exc:
        raise SnapshotUnavailableError(
            f"the snapshot build for country '{country}' failed: {type(exc).__name__}: "
            f"{exc}. This is a data-source failure, not a thesis outcome — "
            f"Section 16.3 forbids reporting it as a no-trade."
        ) from exc

    elapsed = (utc_now() - started).total_seconds()

    # A build that produced nothing at all is unavailable. A build that
    # produced *some* fields is partial, and the provenance says so.
    requested = list(getattr(report, "requested", []) or [])
    succeeded = list(getattr(report, "succeeded", []) or [])
    if requested and not succeeded:
        failed = dict(getattr(report, "failed", {}) or {})
        raise SnapshotUnavailableError(
            f"the snapshot build for country '{country}' fetched no usable series: "
            f"{len(failed)} field(s) failed ({sorted(failed)}). Nothing downstream "
            f"can be computed from an empty snapshot."
        )

    provenance = _provenance_from_report(
        snapshot,
        report=report,
        from_cache=False,
        build_seconds=elapsed,
        generated_at=now,
    )
    return snapshot, provenance
