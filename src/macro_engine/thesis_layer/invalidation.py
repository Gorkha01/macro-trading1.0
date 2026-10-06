"""Module 14 — thesis invalidation, and the LTCM-lesson hard gate (D-063).

Section 20.15's ``derive_invalidation_conditions`` decides what would falsify a
thesis. Its output is the one thing that lands in
``TradeIdea.stop_or_invalidation``, which the schema **refuses to leave empty for
a live trade** — *"a position without a stated falsifier is a position that
cannot be exited"*.

Four defects in the sample, all measured before any code was written
--------------------------------------------------------------------

**1. It raises `TypeError` on the output its own sibling produces.** The sample
writes ``if inflation.value < 0``. ``ModelResult.value`` is a union, and
``inflation_convergence_classifier`` publishes a **``dict``**
(``InflationConvergenceVerdict(...).model_dump()``), so the comparison is
``dict < int``:

    TypeError: '<' not supported between instances of 'dict' and 'int'

The same section's ``build_confirmation_signals`` guards its comparisons with
``isinstance(result.value, (int, float))``. ``derive_invalidation_conditions``
does not — **the two halves of §16.4 disagree about the contract they share.**

**2. ``growth`` is declared and never read.** Three parameters, two branches.

**3. The fallback sentence SATISFIES the gate it says is unmet.** The gate is
``not self.stop_or_invalidation.strip()``; the sample's fallback —
*"No clear evidence-based invalidation condition identified — DO NOT promote this
thesis past DRAFT"* — is **non-empty**, so a live trade whose stated falsifier is
*"no falsifier was found"* passes. Measured: ``TradeIdea`` accepts it.

**4. The model the sample NAMES cannot express the condition it names.** It
attributes *"broad-based reacceleration"* to ``inflation_convergence_classifier``,
whose verdict vocabulary is ``HIGH / MEDIUM / LOW / CONFLICTED`` and whose
``agreeing`` field is the majority **count**, not the majority **side**. A
``HIGH`` verdict is equally compatible with six measures agreeing *down* and with
six agreeing *up*: the verdict is **direction-blind**, so "reacceleration" is not
computable from it at all.

What ships instead
------------------
The narrowing is explicit, the two falsifier *forms* are distinguished, and the
identified/not-identified split is a typed field rather than a sentence:

* A **signed** signal falsifies by **reversing** — ``crosses_back_positive`` or
  ``crosses_back_negative``, chosen by its current sign. **Both signs produce a
  condition**, which is the repair for defect 2's sibling problem: the sample's
  two ``< 0`` tests can only ever describe a thesis leaning on *loosening* and
  *disinflation*, so a thesis leaning on tightening has no falsifier at all.
* An **agreement** classifier falsifies by its agreement **collapsing** — the
  only falsifier that model can support.
* A signal sitting **exactly on** the crossing, or an agreement verdict that
  never supported the thesis, produces **no** condition. Absence of direction is
  not evidence for either side, which is the same principle the classifier
  states for its own flat readings.
* A value whose shape cannot be read is **reported**, never crashed on and never
  silently skipped.

And ``text`` is **empty when nothing was identified**, so the schema's existing
gate fires and the builder must route to ``no_trade_thesis`` — which is what
defect 3's fallback sentence was *asking for* and could not enforce.

What this cannot do
-------------------
**It cannot tell whether a condition is the RIGHT one.** It states the falsifier
implied by each signal's own sign; whether that signal is the one the thesis
actually leans on is a judgement the caller makes when it decides the thesis
direction. The output names its model and its threshold so the judgement is
checkable, not so it is automated.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.inflation_convergence import CONVERGENCE_CLASSES

__all__ = [
    "InvalidationAssessment",
    "InvalidationCondition",
    "InvalidationTrigger",
    "UnreadableInput",
    "derive_invalidation_conditions",
]


#: How a signal can falsify a thesis.
#:
#: ``crosses_back_positive`` / ``crosses_back_negative`` are the two directions a
#: **signed** signal can reverse in, and they are a partition of the sign axis —
#: a signal at exactly the crossing produces neither, because there is no
#: direction to reverse *from*. ``agreement_collapses`` is the only falsifier an
#: **agreement** classifier can support, and it is a different *form*: a loss of
#: breadth, not a sign flip.
InvalidationTrigger = Literal[
    "crosses_back_positive",
    "crosses_back_negative",
    "agreement_collapses",
]

#: Runtime-iterable mirror of :data:`InvalidationTrigger`, so a test can assert
#: the declared vocabulary and the producible one agree (D-045a's two halves).
_TRIGGERS: tuple[str, ...] = get_args(InvalidationTrigger)


class InvalidationCondition(BaseModel):
    """One falsifier, with everything needed to recompute it.

    ``model_name``, ``observed_value`` and ``threshold`` exist so a reader can
    check the condition against the model's own output instead of trusting a
    sentence. Section 20.15's prose conditions carry none of the three — the
    parenthetical *"(claims fall, JOLTS openings stabilize)"* is not the same
    test as *"the score reverses positive"*, and neither is checkable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = Field(description="Which upstream model this condition reads.")
    trigger: InvalidationTrigger
    observed_value: str = Field(description="The value as read, rendered for a reader.")
    threshold: float | None = Field(
        default=None,
        description=(
            "The level the signal must cross. ``None`` for an agreement trigger, "
            "which has a verdict band rather than a number."
        ),
    )
    statement: str = Field(description="The sentence that reaches stop_or_invalidation.")


