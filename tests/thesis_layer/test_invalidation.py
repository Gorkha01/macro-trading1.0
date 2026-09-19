"""Tests for ``derive_invalidation_conditions`` (Module 14, D-063).

Section 16.2's Q8, Section 20.15's sample, and the LTCM-lesson hard gate in
``TradeIdea.stop_or_invalidation``.

The four defects this file exists to pin
----------------------------------------
1. **The sample raises `TypeError` on its own sibling's output.** It writes
   ``if inflation.value < 0`` while ``inflation_convergence_classifier``
   publishes a **dict**. ``test_a_convergence_verdict_does_not_raise`` and
   ``test_every_unreadable_shape_is_reported_not_raised`` are the pins.
2. **``growth`` was declared and never read.**
   ``test_all_three_inputs_produce_a_condition`` drives all three and asserts
   each one appears.
3. **The sample's fallback sentence SATISFIES the gate it says is unmet** —
   measured: ``TradeIdea`` accepts it. ``test_nothing_identified_leaves_the_text_empty``
   and ``test_the_schema_gate_now_fires`` are the pins, and they are the reason
   the return type is not a bare ``str``.
4. **The model the sample names cannot express the condition it names** — the
   convergence verdict is direction-blind.
   ``test_the_agreement_falsifier_is_a_collapse_not_a_reversal`` is the pin.

Expected values are computed from the fixture's own leaves rather than read back
from the same config the code reads, per D-035.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult, ModelValue, utc_now
from macro_engine.thesis_layer.invalidation import (
    _TRIGGERS,
    InvalidationAssessment,
    InvalidationCondition,
    InvalidationTrigger,
    UnreadableInput,
    derive_invalidation_conditions,
)
from macro_engine.thesis_layer.schemas import TradeIdea

#: The real published shapes, taken from the shipped functions:
#:   output_gap                        -> round(gap_pct, 2)                       (float)
#:   inflation_breadth_score           -> round(average, 4)                       (float)
#:   labor_tightness_score             -> round(score, 1)                         (float)
#:   inflation_convergence_classifier  -> InflationConvergenceVerdict(...).model_dump()  (dict)
_GROWTH = -1.2
_INFLATION = -0.04
_LABOR = -2.5


def _result(name: str, value: ModelValue) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.6,
        interpretation=f"{name} = {value!r}",
        context="",
        inputs_used=[],
    )


def _assess(
    *,
    growth: ModelValue = _GROWTH,
    inflation: ModelValue = _INFLATION,
    labor: ModelValue = _LABOR,
) -> InvalidationAssessment:
    return derive_invalidation_conditions(
        _result("output_gap", growth),
        _result("inflation_breadth_score", inflation),
        _result("labor_tightness_score", labor),
    )


def _verdict(classification: str) -> dict[str, object]:
    """A dict shaped like ``InflationConvergenceVerdict.model_dump()``."""
    return {
        "classification": classification,
        "agreeing": 4,
        "opposing": 1,
        "flat": 1,
        "measures_used": 6,
        "frac_agreeing": 0.8,
        "independent_families": 3,
        "family_names": ["BLS_CPI", "BEA_PCE", "ATLANTA_FED"],
        "bands_available": ["HIGH"],
        "base_rates": {},
    }


# ---------------------------------------------------------------------------
# Defect 1 — the crash
# ---------------------------------------------------------------------------


def test_a_convergence_verdict_does_not_raise() -> None:
    """THE CRASH. Section 20.15 writes ``if inflation.value < 0``; the verdict
    is a dict, so the comparison is ``dict < int`` and raises.

    Executed against the shipped classifier's shape before this implementation
    existed: ``TypeError: '<' not supported between instances of 'dict' and
    'int'``. The builder happens to pass ``inflation_breadth_score`` (a float)
    today, so the crash is latent rather than immediate — and the sample's own
    docstring names the dict-valued model, which is what makes it reachable.
    """
    assessment = _assess(inflation=_verdict("HIGH"))
    assert assessment.identified is True
    assert not assessment.unreadable


@pytest.mark.parametrize(
    "value",
    [
        {"classification": "NOT_A_VERDICT"},  # dict, wrong vocabulary member
        {"no_classification": 1},  # dict, no verdict at all
        "CONVERGING_DOWN",  # a bare str
        "1.5",  # a NUMERIC-LOOKING str: floats cleanly, and must still be refused
        "-2.5",  # the same, on the other side of the crossing
        ["-1"],  # a list
        None,  # absent
        True,  # a bool
    ],
)
def test_every_unreadable_shape_is_reported_not_raised(value: ModelValue) -> None:
    """The contract is ``ModelResult``, whose ``value`` is a union. Every member
    the function cannot narrow must be REPORTED, never crashed on and never
    silently skipped — a skipped input reads as "no falsifier from this leg",
    which is a different claim from "this leg was not read"."""
    assessment = _assess(inflation=value)
    assert assessment.unreadable, f"{value!r} should have been reported"
    assert assessment.unreadable[0].model_name == "inflation_breadth_score"
    assert assessment.unreadable[0].value_type == type(value).__name__


def test_a_bool_is_not_a_signed_scalar() -> None:
    """``isinstance(True, int)`` is ``True``, so a bool-valued result would
    otherwise read as a score of ``1.0`` and produce a confident falsifier from
    a flag."""
    assessment = _assess(labor=True)
    assert [u.model_name for u in assessment.unreadable] == ["labor_tightness_score"]


# ---------------------------------------------------------------------------
# Defect 2 — the never-read parameter
# ---------------------------------------------------------------------------


def test_all_three_inputs_produce_a_condition() -> None:
    """``growth`` was declared and never read. Each input must contribute."""
    assessment = _assess()
    assert {c.model_name for c in assessment.conditions} == {
        "output_gap",
        "inflation_breadth_score",
        "labor_tightness_score",
    }


def test_the_growth_leg_changes_the_output() -> None:
    """Symmetry-breaking on the previously-dead parameter: flipping ONLY
    ``growth`` must change the text."""
    negative = _assess(growth=-1.2)
    positive = _assess(growth=+1.2)
    assert negative.text != positive.text
    assert "output_gap crosses back above" in negative.text
    assert "output_gap crosses back below" in positive.text


# ---------------------------------------------------------------------------
# Defect 3 — the fallback sentence satisfied the gate
# ---------------------------------------------------------------------------


def test_the_specifications_fallback_sentence_satisfies_the_gate() -> None:
    """The defect, pinned as a property of the SCHEMA rather than of this code.

    The gate is ``not self.stop_or_invalidation.strip()``. Section 20.15's
    fallback is non-empty, so a live trade whose stated falsifier is "no
    falsifier was found" passes. If this test ever fails, the schema changed and
    the reason for this function's return type changed with it.
    """
    fallback = (
        "No clear evidence-based invalidation condition identified — DO NOT "
        "promote this thesis past DRAFT (Module 14 Q8 requirement)"
    )
    idea = TradeIdea(
        instrument="UST 2yr note futures",
        direction="long",
        timeframe="6-12m",
        stop_or_invalidation=fallback,
    )
    assert idea.is_trade is True
    assert idea.stop_or_invalidation.strip()


def test_nothing_identified_leaves_the_text_empty() -> None:
    """The repair: ``text`` is EMPTY, so the gate above fires."""
    assessment = _assess(growth=0.0, inflation=0.0, labor=0.0)
    assert assessment.identified is False
    assert assessment.text == ""
    assert not assessment.conditions
    assert assessment.reason


def test_the_schema_gate_now_fires() -> None:
    """End to end: the assessment's empty text is refused by ``TradeIdea``."""
    assessment = _assess(growth=0.0, inflation=0.0, labor=0.0)
    with pytest.raises(ValidationError, match="non-empty stop_or_invalidation"):
        TradeIdea(
            instrument="UST 2yr note futures",
            direction="long",
            timeframe="6-12m",
            stop_or_invalidation=assessment.text,
        )


