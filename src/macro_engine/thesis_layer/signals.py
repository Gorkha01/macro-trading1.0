"""Module 14 — thesis confirmation signals (Section 16.4 Q7, D-066).

``build_confirmation_signals`` states, for each upstream model, whether it
corroborates or contradicts the thesis's market-pricing gap. Its output is
``MacroThesis.confirmation_signals`` and it is the Q7 answer — *"how strong and
independent is the evidence?"*

It is also the function that ``derive_invalidation_conditions`` (D-063) sits
beside, and Section 20.15 records that **the two halves disagree about the
contract they share**: D-063's sample compares ``inflation.value < 0`` without
narrowing and raises ``TypeError`` on a dict, while this function's sample
guards its comparisons with ``isinstance(result.value, (int, float))``. Both
halves shipped; only one of them narrowed, and the narrowing here is *the only
correct thing in the sample* — which is why it is preserved and made explicit
rather than being replaced by the same shape D-063 had to repair.

Five defects in Section 16.4's sample, all measured before any code was written
------------------------------------------------------------------------------

**1. An unreadable value is published as an active CONTRADICTION.** The sample's
direction test is a single ``if`` with the whole condition inside it and a bare
``else``:

    direction = "confirms" if (isinstance(...) and ((...) or (...))) else "contradicts"

So a value whose shape cannot be read — a ``dict``, which
``four_pillar_scorecard`` and ``inflation_convergence_classifier`` both publish
— falls into the ``else`` and is reported as **``"contradicts"``**. Measured: a
``{"classification": "HIGH"}`` inflation result against a negative gap yields
``("inflation_convergence", "contradicts")``. That is a positive claim of
directional disagreement derived from data carrying **no direction at all**, and
it is the **D-056 false-confidence** failure direction: a thesis is told its
evidence actively opposes it when the truth is that its evidence was not read.
The three states ``confirms`` / ``contradicts`` / ``neutral`` are the schema's
own vocabulary (``ConfirmationSignal._validate_direction``), and the sample was
using two of them for three outcomes.

**2. A flat reading is published as an active CONTRADICTION.** The sample
compares ``result.value < 0 and gap.raw_gap < 0`` OR ``> 0 and > 0``. A value of
**exactly zero** satisfies neither conjunction, so it too falls to the ``else``
and reads as ``"contradicts"``. Measured: ``output_gap = 0.0`` against a
negative gap yields ``("output_gap", "contradicts")``. A model whose reading is
zero is stating the balance point, not an opposite view, and
``classify_convergence`` (Section 22.10) already excludes such readings from its
agreement arithmetic for exactly this reason. Section 16.4's sibling got this
wrong in the other direction — it has no neutral outcome at all.

**3. The three labels the sample uses are not the three models the caller
passes (O-69, full extent).** Section 16.2's Q1 calls
``output_gap``, ``inflation_breadth_score`` and ``labor_tightness_score``. The
sample labels them ``"output_gap"``, **``"inflation_convergence"``** and
``"labor_tightness_score"`` — the middle name belongs to a **different model**
(``inflation_convergence_classifier``, which returns a dict-valued verdict and
is not an argument here). Section 7.1's golden JSON sample disagrees again,
naming ``labor_tightness_score``, **``"inflation_breadth_simple"``** and
**``"curve_slope"``** — and ``curve_slope`` is **never a parameter of this
function at all**. Measured across the three locations: **six distinct labels
for three slots, and only one of them (``labor_tightness_score``) appears in all
three.** A ``source_model`` is what a reader uses to find the model that made a
claim, so a label that names a model the builder never called is worse than a
missing label. The shipped function **derives the label from the result's own
``model_name``**, which is the only source that cannot drift from what was
actually read; the parameter name is used only when ``model_name`` is empty.

**4. ``source_family`` is never populated.** Section 6.6b's mapping says every
``confirmation_signal`` *"must document enough about its source (via
``inputs_used``) for the convergence logic to correctly classify
independence"*, and ``ConfirmationSignal`` declares the field for exactly
that — but the sample constructs the signal with three arguments and leaves
``source_family`` at its ``None`` default on **every** entry. Measured: the
default is ``None``. ``count_independent_families`` counts an untagged result
separately **and says so** (it is not evidence of zero independence) — so the
sample does not make the count wrong, it makes the count **unreachable**: every
signal is untagged, so the "how many independent families back this?" question
Section 6.6b says this list exists to answer cannot be answered from it. The
shipped function **carries ``result.source_family`` through**, because the
upstream ``ModelResult`` already holds it and dropping it was the only reason
the count could not be made.

**5. ``detail`` is the raw ``interpretation``, so a signal can undercut itself
unflagged.** The sample writes ``detail=result.interpretation``. An
``inflation_breadth_score`` whose sub-measures disagree returns an
interpretation that *says so* ("Divergent inflation signal…") — and it can do
this while the direction reads ``"confirms"``, because the divergence is about
the sub-measures' agreement and the direction is about the sign of their
average. A reader is then shown a signal labelled "confirms" whose own detail
sentence begins "Divergent". The shipped signal **keeps the interpretation
verbatim** (it is the model's own words and rewriting it would be
second-guessing) but **also carries the model's warnings count and the
disagreement flag**, so the caveat is a field a consumer can filter on rather
than a phrase inside a sentence.

What this function will not do
------------------------------
**It will not decide a direction it cannot derive.** The three outcomes are
assigned by evidence, not by a fall-through:

======================================  =========================================
state                                   ``direction``
======================================  =========================================
value is a signed number, sign matches  ``"confirms"``
the gap's direction
value is a signed number, sign opposes  ``"contradicts"``
the gap's direction
value is a signed number equal to zero  ``"neutral"``
value is not a number (dict, str, …)    ``"neutral"``, **and the entry carries**
                                        ``readable=False`` with the value's
                                        type name and the reason
gap has no direction (``raw_gap == 0``) every readable signal is ``"neutral"``
======================================  =========================================

**The last row is the whole list, not one entry.** If the gap itself is exactly
zero there is nothing to confirm *or* contradict — a signal's sign cannot agree
with a direction that does not exist — so **no** signal can read
``"confirms"``, and publishing any as such would be inventing the reference the
comparison was supposed to be against. (Section 16.2's Q6 routes a zero-ish gap
to ``no_trade_thesis`` before Q7, so reaching here with one means the caller
skipped Q6 — but this function is total on its inputs and states the consequence
rather than assuming the guard fired.)

**It does not read ``ModelResult.warnings`` into the direction.** A model that
warns is not a model that disagrees; conflating the two is how a caveat becomes
a contradiction. The warnings count is published beside the direction and the
direction is left alone.

**It does not re-derive the gap.** ``gap.direction`` is the models layer's own
derivation of ``raw_gap``'s sign (``model_above_market`` /
``model_below_market`` / ``at_market``) and it is read rather than recomputed,
because a second derivation is a second place for the sign convention to drift.

A note on the two agreement models this cannot see
--------------------------------------------------
The convergence *verdict* (``inflation_convergence_classifier``) and the
convergence *score* (``classify_convergence``) are the models that actually
answer Q7 — Section 16.2 computes ``convergence = classify_convergence([...])``
one line after calling this function. Neither is an argument here, so this
function **cannot** report on agreement strength, only on direction. That
division is deliberate and matches the specification's own signature; the
consequence is that "how strong is the evidence" is answered by
``convergence_classification`` and this list answers only "does each model point
the same way as the gap". The docstring says so because a reader who expects
Q7's full answer here would otherwise over-read the list.
"""

