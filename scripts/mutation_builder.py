"""Mutation sweep for ``build_us_macro_thesis`` (D-069).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/builder.py`` in place, so any concurrent test
run, live check or probe reads a mutated module. The blast radius is the
repository.

What this increment is really testing
-------------------------------------
``build_us_macro_thesis`` is the **seam function** — on the Tier 4 checklist and
the Phase 3 checklist, the point where the models layer stops producing numbers
and the thesis layer starts making claims. Its content is *ordering* and
*refusal*, so the defects here divide into the two shapes lesson 5bc names:

- **PRESENCE defects** — a missing field, guard, label or branch. A fixture can
  name the omission, so a behavioural test kills them. The three gate helpers,
  the sentinel pass-through reader, the trigger literals.
- **INTERACTION defects** — two halves that are each correct and can never
  interleave. This is where the increment's **real** defect was found, and it is
  why the sweep is shaped the way it is: the first shipped ``_render`` published
  only the trigger line, so the model warnings and Section 22.5's market-path
  contamination disclosure were dropped from **every stand-down** — and the
  stand-down is the live default today. No single-field test saw it; the live
  check measured it (``contaminated=0 proxy=0`` where the contaminated branch
  was definitely taken).
- **ORDERING defects** — the gate order. Q6 → Q7 → Q8 is observable *only*
  through ``convergence_classification`` on a Q6 stand-down, so this file's
  mutants M2/M3 are paired with a strictness test that reads the source.

What IS killable:

1. **Q6 reads the published gap's verdict.** ``M1`` recomputes the significance
   test from ``abs(raw_gap)`` against the ensemble dispersion, which is
   §16.2's second, competing definition — the defect divergence 8 names.
2. **Q6 short-circuits.** ``M2`` makes Q6 fall through instead of returning, so a
   sub-noise-floor gap proceeds to the instrument.
3. **Q7 is checked before Q6.** ``M3`` reorders the first two gates.
4. **Q7's trigger is its own.** ``M4`` makes Q7 emit Q6's trigger literal.
5. **Q7 requires the assessment.** ``M5`` drops the type refusal.
6. **Q8's trigger is its own.** ``M6`` makes Q8 emit Q7's trigger literal.
7. **Q8 is checked at all.** ``M7`` removes Q8's stand-down branch, restoring
   §16.2's sample — which has no Q8 (divergence 3).
8. **A stand-down carries the model warnings.** ``M8`` reverts ``_render`` to
   the shipped-broken form: publish only the trigger line. **This is the
   increment's real defect, and killing it is the sweep's main job.**
9. **The trigger line stays first.** ``M9`` prepends the collected warnings
   *before* the trigger line, so a reader meets the caveats first.
10. **The instrument reader passes sentinels through.** ``M10`` maps a sentinel
    to a production instrument — Section 22.12's forbidden substitution.
11. **The sentinel is not defaulted.** ``M11`` substitutes a fallback whenever
    the reader finds no dict, so a refused selection silently becomes a trade.
12. **The direction follows the selector.** ``M12`` reverts to §16.2's
    gap-only rule, the divergence 6 defect.
13. **The scenario list is not fabricated.** ``M13`` fills ``[]`` with a made-up
    distribution.
14. **The regime disclosure survives.** ``M14`` claims a classified state.
15. **The catalyst failure is a warning, not a propagation.** ``M15`` re-raises.
16. **Only ``CatalystSourceError`` is caught.** ``M16`` narrows the catch to
    ``ValueError``, so the real error escapes.
17. **The falsifier is the assessment's own text.** ``M17`` writes a sentinel
    into ``stop_or_invalidation`` on the live path, which is the LTCM gate.
18. **The control.** ``M18.1`` re-spells the gap direction as an equivalent
    expression — must survive.

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether the caller passed the right ``thesis_type``.** Correct by
   construction: the builder takes the choice as a parameter precisely because a
   gap cannot imply it (divergence 1). A sweep over this file cannot see a
   caller's analytical judgment.
2. **Whether ``EconomyReads`` holds the right three models.** Same class. The
   builder refuses to derive them (no snapshot-fed helper exists — measured), so
   their correctness is not a property of this file.
3. **Whether the three gates fire on a *future* day's data.** That is a
   measurement about the world, not a mutation. It is recorded in the live test
   and in D-069's prose.
4. **Whether ``collect_all_warnings`` de-duplicates correctly.** D-067's sweep
   certifies that module; M8 here proves the builder **calls** it.
5. **Whether a sentinel route is reached at all.** O-87 measured that
   ``select_instrument`` publishes two shapes; M10/M11 prove the reader handles
   both, not which one today's universe produces.

The honesty control
-------------------
``M18.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything.

Anchors
-------
Every anchor is verified against the SHIPPED source by ``check_targets`` before a
single mutation is applied — present **exactly once** — and by
``check_anchor_landings``, which proves it lands in a symbol this increment owns.

``refuse_on_noop`` is set for every mutation, which is D-064's lesson 93: a
mutation whose ``old`` text is absent is reported NOT APPLIED and, in the D-064
sweep, silently left the denominator — the sweep certified ``25/27`` while two
mutations never ran. Here an unapplied mutation is a **refusal**, not a note.
"""

