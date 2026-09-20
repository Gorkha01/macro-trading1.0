"""RED->GREEN: `assert_finite` does not cover the curve fields.

D-074's fix added `assert_finite()` as "the only chokepoint every path shares",
explicitly because a snapshot can arrive via `model_construct`, a pickle or a
parquet round-trip and never face field validation. But the guard iterates
`iter_scalar_series()`, which selects only fields whose value is a
`list[ObservationPoint]` — so `yield_curve` and `tips_yields` are never visited.

`YieldCurveSnapshot.tenors` is `dict[str, float]` with **no** `allow_inf_nan=False`,
so `nan` is accepted there by pydantic's default (the exact D-074.1 mechanism).
A `nan` yield therefore passes the schema, passes `assert_finite`, and reaches
`validate_yield_curve`, whose checks are all comparisons:
`yld <= 0.0` is False for nan, `yld > max` is False for nan. The curve reports
**CLEAN**.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from macro_engine.data_layer.schemas import MacroDataSnapshot, YieldCurveSnapshot


def test_a_non_finite_curve_tenor_is_refused_at_construction() -> None:
    """A `nan` tenor must not be constructible."""
    with pytest.raises(Exception) as excinfo:
        YieldCurveSnapshot(
            as_of=date(2026, 9, 17),
            tenors={"2yr": float("nan"), "10yr": 4.5},
        )
    assert "nan" in str(excinfo.value).lower() or "finite" in str(excinfo.value).lower()


def test_a_non_finite_curve_tenor_is_caught_by_the_snapshot_guard() -> None:
    """The backstop must see the curve, not only the scalar lists.

    Built via `model_construct` because that is the documented bypass — the
    path that never runs field validation, which is the reason `assert_finite`
    exists at all.
    """
    curve = YieldCurveSnapshot.model_construct(
        as_of=date(2026, 9, 17),
        tenors={"2yr": float("inf"), "10yr": 4.5},
        retrieved_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
    )
    snapshot = MacroDataSnapshot.model_construct(
        country="us",
        as_of=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        yield_curve=curve,
    )

    with pytest.raises(ValueError, match="non-finite"):
        snapshot.assert_finite()


def test_a_clean_curve_passes_the_guard() -> None:
    """The absence half: a clean curve must not raise."""
    curve = YieldCurveSnapshot(as_of=date(2026, 9, 17), tenors={"2yr": 4.0, "10yr": 4.5})
    snapshot = MacroDataSnapshot(
        country="us",
        as_of=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        yield_curve=curve,
    )

    snapshot.assert_finite()  # must not raise
