"""Tests for Module 14's no-trade outcome (Section 16.3, D-068).

Offline, fixture-driven. One live test is marked and exercised separately; it
proves the three triggers are reachable with a **real** snapshot rather than
synthetic objects.

These tests pin the five measured defects in Section 16.4's sample. Each defect
gets a test that would fail if the repair were reverted, so the sample can never
be quietly restored.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer.invalidation import (
    InvalidationAssessment,
    InvalidationCondition,
)
from macro_engine.thesis_layer.no_trade import (
    NO_TRADE_TRIGGER_LABELS,
    NoTradeDecision,
    NoTradeTrigger,
    no_trade_thesis,
    render_no_trade_thesis,
)
from macro_engine.thesis_layer.schemas import (
    ConfirmationSignal,
    MacroThesis,
    ThesisStatus,
    TradeIdea,
)
from macro_engine.thesis_layer.signals import ConfirmationSignalAssessment


def _gap(raw_gap: float = 0.05, dispersion: float = 0.42) -> MarketPricingGap:
    """A gap inside its noise floor, i.e. Q6's condition is met."""
    return MarketPricingGap(
        model_implied_value=3.05,
        market_implied_value=3.0,
        raw_gap=raw_gap,
        dispersion=dispersion,
        is_meaningful=abs(raw_gap) > dispersion,
        interpretation="model sits just above the market path; inside the noise floor",
    )


def _signals(*directions: str) -> ConfirmationSignalAssessment:
    entries = tuple(
        ConfirmationSignal(source_model=f"m{i}", direction=d, detail="fixture")
        for i, d in enumerate(directions)
    )
    return ConfirmationSignalAssessment(
        signals=entries,
        unreadable=(),
        agreeing=sum(1 for s in entries if s.direction == "confirms"),
        disagreeing=sum(1 for s in entries if s.direction == "contradicts"),
        neutral=sum(1 for s in entries if s.direction == "neutral"),
    )


def _invalidation(identified: bool = False) -> InvalidationAssessment:
    from datetime import UTC, datetime

    return InvalidationAssessment(
        conditions=(
            (
                InvalidationCondition(
                    model_name="output_gap",
                    trigger="crosses_back_negative",
                    observed_value="0.83",
                    threshold=0.0,
                    statement="output_gap crosses back below 0",
                ),
            )
            if identified
            else ()
        ),
        unreadable=(),
        neutral=(),
        text="output_gap crosses back below 0" if identified else "",
        identified=identified,
        reason="" if identified else "no input carries a direction to reverse from",
        as_of=datetime(2026, 9, 19, tzinfo=UTC),
    )


def _thesis_fields() -> dict[str, object]:
    """The six required ``MacroThesis`` fields, minimal and valid."""
    return {
        "thesis_id": "fixture",
        "regime": {"state": "neutral", "confidence": 0.0},
        "growth_view": {},
        "inflation_view": {},
        "policy_view": {},
        "market_pricing_gap": _gap(),
        "convergence_classification": "NO_SIGNAL",
    }


# ---------------------------------------------------------------------------
# Defect 2 — one string slot for three triggers
# ---------------------------------------------------------------------------


def test_the_trigger_is_a_field_not_a_phrase() -> None:
    """The Q that fired is readable without parsing the sentence.

    Section 16.4's sample hands over a bare ``reason: str``, so *which gate
    fired* is a property of the sentence an author happened to write. Two of the
    three triggers can produce byte-identical reasons and the sample cannot tell
    them apart.
    """
    q6 = no_trade_thesis("not enough signal", trigger="gap_below_dispersion", gap=_gap())
    q7 = no_trade_thesis("not enough signal", trigger="conflicted_signals")
    q8 = no_trade_thesis("not enough signal", trigger="no_falsifier")

    # The reasons are identical...
    assert q6.reason == q7.reason == q8.reason == "not enough signal"
    # ...and the decisions are still distinguishable, because the trigger is data.
    assert {q6.trigger, q7.trigger, q8.trigger} == {
        "gap_below_dispersion",
        "conflicted_signals",
        "no_falsifier",
    }


