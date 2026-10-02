"""Hand-computed verification suite for the shared contract layer (contracts.py).

Covers the three things every other module inherits: the LAW-1 single
confidence producer (``compute_confidence``), the recursive non-finite input
guard (``FiniteInputs``), and the ``ModelResult`` reasoning-object contract.
Every expected number is derived here, not copied from the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    ModelValue,
    compute_confidence,
    utc_now,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily


def _conf() -> dict[str, float]:
    return get_settings().confidence.values


# ---------------------------------------------------------------------------
# compute_confidence — the single LAW-1 confidence rule (Section 22.8)
# ---------------------------------------------------------------------------
def test_confidence_formula_baseline_no_factors():
    # base 0.70, no penalties, count 0 -> 0.70, clamped & rounded.
    assert compute_confidence(ConfidenceInputs()) == pytest.approx(0.70)


def test_confidence_heuristic_only():
    # 0.70 - 0.20 (heuristic) = 0.50
    assert compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True)
    ) == pytest.approx(0.50)


def test_confidence_all_penalties_no_bonus():
    # 0.70 - 0.25 - 0.20 - 0.20 = 0.05 (== floor)
    c = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
        )
    )
    assert c == pytest.approx(0.05)


def test_confidence_floor_cannot_be_breached():
    # All three penalties WITHOUT bonus would be 0.05 (already floor); push harder
    # by adding a negative source count is impossible (ge=0). Confirm the floor
    # holds at exactly 0.05 even with all penalties.
    c = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )
    assert c == _conf()["floor"]
    assert c == pytest.approx(0.05)


def test_confidence_independence_bonus_added_before_clamp():
    # 0.70 - 0.20 (heuristic) + min(4*0.05, 0.25) = 0.50 + 0.20 = 0.70
    c = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=4)
    )
    assert c == pytest.approx(0.70)


def test_confidence_bonus_capped_at_0_25():
    # 0.70 + min(10*0.05, 0.25) = 0.70 + 0.25 = 0.95 (== ceiling, no clipping
    # below since 0.95 is exactly the ceiling). With all three penalties too:
    # 0.70 - 0.65 + 0.25 = 0.30.
    c_all = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=10,
        )
    )
    assert c_all == pytest.approx(0.30)
    # Pure bonus cap check (no penalties): 0.70 + 0.25 = 0.95.
    c_bonus = compute_confidence(ConfidenceInputs(source_independence_count=10))
    assert c_bonus == _conf()["ceiling"]
    assert c_bonus == pytest.approx(0.95)


def test_confidence_is_derived_not_asserted():
    # LAW 1: no model hardcodes confidence. The function reads every constant
    # from config; we prove the config is the single source by checking the
    # formula matches the config values directly (not magic numbers in code).
    p = _conf()
    expected = p["base"] - p["heuristic_penalty"] + min(
        3 * p["source_independence_bonus"], p["source_independence_bonus_cap"]
    )
    expected = round(max(p["floor"], min(p["ceiling"], expected)), 3)
    assert compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=3)
    ) == expected


# ---------------------------------------------------------------------------
# FiniteInputs — recursive non-finite guard (D-078 / D-139)
# ---------------------------------------------------------------------------
class _Scalar(FiniteInputs):
    x: float


class _Series(FiniteInputs):
    xs: list[float]


class _Matrix(FiniteInputs):
    grid: list[list[float]]


class _Curve(FiniteInputs):
    tenors: dict[str, float]


class _Mixed(FiniteInputs):
    points: dict[str, list[float]]


class _Sub(BaseModel):
    a: float
    b: float


class _Nested(FiniteInputs):
    comp: _Sub


def test_finite_scalar_ok():
    assert _Scalar(x=1.5).x == 1.5


def test_finite_scalar_nan_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        _Scalar(x=float("nan"))


def test_finite_scalar_inf_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        _Scalar(x=float("inf"))


def test_finite_list_ok():
    assert _Series(xs=[1.0, 2.0, 3.0]).xs == [1.0, 2.0, 3.0]


def test_finite_list_bad_element_rejected():
    with pytest.raises(ValueError, match=r"xs\[1\]=inf"):
        _Series(xs=[1.0, float("inf"), 3.0])


def test_finite_matrix_bad_diagonal_rejected():
    # A list[list[float]] — the matrix shape. One nan on the diagonal must be
    # caught at the inner level, named xs[0][0].
    with pytest.raises(ValueError, match=r"grid\[0\]\[0\]=nan"):
        _Matrix(grid=[[float("nan"), 1.0], [2.0, 3.0]])


def test_finite_matrix_ok():
    m = _Matrix(grid=[[1.0, 2.0], [3.0, 4.0]])
    assert m.grid == [[1.0, 2.0], [3.0, 4.0]]


def test_finite_dict_value_bad_rejected():
    # A tenor->rate map; a nan rate must be caught, named tenors['10y'].
    with pytest.raises(ValueError, match=r"tenors\['10y'\]=nan"):
        _Curve(tenors={"3mo": 0.05, "10y": float("nan")})


def test_finite_dict_ok():
    c = _Curve(tenors={"3mo": 0.05, "10y": 4.2})
    assert c.tenors["10y"] == 4.2


def test_finite_mixed_dict_of_lists_rejected():
    with pytest.raises(ValueError, match=r"points\['q2'\]\[1\]=inf"):
        _Mixed(points={"q1": [1.0, 2.0], "q2": [3.0, float("inf")]})


def test_finite_nested_model_rejected():
    # A nested pydantic model field is still an input; nan inside it is refused.
    with pytest.raises(ValueError, match="non-finite"):
        _Nested(comp=_Sub(a=1.0, b=float("nan")))


def test_finite_bool_not_treated_as_float():
    # bool is an int subclass in Python; it must NOT trip the float non-finite
    # check (a bool is never non-finite). A list containing True must pass.
    class _WithBool(FiniteInputs):
        flags: list[bool]

    assert _WithBool(flags=[True, False]).flags == [True, False]


def test_finite_none_field_ok():
    class _Opt(FiniteInputs):
        maybe: float | None = None

    assert _Opt().maybe is None


def test_finite_extra_field_forbidden():
    with pytest.raises(ValueError):
        _Scalar(x=1.0, y=2.0)


# ---------------------------------------------------------------------------
# ModelResult — the reasoning-object contract (Section 22.9 / Finding #9)
# ---------------------------------------------------------------------------
def _base_result(value: ModelValue, **kw) -> ModelResult:
    return ModelResult(
        model_name="unit_test",
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.55,
        interpretation="test value",
        context="vs target",
        inputs_used=["x"],
        **kw,
    )


@pytest.mark.parametrize(
    "value",
    [3.14, -7, "tightening", True, False, {"a": 1}, [1, 2, 3], None],
)
def test_model_result_accepts_full_value_union(value):
    # The corrected union: float|int|str|bool|dict|list|None.
    res = _base_result(value)
    assert res.value == value


def test_model_result_confidence_range_enforced():
    with pytest.raises(ValueError):
        ModelResult(
            model_name="x",
            country="us",
            as_of=utc_now(),
            value=1.0,
            confidence=1.5,  # > 1.0 violates Annotated ge/le
            interpretation="i",
            context="c",
            inputs_used=["x"],
        )


def test_model_result_source_family_typed():
    res = _base_result(1.0, source_family=EvidenceSourceFamily.BLS_CPI)
    assert res.source_family is EvidenceSourceFamily.BLS_CPI


def test_model_result_extra_field_forbidden():
    with pytest.raises(ValueError):
        _base_result(1.0, not_a_field=9)


def test_utc_now_is_timezone_aware_utc():
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.now(tz=UTC).utcoffset()
    # naive datetime.utcnow() would have tzinfo is None; we assert the fix.
    assert now.tzinfo == UTC
