"""Module 14 — the thesis-wide warning aggregate (Section 16.4, D-067).

``collect_all_warnings`` answers one question for the thesis: **what did the
models that produced this thesis say about their own limits, and how much of
that is shared.** It fills ``MacroThesis.warnings``, and both the schema and
Section 7.2 step 9 describe that field in the strongest terms available to this
project:

    "The union of every underlying ModelResult.warnings plus any
    convergence-specific caveats. Never dropped (Section 7.2 step 9)."

Section 16.4's sample is nine lines:

    def collect_all_warnings(*model_results: ModelResult) -> list[str]:
        all_warnings = []
        for r in model_results:
            all_warnings.extend(r.warnings)
        return list(dict.fromkeys(all_warnings))   # de-duplicated, order-preserved

This is a **summariser**, and the project has a rule about summarisers (D-027):
*a summariser must not be scored by its own output.* The question this module had
to answer first was therefore not "does it de-duplicate correctly" but **"which
of the two answers a reader needs does a flat list actually carry"**.

Seven defects, all measured (D-067)
-----------------------------------
The first four are structural — visible with two synthetic results and no data:

**1. De-duplication destroys the count, and the count is the signal.**
``list(dict.fromkeys(...))`` collapses identical strings. Whether that is right
depends on the question, and the two answers disagree:

- *one fact, printed once* — de-dup is correct; printing it N times is noise;
- *all N models are looking through the same degraded input* — the count **is**
  the finding.

Measured (`probe_warnings_defects.py`): four models raising the identical string
aggregate to **one** entry. That is **D-046's "five signals are not five votes"
problem inverted** — there, five correlated measures were *over*-counted as five
votes; here, one fact seen by four models is *under*-counted as one.

**2. The output cannot attribute a warning to its source.** A flat
``list[str]`` has no room for "which models raised this", so *"two models
independently reported this"* and *"one model said it twice"* are the **same
value**. Measured: two models with byte-identical warnings produce a one-element
list with no trace that there were two.

**3. Whether de-duplication fires at all is decided by an unstated PRODUCER
convention.** If a model prefixes its warning with its own ``model_name``, the
strings differ and nothing collapses; if it does not, they collapse. Measured
both ways: **0 of 8** live warnings name their own model, so the collapse
behaviour is currently undefined-by-accident rather than chosen. The consumer
cannot control it, and nothing in the contract states it.

**4. "No warnings" and "not passed" are the same value.** ``collect_all_warnings
(quiet_model)`` and ``collect_all_warnings()`` both return ``[]``. This is
**D-066's shape** one function over: an absent input and a clean input are
indistinguishable, because the return type has one slot for two states.

Three more are about what the function *cannot* carry at all:

**5. Section 21.4's mandatory class has no route in.** §21.4 states that every
BLOCKED input "must be ... surfaced in every thesis's ``warnings``". The
signature takes ``*model_results: ModelResult`` — and a BLOCKED input is one no
model could run on, so **it is not a ModelResult**. Measured against the live
registry: **5 known blocked members, 0 routes into the aggregate as specified.**

**6. Section 5.4's disclosure class does not reach it either.** Measured on a
live snapshot: **5 of 5** ``data_quality_flags`` fail to appear in the aggregate.
The flag currently only *lowers confidence* (D-033 / §22.8); it is never
surfaced as text. The fact survives in ``MacroThesis.snapshot_quality_flags``,
so it is not lost — but §21.4 says *warnings*, and warnings does not get it.

**7. Defects 1 and 6 are COUPLED, and the coupling is the point.** The natural
fix for defect 6 — route snapshot flags into each result's warnings — makes
**every** model built from that snapshot carry the **same** flag string, which
is exactly the collision case defect 1 collapses away. So the honest fix for
§21.4's obligation is the thing that activates the de-dup loss. A repair that
treats them separately will reintroduce one while fixing the other.

What this module does instead of picking a side
-----------------------------------------------
The return type gains a slot for each question, so neither has to be encoded as
a lie in the other:

- ``warnings`` — the de-duplicated, order-preserved ``list[str]`` §16.4
  specifies, unchanged in content and order. **Every consumer that wants "what
  should a human read" gets exactly what it got before.**
- ``sources`` — a ``tuple`` of ``WarningSource(text, model_names)`` recording
  **which** models raised each text. The count defect 1 discarded is here, and
  it is a field rather than a phrase.
- ``unattributed`` — text that reached the aggregate **without** a
  ``ModelResult`` behind it: the §21.4 blocked entries and the §5.4 quality
  flags. These are typed ``UnattributedWarning(text, origin, detail)``, so the
  two mandatory classes get a route that does not pretend to be a model result.
  Passed in by the caller, because **the function cannot discover them** — a
  blocked input is the absence of data, which no enumeration of results reveals.
- ``contributing_models`` / ``models_with_warnings`` — the denominators. A
  warning list with no denominator cannot be read as "how degraded is this
  thesis", which is the question ``warnings`` exists to answer.
- ``model_warnings`` — the ``dict[str, tuple[str, ...]]`` mapping models to
  their own warnings, so a reader can still group by source.

What this does NOT do
---------------------
- **It does not decide whether de-duplication should happen.** It happens, as
  §16.4 specifies, in ``warnings``. The alternative reading is preserved in
  ``sources`` rather than argued for. Choosing would be a specification decision
  (it changes what the published field means), and D-064's direction-blindness
  is the precedent for disclosing rather than guessing.
- **It does not walk the registry or the snapshot itself.** ``unattributed`` is
  a **parameter**, because a function that silently reached into global config
  would make the §21.4 obligation look discharged whether or not the caller
  passed anything. The caller must name what it is omitting; that is the point
  (the same reasoning as D-062's mandatory scope warning).
- **It does not weaken "never dropped".** Every input warning appears in
  ``warnings`` or in a ``WarningSource``; every unattributed input appears in
  ``unattributed``. The union of the three is a superset of the inputs, and the
  census is asserted.
- **It does not deduplicate ``unattributed`` against ``warnings``.** A §5.4 flag
  and a model's own warning are different claims about different things even
  when the text overlaps; merging them would hide which class was raised.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import ModelResult

__all__ = [
    "UnattributedWarning",
    "WarningOrigin",
    "WarningSource",
    "WarningSummary",
    "collect_all_warnings",
]

#: Where a warning that has no `ModelResult` behind it came from.
#:
#: Section 21.4's blocked class and Section 5.4's disclosure class are the two
#: the specification makes **mandatory**, and neither is a model result. The
#: vocabulary is closed so an unlisted origin is a type error rather than a new
#: string nobody validates (the O-29 lesson: a bare `str` lets a typo fall
#: through).
WarningOrigin = Literal["blocked_input", "data_quality_flag", "caller"]


class UnattributedWarning(BaseModel):
    """A warning with no ``ModelResult`` behind it.

    These are the two classes the specification makes **mandatory** — Section
    21.4's blocked inputs and Section 5.4's data-quality disclosures — plus a
    ``caller`` member for anything else the thesis builder needs surfaced.

    A typed record rather than a bare string, for the same reason Module 13's
    provenance is a typed field (D-046): a string is a reporting surface a
    caller may rewrite, and the origin is a fact. ``origin`` is what lets a
    reader answer *"is this thesis missing data, or looking through degraded
    data?"* — two different problems with different remedies.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, description="The warning, in full.")
    origin: WarningOrigin = Field(
        description=(
            "Which class this belongs to. 'blocked_input' (Section 21.1/21.4) "
            "and 'data_quality_flag' (Section 5.4) are the mandatory two."
        )
    )
    detail: str | None = Field(
        default=None,
        description=(
            "What was omitted, when the text alone does not say. For a blocked "
            "input this is the registry's reason; for a quality flag, the "
            "affected series and date."
        ),
    )


