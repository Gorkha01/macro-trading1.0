"""Module 14 — the no-trade outcome (Section 16.3, D-068).

``no_trade_thesis`` is the function that says **"there is no clean edge here."**
Section 16.3 is emphatic that this is a first-class, fully-formed thesis rather
than an exception, a ``None``, or a fallback for missing data:

    "NO TRADE is a first-class, fully-formed MacroThesis — not an exception,
    not a null return. Module 14's explicit teaching: prefer fewer high-quality
    decisions; correctly identifying 'no clean edge exists right now' is itself
    a valuable output, not a failure to answer."

Section 16.2 routes to it from exactly **three** places:

======================  ==========================================================
Q                       condition
======================  ==========================================================
**Q6**                  ``abs(gap.raw_gap) <= gap.dispersion`` — the gap is inside
                        the policy rules' own disagreement, so it is not
                        distinguishable from noise
**Q7**                  ``convergence == "CONFLICTED"`` — growth and inflation
                        point opposite ways (Module 12 dual-mandate tension)
**Q8**                  ``invalidation.identified is False`` — no evidence-based
                        falsifier could be derived, so the position could not be
                        exited on evidence (D-063 / O-68)
======================  ==========================================================

Section 16.4's sample is nine lines:

    def no_trade_thesis(reason: str) -> MacroThesis:
        return MacroThesis(
            thesis_id=generate_id(), country="us", created_at=datetime.utcnow(),
            trade_idea=TradeIdea(
                instrument="NONE", direction="n/a", timeframe="n/a",
                sizing_logic="No position — see warnings for reason",
                stop_or_invalidation="n/a", catalysts=[],
            ),
            status=ThesisStatus.WATCH,
            warnings=[reason],
            # other fields populated with whatever partial view was formed,
        )

Five defects, all measured before any code was written (``.probe/p_d068_1.py``,
``.probe/p_d068_2.py``)
----------------------------------------------------------------------------------------

**1. The sample does not run.** ``MacroThesis`` declares ``regime``,
``growth_view``, ``inflation_view``, ``policy_view`` and ``market_pricing_gap``
as **required** (no default), plus ``convergence_classification``. Measured: the
sample body raises ``ValidationError`` naming **six** unset required fields. The
sample is not a simplification of the real call — it is a call that cannot
succeed, and the ``# other fields populated with whatever partial view was
formed`` comment is the tell: the author knew, and left the requirement as prose.

**2. One string slot for three triggers.** All three paths hand over a
``reason: str``. Whether two no-trade outcomes are distinguishable depends on
whether two *sentences* were written differently at two *call sites* — a
property of the author, not of the data. Measured: the three triggers produce
three strings today only because three different sentences were composed by
hand. Nothing in the returned object records **which Q fired**, so a consumer
that wants to count "how often do we stand down because of Q6 vs Q8" cannot.

**3. Each trigger already holds a rich object, and all three are discarded.**
Measured live: at the moment of each call there is an object carrying far more
than a sentence —

- **Q6** holds a ``MarketPricingGap`` with ``raw_gap``, ``dispersion`` and both
  implied values (the *magnitudes* that say how close the call was);
- **Q7** holds a ``ConfirmationSignalAssessment`` with the **full per-model
  direction table** and the agreeing/disagreeing/neutral census (measured:
  ``['confirms', 'confirms', 'confirms']``);
- **Q8** holds an ``InvalidationAssessment`` with ``unreadable[...]`` and
  ``neutral[...]``, each carrying *why* the input could not be read.

§16.4 keeps only the sentence. This is **D-067's defect 2** one function on —
*the output cannot attribute itself to its source* — and it is worse here
because the dropped object is the only record of **which of three very
different things happened**.

**4. "No reason" and "a reason" are the same value.** ``warnings=[reason]``.
Measured: ``warnings=[""]`` is **accepted** (an empty string is a list member),
and ``warnings=[]`` is **accepted**. So a caller that forgets to pass a reason
produces a fully-valid no-trade thesis whose explanation is empty, and *"we
stood down"*, *"we stood down and forgot to say why"*, and *"we stood down
because of an empty string"* are the **same object**. This is **D-066's shape**
(defect 4) reached from a third direction: one slot, three states.

**5. ``stop_or_invalidation="n/a"`` satisfies the very gate it is standing down
from.** Measured: ``"n/a".strip()`` is truthy. On a no-trade idea the LTCM gate
is skipped (``is_trade`` is False), so nothing breaks *today* — but the spec
writes a **truthy sentinel into the field the gate reads**, which means the
no-trade shape is one ``is_trade`` flip away from asserting a falsifier it does
not have. ``TradeIdea``'s own default is ``""``, and that is what this module
uses: on a no-trade, the honest value for "how would this be falsified" is
**nothing**, not ``"n/a"``.

What this module does instead of passing a sentence
---------------------------------------------------
The return type is a ``NoTradeDecision``, and the builder renders it into a
``MacroThesis``:

- ``trigger`` — a closed vocabulary (``NoTradeTrigger``) naming **which Q
  fired**: ``gap_below_dispersion`` / ``conflicted_signals`` /
  ``no_falsifier`` / ``caller``. A field, not a phrase, so it can be counted.
- ``reason`` — the human sentence §16.4 asks for, unchanged in role.
- ``evidence`` — the object the trigger already held, kept as a **typed
  union** so the caller hands over what it has rather than flattening it.
- ``elapsed`` — how far the trigger was from *not* firing, when the trigger has
  a magnitude (Q6 only). An absolute gap tells a reader nothing about whether it
  was 1bp short of meaningful or 200bp short.

The builder then writes ``trigger`` into the thesis's ``warnings`` as a labelled
line and the evidence summary into ``context``-style prose, so the published
``MacroThesis`` carries the trigger without a schema change (the six required
fields are all supplied by the caller).

Why the trigger is a closed vocabulary and not a free string
------------------------------------------------------------
O-29's lesson: a bare ``str`` lets a typo fall through, and the consumer that
wants to count by trigger silently gets an empty bucket. A ``Literal`` makes an
unlisted trigger a type error at the call site.

What this does NOT do
---------------------
- **It does not build the ``MacroThesis``.** §16.4's sample returns one; that
  requires the six required fields, which only ``build_us_macro_thesis`` has.
  Returning a decision object keeps the three triggers testable **without** a
  snapshot, which is why all three can be pinned offline. The builder's
  rendering is tested at the seam (O-70/O-79's class).
- **It does not re-derive which trigger fired.** The caller states it. A
  function that guessed from the reason string would be parsing prose to recover
  a fact the caller had in hand.
- **It does not choose the status.** §16.4 says ``WATCH``; ``ThesisStatus`` is
  carried on the decision so a future rule has one place to change it, and the
  value is asserted to be the spec's.
- **It does not put the reason in ``warnings`` as a bare string.** The label
  ``"No trade: <trigger> — <reason>"`` is written by the renderer, so the
  trigger survives into the published object and the free text cannot be
  mistaken for a model warning.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer.invalidation import InvalidationAssessment
from macro_engine.thesis_layer.schemas import MacroThesis, ThesisStatus, TradeIdea
from macro_engine.thesis_layer.signals import ConfirmationSignalAssessment

__all__ = [
    "NO_TRADE_INSTRUMENT",
    "NO_TRADE_TRIGGER_LABELS",
    "NoTradeDecision",
    "NoTradeEvidence",
    "NoTradeTrigger",
    "no_trade_thesis",
    "render_no_trade_thesis",
]

#: The instrument a stand-down reports (Section 16.4).
#:
#: Declared **here**, beside the trade idea that publishes it, rather than in the
#: builder: the no-trade shape is this module's, so the literal that makes a
#: stand-down recognisable has to live where it is written. A second declaration
#: elsewhere is a definition with no production consumer, and the two could drift
#: while every test still passed (measured during D-069).
NO_TRADE_INSTRUMENT = "NONE"

#: The closed vocabulary of reasons a thesis can be stood down (Section 16.2).
#:
#: One member per Q that routes to no-trade, plus ``caller`` for a stand-down
#: that happens outside the three documented gates (an operator, or a future
#: guard). ``caller`` exists so that "the three gates did not fire but we are
#: still not trading" is **sayable** — the alternative is a caller reusing one
#: of the three labels for a fourth situation, which is exactly defect 2.
#:
#: A ``Literal`` rather than a ``str``: an unlisted trigger is then a type error
#: at the call site instead of a new string nobody validates (O-29's lesson).
NoTradeTrigger = Literal[
    "gap_below_dispersion",
    "conflicted_signals",
    "no_falsifier",
    "caller",
]

#: Human-readable label per trigger, for the published ``warnings`` line.
#:
#: A ``dict`` keyed by the same ``Literal``, so a trigger added to the vocabulary
#: without a label is a ``KeyError`` in the census test rather than an
#: unlabelled warning on a real thesis.
NO_TRADE_TRIGGER_LABELS: dict[NoTradeTrigger, str] = {
    "gap_below_dispersion": "Q6: gap is inside the policy rules' own dispersion",
    "conflicted_signals": "Q7: growth and inflation signals directly contradict",
    "no_falsifier": "Q8: no evidence-based invalidation condition could be derived",
    "caller": "caller: stood down outside the three documented gates",
}

#: What a trigger held at the moment it fired, kept instead of flattened.
#:
#: A union rather than ``object`` for the same reason ``NoTradeTrigger`` is a
#: ``Literal``: ``object`` would accept a string, which is the thing this module
#: exists to stop discarding. ``None`` is a member because ``caller`` stands
#: down with no gate-specific object behind it, and pretending otherwise would
#: be the defect-4 conflation again.
NoTradeEvidence = MarketPricingGap | ConfirmationSignalAssessment | InvalidationAssessment | None


class NoTradeDecision(BaseModel):
    """The answer to "should there be a trade?" when the answer is no.

    Section 16.3's outcome, in the form that can be tested without a snapshot:
    **which** gate fired, **why** in one sentence, and **what** the gate was
    looking at. ``render_no_trade_thesis`` turns this into the published
    ``MacroThesis``.

    Frozen, like the other assessment objects (``InvalidationAssessment``), because
    a decision is a record rather than a working buffer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger: NoTradeTrigger = Field(
        description=(
            "Which Section 16.2 gate fired. A field so that no-trade outcomes can "
            "be counted by cause rather than searched by substring."
        )
    )
    reason: str = Field(
        description=(
            "The human sentence Section 16.4 calls `reason`. Must be non-empty: an "
            "empty reason is refused rather than accepted, because an unexplained "
            "stand-down and an explained one would otherwise be the same object."
        )
    )
    evidence: NoTradeEvidence = Field(
        default=None,
        description=(
            "The object the firing gate already held — the gap, the signal "
            "assessment, or the invalidation assessment. None only for `caller`."
        ),
    )
    elapsed: float | None = Field(
        default=None,
        description=(
            "For `gap_below_dispersion`: `dispersion - abs(raw_gap)`. How far "
            "INSIDE the noise floor the gap was, in the gap's own unit. A gap "
            "1bp short of meaningful and one 200bp short are both 'not "
            "meaningful' and are not the same situation; this is the field that "
            "distinguishes them. None when the trigger has no magnitude."
        ),
    )
    status: ThesisStatus = Field(
        default=ThesisStatus.WATCH,
        description=(
            "Section 16.4 sets WATCH for a no-trade. Carried so a future rule has "
            "one place to change."
        ),
    )

    def warning_line(self) -> str:
        """The labelled line the renderer writes into ``MacroThesis.warnings``.

        The label is prepended rather than concatenated so the trigger survives
        into the published object: a consumer reading ``warnings`` can tell a
        stand-down from a model warning and can tell *which* stand-down, without
        parsing the sentence (defect 2).
        """
        return f"No trade [{self.trigger}] ({NO_TRADE_TRIGGER_LABELS[self.trigger]}): {self.reason}"

    @property
    def is_marginal(self) -> bool:
        """Whether the stand-down was close to not happening.

        Only meaningful for ``gap_below_dispersion``: a gap that missed the
        significance bar by a hair is a very different signal-to-noise story
        from one that missed it by a mile, and ``elapsed`` is small in the first
        case. ``None`` elapsed returns ``False`` because "not close" is the safe
        reading when the question does not apply — publishing ``True`` would
        invent a near-miss.

        The comparison is in **basis points**, converted explicitly from the
        percentage points ``elapsed`` carries. This is not cosmetic: the previous
        implementation compared the pp shortfall against the literal ``1e-9``,
        which is ``1e-11`` bp — unreachable, because ``raw_gap`` is rounded to 4
        decimals upstream and a shortfall that small cannot occur. Every real
        stand-down therefore reported ``is_marginal=False`` and the near-miss
        distinction this field exists to draw could never fire. The tolerance now
        lives in config (``policy.ensemble.near_miss_tolerance_bp``) so it is a
        reviewable judgement rather than a buried constant, and the ``* 100`` is
        the same unit conversion the ensemble's own bands use.
        """
        if self.elapsed is None:
            return False
        tolerance_bp = get_settings().policy.ensemble.near_miss_tolerance_bp_value
        return 0.0 <= self.elapsed * 100.0 <= tolerance_bp


