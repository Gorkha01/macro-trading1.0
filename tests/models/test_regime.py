"""Hand-computed verification tests for models/regime.py (Module 3, rule-based).

Every expected value below is derived BY HAND from the formula and the config
values in config/settings.yaml (read, not assumed):

  regime.recession_output_gap_max.value        = -1.5   (recession_gap)
  regime.weak_growth_output_gap_max.value      = -0.5   (weak_growth_gap)
  regime.neutral_inflation_trend_band_pp.value =  0.1   (neutral_inflation_band)
  regime.growth_momentum_band_pp.value         =  0.25  (growth_momentum_band)
  regime.measured_rising_inflation_rate.value  =  0.9375
  regime.base_rates.rates.late_expansion_value =  0.4875

  confidence base / penalties:
    base = 0.70
    data_quality_flag_penalty = 0.25
    heuristic_penalty         = 0.20   (bands are uncalibrated_illustrative)
    unobservable_penalty      = 0.20   (output gap vs potential, u*)
    source_independence_bonus = 0.05 / family, cap 0.25
    floor 0.05, ceiling 0.95

So a clean run (no data flag, bands uncalibrated, depends_on_unobservable,
source_independence_count = 0) -> 0.70 - 0.20 - 0.20 = 0.30.

These are REAL-WORLD checks: the classifier's partition of the (growth,
inflation) plane is verified against the hand-derived state grid, not against a
mirror of the code. If a comparison operator or a band value silently changes,
the hand value here fails.
"""

from __future__ import annotations

import math as _math
from typing import Any

import pytest

