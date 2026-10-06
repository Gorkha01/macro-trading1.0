"""``thesis_layer/invalidation.py`` — the four sample defects, and the vocabulary parity.

The module's docstring lists four measured defects in Section 20.15's sample.
Before 2026-10-06 **none of them had a test** and there was no test file for this
module at all, so ``_TRIGGERS`` — declared "so a test can assert the declared
vocabulary and the producible one agree (D-045a's two halves)" — was read by
nothing. That parity test is here (``test_the_declared_trigger_vocabulary_is_...``),
and so is one test per defect.

Every defect test FAILS against the specification's sample, which is the point:
the sample's behaviour is what is being replaced.

The sample (AGENTS.md, Section 20.15), for reference::

    if labor.value < 0:        # TypeError on a dict-valued result
        conditions.append("labor_tightness_score reverses positive (...)")
    if inflation.value < 0:    # attributes "reacceleration" to a direction-blind model
        conditions.append("inflation_convergence_classifier shows broad-based reacceleration ...")
    return " OR ".join(conditions) if conditions else "No clear evidence-based ..."

Sign convention: ``crossing`` is the models' own balance point (0.0, from
``settings.invalidation.crossing``), so a POSITIVE signal falsifies by crossing
back **negative** and a NEGATIVE one by crossing back **positive**.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from macro_engine.models.contracts import ModelResult
from macro_engine.thesis_layer import invalidation
from macro_engine.thesis_layer.invalidation import (
    _TRIGGERS,
    InvalidationAssessment,
    derive_invalidation_conditions,
)
from macro_engine.thesis_layer.schemas import TradeIdea

_AS_OF = datetime(2026, 10, 6, tzinfo=UTC)
_LIVE_INSTRUMENT = "UST cash (2yr, 5yr, 10yr, 30yr)"

#: ``ModelResult.value``'s declared union.
_ValueT = float | int | str | bool | dict[str, Any] | list[Any] | None


def _result(name: str, value: _ValueT) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=_AS_OF,
        value=value,
        confidence=0.5,
        interpretation="a reading",
        context="test",
        inputs_used=["x"],
    )


def _derive(growth: _ValueT, inflation: _ValueT, labor: _ValueT) -> InvalidationAssessment:
    return derive_invalidation_conditions(
        _result("output_gap", growth),
        _result("inflation_breadth_score", inflation),
        _result("labor_tightness_score", labor),
    )


def _verdict(classification: str) -> dict[str, Any]:
    """The shape ``inflation_convergence_classifier`` publishes (a model_dump)."""
    return {"classification": classification, "agreeing": 6, "disagreeing": 0}


# ---------------------------------------------------------------------------
# defect 1 — the sample raises TypeError on its own sibling's output
# ---------------------------------------------------------------------------


def test_a_dict_valued_input_does_not_raise() -> None:
    """``dict < int`` is a TypeError; the sample's ``if inflation.value < 0`` hits it."""
    assessment = _derive(-1.0, _verdict("HIGH"), -1.0)  # must not raise
    assert isinstance(assessment, InvalidationAssessment)


def test_a_convergence_verdict_produces_an_agreement_condition() -> None:
    """The classifier's verdict IS readable, so it gets a falsifier of its own form."""
    assessment = _derive(-1.0, _verdict("HIGH"), -1.0)
    by_model = {c.model_name: c for c in assessment.conditions}
    assert "inflation_breadth_score" in by_model
    condition = by_model["inflation_breadth_score"]
    assert condition.trigger == "agreement_collapses"
    assert condition.threshold is None
    assert condition.observed_value == "HIGH"


# ---------------------------------------------------------------------------
# defect 2 — growth was declared and never read
# ---------------------------------------------------------------------------


def test_growth_is_read_symmetrically_with_the_other_two() -> None:
    """The sample read only ``labor`` and ``inflation``; all three are read here."""
    assessment = _derive(-1.0, -1.0, -1.0)
    assert [c.model_name for c in assessment.conditions] == [
        "output_gap",
        "inflation_breadth_score",
        "labor_tightness_score",
    ]


def test_each_signed_input_produces_its_own_condition() -> None:
    """Three parameters, three conditions — not two."""
    assert len(_derive(-1.0, -2.0, -3.0).conditions) == 3


# ---------------------------------------------------------------------------
# defect 3 — the fallback sentence SATISFIED the gate it said was unmet
# ---------------------------------------------------------------------------


