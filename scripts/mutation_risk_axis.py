"""Mutation sweep for Section 17.4's risk axis (D-073).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/builder.py`` in place, so any concurrent test run,
live check or probe reads a mutated module. D-047's Postscript 2 records a
contaminated reading produced exactly that way, and D-049 left the source mutated
when its sweep was killed mid-run -- the full suite then passed *with the mutation
in place*. The blast radius is the whole repository.

Why the mutations are named after defects
-----------------------------------------
Every predecessor named its mutations after the defect each one repairs, and this
sweep follows. D-073's defects are unusual in one specific way: **the axis writes
no number and computes no arithmetic**. It reads one, compares it to a bound, and
chooses a status plus a sentence. So the mutation surface is almost entirely
*control flow and published text*, and three of the five groups are about which
of several adjacent findings a result is allowed to be.

The three defect classes this sweep is built around
---------------------------------------------------
1. **A threshold that cannot fire.** ``M1.*``. The first draft set the near-zero
   bound to ``0.02``, which is strictly positive and strictly below the position
   cap — and *below the smallest size the sizing path can produce*. A bound that
   no input can reach makes Section 17.4 a declaration with no consumer, which is
   the declared-consumed-unreachable class this project has found nine times now.
   The mutation points the bound *at* the shipped leaf, so a test that only
   checked "positive and below the cap" would survive it.

2. **Two findings collapsed into one.** ``M2.*``. A *refusal* (the translation
   declined, for its own stated reason) and a *demotion* (the size is too small)
   are different facts calling for different actions. Assigning the demotion's
   status on the refusal path is the failure: the reason stops travelling, and
   ``WATCH`` then cannot distinguish "the book says no" from "too small to hold".

3. **A disclosed absence turned into a silent pass.** ``M3.*``. ``target is
   None`` must publish that the check *did not run*. Returning the thesis
   unchanged makes an unsized thesis indistinguishable from a sized-and-cleared
   one — the "unchecked read as checked" direction, which is the one failure a
   reader cannot detect from any number in the output.

What this sweep structurally CANNOT find
----------------------------------------
**The demotion is unreachable through the shipped builder, and no mutation can
change that.** Every live family stands down at Q6/Q7/Q8 before the axis runs, and
every live-shaped thesis refuses at gate 2 because the scenario probabilities are
``uncalibrated_illustrative``. So the demotion fires only on a *constructed*
input, and a mutation that breaks it is killed by the constructed fixture — which
is what ``M2.*`` and ``M4.*`` are for. This is stated rather than hidden because a
reader who assumed these mutations exercise "the real path" would credit the suite
with a reach it does not have.

**"The default does not change behaviour" is a NEGATIVE.** ``M3.1`` reintroduces
the silent return and must be killed; beyond that the assertion is that the *only*
difference is one appended warning, which lives in
``test_the_axis_leaves_the_thesis_untouched_when_no_budget_is_supplied``.

The honesty control
-------------------
``M5.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and no
other number it prints means anything. This control is what D-051's first draft
lacked when it reported a false 56/56.
"""

from __future__ import annotations