from __future__ import annotations

import argparse
import ast
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILDER = REPO / "src/macro_engine/thesis_layer/builder.py"

#: The test selection a surviving mutation must be *capable* of killing.
#: ``test_builder.py`` carries the behavioural assertions for every mutant;
#: ``test_builder_strictness.py`` carries the **static** guards no behavioural
#: assertion can make — the gate ORDER (read by source position) and the
#: sentinel pass-through (an absence, not a behaviour). Both files are named
#: because a kill that could have come from either must be attributable.
PYTEST_TARGETS = [
    "tests/thesis_layer/test_builder.py",
    "tests/thesis_layer/test_builder_strictness.py",
]


@dataclass(frozen=True)
class Mutation:
    """One single-substring rewrite of one file."""

    group: str
    name: str
    path: Path
    old: str
    new: str
    intent: str
    expect_killed: bool | None = None
    inert_proof: str = ""


@dataclass
class Result:
    """The outcome of applying and testing one mutation."""

    mutation: Mutation
    applied: bool
    exit_code: int
    output: str = field(default="")

    @property
    def killed(self) -> bool:
        """True only for a genuine test failure.

        Exit 4 is pytest's usage error (a missing path, a plugin crash, no tests
        collected). Counting it as a kill is how D-051's first draft reported
        56/56 against a control that could not fail.
        """
        return self.exit_code not in (0, 4)


# ---------------------------------------------------------------------------
# Anchors — read out of the shipped source, never transcribed from memory
# ---------------------------------------------------------------------------