def test_an_identified_assessment_passes_the_gate() -> None:
    """The other half: a real falsifier is accepted."""
    assessment = _assess()
    idea = TradeIdea(
        instrument="UST 2yr note futures",
        direction="long",
        timeframe="6-12m",
        stop_or_invalidation=assessment.text,
    )
    assert idea.is_trade is True


def test_the_reason_names_the_unreadable_inputs() -> None:
    """A no-trade reason that does not say WHICH input failed is not actionable."""
    assessment = _assess(growth="n/a", inflation="n/a", labor="n/a")
    assert "3 of 3" in assessment.reason
    assert "output_gap" in assessment.reason


# ---------------------------------------------------------------------------
# Defect 4 — the direction-blind classifier
# ---------------------------------------------------------------------------


def test_the_agreement_falsifier_is_a_collapse_not_a_reversal() -> None:
    """The model the sample names cannot express "reacceleration".

    Its vocabulary is HIGH / MEDIUM / LOW / CONFLICTED and ``agreeing`` is the
    majority COUNT, not the majority SIDE — so a HIGH verdict is equally
    compatible with six measures agreeing down and with six agreeing up. The
    falsifier it CAN support is an agreement collapse, and that is what ships.
    """
    assessment = _assess(inflation=_verdict("HIGH"))
    condition = next(c for c in assessment.conditions if c.trigger == "agreement_collapses")
    assert condition.model_name == "inflation_breadth_score"
    assert condition.threshold is None, "an agreement trigger has a band, not a number"
    assert "agreement falls below HIGH" in condition.statement
    assert "reacceleration" not in condition.statement, (
        "the classifier is direction-blind; naming a direction would attribute "
        "to it a claim it cannot make"
    )


