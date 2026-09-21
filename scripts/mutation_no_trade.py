"""Mutation sweep for ``no_trade_thesis`` (D-068).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/no_trade.py`` in place, so any concurrent test
run, live check or probe reads a mutated module. The blast radius is the
repository.

What this increment is really testing
-------------------------------------
Section 16.4's ``no_trade_thesis`` is nine lines and its entire content is
``MacroThesis(... warnings=[reason])``. So — exactly like D-067 — almost every
defect here is about **what a one-dimensional signature and return type can
carry** rather than about arithmetic. That shapes which mutants are killable:

- The **five measured defects** (D-068) are: (1) the sample body raises, because
  ``MacroThesis`` has six required fields; (2) one string slot for three
  triggers; (3) the rich object each trigger already held is discarded;
  (4) ``warnings=[reason]`` accepts an empty string; (5) ``"n/a"`` satisfies the
  LTCM gate it stands down from.
- Defects **1, 3, 4 and 5** are all killable here, because they are properties
  of *this file*: the renderer's required-field contract, the ``evidence`` field,
  the empty-reason refusal, and the sentinel choice.
- Defect **2** is killable only through ``trigger`` being a *field* — the
  mutations that collapse it back to a string are M2 and M3.

What IS killable:

1. **The trigger is a field not a phrase.** ``M1`` drops the trigger from the
   warning line, so the published object no longer says which Q fired.
2. **The vocabulary stays closed.** ``M2`` widens the ``Literal`` to ``str``.
   This one is a **static** kill (``test_the_trigger_vocabulary_is_closed`` reads
   ``__args__``), listed with its own note.
3. **Every trigger has a label.** ``M3`` deletes a label, which facts the
   vocabulary/label census test.
4. **The empty reason is refused.** ``M4`` removes the guard, restoring §16.4's
   accept-``""`` behaviour (defect 4).
5. **Whitespace-only is refused too.** ``M5`` narrows the guard to the exact
   empty string, so ``"   "`` slips through.
6. **Q6's gap is required.** ``M6`` drops the missing-gap refusal, so the one
   trigger with a magnitude loses it silently.
7. **``elapsed`` measures the distance inside the floor.** ``M7`` drops the
   ``abs``, so a negative gap reports a distance that grows the *wrong* way.
8. **``elapsed`` is not fabricated where it does not apply.** ``M8`` sets
   ``elapsed`` for every trigger.
9. **The no-trade idea carries no sentinel.** ``M9`` restores ``"n/a"`` (defect
   5) — the mutation that makes the schema believe a falsifier exists.
10. **The renderer refuses a reserved override.** ``M10`` drops the guard, so a
    caller can replace the stand-down shape.
11. **The renderer writes the trigger line first.** ``M11`` appends instead of
    prepends.
12. **The decision is frozen.** ``M12`` drops ``frozen=True``.
13. **The status is the spec's WATCH.** ``M13`` changes it to DRAFT.
14. **The control.** ``M14.1`` re-spells the stored reason as a one-element join —
    must survive.

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether a caller states the right trigger.** The function records what it is
   told; a caller that passes ``trigger="no_falsifier"`` for a Q6 stand-down is
   outside this file. Same class as D-067's defect 5 (a route with no call
   site), and it is the seam ``build_us_macro_thesis`` closes (O-70/O-79).
2. **Whether ``evidence`` is the object the trigger actually held.** M-by-m the
   tests pin that the *passed* object survives; whether the caller passed the
   right one is not testable here.
3. **Whether §16.4's ``"n/a"`` is genuinely unsafe in production.** Measured:
   ``"n/a".strip()`` is truthy and the gate would accept it. That the gate is
   currently *skipped* on a no-trade is a property of ``is_trade``, not of this
   file — the mutant proves the sentinel is dangerous, not that the danger is
   live.
4. **The six required ``MacroThesis`` fields.** ``render_no_trade_thesis`` takes
   them as ``**thesis_fields``; whether a caller supplies the *correct* partial
   view is the builder's problem.

The honesty control
-------------------
``M14.1`` is semantically identical to the shipped code and **must survive**. If
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
NO_TRADE = REPO / "src/macro_engine/thesis_layer/no_trade.py"

#: The test selection a surviving mutation must be *capable* of killing.
#: ``test_no_trade.py`` carries the behavioural assertions for every mutant;
#: ``test_no_trade_strictness.py`` carries the **static** guard (D-068) that no
#: behavioural assertion can make — the closed trigger vocabulary, which is a
#: type-level property. Both files are named because a kill that could have come
#: from either must be attributable to one of them.
PYTEST_TARGETS = [
    "tests/thesis_layer/test_no_trade.py",
    "tests/thesis_layer/test_no_trade_strictness.py",
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
    "no_trade.py": frozenset(
        {
            "no_trade_thesis",
            "render_no_trade_thesis",
            "NoTradeDecision",
            "NoTradeTrigger",
            "_build_no_trade_trade_idea",
            "<module>",
        }
    ),
}

# --- M1: the trigger survives into the published warning ---------------------
_WARNING_LINE = (
    '        return f"No trade [{self.trigger}] '
    '({NO_TRADE_TRIGGER_LABELS[self.trigger]}): {self.reason}"'
)

# --- M2: the vocabulary is closed --------------------------------------------
#: The whole ``Literal[...]`` assignment, so the mutant removes the closed set
#: rather than just one member (D-048: a one-member edit would also be unique,
#: but the point of the mutation is the *type*, so the anchor is the type).
_TRIGGER_TYPE = (
    "NoTradeTrigger = Literal[\n"
    '    "gap_below_dispersion",\n'
    '    "conflicted_signals",\n'
    '    "no_falsifier",\n'
    '    "caller",\n'
    "]"
)

# --- M3: every trigger has a label ------------------------------------------
#: One label line, spanning its key so the anchor cannot match a different
#: member's line. Split across adjacent literals only to satisfy the line limit —
#: the value is a single string.
_LABEL_ENTRY = (
    '    "no_falsifier": "Q8: no evidence-based invalidation condition could be derived",\n'
)

# --- M4: the empty reason is refused -----------------------------------------
_EMPTY_GUARD = "    if not stripped:\n        raise ValueError("

# --- M5: whitespace-only is refused too --------------------------------------
#: The ``stripped`` local is what makes whitespace empty; the mutant tests
#: ``reason`` directly, so ``"   "`` passes the guard.
_STRIP = "    stripped = reason.strip()\n    if not stripped:"

# --- M6: Q6 requires the gap ------------------------------------------------
_MISSING_GAP_GUARD = (
    '    if trigger == "gap_below_dispersion":\n'
    "        if gap is None:\n"
    "            raise ValueError("
)

# --- M7: elapsed is an absolute distance --------------------------------------
_ELAPSED = "        elapsed = gap.dispersion - abs(gap.raw_gap)"

# --- M8: elapsed is not fabricated -------------------------------------------
#: ``elapsed`` starts as ``None`` and is only set inside Q6's branch. The mutant
#: moves the assignment out of the guard by widening the branch condition — it
#: sets ``elapsed`` for every trigger, using the gap when present or 0.0.
_ELAPSED_SCOPE = """    elapsed: float | None = None
    if trigger == "gap_below_dispersion":
        if gap is None:"""

# --- M9: the no-trade idea carries no sentinel --------------------------------
_SENTINEL = '        stop_or_invalidation="",'

# --- M10: the renderer refuses a reserved override ----------------------------
_RESERVED_GUARD = "    clashes = sorted(reserved & thesis_fields.keys())\n    if clashes:"

# --- M11: the trigger line is written first -----------------------------------
#: The renderer puts the trigger line at position 0. Mutation M9's neighbour in
#: the same function, but a different statement — the warning list.
_WARNINGS_LIST = "        warnings=[decision.warning_line()],"

# --- M12: the decision is frozen ----------------------------------------------
_DECISION_CONFIG = """class NoTradeDecision(BaseModel):
    \"\"\"The answer to "should there be a trade?" when the answer is no.

    Section 16.3's outcome, in the form that can be tested without a snapshot:
    **which** gate fired, **why** in one sentence, and **what** the gate was
    looking at. ``render_no_trade_thesis`` turns this into the published
    ``MacroThesis``.

    Frozen, like the other assessment objects (``InvalidationAssessment``), because
    a decision is a record rather than a working buffer.
    \"\"\"

    model_config = ConfigDict(frozen=True, extra="forbid")"""

# --- M13: the status is the spec's WATCH --------------------------------------
_STATUS_DEFAULT = """    status: ThesisStatus = Field(
        default=ThesisStatus.WATCH,"""

# --- M14: the honesty control -------------------------------------------------
#: ``reason=stripped`` is the only place the stripped local is read. The control
#: re-spells it as an equivalent expression on the same value, so the behaviour
#: is identical and the mutant must survive.
_CONTROL_ANCHOR = "        reason=stripped,"


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: the trigger survives into the warning ---------------------------
        Mutation(
            group="M1",
            name="M1.1 the warning line drops the trigger",
            path=NO_TRADE,
            old=_WARNING_LINE,
            new='        return f"No trade: {self.reason}"',
            intent=(
                "Restores defect 2: the published warning is a sentence with no "
                "record of which Q fired, so 'we stood down for Q6' and 'we stood "
                "down for Q8' become the same string again. The kill is "
                "test_the_warning_line_carries_the_trigger."
            ),
        ),
        # -- M2: the vocabulary is closed (STATIC kill) --------------------------
        Mutation(
            group="M2",
            name="M2.1 the trigger vocabulary is widened to str (STATIC)",
            path=NO_TRADE,
            old=_TRIGGER_TYPE,
            new="NoTradeTrigger = str",
            intent=(
                "The O-29 defect: a bare `str` lets a typo'd trigger fall through "
                "and the consumer that counts by trigger silently gets an empty "
                "bucket. Behaviourally this mutant is mostly harmless — a wrong "
                "string still reaches NO_TRADE_TRIGGER_LABELS and KeyErrors — so "
                "the kill is the STATIC assertion "
                "test_the_trigger_vocabulary_is_closed in "
                "test_no_trade_strictness.py, which reads NoTradeTrigger.__args__."
            ),
        ),
        # -- M3: every trigger has a label ---------------------------------------
        Mutation(
            group="M3",
            name="M3.1 a trigger's label is deleted",
            path=NO_TRADE,
            old=_LABEL_ENTRY,
            new="",
            intent=(
                "A trigger added to the vocabulary without a label would KeyError "
                "when a real thesis is rendered. Deleting one proves the census "
                "test (test_every_trigger_has_a_label) is load-bearing."
            ),
        ),
        # -- M4: the empty reason is refused -------------------------------------
        Mutation(
            group="M4",
            name="M4.1 an empty reason is accepted",
            path=NO_TRADE,
            old=_EMPTY_GUARD,
            new="    if False:\n        raise ValueError(",
            intent=(
                "Restores defect 4 exactly: §16.4's warnings=[reason] accepts '', "
                "so 'we stood down' and 'we stood down and cannot say why' are "
                "the same object. The kill is test_an_empty_reason_is_refused."
            ),
        ),
        # -- M5: whitespace-only is refused too ----------------------------------
        Mutation(
            group="M5",
            name="M5.1 the guard tests reason, not the stripped reason",
            path=NO_TRADE,
            old=_STRIP,
            new="    stripped = reason.strip()\n    if not reason:",
            intent=(
                "Whitespace-only slips through: the guard checks the raw string, "
                "so '   ' is accepted and the stored reason is the empty string "
                "after stripping. The kill is test_a_whitespace_reason_is_refused."
            ),
        ),
        # -- M6: Q6 requires the gap --------------------------------------------
        Mutation(
            group="M6",
            name="M6.1 Q6 no longer requires the gap argument",
            path=NO_TRADE,
            old=_MISSING_GAP_GUARD,
            new="    if False:\n        if gap is None:\n            raise ValueError(",
            intent=(
                "The one trigger with a magnitude loses it silently: a caller that "
                "forgot the gap gets a decision whose elapsed is None, and a gap "
                "1bp short of meaningful becomes the same object as one 200bp "
                "short. The kill is "
                "test_gap_below_dispersion_without_a_gap_is_refused."
            ),
        ),
        # -- M7: elapsed is an absolute distance ---------------------------------
        Mutation(
            group="M7",
            name="M7.1 elapsed drops the abs()",
            path=NO_TRADE,
            old=_ELAPSED,
            new="        elapsed = gap.dispersion - gap.raw_gap",
            intent=(
                "A negative raw_gap reports a distance that grows the wrong way: "
                "the field stops meaning 'how far inside the floor'. The kill is "
                "test_elapsed_is_absolute_so_a_negative_gap_reads_the_same."
            ),
        ),
        # -- M8: elapsed is not fabricated ---------------------------------------
        Mutation(
            group="M8",
            name="M8.1 elapsed is set for every trigger",
            path=NO_TRADE,
            old=_ELAPSED_SCOPE,
            new="""    elapsed: float | None = 0.0
    if True:
        if gap is None:""",
            intent=(
                "Every decision now claims a magnitude, so a Q7/Q8 stand-down "
                "reports a 'how close' figure it has no basis for — a fabricated "
                "detail is worse than an absent one. The kill is "
                "test_elapsed_is_none_when_the_trigger_has_no_magnitude."
            ),
        ),
        # -- M9: the no-trade idea carries no sentinel ---------------------------
        Mutation(
            group="M9",
            name="M9.1 the no-trade idea writes the 'n/a' sentinel",
            path=NO_TRADE,
            old=_SENTINEL,
            new='        stop_or_invalidation="n/a",',
            intent=(
                "Restores defect 5 verbatim: §16.4 writes a TRUTHY sentinel into "
                "the field the LTCM gate reads, so the stand-down is one "
                "is_trade flip from asserting a falsifier it does not have. The "
                "kill is test_the_no_trade_idea_carries_no_falsifier_rather_than_a_sentinel."
            ),
        ),
        # -- M10: the renderer refuses a reserved override -----------------------
        Mutation(
            group="M10",
            name="M10.1 the reserved-field guard is removed",
            path=NO_TRADE,
            old=_RESERVED_GUARD,
            new="    clashes = sorted(reserved & thesis_fields.keys())\n    if False:",
            intent=(
                "A caller can silently replace the stand-down shape — pass a live "
                "trade_idea, or overwrite the trigger line in warnings — and the "
                "returned thesis no longer describes the decision it was rendered "
                "from. The kill is test_render_refuses_a_trade_idea_override (and "
                "its three siblings)."
            ),
        ),
        # -- M11: the trigger line is written first ------------------------------
        Mutation(
            group="M11",
            name="M11.1 the trigger line is not what the thesis publishes",
            path=NO_TRADE,
            old=_WARNINGS_LIST,
            new="        warnings=[],",
            intent=(
                "The published thesis loses its record of which gate fired, which "
                "is the whole repair in miniature. The kill is "
                "test_render_puts_the_trigger_line_first."
            ),
        ),
        # -- M12: the decision is frozen -----------------------------------------
        Mutation(
            group="M12",
            name="M12.1 NoTradeDecision is no longer frozen",
            path=NO_TRADE,
            old=_DECISION_CONFIG,
            new=_DECISION_CONFIG.replace(
                'model_config = ConfigDict(frozen=True, extra="forbid")',
                'model_config = ConfigDict(extra="forbid")',
            ),
            intent=(
                "A decision becomes a working buffer, so a caller can rewrite "
                "which gate fired after the fact. The kill is "
                "test_the_decision_is_frozen."
            ),
        ),
        # -- M13: the status is the spec's WATCH ---------------------------------
        Mutation(
            group="M13",
            name="M13.1 the status default is DRAFT, not WATCH",
            path=NO_TRADE,
            old=_STATUS_DEFAULT,
            new="""    status: ThesisStatus = Field(
        default=ThesisStatus.DRAFT,""",
            intent=(
                "Section 16.4 sets WATCH; DRAFT is what a live thesis that has not "
                "been reviewed carries, so a no-trade would claim a promotion path "
                "it must not have. The kill is test_the_status_is_the_specs_watch "
                "and test_the_rendered_thesis_is_watch_not_draft."
            ),
        ),
        # -- M14: the honesty control --------------------------------------------
        Mutation(
            group="M14",
            name="M14.1 reason is re-spelled as a one-element join (CONTROL)",
            path=NO_TRADE,
            old=_CONTROL_ANCHOR,
            new='        reason="".join([stripped]),',
            intent=(
                "CONTROL — `' '.join([x])` on a one-element list is `x` for any "
                "string, so the decision carries the same reason. Semantically "
                "identical; it must survive."
            ),
            expect_killed=False,
            inert_proof=(
                "CONTROL — the reason is rebuilt through a one-element join, which "
                "is the identity on strings. Nothing observable changes, so a kill "
                "would mean the selection is detecting the SHAPE of the code rather "
                "than its behaviour, and no other number here could be trusted."
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
    **right place** (**O-67**). ``no_trade.py`` has several ``if``/``raise``-shaped
    statements a careless anchor could match in a neighbour.
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
            "tests/thesis_layer/test_no_trade.py",
            "tests/thesis_layer/test_no_trade_strictness.py",
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
            "tests/thesis_layer/test_no_trade.py",
            "tests/thesis_layer/test_no_trade_strictness.py",
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
    print("mutation sweep: no_trade_thesis (D-068)")
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

    control_name = "M14.1 reason is re-spelled as a one-element join (CONTROL)"
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