def enclosing_symbol(text: str, index: int) -> str:
    """The top-level symbol a character offset falls inside, or ``"<module>"``.

    **Deliberately duplicated from ``tools/sweep_health.py``, not imported** —
    ``mypy --strict`` refuses the import (``tools/`` has no ``__init__.py`` and
    the gate names both ``src tests scripts tools``, so one file becomes two
    modules). The owner is resolved by **parsing**, not by a backwards line walk,
    because a line-walk matches ``def ...`` inside a comment (D-064).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "<module>"
    offset_line = text[:index].count("\n") + 1
    enclosing: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.lineno > offset_line:
            continue
        if node.end_lineno is not None and node.end_lineno < offset_line:
            continue
        enclosing.append((node.lineno, node.name))
    if not enclosing:
        return "<module>"
    return max(enclosing)[1]


#: The top-level symbols this increment owns in the builder.
_ALLOWED_ANCHOR_OWNERS: dict[str, frozenset[str]] = {
    "builder.py": frozenset(
        {
            "build_us_macro_thesis",
            "_render",
            "_instrument_from",
            "_direction_for",
            "_regime_view",
            "_scalar",
            "_family_count",
            "_resolve_catalysts",
            "_thesis_warnings",
            "_q6_decision",
            "_q7_decision",
            "_q8_decision",
            "_gap_direction",
            "new_thesis_id",
            "EconomyReads",
            "<module>",
        }
    ),
}

# --- M1: Q6 reads the published gap's own verdict ----------------------------
_Q6_CONDITION = "    if not gap.is_meaningful:"

# --- M2: Q6 short-circuits before Q7 -----------------------------------------
#: The Q6 return block, up to and including its closing paren. Mutating the
#: `return` into a no-op lets a sub-noise-floor gap fall through to Q7.
_Q6_RETURN = """        decision = _q6_decision(gap)
        return _render("""

# --- M3: the gate ORDER (STATIC kill) ----------------------------------------
#: The Q7 branch condition. Swapping the two gate conditions is the reorder; the
#: anchor is the *comparison*, so the mutant changes which gate is evaluated
#: against which value rather than merely moving a line.
_Q7_CONDITION = "    if convergence is ConvergenceClassification.CONFLICTED:"

# --- M4: Q7's trigger is its own ---------------------------------------------
_Q7_TRIGGER = '        trigger="conflicted_signals",'

# --- M5: Q7 requires the assessment ------------------------------------------
_Q7_TYPE_GUARD = "    if not isinstance(assessment, ConfirmationSignalAssessment):"

# --- M6: Q8's trigger is its own ---------------------------------------------
_Q8_TRIGGER = '        trigger="no_falsifier",'

# --- M7: Q8 is checked at all -------------------------------------------------
_Q8_CONDITION = "    if not invalidation.identified:"

# --- M8: a stand-down carries the model warnings ------------------------------
#: The append that D-069's live check forced into existence. Reverting it to a
#: no-op restores the shipped defect exactly.
_WARNING_APPEND = """    if warnings:
        thesis.warnings = [*thesis.warnings, *warnings]
    return thesis"""

# --- M9: the trigger line stays first -----------------------------------------
#: ``thesis.warnings`` is ``[trigger_line]`` at this point. Prefixing the
#: collected warnings inverts the order D-068 established.
_WARNING_ORDER = "        thesis.warnings = [*thesis.warnings, *warnings]"

# --- M10: the instrument reader passes sentinels through ----------------------
#: The ``isinstance(value, str)`` branch returns the sentinel unchanged. The
#: mutant maps it to a production instrument — Section 22.12's forbidden
#: substitution.
_SENTINEL_BRANCH = """    if isinstance(value, str):
        if not value:
            raise ValueError("""

# --- M11: the sentinel is not defaulted ---------------------------------------
#: The dict branch's refusal when ``instrument`` is missing. Mutating it into a
#: fallback makes a refused selection silently tradeable.
_DICT_REFUSAL = """    if not isinstance(instrument, str) or not instrument:
        raise KeyError("""

# --- M12: the direction follows the selector ----------------------------------
#: The preference inside ``_direction_for``. ``isinstance``-guarded on a dict so
#: the anchor cannot match the sentinel branch above it.
_DIRECTION_SELECTOR = """    value = selection.value
    published = value.get("direction") if isinstance(value, dict) else None
    if published in ("long", "short"):
        return str(published)"""

# --- M13: the scenario list is not fabricated ---------------------------------
#: The LIVE path's scenario assignment — where a fabricated distribution would
#: be published. The stand-down's ``[]`` is a different site (asserted
#: behaviourally); mutating this one proves the live path's four are real.
_SCENARIO_ASSIGNMENT = "    scenarios = build_scenario_distribution(gap, convergence)"

# --- M14: the regime disclosure survives --------------------------------------
_REGIME_NOTE = '"state": None,'

# --- M15: the catalyst failure is a warning, not a propagation -----------------
#: The ``except`` header alone. The mutant re-raises the error it just caught,
#: which is the propagation §16.2's sample would have produced.
_CATALYST_CATCH = "    except CatalystSourceError as exc:"
_RE_RAISE = (
    "    except CatalystSourceError as exc:\n"
    "        raise exc from None\n"
    "    except Exception:  # unreachable, mutated"
)

# --- M16: only ``CatalystSourceError`` is caught -------------------------------
_CATALYST_EXC_TYPE = "    except CatalystSourceError as exc:"

# --- M17: the falsifier is the assessment's own text ---------------------------
_FALSIFIER = "            stop_or_invalidation=invalidation.text,"

# --- M18: the honesty control ---------------------------------------------------
#: ``_gap_direction`` returns ``"long"`` for a negative gap. The control
#: re-spells the comparison as its negation on the same operand, which is the
#: identity — so the behaviour is identical and the mutant must survive.
_CONTROL_ANCHOR = '    return "long" if gap.raw_gap < 0 else "short"'


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: Q6 reads the published gap's verdict ---------------------------
        Mutation(
            group="M1",
            name="M1.1 Q6 recomputes the significance test from the raw gap",
            path=BUILDER,
            old=_Q6_CONDITION,
            new="    if abs(gap.raw_gap) <= abs(gap.raw_gap) * 1e12:",
            intent=(
                "Restores §16.2's second definition of the same predicate: the "
                "sample tests the gap against the ENSEMBLE dispersion while the "
                "shipped gap tests its own median-based one, so the verdict and "
                "the evidence published beside it can disagree. The kill is "
                "test_q6_reads_the_gaps_own_verdict_not_a_recomputation (the gap "
                "is not meaningful, so the guard must fire and this mutant does "
                "not)."
            ),
        ),
        # -- M2: Q6 short-circuits ----------------------------------------------
        Mutation(
            group="M2",
            name="M2.1 Q6 does not short-circuit, so a sub-floor gap proceeds",
            path=BUILDER,
            old=_Q6_RETURN,
            new="""        decision = _q6_decision(gap)
        if False:
            return _render(""",
            intent=(
                "A gap inside the rules' own disagreement no longer stands the "
                "sentence down, so the builder trades a difference it has just "
                "called noise. The kill is test_q6_fires_and_names_its_trigger_"
                "and_hands_over_the_gap."
            ),
        ),
        # -- M3: the gate ORDER (STATIC kill) ------------------------------------
        Mutation(
            group="M3",
            name="M3.1 the Q7 condition is evaluated where Q6's belongs (STATIC)",
            path=BUILDER,
            old=_Q7_CONDITION,
            new="    if not gap.is_meaningful:",
            intent=(
                "Two identical guards now stand in for each other, so the gate "
                "that fires is decided by a branch that no longer tests its own "
                "question. Behaviourally most inputs still stand down — which is "
                "why the kill is the STATIC assertion "
                "test_the_three_gates_are_checked_in_the_documented_order, which "
                "reads the source positions."
            ),
        ),
        # -- M4: Q7's trigger is its own -----------------------------------------
        Mutation(
            group="M4",
            name="M4.1 Q7 states Q6's trigger",
            path=BUILDER,
            old=_Q7_TRIGGER,
            new='        trigger="gap_below_dispersion",',
            intent=(
                "O-70/O-79/O-85's closing condition, inverted: the published "
                "thesis attributes the stand-down to a gate that did not fire, so "
                "counting no-trades by cause gives a wrong answer. The kill is "
                "test_q7_fires_on_directly_opposed_reads_and_names_its_trigger."
            ),
        ),
        # -- M5: Q7 requires the assessment --------------------------------------
        Mutation(
            group="M5",
            name="M5.1 Q7 no longer refuses a non-assessment",
            path=BUILDER,
            old=_Q7_TYPE_GUARD,
            new="    if False:",
            intent=(
                "A caller can pass anything, and the census that makes the reason "
                "meaningful is gone (D-066's whole point). The kill is "
                "test_q7_refuses_anything_but_a_confirmation_signal_assessment."
            ),
        ),
        # -- M6: Q8's trigger is its own -----------------------------------------
        Mutation(
            group="M6",
            name="M6.1 Q8 states Q7's trigger",
            path=BUILDER,
            old=_Q8_TRIGGER,
            new='        trigger="conflicted_signals",',
            intent=(
                "Same class as M4 for the third gate. The kill is "
                "test_q8_fires_when_nothing_can_be_read_and_hands_over_the_"
                "assessment."
            ),
        ),
        # -- M7: Q8 is checked at all --------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 Q8's stand-down branch is removed",
            path=BUILDER,
            old=_Q8_CONDITION,
            new="    if False:",
            intent=(
                "Restores §16.2's sample, which has NO Q8 (divergence 3): a thesis "
                "whose falsifier could not be derived proceeds to a trade. The "
                "kill is the whole Q8 section of test_builder.py, plus the "
                "strictness test that pins the gate's presence."
            ),
        ),
        # -- M8: a stand-down carries the model warnings -------------------------
        Mutation(
            group="M8",
            name="M8.1 a stand-down publishes only the trigger line (THE REAL DEFECT)",
            path=BUILDER,
            old=_WARNING_APPEND,
            new="""    if False:
        thesis.warnings = [*thesis.warnings, *warnings]
    return thesis""",
            intent=(
                "The increment's real defect, restored verbatim: every stand-down "
                "— which is the live default today — loses the model warnings and "
                "Section 22.5's market-path contamination disclosure, so a reader "
                "asking 'why no trade?' cannot see how weak the inputs were. The "
                "kill is test_a_stand_down_carries_the_model_warnings_too."
            ),
        ),
        # -- M9: the trigger line stays first ------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the collected warnings are written before the trigger line",
            path=BUILDER,
            old=_WARNING_ORDER,
            new="        thesis.warnings = [*warnings, *thesis.warnings]",
            intent=(
                "D-068 owns the ordering: the trigger line must be first so a "
                "reader meets the stand-down before the caveats it is made of. "
                "The kill is test_the_trigger_line_still_comes_first_on_a_stand_"
                "down."
            ),
        ),
        # -- M10: the instrument reader passes sentinels through ------------------
        Mutation(
            group="M10",
            name="M10.1 a sentinel instrument is substituted with a production one",
            path=BUILDER,
            old=_SENTINEL_BRANCH,
            new="""    if isinstance(value, str):
        return "UST 2yr note futures"
    if False:
        if not value:
            raise ValueError(""",
            intent=(
                "Section 22.12's forbidden substitution: a universe that refused to "
                "name an instrument — because no production expression exists, or "
                "because the country is not built — is reported as a concrete "
                "trade instead. The analytical-only path measured by O-87. The "
                "kill is test_a_sentinel_instrument_is_passed_through_not_"
                "substituted."
            ),
        ),
        # -- M11: the sentinel is not defaulted -----------------------------------
        Mutation(
            group="M11",
            name="M11.1 a selection with no instrument silently becomes a trade",
            path=BUILDER,
            old=_DICT_REFUSAL,
            new="""    if False:
        raise KeyError(""",
            intent=(
                "A dict-shaped selection that carries no instrument now yields a "
                "default, so a refusal is indistinguishable from a trade. The kill "
                "is test_a_dict_selection_without_an_instrument_is_refused."
            ),
        ),
        # -- M12: the direction follows the selector ------------------------------
        Mutation(
            group="M12",
            name="M12.1 the direction reverts to the gap-sign-only rule",
            path=BUILDER,
            old=_DIRECTION_SELECTOR,
            new="""    value = selection.value
    published = value.get("direction") if isinstance(value, dict) else None
    if False:
        return str(published)""",
            intent=(
                "Divergence 6 restored: §16.2's `'long' if raw_gap < 0 else "
                "'short'` is right for a rates instrument and false for a curve "
                "steepener, an FX carry or an equity expression. The selector's "
                "published direction is discarded and the gap's sign is used "
                "instead. The kill is "
                "test_the_direction_reader_prefers_the_selectors_published_"
                "direction, whose fixture makes the two DISAGREE."
            ),
        ),
        # -- M13: the scenario list is not fabricated ------------------------------
        Mutation(
            group="M13",
            name="M13.1 the scenario distribution is replaced by a fixed guess",
            path=BUILDER,
            old=_SCENARIO_ASSIGNMENT,
            new="    scenarios = []  # mutated: a distribution was asked for",
            intent=(
                "A live thesis loses the four-outcome distribution Q10 asks for, so "
                "the sizing logic's `scenarios` and the asymmetry §7.3 documents "
                "vanish without anything failing. The kill is the live-path "
                "assertion that a DRAFT thesis carries four scenarios."
            ),
        ),
        # -- M14: the regime disclosure survives -----------------------------------
        Mutation(
            group="M14",
            name="M14.1 the unclassified regime claims to be classified",
            path=BUILDER,
            old=_REGIME_NOTE,
            new='"state": "expansion",',
            intent=(
                "The disclosure that no regime model ran is replaced by an invented "
                "state, so a reader cannot tell a measurement from a placeholder. "
                "The kill is test_the_regime_view_discloses_that_it_did_not_run."
            ),
        ),
        # -- M15: the catalyst failure is a warning, not a propagation -------------
        Mutation(
            group="M15",
            name="M15.1 an unreachable calendar propagates instead of warning",
            path=BUILDER,
            old=_CATALYST_CATCH,
            new=_RE_RAISE,
            intent=(
                "A network blip now makes every thesis fail, and the caller learns "
                "nothing about which input was missing. The kill is "
                "test_an_unreachable_calendar_is_a_labelled_warning_not_a_lost_"
                "thesis."
            ),
        ),
        # -- M16: only ``CatalystSourceError`` is caught ---------------------------
        Mutation(
            group="M16",
            name="M16.1 the catch is narrowed to ValueError",
            path=BUILDER,
            old=_CATALYST_EXC_TYPE,
            new="    except ValueError as exc:  # mutated",
            intent=(
                "The real error escapes uncaught, so the labelled-warning branch "
                "(and its test) is unreachable — while still catching SOMETHING, "
                "which is what makes this the interesting variant of M15 rather "
                "than a duplicate. The kill is "
                "test_an_unreachable_calendar_is_a_labelled_warning_not_a_lost_"
                "thesis."
            ),
        ),
        # -- M17: the falsifier is the assessment's own text ------------------------
        Mutation(
            group="M17",
            name="M17.1 the live thesis writes a truthy sentinel as its falsifier",
            path=BUILDER,
            old=_FALSIFIER,
            new='            stop_or_invalidation="n/a",',
            intent=(
                "Lesson 5bd: 'n/a' is truthy and satisfies the LTCM gate, so a "
                "thesis whose only falsifier was never derived asserts one "
                "anyway. The kill is test_the_falsifier_is_the_assessments_own_"
                "text."
            ),
        ),
        # -- M18: the honesty control ----------------------------------------------
        Mutation(
            group="M18",
            name="M18.1 the gap direction is re-spelled as its negation (CONTROL)",
            path=BUILDER,
            old=_CONTROL_ANCHOR,
            new='    return "long" if not (gap.raw_gap >= 0) else "short"',
            intent=(
                "CONTROL — `not (x >= 0)` is `x < 0` for every float, so the "
                "direction is unchanged. Semantically identical; it must survive."
            ),
            expect_killed=False,
            inert_proof=(
                "CONTROL — the comparison is rewritten as its De Morgan-negated "
                "form, which is the identity over the reals (NaN cannot reach here: "
                "`_gap_direction` already refused a gap whose sign is "
                "indeterminate). Nothing observable changes, so a kill would mean "
                "the selection is detecting the SHAPE of the code rather than its "
                "behaviour, and no other number here could be trusted."
            ),
        ),
    ]


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test — a conclusion about code nobody mutated.
    """
    problems: list[str] = []
    by_file: dict[Path, str] = {}
    for path in {mt.path for mt in mutations}:
        by_file[path] = path.read_text(encoding="utf-8")

    for mt in mutations:
        text = by_file[mt.path]
        if mt.old == mt.new:
            problems.append(f"{mt.name}: INERT BY CONSTRUCTION (old == new)")
            continue
        count = text.count(mt.old)
        if count == 0:
            problems.append(f"{mt.name}: target ABSENT in {mt.path.name} (0 occurrences)")
        elif count > 1:
            problems.append(
                f"{mt.name}: target AMBIGUOUS in {mt.path.name} "
                f"({count} occurrences) -- str.replace would rewrite the first"
            )
    if verbose:
        print(f"check_targets: {len(mutations)} mutations, {len(problems)} problem(s)")
        for p in problems:
            print(f"  !! {p}")
    return problems


def check_anchor_landings(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every anchor lands in a symbol THIS increment owns.

    ``check_targets`` proves an anchor is unique; it cannot prove it is in the
    **right place** (**O-67**). ``builder.py`` has a 100-line module docstring
    quoting §16.2's sample — including the very gate conditions M1/M3 anchor on —
    so a careless anchor could match the prose and mutate a docstring.
    """
    problems: list[str] = []
    for mt in mutations:
        allowed = _ALLOWED_ANCHOR_OWNERS.get(mt.path.name)
        if allowed is None:
            problems.append(f"{mt.name}: no anchor-owner rule for {mt.path.name}")
            continue
        text = mt.path.read_text(encoding="utf-8")
        index = text.find(mt.old)
        if index < 0:
            continue  # check_targets already reports ABSENT
        owner = enclosing_symbol(text, index)
        if owner not in allowed:
            problems.append(
                f"{mt.name}: anchor lands in {owner!r}, which this increment does "
                f"not own (allowed: {sorted(allowed)})"
            )
    if verbose:
        print(f"check_anchor_landings: {len(mutations)} mutations, {len(problems)} problem(s)")
        for p in problems:
            print(f"  !! {p}")
    return problems


def check_tests_collect() -> list[str]:
    """Prove the test selection actually collects tests BEFORE the sweep runs.

    A bad target path makes pytest exit **4**, and exit 4 is not a kill. Without
    this gate a typo'd path produces a false 100%-killed report (D-051).
    """
    problems: list[str] = []
    for target in PYTEST_TARGETS:
        if not (REPO / target).exists():
            problems.append(f"test target ABSENT: {target}")
    if problems:
        return problems
    proc = subprocess.run(
        # The path is inlined as a literal rather than passed via PYTEST_TARGETS
        # because ruff's S603 treats a variable list as possible untrusted input.
        # It is the same string; the existence check above proves they cannot
        # drift.
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/thesis_layer/test_builder.py",
            "tests/thesis_layer/test_builder_strictness.py",
            "-m",
            "not live",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        problems.append(f"test selection does not collect (pytest exit {proc.returncode})")
        return problems
    match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
    if not match or int(match.group(1)) == 0:
        problems.append("test selection collects ZERO tests")
    return problems


def run_pytest() -> tuple[int, str]:
    """Run the targeted tests. Non-zero means the mutation was killed.

    Exit code **4** is pytest's "usage error / no tests collected", which is not
    a kill. ``-x`` is passed and is not optional (lesson 61): the kill signal
    must be cheap, because the cheap path is the one that gets used.
    """
    proc = subprocess.run(
        # Inlined literal, per the S603 note in ``check_tests_collect``.
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/thesis_layer/test_builder.py",
            "tests/thesis_layer/test_builder_strictness.py",
            "-m",
            "not live",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


#: The mutation currently written to disk, so a signal handler can undo it.
_IN_FLIGHT: list[tuple[Path, str] | None] = [None]


def _restore_in_flight(_signum: int, _frame: object) -> None:
    """Undo an in-flight mutation, then exit. Installed for SIGTERM/SIGINT.

    Without this a killed sweep leaves mutated source on disk — D-057's first run
    was stopped by a ``SIGTERM`` that bypassed the ``finally``, and D-062 caught a
    leftover (`MX3d`) with ``tools/sweep_health.py``'s scan. **O-83 adds: the
    scan is per-sweep, so a leftover in a SHARED file is invisible. This handler
    plus the close-procedure grep is the defence.**
    """
    pending = _IN_FLIGHT[0]
    if pending is not None:
        path, original = pending
        path.write_text(original, encoding="utf-8", newline="")
        print(f"\n!! interrupted -- restored {path.name} from the in-flight mutation")
    raise SystemExit(130)


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the selection, restore the file."""
    original = mutation.path.read_text(encoding="utf-8")
    mutated = original.replace(mutation.old, mutation.new, 1)
    if mutated == original:
        return Result(mutation=mutation, applied=False, exit_code=-1)

    _IN_FLIGHT[0] = (mutation.path, original)
    try:
        mutation.path.write_text(mutated, encoding="utf-8", newline="")
        code, out = run_pytest()
    finally:
        mutation.path.write_text(original, encoding="utf-8", newline="")
        _IN_FLIGHT[0] = None
    return Result(mutation=mutation, applied=True, exit_code=code, output=out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M1")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: build_us_macro_thesis (D-069)")
    print("FOREGROUND ONLY -- this rewrites files under src/ while it runs.")
    print("=" * 78)

    mutations = build_mutations()
    problems = check_targets(mutations)
    if problems:
        print(
            "\nREFUSING TO RUN: check_targets found absent or ambiguous targets. "
            "A sweep that mutates the wrong site reports survivors that mean "
            "nothing (D-048)."
        )
        return 2

    landing_problems = check_anchor_landings(mutations)
    if landing_problems:
        print(
            "\nREFUSING TO RUN: an anchor lands in a function this increment does "
            "not own. The mutant would rewrite a neighbour, the tests that catch it "
            "are not in this selection, and the sweep would report a survivor about "
            "code nobody mutated (O-67)."
        )
        return 2

    test_problems = check_tests_collect()
    if test_problems:
        print("\nREFUSING TO RUN: the test selection is broken, so exit codes")
        print("would not distinguish a kill from a harness error:")
        for p in test_problems:
            print(f"  !! {p}")
        return 2
    print(f"test selection collects cleanly: {', '.join(PYTEST_TARGETS)}")

    if args.list:
        for mt in mutations:
            print(f"  {mt.group:4} {mt.path.name:14} {mt.name}")
        return 0

    if args.group:
        mutations = [mt for mt in mutations if mt.group == args.group]
        if not mutations:
            print(f"no mutations in group {args.group}")
            return 2
        print(f"restricted to group {args.group}: {len(mutations)} mutation(s)")

    results: list[Result] = []
    for mt in mutations:
        print(f"\n--- {mt.group} {mt.name}")
        res = apply_and_test(mt)
        results.append(res)
        if not res.applied:
            print("    NOT APPLIED (no-op)")
        elif res.killed:
            first_fail = next(
                (ln for ln in res.output.splitlines() if ln.startswith("FAILED")),
                "(see output)",
            )
            print(f"    KILLED  {first_fail}")
        else:
            print("    SURVIVED")

    killed = sum(1 for r in results if r.applied and r.killed)
    survived = [r for r in results if r.applied and not r.killed]
    noop = [r for r in results if not r.applied]

    print("\n" + "=" * 78)
    print(f"applied {len(results) - len(noop)} / {len(results)}")
    print(f"killed  {killed}")
    print(f"survived {len(survived)}")

    # D-064's lesson 93: a mutation that was never APPLIED silently leaves the
    # denominator, and a sweep that does not say so can certify a run it did not
    # perform. The D-064 sweep printed "applied 25 / 27" and still certified.
    if noop:
        print("\nREFUSING TO CERTIFY: the following mutations were NOT APPLIED.")
        print("Their target text produced no change, so they tested nothing and")
        print("their absence from the survivor list is not evidence (lesson 93).")
        for r in noop:
            print(f"  !! {r.mutation.name}")
        return 2

    defects: list[str] = []
    if survived:
        print("\nsurvivors, classified:")
        for r in survived:
            name = r.mutation.name
            proof = r.mutation.inert_proof
            if not proof:
                defects.append(name)
                print(f"  [NO PROOF] {name}")
                continue
            tag = "control" if "CONTROL" in name else "inert"
            print(f"  [{tag}] {name}")
            for line in proof.splitlines():
                print(f"           {line}")

    print()
    if defects:
        print(
            "REFUSING TO CERTIFY: the following survivors carry no proof. An "
            "exemption must be an argument, not a label (O-42)."
        )
        for d in defects:
            print(f"  !! {d}")
        return 2

    control_name = "M18.1 the gap direction is re-spelled as its negation (CONTROL)"
    control = next((r for r in results if r.mutation.name == control_name), None)
    if control is not None and control.killed:
        print(
            "REFUSING TO CERTIFY: the honesty control was killed. The sweep is "
            "reporting kills it cannot justify, so no other number means anything."
        )
        return 2

    print("RESULT: every survivor is either expected or proven inert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
