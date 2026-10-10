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
    "SnapshotStoreEmptyError",
    "has_persisted_snapshot",
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
#
# ⚠️ ``fed_total_assets``, ``reserve_balances``, ``ppi_stage_crude`` and
# ``ppi_stage_intermediate`` were added 2026-09-29 (audit finding P-1, Class C/F).
# They were DECLARED on the schema, POPULATED by the snapshot builder and the
# registry, and — measured — silently ERASED by this tuple's omission: a
# snapshot holding all four round-tripped to ZERO rows, because
# ``long_frame_from_snapshot`` iterates THIS list and nothing else. The coverage
# test only asserted the reverse direction (``declared ⊆ schema``), so the loss
# was invisible to every gate. Two guards now cover it: the test asserts BOTH
# directions, and a round-trip test pins a populated value for each.
SCALAR_SERIES_FIELDS: tuple[str, ...] = (
    "gdp_real",
    "gdp_nominal",
    "gdi",
    "gdp_potential",
    "cpi_headline",
    "cpi_core",
    "pce_core",
    "ppi",
    "ppi_stage_crude",
    "ppi_stage_intermediate",
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
    "fed_total_assets",
    "reserve_balances",
    "credit_spread_hy",
    "credit_spread_ig",
    # Section 22.3 — the UK block. Added 2026-10-10 with the multi-country
    # increment, and added HERE in the same change rather than after the gate
    # failed, because the failure this tuple causes is silent: these fields would
    # be declared, fetched, populated — and erased from every persisted snapshot,
    # exactly the P-1 defect the note above records. The coverage test's both-way
    # assertion is what makes the omission a gate failure rather than a data loss.
    "gb_cpi_headline",
    "gb_cpi_core",
    "gb_unemployment_rate",
    "gb_gdp_growth_qoq",
    "gb_bank_rate",
    "gb_gilt_10y_yield",
    "gb_short_rate_3m",
    # Section 22.3 — the euro-area block. Added 2026-10-10 with the second
    # multi-country increment, and added HERE in the same change rather than
    # after the gate failed: the failure this tuple causes is silent — these
    # fields would be declared, fetched, populated, and ERASED from every
    # persisted snapshot (the P-1 defect). The registry-key/schema-attribute
    # naming is what makes the two lists easy to get out of step.
    "eu_hicp_index",
    "eu_ecb_deposit_rate",
    "eu_ecb_main_refi_rate",
    "eu_estr",
    "eu_unemployment_rate",
    "eu_gdp_real_level",
    "eu_short_rate_3m",
    "eu_long_rate_10y",
)

# Curve-shaped series: stored with field == curve name and the tenor in series_id.
CURVE_SERIES_FIELDS: tuple[str, ...] = ("yield_curve", "tips_yields")

# Keyed mappings: stored with field == f"{name}.{symbol}".
MAPPING_SERIES_FIELDS: tuple[str, ...] = ("fx_spot", "commodity_spot", "equity_index")

# Long-format schema. One row per (series, date) observation, plus snapshot-level
# columns denormalized onto every row so a single file is self-describing.
#
# ``release_datetime`` and ``vintage_datetime`` are part of this schema because
# they are part of an observation, and Section 6's whole point is that the four
# timestamps are NOT interchangeable. They were previously omitted, which meant
# a snapshot could carry a populated ``release_datetime``, be written to the
# audit trail, and read back with every release stamp silently dropped — the
# exact "declared, consumed, unreachable" class this project keeps finding. The
# write path dropped them and the read path could not restore them, so no test
# that stopped at ``build_snapshot()`` could see it. Nullable by design: NULL
# means UNKNOWN, never "equal to observation_date".
_LONG_COLUMNS: tuple[str, ...] = (
    "country",
    "snapshot_as_of",
    "field",
    "series_id",
    "observation_date",
    "value",
    "source",
    "retrieved_at",
    "release_datetime",
    "vintage_datetime",
)


def _raw_root(country: str) -> Path:
    settings = get_settings()
    root = project_root() / str(settings.data.raw_store_path) / country
    root.mkdir(parents=True, exist_ok=True)
    return root


