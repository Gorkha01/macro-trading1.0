"""Module 10 tests — oil balance, gold driver attribution, metals complex.

Written fresh for this review campaign. Every expected value is hand-computed
from the formula and the config, then asserted as a literal — never read back
out of the function under test.

Config in force, quoted so the arithmetic is checkable by hand:

    oil_balance.value_decimals              = 2
    oil_balance.reliability_value           = 0.30
    oil_balance.tight_spare_threshold_value = 2.0
    gold_driver.yield_change_threshold_bp   = 10.0
    gold_driver.crisis_vix_threshold_value  = 30.0
    gold_driver.value_decimals              = 1
    gold_driver.reliability_value           = 0.35
    metals_complex.aluminum_band_pct        = 2.0
    metals_complex.broad_weakness_threshold_pct = 2.0
    metals_complex.value_decimals           = 1
    metals_complex.reliability_value        = 0.30
    confidence                              = base 0.70, dq 0.25, heuristic 0.20,
                                              unobservable 0.20, independence 0.05
                                              (cap 0.25), floor 0.05, ceiling 0.95

Confidence, hand-derived (all three functions, all-supplied case)
-----------------------------------------------------------------
``data_quality_flags_present`` is ``fetched_legs < N`` so it is True when a leg
was supplied rather than fetched; ``is_heuristic_not_calibrated`` is True
because every reliability cap here is ``uncalibrated_illustrative``; and
``source_independence_count`` is **0 when nothing was fetched** (all three
series come through FRED, so even two fetched legs count as ONE provider — the
module is explicit that "legs are not sources").

    computed = 0.70 - 0.25 (dq) - 0.20 (heuristic) + 0 = 0.25
    oil    0.25 x 0.30 = 0.075
    gold   0.25 x 0.35 = 0.0875
    metals 0.25 x 0.30 = 0.075

The confidence is a **product**, not ``min()``: the computed half is below the
cap on no path here either, so ``min()`` would publish the cap everywhere and
make the whole ``compute_confidence`` branch dead code (the D-118 shape).

Tests supply every input, so no network fetch is attempted. The fetch-failure
paths are exercised by monkeypatching the client functions.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.data_layer import commodities_client as client
from macro_engine.models.commodities import (
    GoldDriverInputs,
    MetalsComplexInputs,
    OilBalanceInputs,
    _classify_metals,
    _direction_for,
    gold_driver_attribution,
    metals_complex_divergence,
    oil_balance_signal,
)

_S = get_settings()


def test_config_values_this_file_hand_computed_against():
    """A failure here means this file is stale, not that the model is wrong."""
    assert _S.oil_balance.value_decimals == 2
    assert _S.oil_balance.reliability_value == 0.30
    assert _S.oil_balance.tight_spare_threshold_value == 2.0
    assert _S.gold_driver.yield_change_threshold_bp == 10.0
    assert _S.gold_driver.crisis_vix_threshold_value == 30.0
    assert _S.gold_driver.reliability_value == 0.35
    assert _S.metals_complex.aluminum_band_pct == 2.0
    assert _S.metals_complex.broad_weakness_threshold_pct == 2.0
    assert _S.metals_complex.reliability_value == 0.30


# --------------------------------------------------------------------------
# oil_balance_signal
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("deviation", "tightness", "direction"),
    [
        (-1000.0, 1000.0, "tightening"),   # a DRAW (stock below norm) tightens
        (1000.0, -1000.0, "loosening"),    # a BUILD loosens
    ],
)
def test_oil_tightness_is_the_negated_deviation(deviation, tightness, direction):
    """``tightness = -inventory_deviation`` (Section 6.8)."""
    r = oil_balance_signal(
        OilBalanceInputs(
            inventory_change_weekly=deviation, opec_spare_capacity_proxy=1.0
        )
    )
    assert r.value["tightness"] == tightness
    assert r.direction == direction


def test_oil_an_exactly_seasonal_market_is_neutral_not_loosening():
    """F-COM-002. deviation == 0 means the market sits exactly on its five-year
    seasonal norm: neither tightening nor loosening.

    The specification's ``tightness > 0 else`` shape reports this as
    ``loosening`` — the D-040 class, a boundary that reports a non-event as a
    move. Two further facts are pinned:

    * the published tightness is ``0.0`` and NOT ``-0.0``: ``-0.0`` is what
      ``-deviation`` yields, and it prints "-0.0" / formats "-0.00";
    * the direction is read from the PUBLISHED (rounded) value, so a tightness
      below the declared precision cannot publish ``0.0`` beside "tightening".
    """
    r = oil_balance_signal(
        OilBalanceInputs(inventory_change_weekly=0.0, opec_spare_capacity_proxy=1.0)
    )
    assert r.value["tightness"] == 0.0
    assert repr(r.value["tightness"]) == "0.0", "must be +0.0, not IEEE-754 -0.0"
    assert r.direction == "neutral"
    assert "-0.00" not in r.interpretation

    # sub-precision: below value_decimals=2, so it publishes as neutral too
    sub = oil_balance_signal(
        OilBalanceInputs(inventory_change_weekly=-0.001, opec_spare_capacity_proxy=1.0)
    )
    assert sub.value["tightness"] == 0.0
    assert sub.direction == "neutral", "direction must not contradict the published value"


def test_oil_all_three_published_numbers_share_one_precision():
    """F-COM-003. The module's own rule is that every bare ``round(...)`` becomes
    a config-declared precision; spare capacity was the one number still raw."""
    r = oil_balance_signal(
        OilBalanceInputs(
            inventory_change_weekly=-1234.5678, opec_spare_capacity_proxy=2.3456789
        )
    )
    v = r.value
    assert v["tightness"] == 1234.57
    assert v["inventory_seasonal_deviation_thousand_barrels"] == -1234.57
    assert v["opec_spare_capacity_mbd"] == 2.35


def test_oil_confidence_is_the_product_of_two_factors():
    """Hand: computed 0.25 (dq + heuristic, 0 independence) x cap 0.30 = 0.075."""
    r = oil_balance_signal(
        OilBalanceInputs(inventory_change_weekly=-1000.0, opec_spare_capacity_proxy=1.0)
    )
    assert r.confidence == 0.075


def test_oil_confidence_rises_with_a_fetched_leg(monkeypatch):
    """A fetched pair removes the data-quality flag and adds ONE provider.

    Hand with both legs fetched: dq False, independence 1 ->
    computed = 0.70 - 0.20 + 0.05 = 0.55; x 0.30 = 0.165.
    """
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_inventory_deviation",
        lambda: (-1000.0, "FETCHED"),
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_spare_capacity",
        lambda: (1.0, "FETCHED"),
    )
    r = oil_balance_signal(OilBalanceInputs())
    assert r.confidence == 0.165


def test_oil_counts_providers_not_legs_matching_its_two_siblings(monkeypatch):
    """F-COM-004. Both oil legs are EIA series (WCESTUS1 and COPS_OPEC), so two
    fetches are ONE provider — the same rule the gold and metals functions apply
    with "legs are not sources".

    Before the fix this published 0.60 x 0.30 = 0.18 for two fetched EIA legs,
    i.e. MORE corroboration than metals claims (0.55 x 0.30) for three fetched
    legs. The three functions must agree that legs are not sources.
    """
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_inventory_deviation",
        lambda: (-1000.0, "FETCHED"),
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_spare_capacity",
        lambda: (1.0, "FETCHED"),
    )
    oil = oil_balance_signal(OilBalanceInputs())

    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_metal_leg",
        lambda *, supplied, fetcher, name, metal: (5.0, "FETCHED", True),
    )
    metals = metals_complex_divergence(MetalsComplexInputs())

    # Both must be `computed(0.55) x cap`, differing only in the cap.
    assert oil.confidence == 0.55 * 0.30
    assert metals.confidence == 0.55 * 0.30
    assert oil.confidence != 0.60 * 0.30, "two EIA legs must not count as 2 sources"


def test_oil_warns_on_negative_spare_capacity_without_clamping():
    r = oil_balance_signal(
        OilBalanceInputs(inventory_change_weekly=-500.0, opec_spare_capacity_proxy=-1.5)
    )
    assert r.value["opec_spare_capacity_mbd"] == -1.5, "reported, never clamped"
    assert any("negative" in w for w in r.warnings)


def test_oil_warns_when_spare_capacity_provides_buffer_against_a_tight_read():
    """The two inputs can disagree and the disagreement is information:
    a draw (tight) with spare >= 2.0 mb/d still has buffer."""
    r = oil_balance_signal(
        OilBalanceInputs(inventory_change_weekly=-500.0, opec_spare_capacity_proxy=3.0)
    )
    assert r.direction == "tightening"
    assert any("buffer" in w for w in r.warnings)


def test_oil_no_buffer_warning_below_the_threshold():
    r = oil_balance_signal(
        OilBalanceInputs(inventory_change_weekly=-500.0, opec_spare_capacity_proxy=1.0)
    )
    assert not any("buffer" in w for w in r.warnings)


def test_oil_refuses_when_a_leg_cannot_be_resolved(monkeypatch):
    """A tightness from one leg is a different claim, not a weaker one."""
    monkeypatch.setattr(
        "macro_engine.models.commodities._fetch_inventory_deviation",
        lambda: (None, "NOT AVAILABLE"),
    )
    with pytest.raises(ValueError) as exc:
        oil_balance_signal(OilBalanceInputs(opec_spare_capacity_proxy=1.0))
    assert "inventory_change_weekly" in str(exc.value)


def test_oil_always_carries_the_out_of_universe_warning():
    """Section 6.8: informational only, never a trade signal."""
    r = oil_balance_signal(
        OilBalanceInputs(inventory_change_weekly=-500.0, opec_spare_capacity_proxy=1.0)
    )
    assert any("standalone trade signal" in w for w in r.warnings)
    assert r.inputs_used == ["inventory_change_weekly", "opec_spare_capacity_proxy"]


def test_oil_rejects_non_finite_inputs():
    with pytest.raises(ValueError):
        OilBalanceInputs(
            inventory_change_weekly=float("nan"), opec_spare_capacity_proxy=1.0
        )
    with pytest.raises(ValueError):
        OilBalanceInputs(
            inventory_change_weekly=1.0, opec_spare_capacity_proxy=float("inf")
        )


# --------------------------------------------------------------------------
# gold_driver_attribution
# --------------------------------------------------------------------------


def test_gold_direction_is_none_because_an_attribution_has_no_direction():
    """F-COM-001. ``direction`` used to carry the dominant LAYER name
    ("real_yield", "crisis_confidence", "none_identified") in a field the
    contract defines as 'which way the value moves the underlying economic
    quantity'. A layer name is not a direction, and it duplicated
    ``value["dominant_layer"]`` verbatim.

    ``None`` is the contract's own answer ("None when the model's value has no
    direction") and is honest: this model has no gold-price input and derives no
    price direction.
    """
    for ry, trend, crisis in [
        (25.0, None, False),
        (0.0, "rising", False),
        (0.0, None, True),
        (0.0, None, False),
    ]:
        r = gold_driver_attribution(
            GoldDriverInputs(
                real_yield_change_bp=ry,
                central_bank_net_purchases_trend=trend,
                crisis_indicator=crisis,
            )
        )
        assert r.direction is None, (ry, trend, crisis)
        # the layer is still published where it belongs
        assert isinstance(r.value["dominant_layer"], str)


def test_gold_dominant_layer_is_the_first_active_one_in_specification_order():
    """real_yield, then cb_diversification, then crisis_confidence — the spec's
    own append order, so the PRIMARY channel wins when several fire."""
    all_three = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=25.0,
            central_bank_net_purchases_trend="rising",
            crisis_indicator=True,
        )
    )
    assert all_three.value["active_layers"] == [
        "real_yield",
        "cb_diversification",
        "crisis_confidence",
    ]
    assert all_three.value["dominant_layer"] == "real_yield"

    # drop the primary: the structural layer leads
    no_primary = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=0.0,
            central_bank_net_purchases_trend="rising",
            crisis_indicator=True,
        )
    )
    assert no_primary.value["dominant_layer"] == "cb_diversification"


def test_gold_real_yield_layer_fires_on_a_move_in_EITHER_direction():
    """The predicate is ``abs(change_bp) > threshold``: a real-yield FALL of
    25bp moves gold through the same opportunity-cost channel as a rise."""
    for change in (25.0, -25.0):
        r = gold_driver_attribution(
            GoldDriverInputs(
                real_yield_change_bp=change, central_bank_net_purchases_trend=None,
                crisis_indicator=False,
            )
        )
        assert r.value["dominant_layer"] == "real_yield"
    inside = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=9.9, central_bank_net_purchases_trend=None,
            crisis_indicator=False,
        )
    )
    assert inside.value["active_layers"] == []


def test_gold_real_yield_threshold_boundary_is_strict():
    """``> 10.0``: exactly 10.0 does not fire."""
    at = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=10.0, central_bank_net_purchases_trend=None,
            crisis_indicator=False,
        )
    )
    assert at.value["active_layers"] == []
    over = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=10.1, central_bank_net_purchases_trend=None,
            crisis_indicator=False,
        )
    )
    assert over.value["active_layers"] == ["real_yield"]


def test_gold_no_layer_identified_is_a_reading_not_an_error():
    r = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=0.0,
            central_bank_net_purchases_trend=None,
            crisis_indicator=False,
        )
    )
    assert r.value["dominant_layer"] == "none_identified"
    assert any("NO layer was identified" in w for w in r.warnings)


def test_gold_unresolvable_cb_trend_degrades_to_inactive_and_is_disclosed():
    """The CB layer has no free live source (a MEASURED block), so its absence is
    disclosed as 'not evaluated', NOT as evidence that CB buying is flat."""
    r = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=25.0,
            central_bank_net_purchases_trend=None,
            crisis_indicator=False,
        )
    )
    assert "cb_diversification" not in r.value["active_layers"]
    assert any("NOT evaluated" in w for w in r.warnings)
    assert any("central_bank_net_purchases_trend NOT RESOLVED" in p
               for p in r.data_provenance)


def test_gold_confidence_is_the_product_of_two_factors():
    """Hand: computed 0.25 x cap 0.35 = 0.0875."""
    r = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=25.0,
            central_bank_net_purchases_trend=None,
            crisis_indicator=False,
        )
    )
    assert r.confidence == 0.0875


def test_gold_independence_counts_providers_not_legs(monkeypatch):
    """Both live legs are FRED series: two fetches, ONE provider. Counting legs
    as sources would overstate the evidence — 'legs are not sources'."""
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_real_yield_change",
        lambda: (25.0, "FETCHED"),
    )
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_crisis_indicator",
        lambda: (False, "FETCHED"),
    )
    r = gold_driver_attribution(GoldDriverInputs())
    # Both fetched: dq False, independence 1 -> 0.70 - 0.20 + 0.05 = 0.55; x 0.35
    assert r.confidence == 0.55 * 0.35


def test_gold_refuses_when_the_primary_layer_cannot_be_resolved(monkeypatch):
    """The real-yield channel is the primary driver; a reading without it would
    silently report whichever secondary layer happened to fire."""
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_real_yield_change",
        lambda: (None, "NOT AVAILABLE"),
    )
    with pytest.raises(ValueError) as exc:
        gold_driver_attribution(GoldDriverInputs(crisis_indicator=False))
    assert "PRIMARY layer" in str(exc.value)


def test_gold_refuses_when_the_crisis_layer_cannot_be_resolved(monkeypatch):
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_crisis_indicator",
        lambda: (None, "NOT AVAILABLE"),
    )
    with pytest.raises(ValueError) as exc:
        gold_driver_attribution(GoldDriverInputs(real_yield_change_bp=25.0))
    assert "CRISIS layer" in str(exc.value)


def test_gold_trend_vocabulary_is_enforced_so_a_typo_is_visible():
    """Appendix D matches the exact string, so "raise" would silently read as
    'this layer is inactive'."""
    for bad in ("raise", "RISING", "Rising", "", "rising "):
        with pytest.raises(ValueError):
            GoldDriverInputs(
                real_yield_change_bp=1.0,
                central_bank_net_purchases_trend=bad,
                crisis_indicator=False,
            )
    for good in ("rising", "flat", "falling"):
        GoldDriverInputs(
            real_yield_change_bp=1.0,
            central_bank_net_purchases_trend=good,
            crisis_indicator=False,
        )


def test_gold_only_rising_activates_the_cb_layer():
    """'flat' and 'falling' are in the vocabulary but are NOT active."""
    for trend in ("flat", "falling"):
        r = gold_driver_attribution(
            GoldDriverInputs(
                real_yield_change_bp=0.0,
                central_bank_net_purchases_trend=trend,
                crisis_indicator=False,
            )
        )
        assert "cb_diversification" not in r.value["active_layers"]


def test_gold_warns_that_gold_is_not_a_simple_inflation_hedge():
    """Appendix D's central correction, on every call."""
    r = gold_driver_attribution(
        GoldDriverInputs(
            real_yield_change_bp=25.0,
            central_bank_net_purchases_trend=None,
            crisis_indicator=False,
        )
    )
    assert any("NOT a simple inflation hedge" in w for w in r.warnings)
    assert any("INFORMATIONAL ONLY" in w for w in r.warnings)


