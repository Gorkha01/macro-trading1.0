"""``thesis_layer/signals.py`` — the five sample defects, each pinned.

The module's whole docstring is a list of five ways Section 16.4's sample got
this wrong. Before 2026-10-06 **none of them had a test**: ``tests/thesis_layer/``
held only ``test_warnings_citations.py``, so the module's entire reason for
existing — that an unreadable value must not be published as a contradiction —
was asserted in prose and nowhere else.

Each test below names the defect it pins, and every one of them FAILS against
the specification's sample (that is the point: the sample's behaviour is the
thing being replaced).

Sign convention, stated once because every expectation depends on it:
``raw_gap = model_implied - market_implied``, so a NEGATIVE gap means the model
sits BELOW the market (``direction == "model_below_market"``, ``gap_sign == -1``)
and a NEGATIVE model value is the one that CONFIRMS it. The default gap here is
``-1.4``, so "confirms" fixtures are negative and "contradicts" fixtures positive.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from macro_engine.models.contracts import ModelResult
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer import signals
from macro_engine.thesis_layer.schemas import ConfirmationSignal
from macro_engine.thesis_layer.signals import (
    ConfirmationSignalAssessment,
    UnreadableConfirmationInput,
    build_confirmation_signals,
)

#: ``ModelResult.value``'s declared union — the fixtures have to stay inside it,
#: or the "unreadable" cases would be testing a shape the type cannot hold.
_ValueT = float | int | str | bool | dict[str, Any] | list[Any] | None

_AS_OF = datetime(2026, 10, 6, tzinfo=UTC)
#: A model-below-market gap, so NEGATIVE values confirm it.
_GAP = -1.4


def _result(
    name: str,
    value: _ValueT,
    *,
    interpretation: str = "a reading",
    warnings: list[str] | None = None,
    family: EvidenceSourceFamily | None = None,
) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=_AS_OF,
        value=value,
        confidence=0.5,
        interpretation=interpretation,
        context="test",
        inputs_used=["x"],
        warnings=warnings or [],
        source_family=family,
    )


def _gap(raw_gap: float) -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=2.0,
        market_implied_value=2.0 - raw_gap,
        raw_gap=raw_gap,
        dispersion=0.1,
        is_meaningful=abs(raw_gap) > 0.1,
        interpretation="test gap",
    )


def _build(
    growth: _ValueT,
    inflation: _ValueT,
    labor: _ValueT,
    raw_gap: float = _GAP,
) -> ConfirmationSignalAssessment:
    """Build an assessment with the three canonical model_names."""
    return build_confirmation_signals(
        _result("output_gap", growth),
        _result("inflation_breadth_score", inflation),
        _result("labor_tightness_score", labor),
        _gap(raw_gap),
    )


# ---------------------------------------------------------------------------
# defect 1 — an unreadable value must not be published as a CONTRADICTION
# ---------------------------------------------------------------------------


def test_an_unreadable_value_is_neutral_and_reported_not_contradicting() -> None:
    """The sample's bare ``else`` published ``contradicts`` for a dict.

    A ``{"classification": "HIGH"}`` inflation result carries no direction at
    all, so reporting it as opposing the thesis is the D-056 false-confidence
    failure: the thesis is told its evidence disagrees when the evidence was
    never read. (The two readable legs here CONFIRM, so ``contradicts`` would
    have been a claim about a value that carried nothing.)
    """
    assessment = _build(-1.0, {"classification": "HIGH"}, -1.0)
    by_name = {s.source_model: s for s in assessment.signals}
    assert by_name["inflation_breadth_score"].direction == "neutral"
    assert assessment.agreeing == 2
    assert assessment.disagreeing == 0
    assert assessment.neutral == 1
    assert [u.source_model for u in assessment.unreadable] == ["inflation_breadth_score"]
    assert assessment.unreadable[0].value_type == "dict"


def test_an_unreadable_entry_says_so_in_its_own_detail() -> None:
    """The caveat must be visible on the entry, not only in a side list."""
    assessment = _build(-1.0, {"classification": "HIGH"}, -1.0)
    detail = next(s.detail for s in assessment.signals if s.direction == "neutral")
    assert "[unreadable:" in detail
    assert "reported neutral, not as a contradiction" in detail


# ---------------------------------------------------------------------------
# defect 2 — a flat reading is a balance point, not a contradiction
# ---------------------------------------------------------------------------


def test_a_zero_reading_is_neutral_not_contradicting() -> None:
    """The sample's two ``> 0``/``< 0`` conjunctions both fail on exactly 0."""
    assessment = _build(0.0, -1.0, -1.0)
    by_name = {s.source_model: s for s in assessment.signals}
    assert by_name["output_gap"].direction == "neutral"
    assert assessment.neutral == 1
    assert "balance point" in by_name["output_gap"].detail
    assert assessment.unreadable == ()  # zero IS readable, just not directional