def test_the_no_falsifier_fallback_is_not_published_as_a_condition() -> None:
    """The sample's sentence passed ``TradeIdea``'s non-empty check.

    Measured 2026-10-06: ``TradeIdea(instrument=…, direction="long",
    stop_or_invalidation="No clear evidence-based invalidation condition
    identified — DO NOT promote this thesis past DRAFT …")`` is ACCEPTED — a live
    trade whose stated falsifier is "no falsifier was found". Here ``text`` is
    the EMPTY STRING instead, so the schema's own gate fires.
    """
    assessment = _derive(0.0, 0.0, 0.0)  # all three sit on the crossing
    assert assessment.identified is False
    assert assessment.conditions == ()
    assert assessment.text == ""
    assert assessment.reason  # a reason for no_trade_thesis()
    with pytest.raises(ValidationError, match="stop_or_invalidation"):
        TradeIdea(
            instrument=_LIVE_INSTRUMENT,
            direction="long",
            stop_or_invalidation=assessment.text,
        )


def test_the_sample_fallback_sentence_really_would_have_passed() -> None:
    """Non-vacuity for the test above: the OLD text does satisfy the gate."""
    old_fallback = (
        "No clear evidence-based invalidation condition identified — DO NOT "
        "promote this thesis past DRAFT (Module 14 Q8 requirement)"
    )
    idea = TradeIdea(
        instrument=_LIVE_INSTRUMENT, direction="long", stop_or_invalidation=old_fallback
    )
    assert idea.is_trade is True


# ---------------------------------------------------------------------------
# defect 4 — the named model cannot express the condition named for it
# ---------------------------------------------------------------------------


def test_the_agreement_falsifier_is_a_collapse_not_a_reacceleration() -> None:
    """The classifier is direction-blind, so "reacceleration" is not computable."""
    assessment = _derive(-1.0, _verdict("HIGH"), -1.0)
    statements = " ".join(c.statement for c in assessment.conditions)
    assert "reacceleration" not in statements.lower()
    assert "agreement falls below HIGH" in statements


def test_a_verdict_that_never_supported_the_thesis_is_neutral() -> None:
    """Its collapse is not a falsifier for a thesis that never rested on it."""
    assessment = _derive(-1.0, _verdict("MEDIUM"), -1.0)
    assert "inflation_breadth_score" not in {c.model_name for c in assessment.conditions}
    assert any("never resting on broad agreement" in n for n in assessment.neutral)


# ---------------------------------------------------------------------------
# the sign axis, the crossing, and the unreadable shapes
# ---------------------------------------------------------------------------


def test_both_signs_produce_a_condition() -> None:
    """The sample's two ``< 0`` tests could only ever describe one lean."""
    positive = _derive(1.0, 1.0, 1.0)
    negative = _derive(-1.0, -1.0, -1.0)
    assert {c.trigger for c in positive.conditions} == {"crosses_back_negative"}
    assert {c.trigger for c in negative.conditions} == {"crosses_back_positive"}
    assert "crosses back below 0" in positive.conditions[0].statement
    assert "crosses back above 0" in negative.conditions[0].statement


def test_a_signal_exactly_on_the_crossing_is_neutral() -> None:
    """Absence of direction is not evidence for either side."""
    assessment = _derive(0.0, -1.0, -1.0)
    assert "output_gap" not in {c.model_name for c in assessment.conditions}
    assert any("sits exactly on the crossing" in n for n in assessment.neutral)
    assert assessment.unreadable == ()  # zero IS readable, just not directional


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, False])
def test_a_non_finite_or_boolean_value_is_unreadable_not_a_falsifier(bad: _ValueT) -> None:
    """D-078: ``nan`` read as neutral ("on the crossing") and ``inf`` emitted a
    confident ``crosses_back_negative`` — both from a value that was never read."""
    assessment = _derive(bad, -1.0, -1.0)
    assert "output_gap" not in {c.model_name for c in assessment.conditions}
    assert [u.model_name for u in assessment.unreadable] == ["output_gap"]


@pytest.mark.parametrize("bad", ["1.5", None, [1.0]])
def test_an_unreadable_shape_is_reported_not_skipped(bad: _ValueT) -> None:
    assessment = _derive(-1.0, bad, -1.0)
    assert [u.model_name for u in assessment.unreadable] == ["inflation_breadth_score"]
    assert assessment.unreadable[0].value_type == type(bad).__name__


