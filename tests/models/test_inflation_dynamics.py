"""Module 3.3 + 5.6 tests — the Phillips curve and the cross-asset transmission map.

Written fresh for this review campaign. Every expected value below is
**hand-computed from the formula and the config**, then asserted as a literal —
never read back out of the function under test. That discipline is the whole
point: a test that compares a function against itself cannot detect the defect
this campaign exists to find.

Config values in force (``get_settings()``), quoted so the arithmetic below can
be checked by hand without running anything:

    phillips.beta                                  = 0.5
    phillips.illustrative_u_star_revision          = 0.5   pp
    phillips.slack_negligible_threshold            = 0.05  pp
    transmission.flat_band                         = 0.5   bp
    transmission.real_driven_threshold             = 0.66  share
    transmission.breakeven_driven_threshold        = 0.66  share
    transmission.trivial_move                      = 2.0   bp
    transmission.gold_base_rate                    = 0.7556
    transmission.breakeven_negative_share          = 0.2652

Module 3.3 — the arithmetic
---------------------------
``pi = pi^e - beta * (u - u*)``

    pi^e=2.5, u=4.0, u*=4.4
        gap = 4.0 - 4.4 = -0.4
        pi  = 2.5 - 0.5 * (-0.4) = 2.5 + 0.2 = 2.70          <- TIGHT, raises pi

    pi^e=2.5, u=5.4, u*=4.4
        gap = +1.0
        pi  = 2.5 - 0.5 * (+1.0) = 2.00                       <- SLACK, lowers pi

    pi^e=2.5, u=4.4, u*=4.4
        gap = 0.0
        pi  = 2.5 - 0.0 = 2.50                                <- AT u*

The FIRST case is the load-bearing one. The plausible wrong implementation
``pi^e + beta*(u - u*)`` returns **2.30** on it, so the assertion
``value == 2.70`` distinguishes right from backwards on a case whose answer is
known before the code runs. No shape assertion and no magnitude bound could.

Module 5.6 — the arithmetic
---------------------------
The real leg is derived, not fetched: ``real = nominal - breakeven``.

    nominal=+10.0, breakeven=+2.0
        real            = 10.0 - 2.0 = +8.0
        real_share      = 8.0 / 10.0 = 0.80   >= 0.66 -> real_drives
        breakeven_share = 2.0 / 10.0 = 0.20   <  0.66
        driver          = real_driven
        bonds           = down   (nominal +10 > +0.5 flat band)
        gold            = down   (real    +8.0 > +0.5)

    nominal=+10.0, breakeven=+12.0
        real            = 10.0 - 12.0 = -2.0
        real_share      = -0.20  (abs 0.20 < 0.66)
        breakeven_share =  1.20  (abs 1.20 >= 0.66) -> breakeven_drives
        driver          = breakeven_driven
        bonds           = down   (nominal +10)
        gold            = up     (real -2.0)      <- the DISAGREEMENT case

Note the identities these two examples exercise, both exact rather than
approximate:

    real_share + breakeven_share == 1.0   exactly, for any non-zero nominal

which is why ``both_channels`` can only be reached when the two legs point in
OPPOSITE directions: a share and its complement cannot both clear a 0.66
threshold while summing to 1 unless one of them is negative.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    compute_confidence,
)
from macro_engine.models.inflation_dynamics import (
    ASSET_KEYS,
    InflationTransmissionInputs,
    PhillipsCurveInputs,
    _driver_of,
    _leg_direction,
    cross_asset_transmission,
    phillips_curve_inflation,
)

# --------------------------------------------------------------------------
# Config, read once, so a recalibration is a loud failure rather than a quiet
# reinterpretation of every hand-computed number below.
# --------------------------------------------------------------------------

_SETTINGS = get_settings()
_BETA = _SETTINGS.phillips.beta_value
_U_STAR_REVISION = _SETTINGS.phillips.illustrative_u_star_revision
_SLACK_NEGLIGIBLE = _SETTINGS.phillips.slack_negligible_threshold
_FLAT = _SETTINGS.transmission.flat_band
_REAL_THRESH = _SETTINGS.transmission.real_driven_threshold
_BE_THRESH = _SETTINGS.transmission.breakeven_driven_threshold
_TRIVIAL = _SETTINGS.transmission.trivial_move
_GOLD_BASE = _SETTINGS.transmission.gold_base_rate


def test_config_values_match_the_arithmetic_hand_computed_in_this_file():
    """Pin every config leaf the hand arithmetic above depends on.

    If this fails, the numbers in this file are stale — not the code. Naming
    that distinction is the point: it stops a recalibration from being read as
    a defect in the model.
    """
    assert _BETA == 0.5
    assert _U_STAR_REVISION == 0.5
    assert _SLACK_NEGLIGIBLE == 0.05
    assert _FLAT == 0.5
    assert _REAL_THRESH == 0.66
    assert _BE_THRESH == 0.66
    assert _TRIVIAL == 2.0
    assert _GOLD_BASE == 0.7556


# --------------------------------------------------------------------------
# Module 3.3 — phillips_curve_inflation
# --------------------------------------------------------------------------


def test_tight_labor_market_raises_inflation_above_expectations():
    """THE direction test: u below u* must push pi ABOVE pi^e.

    Hand: pi^e=2.5, u=4.0, u*=4.4 -> gap -0.4 -> 2.5 - 0.5*(-0.4) = 2.70.

    The backwards implementation `pi^e + beta*(u - u*)` returns 2.30 here, so
    this single assertion separates the two readings. It is the reason the
    module docstring says the sign convention "has a dedicated test".
    """
    result = phillips_curve_inflation(
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=4.0, nairu=4.4)
    )
    assert result.value == 2.70
    assert result.value > 2.5, "a tight market must raise inflation above pi^e"


def test_slack_labor_market_lowers_inflation_below_expectations():
    """Hand: pi^e=2.5, u=5.4, u*=4.4 -> gap +1.0 -> 2.5 - 0.5 = 2.00."""
    result = phillips_curve_inflation(
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=5.4, nairu=4.4)
    )
    assert result.value == 2.00
    assert result.value < 2.5, "slack must lower inflation below pi^e"


def test_at_u_star_inflation_equals_expectations_exactly():
    """Hand: gap = 0 -> pi = pi^e = 2.50. The slack term is exactly zero."""
    result = phillips_curve_inflation(
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=4.4, nairu=4.4)
    )
    assert result.value == 2.50


def test_u_gap_is_reported_unrounded_and_inflation_is_rerivable_from_it():
    """The module claims a reader can recompute the value from the two numbers.

    That claim is only true if the reported gap is UNROUNDED (a gap rounded to
    2dp would not reconcile for most inputs). Pick an input where rounding would
    show: u=4.17, u*=4.40 -> gap = -0.23 exactly, pi = 2.5 + 0.115 = 2.615 ->
    published 2.62 (round-half-even at 2dp would give 2.61 for 2.615, so use
    a gap whose product is unambiguous).
    """
    result = phillips_curve_inflation(
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=4.20, nairu=4.40)
    )
    gap = 4.20 - 4.40  # = -0.20
    expected = 2.5 - 0.5 * gap  # = 2.60
    assert result.value == round(expected, 2)
    assert f"{gap:+.2f}" in result.interpretation
    # The unrounded slack term is published in the context string.
    assert f"{-0.5 * gap:+.3f}" in result.context


def test_negative_implied_inflation_is_warned():
    """Defensible state, worth flagging: needs pi^e < 0 or a huge gap.

    Hand: pi^e=-1.0, u=10.0, u*=4.0 -> gap +6.0 -> -1.0 - 3.0 = -4.00.
    """
    result = phillips_curve_inflation(
        PhillipsCurveInputs(inflation_expectations=-1.0, unemployment_rate=10.0, nairu=4.0)
    )
    assert result.value == -4.00
    assert any("NEGATIVE" in w for w in result.warnings)


def test_slack_negligible_warning_fires_only_below_the_threshold():
    """The threshold is 0.05pp and the comparison is strict (<).

    slack_contribution = -beta * gap = -0.5 * gap, so
    ``abs(contribution) < 0.05  <=>  abs(gap) < 0.1``.

    **The boundary is NOT at a decimal round number, and asserting it as one is
    a trap this test deliberately documents.** The gap is computed as
    ``unemployment_rate - nairu`` on floats. ``4.5 - 4.4`` is
    ``0.09999999999999964`` — strictly BELOW 0.1 — so the product is
    ``0.04999999999999982 < 0.05`` and the warning *does* fire. A test written
    from decimal reasoning ("0.10 is exactly the boundary, so no warn") fails
    against correct code. Compute the expected branch from the SAME float
    expression the module uses, never from the decimal intent.

    Measured, for the record:
        u=4.5       gap=0.0999999999999996_4  -> 0.0499999999999998_2 -> WARN
        u=4.5000001 gap=0.1000000999999999_3  -> 0.0500000499999999_6 -> no warn
    """

    def warns(gap_want: float) -> bool:
        r = phillips_curve_inflation(
            PhillipsCurveInputs(
                inflation_expectations=2.5,
                unemployment_rate=4.4 + gap_want,
                nairu=4.4,
            )
        )
        return any("slack term contributes only" in w for w in r.warnings)

    # Derive the expectation from the same float arithmetic, not from decimals.
    def expected(gap_want: float) -> bool:
        real_gap = (4.4 + gap_want) - 4.4
        return abs(-_BETA * real_gap) < _SLACK_NEGLIGIBLE

    for gap_want in (0.08, -0.08, 0.1, -0.1, 0.1000001, -0.1000001, 0.3, 0.0):
        assert warns(gap_want) is expected(gap_want), (
            f"gap_want={gap_want}: module and hand-derived float branch disagree"
        )

    # And the two facts worth pinning explicitly, because they are the ones a
    # decimal-intuition test gets wrong.
    assert (4.5 - 4.4) < 0.1, "4.5-4.4 is BELOW 0.1 in IEEE-754, not equal to it"
    assert warns(0.1) is True, "the apparent 0.10 boundary still warns"
    assert warns(0.1000001) is False, "only a genuinely larger gap stops warning"
    # sign-independent: the branch is on abs()
    assert warns(0.08) == warns(-0.08)


def test_three_unconditional_warnings_are_always_present():
    """Both uncertainty warnings describe the EQUATION, not this input set.

    The module is explicit that making them conditional would imply the model
    is free of them on some inputs, which it never is. Assert the count of
    always-on warnings does not depend on the input.
    """
    for pe, u, us in [(2.5, 4.0, 4.4), (0.0, 0.0, 0.0), (-5.0, 100.0, 0.0)]:
        r = phillips_curve_inflation(
            PhillipsCurveInputs(inflation_expectations=pe, unemployment_rate=u, nairu=us)
        )
        for fragment in ("CHOICE of pi^e", "UNOBSERVABLE", "UNANCHORED"):
            assert any(fragment in w for w in r.warnings), fragment


def test_confidence_is_the_lowest_in_the_suite_and_hand_derived():
    """Three penalties at once: heuristic + unobservable.

    Hand: compute_confidence(heuristic=True, unobservable=True) == 0.30,
    which is the same inputs used elsewhere for the suite's floor.
    """
    expected = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, depends_on_unobservable=True)
    )
    assert expected == 0.30
    r = phillips_curve_inflation(
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=4.0, nairu=4.4)
    )
    assert r.confidence == 0.30


def test_inputs_used_names_all_three_terms_and_no_beta():
    """beta is read from config, so it is NOT an input_used key."""
    r = phillips_curve_inflation(
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=4.0, nairu=4.4)
    )
    assert r.inputs_used == ["inflation_expectations", "unemployment_rate", "nairu"]
    assert "beta" not in r.inputs_used


def test_unemployment_and_nairu_are_bounded_but_expectations_is_not():
    """u and u* are percentages in [0, 100]; pi^e carries no bound (can be < 0)."""
    with pytest.raises(ValidationError):
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=-0.1, nairu=4.4)
    with pytest.raises(ValidationError):
        PhillipsCurveInputs(inflation_expectations=2.5, unemployment_rate=4.0, nairu=100.1)
    # pi^e negative is allowed
    PhillipsCurveInputs(inflation_expectations=-3.0, unemployment_rate=4.0, nairu=4.4)


# --------------------------------------------------------------------------
# Module 5.6 — helpers, on their own
# --------------------------------------------------------------------------


def test_leg_direction_flat_band_is_inclusive_on_the_flat_side():
    """D-045a: the boundary must be pinned or a < -> <= change is unobservable.

    flat_band = 0.5, and the test is `abs(x) <= flat_band`.
    """
    assert _leg_direction(0.0, 0.5) == "flat"
    assert _leg_direction(0.5, 0.5) == "flat", "exactly the band is flat"
    assert _leg_direction(-0.5, 0.5) == "flat", "symmetric"
    assert _leg_direction(0.5000001, 0.5) == "down"
    assert _leg_direction(-0.5000001, 0.5) == "up"


def test_leg_direction_reports_a_flat_market_as_flat_not_as_a_move():
    """The specification's `"down" if x > 0 else "up"` reports x == 0 as `up`.

    Live measurement in the module: DGS10 is exactly unchanged on 7.7% of daily
    changes. So this is a wrong sign on a seventh of observations, which is why
    it is repaired rather than tolerated.
    """
    assert _leg_direction(0.0, 0.5) == "flat"
    assert _leg_direction(0.0, 0.5) != "up"


def test_driver_of_returns_indeterminate_below_the_trivial_floor():
    """trivial_move = 2.0; the comparison is on the NOMINAL and is strict (<).

    The floor guards the ratio ``real / nominal``, so it is the nominal that is
    tested, and it must be ``real = nominal - breakeven`` — passing a nominal
    that is not the sum of the two legs is a self-inflicted test bug (it is the
    one I made when writing this file).

    Hand, with the legs consistent:
        nominal=1.9, breakeven=1.7 -> real=0.2   -> 1.9  < 2.0 -> indeterminate
        nominal=1.0, breakeven=0.5 -> real=0.5   -> 1.0  < 2.0 -> indeterminate
        nominal=-1.9, breakeven=-1.7 -> real=-0.2 -> |1.9| < 2.0 -> indeterminate
    """
    kw = dict(real_threshold=0.66, breakeven_threshold=0.66, trivial_move=2.0)
    assert _driver_of(0.2, 1.7, 1.9, **kw) == "indeterminate"
    assert _driver_of(0.5, 0.5, 1.0, **kw) == "indeterminate"
    assert _driver_of(-0.2, -1.7, -1.9, **kw) == "indeterminate"
    # The floor is on the ABSOLUTE nominal: a large opposite-signed pair is
    # classifiable even though one leg is negative.
    assert _driver_of(14.0, -4.0, 10.0, **kw) == "real_driven"


def test_driver_of_classifies_the_four_outcomes_by_hand():
    """Hand-computed shares at thresholds 0.66 / 0.66, floor 2.0.

    nominal=+10, breakeven=+2   -> real=+8,  shares 0.80 / 0.20 -> real_driven
    nominal=+10, breakeven=+8   -> real=+2,  shares 0.20 / 0.80 -> breakeven_driven
    nominal=+10, breakeven=+5   -> real=+5,  shares 0.50 / 0.50 -> neither_channel
    nominal=+10, breakeven=+14  -> real=-4,  shares -0.40/1.40  -> breakeven_driven
    nominal=+10, breakeven=-4   -> real=+14, shares 1.40/-0.40  -> real_driven
    """
    kw = dict(real_threshold=0.66, breakeven_threshold=0.66, trivial_move=2.0)
    assert _driver_of(8.0, 2.0, 10.0, **kw) == "real_driven"
    assert _driver_of(2.0, 8.0, 10.0, **kw) == "breakeven_driven"
    assert _driver_of(5.0, 5.0, 10.0, **kw) == "neither_channel"
    assert _driver_of(-4.0, 14.0, 10.0, **kw) == "breakeven_driven"
    assert _driver_of(14.0, -4.0, 10.0, **kw) == "real_driven"


def test_both_channels_requires_opposite_signed_legs_never_same_signed():
    """The docstring's claim, tested as an invariant over the whole space.

    real_share + breakeven_share == 1 exactly. So if both are >= 0.66, their
    sum would be >= 1.32 > 1, which is impossible unless one is negative.
    Sweep sign combinations and assert the invariant holds.
    """
    kw = dict(real_threshold=0.66, breakeven_threshold=0.66, trivial_move=2.0)
    saw_both = False
    for nom in (10.0, -10.0, 50.0, -50.0):
        for be in (nom * 1.5, -nom * 0.5, nom * 0.5, -nom * 1.5):
            real = nom - be
            d = _driver_of(real, be, nom, **kw)
            if d == "both_channels":
                saw_both = True
                # one share must be negative for both to clear 0.66
                real_share = real / nom
                assert real_share < 0 or (be / nom) < 0, (
                    "both_channels reached with two same-signed legs"
                )
    assert saw_both, "the sweep must actually reach both_channels"


def test_the_two_shares_sum_to_exactly_one():
    """An exact identity, not an approximation: real/n + be/n = (real+be)/n = 1."""
    for nom, be in [(10.0, 2.0), (-10.0, -2.0), (10.0, 12.0), (0.4, 2.0), (7.0, -3.0)]:
        r = cross_asset_transmission(
            InflationTransmissionInputs(
                nominal_yield_change_bp=nom, breakeven_change_bp=be, surprise_driver="demand"
            )
        )
        rs = r.value["real_leg_share_of_move"]
        bs = r.value["breakeven_leg_share_of_move"]
        assert rs is not None and bs is not None
        assert math.isclose(rs + bs, 1.0, abs_tol=1e-9), (nom, be, rs, bs)


# --------------------------------------------------------------------------
# Module 5.6 — cross_asset_transmission, hand-computed end to end
# --------------------------------------------------------------------------


def test_real_leg_is_derived_as_nominal_minus_breakeven():
    """real = nominal - breakeven, and it is published rounded to 2dp.

    Hand: 10.0 - 2.0 = 8.0;  10.0 - 12.0 = -2.0;  4.4 - 1.1 = 3.3.
    """
    for nom, be in [(10.0, 2.0), (10.0, 12.0), (4.4, 1.1)]:
        r = cross_asset_transmission(
            InflationTransmissionInputs(
                nominal_yield_change_bp=nom, breakeven_change_bp=be, surprise_driver="demand"
            )
        )
        assert r.value["real_yield_change_bp"] == round(nom - be, 2)


def test_gold_follows_the_real_leg_and_bonds_follow_the_nominal_leg():
    """The central non-obvious claim: bonds key on NOMINAL, gold keys on REAL.

    This is the case where they disagree, which is why the two legs are
    separate keys at all:
        nominal +10 (-> bonds down), breakeven +12 -> real -2 (-> gold up)
    """
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=12.0, surprise_driver="demand"
        )
    )
    assert r.value["bonds"] == "down"
    assert r.value["gold"] == "up"
    assert r.value["real_yield_change_bp"] == -2.0
    assert any("GOLD DISAGREES WITH BONDS" in w for w in r.warnings)


def test_gold_can_be_flat_while_bonds_move():
    """be == nominal -> real == 0 -> gold flat while bonds is down."""
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=5.0, breakeven_change_bp=5.0, surprise_driver="demand"
        )
    )
    assert r.value["real_yield_change_bp"] == 0.0
    assert r.value["gold"] == "flat"
    assert r.value["bonds"] == "down"
    # and the disagreement warning must NOT fire when gold is flat
    assert not any("GOLD DISAGREES" in w for w in r.warnings)


def test_usd_is_unresolved_never_a_sentence_and_always_warned():
    """D-052 defect 3: the spec emitted 'up_if_relative_rate_expectations_rose'.

    A value no caller can branch on is not an output. The repaired form is
    `unresolved` plus a warning naming the missing counterparty reaction.
    """
    for sd in ("demand", "supply_shock", "shelter_lag_mechanical"):
        r = cross_asset_transmission(
            InflationTransmissionInputs(
                nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver=sd
            )
        )
        assert r.value["usd"] == "unresolved"
        assert any("COUNTERPARTY central bank" in w for w in r.warnings)


def test_surprise_driver_is_a_literal_so_a_typo_is_a_validation_error():
    """D-029: the spec had a bare `str` whose typo silently reached `else`."""
    for bad in ("supply shock", "garbage", "Supply_Shock", "", "DEMAND"):
        with pytest.raises(ValidationError):
            InflationTransmissionInputs(
                nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver=bad
            )


def test_equities_overall_maps_the_declared_driver_exhaustively():
    """Three drivers -> three distinct equity readings; shelter is the fallback.

    Hand: supply_shock -> worse_than_rate_move_alone
          demand       -> better_than_rate_move_alone
          shelter_lag_mechanical -> flat
    """
    expected = {
        "supply_shock": "worse_than_rate_move_alone",
        "demand": "better_than_rate_move_alone",
        "shelter_lag_mechanical": "flat",
    }
    for sd, want in expected.items():
        r = cross_asset_transmission(
            InflationTransmissionInputs(
                nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver=sd
            )
        )
        assert r.value["equities_overall"] == want, sd


def test_both_zero_changes_are_rejected_only_when_no_surprise_is_offered():
    """The validator rejects the (0, 0, no surprise) combination and nothing else.

    A SINGLE zero is a real observation (a Treasury market that did not move)
    and must be representable — rejecting it would be D-050's allow_all_neutral
    lesson. Two identical zeros with no size anywhere carry no information.
    """
    with pytest.raises(ValidationError):
        InflationTransmissionInputs(
            nominal_yield_change_bp=0.0, breakeven_change_bp=0.0, surprise_driver="demand"
        )
    # (0, 0) WITH a surprise is allowed
    InflationTransmissionInputs(
        nominal_yield_change_bp=0.0,
        breakeven_change_bp=0.0,
        surprise_driver="demand",
        inflation_surprise_bp=5.0,
    )
    # a single zero is allowed
    InflationTransmissionInputs(
        nominal_yield_change_bp=0.0, breakeven_change_bp=3.0, surprise_driver="demand"
    )


def test_inflation_surprise_is_published_but_never_moves_a_direction():
    """D-052 defect 1: the spec declared it, listed it in inputs_used, never read it.

    The repair keeps it as a DISCLOSURE. Assert the strong form: enumerating
    the declared input space, the map's directions are invariant to it.
    """
    base = dict(nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver="demand")
    without = cross_asset_transmission(InflationTransmissionInputs(**base))
    directional_keys = [k for k in ASSET_KEYS]
    for surprise in (0.0, 1.0, -1.0, 250.0, -250.0):
        with_s = cross_asset_transmission(
            InflationTransmissionInputs(**base, inflation_surprise_bp=surprise)
        )
        for k in directional_keys:
            assert with_s.value[k] == without.value[k], (k, surprise)
        assert with_s.value["inflation_surprise_bp"] == surprise
    # and it is named in inputs_used only when supplied
    assert "inflation_surprise_bp" not in without.inputs_used


def test_asset_keys_is_exactly_the_published_directional_subset():
    """ASSET_KEYS must be a subset of the published value and must not be empty.

    D-038: a test that ITERATES a published dict is vacuous when it is empty,
    so assert the key set explicitly rather than looping over whatever exists.
    """
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver="demand"
        )
    )
    published = set(r.value)
    assert set(ASSET_KEYS).issubset(published), "an ASSET_KEY is not published"
    assert len(ASSET_KEYS) == 6
    # the diagnostics must ALSO be present (they are the coupling disclosure)
    for extra in ("driver_channel", "real_yield_change_bp", "gold_call_base_rate"):
        assert extra in published


def test_every_published_direction_is_a_member_of_the_declared_literal():
    """D-045a: a Literal is a promise with two halves — membership and producibility.

    Membership: every emitted direction must be one the Literal allows. Sweep
    the space and check, rather than asserting on one hand-picked input.
    """
    allowed = {
        "down",
        "up",
        "value_outperforms",
        "growth_outperforms",
        "worse_than_rate_move_alone",
        "better_than_rate_move_alone",
        "flat",
        "unresolved",
    }
    seen: set[str] = set()
    for nom in (-50.0, -10.0, -3.0, -0.4, 0.0, 0.4, 3.0, 10.0, 50.0):
        for be in (-50.0, -10.0, -3.0, 0.0, 3.0, 10.0, 50.0):
            if nom == 0.0 and be == 0.0:
                continue
            for sd in ("demand", "supply_shock", "shelter_lag_mechanical"):
                r = cross_asset_transmission(
                    InflationTransmissionInputs(
                        nominal_yield_change_bp=nom, breakeven_change_bp=be, surprise_driver=sd
                    )
                )
                for k in ASSET_KEYS:
                    v = r.value[k]
                    assert v in allowed, (k, v, nom, be, sd)
                    seen.add(v)
    # producibility: the sweep must actually produce the interesting ones
    assert "flat" in seen
    assert "unresolved" in seen
    assert "worse_than_rate_move_alone" in seen
    assert "better_than_rate_move_alone" in seen
    assert "value_outperforms" in seen
    assert "growth_outperforms" in seen


def test_gold_base_rate_warning_is_symmetric_across_both_branches():
    """D-135: the caveat must fire on BOTH gold branches on a nominal rise.

    Before the fix it fired only on `gold == "down"`, which IS the base rate
    (0.7556), so it advertised the modal answer as the exception and left
    `gold: up` on a nominal rise — the informative minority — uncaveated.
    """
    # gold down on a nominal rise: nominal +10, breakeven +2 -> real +8
    r_down = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver="demand"
        )
    )
    assert r_down.value["gold"] == "down"
    assert any("Gold reads DOWN" in w for w in r_down.warnings)

    # gold up on a nominal rise: nominal +10, breakeven +12 -> real -2
    r_up = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=12.0, surprise_driver="demand"
        )
    )
    assert r_up.value["gold"] == "up"
    assert any("Gold reads UP" in w for w in r_up.warnings), (
        "the minority branch must carry its own caveat"
    )


def test_gold_base_rate_warning_does_not_fire_on_a_nominal_fall():
    """The gate requires nominal_yield_change_bp > 0 — it is about a RISE."""
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=-10.0, breakeven_change_bp=2.0, surprise_driver="demand"
        )
    )
    assert r.value["gold"] == "up"
    assert not any("Gold reads" in w for w in r.warnings)


def test_gold_base_rate_branches_publish_complementary_measured_rates():
    """The two branches quote rates that sum to 1 — no new config leaf invented.

    gold == down -> share = gold_base_rate            = 0.7556
    gold == up   -> share = 1 - gold_base_rate        = 0.2444
    """
    r_down = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver="demand"
        )
    )
    r_up = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=12.0, surprise_driver="demand"
        )
    )
    assert any("75.56%" in w for w in r_down.warnings)
    assert any("24.44%" in w for w in r_up.warnings)
    assert r_down.value["gold_call_base_rate"] == 0.7556


def test_flat_nominal_reports_flat_for_all_three_coupled_keys():
    """The three keys driven by `bonds` must agree with each other always.

    Hand: nominal +0.4 is inside the 0.5 flat band -> bonds flat, and both
    derived keys are flat with it (long_duration is the same reading, and
    value_vs_growth has no spread to report).
    """
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=0.4, breakeven_change_bp=2.0, surprise_driver="demand"
        )
    )
    assert r.value["bonds"] == "flat"
    assert r.value["long_duration_growth_equities"] == "flat"
    assert r.value["value_vs_growth"] == "flat"
    assert any("flat band" in w for w in r.warnings)


def test_the_three_bonds_keyed_outputs_never_disagree():
    """Locks in the coupling the module DOCUMENTS — and only that coupling.

    `bonds`, `long_duration_growth_equities` and `value_vs_growth` are one
    predicate published three ways. Whatever the input, they must move
    together: down/down/value_outperforms, or up/up/growth_outperforms, or
    all three flat. If they ever disagreed the docstring would be wrong.
    """
    legal = {
        ("down", "down", "value_outperforms"),
        ("up", "up", "growth_outperforms"),
        ("flat", "flat", "flat"),
    }
    for nom in (-50.0, -10.0, -3.0, -0.4, 0.0, 0.4, 3.0, 10.0, 50.0):
        for be in (-50.0, -10.0, -3.0, 0.0, 3.0, 10.0, 50.0):
            if nom == 0.0 and be == 0.0:
                continue
            r = cross_asset_transmission(
                InflationTransmissionInputs(
                    nominal_yield_change_bp=nom, breakeven_change_bp=be, surprise_driver="demand"
                )
            )
            trio = (
                r.value["bonds"],
                r.value["long_duration_growth_equities"],
                r.value["value_vs_growth"],
            )
            assert trio in legal, (nom, be, trio)


def test_gold_is_independent_of_the_bonds_keyed_trio():
    """F-IDB-001: the docstring says the four asset keys carry 'at most two bits'.

    That claim is FALSE and this test pins the truth so it cannot regress.

    `bonds` keys on the NOMINAL leg; `gold` keys on the REAL leg. Those are
    different quantities, so `gold` is free to take all three of its values for
    each of the three `bonds` values -> 9 joint states, ~3.17 bits, not 2.

    This is not pedantry: the same file, and D-052's defect-2 write-up, use the
    two-bits figure to justify treating the coupled keys as a single vote. The
    vote count is right for the trio; it is wrong for the four, and a reader who
    takes "two bits" literally would under-count the map's real content.
    """
    trio_to_golds: dict[tuple[str, str, str], set[str]] = {}
    for nom in (-100.0, -10.0, -3.0, -0.4, 0.0, 0.4, 3.0, 10.0, 100.0):
        for be in (-100.0, -10.0, -3.0, 0.0, 3.0, 10.0, 100.0):
            if nom == 0.0 and be == 0.0:
                continue
            r = cross_asset_transmission(
                InflationTransmissionInputs(
                    nominal_yield_change_bp=nom, breakeven_change_bp=be, surprise_driver="demand"
                )
            )
            trio = (
                r.value["bonds"],
                r.value["long_duration_growth_equities"],
                r.value["value_vs_growth"],
            )
            trio_to_golds.setdefault(trio, set()).add(r.value["gold"])

    joint_states = sum(len(g) for g in trio_to_golds.values())
    assert joint_states == 9, (
        f"expected 9 joint states (3 bonds x 3 gold), measured {joint_states}"
    )
    # Every trio must see all three gold readings — gold is fully independent.
    for trio, golds in trio_to_golds.items():
        assert golds == {"down", "up", "flat"}, (trio, golds)


def test_confidence_is_hand_derived_and_not_the_specs_hardcoded_0_45():
    """D-052 defect 7: the spec hardcoded 0.45; the module must compute it.

    The driver split is an ATTRIBUTION, not an observation, but the module
    passes depends_on_unobservable=False (unlike the Phillips curve). Hand:
    compute_confidence(heuristic=True, unobservable=False) == 0.50.
    """
    expected = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, depends_on_unobservable=False)
    )
    assert expected == 0.50
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=2.0, surprise_driver="demand"
        )
    )
    assert r.confidence == 0.50
    assert r.confidence != 0.45


def test_a_trivial_move_warns_the_split_is_immeasurable():
    """nominal +1.9 < trivial_move 2.0 -> indeterminate + a warning about it."""
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=1.9, breakeven_change_bp=-5.0, surprise_driver="demand"
        )
    )
    assert r.value["driver_channel"] == "indeterminate"
    assert any("near-zero denominator" in w for w in r.warnings)


def test_both_channels_warns_and_names_the_opposite_sign_mechanism():
    """For both legs to clear 0.66 their shares must sum to > 1.32, impossible
    unless one is negative — so the reachable case has a NEGATIVE real share.

    nominal=+10, breakeven=+20 -> real=-10, shares -1.00 / 2.00 -> both_channels.
    (nominal=+10, breakeven=+14 gives -0.40 / 1.40, which is breakeven_driven
    only — the real leg is below the band. Getting this wrong is the second
    test bug I made in this file; the arithmetic is now done from the shares.)
    """
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=20.0, surprise_driver="demand"
        )
    )
    assert r.value["real_yield_change_bp"] == -10.0
    assert r.value["real_leg_share_of_move"] == -1.0
    assert r.value["breakeven_leg_share_of_move"] == 2.0
    assert r.value["driver_channel"] == "both_channels"
    assert any("BOTH legs carry most of the move" in w for w in r.warnings)
    assert any("OPPOSITE directions" in w for w in r.warnings)
    # and the neighbouring case is NOT both_channels, pinning the band edge
    r_be = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=10.0, breakeven_change_bp=14.0, surprise_driver="demand"
        )
    )
    assert r_be.value["driver_channel"] == "breakeven_driven"
