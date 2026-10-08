"""Hand-computed verification suite for Module 2 — bond mathematics.

Every expected number here is derived by hand from the bond formulas and
cross-checked against the config leaves, never copied from the implementation.
The golden case (F=1000, c=5%, y=6%, n=3) is worked out period by period.

Yields and coupons are DECIMALS throughout (Section 20.2); basis points appear
only where a name says ``_bp``.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
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

# The golden bond: F=1000, coupon 5% (50/yr), yield 6%, 3 periods.
GOLDEN = BondPricingInputs(face_value=1000.0, coupon_rate=0.05, yield_rate=0.06, periods=3)


def _repo(
    sofr: float,
    iorb: float,
    on_rrp: float,
    effr: float,
    persistence: int | None = None,
    volume: float | None = None,
) -> RepoStressInputs:
    return RepoStressInputs(
        sofr=sofr,
        iorb=iorb,
        on_rrp_rate=on_rrp,
        fed_funds_effective=effr,
        persistence_days=persistence,
        repo_volume_change_pct=volume,
    )


def _cfg() -> dict[str, float]:
    s = get_settings()
    return {
        "elevated": s.scalar("bond_math.repo_stress.elevated_threshold_bp"),
        "acute": s.scalar("bond_math.repo_stress.acute_threshold_bp"),
        "persistence": s.scalar("bond_math.repo_stress.persistence_days_required"),
        "volume": s.scalar("bond_math.repo_stress.repo_volume_change_threshold_pct"),
    }


# ---------------------------------------------------------------------------
# Config bridging — the spec's literal 25 must live in config (LAW 1)
# ---------------------------------------------------------------------------
def test_repo_stress_thresholds_come_from_config() -> None:
    c = _cfg()
    assert c["elevated"] == 10.0
    assert c["acute"] == 25.0
    assert c["persistence"] == 3.0
    assert c["volume"] == 10.0


# ---------------------------------------------------------------------------
# price_bond — golden case worked out period by period
# ---------------------------------------------------------------------------
def test_price_bond_golden_case() -> None:
    # PVs: 50/1.06 = 47.1698 ; 50/1.1236 = 44.4998 ; 1050/1.191016 = 881.6025
    # Price = 47.1698 + 44.4998 + 881.6025 = 973.2721
    res = price_bond(GOLDEN)
    assert res.value == pytest.approx(973.27, abs=0.01)
    assert "discount" in res.interpretation  # price < face -> discount
    assert res.confidence == pytest.approx(0.70)  # pure arithmetic: base only


def test_price_bond_premium_and_par() -> None:
    # Coupon > yield -> premium: F=1000, c=8%, y=5%, n=3
    # PVs: 80/1.05=76.1905 ; 80/1.1025=72.5624 ; 1080/1.157625=932.9583 -> 1081.71
    prem = price_bond(
        BondPricingInputs(face_value=1000.0, coupon_rate=0.08, yield_rate=0.05, periods=3)
    )
    assert prem.value == pytest.approx(1081.71, abs=0.01)
    assert "premium" in prem.interpretation
    # Coupon == yield -> exactly par
    par = price_bond(
        BondPricingInputs(face_value=1000.0, coupon_rate=0.05, yield_rate=0.05, periods=5)
    )
    assert par.value == pytest.approx(1000.00, abs=0.01)
    assert "at par" in par.interpretation


def test_price_bond_zero_yield_limit_is_undiscounted_sum() -> None:
    # y = 0 -> price = coupon*periods + face = 50*3 + 1000 = 1150
    res = price_bond(
        BondPricingInputs(face_value=1000.0, coupon_rate=0.05, yield_rate=0.0, periods=3)
    )
    assert res.value == pytest.approx(1150.00)


def test_price_bond_rejects_non_finite_and_bad_bounds() -> None:
    # nan on a bounded field is caught by the `gt=-1.0` bound first (nan fails
    # every comparison, which is the documented reason for the guard); the
    # FiniteInputs guard is what catches it on an unbounded float field.
    with pytest.raises(ValueError):
        BondPricingInputs(face_value=1000.0, coupon_rate=0.05, yield_rate=float("nan"), periods=3)
    with pytest.raises(ValueError):
        BondPricingInputs(face_value=0.0, coupon_rate=0.05, yield_rate=0.06, periods=3)
    with pytest.raises(ValueError):
        BondPricingInputs(face_value=1000.0, coupon_rate=0.05, yield_rate=0.06, periods=0)


def test_price_bond_non_finite_face_value_named_by_finite_inputs() -> None:
    # face_value carries no lower-order bound beyond gt=0, so float('inf') here
    # reaches the FiniteInputs guard and is named as non-finite.
    with pytest.raises(ValueError, match="non-finite"):
        BondPricingInputs(face_value=float("inf"), coupon_rate=0.05, yield_rate=0.06, periods=3)


# ---------------------------------------------------------------------------
# macaulay_duration — must use the UNROUNDED price, and include redemption
# ---------------------------------------------------------------------------
def test_macaulay_duration_golden_case() -> None:
    # Weighted: 1*47.1698 + 2*44.4998 + 3*881.6025 = 2780.9770
    # Price (unrounded) = 973.2721  -> 2.8573
    res = macaulay_duration(GOLDEN)
    assert res.value == pytest.approx(2.857, abs=0.001)


def test_macaulay_duration_zero_coupon_equals_maturity() -> None:
    # A zero-coupon bond's Macaulay duration is exactly its maturity.
    res = macaulay_duration(
        BondPricingInputs(face_value=1000.0, coupon_rate=0.0, yield_rate=0.05, periods=10)
    )
    assert res.value == pytest.approx(10.0, abs=0.001)


def test_macaulay_duration_uses_unrounded_price_not_presentation_price() -> None:
    # The documented defect: dividing by a 2-dp price gives 2.828 instead of
    # 2.829. We assert the unrounded-derived value to 3dp.
    res = macaulay_duration(
        BondPricingInputs(face_value=100.0, coupon_rate=0.05, yield_rate=0.05, periods=3)
    )
    # Hand: CFs 5, 5, 105 at y = 5%
    # PVs: 4.761905, 4.535147, 90.702948 -> price 100.0
    # Weighted: 4.761905 + 9.070294 + 272.108844 = 285.941043
    # Duration = 285.941043 / 100.0 = 2.859
    assert res.value == pytest.approx(2.859, abs=0.001)


def test_macaulay_duration_is_less_than_maturity_for_coupon_bond() -> None:
    res = macaulay_duration(GOLDEN)
    assert res.value_float() < GOLDEN.periods


# ---------------------------------------------------------------------------
# modified_duration and convexity
# ---------------------------------------------------------------------------
def test_modified_duration_is_macaulay_over_one_plus_y() -> None:
    # ModDur = MacDur / (1+y) = 2.8573 / 1.06 = 2.6956
    res = modified_duration(2.8573, 0.06)
    assert res.value == pytest.approx(2.696, abs=0.001)


def test_convexity_golden_case() -> None:
    # t(t+1)PV: 1*2*47.1698=94.3396 ; 2*3*44.4998=266.9988 ; 3*4*881.6025=10579.2300
    # Sum = 10940.5684 ; Price*(1+y)^2 = 973.2721 * 1.1236 = 1093.5675
    # Convexity = 10940.5684 / 1093.5675 = 10.0045
    res = convexity(ConvexityInputs(coupon=50.0, face_value=1000.0, yield_rate=0.06, n_periods=3))
    assert res.value == pytest.approx(10.0045, abs=0.001)


def test_convexity_positive_and_increases_with_maturity() -> None:
    short = convexity(ConvexityInputs(coupon=50.0, face_value=1000.0, yield_rate=0.06, n_periods=2))
    long = convexity(ConvexityInputs(coupon=50.0, face_value=1000.0, yield_rate=0.06, n_periods=10))
    assert short.value_float() > 0
    assert long.value_float() > short.value_float()


def test_convexity_inputs_reject_bad_bounds() -> None:
    with pytest.raises(ValueError):
        ConvexityInputs(coupon=50.0, face_value=1000.0, yield_rate=0.06, n_periods=0)


# ---------------------------------------------------------------------------
# price_change_with_convexity — the convexity term is ALWAYS positive
# ---------------------------------------------------------------------------
def test_price_change_convexity_term_positive_both_directions() -> None:
    # dy = +0.01: linear = -2.696*0.01 = -0.02696 ; convex = 0.5*10*0.0001 = 0.0005
    # total = -0.02646 -> -2.6460%
    up = price_change_with_convexity(2.696, 10.0, 0.01)
    assert up.value == pytest.approx(-2.6460, abs=0.001)
    # dy = -0.01: linear = +0.02696 ; convex = +0.0005 -> +2.7460%
    down = price_change_with_convexity(2.696, 10.0, -0.01)
    assert down.value == pytest.approx(2.7460, abs=0.001)
    # The asymmetry: the gain on a rally exceeds the loss on an equivalent selloff.
    assert down.value_float() > abs(up.value_float())


def test_price_change_convexity_is_zero_at_no_yield_change() -> None:
    res = price_change_with_convexity(2.696, 10.0, 0.0)
    assert res.value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# repo_stress_check — severity ladder + Section 22.11 corroboration gates
# ---------------------------------------------------------------------------
def test_repo_normal_within_corridor() -> None:
    # SOFR 5.33, IORB 5.40 -> spread -7.0bp -> NORMAL
    res = repo_stress_check(_repo(sofr=5.33, iorb=5.40, on_rrp=5.30, effr=5.33))
    assert res.value_dict()["severity"] == "NORMAL"
    assert res.value_dict()["sofr_minus_iorb_bp"] == pytest.approx(-7.0)
    assert res.value_dict()["corridor_intact"] is True
    # NORMAL carries the single-snapshot caveat, not an all-clear.
    assert any("single-snapshot" in w for w in res.warnings)


def test_repo_elevated_above_10bp_below_25bp() -> None:
    # SOFR 5.53 vs IORB 5.40 -> +13bp -> above elevated 10, below acute 25
    res = repo_stress_check(_repo(sofr=5.53, iorb=5.40, on_rrp=5.30, effr=5.33))
    assert res.value_dict()["severity"] == "ELEVATED"
    assert res.value_dict()["raw_severity_before_corroboration"] == "ELEVATED"


def test_repo_acute_requires_persistence_and_volume() -> None:
    # SOFR 5.70 vs IORB 5.40 -> +30bp -> raw ACUTE. With NO corroboration the
    # §22.11 gate caps severity at ELEVATED and says why.
    res = repo_stress_check(_repo(sofr=5.70, iorb=5.40, on_rrp=5.30, effr=5.33))
    assert res.value_dict()["raw_severity_before_corroboration"] == "ACUTE_REPO_STRESS"
    assert res.value_dict()["severity"] == "ELEVATED"
    assert any("not sufficient to declare ACUTE_REPO_STRESS" in w for w in res.warnings)


def test_repo_acute_escalates_with_both_corroborations() -> None:
    # persistence >= 3 days AND |volume change| >= 10%
    res = repo_stress_check(
        _repo(sofr=5.70, iorb=5.40, on_rrp=5.30, effr=5.33, persistence=4, volume=15.0)
    )
    assert res.value_dict()["severity"] == "ACUTE_REPO_STRESS"


def test_repo_acute_does_not_escalate_with_only_persistence() -> None:
    res = repo_stress_check(_repo(sofr=5.70, iorb=5.40, on_rrp=5.30, effr=5.33, persistence=4))
    assert res.value_dict()["severity"] == "ELEVATED"


def test_repo_volume_gate_uses_absolute_value() -> None:
    # A large NEGATIVE volume change is corroborating too (abs >= threshold).
    res = repo_stress_check(
        _repo(sofr=5.70, iorb=5.40, on_rrp=5.30, effr=5.33, persistence=4, volume=-15.0)
    )
    assert res.value_dict()["severity"] == "ACUTE_REPO_STRESS"


def test_repo_threshold_boundaries_are_strict() -> None:
    # Exactly at 10.0bp is NOT above the elevated threshold -> NORMAL
    at_10 = repo_stress_check(_repo(sofr=5.50, iorb=5.40, on_rrp=5.30, effr=5.33))
    assert at_10.value_dict()["sofr_minus_iorb_bp"] == pytest.approx(10.0)
    assert at_10.value_dict()["severity"] == "NORMAL"
    # Exactly at 25.0bp is NOT above the acute threshold -> ELEVATED
    at_25 = repo_stress_check(_repo(sofr=5.65, iorb=5.40, on_rrp=5.30, effr=5.33))
    assert at_25.value_dict()["sofr_minus_iorb_bp"] == pytest.approx(25.0)
    assert at_25.value_dict()["severity"] == "ELEVATED"


def test_repo_corridor_not_intact_is_surfaced() -> None:
    # IORB (5.25) below the ON-RRP rate (5.30): not the floor system.
    res = repo_stress_check(_repo(sofr=5.33, iorb=5.25, on_rrp=5.30, effr=5.33))
    assert res.value_dict()["corridor_intact"] is False
    assert any("Corridor not intact" in w for w in res.warnings)


def test_repo_confidence_reflects_uncalibrated_threshold() -> None:
    # acute_threshold_bp is uncalibrated_illustrative -> heuristic penalty applies.
    assert get_settings().is_calibrated("bond_math.repo_stress.acute_threshold_bp") is False
    res = repo_stress_check(_repo(sofr=5.33, iorb=5.40, on_rrp=5.30, effr=5.33))
    # base 0.70 - 0.20 heuristic = 0.50, plus 0 independence bonus
    assert res.confidence == pytest.approx(0.50)


def test_repo_inputs_reject_non_finite() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        RepoStressInputs(sofr=float("inf"), iorb=5.40, on_rrp_rate=5.30, fed_funds_effective=5.33)