@pytest.mark.parametrize("classification", ["MEDIUM", "LOW", "CONFLICTED"])
def test_a_verdict_that_never_supported_the_thesis_is_neutral(classification: str) -> None:
    """Only a thesis resting on HIGH can have its agreement collapse. The other
    three verdicts are a PARTITION of the remaining vocabulary, not a
    fall-through."""
    assessment = _assess(inflation=_verdict(classification))
    assert not any(c.trigger == "agreement_collapses" for c in assessment.conditions)
    assert any(classification in note for note in assessment.neutral)


def test_every_convergence_verdict_member_is_handled() -> None:
    """Enumerate the classifier's own vocabulary, so a member added without this
    function learning about it fails here rather than falling through."""
    from macro_engine.models.inflation_convergence import CONVERGENCE_CLASSES

    for member in CONVERGENCE_CLASSES:
        assessment = _assess(inflation=_verdict(member))
        assert not assessment.unreadable, f"{member} should be readable"
        if member == "HIGH":
            assert any(c.trigger == "agreement_collapses" for c in assessment.conditions)
        else:
            assert not assessment.conditions or all(
                c.model_name != "inflation_breadth_score" for c in assessment.conditions
            )


# ---------------------------------------------------------------------------
# The sign partition
# ---------------------------------------------------------------------------


def test_both_signs_produce_a_condition() -> None:
    """The sample's two ``< 0`` tests can only describe a thesis leaning on
    loosening and disinflation, so a thesis leaning on tightening has NO
    falsifier at all. The repair is a two-way partition."""
    negative = _assess(growth=-1.0, inflation=-1.0, labor=-1.0)
    positive = _assess(growth=+1.0, inflation=+1.0, labor=+1.0)
    assert {c.trigger for c in negative.conditions} == {"crosses_back_positive"}
    assert {c.trigger for c in positive.conditions} == {"crosses_back_negative"}


def test_every_trigger_member_is_reachable() -> None:
    """A three-member vocabulary with three reachable states, driven as a grid."""
    seen: set[str] = set()
    for growth, inflation, labor in (
        (-1.0, -1.0, -1.0),
        (+1.0, +1.0, +1.0),
        (-1.0, _verdict("HIGH"), +1.0),
    ):
        seen |= {
            c.trigger for c in _assess(growth=growth, inflation=inflation, labor=labor).conditions
        }
    assert seen == set(_TRIGGERS)


def test_the_trigger_vocabulary_is_declared_and_agrees_with_the_mirror() -> None:
    """A ``Literal`` is not runtime-enforced, so a value assertion cannot see a
    member removed from the type (D-054)."""
    from typing import get_args

    assert set(get_args(InvalidationTrigger)) == set(_TRIGGERS)
    assert set(_TRIGGERS) == {
        "crosses_back_positive",
        "crosses_back_negative",
        "agreement_collapses",
    }


def test_a_signal_exactly_on_the_crossing_is_neutral() -> None:
    """A signal at the balance point has no direction to reverse FROM.
    Reporting one would be presenting absence of evidence as evidence — the same
    principle the classifier states for its own flat readings."""
    assessment = _assess(growth=0.0)
    assert not any(c.model_name == "output_gap" for c in assessment.conditions)
    assert any("exactly on the crossing" in note for note in assessment.neutral)
    assert assessment.identified is True, "the other two legs still carry a direction"


