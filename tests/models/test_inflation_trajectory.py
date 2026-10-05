"""Hand-computed verification tests for models/inflation_trajectory.py (Module 3.6).

project_inflation_trajectory(inputs) -> ModelResult; value is a dict:
    projected_change_pp = beta * score * fiscal_scale
    beta from config = 0.006 pp per score point (FIXED, not a literal).
    bands from config: reaccelerating above +0.05pp, decelerating below -0.05pp,
    strict on both sides (a reading exactly on a bound -> "stable").
    direction = reaccelerating | stable | decelerating.

Hand checks:
  * sign: positive score (tight labor) -> POSITIVE change -> reaccelerating.
    The spec negated twice and the two negations cancelled; inverting here is
    the single easiest error, so it has a dedicated test.
  * reachability: sweeping score in [-100, 100] must produce ALL THREE labels
    (the spec's pairing left "stable" at 79.1% of months -- the D-047 base-state
    failure; this pairing partitions live history as ~31/40/28%).
  * fiscal: scales MAGNITUDE only, never sign.
  * confidence (LAW 1, from compute_confidence):
        base 0.70 - heuristic 0.20 - unobservable 0.20 + indep*0.05 (cap 0.25)
      - agrees/disagrees with an independent growth family -> indep 1 -> 0.35
      - unavailable / not_directional growth              -> indep 0 -> 0.30
      - plus -0.25 if labor carried warnings (data_quality flag)
    F-INTRAJ-002 FIX: disagreement by an independent family now counts as
    independence (per the module docstring), so it yields 0.35, not 0.30.
"""

from __future__ import annotations

import pytest

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.inflation_trajectory import (
    InflationTrajectoryInputs,
    project_inflation_trajectory,
)


def _mr(value: float, warnings: list[str] | None = None) -> ModelResult:
    return ModelResult(
        model_name="fixture",
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.7,
        interpretation="x",
        context="x",
        inputs_used=["x"],
        warnings=list(warnings or []),
    )


def _run(
    score: float,
    growth_value: float = 1.0,
    inflation_value: float = 3.5,
    fiscal: bool = False,
    labor_warnings: list[str] | None = None,
) -> ModelResult:
    return project_inflation_trajectory(
        InflationTrajectoryInputs(
            growth=_mr(growth_value),
            labor=_mr(score, warnings=labor_warnings),
            inflation=_mr(inflation_value),
            fiscal_response_active=fiscal,
        )
    )


# --------------------------------------------------------------------------
# arithmetic / sign
# --------------------------------------------------------------------------


def test_tight_labor_is_reaccelerating() -> None:
    # score +10 -> change = 0.006 * 10 = 0.06pp > 0.05 -> reaccelerating.
    res = _run(10.0)
    assert res.value_dict()["projected_change_pp"] == pytest.approx(0.06, abs=1e-9)
    assert res.value_dict()["direction"] == "reaccelerating"
    assert res.value_dict()["labor_score"] == 10.0


def test_loose_labor_is_decelerating() -> None:
    # score -10 -> change = -0.06pp < -0.05 -> decelerating (sign preserved).
    res = _run(-10.0)
    assert res.value_dict()["projected_change_pp"] == pytest.approx(-0.06, abs=1e-9)
    assert res.value_dict()["direction"] == "decelerating"


def test_mid_score_is_stable() -> None:
    # score +5 -> change = 0.03pp -> inside dead band -> stable.
    res = _run(5.0)
    assert res.value_dict()["direction"] == "stable"


# --------------------------------------------------------------------------
# strict boundary partitioning
# --------------------------------------------------------------------------


def test_boundary_strict_top() -> None:
    # change_pp = 0.006 * score; just above 0.05 -> reaccel; just below -> stable.
    assert _run(8.34).value_dict()["direction"] == "reaccelerating"
    assert _run(8.33).value_dict()["direction"] == "stable"


def test_boundary_strict_bottom() -> None:
    assert _run(-8.34).value_dict()["direction"] == "decelerating"
    assert _run(-8.33).value_dict()["direction"] == "stable"


def test_exact_boundary_falls_to_stable() -> None:
    # score that yields change_pp exactly ~0.05 -> stable (boundary belongs to stable).
    res = _run(0.05 / 0.006)
    assert abs(res.value_dict()["projected_change_pp"] - 0.05) < 1e-9
    assert res.value_dict()["direction"] == "stable"


# --------------------------------------------------------------------------
# reachability across the declared score range
# --------------------------------------------------------------------------


def test_all_three_directions_reachable() -> None:
    seen = set()
    for s in range(-100, 101):
        seen.add(_run(float(s)).value_dict()["direction"])
    assert seen == {"reaccelerating", "stable", "decelerating"}