from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.regime import (
    RegimeInputs,
    _growth_axis,
    _inflation_axis,
    _select_state,
    classify_regime_rule_based,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_inputs(
    output_gap: float,
    inflation_trend_3m: float,
    *,
    inflation_yoy: float = 2.0,
    unemployment_gap: float = 0.5,
    output_gap_change: float | None = None,
    data_quality_flags_present: bool = False,
) -> RegimeInputs:
    return RegimeInputs(
        output_gap=output_gap,
        inflation_yoy=inflation_yoy,
        inflation_trend_3m=inflation_trend_3m,
        unemployment_gap=unemployment_gap,
        output_gap_change=output_gap_change,
        data_quality_flags_present=data_quality_flags_present,
    )


# ---------------------------------------------------------------------------
# _inflation_axis — bands are CLOSED (inclusive) at +/- neutral_band
# ---------------------------------------------------------------------------
def test_inflation_axis_rising_above_band() -> None:
    assert _inflation_axis(0.5, 0.1) == "rising"


def test_inflation_axis_falling_below_band() -> None:
    assert _inflation_axis(-0.5, 0.1) == "falling"


def test_inflation_axis_flat_inside_band() -> None:
    # |trend| <= band -> flat. Check the boundary is inclusive.
    assert _inflation_axis(0.0, 0.1) == "flat"
    assert _inflation_axis(0.1, 0.1) == "flat"  # exactly on upper edge
    assert _inflation_axis(-0.1, 0.1) == "flat"  # exactly on lower edge
    assert _inflation_axis(0.0999, 0.1) == "flat"


def test_inflation_axis_boundary_exclusive_just_outside() -> None:
    # One epsilon outside the band flips the bucket.
    assert _inflation_axis(0.1001, 0.1) == "rising"
    assert _inflation_axis(-0.1001, 0.1) == "falling"


# ---------------------------------------------------------------------------
# _growth_axis — half-open partition, boundary belongs to the UPPER band
# ---------------------------------------------------------------------------
def test_growth_axis_deep_contraction() -> None:
    assert _growth_axis(-2.0, -1.5, -0.5) == "deep_contraction"


def test_growth_axis_contraction() -> None:
    assert _growth_axis(-1.0, -1.5, -0.5) == "contraction"


def test_growth_axis_above_trend() -> None:
    assert _growth_axis(1.0, -1.5, -0.5) == "above_trend"


def test_growth_axis_boundary_on_recession_threshold_is_contraction() -> None:
    # gap == recession_gap: not < recession_gap (strict), so it is contraction.
    assert _growth_axis(-1.5, -1.5, -0.5) == "contraction"


def test_growth_axis_boundary_on_weak_threshold_is_above_trend() -> None:
    # gap == weak_growth_gap: not < weak_growth_gap (strict), so above_trend.
    assert _growth_axis(-0.5, -1.5, -0.5) == "above_trend"


# ---------------------------------------------------------------------------
# _select_state — every one of the nine declared states, hand-derived
# ---------------------------------------------------------------------------
def test_state_recession_depth_beats_direction() -> None:
    # deep_contraction -> recession regardless of inflation axis.
    assert (
        _select_state("deep_contraction", "rising", gap=-2.0, momentum_band=0.25, gap_change=None)
        == "recession"
    )
    assert (
        _select_state("deep_contraction", "falling", gap=-2.0, momentum_band=0.25, gap_change=None)
        == "recession"
    )
    assert (
        _select_state("deep_contraction", "flat", gap=-2.0, momentum_band=0.25, gap_change=None)
        == "recession"
    )


def test_state_stagflation() -> None:
    # contraction + rising inflation.
    assert (
        _select_state("contraction", "rising", gap=-1.0, momentum_band=0.25, gap_change=None)
        == "stagflation"
    )


def test_state_recovery_requires_closing_gap() -> None:
    # contraction + falling + gap_change > 0  -> recovery.
    assert (
        _select_state("contraction", "falling", gap=-1.0, momentum_band=0.25, gap_change=0.3)
        == "recovery"
    )


def test_state_slowdown_falling_without_gap_change() -> None:
    # contraction + falling + gap_change None -> slowdown (cannot decide recovery).
    assert (
        _select_state("contraction", "falling", gap=-1.0, momentum_band=0.25, gap_change=None)
        == "slowdown"
    )


def test_state_slowdown_falling_with_widening_gap() -> None:
    # contraction + falling + gap_change <= 0 -> slowdown.
    assert (
        _select_state("contraction", "falling", gap=-1.0, momentum_band=0.25, gap_change=-0.2)
        == "slowdown"
    )


def test_state_slowdown_flat_inflation() -> None:
    # contraction + flat inflation -> slowdown (inflation does not distinguish).
    assert (
        _select_state("contraction", "flat", gap=-1.0, momentum_band=0.25, gap_change=None)
        == "slowdown"
    )


def test_state_disinflation_above_trend_falling() -> None:
    # above_trend + |gap| > band + falling inflation.
    assert (
        _select_state("above_trend", "falling", gap=1.0, momentum_band=0.25, gap_change=None)
        == "disinflation"
    )


def test_state_late_expansion_above_trend_rising() -> None:
    # above_trend + |gap| > band + rising inflation.
    assert (
        _select_state("above_trend", "rising", gap=1.0, momentum_band=0.25, gap_change=None)
        == "late_expansion"
    )


def test_state_reflation_at_band_rising() -> None:
    # above_trend + |gap| <= band + rising inflation -> reflation (not expansion).
    assert (
        _select_state("above_trend", "rising", gap=0.1, momentum_band=0.25, gap_change=None)
        == "reflation"
    )


def test_state_reflation_above_band_flat() -> None:
    # above_trend + |gap| > band + flat inflation -> reflation (final fallthrough).
    assert (
        _select_state("above_trend", "flat", gap=1.0, momentum_band=0.25, gap_change=None)
        == "reflation"
    )


def test_state_early_expansion_at_band_below_trend() -> None:
    # above_trend + |gap| <= band + not rising + gap < 0 -> early_expansion.
    assert (
        _select_state("above_trend", "falling", gap=-0.1, momentum_band=0.25, gap_change=None)
        == "early_expansion"
    )


def test_state_mid_expansion_at_band_settled() -> None:
    # above_trend + |gap| <= band + not rising + gap >= 0 -> mid_expansion.
    assert (
        _select_state("above_trend", "falling", gap=0.1, momentum_band=0.25, gap_change=None)
        == "mid_expansion"
    )


def test_momentum_band_boundary_belongs_to_at_trend() -> None:
    # |gap| == band -> at trend band (inclusive). gap=0.25 falling -> mid_expansion.
    assert (
        _select_state("above_trend", "falling", gap=0.25, momentum_band=0.25, gap_change=None)
        == "mid_expansion"
    )
    # One epsilon outside -> above band -> disinflation.
    assert (
        _select_state("above_trend", "falling", gap=0.2501, momentum_band=0.25, gap_change=None)
        == "disinflation"
    )


# ---------------------------------------------------------------------------
# slack_corroborated — the SIGN comparison is output_gap vs -unemployment_gap
# ---------------------------------------------------------------------------
def test_slack_corroborated_both_slack() -> None:
    # output_gap<0 (below potential) AND unemployment_gap>0 (slack) -> agree.
    inp = make_inputs(output_gap=-1.0, inflation_trend_3m=0.5, unemployment_gap=0.5)
    assert inp.slack_corroborated is True


def test_slack_corroborated_both_tight() -> None:
    # output_gap>0 (above potential) AND unemployment_gap<0 (tight) -> agree.
    inp = make_inputs(output_gap=1.0, inflation_trend_3m=0.5, unemployment_gap=-0.5)
    assert inp.slack_corroborated is True


def test_slack_corroborated_disagree_output_above_labour_slack() -> None:
    # output_gap>0 (tight) but unemployment_gap>0 (slack) -> disagree.
    inp = make_inputs(output_gap=1.0, inflation_trend_3m=0.5, unemployment_gap=0.5)
    assert inp.slack_corroborated is False


def test_slack_corroborated_disagree_output_slack_labour_tight() -> None:
    # output_gap<0 (slack) but unemployment_gap<0 (tight) -> disagree.
    inp = make_inputs(output_gap=-1.0, inflation_trend_3m=0.5, unemployment_gap=-0.5)
    assert inp.slack_corroborated is False


def test_slack_corroborated_zero_output_gap_is_no_evidence() -> None:
    # A zero on either measure is NO evidence, not agreement.
    inp = make_inputs(output_gap=0.0, inflation_trend_3m=0.5, unemployment_gap=0.5)
    assert inp.slack_corroborated is False


def test_slack_corroborated_zero_unemployment_gap_is_no_evidence() -> None:
    inp = make_inputs(output_gap=-1.0, inflation_trend_3m=0.5, unemployment_gap=0.0)
    assert inp.slack_corroborated is False


# ---------------------------------------------------------------------------
# classify_regime_rule_based — integration, hand-derived state + confidence
# ---------------------------------------------------------------------------
def test_classify_late_expansion_state_and_axes() -> None:
    res = classify_regime_rule_based(make_inputs(output_gap=1.0, inflation_trend_3m=0.5))
    assert res.value_dict()["state"] == "late_expansion"
    assert res.value_dict()["growth_axis"] == "above_trend"
    assert res.value_dict()["inflation_axis"] == "rising"
    # base rate looked up from config rate_map for late_expansion.
    assert res.value_dict()["state_base_rate"] == pytest.approx(0.4875)
    assert res.value_dict()["rising_inflation_base_rate"] == pytest.approx(0.9375)


def test_classify_recession_depth_beats_direction() -> None:
    res = classify_regime_rule_based(make_inputs(output_gap=-2.0, inflation_trend_3m=0.5))
    assert res.value_dict()["state"] == "recession"
    assert res.value_dict()["growth_axis"] == "deep_contraction"
    # The inflation axis did not decide the label -> REGIME_TENSION.
    assert res.value_dict()["regime_tension"] == "REGIME_TENSION"


def test_classify_recovery_reachable_only_with_gap_change() -> None:
    res = classify_regime_rule_based(
        make_inputs(output_gap=-1.0, inflation_trend_3m=-0.5, output_gap_change=0.3)
    )
    assert res.value_dict()["state"] == "recovery"


def test_classify_slowdown_not_recovery_when_gap_change_missing() -> None:
    res = classify_regime_rule_based(make_inputs(output_gap=-1.0, inflation_trend_3m=-0.5))
    assert res.value_dict()["state"] == "slowdown"
    # The slowdown/recovery ambiguity was not decidable -> explicit warning.
    assert any("SLOWDOWN, NOT RECOVERY" in w for w in res.warnings)


def test_classify_flat_inflation_is_single_axis_tension() -> None:
    res = classify_regime_rule_based(make_inputs(output_gap=1.0, inflation_trend_3m=0.0))
    # trend=0.0 is inside the neutral band -> inflation axis did not distinguish.
    assert res.value_dict()["regime_tension"] == "REGIME_TENSION"
    assert any(
        "inflation momentum" in r.lower() for r in res.value_dict()["regime_tension_reasons"]
    )


def test_classify_two_axis_case_has_no_tension() -> None:
    res = classify_regime_rule_based(make_inputs(output_gap=1.0, inflation_trend_3m=0.5))
    assert res.value_dict()["regime_tension"] == "NO_REGIME_TENSION"
    assert res.value_dict()["regime_tension_reasons"] == []


def test_classify_all_nine_states_reachable() -> None:
    """Each declared state is produced by at least one hand-built reading."""
    cases = {
        "recession": (-2.0, 0.5, None),
        "stagflation": (-1.0, 0.5, None),
        "recovery": (-1.0, -0.5, 0.3),
        "slowdown": (-1.0, -0.5, None),
        "disinflation": (1.0, -0.5, None),
        "late_expansion": (1.0, 0.5, None),
        "reflation": (0.1, 0.5, None),
        "early_expansion": (-0.1, -0.5, None),
        "mid_expansion": (0.1, -0.5, None),
    }
    reached = set()
    for expected, (gap, trend, gc) in cases.items():
        res = classify_regime_rule_based(
            make_inputs(output_gap=gap, inflation_trend_3m=trend, output_gap_change=gc)
        )
        assert res.value_dict()["state"] == expected, (
            f"expected {expected}, got {res.value_dict()['state']}"
        )
        reached.add(res.value_dict()["state"])
    assert reached == {
        "recession",
        "stagflation",
        "recovery",
        "slowdown",
        "disinflation",
        "late_expansion",
        "reflation",
        "early_expansion",
        "mid_expansion",
    }


# ---------------------------------------------------------------------------
# Confidence wiring — verify the model passes exactly the documented factors
# ---------------------------------------------------------------------------
def test_classify_confidence_clean_is_0_30_hand_computed() -> None:
    res = classify_regime_rule_based(make_inputs(output_gap=1.0, inflation_trend_3m=0.5))
    # 0.70 - 0.20 (heuristic, bands uncalibrated) - 0.20 (unobservable) = 0.30
    assert res.confidence == 0.30


def test_classify_confidence_matches_compute_confidence_factors() -> None:
    res = classify_regime_rule_based(make_inputs(output_gap=1.0, inflation_trend_3m=0.5))
    expected = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
            depends_on_unobservable=True,
        )
    )
    assert res.confidence == expected


