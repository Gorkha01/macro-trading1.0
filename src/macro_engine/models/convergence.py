"""Module 12 — the general convergence classifier.

AGENTS.md Section 22.10 (Finding #10), with Section 15.19-D's integration
requirement and Section 12's Module 12 narrative. One function.

What it is
----------
The **general** convergence classifier, distinct from the two it is easily
confused with:

* ``inflation_convergence_classifier`` (Module 5.3, D-047) classifies **inflation
  sub-measures** — a fixed, narrow input set.
* ``four_pillar_scorecard`` (Module 12.2, D-050) classifies **four named pillars**
  — a fixed, four-wide input set with pillars addressed by name.
* **This function** classifies **an arbitrary list of already-produced
  ``ModelResult``s** — the shape the thesis builder actually has, because it
  collects whatever the pipeline ran rather than a fixed roster.

That difference is the whole reason it exists separately: the specification calls
it at ``build_us_macro_thesis`` (Q7) with ``[growth, inflation, labor, gap]``,
which is a *list*, not a record with named fields.

Six specification defects are corrected here. They fall into three groups:

Group 1 — the function does not run at all
------------------------------------------
**Defect 1 — ``count_independent_families()`` returns a ``ModelResult``, and the
specification compares it to an ``int``.** Section 15.19-D ships the supplier
returning a ``ModelResult`` (D-046, because the count is uninterpretable without
its untagged denominator — a bare ``int`` cannot distinguish "three families from
five signals" from "three families from nine"). Section 22.10's classifier then
writes::

    independent_family_count = count_independent_families(signals)
    ...
    if frac >= 0.8 and independent_family_count >= 3:

which raises ``TypeError: '>=' not supported between instances of 'ModelResult'
and 'int'`` on **every call that reaches the family gate**. The specification's
two halves were written against different versions of the supplier and were never
run together. Verified live before this module was written.

**Defect 2 — the ``signals[0]`` reference is still there, and it is the exact bug
Finding #10 claimed to remove.** Section 22.10's prose says the correction is
"no longer uses ``signals[0]`` as an arbitrary reference". The code directly
below it does::

    agree_count = sum(1 for d in directions if d == directions[0] and d != 0)

Two consequences, both measured:

* **A neutral first signal collapses the read.** If ``directions[0] == 0`` then
  ``d != 0`` is false for every element and ``agree_count`` is **0**, so
  ``frac`` is ``0.0`` and the verdict is ``LOW`` — *regardless of how unanimous
  the directional signals are*. ``[0, +1, +1, +1]`` returns ``LOW`` while
  ``[+1, 0, +1, +1]`` — the same multiset — returns ``MEDIUM``.
* **The verdict depends on list order.** Over all multisets at ``n <= 5`` across
  family counts ``0..4``, **132 of 1800** cases produce *different verdicts* under
  permutation of the same signals. A classifier whose output changes when its
  input list is reordered is not classifying the evidence, it is classifying the
  call site.

Group 2 — the arithmetic does not express the prose
---------------------------------------------------
**Defect 3 — the denominator counts neutrals, so the thresholds are diluted.**
Section 22.10's own corrected version divides by the **non-neutral** count
(``len(non_neutral)``); Section 12's version divides by ``len(directions)``, the
whole list. A neutral signal is not evidence for either direction — Section 12's
own docstring says so — so including it in the denominator *dilutes* agreement in
proportion to how much of the input is neutral. Measured on the same signals:

```
dirs=[+1, +1, 0, 0]   non-neutral denominator 1.000   whole-list denominator 0.500
dirs=[+1, +1, +1, 0]  non-neutral denominator 1.000   whole-list denominator 0.750
```

The first is unanimous among everything that reads at all; the second calls the
same evidence a coin flip. The two sections of the specification therefore
disagree about the same input, and only one of them can be right.

**Defect 4 — ``NO_SIGNAL`` is unreachable in the general classifier, although the
vocabulary declares it.** ``ConvergenceClassification`` (thesis layer) declares
``NO_SIGNAL`` first-class with a docstring explaining why it differs from ``LOW``,
and Section 22.10's version returns it. Section 12's version has **no all-neutral
branch**: an all-neutral list has no opposition and ``agree_count == 0``, so it
falls through to ``frac = 0.0`` and returns **``LOW``**. An all-neutral read is
reported as "weak agreement" when the truth is "nothing was measured". This is
D-045a's "a ``Literal`` is a promise with two halves" at the level of an enum: the
member is declared and cannot be produced.

**Defect 5 — ``LOW`` conflates three unrelated situations.** Because the family
floors are checked *inside* the ``frac`` branches, a **unanimous** read with a low
family count falls through to the ``else`` and is reported ``LOW`` alongside a
genuinely weak-agreement read. Measured: ``dirs=[+1,+1,+1,+1]`` with one family
returns ``LOW`` — the pillars agree completely and the verdict says the agreement
is weak. The section's own warning text ("agreement is high but source
independence is low") can therefore never fire, because the branch that would emit
it is not reached.

Group 3 — the composition defect D-050 found, present again
-----------------------------------------------------------
**Defect 6 — the thresholds behind the ``CONFLICTED`` gate are inert.** This is
D-050's fifth defect, and it is *structural to the specification's gate order*
rather than to any threshold. ``CONFLICTED`` is tested first and consumes every
opposed read, so a read reaching the agreement gates has all non-neutral signals
pointing the same way. The reachable dissent count past that gate is exactly
``{0}`` for every ``n`` — verified by enumeration. Consequently:

* ``agree_frac >= 0.8`` and ``>= 0.6`` are, at ``n <= 4``, **the same test**
  (``1.0``) or a test on a value the classifier can only reach by ``n >= 5``;
  * no ratio ever lands in ``[0.8, 1.0)`` for ``n <= 4``;
  * ``MEDIUM`` requires ``n >= 5`` **and** two families simultaneously.

**Corrected after the F-SC-001 cross-check (D-051).** The paragraph above is
incomplete: it describes the gates as reachable only at ``n >= 5``, but ``CONFLICTED``
was ``opposed = up > 0 and down > 0``, so at **every** ``n`` a read reaching the
agreement gates was unanimous and ``MEDIUM`` (which needs ``dissent > 0`` together
with ``not opposed``) was unreachable outright — not merely hard to reach. The
predicate is now ``opposed = up >= 2 and down >= 2`` (a genuine standoff needs at
least two signals pointing each way), so a clear majority with one dissenter
reaches ``MEDIUM`` at any ``n >= 3`` while 2-vs-2 standoffs stay ``CONFLICTED``.
The same correction is applied to ``scorecard.py`` (F-SC-001/F-CV-001).

The repaired form expresses the gates as what they can actually be — **is there
agreement at all, and is it backed by independent sources** — while still
publishing the fraction so the thresholds remain auditable from the output.

Group 4 — a defect introduced by this repair, found by its own test
-------------------------------------------------------------------
**Defect 7 — the family census must run over the DIRECTIONAL signals only.**
The first draft of this module (and the obvious reading of §15.19-D, which says
``count_independent_families()`` should be called on "its inputs") measured the
family count over **all** signals, neutrals included. That inverts §15.19-D's own
purpose. A neutral signal carries **no direction**, so its family cannot be one
of the families backing a *directional* verdict — but the count said otherwise,
and the consequence is directly exploitable::

    two directional signals, 2 families        -> MEDIUM, confidence 0.60
    the same two + 3 NEUTRAL signals, 3 new families -> HIGH, confidence 0.75

Padding a read with neutral signals from new families promotes it, with no new
directional observation. That is redundant-evidence false confidence — the exact
failure §15.19-D exists to prevent — reached by a different route. The census now
runs over the directional subset, the neutral-only families are published
separately in ``value.families_excluded_as_neutral``, and a warning names them.

The test that found it was
``test_neutral_signals_cannot_promote_a_read_by_padding``, which was written to
assert the *opposite* and failed.

The repair in one sentence
--------------------------
Direction is derived from ``value`` **without reference to position**, the
denominator is the non-neutral count, ``NO_SIGNAL`` is a real branch, the family
floor is tested **separately from** the agreement level (so "unanimous but
single-source" is its own outcome rather than a species of ``LOW``), and the
family count is measured over the **directional** signals by calling Section
15.19-D's supplier rather than accepted as an argument.

What this function does *not* do
--------------------------------
It does not decide trades. ``CONFLICTED`` **blocks** construction elsewhere
(§16.3, ``build_us_macro_thesis``'s Q7); this function only reports it. It also
does not know which signals it was handed — it classifies a list, and a caller
that supplies four measures of one release gets four votes' worth of *direction*
and one family's worth of *independence*, which is the point.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.evidence import count_independent_families

__all__ = [
    "ConvergenceInputs",
    "ConvergenceVerdict",
    "classify_convergence",
]

#: The five verdicts, declared once so a test can assert every member is
#: producible (the D-045a "a ``Literal`` is a promise with two halves" rule).
#: The member set matches ``thesis_layer.schemas.ConvergenceClassification``
#: exactly — ``models/`` is the lower layer and cannot import it — and a test
#: asserts the two agree, because a forked vocabulary is the D-046 defect.
ConvergenceVerdict = Literal["NO_SIGNAL", "CONFLICTED", "HIGH", "MEDIUM", "LOW"]


def _direction(value: object) -> int:
    """Derive a signal's direction from its ``value``, position-independently.

    ``+1`` tightening-implying, ``-1`` easing-implying, ``0`` neutral. A
    non-numeric value is neutral because it carries no direction — a ``ModelResult``
    whose ``value`` is a dict or a verdict word is a perfectly valid upstream
    result (``four_pillar_scorecard`` itself returns a dict), and silently
    treating it as directional would be worse than ignoring it.

    Deliberately takes ``object`` and narrows here rather than accepting a
    ``float``: the signal list is heterogeneous by construction, and a coerced
    signature would push the narrowing to the caller where it would be repeated
    and eventually forgotten.
    """
    if isinstance(value, bool):  # bool is an int subclass; a flag is not a level
        return 0
    if isinstance(value, (int, float)):
        if value > 0:
            return 1
        if value < 0:
            return -1
    return 0


class ConvergenceInputs(BaseModel):
    """An arbitrary list of produced ``ModelResult``s to classify.

    A record rather than a bare list argument so the list can carry its own
    documentation and be extended without changing the signature — the same
    reason ``ScorecardInputs`` is a model.
    """

    model_config = ConfigDict(extra="forbid")

    signals: list[ModelResult] = Field(
        min_length=1,
        description=(
            "The signals to classify. Order does not affect the verdict — a "
            "test asserts this over the whole permutation group, because the "
            "specification's own version is order-dependent (Defect 2)."
        ),
    )


def classify_convergence(inputs: ConvergenceInputs) -> ModelResult:
    """Classify agreement across an arbitrary list of signals.

    Returns one of ``NO_SIGNAL`` / ``CONFLICTED`` / ``HIGH`` / ``MEDIUM`` /
    ``LOW``, plus the agreement fraction, the dissent count, the agreement
    margin, the **measured** independent-family count and the per-signal
    directions.

    The verdict order is deliberate and is the repair for Defect 6:

    ``NO_SIGNAL`` → ``CONFLICTED`` → the agreement gates.

    Every quantity a gate depends on is published, because the specification's
    output was a bare string and its thresholds could not be audited from it.

    Confidence comes from ``compute_confidence()`` (Section 22.8) and is **flat
    across verdicts**: the verdict is a fact about the world, the confidence is a
    fact about how well the signals were measured. It does move with the
    **measured family count**, because that *is* a measurement-quality fact.
    """
    settings = get_settings().convergence
    signals = inputs.signals

    directions = [_direction(s.value) for s in signals]
    non_neutral = [d for d in directions if d != 0]
    n = len(non_neutral)

    # Section 15.19-D discharged literally: the classifier measures the family
    # count by calling the supplier, rather than accepting a caller's int.
    #
    # **The census runs over the DIRECTIONAL signals only.** A neutral signal
    # carries no direction, so its family cannot be one of the families backing
    # a directional verdict — counting it lets a caller promote a read by
    # appending neutral signals from new families, which is §15.19-D's own
    # failure mode inverted (measured: two directional signals across two
    # families read MEDIUM at 0.60; adding three neutral signals from three new
    # families makes the same read HIGH at 0.75, with no new directional
    # evidence). The neutral signals' families are still reported separately, so
    # the exclusion is visible rather than silent.
    directional = [s for s, d in zip(signals, directions, strict=True) if d != 0]
    census = count_independent_families(directional)
    census_value = census.value
    if not isinstance(census_value, dict):  # pragma: no cover - contract guard
        raise TypeError(
            "count_independent_families returned a non-dict value; "
            "classify_convergence reads its `distinct_families` key and cannot "
            "continue."
        )
    distinct = census_value.get("distinct_families")
    if not isinstance(distinct, int):
        raise TypeError(
            "count_independent_families returned no integer `distinct_families`; "
            "classify_convergence cannot proceed without a measured family count."
        )
    untagged = census_value.get("untagged")
    if not isinstance(untagged, int):  # pragma: no cover - contract guard
        raise TypeError(
            "count_independent_families returned no integer `untagged`; "
            "classify_convergence cannot report a provenance share it did not "
            "measure. A missing key and a measured zero are different facts."
        )
    # The census runs over the DIRECTIONAL signals, where `with_source_family`
    # guarantees a family — so its `untagged` is structurally 0 and is NOT the
    # figure to publish. A neutral signal is the only kind that can lack a
    # family (the provenance guard refuses None for a directional one), and the
    # census deliberately excludes neutral signals. Counting over the WHOLE list
    # is what the disclosure below has always claimed to do ("of {total}
    # signal(s)"); reading the census made that disclosure unfireable (D-077).
    untagged_count = sum(1 for s in signals if s.source_family is None)

    # Families present only among the neutral signals. Counted and published so
    # the reader can see what was set aside, not folded into the verdict.
    neutral_families = {
        s.source_family.value
        for s, d in zip(signals, directions, strict=True)
        if d == 0 and s.source_family is not None
    }
    directional_families = set(census_value.get("families") or [])
    excluded_families = sorted(neutral_families - directional_families)

    up = sum(1 for d in non_neutral if d > 0)
    down = sum(1 for d in non_neutral if d < 0)
    # CONFLICTED requires a genuine STANDOFF — at least two signals pointing each
    # way. A 3-vs-1 split (or any split with a clear majority and one dissenter) is
    # NOT a standoff; the §22.10 severity model assigns it to MEDIUM. The prior
    # `up > 0 and down > 0` gate routed every such split to CONFLICTED, which made
    # the MEDIUM branch (requires NOT opposed AND dissent>0) unreachable — the same
    # dead-branch contradiction found in scorecard.py (F-SC-001 / D-051 cross-check).
    # Narrowing to `>= 2 on each side` keeps 2-vs-2 splits CONFLICTED while letting
    # a clear-majority-with-one-dissenter read reach MEDIUM.
    opposed = up >= 2 and down >= 2
    # The denominator is the NON-NEUTRAL count (Defect 3). Two measures are
    # published: `agree_frac` is the specification's measure, and the margin is
    # the share by which the larger side leads -- it reaches 0.0 on a tie and
    # privileges neither direction.
    agree_frac = max(up, down) / n if n else 0.0
    margin = abs(up - down) / n if n else 0.0
    dissent = n - max(up, down) if n else 0

    verdict: ConvergenceVerdict
    if n == 0:
        verdict = "NO_SIGNAL"
        reason = (
            f"all {len(signals)} signal(s) read neutral — no directional read "
            "exists, so there is nothing to agree or disagree about"
        )
    elif opposed:
        verdict = "CONFLICTED"
        up_i = [i for i, d in enumerate(directions) if d > 0]
        down_i = [i for i, d in enumerate(directions) if d < 0]
        reason = (
            f"{len(up_i)} signal(s) read tightening while {len(down_i)} read "
            f"easing — a genuine directional opposition, not weak agreement "
            f"(agreement {agree_frac:.0%})"
        )
    elif dissent <= settings.high_dissent_ceiling and distinct >= settings.high_family_floor:
        verdict = "HIGH"
        reason = (
            f"unanimous among {n} directional signal(s), backed by {distinct} "
            "independent source families"
        )
    elif dissent <= settings.medium_dissent_ceiling and distinct >= settings.medium_family_floor:
        verdict = "MEDIUM"
        reason = (
            f"{n - dissent} of {n} directional signal(s) agree with {dissent} "
            f"dissenting, backed by {distinct} independent source families"
        )
    elif distinct < settings.medium_family_floor:
        # Defect 5's repair: this is its OWN outcome, not a species of LOW.
        verdict = "LOW"
        reason = (
            f"{n} signal(s) agree ({agree_frac:.0%}) but they span only "
            f"{distinct} source family/families, below the "
            f"{settings.medium_family_floor} required for MEDIUM — agreement "
            "within one release is ONE vote, however many sub-measures compose it"
        )
    else:
        verdict = "LOW"
        reason = (
            f"agreement is weak: {n - dissent} of {n} directional signal(s) "
            f"agree with {dissent} dissenting, above the "
            f"{settings.medium_dissent_ceiling} dissenter(s) MEDIUM permits"
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=any(s.data_quality_flags_present for s in signals),
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
            source_independence_count=distinct,
        )
    )

    return ModelResult(
        model_name="classify_convergence",
        country="us",
        as_of=utc_now(),
        value={
            "classification": verdict,
            "agreement_fraction": round(agree_frac, 4),
            "agreement_margin": round(margin, 4),
            "dissenting_signals": dissent,
            "non_neutral_signals": n,
            "total_signals": len(signals),
            "independent_families": distinct,
            "untagged_signals": untagged_count,
            "families_excluded_as_neutral": excluded_families,
            "directions": directions,
        },
        confidence=confidence,
        interpretation=f"Convergence: {verdict} — {reason}.",
        context=(
            "Weighted by MEASURED independent source families over the "
            "DIRECTIONAL signals (Section 15.19-D), not by the raw signal count. "
            "The agreement denominator is the NON-NEUTRAL signal count. "
            "CONFLICTED is a first-class blocking outcome (Section 16.3 Q7)."
        ),
        inputs_used=[s.model_name for s in signals],
        warnings=_convergence_warnings(
            verdict=verdict,
            distinct=distinct,
            untagged_count=untagged_count,
            excluded_families=excluded_families,
            total=len(signals),
            n=n,
            agree_frac=agree_frac,
            medium_family_floor=settings.medium_family_floor,
            high_family_floor=settings.high_family_floor,
        ),
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="categorical (a convergence verdict over the directional signals)",
        direction=(
            f"{verdict}: {agree_frac:.0%} of the {n} non-neutral signal(s) point "
            f"the same way, weighted by measured independent source families"
        ),
        assumptions=[
            "The three possible verdicts are defined on the WEIGHTED agreement "
            "fraction, where the weight is MEASURED independent source families "
            "and not the raw signal count (Section 15.19-D). So a verdict is a "
            "statement about evidence diversity, not about how many models were "
            "run.",
            "NEUTRAL signals are excluded from the denominator. A signal that "
            "points neither way is treated as carrying no directional "
            "information rather than as a disagreement, which is why "
            "`non_neutral_signals` is published beside `total_signals`.",
            "Signal direction is READ from each signal's own value and unit, "
            "using the model's own convention. A signal whose direction cannot be "
            "read is counted in `untagged_signals` rather than guessed at.",
            "CONFLICTED is a BLOCKING outcome, not a low-confidence pass: it "
            "routes the thesis to no-trade via Section 16.3 Q7 because growth and "
            "inflation pointing opposite ways is a genuine incapacity to form a "
            "view, not a weak view.",
        ],
        data_provenance=[
            "signals — Q1's three economy reads plus the market-pricing-gap "
            "signal, assembled by the builder's classify_thesis_convergence",
            "source-family tags on each signal — from the each model's own "
            "`source_family`, counted by count_independent_families; an untagged "
            "signal is reported rather than silently dropped",
            "Weighting floors (medium_family_floor, high_family_floor) are "
            "config-sourced thresholds, and the warnings name when a verdict "
            "rests on a family count below them",
        ],
        limitations=[
            "THE VERDICT IS A STATEMENT ABOUT EVIDENCE DIVERSITY, NOT A "
            "PROBABILITY. 'HIGH agreement' means the directional signals span "
            "enough independent source families and agree; it does not mean the "
            "view is 80% likely to be right.",
            "INDEPENDENCE IS TAKEN FROM DECLARED FAMILIES, not verified. Two "
            "models that share a source but are tagged with different families "
            "would be counted as independent, and the count is only as honest as "
            "the tagging.",
            "A SMALL SIGNAL SET MAKES CONVERGENCE CHEAP: with three directional "
            "signals, one odd one out drops agreement sharply, so the verdict is "
            "sensitive to the composition of `signals` rather than only to the "
            "economy.",
            "NEUTRAL IS NOT THE SAME AS ABSENT. A signal that carries no "
            "direction is excluded from the denominator, so a reading with many "
            "neutral signals can show high agreement on very little directional "
            "evidence — `non_neutral_signals` is the field that bounds this.",
            "Points-in-time: the signals inherit their own models' vintage "
            "limitations, including the output gap's revision dependence, and no "
            "release or vintage datetime exists on this installation (Section 6, "
            "measured 2026-09-19).",
        ],
        decision_relevance=(
            "Section 16.2's Q7 — the convergence verdict that ends the sentence. "
            "CONFLICTED routes to no-trade (Section 16.3); otherwise the verdict "
            "is published on the thesis as the `convergence_classification`."
        ),
        decision_prohibition=[
            "MUST NOT be read as a probability or a confidence. It is a "
            "categorical verdict over a weighted agreement fraction, and the "
            "confidence on this result is a separate and differently-sourced "
            "quantity.",
            "MUST NOT be interpreted without `non_neutral_signals`. A HIGH "
            "verdict over two directional signals is a much weaker statement than "
            "the same verdict over six, and the total signal count alone does not "
            "reveal which case applied.",
            "MUST NOT be treated as a soft signal that can be overridden by "
            "conviction when it reads CONFLICTED. Section 16.3 Q7 makes it a "
            "blocking outcome by design.",
            "MUST NOT be used to claim independent confirmation without checking "
            "`independent_families`: agreement among signals from one source "
            "family is not corroboration.",
        ],
    )


def _convergence_warnings(
    *,
    verdict: str,
    distinct: int,
    untagged_count: int,
    excluded_families: list[str],
    total: int,
    n: int,
    agree_frac: float,
    medium_family_floor: int,
    high_family_floor: int,
) -> list[str]:
    """Build the warning list. Every branch is reachable by some test."""
    warnings: list[str] = [
        "Thresholds are illustrative starting heuristics, not calibrated "
        "against realised convergence outcomes — Phase 5+ calibration required.",
    ]
    if verdict == "CONFLICTED":
        warnings.append(
            "CONFLICTED — the signals point opposite ways. This MUST block trade "
            "construction (Section 16.3 Q7 / Module 12 dual-mandate tension)."
        )
    elif verdict == "NO_SIGNAL":
        warnings.append(
            f"NO_SIGNAL — all {total} signal(s) neutral. This is NOT LOW: no "
            "directional read exists, so there is nothing for the signals to "
            "agree or disagree about."
        )
    elif distinct < medium_family_floor:
        warnings.append(
            f"Agreement is {agree_frac:.0%} across {n} directional signal(s), but "
            f"they span only {distinct} source family/families. This is likely "
            "redundant evidence rather than genuine convergence — the case "
            "Section 15.19-D exists to catch."
        )
    elif distinct < high_family_floor:
        warnings.append(
            f"Agreement is {agree_frac:.0%} across {n} directional signal(s) "
            f"spanning {distinct} source families — enough for MEDIUM, below the "
            f"{high_family_floor} required for HIGH."
        )
    if untagged_count:
        warnings.append(
            f"{untagged_count} of {total} signal(s) carry no source family and are "
            "EXCLUDED from the independence count rather than counted as "
            "independent. Unknown provenance is not evidence either way; resolve "
            "with tag_evidence_source() before treating this verdict as final."
        )
    if excluded_families:
        warnings.append(
            f"{len(excluded_families)} source family/families "
            f"({', '.join(excluded_families)}) appear ONLY among neutral signals "
            "and are excluded from the independence count. A neutral signal "
            "carries no direction, so its family cannot be one of the families "
            "backing a directional verdict — counting it would let the read be "
            "promoted by padding the list with neutral signals."
        )
    if 0 < n < total:
        warnings.append(
            f"{total - n} of {total} signal(s) read neutral and are excluded from "
            "the agreement denominator, which is why it counts "
            f"{n} signal(s) rather than {total}."
        )
    return warnings