import argparse
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/macro_engine/thesis_layer/builder.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/thesis_layer/test_risk_axis.py`` is the increment's own file and the
#: primary kill surface.
#:
#: ``tests/thesis_layer/test_builder_live.py`` is included because the axis runs
#: at the end of ``build_us_macro_thesis`` on the LIVE path, and a mutation that
#: changed a live thesis's status or warnings must die there too — the axis is
#: inside the builder, so the builder's own file is a legitimate kill site.
#:
#: ``tests/thesis_layer/test_integrity_gates.py`` is included because the §25
#: Kelly gate is re-checked on this new path by a behavioural receipt in that
#: file, and because its import guard pins the permitted surface. A mutation that
#: widened the axis's imports must be caught by the guard rather than by review.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
    "tests/thesis_layer/test_risk_axis.py",
    "tests/thesis_layer/test_builder_live.py",
    "tests/thesis_layer/test_integrity_gates.py",
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
    #: ``None`` means "expect the tests to fail", which is the normal case.
    #: ``True`` means the mutation is provably inert (see ``_EXPECTED_INERT``).
    #: ``False`` means it is expected to *pass* but for a documented reason.
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
# The catalogue
# ---------------------------------------------------------------------------
#
# Anchors are transcribed from the SHIPPED source and are re-verified against it
# by ``check_targets`` before a single mutation is applied. Formatting drift is a
# known trap (lesson 50): ``ruff format`` reflows these lines when the
# surrounding code changes, and a drifted anchor reads as a test defect rather
# than a harness defect. The sweep is re-run at close for exactly this reason.
#
# **The ambiguity hazard here is LOW, and that is worth stating because the
# predecessor's was severe.** All five mutations target ``_apply_risk_axis``,
# which is the only function in ``builder.py`` that emits a ``[Q12 risk]`` line,
# and each anchor is a distinctive multi-line statement. ``check_targets`` is
# still the gate that proves it rather than assuming it.

# --- M1: the bound (defect 1 -- a threshold that cannot fire) ----------------

_M1_BOUND_SHIPPED = "    demotion = get_settings().risk.thesis_demotion_fraction"
_M1_BOUND_NEVER_FIRES = "    demotion = 0.0"

_M1_BOUND_DEMOTES_EVERYTHING = "    demotion = 1.0"