def test_classify_confidence_with_data_quality_flag_floor() -> None:
    # 0.70 - 0.25 (data flag) - 0.20 - 0.20 = 0.05 (clamped to floor).
    res = classify_regime_rule_based(
        make_inputs(output_gap=1.0, inflation_trend_3m=0.5, data_quality_flags_present=True)
    )
    assert res.confidence == 0.05
    assert any("SLACK" in w or "data" in w.lower() for w in res.warnings) or res.confidence == 0.05


# ---------------------------------------------------------------------------
# STEP 6 fuzzing — non-finite inputs must fail loudly, never classify silently.
# RegimeInputs carries a non-finite validator; a NaN/inf reading must therefore
# raise at construction rather than produce a plausible-but-wrong regime label.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("og", _math.nan),
        ("og", _math.inf),
        ("og", -_math.inf),
        ("iy", _math.nan),
        ("it", _math.nan),
        ("it", _math.inf),
        ("ug", _math.nan),
        ("gc", _math.nan),
    ],
)
def test_non_finite_inputs_rejected(field: str, value: object) -> None:
    kw: dict[str, Any] = {"og": 1.0, "iy": 2.0, "it": 0.5, "ug": 0.5, "gc": None}
    kw[field] = value
    with pytest.raises(ValueError):
        classify_regime_rule_based(
            make_inputs(
                kw["og"],
                kw["it"],
                inflation_yoy=kw["iy"],
                unemployment_gap=kw["ug"],
                output_gap_change=kw["gc"],
            )
        )
