"""Tests for ``build_confirmation_signals`` (§16.4 Q7, D-066).

The defects this file exists to pin
-----------------------------------
1. **An unreadable value is published as an active CONTRADICTION.** §16.4's
   single ``if``/``else`` sends a non-numeric value (a ``dict``, which
   ``four_pillar_scorecard`` and ``inflation_convergence_classifier`` both
   publish) to the ``else`` and labels it ``"contradicts"`` — a directional
   claim from data carrying none. ``test_an_unreadable_value_is_neutral_not_a_contradiction``
   is the pin, and D-056 (false confidence) is the reason it matters.
2. **A flat (exactly zero) value is published as an active CONTRADICTION.**
   ``test_a_zero_value_is_neutral_not_a_contradiction``.
3. **The three labels the sample uses are not the three models the caller
   passes (O-69).** Six distinct labels across §16.4, §7.1 and §16.2, only one
   common. ``test_the_label_is_the_result_own_model_name`` and
   ``test_the_spec_names_six_labels_for_three_slots``.
4. **``source_family`` is never populated.** ``test_the_family_is_carried_through``
   and ``test_an_untagged_result_stays_untagged``.
5. **``detail`` is the raw interpretation, so a signal can undercut itself.**
   ``test_a_corroborating_signal_reports_its_models_warning_count``.
6. **A zero gap makes every comparison meaningless.** The sample would still
   publish ``confirms`` for any nonzero signal, inventing the reference.
   ``test_a_zero_gap_makes_every_signal_neutral``.
7. **A NON-FINITE value reaches the classifier through the type test it was
   never meant to pass (D-078).** Defect 1's fix declines to read a value that
   is not an ``int``/``float``; ``nan`` **is** a ``float``, so it is read, and
   ``_direction_for`` publishes ``"contradicts"`` — the exact outcome defect 1
   prevents, arriving through the gate defect 1's fix sits behind.
   ``test_a_non_finite_value_is_unreadable_not_a_contradiction`` is the pin.

Plus the structural pins: the census counts match the list, the order follows
the argument order, and the three-outcome vocabulary is the schema's own.
"""

from __future__ import annotations

from typing import Any

import pytest

from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer.schemas import ConfirmationSignal
from macro_engine.thesis_layer.signals import (
    ConfirmationSignalAssessment,
    UnreadableConfirmationInput,
    build_confirmation_signals,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    model_name: str,
    value: Any,  # the whole point of this helper is that value is a union
    *,
    interpretation: str = "a reading",
    warnings: list[str] | None = None,
    source_family: EvidenceSourceFamily | None = None,
) -> ModelResult:
    """A minimal but schema-valid ``ModelResult`` for the shape under test."""
    return ModelResult(
        model_name=model_name,
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.5,
        interpretation=interpretation,
        context="test",
        inputs_used=[],
        warnings=warnings or [],
        source_family=source_family,
    )


def _gap(raw_gap: float) -> MarketPricingGap:
    """A gap whose direction is ``raw_gap``'s sign (``is_meaningful`` True)."""
    return MarketPricingGap(
        model_implied_value=4.0,
        market_implied_value=4.0 - raw_gap,
        raw_gap=raw_gap,
        dispersion=0.1,
        is_meaningful=abs(raw_gap) > 0.1,
        unit="%",
        interpretation="test gap",
    )


def _directions(assessment: ConfirmationSignalAssessment) -> dict[str, str]:
    return {s.source_model: s.direction for s in assessment.signals}


# ---------------------------------------------------------------------------
# Defect 1: an unreadable value is neutral, not a contradiction
# ---------------------------------------------------------------------------


def test_an_unreadable_value_is_neutral_not_a_contradiction() -> None:
    """A dict-valued result carries no direction and must read ``neutral``.

    §16.4's sample sends it to the ``else`` and publishes ``"contradicts"`` —
    a positive claim of disagreement from data that was not read (D-056).
    """
    inflation = _result(
        "inflation_convergence_classifier", {"classification": "HIGH", "agreeing": 5}
    )
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), inflation, _result("labor_tightness_score", 1.0), _gap(-0.5)
    )
    assert _directions(assessment)["inflation_convergence_classifier"] == "neutral"
    # The other two signals (both positive, against a negative gap) genuinely do
    # contradict — so the count is 2, and the unreadable one is NOT the third.
    assert assessment.disagreeing == 2, (
        "an unreadable value must not be counted as an active disagreement; "
        "§16.4's else-branch does exactly that"
    )
    assert "inflation_convergence_classifier" not in {
        s.source_model for s in assessment.signals if s.direction == "contradicts"
    }


