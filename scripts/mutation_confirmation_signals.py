"""Mutation sweep for ``build_confirmation_signals`` (D-066).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/signals.py``
in place, so any concurrent test run, live check or probe reads a mutated
module. The blast radius is the repository.

What this increment is really testing
-------------------------------------
Section 16.4's sample is a single ``if``/``else`` over three inputs, so almost
every defect here is about **which of the three outcomes a value is assigned to**
rather than about arithmetic — the same shape as D-065, one layer up:

1. **An unreadable value falls to ``contradicts``.** ``M1`` restores the
   else-branch behaviour for a non-numeric value (a ``dict``), publishing a
   directional claim from data carrying none (D-056, false confidence).
2. **A zero value falls to ``contradicts``.** ``M2`` restores it for ``v == 0``
   — a balance point read as an opposing view.
3. **The label is not the result's own name.** ``M3`` restores §16.4's
   hardcoded slot vocabulary, whose middle entry names a model Q1 never passes
   (**O-69**).
4. **``source_family`` is dropped.** ``M4`` restores the sample's ``None``
   default, which makes ``count_independent_families`` unreachable at this layer.
5. **A zero gap still produces ``confirms``.** ``M5`` removes the no-direction
   guard, inventing the reference the comparison was against.
6. **``bool`` reads as a number.** ``M6`` removes the bool exclusion, so
   ``isinstance(True, int)`` publishes a direction from a flag.
7. **The warning marker is dropped from a corroborating signal.** ``M7``.

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether "direction agreement with the gap" is the right Q7 question.**
   Section 6.6b says Q7 is *"evidence strength and independence"*, and the real
   answer to that is the convergence verdict ``classify_convergence`` computes
   one line later in §16.2. That function is **not an argument here**, so no
   mutation can make this list answer the strength question — the limitation is
   a specification judgement, recorded in the module docstring.
2. **Whether labelling a dict-valued input ``neutral`` is better than
   ``unreadable`` as a fourth vocabulary member.** The schema's own
   ``_validate_direction`` permits only three (Section 22.10 / Finding #10), so
   a fourth member is a schema change (§22.13), not a sweep target.
3. **Whether a real model's sign agrees with the real gap.** The live check
   pulls FRED; the sweep cannot pin a direction that moves with the data.

The honesty control
-------------------
``M8.1`` is semantically identical to the shipped code and **must survive**. If
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
SIGNALS = REPO / "src/macro_engine/thesis_layer/signals.py"

#: The test selection a surviving mutation must be *capable* of killing.
#: ``test_signals.py`` carries the behavioural assertions for every mutant.
#: One file suffices, and a second, unused target would make a kill
#: unattributable.
PYTEST_TARGETS = ["tests/thesis_layer/test_signals.py"]


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
    "signals.py": frozenset(
        {
            "build_confirmation_signals",
            "_direction_for",
            "_signed_scalar",
            "_gap_sign",
            "_family_of",
            "_detail_for",
            "<module>",
        }
    ),
}

# --- M1: an unreadable value is neutral, not a contradiction ----------------
_UNREADABLE_GUARD = "        if scalar is None:"

# --- M2: a zero value is neutral, not a contradiction -----------------------
_ZERO_VALUE = "    if value == 0.0:"

# --- M3: the label is the result's own model_name ---------------------------
_LABEL = "        label = result.model_name or fallback"

# --- M4: source_family is carried through -----------------------------------
#: The two call sites differ only in indentation, so each anchor spans its own
#: ``direction=`` line to stay unique (D-048: an anchor present twice is a
#: refusal, and ``check_targets`` caught exactly that on the first draft).
_FAMILY_FIRST = (
    '                    direction="neutral",\n'
    "                    detail=detail,\n"
    "                    source_family=_family_of(result),"
)
_FAMILY_READABLE = (
    "                direction=direction,\n"
    "                detail=detail,\n"
    "                source_family=_family_of(result),"
)

# --- M5: a zero gap makes every signal neutral ------------------------------
_GAP_SIGN_FIELD = "    sign = _gap_sign(gap)"
_ZERO_GAP_GUARD = "    if gap_sign == 0:"

# --- M6: bool is not a number -----------------------------------------------
_BOOL_EXCLUSION_LINE = "    if isinstance(value, bool):"

# --- M7: the warning marker on a corroborating signal -----------------------
_WARNING_MARKER = '    if direction != "neutral" and result.warnings:'

# --- M8: the honesty control -------------------------------------------------
_SLOT_FALLBACK = "        scalar = _signed_scalar(result.value)"


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: the unreadable branch ------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 an unreadable value falls through to 'contradicts'",
            path=SIGNALS,
            old=_UNREADABLE_GUARD,
            new="        if False:",
            intent=(
                "Restores Section 16.4's else-branch: a dict-valued result is "
                "reported as an active contradiction. The kill is "
                "test_an_unreadable_value_is_neutral_not_a_contradiction."
            ),
        ),
        # -- M2: the zero-value case --------------------------------------------
        Mutation(
            group="M2",
            name="M2.1 a value of exactly zero falls through to 'contradicts'",
            path=SIGNALS,
            old=_ZERO_VALUE,
            new="    if False:",
            intent=(
                "Zero satisfies neither conjunction in the sample, so it lands in "
                "the else and reads as an opposing view. The kill is "
                "test_a_zero_value_is_neutral_not_a_contradiction."
            ),
        ),
        # -- M3: the label ------------------------------------------------------
        Mutation(
            group="M3",
            name="M3.1 the label is Section 16.4's hardcoded slot vocabulary",
            path=SIGNALS,
            old=_LABEL,
            new="        label = _SLOT_FALLBACK_NAMES[slots.index((result, fallback))]",
            intent=(
                "Restores the sample's labels, whose middle entry "
                "('inflation_convergence') names a model Q1 never passes (O-69). "
                "The kill is test_the_label_is_the_result_own_model_name."
            ),
        ),
        # -- M4: source_family ---------------------------------------------------
        Mutation(
            group="M4",
            name="M4.1 source_family is dropped on the unreadable path",
            path=SIGNALS,
            old=_FAMILY_FIRST,
            new=_FAMILY_FIRST.replace("source_family=_family_of(result),", "source_family=None,"),
            intent=(
                "The sample leaves source_family at None on every entry. This "
                "restores it for the unreadable path. The kill is "
                "test_families_survive_every_direction."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 source_family is dropped on the readable path",
            path=SIGNALS,
            old=_FAMILY_READABLE,
            new=_FAMILY_READABLE.replace(
                "source_family=_family_of(result),", "source_family=None,"
            ),
            intent=(
                "The same defect on the main path, so the two cannot both be "
                "repaired by one assertion. The kill is "
                "test_the_family_is_carried_through."
            ),
        ),
        # -- M5: the zero-gap case ----------------------------------------------
        Mutation(
            group="M5",
            name="M5.1 a zero gap still yields 'confirms' (sign defaults to +1)",
            path=SIGNALS,
            old=_GAP_SIGN_FIELD,
            new="    sign = _gap_sign(gap) or 1",
            intent=(
                "A zero gap now compares as if the model sat above the market, "
                "so a positive signal reads 'confirms' against a gap with no "
                "direction. The kill is test_a_zero_gap_makes_every_signal_neutral."
            ),
        ),
        # -- M6: bool exclusion -------------------------------------------------
        Mutation(
            group="M6",
            name="M6.1 bool reads as a signed number",
            path=SIGNALS,
            old=_BOOL_EXCLUSION_LINE,
            new="    if False:",
            intent=(
                "isinstance(True, int) is True, so a flag-valued result publishes "
                "a direction. The kill is test_a_boolean_value_is_not_a_signed_number."
            ),
        ),
        # -- M7: the warning marker ---------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 the warning marker is dropped from a corroborating signal",
            path=SIGNALS,
            old=_WARNING_MARKER,
            new="    if False:",
            intent=(
                "A model that warned no longer says so, so a 'confirms' can carry "
                "a caveat unflagged. The kill is "
                "test_a_corroborating_signal_reports_its_models_warning_count."
            ),
        ),
        # -- M8: the honesty control --------------------------------------------
        Mutation(
            group="M8",
            name="M8.1 the scalar read is re-wrapped with the same call (CONTROL)",
            path=SIGNALS,
            old=_SLOT_FALLBACK,
            new="        scalar = _signed_scalar(\n            result.value\n        )",
            intent=(
                "CONTROL — the call is re-wrapped across lines but invokes the "
                "identical function with the identical argument."
            ),
            expect_killed=False,
            inert_proof="CONTROL — semantically identical by construction.",
        ),
    ]


_INERT_PROOFS: dict[str, str] = {
    "M8.1 the scalar read is re-wrapped with the same call (CONTROL)": (
        "CONTROL — semantically identical by construction."
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
    **right place** (**O-67**). ``signals.py`` has several ``if False:``-shaped
    guards that a careless anchor could match in a neighbour.
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
            "tests/thesis_layer/test_signals.py",
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
            "tests/thesis_layer/test_signals.py",
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
    print("mutation sweep: build_confirmation_signals (D-066)")
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

    control_name = "M8.1 the scalar read is re-wrapped with the same call (CONTROL)"
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
