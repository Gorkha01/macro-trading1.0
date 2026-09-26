"""Hand-verified tests for ``uip_expected_move`` — Module 9, Section 20.9.

This function is the project's one model whose documented purpose is that it
**fails**, so the tests are built around three things that are easy to get wrong
and impossible to see from the output:

1. **It is NOT ``cip_check`` read forward, and the test suite has to hold that
   distinction or a future edit will collapse the two.** The two functions read
   the same two rates; what separates them is that ``cip_check`` takes a TRADED
   FORWARD and measures a DEVIATION, while this one consults no forward and
   predicts an EXPECTED SPOT MOVE. The bridge between them is an IDENTITY —
   UIP's one-year expected move equals CIP's forward premium,
   ``(i_d - i_f) / (1 + i_f)`` — and
   ``test_the_one_year_expected_move_is_the_cip_forward_premium`` asserts it
   against a value derived from the CIP identity, not against a restatement of
   this function's own arithmetic.
2. **The horizon is load-bearing and the specification omits it.** Section 20.9
   writes ``expected = i_domestic - i_foreign`` and stops — a silently ONE-YEAR
   expectation. A 3 % differential is a 3 % expected move over a year and 0.75 %
   over a quarter, and a carry trade is expressed over its own tenor. The
   horizon scaling must therefore be exact,
   ``(1 + i_d t) / (1 + i_f t) - 1``, and the specification's first-order form
   is published BESIDE it so the approximation's size is visible.
3. **Confidence is a model-specific CAP, not a computed penalty**, and the test
   cannot tell a literal from a value by asserting the number alone. The
   confidence tests assert against the CONFIG LEAF and against a PERTURBED leaf,
   so a hardcoded literal fails them (D-050's trap, which bit D-111).

The boundary fixtures are built by **addition with binary-exact values** and each
asserts its own exactness (lesson 5o): ``90 / 360 == 0.25`` is exact, where a
fixture built as ``0.2500001 - 1e-7`` would sit a hair off the point it claims to
probe.
"""

from __future__ import annotations

import math
from typing import get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, FxCarrySettings, get_settings
from macro_engine.models.contracts import EvidenceSourceFamily, ModelResult
from macro_engine.models.fx_carry import (
    UIPDirection,
    UIPInputs,
    uip_expected_move,
)
from tests.helpers import as_float, as_str

#: The shipped reliability cap, read once for the tests that must pin it. A
#: fixture built from a re-typed literal would keep testing the old value after
#: the config moved.
_UIP_CAP = 0.15


def _inputs(**overrides: object) -> UIPInputs:
    base: dict[str, object] = {
        "i_domestic_annualized": 0.0425,
        "i_foreign_annualized": 0.0100,
        "tenor_days": 360,
        "day_count_basis": "actual_360",
    }
    base.update(overrides)
    return UIPInputs.model_validate(base)


