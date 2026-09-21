"""Mutation sweep for ``derive_invalidation_conditions`` (Module 14, D-063).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/invalidation.py`` and
``src/macro_engine/config.py`` in place, so any concurrent test run, live check
or probe reads a mutated module. The blast radius is the whole repository.

What this increment is really testing
-------------------------------------
Section 20.15's sample has **four** defects, and three of them are of a kind no
value assertion reaches on its own:

1. **It raises `TypeError` on its own sibling's output** — ``inflation.value < 0``
   against a ``dict``. The mutations in ``M1`` all attack the narrowing, because
   the narrowing *is* the repair: a mutant that reads a bool as a score, or
   accepts any dict as a verdict, is the sample's defect wearing a different hat.
2. **``growth`` was never read.** ``M5`` deletes it from the loop.
3. **The fallback sentence satisfied the gate it says is unmet.** ``M4`` restores
   it, and the kill is an assertion about the SCHEMA refusing the result — the
   gate is the test, not the string.
4. **The model the sample names is direction-blind.** ``M3`` makes the agreement
   branch emit a reversal, and the kill asserts the word "reacceleration" never
   appears.

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether a condition is the RIGHT one.** The function states the falsifier
   implied by each signal's own sign. Whether that signal is the one the thesis
   leans on is a judgement the caller makes; no mutation makes the function
   *decide* it.

2. **That the direction-blindness is real.** ``M3.3`` can only show the branch
   emits the right *word*; that
   ``InflationConvergenceVerdict`` genuinely cannot express a direction is a fact
   about that model's field set, pinned by a test that reads it, not by a mutant.

3. **The builder's wiring.** ``build_us_macro_thesis`` does not exist yet, so the
   round-trip (assessment → ``TradeIdea.stop_or_invalidation`` → the schema gate)
   is asserted in the tests against a hand-built ``TradeIdea``. When the builder
   ships, its own seam needs its own test — **a unit test of a callee cannot see
   its caller's mistake.**

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
``_signed_scalar`` and ``_agreement_class`` both contain several bare
``return None`` lines, so every anchor here is extended past its own guard; a
fragment that is merely *unique* can still be in the wrong function (**O-67**).
"""

from __future__ import annotations

import argparse
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from _sweep_gate import sweep_lifecycle

