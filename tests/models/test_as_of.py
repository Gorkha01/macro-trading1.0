"""Hand-computed verification tests for models/as_of.py (Module, Section 5.5 / O-7).

Point-in-time discipline: observations dated AFTER as_of are withheld, not silently
consumed. Realised points are returned sorted oldest-first. The cutoff is the
calendar DATE of as_of (an observation stamped today is included at any instant today).

All expectations are derived by hand from the filter rule:
  realised  = [p for p if p.observation_date <= as_of.date()]
  withheld  = [p for p if p.observation_date >  as_of.date()]
  sorted by observation_date ascending.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from macro_engine.data_layer.schemas import ObservationPoint
from macro_engine.models.as_of import (
    latest_observation,
    observation_as_of,
    observation_on_or_before,
)

UTC = UTC


def _pt(day: int, value: float, sid: str = "gdp_potential") -> ObservationPoint:
    return ObservationPoint(
        observation_date=date(2026, 1, day),
        value=float(value),
        series_id=sid,
    )


# 2026-01-08 is the as_of instant below; 01-10 / 01-15 / 01-20 are future-dated.
_POINTS = [
    _pt(10, 110.0),
    _pt(1, 100.0),
    _pt(15, 115.0),
    _pt(5, 105.0),
    _pt(20, 120.0),
]


def test_observation_as_of_withholds_future_and_sorts() -> None:
    asof = observation_as_of(
        _POINTS, as_of=datetime(2026, 1, 8, tzinfo=UTC), series_id="gdp_potential"
    )
    # Realised: 01-01 (100) and 01-05 (105) only. 01-10/15/20 are withheld.
    assert len(asof.points) == 2
    assert [p.value for p in asof.points] == [100.0, 105.0]  # sorted oldest-first
    assert asof.withheld == 3
    assert asof.withheld_horizon == date(2026, 1, 20)
    assert asof.is_empty is False
    assert asof.was_truncated is True
    assert asof.series_id == "gdp_potential"


def test_latest_observation_returns_most_recent_realised() -> None:
    latest = latest_observation(_POINTS, as_of=datetime(2026, 1, 8, tzinfo=UTC))
    assert latest is not None
    assert latest.value == 105.0  # 01-05 is the newest realised point


def test_observation_on_or_before_ignores_as_of() -> None:
    # This helper answers "latest <= target" in the series' own history, NOT
    # routed through the as_of cutoff.
    target = date(2026, 1, 12)
    pt = observation_on_or_before(_POINTS, target)
    assert pt is not None
    assert pt.value == 110.0  # 01-10 is the newest point on/before 01-12


def test_truncation_warning_formatting() -> None:
    asof = observation_as_of(
        _POINTS, as_of=datetime(2026, 1, 8, tzinfo=UTC), series_id="gdp_potential"
    )
    w = asof.truncation_warning(series_label="GDPPOT")
    assert w is not None
    assert "3 forward-dated observation(s)" in w
    assert "2026-01-20" in w
    assert "2026-01-08" in w


def test_empty_series_is_hard_stop_not_default() -> None:
    empty = observation_as_of([], as_of=datetime(2026, 1, 8, tzinfo=UTC))
    assert empty.is_empty is True
    assert empty.latest is None
    assert empty.was_truncated is False
    assert empty.truncation_warning() is None


def test_all_future_dated_series_is_empty_but_truncated() -> None:
    future = [_pt(20, 200.0), _pt(25, 201.0)]
    asof = observation_as_of(future, as_of=datetime(2026, 1, 8, tzinfo=UTC))
    assert asof.is_empty is True
    assert asof.latest is None
    assert asof.withheld == 2
    assert asof.was_truncated is True


def test_series_id_defaults_from_first_point() -> None:
    asof = observation_as_of(_POINTS, as_of=datetime(2026, 1, 8, tzinfo=UTC))
    assert asof.series_id == "gdp_potential"
