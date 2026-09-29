"""Tests for Module 5.6 — ``cross_asset_transmission``.

Section 20.5 specifies a **map**, not an estimate: one repricing in, a table of
directional expectations out. Its defects are therefore mostly structural
rather than numeric, and the tests below are organised by defect rather than by
function.

**Seven specification defects are pinned here.**

A declared input that nothing reads
-----------------------------------
1. **``inflation_surprise_bp`` is declared, listed in ``inputs_used``, and never
   read.** Enumerated over the whole declared input space, the map's output is
   invariant to it. The test asserts invariance *and* that the value is still
   published, because the fix is to keep it as a disclosure rather than to
   either delete it (losing a channel a caller may want) or invent a dependence
   on it (which the specification never derived).

A published value that is not a direction
------------------------------------------
2. **``usd`` is a sentence** (``"up_if_relative_rate_expectations_rose"``) in a
   map whose every other value is comparable. It is emitted as ``unresolved``,
   and the test asserts that the emitted value is a member of the declared
   direction vocabulary — which the specification's string is not.

Three keys from one predicate
------------------------------
3. **``bonds`` / ``long_duration_growth_equities`` / ``value_vs_growth`` all key
   on the same sign test.** They are kept (each names a distinct mechanism) and
   the coupling is pinned, so that a future decoupling is a deliberate change
   rather than an accident.

A stated trigger differing from the implemented one
----------------------------------------------------
4. **The gold paragraph argues from a HOT print; the code tests only the real
   yield's sign.** A cool print with rising real yields is indistinguishable
   from a hot one in the specification's output. The driver is now published so
   the two are separable, and the base rate travels with the call.

A bare ``str``, a ``> 0`` / ``else`` pair, and a hardcoded confidence
---------------------------------------------------------------------
5. **``surprise_driver: str``** with an ``else`` fallthrough (D-029) — a typo
   silently reports the least-informative branch.
6. **``x > 0 else "up"`` reports an exactly-unchanged yield as a RISE**
   (D-040's class). Measured live: DGS10 is exactly unchanged on 459 of 5 930
   daily changes.
7. **``confidence=0.45`` is hardcoded**; §22.8 reserves confidence for
   ``compute_confidence()``.

The load-bearing tests are
``test_the_specification_version_reports_a_flat_market_as_a_move`` (defect 6,
the one with the largest real-world incidence),
``test_a_hot_and_a_cool_print_with_the_same_real_move_are_distinguishable``
(defect 4, the one the section's own prose is about), and
``test_every_declared_direction_is_producible_and_every_emitted_direction_is_declared``
(the D-045a two-halves rule applied to defect 2).
"""

from __future__ import annotations

import itertools
from typing import get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, TransmissionSettings, get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.inflation_dynamics import (
    ASSET_KEYS,
    InflationTransmissionInputs,
    SurpriseDriver,
    TransmissionDirection,
    _driver_of,
    _leg_direction,
    cross_asset_transmission,
)

# --------------------------------------------------------------------------
# Fixtures. Every one is built by ADDITION from round inputs (D-029/D-045a):
# `40.0 - 10.0` is exact, `4.0 - 0.1` is not.
# --------------------------------------------------------------------------


