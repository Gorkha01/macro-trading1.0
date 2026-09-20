"""Mutation sweep for ``project_inflation_trajectory`` (Module 3.6, D-053).

Run this in the FOREGROUND ONLY. The sweep rewrites files under ``src/`` while it
runs -- that is what makes it a mutation sweep -- so nothing else may read those
files while it runs. D-049 is the demonstration of what happens otherwise: a
sweep was backgrounded, a mutation it had written was still on disk when the full
suite ran in another shell, and the suite failed against code nobody had written
on purpose.

Why this sweep exists at all
----------------------------
The module docstring names **seven specification defects**. The mutation groups
below are those defects, one group per defect, so a survivor points directly at
the repair that no test pins:

* **M1 -- the sign.** The specification negates twice (``slack = -s/100``, then
  ``pc = -beta*slack``) and the negations cancel, so the shipped expression is
  ``beta * score``. The single most likely defect in this function is writing one
  negation instead of two, which produces a plausible number in the wrong
  direction. M1 mutates the sign in both places it can be changed.
* **M2 -- the unit.** ``beta`` is in pp-per-score-point and the bands are in pp.
  A mutation that divides by 100 (the unit error the specification *made*) must
  be killed by the magnitude and band tests.
* **M3 -- the band comparison.** Strict on both sides, so a reading exactly on a
  bound is ``stable``. ``>`` -> ``>=`` and ``<`` -> ``<=`` are invisible in every
  non-boundary test; group M3 is the boundary test's reason to exist.
* **M4 -- reachability.** The D-047 base-state failure. A mutation that widens a
  band until a label dies must be killed by
  ``test_every_direction_is_reachable_over_the_declared_range``.
* **M5 -- the unread parameter.** The specification declares ``growth`` and never
  reads it. A mutation that restores that inertness must be killed.
* **M6 -- the §18.6 fiscal flag.** A mutation that ignores the flag, or that
  applies it so as to flip a sign, must be killed.
* **M7 -- provenance.** ``inputs_used`` must not list an input the body does not
  read (the specification listed ``inflation.value`` and never read it).
* **M8 -- §22.8.** ``confidence`` must come from ``compute_confidence()`` and must
  respond to the stated factors; the specification hardcoded ``0.35``.
* **M9 -- config.** The thresholds must come from ``settings.yaml``. Mutating a
  config property to a literal must be killed.
* **M10 -- the honesty control.** Two mutations that are semantically identical to
  the shipped code. A sweep that reports either as killed is reporting kills it
  cannot justify; they are expected to SURVIVE and are not defects.

Two kinds of inert survivor
---------------------------
``_EXPECTED_INERT`` carries mutations that survive at the shipped configuration
and are proven inert. Each proof is *executable*: ``--probe-inert`` re-applies the
mutation under a perturbed configuration, where it MUST be killed. An unproven
inertness claim would make a hole in the sweep indistinguishable from a test that
does not exist.

What "survived" means
---------------------
Three categories are recorded rather than hidden: ``expect_killed=False`` (the
honesty control), ``_EXPECTED_INERT`` (proven inert, with the proof executed), and
mutants targeting **warning wording** rather than a branch. The project's standing
position (D-049..D-052) is that warning *text* is not the safety mechanism -- the
warning *branch* is, and the branches are tested as a set. Wording mutants are not
expected to be killed and are not counted as defects.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODEL = REPO / "src/macro_engine/models/inflation_trajectory.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
PYTEST_TARGETS = [
    "tests/models/test_inflation_trajectory.py",
]

#: Mutations that survive at the SHIPPED configuration and are proven inert.
#: Each proof is executed by ``--probe-inert`` under a perturbed config.
#:
#: This set is EMPTY, and that is the honest outcome rather than a problem. The
#: first draft listed M8.3 here on the assumption that the main suite's fixtures
#: all carry empty warning lists. They do not:
#: ``test_labor_warnings_flag_the_confidence`` passes a populated list, so the
#: mutant is killed and the entry would have been a false inertness claim --
#: exactly the kind of claim that ``--probe-inert`` exists to falsify. It was
#: moved to the killed column after the sweep reported it KILLED.
#:
#: An empty set means this sweep currently claims **no** unobservable mutations,
#: which is a stronger statement than a populated set: nothing here is excused
#: from having a test.
_EXPECTED_INERT: frozenset[str] = frozenset()


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
        collected). Counting it as a kill is how the first draft of the D-051
        sweep reported 56/56 against a control that could not fail (D-051).
        """
        return self.exit_code not in (0, 4)