def test_every_trigger_has_a_label() -> None:
    """The vocabulary and its labels are the same set.

    A trigger added to the ``Literal`` without a label would raise ``KeyError``
    in ``warning_line()`` on a real thesis — this catches it at test time.
    """
    members = set(NoTradeTrigger.__args__)  # type: ignore[attr-defined]
    assert members == set(NO_TRADE_TRIGGER_LABELS), (
        "NoTradeTrigger and NO_TRADE_TRIGGER_LABELS describe different sets; a "
        "trigger with no label would KeyError when a thesis is rendered."
    )


def test_the_warning_line_carries_the_trigger() -> None:
    """The published warning names the gate, so it survives into ``warnings``."""
    decision = no_trade_thesis("not enough signal", trigger="conflicted_signals")
    line = decision.warning_line()

    assert "conflicted_signals" in line
    assert "not enough signal" in line
    assert line.startswith("No trade [")


# ---------------------------------------------------------------------------
# Defect 3 — the rich object each trigger already held
# ---------------------------------------------------------------------------


def test_q6_keeps_the_gap_object() -> None:
    """Q6's evidence is the ``MarketPricingGap``, not a sentence about it."""
    gap = _gap(raw_gap=0.05, dispersion=0.42)
    decision = no_trade_thesis("inside the noise floor", trigger="gap_below_dispersion", gap=gap)

    assert decision.evidence is gap
    assert isinstance(decision.evidence, MarketPricingGap)
    # The magnitudes the sentence cannot carry:
    assert decision.evidence.raw_gap == 0.05
    assert decision.evidence.dispersion == 0.42


def test_q7_keeps_the_signal_table() -> None:
    """Q7's evidence is the per-model direction table, not a summary of it."""
    assessment = _signals("confirms", "contradicts", "neutral")
    decision = no_trade_thesis(
        "pillars contradict", trigger="conflicted_signals", evidence=assessment
    )

    assert decision.evidence is assessment
    assert isinstance(decision.evidence, ConfirmationSignalAssessment)
    assert [s.direction for s in decision.evidence.signals] == [
        "confirms",
        "contradicts",
        "neutral",
    ]
    assert decision.evidence.agreeing == 1
    assert decision.evidence.disagreeing == 1


def test_q8_keeps_the_invalidation_assessment() -> None:
    """Q8's evidence is the assessment, including *why* nothing was identified."""
    assessment = _invalidation(identified=False)
    decision = no_trade_thesis("no falsifier", trigger="no_falsifier", evidence=assessment)

    assert decision.evidence is assessment
    assert isinstance(decision.evidence, InvalidationAssessment)
    assert decision.evidence.identified is False
    assert decision.evidence.reason  # the model's own explanation survives


# ---------------------------------------------------------------------------
# Defect 4 — an empty or missing reason was accepted
# ---------------------------------------------------------------------------


def test_an_empty_reason_is_refused() -> None:
    """Section 16.4's ``warnings=[reason]`` accepts ``""``; this does not."""
    with pytest.raises(ValueError, match="reason must be a non-empty sentence"):
        no_trade_thesis("", trigger="caller")


def test_a_whitespace_reason_is_refused() -> None:
    """Whitespace is empty for reading purposes, which is the only purpose here."""
    with pytest.raises(ValueError, match="reason must be a non-empty sentence"):
        no_trade_thesis("   \n\t ", trigger="caller")


def test_the_refusal_explains_the_conflation() -> None:
    """ "We stood down" and "we stood down and cannot say why" differ by this error."""
    with pytest.raises(ValueError) as excinfo:
        no_trade_thesis("", trigger="no_falsifier")
    message = str(excinfo.value)

    assert "indistinguishable" in message
    assert "trigger='caller'" in message  # the suggested alternative is named


