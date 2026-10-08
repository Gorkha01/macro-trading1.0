"""Hand-computed verification suite for Module 7.3 — the leading-indicator PROXY.

Every expected number is derived by hand from the module's own stated arithmetic
and cross-checked against the config threshold, never copied from the code. The
module is deliberately NOT the Conference Board LEI (licensed, unreachable), so
its own documented formulas are the ground truth; the official LEI's six-month
growth framing is consistent with the six-month annualized horizon used here.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.lei_proxy import (
    LeadingIndicatorProxyInputs,
    _breadth_null_rate,
    leading_indicator_proxy,
)

FOUR_DECLINING = {
    "initial_claims_inverted": -8.0,
    "building_permits": -4.0,
    "curve_slope_10y3m": -12.0,
    "sp500": -6.0,
}


def _run(components: dict[str, float], weights: dict[str, float] | None = None) -> ModelResult:
    return leading_indicator_proxy(
        LeadingIndicatorProxyInputs(components=components, weights=weights)
    )


# ---------------------------------------------------------------------------
# Config bridging — the breadth threshold must come from config (LAW 1)
# ---------------------------------------------------------------------------
def test_breadth_threshold_comes_from_config() -> None:
    assert get_settings().leading_indicator.breadth_threshold_value == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# The module's three documented hand calculations
# ---------------------------------------------------------------------------
def test_golden_case_four_falling_equal_weight() -> None:
    # composite = 0.25 * (-8 -4 -12 -6) = -7.50 ; breadth 4/4 = 1.00
    res = _run(FOUR_DECLINING)
    v = res.value_dict()
    assert v["composite_6mo_annualized"] == pytest.approx(-7.50)
    assert v["breadth_declining"] == pytest.approx(1.00)
    assert v["n_declining"] == 4 and v["n_components"] == 4
    assert v["broad_based"] is True
    assert v["lead_direction"] == "broad_based_decline"
    assert v["equal_weighted"] is True


def test_concentrated_decline_is_not_broad_based() -> None:
    # claims -20, permits +1, curve +0.5, equity +2
    # composite = 0.25 * (-20 + 1 + 0.5 + 2) = -4.125 ; breadth 1/4 = 0.25
    res = _run(
        {
            "initial_claims_inverted": -20.0,
            "building_permits": 1.0,
            "curve_slope_10y3m": 0.5,
            "sp500": 2.0,
        }
    )
    v = res.value_dict()
    # Exact composite is -4.125. Published value is round(-4.125, 2) = -4.12
    # (Python's round() is half-to-even; the docstring's prose rounds half-up to
    # -4.125 -> -4.13). The arithmetic is exact; only the 2-dp display differs.
    assert v["composite_6mo_annualized"] == pytest.approx(-4.125, abs=0.005)
    assert v["breadth_declining"] == pytest.approx(0.25)
    assert v["broad_based"] is False
    assert v["lead_direction"] == "mixed"


def test_advance_requires_the_composite_to_agree() -> None:
    # claims -30, permits +1, curve +0.5, equity +2
    # composite = 0.25 * (-30 +1 +0.5 +2) = -6.625 (NEGATIVE)
    # advance_breadth = 3/4 = 0.75 >= 0.6, but composite < 0 -> must be "mixed",
    # not "broad_based_advance". A breadth-only test would contradict the headline.
    res = _run(
        {
            "initial_claims_inverted": -30.0,
            "building_permits": 1.0,
            "curve_slope_10y3m": 0.5,
            "sp500": 2.0,
        }
    )
    v = res.value_dict()
    # Exact composite is -6.625; published as round(-6.625, 2) = -6.62 (half-to-even).
    assert v["composite_6mo_annualized"] == pytest.approx(-6.625, abs=0.005)
    assert v["lead_direction"] == "mixed"


def test_advance_when_breadth_and_composite_agree() -> None:
    # Three rising, sum positive: 0.25 * (1 + 2 + 3 - 1) = 1.25 > 0
    res = _run({"a": 1.0, "b": 2.0, "c": 3.0, "d": -1.0})
    v = res.value_dict()
    assert v["composite_6mo_annualized"] == pytest.approx(1.25)
    assert v["lead_direction"] == "broad_based_advance"


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
def test_supplied_weights_are_used_and_flagged_not_equal() -> None:
    # weights 0.5/0.25/0.15/0.10 over -8,-4,-12,-6:
    # -4.0 -1.0 -1.8 -0.6 = -7.4
    res = _run(
        FOUR_DECLINING,
        weights={
            "initial_claims_inverted": 0.5,
            "building_permits": 0.25,
            "curve_slope_10y3m": 0.15,
            "sp500": 0.10,
        },
    )
    v = res.value_dict()
    assert v["composite_6mo_annualized"] == pytest.approx(-7.4)
    assert v["equal_weighted"] is False
    assert "weights" in res.inputs_used


def test_weights_must_cover_every_component() -> None:
    with pytest.raises(ValueError, match="weights omits component"):
        LeadingIndicatorProxyInputs(components={"a": -1.0, "b": -2.0}, weights={"a": 0.5})


def test_weights_reject_unknown_component() -> None:
    with pytest.raises(ValueError, match="absent from 'components'"):
        LeadingIndicatorProxyInputs(components={"a": -1.0}, weights={"a": 1.0, "ghost": 1.0})


def test_weights_reject_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        LeadingIndicatorProxyInputs(components={"a": -1.0, "b": 2.0}, weights={"a": -1.0, "b": 2.0})


def test_weights_reject_all_zero() -> None:
    with pytest.raises(ValueError, match="every weight is zero"):
        LeadingIndicatorProxyInputs(components={"a": -1.0, "b": 2.0}, weights={"a": 0.0, "b": 0.0})


def test_weights_need_not_sum_to_one() -> None:
    # Weights are a split of influence, not probabilities; they are used as given.
    # 2.0*(-8) + 1.0*(-4) + 1.0*(-12) + 1.0*(-6) = -38.0
    res = _run(
        FOUR_DECLINING,
        weights={
            "initial_claims_inverted": 2.0,
            "building_permits": 1.0,
            "curve_slope_10y3m": 1.0,
            "sp500": 1.0,
        },
    )
    assert res.value_dict()["composite_6mo_annualized"] == pytest.approx(-38.0)


# ---------------------------------------------------------------------------
# Breadth: the three-of-four boundary (ceil(0.6*4)=3)
# ---------------------------------------------------------------------------
def test_three_of_four_is_broad_based_two_is_not() -> None:
    three = _run({"a": -1.0, "b": -2.0, "c": -3.0, "d": 4.0})
    assert three.value_dict()["breadth_declining"] == pytest.approx(0.75)
    assert three.value_dict()["broad_based"] is True
    two = _run({"a": -1.0, "b": -2.0, "c": 3.0, "d": 4.0})
    assert two.value_dict()["breadth_declining"] == pytest.approx(0.50)
    assert two.value_dict()["broad_based"] is False


def test_single_component_breadth_is_all_or_nothing() -> None:
    down = _run({"only": -5.0})
    assert down.value_dict()["breadth_declining"] == pytest.approx(1.0)
    assert down.value_dict()["broad_based"] is True
    up = _run({"only": 5.0})
    assert up.value_dict()["breadth_declining"] == pytest.approx(0.0)
    assert up.value_dict()["lead_direction"] == "broad_based_advance"


def test_zero_change_is_neither_declining_nor_advancing() -> None:
    # A 0.0 component counts in neither `change < 0` nor `change > 0`.
    res = _run({"a": -1.0, "b": -1.0, "c": 0.0, "d": 1.0})
    assert res.value_dict()["n_declining"] == 2
    assert res.value_dict()["breadth_declining"] == pytest.approx(0.5)


def test_fewer_than_three_components_warns() -> None:
    res = _run({"a": -1.0, "b": -2.0})
    assert any("Only 2 component(s) supplied" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# The D-029 null-model base rate (combinatorial, not a hit rate)
# ---------------------------------------------------------------------------
def test_null_rate_matches_binomial_arithmetic() -> None:
    # n=4, p=0.5: P(X >= 3) = (4 + 1)/16 = 5/16 = 0.3125
    assert _breadth_null_rate(4, 0.6) == pytest.approx(0.3125)
    # n=1: required = ceil(0.6) = 1 -> 1/2 = 0.5
    assert _breadth_null_rate(1, 0.6) == pytest.approx(0.5)
    # n=2: required = ceil(1.2) = 2 -> 1/4 = 0.25
    assert _breadth_null_rate(2, 0.6) == pytest.approx(0.25)
    # n=10: required = 6 -> (210+120+45+10+1)/1024 = 386/1024 = 0.37695
    assert _breadth_null_rate(10, 0.6) == pytest.approx(386 / 1024, abs=1e-9)


def test_null_rate_edge_cases() -> None:
    # threshold 0 -> required 0 <= 0 -> rate 1.0 (trivially satisfied)
    assert _breadth_null_rate(4, 0.0) == 1.0
    # threshold 1.0 -> required = n -> 1/2**n
    assert _breadth_null_rate(4, 1.0) == pytest.approx(1 / 16)
    # threshold above 1 -> required > n -> 0.0 (impossible)
    assert _breadth_null_rate(4, 1.5) == 0.0


def test_null_rate_travels_on_the_output() -> None:
    res = _run(FOUR_DECLINING)
    assert res.value_dict()["breadth_threshold"] == pytest.approx(0.6)
    assert res.value_dict()["breadth_null_rate"] == pytest.approx(0.3125)
    assert any("COMBINATORIAL null frequency" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# Non-finite refusal — a nan must not silently count as "did not decline"
# ---------------------------------------------------------------------------
def test_non_finite_component_refused() -> None:
    with pytest.raises(ValueError, match=r"non-finite|is nan"):
        LeadingIndicatorProxyInputs(components={"a": -1.0, "b": float("nan")})
    with pytest.raises(ValueError):
        LeadingIndicatorProxyInputs(components={"a": float("inf")})


def test_empty_components_rejected() -> None:
    with pytest.raises(ValueError):
        LeadingIndicatorProxyInputs(components={})


# ---------------------------------------------------------------------------
# Contract fields, confidence and the "not LEI" disclaimer
# ---------------------------------------------------------------------------
def test_confidence_is_computed_not_asserted() -> None:
    # base 0.70 - 0.20 heuristic - 0.20 unobservable = 0.30
    res = _run(FOUR_DECLINING)
    assert res.confidence == pytest.approx(0.30)
    # It must NOT vary with the reading (the spec's 0.5/0.3 literal is removed).
    other = _run({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0})
    assert other.confidence == pytest.approx(0.30)


def test_not_lei_disclaimer_present() -> None:
    res = _run(FOUR_DECLINING)
    assert any("NOT the Conference Board LEI" in w for w in res.warnings)
    assert "PROXY" in res.interpretation or "proxy" in res.interpretation


def test_all_lead_direction_members_producible() -> None:
    # D-045a: every member of the LeadDirection Literal must be producible.
    decline = _run(FOUR_DECLINING)
    mixed = _run({"a": -20.0, "b": 1.0, "c": 0.5, "d": 2.0})
    advance = _run({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0})
    produced = {
        decline.value_dict()["lead_direction"],
        mixed.value_dict()["lead_direction"],
        advance.value_dict()["lead_direction"],
    }
    assert produced == {"broad_based_decline", "mixed", "broad_based_advance"}


def test_value_carries_all_documented_keys() -> None:
    res = _run(FOUR_DECLINING)
    assert set(res.value_dict().keys()) == {
        "composite_6mo_annualized",
        "breadth_declining",
        "n_components",
        "n_declining",
        "broad_based",
        "lead_direction",
        "breadth_threshold",
        "breadth_null_rate",
        "equal_weighted",
    }