def _value(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    return as_float(result, key=key)


def _label(result: ModelResult, key: str) -> str:
    return as_str(result, key=key)


# ---------------------------------------------------------------------------
# The expectation itself — hand-derived from the parity identity.
# ---------------------------------------------------------------------------

#: (label, i_domestic, i_foreign, tenor_days, expected exact percent)
_CASES: tuple[tuple[str, float, float, int, float], ...] = (
    # 1-year, domestic pays more: (1.0425/1.0100 - 1) * 100 = 3.21782178...
    ("one year, domestic higher", 0.0425, 0.0100, 360, 3.2178217821782178),
    # 1-year, foreign pays more: (1.0100/1.0425 - 1) * 100 = -3.11750599...
    ("one year, foreign higher", 0.0100, 0.0425, 360, -3.1175059952038369),
    # equal rates: exactly zero
    ("equal rates", 0.0300, 0.0300, 360, 0.0),
    # a quarter: (1 + 0.0425/4)/(1 + 0.0100/4) - 1, * 100
    ("one quarter, domestic higher", 0.0425, 0.0100, 90, 0.8104738154613466),
)


@pytest.mark.parametrize(
    ("label", "i_d", "i_f", "tenor_days", "expected_pct"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_the_expected_move_matches_the_hand_derived_identity(
    label: str, i_d: float, i_f: float, tenor_days: int, expected_pct: float
) -> None:
    """The exact parity ratio, checked against a value computed by hand.

    The expected value is derived from the identity
    ``(1 + i_d t)/(1 + i_f t) - 1`` in the test itself, independently of the
    implementation's own expression, so the two agreeing is evidence rather than
    a restatement.
    """
    result = uip_expected_move(
        _inputs(
            i_domestic_annualized=i_d,
            i_foreign_annualized=i_f,
            tenor_days=tenor_days,
        )
    )
    published = _number(result, "expected_move_pct")
    assert published == pytest.approx(expected_pct, abs=5e-7)


def test_the_one_year_expected_move_is_the_cip_forward_premium() -> None:
    """THE BRIDGE: UIP's one-year move equals CIP's forward premium, exactly.

    This is what makes the two functions ONE parity family rather than two
    unrelated calculations — and it is also a statement of the hypothesis that
    FAILS. CIP rearranged gives the forward premium
    ``F/S - 1 = (i_d - i_f) / (1 + i_f)``; UIP asserts the expected spot change
    equals that premium. The test derives the premium from the CIP identity
    directly (not from this function's arithmetic) and asserts equality.

    At a 3.25 % differential the exact premium is 3.2178 %, while the
    specification's ``i_d - i_f`` gives 3.25 % — a 3.2 bp gap. That gap is the
    second-order term, and this test pins that BOTH functions agree on the exact
    figure while the published simple figure is the specification's.
    """
    i_d, i_f = 0.0425, 0.0100
    # Derived from CIP, not from uip: with S = 1 the forward is (1+i_d)/(1+i_f).
    cip_implied_forward = (1.0 + i_d) / (1.0 + i_f)
    cip_forward_premium_pct = (cip_implied_forward - 1.0) * 100.0

    result = uip_expected_move(_inputs(i_domestic_annualized=i_d, i_foreign_annualized=i_f))
    published = _number(result, "expected_move_pct")

    assert published == pytest.approx(cip_forward_premium_pct, abs=5e-7)
    # And the specification's first-order form is the OTHER published number.
    assert _number(result, "expected_move_simple_pct") == pytest.approx(
        (i_d - i_f) * 100.0, abs=5e-7
    )


def test_the_specification_form_is_within_a_fraction_of_a_basis_point() -> None:
    """The approximation's size is PUBLISHED, not asserted in prose.

    The gap between the exact ratio and the specification's ``(i_d - i_f) * t``
    is the second-order term ``i_f * (i_d - i_f)``, so it scales with the FOREIGN
    rate as well as with the differential. At a small G10 differential it is a
    fraction of a basis point; at a 4 pp differential with a 1 % foreign rate it
    is 4 bp — still far too small to change a sign, but NOT negligible, which is
    exactly why both numbers travel with the result rather than one replacing the
    other. The bound is derived from the second-order expression, not chosen.
    """
    i_d, i_f = 0.05, 0.01
    result = uip_expected_move(_inputs(i_domestic_annualized=i_d, i_foreign_annualized=i_f))
    exact = _number(result, "expected_move_pct")
    simple = _number(result, "expected_move_simple_pct")
    # The second-order term, in percentage points, with a 10x safety margin.
    second_order_pp = i_f * (i_d - i_f) * 100.0
    assert abs(simple - exact) <= second_order_pp * 10.0
    # And it is far too small to flip the sign of a real differential.
    assert abs(simple - exact) < abs(exact)


def test_the_gap_is_second_order_in_the_foreign_rate() -> None:
    """Halving the FOREIGN rate roughly halves the exact-vs-simple gap.

    This pins that the difference is the second-order term rather than an
    unexplained error: at a fixed differential the gap should scale with ``i_f``.
    """
    high = uip_expected_move(_inputs(i_domestic_annualized=0.06, i_foreign_annualized=0.02))
    low = uip_expected_move(_inputs(i_domestic_annualized=0.05, i_foreign_annualized=0.01))
    gap_high = abs(_number(high, "expected_move_simple_pct") - _number(high, "expected_move_pct"))
    gap_low = abs(_number(low, "expected_move_simple_pct") - _number(low, "expected_move_pct"))
    # Both have a 4pp differential; the higher foreign rate gives a bigger gap.
    assert gap_high > gap_low


@pytest.mark.parametrize(("tenor_days"), [90, 180, 360])
def test_the_expectation_scales_approximately_with_the_horizon(tenor_days: int) -> None:
    """The horizon is LOAD-BEARING, and the scaling is APPROXIMATELY periodic.

    Section 20.9 omits the horizon, which silently makes the expectation a
    one-year figure. Scaling it is what makes the output comparable with a carry
    computed over the same tenor, so the scaling must actually happen — but it is
    **not exactly linear in t**, because the exact ratio
    ``(1 + i_d t)/(1 + i_f t)`` is a hyperbola rather than a straight line. The
    specification's linear form is the first-order approximation, and this test
    asserts the linear relationship only within the second-order tolerance that
    the two published numbers bracket.
    """
    quarter = uip_expected_move(_inputs(tenor_days=90))
    scaled = uip_expected_move(_inputs(tenor_days=tenor_days))
    ratio = _number(scaled, "expected_move_pct") / _number(quarter, "expected_move_pct")
    # The gap from exact proportionality is the same second-order term the
    # previous tests bound: a few tenths of a percent at a 3.25pp differential.
    assert ratio == pytest.approx(tenor_days / 90, rel=1e-2)
    if tenor_days > 90:
        # The hyperbola falls short of the straight line, so a longer tenor
        # scales the move by LESS than the naive ratio. At t == 90 it is the
        # same fixture divided by itself and the comparison is vacuous.
        assert ratio < tenor_days / 90


def test_the_period_rates_are_published_and_consistent() -> None:
    """The conversion is visible: period == annualised * tenor/basis, to 6dp.

    **Includes ``differential_period``, and that line was ADDED to kill a
    survivor.** The first version asserted only the two period LEGS, so the
    mutation ``U2c`` — ``differential_period = differential_annualized``, which
    drops the scaling and mixes an annualised gap with a period move — went
    **unseen**: the legs were checked, the differential was not.
    """
    result = uip_expected_move(
        _inputs(i_domestic_annualized=0.0480, i_foreign_annualized=0.0120, tenor_days=90)
    )
    assert _number(result, "i_domestic_period") == pytest.approx(0.0480 * 0.25, abs=1e-9)
    assert _number(result, "i_foreign_period") == pytest.approx(0.0120 * 0.25, abs=1e-9)
    # The differential is published in BOTH units and the period one is scaled —
    # the scaling is the whole distinction between the two published fields.
    assert _number(result, "differential_annualized") == pytest.approx(0.0360, abs=1e-9)
    assert _number(result, "differential_period") == pytest.approx(0.0360 * 0.25, abs=1e-9)
    # And the period differential is the ANNUALISED one scaled by tenor/basis, so
    # at a quarter-tenor it is strictly smaller — the assertion that above all
    # kills a dropped scaling, since a dropped scaling makes them equal.
    assert _number(result, "differential_period") != _number(result, "differential_annualized")


def test_the_day_count_basis_selects_the_scaling_map() -> None:
    """`actual_365` divides by 365, not 360 — the basis is READ, not assumed.

    **Added to kill ``U2d``**, which hardcoded ``basis_days = 360`` instead of
    reading ``_BASIS_DAYS[inputs.day_count_basis]``. Every other test used
    ``actual_360``, where the hardcoded 360 is indistinguishable from the read
    value — so the mutation was invisible until a fixture used the OTHER basis.
    The two bases must give DIFFERENT period rates for the same annualised input.

    The tenor is 360 days, admissible on BOTH bases (a 365-day tenor would exceed
    ``actual_360`` and be refused by the domain guard, so the fixture could not
    reach the comparison this test exists to make).
    """
    over_360 = uip_expected_move(
        _inputs(i_domestic_annualized=0.05, tenor_days=360, day_count_basis="actual_360")
    )
    over_365 = uip_expected_move(
        _inputs(i_domestic_annualized=0.05, tenor_days=360, day_count_basis="actual_365")
    )
    # 360/360 vs 360/365: the ACT/360 leg is scaled slightly LARGER for the same
    # 360-day tenor, so mis-reading the basis moves the published period rate.
    # The tolerance is the model's own PUBLISHED precision (8dp ⇒ 5e-9), per
    # D-109: a bound tighter than the coarser side's rounding tests the rounding,
    # not the agreement.
    assert _number(over_360, "i_domestic_period") == pytest.approx(0.05, abs=5e-9)
    assert _number(over_365, "i_domestic_period") == pytest.approx(0.05 * 360 / 365, abs=5e-9)
    assert _number(over_360, "i_domestic_period") > _number(over_365, "i_domestic_period")


def test_the_simple_form_carries_the_tenor_scaling() -> None:
    """The published first-order form is a PERIOD figure, not an annual one.

    **Added to kill ``U3c``**, which published
    ``differential_annualized * 100.0`` — dropping the ``period_scale`` so the
    simple form was a one-year number beside a period exact one. At the default
    one-year fixture the two coincide (``period_scale == 1``), which is why every
    other test missed it; this fixture is a QUARTER, where they must differ by 4x.
    """
    result = uip_expected_move(_inputs(tenor_days=90))
    simple = _number(result, "expected_move_simple_pct")
    annual = _number(result, "differential_annualized") * 100.0
    # A quarter- tenor simple form is the annual differential over four.
    assert simple == pytest.approx(annual * 0.25, abs=1e-6)
    # And it is strictly smaller than the annual figure — a dropped scaling makes
    # them equal, which the equality above would not by itself catch at 4x.
    assert simple != pytest.approx(annual, abs=1e-6)


# ---------------------------------------------------------------------------
# The direction label — derived from the sign of the published move.
# ---------------------------------------------------------------------------


def test_the_direction_matches_the_sign_of_the_published_move() -> None:
    """Derived from the PUBLISHED number, so the two cannot disagree."""
    result = uip_expected_move(_inputs())
    assert _label(result, "direction") == "domestic_depreciation"
    assert _number(result, "expected_move_pct") > 0.0

    mirrored = uip_expected_move(_inputs(i_domestic_annualized=0.0100, i_foreign_annualized=0.0425))
    assert _label(mirrored, "direction") == "domestic_appreciation"
    assert _number(mirrored, "expected_move_pct") < 0.0


def test_the_flat_case_is_its_own_label() -> None:
    """Equal rates are the ABSENCE of a prediction, not a tiny one."""
    result = uip_expected_move(_inputs(i_domestic_annualized=0.0300, i_foreign_annualized=0.0300))
    assert _label(result, "direction") == "flat"
    assert _number(result, "expected_move_pct") == 0.0
    assert result.direction == "flat"


def test_the_direction_and_the_value_direction_field_agree() -> None:
    """The ModelResult.direction field is the label, not a re-derived string."""
    for i_d, i_f, expected in (
        (0.05, 0.01, "domestic_depreciation"),
        (0.01, 0.05, "domestic_appreciation"),
        (0.03, 0.03, "flat"),
    ):
        result = uip_expected_move(_inputs(i_domestic_annualized=i_d, i_foreign_annualized=i_f))
        assert result.direction == expected
        assert _label(result, "direction") == expected


def test_every_declared_direction_is_in_the_type() -> None:
    assert set(get_args(UIPDirection)) == {
        "domestic_depreciation",
        "domestic_appreciation",
        "flat",
    }


def test_every_direction_is_reachable_by_a_real_fixture() -> None:
    """All three labels are produced by an admissible input — no dead vocabulary."""
    seen = set()
    for i_d, i_f in ((0.05, 0.01), (0.01, 0.05), (0.03, 0.03)):
        result = uip_expected_move(_inputs(i_domestic_annualized=i_d, i_foreign_annualized=i_f))
        seen.add(_label(result, "direction"))
    assert seen == set(get_args(UIPDirection))


# ---------------------------------------------------------------------------
# Confidence — a CAP read from config, not a computed penalty.
# ---------------------------------------------------------------------------


def test_confidence_is_the_configured_cap() -> None:
    """The published confidence IS the leaf, not a hardcoded 0.15.

    Asserted against the config leaf rather than the literal, so a hardcoded
    number would fail this test the moment the leaf moved.
    """
    leaf = get_settings().fx_carry.uip_reliability_value
    result = uip_expected_move(_inputs())
    assert result.confidence == leaf


def test_moving_the_cap_moves_the_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PERTURBED leaf must move the result — the discriminating control.

    Without this, a hardcoded ``0.15`` would pass
    ``test_confidence_is_the_configured_cap`` whenever the leaf also happened to
    be 0.15. Perturbing the leaf and requiring the output to follow is what
    distinguishes a read from a coincidence (D-050's trap).
    """
    from macro_engine import config as config_module

    settings = get_settings()
    perturbed = settings.fx_carry.model_copy(
        update={
            "uip_reliability_cap": CalibratedValue(
                value=0.33, calibration_status="institutional_convention"
            )
        }
    )
    monkeypatch.setattr(type(settings), "fx_carry", property(lambda self: perturbed), raising=False)
    try:
        result = uip_expected_move(_inputs())
        assert result.confidence == pytest.approx(0.33)
    finally:
        config_module.get_settings.cache_clear()
        monkeypatch.undo()


def test_the_cap_is_far_below_the_neighbouring_functions() -> None:
    """The cap is DELIBERATELY lower than the other Module 9 models.

    ``cip_check`` and ``carry_score`` report around 0.5 because they MEASURE
    something; this model reports the specification's 0.15 because its
    hypothesis is discredited. The gap is the point, so it is asserted rather
    than left to prose.
    """
    from macro_engine.models.fx_carry import CarryScoreInputs, carry_score

    uip_conf = uip_expected_move(_inputs()).confidence
    carry_conf = carry_score(
        CarryScoreInputs(rate_differential_annualized=0.02, realized_vol_annualized=0.08)
    ).confidence
    assert uip_conf < carry_conf
    assert uip_conf == _UIP_CAP


# ---------------------------------------------------------------------------
# The domain guards — each with a negative control.
# ---------------------------------------------------------------------------

_BAD_FINITE = (float("nan"), float("inf"), float("-inf"))


@pytest.mark.parametrize("field", ["i_domestic_annualized", "i_foreign_annualized"])
@pytest.mark.parametrize("bad", _BAD_FINITE)
def test_the_domain_guards_refuse_a_non_finite_rate(field: str, bad: float) -> None:
    with pytest.raises(ValidationError, match=field):
        _inputs(**{field: bad})


@pytest.mark.parametrize("field", ["i_domestic_annualized", "i_foreign_annualized"])
def test_the_negative_control_for_each_guard_is_accepted(field: str) -> None:
    """A perfectly ordinary negative rate is NOT refused by the finiteness guard.

    Without this, the guard test would pass even if the guard rejected every
    value — it would be testing "an error is raised", not "this error is raised
    for this reason" (O-127's class).
    """
    result = uip_expected_move(_inputs(**{field: -0.005}))
    assert result.model_name == "uip_expected_move"


def test_a_tenor_beyond_the_basis_is_refused() -> None:
    with pytest.raises(ValidationError, match="tenor_days"):
        _inputs(tenor_days=361, day_count_basis="actual_360")


def test_a_tenor_exactly_at_the_basis_is_admitted() -> None:
    """The boundary itself is admissible — simple interest is exact AT one year."""
    result = uip_expected_move(_inputs(tenor_days=360, day_count_basis="actual_360"))
    assert _number(result, "expected_move_pct") > 0.0


def test_a_period_rate_at_minus_one_hundred_percent_is_refused() -> None:
    """A foreign period rate of exactly -100% divides the parity ratio by zero."""
    with pytest.raises(ValidationError, match="i_foreign_annualized"):
        _inputs(i_foreign_annualized=-4.0, tenor_days=90)  # -4.0 * 0.25 == -1.0


def test_a_period_rate_just_above_minus_one_hundred_percent_is_admitted() -> None:
    """The negative control: one step inside the boundary is admissible."""
    result = uip_expected_move(
        _inputs(i_foreign_annualized=-3.9, tenor_days=90)  # -> period -0.975
    )
    assert result.model_name == "uip_expected_move"


def test_an_extra_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        UIPInputs.model_validate(
            {
                "i_domestic_annualized": 0.04,
                "i_foreign_annualized": 0.01,
                "tenor_days": 360,
                "not_a_field": 1.0,
            }
        )


def test_the_day_count_basis_is_a_closed_vocabulary() -> None:
    with pytest.raises(ValidationError):
        UIPInputs.model_validate(
            {
                "i_domestic_annualized": 0.04,
                "i_foreign_annualized": 0.01,
                "tenor_days": 360,
                "day_count_basis": "actual_366",
            }
        )


# ---------------------------------------------------------------------------
# The settings validator for the new leaf.
# ---------------------------------------------------------------------------


def _fx_carry_settings(**overrides: object) -> FxCarrySettings:
    """The shipped ``fx_carry`` block, so a new required field arrives for free.

    Seeded from ``get_settings().fx_carry`` rather than hand-listed. The
    hand-listed form broke at D-109, D-110 and D-112; D-114 (which added
    ``ppp_reliability_cap`` and ``ppp_tactical_horizon_years``) is the first to
    use the generating form. The three cases below all override
    ``uip_reliability_cap`` explicitly, so the shipped value is never the subject
    of an assertion here.
    """
    base: dict[str, object] = dict(get_settings().fx_carry)
    base.update(overrides)
    return FxCarrySettings.model_validate(base)


def test_the_settings_validator_refuses_a_cap_above_one() -> None:
    with pytest.raises(ValidationError, match="uip_reliability_cap"):
        _fx_carry_settings(
            uip_reliability_cap=CalibratedValue(
                value=1.5, calibration_status="uncalibrated_illustrative"
            )
        )


def test_the_settings_validator_refuses_a_negative_cap() -> None:
    with pytest.raises(ValidationError, match="uip_reliability_cap"):
        _fx_carry_settings(
            uip_reliability_cap=CalibratedValue(
                value=-0.1, calibration_status="uncalibrated_illustrative"
            )
        )


def test_the_settings_validator_admits_the_boundary_caps() -> None:
    """0 and 1 are both admissible — the closed interval's own endpoints."""
    for value in (0.0, 1.0):
        settings = _fx_carry_settings(
            uip_reliability_cap=CalibratedValue(
                value=value, calibration_status="uncalibrated_illustrative"
            )
        )
        assert settings.uip_reliability_value == pytest.approx(value)


def test_the_settings_validator_accepts_the_shipped_cap() -> None:
    settings = _fx_carry_settings()
    assert settings.uip_reliability_value == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# The warnings — the flat branch, and the silence floor.
# ---------------------------------------------------------------------------


def test_the_flat_case_warns_that_zero_is_the_absence_of_a_prediction() -> None:
    result = uip_expected_move(_inputs(i_domestic_annualized=0.0300, i_foreign_annualized=0.0300))
    assert len(result.warnings) == 1
    assert "exactly zero" in result.warnings[0].lower()


def test_a_non_flat_case_is_silent() -> None:
    """A warning that fired on every call would be noise."""
    result = uip_expected_move(_inputs())
    assert result.warnings == []


def test_every_warning_branch_is_reached_by_some_fixture() -> None:
    """Coverage of the warning function: exactly the flat branch, and no other."""
    fired = 0
    for i_d, i_f in ((0.05, 0.01), (0.01, 0.05), (0.03, 0.03)):
        result = uip_expected_move(_inputs(i_domestic_annualized=i_d, i_foreign_annualized=i_f))
        fired += len(result.warnings)
    assert fired == 1


# ---------------------------------------------------------------------------
# The result contract.
# ---------------------------------------------------------------------------


def test_the_result_carries_the_module_contract() -> None:
    result = uip_expected_move(_inputs())
    assert isinstance(result, ModelResult)
    assert result.model_name == "uip_expected_move"
    assert result.country == "us"
    assert result.unit == "percent (expected spot change over the stated tenor)"
    assert result.source_family == EvidenceSourceFamily.MARKET_FX
    assert result.inputs_used == [
        "i_domestic_annualized",
        "i_foreign_annualized",
        "tenor_days",
        "day_count_basis",
    ]
    assert result.decision_relevance
    assert result.decision_prohibition
    assert result.limitations
    assert result.assumptions


def test_the_limitations_name_the_specification_s_standing_caveat() -> None:
    """Section 20.9's 'Do NOT use as a point forecast' belongs in limitations.

    It holds on EVERY call, so it is not a warning (a condition of this run) —
    the same move D-109 and D-111 made for their own standing caveats.
    """
    result = uip_expected_move(_inputs())
    joined = " ".join(result.limitations).lower()
    assert "known to fail empirically" in joined
    assert "forecast" in joined


def test_the_limitations_disclose_the_second_order_approximation() -> None:
    result = uip_expected_move(_inputs())
    joined = " ".join(result.limitations).lower()
    assert "second-order" in joined or "first-order" in joined


def test_the_limitations_disclose_that_expected_spot_is_unobservable() -> None:
    result = uip_expected_move(_inputs())
    joined = " ".join(result.limitations).lower()
    assert "unobservable" in joined


def test_the_limitations_disclose_that_no_forward_is_consulted() -> None:
    """The distinction from cip_check is a LIMITATION the reader must see."""
    result = uip_expected_move(_inputs())
    joined = " ".join(result.limitations).lower()
    assert "no forward rate is consulted" in joined


def test_the_prohibitions_forbid_reading_it_as_a_forecast() -> None:
    result = uip_expected_move(_inputs())
    joined = " ".join(result.decision_prohibition).lower()
    assert "point forecast" in joined
    assert "confidence" in joined  # not comparable with the neighbours'


def test_the_decision_relevance_states_the_cip_distinction() -> None:
    """The supersession answer is published, not left to the reader."""
    result = uip_expected_move(_inputs())
    assert result.decision_relevance is not None
    relevance = result.decision_relevance.lower()
    assert "cip_check" in relevance
    assert "different quantity" in relevance


def test_the_context_states_the_units_and_both_forms() -> None:
    result = uip_expected_move(_inputs())
    context = result.context.lower()
    assert "annualised decimals" in context
    assert "exact parity ratio" in context
    assert "first-order" in context


def test_the_published_values_are_rounded_but_the_direction_is_not_derived_from_them() -> None:
    """The label comes from the unrounded sign, so rounding cannot flip it.

    A tiny positive differential publishes ``expected_move_pct`` as 0.0 after
    6dp rounding, but the direction must still be ``domestic_depreciation`` — the
    label is derived from the sign of the computed value, and the computed value
    here is genuinely positive even though the published copy rounds to zero.
    The differential (1e-10) is chosen so the move in percent is 1e-8, which
    ``round(..., 6)`` maps to 0.0.
    """
    result = uip_expected_move(
        _inputs(i_domestic_annualized=0.0100_000_001, i_foreign_annualized=0.0100)
    )
    assert _number(result, "expected_move_pct") == 0.0  # rounded
    assert _label(result, "direction") == "domestic_depreciation"


def test_the_result_is_a_model_result() -> None:
    assert isinstance(uip_expected_move(_inputs()), ModelResult)


def test_the_module_exports_the_new_names() -> None:
    from macro_engine.models import fx_carry

    assert "uip_expected_move" in fx_carry.__all__
    assert "UIPInputs" in fx_carry.__all__


def test_the_published_numbers_are_finite() -> None:
    result = uip_expected_move(_inputs())
    for key, raw in _value(result).items():
        if isinstance(raw, float):
            assert math.isfinite(raw), f"{key} published a non-finite value"