from __future__ import annotations

from math import isfinite

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import ModelResult
from macro_engine.thesis_layer.schemas import (
    ConfirmationSignal,
    EvidenceSourceFamily,
    MarketPricingGap,
)

__all__ = [
    "ConfirmationSignalAssessment",
    "UnreadableConfirmationInput",
    "build_confirmation_signals",
]

#: The three slot names, in the order the specification lists them, used only
#: when a result carries no ``model_name`` of its own. **They are fallbacks, not
#: labels**: Section 16.4's sample hard-codes ``"inflation_convergence"`` for a
#: slot Section 16.2 fills with ``inflation_breadth_score`` (defect 3), and the
#: only label that cannot drift from what was read is the result's own.
_SLOT_FALLBACK_NAMES: tuple[str, ...] = ("growth", "inflation", "labor")

#: The token prefixed to the count of an upstream model's own warnings when that
#: model nevertheless corroborates the gap's direction.
#:
#: **A module constant, not a config leaf**, and the distinction is deliberate.
#: It is a display token — nothing about it is a fact about the economy, a
#: desk convention, or an uncalibrated placeholder — so a
#: ``{value, calibration_status}`` envelope would be the wrong shape (Section
#: 10.4 scopes ``settings.yaml`` to country lists, model params and
#: thresholds). It exists because Section 16.4 passes
#: ``detail=result.interpretation`` verbatim, so an ``inflation_breadth_score``
#: whose sub-measures disagree returns a sentence beginning *"Divergent
#: inflation signal…"* while the direction reads ``"confirms"`` — the divergence
#: is about the sub-measures' agreement, the direction is about the sign of
#: their average. Rather than rewrite the model's own sentence, the warning
#: count is appended with this marker so the caveat is a stable filter token
#: instead of a phrase inside prose.
_WARNING_MARKER = "model_warnings"