class SnapshotStoreEmptyError(FileNotFoundError):
    """Raised when a country's audit trail holds no snapshot at all.

    Subclasses ``FileNotFoundError`` because that is exactly what it is: the
    caller asked for a file and there is none.

    **Why this class has to exist.** ``load_snapshot`` on an empty store used to
    return a default empty ``MacroDataSnapshot()`` — silently, successfully. Any
    caller that tried to distinguish "no snapshot persisted yet" from "a snapshot
    was persisted and it was empty" by catching an exception caught nothing, so
    the failure surfaced later as a nonsense downstream error. That is precisely
    how ``tests/api_layer`` came to report 22 failures on a fresh clone (where
    ``data/raw/`` is git-ignored and therefore absent): the fixture guarded with
    ``except (FileNotFoundError, ValueError)``, never fired, and seeded an empty
    snapshot whose ``yield_curve`` is ``None`` — after which the API layer
    correctly reported "no curve" and the tests blamed the API.

    Distinguishing the two states is the entire point, so the distinction is
    carried by the type, not by inspecting the returned object for emptiness:
    an empty snapshot is a legitimate audit fact (see ``long_frame_from_snapshot``)
    while an absent store is a deployment/checkout state.
    """


def has_persisted_snapshot(country: str = "us") -> bool:
    """Whether the audit trail holds at least one snapshot for ``country``.

    The cheap, side-effect-aware predicate. ``_raw_root`` mkdirs as a side effect
    of resolving the path, which is correct for the write path but means this
    check creates an empty directory — acceptable, since it is the same directory
    ``load_snapshot`` would go on to read.
    """
    return _latest_parquet(country) is not None


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
    """Render a snapshot as a long-format frame for Parquet storage.

    The two release-side timestamps are carried through as nullable columns.
    ``None`` is written as a genuine NULL rather than being coerced to
    ``observation_date``, because Section 6 forbids exactly that substitution —
    and a NULL round-tripped correctly is what lets a reader tell "release
    timing known" from "unknown" after the fact.
    """
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
                    "release_datetime": point.release_datetime,
                    "vintage_datetime": point.vintage_datetime,
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
    # Both stamp columns are normalised to UTC on the way to disk, matching
    # ``retrieved_at`` and ``snapshot_as_of`` above. The instant is the fact;
    # the source's offset (``_extract_exact`` keeps it, e.g.
    # ``2026-09-11T08:37:49-05:00``) is presentation. Normalising here means a
    # reader never has to wonder which offset a stored stamp carries, and an
    # unknown stamp stays NaT — never coerced to the observation date.
    frame["release_datetime"] = pd.to_datetime(frame["release_datetime"], utc=True)
    frame["vintage_datetime"] = pd.to_datetime(frame["vintage_datetime"], utc=True)
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