def test_gold_rejects_non_finite_real_yield():
    with pytest.raises(ValueError):
        GoldDriverInputs(real_yield_change_bp=float("nan"), crisis_indicator=False)


# --------------------------------------------------------------------------
# metals_complex_divergence
# --------------------------------------------------------------------------


def test_metals_china_construction_specific_hand_computed():
    """iron ore falls HARDEST, copper also falls, aluminum FLAT (|al| < 2.0).

    copper -5.0, iron -8.0, aluminum 0.0 -> -8 < -5 < 0 and |0| < 2.0 -> CHINA.
    """
    r = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-5.0, iron_ore_change_pct=-8.0, aluminum_change_pct=0.0
        )
    )
    assert r.value["verdict"] == "CHINA_CONSTRUCTION_SPECIFIC"
    assert any("STABILITY is the discriminating evidence" in w for w in r.warnings)


def test_metals_broad_industrial_weakness_hand_computed():
    """ALL THREE below -2.0."""
    r = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-5.0, iron_ore_change_pct=-8.0, aluminum_change_pct=-3.0
        )
    )
    assert r.value["verdict"] == "BROAD_INDUSTRIAL_WEAKNESS"
    assert any("NOT construction-specific" in w for w in r.warnings)


def test_metals_mixed_when_neither_pattern_holds():
    """iron ore NOT falling hardest (-0.5 > -1.0), so the construction test's
    `iron_ore < copper` fails; nothing is near the broad threshold either.
    (An earlier draft of this test used iron -1.5, which DOES fall hardest and
    so correctly returns CHINA_CONSTRUCTION_SPECIFIC.)
    """
    r = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-1.0, iron_ore_change_pct=-0.5, aluminum_change_pct=0.5
        )
    )
    assert r.value["verdict"] == "MIXED_no_clear_pattern"
    assert any("NO clear pattern" in w for w in r.warnings)