# ---------------------------------------------------------------------------
# defect 3 — the label is the result's own model_name
# ---------------------------------------------------------------------------


def test_the_label_comes_from_the_result_not_the_slot() -> None:
    """A ``source_model`` a reader cannot trace is worse than a missing one."""
    assessment = _build(-1.0, -1.0, -1.0)
    assert [s.source_model for s in assessment.signals] == [
        "output_gap",
        "inflation_breadth_score",
        "labor_tightness_score",
    ]


def test_the_slot_name_is_only_a_fallback_for_an_empty_model_name() -> None:
    assessment = build_confirmation_signals(
        _result("", -1.0),
        _result("", -1.0),
        _result("", -1.0),
        _gap(_GAP),
    )
    assert [s.source_model for s in assessment.signals] == ["growth", "inflation", "labor"]


# ---------------------------------------------------------------------------
# defect 4 — source_family is carried through, not dropped
# ---------------------------------------------------------------------------


def test_source_family_is_carried_through_from_the_model_result() -> None:
    assessment = build_confirmation_signals(
        _result("a", -1.0, family=EvidenceSourceFamily.MARKET_FX),
        _result("b", -1.0, family=None),
        _result("c", -1.0, family=EvidenceSourceFamily.BLS_JOLTS),
        _gap(_GAP),
    )
    assert [s.source_family for s in assessment.signals] == [
        EvidenceSourceFamily.MARKET_FX,
        None,
        EvidenceSourceFamily.BLS_JOLTS,
    ]


# ---------------------------------------------------------------------------
# defect 5 — a hedging model is visible as a field, not a phrase
# ---------------------------------------------------------------------------


def test_a_warning_count_is_appended_when_the_model_corroborates() -> None:
    """The signal says ``confirms`` while its own model reports caveats — the
    count is what stops a reader from taking the corroboration at face value."""
    assessment = build_confirmation_signals(
        _result("output_gap", -1.0, warnings=["sub-measures disagree"]),
        _result("inflation_breadth_score", -1.0),
        _result("labor_tightness_score", -1.0),
        _gap(_GAP),
    )
    first = assessment.signals[0]
    assert first.direction == "confirms"
    assert "model_warnings: 1" in first.detail


def test_a_neutral_entry_does_not_carry_the_warning_marker() -> None:
    """The marker flags a CORROBORATION that hedges; a neutral entry has no
    corroboration to undercut, so the count is not appended."""
    assessment = build_confirmation_signals(
        _result("output_gap", 0.0, warnings=["hedged"]),
        _result("inflation_breadth_score", -1.0),
        _result("labor_tightness_score", -1.0),
        _gap(_GAP),
    )
    assert assessment.signals[0].direction == "neutral"
    assert "model_warnings" not in assessment.signals[0].detail


# ---------------------------------------------------------------------------
# the non-finite / bool cases (D-078), and the zero-gap total case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, False])
def test_a_non_finite_or_boolean_value_is_unreadable_not_directional(bad: _ValueT) -> None:
    """``nan`` would publish ``contradicts`` and ``inf`` ``confirms`` through the
    type test; a bool would publish a direction from a flag (D-078)."""
    assessment = _build(bad, -1.0, -1.0)
    assert assessment.signals[0].direction == "neutral"
    assert [u.source_model for u in assessment.unreadable] == ["output_gap"]
    assert assessment.disagreeing == 0
    assert assessment.agreeing == 2