def test_a_reason_is_stripped_not_stored_raw() -> None:
    """Leading/trailing whitespace is not part of the sentence."""
    decision = no_trade_thesis("  padded  ", trigger="caller")
    assert decision.reason == "padded"


# ---------------------------------------------------------------------------
# Defect 5 — "n/a" satisfies the gate it stands down from
# ---------------------------------------------------------------------------


def test_the_no_trade_idea_carries_no_falsifier_rather_than_a_sentinel() -> None:
    """``stop_or_invalidation`` is empty, not ``"n/a"``.

    Measured: ``"n/a".strip()`` is truthy, so Section 16.4's sample writes a
    sentinel that would satisfy the LTCM gate if ``is_trade`` ever flipped. The
    honest value for a position that does not exist is nothing.
    """
    decision = no_trade_thesis("no edge", trigger="caller")
    thesis = render_no_trade_thesis(decision, **_thesis_fields())

    assert thesis.trade_idea.stop_or_invalidation == ""
    assert thesis.trade_idea.is_trade is False


def test_the_sentinel_would_have_passed_the_gate() -> None:
    """Prove the defect was real: ``"n/a"`` is a usable falsifier to the schema.

    This is the measurement, kept as a test so the reason for the divergence from
    Section 16.4's sample is executable rather than a claim in a docstring.
    """
    assert bool("n/a".strip()) is True
    # And a TradeIdea carrying only the sentinel passes the live-trade gate:
    idea = TradeIdea(
        instrument="SOFR_FUTURE",
        direction="long",
        stop_or_invalidation="n/a",
    )
    assert idea.is_trade is True  # the gate was satisfied by "n/a"


# ---------------------------------------------------------------------------
# Defect 1 — the sample's body does not run
# ---------------------------------------------------------------------------


def test_the_sample_body_cannot_construct_a_macrothesis() -> None:
    """Section 16.4's nine-line body raises, naming its unset required fields.

    The measurable form of defect 1: the sample is not a simplification, it is a
    call that cannot succeed, and the required-field list is why this module
    returns a decision object instead.
    """
    with pytest.raises(ValidationError) as excinfo:
        # Deliberately missing the six required fields — that IS the assertion,
        # so the type error mypy reports here is the defect under test, not a
        # mistake. A `type: ignore` on the CALL rather than per-argument, because
        # the six missing-field errors are one fact.
        MacroThesis(  # type: ignore[call-arg]
            thesis_id="x",
            trade_idea=TradeIdea(instrument="NONE"),
            status=ThesisStatus.WATCH,
            warnings=["a reason"],
        )
    text = str(excinfo.value)
    for field_name in (
        "regime",
        "growth_view",
        "inflation_view",
        "policy_view",
        "market_pricing_gap",
    ):
        assert field_name in text, f"{field_name} should be named as missing"


def test_the_three_triggers_are_testable_without_a_snapshot() -> None:
    """The point of returning a decision object: no snapshot needed to build one."""
    decisions = [
        no_trade_thesis("g", trigger="gap_below_dispersion", gap=_gap()),
        no_trade_thesis("c", trigger="conflicted_signals"),
        no_trade_thesis("f", trigger="no_falsifier"),
        no_trade_thesis("x", trigger="caller"),
    ]
    assert all(isinstance(d, NoTradeDecision) for d in decisions)
    assert len({d.trigger for d in decisions}) == 4


# ---------------------------------------------------------------------------
# elapsed — how close the call was
# ---------------------------------------------------------------------------


def test_elapsed_measures_how_far_inside_the_noise_floor() -> None:
    """A gap 1bp short of meaningful and one 200bp short are not the same call."""
    barely = no_trade_thesis(
        "barely inside", trigger="gap_below_dispersion", gap=_gap(raw_gap=0.415, dispersion=0.42)
    )
    clearly = no_trade_thesis(
        "clearly inside", trigger="gap_below_dispersion", gap=_gap(raw_gap=0.01, dispersion=0.42)
    )

    assert barely.elapsed == pytest.approx(0.005)
    assert clearly.elapsed == pytest.approx(0.41)
    # `elapsed` is `float | None` (it is None for every trigger but Q6), so the
    # comparison is asserted on narrowed values rather than the union — and the
    # narrowing IS the check that Q6 populated it.
    assert barely.elapsed is not None
    assert clearly.elapsed is not None
    assert barely.elapsed < clearly.elapsed