def test_metals_construction_test_requires_iron_ore_to_fall_hardest():
    """`iron_ore < copper < 0`: equal falls, or copper falling harder, do not
    localise the shock to construction."""
    equal = _classify_metals(
        copper=-5.0, iron_ore=-5.0, aluminum=0.0,
        aluminum_band_pct=2.0, broad_weakness_threshold_pct=2.0,
    )
    assert equal == "MIXED_no_clear_pattern", "-5 < -5 is False"

    copper_worse = _classify_metals(
        copper=-8.0, iron_ore=-5.0, aluminum=0.0,
        aluminum_band_pct=2.0, broad_weakness_threshold_pct=2.0,
    )
    assert copper_worse == "MIXED_no_clear_pattern"


def test_metals_threshold_boundaries_are_strict():
    """`all(v < -2.0)`: exactly -2.0 does not count as broad weakness."""
    at = _classify_metals(
        copper=-2.0, iron_ore=-2.0, aluminum=-2.0,
        aluminum_band_pct=2.0, broad_weakness_threshold_pct=2.0,
    )
    assert at != "BROAD_INDUSTRIAL_WEAKNESS"

    over = _classify_metals(
        copper=-2.001, iron_ore=-2.001, aluminum=-2.001,
        aluminum_band_pct=2.0, broad_weakness_threshold_pct=2.0,
    )
    assert over == "BROAD_INDUSTRIAL_WEAKNESS"

    # aluminum band: |aluminum| < 2.0, so exactly 2.0 is not "flat"
    at_band = _classify_metals(
        copper=-5.0, iron_ore=-8.0, aluminum=2.0,
        aluminum_band_pct=2.0, broad_weakness_threshold_pct=2.0,
    )
    assert at_band != "CHINA_CONSTRUCTION_SPECIFIC"


