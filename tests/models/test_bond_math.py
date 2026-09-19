"""Hand-verified tests for Module 2 bond mathematics.

AGENTS.md Section 21.2 Steps 4-5. Every expected value here was computed
independently of the implementation, by hand, and is quoted with its derivation
in a comment — because Section 21.2 warns that "a test passing on the first
attempt may be asserting whatever the code produced".

Section 11.1 mandates two of these by name:
``test_convexity_hand_calculation`` and
``test_price_change_with_convexity_asymmetry``.
"""

from __future__ import annotations

import pytest

from macro_engine.models.bond_math import (
    BondPricingInputs,
    ConvexityInputs,
    RepoStressInputs,
    convexity,
    macaulay_duration,
    modified_duration,
    price_bond,
    price_change_with_convexity,
    repo_stress_check,
)
from tests.helpers import as_float

# The Section 11.1 reference bond: 3-year, 6% annual coupon, 8% yield, face 100.
#
# Hand computation:
#   CF1 = 6,  CF2 = 6,  CF3 = 106
#   P   = 6/1.08 + 6/1.08^2 + 106/1.08^3
#       = 5.555556 + 5.144033 + 84.146217 = 94.845806...  -> 94.85
#   MacDur = (1*5.555556 + 2*5.144033 + 3*84.146217) / 94.845806
#          = (5.555556 + 10.288066 + 252.438651) / 94.845806
#          = 268.282273 / 94.845806 = 2.828615...  -> 2.829
_REFERENCE_BOND = BondPricingInputs(face_value=100.0, coupon_rate=0.06, yield_rate=0.08, periods=3)


def test_price_bond_matches_hand_calculation() -> None:
    """Section 11.1's mandated pricing case."""
    result = price_bond(_REFERENCE_BOND)
    # 6/1.08 + 6/1.08**2 + 106/1.08**3 = 94.84580602550423
    assert result.value == 94.85


def test_price_bond_is_a_discount_when_yield_exceeds_coupon() -> None:
    """A bond yielding above its coupon must price below par.

    Asserted as a *relation*, not a value: this is the same guard as the exact
    figure above but it cannot be satisfied by a coincidentally-correct
    constant, so the two together are harder to pass accidentally.
    """
    result = price_bond(_REFERENCE_BOND)
    assert as_float(result) < _REFERENCE_BOND.face_value
    assert "discount" in result.interpretation


def test_price_bond_is_a_premium_when_coupon_exceeds_yield() -> None:
    premium_bond = BondPricingInputs(face_value=100.0, coupon_rate=0.10, yield_rate=0.05, periods=3)
    result = price_bond(premium_bond)
    assert as_float(result) > premium_bond.face_value
    assert "premium" in result.interpretation


def test_price_bond_at_par_is_exactly_face_value() -> None:
    """Coupon == yield must price at par. An identity, not an approximation."""
    par_bond = BondPricingInputs(face_value=1000.0, coupon_rate=0.05, yield_rate=0.05, periods=10)
    result = price_bond(par_bond)
    assert result.value == pytest.approx(1000.0, abs=0.01)
    assert "at par" in result.interpretation


def test_price_bond_at_zero_yield_is_the_undiscounted_sum() -> None:
    """The y=0 branch is the algebraic limit, not an arbitrary special case.

    3 x 6 coupon + 100 face = 118. If the closed-form annuity factor had been
    used unguarded this would raise ZeroDivisionError instead.
    """
    zero_yield = BondPricingInputs(face_value=100.0, coupon_rate=0.06, yield_rate=0.0, periods=3)
    assert price_bond(zero_yield).value == 118.0


def test_macaulay_duration_matches_hand_calculation() -> None:
    """268.282273 / 94.845806 = 2.828615..., which rounds to 2.829.

    This test caught a real defect: an earlier implementation priced the bond
    through ``price_bond()``, whose value is already rounded to 2 decimal
    places, and returned 2.828. The rounded denominator is wrong in the third
    decimal — invisible without this independent hand calculation.
    """
    result = macaulay_duration(_REFERENCE_BOND)
    assert result.value == 2.829


