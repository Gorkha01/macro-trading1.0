"""Hand-computed tests for Module 11 — Equity Macro.

This is the file ``equity_macro.py``'s own docstring cites as the guard on
``SECTOR_ROTATION_PRIOR``'s exhaustiveness ("asserted by
tests/models/test_equity_macro.py"). It did not exist until this review — see
F-EM-001.

Every expected number is derived from the CONFIG LEAVES and from the formula,
not from running the code:

    equity_macro.reliability_cap                 = 0.40  (sector prior)
    equity_macro.duration_reliability_cap        = 0.30
    equity_macro.factor_tilt_reliability_cap     = 0.35
    all three caps are `uncalibrated_illustrative` -> heuristic penalty applies

    duration_sensitivity.growth_proxy_years      = 15.0
    duration_sensitivity.value_proxy_years       = 5.0
    rate_change_bp band                          = [-1000, +1000] inclusive

    computed = 0.70 - 0.20 (heuristic) + min(1 * 0.05, 0.25) = 0.55
    sector  : 0.55 * 0.40 = 0.2200
    duration: 0.55 * 0.30 = 0.1650
    factor  : 0.55 * 0.35 = 0.1925

    est_pct_move = -proxy_duration * (rate_change_bp / 10000)
    growth +100bp -> -15 * 0.01 = -0.15 -> -15.00 %
    value  +100bp ->  -5 * 0.01 = -0.05 ->  -5.00 %
    growth  -50bp -> -15 * (-0.005) = +0.075 -> +7.50 %
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import EvidenceSourceFamily, ModelResult
from macro_engine.models.equity_macro import (
    FACTOR_NAMES,
    FACTOR_REGIME_MAP,
    SECTOR_PRIOR_EXTENSION_REGIMES,
    SECTOR_ROTATION_PRIOR,
    SPECIFICATION_REGIMES,
    DurationSensitivityInputs,
    FactorTiltInputs,
    SectorRotationInputs,
    duration_sensitivity,
    factor_tilt_prior,
    sector_rotation_prior,
)
from macro_engine.models.regime import REGIME_STATES, RegimeState

ALL_REGIMES = list(REGIME_STATES)


def rot(regime: str) -> ModelResult:
    return sector_rotation_prior(
        SectorRotationInputs(regime_state=regime)  # type: ignore[arg-type]
    )


def tilt(regime: str) -> ModelResult:
    return factor_tilt_prior(
        FactorTiltInputs(regime_state=regime)  # type: ignore[arg-type]
    )


def dur(style: str, bp: float) -> ModelResult:
    return duration_sensitivity(
        DurationSensitivityInputs(style=style, rate_change_bp=bp)  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# F-EM-001 — the coverage claim the module is built around
# ---------------------------------------------------------------------------
def test_sector_prior_is_exhaustive_over_the_classifier_vocabulary() -> None:
    """Section 6.9's six-key map silently answered "no prior" for three regimes.

    This module exists to close that hole, so the map must cover every member of
    REGIME_STATES — including slowdown/recovery/reflation, which D-037 made
    reachable.
    """
    assert set(SECTOR_ROTATION_PRIOR) == set(REGIME_STATES)
    missing = set(REGIME_STATES) - set(SECTOR_ROTATION_PRIOR)
    assert not missing, f"no sector prior for: {sorted(missing)}"


def test_factor_prior_is_exhaustive_over_the_classifier_vocabulary() -> None:
    assert set(FACTOR_REGIME_MAP) == set(REGIME_STATES)


def test_the_regime_literal_and_the_tuple_are_the_same_set() -> None:
    """The maps key on the Literal; the tuple is its runtime-iterable form."""
    from typing import get_args

    assert set(get_args(RegimeState)) == set(REGIME_STATES)


def test_specification_and_extension_rows_partition_the_vocabulary() -> None:
    """A reader must be able to tell a Section 6.9 row from this build's."""
    assert len(SPECIFICATION_REGIMES) == 6
    assert set(SECTOR_PRIOR_EXTENSION_REGIMES) == {"slowdown", "recovery", "reflation"}
    assert not set(SPECIFICATION_REGIMES) & set(SECTOR_PRIOR_EXTENSION_REGIMES)
    assert set(SPECIFICATION_REGIMES) | set(SECTOR_PRIOR_EXTENSION_REGIMES) == set(REGIME_STATES)