def test_elapsed_is_absolute_so_a_negative_gap_reads_the_same() -> None:
    """``raw_gap`` can be negative; the distance inside the floor is not."""
    negative = no_trade_thesis(
        "negative gap", trigger="gap_below_dispersion", gap=_gap(raw_gap=-0.05, dispersion=0.42)
    )
    assert negative.elapsed == pytest.approx(0.37)


def test_elapsed_is_none_when_the_trigger_has_no_magnitude() -> None:
    """Only Q6 has a "how close" notion; inventing one elsewhere is a false detail."""
    triggers: tuple[NoTradeTrigger, ...] = ("conflicted_signals", "no_falsifier", "caller")
    for trigger in triggers:
        decision = no_trade_thesis("x", trigger=trigger)
        assert decision.elapsed is None


def test_gap_below_dispersion_without_a_gap_is_refused() -> None:
    """The one argument this trigger cannot do without."""
    with pytest.raises(ValueError, match="requires the `gap` argument"):
        no_trade_thesis("inside the floor", trigger="gap_below_dispersion")


def test_gap_below_dispersion_defaults_its_evidence_to_the_gap() -> None:
    """Passing only ``gap`` gives both ``elapsed`` and ``evidence``."""
    gap = _gap()
    decision = no_trade_thesis("inside", trigger="gap_below_dispersion", gap=gap)
    assert decision.evidence is gap


def test_is_marginal_flags_a_zero_or_epsilon_elapsed() -> None:
    """``is_marginal`` reads the field rather than re-deriving from the sentence."""
    on_the_line = no_trade_thesis(
        "on the line", trigger="gap_below_dispersion", gap=_gap(raw_gap=0.42, dispersion=0.42)
    )
    assert on_the_line.elapsed == pytest.approx(0.0)
    assert on_the_line.is_marginal is True

    clearly_inside = no_trade_thesis(
        "clearly", trigger="gap_below_dispersion", gap=_gap(raw_gap=0.01, dispersion=0.42)
    )
    assert clearly_inside.is_marginal is False


def test_is_marginal_uses_a_basis_point_tolerance_and_is_reachable() -> None:
    """The defect this pins: ``is_marginal`` could never be ``True`` for a real gap.

    The old implementation compared the shortfall in **percentage points**
    against the literal ``1e-9`` — i.e. ``1e-11`` of a basis point — while
    ``raw_gap`` is rounded to 4 decimals upstream. A gap can therefore never be
    that close, so the near-miss distinction the field exists to draw was
    unreachable in production even though a unit test at ``elapsed == 0.0``
    passed. The tolerance is now ``policy.ensemble.near_miss_tolerance_bp`` and
    the comparison converts pp -> bp explicitly.

    The expected values are derived from the *config leaf* rather than read from
    the same property the code uses, per D-035, so a change to the leaf is
    observable here instead of silently shifting the boundary.
    """
    tolerance_bp = get_settings().policy.ensemble.near_miss_tolerance_bp_value
    assert tolerance_bp > 0.0, "a zero tolerance makes the flag unreachable again"

    # Just inside the tolerance: the shortfall in bp is half the tolerance.
    inside_shortfall_pp = (tolerance_bp / 2.0) / 100.0
    inside = no_trade_thesis(
        "near miss",
        trigger="gap_below_dispersion",
        gap=_gap(raw_gap=0.42 - inside_shortfall_pp, dispersion=0.42),
    )
    assert inside.elapsed == pytest.approx(inside_shortfall_pp)
    assert inside.is_marginal is True, (
        "a shortfall inside the configured bp tolerance must read as marginal; "
        "this is the case the 1e-9 literal made unreachable"
    )

    # Just outside: twice the tolerance.
    outside_pp = (tolerance_bp * 2.0) / 100.0
    outside = no_trade_thesis(
        "clear miss",
        trigger="gap_below_dispersion",
        gap=_gap(raw_gap=0.42 - outside_pp, dispersion=0.42),
    )
    assert outside.elapsed == pytest.approx(outside_pp)
    assert outside.is_marginal is False

    # The boundary itself: bp distance equal to the tolerance is inclusive.
    at_tolerance = no_trade_thesis(
        "exactly at tolerance",
        trigger="gap_below_dispersion",
        gap=_gap(raw_gap=0.42 - tolerance_bp / 100.0, dispersion=0.42),
    )
    assert at_tolerance.is_marginal is True