class WarningSource(BaseModel):
    """One de-duplicated warning text, plus the models that raised it.

    This is the half of the answer ``list[str]`` cannot carry (defects 1 and 2).
    ``model_names`` is ordered by first appearance across the input results, so
    the output is deterministic for a given input order — the same property
    §16.4's ``dict.fromkeys`` is written to have.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, description="The warning text, as first seen.")
    model_names: tuple[str, ...] = Field(
        description=(
            "Every model that raised this exact text, in first-appearance "
            "order, de-duplicated. Length >= 1. A length > 1 *is* the finding "
            "de-duplication discarded: several models saw the same problem."
        )
    )

    @property
    def raised_by_multiple_models(self) -> bool:
        """Whether more than one model raised this text.

        The single bit the flat list cannot express, named so a caller can read
        it without counting.
        """
        return len(self.model_names) > 1


class WarningSummary(BaseModel):
    """The aggregate, with a slot for each of the questions it answers.

    ``warnings`` is §16.4's output, unchanged in content and order — every
    consumer that wants the de-duplicated list gets exactly what it got before.
    Everything else is the answer the flat list could not carry.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    warnings: tuple[str, ...] = Field(
        description=(
            "Section 16.4's output: every input warning, de-duplicated, order "
            "preserved. This is what a human reads."
        )
    )
    sources: tuple[WarningSource, ...] = Field(
        description=(
            "One entry per element of ``warnings``, in the same order, "
            "recording which models raised it. The count defect 1 discarded."
        )
    )
    unattributed: tuple[UnattributedWarning, ...] = Field(
        description=(
            "Warnings with no ModelResult behind them — Section 21.4's blocked "
            "inputs and Section 5.4's quality flags, passed by the caller. "
            "Order preserved as given; never merged into ``warnings``."
        )
    )
    model_warnings: dict[str, tuple[str, ...]] = Field(
        description=(
            "Each model's own warnings, keyed by ``model_name``, in the order "
            "the results were passed. Lets a reader group by source, which the "
            "flat list's order alone cannot (defect 3)."
        )
    )
    contributing_models: int = Field(
        ge=0,
        description="How many ModelResults were passed, including warning-free ones.",
    )
    models_with_warnings: int = Field(
        ge=0,
        description=(
            "How many of them raised at least one warning. Distinct from "
            "``contributing_models`` on purpose: '3 of 9 models warned' is a "
            "different statement from '3 models warned'."
        ),
    )

    @property
    def all_texts(self) -> tuple[str, ...]:
        """``warnings`` followed by the unattributed texts.

        The union a caller needs for "is anything being disclosed at all",
        without having to remember that there are two sources. Deliberately a
        property rather than the primary field, so a caller that wants only
        §16.4's list cannot get it by accident.
        """
        return self.warnings + tuple(w.text for w in self.unattributed)

    @property
    def shared_warnings(self) -> tuple[WarningSource, ...]:
        """Only those raised by more than one model.

        The subset a reader wants when asking "what is systemic rather than
        local" — the question de-duplication made unanswerable.
        """
        return tuple(s for s in self.sources if s.raised_by_multiple_models)