REPO = Path(__file__).resolve().parent.parent
INVALIDATION = REPO / "src/macro_engine/thesis_layer/invalidation.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/thesis_layer/test_invalidation.py`` carries the behavioural
#: assertions. ``tests/thesis_layer/test_production_universe.py`` is included
#: because the new module imports the thesis layer's schemas, so a mutation that
#: breaks the schema contract must not be attributed to a gap in the new file.
#: ``tests/test_infrastructure.py`` covers the ``config.py`` mutants.
PYTEST_TARGETS = [
    "tests/thesis_layer/test_invalidation.py",
    "tests/thesis_layer/test_production_universe.py",
    "tests/test_infrastructure.py",
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


def _slice_source(path: Path, first: str, last: str, *, after: str | None = None) -> str:
    """Return the source text from the line containing ``first`` to ``last``.

    ``after`` scopes the search to a symbol, because ``check_targets`` proves an
    anchor is *unique* and not that it is in the *right function* (**O-67**).
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    base = 0
    if after is not None:
        anchor = next((i for i, ln in enumerate(lines) if after in ln), None)
        if anchor is None:
            raise RuntimeError(f"anchor scope not found in {path.name}: {after!r}")
        base = anchor + 1
    start = next((i for i in range(base, len(lines)) if first in lines[i]), None)
    if start is None:
        raise RuntimeError(f"anchor start not found in {path.name}: {first!r}")
    end = next((i for i in range(start, len(lines)) if last in lines[i]), None)
    if end is None:
        raise RuntimeError(f"anchor end not found in {path.name}: {last!r}")
    return "".join(lines[start : end + 1])


#: The top-level symbols this increment owns in each file.
_ALLOWED_ANCHOR_OWNERS: dict[str, frozenset[str]] = {
    "invalidation.py": frozenset(
        {
            "derive_invalidation_conditions",
            "_signed_scalar",
            "_agreement_class",
            "_condition_for_scalar",
            "InvalidationAssessment",
        }
    ),
    "config.py": frozenset({"InvalidationSettings", "Settings"}),
}

# --- M1: the narrowing (the crash class) ------------------------------------
_SIGNED_BOOL_GUARD = "    if isinstance(value, bool):\n        return None"
#: The guarded numeric narrowing, post-D-078. The anchor carries BOTH guards —
#: the ``bool`` exclusion and the ``isfinite`` bound — because the mutant's job
#: is to remove the narrowing, and the narrowing is now the pair. Before the
#: D-078 fix this constant named the unguarded ``isinstance(value, (int, float))``
#: form, which the fix replaced; the anchor moved with the code rather than the
#: mutant being retired, because "anything floatable is a score" is still the
#: defect the test must keep catching.
_SIGNED_NUMERIC = (
    "    if isinstance(value, (int, float)) and isfinite(value):\n"
    "        return float(value)\n"
    "    return None"
)
_AGREEMENT_DICT_GUARD = "    if not isinstance(value, dict):\n        return None"
_AGREEMENT_MEMBERSHIP = (
    "    if isinstance(classification, str) and classification in CONVERGENCE_CLASSES:"
)
_UNREADABLE_APPEND = "        unreadable.append(\n            UnreadableInput("

# --- M2: the sign partition -------------------------------------------------
_ABOVE = "    if value > crossing:"
_BELOW = "    elif value < crossing:"
_ELSE_NONE = "    else:\n        return None"
_TRIGGER_NEGATIVE = '        trigger: InvalidationTrigger = "crosses_back_negative"'
_TRIGGER_POSITIVE = '        trigger = "crosses_back_positive"'

# --- M3: the agreement branch -----------------------------------------------
_AGREEMENT_EQ = "            if agreement == supporting:"
_AGREEMENT_TRIGGER = '                        trigger="agreement_collapses",'
_AGREEMENT_THRESHOLD = "                        threshold=None,"

# --- M4: the identified/text partition --------------------------------------
_TEXT_JOIN = '    text = " OR ".join(c.statement for c in conditions)'
_IDENTIFIED = "    identified = bool(conditions)"
_REASON_UNREADABLE = '        names = ", ".join(u.model_name for u in unreadable)'

# --- M5: the never-read parameter -------------------------------------------
_LOOP = '    for role, result in (("growth", growth), ("inflation", inflation), ("labor", labor)):'
_LABEL = "        label = result.model_name or role"

# --- M6: the published fields -----------------------------------------------
_OBSERVED = '        observed_value=f"{value:+g}",'

# --- M7: the contract -------------------------------------------------------
_ASSESSMENT_CONFIG = _slice_source(
    INVALIDATION,
    '    model_config = ConfigDict(frozen=True, extra="forbid")',
    "    conditions: tuple[InvalidationCondition, ...]",
    after="class InvalidationAssessment(BaseModel):",
)

# --- M8: the config accessors -----------------------------------------------
_CROSSING = "        return float(self.zero_crossing_threshold.value)"
_SUPPORTING = "        return str(self.supporting_agreement_class.value)"

# --- M9: the honesty control -------------------------------------------------
_M9_CONTROL_OLD = '    text = " OR ".join(c.statement for c in conditions)'
_M9_CONTROL_NEW = '    text = " OR ".join([c.statement for c in conditions])'


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: the narrowing ---------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 the bool exclusion is removed (True reads as a score of 1.0)",
            path=INVALIDATION,
            old=_SIGNED_BOOL_GUARD,
            new="    if False:\n        return None",
            intent=(
                "`isinstance(True, int)` is True, so a flag would produce a "
                "confident falsifier. Only a bool-valued fixture sees this."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 the numeric narrowing is removed (anything floatable is a score)",
            path=INVALIDATION,
            old=_SIGNED_NUMERIC,
            new=(
                "    try:\n"
                "        return float(value)  # type: ignore[arg-type]\n"
                "    except (TypeError, ValueError):\n"
                "        return None"
            ),
            intent=(
                "A string that looks numeric becomes a score. Section 20.15's "
                "crash was the OTHER direction; this is the same missing "
                "narrowing reached from the permissive side."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.3 the agreement dict guard is removed",
            path=INVALIDATION,
            old=_AGREEMENT_DICT_GUARD,
            new="    if False:\n        return None",
            intent="A non-dict reaches `.get` and raises AttributeError instead of being reported.",
        ),
        Mutation(
            group="M1",
            name="M1.4 the agreement vocabulary membership test is removed",
            path=INVALIDATION,
            old=_AGREEMENT_MEMBERSHIP,
            new="    if isinstance(classification, str):",
            intent=(
                "Any dict carrying a string under `classification` reads as a "
                "verdict, so a typo becomes a supported thesis."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.5 the unreadable branch is removed (the shape is skipped silently)",
            path=INVALIDATION,
            old=_UNREADABLE_APPEND,
            new=("        neutral.append(\n            UnreadableInput("),
            intent=(
                "The unreadable shape is filed under `neutral` instead of being "
                "reported, so it reads as 'no falsifier from this leg' rather than "
                "'this leg was not read'. NOTE: the first draft of this mutation "
                "wrote `neutral.append(...) or unreadable.append(...)`, which "
                "STILL appended to `unreadable` (list.append returns None, so "
                "`None or X` evaluates X) and survived for that reason alone — a "
                "mutant that does not change the program is not a test gap."
            ),
        ),
        # -- M2: the sign partition ----------------------------------------
        Mutation(
            group="M2",
            name="M2.1 the above-crossing comparison becomes inclusive",
            path=INVALIDATION,
            old=_ABOVE,
            new="    if value >= crossing:",
            intent="Differs only ON the crossing, so the fixture must sit exactly there.",
        ),
        Mutation(
            group="M2",
            name="M2.2 the below-crossing comparison becomes inclusive",
            path=INVALIDATION,
            old=_BELOW,
            new="    elif value <= crossing:",
            intent="Mirror of M2.1: the neutral state stops being reachable.",
        ),
        Mutation(
            group="M2",
            name="M2.3 the neutral branch is removed (zero gets a direction)",
            path=INVALIDATION,
            old=_ELSE_NONE,
            new=(
                "    else:\n"
                '        trigger = "crosses_back_positive"\n'
                '        statement = f"{model_name} reverses"'
            ),
            intent=(
                "A signal at the balance point is given a direction, which is "
                "absence of evidence reported as evidence."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.4 the two reversal triggers swap",
            path=INVALIDATION,
            old=_TRIGGER_NEGATIVE,
            new='        trigger: InvalidationTrigger = "crosses_back_positive"',
            intent=(
                "A signal above the crossing now reports an upward reversal. The "
                "common-case branch is wrong, so a one-sided fixture cannot see it."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.5 the comparators invert (both directions reversed)",
            path=INVALIDATION,
            old=_ABOVE,
            new="    if value < crossing:",
            intent="The whole sign convention of the falsifier.",
        ),
        # -- M3: the agreement branch --------------------------------------
        Mutation(
            group="M3",
            name="M3.1 the agreement equality inverts",
            path=INVALIDATION,
            old=_AGREEMENT_EQ,
            new="            if agreement != supporting:",
            intent=(
                "The four-member verdict vocabulary is partitioned the wrong "
                "way: only NON-HIGH verdicts produce a falsifier."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2 the agreement falsifier becomes a reversal",
            path=INVALIDATION,
            old=_AGREEMENT_TRIGGER,
            new='                        trigger="crosses_back_positive",',
            intent=(
                "The sample's defect: a direction-blind classifier asked for a "
                "direction. The kill asserts 'reacceleration' never appears."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the agreement trigger gains a numeric threshold",
            path=INVALIDATION,
            old=_AGREEMENT_THRESHOLD,
            new="                        threshold=crossing,",
            intent="An agreement band is published as if it were a crossing level.",
        ),
        # -- M4: the identified/text partition ------------------------------
        Mutation(
            group="M4",
            name="M4.1 the text is never empty (the sample's fallback returns)",
            path=INVALIDATION,
            old=_TEXT_JOIN,
            new=(
                '    text = " OR ".join(c.statement for c in conditions) or (\n'
                '        "No clear evidence-based invalidation condition identified — "\n'
                '        "DO NOT promote this thesis past DRAFT (Module 14 Q8 requirement)"\n'
                "    )"
            ),
            intent=(
                "THE DEFECT. The fallback is non-empty, so it satisfies the LTCM "
                "gate it says is unmet. The kill is the SCHEMA refusing the result."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 identified is hardcoded True",
            path=INVALIDATION,
            old=_IDENTIFIED,
            new="    identified = True",
            intent="The typed field the prose string cannot carry stops tracking the conditions.",
        ),
        Mutation(
            group="M4",
            name="M4.3 the reason stops naming the unreadable inputs",
            path=INVALIDATION,
            old=_REASON_UNREADABLE,
            new='        names = "some inputs"',
            intent="A no-trade reason that does not say WHICH input failed is not actionable.",
        ),
        # -- M5: the never-read parameter ------------------------------------
        Mutation(
            group="M5",
            name="M5.1 growth is dropped from the loop (the sample's defect)",
            path=INVALIDATION,
            old=_LOOP,
            new='    for role, result in (("inflation", inflation), ("labor", labor)):',
            intent=(
                "Section 20.15 declares three parameters and reads two. The kill "
                "must be an assertion that ALL THREE contribute."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.2 the label falls back to the role instead of the model name",
            path=INVALIDATION,
            old=_LABEL,
            new="        label = role",
            intent=(
                "The condition stops naming the model that produced it, which is "
                "the whole point of publishing `model_name`."
            ),
        ),
        # -- M6: the published fields ----------------------------------------
        Mutation(
            group="M6",
            name="M6.1 the observed value is published as a constant",
            path=INVALIDATION,
            old=_OBSERVED,
            new='        observed_value="n/a",',
            intent="A reader can no longer check the condition against the model's own output.",
        ),
        # -- M7: the contract -------------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 the assessment stops forbidding extra fields",
            path=INVALIDATION,
            old=_ASSESSMENT_CONFIG,
            new=_ASSESSMENT_CONFIG.replace('extra="forbid"', 'extra="allow"'),
            intent="A typo'd field is silently accepted.",
        ),
        Mutation(
            group="M7",
            name="M7.2 the assessment stops being frozen",
            path=INVALIDATION,
            old=_ASSESSMENT_CONFIG,
            new=_ASSESSMENT_CONFIG.replace("frozen=True, ", ""),
            intent=(
                "The assessment is the record of what would falsify a position; "
                "mutating it after the fact is how a falsifier gets softened."
            ),
        ),
        # -- M8: the config accessors ----------------------------------------
        Mutation(
            group="M8",
            name="M8.1 the crossing accessor returns a literal",
            path=CONFIG,
            old=_CROSSING,
            new="        return 0.0",
            intent="A literal equal to the shipped leaf: invisible unless a test MOVES the leaf.",
        ),
        Mutation(
            group="M8",
            name="M8.2 the supporting-agreement accessor returns a literal",
            path=CONFIG,
            old=_SUPPORTING,
            new='        return "HIGH"',
            intent="Mirror of M8.1 for the string leaf.",
        ),
        # -- M9: the honesty control -----------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the text is joined through a list comprehension (CONTROL)",
            path=INVALIDATION,
            old=_M9_CONTROL_OLD,
            new=_M9_CONTROL_NEW,
            intent=(
                "Semantically IDENTICAL to the shipped code. SURVIVAL IS REQUIRED: "
                "if the sweep reports this killed it cannot justify its own kills."
            ),
            expect_killed=False,
            inert_proof=(
                'HONESTY CONTROL. `" OR ".join(gen)` and `" OR ".join([gen])` '
                "are the same string for every input, so this mutation cannot "
                "change any observable. Its survival is a requirement, not a "
                "finding — D-051's first draft lacked one and reported a false "
                "56/56, and D-059's control is what exposed a DEAD TEST inflating "
                "its first run to a false 31/31."
            ),
        ),
    ]


#: Mutations expected to survive, each of which MUST have an entry in
#: ``_INERT_PROOFS``. A name here without a proof makes the sweep exit 2.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M9.1 the text is joined through a list comprehension (CONTROL)",
    }
)

#: The argument for each exception above. The harness refuses to certify a
#: survivor whose excuse is a label rather than a reason (O-42, built by D-056).
_INERT_PROOFS: dict[str, str] = {
    mt.name: mt.inert_proof for mt in build_mutations() if mt.inert_proof
}


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test — a conclusion about code nobody mutated.

    **This module is unusually exposed to that.** ``_signed_scalar`` and
    ``_agreement_class`` each contain several bare ``return None`` lines, so
    every anchor in ``M1`` is extended past its own guard rather than anchored on
    the statement alone.

    It doubles as the clean-tree precondition: a sweep started against an
    already-mutated tree finds its own anchor ABSENT and **refuses**.
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
    **right place** (**O-67**). A unique fragment belonging to a neighbouring
    function passes silently, the mutant rewrites that function instead, and the
    tests that would catch it are not in this selection — so the sweep reports a
    **survivor** and the reader concludes the suite is weak. That happened twice
    in the D-061/D-062 session.
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
        owner = "<module>"
        for line in reversed(text[:index].splitlines()):
            if line.startswith(("def ", "class ")) and not line.startswith(
                ("    def", "    class")
            ):
                owner = line.split("(")[0].replace("def ", "").replace("class ", "")
                break
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
        path = REPO / target
        if not path.exists():
            problems.append(f"test target ABSENT: {target}")
            continue
        # Inlined as literals rather than passed as `target` because ruff's S603
        # rule treats a variable argument as untrusted input; the loop verifies
        # existence above so the two stay in step.
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/thesis_layer/test_invalidation.py",
                "tests/thesis_layer/test_production_universe.py",
                "tests/test_infrastructure.py",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            problems.append(
                f"test target does not collect (pytest exit {proc.returncode}): {target}"
            )
            continue
        match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
        if not match or int(match.group(1)) == 0:
            problems.append(f"test target collects ZERO tests: {target}")
    return problems


def run_pytest() -> tuple[int, str]:
    """Run the targeted tests. Non-zero means the mutation was killed.

    Exit code **4** is pytest's "usage error / no tests collected", which is not
    a kill. ``-x`` is passed and is not optional (lesson 61): the kill signal
    must be cheap, because the cheap path is the one that gets used.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/thesis_layer/test_invalidation.py",
            "tests/thesis_layer/test_production_universe.py",
            "tests/test_infrastructure.py",
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
    parser.add_argument("--group", help="run only this mutation group, e.g. M2")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: derive_invalidation_conditions (Module 14, D-063)")
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

    defects: list[str] = []
    if survived:
        print("\nsurvivors, classified:")
        for r in survived:
            name = r.mutation.name
            proof = _INERT_PROOFS.get(name, "")
            if not proof:
                defects.append(name)
                print(f"  [NO PROOF] {name}")
                continue
            if "CONTROL" in name:
                tag = "control"
            elif "INERT BY CONSTRUCTION" in proof:
                tag = "inert (construction)"
            elif "INERT BY UNREACHABILITY" in proof:
                tag = "inert (unreachability)"
            else:
                tag = "inert"
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

    control_name = "M9.1 the text is joined through a list comprehension (CONTROL)"
    control = next((r for r in results if r.mutation.name == control_name), None)
    if control is not None and control.killed:
        print(
            "REFUSING TO CERTIFY: the honesty control was killed. The sweep is "
            "reporting kills it cannot justify, so no other number means anything."
        )
        return 2

    if any(r.mutation.name in _EXPECTED_INERT for r in results if r.applied and r.killed):
        print("NOTE: an expected-inert mutation was killed — the exemption is stale.")

    print("RESULT: every survivor is either expected or proven inert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