def snapshot_from_long_frame(
    frame: pd.DataFrame,
    *,
    empty_country: str | None = None,
    empty_as_of: datetime | None = None,
) -> MacroDataSnapshot:
    """Rehydrate a ``MacroDataSnapshot`` from a long-format frame.

    Used by the offline test path and by any future backfill job. Note that
    ``data_quality_flags`` is *not* round-tripped: flags are a property of a
    validation run, not of the raw data, so they are re-derived on load rather
    than restored stale.

    ``empty_country`` / ``empty_as_of`` are consulted **only when the frame is
    empty**, because an empty frame carries no row to read them from. They exist
    because the write path deliberately persists an empty snapshot ("we fetched
    and got nothing" is an audit fact) and returning a bare
    ``MacroDataSnapshot()`` would replace the recorded ``as_of`` with NOW — a
    fabricated value, which is the one direction this project never accepts.
    :func:`load_snapshot` supplies them, decoding ``as_of`` from the filename
    token, since the filename is the only place the fact survives.
    """
    if frame.empty:
        if empty_as_of is None:
            return MacroDataSnapshot(country=empty_country or "us")
        return MacroDataSnapshot(country=empty_country or "us", as_of=empty_as_of)

    country = str(frame["country"].iloc[0])
    as_of = pd.Timestamp(frame["snapshot_as_of"].iloc[0]).to_pydatetime()

    def optional_timestamp(value: Any) -> datetime | None:
        """Read a nullable timestamp column, preserving SQL NULL as ``None``.

        ``pd.isna`` covers both ``NaT`` (how pandas stores a missing datetime)
        and ``None``. It must be tested BEFORE ``to_pydatetime``, because
        ``NaT.to_pydatetime()`` raises rather than returning ``None`` — the
        failure that would otherwise surface as "the audit trail is corrupt"
        when in fact the snapshot legitimately had no release stamp.

        Typed ``Any`` rather than ``object``: the value comes from a pandas row
        accessor, whose static type is ``Any``, and narrowing it to ``object``
        only pushes the ``isna``/``Timestamp`` overload mismatch onto this line.
        """
        if value is None or pd.isna(value):
            return None
        return pd.Timestamp(value).to_pydatetime()

    def points_for(field_name: str) -> list[ObservationPoint]:
        subset = frame[frame["field"] == field_name]
        return [
            ObservationPoint(
                observation_date=pd.Timestamp(row["observation_date"]).date(),
                value=float(row["value"]),
                series_id=str(row["series_id"]),
                source=str(row["source"]),
                retrieved_at=pd.Timestamp(row["retrieved_at"]).to_pydatetime(),
                release_datetime=optional_timestamp(row.get("release_datetime")),
                vintage_datetime=optional_timestamp(row.get("vintage_datetime")),
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


def load_snapshot(country: str = "us", *, strict: bool = False) -> MacroDataSnapshot:
    """Load the most recent persisted snapshot for a country.

    ``strict=True`` raises ``SnapshotStoreEmptyError`` when the audit trail holds
    nothing, instead of returning an empty snapshot. Default is ``False`` so the
    existing permissive behaviour — and the callers that legitimately want "give
    me whatever is there, empty is fine" — are unchanged.

    Use ``strict=True`` whenever the caller cannot act on an empty snapshot and
    would otherwise misreport its own downstream failure as a defect in the data
    layer. The API test fixtures are the canonical case.
    """
    path = _latest_parquet(country)
    if path is None:
        if strict:
            raise SnapshotStoreEmptyError(
                f"no persisted snapshot for {country!r} under "
                f"{_raw_root(country)}; run a live snapshot build to populate the "
                f"audit trail (see scripts/live_api_check.py)"
            )
        return MacroDataSnapshot(country=country)

    # An empty FILE is a legitimate audit fact (see `long_frame_from_snapshot`),
    # and its `as_of` survives only in the FILENAME — the long frame has no row
    # to carry it. Decoding the token here is what `parse_compact_timestamp`
    # exists for, and it is the difference between "this snapshot was taken at
    # 09:30 and found nothing" and "this snapshot was taken now": a fabricated
    # value rather than a missing one.
    return snapshot_from_long_frame(
        pd.read_parquet(path),
        empty_country=country,
        empty_as_of=parse_compact_timestamp(path.stem),
    )


def parse_compact_timestamp(token: str) -> datetime:
    """Inverse of :func:`parquet_path_for`'s filename token.

    This exists to make the invariant :func:`parquet_path_for` relies on
    checkable: the ``YYYYMMDDTHHMMSSZ`` compaction is exactly what makes the
    lexicographic order of the filenames match chronological order.

    **It now has exactly one production caller.** It had none when the D-134
    audit measured it (2026-09-29), and its docstring then falsely claimed "Used
    by tools". :func:`load_snapshot` calls it to recover ``as_of`` for an EMPTY
    snapshot file, whose long frame has no row to carry the timestamp — the
    filename is the only place that fact survives.
    ``load_latest_snapshot_frame`` still takes the LAST name from a glob-and-sort
    rather than parsing, which is the whole point of the compaction. This
    function exists so the token format has one decoding definition to argue
    with instead of a re-derived ``strptime`` at each reader.

    Raises :class:`ValueError` on a token that is not in the format. It
    refuses rather than returning ``None``: an unparsed timestamp read as a
    fallback would silently become a wrong "latest" ordering, which is the
    O-134 class of fault.
    """
    return datetime.strptime(token, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