class _Rendered(NamedTuple):
    """Internal: the parts of the published thesis this module is responsible for."""

    trade_idea: TradeIdea
    warnings: list[str]
    status: ThesisStatus


def _build_no_trade_trade_idea() -> TradeIdea:
    """The ``TradeIdea`` for a stand-down, built the way ``TradeIdea`` wants.

    Two deliberate differences from §16.4's sample, both measured defects:

    - ``stop_or_invalidation`` is **``""``, not ``"n/a"``**. Measured: ``"n/a"``
      is truthy, so it would satisfy the LTCM gate if ``is_trade`` ever flipped.
      ``TradeIdea``'s own default is ``""`` for exactly this reason, and on a
      no-trade the honest answer to "how would this be falsified" is *nothing*.
    - ``sizing_logic`` says what the object is, not where to look for the reason.
      §16.4 writes *"No position — see warnings for reason"*, which sends the
      reader to a list this function has already labelled; the reason is now on
      the decision object itself, so the field can state the fact.
    """
    return TradeIdea(
        instrument=NO_TRADE_INSTRUMENT,
        direction="n/a",
        timeframe="n/a",
        sizing_logic="No position — no clean edge, see warnings for the trigger",
        stop_or_invalidation="",
        catalysts=[],
    )


def no_trade_thesis(
    reason: str,
    *,
    trigger: NoTradeTrigger,
    evidence: NoTradeEvidence = None,
    gap: MarketPricingGap | None = None,
) -> NoTradeDecision:
    """Stand a thesis down, recording **which** gate fired and **what** it saw.

    ``reason`` is Section 16.4's parameter and keeps its meaning: one sentence a
    human reads. ``trigger`` is the field the sample lacks and the reason this
    module exists — without it, *"we stood down for Q6"* and *"we stood down for
    Q8"* are the same value (defect 2).

    ``gap`` is optional and only read for ``gap_below_dispersion``, where it
    supplies ``elapsed`` — how far inside the noise floor the gap sat. Passing it
    for another trigger is allowed and ignored, because requiring the caller to
    remember which triggers take which argument is how a required argument gets
    passed by reflex.

    Raises
    ------
    ValueError
        If ``reason`` is empty or whitespace. **This is the repair for defect
        4**: §16.4's ``warnings=[reason]`` accepts ``""`` and produces a valid
        thesis whose explanation is blank, so *"stood down"* and *"stood down
        and forgot to say why"* are the same object. Refusing an empty reason is
        the only place that can be caught, because by the time a ``MacroThesis``
        exists the emptiness is indistinguishable from a short answer.
    """
    stripped = reason.strip()
    if not stripped:
        raise ValueError(
            "no_trade_thesis: reason must be a non-empty sentence. Section 16.4's "
            "sample builds `warnings=[reason]`, which accepts an empty string, so a "
            "caller that forgot a reason produced a valid stand-down with a blank "
            "explanation — and 'we stood down' became indistinguishable from 'we "
            "stood down and cannot say why'. Pass a sentence, or use trigger="
            "'caller' with a description of what the operator decided."
        )

    elapsed: float | None = None
    if trigger == "gap_below_dispersion":
        if gap is None:
            raise ValueError(
                "no_trade_thesis: trigger='gap_below_dispersion' requires the `gap` "
                "argument, because the whole point of this trigger is HOW FAR inside "
                "the noise floor the gap sat (Section 16.2 Q6). Without it, a gap 1bp "
                "short of meaningful and one 200bp short are the same decision."
            )
        elapsed = gap.dispersion - abs(gap.raw_gap)
        if evidence is None:
            evidence = gap

    return NoTradeDecision(
        trigger=trigger,
        reason=stripped,
        evidence=evidence,
        elapsed=elapsed,
    )


