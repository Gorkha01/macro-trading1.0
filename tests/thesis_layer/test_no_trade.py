"""``thesis_layer/no_trade.py`` — the five sample defects, plus two live ones.

The module's docstring lists five measured defects in Section 16.4's nine-line
sample. Before 2026-10-06 there was no test file for this module at all, so
``NO_TRADE_TRIGGER_LABELS``' comment — "a trigger added to the vocabulary without
a label is a ``KeyError`` in the census test" — named a test that did not exist.

Two live defects were found BY this review:

* ``F-NT-001`` — ``NoTradeDecision.reason``'s description said an empty reason is
  "refused rather than accepted", but the model had no ``min_length``: only the
  factory refused it, so ``NoTradeDecision(trigger="caller", reason="")`` was
  accepted.
* ``F-NT-002`` — ``evidence`` was optional for EVERY trigger, so the discarding
  the module exists to stop (defect 3) could be reintroduced by simply not
  passing it, while the field description asserted "None only for ``caller``".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from macro_engine.models.contracts import ModelResult
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer.no_trade import (
    NO_TRADE_INSTRUMENT,
    NO_TRADE_TRIGGER_LABELS,
    NoTradeDecision,
    NoTradeTrigger,
    no_trade_thesis,
    render_no_trade_thesis,
)
from macro_engine.thesis_layer.schemas import (
    NO_PRODUCTION_INSTRUMENT,
    ConvergenceClassification,
    ThesisStatus,
    TradeIdea,
)
from macro_engine.thesis_layer.signals import ConfirmationSignalAssessment

_AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


def _gap(raw_gap: float = -0.05, dispersion: float = 0.06) -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=2.0,
        market_implied_value=2.0 - raw_gap,
        raw_gap=raw_gap,
        dispersion=dispersion,
        is_meaningful=abs(raw_gap) > dispersion,
        interpretation="model sits marginally below the market",
    )


def _thesis_fields() -> dict[str, object]:
    """The six required ``MacroThesis`` fields, supplied as a caller would."""
    return {
        "thesis_id": "T-0001",
        "regime": {"label": "late-cycle"},
        "growth_view": {"direction": "cooling"},
        "inflation_view": {"direction": "sticky"},
        "policy_view": {"direction": "easing"},
        "market_pricing_gap": _gap(),
        "convergence_classification": ConvergenceClassification.CONFLICTED,
    }


def _assessment() -> ConfirmationSignalAssessment:
    """A real ``ConfirmationSignalAssessment`` for the Q7 trigger (not a stub)."""
    from macro_engine.thesis_layer.signals import build_confirmation_signals

    def r(name: str, value: float) -> ModelResult:
        return ModelResult(
            model_name=name,
            country="us",
            as_of=_AS_OF,
            value=value,
            confidence=0.5,
            interpretation="i",
            context="c",
            inputs_used=["x"],
        )

    return build_confirmation_signals(r("a", 1.0), r("b", -1.0), r("c", 1.0), _gap(-1.0))


# ---------------------------------------------------------------------------
# defect 1 — the sample does not run
# ---------------------------------------------------------------------------


def test_the_sample_body_cannot_succeed() -> None:
    """Six ``MacroThesis`` fields are required; the sample never supplies them.

    Non-vacuity for the renderer: the missing-field refusal is real, so
    ``render_no_trade_thesis`` cannot be a no-op wrapper.
    """
    decision = no_trade_thesis("conflict", trigger="conflicted_signals", evidence=_assessment())
    with pytest.raises(ValidationError):
        render_no_trade_thesis(decision)  # no thesis fields at all


def test_the_renderer_supplies_the_no_trade_shape_and_nothing_else() -> None:
    decision = no_trade_thesis("conflict", trigger="conflicted_signals", evidence=_assessment())
    thesis = render_no_trade_thesis(decision, **_thesis_fields())
    assert thesis.trade_idea.instrument == NO_TRADE_INSTRUMENT
    assert thesis.status is ThesisStatus.WATCH
    assert len(thesis.warnings) == 1


# ---------------------------------------------------------------------------
# defect 2 — one string slot for three triggers
# ---------------------------------------------------------------------------


def test_the_trigger_is_a_field_so_stand_downs_can_be_counted_by_cause() -> None:
    a = no_trade_thesis("gap inside the noise floor", trigger="gap_below_dispersion", gap=_gap())
    b = no_trade_thesis("conflict", trigger="conflicted_signals", evidence=_assessment())
    assert a.trigger == "gap_below_dispersion"
    assert b.trigger == "conflicted_signals"
    # (`a.trigger != b.trigger` is not asserted: mypy proves the two Literals
    #  disjoint, which is the point — the vocabulary makes them distinguishable.)
    assert "[gap_below_dispersion]" in a.warning_line()
    assert "[conflicted_signals]" in b.warning_line()


def test_every_declared_trigger_has_a_label() -> None:
    """The 'census test' ``NO_TRADE_TRIGGER_LABELS``' comment names — it did not exist.

    A trigger added to the ``Literal`` without a label must fail HERE rather than
    producing an unlabelled warning on a real thesis. ``get_args`` reads the
    declared vocabulary, so the two halves cannot drift.
    """
    from typing import get_args

    declared = set(get_args(NoTradeTrigger))
    assert declared == set(NO_TRADE_TRIGGER_LABELS), (
        f"declared {sorted(declared)} vs labelled {sorted(NO_TRADE_TRIGGER_LABELS)} — a "
        f"trigger without a label renders as an unlabelled warning."
    )
    assert declared == {"gap_below_dispersion", "conflicted_signals", "no_falsifier", "caller"}


def test_a_caller_stand_down_is_sayable() -> None:
    """The fourth member exists so a non-gate stand-down need not reuse a gate label."""
    d = no_trade_thesis("operator flattened the book", trigger="caller")
    assert d.trigger == "caller"
    assert d.evidence is None


# ---------------------------------------------------------------------------
# defect 3 — the gate's rich object was discarded
# ---------------------------------------------------------------------------


def test_the_evidence_the_gate_held_is_carried() -> None:
    assessment = _assessment()
    d = no_trade_thesis("conflict", trigger="conflicted_signals", evidence=assessment)
    assert d.evidence is assessment


def test_gap_below_dispersion_defaults_its_evidence_to_the_gap() -> None:
    gap = _gap()
    d = no_trade_thesis("inside the noise floor", trigger="gap_below_dispersion", gap=gap)
    assert d.evidence is gap
    assert d.elapsed == pytest.approx(gap.dispersion - abs(gap.raw_gap))


def test_elapsed_is_only_set_for_the_gap_trigger() -> None:
    d = no_trade_thesis("conflict", trigger="conflicted_signals", evidence=_assessment())
    assert d.elapsed is None


# ---------------------------------------------------------------------------
# defect 4 — "no reason" and "a reason" were the same value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_an_empty_or_whitespace_reason_is_refused_by_the_factory(bad: str) -> None:
    with pytest.raises(ValueError, match="reason must be a non-empty sentence"):
        no_trade_thesis(bad, trigger="caller")


def test_an_empty_reason_is_refused_by_the_model_too() -> None:
    """(F-NT-001) The description said it is "refused rather than accepted".

    It was not: only ``no_trade_thesis`` refused it, so a directly-constructed
    decision carried a blank explanation — the exact conflation defect 4 names.
    """
    with pytest.raises(ValidationError):
        NoTradeDecision(trigger="caller", reason="")
    # ...and the reason is preserved as given (stripped by the factory, not here).
    assert NoTradeDecision(trigger="caller", reason="  spaced  ").reason == "  spaced  "


# ---------------------------------------------------------------------------
# defect 5 — "n/a" satisfied the gate it stood down from
# ---------------------------------------------------------------------------


def test_a_stand_down_carries_an_empty_falsifier_not_a_truthy_sentinel() -> None:
    d = no_trade_thesis("caller", trigger="caller")
    thesis = render_no_trade_thesis(d, **_thesis_fields())
    assert thesis.trade_idea.stop_or_invalidation == ""
    assert thesis.trade_idea.is_trade is False


def test_a_truthy_sentinel_would_have_satisfied_the_gate() -> None:
    """Non-vacuity: ``"n/a".strip()`` is truthy, so the sample's value passes.

    The gate is skipped on a no-trade today (``is_trade`` is False), which is
    exactly why a truthy sentinel in that field is one flip away from asserting
    a falsifier that does not exist.
    """
    assert "n/a".strip()  # truthy
    # On a LIVE idea the same string satisfies the LTCM gate outright:
    live = TradeIdea(
        instrument="UST cash (2yr, 5yr, 10yr, 30yr)",
        direction="long",
        stop_or_invalidation="n/a",
    )
    assert live.stop_or_invalidation.strip()


# ---------------------------------------------------------------------------
# the renderer's contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reserved", ["trade_idea", "status", "warnings"])
def test_the_renderer_refuses_the_fields_it_owns(reserved: str) -> None:
    d = no_trade_thesis("caller", trigger="caller")
    with pytest.raises(ValueError, match=r"must not be passed"):
        render_no_trade_thesis(d, **{**_thesis_fields(), reserved: object()})


def test_the_trigger_line_is_the_only_warning_this_module_writes() -> None:
    """The builder appends the collected caveats BEHIND it (measured, builder.py)."""
    d = no_trade_thesis("conflict", trigger="conflicted_signals", evidence=_assessment())
    thesis = render_no_trade_thesis(d, **_thesis_fields())
    assert thesis.warnings == [d.warning_line()]


# ---------------------------------------------------------------------------
# the near-miss distinction
# ---------------------------------------------------------------------------


def test_a_near_miss_is_distinguished_from_a_comfortable_stand_down() -> None:
    near = no_trade_thesis("near", trigger="gap_below_dispersion", gap=_gap(-0.05, 0.06))
    far = no_trade_thesis("far", trigger="gap_below_dispersion", gap=_gap(0.0, 0.5))
    assert near.is_marginal is True
    assert far.is_marginal is False


def test_no_elapsed_is_not_a_near_miss() -> None:
    """ "Not close" is the safe reading when the question does not apply."""
    d = no_trade_thesis("conflict", trigger="conflicted_signals", evidence=_assessment())
    assert d.is_marginal is False


def test_the_near_miss_note_gets_the_unit_conversion_the_right_way_round() -> None:
    """(F-NT-005) The note claimed 1e-9 pp was 1e-11 bp; it is 1e-7 bp.

    1 pp = 100 bp, so the conversion MULTIPLIES — which is what the code beside
    the note does (``self.elapsed * 100.0``). The old figure is the result of
    dividing by 100, a unit-direction slip in the very conversion the paragraph
    is about.
    """
    import inspect
    from pathlib import Path

    from macro_engine.thesis_layer import no_trade as nt

    assert pytest.approx(1e-7) == 1e-9 * 100.0
    source = Path(inspect.getfile(nt)).read_text(encoding="utf-8")
    assert "1e-11" not in source
    assert "1e-7 bp" in source
    # and the code itself still converts by multiplying:
    assert "* 100.0" in source


# ---------------------------------------------------------------------------
# the sentinel: two declarations, one fact
# ---------------------------------------------------------------------------


def test_the_two_none_sentinels_are_the_same_value() -> None:
    """(F-NT-004) ``no_trade.NO_TRADE_INSTRUMENT`` and ``schemas.NO_PRODUCTION_INSTRUMENT``.

    Two declarations of one literal, and this module's own comment names exactly
    this drift risk ("the two could drift while every test still passed"). A
    divergence would ALSO make ``_build_no_trade_trade_idea`` raise, because
    ``TradeIdea``'s validator compares against the schemas copy — so the binding
    is asserted here and exercised by every render test above.
    """
    assert NO_TRADE_INSTRUMENT == NO_PRODUCTION_INSTRUMENT


# ---------------------------------------------------------------------------
# (F-NT-002) the evidence requirement, on the schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", ["gap_below_dispersion", "conflicted_signals", "no_falsifier"])
def test_a_non_caller_trigger_must_carry_its_evidence(trigger: NoTradeTrigger) -> None:
    """(F-NT-002) Omitting ``evidence`` must not silently reintroduce defect 3.

    Enforced on ``NoTradeDecision`` rather than only in the factory, so a caller
    cannot bypass it by constructing the decision directly — the principle
    ``MacroThesis._enforce_invalidation_gate`` states.
    """
    with pytest.raises(ValidationError, match="must carry the evidence its gate held"):
        NoTradeDecision(trigger=trigger, reason="a sentence")


def test_the_factory_also_refuses_a_missing_evidence() -> None:
    with pytest.raises(ValidationError, match="must carry the evidence its gate held"):
        no_trade_thesis("conflict", trigger="conflicted_signals")


def test_the_gap_trigger_still_requires_its_gap_argument() -> None:
    """The argument requirement and the evidence requirement are separate."""
    with pytest.raises(ValueError, match="requires the `gap`"):
        no_trade_thesis("inside the noise floor", trigger="gap_below_dispersion")