# --------------------------------------------------------------------------
# Transcribed targets. Every one of these is a byte-for-byte copy of text in
# the shipped source; check_targets refuses to run if any has drifted.
# --------------------------------------------------------------------------

# --- M1: the sign (Defect 6 — the two negations that cancel) --------------
_CHANGE_PP = "    change_pp = beta * score * fiscal_scale"

# --- M2: the unit (Defect 6 — pp vs score fraction) ----------------------
_BETA = "    beta = trajectory.beta_pp_per_score_point"

# --- M3: the band comparison (strict on both sides) ----------------------
_UPPER_BRANCH = "    if change_pp > upper:"
_LOWER_BRANCH = "    elif change_pp < lower:"

# --- M4: reachability (Defect 7 — the base-state failure) ---------------
_UPPER_BAND = "    upper = trajectory.bands.reaccelerating_above"

# --- M5: the unread parameter (Defect 3) --------------------------------
_CORROBORATION = "    corroboration, warnings = _growth_corroboration(inputs.growth, tight_labor)"

# --- M6: the §18.6 fiscal flag (Defect 5) -------------------------------
_FISCAL_SCALE = (
    "    fiscal_scale = trajectory.fiscal_active_scale if inputs.fiscal_response_active else 1.0"
)

# --- M7: provenance (Defect 4) -------------------------------------------
_INFLATION_READ = "    inflation_raw = inputs.inflation.value"

# --- M8: §22.8 confidence (Defect 2) ------------------------------------
_CONFIDENCE_CALL = "        confidence=compute_confidence("
_DATA_QUALITY = "                data_quality_flags_present=bool(inputs.labor.warnings),"
_INDEPENDENCE = (
    # Transcribed verbatim from the source; must not be reflowed, so the line
    # length is exempt here rather than the literal being broken across lines.
    # NOTE: this expression was reformatted by `ruff format` after the first
    # sweep (it was one long line, now three). check_targets caught the drift on
    # the close-out re-run -- which is exactly what the gate is for. When
    # anchoring a multi-line target, verify against the file as `ruff format`
    # leaves it, not as it was first written.
    "                    0\n"
    '                    if corroboration.startswith("disagrees") or corroboration == "unavailable"\n'
    "                    else 1"
)

# --- M9: config, not literals (Defect 1) --------------------------------
_NAIRU_CTX = '            f"NAIRU of {settings.phillips.nairu_value}% and the Section 6.3 "'


