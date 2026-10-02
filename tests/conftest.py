"""Shared constructors for the macro-engine test suite.

These helpers build **real production types** — ``ObservationPoint``,
``YieldCurveSnapshot``, ``MacroDataSnapshot`` — not stand-ins for them. That
distinction is the whole reason they exist in one place: a test that builds a
dict and calls it a snapshot is testing a dict, and every field validator,
finiteness guard and range check on the real model is silently skipped.

What they are NOT: a source of values. Every *number* passed to these helpers
is supplied by the calling test, and several tests deliberately pass
impossible values (``unemployment_rate = 150``) because the behaviour under
test is that an impossible value is flagged rather than accepted. The helpers
contribute structure — dates, series ids, tenor keys — and no economics.

Reconstructed during the production review (finding F-BASE-001): the committed
suite imports these three names but no ``tests/conftest.py`` was ever
committed, so ``pytest`` could not collect. The signatures below are derived
from the call sites in the committed tests, and from the field names declared
by ``MacroDataSnapshot`` — not invented.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)
from macro_engine.models.contracts import utc_now

__all__ = ["make_curve", "make_points", "make_snapshot"]

# Observation dates are laid out backwards from a fixed offset so that every
# generated point is strictly in the past. This matters: `validate_observations`
# raises FUTURE_OBSERVATION_DATE for a point dated after its `retrieved_at`, so
# a helper that dated points forward from today would make unrelated tests fail
# for a reason that has nothing to do with what they assert.
_LEAD_DAYS = 30


def _base_date() -> date:
    """First observation date: today minus the lead, so all points are past."""
    return utc_now().date() - timedelta(days=_LEAD_DAYS)


def make_points(
    values: list[float],
    series_id: str,
    *,
    step_days: int = 1,
) -> list[ObservationPoint]:
    """Build one ``ObservationPoint`` per value, dated ascending and in the past.

    ``series_id`` is the internal field name (``cpi_headline``), not a provider
    symbol — ``ObservationPoint`` documents that distinction and the registry
    is what maps one to the other.
    """
    base = _base_date()
    retrieved = utc_now()
    return [
        ObservationPoint(
            observation_date=base + timedelta(days=index * step_days),
            value=value,
            series_id=series_id,
            retrieved_at=retrieved,
        )
        for index, value in enumerate(values)
    ]


def make_curve(
    tenors: dict[str, float],
    *,
    as_of: date | None = None,
) -> YieldCurveSnapshot:
    """Build a curve from a tenor -> yield-in-percent mapping.

    Yields are PERCENT (``4.35`` means 4.35%), which is the convention
    ``YieldCurveSnapshot`` states. Tenor labels are validated against
    ``CANONICAL_TENORS`` by the model itself, so an unknown label raises here
    rather than being carried into a test as a quietly-absent tenor.
    """
    return YieldCurveSnapshot(
        as_of=as_of if as_of is not None else _base_date(),
        tenors=dict(tenors),
    )


def make_snapshot(**fields: Any) -> MacroDataSnapshot:
    """Build a ``MacroDataSnapshot``, refusing unknown field names.

    ``MacroDataSnapshot`` is ``extra="forbid"``, so an unknown keyword would
    raise on its own — but the resulting error names the model, not the
    offending keyword. Since the snapshot has ~28 series fields with similar
    names (``ppi`` / ``ppi_stage_crude`` / ``ppi_stage_intermediate``), a typo
    that silently produced an empty field is a real hazard: an empty list is a
    legal value, and a test asserting "not flagged" would pass for the wrong
    reason. So the name is checked first and the error names it.
    """
    known = set(MacroDataSnapshot.model_fields)
    unknown = sorted(set(fields) - known)
    if unknown:
        raise ValueError(
            f"unknown MacroDataSnapshot field(s) {unknown}; "
            f"permitted fields: {sorted(known)}"
        )
    return MacroDataSnapshot(**fields)