def test_macaulay_duration_includes_redemption_in_the_final_weight() -> None:
    """A duration that drops the face value from period-n is systematically low.

    This asserts the defect directly: the correct duration must EXCEED what the
    coupon-only weighted sum would produce, since adding a large weight at t=n
    can only raise the weighted average.
    """
    result = macaulay_duration(_REFERENCE_BOND)

    coupon = 6.0
    price_without_redemption_weight = (1 * coupon / 1.08 + 2 * coupon / 1.08**2) / (
        coupon / 1.08 + coupon / 1.08**2
    )
    assert as_float(result) > price_without_redemption_weight


def test_modified_duration_is_macaulay_over_one_plus_yield() -> None:
    mac_dur = as_float(macaulay_duration(_REFERENCE_BOND))
    result = modified_duration(mac_dur, 0.08)
    # 2.829 / 1.08 = 2.619444... -> 2.619
    assert result.value == pytest.approx(2.619, abs=0.001)


def test_a_zero_coupon_bond_duration_equals_its_maturity() -> None:
    """For a pure discount bond, Macaulay duration is exactly the maturity.

    An identity, and one that fails loudly if the redemption is mishandled.
    """
    zero_coupon = BondPricingInputs(face_value=100.0, coupon_rate=0.0, yield_rate=0.05, periods=5)
    assert macaulay_duration(zero_coupon).value == pytest.approx(5.0, abs=0.001)


def test_convexity_hand_calculation() -> None:
    """Section 11.1's mandated convexity case.

    Hand computation for the reference cash flows (6, 6, 106) at y=0.08:
      PV1 = 6/1.08       = 5.55555556, t(t+1)=2   -> 11.11111111
      PV2 = 6/1.08^2     = 5.14403292, t(t+1)=6   -> 30.86419753
      PV3 = 106/1.08^3   = 84.14621726, t(t+1)=12 -> 1009.75460715
      SUM PV           = 94.84580574
      SUM t(t+1)PV     = 1051.72991579
      Convexity = 1051.72991579 / (94.84580574 * 1.08^2)
                = 1051.72991579 / 110.62796695
                = 9.506949...  -> 9.5069
    """
    result = convexity(ConvexityInputs(coupon=6.0, face_value=100.0, yield_rate=0.08, n_periods=3))
    assert result.value == pytest.approx(9.5069, abs=0.0001)


def test_price_change_with_convexity_asymmetry() -> None:
    """Section 11.1's mandated asymmetry assertion.

    Convexity's contribution is quadratic in dy and therefore always positive,
    so a -100bp move must produce a LARGER absolute gain than a +100bp move
    produces as a loss. This is the property that makes convexity valuable, and
    it is asserted as an inequality rather than as two values — an inequality
    cannot be satisfied by tuning constants to match a snapshot.
    """
    mod_dur = 2.619
    conv = 9.5069

    down = price_change_with_convexity(mod_dur, conv, -0.01)
    up = price_change_with_convexity(mod_dur, conv, +0.01)

    assert as_float(down) > abs(as_float(up)), (
        "a -100bp move must gain more than a +100bp move loses"
    )
    assert as_float(down) > 0
    assert as_float(up) < 0


def test_price_change_with_convexity_is_exactly_linear_without_convexity() -> None:
    """At conv=0 the estimate must reduce to the duration term alone.

    A boundary check: it catches a mis-signed or mis-scaled convexity term,
    which an asymmetry test alone would not.
    """
    result = price_change_with_convexity(2.0, 0.0, 0.01)
    # -2.0 * 0.01 * 100 = -2.0 percent
    assert result.value == pytest.approx(-2.0, abs=1e-9)


def _normal_repo_inputs(**overrides: object) -> RepoStressInputs:
    """A calm corridor, which each test perturbs in exactly one way."""
    base: dict[str, object] = {
        "sofr": 4.33,
        "iorb": 4.40,
        "on_rrp_rate": 4.25,
        "fed_funds_effective": 4.33,
        "persistence_days": None,
        "repo_volume_change_pct": None,
    }
    base.update(overrides)
    return RepoStressInputs(**base)  # type: ignore[arg-type]


