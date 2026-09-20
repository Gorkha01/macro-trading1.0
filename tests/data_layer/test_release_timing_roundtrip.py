"""Section 6's release-side timestamps must survive the audit trail.

The defect this pins
--------------------
``ObservationPoint`` carries four timestamps that Section 6 says are NOT
interchangeable — ``observation_date`` (what period the value describes),
``release_datetime`` (when it became public), ``vintage_datetime`` (which
revision), and ``retrieved_at`` (when this process read it). ``release_datetime``
is populated in production from each series' own ``last_updated`` metadata at
42/42 registry coverage.

But ``persistence._LONG_COLUMNS`` listed only ``retrieved_at``. So a snapshot
carrying populated release stamps was written to Parquet with those stamps
dropped, and ``snapshot_from_long_frame`` had no column to read them from. The
data layer did the work, reported the coverage, and then the audit trail threw
it away — the D-037/D-045/D-048/O-48 class: **declared, consumed, unreachable**.

Why no existing test caught it
------------------------------
Every assertion in ``tests/data_layer/`` stops at ``build_snapshot()`` or at the
frame built in memory by ``long_frame_from_snapshot``. The drop happened one
step later, between that frame and the file. A write/read asymmetry is invisible
to any test that does not do both — which is exactly the lesson the curve
round-trip already taught this file's neighbours (see the comment in
``snapshot_from_long_frame`` about curves being persisted and then discarded).

The three states, and why the read path must not collapse them
--------------------------------------------------------------
* a stamp present      -> the source stated when it published;
* ``None``             -> UNKNOWN, which is a different fact from the next one;
* ``observation_date`` -> what a consumer reads if ``None`` is coerced on the way
  out, and the exact substitution Section 6 prohibits.

So the read path returns ``None`` for a NULL and never substitutes. ``NaT`` is
how pandas stores a missing datetime, and ``NaT.to_pydatetime()`` raises rather
than returning ``None`` — hence the explicit ``pd.isna`` guard, which is itself
worth a test because the failure would look like a corrupt audit trail.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from macro_engine.data_layer.persistence import (
    _LONG_COLUMNS,
    load_latest_snapshot_frame,
    long_frame_from_snapshot,
    snapshot_from_long_frame,
    write_snapshot,
)
from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint


def _point(
    *,
    series_id: str,
    observation_date: date,
    value: float,
    release_datetime: datetime | None,
) -> ObservationPoint:
    return ObservationPoint(
        observation_date=observation_date,
        value=value,
        series_id=series_id,
        source="openbb",
        retrieved_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        release_datetime=release_datetime,
    )


def _snapshot_with_release_stamps() -> MacroDataSnapshot:
    """One series where timing is known and one where it is unknown.

    Both cases matter in the same frame: a round-trip that coerced ``None`` to
    the observation date would pass a test that only ever wrote populated
    stamps.
    """
    return MacroDataSnapshot(
        country="us",
        as_of=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        cpi_headline=[
            _point(
                series_id="cpi_headline",
                observation_date=date(2026, 7, 1),
                value=334.131,
                release_datetime=datetime(2026, 8, 12, 8, 30, tzinfo=UTC),
            ),
            _point(
                series_id="cpi_headline",
                observation_date=date(2026, 8, 1),
                value=335.0,
                release_datetime=datetime(2026, 9, 11, 8, 30, tzinfo=UTC),
            ),
        ],
        unemployment_rate=[
            _point(
                series_id="unemployment_rate",
                observation_date=date(2026, 8, 1),
                value=4.2,
                release_datetime=None,  # UNKNOWN, and must stay unknown
            )
        ],
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_the_long_schema_carries_both_release_side_timestamps() -> None:
    """The columns must exist, since their absence is the defect."""
    assert "release_datetime" in _LONG_COLUMNS
    assert "vintage_datetime" in _LONG_COLUMNS


# ---------------------------------------------------------------------------
# Write side
# ---------------------------------------------------------------------------


def test_long_frame_carries_release_datetimes_and_nulls() -> None:
    """The write side must emit the stamp, and a real NULL where it is unknown."""
    frame = long_frame_from_snapshot(_snapshot_with_release_stamps())

    cpi = frame[frame["field"] == "cpi_headline"].sort_values("observation_date")
    assert list(cpi["release_datetime"]) == [
        pd.Timestamp("2026-08-12T08:30:00Z"),
        pd.Timestamp("2026-09-11T08:30:00Z"),
    ]

    unrate = frame[frame["field"] == "unemployment_rate"]
    assert len(unrate) == 1
    # NULL, not the observation date. This is the substitution Section 6 forbids.
    assert pd.isna(unrate["release_datetime"].iloc[0])


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------


def test_null_release_datetime_reads_back_as_none_not_the_observation_date() -> None:
    """An unknown stamp must come back UNKNOWN, never as the observation date."""
    snapshot = snapshot_from_long_frame(long_frame_from_snapshot(_snapshot_with_release_stamps()))

    point = snapshot.unemployment_rate[0]
    assert point.release_datetime is None
    assert point.has_known_release_timing is False
    # The specific substitution that the whole module exists to prevent.
    assert point.release_datetime != datetime.combine(point.observation_date, datetime.min.time())


def test_known_release_datetimes_survive_the_round_trip() -> None:
    """The instant and the .known-timing predicate must both come back."""
    original = _snapshot_with_release_stamps()
    restored = snapshot_from_long_frame(long_frame_from_snapshot(original))

    original_cpi = sorted(original.cpi_headline, key=lambda p: p.observation_date)
    restored_cpi = sorted(restored.cpi_headline, key=lambda p: p.observation_date)
    assert len(restored_cpi) == len(original_cpi)
    for before, after in zip(original_cpi, restored_cpi, strict=True):
        assert after.release_datetime == before.release_datetime
        assert after.has_known_release_timing is True
        assert after.observation_date == before.observation_date
        assert after.value == before.value
        assert after.series_id == before.series_id


def test_read_path_tolerates_a_frame_missing_the_release_columns() -> None:
    """An older audit file predating these columns must still load.

    The read path uses ``row.get``, so a frame written before the schema change
    reads back with timing UNKNOWN rather than raising. That is the correct
    degradation: a missing column means "this file cannot answer the question",
    not "this file is corrupt".
    """
    legacy = long_frame_from_snapshot(_snapshot_with_release_stamps()).drop(
        columns=["release_datetime", "vintage_datetime"]
    )
    restored = snapshot_from_long_frame(legacy)

    assert [p.release_datetime for p in restored.cpi_headline] == [None, None]
    assert all(p.has_known_release_timing is False for p in restored.cpi_headline)


# ---------------------------------------------------------------------------
# File round-trip — the step the in-memory tests above cannot see
# ---------------------------------------------------------------------------


def test_release_timing_survives_a_real_parquet_write_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE regression: write to disk through ``write_snapshot`` and read back.

    This is the test whose absence allowed the defect. It exercises the actual
    file boundary, so a column dropped from ``_LONG_COLUMNS`` — which is what
    happened — fails here even though every in-memory assertion above still
    passes.
    """
    from macro_engine import config as config_module
    from macro_engine.data_layer import persistence as persistence_module

    monkeypatch.setattr(persistence_module, "_raw_root", lambda country: tmp_path)
    settings = config_module.get_settings()
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: settings.model_copy(
            update={"data": settings.data.model_copy(update={"persist_parquet": True})}
        ),
    )

    snapshot = _snapshot_with_release_stamps()
    written = write_snapshot(snapshot)
    assert written is not None and written.exists(), "the write path must land a file"

    reloaded = snapshot_from_long_frame(load_latest_snapshot_frame())

    known = [p for p in reloaded.cpi_headline if p.has_known_release_timing]
    assert len(known) == 2, "release stamps were dropped at the file boundary"
    assert {p.release_datetime for p in known} == {
        datetime(2026, 8, 12, 8, 30, tzinfo=UTC),
        datetime(2026, 9, 11, 8, 30, tzinfo=UTC),
    }
    # and the unknown one is still unknown after a real file round-trip
    assert reloaded.unemployment_rate[0].release_datetime is None