def test_the_crossing_boundary_is_exclusive() -> None:
    """The fixture sits EXACTLY on the configured crossing, so it can
    distinguish ``>`` from ``>=`` — the failure D-055 shipped."""
    crossing = get_settings().invalidation.crossing
    assert crossing == 0.0, "the fixture below assumes the shipped crossing"
    at_crossing = _assess(growth=crossing)
    assert not any(c.model_name == "output_gap" for c in at_crossing.conditions)
    just_above = _assess(growth=crossing + 1e-9)
    assert any(c.model_name == "output_gap" for c in just_above.conditions)


# ---------------------------------------------------------------------------
# The condition's own fields
# ---------------------------------------------------------------------------


def test_a_condition_names_its_model_value_and_threshold() -> None:
    """Section 20.15's prose conditions carry none of the three, so a reader
    cannot recompute them. The parenthetical "(claims fall, JOLTS openings
    stabilize)" is also NOT the same test as "the score reverses positive"."""
    assessment = _assess(labor=-2.5)
    condition = next(c for c in assessment.conditions if c.model_name == "labor_tightness_score")
    assert condition.observed_value == "-2.5"
    assert condition.threshold == 0.0
    assert "-2.5" in condition.statement
    assert "0" in condition.statement


def test_the_text_is_the_conditions_joined_by_or() -> None:
    """The text is derived from the conditions, not written separately — two
    renderings of one quantity would drift."""
    assessment = _assess()
    assert assessment.text == " OR ".join(c.statement for c in assessment.conditions)
    assert assessment.text.count(" OR ") == len(assessment.conditions) - 1


def test_the_assessment_is_frozen_and_forbids_extra_fields() -> None:
    assessment = _assess()
    with pytest.raises(ValidationError):
        InvalidationAssessment(  # type: ignore[call-arg]
            conditions=assessment.conditions,
            unreadable=assessment.unreadable,
            neutral=assessment.neutral,
            text=assessment.text,
            identified=assessment.identified,
            reason=assessment.reason,
            as_of=assessment.as_of,
            typo=1,
        )


@pytest.mark.parametrize(
    ("model_cls", "field", "value"),
    [
        (InvalidationAssessment, "identified", False),
        (InvalidationAssessment, "text", "softened"),
        (InvalidationCondition, "statement", "softened"),
        (UnreadableInput, "reason", "softened"),
    ],
)
def test_every_published_model_is_frozen(model_cls: type, field: str, value: object) -> None:
    """The assessment is the record of what would falsify a position. Mutating it
    after the fact is how a falsifier gets softened, and a softened falsifier is
    the same defect as an absent one — so ``frozen=True`` is load-bearing on all
    three models, not decoration."""
    if model_cls is InvalidationAssessment:
        instance: object = _assess()
    elif model_cls is InvalidationCondition:
        instance = _assess().conditions[0]
    else:
        instance = _assess(growth="n/a").unreadable[0]
    with pytest.raises(ValidationError):
        setattr(instance, field, value)


def test_the_assessment_carries_a_timestamp() -> None:
    """``utc_now()``, never a naive datetime."""
    assessment = _assess()
    assert assessment.as_of.tzinfo is not None


# ---------------------------------------------------------------------------
# The config accessors, perturbed
# ---------------------------------------------------------------------------


def test_the_crossing_reads_the_config_leaf() -> None:
    """Perturbed to a value no literal could produce, so a hardcoded ``0``
    cannot pass (D-050)."""
    leaf = get_settings().invalidation.zero_crossing_threshold
    original = leaf.value
    object.__setattr__(leaf, "value", 5.0)
    try:
        assessment = _assess(growth=2.0)
        condition = next(c for c in assessment.conditions if c.model_name == "output_gap")
        assert condition.threshold == 5.0
        assert "5" in condition.statement
        assert condition.trigger == "crosses_back_positive", (
            "2.0 is below a crossing of 5.0, so the reversal is upward"
        )
    finally:
        object.__setattr__(leaf, "value", original)


def test_the_supporting_agreement_class_reads_the_config_leaf() -> None:
    leaf = get_settings().invalidation.supporting_agreement_class
    original = leaf.value
    object.__setattr__(leaf, "value", "MEDIUM")
    try:
        # MEDIUM now supports a thesis, HIGH no longer does.
        medium = _assess(inflation=_verdict("MEDIUM"))
        assert any(c.trigger == "agreement_collapses" for c in medium.conditions)
        high = _assess(inflation=_verdict("HIGH"))
        assert not any(c.trigger == "agreement_collapses" for c in high.conditions)
    finally:
        object.__setattr__(leaf, "value", original)
