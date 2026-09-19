"""Tests for the cross-market relative-value constructor (Module 15.3, D-062).

AGENTS.md Section 20.12 (the constructor), Section 20.14's golden test, Section
22.3 (US-only scope) and the D-062 decision record.

The defect this file exists to pin
----------------------------------
Section 20.12 computes ``degradation = correlation_normal - correlation_stressed``
and then **defaults ``correlation_stressed`` to the literal 0.9 inside the model
body**. Measured over eight real US cross-market pairs (D-062 probe P2) the
*normal* correlation runs **-0.623 .. 0.820**, so on the specification's own
default the published ``hedge_degradation`` is **negative for 8 of 8 pairs** —
the specification silently asserts, universally, that the hedge *improves* in a
crisis, which is the opposite of the premise its own docstring states.

So the number is not wrong arithmetic; it is a **sign nobody checked**. Three
tests below are the ones that matter:

* ``test_the_specification_default_reports_the_hedge_improving`` — pins the
  defect itself, on the shipped config, so a change that hides it is visible.
* ``test_every_hedge_direction_is_reachable`` — the three-way partition, driven
  as a grid rather than one fixture per state (D-053's lesson 49).
* ``test_the_config_default_route_is_published`` — Section 21.1 assigns the
  field to ``risk.stress_correlation``, and that accessor had **no consumer**
  before this function, which is what made the default's effect invisible.

Expected values are hand-computed in each docstring rather than captured from a
run, per Section 11.1.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ConfidenceInputs, ModelResult, compute_confidence
from macro_engine.models.yield_curve import (
    _HEDGE_DIRECTIONS,
    CorrelationStressedSource,
    CrossMarketRVInputs,
    HedgeDirection,
    construct_cross_market_rv,
)

#: A live-shaped pair: US IG credit against the 10y Treasury, both legs' modified
#: durations taken from the shipped ``bond_math`` over the 80-case grid of
#: D-062 probe P3 (6.7950 .. 9.9750 for a 10y, 4.0555 .. 4.9875 for a 5y).
_LONG_DURATION = 6.8
_SHORT_DURATION = 8.47
_NOTIONAL = 10_000_000.0


def _inputs(**overrides: object) -> CrossMarketRVInputs:
    """A live-shaped cross-market RV pair, overridable per test."""
    params: dict[str, object] = {
        "market_a": "US IG credit",
        "market_b": "US Treasury 10y",
        "duration_a": _LONG_DURATION,
        "duration_b": _SHORT_DURATION,
        "target_notional_a": _NOTIONAL,
        "correlation_normal": 0.42,
    }
    params.update(overrides)
    return CrossMarketRVInputs(**params)  # type: ignore[arg-type]


def _construct(**overrides: object) -> ModelResult:
    return construct_cross_market_rv(_inputs(**overrides))


def _values(result: ModelResult) -> dict[str, object]:
    """Narrow a dict-valued ``ModelResult`` for indexing."""
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    item = _values(result)[key]
    assert isinstance(item, (int, float)), f"{key} is {type(item).__name__}, not numeric"
    return float(item)


def _text(result: ModelResult, key: str) -> str:
    item = _values(result)[key]
    assert isinstance(item, str), f"{key} is {type(item).__name__}, not a string"
    return item


def _flag(result: ModelResult, key: str) -> bool:
    item = _values(result)[key]
    assert isinstance(item, bool), f"{key} is {type(item).__name__}, not a bool"
    return item


# ---------------------------------------------------------------------------
# The arithmetic, hand-computed
# ---------------------------------------------------------------------------


def test_the_notional_is_the_duration_ratio_applied_to_the_long_leg() -> None:
    """Section 20.12: ``N_b = N_a * (D_a / D_b)``.

    Hand calculation: 6.8 / 8.47 = 0.802833530...; times $10,000,000 =
    $8,028,335.30. Rounded to 2dp, which is what the specification publishes.
    """
    result = _construct()
    assert _number(result, "notional_a_long") == _NOTIONAL
    assert _number(result, "notional_b_short") == pytest.approx(8_028_335.30, abs=0.01)
    assert _number(result, "duration_ratio_a_to_b") == pytest.approx(0.802834, abs=1e-6)


def test_the_duration_dollars_balance_by_construction() -> None:
    """The D-009 cross-field identity, recomputed from the published legs.

    ``N_a * D_a == N_b * D_b`` is what "duration-matched" means, and it must be
    recomputable from the output rather than trusted.
    """
    result = _construct()
    a = _number(result, "duration_dollars_a")
    b = _number(result, "duration_dollars_b")
    assert a == pytest.approx(_NOTIONAL * _LONG_DURATION, rel=1e-12)
    assert b == pytest.approx(a, rel=1e-9)


def test_the_residual_is_zero_and_flagged_as_definitional() -> None:
    """The residual is ``N_l``'s own definition, so it cannot be a check.

    D-059 measured this for the curve constructor: the quantity is exactly zero
    for every input, correct or not. This function publishes it **and says so**,
    because a reader arriving from the curve trade will look for it here.
    """
    result = _construct()
    assert _number(result, "net_duration_residual") == 0.0
    assert _flag(result, "net_duration_residual_is_definitional") is True


def test_the_residual_stays_below_the_display_tolerance_across_a_grid() -> None:
    """The residual is DEFINITIONAL, so it is zero up to float noise — and the
    margin is finite, which is the point of measuring rather than asserting.

    12 cases over notionals $1e3..$1e12 and three real duration pairs. The
    residual is exactly 0.0 in 9 of them; the worst is **3.906e-03**, which is
    **39% of the 0.01 display tolerance** — a 2.6x margin, NOT infinite. D-059
    found the same shape for the curve constructor (a 10x margin there); the
    difference is that this contract's longer duration pairs reach the noise
    floor sooner. So the assertion is "below the tolerance", not "exactly zero":
    the stronger claim is the one an earlier draft of this test made, and
    executing the grid is what falsified it.
    """
    tolerance = get_settings().curve_trade.display_tolerance
    worst = 0.0
    for notional in (1e3, 1e6, 1e9, 1e12):
        for dur_a, dur_b in ((0.48, 1.92), (1.92, 29.93), (19.58, 4.57)):
            result = _construct(target_notional_a=notional, duration_a=dur_a, duration_b=dur_b)
            worst = max(worst, abs(_number(result, "net_duration_residual")))
            assert not any("floating-point artefact" in w for w in result.warnings)
    assert worst < tolerance, f"worst residual {worst} reached the display tolerance"
    assert worst > 0.0, "if the noise is gone entirely, this bound has no margin to report"


def test_the_residual_warning_fires_only_at_extreme_notionals() -> None:
    """The branch is reachable, so it is not deletable code (D-031).

    Measured: the smallest trigger in the probe grid is a $1e13 long leg with
    durations 8.47/29.93, where the float noise reaches 0.015625 against a
    0.01 display tolerance. At $1e6 — every ordinary trade — it is exactly zero
    and the warning is absent, which is the absence half.
    """
    loud = _construct(target_notional_a=1e13, duration_a=8.47, duration_b=29.93)
    assert any("residual" in w for w in loud.warnings), (
        "the definitional residual's float noise must be disclosed when it fires"
    )
    quiet = _construct()
    assert not any("residual" in w for w in quiet.warnings)


# ---------------------------------------------------------------------------
# The golden test from Section 20.14
# ---------------------------------------------------------------------------


def test_cross_market_rv_always_warns_correlation() -> None:
    """Section 20.14's golden test: the LTCM warning is UNCONDITIONAL.

    Section 18.2 makes it a requirement on any ``TradeIdea`` built on a
    cross-market RV instrument, so it must survive every input — including the
    "good" one where the hedge degrades as expected.
    """
    for overrides in (
        {},
        {"correlation_normal": 0.42, "correlation_stressed": 0.85},
        {"correlation_normal": -0.62, "correlation_stressed": -0.60},
        {"correlation_normal": 0.42, "correlation_stressed": 0.42},
    ):
        result = _construct(**overrides)
        assert any("MODELING ASSUMPTION" in w for w in result.warnings), overrides
        assert any("LTCM" in w for w in result.warnings), overrides
        assert any("HIGHER leverage" in w for w in result.warnings), overrides


def test_the_scope_warning_is_unconditional() -> None:
    """Section 22.3: the instrument set is US-only, and Section 20.12 labels its
    output ``country="global"`` — the unearned genericity claim Section 22.3
    retracts. The refusal lives in the warning, because the contract has no
    country field to refuse on."""
    result = _construct()
    assert any("SCOPE" in w and "US-only" in w for w in result.warnings)


def test_the_country_is_us_not_global() -> None:
    """``ModelResult.country``'s own description says ``"us" only through
    Phase 4``. Section 20.12 writes ``country="global"``."""
    assert _construct().country == "us"


# ---------------------------------------------------------------------------
# The headline: the sign of the degradation
# ---------------------------------------------------------------------------


def test_the_specification_default_reports_the_hedge_improving() -> None:
    """THE DEFECT, pinned on the shipped config.

    ``correlation_normal`` 0.42 against the configured 0.9 gives
    ``degradation = 0.42 - 0.9 = -0.48``. A negative degradation means the hedge
    reports as *improving* under stress — the opposite of the premise Section
    20.12's own docstring states. This is not a contrived fixture: 0.42 is the
    measured normal correlation of the 10y-nominal/breakeven pair, and **every**
    measured pair produces the same sign on this default.
    """
    result = _construct()
    assert _number(result, "hedge_degradation") == pytest.approx(-0.48)
    assert _text(result, "hedge_direction") == "improves_under_stress"
    assert any("IMPROVING under stress" in w for w in result.warnings)


def test_a_degrading_hedge_is_reported_as_degrading() -> None:
    """The ordinary case, which the specification's default never produces.

    ``0.42 - 0.20 = +0.22``: the hedge works less well in stress, so the
    degradation is positive and the direction label is the other one.
    """
    result = _construct(correlation_normal=0.42, correlation_stressed=0.20)
    assert _number(result, "hedge_degradation") == pytest.approx(0.22)
    assert _text(result, "hedge_direction") == "degrades_under_stress"
    assert not any("IMPROVING under stress" in w for w in result.warnings)


def test_an_unchanged_hedge_is_neither_up_nor_down() -> None:
    """Exact equality is reachable, so ``unchanged`` must be tested FIRST.

    A two-way ``> 0 else "improves"`` would report an unchanged correlation as an
    improvement — D-052's ``_leg_direction`` defect, in the function whose whole
    output is this number. The boundary is binary-exact by construction: the two
    correlations are the same value.
    """
    result = _construct(correlation_normal=0.375, correlation_stressed=0.375)
    assert _number(result, "hedge_degradation") == 0.0
    assert _text(result, "hedge_direction") == "unchanged"


def test_every_hedge_direction_is_reachable() -> None:
    """The quadrant grid, not one fixture per state (D-053's lesson 49).

    All three states, driven from the sign of the difference — including the
    two negative-correlation cells, which the specification's positive default
    makes impossible to reach.
    """
    seen: dict[str, set[str]] = {}
    for normal, stressed in (
        (0.42, 0.20),
        (0.20, 0.42),
        (0.30, 0.30),
        (-0.62, -0.80),
        (-0.62, -0.40),
        (-0.62, -0.62),
    ):
        result = _construct(correlation_normal=normal, correlation_stressed=stressed)
        seen.setdefault(_text(result, "hedge_direction"), set()).add(f"{normal}/{stressed}")
    assert set(seen) == {"degrades_under_stress", "improves_under_stress", "unchanged"}


def test_the_hedge_direction_vocabulary_is_declared_and_agrees_with_the_mirror() -> None:
    """A ``Literal`` is not runtime-enforced, so a value assertion cannot see a
    member that was removed from the type (D-054). Only ``get_args`` can."""
    from typing import get_args

    assert set(get_args(HedgeDirection)) == set(_HEDGE_DIRECTIONS)
    assert set(get_args(HedgeDirection)) == {
        "degrades_under_stress",
        "improves_under_stress",
        "unchanged",
    }


def test_the_stressed_source_vocabulary_is_declared() -> None:
    from typing import get_args

    assert set(get_args(CorrelationStressedSource)) == {
        "caller_supplied",
        "config_default",
    }


# ---------------------------------------------------------------------------
# The route the stressed correlation arrived by
# ---------------------------------------------------------------------------


def test_the_config_default_route_is_published() -> None:
    """Section 21.1 assigns ``correlation_stressed`` to ``risk.stress_correlation``.

    That accessor had no consumer anywhere in the tree before this function
    (D-062 probe P4), so the leaf was a config surface nothing read. The route
    is published because a default and a measurement of *this pair* are
    different claims and the number alone cannot distinguish them.
    """
    result = _construct()
    assert _text(result, "correlation_stressed_source") == "config_default"
    assert _number(result, "correlation_stressed") == get_settings().risk.stress_corr
    assert any("was NOT supplied" in w for w in result.warnings)


def test_a_supplied_stressed_correlation_suppresses_the_default_disclosure() -> None:
    """The absence half: a caller who supplied the pair's own number must not be
    told it was defaulted."""
    result = _construct(correlation_normal=0.42, correlation_stressed=0.55)
    assert _text(result, "correlation_stressed_source") == "caller_supplied"
    assert _number(result, "correlation_stressed") == 0.55
    assert not any("was NOT supplied" in w for w in result.warnings)


def test_the_default_route_reads_the_config_leaf_rather_than_a_literal() -> None:
    """The accessor must be READ, so move the leaf and watch the output follow.

    Section 20.12 writes ``0.9`` as a literal default in the model body. A test
    asserting the shipped value cannot tell a live config read from a hardcoded
    copy of the same number (D-050), so the leaf is perturbed to a value no
    literal could produce.
    """
    settings = get_settings()
    leaf = settings.risk.stress_correlation
    original = leaf.value
    object.__setattr__(leaf, "value", 0.1234)
    try:
        result = _construct()
        assert _number(result, "correlation_stressed") == pytest.approx(0.1234)
        assert _number(result, "hedge_degradation") == pytest.approx(0.42 - 0.1234, abs=1e-3)
        assert _text(result, "hedge_direction") == "degrades_under_stress"
    finally:
        object.__setattr__(leaf, "value", original)


# ---------------------------------------------------------------------------
# The plausibility bound on the degradation
# ---------------------------------------------------------------------------


def test_a_degradation_beyond_the_measured_range_is_disclosed() -> None:
    """The specification's default reaches -1.52 for a negatively-correlated
    pair; the measured range over eight real pairs is 0.004 .. 0.175 on the
    S&P tail and 0.072 .. 0.320 on the VIX tail.

    Hand calculation: ``-0.62 - 0.9 = -1.52``. Note the magnitude exceeds 1.0 —
    the difference of two unit-interval correlations is bounded by 2, so this is
    arithmetically legal and economically meaningless, which is exactly why the
    bound exists.
    """
    result = _construct(correlation_normal=-0.62)
    assert _number(result, "hedge_degradation") == pytest.approx(-1.52, abs=1e-3)
    assert _flag(result, "hedge_degradation_exceeds_plausible_bound") is True
    assert any("plausibility bound" in w for w in result.warnings)


def test_a_degradation_inside_the_measured_range_is_not_disclosed() -> None:
    """Absence half. 0.175 is the worst measured pair, inside the 0.5 bound."""
    result = _construct(correlation_normal=0.42, correlation_stressed=0.245)
    assert _flag(result, "hedge_degradation_exceeds_plausible_bound") is False
    assert not any("plausibility bound" in w for w in result.warnings)


def test_the_bound_is_exclusive_at_the_boundary() -> None:
    """The comparison is ``>``, and the fixture sits EXACTLY on the bound.

    ``0.92 - 0.42 == 0.5`` is binary-exact by construction (both operands are
    binary-exact decimals), so this fixture can distinguish ``>`` from ``>=`` —
    which is the failure D-055 shipped. Assert the exactness rather than
    assuming it.
    """
    assert 0.92 - 0.42 == 0.5, "the fixture must be binary-exact to sit on the bound"
    at_bound = _construct(correlation_normal=0.42, correlation_stressed=0.92)
    assert _flag(at_bound, "hedge_degradation_exceeds_plausible_bound") is False
    over = _construct(correlation_normal=0.42, correlation_stressed=0.97)
    assert _flag(over, "hedge_degradation_exceeds_plausible_bound") is True


def test_the_bound_accessor_reads_the_config_leaf() -> None:
    """Perturbed, so a hardcoded literal cannot pass."""
    settings = get_settings()
    leaf = settings.cross_market_rv.max_abs_hedge_degradation
    original = leaf.value
    object.__setattr__(leaf, "value", 0.01)
    try:
        result = _construct(correlation_normal=0.42, correlation_stressed=0.20)
        assert _flag(result, "hedge_degradation_exceeds_plausible_bound") is True
    finally:
        object.__setattr__(leaf, "value", original)


# ---------------------------------------------------------------------------
# The input contract Section 20.12 does not have
# ---------------------------------------------------------------------------


def test_the_input_contract_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CrossMarketRVInputs(
            market_a="a",
            market_b="b",
            duration_a=1.0,
            duration_b=1.0,
            target_notional_a=1.0,
            correlation_normal=0.0,
            typo_field=1.0,  # type: ignore[call-arg]
        )


def test_the_same_market_on_both_legs_is_refused() -> None:
    """A relative-value trade needs two different markets.

    Section 20.12 accepts any ``str`` and never compares them, so it would price
    a notional for a position that is long and short the same thing.
    """
    with pytest.raises(ValidationError, match="the same market"):
        _inputs(market_b="US IG credit")


def test_the_same_market_is_refused_across_case_and_whitespace() -> None:
    """``"US IG credit"`` and ``"us ig credit "`` are one market."""
    with pytest.raises(ValidationError, match="the same market"):
        _inputs(market_b="  us ig credit ")


def test_an_empty_market_label_is_refused() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        _inputs(market_b="   ")


@pytest.mark.parametrize("field", ["duration_a", "duration_b"])
def test_a_duration_below_the_measured_floor_is_refused(field: str) -> None:
    """The measured floor over 80 real Treasury configurations is 0.4810y."""
    with pytest.raises(ValidationError, match="outside the plausible band"):
        _inputs(**{field: 0.01})


@pytest.mark.parametrize("field", ["duration_a", "duration_b"])
def test_a_duration_above_the_measured_ceiling_is_refused(field: str) -> None:
    """A modified duration cannot exceed the instrument's maturity; the measured
    maximum is 29.9250y for a 30y zero-coupon."""
    with pytest.raises(ValidationError, match="outside the plausible band"):
        _inputs(**{field: 45.0})


@pytest.mark.parametrize("field", ["duration_a", "duration_b"])
def test_a_duration_exactly_on_each_band_edge_is_accepted(field: str) -> None:
    """Both edges are INCLUSIVE, so a fixture sitting exactly on each must pass.

    Without this, a ``<=`` changed to ``<`` would silently start refusing real
    instruments at the boundary and no test would notice.
    """
    settings = get_settings().cross_market_rv
    at_floor = _inputs(**{field: settings.minimum_duration})
    assert getattr(at_floor, field) == settings.minimum_duration
    at_ceiling = _inputs(**{field: settings.maximum_duration})
    assert getattr(at_ceiling, field) == settings.maximum_duration


@pytest.mark.parametrize("field", ["duration_a", "duration_b"])
def test_a_zero_duration_is_refused_by_the_field_bound(field: str) -> None:
    """Section 20.12 has no bound at all, so ``duration_b = 0`` divides by zero."""
    with pytest.raises(ValidationError):
        _inputs(**{field: 0.0})


@pytest.mark.parametrize("field", ["correlation_normal", "correlation_stressed"])
def test_a_correlation_outside_the_unit_interval_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        _inputs(**{field: 1.4})


def test_a_negative_correlation_is_legal() -> None:
    """Three of the eight measured pairs have a negative normal correlation, so
    refusing the sign would refuse real cross-market trades."""
    result = _construct(correlation_normal=-0.62, correlation_stressed=-0.60)
    assert _number(result, "correlation_normal") == pytest.approx(-0.62)
    assert _text(result, "hedge_direction") == "improves_under_stress"


def test_a_non_positive_notional_is_refused() -> None:
    with pytest.raises(ValidationError):
        _inputs(target_notional_a=0.0)


# ---------------------------------------------------------------------------
# The unit attestation
# ---------------------------------------------------------------------------


def test_omitting_the_modified_duration_attestation_is_disclosed() -> None:
    """A Macaulay-vs-modified mismatch is a relative error between the legs, and
    the absolute band cannot see it at short maturities."""
    result = _construct(duration_is_modified=False)
    assert any("not attested as MODIFIED" in w for w in result.warnings)


def test_the_default_attestation_produces_no_warning() -> None:
    """The field DEFAULTS to ``True``, so the helper must omit it — passing it
    explicitly would override the default the mutation changes."""
    result = _construct()
    assert not any("not attested as MODIFIED" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Published keys, inputs_used, confidence, and the prose
# ---------------------------------------------------------------------------


def test_every_published_key_is_present() -> None:
    """Assert the key SET first — a test that iterates a published dict is
    vacuous when the dict is empty (D-038)."""
    assert set(_values(_construct())) == {
        "market_a_long",
        "market_b_short",
        "notional_a_long",
        "notional_b_short",
        "duration_a_years",
        "duration_b_years",
        "duration_ratio_a_to_b",
        "duration_dollars_a",
        "duration_dollars_b",
        "net_duration_residual",
        "net_duration_residual_is_definitional",
        "correlation_normal",
        "correlation_stressed",
        "correlation_stressed_source",
        "hedge_degradation",
        "hedge_direction",
        "hedge_degradation_exceeds_plausible_bound",
    }


def test_inputs_used_lists_every_field_the_function_consumes() -> None:
    """Section 20.12 lists four of its seven fields, omitting
    ``correlation_stressed`` — which the published value contains — and both
    market labels, which the interpretation names."""
    assert set(_construct().inputs_used) == {
        "market_a",
        "market_b",
        "duration_a",
        "duration_b",
        "target_notional_a",
        "correlation_normal",
        "correlation_stressed",
        "duration_is_modified",
    }


def test_confidence_is_computed_not_asserted() -> None:
    """Section 22.8. Assert the DISCRIMINATING property rather than the literal:
    the specification hardcodes 0.5, and the computed value must differ from it
    (0.7 with the shipped config)."""
    result = _construct()
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=False,
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)
    assert result.confidence != 0.5, (
        "Section 20.12 hardcodes confidence=0.5; the computed value must differ"
    )


def test_confidence_follows_a_perturbed_calibration_status() -> None:
    """The penalty must be reachable: move the leaf's status to an illustrative
    placeholder and the computed confidence must fall."""
    settings = get_settings()
    leaf = settings.cross_market_rv.minimum_duration_years
    original = leaf.calibration_status
    object.__setattr__(leaf, "calibration_status", "uncalibrated_illustrative")
    try:
        penalised = _construct()
    finally:
        object.__setattr__(leaf, "calibration_status", original)
    assert penalised.confidence < _construct().confidence


def test_the_published_labels_are_the_inputs() -> None:
    """The legs must be named in the output exactly as the caller named them.

    A mutation that publishes ``market_b`` under ``market_a_long`` survived the
    first sweep: the key-SET test cannot see it, and the interpretation test
    reads a different string. The two fixture labels are distinct, so the
    assertion discriminates.
    """
    result = _construct()
    assert _text(result, "market_a_long") == "US IG credit"
    assert _text(result, "market_b_short") == "US Treasury 10y"
    assert _text(result, "market_a_long") != _text(result, "market_b_short")


def test_the_published_legs_follow_overridden_labels() -> None:
    """Symmetry-breaking: a literal cannot satisfy both calls."""
    result = _construct(market_a="Bund 10y", market_b="US 30y")
    assert _text(result, "market_a_long") == "Bund 10y"
    assert _text(result, "market_b_short") == "US 30y"


def test_the_interpretation_names_both_markets() -> None:
    result = _construct()
    assert "US IG credit" in result.interpretation
    assert "US Treasury 10y" in result.interpretation


def test_the_context_states_the_duration_convention() -> None:
    """The function's premise is that the common factor cancels, and the
    convention it uses cancels only when the legs price alike (O-57/O-59)."""
    context = _construct().context
    assert "N*D" in context
    assert "N*P*D" in context


# ---------------------------------------------------------------------------
# Warning coverage — a PARTITION, not a hit
# ---------------------------------------------------------------------------

#: One mutually non-colliding marker per conditional warning branch. A branch
#: whose marker is a substring of another's leaves the guard green while the
#: branch is gone (D-052's M10.3).
_CONDITIONAL_MARKERS: dict[str, str] = {
    "hedge_improves": "IMPROVING under stress",
    "config_default_route": "was NOT supplied",
    "degradation_bound": "plausibility bound",
    "not_attested_modified": "not attested as MODIFIED",
    "definitional_residual": "floating-point artefact",
}


def test_every_conditional_warning_branch_is_reachable() -> None:
    """A warning branch with no test is deletable, so drive each one.

    Five conditional branches, five fixtures, each asserted to reach exactly one
    marker — the partition form of a coverage guard.
    """
    reached: dict[str, int] = dict.fromkeys(_CONDITIONAL_MARKERS, 0)
    fixtures = [
        _construct(),  # config default -> improves + default route
        _construct(correlation_normal=-0.62),  # beyond the bound
        _construct(duration_is_modified=False),
        _construct(target_notional_a=1e13, duration_a=8.47, duration_b=29.93),
        _construct(correlation_normal=0.42, correlation_stressed=0.20),
    ]
    for result in fixtures:
        for warning in result.warnings:
            hits = [k for k, marker in _CONDITIONAL_MARKERS.items() if marker in warning]
            assert len(hits) <= 1, f"warning matches two markers: {warning}"
            for hit in hits:
                reached[hit] += 1
    assert all(count > 0 for count in reached.values()), reached


def test_a_warning_matches_exactly_one_marker() -> None:
    """The partition assertion itself, so a future collision fails loudly."""
    for result in (
        _construct(),
        _construct(correlation_normal=-0.62),
        _construct(duration_is_modified=False),
    ):
        for warning in result.warnings:
            hits = [k for k, marker in _CONDITIONAL_MARKERS.items() if marker in warning]
            assert len(hits) <= 1


def test_the_unconditional_warnings_are_exactly_three() -> None:
    """A fully clean call publishes the three Section 20.12/22.3 mandates and
    nothing else. A warning that always fires tells a reader nothing about the
    trade, which is why the conditional branches above have to exist."""
    result = _construct(correlation_normal=0.42, correlation_stressed=0.20)
    assert len(result.warnings) == 3
    assert not any(
        any(marker in w for marker in _CONDITIONAL_MARKERS.values()) for w in result.warnings
    )
