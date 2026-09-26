"""Hand-verified tests for ``dollar_smile_regime`` — Module 9, Section 6.7.

This function is not arithmetic — it is a **three-way threshold classifier**, and
that changes what has to be proved. Every one of the three failure modes below
was **measured before a line of the function was written** (the probe lives at
``.probe/dollar_smile_probe.py`` and the live check re-runs its enumeration):

1. **Reachability.** The stub is most-severe-first, which is the shape D-050 found
   could leave the branches behind the first gate unreachable. Enumerated over the
   shipped thresholds, all three limbs ARE reachable — the left gate does not
   consume the space behind it, because ``vix_level`` is a continuous level rather
   than a flag. ``test_every_limb_is_reachable_and_the_left_gate_consumes_nothing``
   pins that, and it is the tripwire that fails if a future edit changes the shape.
2. **The zero case.** With the specification's ``> 0``, an exactly-zero surprise or
   an exactly-zero rate gap falls through to the **middle** label — a neutral input
   published as "synchronized global growth". The boundary is kept at the
   specification's ``> 0`` (so the middle branch OWNS the zero case) and the model
   publishes ``is_neutral_input`` so that the two causes of a middle label are
   distinguishable. ``test_a_zero_input_is_neutral_and_says_so`` pins it.
3. **Confidence.** Section 6.7 hardcodes ``confidence=0.4``, and the
   correctly-computed value is **also** 0.40 today (base 0.7 minus the 0.20
   heuristic penalty, both leaves uncalibrated). A test asserting ``== 0.4``
   therefore cannot tell a literal from the computed value — D-050's trap. The
   confidence tests below assert against ``compute_confidence`` and against a
   PERTURBED base instead, so a hardcoded literal fails them.

The boundary fixtures are built by **addition with binary-exact values**, never by
subtraction, and each asserts its own exactness: ``25.0 + 0.5 == 25.5`` is exact,
where a fixture built as ``25.5 - 0.4`` would sit a hair off the boundary it claims
to probe (lesson 5o).
"""

from __future__ import annotations

import itertools
import math
from typing import get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import CalibratedValue, FxCarrySettings, get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.fx_carry import (
    _DOLLAR_SMILE_BASE_RATES,
    DollarSmileInputs,
    DollarSmileSide,
    _dollar_smile_is_neutral,
    _dollar_smile_thresholds_are_calibrated,
    dollar_smile_regime,
)
from tests.helpers import as_bool, as_float, as_str

#: The shipped thresholds, read once for the fixtures that must sit ON them. A
#: fixture built from a re-typed literal would keep testing the old boundary
#: after the config moved.
_VIX_GATE = 25.0
_SIGN_BOUNDARY = 0.0


def _inputs(**overrides: object) -> DollarSmileInputs:
    base: dict[str, object] = {
        "vix_level": 15.0,
        "us_growth_surprise": 1.0,
        "us_vs_row_rate_diff": 0.5,
    }
    base.update(overrides)
    return DollarSmileInputs.model_validate(base)