def test_is_marginal_never_fires_for_a_negative_elapsed() -> None:
    """``elapsed`` is a distance inside the floor, so it cannot be negative.

    The property guards the lower bound as well as the upper one: a negative
    shortfall would mean the gap was *outside* the floor and should not have
    stood down at all, and reporting it as a near-miss would compound the error.
    """
    decision = NoTradeDecision(trigger="gap_below_dispersion", reason="x", elapsed=-0.01)
    assert decision.is_marginal is False


def test_is_marginal_is_false_when_elapsed_does_not_apply() -> None:
    """ "Not close" is the safe reading; ``True`` would invent a near-miss."""
    decision = no_trade_thesis("conflicted", trigger="conflicted_signals")
    assert decision.elapsed is None
    assert decision.is_marginal is False


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_the_status_is_the_specs_watch() -> None:
    """Section 16.4 sets WATCH for a no-trade; carried so a rule has one home."""
    decision = no_trade_thesis("no edge", trigger="caller")
    assert decision.status is ThesisStatus.WATCH


def test_the_rendered_thesis_is_watch_not_draft() -> None:
    """A stand-down is WATCH, distinct from the DRAFT a live thesis gets.

    The two are compared as **values** rather than by identity. Measured: writing
    ``assert status is not ThesisStatus.DRAFT`` after ``assert status is
    ThesisStatus.WATCH`` makes mypy report ``comparison-overlap`` — the first
    assertion has already narrowed the type, so the second is provably true and
    therefore asserts nothing. Comparing ``.value`` keeps the intent (the two
    statuses differ) without the narrowing that makes it vacuous.
    """
    thesis = render_no_trade_thesis(
        no_trade_thesis("no edge", trigger="caller"), **_thesis_fields()
    )
    assert thesis.status is ThesisStatus.WATCH
    assert thesis.status.value != ThesisStatus.DRAFT.value


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_render_produces_a_full_thesis_with_the_no_trade_shape() -> None:
    """The published object: instrument NONE, no direction, WATCH, labelled warning."""
    thesis = render_no_trade_thesis(
        no_trade_thesis("no clean edge", trigger="no_falsifier"), **_thesis_fields()
    )

    assert isinstance(thesis, MacroThesis)
    assert thesis.trade_idea.instrument == "NONE"
    assert thesis.trade_idea.direction == "n/a"
    assert thesis.trade_idea.timeframe == "n/a"
    assert thesis.trade_idea.catalysts == []
    assert thesis.status is ThesisStatus.WATCH


def test_render_puts_the_trigger_line_first() -> None:
    """The stand-down is read before the caveats it is made of."""
    thesis = render_no_trade_thesis(
        no_trade_thesis("no clean edge", trigger="conflicted_signals"), **_thesis_fields()
    )

    assert len(thesis.warnings) == 1
    assert thesis.warnings[0].startswith("No trade [conflicted_signals]")


def test_render_passes_the_callers_partial_views_through() -> None:
    """The caller's six fields survive, so a human can still see the partial view."""
    fields = _thesis_fields()
    fields["regime"] = {"state": "restrictive", "confidence": 0.7}
    fields["growth_view"] = {"output_gap": 0.83}

    thesis = render_no_trade_thesis(no_trade_thesis("no clean edge", trigger="caller"), **fields)

    assert thesis.regime == {"state": "restrictive", "confidence": 0.7}
    assert thesis.growth_view == {"output_gap": 0.83}