def test_an_unreadable_value_is_reported_with_its_type() -> None:
    """The entry must say *why* it did not read, not just that it is neutral."""
    inflation = _result("inflation_convergence_classifier", {"classification": "HIGH"})
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), inflation, _result("labor_tightness_score", 1.0), _gap(-0.5)
    )
    assert len(assessment.unreadable) == 1
    entry = assessment.unreadable[0]
    assert entry.source_model == "inflation_convergence_classifier"
    assert entry.value_type == "dict"
    assert "contradicts" in entry.reason


def test_an_unreadable_value_still_produces_an_entry() -> None:
    """One entry per input: a dropped entry is the D-054 silence failure."""
    inflation = _result("inflation_convergence_classifier", ["a", "list"])
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), inflation, _result("labor_tightness_score", 1.0), _gap(-0.5)
    )
    assert len(assessment.signals) == 3
    assert [s.source_model for s in assessment.signals] == [
        "output_gap",
        "inflation_convergence_classifier",
        "labor_tightness_score",
    ]


def test_a_boolean_value_is_not_a_signed_number() -> None:
    """``isinstance(True, int)`` is True, so bool must be excluded first."""
    flag = _result("some_flag_model", True)
    assessment = build_confirmation_signals(
        flag, _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert _directions(assessment)["some_flag_model"] == "neutral"
    assert assessment.unreadable[0].value_type == "bool"


def test_a_string_verdict_is_unreadable() -> None:
    """A verdict word is a perfectly valid upstream result, not a direction."""
    verdict = _result("inflation_convergence_classifier", "HIGH")
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), verdict, _result("labor", 1.0), _gap(-0.5)
    )
    assert _directions(assessment)["inflation_convergence_classifier"] == "neutral"


# ---------------------------------------------------------------------------
# Defect 2: a zero value is neutral, not a contradiction
# ---------------------------------------------------------------------------