def test_release_stamp_instants_are_timezone_stable_across_the_file_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offset-aware source stamp must denote the same INSTANT on the way back.

    ``publication_dates._extract_exact`` preserves the provider's own offset
    (verified live: ``2026-09-11T08:37:49-05:00``). The storage layer normalises
    to UTC, which is fine for an *instant* and wrong for a *wall clock* — so the
    assertion is on equality of the instant, whichever offset each side carries,
    and on the UTC offset of the returned value being zero.
    """
    from macro_engine import config as config_module
    from macro_engine.data_layer import persistence as persistence_module

    monkeypatch.setattr(persistence_module, "_raw_root", lambda country: tmp_path)
    settings = config_module.get_settings()
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: settings.model_copy(
            update={"data": settings.data.model_copy(update={"persist_parquet": True})}
        ),
    )

    provider_offset = datetime(2026, 9, 11, 8, 37, 49, tzinfo=timezone(timedelta(hours=-5)))
    snapshot = MacroDataSnapshot(
        country="us",
        as_of=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        cpi_headline=[
            _point(
                series_id="cpi_headline",
                observation_date=date(2026, 8, 1),
                value=335.0,
                release_datetime=provider_offset,
            )
        ],
    )
    assert write_snapshot(snapshot) is not None

    restored = snapshot_from_long_frame(load_latest_snapshot_frame())
    stamp = restored.cpi_headline[0].release_datetime
    assert stamp is not None
    assert stamp == provider_offset, "the instant moved across the file boundary"
    assert stamp.utcoffset() == timedelta(0), "stored stamps are normalised to UTC"
