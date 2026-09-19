"""Point-in-time persistence (AGENTS.md Section 5.5).

Phase 1 writes every ``MacroDataSnapshot`` to
``data/raw/{country}/{timestamp}.parquet`` — a basic audit trail with zero new
infrastructure. ``extensions/duckdb_store.py`` is the Phase 5+ upgrade path and
reuses the exact same files.

Two things this layer is careful about:

1. **Vintage storage is a prerequisite, not a nicety.** Section 21.1 notes that
   ``prior_month_revision`` / ``two_months_ago_revision`` are DERIVED and
   require vintage storage — "compute from the difference between the
   currently-published value and what was published previously". Before enough
   history accumulates, revision reads must return ``None``, never zero. This
   module is what makes that history exist.

2. **The file name is the retrieval timestamp.** Snapshots are keyed by when
   they were *retrieved*, not by the economic data date, because two snapshots
   one hour apart can carry different vintages of the same observation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from macro_engine.config import get_settings, project_root
from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)

__all__ = [
    "CURVE_SERIES_FIELDS",
    "MAPPING_SERIES_FIELDS",
    "SCALAR_SERIES_FIELDS",
    "load_latest_snapshot_frame",
    "load_snapshot",
    "long_frame_from_snapshot",
    "parquet_path_for",
    "snapshot_from_long_frame",
    "write_snapshot",
]

logger = logging.getLogger(__name__)

# Scalar (single-symbol) series carried in MacroDataSnapshot. Declared ONCE and
# consumed by both the write and read paths: previously these were two parallel
# literal tuples, which meant adding a field to one and forgetting the other
# would have silently dropped it from every persisted snapshot — a data-loss bug
# with no error message. The test suite asserts this list matches the schema.
SCALAR_SERIES_FIELDS: tuple[str, ...] = (
    "gdp_real",
    "gdp_nominal",
    "gdi",
    "gdp_potential",
    "cpi_headline",
    "cpi_core",
    "pce_core",
    "ppi",
    "unemployment_rate",
    "initial_claims",
    "continuing_claims",
    "jolts_openings",
    "jolts_quits",
    "fed_funds_rate",
    "sofr",
    "iorb",
    "on_rrp_rate",
    "on_rrp_volume_bn",
    "credit_spread_hy",
    "credit_spread_ig",
)

# Curve-shaped series: stored with field == curve name and the tenor in series_id.
CURVE_SERIES_FIELDS: tuple[str, ...] = ("yield_curve", "tips_yields")

# Keyed mappings: stored with field == f"{name}.{symbol}".
MAPPING_SERIES_FIELDS: tuple[str, ...] = ("fx_spot", "commodity_spot", "equity_index")

# Long-format schema. One row per (series, date) observation, plus snapshot-level
# columns denormalized onto every row so a single file is self-describing.
_LONG_COLUMNS: tuple[str, ...] = (
    "country",
    "snapshot_as_of",
    "field",
    "series_id",
    "observation_date",
    "value",
    "source",
    "retrieved_at",
)


def _raw_root(country: str) -> Path:
    settings = get_settings()
    root = project_root() / str(settings.data.raw_store_path) / country
    root.mkdir(parents=True, exist_ok=True)
    return root


def parquet_path_for(snapshot: MacroDataSnapshot) -> Path:
    """Destination path for a snapshot's Parquet file.

    The timestamp is compacted to ``YYYYMMDDTHHMMSSZ`` so the lexicographic
    order of the filenames matches chronological order — which is what makes a
    glob-and-sort the correct "give me the latest" implementation, and what
    DuckDB will later rely on without a metadata table.
    """
    stamp = snapshot.as_of
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    stamp = stamp.astimezone(UTC)
    token = stamp.strftime("%Y%m%dT%H%M%SZ")
    return _raw_root(snapshot.country) / f"{token}.parquet"


def _iter_series(snapshot: MacroDataSnapshot) -> list[tuple[str, list[ObservationPoint]]]:
    """Flatten a snapshot into ``(field_name, points)`` pairs.

    Covers the scalar series, the curve snapshots, and the keyed mappings so
    that nothing is silently left out of the audit trail.
    """
    pairs: list[tuple[str, list[ObservationPoint]]] = []

    for name in SCALAR_SERIES_FIELDS:
        points = getattr(snapshot, name)
        if points:
            pairs.append((name, points))

    for curve_field in CURVE_SERIES_FIELDS:
        curve = getattr(snapshot, curve_field)
        if curve is None:
            continue
        pairs.append(
            (
                curve_field,
                [
                    ObservationPoint(
                        observation_date=curve.as_of,
                        value=value,
                        series_id=f"{curve_field}.{tenor}",
                        source="openbb",
                        retrieved_at=curve.retrieved_at,
                    )
                    for tenor, value in curve.tenors.items()
                ],
            )
        )

    for mapping_field in MAPPING_SERIES_FIELDS:
        mapping = getattr(snapshot, mapping_field)
        for symbol, points in mapping.items():
            if points:
                pairs.append((f"{mapping_field}.{symbol}", points))

    return pairs


def long_frame_from_snapshot(snapshot: MacroDataSnapshot) -> pd.DataFrame:
    """Render a snapshot as a long-format frame for Parquet storage."""
    rows: list[dict[str, Any]] = []
    for field_name, points in _iter_series(snapshot):
        for point in points:
            rows.append(
                {
                    "country": snapshot.country,
                    "snapshot_as_of": snapshot.as_of,
                    "field": field_name,
                    "series_id": point.series_id,
                    "observation_date": point.observation_date,
                    "value": point.value,
                    "source": point.source,
                    "retrieved_at": point.retrieved_at,
                }
            )

    if not rows:
        # An empty snapshot still gets a file. "We fetched and got nothing" is
        # itself an audit fact, and omitting it would make a failed fetch
        # indistinguishable from a fetch that never ran.
        return pd.DataFrame(columns=list(_LONG_COLUMNS))

    frame = pd.DataFrame(rows)
    frame["observation_date"] = pd.to_datetime(frame["observation_date"]).dt.date
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], utc=True)
    frame["snapshot_as_of"] = pd.to_datetime(frame["snapshot_as_of"], utc=True)
    return frame[list(_LONG_COLUMNS)]


def write_snapshot(snapshot: MacroDataSnapshot) -> Path | None:
    """Persist a snapshot to Parquet. Returns the path, or ``None`` if disabled.

    Failures are logged and swallowed rather than raised: an audit-trail write
    failing must not abort the thesis computation the operator actually asked
    for. The reverse tradeoff (fail loudly, lose the thesis) is worse.
    """
    settings = get_settings()
    if not settings.data.persist_parquet:
        logger.info("Parquet persistence disabled by config; skipping write.")
        return None

    path = parquet_path_for(snapshot)
    try:
        frame = long_frame_from_snapshot(snapshot)
        frame.to_parquet(path, index=False)
        logger.info("Wrote snapshot (%s rows) to %s", len(frame), path)
        return path
    except Exception as exc:
        logger.error("Failed to persist snapshot to %s: %s", path, exc)
        return None


def _latest_parquet(country: str) -> Path | None:
    root = _raw_root(country)
    files = sorted(root.glob("*.parquet"))
    return files[-1] if files else None


def load_latest_snapshot_frame(country: str = "us") -> pd.DataFrame:
    """Read the most recent persisted snapshot frame, or an empty frame."""
    path = _latest_parquet(country)
    if path is None:
        return pd.DataFrame(columns=list(_LONG_COLUMNS))
    return pd.read_parquet(path)


def snapshot_from_long_frame(frame: pd.DataFrame) -> MacroDataSnapshot:
    """Rehydrate a ``MacroDataSnapshot`` from a long-format frame.

    Used by the offline test path and by any future backfill job. Note that
    ``data_quality_flags`` is *not* round-tripped: flags are a property of a
    validation run, not of the raw data, so they are re-derived on load rather
    than restored stale.
    """
    if frame.empty:
        return MacroDataSnapshot()

    country = str(frame["country"].iloc[0])
    as_of = pd.Timestamp(frame["snapshot_as_of"].iloc[0]).to_pydatetime()

    def points_for(field_name: str) -> list[ObservationPoint]:
        subset = frame[frame["field"] == field_name]
        return [
            ObservationPoint(
                observation_date=pd.Timestamp(row["observation_date"]).date(),
                value=float(row["value"]),
                series_id=str(row["series_id"]),
                source=str(row["source"]),
                retrieved_at=pd.Timestamp(row["retrieved_at"]).to_pydatetime(),
            )
            for _, row in subset.iterrows()
        ]

    snapshot = MacroDataSnapshot(country=country, as_of=as_of)
    for name in SCALAR_SERIES_FIELDS:
        setattr(snapshot, name, points_for(name))

    # Curves are written with field == curve name and the tenor in series_id
    # (e.g. field="yield_curve", series_id="yield_curve.10yr"). The read path
    # must reconstruct that shape explicitly: an earlier version only rebuilt
    # the scalar and mapping fields, so every curve was persisted correctly and
    # then silently discarded on load — the write/read asymmetry was invisible
    # until a live round-trip test asserted the curve came back.
    for curve_field in CURVE_SERIES_FIELDS:
        subset = frame[frame["field"] == curve_field]
        if subset.empty:
            continue
        tenors: dict[str, float] = {}
        curve_as_of = as_of.date()
        retrieved_at = as_of
        for _, row in subset.iterrows():
            series_id = str(row["series_id"])
            # series_id is "<curve_field>.<tenor>"; the tenor is the suffix.
            tenor = series_id.split(".", 1)[1] if "." in series_id else series_id
            tenors[tenor] = float(row["value"])
            observation_date = pd.Timestamp(row["observation_date"]).date()
            if observation_date > curve_as_of:
                curve_as_of = observation_date
            retrieved_at = pd.Timestamp(row["retrieved_at"]).to_pydatetime()
        setattr(
            snapshot,
            curve_field,
            YieldCurveSnapshot(as_of=curve_as_of, tenors=tenors, retrieved_at=retrieved_at),
        )

    for mapping_field in MAPPING_SERIES_FIELDS:
        mapping: dict[str, list[ObservationPoint]] = {}
        prefix = f"{mapping_field}."
        for field_name in frame["field"].unique():
            if isinstance(field_name, str) and field_name.startswith(prefix):
                symbol = field_name[len(prefix) :]
                mapping[symbol] = points_for(field_name)
        setattr(snapshot, mapping_field, mapping)

    return snapshot


def load_snapshot(country: str = "us") -> MacroDataSnapshot:
    """Load the most recent persisted snapshot for a country."""
    return snapshot_from_long_frame(load_latest_snapshot_frame(country))


def parse_compact_timestamp(token: str) -> datetime:
    """Inverse of ``parquet_path_for``'s filename token. Used by tools."""
    return datetime.strptime(token, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