def test_a_zero_gap_makes_every_readable_signal_neutral() -> None:
    """No reference direction exists, so nothing can confirm or contradict it."""
    assessment = _build(-1.0, 1.0, -1.0, raw_gap=0.0)
    assert {s.direction for s in assessment.signals} == {"neutral"}
    assert assessment.agreeing == 0
    assert assessment.disagreeing == 0
    assert assessment.neutral == 3
    assert "no direction to confirm" in assessment.signals[0].detail


def test_one_signal_per_input_in_input_order() -> None:
    """Silently dropping an input from a list a reader may count is D-054."""
    assessment = _build(-1.0, {"a": 1}, -1.0)
    assert len(assessment.signals) == 3
    assert len(assessment.unreadable) == 1


def test_the_census_partitions_the_list_and_unreadable_entries_are_neutral() -> None:
    """The assessment's own field description claims two relationships.

    ``unreadable`` says "Each has a matching entry in ``signals`` reading
    ``neutral``", and the three counts are meant to partition the list. Neither
    is VALIDATED — the model is a frozen report built in exactly one place — so
    both are pinned here rather than left to the prose.
    """
    assessment = _build(-1.0, {"a": 1}, float("nan"))
    assert assessment.agreeing + assessment.disagreeing + assessment.neutral == len(
        assessment.signals
    )
    assert len(assessment.unreadable) == 2
    neutral = [s for s in assessment.signals if s.direction == "neutral"]
    assert {u.source_model for u in assessment.unreadable} == {s.source_model for s in neutral}


# ---------------------------------------------------------------------------
# the prose claims corrected in the 2026-10-06 review
# ---------------------------------------------------------------------------
# Each is a text guard rather than a behavioural test, because the CODE was
# already right in every case — what was wrong was what the module SAID about
# it. The guards fail if the false statement is re-introduced.


def _signals_source() -> str:
    return Path(inspect.getfile(signals)).read_text(encoding="utf-8")


def test_the_non_finite_note_matches_the_guard() -> None:
    """(F-SIG-001) The docstring said ``inf`` was 'admitted'; the guard EXCLUDES it.

    ``_signed_scalar`` gates on ``isfinite``, so ``inf`` and ``-inf`` return
    ``None`` exactly as ``nan`` does — and the reason the note gives
    (``inf > 0`` is ``True``, so it would publish ``confirms``) is a reason to
    exclude, not to admit.
    """
    source = _signals_source()
    assert "``inf`` is admitted" not in source
    assert "``inf`` is excluded" in source


def test_no_model_is_described_as_carrying_a_readable_field() -> None:
    """(F-SIG-002) No model here, or in ``schemas.py``, has a ``readable`` field.

    The unreadable detail lives in ``UnreadableConfirmationInput``, which the
    ASSESSMENT carries — the signal itself carries it as a ``detail`` suffix.
    The two exact phrasings that asserted otherwise are what this pins; the
    correction is allowed to NAME the old claim (it does, to record it), so a
    blanket ``"readable" not in source`` would be wrong.
    """
    source = _signals_source()
    assert "and the entry carries" not in source, "the docstring table's false row is back"
    assert "(with ``readable=False``)" not in source, (
        "UnreadableConfirmationInput's false parenthetical is back"
    )
    assert not hasattr(ConfirmationSignal, "readable")
    assert "readable" not in UnreadableConfirmationInput.model_fields


def test_the_warning_marker_note_states_its_condition() -> None:
    """(F-SIG-004) The count is appended only when the direction is NOT neutral."""
    source = _signals_source()
    assert "When the model warned **and the direction is not neutral**" in source


def test_the_family_note_does_not_claim_a_consumer_that_does_not_exist() -> None:
    """(F-SIG-005) Nothing counts families from this list (see F-TSC-006)."""
    source = _signals_source()
    assert "remains visible to ``count_independent_families``" not in source
    assert "nothing in ``src/`` currently COUNTS families" in source
