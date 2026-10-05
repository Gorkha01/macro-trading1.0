"""Tests for ``api_layer/snapshot_provider.py``'s ``SnapshotProvenance`` disclosures.

``tests/api_layer/`` was empty: these disclosures are PUBLISHED on every
``/dashboard``, ``/query`` and ``/thesis`` response (``routes_dashboard.py:197``,
``routes_query.py:291``, ``routes_thesis.py:233``) and nothing tested them.

Finding guarded here:
  * F-SNAP-001 (SEV-2) — the ``SNAPSHOT FLAGGED`` line told a consumer "these
    flags are NOT applied as a confidence penalty automatically ... which no
    model populates from this snapshot-level list". FALSE: ``gdp_nowcast``
    reads the list and re-prices its confidence. This is the THIRD instance of
    the same false claim (with ``data_layer/validation.py`` and
    ``data_layer/schemas.py``) and the worst surface of the three, because it is
    a runtime message rather than a docstring — and it is actionable: a consumer
    who believes it will apply a penalty that has already been applied.
"""

from __future__ import annotations

from datetime import UTC, datetime

from macro_engine.api_layer.snapshot_provider import SnapshotProvenance

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _prov(*, flags: int = 0, stale: bool = False, cached: bool = False) -> SnapshotProvenance:
    return SnapshotProvenance(
        country="us",
        as_of=NOW,
        generated_at=NOW,
        age_hours=30.0 if stale else 1.0,
        age_exceeds_max=stale,
        max_age_hours=24.0,
        from_cache=cached,
        data_quality_flag_count=flags,
    )


def _flagged_line(flags: int = 3) -> str:
    lines = [w for w in _prov(flags=flags).warnings() if w.startswith("SNAPSHOT FLAGGED")]
    assert len(lines) == 1
    return lines[0]


def test_flagged_disclosure_names_gdp_nowcast_as_the_exception() -> None:
    line = _flagged_line()
    assert "gdp_nowcast" in line
    # The over-claim that made it false must be gone.
    assert "no model" not in line
    assert "which no model populates" not in line


def test_flagged_disclosure_still_warns_the_other_models_do_not_penalise() -> None:
    line = _flagged_line()
    assert "MOST models" in line
    assert "explicitly" in line


def test_a_clean_snapshot_emits_no_flagged_disclosure() -> None:
    assert not [w for w in _prov(flags=0).warnings() if "SNAPSHOT FLAGGED" in w]


def test_the_other_provenance_disclosures_still_fire() -> None:
    stale = [w for w in _prov(stale=True).warnings() if w.startswith("SNAPSHOT STALE")]
    cached = [w for w in _prov(cached=True).warnings() if w.startswith("SNAPSHOT REUSED")]
    assert len(stale) == 1 and "beyond the configured" in stale[0]
    assert len(cached) == 1 and "served from" in cached[0]