def test_every_factor_row_tilts_exactly_the_five_named_factors() -> None:
    assert FACTOR_NAMES == ("value", "momentum", "quality", "low_vol", "size")
    for regime, row in FACTOR_REGIME_MAP.items():
        assert set(row) == set(FACTOR_NAMES), regime


# ---------------------------------------------------------------------------
# sector_rotation_prior
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("regime", ALL_REGIMES)
def test_every_regime_returns_its_mapped_sectors(regime: str) -> None:
    res = rot(regime)
    assert res.value == list(SECTOR_ROTATION_PRIOR[regime])
    assert len(res.value) >= 1


def test_sector_order_is_preserved_most_advantaged_first() -> None:
    """The order is the specification's claim about which sector leads."""
    assert rot("recession").value == ["utilities", "staples", "healthcare"]
    assert rot("late_expansion").value == ["energy", "materials"]


def test_extension_rows_are_declared_as_such() -> None:
    """A caller can distinguish a spec row from an extension row."""
    for regime in SECTOR_PRIOR_EXTENSION_REGIMES:
        joined = " ".join(rot(regime).assumptions)
        assert "this build's declaration" in joined, regime
    for regime in SPECIFICATION_REGIMES:
        joined = " ".join(rot(regime).assumptions)
        assert "this build's declaration" not in joined, regime


@pytest.mark.parametrize("regime", ALL_REGIMES)
def test_sector_confidence_is_the_capped_computed_value(regime: str) -> None:
    """0.55 computed * 0.40 cap = 0.22 — multiplicative, not min()."""
    assert rot(regime).confidence == pytest.approx(0.22)


def test_the_prior_not_rule_caveat_is_always_published() -> None:
    for regime in ALL_REGIMES:
        joined = " ".join(rot(regime).warnings) + " " + rot(regime).context
        assert "BASE-RATE PRIOR" in joined or "base-rate prior" in joined.lower()


def test_an_out_of_vocabulary_regime_is_refused_not_defaulted() -> None:
    """A typo must not fall through the map's .get into the generic fallback."""
    with pytest.raises(ValidationError):
        SectorRotationInputs(regime_state="recesion")  # type: ignore[arg-type]


def test_sector_result_publication_fields() -> None:
    res = rot("recession")
    assert res.model_name == "sector_rotation_prior"
    assert res.unit == "sector_names"
    assert res.direction is None
    assert res.source_family == EvidenceSourceFamily.MANUAL_ASSESSMENT
    assert res.inputs_used == ["regime_state"]


# ---------------------------------------------------------------------------
# duration_sensitivity
# ---------------------------------------------------------------------------
def test_growth_falls_fifteen_percent_on_a_hundred_bp_rise() -> None:
    res = dur("growth", 100.0)
    assert res.value == pytest.approx(-15.0)


def test_value_falls_five_percent_on_a_hundred_bp_rise() -> None:
    res = dur("value", 100.0)
    assert res.value == pytest.approx(-5.0)


def test_growth_moves_three_times_as_far_as_value() -> None:
    """15yr vs 5yr proxy — the whole content of the growth/value duration trade."""
    g = dur("growth", 100.0).value_float()
    v = dur("value", 100.0).value_float()
    assert g / v == pytest.approx(3.0)


def test_a_rate_fall_raises_the_price() -> None:
    res = dur("growth", -50.0)
    assert res.value == pytest.approx(7.5)


def test_direction_is_down_for_a_rise_and_up_for_a_fall() -> None:
    assert dur("growth", 100.0).direction == "down"
    assert dur("growth", -100.0).direction == "up"


def test_direction_is_none_for_a_zero_move() -> None:
    assert dur("growth", 0.0).direction is None


def test_a_zero_rate_move_publishes_zero_not_negative_zero() -> None:
    """F-EM-002: -duration * 0.0 is IEEE-754 NEGATIVE ZERO.

    round(-0.0 * 100, 2) is -0.0, so the published value was `-0.0` and the
    interpretation read "-0.00%" for a rate move that is exactly zero. `-0.0`
    compares equal to `0.0`, so this is cosmetic rather than an economic error —
    but a published percentage of "-0.00%" for no move is still wrong, and -0.0
    survives JSON serialisation.
    """
    res = dur("growth", 0.0)
    assert res.value == pytest.approx(0.0)
    assert math.copysign(1.0, res.value_float()) > 0.0, f"value is negative zero: {res.value!r}"
    assert str(res.value) == "0.0"
    assert "-0.00%" not in res.interpretation