def test_an_unreadable_verdict_dict_is_reported() -> None:
    """A dict the classifier does not publish is unreadable, not silently agreement."""
    assessment = _derive(-1.0, {"classification": "SOMETHING_NEW"}, -1.0)
    assert [u.model_name for u in assessment.unreadable] == ["inflation_breadth_score"]


# ---------------------------------------------------------------------------
# the assessment's own contract
# ---------------------------------------------------------------------------


def test_the_text_is_the_or_joined_statements_and_identified_tracks_them() -> None:
    assessment = _derive(-1.0, -1.0, -1.0)
    assert assessment.text == " OR ".join(c.statement for c in assessment.conditions)
    assert assessment.identified is True
    assert assessment.reason == ""


def test_every_input_is_accounted_for_exactly_once() -> None:
    """A reader counting the three inputs must be able to reconcile them.

    Each input lands in exactly one of the three buckets — a condition, a
    ``neutral`` message, or an ``unreadable`` entry — so the bucket sizes sum to
    the input count. (``neutral`` holds MESSAGES, one per neutral input, not
    model names.)
    """
    assessment = _derive(-1.0, {"a": 1}, 0.0)
    assert (len(assessment.conditions) + len(assessment.neutral) + len(assessment.unreadable)) == 3
    assert len(assessment.conditions) == 1
    assert len(assessment.neutral) == 1
    assert len(assessment.unreadable) == 1


# ---------------------------------------------------------------------------
# D-045a — the declared trigger vocabulary and the producible one
# ---------------------------------------------------------------------------
# This is the test `_TRIGGERS` was declared for and did not have.


def test_the_declared_trigger_vocabulary_is_the_producible_one() -> None:
    """Every declared trigger must be producible, and nothing undeclared produced.

    The declared half is ``InvalidationTrigger`` (a ``Literal``, so not iterable
    at runtime) mirrored by ``_TRIGGERS``; the producible half is collected by
    exercising the function. A trigger added to the Literal but never emitted, or
    emitted but not declared, fails here — which is D-045a's "declared, consumed,
    unreachable" class caught from both sides.
    """
    producible = {c.trigger for c in _derive(1.0, 1.0, 1.0).conditions}
    producible |= {c.trigger for c in _derive(-1.0, -1.0, -1.0).conditions}
    producible |= {c.trigger for c in _derive(-1.0, _verdict("HIGH"), -1.0).conditions}

    assert producible == set(_TRIGGERS), (
        f"declared {sorted(_TRIGGERS)} but producible {sorted(producible)} — "
        f"the vocabulary and the code have drifted (D-045a)."
    )
    assert len(_TRIGGERS) == 3


# ---------------------------------------------------------------------------
# the prose claims corrected in the 2026-10-06 review
# ---------------------------------------------------------------------------


def _invalidation_source() -> str:
    return Path(inspect.getfile(invalidation)).read_text(encoding="utf-8")


def test_the_drift_note_describes_the_present_not_the_past() -> None:
    """(F-INV-001) The note said the ``isfinite`` guard 'was **not** mirrored here'.

    MEASURED 2026-10-06: it IS here (``_signed_scalar(float('inf'))`` is None),
    and git shows it was added to this file in ``0d0f97f`` — later than the
    signals twin, which is the drift the note predicts. The stale wording would
    send a reader looking for a guard that is already present.
    """
    source = _invalidation_source()
    # The OLD sentence's distinctive tail — the correction is allowed to quote
    # the phrase itself (it does, to record what changed), so the guard targets
    # the claim that made it misleading rather than the quoted words.
    assert "mirrored here, which is precisely the drift the note predicts" not in source
    assert "both copies now carry it" in source
    # ...and the structural truth the corrected note claims:
    assert invalidation._signed_scalar(float("inf")) is None
    assert invalidation._signed_scalar(float("nan")) is None


def test_the_finiteness_note_does_not_claim_a_guard_that_is_not_there() -> None:
    """(F-INV-003) ``_condition_for_scalar`` has no guard of its own.

    It said 'The guard is stated because …', which reads as though one were
    implemented. Finiteness is an ASSUMPTION the single caller maintains, and the
    note now says so.
    """
    source = _invalidation_source()
    assert "The guard is stated because" not in source
    assert "no guard of its own" in source