def build_mutations() -> list[Mutation]:
    """The catalogue. One group per specification defect the module names."""
    mutations: list[Mutation] = []

    # -- M1: the sign. Three independent ways to get it wrong. ------------
    mutations.append(
        Mutation(
            group="M1",
            name="M1.1 projected change sign inverted (single negation)",
            path=MODEL,
            old=_CHANGE_PP,
            new="    change_pp = beta * (-score) * fiscal_scale",
            intent=(
                "The specification negates twice and the negations cancel, so a "
                "tight market must project RISING inflation. Writing one negation "
                "inverts every direction while leaving magnitudes untouched -- the "
                "exact error the module docstring warns about."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M1",
            name="M1.2 projected change ignores the score sign (absolute value)",
            path=MODEL,
            old=_CHANGE_PP,
            new="    change_pp = beta * abs(score) * fiscal_scale",
            intent=(
                "Taking the magnitude loses the direction entirely: a loose market "
                "would project reaccelerating inflation."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M1",
            name="M1.3 projected change drops the score (constant sign)",
            path=MODEL,
            old=_CHANGE_PP,
            new="    change_pp = beta * (score - score) + beta * fiscal_scale",
            intent=(
                "A change independent of the score makes every direction a "
                "function of `fiscal_scale` alone. Only the monotonicity and "
                "sign tests catch this."
            ),
        )
    )

    # -- M2: the unit. -----------------------------------------------------
    mutations.append(
        Mutation(
            group="M2",
            name="M2.1 beta rescaled by 1/100 (the specification's unit error)",
            path=MODEL,
            old=_CHANGE_PP,
            new="    change_pp = beta * score / 100.0 * fiscal_scale",
            intent=(
                "Dividing by 100 is precisely the specification's unit mistake. "
                "It must be killed by the band and magnitude assertions, not by "
                "the sign test."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M2",
            name="M2.2 beta read from the wrong config leaf",
            path=MODEL,
            old=_BETA,
            new="    beta = trajectory.bands.reaccelerating_above",
            intent=(
                "Reading the band edge as the slope is a plausible-looking "
                "substitution that changes the published beta and the arithmetic."
            ),
        )
    )

    # -- M3: the band comparison. ------------------------------------------
    mutations.append(
        Mutation(
            group="M3",
            name="M3.1 upper comparison made non-strict (> to >=)",
            path=MODEL,
            old=_UPPER_BRANCH,
            new="    if change_pp >= upper:",
            intent=(
                "A reading exactly on the upper bound must fall to `stable`. "
                "Invisible in every non-boundary test, which is why the boundary "
                "test exists."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M3",
            name="M3.2 lower comparison made non-strict (< to <=)",
            path=MODEL,
            old=_LOWER_BRANCH,
            new="    elif change_pp <= lower:",
            intent="The mirror of M3.1 on the lower bound.",
        )
    )
    mutations.append(
        Mutation(
            group="M3",
            name="M3.3 band comparisons swapped (upper tested against lower)",
            path=MODEL,
            old=_UPPER_BRANCH,
            new="    if change_pp > lower:",
            intent=(
                "Testing the upper branch against the lower bound makes every "
                "positive reading `reaccelerating` and leaves `decelerating` to "
                "the elif, which is now unreachable in its intended range."
            ),
        )
    )

    # -- M4: reachability. --------------------------------------------------
    mutations.append(
        Mutation(
            group="M4",
            name="M4.1 upper band widened past the reachable range",
            path=MODEL,
            old=_UPPER_BAND,
            new="    upper = trajectory.bands.reaccelerating_above * 1000.0",
            intent=(
                "A band wider than the score can reach kills `reaccelerating` -- "
                "the D-047 base-state failure. Caught by the reachability test."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M4",
            name="M4.2 lower band widened past the reachable range",
            path=MODEL,
            old="    lower = trajectory.bands.decelerating_below",
            new="    lower = trajectory.bands.decelerating_below * 1000.0",
            intent="The mirror of M4.1 on the decelerating label.",
        )
    )

    # -- M5: the unread parameter. -----------------------------------------
    mutations.append(
        Mutation(
            group="M5",
            name="M5.1 growth ignored (the specification's defect restored)",
            path=MODEL,
            old=_CORROBORATION,
            new=(
                "    corroboration, warnings = _growth_corroboration("
                'ModelResult(model_name="ignored", country="us", as_of=utc_now(), '
                'value=0.0, confidence=0.0, interpretation="", context="", '
                "inputs_used=[], warnings=[]), tight_labor)"
            ),
            intent=(
                "Restores the specification's declared-but-unread parameter: "
                "`growth` is accepted and never consulted. Killed by "
                "test_growth_actually_changes_the_output."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M5",
            name="M5.2 corroboration always reports agreement",
            path=MODEL,
            old="    growth_expanding = growth_value > 0",
            new="    growth_expanding = (growth_value > 0) == bool(tight_labor)",
            intent=(
                "If the agreement test is forced true, the disagreement branch "
                "becomes unreachable and the warning never fires."
            ),
        )
    )

    # -- M6: the fiscal flag. ----------------------------------------------
    mutations.append(
        Mutation(
            group="M6",
            name="M6.1 fiscal flag ignored (scale always 1.0)",
            path=MODEL,
            old=_FISCAL_SCALE,
            new="    fiscal_scale = 1.0",
            intent=(
                "Section 18.6 requires the flag to weight the fiscal-transfer "
                "channel. Ignoring it makes the parameter declared-and-unread."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M6",
            name="M6.2 fiscal flag inverts the sign when active",
            path=MODEL,
            old=_FISCAL_SCALE,
            new=(
                "    fiscal_scale = -trajectory.fiscal_active_scale if "
                "inputs.fiscal_response_active else 1.0"
            ),
            intent=(
                "A negative multiplier flips the direction whenever fiscal is "
                "active. Killed by test_fiscal_flag_never_changes_the_sign."
            ),
        )
    )

    # -- M7: provenance. ----------------------------------------------------
    mutations.append(
        Mutation(
            group="M7",
            name="M7.1 inflation level not read (reported as a constant)",
            path=MODEL,
            old=_INFLATION_READ,
            new="    inflation_raw = 2.0",
            intent=(
                "The specification listed `inflation.value` in `inputs_used` and "
                "never read it. Reading a constant restores that false provenance "
                "claim. Killed by test_inflation_level_is_reported."
            ),
        )
    )

    # -- M8: §22.8 confidence. ---------------------------------------------
    mutations.append(
        Mutation(
            group="M8",
            name="M8.1 confidence hardcoded to the specification's 0.35",
            path=MODEL,
            old=_CONFIDENCE_CALL,
            new="        confidence=0.35,  # noqa: ERA001  compute_confidence(",
            intent=(
                "Section 22.8 forbids a hardcoded confidence: "
                "`compute_confidence()` is the only producer. 0.35 is the exact "
                "literal the specification wrote."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M8",
            name="M8.2 source-independence factor dropped",
            path=MODEL,
            old=_INDEPENDENCE,
            new="                    1",
            intent=(
                "Removing the disagreement penalty makes a contradicting growth "
                "reading score as well as a corroborating one. Killed by "
                "test_confidence_is_produced_not_hardcoded."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M8",
            name="M8.3 data-quality flag forced False",
            path=MODEL,
            old=_DATA_QUALITY,
            new="                data_quality_flags_present=False,  # noqa: ERA001",
            intent=(
                "Dropping the labor-warning flag means a flagged input no longer "
                "lowers confidence. Killed by "
                "test_labor_warnings_flag_the_confidence."
            ),
        )
    )

    # -- M9: config, not literals. -----------------------------------------
    mutations.append(
        Mutation(
            group="M9",
            name="M9.1 confidence factors forced off (calibrated-looking)",
            path=MODEL,
            old="                is_heuristic_not_calibrated=True,",
            new="                is_heuristic_not_calibrated=False,",
            intent=(
                "Claiming the model is calibrated when beta is not fitted is the "
                "§22.8 'falsely confident' failure. Changes the published "
                "confidence, so the computes-it-exactly test kills it."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M9",
            name="M9.2 unobservable dependency dropped",
            path=MODEL,
            old="                depends_on_unobservable=True,",
            new="                depends_on_unobservable=False,",
            intent=(
                "The Phillips relation is in u*, which §21.4 item 13 makes "
                "unobservable. Dropping the factor raises confidence above what "
                "the evidence supports."
            ),
        )
    )
    mutations.append(
        Mutation(
            group="M9",
            name="M9.3 context drops the NAIRU it claims to interpret against",
            path=MODEL,
            old=_NAIRU_CTX,
            new='            f"Section 6.3 "',
            intent=(
                "The context string asserts the reading is interpreted against "
                "the configured NAIRU. Removing the reference makes that claim "
                "false. Report-only: see the wording-mutant note in the docstring."
            ),
            expect_killed=False,
        )
    )
    mutations.append(
        Mutation(
            group="M9",
            name="M9.4 config property returns the wrong unit scale",
            path=CONFIG,
            old="        return float(self.beta_core_inflation_pp_per_score_point.value)",
            new="        return float(self.beta_core_inflation_pp_per_score_point.value) / 100.0",
            intent=(
                "A 100x error in the config accessor is the specification's unit "
                "mistake relocated into config, where no model-body test looks. "
                "Must be killed by the magnitude and band tests."
            ),
        )
    )

    # -- M10: the honesty control. -----------------------------------------
    mutations.append(
        Mutation(
            group="M10",
            name="M10.1 honesty control: arithmetic rewritten equivalently",
            path=MODEL,
            old=_CHANGE_PP,
            new="    change_pp = (score * beta) * fiscal_scale",
            intent=(
                "HONESTY CONTROL. Commutative multiplication: semantically "
                "identical to the shipped expression. This mutation MUST SURVIVE. "
                "A sweep that reports it killed is reporting a kill it cannot "
                "justify."
            ),
            expect_killed=False,
        )
    )
    mutations.append(
        Mutation(
            group="M10",
            name="M10.2 honesty control: docstring wording only",
            path=MODEL,
            old='            f"{_SCORE_CEILING:.0f}] scale; got {type(value).__name__} ({value!r})."',
            new='            f"{_SCORE_CEILING:.0f}] scale; received {type(value).__name__} ({value!r})."',
            intent=(
                "HONESTY CONTROL. A wording change inside an error message that no "
                "test matches on. MUST SURVIVE -- if it is killed, a test is "
                "asserting on prose rather than on behaviour."
            ),
            expect_killed=False,
        )
    )

    return mutations


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` string appearing twice silently rewrites the wrong site and the sweep
    then reports a surviving test -- a conclusion about code nobody mutated. An
    ``old`` appearing zero times means the target has drifted and the mutation is
    not testing what its name says.
    """
    problems: list[str] = []
    by_file: dict[Path, str] = {}
    for path in {mt.path for mt in mutations}:
        by_file[path] = path.read_text(encoding="utf-8")

    for mt in mutations:
        text = by_file[mt.path]
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

    This gate exists because of a defect the D-051 sweep found in itself: a bad
    target path makes pytest exit **4**, and exit 4 was being counted as a kill,
    producing a false 56/56.
    """
    problems: list[str] = []
    for target in PYTEST_TARGETS:
        path = REPO / target
        if not path.exists():
            problems.append(f"test target ABSENT: {target}")
            continue
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/models/test_inflation_trajectory.py",
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
    a kill -- it means the harness is broken.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "--no-header",
            "tests/models/test_inflation_trajectory.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the tests, restore the file. Foreground only.

    The restore reads from the in-memory ``original`` rather than a backup file,
    so the ``finally`` is unconditional: a crash inside ``run_pytest`` still puts
    the shipped source back. A sweep that can leave ``src/`` mutated is the D-049
    failure mode with extra steps.
    """
    original = mutation.path.read_text(encoding="utf-8")
    mutated = original.replace(mutation.old, mutation.new, 1)
    if mutated == original:
        return Result(mutation=mutation, applied=False, exit_code=0)

    try:
        mutation.path.write_text(mutated, encoding="utf-8", newline="")
        code, out = run_pytest()
    finally:
        mutation.path.write_text(original, encoding="utf-8", newline="")
    return Result(mutation=mutation, applied=True, exit_code=code, output=out)


def probe_threshold_inertness(mutations: list[Mutation]) -> int:
    """Re-apply every ``_EXPECTED_INERT`` mutation under a perturbed config.

    A mutation declared inert must become KILLED once the input it cannot reach is
    made reachable. If it still survives there, the "inert" claim is a hole in the
    sweep rather than a proof.

    ``_EXPECTED_INERT`` is currently empty (see its docstring: the one candidate,
    M8.3, turned out to be killed outright), so this reports that there is nothing
    to prove rather than silently passing. The machinery is kept because the next
    increment that adds an inert claim inherits a proof harness rather than a
    promise.
    """
    targets = [mt for mt in mutations if mt.name in _EXPECTED_INERT]
    if not targets:
        print("_EXPECTED_INERT is empty -- no inertness claims to prove.")
        print("This is a statement, not a skip: the sweep excuses no mutation.")
        return 0

    test_path = REPO / f"{PYTEST_TARGETS[0]}"
    original_test = test_path.read_text(encoding="utf-8")
    problems: list[str] = []

    for mt in targets:
        original = mt.path.read_text(encoding="utf-8")
        # Perturb the fixture so results carry a warning, making the
        # data-quality-dependent mutants distinguishable.
        perturbed_test = original_test.replace(
            "        warnings=warnings or [],",
            '        warnings=warnings if warnings is not None else ["probe-inert"],',
            1,
        )
        mutated = original.replace(mt.old, mt.new, 1)
        if mutated == original:
            problems.append(f"{mt.name}: target went ABSENT between the main run and --probe-inert")
            continue
        try:
            mt.path.write_text(mutated, encoding="utf-8", newline="")
            test_path.write_text(perturbed_test, encoding="utf-8", newline="")
            code, _out = run_pytest()
        finally:
            mt.path.write_text(original, encoding="utf-8", newline="")
            test_path.write_text(original_test, encoding="utf-8", newline="")
        killed = code not in (0, 4)
        verdict = "KILLED (proof holds)" if killed else "SURVIVED (proof FAILS)"
        print(f"  {mt.name}: {verdict}")
        if not killed:
            problems.append(
                f"{mt.name}: declared inert but still survives when the input "
                f"becomes reachable -- the inertness claim is unproven"
            )
    if problems:
        for p in problems:
            print(f"  !! {p}")
        return 1
    print("every _EXPECTED_INERT claim is proven by perturbation.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M1")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    parser.add_argument(
        "--probe-inert",
        action="store_true",
        help="re-apply every _EXPECTED_INERT mutation under a perturbed config; "
        "each must be KILLED there. Run this AFTER the main sweep.",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("mutation sweep: project_inflation_trajectory (Module 3.6, D-053)")
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
    print(f"test selection collects cleanly: {', '.join(PYTEST_TARGETS)}")

    if args.list:
        for mt in mutations:
            print(f"  {mt.group:3} {mt.path.name:26} {mt.name}")
        return 0

    if args.probe_inert:
        return probe_threshold_inertness(mutations)

    if args.group:
        mutations = [mt for mt in mutations if mt.group == args.group]
        if not mutations:
            print(f"no mutations in group {args.group}")
            return 2
        print(f"restricted to group {args.group}: {len(mutations)} mutation(s)")

    results: list[Result] = []
    for mt in mutations:
        print(f"\n--- {mt.group} {mt.name}")
        print(f"    intent: {mt.intent}")
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
                print(f"  [expected]  {r.mutation.name}")
            elif r.mutation.name in _EXPECTED_INERT and not r.mutation.inert_proof:
                print(f"  [inert]     {r.mutation.name}")
                print(
                    "              proof: executed by `--probe-inert` "
                    "(see _EXPECTED_INERT for the argument)"
                )
            elif r.mutation.inert_proof:
                print(f"  [inert]     {r.mutation.name}")
                print(f"              proof: {r.mutation.inert_proof}")
            else:
                print(f"  [DEFECT]    {r.mutation.name} -- no test pins this")
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