# --------------------------------------------------------------------------
# fiscal scaling: magnitude only, never sign
# --------------------------------------------------------------------------


def test_fiscal_scales_magnitude_not_sign() -> None:
    # stable at score +6 (0.036pp); fiscal 1.5x -> 0.054pp -> crosses to reaccel.
    base = _run(6.0)
    scaled = _run(6.0, fiscal=True)
    assert base.value_dict()["direction"] == "stable"
    assert scaled.value_dict()["direction"] == "reaccelerating"
    assert scaled.value_dict()["fiscal_scale_applied"] == 1.5
    # negative score keeps negative sign under fiscal:
    neg = _run(-6.0)
    neg_scaled = _run(-6.0, fiscal=True)
    assert neg.value_dict()["direction"] == "stable"
    assert neg_scaled.value_dict()["direction"] == "decelerating"
    assert neg_scaled.value_dict()["projected_change_pp"] < 0


# --------------------------------------------------------------------------
# growth corroboration + independence-count confidence
# --------------------------------------------------------------------------


def test_agreement_yields_independence_credit() -> None:
    # tight labor (+10) + expanding growth (+1) -> "agrees_expansion" -> indep 1.
    res = _run(10.0, growth_value=1.0)
    assert res.value_dict()["growth_corroboration"] == "agrees_expansion"
    # 0.70 - 0.20 - 0.20 + 0.05 = 0.35
    assert res.confidence == pytest.approx(0.350, abs=1e-9)


def test_disagreement_also_yields_independence_credit() -> None:
    # tight labor (+10) + contracting growth (-1) -> disagrees, but still indep 1
    # (F-INTRAJ-002 FIX: a disagreeing independent family counts).
    res = _run(10.0, growth_value=-1.0)
    assert res.value_dict()["growth_corroboration"] == "disagrees_tight_labor_weak_growth"
    assert res.confidence == pytest.approx(0.350, abs=1e-9)


def test_unavailable_growth_no_independence_credit() -> None:
    # growth value is not a number -> "unavailable" -> indep 0 -> 0.30.
    res = project_inflation_trajectory(
        InflationTrajectoryInputs(
            growth=_mr("not-a-number"),  # type: ignore[arg-type]
            labor=_mr(10.0),
            inflation=_mr(3.5),
        )
    )
    assert res.value_dict()["growth_corroboration"] == "unavailable"
    assert res.confidence == pytest.approx(0.300, abs=1e-9)


def test_flat_score_is_not_directional() -> None:
    # score exactly 0 -> tight_labor None -> "not_directional" -> indep 0 -> 0.30.
    res = _run(0.0)
    assert res.value_dict()["growth_corroboration"] == "not_directional"
    assert res.confidence == pytest.approx(0.300, abs=1e-9)
    assert res.value_dict()["direction"] == "stable"


def test_labor_warnings_lower_confidence() -> None:
    # agrees + labor carries a warning -> data_quality flag -0.25 -> 0.10.
    res = _run(10.0, growth_value=1.0, labor_warnings=["dq flag"])
    assert res.confidence == pytest.approx(0.100, abs=1e-9)


# --------------------------------------------------------------------------
# input validation & provenance
# --------------------------------------------------------------------------


def test_bool_score_rejected() -> None:
    # A bool is refused by the TYPE guard (isinstance(x, bool)), not the range
    # check, so the rejection is a TypeError rather than a ValueError.
    with pytest.raises(TypeError):
        _run(True)


def test_out_of_range_score_rejected() -> None:
    with pytest.raises(ValueError):
        _run(150.0)
    with pytest.raises(ValueError):
        _run(-150.0)


def test_non_finite_score_rejected() -> None:
    # nan/inf survive the isinstance(int,float) check but fail the range check.
    with pytest.raises(ValueError):
        _run(float("nan"))
    with pytest.raises(ValueError):
        _run(float("inf"))


def test_non_numeric_inflation_level_reported_as_none() -> None:
    res = project_inflation_trajectory(
        InflationTrajectoryInputs(
            growth=_mr(1.0),
            labor=_mr(10.0),
            inflation=_mr("n/a"),  # type: ignore[arg-type]
        )
    )
    assert res.value_dict()["inflation_level"] is None
    assert any("not a number" in w for w in res.warnings)


def test_inputs_used_lists_all_four() -> None:
    res = _run(10.0)
    assert set(res.inputs_used) == {
        "growth.value",
        "labor.value",
        "inflation.value",
        "fiscal_response_active",
    }


def test_inflation_level_reported() -> None:
    res = _run(10.0, inflation_value=3.7)
    assert res.value_dict()["inflation_level"] == pytest.approx(3.7, abs=1e-9)
