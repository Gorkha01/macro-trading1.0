"""Hand-verified tests for the duration-weighted curve-trade constructor.

AGENTS.md Section 15.1b (the constructor), Section 21.2 Steps 4-5, and the
D-059 decision record.

The defect this file exists to pin
----------------------------------
Section 15.1b publishes ``net_duration_residual`` with a warning that fires
when ``abs(residual) >= 0.01``, described as "check duration inputs". That
residual is **tautologically zero** — it is ``notional_long``'s definition
algebraically simplified — so no duration input, however wrong, can make it
fire. Two tests here pin that fact directly:

* ``test_the_residual_is_zero_for_a_duration_wrong_by_ten_times`` — the
  strongest available falsification, and it cannot fail by design.
* ``test_the_real_check_is_the_duration_to_tenor_band`` — the replacement.

Expected values are hand-computed in each docstring rather than captured from
a run, per Section 11.1.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.yield_curve import (
    CurveTradeConstructor,
    _tenor_years,
    construct_duration_weighted_curve_trade,
)


def _construct(**overrides: object) -> ModelResult:
    """A live-shaped 2y/10y steepener, overridable per test.

    Durations are MODIFIED, in YEARS: 1.842 for a 2y note and 9.402 for a 10y,
    both consistent with par bonds at the coupons in the 2026 curve.
    """
    params: dict[str, object] = {
        "short_tenor": "2y",
        "long_tenor": "10y",
        "short_duration": 1.842,
        "long_duration": 9.402,
        "target_notional_short": 10_000_000.0,
    }
    params.update(overrides)
    return construct_duration_weighted_curve_trade(CurveTradeConstructor(**params))  # type: ignore[arg-type]


def _values_of(result: ModelResult) -> dict[str, object]:
    """Narrow a dict-valued ``ModelResult`` for indexing.

    ``ModelResult.value`` is a union, so indexing it directly needs a cast or an
    ``isinstance`` check at every call site. This is the same trick the live
    check uses; asserting here means a shape error fails loudly rather than
    being read as a missing key.
    """
    value = result.value
    assert isinstance(value, dict)
    return value


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def test_notional_is_the_duration_weighted_formula() -> None:
    """N_long = N_short * (D_short / D_long) = 1e7 * (1.842 / 9.402).

    1.842 / 9.402 = 0.1959157626...
    1e7 * 0.1959157626 = 1_959_157.626...
    Rounded to 2dp: 1_959_157.63
    """
    value = _construct().value
    assert isinstance(value, dict)
    assert value["notional_short"] == 10_000_000.0
    assert value["notional_long"] == 1_959_157.63


def test_equal_notional_would_be_wrong_by_a_factor_of_the_duration_ratio() -> None:
    """The whole point of the function: the legs are NOT equal.

    Equal-notional would put 1e7 on the long leg, which is
    1e7 / 1_959_157.63 = 5.1042x too much. Stated as an assertion on the
    ratio so a regression to equal-notional fails loudly.
    """
    value = _construct().value
    assert isinstance(value, dict)
    # Published rounded to 6dp for presentation: 0.1959157626... -> 0.195916.
    assert value["notional_long_to_short_ratio"] == 0.195916
    assert value["notional_long_to_short_ratio"] < 1.0


def test_duration_dollars_balance() -> None:
    """N_short * D_short == N_long * D_long, to the rounding of the notional.

    1e7 * 1.842 = 18_420_000
    1_959_157.63 * 9.402 = 18_420_000.036... (the 2dp rounding of the notional)
    """
    value = _construct().value
    assert isinstance(value, dict)
    assert value["duration_dollars_short"] == 18_420_000.0
    assert value["duration_dollars_long"] == pytest.approx(18_420_000.0, abs=0.05)


def test_the_long_leg_is_the_smaller_notional_on_a_2s10s() -> None:
    """A duration-weighted steepener short the 2y needs FEWER long dollars.

    D_short < D_long, so N_long = N_short * (D_s / D_l) < N_short. This is the
    single most counter-intuitive output of the function and the one a reader
    is most likely to misread, so it is asserted explicitly.
    """
    value = _construct().value
    assert isinstance(value, dict)
    assert value["notional_long"] < value["notional_short"]


# ---------------------------------------------------------------------------
# The tautology -- the specification's dead guard, pinned
# ---------------------------------------------------------------------------


def test_the_residual_is_definitionally_zero_on_a_correct_trade() -> None:
    """The residual is0.0 because the notional is unrounded, not because the
    durations are right. See the next test for the proof that it cannot be
    wrong."""
    value = _construct().value
    assert isinstance(value, dict)
    assert value["net_duration_residual"] == 0.0
    assert value["net_duration_residual_is_definitional"] is True


def test_the_residual_is_zero_for_a_duration_wrong_by_ten_times() -> None:
    """THE FINDING (D-059 probe P14), pinned as a live fact.

    Substituting a short duration of 18.42 — ten times a real 2y note's
    modified duration, which the contract's band REFUSES before arithmetic
    (see the band tests) — the residual formula still yields exactly zero:

        residual = (N_s * D_s) - (N_l * D_l),  N_l := N_s * (D_s / D_l)
                 = N_s*D_s - N_s*(D_s/D_l)*D_l = 0

    So the function's own warning ("check duration inputs") cannot detect the
    one input error it names. The substitution is done by calling the formula
    directly rather than through the contract, precisely because the contract
    now refuses the input — the point is that the RESIDUAL never would.
    """
    n_short, d_short, d_long = 10_000_000.0, 18.42, 9.402
    n_long = n_short * (d_short / d_long)
    residual = (n_short * d_short) - (n_long * d_long)
    assert residual == 0.0

    # And the specification's warning threshold cannot fire on it either.
    assert not (abs(residual) >= 0.01)


def test_the_residual_moves_only_from_the_notional_rounding() -> None:
    """The single source of a nonzero residual is the 2dp presentational round.

    At D_s=1.842, D_l=9.402, N=1e7: raw N_long = 1_959_157.6260... which
    rounds to 1_959_157.63. Recomputing the residual against the ROUNDED value
    gives 1e7*1.842 - 1_959_157.63*9.402 = -0.0372599959... — a rounding
    artefact, not an input error. This is asserted so the two are never
    conflated.
    """
    n_short, d_short, d_long = 10_000_000.0, 1.842, 9.402
    n_long_rounded = 1_959_157.63
    residual_from_rounding = (n_short * d_short) - (n_long_rounded * d_long)
    assert residual_from_rounding == pytest.approx(-0.03726, abs=1e-5)

    # The shipped function reports the UNROUNDED residual, which is exactly 0.
    value = _construct().value
    assert isinstance(value, dict)
    assert value["net_duration_residual"] == 0.0


# ---------------------------------------------------------------------------
# The real check -- the duration/tenor band
# ---------------------------------------------------------------------------


def test_the_real_check_is_the_duration_to_tenor_band() -> None:
    """A duration inconsistent with its named tenor is REFUSED.

    18.42 years of modified duration on a 2y note gives a ratio of 9.21,
    far outside the configured band [0.15, 1.05]. The message names the unit
    trap explicitly, because the likeliest cause is periods-vs-years.
    """
    with pytest.raises(ValueError, match=r"implausible for '2y'"):
        _construct(short_duration=18.42)


def test_a_duration_exceeding_its_own_maturity_is_refused() -> None:
    """No instrument can have a modified duration longer than its maturity.

    A 2y note with 2.2 years of duration is impossible: ratio 1.10, strictly
    above the 1.05 ceiling. The fixture must land OFF the boundary — 2.1 gives
    ratio 1.05 exactly, which the inclusive band ADMITS, and asserting a
    refusal there would be asserting the wrong thing (lessons 5y/63).
    """
    with pytest.raises(ValueError, match="implausible"):
        _construct(short_duration=2.2)


def test_the_ceiling_itself_is_inclusive() -> None:
    """The band's endpoints are admitted, and 1.05 exactly is the boundary.

    Pinned so the inclusive/exclusive choice is a decision rather than an
    artefact: a future change to `<=` vs `<` in the guard has to change this
    test, and the test states which way it currently reads.
    """
    value = _construct(short_duration=2.1).value
    assert isinstance(value, dict)
    assert value["short_duration_years"] == 2.1


def test_the_zero_coupon_limit_is_admitted() -> None:
    """ModDur == tenor is the zero-coupon ceiling and IS a real instrument."""
    value = _construct(short_duration=2.0, long_duration=10.0).value
    assert isinstance(value, dict)
    assert value["notional_long"] == 2_000_000.0


def test_a_long_tenor_with_a_low_coupon_is_admitted() -> None:
    """The band's floor exists to admit 30y near-zero-coupon issues.

    A 30y with 5.5 years of duration gives ratio 0.1833, above the 0.15 floor.
    This is the regression guard for the first draft's 0.5 floor, which would
    have rejected every 20y and 30y UST (D-059 probe P16).
    """
    value = _construct(long_tenor="30y", long_duration=5.5).value
    assert isinstance(value, dict)
    assert value["long_tenor"] == "30y"


def test_the_band_bounds_come_from_config_and_are_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Move the config leaf, so a hardcoded literal produces a different answer.

    At the shipped floor of 0.15 a 2y note with 0.20 years of duration is
    admitted (ratio 0.10... no, 0.10 < 0.15, so REFUSED). To make the test
    discriminating the floor is moved to 0.05, which admits it. A hardcoded
    0.15 would still refuse and the test would fail.
    """
    settings = get_settings()
    monkeypatch.setattr(settings.curve_trade.duration_to_tenor_min, "value", 0.05, raising=False)

    # floor 0.05 -> ratio 0.10 for a 2y note with 0.20y duration -> admitted.
    value = _construct(short_duration=0.2).value
    assert isinstance(value, dict)
    assert value["short_duration_years"] == 0.2

    # And with the shipped floor restored, the same input is refused.
    monkeypatch.setattr(settings.curve_trade.duration_to_tenor_min, "value", 0.15, raising=False)
    with pytest.raises(ValueError, match="implausible"):
        _construct(short_duration=0.2)