def test_a_zero_value_is_neutral_not_a_contradiction() -> None:
    """Zero is the balance point, not an opposing view.

    §16.4's conjunction ``(v > 0 and gap > 0) or (v < 0 and gap < 0)`` is False
    for v == 0, so the sample's ``else`` labels it ``"contradicts"``.
    """
    assessment = build_confirmation_signals(
        _result("output_gap", 0.0), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert _directions(assessment)["output_gap"] == "neutral"
    assert "output_gap" not in {
        s.source_model for s in assessment.signals if s.direction == "contradicts"
    }
    assert assessment.neutral == 1


def test_a_zero_value_is_not_unreadable() -> None:
    """Zero is *read* — it is a flat reading, not an unreadable one."""
    assessment = build_confirmation_signals(
        _result("output_gap", 0.0), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert assessment.unreadable == ()
    assert assessment.neutral == 1


# ---------------------------------------------------------------------------
# Defect 7: a NON-FINITE value is unreadable, not a contradiction (D-078)
# ---------------------------------------------------------------------------
#
# Defects 1 and 2 above are the same wrong outcome reached two ways: a value that
# carries no direction published as an active ``"contradicts"``. Both fixes work
# by making the value unreadable (defect 1) or neutral (defect 2) first. A
# ``nan`` defeats BOTH fixes, because it reaches ``_signed_scalar`` as a genuine
# ``float`` instance — it passes the type test that defect 1's fix relies on —
# and then reaches ``_direction_for``, where ``(nan > 0) == (gap_sign > 0)`` is
# ``False`` for any gap sign. So it is published as ``"contradicts"``: the very
# outcome defects 1 and 2 exist to prevent, arriving through the one gate they
# both sit downstream of.

_NON_FINITE_VALUES = (float("nan"), float("inf"), float("-inf"))


@pytest.mark.parametrize("bad", _NON_FINITE_VALUES)
def test_a_non_finite_value_is_unreadable_not_a_contradiction(bad: float) -> None:
    """A `nan` signal read as ``negatively`` contradicting the thesis.

    Measured before the fix: ``_direction_for(nan, +1) == "contradicts"`` and
    ``_direction_for(inf, +1) == "confirms"`` — i.e. a non-finite reading
    published a **directional verdict about a model's agreement with the
    thesis**, with no direction in it. §21.0 rule 3: a missing value must never
    become a substantive claim, and "this model disagrees with you" is about as
    substantive as a claim gets.
    """
    assessment = build_confirmation_signals(
        _result("output_gap", bad), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert _directions(assessment)["output_gap"] == "neutral"
    assert "output_gap" not in {
        s.source_model for s in assessment.signals if s.direction == "contradicts"
    }


@pytest.mark.parametrize("bad", _NON_FINITE_VALUES)
def test_a_non_finite_value_is_reported_unreadable(bad: float) -> None:
    """It must be *named* as unreadable, not silently neutralised.

    A silent neutral is nearly as bad as a false contradiction: the reader sees
    a model that abstained rather than one whose input could not be read at all.
    The census exists so the difference is visible.
    """
    assessment = build_confirmation_signals(
        _result("output_gap", bad), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert assessment.unreadable, f"{bad!r} should have been reported unreadable"
    assert assessment.unreadable[0].source_model == "output_gap"
    assert assessment.unreadable[0].value_type == "float"


@pytest.mark.parametrize("bad", _NON_FINITE_VALUES)
def test_a_non_finite_value_does_not_raise(bad: float) -> None:
    """Reported, never raised — a bad input must not abort the whole thesis."""
    assessment = build_confirmation_signals(
        _result("output_gap", bad), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert len(assessment.signals) == 3


def test_a_finite_value_still_reads_both_directions() -> None:
    """The guard must not narrow the readable range (no over-reach).

    Pins both signs against both gap signs, so a fix that accidentally dropped
    the readable set would be caught here rather than in production.
    """

    def direction(value: float, gap: float) -> str:
        return _directions(
            build_confirmation_signals(
                _result("output_gap", value),
                _result("infl", 0.2),
                _result("labor", 1.0),
                _gap(gap),
            )
        )["output_gap"]

    assert direction(0.5, 1.0) == "confirms"
    assert direction(-0.5, 1.0) == "contradicts"
    assert direction(-0.5, -1.0) == "confirms"
    assert direction(0.5, -1.0) == "contradicts"


# ---------------------------------------------------------------------------
# Defect 3: the label is the result's own model_name (O-69)
# ---------------------------------------------------------------------------


def test_the_label_is_the_result_own_model_name() -> None:
    """The label must name the model that was actually read.

    §16.4 calls the middle slot ``"inflation_convergence"`` while §16.2 passes
    ``inflation_breadth_score`` — a label naming a model the builder never
    called. Deriving it from ``model_name`` is the repair.
    """
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5),
        _result("inflation_breadth_score", 0.2),
        _result("labor_tightness_score", 1.0),
        _gap(-0.5),
    )
    assert [s.source_model for s in assessment.signals] == [
        "output_gap",
        "inflation_breadth_score",
        "labor_tightness_score",
    ]
    assert "inflation_convergence" not in _directions(assessment), (
        "the sample's label names a different model than §16.2 passes (O-69)"
    )


def test_an_empty_model_name_falls_back_to_the_slot() -> None:
    """A result with no ``model_name`` still gets a label."""
    assessment = build_confirmation_signals(
        _result("", 0.5), _result("", 0.2), _result("", 1.0), _gap(-0.5)
    )
    assert [s.source_model for s in assessment.signals] == ["growth", "inflation", "labor"]


def test_the_spec_names_six_labels_for_three_slots() -> None:
    """O-69's full extent, transcribed so the ambiguity cannot be forgotten.

    Three locations name a label set for the same three argument slots; only
    ``labor_tightness_score`` appears in all three, and ``curve_slope`` is not a
    parameter of this function at all.
    """
    section_16_4 = ("output_gap", "inflation_convergence", "labor_tightness_score")
    section_7_1_golden = ("labor_tightness_score", "inflation_breadth_simple", "curve_slope")
    section_16_2_actual = ("output_gap", "inflation_breadth_score", "labor_tightness_score")

    labels = set(section_16_4) | set(section_7_1_golden) | set(section_16_2_actual)
    assert len(labels) == 6

    common = set(section_16_4) & set(section_7_1_golden) & set(section_16_2_actual)
    assert common == {"labor_tightness_score"}, (
        "exactly one label is common to all three locations; the repair cannot "
        "rely on a hardcoded vocabulary because there is not one"
    )
    assert "curve_slope" not in section_16_2_actual


# ---------------------------------------------------------------------------
# Defect 4: source_family is carried through
# ---------------------------------------------------------------------------


def test_the_family_is_carried_through() -> None:
    """§6.6b: each entry must document enough to classify independence."""
    growth = _result("output_gap", 0.5, source_family=EvidenceSourceFamily.BEA_PCE)
    assessment = build_confirmation_signals(
        growth, _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert assessment.signals[0].source_family is EvidenceSourceFamily.BEA_PCE, (
        "the sample leaves source_family at its None default on every entry, "
        "which makes count_independent_families unreachable at this layer"
    )


def test_an_untagged_result_stays_untagged() -> None:
    """A ``None`` family is honest, not a defect — it must not be invented."""
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert all(s.source_family is None for s in assessment.signals)


def test_families_survive_every_direction() -> None:
    """Tagging is orthogonal to direction — a neutral entry keeps its family."""
    inflation = _result(
        "inflation_convergence_classifier",
        {"classification": "HIGH"},
        source_family=EvidenceSourceFamily.BLS_CPI,
    )
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), inflation, _result("labor", 1.0), _gap(-0.5)
    )
    assert assessment.signals[1].direction == "neutral"
    assert assessment.signals[1].source_family is EvidenceSourceFamily.BLS_CPI


# ---------------------------------------------------------------------------
# Defect 5: the model's own warnings travel with a corroborating signal
# ---------------------------------------------------------------------------


def test_a_corroborating_signal_reports_its_models_warning_count() -> None:
    """A model that warns is not a model that disagrees — both facts are shown."""
    labor = _result("labor_tightness_score", -1.0, warnings=["w1", "w2"])
    assessment = build_confirmation_signals(
        _result("output_gap", -0.5), _result("infl", -0.2), labor, _gap(-0.5)
    )
    entry = _directions(assessment)
    assert entry["labor_tightness_score"] == "confirms"
    detail = next(s.detail for s in assessment.signals if s.source_model == "labor_tightness_score")
    assert "model_warnings: 2" in detail


def test_the_marker_is_a_module_constant_not_a_config_leaf() -> None:
    """The token is a display marker, so it is a constant rather than a tunable.

    Pinned because the first draft put it in ``settings.yaml`` as a
    ``CalibratedValue``, and ``test_every_calibrated_leaf_has_a_numeric_property_accessor``
    correctly refused it: a string envelope can never be read as a plain number,
    which is the only route that guard accepts. A display token is not a fact
    about the economy, a convention, or an uncalibrated placeholder, so the
    envelope was the wrong shape rather than an accessor being missing.
    """
    from macro_engine.thesis_layer.signals import _WARNING_MARKER

    assert _WARNING_MARKER == "model_warnings"
    from macro_engine.config import get_settings

    dumped = get_settings().model_dump()
    assert "confirmation_signals" not in dumped, (
        "the marker belongs beside _SLOT_FALLBACK_NAMES, not in settings.yaml"
    )


def test_a_warning_free_signal_carries_no_marker() -> None:
    """The marker appears only when there is a count to report."""
    assessment = build_confirmation_signals(
        _result("output_gap", -0.5), _result("infl", -0.2), _result("labor", -1.0), _gap(-0.5)
    )
    assert all("model_warnings" not in s.detail for s in assessment.signals)


def test_an_unreadable_entry_does_not_report_warnings() -> None:
    """The marker is for *corroborating* signals; an unreadable one has no side."""
    verdict = _result(
        "inflation_convergence_classifier", {"classification": "HIGH"}, warnings=["w"]
    )
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), verdict, _result("labor", 1.0), _gap(-0.5)
    )
    detail = next(
        s.detail for s in assessment.signals if s.source_model == "inflation_convergence_classifier"
    )
    assert "model_warnings" not in detail
    assert "unreadable" in detail