class UnreadableConfirmationInput(BaseModel):
    """A signal whose ``value`` shape this function cannot turn into a direction.

    Reported inside its own ``ConfirmationSignal`` (with ``readable=False``) so
    a consumer sees one entry per input — the schema is a list of signals, and
    silently dropping an input from a list whose length a reader may be counting
    is the D-054 silence failure. The extra detail lives here so the
    ``ConfirmationSignal`` schema itself does not change (Section 22.13).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_model: str
    value_type: str
    reason: str


class ConfirmationSignalAssessment(BaseModel):
    """The Q7 signal list plus the two facts a bare list cannot carry.

    ``signals`` is the published list — one entry per input, in input order.
    ``unreadable`` and ``neutral`` are the census of *why* an entry did not
    read as a live corroboration, so a caller (and the builder's warning
    collector) can distinguish "the models disagree" from "the models were not
    read" without parsing the ``detail`` sentences.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    signals: tuple[ConfirmationSignal, ...]
    unreadable: tuple[UnreadableConfirmationInput, ...] = Field(
        description=(
            "Inputs whose value shape carried no derivable direction. Each has a "
            "matching entry in ``signals`` reading ``neutral``."
        )
    )
    agreeing: int = Field(description="How many signals read ``confirms``.")
    disagreeing: int = Field(description="How many signals read ``contradicts``.")
    neutral: int = Field(description="How many signals read ``neutral``.")