def test_the_ceiling_comes_from_config_and_is_not_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The multiplier is chosen so the shipped ceiling REFUSES this input.

    A 2y note with 2.5 years of duration has ratio 1.25. Under the shipped
    ceiling of 1.05 that is refused; under a raised ceiling of 1.30 it is
    admitted. A hardcoded 1.05 would refuse under both and fail the second
    assertion -- which is what makes this discriminating.

    (0.95 was tried first and is a WEAK fixture: it lies between the two
    ceilings but the shipped one refuses it too, so the mutation could not be
    observed. Lesson 63/71.)
    """
    from macro_engine.models import yield_curve  # noqa: F401  (import kept for symmetry)

    settings = get_settings()
    monkeypatch.setattr(settings.curve_trade.duration_to_tenor_max, "value", 1.30, raising=False)
    value = _construct(short_duration=2.5).value
    assert isinstance(value, dict)
    assert value["short_duration_years"] == 2.5

    monkeypatch.setattr(settings.curve_trade.duration_to_tenor_max, "value", 1.05, raising=False)
    with pytest.raises(ValueError, match="implausible"):
        _construct(short_duration=2.5)


# ---------------------------------------------------------------------------
# Leg distinctness and ordering
# ---------------------------------------------------------------------------


def test_the_same_tenor_on_both_legs_is_refused() -> None:
    """A 'curve trade' whose legs coincide measures no slope."""
    with pytest.raises(ValueError, match="strictly inside"):
        _construct(short_tenor="10y", long_tenor="10y", short_duration=9.4, long_duration=9.4)


def test_inverted_legs_are_refused() -> None:
    """A 'short' leg longer than the 'long' leg inverts the sign's meaning.

    Named by its own message so the ordering guard and the gap guard are not
    confused with one another (lesson 68).
    """
    with pytest.raises(ValueError, match=r"'10y' \(10.0y\) must be strictly inside"):
        _construct(short_tenor="10y", long_tenor="2y", short_duration=9.4, long_duration=1.8)


def test_legs_one_day_apart_are_admitted() -> None:
    """The ordering guard is strict inequality, not a minimum gap.

    A gap of 0.004 years (about 1.5 days) passes -- the guard is about ORDER,
    not about economic meaningfulness. Asserted so a future tightening of this
    rule has to change a test rather than slip in.
    """
    value = _construct(short_tenor="2y", long_tenor="2.004y", long_duration=1.9).value
    assert isinstance(value, dict)
    assert value["long_tenor"] == "2.004y"


def test_the_long_leg_is_band_checked_too() -> None:
    """Both legs are checked, and the failure names the LONG one.

    The sweep's `M4.5` restricted the check to the short leg and survived --
    every band failure test used a bad SHORT duration, so the long leg's check
    was never exercised. A unit error is equally likely on either leg.

    A 10y with 94.02 years of duration gives ratio 9.402, far outside the band.
    """
    with pytest.raises(ValueError, match=r"long_duration .* implausible for '10y'"):
        _construct(long_duration=94.02)


def test_the_long_leg_can_fail_alone() -> None:
    """The failure is attributable: a bad long leg with a GOOD short leg still
    raises, so the check is not accidentally satisfied by the short leg."""
    with pytest.raises(ValueError, match="long_duration"):
        _construct(long_duration=94.02)
    # And the mirror: a good long leg with a bad short leg must name the short.
    with pytest.raises(ValueError, match="short_duration"):
        _construct(short_duration=18.42)


def test_the_band_loop_reaches_the_long_leg_after_the_short_passes() -> None:
    """A bad LONG leg is refused even when the SHORT leg is valid.

    This test previously asserted ``implausible for '2y'`` and compared it
    against a failure that names the long leg -- so it failed on *unmutated*
    source, and the D-059 sweep reported a false 31/31 because the honesty
    control died alongside it (the D-051 trap). The fixture is now stated
    explicitly and the expectation matches the leg the message actually names.

    A ``3y`` long leg carrying 0.4 years of duration gives ratio 0.1333, below
    the 0.15 floor, while the ``2y``/1.9 short leg is comfortably inside the
    band -- so the loop must reach the second iteration to fail.
    """
    with pytest.raises(ValueError, match=r"long_duration 0\.4 is implausible for '3y'"):
        _construct(short_tenor="2y", long_tenor="3y", long_duration=0.4, short_duration=1.9)


def test_a_bad_short_leg_fails_before_the_long_leg_is_considered() -> None:
    """When BOTH legs are bad, the message names the short one.

    Pins the loop's ORDER, which is what makes a failure attributable: with two
    invalid legs the first one is reported, so the caller is not sent to the
    wrong input.

    Note the fixture is chosen carefully. ``short_duration=0.24`` against ``2y``
    gives ratio 0.12, below the 0.15 floor, so the SHORT leg is genuinely
    invalid; ``long_duration=0.4`` against ``3y`` gives 0.1333, also invalid.
    An earlier draft used ``short_duration=0.4`` (ratio 0.2000, INSIDE the band)
    and the test failed because the short leg was in fact valid — the claim was
    about ordering and the fixture did not create the condition being ordered.
    """
    with pytest.raises(ValueError, match=r"short_duration 0\.24 is implausible for '2y'"):
        _construct(short_tenor="2y", long_tenor="3y", short_duration=0.24, long_duration=0.4)


# ---------------------------------------------------------------------------
# Tenor parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [("2y", 2.0), ("10y", 10.0), ("30y", 30.0), ("2.5y", 2.5), ("0.5y", 0.5)],
)
def test_year_tenors_parse(label: str, expected: float) -> None:
    assert _tenor_years(label) == expected


@pytest.mark.parametrize("label", ["2yr", "6m", "", "y", "2w", "abc"])
def test_non_year_tenors_are_refused(label: str) -> None:
    """The parser refuses rather than guesses.

    ``"2yr"`` is the spelling ``CurveSlopeInputs`` uses, and it is refused
    here deliberately: this contract reads the years for an arithmetic check,
    and a silent normalisation of a *different unit suffix* would hide a unit
    mismatch. Anything without the ``y`` suffix, or without a number, is
    refused.
    """
    with pytest.raises(ValueError, match="not a year tenor"):
        _tenor_years(label)


@pytest.mark.parametrize("label", ["2Y", " 2y ", "10Y"])
def test_case_and_whitespace_are_normalised(label: str) -> None:
    """Case IS folded, deliberately, unlike the suffix.

    Folding case cannot change the implied unit -- ``"2Y"`` and ``"2y"`` mean
    the same thing to any reader, so accepting both removes a gratuitous
    failure with no risk of a wrong answer. Refusing a *suffix* is different:
    ``"2yr"`` might be a different convention's spelling and normalising it
    would hide that. The distinction is asserted so the two rules cannot be
    collapsed into one by a later edit.
    """
    assert _tenor_years(label) == float(label.strip().lower()[:-1])


@pytest.mark.parametrize("label", ["0y", "-2y"])
def test_non_positive_tenors_are_refused(label: str) -> None:
    with pytest.raises(ValueError, match="not a positive number of years"):
        _tenor_years(label)


# ---------------------------------------------------------------------------
# The unit attestation
# ---------------------------------------------------------------------------


def test_a_macaulay_attestation_produces_a_warning() -> None:
    """Failure to attest MODIFIED gives a warning, not an error.

    The Macaulay-vs-Modified gap is ~1-2%, invisible arithmetically, so the
    only honest handling is to make the caller state it and warn otherwise.
    """
    result = _construct(duration_is_modified=False)
    assert any("MODIFIED" in w for w in result.warnings)


def test_no_warning_when_the_attestation_is_given() -> None:
    """The default attests MODIFIED, so the live-shaped trade warns of nothing
    about units."""
    result = _construct()
    assert not any("MODIFIED" in w for w in result.warnings)


def test_the_warning_states_the_magnitude_of_the_gap() -> None:
    """A warning that does not say how big the error is cannot be acted on."""
    result = _construct(duration_is_modified=False)
    unit_warnings = [w for w in result.warnings if "MODIFIED" in w]
    assert len(unit_warnings) == 1
    assert "1-2%" in unit_warnings[0]


# ---------------------------------------------------------------------------
# The lopsided-notional warning
# ---------------------------------------------------------------------------


def test_an_inverted_duration_structure_warns_but_is_not_refused() -> None:
    """If D_short > D_long the long leg is the BIGGER notional.

    That is unusual enough to warn about, but it is not impossible (an
    inverted curve, or a curve trade expressed with an unusual pair), so it
    must NOT be refused. The distinction is the point: the contract refuses
    impossible inputs and warns about merely surprising ones.
    """
    result = _construct(long_tenor="3y", long_duration=1.5)
    assert any("LARGER" in w for w in result.warnings)


def test_a_normal_trade_does_not_warn_about_leg_size() -> None:
    result = _construct()
    assert not any("LARGER" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# The result contract
# ---------------------------------------------------------------------------


def test_the_result_is_a_model_result_with_computed_confidence() -> None:
    result = _construct()
    assert isinstance(result, ModelResult)
    stamp = get_settings().confidence
    assert 0.0 < result.confidence <= 1.0
    assert stamp is not None


def test_confidence_is_not_hardcoded_at_the_specs_0_9() -> None:
    """Section 15.1b writes ``confidence=0.9``. Section 22.8 forbids it.

    The shipped value is compute_confidence's output for this function's
    factor states, which is 0.7 at the shipped penalty -- NOT 0.9.
    """
    assert _construct().confidence != 0.9


def test_every_published_key_is_present() -> None:
    """The value dict is the contract; a missing key is a silent break."""
    value = _construct().value
    assert isinstance(value, dict)
    assert set(value) == {
        "notional_short",
        "notional_long",
        "notional_long_to_short_ratio",
        "duration_dollars_short",
        "duration_dollars_long",
        "net_duration_residual",
        "net_duration_residual_is_definitional",
        "short_tenor",
        "long_tenor",
        "short_duration_years",
        "long_duration_years",
        "direction",
    }


def test_the_direction_reflects_the_input_not_the_leg_order() -> None:
    """`direction` is a stated decision, because the notional formula is
    identical for a steepener and a flattener -- nothing in the arithmetic
    distinguishes them. Asserted in both states so the field cannot silently
    become a constant."""
    assert _values_of(_construct(is_steepener=True))["direction"] == "steepener"
    assert _values_of(_construct(is_steepener=False))["direction"] == "flattener"


def test_the_default_direction_is_a_steepener() -> None:
    """The default must be asserted, not assumed.

    The two tests above pass `is_steepener` EXPLICITLY in both states, so they
    say nothing about the default — the sweep's `M6.3` flipped the default to
    `False` and survived, which is exactly the "test asserted an outcome both
    programs produce" class. This test reads the default through the contract
    and then through the published value.
    """
    defaulted = CurveTradeConstructor(
        short_tenor="2y",
        long_tenor="10y",
        short_duration=1.842,
        long_duration=9.402,
        target_notional_short=10_000_000.0,
    )
    assert defaulted.is_steepener is True
    published = _values_of(construct_duration_weighted_curve_trade(defaulted))
    assert published["direction"] == "steepener"


def test_the_default_attestation_is_modified() -> None:
    """The MODIFIED default is likewise asserted rather than exercised only
    through an explicit argument (the same gap `M6.3` exposed on the direction)."""
    defaulted = CurveTradeConstructor(
        short_tenor="2y",
        long_tenor="10y",
        short_duration=1.842,
        long_duration=9.402,
        target_notional_short=10_000_000.0,
    )
    assert defaulted.duration_is_modified is True


def test_as_of_is_timezone_aware() -> None:
    """Naive datetimes are banned project-wide."""
    assert _construct().as_of.tzinfo is not None


def test_the_inputs_used_list_names_the_real_inputs() -> None:
    assert set(_construct().inputs_used) == {
        "short_tenor",
        "long_tenor",
        "short_duration",
        "long_duration",
        "target_notional_short",
    }