def test_metals_the_two_branches_are_mutually_exclusive_as_documented():
    """The module claims the if/elif order DECIDES NOTHING because the two tests
    cannot both hold with positive bands. That claim is config-dependent, so it
    is asserted as a sweep rather than trusted: a future config that raised
    aluminum_band_pct above broad_weakness_threshold_pct would silently make the
    documented precedence load-bearing.
    """
    band = _S.metals_complex.aluminum_band_pct
    thr = _S.metals_complex.broad_weakness_threshold_pct
    assert band > 0 and thr > 0

    overlaps = []
    for cu in (-8.0, -5.0, -2.0, -1.0, -0.5, 0.0, 0.5, 2.0):
        for io in (-8.0, -5.0, -2.0, -1.0, -0.5, 0.0):
            for al in (-8.0, -3.0, -1.5, -1.0, -0.5, -0.1, 0.0, 0.5, 2.0):
                constr = io < cu < 0 and abs(al) < band
                broad = all(v < -thr for v in (cu, io, al))
                if constr and broad:
                    overlaps.append((cu, io, al))
    assert not overlaps, f"the two branches now overlap: {overlaps[:5]}"
    assert band <= thr


def test_metals_band_ordering_is_refused_by_config_not_merely_observed():
    """F-COM-005. The mutual-exclusivity of the two verdicts is a property of the
    CONFIG (``aluminum_band_pct <= broad_weakness_threshold_pct``), so it is
    enforced at load time — Section 21's "configuration errors are startup
    errors" rule — rather than left to a test that only inspects today's values.

    Before this guard existed, raising the band above the threshold produced
    overlapping verdicts where the if/elif order silently demoted
    BROAD_INDUSTRIAL_WEAKNESS to CHINA_CONSTRUCTION_SPECIFIC, with nothing
    failing.
    """
    from macro_engine.config import CalibratedValue, MetalsComplexSettings

    def _leaf(value):
        return CalibratedValue(value=value, calibration_status="uncalibrated_illustrative")

    def build(band, threshold):
        return MetalsComplexSettings(
            reliability_cap=_leaf(0.30),
            value_decimals_leaf=_leaf(1),
            aluminum_stability_band_pct_leaf=_leaf(band),
            broad_weakness_threshold_pct_leaf=_leaf(threshold),
        )

    # Equal (today's config) and strictly smaller are both fine.
    assert build(2.0, 2.0).aluminum_band_pct == 2.0
    assert build(1.0, 2.0).aluminum_band_pct == 1.0

    # The band ABOVE the threshold is refused, and the message says why.
    with pytest.raises(ValueError) as exc:
        build(3.0, 2.0)
    msg = str(exc.value)
    assert "must not exceed" in msg
    assert "if/elif" in msg, "the message must name the consequence"

    # And a config that fails it cannot even be loaded: the guard is on the
    # settings model, not on a helper the model function happens to call.
    with pytest.raises(ValueError):
        build(2.5, 2.0)


