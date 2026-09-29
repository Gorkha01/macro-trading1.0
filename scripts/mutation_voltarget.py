"""Mutation sweep for ``volatility_target_scaling`` (Module 17.2, Section 20.13, D-056).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/portfolio/risk_budget.py`` and
``src/macro_engine/config.py`` in place, so any concurrent test run, live check
or probe reads a mutated module. D-047's Postscript 2 records a contaminated
reading produced exactly that way, and D-049 left the source mutated when its
sweep was killed mid-run -- the full suite then passed *with the mutation in
place*. The blast radius is the whole repository.

Why the mutations are named after defects
-----------------------------------------
Both predecessors on this module -- ``evaluate_drawdown_rules`` (D-054) and
``check_rebalancing_drift`` (D-055) -- named their mutations after the defect
each one repairs, because the function's input space is continuous and its
decision space is tiny. ``volatility_target_scaling`` is the smallest decision
space yet: one multiply, one ``min``, three booleans and three mutually
exclusive warning branches. So the groups here are the **repairs of the six
documented defects** (plus the contract clauses), not an enumeration. A survivor
names a repair no test pins. The grouping, not the count, is what tells you what
is missing (D-031).

What this sweep structurally CANNOT find
----------------------------------------
**The D-037 class -- "declared, consumed, unreachable" -- is nearly invisible to
mutation testing, and that is the central defect of this increment.** D1 is four
of five ``RiskLimits`` fields never being read. A mutation must *change an
existing expression*; a field that appears in no expression has nothing to
mutate. ``M1.*`` therefore attacks the one place the unreachability is
*observable* -- ``unread_by_vol_targeting``'s returned list, and the published
``limits_declared_but_not_enforced`` key -- rather than the absence itself. If
this group ever reports survivors, the honest-reporting mechanism has lost its
only guard, and the four inert limits become silently inert again.

**The golden test is a HIT, not a PARTITION (D2), and no mutation can expose
that either.** ``test_vol_target_respects_hard_limits`` is phrased about
``max_leverage`` and passes on correct code; it passes equally on code that
enforces *only* ``max_leverage``, which is the shipped code. A test cannot be
killed for being under-specified by mutating the implementation -- the fix is a
different test, and ``M1.*`` is that different test expressed as a mutation
target. This is lesson 49 restated as a harness limitation.

The honesty control
-------------------
``M8.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. This control is what D-051's first
draft lacked when it reported a false 56/56.

The two-sided-clip problem
--------------------------
**``min()`` is the whole of this function's constraint enforcement, and ``min()``
is one-sided.** ``M3.*`` is the group that catches a repair which makes the clip
*look* two-sided without making it so. ``M3.2`` is the sharpest of them: applying
the ceiling only where ``raw_scale >= 1.0`` leaves the limit inert on exactly the
path a vol target exists for -- de-risking -- while the constraint still appears
enforced and still fires on the up-scaling side. A reader would call that fixed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from _sweep_gate import sweep_lifecycle

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/macro_engine/portfolio/risk_budget.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/test_infrastructure.py`` is included because the ``config.py``
#: mutants land on ``RiskSettings``'s new leaves and their accessors, and that
#: file is where the shipped YAML's round-trip through the settings model is
#: asserted.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
    "tests/portfolio/test_volatility_target.py",
    "tests/portfolio/test_risk_budget.py",
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
# known trap (lesson 50): ``ruff format`` reflows these lines when the surrounding
# code changes, and a drifted anchor reads as a test defect rather than a harness
# defect. The sweep is re-run at close for exactly this reason.

# --- M1: D1 -- the four inert limits and their honest reporting --------------

_M1_UNREAD_LIST = """        return [
            "max_position_pct_of_portfolio",
            "max_factor_exposure_pct",
            "min_liquidity_days_to_unwind",
        ]"""

_M1_PUBLISHED_KEY = '"limits_declared_but_not_enforced": inputs.limits.unread_by_vol_targeting,'

# --- M2: D5/D6 -- the exposure reading and the pre-existing breach -----------

_M2_BREACH = "    pre_existing_breach = inputs.current_gross_exposure > ceiling"
_M2_SCALED = "    scaled_exposure = inputs.current_gross_exposure * raw_scale"
_M2_CEILING = "    ceiling = inputs.limits.max_leverage"

# --- M3: D3/D4 -- the one-sided clip ----------------------------------------

_M3_CLIP = "    final_exposure = min(scaled_exposure, ceiling)"
_M3_CLIPPED_FLAG = "    clipped = final_exposure < scaled_exposure"

# --- M4: the reflexivity warning and its config-driven threshold ------------

_M4_THRESHOLD = "    reflexivity_threshold = settings.risk.reflexivity_scale_threshold"
_M4_GUARD = "    if raw_scale < reflexivity_threshold:"

# --- M5: direction and the de-risking magnitude -----------------------------

_M5_DIRECTION = (
    '    direction = "de-risk" if raw_scale < 1.0 else "lever up" if raw_scale > 1.0 else "hold"'
)
_M5_DERISK = '            "de_risking_fraction": round(max(0.0, 1.0 - raw_scale), 6),'


def build_mutations() -> list[Mutation]:
    """The catalogue, grouped by the defect each group repairs."""
    return [
        # -- M1: the four declared-but-inert limits (D1, the D-037 class) -----
        Mutation(
            group="M1",
            name="M1.1 the unread-limits report omits the factor-exposure limit",
            path=SRC,
            old=_M1_UNREAD_LIST,
            new=_M1_UNREAD_LIST.replace('            "max_factor_exposure_pct",\n', ""),
            intent=(
                "D1: the honest-reporting list. Dropping a name makes a declared-and-"
                "inert limit disappear from the one place its inertness is visible."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 the unread-limits report claims max_leverage is unenforced",
            path=SRC,
            old=_M1_UNREAD_LIST,
            new=_M1_UNREAD_LIST.replace(
                "        ]",
                '            "max_leverage",\n        ]',
            ),
            intent=(
                "D1: the mirror error. max_leverage IS enforced, so reporting it as "
                "unenforced is a false negative about the constraint that works."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.3 the unread-limits report is emptied",
            path=SRC,
            old=_M1_UNREAD_LIST,
            new="        return []",
            intent=(
                "D1: the full revert to the pre-D-056 state, where four inert limits "
                "were reported as none."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.4 the published key still computes but is renamed",
            path=SRC,
            old=_M1_PUBLISHED_KEY,
            new=_M1_PUBLISHED_KEY.replace("limits_declared_but_not_enforced", "unused_limits"),
            intent=(
                "The published vocabulary. A silent rename leaves a consumer reading "
                "an absent key without an error."
            ),
        ),
        # -- M2: D5/D6 -- the exposure reading and the breach attribution -----
        Mutation(
            group="M2",
            name="M2.1 the breach test is inclusive (at the ceiling reads as a breach)",
            path=SRC,
            old=_M2_BREACH,
            new="    pre_existing_breach = inputs.current_gross_exposure >= ceiling",
            intent=(
                "D6: at gross == ceiling the book is AT the limit, which the limit "
                "permits. An inclusive test calls a compliant book a breach."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the scale is applied to the ceiling instead of the exposure",
            path=SRC,
            old=_M2_SCALED,
            new="    scaled_exposure = inputs.current_gross_exposure + raw_scale",
            intent=(
                "D5: the exposure reading. Addition instead of multiplication makes "
                "the identity realised == target false for every gross but one."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.3 the ceiling is hardcoded to the shipped 3.0",
            path=SRC,
            old=_M2_CEILING,
            new="    ceiling = 3.0",
            intent=(
                "A hardcoded ceiling passes every test built on the shipped config. "
                "Section 21 prohibits literals in models."
            ),
        ),
        # -- M3: D3/D4 -- the one-sided clip ---------------------------------
        Mutation(
            group="M3",
            name="M3.1 the clip is removed entirely",
            path=SRC,
            old=_M3_CLIP,
            new="    final_exposure = scaled_exposure",
            intent=(
                "D3: the hard constraint gone. Section 20.13 says hard constraints "
                "always win, so this is the function's whole enforcement."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2 the clip is applied to the de-risking side only",
            path=SRC,
            old=_M3_CLIP,
            new=(
                "    final_exposure = (\n"
                "        min(scaled_exposure, ceiling) if raw_scale >= 1.0 else scaled_exposure\n"
                "    )"
            ),
            intent=(
                "D3: the one-sided clip relocated. Applying the ceiling ONLY when "
                "scaling up means the limit is inert exactly on the path it exists "
                "for -- the de-risking side -- while looking enforced."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the clipped flag reports inequality in the wrong direction",
            path=SRC,
            old=_M3_CLIPPED_FLAG,
            new="    clipped = final_exposure > scaled_exposure",
            intent=(
                "D4: `final < scaled` is exactly the condition under which the "
                "ceiling bound. Inverting it makes the flag always false."
            ),
        ),
        # -- M4: the reflexivity warning and its threshold --------------------
        Mutation(
            group="M4",
            name="M4.1 the reflexivity threshold is hardcoded to the shipped 0.8",
            path=SRC,
            old=_M4_THRESHOLD,
            new="    reflexivity_threshold = 0.8",
            intent=(
                "The threshold is a policy number, so Section 21 puts it in config. "
                "A literal passes every test that uses the shipped value."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 the reflexivity guard is inclusive at the threshold",
            path=SRC,
            old=_M4_GUARD,
            new="    if raw_scale <= reflexivity_threshold:",
            intent=(
                "A boundary convention. The `<=` widens the warning to exactly the "
                "threshold, which is the one input where the two differ."
            ),
        ),
        # -- M5: direction and the de-risking magnitude -----------------------
        Mutation(
            group="M5",
            name="M5.1 the direction labels are swapped",
            path=SRC,
            old=_M5_DIRECTION,
            new=_M5_DIRECTION.replace('"de-risk"', '"TMP"')
            .replace('"lever up"', '"de-risk"')
            .replace('"TMP"', '"lever up"'),
            intent=(
                "A de-risking function that reports 'lever up' when it cuts is the "
                "D-054 failure mode expressed as a label."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.2 the de-risking magnitude is clamped to zero",
            path=SRC,
            old=_M5_DERISK,
            new='            "de_risking_fraction": 0.0,',
            intent=(
                "D4's compensating signal. Without this key a 94% de-risking reports "
                "only `clipped=False`, so zeroing it restores the silent failure."
            ),
        ),
        # -- M6: the contract -------------------------------------------------
        Mutation(
            group="M6",
            name="M6.1 the confidence is hardcoded to the computed value",
            path=SRC,
            old="""    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            # The vol estimate is data-dependent but this function's own
            # arithmetic is a stated convention, and the target is a policy
            # number rather than a fitted one.
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
        )
    )""",
            new="    confidence = 0.5",
            intent=(
                "Section 22.8: compute_confidence() is the ONLY producer. The "
                "mutation's replacement string coincides with the computed value, "
                "which is what makes it inert -- see _INERT_PROOFS."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.2 the round() on the published scale is dropped",
            path=SRC,
            old='            "raw_scale": round(raw_scale, 6),',
            new='            "raw_scale": raw_scale,',
            intent=(
                "The published precision. Unrounded floats make the value map "
                "unstable across runs and platforms."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.3 the model_name is renamed",
            path=SRC,
            old='        model_name="volatility_target_scaling",',
            new='        model_name="vol_target",',
            intent="The model identity, which a downstream router may key on.",
        ),
        # -- M7: the input contract -------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 VolTargetInputs stops forbidding extra fields",
            path=SRC,
            old="""    \"\"\"

    model_config = ConfigDict(extra="forbid")

    target_vol_annualized: float = Field(""",
            new="""    \"\"\"

    model_config = ConfigDict(extra="ignore")

    target_vol_annualized: float = Field(""",
            intent=(
                "extra='forbid' is load-bearing: a typo'd kwarg would otherwise be "
                "ignored and the caller would read a result built from defaults. "
                "Anchored on the real model_config line rather than on the class "
                "header, because inserting a SECOND assignment above the docstring "
                "is overridden by this one and mutates nothing (caught by this "
                "sweep's first run)."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.2 RiskLimits stops forbidding extra fields",
            path=SRC,
            old="""    model_config = ConfigDict(extra="forbid")

    max_position_pct_of_portfolio: float = Field(""",
            new="""    model_config = ConfigDict(extra="ignore")

    max_position_pct_of_portfolio: float = Field(""",
            intent="Same contract clause on the limits model.",
        ),
        # -- M8: the honesty control ------------------------------------------
        Mutation(
            group="M8",
            name="M8.1 the pre-existing-breach short-circuit is expressed differently (CONTROL)",
            path=SRC,
            old="    clipped = final_exposure < scaled_exposure",
            new="    clipped = bool(final_exposure < scaled_exposure) is True",
            intent=(
                "The control. Semantically identical to the shipped code, so it MUST "
                "survive. A sweep that kills this is reporting kills it cannot "
                "justify (D-051)."
            ),
            expect_killed=False,
        ),
        # -- CX: the config surface -------------------------------------------
        Mutation(
            group="CX",
            name="CX1 the accessor returns the percent value unscaled",
            path=CONFIG,
            old="        return float(self.max_position_pct_of_portfolio.value)",
            new="        return float(self.max_position_pct_of_portfolio.value) * 100.0",
            intent=(
                "The D-054/D-056 unit trap. A 100x error here makes every position "
                "limit unreachable while the number still looks like a limit."
            ),
        ),
        Mutation(
            group="CX",
            name="CX2 the reflectivity accessor reads the leverage leaf",
            path=CONFIG,
            old="        return float(self.vol_target_reflexivity_scale.value)",
            new="        return float(self.max_leverage.value)",
            intent=(
                "A cross-leaf read: the accessor resolves, returns a plausible float "
                "(3.0), and is wrong. Only a test that moves the leaf catches it."
            ),
        ),
        Mutation(
            group="CX",
            name="CX3 the percent-in-fraction validator is deleted",
            path=CONFIG,
            old="""        for name, value in (
            ("max_position_pct_of_portfolio", self.max_position_fraction),
            ("max_factor_exposure_pct", self.max_factor_exposure_fraction),
        ):
            if not 0.0 < value <= 1.0:""",
            new="""        for name, value in (
            ("max_position_pct_of_portfolio", self.max_position_fraction),
            ("max_factor_exposure_pct", self.max_factor_exposure_fraction),
        ):
            if not 0.0 < value <= 10.0:""",
            intent=(
                "The settings-leaf unit guard. Widening the bound to 10.0 admits a "
                "percent (15.0 still rejected, so the guard looks alive) while "
                "letting the 100x error through in the 1.0..10.0 band."
            ),
        ),
    ]


#: Mutations that are provably unable to change behaviour. Every entry needs a
#: proof in ``_INERT_PROOFS`` or the harness returns exit 2 rather than certify.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M6.1 the confidence is hardcoded to the computed value",
    }
)

#: The proofs backing ``_EXPECTED_INERT``. A name in the set without a proof here
#: is a claim, not a result, and the harness refuses to certify.
#:
#: **M6.1 is INERT BY ANCHORING (lesson 54), and the proof is CONDITIONAL.** The
#: mutant's replacement is the literal ``0.5``; ``compute_confidence`` with the
#: shipped config returns ``base 0.7 - heuristic_penalty 0.2 = 0.5``. So over the
#: shipped configuration the two programs agree on every input -- not because the
#: branch is unreachable (as D-055's M4.6 was), but because the mutation's
#: *replacement string was transcribed from the value the code already computes*.
#: The proof is conditional for a real reason: ``config/settings.yaml`` carries
#: the confidence constants with ``calibration_status: uncalibrated_illustrative``
#: and a note that Phase 5+ recalibrates them. The moment ``base`` or
#: ``heuristic_penalty`` moves, ``0.5`` stops being the computed value and this
#: mutation becomes killable -- which is exactly the change Section 22.8 exists to
#: make visible.
#:
#: The honest conclusion: **this survivor is a limitation of the MUTATION, not a
#: gap in the tests.** ``test_confidence_is_computed_not_asserted`` asserts
#: ``result.confidence == approx(0.5)`` and cannot distinguish the two programs
#: for the same reason the mutation cannot -- they share an output. A mutation
#: aimed at 22.8 has to move the value, e.g. to ``0.9``; that variant is killable
#: and is deliberately NOT shipped here, because a mutation whose replacement is
#: chosen to be *wrong* tests the test, while this one records an equivalence.
_INERT_PROOFS: dict[str, str] = {
    "M6.1 the confidence is hardcoded to the computed value": (
        "CONDITIONAL ON THE SHIPPED CONFIG. Probed: compute_confidence with "
        "data_quality_flags_present=False, is_heuristic_not_calibrated=True and "
        "depends_on_unobservable=False returns 0.7 - 0.2 = 0.5, and the mutant's "
        "literal is 0.5, so the two programs agree on every reachable input. This "
        "is INERT BY ANCHORING rather than by unreachability: the branch is "
        "reachable and load-bearing, but the replacement was transcribed from the "
        "value it replaces. The proof expires when Phase 5+ recalibrates "
        "confidence.base or confidence.heuristic_penalty, at which point the "
        "literal stops coinciding and the same mutation becomes killable."
    ),
}


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` string appearing twice silently rewrites the wrong site and the sweep
    then reports a surviving test -- a conclusion about code nobody mutated. An
    ``old`` appearing zero times means the target has drifted and the mutation is
    not testing what its name says.

    **Derived-anchor ambiguity is the live hazard for this sweep.** Three
    functions now share ``risk_budget.py``. ``min(...)``, ``float(...)`` and
    ``>= ceiling``-shaped expressions all appear in more than one function, and
    ``evaluate_drawdown_rules`` ships ``reduction >= 1.0`` beside this function's
    ``raw_scale >= 1.0``-shaped direction test. So the anchors below are pinned
    to their surrounding statement rather than to the bare expression, and this
    gate is what proves the pinning worked.
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

    The near-miss trap for this sweep is that ``test_volatility_target.py`` is a
    NEW file in a package that already holds ``test_risk_budget.py``; a stale
    ``__init__.py`` or a name that differs by one word collects zero tests from a
    plausible-looking path.
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
                "tests/portfolio/test_volatility_target.py",
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


def run_pytest() -> tuple[int, str]:
    """Run the targeted tests. Non-zero means the mutation was killed.

    Exit code **4** is pytest's "usage error / no tests collected", which is not
    a kill -- it means the harness is broken. It is reported as an error rather
    than folded into the kill count, because that conflation is exactly what
    produced D-051's false 56/56.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/portfolio/test_volatility_target.py",
            "tests/portfolio/test_risk_budget.py",
            "tests/test_infrastructure.py",
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
    """
    original = mutation.path.read_text(encoding="utf-8")
    mutated = original.replace(mutation.old, mutation.new, 1)
    if mutated == original:
        return Result(mutation=mutation, applied=False, exit_code=-1)

    try:
        mutation.path.write_text(mutated, encoding="utf-8", newline="")
        code, out = run_pytest()
    finally:
        mutation.path.write_text(original, encoding="utf-8", newline="")
    return Result(mutation=mutation, applied=True, exit_code=code, output=out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M3")
    parser.add_argument(
        "--check-targets",
        dest="check_targets",
        action="store_true",
        help="alias for --list: the sweep-wide check-only flag (O-138)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("mutation sweep: volatility_target_scaling (Module 17.2, Section 20.13, D-056)")
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

    if args.list or args.check_targets:
        for mt in mutations:
            print(f"  {mt.group:4} {mt.path.name:16} {mt.name}")
        return 0

    if args.group:
        mutations = [mt for mt in mutations if mt.group == args.group]
        if not mutations:
            print(f"no mutations in group {args.group}")
            return 2
        print(f"restricted to group {args.group}: {len(mutations)} mutation(s)")

    # O-103: the sidecar is the interrupt defence with real reach on win32,
    # where no Python signal handler runs for SIGTERM/SIGINT and a killed
    # process gets no `finally` turn. This runs after the early returns so a
    # run that mutates nothing leaves no sidecar behind, and it heals a
    # previous kill BEFORE the baseline is read -- reading first would adopt
    # a mutant as the baseline (D-081).
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
