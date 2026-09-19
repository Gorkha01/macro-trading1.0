"""Phase 5+ extension: DuckDB-backed store over the existing Parquet directory.

Interface contract (AGENTS.md Section 12): ``persistence.py`` already writes
Parquet and ``MacroDataSnapshot`` already carries ``retrieved_at`` timestamps,
so this extension is a pure *query-layer* addition. It must not require any
schema change to the data layer — that is the whole reason the persistence
format was chosen as Parquet in Phase 1.

Nothing here is imported by Phase 1-4 code. This module exists so that the
eventual upgrade is a body-fill, not a refactor of its callers.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

__all__ = ["DuckDBStore"]


class DuckDBStore:
    """Query interface over ``data/raw/{country}/*.parquet``.

    Phase 5+ replaces the glob-and-read in ``persistence.load_latest_snapshot_frame``
    with an ``ATTACH``-based query. The public surface mirrors the persistence
    module deliberately: same inputs, same outputs, so a caller swaps one for
    the other without touching anything else.
    """

    def __init__(self, parquet_root: Path | None = None) -> None:
        raise NotImplementedError(
            "Phase 5+ — requires the `duckdb` dependency, which Section 4 does not "
            "permit installing before its phase. See docs/DECISIONS.md."
        )

    def query_series(
        self,
        *,
        field: str,
        country: str = "us",
        start: date | None = None,
        end: date | None = None,
    ) -> Any:
        """Return observations for one field, point-in-time queried."""
        raise NotImplementedError("Phase 5+ — see DuckDBStore.__init__.")