def render_no_trade_thesis(decision: NoTradeDecision, **thesis_fields: object) -> MacroThesis:
    """Render a ``NoTradeDecision`` into the published ``MacroThesis``.

    The caller supplies the six required ``MacroThesis`` fields (``regime``,
    ``growth_view``, ``inflation_view``, ``policy_view``, ``market_pricing_gap``
    and ``convergence_classification``) as keyword arguments, because this
    module has no snapshot and inventing them would be publishing a partial view
    that never existed (defect 1's ``# other fields populated with whatever
    partial view was formed`` is precisely that invention).

    ``trade_idea``, ``status`` and ``warnings`` are set here and **must not** be
    passed: a caller overriding the no-trade shape would defeat the module, and
    the error says so rather than silently winning.

    The trigger line is written **first** in ``warnings``, so a reader sees the
    stand-down before the caveats it is made of.
    """
    reserved = {"trade_idea", "status", "warnings"}
    clashes = sorted(reserved & thesis_fields.keys())
    if clashes:
        raise ValueError(
            f"render_no_trade_thesis: {clashes} are set by this function and must "
            f"not be passed. They are the no-trade shape itself — a caller that "
            f"overrides them would produce a thesis whose trade_idea is not the "
            f"stand-down its trigger describes."
        )

    rendered = _Rendered(
        trade_idea=_build_no_trade_trade_idea(),
        warnings=[decision.warning_line()],
        status=decision.status,
    )

    return MacroThesis(
        trade_idea=rendered.trade_idea,
        status=rendered.status,
        warnings=rendered.warnings,
        **thesis_fields,  # type: ignore[arg-type]
    )
