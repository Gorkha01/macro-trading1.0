"""Snapshot construction — the one place a ``MacroDataSnapshot`` is assembled.

AGENTS.md Section 5.2 + 5.3, Section 21.0, Section 21.1.

This module is the seam between the data layer and the models layer. Its whole
job is: *every model's input comes from here, and nothing enters a snapshot
without a registry-verified provenance.*

Design rules it enforces, and why
---------------------------------
**The registry is the only source of routing.** No provider, symbol, or
endpoint literal appears in this file. A series re-point after a source change
is a config edit, never a code change.

**An unverifiable series is omitted and flagged, never guessed.** Section 21.0
rule 1 makes live execution the test of a function; a series that cannot be
fetched is recorded in ``data_quality_flags`` as an explicit absence. Section
5.4's "flag, don't fix" then means the absence reaches
``compute_confidence()`` instead of being silently defaulted to zero — which
would look like a real observation of zero and quietly corrupt every model
downstream.

**One series failing does not kill the snapshot.** The alternative is that a
single transient FRED outage makes the entire thesis unbuildable. But a
partial snapshot must be *visibly* partial: every omission appends a flag, and
the returned report names which fields succeeded, so the caller can decide
whether the remainder is usable without inspecting the object by hand.
Graceful degradation with an audit trail, never silent degradation.

**The horizon is pinned once.** ``as_of`` is captured at the start, so a
snapshot assembled across several minutes of sequential HTTP calls is still a
single point-in-time object.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError
from macro_engine.data_layer.schemas import ObservationPoint, YieldCurveSnapshot
from macro_engine.data_layer.validation import (
    ValidationReport,
    attach_flags,
    validate_observations,
    validate_yield_curve,
)
from macro_engine.models.contracts import utc_now

if TYPE_CHECKING:
    from macro_engine.config import RegistrySeries
    from macro_engine.data_layer.schemas import MacroDataSnapshot

__all__ = ["SnapshotBuildReport", "build_snapshot", "fetch_curve", "fetch_field"]

logger = logging.getLogger(__name__)

# Curve-shaped fields, identified structurally (the entry declares `tenors`)
# rather than by name, so a new curve added to config needs no code change.
CURVE_FIELDS: frozenset[str] = frozenset({"yield_curve", "tips_yields"})


class SnapshotBuildReport:
    """What happened while assembling a snapshot.

    Returned alongside the snapshot so a caller can distinguish "the data is
    clean" from "the data is missing in five places", which the snapshot's own
    field contents cannot express on their own.
    """

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.succeeded: list[str] = []
        self.failed: dict[str, str] = {}
        self.skipped_unverified: list[str] = []
        self.observation_counts: dict[str, int] = {}

    @property
    def is_complete(self) -> bool:
        """True only when nothing was skipped and nothing failed."""
        return not self.failed and not self.skipped_unverified

    def as_flags(self) -> list[str]:
        """Render the report as ``data_quality_flags`` entries.

        These are distinct from validation findings: validation flags describe
        data that arrived and looked wrong, whereas these describe data that
        never arrived at all. Both matter, and conflating them would hide the
        difference between "bad number" and "no number".
        """
        flags: list[str] = []
        for field, reason in sorted(self.failed.items()):
            flags.append(f"FETCH_FAILED:{field}:{reason}")
        for field in sorted(self.skipped_unverified):
            flags.append(f"UNVERIFIED_SERIES_SKIPPED:{field}")
        for field in sorted(self.succeeded):
            if self.observation_counts.get(field, 0) == 0:
                flags.append(f"EMPTY_SERIES:{field}")
        return flags

    def summary(self) -> str:
        return (
            f"requested={len(self.requested)} succeeded={len(self.succeeded)} "
            f"failed={len(self.failed)} skipped_unverified={len(self.skipped_unverified)}"
        )


def _lookback_start() -> str:
    """Start date for the fetch window, from config — never an inline literal.

    A shared window across all series is deliberate: it keeps the snapshot's
    series mutually aligned in time. Series with shorter native history simply
    return what exists.
    """
    settings = get_settings()
    days = int(settings.data.lookback) * 365
    return (utc_now() - timedelta(days=days)).date().isoformat()


def resolve_snapshot_field(field_name: str, entry: RegistrySeries) -> str:
    """The ``MacroDataSnapshot`` attribute a registry entry populates.

    Registry keys and schema field names are not always identical — the key
    ``treasury_curve`` fills the schema's ``yield_curve``. Assuming they always
    matched silently discarded the entire Treasury curve on the first live
    build, so the mapping is now explicit (``snapshot_field``) with the key as
    the fallback.

    The fallback is what makes ``snapshot_field`` load-bearing rather than
    decorative, and it is also its one hazard: a registry entry that is NOT a
    snapshot field at all resolves to itself and then fails
    ``_assert_field_exists``. That is the intended outcome — a registry entry
    added for a model's own input provenance must declare that it is not part
    of the snapshot rather than being silently absorbed or silently ignored.
    """
    if entry.not_a_snapshot_field:
        raise OpenBBFetchError(
            f"registry entry '{field_name}' is declared "
            "`not_a_snapshot_field: true`, so it cannot be fetched into "
            "MacroDataSnapshot. It exists to document a model's input "
            "provenance. Use it directly in the model's live check, or remove "
            "the declaration if it genuinely should be part of the snapshot."
        )
    return entry.snapshot_field or field_name


def _assert_field_exists(field_name: str, target: str) -> None:
    """Fail loudly if the resolved target is not a real schema field.

    Without this, ``setattr`` on a Pydantic model with ``extra`` disallowed
    raises deep inside the loop and the reason is hard to see; with it, the
    registry and the schema are forced to agree at the point of use.
    """
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    if target not in MacroDataSnapshot.model_fields:
        raise OpenBBFetchError(
            f"registry field '{field_name}' resolves to snapshot attribute '{target}', "
            "which MacroDataSnapshot does not define. Fix `snapshot_field` in "
            "config/series_registry.yaml or add the field to the schema."
        )


def _points_from_frame(
    frame: pd.DataFrame, *, series_id: str, fallback_source: str
) -> list[ObservationPoint]:
    """Convert a normalized frame into ``ObservationPoint`` records."""
    points: list[ObservationPoint] = []
    for _, row in frame.iterrows():
        raw_date = row["date"]
        if isinstance(raw_date, pd.Timestamp):
            observation_date: date = raw_date.date()
        elif isinstance(raw_date, date):
            observation_date = raw_date
        else:
            observation_date = pd.Timestamp(raw_date).date()
        points.append(
            ObservationPoint(
                observation_date=observation_date,
                value=float(row["value"]),
                series_id=series_id,
                source=str(row.get("source", fallback_source) or fallback_source),
                retrieved_at=pd.Timestamp(row["retrieved_at"]).to_pydatetime(),
            )
        )
    return points


def fetch_field(
    client: OpenBBClient,
    field_name: str,
    entry: RegistrySeries,
    *,
    start: str | None = None,
) -> list[ObservationPoint]:
    """Fetch one scalar registry field and convert it to ``ObservationPoint``s.

    Raises ``OpenBBFetchError`` unchanged so the caller can record the failure
    per-field. It deliberately does not catch-and-return-empty, because an
    empty list is indistinguishable from a series that legitimately has no
    observations in the window — and that ambiguity is how a broken mapping
    masquerades as a quiet market.
    """
    if entry.endpoint is None:
        raise OpenBBFetchError(
            f"registry entry '{field_name}' has no endpoint configured; "
            "add one in config/series_registry.yaml"
        )
    if entry.symbol is None:
        raise OpenBBFetchError(
            f"registry entry '{field_name}' declares no symbol but is being fetched as a scalar"
        )

    frame = client.fetch_series(
        provider=entry.provider,
        endpoint=entry.endpoint,
        params={"symbol": entry.symbol, "start_date": start},
        series_label=field_name,
    )
    return _points_from_frame(
        frame, series_id=field_name, fallback_source=f"{entry.provider}:{entry.symbol}"
    )


def fetch_curve(
    client: OpenBBClient,
    field_name: str,
    entry: RegistrySeries,
    *,
    start: str | None = None,
) -> YieldCurveSnapshot:
    """Fetch every tenor of a curve and assemble a ``YieldCurveSnapshot``.

    A missing tenor raises rather than being interpolated: a curve built partly
    from invented points is not a curve, and every downstream slope/curvature
    read would inherit the invention silently. The caller records the failure
    for the whole curve, which is the honest outcome — a half-observed curve
    cannot support a 2s10s read in the first place.
    """
    if not entry.tenors:
        raise OpenBBFetchError(f"curve '{field_name}' declares no tenors")

    endpoint = entry.endpoint or "economy.fred_series"
    tenors: dict[str, float] = {}
    latest_date: date | None = None

    for tenor, symbol in entry.tenors.items():
        frame = client.fetch_series(
            provider=entry.provider,
            endpoint=endpoint,
            params={"symbol": symbol, "start_date": start},
            series_label=f"{field_name}.{tenor}",
        )
        if frame.empty:
            raise OpenBBFetchError(
                f"curve '{field_name}' tenor '{tenor}' (symbol {symbol}) returned no observations"
            )
        row = frame.iloc[-1]
        raw_date = row["date"]
        tenor_date = (
            raw_date.date() if isinstance(raw_date, pd.Timestamp) else pd.Timestamp(raw_date).date()
        )
        if latest_date is None or tenor_date > latest_date:
            latest_date = tenor_date
        tenors[tenor] = float(row["value"])

    return YieldCurveSnapshot(
        as_of=latest_date or utc_now().date(),
        tenors=tenors,
        retrieved_at=utc_now(),
    )


def _apply_validation(
    snapshot: MacroDataSnapshot,
    raw_by_field: dict[str, list[ObservationPoint]],
) -> MacroDataSnapshot:
    """Run per-series validation and return a snapshot carrying the findings.

    Bounds come from the registry's ``plausible_range`` where declared, so a
    new series is validated the moment it is registered rather than when
    someone remembers to add a rule here.
    """
    registry = get_registry()
    aggregate = ValidationReport()

    for field_name, points in raw_by_field.items():
        entry = registry.series.get(field_name)
        bounds = entry.plausible_range if entry is not None else None
        low, high = (float(bounds[0]), float(bounds[1])) if bounds else (None, None)
        aggregate.extend(
            validate_observations(
                points,
                series_id=field_name,
                min_value=low,
                max_value=high,
                required=True,
                # A projection series (CBO GDPPOT) legitimately extends beyond
                # today; marking it keeps ~41 valid points from being flagged
                # as ERROR and drowning the real diagnostics.
                forward_looking=bool(entry.forward_looking) if entry is not None else False,
                # A daily series the provider has already published for the
                # current calendar day while the clock is on the previous UTC
                # date (FRED IORB). A per-series property rather than a code
                # exception, so a series that should NOT lead still errors.
                future_date_tolerance_days=(
                    entry.future_date_tolerance_days if entry is not None else 0
                ),
            )
        )

    for curve_field in CURVE_FIELDS:
        curve = getattr(snapshot, curve_field, None)
        if curve is not None:
            aggregate.extend(validate_yield_curve(curve, series_id=curve_field))

    # attach_flags returns a COPY carrying the findings, because provenance is
    # immutable once built. Returning that copy IS the application of the flags
    # — and the caller must not append the findings a second time, which would
    # duplicate every validation flag on the snapshot.
    return attach_flags(snapshot, aggregate)


def build_snapshot(
    country: str = "us",
    *,
    client: OpenBBClient | None = None,
    fields: list[str] | None = None,
    persist: bool = False,
) -> tuple[MacroDataSnapshot, SnapshotBuildReport]:
    """Assemble a ``MacroDataSnapshot`` from registry-verified series.

    Parameters
    ----------
    country:
        Only ``"us"`` is implemented (Section 22.3). Anything else raises.
    client:
        Injected for testability. Defaults to a freshly constructed client.
    fields:
        Override the configured field list. Defaults to
        ``settings.snapshot_fields.{country}``.
    persist:
        Write the snapshot to the parquet audit trail (Section 5.5).

    Returns
    -------
    (snapshot, report)
        The report is not optional: a caller that ignores it cannot tell a
        complete snapshot from a half-empty one.
    """
    from macro_engine.data_layer import persistence as persistence_module
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    settings = get_settings()

    # Section 22.3: no function may claim country-genericity it has not earned.
    if country not in settings.country.implemented:
        raise NotImplementedError(
            f"country '{country}' is not implemented. Implemented: "
            f"{sorted(settings.country.implemented)} (Section 22.3)."
        )

    client = client if client is not None else OpenBBClient()
    requested = (
        list(fields) if fields is not None else list(settings.snapshot_fields.get(country, []))
    )
    if not requested:
        raise ValueError(
            f"no snapshot fields configured for country '{country}'. "
            "Set snapshot_fields.us in config/settings.yaml."
        )

    report = SnapshotBuildReport()
    report.requested = list(requested)

    start = _lookback_start()
    snapshot = MacroDataSnapshot(country=country, as_of=utc_now())
    raw_by_field: dict[str, list[ObservationPoint]] = {}

    for field_name in requested:
        entry = get_registry().series.get(field_name)
        if entry is None:
            report.failed[field_name] = "not_defined_in_registry"
            logger.error("snapshot field '%s' is not defined in the series registry", field_name)
            continue

        try:
            get_registry().require_verified(field_name)
        except NotImplementedError as exc:
            # Unverified / blocked: an explicit, reported absence — never a
            # silent substitution and never a guessed default.
            report.skipped_unverified.append(field_name)
            logger.warning("skipping unverified series '%s': %s", field_name, exc)
            continue

        try:
            target = resolve_snapshot_field(field_name, entry)
            _assert_field_exists(field_name, target)

            if field_name in CURVE_FIELDS or entry.tenors:
                curve = fetch_curve(client, field_name, entry, start=start)
                setattr(snapshot, target, curve)
                report.observation_counts[field_name] = len(curve.tenors)
            else:
                points = fetch_field(client, field_name, entry, start=start)
                setattr(snapshot, target, points)
                raw_by_field[target] = points
                report.observation_counts[field_name] = len(points)
                snapshot.field_sources[field_name] = f"{entry.provider}:{entry.symbol}"
            report.succeeded.append(field_name)
        except OpenBBFetchError as exc:
            report.failed[field_name] = str(exc)[:200]
            logger.error("failed to fetch '%s': %s", field_name, exc)
        except Exception as exc:
            report.failed[field_name] = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("unexpected error fetching '%s'", field_name)

    # Validation flags are already merged by _apply_validation (attach_flags
    # returns a copy); only the build-report flags remain to add. Appending
    # findings again here would double every validation flag.
    snapshot = _apply_validation(snapshot, raw_by_field)
    snapshot.data_quality_flags = [*snapshot.data_quality_flags, *report.as_flags()]

    if persist:
        persistence_module.write_snapshot(snapshot)

    logger.info("snapshot build complete: %s", report.summary())
    return snapshot, report