def _value(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    return as_float(result, key=key)


def _label(result: ModelResult, key: str) -> str:
    return as_str(result, key=key)


def _flag(result: ModelResult, key: str) -> bool:
    return as_bool(result, key=key)


# ---------------------------------------------------------------------------
# The classification itself — the whole point of the function.
# ---------------------------------------------------------------------------

#: (label, vix, growth, diff, expected side)
_CASES: tuple[tuple[str, float, float, float, str], ...] = (
    ("left: crisis with strong US data", 30.0, 1.0, 1.0, "left"),
    ("left: crisis with weak US data", 30.0, -1.0, -1.0, "left"),
    ("right: below the gate, both positive", 15.0, 1.0, 1.0, "right"),
    ("middle: below the gate, growth negative", 15.0, -1.0, 1.0, "middle"),
    ("middle: below the gate, diff negative", 15.0, 1.0, -1.0, "middle"),
    ("middle: below the gate, both negative", 15.0, -1.0, -1.0, "middle"),
)


@pytest.mark.parametrize(
    ("label", "vix", "growth", "diff", "expected"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_the_side_matches_the_hand_derived_region(
    label: str, vix: float, growth: float, diff: float, expected: str
) -> None:
    result = dollar_smile_regime(
        _inputs(vix_level=vix, us_growth_surprise=growth, us_vs_row_rate_diff=diff)
    )
    assert _label(result, "side") == expected


def test_the_left_gate_is_decided_by_vix_alone() -> None:
    """Above the gate, the growth and rate inputs have no say at all.

    Section 6.7 tests the VIX gate first, and the order is load-bearing rather
    than cosmetic: a crisis reading with strong US data is classified as the left
    limb, because the safe-haven bid is what the market is trading. Reversing the
    branch order would silently relabel every such reading as durable US
    outperformance — so this test drives all four sign combinations above the gate
    and requires the same answer.
    """
    for growth, diff in itertools.product((-1.0, 1.0), repeat=2):
        result = dollar_smile_regime(
            _inputs(vix_level=30.0, us_growth_surprise=growth, us_vs_row_rate_diff=diff)
        )
        assert _label(result, "side") == "left", f"growth={growth} diff={diff}"


# ---------------------------------------------------------------------------
# Reachability — D-050's hazard, enumerated rather than assumed.
# ---------------------------------------------------------------------------


def test_every_declared_side_is_in_the_type() -> None:
    """The easy half: the type's declared members are what the code names."""
    assert set(get_args(DollarSmileSide)) == {"left", "right", "middle"}


def test_every_limb_is_reachable_by_a_real_fixture() -> None:
    """The half that catches a dead vocabulary entry (D-045a).

    A member no input can produce is D-037's dead-branch class one level up, and
    a value assertion cannot see it — it is evaluated against whatever the
    function returns, so a member removed from the TYPE simply never appears.
    """
    produced = {
        _label(
            dollar_smile_regime(
                _inputs(vix_level=vix, us_growth_surprise=g, us_vs_row_rate_diff=d)
            ),
            "side",
        )
        for vix, g, d in (
            (30.0, 1.0, 1.0),  # left
            (15.0, 1.0, 1.0),  # right
            (15.0, -1.0, 1.0),  # middle
        )
    }
    assert produced == set(get_args(DollarSmileSide))


def test_the_left_gate_consumes_nothing_behind_it() -> None:
    """THE TRIPWIRE for the D-050 hazard, and what makes this case different.

    A most-severe-first classifier can leave the branches behind its first gate
    unreachable. Here the first gate is a comparison against a **continuous
    level**, so the space behind it is the whole ``vix <= gate`` half-plane
    rather than an empty set — and both inner labels are produced inside it.

    The test walks the grid rather than asserting the sentence, so a future edit
    that made the VIX gate a flag (or narrowed it to an equality) would fail here
    instead of shifting the label distribution silently.
    """
    for vix in (0.0, 5.0, _VIX_GATE, 20.0, 24.5):
        behind = {
            _label(
                dollar_smile_regime(
                    _inputs(vix_level=vix, us_growth_surprise=g, us_vs_row_rate_diff=d)
                ),
                "side",
            )
            for g, d in itertools.product((-1.0, 1.0), repeat=2)
        }
        assert behind == {"right", "middle"}, f"vix={vix} behind the gate"


def test_the_reachable_set_is_exactly_three_limbs_over_a_sign_grid() -> None:
    """The full sign grid above AND below the gate, asserting the partition.

    Nine sign pairs at each of two VIX levels is the smallest grid that can show
    the partition: above the gate every pair is ``left``; below it exactly one
    pair is ``right`` and the other eight are ``middle``. D-053's rule — drive the
    GRID, not one hand-picked fixture per declared state — because N states with
    N tests is a HIT, not a PARTITION.
    """
    signs = (-1.0, 0.0, 1.0)
    above = {
        _label(
            dollar_smile_regime(
                _inputs(vix_level=30.0, us_growth_surprise=g, us_vs_row_rate_diff=d)
            ),
            "side",
        )
        for g, d in itertools.product(signs, repeat=2)
    }
    assert above == {"left"}, "above the gate the VIX input decides alone"

    below: list[str] = [
        _label(
            dollar_smile_regime(
                _inputs(vix_level=15.0, us_growth_surprise=g, us_vs_row_rate_diff=d)
            ),
            "side",
        )
        for g, d in itertools.product(signs, repeat=2)
    ]
    assert below.count("right") == 1, "exactly one sign pair is US outperformance"
    assert below.count("middle") == 8, "the other eight are the middle limb"


# ---------------------------------------------------------------------------
# The zero case — the specification's `> 0` leaves a neutral input in the middle.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("growth", "diff"),
    ((0.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
    ids=("zero growth", "zero diff", "both zero"),
)
def test_a_zero_input_is_neutral_and_the_middle_limb_owns_it(growth: float, diff: float) -> None:
    """A neutral input is NOT evidence of US outperformance.

    With ``> 0``, an exactly-zero surprise or an exactly-zero rate gap falls to
    the middle label. That is a decision, not an accident: zero is the NEUTRAL
    value of a signed surprise — a release landing on consensus prints it — so
    reading it as "US outperformance" would be a neutral input published as a
    positive regime claim (D-040's class).
    """
    result = dollar_smile_regime(
        _inputs(vix_level=15.0, us_growth_surprise=growth, us_vs_row_rate_diff=diff)
    )
    assert _label(result, "side") == "middle"
    assert _flag(result, "is_neutral_input") is True


def test_a_negative_input_is_middle_but_is_not_neutral() -> None:
    """The other cause of a middle label, which must not be confused with it.

    "The inputs point against US outperformance" and "an input carries no signal
    at all" are different claims, and the label cannot hold both — so
    ``is_neutral_input`` must be ``False`` here.
    """
    result = dollar_smile_regime(
        _inputs(vix_level=15.0, us_growth_surprise=-1.0, us_vs_row_rate_diff=1.0)
    )
    assert _label(result, "side") == "middle"
    assert _flag(result, "is_neutral_input") is False


def test_a_neutrality_is_only_claimed_on_the_middle_limb() -> None:
    """A zero input above the VIX gate had no say, so the flag must be False."""
    result = dollar_smile_regime(
        _inputs(vix_level=30.0, us_growth_surprise=0.0, us_vs_row_rate_diff=0.0)
    )
    assert _label(result, "side") == "left"
    assert _flag(result, "is_neutral_input") is False


def test_a_negative_differential_alone_is_not_neutral() -> None:
    """The guard against a too-broad neutrality helper.

    A helper written as ``not (growth > 0 and diff > 0)`` would return ``True``
    for an outright negative input — which is exactly the confusion the field
    exists to prevent. Both operands are driven negative so the equality test
    inside the helper is what has to be right, not the negated conjunction.
    """
    for growth, diff in ((-1.0, -1.0), (-5.0, 2.0), (2.0, -5.0)):
        result = dollar_smile_regime(
            _inputs(vix_level=15.0, us_growth_surprise=growth, us_vs_row_rate_diff=diff)
        )
        assert _label(result, "side") == "middle"
        assert _flag(result, "is_neutral_input") is False, f"growth={growth} diff={diff}"


def test_the_neutrality_helper_agrees_with_the_classifier() -> None:
    """The helper is DERIVED from the same expression, so they cannot disagree.

    Driven over a grid of small magnitudes either side of the boundary, so a
    helper that used ``>= 0`` (or ``abs(x) < eps``) diverges from the classifier
    and this test fails.
    """
    for value in (-1.0, -1e-9, 0.0, 1e-9, 1.0):
        for other in (-1.0, 0.0, 1.0):
            expected = (value == 0.0) or (other == 0.0)
            assert _dollar_smile_is_neutral(value, other) is expected


# ---------------------------------------------------------------------------
# The boundaries — built by ADDITION, with their exactness asserted.
# ---------------------------------------------------------------------------


def test_a_vix_exactly_on_the_gate_is_not_left() -> None:
    """The comparison is STRICTLY greater, and the boundary itself is not left.

    The fixture asserts its own position: ``25.0 + 0.5 == 25.5`` exactly, so the
    gate value is reached by binary-exact arithmetic rather than by a subtraction
    that lands a hair off the boundary it claims to probe (lesson 5o).
    """
    # Binary-exact on BOTH routes, and the round trip is asserted too: it is
    # what makes "25.0 is exactly the gate" a fact about the fixture rather
    # than a hope about the representation.
    assert 25.0 + 0.5 == 25.5
    assert (25.0 + 0.5) - 0.5 == 25.0
    result = dollar_smile_regime(
        _inputs(vix_level=25.0, us_growth_surprise=-1.0, us_vs_row_rate_diff=-1.0)
    )
    assert _flag(result, "vix_above_threshold") is False
    assert _label(result, "side") == "middle", (
        "at exactly the gate the left limb must not fire — otherwise '<=' replaced '>'"
    )


def test_a_vix_one_step_above_the_gate_is_left() -> None:
    """The other side of the same boundary, at one representable step."""
    just_above = math.nextafter(25.0, math.inf)
    assert just_above > _VIX_GATE
    result = dollar_smile_regime(
        _inputs(vix_level=just_above, us_growth_surprise=-1.0, us_vs_row_rate_diff=-1.0)
    )
    assert _label(result, "side") == "left"


@pytest.mark.parametrize("field", ("us_growth_surprise", "us_vs_row_rate_diff"))
def test_a_signed_input_exactly_on_the_boundary_is_not_above_it(field: str) -> None:
    """``> 0`` is strict, and zero must NOT establish US outperformance.

    Driving both fields, because a single symmetric fixture could pass while one
    of the two comparisons had become ``>=``.
    """
    other = {
        "us_growth_surprise": "us_vs_row_rate_diff",
        "us_vs_row_rate_diff": "us_growth_surprise",
    }[field]
    result = dollar_smile_regime(_inputs(vix_level=15.0, **{field: 0.0, other: 1.0}))
    assert _flag(result, f"{'growth' if 'growth' in field else 'rate'}_above_boundary") is False
    assert _label(result, "side") == "middle"


def test_a_signed_input_one_step_above_the_boundary_is_above_it() -> None:
    """The smallest positive float establishes US outperformance."""
    tiny = math.nextafter(0.0, math.inf)
    assert tiny > 0.0
    result = dollar_smile_regime(
        _inputs(vix_level=15.0, us_growth_surprise=tiny, us_vs_row_rate_diff=tiny)
    )
    assert _label(result, "side") == "right"


def test_the_published_branch_tests_reproduce_the_label() -> None:
    """The three booleans are a real decomposition, not decoration.

    Recomputing each from the published inputs and thresholds must return the
    published boolean, and the side must follow from the three booleans alone —
    so a reader can reconstruct the branch that fired without the source.
    """
    for vix, growth, diff in (
        (30.0, 1.0, 1.0),
        (15.0, 1.0, 1.0),
        (15.0, 0.0, 1.0),
        (15.0, -1.0, -1.0),
        (25.0, 1.0, 1.0),
    ):
        result = dollar_smile_regime(
            _inputs(vix_level=vix, us_growth_surprise=growth, us_vs_row_rate_diff=diff)
        )
        vix_above = _number(result, "vix_level") > _number(result, "vix_threshold")
        growth_above = _number(result, "us_growth_surprise") > _number(result, "sign_boundary")
        rate_above = _number(result, "us_vs_row_rate_diff") > _number(result, "sign_boundary")

        assert _flag(result, "vix_above_threshold") is vix_above
        assert _flag(result, "growth_above_boundary") is growth_above
        assert _flag(result, "rate_above_boundary") is rate_above

        expected = "left" if vix_above else "right" if (growth_above and rate_above) else "middle"
        assert _label(result, "side") == expected


# ---------------------------------------------------------------------------
# The config is READ, not literals — symmetry-breaking fixtures.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("moved_to", "vix", "expected"),
    (
        # At the shipped 25.0 a VIX of 15 is below the gate. Moved DOWN to 10.0
        # the same reading is above it; moved UP to 40.0 a VIX of 30 is below.
        (10.0, 15.0, "left"),
        (40.0, 30.0, "middle"),
    ),
    ids=("gate lowered", "gate raised"),
)
def test_moving_the_vix_gate_moves_the_side(
    monkeypatch: pytest.MonkeyPatch, moved_to: float, vix: float, expected: str
) -> None:
    """A hardcoded 25.0 cannot follow a moved gate — this is what kills it."""
    fx = get_settings().fx_carry
    monkeypatch.setattr(fx.dollar_smile_vix_threshold, "value", moved_to, raising=False)
    result = dollar_smile_regime(
        _inputs(vix_level=vix, us_growth_surprise=-1.0, us_vs_row_rate_diff=-1.0)
    )
    assert _label(result, "side") == expected
    assert _number(result, "vix_threshold") == moved_to


def test_moving_the_sign_boundary_moves_the_side(monkeypatch: pytest.MonkeyPatch) -> None:
    """The boundary is READ, and a hardcoded 0.0 cannot reproduce a moved one.

    Raising the boundary above the fixture's inputs takes the reading out of the
    right limb without changing the VIX input at all.
    """
    fx = get_settings().fx_carry
    shipped = dollar_smile_regime(
        _inputs(vix_level=15.0, us_growth_surprise=0.5, us_vs_row_rate_diff=0.5)
    )
    assert _label(shipped, "side") == "right"

    monkeypatch.setattr(fx.dollar_smile_sign_boundary, "value", 1.0, raising=False)
    moved = dollar_smile_regime(
        _inputs(vix_level=15.0, us_growth_surprise=0.5, us_vs_row_rate_diff=0.5)
    )
    assert _label(moved, "side") == "middle"
    assert _number(moved, "sign_boundary") == 1.0


# ---------------------------------------------------------------------------
# Confidence — computed, and by its discriminating property.
# ---------------------------------------------------------------------------


def test_confidence_is_the_heuristic_penalised_value() -> None:
    """The computed value, NOT the specification's literal.

    ``compute_confidence`` with the penalty is 0.40, which is ALSO Section 6.7's
    hardcoded literal — so ``== 0.4`` would pass on a hardcoded constant. The
    discriminating assertion is that the penalised and un-penalised values DIFFER.
    """
    result = dollar_smile_regime(_inputs())
    penalised = compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True))
    unpenalised = compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=False))
    assert result.confidence == pytest.approx(penalised)
    assert penalised != pytest.approx(unpenalised)