def test_repo_stress_normal_when_sofr_sits_below_iorb() -> None:
    """SOFR below IORB is the expected floor-system state."""
    result = repo_stress_check(_normal_repo_inputs())
    assert isinstance(result.value, dict)
    assert result.value["severity"] == "NORMAL"
    assert result.value["corridor_intact"] is True


def test_repo_stress_elevated_on_a_moderate_breach() -> None:
    """SOFR 12bp above IORB clears the 10bp elevated threshold."""
    result = repo_stress_check(_normal_repo_inputs(sofr=4.52))
    assert isinstance(result.value, dict)
    assert result.value["severity"] == "ELEVATED"


def test_repo_stress_refuses_escalation_without_corroboration() -> None:
    """Section 22.11: a single-snapshot breach without persistence AND volume
    must NOT be labelled ACUTE_REPO_STRESS.

    This is the test that proves the amendment was implemented rather than the
    specification's original unconditional rule. It asserts three things that
    together can only hold if the gate exists: the raw breach is recorded, the
    severity is capped, and a warning explains why.
    """
    result = repo_stress_check(_normal_repo_inputs(sofr=4.80))
    assert isinstance(result.value, dict)
    assert result.value["raw_severity_before_corroboration"] == "ACUTE_REPO_STRESS"
    assert result.value["severity"] == "ELEVATED", "breach alone must not escalate"
    assert any("Section 22.11" in warning for warning in result.warnings)


def test_repo_stress_escalates_with_persistence_and_volume() -> None:
    """Both corroborating conditions satisfied -> the acute label is applied."""
    result = repo_stress_check(
        _normal_repo_inputs(sofr=4.80, persistence_days=5, repo_volume_change_pct=25.0)
    )
    assert isinstance(result.value, dict)
    assert result.value["severity"] == "ACUTE_REPO_STRESS"


def test_repo_stress_persistence_alone_is_not_sufficient() -> None:
    """A mutation guard on the AND: persistence without volume must not pass."""
    result = repo_stress_check(_normal_repo_inputs(sofr=4.80, persistence_days=5))
    assert isinstance(result.value, dict)
    assert result.value["severity"] == "ELEVATED"


def test_repo_stress_volume_alone_is_not_sufficient() -> None:
    """The mirror of the previous test — volume without persistence must not pass."""
    result = repo_stress_check(_normal_repo_inputs(sofr=4.80, repo_volume_change_pct=25.0))
    assert isinstance(result.value, dict)
    assert result.value["severity"] == "ELEVATED"


def test_repo_stress_flags_a_broken_corridor() -> None:
    """If IORB is not above the ON-RRP rate, the floor system does not exist in
    these inputs and the severity label is computed against a foreign setup."""
    result = repo_stress_check(_normal_repo_inputs(iorb=4.20, on_rrp_rate=4.25))
    assert isinstance(result.value, dict)
    assert result.value["corridor_intact"] is False
    assert any("Corridor not intact" in warning for warning in result.warnings)


def test_repo_stress_refuses_incomplete_corridor_inputs() -> None:
    """All four rates are required — a missing leg must raise, not default.

    If ``on_rrp_rate`` were optional, a caller with three of four rates would
    receive a NORMAL verdict that is actually an untested hypothesis.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RepoStressInputs(  # type: ignore[call-arg]
            sofr=4.33, iorb=4.40, fed_funds_effective=4.33
        )


def test_all_bond_math_confidences_come_from_the_formula() -> None:
    """Section 22.8: no literal confidence anywhere in this module.

    Asserts the computed values, which is the only observable consequence of
    having removed the literals. Pure arithmetic without calibration penalties
    must land on the configured base.
    """
    from macro_engine.config import get_settings

    base = get_settings().scalar("confidence.base")
    for result in (
        price_bond(_REFERENCE_BOND),
        macaulay_duration(_REFERENCE_BOND),
        modified_duration(2.829, 0.08),
        convexity(ConvexityInputs(coupon=6.0, face_value=100.0, yield_rate=0.08, n_periods=3)),
        price_change_with_convexity(2.619, 9.5069, 0.01),
    ):
        assert result.confidence == base, (
            f"{result.model_name} confidence {result.confidence} != configured base {base}"
        )
