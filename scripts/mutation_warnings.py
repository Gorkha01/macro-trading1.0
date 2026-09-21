"""Mutation sweep for ``collect_all_warnings`` (D-067).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/warnings.py``
in place, so any concurrent test run, live check or probe reads a mutated
module. The blast radius is the repository.

What this increment is really testing
-------------------------------------
Section 16.4's sample is nine lines and its entire content is a
``dict.fromkeys`` de-duplication. So almost every defect here is about **what a
one-dimensional return type can carry** rather than about arithmetic — and the
sweep is therefore unusual in one respect worth stating up front: **three of the
seven measured defects are not killable by any mutation of this file.** They are
consequences of the *signature* (what is passed in) and of *call sites that do
not exist yet*, and a mutation sweep can only test the code it has. Those are
listed in "what this sweep structurally CANNOT find" below, and they are carried
as open issues rather than silently dropped.

What IS killable:

1. **De-duplication drops the raiser count.** ``M1`` restores §16.4's flat output
   by rebuilding ``sources`` one-model-per-text, so the count defect 1 discarded
   is discarded again (D-046's over/under-counting, inverted).
2. **Attribution collapses to a boolean.** ``M2`` finds the first raiser rather
   than every raiser — the shape a ``warning -> bool`` summary would have.
3. **Order is not preserved.** ``M3`` sorts, which §16.4's ``dict.fromkeys``
   deliberately does not do.
4. **The two censuses are not asserted.** ``M4`` deletes the raiser census. It
   is expected to **survive** and is **exempted with an argument**, because the
   guard is *unreachable by construction* (lesson 65) — not inert, but trippable
   by no input. Its presence is pinned statically instead.
5. **``unattributed`` is reordered ahead of the models' warnings.** ``M5``
   reverses ``all_texts``, so the published list is demoted behind the
   supplement. **This mutation survived the first run of the sweep** — a real
   gap in ``test_warnings.py``, closed by adding
   ``test_all_texts_puts_the_models_warnings_first`` rather than by exempting it.
6. **A warning-free model is dropped from the denominator.** ``M6`` removes the
   ``if not own: continue``/``+= 1`` guard, collapsing "3 of 9 warned" into
   "9 of 9 warned".
7. **``shared_warnings`` returns everything.** ``M7`` drops the filter, so the
   "what is systemic rather than local" question gets every warning back.
8. **The published summary is mutable.** ``M8`` drops ``frozen=True`` from
   ``WarningSummary``, so a caller can rewrite the thesis's disclosure.
9. **The control.** ``M9.1`` re-spells the result loop as an ``enumerate`` —
   semantically identical, must survive.

One mutation is killed by a **static** guard, not a behavioural one
-------------------------------------------------------------------
``M2`` narrows ``raisers`` to ``dict[str, str]``. Behaviourally the mutant dies
with an ``AttributeError`` raised from *inside* ``collect_all_warnings``, so
pytest reports a failure but no assertion of mine is what caught it — and if the
``.append`` were re-spelled too, nothing would. The kill used here is
``test_the_raiser_map_keeps_one_entry_per_model_not_per_text`` in
``tests/thesis_layer/test_warnings_strictness.py``, which reads the annotation
statically. That file exists because of this mutant.

What this sweep structurally CANNOT find
----------------------------------------
1. **Defect 4 — "no warnings" vs "not passed".** Both states are within one
   call's inputs, so no rewrite of this file can distinguish them for a caller
   that never passes anything. The repair is the two ``contributing_models`` /
   ``models_with_warnings`` fields, and the sweep confirms they survive (M6) —
   but whether a *future* caller checks them is not testable here.
2. **Defect 5 — §21.4's blocked class has no route in, at any call site.**
   Measured against the live registry: 5 blocked members, 0 routes. The route
   this module provides is ``unattributed``, and M5 proves it is ordered and
   separable; but **no call site passes it**, and a sweep over this file cannot
   create one. The obligation is discharged at ``build_us_macro_thesis``
   (Tier 4 #11), and until then it is open (O-81).
3. **Defect 6 — §5.4's flags do not reach any model's own warnings.** Same
   shape: the wiring lives in the models layer, not here.
4. **Whether de-duplication SHOULD be the published semantics.** §16.4 says it
   should, so it is preserved and the alternative reading is carried in
   ``sources`` rather than argued for. A mutation cannot settle a specification
   question (D-064's direction-blindness precedent).
5. **Whether the two internal censuses are ever tripped.** They cannot be, and
   that is the point of M4's exemption — an unreachable guard's *deletion* is
   unobservable, so the sweep reports it as a survivor and the argument for
   keeping it lives in the test file.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
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

from _sweep_gate import sweep_lifecycle

REPO = Path(__file__).resolve().parent.parent
WARNINGS = REPO / "src/macro_engine/thesis_layer/warnings.py"

#: The test selection a surviving mutation must be *capable* of killing.
#: ``test_warnings.py`` carries the behavioural assertions for every mutant;
#: ``test_warnings_strictness.py`` carries the two **static** guards (D-067) that
#: no behavioural assertion can make — the ``raisers`` annotation, whose mutant
#: dies inside the function under test rather than at an assertion, and the
#: internal censuses, which have no reachable input. Both files are named because
#: a kill that could have come from either must be attributable to one of them.
PYTEST_TARGETS = [
    "tests/thesis_layer/test_warnings.py",
    "tests/thesis_layer/test_warnings_strictness.py",
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
    see ``scripts/mutation_scenario_distribution.py`` for the full reason
    (``mypy --strict`` refuses the import: ``tools/`` has no ``__init__.py`` and
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


#: The top-level symbols this increment owns in each file.
_ALLOWED_ANCHOR_OWNERS: dict[str, frozenset[str]] = {
    "warnings.py": frozenset(
        {
            "collect_all_warnings",
            "WarningSummary",
            "WarningSource",
            "UnattributedWarning",
            "<module>",
        }
    ),
}

# --- M1: the raiser count survives ------------------------------------------
_RAISER_LIST = "            raisers.setdefault(text, []).append(result.model_name)"
_SOURCES_BUILD = """    sources = tuple(
        WarningSource(text=text, model_names=tuple(names)) for text, names in raisers.items()
    )"""

# --- M2: attribution collapses to one raiser --------------------------------
#: ``:`` widened to ``[\)]`` so the anchor spans the ``.append`` call, which
#: keeps it distinct from ``raisers: dict[...] = {}`` above it (D-048: an anchor
#: present twice is a refusal, and ``check_targets`` is what catches it).
_RAISER_TYPE = "    raisers: dict[str, list[str]] = {}"

# --- M3: order is preserved --------------------------------------------------
#: ``warnings`` is built from ``tuple(raisers)`` — dict insertion order, which is
#: §16.4's deliberate property. Spanning the following blank-comment line keeps
#: this anchor distinct from the two other ``tuple(...)`` builds in the file.
_WARNINGS_BUILD = "    warnings = tuple(raisers)  # de-duplicated, order-preserved (§16.4)"

# --- M4: the raiser census is asserted ---------------------------------------
_CENSUS = "    if total_raisers != total_own:"

# --- M5: unattributed is not merged into warnings ----------------------------
_ALL_TEXTS = "        return self.warnings + tuple(w.text for w in self.unattributed)"

# --- M6: a warning-free model is in the denominator --------------------------
#: The guard is the line to remove: with it gone every passed model increments
#: the warning count, so ``models_with_warnings == contributing_models`` and the
#: denominator stops distinguishing "3 of 9 warned" from "9 of 9 warned".
_WARNING_FREE_GUARD = """        if not own:
            continue
        models_with_warnings += 1"""

# --- M7: all_texts includes both halves --------------------------------------
#: The ``if not own: continue`` that keeps a quiet model out of ``models_with_warnings``
#: is M6's neighbour; M7 targets the property instead. Two distinct symbols, so
#: a kill cannot be attributed to the wrong one.
_SHARED_WARNINGS = "        return tuple(s for s in self.sources if s.raised_by_multiple_models)"

# --- M8: the frozen/extra-forbid config --------------------------------------
#: ``WarningSummary`` is the record the thesis publishes. Dropping ``frozen``
#: lets a caller mutate a published summary — the same defect the sibling
#: thesis-layer records guard. The anchor is scoped to ``WarningSummary`` by
#: spanning its ``warnings`` declaration, because ``extra="forbid", frozen=True``
#: appears once per model in this file (D-048).
_SUMMARY_CONFIG = """class WarningSummary(BaseModel):
    \"\"\"The aggregate, with a slot for each of the questions it answers.

    ``warnings`` is §16.4's output, unchanged in content and order — every
    consumer that wants the de-duplicated list gets exactly what it got before.
    Everything else is the answer the flat list could not carry.
    \"\"\"

    model_config = ConfigDict(extra="forbid", frozen=True)"""

# --- M9: the honesty control -------------------------------------------------
_CONTROL_ANCHOR = "    for result in model_results:"


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: the raiser count -------------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 sources keeps only the FIRST raiser of each text",
            path=WARNINGS,
            old=_RAISER_LIST,
            new="            raisers.setdefault(text, [result.model_name])",
            intent=(
                "Restores the count defect 1 discarded: one model per text, so "
                "'four models saw this' is published as 'a model saw this'. The "
                "kill is test_the_count_of_raisers_survives_de_duplication."
            ),
        ),
        # -- M2: attribution -----------------------------------------------------
        Mutation(
            group="M2",
            name="M2.1 raisers is a text->single-model map, not text->list",
            path=WARNINGS,
            old=_RAISER_TYPE,
            new="    raisers: dict[str, str] = {}",
            intent=(
                "The boolean alternative: a text maps to one raiser, so a shared "
                "warning and a solo one are the same shape, and the whole "
                "defect-1/defect-2 repair collapses back to the flat list's "
                "information content. The kill is "
                "test_the_raiser_map_keeps_one_entry_per_model_not_per_text, in "
                "test_warnings_strictness.py — see the note on that group."
            ),
        ),
        # -- M3: order -----------------------------------------------------------
        Mutation(
            group="M3",
            name="M3.1 warnings is sorted, not first-seen order",
            path=WARNINGS,
            old=_WARNINGS_BUILD,
            new="    warnings = tuple(sorted(raisers))",
            intent=(
                "§16.4's dict.fromkeys is order-preserving by design; sorting "
                "silently reorders the published list. The kill is "
                "test_warnings_is_de_duplicated_and_order_preserved."
            ),
        ),
        # -- M4: the raiser census -----------------------------------------------
        Mutation(
            group="M4",
            name="M4.1 the raiser census is not asserted (UNREACHABLE — exemption)",
            path=WARNINGS,
            old=_CENSUS,
            new="    if False:",
            intent=(
                "Deletes an internal guard that no input can trip: every warning "
                "belongs to exactly one model, so `total_raisers != total_own` "
                "cannot occur. Expected to SURVIVE, and exempted below with an "
                "argument rather than a label (D-067, lesson 65)."
            ),
            expect_killed=False,
            inert_proof=(
                "UNREACHABLE BY CONSTRUCTION, not inert by rewriting. `raisers` "
                "is appended exactly once per input warning "
                "(`raisers.setdefault(text, []).append(result.model_name)`), and "
                "`total_own` is the length of every model's own warning tuple, so "
                "`sum(len(s.model_names)) == sum(len(w))` holds identically. The "
                "guard is kept because it DOCUMENTS the invariant a summariser "
                "must not violate and would catch a future edit that made it "
                "reachable (e.g. collapsing a text before attributing it). No "
                "mutation of this file can make it fire, and the tests that pin "
                "its PRESENCE are "
                "test_the_internal_guards_are_unreachable_by_design and "
                "test_the_length_census_is_present."
            ),
        ),
        # -- M5: unattributed is ordered after the models' warnings ---------------
        Mutation(
            group="M5",
            name="M5.1 all_texts puts the unattributed class ahead of the models'",
            path=WARNINGS,
            old=_ALL_TEXTS,
            new="        return tuple(w.text for w in self.unattributed) + self.warnings",
            intent=(
                "`all_texts` reverses the two halves: §16.4's published list is "
                "demoted behind the supplement, and the union changes meaning "
                "without changing its contents. The kill is "
                "test_all_texts_puts_the_models_warnings_first — added by this "
                "sweep after the mutation SURVIVED the whole selection, which "
                "was a real gap in the test file rather than an inert change."
            ),
        ),
        # -- M6: the denominator -------------------------------------------------
        Mutation(
            group="M6",
            name="M6.1 a warning-free model is still counted as having warned",
            path=WARNINGS,
            old=_WARNING_FREE_GUARD,
            new="        models_with_warnings += 1",
            intent=(
                "The guard that keeps a quiet model out of the numerator is "
                "removed, collapsing '3 of 9 warned' into '9 of 9'. The kill is "
                "test_the_denominators_are_reported_separately."
            ),
        ),
        # -- M7: shared_warnings -------------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 shared_warnings returns every source, not only shared ones",
            path=WARNINGS,
            old=_SHARED_WARNINGS,
            new="        return tuple(self.sources)",
            intent=(
                "The 'what is systemic rather than local' question gets every "
                "warning back, which is the flat list's answer again. The kill "
                "is test_shared_warnings_exposes_only_the_multiply_raised."
            ),
        ),
        # -- M8: the published record is frozen ----------------------------------
        Mutation(
            group="M8",
            name="M8.1 WarningSummary is no longer frozen",
            path=WARNINGS,
            old=_SUMMARY_CONFIG,
            new=_SUMMARY_CONFIG.replace(
                'model_config = ConfigDict(extra="forbid", frozen=True)',
                'model_config = ConfigDict(extra="forbid")',
            ),
            intent=(
                "A published summary becomes mutable, so a caller can rewrite "
                "the thesis's disclosure after the fact. The kill is "
                "test_the_summary_is_frozen."
            ),
        ),
        # -- M9: the honesty control ---------------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the result loop is re-spelled as an enumerate (CONTROL)",
            path=WARNINGS,
            old=_CONTROL_ANCHOR,
            new="    for _index, result in enumerate(model_results):",
            intent=(
                "CONTROL — the loop variable is renamed and the index is unused "
                "but bound; the body is untouched, so the behaviour is identical."
            ),
            expect_killed=False,
            inert_proof=(
                "CONTROL — `enumerate` binds the same `result` for every "
                "iteration and `_index` is never read, so the function is "
                "semantically identical. The rename is why this can only be "
                "'proven inert' by inspection, not by a test."
            ),
        ),
    ]


_INERT_PROOFS: dict[str, str] = {
    "M4.1 the raiser census is not asserted (UNREACHABLE — exemption)": (
        "UNREACHABLE BY CONSTRUCTION, not inert by rewriting. `raisers` is "
        "appended exactly once per input warning, and `total_own` is the length "
        "of every model's own warning tuple, so `sum(len(s.model_names)) == "
        "sum(len(w))` holds identically and the guard cannot fire. The guard is "
        "kept because it documents the invariant a summariser must not violate; "
        "its presence is pinned by "
        "test_the_internal_guards_are_unreachable_by_design."
    ),
    "M9.1 the result loop is re-spelled as an enumerate (CONTROL)": (
        "CONTROL — `enumerate` binds the same `result` for every iteration and "
        "`_index` is never read, so the function is semantically identical. The "
        "rename is why this can only be 'proven inert' by inspection, not by a "
        "test."
    ),
}


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
    **right place** (**O-67**). ``warnings.py`` has several ``+= 1`` and
    ``tuple(...)``-shaped statements a careless anchor could match in a
    neighbour.
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
        # It is the same string; ``check_tests_collect`` already asserted the
        # path exists, so the two cannot drift.
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/thesis_layer/test_warnings.py",
            "tests/thesis_layer/test_warnings_strictness.py",
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
            "tests/thesis_layer/test_warnings.py",
            "tests/thesis_layer/test_warnings_strictness.py",
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
    leftover (`MX3d`) with ``tools/sweep_health.py``'s scan.
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
    print("mutation sweep: collect_all_warnings (D-067)")
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
            print(f"  {mt.group:4} {mt.path.name:20} {mt.name}")
        return 0

    if args.group:
        mutations = [mt for mt in mutations if mt.group == args.group]
        if not mutations:
            print(f"no mutations in group {args.group}")
            return 2
        print(f"restricted to group {args.group}: {len(mutations)} mutation(s)")

    # O-103: the sidecar is the interrupt defence with real reach here. On
    # win32 no Python signal handler runs for SIGTERM/SIGINT and a killed
    # process gets no `finally` turn, so `_restore_in_flight` above cannot
    # fire. This runs after the early returns so a run that mutates nothing
    # leaves no sidecar behind, and it heals a previous kill BEFORE the
    # baseline is read -- reading first would adopt a mutant as the baseline
    # (D-081).
    with sweep_lifecycle(sorted({mt.path for mt in mutations})):
        return _run_sweep(mutations)


def _run_sweep(mutations: list[Mutation]) -> int:
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
            proof = r.mutation.inert_proof or _INERT_PROOFS.get(name, "")
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

    control_name = "M9.1 the result loop is re-spelled as an enumerate (CONTROL)"
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