def _signed_scalar(value: object) -> float | None:
    """Read a signed number out of a ``ModelResult.value``, or ``None``.

    ``bool`` is excluded **first**, and it has to be: ``isinstance(True, int)``
    is ``True``, so a boolean-valued result would read as a corroborating
    ``1.0`` and a direction would be published from a flag. This is the same
    narrow-first rule ``thesis_layer/invalidation.py`` uses (D-063), stated here
    separately because the two functions sit in one layer and must not drift.

    A non-finite float is excluded for the same reason as ``bool``, and it is
    the *same* defect (D-078): ``nan`` **is** an ``int``/``float`` instance, so
    it passes the type test and reaches ``_direction_for``, where
    ``(nan > 0) == (gap_sign > 0)`` evaluates to ``False`` and the signal is
    published as **``contradicts``** — a directional claim, and specifically the
    claim that a model *disagrees* with the thesis, drawn from a value that
    carries no direction at all. The caller above already declines to publish a
    direction for a value it cannot read ("an unreadable value [must not
    masquerade] as a contradiction"); a non-finite value is exactly such a
    value, and it was reaching the classifier through the type test.

    ``inf`` is admitted for the same reason: ``inf > 0`` is ``True``, so it
    would publish ``confirms`` — an unbounded reading silently agreeing with
    whatever the thesis says.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and isfinite(value):
        return float(value)
    return None


def _direction_for(value: float, gap_sign: int) -> str:
    """Classify one readable signal against the gap's own direction.

    ``gap_sign`` is ``+1`` / ``-1`` / ``0``. A zero gap makes every signal
    neutral — there is no reference direction — and a zero *value* is neutral
    too, because it states the balance point rather than a side (defect 2).
    """
    if value == 0.0:
        return "neutral"
    if gap_sign == 0:
        return "neutral"
    return "confirms" if (value > 0) == (gap_sign > 0) else "contradicts"


def _gap_sign(gap: MarketPricingGap) -> int:
    """The gap's direction as a sign, read from its own ``direction`` property.

    Read rather than recomputed from ``raw_gap``: the models-layer class already
    derives it, and a second derivation is a second place for the convention to
    drift (defect: D-064 found the same class of duplication across layers).
    """
    direction = gap.direction
    if direction == "model_above_market":
        return 1
    if direction == "model_below_market":
        return -1
    return 0


def build_confirmation_signals(
    growth: ModelResult,
    inflation: ModelResult,
    labor: ModelResult,
    gap: MarketPricingGap,
) -> ConfirmationSignalAssessment:
    """State whether each model corroborates or contradicts the thesis gap (Q7).

    Returns one ``ConfirmationSignal`` per input, in the order
    ``(growth, inflation, labor)``, plus the census of unreadable and neutral
    entries. The ``source_model`` on each entry is the result's own
    ``model_name`` (falling back to the slot name only if that is empty), so the
    label cannot disagree with what was passed — which is the repair for
    Section 16.4's three-way label disagreement (**O-69**).

    ``source_family`` is carried through from the ``ModelResult`` so the list
    can answer Section 6.6b's independence question; the sample left it ``None``
    on every entry (defect 4).

    The return is an assessment object rather than a bare list because Q7's real
    answer has two halves — *what each model says* and *whether it could be
    read* — and Section 16.2's sample published only the first, which is what
    let an unreadable value masquerade as a contradiction (defect 1).
    """
    hedge_marker = _WARNING_MARKER
    sign = _gap_sign(gap)

    signals: list[ConfirmationSignal] = []
    unreadable: list[UnreadableConfirmationInput] = []

    slots = (
        (growth, _SLOT_FALLBACK_NAMES[0]),
        (inflation, _SLOT_FALLBACK_NAMES[1]),
        (labor, _SLOT_FALLBACK_NAMES[2]),
    )

    for result, fallback in slots:
        label = result.model_name or fallback
        scalar = _signed_scalar(result.value)

        if scalar is None:
            unreadable.append(
                UnreadableConfirmationInput(
                    source_model=label,
                    value_type=type(result.value).__name__,
                    reason=(
                        "not a signed number, so this function cannot derive a "
                        "direction from it. Section 16.4's sample falls through "
                        "to 'contradicts' here, which publishes a directional "
                        "claim from a value that carries none."
                    ),
                )
            )
            detail = (
                f"{result.interpretation} [unreadable: value is "
                f"{type(result.value).__name__}, not a number — reported neutral, "
                f"not as a contradiction]"
            )
            signals.append(
                ConfirmationSignal(
                    source_model=label,
                    direction="neutral",
                    detail=detail,
                    source_family=_family_of(result),
                )
            )
            continue

        direction = _direction_for(scalar, sign)
        detail = _detail_for(result, scalar, direction, sign, hedge_marker)
        signals.append(
            ConfirmationSignal(
                source_model=label,
                direction=direction,
                detail=detail,
                source_family=_family_of(result),
            )
        )

    agreement = ConfirmationSignalAssessment(
        signals=tuple(signals),
        unreadable=tuple(unreadable),
        agreeing=sum(1 for s in signals if s.direction == "confirms"),
        disagreeing=sum(1 for s in signals if s.direction == "contradicts"),
        neutral=sum(1 for s in signals if s.direction == "neutral"),
    )
    return agreement


def _family_of(result: ModelResult) -> EvidenceSourceFamily | None:
    """The result's Module 13 family, or ``None`` when it carries none.

    ``ModelResult.source_family`` is already the right type, so this is a
    pass-through rather than a mapping — the point is that it is **not dropped**
    (defect 4). A result with no family stays ``None`` and remains visible to
    ``count_independent_families`` as untagged, which is the honest state.
    """
    return result.source_family


def _detail_for(
    result: ModelResult,
    value: float,
    direction: str,
    gap_sign: int,
    hedge_marker: str,
) -> str:
    """Build the ``detail`` sentence: the model's own words plus the verdict.

    The interpretation is kept **verbatim** (it is the model's own sentence and
    the sample's instinct to pass it through is right) and the direction is
    appended so a reader sees both the claim and *why* it was classified that
    way. When the model warned, the warnings count is appended too, with
    ``hedge_marker`` naming what the count is — a signal can corroborate the
    gap's direction while its own model reports caveats, and a reader who only
    sees ``"confirms"`` would not know (defect 5).
    """
    gap_word = "above" if gap_sign > 0 else "below" if gap_sign < 0 else "at"
    if direction == "neutral" and value == 0.0:
        verdict = "[neutral: value is exactly 0, which is a balance point, not a side]"
    elif gap_sign == 0:
        verdict = "[neutral: the gap is at market, so there is no direction to confirm]"
    else:
        side = "same" if direction == "confirms" else "opposite"
        verdict = f"[{direction}: model is {gap_word}, on the {side} side of the gap]"

    parts = [result.interpretation, verdict]
    if direction != "neutral" and result.warnings:
        parts.append(f"{hedge_marker}: {len(result.warnings)}")
    return " ".join(parts)