def test_render_survives_the_conflicted_schema_gate() -> None:
    """CONFLICTED + no-trade is ALLOWED — 'conflicted' is a reason to stand down.

    ``MacroThesis._enforce_conflicted_blocks_trade`` refuses CONFLICTED together
    with a live trade; a no-trade has ``is_trade`` False, so the gate permits the
    one combination where CONFLICTED is the honest classification.
    """
    fields = _thesis_fields()
    fields["convergence_classification"] = "CONFLICTED"

    thesis = render_no_trade_thesis(
        no_trade_thesis("pillars contradict", trigger="conflicted_signals"), **fields
    )

    assert thesis.convergence_classification.value == "CONFLICTED"
    assert thesis.trade_idea.is_trade is False


def test_render_refuses_a_trade_idea_override() -> None:
    """A caller cannot silently replace the stand-down shape."""
    with pytest.raises(ValueError, match="trade_idea"):
        render_no_trade_thesis(
            no_trade_thesis("x", trigger="caller"),
            trade_idea=TradeIdea(
                instrument="SOFR_FUTURE", direction="long", stop_or_invalidation="s"
            ),
            **_thesis_fields(),
        )


def test_render_refuses_a_status_override() -> None:
    """Nor the status: a no-trade rendered as DRAFT would claim a promotion path."""
    with pytest.raises(ValueError, match="status"):
        render_no_trade_thesis(
            no_trade_thesis("x", trigger="caller"),
            status=ThesisStatus.DRAFT,
            **_thesis_fields(),
        )


def test_render_refuses_a_warnings_override() -> None:
    """Nor the warnings: the trigger line is the record of which gate fired."""
    with pytest.raises(ValueError, match="warnings"):
        render_no_trade_thesis(
            no_trade_thesis("x", trigger="caller"),
            warnings=["something else"],
            **_thesis_fields(),
        )


def test_the_reserved_names_are_named_in_the_error() -> None:
    """The error says which fields clash, not just that something did."""
    with pytest.raises(ValueError) as excinfo:
        render_no_trade_thesis(
            no_trade_thesis("x", trigger="caller"),
            status=ThesisStatus.DRAFT,
            warnings=["x"],
            **_thesis_fields(),
        )
    assert "status" in str(excinfo.value)
    assert "warnings" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The decision object's own contract
# ---------------------------------------------------------------------------


def test_the_decision_is_frozen() -> None:
    """A decision is a record, not a buffer (the ``InvalidationAssessment`` rule)."""
    decision = no_trade_thesis("no edge", trigger="caller")
    with pytest.raises(ValidationError):
        decision.reason = "changed"


def test_the_decision_forbids_extra_fields() -> None:
    """An unlisted field would be a place for a typo to live."""
    with pytest.raises(ValidationError):
        NoTradeDecision(trigger="caller", reason="x", surprise=1)  # type: ignore[call-arg]


def test_the_trigger_vocabulary_is_closed() -> None:
    """The four members, exactly — a fifth is a type error, not a new string."""
    assert set(NoTradeTrigger.__args__) == {  # type: ignore[attr-defined]
        "gap_below_dispersion",
        "conflicted_signals",
        "no_falsifier",
        "caller",
    }


def test_the_evidence_union_accepts_three_shapes_and_none() -> None:
    """The union is the three gate objects plus ``None`` for ``caller``."""
    assert no_trade_thesis("g", trigger="gap_below_dispersion", gap=_gap()).evidence is not None
    assert (
        no_trade_thesis("c", trigger="conflicted_signals", evidence=_signals("confirms")).evidence
        is not None
    )
    assert (
        no_trade_thesis("f", trigger="no_falsifier", evidence=_invalidation()).evidence is not None
    )
    assert no_trade_thesis("x", trigger="caller").evidence is None