def test_the_interpretation_is_kept_verbatim() -> None:
    """The model's own sentence is not rewritten — it is annotated."""
    labor = _result("labor_tightness_score", -1.0, interpretation="Divergent reading here")
    assessment = build_confirmation_signals(
        _result("output_gap", -0.5), _result("infl", -0.2), labor, _gap(-0.5)
    )
    detail = next(s.detail for s in assessment.signals if s.source_model == "labor_tightness_score")
    assert detail.startswith("Divergent reading here")


# ---------------------------------------------------------------------------
# Defect 6: a zero gap makes every comparison meaningless
# ---------------------------------------------------------------------------


def test_a_zero_gap_makes_every_signal_neutral() -> None:
    """No gap direction ⇒ nothing to confirm or contradict.

    §16.4 would still publish ``confirms`` for any nonzero signal against a zero
    gap, inventing the reference the comparison was supposed to be against.
    """
    assessment = build_confirmation_signals(
        _result("output_gap", 5.0), _result("infl", 3.0), _result("labor", -2.0), _gap(0.0)
    )
    assert all(s.direction == "neutral" for s in assessment.signals)
    assert assessment.agreeing == 0
    assert assessment.disagreeing == 0


def test_a_zero_gap_is_not_an_unreadable_input() -> None:
    """The signals were read perfectly; it is the *gap* that has no direction."""
    assessment = build_confirmation_signals(
        _result("output_gap", 5.0), _result("infl", 3.0), _result("labor", -2.0), _gap(0.0)
    )
    assert assessment.unreadable == ()
    assert assessment.neutral == 3