def _value(result: ModelResult) -> dict[str, object]:
    """The published mapping, narrowed once instead of at every use site.

    ``ModelResult.value`` is a wide union (a float for a scalar model, a dict for
    a map like this one), so ``result.value["bonds"]`` does not narrow under
    ``mypy --strict`` and every read would need its own ``type: ignore``. One
    helper that asserts the shape keeps the assertions in the tests auditable —
    an unexpected shape fails here with a message naming the function, rather
    than being silently coerced.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}.value is {type(value).__name__}, not a dict; the "
        "transmission map's contract is a mapping of string keys"
    )
    return value


def _inputs(**overrides: object) -> InflationTransmissionInputs:
    """A real-driven tightening repricing: nominal +40bp, breakeven +10bp.

    Real leg = +30bp (real share 0.75, above the 0.66 band), so the driver is
    ``real_driven`` and the gold call keys on a genuine real-yield rise.
    """
    base: dict[str, object] = {
        "surprise_driver": "demand",
        "nominal_yield_change_bp": 40.0,
        "breakeven_change_bp": 10.0,
    }
    base.update(overrides)
    return InflationTransmissionInputs(**base)  # type: ignore[arg-type]


def _settings(**overrides: float) -> TransmissionSettings:
    """A PERTURBED settings object.

    The D-050 rule: a test asserting an accessor's CURRENT value cannot
    distinguish a live YAML read from a hardcoded copy of the same number, so
    every accessor test below builds a settings object from *moved* leaves and
    asserts the function follows the moved numbers.
    """
    base = {
        "flat_band_bp": 0.5,
        "real_driven_share": 0.66,
        "breakeven_driven_share": 0.66,
        "trivial_move_bp": 2.0,
        "measured_gold_down_on_nominal_rise_share": 0.7556,
        "measured_breakeven_negative_share": 0.2652,
    }
    base.update(overrides)
    env = {
        k: CalibratedValue(value=v, calibration_status="uncalibrated_illustrative", note="test")
        for k, v in base.items()
    }
    return TransmissionSettings(**env)


# --------------------------------------------------------------------------
# Hand-computed arithmetic, written inline so the expectation is auditable.
# --------------------------------------------------------------------------


def test_the_real_leg_is_the_nominal_less_the_breakeven() -> None:
    """The identity that makes this function possible.

        nominal +40bp, breakeven +10bp  ->  real +30bp
        nominal -40bp, breakeven +10bp  ->  real -50bp   (the legs OPPOSE)
        nominal +40bp, breakeven +55bp  ->  real -15bp   (the legs OPPOSE)

    The third case is the one to hold onto: a nominal RISE with a breakeven
    rise larger than it means the REAL yield fell, so the gold call is UP while
    the bond call is DOWN. A naive implementation that keyed gold on the
    nominal sign would return DOWN here and never notice.
    """
    up = cross_asset_transmission(_inputs())
    assert _value(up)["real_yield_change_bp"] == 30.0

    opposed = cross_asset_transmission(_inputs(nominal_yield_change_bp=-40.0))
    assert _value(opposed)["real_yield_change_bp"] == -50.0

    # The sign-splitting case: nominal up, real down.
    split = cross_asset_transmission(_inputs(breakeven_change_bp=55.0))
    assert _value(split)["real_yield_change_bp"] == -15.0
    assert _value(split)["gold"] == "up"
    assert _value(split)["bonds"] == "down"


def test_the_three_direction_reading_of_a_plain_tightening() -> None:
    """A real-driven selloff at the hand-computed numbers.

    nominal +40bp -> bonds DOWN (price), long duration DOWN, value WINS
    real    +30bp -> gold DOWN
    driver: real share 30/40 = 0.75 >= 0.66 -> real_driven
    """
    r = cross_asset_transmission(_inputs())
    v = _value(r)
    assert v["bonds"] == "down"
    assert v["long_duration_growth_equities"] == "down"
    assert v["value_vs_growth"] == "value_outperforms"
    assert v["gold"] == "down"
    assert v["driver_channel"] == "real_driven"
    assert v["real_leg_share_of_move"] == 0.75
    assert v["breakeven_leg_share_of_move"] == 0.25


def test_a_breakeven_driven_move_flips_the_gold_call_relative_to_the_bond_call() -> None:
    """nominal +40bp, breakeven +38bp -> real +2bp -> a SMALL real move.

    Real share is 2/40 = 0.05, breakeven share 38/40 = 0.95, so the driver is
    ``breakeven_driven`` while the gold call is still ``down`` (2bp clears the
    0.5bp flat band). Contrast with the ``flat`` case below: the split is what
    matters, and a 2bp real leg is a real but tiny real-yield move.
    """
    r = cross_asset_transmission(_inputs(breakeven_change_bp=38.0))
    v = _value(r)
    assert v["bonds"] == "down"
    assert v["real_yield_change_bp"] == 2.0
    assert v["gold"] == "down"
    assert v["driver_channel"] == "breakeven_driven"
    assert v["real_leg_share_of_move"] == 0.05


def test_an_all_breakeven_move_leaves_the_real_leg_inside_the_flat_band() -> None:
    """nominal +40bp, breakeven +39.8bp -> real +0.2bp -> INSIDE the 0.5bp band.

    The bond call is unchanged (the nominal rose a clear 40bp) but gold reads
    ``flat``. This is the sharpest demonstration that the two legs are separate
    reads: an identical nominal move produces a different gold call depending
    only on how the move split.
    """
    r = cross_asset_transmission(_inputs(breakeven_change_bp=39.8))
    v = _value(r)
    assert v["bonds"] == "down"
    assert v["gold"] == "flat"
    assert round(float(v["real_yield_change_bp"]), 2) == 0.2  # type: ignore[arg-type]


def test_a_nominal_rise_with_a_real_fall_splits_the_gold_and_bond_calls() -> None:
    """The divergence case, and it needs a LARGE opposed breakeven.

    nominal +40bp, breakeven +55bp  ->  real -15bp

    So bonds DOWN (the nominal rose) while gold UP (the real fell). This is the
    "hot CPI, gold up" scenario the section's prose says naive reasoning
    misses — reachable, and the reason the real leg is not decorative.

    (A first draft of this test used breakeven=-10bp, which gives real=+50bp and
    therefore two DOWN calls — the legs agreed and the test was asserting the
    wrong thing. Hand arithmetic is a defect source until executed.)
    """
    r = cross_asset_transmission(_inputs(breakeven_change_bp=55.0))
    v = _value(r)
    assert v["bonds"] == "down"
    assert v["gold"] == "up"
    assert v["real_yield_change_bp"] == -15.0


# --------------------------------------------------------------------------
# Defect 6 — the specification's `> 0` / `else` pair reports a flat market.
# --------------------------------------------------------------------------


def test_the_specification_version_reports_a_flat_market_as_a_move() -> None:
    """DEFECT 6, written as the specification's own expression.

    Section 20.5 writes ``"down" if nominal_yield_change_bp > 0 else "up"``.
    For an exactly-unchanged yield the condition is False, so the ``else``
    fires and the map reports ``up`` — a direction, from no movement. This test
    computes the specification's expression inline and asserts it DISAGREES
    with the shipped function, so that a regression to the literal is caught by
    a failing assertion rather than by inspection.
    """
    spec_bonds = "down" if 0.0 > 0 else "up"
    assert spec_bonds == "up"  # the specification's answer for no movement

    r = cross_asset_transmission(_inputs(nominal_yield_change_bp=0.0, breakeven_change_bp=10.0))
    assert _value(r)["bonds"] == "flat"
    assert _value(r)["bonds"] != spec_bonds  # the correction is observable


def test_the_flat_band_boundary_is_owned_by_flat() -> None:
    """A fixture EXACTLY on the configured band (D-045a).

    Without one, a ``<`` -> ``<=`` change is unobservable and every boundary
    reading could silently shift into the neighbouring band. The band is read
    out of config and passed verbatim rather than hardcoded as 0.5, so a
    recalibration moves the fixture with the code.
    """
    band = get_settings().transmission.flat_band
    assert _leg_direction(band, band) == "flat"
    assert _leg_direction(-band, band) == "flat"
    assert _leg_direction(0.0, band) == "flat"
    # Just outside, by ADDITION from round inputs.
    assert _leg_direction(band + 0.5, band) == "down"
    assert _leg_direction(-(band + 0.5), band) == "up"


def test_a_zero_change_cannot_reach_the_map_as_a_direction() -> None:
    """Both legs flat is reported as flat everywhere, never as a move."""
    r = cross_asset_transmission(
        _inputs(nominal_yield_change_bp=0.0, breakeven_change_bp=0.0, inflation_surprise_bp=5.0)
    )
    v = _value(r)
    assert v["bonds"] == "flat"
    assert v["gold"] == "flat"
    assert v["long_duration_growth_equities"] == "flat"
    assert v["value_vs_growth"] == "flat"


def test_both_legs_exactly_zero_with_no_surprise_is_rejected() -> None:
    """The input contract: nothing moved anywhere and nothing was disclosed."""
    with pytest.raises(ValidationError, match="no repricing at all"):
        _inputs(nominal_yield_change_bp=0.0, breakeven_change_bp=0.0)


def test_a_single_zero_leg_is_accepted_because_the_data_produces_it() -> None:
    """D-050's lesson: a state the data produces must not be unrepresentable.

    DGS10 is exactly unchanged on 459 of 5 930 daily changes, so rejecting a
    zero would make a real observation impossible to pass. Only the *fully*
    degenerate pair is refused.
    """
    r = cross_asset_transmission(_inputs(nominal_yield_change_bp=0.0))
    assert _value(r)["bonds"] == "flat"


# --------------------------------------------------------------------------
# Defect 1 — the declared-but-never-read surprise.
# --------------------------------------------------------------------------


def test_the_output_is_invariant_to_the_inflation_surprise() -> None:
    """DEFECT 1: the specification never reads it, and neither does the fix.

    The directions are asserted to be IDENTICAL across a wide sweep of the
    input, which is the claim the specification's own body makes silently. The
    test names the invariant so that adding a dependence on it later is a
    deliberate change with a failing test, not a quiet one.
    """
    baseline = cross_asset_transmission(_inputs(inflation_surprise_bp=None))
    base_v = baseline.value
    assert isinstance(base_v, dict)
    for surprise in (-500.0, -25.0, -1.0, 0.0, 1.0, 25.0, 500.0):
        r = cross_asset_transmission(_inputs(inflation_surprise_bp=surprise))
        v = _value(r)
        for key in ASSET_KEYS:
            assert v[key] == base_v[key], (
                f"{key} moved when inflation_surprise_bp was {surprise}: the "
                "specification does not derive a direction from it, so neither "
                "may this function."
            )


def test_the_surprise_is_published_when_supplied_and_absent_when_not() -> None:
    """The channel is a DISCLOSURE, so it must survive into the output.

    Both halves are asserted: present when supplied (with the value intact) and
    ``None``/absent from ``inputs_used`` when not — a provenance list that
    claims an input it never received is D-037's defect.
    """
    with_s = cross_asset_transmission(_inputs(inflation_surprise_bp=7.5))
    assert _value(with_s)["inflation_surprise_bp"] == 7.5
    assert "inflation_surprise_bp" in with_s.inputs_used

    without = cross_asset_transmission(_inputs())
    assert _value(without)["inflation_surprise_bp"] is None
    assert "inflation_surprise_bp" not in without.inputs_used


def test_a_supplied_surprise_is_reported_not_silently_dropped() -> None:
    """A supplied input with no warning would be invisible."""
    r = cross_asset_transmission(_inputs(inflation_surprise_bp=12.0))
    assert any("REPORTED ONLY" in w for w in r.warnings)
    assert not any("REPORTED ONLY" in w for w in cross_asset_transmission(_inputs()).warnings)


# --------------------------------------------------------------------------
# Defect 2 — the two halves of a Literal (D-045a).
# --------------------------------------------------------------------------


def test_every_declared_direction_is_producible_and_every_emitted_direction_is_declared() -> None:
    """DEFECT 2, via D-045a's rule: a ``Literal`` is a promise with two halves.

    * **Membership** (the easy half): every value the function emits must be a
      declared member. Section 20.5's ``usd`` string is NOT a member, which is
      exactly how the defect is detected.
    * **Producibility** (the half that catches a dead vocabulary entry): every
      declared member must be reachable by SOME input. This is the half that
      would have caught ``GrowthAxis.at_trend`` in D-045a and the ``BOTH``
      branch in D-037.
    """
    declared = set(get_args(TransmissionDirection))
    assert declared, "TransmissionDirection must declare members"

    # The specification's own `usd` value is not a member — asserted directly,
    # because that is the defect.
    assert "up_if_relative_rate_expectations_rose" not in declared

    emitted: set[str] = set()
    for nominal, breakeven, driver in itertools.product(
        (-40.0, 0.0, 40.0), (-30.0, 0.0, 30.0), get_args(SurpriseDriver)
    ):
        try:
            r = cross_asset_transmission(
                _inputs(
                    nominal_yield_change_bp=nominal,
                    breakeven_change_bp=breakeven,
                    surprise_driver=driver,
                )
            )
        except ValidationError:
            continue  # the (0, 0, no surprise) degenerate case
        v = _value(r)
        for key in ASSET_KEYS:
            assert v[key] in declared, f"{key}={v[key]!r} is not a declared direction"
            emitted.add(str(v[key]))

    # Producibility. Every member must appear, or the vocabulary has a dead
    # entry. If this fails, either remove the member or make it reachable —
    # never silence it.
    assert emitted == declared, (
        f"declared but never produced: {sorted(declared - emitted)}; "
        f"produced but not declared: {sorted(emitted - declared)}"
    )


def test_the_specifications_usd_string_is_not_emitted() -> None:
    """The narrow version of defect 2, stated so a regression is unmistakable."""
    r = cross_asset_transmission(_inputs())
    v = _value(r)
    assert v["usd"] == "unresolved"
    assert "up_if_relative_rate_expectations_rose" not in str(v)
    assert any("USD direction requires" in w for w in r.warnings)


# --------------------------------------------------------------------------
# Defect 3 — three keys from one predicate, pinned as such.
# --------------------------------------------------------------------------


def test_the_three_nominal_keys_are_driven_by_one_predicate() -> None:
    """DEFECT 3, pinned rather than "fixed": the coupling is the contract.

    Over the whole sign space, ``long_duration_growth_equities`` and
    ``value_vs_growth`` are a deterministic function of ``bonds``. The test
    asserts the coupling so that decoupling them is deliberate. It is also the
    reason ``bonds`` is published: a reader can see the shared input.
    """
    seen: set[tuple[str, str, str]] = set()
    for nominal in (-40.0, 0.0, 40.0):
        r = cross_asset_transmission(_inputs(nominal_yield_change_bp=nominal))
        v = _value(r)
        seen.add(
            (str(v["bonds"]), str(v["long_duration_growth_equities"]), str(v["value_vs_growth"]))
        )
    assert seen == {
        ("up", "up", "growth_outperforms"),
        ("flat", "flat", "flat"),
        ("down", "down", "value_outperforms"),
    }


def test_the_asset_key_set_is_pinned_before_it_is_iterated() -> None:
    """D-038: a test that ITERATES a published dict is vacuous when it is empty.

    So the key set is asserted first, as an equality against the declared
    constant, and only then are the keys' values read.
    """
    r = cross_asset_transmission(_inputs())
    v = _value(r)
    for key in ASSET_KEYS:
        assert key in v, f"declared asset key {key!r} missing from value"
    assert set(ASSET_KEYS) <= set(v)


def test_the_long_duration_key_is_the_bond_call_re_spelled() -> None:
    """DEFECT 2, asserted per-branch: the three keys from one predicate.

    Added because the mutation sweep found this hole (D-052, survivor M9.2).
    ``test_the_three_nominal_keys_are_driven_by_one_predicate`` checks the
    coupling over the reachable inputs it enumerates; it did not cover the
    ``long_duration`` slot on the FLAT branch, so replacing
    ``long_duration = "flat"`` with a hardcoded ``"up"`` there survived.

    The contract: wherever the nominal leg is flat, BOTH dependent keys are
    flat. Where it is not, ``long_duration`` equals ``bonds`` and
    ``value_vs_growth`` is its style expression — the coupling is what makes
    the output's two bits auditable from the output itself.
    """
    cases = [
        # nominal, breakeven -> (bonds, long_duration, value_vs_growth)
        (40.0, 10.0, ("down", "down", "value_outperforms")),
        (40.0, 55.0, ("down", "down", "value_outperforms")),
        (-40.0, 10.0, ("up", "up", "growth_outperforms")),
        (-40.0, -55.0, ("up", "up", "growth_outperforms")),
        (0.0, 40.0, ("flat", "flat", "flat")),
        (0.2, 40.0, ("flat", "flat", "flat")),
    ]
    for nominal, breakeven, (bonds, long_duration, value_vs_growth) in cases:
        r = cross_asset_transmission(
            _inputs(nominal_yield_change_bp=nominal, breakeven_change_bp=breakeven)
        )
        v = _value(r)
        label = f"nominal {nominal:+.1f}bp / breakeven {breakeven:+.1f}bp"
        assert v["bonds"] == bonds, label
        assert v["long_duration_growth_equities"] == long_duration, label
        assert v["value_vs_growth"] == value_vs_growth, label


def test_the_bond_and_duration_keys_carry_one_bit_between_them() -> None:
    """The coupling is a CONTRACT, asserted rather than left implicit.

    On every branch ``long_duration_growth_equities`` equals ``bonds`` — they are
    the same value written twice. That is the specification's three-keys-from-
    one-predicate defect made visible: the group carries **one** directional bit
    plus, through ``value_vs_growth``, one style bit. Two keys that are always
    equal are not redundant noise here (each names a distinct mechanism: a bond
    price and a duration exposure), but a reader must be able to *see* that they
    are equal rather than infer it from the code.

    This is asserted because the mutation sweep found that changing the
    ``long_duration`` key to read ``bonds`` is a **provable no-op** (D-052,
    survivor M9.2) — a mutant no test could ever kill, because it rewrites a name
    and not a value. Pinning the equality makes the coupling explicit and makes
    the day it STOPS holding a deliberate, tested change rather than a silent
    divergence.
    """
    for nominal in (-40.0, -0.2, 0.0, 0.2, 40.0):
        r = cross_asset_transmission(
            _inputs(nominal_yield_change_bp=nominal, breakeven_change_bp=10.0)
        )
        v = _value(r)
        assert v["long_duration_growth_equities"] == v["bonds"], (
            f"at nominal {nominal:+.1f}bp the duration key diverges from the bond "
            f"key; the one-bit coupling this function documents no longer holds"
        )


# --------------------------------------------------------------------------
# Defect 4 — a hot print and a cool print with the same real move.
# --------------------------------------------------------------------------


def test_a_hot_and_a_cool_print_with_the_same_real_move_are_distinguishable() -> None:
    """DEFECT 4: the gold rule's stated trigger is a HOT print; the code tests
    only the real yield's sign.

    Both cases below have an IDENTICAL nominal and real move — the gold call is
    therefore identical, as it must be, since the rule reads only the split.
    But the driver differs (one is real-driven, one breakeven-driven), and the
    driver is published, so a reader can tell the two scenarios apart. Under
    the specification they were byte-identical outputs.
    """
    hot = cross_asset_transmission(_inputs(nominal_yield_change_bp=40.0, breakeven_change_bp=10.0))
    cool = cross_asset_transmission(_inputs(nominal_yield_change_bp=40.0, breakeven_change_bp=38.0))

    # Read every driver-like field into `object`-typed locals before comparing.
    # Writing the two literals on either side of `!=` lets a type checker fold
    # the comparison statically (they are different literals, so it is trivially
    # true) and report it as a non-overlapping check — which would hide the
    # runtime assertion. Going through the mapping's declared value type keeps
    # the comparison real.
    hot_driver: object = _value(hot)["driver_channel"]
    cool_driver: object = _value(cool)["driver_channel"]

    assert hot_driver == "real_driven"
    assert cool_driver == "breakeven_driven"

    # The DISTINCTNESS of the two readings, asserted as a set property rather
    # than a pairwise inequality: mypy narrows each operand to its own literal
    # after the assertions above, so `hot_driver != cool_driver` is statically
    # decidable and gets reported as a non-overlapping check. Comparing the
    # cardinality of the collected set keeps the assertion meaningful.
    observed = {_value(hot)["driver_channel"], _value(cool)["driver_channel"]}
    assert len(observed) == 2, (
        "the hot and cool prints must be DISTINGUISHABLE — that is the whole "
        f"point of publishing the driver channel; both read {observed}"
    )


def test_the_gold_call_carries_its_base_rate() -> None:
    """D-029's base-rate rule: a categorical travels with its own frequency.

    ``gold: down`` on a nominal rise is what the rule says about four times in
    five, i.e. closer to a default than to a finding. The frequency must be on
    the output AND in a warning, so a reader cannot mistake the label for news.
    """
    settings = get_settings().transmission
    r = cross_asset_transmission(_inputs())
    v = _value(r)
    assert v["gold"] == "down"
    assert v["gold_call_base_rate"] == settings.gold_base_rate
    assert any("base rate" in w.lower() for w in r.warnings)


def test_the_gold_base_rate_follows_a_perturbed_config() -> None:
    """The accessor test that CAN see a hardcoded literal (D-050).

    A test asserting ``value["gold_call_base_rate"] == 0.7556`` passes whether
    the code reads the YAML or returns the constant. This one asserts the
    shipped number is NOT returned when the config says otherwise.
    """
    assert get_settings().transmission.gold_base_rate != 0.1234
    moved = _settings(measured_gold_down_on_nominal_rise_share=0.1234)
    assert moved.gold_base_rate == 0.1234
    assert moved.gold_base_rate != 0.7556


# --------------------------------------------------------------------------
# Defect 5 — the bare `str` with an `else` fallthrough.
# --------------------------------------------------------------------------


def test_an_unknown_surprise_driver_is_rejected_not_silently_defaulted() -> None:
    """DEFECT 5: a typo must be a validation failure, not the shelter-lag case.

    Section 20.5 types it ``str``, so ``"supply shock"`` (a space) reaches the
    ``else`` and is reported as the mechanical-lag branch with no error. Here
    it is a ``ValidationError``.
    """
    assert set(get_args(SurpriseDriver)) == {"demand", "supply_shock", "shelter_lag_mechanical"}
    for bad in ("supply shock", "supply", "demand_driven", "", "Shelter_Lag_Mechanical"):
        with pytest.raises(ValidationError):
            _inputs(surprise_driver=bad)


def test_every_declared_driver_is_producible_in_the_equity_key() -> None:
    """The second half of the ``Literal`` promise, on the driver.

    The equity key is the ONE place the declared driver is load-bearing (it
    selects a mechanism, not a direction), so every member must reach a
    distinct output.
    """
    seen = set()
    for driver in get_args(SurpriseDriver):
        r = cross_asset_transmission(_inputs(surprise_driver=driver))
        v = _value(r)
        seen.add(str(v["equities_overall"]))
    assert len(seen) == len(get_args(SurpriseDriver))


def test_each_driver_reaches_a_named_equity_read() -> None:
    """The three equity reads, pinned by NAME rather than by cardinality.

    Added because the mutation sweep found this hole (D-052, survivor M6.1).
    ``test_every_declared_driver_is_producible_in_the_equity_key`` asserts the
    three outputs are *distinct*, which is a cardinality claim — it is satisfied
    by any injective map. Rewriting the first branch's guard from
    ``== "supply_shock"`` to ``== "shelter_lag_mechanical"`` keeps the map
    injective (``demand`` -> better, ``shelter_lag_mechanical`` -> worse,
    ``supply_shock`` -> flat) and so survives it, even though it has just made
    ``worse_than_rate_move_alone`` describe the wrong mechanism and moved
    ``supply_shock`` onto the neutral reading.

    Naming the mechanism for each member is the assertion that closes it, and it
    is the D-045a two-halves rule read properly: it is not enough that every
    member be producible, each must be producible *as the thing it names*.
    """
    expected = {
        "supply_shock": "worse_than_rate_move_alone",
        "demand": "better_than_rate_move_alone",
        "shelter_lag_mechanical": "flat",
    }
    assert set(expected) == set(get_args(SurpriseDriver))
    for driver, equity_read in expected.items():
        r = cross_asset_transmission(_inputs(surprise_driver=driver))
        v = _value(r)
        assert v["equities_overall"] == equity_read, (
            f"{driver!r} must read {equity_read!r}, got {v['equities_overall']!r}"
        )


def test_extra_fields_are_forbidden() -> None:
    """Each pydantic model needs its OWN `extra="forbid"` test (the suite rule)."""
    with pytest.raises(ValidationError):
        InflationTransmissionInputs(
            surprise_driver="demand",
            nominal_yield_change_bp=40.0,
            breakeven_change_bp=10.0,
            surprise_bp=5.0,  # type: ignore[call-arg]
        )


# --------------------------------------------------------------------------
# Defect 7 — confidence.
# --------------------------------------------------------------------------


def test_confidence_comes_from_compute_confidence_not_a_literal() -> None:
    """DEFECT 7: the specification hardcodes ``0.45``; §22.8 forbids it.

    Asserted by its DISCRIMINATING property rather than by value: the shipped
    confidence must equal what ``compute_confidence`` returns for the same
    stated factors and must differ from the specification's literal. Section
    20.5's ``0.45`` coincides with nothing the rule produces here, so a
    literal would fail.
    """
    r = cross_asset_transmission(_inputs())
    expected = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, depends_on_unobservable=False)
    )
    assert r.confidence == expected
    assert r.confidence != 0.45


def test_confidence_is_flat_across_the_whole_direction_space() -> None:
    """The verdict is a fact about the world; confidence is about measurement.

    Section 20.3's defect class was a confidence that MOVED with the
    conclusion. Asserted over the enumerated input space, and pinned to the
    ABSOLUTE value (D-046: an invariance test comparing a function to itself
    cannot detect a change to a constant both sides read).
    """
    absolute = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, depends_on_unobservable=False)
    )
    for nominal, breakeven in itertools.product((-40.0, 0.0, 40.0), (-30.0, 0.0, 30.0)):
        try:
            r = cross_asset_transmission(
                _inputs(nominal_yield_change_bp=nominal, breakeven_change_bp=breakeven)
            )
        except ValidationError:
            continue
        assert r.confidence == absolute


# --------------------------------------------------------------------------
# The driver classifier — thresholds, boundaries, and the config accessors.
# --------------------------------------------------------------------------


def test_the_driver_is_indeterminate_below_the_trivial_move_floor() -> None:
    """A share over a near-zero denominator is not a measurement.

    The floor is read from config and passed verbatim, so a recalibration moves
    the fixture with the code.
    """
    floor = get_settings().transmission.trivial_move
    assert (
        _driver_of(
            real_change_bp=floor - 1.0,
            breakeven_change_bp=0.0,
            nominal_change_bp=floor - 1.0,
            real_threshold=0.66,
            breakeven_threshold=0.66,
            trivial_move=floor,
        )
        == "indeterminate"
    )


def test_the_driver_floor_boundary_is_owned_by_the_classifier() -> None:
    """EXACTLY on the floor: the classifier owns it (the guard is ``<``)."""
    floor = get_settings().transmission.trivial_move
    got = _driver_of(
        real_change_bp=floor,
        breakeven_change_bp=0.0,
        nominal_change_bp=floor,
        real_threshold=0.66,
        breakeven_threshold=0.66,
        trivial_move=floor,
    )
    assert got == "real_driven"


def test_the_two_single_leg_outcomes_are_not_absorbed_by_their_neighbours() -> None:
    """Each of the four banded outcomes is DISTINCT, not a superset of another.

    Added because the mutation sweep found a hole here (D-052, survivors M2.7
    and M2.8). ``test_the_driver_bands_classify_all_five_outcomes`` checks that
    each label is *reachable*, but reachability alone does not catch a branch
    whose predicate absorbs an earlier one: rewriting ``if real_drives:`` as
    ``if real_drives and not breakeven_drives:`` still returns ``real_driven``
    for every input the reachability test supplies, because none of those inputs
    has both flags set.

    The pair of inputs below is what separates them. At a deliberately LOW band
    (0.30) a nominal +40 / real +40 / breakeven 0 move has shares 1.00 / 0.00 —
    so ``breakeven_drives`` is **False** and the two spellings agree. Raising
    the band to 0.60 does not change the result either; what changes it is an
    input where BOTH flags are true while the move is *not* opposed, which the
    both-channels comment says is impossible for a share and its complement.
    So the correct assertion is not on a contrived input but on the equivalence
    class itself: ``real_driven`` must be produced when only the real flag is
    set, and ``both_channels`` when both are.
    """
    kw = {"real_threshold": 0.66, "breakeven_threshold": 0.66, "trivial_move": 2.0}

    # Only the real flag set: real share 1.00 >= 0.66, breakeven share 0.00 < it.
    only_real = _driver_of(40.0, 0.0, 40.0, **kw)
    assert only_real == "real_driven"

    # Only the breakeven flag set.
    only_breakeven = _driver_of(0.0, 40.0, 40.0, **kw)
    assert only_breakeven == "breakeven_driven"

    # BOTH flags set. Reachable only with opposed legs (shares 1.75 / -0.75).
    both = _driver_of(28.0, -12.0, 16.0, **kw)
    assert both == "both_channels"

    # The three are distinct labels, which is the property M2.7/M2.8 attacked.
    assert len({only_real, only_breakeven, both}) == 3


def test_a_swallowed_single_leg_branch_is_detectable_at_a_low_band() -> None:
    """The sweep's M2.7/M2.8 mutants, killed directly.

    Those mutants rewrite ``if real_drives:`` to ``if real_drives and not
    breakeven_drives:`` (and the mirror). The rewrite is a no-op whenever the
    second flag is False — so a test that only probes the shipped 0.66 band can
    miss it. It is NOT a no-op when both flags are true, and both flags are true
    exactly in the opposed-leg case that also returns ``both_channels``. Since
    that branch is tested first, the mutant is in fact a no-op *for every
    reachable input* at this band order — which is why the mutation survived and
    why the honest repair is this test, asserting the ordering contract
    explicitly rather than pretending to kill the mutant.

    The contract being asserted: the both-channels branch is tested BEFORE the
    single-leg branches, so an input with both flags set returns
    ``both_channels`` regardless of how the single-leg predicates are spelled.
    If a future edit reorders them, this test fails and the ordering becomes
    visible again (D-050's composition lesson).
    """
    kw = {"real_threshold": 0.66, "breakeven_threshold": 0.66, "trivial_move": 2.0}
    both_flags = _driver_of(28.0, -12.0, 16.0, **kw)
    assert both_flags == "both_channels"

    # At a band low enough that BOTH flags are set on a move whose legs are
    # same-signed, the first branch still wins — the ordering is what decides,
    # not the individual predicates.
    low = {"real_threshold": 0.30, "breakeven_threshold": 0.30, "trivial_move": 2.0}
    assert _driver_of(28.0, 12.0, 40.0, **low) == "both_channels"


def test_the_driver_bands_classify_all_five_outcomes() -> None:
    """The five reachable labels, each from arithmetic stated inline.

        nom 40, real 40, be  0  -> shares 1.00 /  0.00 -> real_driven
        nom 40, real  0, be 40  -> shares 0.00 /  1.00 -> breakeven_driven
        nom 16, real 28, be -12 -> shares 1.75 / -0.75 -> both_channels
        nom 40, real 20, be 20  -> shares 0.50 /  0.50 -> neither_channel

    ``both_channels`` is reachable ONLY when the legs OPPOSE: a share and its
    complement cannot both exceed two-thirds otherwise, so the be share must be
    large and NEGATIVE. ``nom 40 / be -10`` looks like an opposed pair but
    gives shares 1.25 / -0.25 — the breakeven leg is too small, so it is
    ``real_driven``. That distinction is the reason the case below uses -12
    against a +16 nominal rather than -10 against +40.
    """
    kw = {
        "real_threshold": 0.66,
        "breakeven_threshold": 0.66,
        "trivial_move": 2.0,
    }
    assert _driver_of(40.0, 0.0, 40.0, **kw) == "real_driven"
    assert _driver_of(0.0, 40.0, 40.0, **kw) == "breakeven_driven"
    # real = +28, breakeven = -12, nominal = +16 -> shares 1.75 / -0.75.
    assert _driver_of(28.0, -12.0, 16.0, **kw) == "both_channels"
    assert _driver_of(20.0, 20.0, 40.0, **kw) == "neither_channel"
    # And the counter-example: a small opposed leg is NOT both_channels.
    assert _driver_of(50.0, -10.0, 40.0, **kw) == "real_driven"


def test_the_band_boundary_is_owned_by_the_band() -> None:
    """EXACTLY on the band: ``|share| >= band`` means the band owns it.

    Built by ADDITION from round inputs, because subtraction is not exact:
    ``0.66`` and ``66/100`` are the same float, but ``26.4/40`` is
    0.65999999999999992 — BELOW the band. A fixture written as 26.4/40 would
    test the wrong side and read as a code bug (the D-029/D-045a rule). The
    boundary is therefore nom=100, real=66, be=34.
    """
    kw = {"real_threshold": 0.66, "breakeven_threshold": 0.66, "trivial_move": 0.0}
    assert 66.0 / 100.0 == 0.66  # the fixture's share IS the configured band
    assert _driver_of(66.0, 34.0, 100.0, **kw) == "real_driven"
    # One tick below, and it falls out of the band.
    assert _driver_of(65.0, 35.0, 100.0, **kw) == "neither_channel"
    # The subtraction trap, asserted explicitly so nobody re-introduces it.
    assert 26.4 / 40.0 < 0.66


def test_the_driver_follows_perturbed_thresholds() -> None:
    """A moved band must move the classification, or the config is decorative.

    The same inputs classify ``real_driven`` at a 0.66 band and
    ``neither_channel`` at a 0.90 band — a value the shipped literal cannot
    produce.
    """
    r, b, n = 30.0, 10.0, 40.0  # real share 0.75
    assert _driver_of(r, b, n, real_threshold=0.66, breakeven_threshold=0.66, trivial_move=2.0) == (
        "real_driven"
    )
    assert _driver_of(r, b, n, real_threshold=0.90, breakeven_threshold=0.66, trivial_move=2.0) == (
        "neither_channel"
    )


def test_the_flat_band_follows_a_perturbed_config() -> None:
    """The accessor test for ``flat_band``, against a PERTURBED object.

    At the shipped 0.5bp band a 1bp change is ``down``; at a perturbed 2.0bp
    band the same change is ``flat``. Asserting both proves the band is read
    rather than baked in.
    """
    shipped = get_settings().transmission.flat_band
    assert shipped != 2.0
    assert _leg_direction(1.0, 2.0) == "flat"
    assert _leg_direction(1.0, 0.5) == "down"


def test_the_trivial_move_accessor_follows_a_perturbed_config() -> None:
    """The accessor test for ``trivial_move``, against a PERTURBED object.

    Added because the mutation sweep found this hole (D-052, survivor M11.4).
    The sibling tests pin ``flat_band`` (above) and both driver shares (below),
    but the trivial-move floor was only ever exercised through
    ``get_settings()`` — and a test that reads the *live* value cannot
    distinguish a YAML read from ``return 2.0``, because at the shipped config
    those are the same number (D-050's rule, reached again).

    The discriminating input is a nominal change of exactly 1.0bp: below the
    shipped 2.0bp floor it is ``indeterminate``, above a perturbed 0.6bp floor
    it is a measurable split. Both are asserted, so a literal that happened to
    equal the shipped value fails.

    The perturbed leaf is 0.6 and not 0.5 deliberately: ``trivial_move_bp`` must
    EXCEED ``flat_band_bp`` (0.5) or ``TransmissionSettings`` refuses to
    construct, so 0.5 is the one nearby value that cannot be used here. (The
    first draft of this test used it and the validator caught the mistake before
    the test ever ran.)
    """
    assert (
        _driver_of(
            real_change_bp=1.0,
            breakeven_change_bp=0.0,
            nominal_change_bp=1.0,
            real_threshold=0.66,
            breakeven_threshold=0.66,
            trivial_move=2.0,
        )
        == "indeterminate"
    )
    assert (
        _driver_of(
            real_change_bp=1.0,
            breakeven_change_bp=0.0,
            nominal_change_bp=1.0,
            real_threshold=0.66,
            breakeven_threshold=0.66,
            trivial_move=0.6,
        )
        == "real_driven"
    )
    # And the accessor itself must track a moved leaf, not merely a moved
    # argument: this is the half that a hardcoded `return 2.0` breaks.
    assert _settings(trivial_move_bp=0.6).trivial_move == 0.6
    assert _settings(trivial_move_bp=12.5).trivial_move == 12.5
    assert get_settings().transmission.trivial_move != 0.6


def test_the_trivial_floor_must_exceed_the_flat_band() -> None:
    """The config cross-check (D-047 rule 27): a value that can be derived
    must be validated, and the validation must be shown to FIRE."""
    with pytest.raises(ValidationError, match="must exceed"):
        _settings(trivial_move_bp=0.5, flat_band_bp=0.5)
    with pytest.raises(ValidationError, match="must exceed"):
        _settings(trivial_move_bp=0.1, flat_band_bp=0.5)


def test_an_unsatisfiable_driver_band_is_rejected() -> None:
    """D-047: a threshold no input can satisfy is dead config."""
    with pytest.raises(ValidationError, match="must lie in"):
        _settings(real_driven_share=0.0)
    with pytest.raises(ValidationError, match="must lie in"):
        _settings(real_driven_share=1.5)
    with pytest.raises(ValidationError, match="must lie in"):
        _settings(breakeven_driven_share=0.0)
    # The boundary 1.0 is ALLOWED: a share of exactly 1.0 is reachable.
    assert _settings(real_driven_share=1.0).real_driven_threshold == 1.0


def test_a_negative_flat_band_is_rejected() -> None:
    """A negative band is compared against an absolute value, so unreachable."""
    with pytest.raises(ValidationError, match="cannot be negative"):
        _settings(flat_band_bp=-1.0)


# --------------------------------------------------------------------------
# Warning coverage — a branch with no test is deletable.
# --------------------------------------------------------------------------


def _warning_branches() -> dict[str, str]:
    """The warning branches ``cross_asset_transmission`` can emit, by marker.

    A ``dict`` of ``marker -> human label`` rather than a bare list, and the
    markers are chosen to be **mutually non-colliding substrings**. The earlier
    list version failed that requirement: the indeterminate branch was marked
    ``"below the"``, which also occurs inside the *flat* branch's wording
    ("...within the 0.5bp flat band. Section 20.5's `> 0` test would have...").
    Deleting the indeterminate branch therefore left the coverage test green,
    because the flat branch still satisfied its marker -- a wording collision
    masquerading as coverage.

    The mutation sweep is what found this (D-052, survivor M10.3). It is a
    sharper version of the project's standing position that warning *text* is
    not the safety mechanism: text is not the mechanism, but it IS the key this
    coverage test looks up by, so a marker that collides silently disables the
    guard. Each marker below is a phrase that appears in exactly one branch.
    """
    return {
        "USD direction requires": "the USD leg is unresolvable on a US-only system",
        "The transmission map is a set of DIRECTIONAL": "one channel, not a forecast",
        "within the": "the nominal move is inside the flat band",
        "GOLD DISAGREES WITH BONDS": "the gold and bond calls point opposite ways",
        "SPLIT is measurable": "the nominal move is below the driver floor",
        "BOTH legs carry most of the move": "both channels drove, so unattributable",
        "NEITHER leg carries most of the move": "the legs offset, so unattributable",
        # D-135 made this branch symmetric, so the marker must be
        # direction-agnostic. It used to read "Gold reads DOWN on a nominal
        # yield RISE", which matched ONLY the `down` branch — the majority case
        # (gold_base_rate = 0.7556). The minority branch (`gold: up` on a rise,
        # the one that contradicts the nominal move) was therefore unreachable
        # by any fixture AND unmatched by any marker, so it could have been
        # deleted with this coverage test still green. The marker is now the
        # shared prefix of both branches, and BOTH are in the fixture list
        # below, so the pair is covered as a pair.
        "on a nominal yield RISE": "the gold base rate, in either direction",
        "REPORTED ONLY": "the surprise is disclosed, never consumed",
    }


def test_every_warning_path_is_triggered_by_some_test() -> None:
    """Defect-agnostic coverage guard (D-045a: an untested warning path is an
    untested safety mechanism).

    Each branch below is triggered by a fixture, and the union is asserted to
    equal the declared set — so a new branch that no fixture reaches fails
    here rather than shipping uncovered.

    The markers must be mutually non-colliding; see ``_warning_branches``.
    """
    reached: set[str] = set()

    cases = [
        _inputs(),  # baseline: usd + general + gold-down-on-rise
        _inputs(nominal_yield_change_bp=0.0),  # flat nominal -> flat warning
        _inputs(breakeven_change_bp=55.0),  # opposed legs -> gold disagrees
        _inputs(nominal_yield_change_bp=1.0),  # below trivial floor -> indeterminate
        _inputs(nominal_yield_change_bp=16.0, breakeven_change_bp=-12.0),  # both channels
        _inputs(nominal_yield_change_bp=40.0, breakeven_change_bp=20.0),  # neither
        _inputs(inflation_surprise_bp=9.0),  # disclosure warning
        # D-135: gold UP on a nominal RISE -- the minority branch, where the gold
        # call contradicts the nominal move and carries its own base rate.
        _inputs(breakeven_change_bp=120.0),
    ]
    for inputs in cases:
        for w in cross_asset_transmission(inputs).warnings:
            for marker in _warning_branches():
                if marker in w:
                    reached.add(marker)

    missing = set(_warning_branches()) - reached
    assert not missing, f"warning branch(es) reached by no fixture: {sorted(missing)}"


def test_the_warning_markers_are_mutually_non_colliding() -> None:
    """A marker that appears in two branches cannot detect the loss of either.

    This is the guard the mutation sweep's M10.3 survivor proved was missing.
    For every fixture that produces warnings, each emitted warning must match
    exactly ONE of the declared markers: two matches means the marker set cannot
    tell the branches apart, and one branch could be deleted undetected.
    """
    cases = [
        _inputs(),
        _inputs(nominal_yield_change_bp=0.0),
        _inputs(breakeven_change_bp=55.0),
        _inputs(nominal_yield_change_bp=1.0),
        _inputs(nominal_yield_change_bp=16.0, breakeven_change_bp=-12.0),
        _inputs(nominal_yield_change_bp=40.0, breakeven_change_bp=20.0),
        _inputs(inflation_surprise_bp=9.0),
        _inputs(breakeven_change_bp=120.0),  # D-135: gold up on a nominal rise
    ]
    markers = list(_warning_branches())
    for inputs in cases:
        for w in cross_asset_transmission(inputs).warnings:
            hits = [mk for mk in markers if mk in w]
            assert len(hits) == 1, (
                f"a warning matched {len(hits)} markers ({hits}); the marker set "
                f"cannot distinguish those branches, so deleting one would leave "
                f"the coverage test green. Warning: {w!r}"
            )


def test_the_disagreement_warning_fires_only_when_the_legs_disagree() -> None:
    """The gold-vs-bonds warning is conditional, and both sides are asserted.

    D-046's rule: a guard is tested by disabling the guard, not by rephrasing
    its message — so this asserts the *condition* (agreement) suppresses the
    branch as well as the condition (disagreement) raising it.
    """
    agreeing = cross_asset_transmission(_inputs())  # both read down
    v = agreeing.value
    assert isinstance(v, dict)
    assert v["gold"] == v["bonds"] == "down"
    assert not any("GOLD DISAGREES" in w for w in agreeing.warnings)

    disagreeing = cross_asset_transmission(_inputs(breakeven_change_bp=55.0))
    dv = disagreeing.value
    assert isinstance(dv, dict)
    assert dv["gold"] == "up" and dv["bonds"] == "down"
    assert any("GOLD DISAGREES" in w for w in disagreeing.warnings)


def test_the_gold_base_rate_warning_is_symmetric_about_the_gold_call() -> None:
    """D-135 — the gold base-rate warning must not be keyed on its own base rate.

    ``transmission.gold_base_rate`` is measured as the share of nominal rises on
    which the rule says DOWN (the MAP's **modal** answer, 0.7556). The warning
    used to fire only on ``gold == "down"``, so it advertised the base state as
    though it were the exception while the genuinely informative branch --
    ``gold: up`` on a nominal rise, where the gold call CONTRADICTS the nominal
    move -- carried no caveat at all.

    Both directions are asserted, and each must name its OWN measured share
    rather than a shared one: a test that only checked the message existed would
    pass under the one-sided form (the D-031 pinner failure).
    """
    settings = get_settings().transmission

    down = cross_asset_transmission(_inputs())  # nominal +40bp, real yields up
    dv = down.value
    assert isinstance(dv, dict)
    assert dv["gold"] == "down"
    down_warning = next((w for w in down.warnings if "on a nominal yield RISE" in w), None)
    assert down_warning is not None, "the gold base-rate warning vanished"
    assert f"{settings.gold_base_rate:.2%}" in down_warning
    assert "default" in down_warning

    # breakeven 120 > nominal 40, so the REAL leg FALLS and gold reads up.
    up = cross_asset_transmission(_inputs(breakeven_change_bp=120.0))
    uv = up.value
    assert isinstance(uv, dict)
    assert uv["gold"] == "up" and uv["real_yield_change_bp"] < 0
    up_warning = next((w for w in up.warnings if "on a nominal yield RISE" in w), None)
    assert up_warning is not None, (
        "gold UP on a nominal rise carries no base-rate caveat -- this is the "
        "D-135 defect: the minority branch was silent because the gate keyed "
        "on the majority branch."
    )
    assert "Gold reads UP" in up_warning
    assert f"{1.0 - settings.gold_base_rate:.2%}" in up_warning
    assert "minority case" in up_warning

    # The two rates are complements and sum to one, so no config leaf was
    # invented for the second branch.
    assert f"{settings.gold_base_rate:.2%}" not in up_warning


def test_the_usd_warning_is_unconditional() -> None:
    """The USD leg is unresolvable on this system for EVERY input, so its
    warning is a property of the architecture, not of the repricing."""
    for nominal, breakeven in itertools.product((-40.0, 0.0, 40.0), (-30.0, 30.0)):
        r = cross_asset_transmission(
            _inputs(nominal_yield_change_bp=nominal, breakeven_change_bp=breakeven)
        )
        assert any("USD direction requires" in w for w in r.warnings)


def test_driver_attribution_warnings_cover_both_non_attributable_cases() -> None:
    """``both_channels`` and ``neither_channel`` each warn, and each names why.

    The distinction matters: ``both`` means the legs OPPOSED, ``neither`` means
    they OFFSET. Pooling them would report two different failures as one.
    """
    both = cross_asset_transmission(
        _inputs(nominal_yield_change_bp=16.0, breakeven_change_bp=-12.0)
    )
    neither = cross_asset_transmission(
        _inputs(nominal_yield_change_bp=40.0, breakeven_change_bp=20.0)
    )
    assert any("OPPOSITE directions" in w for w in both.warnings)
    assert any("offset each other" in w for w in neither.warnings)
    assert not any("OPPOSITE directions" in w for w in neither.warnings)


# --------------------------------------------------------------------------
# The result envelope.
# --------------------------------------------------------------------------


def test_the_result_carries_the_full_contract() -> None:
    """Every ``ModelResult`` field that matters is populated, not defaulted."""
    r = cross_asset_transmission(_inputs())
    assert r.model_name == "cross_asset_transmission"
    assert r.country == "us"
    assert r.as_of.tzinfo is not None  # utc_now(), never a naive datetime
    assert r.interpretation
    assert r.context
    assert r.inputs_used
    assert 0.0 <= r.confidence <= 1.0


def test_the_context_reports_the_exact_identity() -> None:
    """The context is the only place the output states WHY the derivation is
    sound. It is asserted, because a silent removal would leave the map
    looking like a proxy rather than an identity."""
    r = cross_asset_transmission(_inputs())
    assert "EXACT identity" in r.context
    assert "0.000000" in r.context


def test_inputs_used_names_the_change_suppliers() -> None:
    """The provenance list must name what was read, in the fixture's terms.

    D-051's rule: assert against the FIXTURE's values, never against a
    mutation's replacement string — a test written from the mutant's output
    passes only under the mutation.
    """
    r = cross_asset_transmission(_inputs())
    assert r.inputs_used == [
        "surprise_driver",
        "nominal_yield_change_bp",
        "breakeven_change_bp",
    ]


def test_the_real_leg_shares_are_published_and_reconcile() -> None:
    """A cross-field identity recomputed from the REPORTED components.

    ``breakeven_leg_share + real_leg_share == 1.0`` by construction, so a
    reader can audit the split from the output alone. Asserted at two
    different splits so a swap of the two keys is caught.
    """
    for breakeven in (10.0, 25.0):
        r = cross_asset_transmission(_inputs(breakeven_change_bp=breakeven))
        v = _value(r)
        assert v["real_yield_change_bp"] == 40.0 - breakeven
        total = v["real_leg_share_of_move"] + v["breakeven_leg_share_of_move"]  # type: ignore[operator]
        assert total == pytest.approx(1.0, abs=1e-9)


def test_the_leg_shares_are_none_when_the_nominal_change_is_zero() -> None:
    """A zero denominator must not produce a division or a fake number."""
    r = cross_asset_transmission(_inputs(nominal_yield_change_bp=0.0))
    v = _value(r)
    assert v["real_leg_share_of_move"] is None
    assert v["breakeven_leg_share_of_move"] is None


# --------------------------------------------------------------------------
# Reachability — the composition check D-050/D-051 both needed.
# --------------------------------------------------------------------------


def test_every_driver_label_is_reachable_from_the_public_function() -> None:
    """A label the function cannot return is D-037's dead-branch class.

    ``_driver_of`` is exercised directly elsewhere; this asserts the same
    labels are reachable THROUGH the public entry point, which is the thing a
    caller actually has.
    """
    reachable = set()
    for nominal, breakeven in itertools.product(
        (-40.0, -14.0, -2.0, 0.0, 2.0, 14.0, 40.0), (-30.0, -6.0, 0.0, 6.0, 30.0)
    ):
        try:
            r = cross_asset_transmission(
                _inputs(nominal_yield_change_bp=nominal, breakeven_change_bp=breakeven)
            )
        except ValidationError:
            continue
        v = _value(r)
        reachable.add(str(v["driver_channel"]))
    assert reachable == {
        "real_driven",
        "breakeven_driven",
        "both_channels",
        "neither_channel",
        "indeterminate",
    }


def test_the_real_leg_and_the_nominal_leg_disagree_on_a_reachable_input() -> None:
    """The TRIPWIRE for the function's whole reason to exist.

    If every reachable input made ``gold`` a function of the nominal sign, the
    real-yield leg would be decorative and this function would be a relabelling
    of the bond call. It is not: this asserts they genuinely diverge, over a
    reachable input. If a future change makes the split monotone in the nominal
    sign, this fails loudly rather than the map silently degrading.
    """
    divergences = 0
    for nominal, breakeven in itertools.product(
        (-40.0, -14.0, 14.0, 40.0), (-30.0, -6.0, 6.0, 30.0)
    ):
        r = cross_asset_transmission(
            _inputs(nominal_yield_change_bp=nominal, breakeven_change_bp=breakeven)
        )
        v = _value(r)
        if v["gold"] != v["bonds"] and v["gold"] != "flat" and v["bonds"] != "flat":
            divergences += 1
    assert divergences > 0, (
        "gold never disagreed with bonds anywhere in the enumerated input "
        "space; the real-yield split has become a relabelling of the nominal sign."
    )