def test_metals_direction_comes_from_the_signs_not_the_verdict_label():
    """D-131. The direction used to be `"expansionary" if verdict == MIXED else
    "restrictive"` — derived from the LABEL. Measured before the fix: an
    ALL-FALLING complex (copper -1.0, iron -0.5, aluminum -1.0) published
    "expansionary" because its pattern was MIXED.
    """
    all_falling = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-1.0, iron_ore_change_pct=-0.5, aluminum_change_pct=-1.0
        )
    )
    assert all_falling.value["verdict"] == "MIXED_no_clear_pattern"
    assert all_falling.direction == "restrictive", (
        "every metal is falling; the direction must say so"
    )

    second = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-1.9, iron_ore_change_pct=-0.1, aluminum_change_pct=-1.9
        )
    )
    assert second.direction == "restrictive"


def test_metals_direction_all_rising_and_mixed():
    rising = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=1.0, iron_ore_change_pct=2.0, aluminum_change_pct=0.5
        )
    )
    assert rising.direction == "expansionary"

    mixed = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-1.0, iron_ore_change_pct=1.0, aluminum_change_pct=1.0
        )
    )
    assert mixed.direction == "neutral"


def test_metals_direction_zero_is_treated_as_not_falling():
    """A flat metal makes the falling test fail: `>= 0` for rising, `< 0` for
    falling. Three flat metals read 'expansionary' — a flat complex is not
    contracting — and that is documented behaviour, not an accident."""
    assert _direction_for(copper=0.0, iron_ore=0.0, aluminum=0.0) == "expansionary"
    assert _direction_for(copper=-1.0, iron_ore=-1.0, aluminum=0.0) == "neutral"