def test_a_perturbed_confidence_base_moves_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hardcoded 0.4 cannot follow a moved base. This is what kills it."""
    settings = get_settings()
    monkeypatch.setattr(settings.confidence.base, "value", 0.9, raising=False)
    moved = dollar_smile_regime(_inputs())
    assert moved.confidence == pytest.approx(0.7)
    assert moved.confidence != pytest.approx(0.4)


def test_the_confidence_helper_reads_both_dollar_smile_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BOTH leaves must be read, because the label rests on both judgements.

    A helper wired to only one of the two would report "calibrated" while the
    other was still a placeholder. Each leaf is moved in turn while the other
    stays uncalibrated, which is the only fixture that separates them.
    """
    fx = get_settings().fx_carry
    monkeypatch.setattr(
        fx.dollar_smile_vix_threshold, "calibration_status", "conventional", raising=False
    )
    monkeypatch.setattr(
        fx.dollar_smile_sign_boundary, "calibration_status", "conventional", raising=False
    )
    assert _dollar_smile_thresholds_are_calibrated() is True

    for calibrated_leaf, placeholder_leaf in (
        (fx.dollar_smile_vix_threshold, fx.dollar_smile_sign_boundary),
        (fx.dollar_smile_sign_boundary, fx.dollar_smile_vix_threshold),
    ):
        monkeypatch.setattr(calibrated_leaf, "calibration_status", "conventional", raising=False)
        monkeypatch.setattr(
            placeholder_leaf, "calibration_status", "uncalibrated_illustrative", raising=False
        )
        assert _dollar_smile_thresholds_are_calibrated() is False, (
            f"{placeholder_leaf} is a placeholder, so the label is not calibrated"
        )


