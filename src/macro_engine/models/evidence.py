"""Module 13 — evidence source families and redundant-evidence detection.

AGENTS.md Section 15.19-D. Two functions and one vocabulary.

Why this module exists
----------------------
A convergence classifier asks "how many of my signals agree?" and that question
has a trap in it. Five inflation sub-measures — headline CPI, core CPI, and (in
later phases) trimmed-mean, median and supercore — are all built from the SAME
BLS survey. They agree because they are the same measurement, not because five
independent observations corroborated each other. Counting them as five votes
manufactures a confidence the data does not support.

The arithmetic that fixes it is a **set of families, not a count of results**:
five CPI-derived measures are one vote, core PCE is a genuinely separate BEA
release and therefore a second, and a TIPS breakeven is market pricing with no
government-release dependency at all and therefore a third.

``compute_confidence()`` already consumes ``source_independence_count``
(§22.8). Before this module that field was ``0`` at every one of its call sites
— the parameter existed and no function could supply it. This is the supplier.

Two corrections to §15.19-D are implemented here, both recorded in DECISIONS:

* **The tag is a typed field, not a warning string.** The specification appends
  ``source_family=<value>`` to ``ModelResult.warnings`` and parses it back with
  a ``startswith`` match. That puts structured data in a prose channel: any
  caller that rewrites, truncates, deduplicates or filters warnings destroys or
  corrupts the tag *silently*, and a hand-written warning could forge one. A
  warning list is a reporting surface; a family is a fact about provenance.
* **``count_independent_families`` returns a ``ModelResult``.** The
  specification returns a bare ``int``, which §22.9 forbids — and here the
  reason is substantive rather than stylistic: the *count* is meaningless
  without knowing **how many results carried no tag at all**. Three families
  from five signals and three families from nine signals are different epistemic
  situations, and a bare integer cannot tell them apart.

Layering
--------
This lives in ``models/`` and not ``thesis_layer/``. ``models/`` is the lower
layer — ``thesis_layer/`` imports from it and never the reverse — and the
convergence classifiers that must call these functions (Module 5's
``inflation_convergence_classifier``, Module 12's ``four_pillar_scorecard``,
``classify_convergence``) are all model-layer. The enum was previously declared
in ``thesis_layer/schemas.py``, where nothing could reach it downward; it moved
here and ``thesis_layer`` re-exports it, so existing imports keep working.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.evidence_family import EvidenceSourceFamily

__all__ = [
    "EvidenceSourceFamily",
    "EvidenceTally",
    "count_independent_families",
    "tag_evidence_source",
]


class EvidenceTally(BaseModel):
    """The counted-out result of a family census.

    Carried as ``value`` of the ``count_independent_families`` ModelResult.
    Every field is needed to interpret the count honestly:

    * ``distinct_families`` — the number to feed ``source_independence_count``.
    * ``tagged`` and ``untagged`` — because a count with no denominator is not a
      measurement. An untagged result is not *no evidence*; it is *unknown
      evidence*, and the two must not be pooled.
    * ``families`` — the actual members, so a reader can see WHICH families
      corroborated rather than only how many.
    * ``duplicate_results`` — results sharing a family with an earlier one. These
      are the redundant votes the whole module exists to collapse.
    """

    model_config = ConfigDict(extra="forbid")

    distinct_families: int = Field(ge=0, le=len(EvidenceSourceFamily))
    families: list[str] = Field(
        description="Sorted family values, so the membership is auditable.",
    )
    tagged: int = Field(ge=0)
    untagged: int = Field(ge=0)
    duplicate_results: int = Field(
        ge=0,
        description="Results whose family was already counted — the collapsed votes.",
    )


def tag_evidence_source(
    model_result: ModelResult,
    family: EvidenceSourceFamily,
    *,
    data_quality_flags_present: bool = False,
) -> ModelResult:
    """Return ``model_result`` carrying ``family`` as its provenance.

    **Returns a copy; does not mutate the argument.** The specification's version
    appends to the caller's ``warnings`` list and returns the same object, so
    tagging a shared result silently relabels it everywhere it is referenced.
    A provenance fact must be attached to the value it describes, and the model
    is ``extra="forbid"``, so a copy with the field set is the honest
    implementation.

    The re-tag case is a **refusal, not a silent overwrite**: a result that
    already carries a family is one whose provenance someone has already
    decided, and changing it here would discard that decision. Re-tagging the
    same family is idempotent and allowed, because a pipeline may legitimately
    apply the same tag in two places.

    ``data_quality_flags_present`` is re-derivable at the point of tagging,
    because the tagger is usually the only place that knows the upstream flags.
    It does **not** change the confidence here — the tagged result's confidence
    was computed when it was built — it is recorded so the convergence callers
    can price it. Rewriting a model's confidence downstream would be exactly the
    "confidence from somewhere other than ``compute_confidence()``" that §22.8
    forbids.
    """
    existing = model_result.source_family
    if existing is not None and existing != family:
        raise ValueError(
            f"{model_result.model_name!r} is already tagged {existing.value!r}; "
            f"refusing to re-tag it as {family.value!r}. A result's provenance is "
            "decided once — if two families genuinely apply, the result is "
            "composite and each component must be tagged separately."
        )

    tagged = model_result.model_copy(update={"source_family": family})
    note = f"Evidence source family: {family.value} (Module 13)."
    if note not in tagged.warnings:
        tagged = tagged.model_copy(update={"warnings": [*tagged.warnings, note]})

    if data_quality_flags_present and not tagged.data_quality_flags_present:
        # Record the flag so a downstream confidence computation can see it.
        # The confidence VALUE is untouched: see the docstring.
        tagged = tagged.model_copy(update={"data_quality_flags_present": True})
    return tagged


def count_independent_families(tagged_results: list[ModelResult]) -> ModelResult:
    """Count DISTINCT source families across ``tagged_results``.

    This — not ``len(tagged_results)`` — is the denominator for convergence
    confidence, because five agreeing CPI sub-measures are one release.

    Empty input returns **zero families and no confidence claim**, not an error:
    "nothing to count" is a legitimate state for a caller building a signal list
    incrementally. It is disclosed in ``warnings`` rather than raised, so a
    pipeline can tally a partially-built list without exception handling.

    Untagged results are **counted and reported separately**. They cannot simply
    be ignored — a result with unknown provenance is not evidence of zero
    independence — and they cannot be assumed independent either, which would
    reproduce the false-convergence failure this module exists to prevent. The
    count of them travels in ``value.untagged`` and in a warning, and the caller
    decides. Resolution necessarily differs: in a fully instrumented pipeline an
    untagged result is a bug; in a phase where some inputs have no assigned
    family yet, it is expected.
    """
    seen: set[str] = set()
    duplicates = 0
    for r in tagged_results:
        family = r.source_family
        if family is None:
            continue
        if family.value in seen:
            duplicates += 1
        else:
            seen.add(family.value)

    untagged = sum(1 for r in tagged_results if r.source_family is None)
    distinct = len(seen)
    families = sorted(seen)

    warnings: list[str] = []
    if not tagged_results:
        warnings.append(
            "NO RESULTS SUPPLIED: the family count is zero because the list was "
            "empty, which is not the same as a measured absence of independence."
        )
    if untagged:
        warnings.append(
            f"{untagged} of {len(tagged_results)} result(s) carry no source family. "
            "They are EXCLUDED from the count rather than counted as independent, "
            "because unknown provenance is not evidence either way. Resolve with "
            "tag_evidence_source() before treating this count as final."
        )
    if duplicates:
        warnings.append(
            f"{duplicates} result(s) shared a family already counted and were "
            "collapsed to a single vote — that is the redundant-evidence "
            "correction, not an error (Module 13)."
        )
    if distinct == 1 and len(tagged_results) > 1 and not untagged:
        warnings.append(
            f"ALL {len(tagged_results)} result(s) are from ONE family "
            f"({families[0]}). Agreement among them is one observation reported "
            "several times and must not be read as convergence."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="count_independent_families",
        country="us",
        as_of=utc_now(),
        value=EvidenceTally(
            distinct_families=distinct,
            families=families,
            tagged=len(tagged_results) - untagged,
            untagged=untagged,
            duplicate_results=duplicates,
        ).model_dump(),
        confidence=confidence,
        interpretation=(
            f"{distinct} independent source family/families across {len(tagged_results)} result(s)."
        ),
        context=(
            "Module 13. This count is the `source_independence_count` argument to "
            "compute_confidence(); the raw result count is NOT a substitute for it."
        ),
        inputs_used=["source_family"],
        warnings=warnings,
    )