def test_metals_confidence_is_the_product_of_two_factors():
    """Hand: computed 0.25 x cap 0.30 = 0.075."""
    r = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-5.0, iron_ore_change_pct=-8.0, aluminum_change_pct=0.0
        )
    )
    assert r.confidence == 0.075


def test_metals_independence_counts_providers_not_legs(monkeypatch):
    """All three are IMF Primary Commodity Prices via FRED: three fetches, ONE
    provider family."""
    def fake(sym, value):
        def _f(as_of):
            raise AssertionError("should not reach the client")
        return _f

    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_metal_leg",
        lambda *, supplied, fetcher, name, metal: (5.0, "FETCHED", True),
    )
    r = metals_complex_divergence(MetalsComplexInputs())
    # all three fetched: dq False (3 == 3), independence 1
    # -> 0.70 - 0.20 + 0.05 = 0.55; x 0.30
    assert r.confidence == 0.55 * 0.30


def test_metals_refuses_when_a_leg_cannot_be_resolved(monkeypatch):
    """A missing leg is a DIFFERENT pattern, not a weaker verdict."""
    monkeypatch.setattr(
        "macro_engine.models.commodities._resolve_metal_leg",
        lambda *, supplied, fetcher, name, metal: (None, "NOT AVAILABLE", False),
    )
    with pytest.raises(ValueError) as exc:
        metals_complex_divergence(MetalsComplexInputs())
    msg = str(exc.value)
    for leg in ("copper_change_pct", "iron_ore_change_pct", "aluminum_change_pct"):
        assert leg in msg


def test_metals_all_three_changes_are_published_alongside_the_verdict():
    """A bare label over unreported inputs is the D-037 shape."""
    r = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-5.0, iron_ore_change_pct=-8.0, aluminum_change_pct=0.0
        )
    )
    assert r.value["copper_change_pct"] == -5.0
    assert r.value["iron_ore_change_pct"] == -8.0
    assert r.value["aluminum_change_pct"] == 0.0
    assert r.inputs_used == [
        "copper_change_pct",
        "iron_ore_change_pct",
        "aluminum_change_pct",
    ]


def test_metals_warns_that_copper_is_not_a_clean_global_growth_proxy():
    r = metals_complex_divergence(
        MetalsComplexInputs(
            copper_change_pct=-5.0, iron_ore_change_pct=-8.0, aluminum_change_pct=0.0
        )
    )
    assert any("~50% China demand" in w for w in r.warnings)
    assert any("INFORMATIONAL ONLY" in w for w in r.warnings)


def test_metals_rejects_non_finite_inputs():
    with pytest.raises(ValueError):
        MetalsComplexInputs(
            copper_change_pct=float("nan"),
            iron_ore_change_pct=1.0,
            aluminum_change_pct=1.0,
        )