def test_the_rate_band_boundaries_are_inclusive() -> None:
    assert dur("growth", 1000.0).value == pytest.approx(-150.0)
    assert dur("growth", -1000.0).value == pytest.approx(150.0)


@pytest.mark.parametrize("bp", [1000.1, -1000.1, 2500.0])
def test_a_rate_move_outside_the_band_is_refused(bp: float) -> None:
    with pytest.raises(ValidationError, match="basis points"):
        DurationSensitivityInputs(style="growth", rate_change_bp=bp)


def test_a_non_finite_rate_move_is_refused() -> None:
    """DurationSensitivityInputs extends FiniteInputs."""
    with pytest.raises(ValidationError):
        DurationSensitivityInputs(style="growth", rate_change_bp=float("nan"))


def test_duration_confidence_is_the_capped_computed_value() -> None:
    """0.55 * 0.30 = 0.165."""
    assert dur("growth", 100.0).confidence == pytest.approx(0.165)


def test_the_illustrative_caveat_is_always_published() -> None:
    res = dur("growth", 100.0)
    joined = " ".join(res.warnings)
    assert "ILLUSTRATIVE" in joined
    assert "not calibrated" in joined
    assert res.unit == "percent_price_change"


# ---------------------------------------------------------------------------
# factor_tilt_prior
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("regime", ALL_REGIMES)
def test_every_regime_returns_five_tilts(regime: str) -> None:
    res = tilt(regime)
    assert set(res.value_dict()) == set(FACTOR_NAMES)
    assert len(res.value_dict()) == 5


@pytest.mark.parametrize("regime", ALL_REGIMES)
def test_tilts_are_within_minus_one_to_plus_one(regime: str) -> None:
    for name, value in tilt(regime).value_dict().items():
        assert -1.0 <= value <= 1.0, (regime, name, value)


def test_recession_tilts_are_the_specification_table_verbatim() -> None:
    assert tilt("recession").value == {
        "value": -0.5,
        "momentum": -1.0,
        "quality": 1.0,
        "low_vol": 1.0,
        "size": -1.0,
    }


def test_slowdown_tilts_to_quality_and_low_vol() -> None:
    row = tilt("slowdown").value_dict()
    assert row["quality"] == 1.0
    assert row["low_vol"] == 1.0
    assert row["momentum"] == -0.5


def test_factor_confidence_is_the_capped_computed_value() -> None:
    """0.55 * 0.35 = 0.1925."""
    assert tilt("recession").confidence == pytest.approx(0.1925)


def test_the_momentum_caveat_is_always_published() -> None:
    """Section 20.20-E: momentum is weakest exactly when the prior matters most."""
    joined = " ".join(tilt("recession").warnings)
    assert "momentum" in joined.lower()
    assert "regime turns" in joined.lower()


def test_an_out_of_vocabulary_regime_is_refused_for_factor_tilt() -> None:
    with pytest.raises(ValidationError):
        FactorTiltInputs(regime_state="reflationary")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LAW 1 — the numbers come from config
# ---------------------------------------------------------------------------
def test_caps_and_proxies_come_from_config() -> None:
    s = get_settings().equity_macro
    assert s.reliability_value == pytest.approx(0.40)
    assert s.duration_reliability_value == pytest.approx(0.30)
    assert s.factor_tilt_reliability_value == pytest.approx(0.35)
    assert s.duration_growth_proxy_years == pytest.approx(15.0)
    assert s.duration_value_proxy_years == pytest.approx(5.0)
    assert s.duration_rate_change_min_bp == pytest.approx(-1000.0)
    assert s.duration_rate_change_max_bp == pytest.approx(1000.0)
    assert s.no_prior_label == "diversified — no strong prior"


def test_the_three_caps_are_all_uncalibrated_so_the_heuristic_penalty_applies() -> None:
    s = get_settings().equity_macro
    assert s.reliability_cap_is_calibrated is False
    assert s.duration_proxy_is_calibrated is False
    assert s.factor_tilt_reliability_cap_is_calibrated is False