# ---------------------------------------------------------------------------
# Direction arithmetic
# ---------------------------------------------------------------------------


def test_a_signal_matching_the_gap_sign_confirms() -> None:
    negative_gap = build_confirmation_signals(
        _result("output_gap", -1.0), _result("infl", -0.2), _result("labor", -3.0), _gap(-0.5)
    )
    assert all(s.direction == "confirms" for s in negative_gap.signals)
    assert negative_gap.agreeing == 3


def test_a_signal_opposing_the_gap_sign_contradicts() -> None:
    positive_gap = build_confirmation_signals(
        _result("output_gap", -1.0), _result("infl", -0.2), _result("labor", -3.0), _gap(0.5)
    )
    assert all(s.direction == "contradicts" for s in positive_gap.signals)
    assert positive_gap.disagreeing == 3


def test_direction_is_symmetric_in_the_gap_sign() -> None:
    """The same signal set flips with the gap sign — no sign-specific branch."""
    args = (_result("output_gap", 1.0), _result("infl", 0.2), _result("labor", -3.0))
    up = build_confirmation_signals(*args, _gap(0.5))
    down = build_confirmation_signals(*args, _gap(-0.5))
    assert _directions(up) != _directions(down)
    for name, direction in _directions(up).items():
        flipped = _directions(down)[name]
        if direction == "confirms":
            assert flipped == "contradicts"
        elif direction == "contradicts":
            assert flipped == "confirms"


def test_a_nonzero_gap_with_a_tiny_signal_still_reads() -> None:
    """Any nonzero signed value has a side, however small."""
    assessment = build_confirmation_signals(
        _result("output_gap", 1e-12), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert _directions(assessment)["output_gap"] == "contradicts"


# ---------------------------------------------------------------------------
# Structure: vocabulary, census, order
# ---------------------------------------------------------------------------


def test_the_vocabulary_is_the_schemas_own() -> None:
    """Every published direction is a member the schema accepts."""
    assessment = build_confirmation_signals(
        _result("output_gap", 0.0),
        _result("inflation_convergence_classifier", {"c": 1}),
        _result("labor_tightness_score", 1.0),
        _gap(-0.5),
    )
    permitted = {"confirms", "contradicts", "neutral"}
    assert {s.direction for s in assessment.signals} <= permitted
    # The schema itself would raise on anything else — this proves it did not.
    for signal in assessment.signals:
        ConfirmationSignal(
            source_model=signal.source_model,
            direction=signal.direction,
            detail=signal.detail,
            source_family=signal.source_family,
        )


def test_the_census_matches_the_list() -> None:
    assessment = build_confirmation_signals(
        _result("output_gap", 0.0),
        _result("inflation_convergence_classifier", {"c": 1}),
        _result("labor_tightness_score", -1.0),
        _gap(-0.5),
    )
    assert assessment.agreeing == sum(1 for s in assessment.signals if s.direction == "confirms")
    assert assessment.disagreeing == sum(
        1 for s in assessment.signals if s.direction == "contradicts"
    )
    assert assessment.neutral == sum(1 for s in assessment.signals if s.direction == "neutral")
    assert assessment.agreeing + assessment.disagreeing + assessment.neutral == 3


def test_the_census_always_covers_every_input() -> None:
    """Three inputs ⇒ three entries ⇒ three counted outcomes."""
    for value in (0.0, 1.0, -1.0, {"c": 1}, True, "HIGH"):
        assessment = build_confirmation_signals(
            _result("output_gap", value), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
        )
        assert len(assessment.signals) == 3
        total = assessment.agreeing + assessment.disagreeing + assessment.neutral
        assert total == 3


def test_every_unreadable_input_has_a_matching_neutral_entry() -> None:
    """The two views of the same fact must not drift."""
    verdict = _result("inflation_convergence_classifier", {"classification": "HIGH"})
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), verdict, _result("labor", 1.0), _gap(-0.5)
    )
    neutral_names = {s.source_model for s in assessment.signals if s.direction == "neutral"}
    unreadable_names = {u.source_model for u in assessment.unreadable}
    assert unreadable_names <= neutral_names


