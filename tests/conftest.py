"""Shared fixtures for the test suite.

Golden tests compute their expected values **by hand** before running, per
Section 21.2 Step 4: "If the test passes on the first attempt without you
having computed the expected value independently, the test is worthless — you
have asserted whatever the code produced." Every expected value in this suite
carries a comment showing the arithmetic that produced it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)
from macro_engine.models.contracts import ModelResult, utc_now

__all__ = [
    "as_float",
    "make_curve",
    "make_points",
    "make_snapshot",
]


def make_points(
    values: list[float],
    *,
    series_id: str,
    start: date | None = None,
    step_days: int = 30,
    retrieved_at_offset_days: int = 0,
) -> list[ObservationPoint]:
    """Build an observation series from a list of values, oldest first.

    ``retrieved_at_offset_days`` lets a test push the retrieval date into the
    future relative to the observations (the normal case) or, with a negative
    value, engineer a future-dated observation to exercise that check.
    """
    retrieval = utc_now() + timedelta(days=retrieved_at_offset_days)
    origin = start or (retrieval.date() - timedelta(days=step_days * (len(values) - 1)))
    return [
        ObservationPoint(
            observation_date=origin + timedelta(days=step_days * index),
            value=value,
            series_id=series_id,
            retrieved_at=retrieval,
        )
        for index, value in enumerate(values)
    ]


def make_curve(tenors: dict[str, float], *, as_of: date | None = None) -> YieldCurveSnapshot:
    """Build a yield curve snapshot. Tenor values are in PERCENT."""
    return YieldCurveSnapshot(
        as_of=as_of or utc_now().date(),
        tenors=tenors,
        retrieved_at=utc_now(),
    )


def make_snapshot(**overrides: object) -> MacroDataSnapshot:
    """Build a snapshot, filling only the fields a test actually needs.

    Defaults to empty everywhere else so that a test's intent is visible in
    the call rather than buried in boilerplate setup.
    """
    return MacroDataSnapshot(**overrides)  # type: ignore[arg-type]


def as_float(result: ModelResult, *, key: str | None = None) -> float:
    """Narrow ``ModelResult.value`` to a float for arithmetic in a test.

    ``ModelResult.value`` is a union by design (Section 22.9): ``float | int |
    str | bool | dict | list | None``. Retyping it in the model would destroy
    that — the union is what lets one result type carry a score, a verdict and
    a structured decomposition.

    So the narrowing belongs at the *use* site, and this helper puts it in one
    place rather than scattering ``float(x)  # type: ignore`` across the suite.
    It asserts rather than casts: if a test calls ``as_float`` on a result that
    is not a float, that is a test bug and should fail loudly, not be silenced.

    With ``key`` given, the value must be a dict and the named entry is
    extracted — the common case for a structured decomposition.
    """
    value = result.value
    if key is not None:
        assert isinstance(value, dict), (
            f"{result.model_name}: expected a dict value to read {key!r} from, "
            f"got {type(value).__name__}"
        )
        entry = value[key]
        assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
            f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not numeric"
        )
        return float(entry)
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{result.model_name}: expected a numeric value, got {type(value).__name__}"
    )
    return float(value)


@pytest.fixture
def empty_snapshot() -> MacroDataSnapshot:
    return make_snapshot()


@pytest.fixture
def healthy_curve() -> YieldCurveSnapshot:
    """A conventionally upward-sloping curve, roughly recent US shape."""
    return make_curve(
        {
            "3mo": 5.25,
            "6mo": 5.10,
            "1yr": 4.85,
            "2yr": 4.55,
            "3yr": 4.40,
            "5yr": 4.30,
            "7yr": 4.32,
            "10yr": 4.35,
            "20yr": 4.60,
            "30yr": 4.55,
        }
    )