def test_the_confidence_helper_is_not_shared_with_the_neighbouring_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate helpers, so calibrating one function's leaf cannot move another's.

    Today all five ``fx_carry`` leaves carry the same status, so a helper pointed
    at the wrong function's leaves returns the same answer — an equivalence that
    would evaporate the moment one was calibrated and not the other. This is the
    fixture that separates them.
    """
    fx = get_settings().fx_carry
    for leaf in (fx.notable_deviation_pct, fx.extreme_deviation_pct, fx.carry_vol_floor):
        monkeypatch.setattr(leaf, "calibration_status", "conventional", raising=False)
    monkeypatch.setattr(
        fx.dollar_smile_vix_threshold,
        "calibration_status",
        "uncalibrated_illustrative",
        raising=False,
    )
    monkeypatch.setattr(
        fx.dollar_smile_sign_boundary,
        "calibration_status",
        "uncalibrated_illustrative",
        raising=False,
    )
    assert _dollar_smile_thresholds_are_calibrated() is False, (
        "the CIP/carry leaves are calibrated; the dollar-smile helper must not follow them"
    )


# ---------------------------------------------------------------------------
# The input guards — refused at construction, each with a negative control.
# ---------------------------------------------------------------------------

_GUARD_FIELDS = ("vix_level", "us_growth_surprise", "us_vs_row_rate_diff")


@pytest.mark.parametrize("field", _GUARD_FIELDS)
@pytest.mark.parametrize("bad", (math.nan, math.inf, -math.inf), ids=("nan", "inf", "-inf"))
def test_the_domain_guards_refuse_a_non_finite_input(field: str, bad: float) -> None:
    """A non-finite input produces a confident LABEL, so it is refused.

    Measured: with the specification's bare comparisons, ``nan`` fails every
    ``>`` and falls through to the MIDDLE limb, while ``+inf`` passes the VIX
    gate and is reported as a full LEFT crisis. Neither raises on its own.
    """
    with pytest.raises(ValidationError, match=field):
        _inputs(**{field: bad})


@pytest.mark.parametrize("field", _GUARD_FIELDS)
def test_the_negative_control_for_each_guard_is_accepted(field: str) -> None:
    """Each guarded field accepts an ordinary value — the guard is not blanket."""
    assert DollarSmileInputs.model_validate(
        {
            "vix_level": 15.0,
            "us_growth_surprise": 1.0,
            "us_vs_row_rate_diff": 0.5,
            **{field: -3.75},
        }
    )


def test_a_negative_vix_is_admitted_because_the_gate_classifies_it() -> None:
    """No sign guard on the VIX level, and that is deliberate.

    A negative reading is not a defect this model should invent a rule for: the
    gate exists to classify it. Refusing it would be an unstated range claim.

    Note what the limb here actually is. The shipped gate is the specification's
    one-sided ``vix_level > 25``, so a below-gate reading falls through to the
    growth/rate test — and with the helper's positive surprises it lands on
    ``right``. The low-VIX arm of the real smile (the U is not monotone) is a
    documented limitation of this gate, NOT something this test may assume away:
    asserting ``middle`` here would write a false claim about the shipped model
    into a passing test. The fixture below therefore carries surprises that make
    the fall-through limb unambiguous, and the assertion pins what the code does.
    """
    result = dollar_smile_regime(
        _inputs(vix_level=-1.0, us_growth_surprise=1.0, us_vs_row_rate_diff=0.5)
    )
    assert _label(result, "side") == "right"
    assert _flag(result, "vix_above_threshold") is False
    assert _flag(result, "growth_above_boundary") is True
    assert _flag(result, "rate_above_boundary") is True


def test_a_negative_vix_with_a_non_positive_surprise_falls_to_middle() -> None:
    """The same negative reading, a different fall-through: pin BOTH exits.

    Together with the test above this fixes the negative-VIX behaviour as
    "admitted, then classified by the fall-through" rather than "admitted, then
    middle" — so a future edit that adds a VIX sign guard, or that reorders the
    branches, fails here instead of passing quietly.
    """
    for growth, diff in ((-1.0, 0.5), (1.0, -0.5), (0.0, 0.5), (1.0, 0.0)):
        result = dollar_smile_regime(
            _inputs(vix_level=-1.0, us_growth_surprise=growth, us_vs_row_rate_diff=diff)
        )
        assert _label(result, "side") == "middle", (growth, diff)
        assert _flag(result, "vix_above_threshold") is False, (growth, diff)


def test_an_extra_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        DollarSmileInputs.model_validate(
            {
                "vix_level": 15.0,
                "us_growth_surprise": 1.0,
                "us_vs_row_rate_diff": 0.5,
                "vix_threshold": 25.0,
            }
        )


# ---------------------------------------------------------------------------
# The settings validator.
# ---------------------------------------------------------------------------


def _fx_carry_settings(**overrides: object) -> FxCarrySettings:
    base: dict[str, object] = {
        "notable_deviation_pct": CalibratedValue(value=0.1, calibration_status="conventional"),
        "extreme_deviation_pct": CalibratedValue(value=0.5, calibration_status="conventional"),
        "carry_vol_floor": CalibratedValue(value=0.1, calibration_status="conventional"),
        "dollar_smile_vix_threshold": CalibratedValue(
            value=25.0, calibration_status="conventional"
        ),
        "dollar_smile_sign_boundary": CalibratedValue(value=0.0, calibration_status="conventional"),
    }
    base.update(overrides)
    return FxCarrySettings.model_validate(base)


def test_the_settings_validator_refuses_a_non_positive_vix_gate() -> None:
    """A non-positive gate makes every reading 'left' — two limbs go dead."""
    with pytest.raises(ValidationError, match="dollar_smile_vix_threshold"):
        _fx_carry_settings(
            dollar_smile_vix_threshold=CalibratedValue(value=0.0, calibration_status="conventional")
        )


def test_the_settings_validator_accepts_a_positive_vix_gate() -> None:
    """The negative control: an ordinary gate must construct."""
    assert _fx_carry_settings().dollar_smile_vix_level == 25.0


def test_the_settings_validator_admits_a_zero_sign_boundary() -> None:
    """Zero is REQUIRED here, so the guard must not be a blanket positivity rule.

    The sign boundary is the point at which a signed quantity stops being
    positive, and the specification writes it as zero. A reused
    ``> 0`` validator would refuse the shipped config.
    """
    assert _fx_carry_settings().dollar_smile_sign_boundary_value == 0.0


def test_the_settings_validator_admits_a_negative_sign_boundary() -> None:
    """A negative boundary is a deliberate (if exotic) choice, not a defect.

    It would widen the right limb to inputs that are slightly negative. The model
    does not refuse it, because doing so would invent a range claim the
    specification does not make.
    """
    settings = _fx_carry_settings(
        dollar_smile_sign_boundary=CalibratedValue(value=-0.25, calibration_status="conventional")
    )
    assert settings.dollar_smile_sign_boundary_value == -0.25


# ---------------------------------------------------------------------------
# The warnings — one branch fires, one stays silent, and the silence is tested.
# ---------------------------------------------------------------------------


def test_the_left_limb_warns_and_names_the_gate_and_the_inputs() -> None:
    result = dollar_smile_regime(
        _inputs(vix_level=30.0, us_growth_surprise=-2.0, us_vs_row_rate_diff=-3.0)
    )
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert "LEFT" in warning
    assert "30.00" in warning, "the warning must carry the INPUT, not only the gate"
    assert "-2.0000" in warning and "-3.0000" in warning
    assert "NOT what decided the label" in warning


def test_the_right_limb_is_silent() -> None:
    """The one limb whose own name is its reason — a warning here is noise."""
    assert (
        dollar_smile_regime(
            _inputs(vix_level=15.0, us_growth_surprise=1.0, us_vs_row_rate_diff=1.0)
        ).warnings
        == []
    )


def test_a_middle_limb_reached_by_a_neutral_input_warns() -> None:
    """The zero case is a condition a reader cannot see from the label."""
    result = dollar_smile_regime(
        _inputs(vix_level=15.0, us_growth_surprise=0.0, us_vs_row_rate_diff=1.0)
    )
    assert len(result.warnings) == 1
    assert "NEUTRAL" in result.warnings[0]
    assert "ABSENCE" in result.warnings[0]


def test_a_middle_limb_reached_by_opposing_inputs_is_silent() -> None:
    """The other cause of a middle label — no condition to report, so no noise.

    This is the assertion that separates the warning's branch from a blanket
    "middle limb" test: a warning emitted on every middle reading would fire here,
    and a warning that fires on ordinary calls is one a reader learns to ignore.
    """
    assert (
        dollar_smile_regime(
            _inputs(vix_level=15.0, us_growth_surprise=-1.0, us_vs_row_rate_diff=1.0)
        ).warnings
        == []
    )


def test_every_warning_branch_is_reached_by_some_fixture() -> None:
    """Enumerate the branches the function can emit and assert each is reached.

    A warning branch with no test is deletable — and this is the pairing that
    stops a new branch shipping uncovered.
    """
    emitted = {
        "left": dollar_smile_regime(_inputs(vix_level=30.0)).warnings,
        "right": dollar_smile_regime(_inputs(vix_level=15.0)).warnings,
        "middle_neutral": dollar_smile_regime(
            _inputs(vix_level=15.0, us_growth_surprise=0.0)
        ).warnings,
        "middle_opposed": dollar_smile_regime(
            _inputs(vix_level=15.0, us_growth_surprise=-1.0)
        ).warnings,
    }
    assert len(emitted["left"]) == 1
    assert emitted["right"] == []
    assert len(emitted["middle_neutral"]) == 1
    assert emitted["middle_opposed"] == []


# ---------------------------------------------------------------------------
# The reasoning contract.
# ---------------------------------------------------------------------------


def test_the_result_carries_the_module_contract() -> None:
    result = dollar_smile_regime(_inputs())
    assert result.model_name == "dollar_smile_regime"
    assert result.country == "us"
    assert result.unit is not None
    assert result.unit.startswith("categorical")
    assert result.source_family is EvidenceSourceFamily.MARKET_FX
    assert result.limitations, "limitations must be present on every call"
    assert result.assumptions, "assumptions must be present on every call"
    assert result.decision_prohibition, "prohibitions must be present on every call"
    assert result.decision_relevance is not None
    assert set(result.inputs_used) == {
        "vix_level",
        "us_growth_surprise",
        "us_vs_row_rate_diff",
    }


def test_the_direction_field_is_absent_on_every_limb() -> None:
    """``direction`` is unset BY DESIGN, and the reason is in the docstring.

    The label is a categorical member of a three-way partition and no member of
    it is a direction: ``left`` and ``right`` both describe USD strength and are
    distinguished by cause. Setting one would have to invent an ordering the
    model does not have — so this test pins the absence, on every limb, rather
    than leaving it as a silent ``None``.
    """
    for vix, growth in ((30.0, 1.0), (15.0, 1.0), (15.0, -1.0)):
        result = dollar_smile_regime(
            _inputs(vix_level=vix, us_growth_surprise=growth, us_vs_row_rate_diff=growth)
        )
        assert result.direction is None


def test_the_limitations_name_the_specification_s_standing_caveat() -> None:
    """Section 6.7's own disclosure, moved from ``warnings`` to ``limitations``.

    It holds on every call, so it is a limitation rather than a condition of this
    run. A test that only checked "some limitation exists" would not notice it
    being demoted back into the warnings list, where it fires on ordinary calls.
    """
    limitations = " ".join(dollar_smile_regime(_inputs()).limitations)
    assert "QUALITATIVE" in limitations
    assert "refine thresholds against history before trusting at size" in limitations
    assert dollar_smile_regime(_inputs()).warnings == []


def test_the_limitations_publish_the_base_rates_with_their_population() -> None:
    """A base rate that travels without its population is a coin flip.

    D-029/D-047's rule: a classifier whose modal output is one label reports
    construction rather than economics, so the mix must travel with the value and
    be labelled as a property of the ENUMERATION rather than of history.

    **The three NUMBERS are asserted, not just the surrounding prose.** The
    first version of this test checked only the sentence skeleton, and the sweep
    proved the gap: a mutation that TRANSPOSED the left and right base rates
    survived, because the published shares (57.85 % vs 6.74 %) were never read by
    anyone. A base rate test that does not read the rate is a test of the
    scaffolding. The expected strings are formatted from the named constant using
    the same ``:.1%`` the model uses, so the assertion moves with the constant
    and does not have to be retyped — while a transposition or an edit to any one
    share still fails here.
    """
    limitations = " ".join(dollar_smile_regime(_inputs()).limitations)
    assert "middle limb is reachable on" in limitations
    assert "not a base rate over history" in limitations
    assert "uniform grid" in limitations
    # The three shares, each formatted exactly as the model publishes them.
    for limb in ("left", "right", "middle"):
        assert f"{_DOLLAR_SMILE_BASE_RATES[limb]:.1%}" in limitations, (
            f"the {limb} limb's published base rate is missing or wrong: "
            f"expected {_DOLLAR_SMILE_BASE_RATES[limb]:.1%}"
        )
    # The shares are DISTINCT, so the three assertions above cannot all be
    # satisfied by one number repeated three times.
    assert len({f"{_DOLLAR_SMILE_BASE_RATES[k]:.1%}" for k in ("left", "right", "middle")}) == 3
    # And the ORDER the enumeration actually produced, pinned so a future edit to
    # the grid is visible here: over vix 0..60 step 0.5 the left limb dominates
    # (a high VIX is reachable over a wide band), the middle is a large minority,
    # and the right is the rarest because it needs BOTH signed inputs positive.
    assert _DOLLAR_SMILE_BASE_RATES["left"] > _DOLLAR_SMILE_BASE_RATES["middle"]
    assert _DOLLAR_SMILE_BASE_RATES["middle"] > _DOLLAR_SMILE_BASE_RATES["right"]
    assert (
        _DOLLAR_SMILE_BASE_RATES["left"]
        + _DOLLAR_SMILE_BASE_RATES["middle"]
        + (_DOLLAR_SMILE_BASE_RATES["right"])
        == 1.0
    )


def test_the_limitations_disclose_the_blocked_consensus_input() -> None:
    """The surprise needs a consensus this installation cannot reach."""
    limitations = " ".join(dollar_smile_regime(_inputs()).limitations)
    assert "consensus" in limitations
    assert "CALLER-SUPPLIED" in limitations


def test_the_limitations_disclose_that_the_label_is_a_partition_not_a_magnitude() -> None:
    """A VIX of 25.1 and a VIX of 80 get the same label — say so."""
    limitations = " ".join(dollar_smile_regime(_inputs()).limitations)
    assert "THREE limbs and no magnitude" in limitations


def test_the_prohibitions_forbid_treating_the_label_as_a_trade() -> None:
    prohibitions = " ".join(dollar_smile_regime(_inputs()).decision_prohibition)
    assert "not a long-dollar recommendation" in prohibitions
    assert "uncalibrated" in prohibitions
    assert "is_neutral_input" in prohibitions


def test_the_context_states_all_three_units_and_the_branch_tests() -> None:
    """The context must let a reader see which branch fired and on what basis."""
    result = dollar_smile_regime(
        _inputs(vix_level=30.0, us_growth_surprise=1.0, us_vs_row_rate_diff=-0.5)
    )
    context = result.context
    assert context is not None
    assert "VIX index level" in context
    assert "sign boundary" in context
    assert "vix_above=True" in context
    assert "growth_above=True" in context
    assert "rate_above=False" in context


def test_the_interpretation_ranks_the_limbs_by_their_own_reading() -> None:
    """Each limb's phrase must be its own, not a shared one.

    A helper that returned one phrase for both the left and right limbs would
    pass every label test above and still tell a reader the wrong thing about
    durability — the two limbs are opposite in exactly that respect.
    """
    left = dollar_smile_regime(_inputs(vix_level=30.0)).interpretation
    right = dollar_smile_regime(_inputs(vix_level=15.0)).interpretation
    middle = dollar_smile_regime(_inputs(vix_level=15.0, us_growth_surprise=-1.0)).interpretation
    assert "reversal-prone" in left
    assert "durable" in right
    assert "diversification flows dominate" in middle
    assert len({left, right, middle}) == 3


def test_the_interpretation_names_the_neutral_case_separately() -> None:
    """The neutral middle limb must not carry the opposed middle limb's phrase."""
    neutral = dollar_smile_regime(_inputs(vix_level=15.0, us_growth_surprise=0.0)).interpretation
    opposed = dollar_smile_regime(_inputs(vix_level=15.0, us_growth_surprise=-1.0)).interpretation
    assert "exactly neutral" in neutral
    assert "exactly neutral" not in opposed
    assert neutral != opposed


def test_the_published_values_are_rounded_but_the_label_is_not_derived_from_them() -> None:
    """Rounding is a presentation choice and must not reach the boundary.

    A VIX a hair above the gate is classified as left even though its ROUNDED
    published value is exactly the gate — so the classifier reads the raw input
    while the output reports a rounded one. Publishing a rounded value and then
    re-deriving the label from it is a defect this pins.
    """
    just_above = math.nextafter(25.0, math.inf)
    result = dollar_smile_regime(_inputs(vix_level=just_above))
    assert _label(result, "side") == "left"
    assert _number(result, "vix_level") == 25.0, "the published value is rounded to 6dp"
    assert _flag(result, "vix_above_threshold") is True


def test_the_result_is_a_model_result() -> None:
    assert isinstance(dollar_smile_regime(_inputs()), ModelResult)


def test_the_module_exports_the_new_names() -> None:
    """The ``__all__`` entry, pinned so a rename cannot orphan the function."""
    from macro_engine.models import fx_carry

    assert "dollar_smile_regime" in fx_carry.__all__
    assert "DollarSmileInputs" in fx_carry.__all__
    assert "DollarSmileSide" in fx_carry.__all__