def collect_all_warnings(
    *model_results: ModelResult,
    unattributed: Iterable[UnattributedWarning] | Sequence[UnattributedWarning] = (),
) -> WarningSummary:
    """Aggregate every model's warnings into the thesis-wide disclosure.

    Section 16.4 specifies the de-duplicated, order-preserved ``list[str]``, and
    that list is preserved exactly in ``WarningSummary.warnings``. What the flat
    list could not carry — which models raised each text, how many did, and the
    two warning classes that have no ``ModelResult`` behind them — is carried in
    the sibling fields rather than argued away (D-067).

    Parameters
    ----------
    *model_results:
        The results whose ``warnings`` are aggregated. Their order determines
        the output order, exactly as §16.4's ``dict.fromkeys`` does.
    unattributed:
        Warnings with no ``ModelResult`` behind them: Section 21.4's blocked
        inputs, Section 5.4's quality flags, and anything else the caller must
        disclose. **Passed by the caller rather than discovered**, because a
        blocked input is the *absence* of data — no enumeration of results can
        reveal it, and a function that pretended otherwise would make the §21.4
        obligation look discharged when nothing had been passed.

    Returns
    -------
    WarningSummary
        ``warnings`` is §16.4's output verbatim. ``sources`` records the
        attribution, ``unattributed`` holds the non-result disclosures,
        ``model_warnings`` groups by source, and the two counts are the
        denominators without which the list cannot be read as a severity.

    Notes
    -----
    "Never dropped" (Section 7.2 step 9) is preserved in the strongest form the
    function can offer: every input warning appears in ``warnings``, every
    attribution appears in ``sources``, and every unattributed disclosure
    appears in ``unattributed``. An empty result is therefore a **total** of
    zero, not an absence — which is what distinguishes it from the
    unspecified-input case §16.4's signature conflates.
    """
    # --- attribution first, so the output order is the input order ----------
    # `dict.fromkeys` on the texts gives §16.4's order and de-duplication; the
    # separate map records every raiser, which is what the list throws away.
    raisers: dict[str, list[str]] = {}
    model_warnings: dict[str, tuple[str, ...]] = {}
    models_with_warnings = 0

    for result in model_results:
        own = tuple(result.warnings)
        model_warnings[result.model_name] = own
        if not own:
            continue
        models_with_warnings += 1
        for text in own:
            # dict preserves first-seen order; the list preserves every raiser.
            raisers.setdefault(text, []).append(result.model_name)

    warnings = tuple(raisers)  # de-duplicated, order-preserved (§16.4)
    sources = tuple(
        WarningSource(text=text, model_names=tuple(names)) for text, names in raisers.items()
    )

    unattributed_tuple = tuple(unattributed)

    summary = WarningSummary(
        warnings=warnings,
        sources=sources,
        unattributed=unattributed_tuple,
        model_warnings=model_warnings,
        contributing_models=len(model_results),
        models_with_warnings=models_with_warnings,
    )

    # --- the census, asserted rather than assumed ----------------------------
    # The two structural invariants a summariser must not be able to violate.
    # Asserted here because the failure they guard is silent: a `warnings`
    # shorter than `sources`, or a raiser list that lost a model, is exactly
    # the defect this function exists to fix, and no downstream reader could
    # tell it had happened.
    if len(summary.warnings) != len(summary.sources):
        raise AssertionError(  # pragma: no cover - construction is total
            f"warnings ({len(summary.warnings)}) and sources ({len(summary.sources)}) "
            f"must be the same length; they are built from one dict"
        )
    total_raisers = sum(len(s.model_names) for s in summary.sources)
    total_own = sum(len(w) for w in summary.model_warnings.values())
    if total_raisers != total_own:
        raise AssertionError(  # pragma: no cover - construction is total
            f"attribution lost a raiser: {total_raisers} recorded against "
            f"{total_own} input warning(s) — 'never dropped' is violated"
        )

    return summary