def test_the_order_follows_the_argument_order() -> None:
    assessment = build_confirmation_signals(
        _result("growth_model", 0.5),
        _result("inflation_model", 0.2),
        _result("labor_model", 1.0),
        _gap(-0.5),
    )
    assert [s.source_model for s in assessment.signals] == [
        "growth_model",
        "inflation_model",
        "labor_model",
    ]


# ---------------------------------------------------------------------------
# The return type is an assessment, not a bare list
# ---------------------------------------------------------------------------


def test_the_return_type_is_an_assessment() -> None:
    """Q7's answer has two halves; a bare list can only carry one.

    §16.4 returns ``list[ConfirmationSignal]``, which is why an unreadable input
    had nowhere to be reported except as a false contradiction.
    """
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    assert isinstance(assessment, ConfirmationSignalAssessment)


def test_the_unreadable_record_is_frozen() -> None:
    entry = UnreadableConfirmationInput(source_model="m", value_type="dict", reason="r")
    with pytest.raises(Exception, match=r"frozen|instance"):
        entry.source_model = "other"


def test_the_assessment_is_frozen() -> None:
    assessment = build_confirmation_signals(
        _result("output_gap", 0.5), _result("infl", 0.2), _result("labor", 1.0), _gap(-0.5)
    )
    with pytest.raises(Exception, match=r"frozen|instance"):
        assessment.agreeing = 99


# ---------------------------------------------------------------------------
# Live (deselected by default)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_q1_models_produce_ordered_labeled_signals() -> None:
    """Build the three real Q1 models through the real plumbing and classify.

    The live claim is narrow and is the one an offline test cannot make: the
    models §16.2 Q1 actually names all **exist**, the live growth leg returns a
    **plausible** value, the labels are each result's own ``model_name``, and
    the census is total. It does **not** assert a direction — the real values
    move with the data, and pinning one would make this a fixture.

    The growth leg goes through ``output_gap_from_snapshot``, **not**
    ``output_gap`` fed by ``.iloc[-1]`` on each series. That shortcut is measured
    (2026-09-19) to return **-17.57%**, because ``GDPPOT`` is a CBO projection
    series whose last observation is **2036-10-01** — the O-7 horizon defect.
    The function that applies the O-7 filter and the D-009 same-quarter pairing
    is the one under test here, so the plausibility assertion below is the pin.

    Deselected unless ``-m live``.
    """
    from macro_engine.data_layer.snapshot_builder import build_snapshot
    from macro_engine.models.gdp_nowcast import output_gap_from_snapshot
    from macro_engine.models.labor_synthesis import (
        InflationSubMeasures,
        LaborInputs,
        inflation_breadth_score,
        labor_tightness_score,
    )

    snapshot, _report = build_snapshot(country="us")
    growth, gap_report = output_gap_from_snapshot(snapshot)

    inflation = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
    )
    labor = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-0.4,
            jolts_openings_yoy_pct=3.0,
            jolts_quits_level_percentile=60.0,
            nfp_3m_avg=180.0,
        )
    )

    assessment = build_confirmation_signals(growth, inflation, labor, _gap(-0.5))

    assert len(assessment.signals) == 3
    assert [s.source_model for s in assessment.signals] == [
        growth.model_name,
        inflation.model_name,
        labor.model_name,
    ]
    assert assessment.agreeing + assessment.disagreeing + assessment.neutral == 3
    assert assessment.unreadable == ()
    # All three legs are numeric by construction — a live value arriving in a
    # non-numeric shape would fail here rather than pass silently.
    assert isinstance(growth.value, (int, float)) and not isinstance(growth.value, bool)
    assert abs(float(growth.value)) <= 15.0, (
        f"live output_gap = {growth.value}; the O-7 horizon filter is not being "
        f"applied (the unfiltered shortcut returns about -17.6%)"
    )
    assert gap_report.withheld_forward_points > 0, (
        "no forward projection points were withheld; GDPPOT's projection block "
        "has vanished, which this filter exists to catch"
    )