class UnreadableInput(BaseModel):
    """An input whose ``value`` shape this function cannot narrow.

    Reported rather than skipped or crashed on. A ``ModelResult`` carries a
    union, so "which shapes are readable" is part of this function's contract and
    must be visible in its output when it is not met.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str
    value_type: str
    reason: str


class InvalidationAssessment(BaseModel):
    """The Q8 answer: what would falsify this thesis, and whether anything does.

    ``identified`` is the field the LTCM gate needs and a prose string cannot
    carry. ``text`` is deliberately **empty** when ``identified`` is False, so
    ``TradeIdea``'s existing validator fires instead of accepting a sentence that
    says no falsifier was found (Section 20.15 defect 3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    conditions: tuple[InvalidationCondition, ...]
    unreadable: tuple[UnreadableInput, ...]
    neutral: tuple[str, ...] = Field(
        description=(
            "Inputs that were read but carry no direction — a signal sitting "
            "exactly on the crossing, or an agreement verdict that never "
            "supported the thesis. Absence of direction is not evidence."
        )
    )
    text: str = Field(
        description=(
            "The `OR`-joined falsifiers for `TradeIdea.stop_or_invalidation`, or "
            "the EMPTY STRING when none was identified."
        )
    )
    identified: bool
    reason: str = Field(description="Why nothing was identified; for no_trade_thesis().")
    as_of: datetime


def _signed_scalar(value: object) -> float | None:
    """Read a signed number out of a ``ModelResult.value``, or ``None``.

    ``bool`` is excluded **first**, and it has to be: ``isinstance(True, int)`` is
    ``True``, so a boolean-valued result would otherwise read as a tightness
    score of ``1.0`` and produce a confident falsifier from a flag.

    A non-finite float is excluded for the same reason as ``bool``, and it is the
    *same* defect (D-078, and the drift D-063 warns against): ``nan`` **is** an
    ``int``/``float`` instance, so it passed the type test and reached
    ``_condition_for_scalar``, where ``nan > crossing`` and ``nan < crossing`` are
    both ``False`` and the branch fell through to ``None`` — reporting the input
    as **neutral**, i.e. "sits exactly on the crossing", from a value that was
    never computed. ``inf`` was worse: ``inf > crossing`` is ``True``, so it
    emitted a confident ``crosses_back_negative`` falsifier ("crosses back below
    0.5") from an unbounded reading. Both were published on the
    ``InvalidationAssessment`` and reached the no-trade decision's evidence.

    This function and ``thesis_layer/signals.py``'s ``_signed_scalar`` are
    deliberately identical twins, and its docstring states the rule: the two
    "sit in one layer and must not drift". The rule exists because the drift
    happened — the ``isfinite`` guard reached this file later than the signals
    twin. MEASURED 2026-10-06: **both copies now carry it.** (An earlier note
    here read "was **not** mirrored here", which described the state *before*
    that repair and would send a reader looking for a guard that is already
    present.) Any change to either guard belongs in both, and
    ``tests/thesis_layer/test_signed_scalar_parity.py`` fails if they disagree.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and isfinite(value):
        return float(value)
    return None


def _agreement_class(value: object) -> str | None:
    """Read a convergence verdict out of a dict-valued result, or ``None``.

    The membership test is against the classifier's **own** published
    vocabulary rather than a re-typed list, so a verdict the classifier adds
    without this function learning about it is reported as unreadable instead of
    being silently accepted as agreement.
    """
    if not isinstance(value, dict):
        return None
    classification = value.get("classification")
    if isinstance(classification, str) and classification in CONVERGENCE_CLASSES:
        return classification
    return None


def _condition_for_scalar(
    model_name: str, value: float, crossing: float
) -> InvalidationCondition | None:
    """A signed signal falsifies by crossing back over ``crossing``.

    Returns ``None`` when the value **is** the crossing: a signal at exactly the
    balance point has no direction to reverse from, and inventing one would be
    reporting absence of evidence as evidence.

    ``value`` is required to be finite. That is an **assumption, not a check**:
    ``_signed_scalar`` is the only caller and it refuses ``nan``/``inf``, so the
    assumption holds by construction — but this function has no guard of its own.
    The distinction it relies on is not cosmetic: a finite value equal to
    ``crossing`` is a *measurement* at the balance point, whereas a non-finite
    value is a missing measurement that must never reach here and be rendered as
    one.
    """
    if value > crossing:
        trigger: InvalidationTrigger = "crosses_back_negative"
        statement = f"{model_name} crosses back below {crossing:g} (currently {value:+g})"
    elif value < crossing:
        trigger = "crosses_back_positive"
        statement = f"{model_name} crosses back above {crossing:g} (currently {value:+g})"
    else:
        return None
    return InvalidationCondition(
        model_name=model_name,
        trigger=trigger,
        observed_value=f"{value:+g}",
        threshold=crossing,
        statement=statement,
    )


def derive_invalidation_conditions(
    growth: ModelResult, inflation: ModelResult, labor: ModelResult
) -> InvalidationAssessment:
    """State what would falsify a thesis, in evidence terms rather than price terms.

    Module 14 / Section 16.2 Q8, and Section 15 Module 1's LTCM lesson: the
    falsifier is a **change in the evidence**, never a price level. A price stop
    tells you the position is losing; it does not tell you the *thesis* is wrong,
    and conflating the two is how a correct thesis is abandoned at its worst
    moment (and how an incorrect one is held).

    All three inputs are read symmetrically — see the module docstring for why
    that is a repair rather than an embellishment.
    """
    settings = get_settings().invalidation
    crossing = settings.crossing
    supporting = settings.agreement_class_supporting_a_thesis

    conditions: list[InvalidationCondition] = []
    unreadable: list[UnreadableInput] = []
    neutral: list[str] = []

    for role, result in (("growth", growth), ("inflation", inflation), ("labor", labor)):
        label = result.model_name or role
        scalar = _signed_scalar(result.value)
        if scalar is not None:
            condition = _condition_for_scalar(label, scalar, crossing)
            if condition is None:
                neutral.append(
                    f"{label} sits exactly on the crossing {crossing:g}; there is "
                    f"no direction to reverse from"
                )
            else:
                conditions.append(condition)
            continue

        agreement = _agreement_class(result.value)
        if agreement is not None:
            if agreement == supporting:
                conditions.append(
                    InvalidationCondition(
                        model_name=label,
                        trigger="agreement_collapses",
                        observed_value=agreement,
                        threshold=None,
                        statement=(
                            f"{label} agreement falls below {supporting} (currently {agreement})"
                        ),
                    )
                )
            else:
                neutral.append(
                    f"{label} reports {agreement}, which is not {supporting}: the "
                    f"thesis was never resting on broad agreement, so its collapse "
                    f"is not a falsifier here"
                )
            continue

        unreadable.append(
            UnreadableInput(
                model_name=label,
                value_type=type(result.value).__name__,
                reason=(
                    "not a signed number and not a convergence verdict dict, so "
                    "this function cannot derive a falsifier from it. Section "
                    "20.15 compares `value < 0` without narrowing, which raises "
                    "TypeError on a dict-valued result."
                ),
            )
        )

    text = " OR ".join(c.statement for c in conditions)
    identified = bool(conditions)

    if identified:
        reason = ""
    elif unreadable:
        names = ", ".join(u.model_name for u in unreadable)
        reason = (
            f"No evidence-based invalidation condition could be derived: "
            f"{len(unreadable)} of 3 inputs ({names}) carried a value shape this "
            f"function cannot read. Do not promote this thesis past DRAFT "
            f"(Module 14 Q8)."
        )
    else:
        reason = (
            "No evidence-based invalidation condition could be derived: every "
            "input was read and none of them carries a direction, so there is "
            "nothing whose reversal would falsify the thesis. Do not promote "
            "this thesis past DRAFT (Module 14 Q8)."
        )

    return InvalidationAssessment(
        conditions=tuple(conditions),
        unreadable=tuple(unreadable),
        neutral=tuple(neutral),
        text=text,
        identified=identified,
        reason=reason,
        as_of=utc_now(),
    )