def build_mutations() -> list[Mutation]:
    """The catalogue, grouped by the defect each mutation reintroduces."""
    return [
        # --- M1: the near-zero bound ---------------------------------------
        Mutation(
            group="M1",
            name="M1.1_bound_at_zero_never_fires",
            path=SRC,
            old=_M1_BOUND_SHIPPED,
            new=_M1_BOUND_NEVER_FIRES,
            intent=(
                "The first draft's failure mode in its purest form: a threshold of "
                "zero can never be reached by a POSITIVE size, so Section 17.4 "
                "demotes nothing. Killed by the bound-vs-reachable-range test and "
                "by the demotion test, which needs the real bound to fire."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2_bound_above_the_cap_demotes_everything",
            path=SRC,
            old=_M1_BOUND_SHIPPED,
            new=_M1_BOUND_DEMOTES_EVERYTHING,
            intent=(
                "The opposite failure: a bound at 1.0 is above the position cap, so "
                "EVERY sized thesis demotes and the rule stops discriminating. "
                "Killed by the bound-below-the-cap assertion."
            ),
        ),
        # --- M2: refusal collapsed into demotion ---------------------------
        Mutation(
            group="M2",
            name="M2.1_refusal_keeps_draft_not_watch",
            path=SRC,
            old=(
                '    if proposal.outcome.startswith("refused_"):\n'
                "        return thesis.model_copy(\n"
                "            update={\n"
                '                "warnings": ['
            ),
            new=(
                '    if proposal.outcome.startswith("refused_"):\n'
                "        return thesis.model_copy(\n"
                "            update={\n"
                '                "status": ThesisStatus.WATCH,\n'
                '                "warnings": ['
            ),
            intent=(
                "A refusal demoted to WATCH. The §25 probability-prohibition "
                "finding would then be reported as a risk-budget finding, and a "
                "reader could not tell 'the book says no' from 'too small to "
                "hold'. Killed by the refusal-keeps-DRAFT assertion."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2_refusal_reason_relabelled_as_demotion",
            path=SRC,
            old=(
                '                    f"This is a REFUSAL, not a demotion: Section 17.4 demotes a "'
            ),
            new=('                    f"This thesis has been DEMOTED under Section 17.4."'),
            intent=(
                "The right status with the WRONG sentence: D-072's defect class, "
                "where no numeric assertion can catch a wrong reason. Killed by "
                "the assertion on the published wording."
            ),
        ),
        # --- M3: the disclosed absence -------------------------------------
        Mutation(
            group="M3",
            name="M3.1_no_budget_returns_silently",
            path=SRC,
            old=(
                "    if target is None:\n"
                "        return thesis.model_copy(\n"
                "            update={\n"
                '                "warnings": ['
            ),
            new=("    if target is None:\n        return thesis"),
            intent=(
                "An unsized thesis becomes indistinguishable from a sized-and-"
                "cleared one -- the 'unchecked read as checked' direction, and the "
                "one failure no number in the output can reveal. Killed by the "
                "DID-NOT-RUN disclosure test."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2_disclosure_drops_the_parameter_name",
            path=SRC,
            old=(
                '                    "so a caller holding a book must pass `risk_budget_target`.",'
            ),
            new=('                    "so no sizing was performed against a book.",'),
            intent=(
                "A disclosure that no longer names the parameter a caller must "
                "pass is a disclosure a caller cannot act on. Killed by the "
                "assertion that the line names `risk_budget_target`."
            ),
        ),
        # --- M4: the demotion's own contract -------------------------------
        Mutation(
            group="M4",
            name="M4.1_demotion_uses_strict_inequality",
            path=SRC,
            old="    if proposal.fraction_of_capital <= demotion:",
            new="    if proposal.fraction_of_capital < demotion:",
            intent=(
                "Section 17.4 says 'at or below' the bound. A strict inequality "
                "leaves the boundary size undemoted, so the one measured size that "
                "sits exactly on the bound flips outcome -- the arithmetic is "
                "identical and only the boundary moves."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2_demotion_drops_the_binding_constraint",
            path=SRC,
            old=(
                '                    f"at or below the {demotion:.4f} near-zero bound (binding "\n'
                '                    f"constraint: {proposal.binding_constraint!r}). A thesis "'
            ),
            new=(
                '                    f"at or below the {demotion:.4f} near-zero bound. A thesis "'
            ),
            intent=(
                "A demotion that does not name what produced the size leaves the "
                "reader unable to tell a liquidity clip from a tiny Kelly optimum. "
                "Killed by the assertion on 'binding constraint'."
            ),
        ),
        # --- M5: the honesty control ---------------------------------------
        Mutation(
            group="M5",
            name="M5.1_control_equivalent_reformatting",
            path=SRC,
            old="    if proposal.fraction_of_capital <= demotion:",
            new="    if (proposal.fraction_of_capital <= demotion) is True:",
            intent=(
                "THE HONESTY CONTROL. Semantically identical to the shipped "
                "expression, so it MUST SURVIVE. A sweep that reports this killed "
                "is reporting a kill it cannot justify, and no other number it "
                "prints means anything (D-051's false 56/56)."
            ),
            expect_killed=False,
        ),
    ]


#: Mutations whose survival is REQUIRED rather than a defect.
_EXPECTED_INERT: frozenset[str] = frozenset()

#: Proofs for entries in ``_EXPECTED_INERT``. An entry there without a proof here
#: is a claim rather than a result, and ``main`` refuses to certify.
_INERT_PROOFS: dict[str, str] = {}


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test -- a conclusion about code nobody mutated. An
    ``old`` appearing zero times means the target has drifted and the mutation
    is not testing what its name says.
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


def check_tests_collect() -> list[str]:
    """Prove the test selection actually collects tests BEFORE the sweep runs.

    This gate exists because of a defect D-051's sweep found in itself: a bad
    target path makes pytest exit **4**, and exit 4 was being counted as a kill,
    producing a false 56/56.

    **D-070's lesson is the second reason it exists, and it is the sharper one.**
    D-070's sweep declared four files and ran three, and a GREEN GATE CERTIFIED A
    SELECTION NOBODY EXECUTED. The repair there was structural: both functions
    splat ONE constant. This sweep does the same -- but it goes one step further,
    because the version below is checked against the literal the ``subprocess``
    call inlines, by ``check_declaration_matches_run``.
    """
    problems: list[str] = []
    for target in PYTEST_TARGETS:
        path = REPO / target
        if not path.exists():
            problems.append(f"test target ABSENT: {target}")
            continue
        # The path is inlined as a literal rather than passed as `target`,
        # because ruff's S603 rule treats a variable argument as potentially
        # untrusted input. The loop verifies `path` exists above, so the two
        # stay in step; the convention is the one the other sweeps follow.
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/thesis_layer/test_risk_axis.py",
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
        # "N tests collected" / "N/M tests collected" -- take the numerator.
        match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
        if not match or int(match.group(1)) == 0:
            problems.append(f"test target collects ZERO tests: {target}")
    return problems


def check_declaration_matches_run() -> list[str]:
    """Prove ``PYTEST_TARGETS`` is the selection ``run_pytest`` actually runs.

    This is D-070's defect expressed as a gate. There, ``PYTEST_TARGETS``
    declared four test files and ``run_pytest`` ran three; ``check_tests_collect``
    validated the *declaration* the run never used, every mutant that should have
    died in the missing file survived, and the survivors looked exactly like
    inert mutants. The fix is to read the source and compare.

    A sweep whose declaration and execution can drift is a sweep that can
    certify a selection nobody executed, so this refuses rather than warns.

    **The anchor matters, and getting it wrong is this defect's own signature.**
    The obvious implementation searches the file for the runner's definition --
    and finds the first occurrence, which is the text in *this* docstring, so the
    slice comes out a few dozen characters long and the gate reported every target
    as un-inlined. The marker below must therefore not be quotable, and the search
    starts from a fixed offset past this function.

    ``_RUNNER_MARKER`` is the sentinel: the runner is located by that comment,
    which appears exactly once in the file and only in the real function body.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    start = source.index(_RUNNER_MARKER)
    end = source.index("\ndef apply_and_test(", start)
    body = source[start:end]

    declared = set(PYTEST_TARGETS)
    inlined = {t for t in declared if f'"{t}"' in body}

    missing = sorted(declared - inlined)
    if missing:
        return [f"declared in PYTEST_TARGETS but NOT inlined in run_pytest(): {t}" for t in missing]
    return []


#: The marker ``check_declaration_matches_run`` uses to locate the executor, so
#: the gate cannot accidentally search its own prose. It appears exactly once in
#: this file, immediately above the runner's ``subprocess`` table.
_RUNNER_MARKER = "# -- the executed selection (read by check_declaration_matches_run) --"


def run_pytest() -> tuple[int, str]:
    """Run the targeted tests. Non-zero means the mutation was killed.

    Exit code **4** is pytest's "usage error / no tests collected", which is not
    a kill -- it means the harness is broken. It is reported as an error rather
    than folded into the kill count, because that conflation is exactly what
    produced D-051's false 56/56.

    **``-x`` IS passed.** The selection is ~40 s on a clean tree; without ``-x``
    every mutant runs it to completion for information entirely contained in the
    first failure. The lesson: the kill signal must be cheap, because the cheap
    path is the one that gets used.
    """
    # -- the executed selection (read by check_declaration_matches_run) --
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/thesis_layer/test_risk_axis.py",
            "tests/thesis_layer/test_builder_live.py",
            "tests/thesis_layer/test_integrity_gates.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the selection, restore the file.

    The restore is in a ``finally`` block so an exception or a ``KeyboardInterrupt``
    cannot leave the source mutated -- D-049's failure. The sweep is FOREGROUND
    ONLY for the same reason.

    ``finally`` is NOT sufficient on its own: it covers exceptions and
    ``KeyboardInterrupt`` but not ``SIGTERM``, and D-057's first run was stopped
    by a process kill which bypassed the cleanup entirely, leaving a HARDCODED
    divisor in ``src/``. ``main`` therefore installs a ``SIGTERM``/``SIGINT``
    handler that restores the in-flight mutation before exiting. The residual
    ``SIGKILL`` risk cannot be engineered away.
    """
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


#: The mutation currently written to disk, so a signal handler can undo it.
#: ``(path, original_text)`` or ``None`` when nothing is applied. A one-slot list
#: rather than a module global so the handler can rebind without ``global``.
_IN_FLIGHT: list[tuple[Path, str] | None] = [None]


def _restore_in_flight(_signum: int, _frame: object) -> None:
    """Undo an in-flight mutation, then exit. Installed for SIGTERM/SIGINT.

    Without this, a killed sweep leaves mutated source on disk -- which is
    precisely what happened on D-057's first run (the ``SIGTERM`` bypassed the
    ``finally``) and had to be repaired by hand.
    """
    pending = _IN_FLIGHT[0]
    if pending is not None:
        path, original = pending
        path.write_text(original, encoding="utf-8", newline="")
        print(f"\n!! interrupted -- restored {path.name} from the in-flight mutation")
    raise SystemExit(130)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M2")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    # A killed sweep must not leave the tree mutated. ``finally`` covers
    # exceptions but not SIGTERM, and D-057's first run was stopped by exactly
    # that and left a hardcoded divisor applied.
    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: Section 17.4's risk axis (thesis_layer/builder.py, D-073)")
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

    test_problems = check_tests_collect()
    if test_problems:
        print("\nREFUSING TO RUN: the test selection is broken, so exit codes")
        print("would not distinguish a kill from a harness error:")
        for p in test_problems:
            print(f"  !! {p}")
        return 2

    drift = check_declaration_matches_run()
    if drift:
        print("\nREFUSING TO RUN: the declared selection is not the executed one.")
        print("This is D-070's defect -- a green gate certifying a selection")
        print("nobody ran -- so it is a hard refusal rather than a warning:")
        for p in drift:
            print(f"  !! {p}")
        return 2

    print(f"test selection collects cleanly: {', '.join(PYTEST_TARGETS)}")
    print("declaration verified against run_pytest(): no drift")

    if args.list:
        for mt in mutations:
            print(f"  {mt.group:4} {mt.path.name:16} {mt.name}")
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

    unexplained = [
        r
        for r in survived
        if r.mutation.expect_killed is not False
        and not r.mutation.inert_proof
        and r.mutation.name not in _EXPECTED_INERT
    ]
    if survived:
        print("\nsurvivors, classified:")
        for r in survived:
            if r.mutation.expect_killed is False:
                print(f"  [control]   {r.mutation.name}  (SURVIVAL IS REQUIRED)")
            elif r.mutation.name in _EXPECTED_INERT:
                print(f"  [inert]     {r.mutation.name}")
                proof = _INERT_PROOFS.get(r.mutation.name, "(PROOF MISSING)")
                print(f"              proof: {proof}")
            elif r.mutation.inert_proof:
                print(f"  [inert]     {r.mutation.name}")
                print(f"              proof: {r.mutation.inert_proof}")
            else:
                print(f"  [DEFECT]    {r.mutation.name} -- no test pins this")

    # An inert entry with no proof is a claim, not a result -- the same standard
    # the docstring sets, now enforced rather than merely stated.
    unproven = sorted(n for n in _EXPECTED_INERT if n not in _INERT_PROOFS)
    if unproven:
        print("\nREFUSING TO CERTIFY: these entries are declared inert WITHOUT a proof:")
        for name in unproven:
            print(f"  !! {name}")
        return 2

    if noop:
        print("\nnot applied (target text matched but produced no change):")
        for r in noop:
            print(f"  {r.mutation.name}")

    print("=" * 78)
    if unexplained:
        print(
            f"RESULT: {len(unexplained)} unexplained survivor(s). Each is a "
            "missing test, not a missing mutation."
        )
        return 1
    print("RESULT: every survivor is either expected or proven inert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
