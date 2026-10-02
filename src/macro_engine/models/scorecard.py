"""Module 12.2 — the four-pillar scorecard.

AGENTS.md Section 20.11, with Section 15.19-D's integration requirement. One
function.

What it is
----------
The capstone of Module 12: four directional pillar reads (growth, inflation,
financial conditions, policy gap) in, one convergence verdict out. It answers
*"do the pillars agree, and is that agreement backed by independent evidence?"*
and it never answers *"should we trade"* — ``CONFLICTED`` **blocks** construction
elsewhere; this function only reports it.

Four specification defects are corrected here, and the first two are defects in
the specification's own arithmetic rather than in its prose.

Defect 1 — the ``CONFLICTED`` gate does not cover ``CONFLICTED`` reads
--------------------------------------------------------------------
The specification computes ``has_up and has_down`` over the non-neutral pillars
(so: *the pillars genuinely oppose each other*), then requires an additional,
**narrower** condition — ``growth_signal * inflation_signal < 0`` — before
returning ``CONFLICTED``. Enumerating all ``3**4 = 81`` pillar combinations,
**50** have at least one pillar pointing each way, and the shipped rule catches
**18** of them. The 32 it misses include every configuration where growth and
inflation agree while financial conditions and policy oppose — the classic
"bad news is good news" split, and precisely the read a trade must not be built
on. Since the specification's own warning text calls ``CONFLICTED`` a mandatory
block, each miss is a false green light.

The repair is the smallest possible one: **the gate is the guard.** The
function computes the opposition predicate once, uses it for the verdict, and
publishes which pillars opposed so a reader can see the split rather than
inferring it.

Defect 2 — ``agree_frac >= 0.9`` and ``>= 0.75`` are not two thresholds
-----------------------------------------------------------------------
``agree_frac`` divides by the number of **non-neutral** pillars, so ``n`` is at
most four and the reachable ratios are forced: ``{1.0}`` at ``n=1``,
``{0.5, 1.0}`` at ``n=2``, ``{0.667, 1.0}`` at ``n=3``, ``{0.5, 0.75, 1.0}`` at
``n=4``. **No ratio ever lands in ``[0.9, 1.0)``** — so ``>= 0.9`` and ``>= 1.0``
are the same test, and the pair ``0.9 / 0.75`` distinguishes exactly one
configuration, the ``n=4`` three-one split. A practical consequence the
thresholds do not express: one dissenter out of three scored ``LOW`` while one
out of four scored ``MEDIUM``.

The repair expresses the gates as **dissent counts** — unanimity for ``HIGH``,
at most one dissenter for ``MEDIUM`` — which is what the fractions were reaching
for and which has no granularity cliff. The fraction, the dissent count **and**
an agreement margin are all still published, so the thresholds are auditable
from the output rather than reconstructed from the code.

Defect 5 — ``MEDIUM`` was unreachable under the original ``opposed`` gate
------------------------------------------------------------------------
The docstring above says the repair "expresses the gates as dissent counts —
at most one dissenter for ``MEDIUM``." That was **false as shipped** until this
defect was corrected. The ``CONFLICTED`` gate was ``opposed = up > 0 and down > 0``,
which is true for *any* non-unanimous read — including a 3-vs-1 majority with a
single dissenter. Because the ``MEDIUM`` branch requires ``NOT opposed AND
dissent > 0``, and ``dissent > 0`` *implies* ``opposed`` under the old predicate,
the ``MEDIUM`` branch could never be reached: every non-unanimous read was
``CONFLICTED``. The companion ``classify_convergence`` (``convergence.py``) carried
the identical dead branch.

The repair (F-SC-001) narrows the predicate to ``opposed = up >= 2 and down >= 2``
— a genuine standoff needs at least two pillars on each side. A 3-vs-1 split now
falls through to ``MEDIUM`` (it has a clear majority and one dissenter, exactly
what the severity model reserves ``MEDIUM`` for), while 2-vs-2 splits remain
``CONFLICTED``. This changes the measured ``CONFLICTED`` base share downward from
the previously cited 350/567 — those 350 included every 3-vs-1 split, which are
now ``MEDIUM`` — so the docstring's "62% of the input space" figure is an
*upper bound* on the standoff share, not a current measurement after this repair.

Defect 3 — Section 15.19-D was not discharged, and this was the increment's
assigned audit
--------------------------------------------------------------------------------
Section 15.19-D obliges every convergence classifier to **call
``count_independent_families()`` on its inputs** and use that count, rather than
the raw number of agreeing signals, as the basis for confidence. The
specification's signature takes ``independent_source_families: int`` — a raw
caller-supplied integer that the function cannot verify.

The failure this permits is the exact one §15.19-D exists to prevent: a caller
passing ``4`` (the **raw signal count**) on a unanimous input gets ``HIGH`` with
no complaint. The function cannot tell *four independent families* from *four
sub-measures of one release*. It also accepts ``families=99`` on a four-pillar
read, and treats ``0`` and ``1`` identically without flagging either.

The repair changes **what the function asks for**, not merely what it validates:
it accepts the tagged ``ModelResult``s and calls ``count_independent_families``
itself. The count is then measured rather than claimed, and the raw-signal-count
error becomes unrepresentable. This is the same contract
``inflation_convergence_classifier`` adopted in D-047.

Defect 4 — four hardcoded confidences
-------------------------------------
``0.2 / 0.75 / 0.5 / 0.3``, moving with the verdict, so severity and confidence
are confounded. Section 22.8 makes ``compute_confidence()`` the only producer.
The function returns a confidence that is **flat across verdicts**, because the
verdict is a fact about the world and the confidence is a fact about how well it
was measured — the D-048/D-049 pattern.

What ``CONFLICTED`` being 62% of the input space means
------------------------------------------------------
Over the whole admissible space, **350 of 567** configurations classify
``CONFLICTED``. Four pillars over ``{-1, 0, +1}`` oppose themselves most of the
time, so a bare verdict carries less information than its prominence suggests.
The measured share travels on every output, so a reader can distinguish a
finding about *this* read from the base state of the input space. This mirrors
D-047's ``HIGH``-is-the-base-state result (89.5%).

The space share and the historical share are different claims
-------------------------------------------------------------
The paragraph above is about the **input space** — what the classifier does to
arbitrary inputs. It is not a claim about history. Deriving all four pillars from
real FRED series over **761 months** (1962-2026) gives a much lower
``CONFLICTED`` share, because real pillars are **correlated**: a tightening cycle
moves growth, inflation and policy together rather than independently. The live
check reports both numbers side by side, and the contrast is the point — a
blocking verdict that occupies 62% of the abstract space need not occupy 62% of
real time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.evidence import count_independent_families
from macro_engine.models.evidence_family import EvidenceSourceFamily

__all__ = [
    "ConvergenceVerdict",
    "PillarRead",
    "ScorecardInputs",
    "four_pillar_scorecard",
]

#: The five verdicts, declared once so a test can assert every member is
#: producible (the D-045a "a Literal is a promise with two halves" rule).
ConvergenceVerdict = Literal["NO_SIGNAL", "CONFLICTED", "HIGH", "MEDIUM", "LOW"]

#: The four pillars, in reporting order. Names are used as published keys and as
#: ``inputs_used`` entries, so they are defined once.
_PILLARS: tuple[str, ...] = (
    "growth",
    "inflation",
    "financial_conditions",
    "policy_gap",
)


def _direction_label(value: int) -> str:
    """Map a pillar read to its vocabulary word.

    ``+1`` tightening-implying, ``-1`` easing-implying, ``0`` neutral. Prose uses
    these words because ``+1`` as "positive" is ambiguous in exactly the way
    ``SignalDirection``'s docstring warns about.
    """
    if value > 0:
        return "tightening"
    if value < 0:
        return "easing"
    return "neutral"


class PillarRead(BaseModel):
    """One pillar's directional read, with its provenance.

    A typed record rather than a bare ``int`` because the signal and its
    evidence family travel together: a direction without a family cannot be
    counted for independence, and §15.19-D's whole point is that the two are
    not separable when computing convergence confidence.
    """

    model_config = ConfigDict(extra="forbid")

    direction: Literal[-1, 0, 1] = Field(
        description=(
            "Directional read: -1 easing-implying, 0 neutral, +1 "
            "tightening-implying. Deliberately a Literal rather than int — "
            "a magnitude here is a category error, not a data point."
        )
    )
    family: EvidenceSourceFamily = Field(
        description=(
            "Module 13 provenance. Two pillars sharing a family are one vote, "
            "however different their directions."
        )
    )
    source: str = Field(
        min_length=1,
        description=(
            "Which upstream function or series produced this read. Recorded so "
            "the checkable part of the input is checkable: a scorecard whose "
            "growth read came from nowhere is not auditable."
        ),
    )


class ScorecardInputs(BaseModel):
    """The four pillars as tagged reads (Section 20.11, corrected).

    **The specification's version takes five bare ints**, the fifth being
    ``independent_source_families`` — a caller-supplied count. That contract
    cannot discharge §15.19-D, because the function has no way to distinguish a
    family count from the raw signal count it is supposed to replace (see the
    module docstring, Defect 3). This version takes the reads themselves and
    measures the count.
    """

    model_config = ConfigDict(extra="forbid")

    growth: PillarRead
    inflation: PillarRead
    financial_conditions: PillarRead
    policy_gap: PillarRead
    allow_all_neutral: bool = Field(
        default=False,
        description=(
            "Opt-in for an all-neutral read. Refusing the state outright would "
            "make a state that REAL DATA PRODUCES unrepresentable — over 761 "
            "months of FRED history, 6 readings (0.8%) have all four pillars "
            "neutral. The guard exists to stop 'we see nothing' being reached by "
            "an empty default, so it asks for the state on purpose rather than "
            "forbidding it."
        ),
    )

    @model_validator(mode="after")
    def _at_least_one_pillar_must_be_directional(self) -> ScorecardInputs:
        reads = [getattr(self, name) for name in _PILLARS]
        if all(r.direction == 0 for r in reads) and not self.allow_all_neutral:
            raise ValueError(
                "All four pillars read neutral, which the classifier reports as "
                "NO_SIGNAL — a legitimate state that real data produces (0.8% of "
                "761 months). It must be asked for on purpose rather than "
                "arrived at by omission, so pass allow_all_neutral=True to "
                "confirm this is an intended all-neutral read."
            )
        return self

    def pillar_reads(self) -> list[PillarRead]:
        """The four reads in reporting order."""
        return [getattr(self, name) for name in _PILLARS]


def _pillar_census(inputs: ScorecardInputs) -> tuple[int, list[str]]:
    """Measure the independent-family count over the four pillar reads.

    Builds one ``ModelResult`` per **directional** pillar carrying that pillar's
    family, then calls the Module 13 supplier. This is §15.19-D's requirement
    discharged literally: the classifier does not accept a count, it computes one.

    **The census runs over the DIRECTIONAL pillars only.** A neutral pillar
    carries no direction, so its family cannot be one of the families backing a
    directional verdict — but counting it lets the read be promoted by padding,
    which is §15.19-D's own failure mode inverted. Measured on the shipped
    arithmetic before this correction: one directional pillar and three neutral
    ones spanning four families returned ``HIGH``, while the same single
    directional pillar alone returns ``LOW``. The three neutral pillars
    contributed three families to a verdict none of them pointed at.

    This defect was found by ``scripts/live_convergence_check.py``'s cross-check
    against ``classify_convergence`` (D-051), which had independently made the
    same mistake and been corrected by its own test — the general classifier
    censuses the directional subset, so the two disagreed on exactly the
    neutral-padded inputs. **One classifier's repair is a defect report against
    every classifier that shares the pattern**, which is why the cross-check
    exists.

    The synthetic results are **census carriers only** — they exist to give the
    counter something to count, and are not returned or published. Their
    ``confidence`` comes from ``compute_confidence(ConfidenceInputs())``, exactly
    as ``inflation_convergence._tagged_measures`` — the other census carrier —
    does. It was the literal ``1.0`` until D-142; that asserted MAXIMUM
    confidence, the precise opposite of what this docstring claimed ("a
    placeholder must not be mistaken for a measured one"), and it was the only
    remaining ``confidence=<literal>`` in the models layer. The value is never
    read (``count_independent_families`` reads ``source_family``), so this is a
    consistency and honesty fix rather than a behaviour change.
    """
    directional = [
        (name, read)
        for name, read in zip(_PILLARS, inputs.pillar_reads(), strict=True)
        if read.direction != 0
    ]
    census_input = count_independent_families(
        [
            ModelResult(
                model_name=f"pillar_{name}",
                country="us",
                as_of=utc_now(),
                value=read.direction,
                confidence=compute_confidence(ConfidenceInputs()),
                interpretation=f"{name} pillar reads {_direction_label(read.direction)}.",
                context="Scorecard pillar read (census carrier).",
                inputs_used=[read.source],
                source_family=read.family,
            )
            for name, read in directional
        ]
    )
    value = census_input.value
    if not isinstance(value, dict):  # pragma: no cover - contract guard
        raise TypeError(
            "count_independent_families returned a non-dict value; the scorecard "
            "reads its `distinct_families` key and cannot continue."
        )
    distinct = value.get("distinct_families")
    if not isinstance(distinct, int):
        raise TypeError(
            "count_independent_families returned no integer `distinct_families`; "
            "the scorecard cannot proceed without a measured family count."
        )
    return distinct, sorted({r.family.value for r in inputs.pillar_reads()})


def four_pillar_scorecard(inputs: ScorecardInputs) -> ModelResult:
    """Classify four-pillar convergence, weighted by source independence.

    Returns one of ``NO_SIGNAL`` / ``CONFLICTED`` / ``HIGH`` / ``MEDIUM`` /
    ``LOW``, plus the agreement fraction, the dissent count, the agreement
    margin and the **measured** independent-family count.

    The published ``value`` carries more than the verdict on purpose. The two
    quantities the specification's gates depend on — agreement and independence
    — were both invisible in its output, so a reader could see "HIGH" without
    being able to see *why*, and the thresholds could not be audited from the
    result. Every quantity that decides the verdict is now published with it.

    Confidence comes from ``compute_confidence()`` (Section 22.8) and is **flat
    across verdicts**: the verdict describes the world, the confidence describes
    how well this function measured it. ``CONFLICTED`` is not less certain than
    ``LOW``; it is a differently-shaped fact about the same quality of input.
    """
    settings = get_settings().scorecard
    directions = [r.direction for r in inputs.pillar_reads()]
    non_neutral = [d for d in directions if d != 0]
    n = len(non_neutral)

    independent_families, family_names = _pillar_census(inputs)

    up = sum(1 for d in non_neutral if d > 0)
    down = sum(1 for d in non_neutral if d < 0)
    # CONFLICTED requires a genuine STANDOFF — at least two pillars pointing each
    # way. A 3-vs-1 split is NOT a standoff: it is a clear majority with a single
    # dissenter, which the §20.11 severity model assigns to MEDIUM. The prior
    # `up > 0 and down > 0` gate routed every such split to CONFLICTED, which made
    # the MEDIUM branch (requires NOT opposed AND dissent>0) unreachable — a
    # contradiction of this module's own docstring. Narrowing the predicate to
    # `>= 2 on each side` keeps 2-vs-2 splits CONFLICTED while letting 3-vs-1
    # reach MEDIUM (Defect 5 / F-SC-001). See also convergence.py.
    opposed = up >= 2 and down >= 2
    # Agreement measured two ways, both published: `agree_frac` is the
    # specification's own measure (larger side over the non-neutral count); the
    # margin is the share by which the larger side leads, which reaches 0.0 on a
    # tie and does not privilege either direction.
    agree_frac = max(up, down) / n if n else 0.0
    margin = abs(up - down) / n if n else 0.0
    dissent = n - max(up, down) if n else 0

    if n == 0:
        verdict: ConvergenceVerdict = "NO_SIGNAL"
        reason = (
            "all four pillars read neutral — no directional signal to converge "
            "on. This is distinct from LOW, where signals exist and disagree"
        )
    elif opposed:
        verdict = "CONFLICTED"
        up_names = [name for name, d in zip(_PILLARS, directions, strict=True) if d > 0]
        down_names = [name for name, d in zip(_PILLARS, directions, strict=True) if d < 0]
        reason = (
            f"the pillars oppose each other — {', '.join(up_names)} read "
            f"tightening while {', '.join(down_names)} read easing. Agreement is "
            f"{agree_frac:.0%} and the read is a genuine split rather than weak "
            f"agreement"
        )
    elif dissent <= settings.high_dissent_ceiling and (
        independent_families >= settings.high_family_floor
    ):
        verdict = "HIGH"
        reason = (
            f"unanimous among {n} directional pillar(s), backed by "
            f"{independent_families} independent source families"
        )
    elif dissent <= settings.medium_dissent_ceiling and (
        independent_families >= settings.medium_family_floor
    ):
        verdict = "MEDIUM"
        reason = (
            f"{n - dissent} of {n} directional pillars agree with {dissent} "
            f"dissenting, backed by {independent_families} independent source "
            f"families"
        )
    else:
        verdict = "LOW"
        if independent_families < settings.medium_family_floor:
            reason = (
                f"{n} pillar(s) agree but they span only {independent_families} "
                f"source family/families, below the {settings.medium_family_floor} "
                f"required for MEDIUM — agreement within one release is one vote, "
                f"however many sub-measures compose it"
            )
        else:
            reason = (
                f"agreement is weak: {n - dissent} of {n} pillars agree with "
                f"{dissent} dissenting, above the "
                f"{settings.medium_dissent_ceiling} dissenter(s) MEDIUM permits"
            )

    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
            source_independence_count=independent_families,
        )
    )

    return ModelResult(
        model_name="four_pillar_scorecard",
        country="us",
        as_of=utc_now(),
        value={
            "classification": verdict,
            "agreement_fraction": round(agree_frac, 4),
            "agreement_margin": round(margin, 4),
            "dissenting_pillars": dissent,
            "non_neutral_pillars": n,
            "independent_families": independent_families,
            "family_names": family_names,
            "pillar_directions": dict(zip(_PILLARS, directions, strict=True)),
        },
        confidence=confidence,
        interpretation=f"Four-pillar convergence: {verdict} — {reason}.",
        context=(
            "Weighted by MEASURED independent source families (Section 15.19-D), "
            "not by the raw signal count. MEDIUM permits one dissenting pillar; "
            "HIGH requires unanimity. CONFLICTED is a first-class blocking "
            "outcome (Module 12.2)."
        ),
        inputs_used=[f"{name}_signal" for name in _PILLARS] + ["source_families"],
        warnings=_scorecard_warnings(
            verdict=verdict,
            independent_families=independent_families,
            family_names=family_names,
            agree_frac=agree_frac,
            n=n,
            conflicted_base_share=settings.conflicted_base_share,
            high_family_floor=settings.high_family_floor,
        ),
    )


def _scorecard_warnings(
    *,
    verdict: str,
    independent_families: int,
    family_names: list[str],
    agree_frac: float,
    n: int,
    conflicted_base_share: float,
    high_family_floor: int,
) -> list[str]:
    """Build the warning list. Every branch is reachable by some test."""
    warnings: list[str] = [
        "Thresholds are illustrative starting heuristics, not calibrated "
        "against realised convergence outcomes — Phase 5+ calibration required.",
    ]
    if verdict == "CONFLICTED":
        warnings.append(
            "CONFLICTED — the pillars point opposite ways. This MUST block trade "
            "construction (Module 12.2). Note that CONFLICTED is the BASE STATE "
            f"of a four-pillar read: {conflicted_base_share:.1%} of the "
            "admissible input space classifies this way, so the verdict alone "
            "does not identify this read as unusual."
        )
    elif verdict == "NO_SIGNAL":
        warnings.append(
            "NO_SIGNAL — all four pillars neutral. This is not LOW: no "
            "directional read exists, so there is nothing for the pillars to "
            "agree or disagree about."
        )
    elif agree_frac >= 0.75 and independent_families < high_family_floor:
        warnings.append(
            f"Agreement is high ({agree_frac:.0%}) but the pillars span only "
            f"{independent_families} source family/families "
            f"({', '.join(family_names)}). This is likely redundant evidence "
            "rather than genuine convergence — the case Section 15.19-D exists "
            "to catch."
        )
    if 0 < n < 4 and verdict not in {"NO_SIGNAL", "CONFLICTED"}:
        warnings.append(
            f"Only {n} of 4 pillars carried a non-neutral read; the other "
            f"{4 - n} were neutral and are excluded from the agreement "
            "denominator. A verdict computed over fewer pillars is less "
            "supported by construction."
        )
    return warnings
