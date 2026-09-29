"""Mutation sweep for ``construct_breakeven_trade`` (Module 15.2, D-060).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/models/yield_curve.py`` and ``src/macro_engine/config.py`` in
place, so any concurrent test run, live check or probe reads a mutated module.
D-049, D-057 and D-058 all left source mutated when a sweep was killed mid-run,
and the full suite then passed *with the mutation in place*. The blast radius is
the whole repository.

What this increment is really testing
-------------------------------------
Section 15.1b's breakeven constructor publishes **no residual and no warnings
list at all** -- unlike its sibling curve constructor, which at least publishes a
residual that nothing can ever make nonzero (D-059). So before this
implementation the breakeven trade had **no guard of any kind**: a duration
wrong by ten times produced a wrong notional, silently, and there was not even a
dead check to point at.

That changes the shape of this sweep. D-059's catalogue had to explain why its
centre mutation was *inert by construction*; here every guard is live, so a
survivor in ``M3``/``M4`` is a **genuine coverage gap** unless a proof says
otherwise. The catalogue still carries one construction inert (``M1.4``, the
residual) because the published key is definitional for the same algebraic
reason -- and that pair of facts (a dead guard in the sibling, NO guard here) is
the increment's actual finding.

What this sweep structurally CANNOT find
----------------------------------------
1. **That the residual is definitional.** ``M1.4`` can only be shown inert; the
   finding is a statement about the *definition*, pinned by a test rather than
   by a mutant.

2. **The N*D vs N*P*D gap.** The function cannot see a price, so no mutation
   makes it *detect* the gap -- there is nothing in its inputs to detect. The
   gap lives in the live cross-check (``scripts/live_breakeven_trade.py``) and
   ships as O-59. ``M6.2`` mutates the warning that discloses it.

3. **The direction field's correctness.** ``M2.4`` inverts the comparator, which
   is detectable; but whether "longer_nominal_duration" is the *right name* for
   a given ratio is a naming claim, not an arithmetic one.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything.

**D-059's first run reported ``31/31 killed, 0 survived`` and it was false** --
a dead test in the suite turned every mutation into a "kill", and only the
control (which cannot be killed) exposed it. The identical failure mode is
available here, which is why the full suite is required to be green on
*unmutated* source before this script is run, and why the control stays.

Anchors
-------
Anchors are transcribed from the SHIPPED source and re-verified against it by
``check_targets`` before a single mutation is applied. Formatting drift is a
known trap (lesson 50): ``ruff format`` reflows these lines, and a drifted
anchor reads as a test defect rather than a harness defect. D-058's ``CX4`` and
D-059's ``M6.2`` were both exactly this -- an anchor written from memory rather
than sliced from the source. The long anchors below are therefore SLICED rather
than transcribed, and the sweep is re-run at close for the same reason.
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
YIELD_CURVE = REPO / "src/macro_engine/models/yield_curve.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/models/test_breakeven_trade.py`` is the new file and carries the
#: behavioural assertions. ``tests/models/test_curve_trade.py`` and
#: ``tests/models/test_yield_curve.py`` are included because the new code shares
#: a module with both -- a mutation that breaks a neighbouring function must not
#: be attributed to a gap in the new file. ``tests/test_infrastructure.py`` is
#: included because the ``config.py`` mutants land on ``CurveTradeSettings``.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
    "tests/models/test_breakeven_trade.py",
    "tests/models/test_curve_trade.py",
    "tests/models/test_yield_curve.py",
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
# Anchors
# ---------------------------------------------------------------------------


def _slice_source(path: Path, first: str, last: str) -> str:
    """Return the source text from the line containing ``first`` to ``last``.

    Raises at import if either marker is absent, so a drift is a loud failure
    rather than a silent no-op mutation. This is D-059's ``M6.2`` fix -- a
    hand-wrapped anchor for a multi-line block is how a mutation quietly stops
    matching its target.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if first in ln), None)
    if start is None:
        raise RuntimeError(f"anchor start not found in {path.name}: {first!r}")
    end = next((i for i in range(start, len(lines)) if last in lines[i]), None)
    if end is None:
        raise RuntimeError(f"anchor end not found in {path.name}: {last!r}")
    return "".join(lines[start : end + 1])


# --- M1: the notional arithmetic ---------------------------------------------

# `ruff format` broke this across three physical lines; a hand-wrapped literal
# is how an anchor silently stops matching (D-058's CX4, D-059's M6.2). Sliced.
_M1_NOTIONAL = _slice_source(
    YIELD_CURVE,
    "notional_nominal = inputs.target_notional_tips * (",
    "inputs.tips_duration / inputs.nominal_duration",
)
_M1_RATIO = "    duration_ratio = inputs.tips_duration / inputs.nominal_duration"
_M1_NOTIONAL_RATIO = "    nominal_to_tips_ratio = notional_nominal / inputs.target_notional_tips"
_M1_DUR_DOLLARS_TIPS = (
    "    duration_dollars_tips = inputs.target_notional_tips * inputs.tips_duration"
)
_M1_DUR_DOLLARS_NOMINAL = (
    "    duration_dollars_nominal = notional_nominal * inputs.nominal_duration"
)
_M1_RESIDUAL = "    net_duration_residual = duration_dollars_tips - duration_dollars_nominal"

# --- M2: the published value and the reported direction ----------------------

_M2_KEY_NOMINAL = '            "notional_nominal_short": round(notional_nominal, 2),'
_M2_KEY_NOTIONAL_RATIO = (
    '            "nominal_to_tips_notional_ratio": round(nominal_to_tips_ratio, 6),'
)
_M2_KEY_DURATION_RATIO = '            "duration_ratio_tips_to_nominal": round(duration_ratio, 6),'
# The definitional key appears in BOTH this function and D-059's. The anchor is
# extended through the following keys, which differ between the two.
_M2_KEY_DEFINITIONAL = _slice_source(
    YIELD_CURVE,
    '"net_duration_residual_is_definitional": True,',
    '"tenor": inputs.tenor,',
)
_M2_DIRECTION_GUARD = "    if duration_ratio > 1.0:"
_M2_DIRECTION_LABEL = '        direction = "longer_tips_duration"'
_M2_DIRECTION_ELSE = '        direction = "longer_nominal_duration"'

# --- M3: the ratio guard (the replacement for a guard §15.1b never had) ------

_M3_IDENTICAL_CHECK = "        if self.tips_duration == self.nominal_duration:"
_M3_RATIO_FLOOR = "        ratio_floor = settings.minimum_breakeven_duration_ratio"
_M3_RATIO_CEILING = "        ratio_ceiling = settings.maximum_breakeven_duration_ratio"
_M3_RATIO_BAND = "        if not ratio_floor <= ratio <= ratio_ceiling:"
_M3_RATIO_CALC = "        ratio = self.tips_duration / self.nominal_duration"

# --- M4: the per-leg duration/tenor band -------------------------------------

# floor/ceiling/the band are BYTE-IDENTICAL to D-059's anchors in the same file.
# Every anchor here therefore spans from the band down through the loop that
# follows it, which is unique to this contract -- D-051's exact failure mode,
# caught by check_targets before a single mutation ran.
_M4_TIPS_BLOCK = _slice_source(
    YIELD_CURVE,
    "        floor = settings.minimum_duration_to_tenor",
    '            ("tips", self.tips_duration),',
)
_M4_NOMINAL_BLOCK = _slice_source(
    YIELD_CURVE,
    "        floor = settings.minimum_duration_to_tenor",
    '            ("nominal", self.nominal_duration),',
)
_M4_BAND = "            if not floor <= ratio <= ceiling:"
_M4_YEARS = "        years = _tenor_years(self.tenor)"
_M4_LOOP = """        for label, duration in (
            ("tips", self.tips_duration),
            ("nominal", self.nominal_duration),
        ):"""

# --- M5: the attestation and the attestation warning -------------------------

# Both constructors declare this field with the same two-line opening, so the
# anchor is extended into the breakeven-specific description ("BOTH durations"
# against the curve constructor's "both durations").
_M5_MODIFIED_DEFAULT = _slice_source(
    YIELD_CURVE,
    "    duration_is_modified: bool = Field(",
    "different yields, so the notional ",
)
_M5_MODIFIED_GUARD = _slice_source(
    YIELD_CURVE,
    "    if not inputs.duration_is_modified:",
    "arithmetic check in this function can detect it.",
)

# --- M6: the residual warning (definitional -- see M1.4) ---------------------

_M6_RESIDUAL_GUARD = "    if abs(net_duration_residual) >= settings.display_tolerance:"

# --- M7: the tenor parser ----------------------------------------------------
# `_tenor_years` is shared with D-059's curve constructor, so these mutations are
# expected to be killed by BOTH test files. That is the point of including the
# curve tests in the selection: a shared helper's guard must be pinned once, and
# this sweep proves the two files together do that.

_M7_SUFFIX = '    if not text.endswith("y") or not text[:-1]:'
_M7_POSITIVE = "    if years <= 0.0:"
_M7_PARSE = "        years = float(text[:-1])"

# --- M8: the config accessors (config.py) ------------------------------------

_M8_RATIO_FLOOR_ACCESSOR = "        return float(self.breakeven_duration_ratio_min.value)"
_M8_RATIO_CEILING_ACCESSOR = "        return float(self.breakeven_duration_ratio_max.value)"
_M8_TOLERANCE_ACCESSOR = "        return float(self.net_duration_display_pct.value)"

# --- M9: the honesty control -------------------------------------------------

_M9_CONTROL_OLD = '        direction = "longer_tips_duration"'
_M9_CONTROL_NEW = '        direction = "longer_" + "tips_duration"'

# The disclosure warning is four concatenated string lines and a closing paren;
# transcribing it by hand is how an anchor drifts. Sliced from the source.
_M6_DISCLOSURE = _slice_source(
    YIELD_CURVE,
    "Notional is duration-matched under the N*D convention",
    "cannot be applied as a fixed adjustment. See O-59.",
)


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: arithmetic ------------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 notional divides instead of multiplying by the ratio",
            path=YIELD_CURVE,
            old=_M1_NOTIONAL,
            new=(
                "    notional_nominal = inputs.target_notional_tips * "
                "(inputs.nominal_duration / inputs.tips_duration)"
            ),
            intent="Inverted ratio: the single most consequential arithmetic error here.",
        ),
        Mutation(
            group="M1",
            name="M1.2 duration-dollars use the wrong legs' notional",
            path=YIELD_CURVE,
            old=_M1_DUR_DOLLARS_NOMINAL,
            new=(
                "    duration_dollars_nominal = "
                "inputs.target_notional_tips * inputs.nominal_duration"
            ),
            intent="The nominal leg's duration-dollars read the TIPS notional.",
        ),
        Mutation(
            group="M1",
            name="M1.3 the residual adds instead of subtracting",
            path=YIELD_CURVE,
            old=_M1_RESIDUAL,
            new="    net_duration_residual = duration_dollars_tips + duration_dollars_nominal",
            intent=(
                "The residual is definitional, so the shipped value is exactly "
                "zero and the mutant makes it 2*x. This was FIRST recorded as "
                "inert-by-construction, on the reasoning that the value is an "
                "algebraic identity no test should pin. That reasoning was WRONG "
                "on the observable half: the residual's consumer is a warning "
                "guarded by `>= display_tolerance`, and the mutant's value is "
                "large, so the mutant PUBLISHES A WARNING where the shipped "
                "contract publishes none. It is therefore killed by an "
                "ABSENCE assertion -- the D-038 'absence half' -- which is what "
                "test_no_residual_warning_is_ever_published now provides. Kept as "
                "a killed mutation: the survivor it once was was a test gap, not "
                "an inertness."
            ),
        ),
        # -- M2: the published value and the reported direction ------------
        Mutation(
            group="M2",
            name="M2.1 the ratio is published as the notional ratio (same number)",
            path=YIELD_CURVE,
            old=_M2_KEY_DURATION_RATIO,
            new='            "duration_ratio_tips_to_nominal": round(nominal_to_tips_ratio, 6),',
            intent=(
                "The two ratios ARE the same number by construction, so this is a "
                "name-level substitution: it must be killed by a test that reads "
                "the duration ratio as a function of the DURATIONS rather than of "
                "the notionals."
            ),
            inert_proof=(
                "NAME-NOT-VALUE (D-052's M9.2 class), and the 'must be killed' "
                "line above is WRONG -- it is exactly backwards and was written "
                "before the mutant was ever run. The two published keys are the "
                "SAME EXPRESSION: `nominal_to_tips_notional_ratio` and "
                "`duration_ratio_tips_to_nominal` are both `D_tips / D_nom`, one "
                "computed from inputs.tips_duration/inputs.nominal_duration and "
                "the other from the notionals that were derived to make the "
                "equality exact (N_nom/N_tips = D_tips/D_nom by the shipping "
                "rule). A test COULD pin each key against the durations, but it "
                "would then be pinning an algebraic identity -- the same defect "
                "as D-059's M1.3 -- because there is no input for which the two "
                "numbers differ. Proven by EXECUTION, not by reading: the mutant "
                "was applied by hand to the live file, the function called, and "
                "the result compared. "
                "applied M2.1 -> duration_ratio under M2.1: 1.125481; "
                "notional_ratio: 1.125481; source RESTORED -> shipped "
                "duration_ratio: 1.125481. Byte-identical output, so no "
                "assertion about the VALUE can distinguish them. What IS "
                "load-bearing is that both keys are published at all and that "
                "`duration_ratio_tips_to_nominal` is typed as a number -- pinned "
                "by the key-set assertion in "
                "test_every_published_key_is_present."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the direction comparator inverts",
            path=YIELD_CURVE,
            old=_M2_DIRECTION_GUARD,
            new="    if duration_ratio < 1.0:",
            intent="The reported direction is the opposite of the measured ratio.",
        ),
        Mutation(
            group="M2",
            name="M2.3 the two direction labels swap",
            path=YIELD_CURVE,
            old=_M2_DIRECTION_LABEL,
            new='        direction = "longer_nominal_duration"',
            intent=(
                "The common-case label is wrong. The inverted fixture publishes "
                "the other label, so a test covering only one direction cannot "
                "see this."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.4 the definitional flag is flipped",
            path=YIELD_CURVE,
            old=_M2_KEY_DEFINITIONAL,
            new='            "net_duration_residual_is_definitional": False,',
            intent=(
                "The key that tells a reader the residual is not a check. This is "
                "the ONLY pin on the residual's status, since the value itself is "
                "a constant (M1.3)."
            ),
        ),
        # -- M3: the ratio guard -------------------------------------------
        Mutation(
            group="M3",
            name="M3.1 the identical-legs check is removed",
            path=YIELD_CURVE,
            old=_M3_IDENTICAL_CHECK,
            new="        if False:",
            intent="A ratio of exactly 1.0 must be refused as the same instrument twice.",
        ),
        Mutation(
            group="M3",
            name="M3.2 the ratio band's floor is raised to the ceiling",
            path=YIELD_CURVE,
            old=_M3_RATIO_FLOOR,
            new=("        ratio_floor = settings.maximum_breakeven_duration_ratio"),
            intent=(
                "Floor and ceiling both become 1.6, so everything below 1.6 is "
                "refused. The lower half of the band must be exercised."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the ratio band's ceiling is lowered to the floor",
            path=YIELD_CURVE,
            old=_M3_RATIO_CEILING,
            new="        ratio_ceiling = settings.minimum_breakeven_duration_ratio",
            intent="Mirror of M3.2: everything above 0.5 is refused.",
        ),
        Mutation(
            group="M3",
            name="M3.4 the ratio is inverted before the band check",
            path=YIELD_CURVE,
            old=_M3_RATIO_CALC,
            new="        ratio = self.nominal_duration / self.tips_duration",
            intent=(
                "The band becomes asymmetric in the wrong direction: 0.76 and "
                "1.24 swap places, so a fixture on one side survives."
            ),
        ),
        # -- M4: the per-leg band ------------------------------------------
        Mutation(
            group="M4",
            name="M4.1 the per-leg floor is replaced by the ceiling",
            path=YIELD_CURVE,
            old=_M4_TIPS_BLOCK,
            new=_M4_TIPS_BLOCK.replace(
                "floor = settings.minimum_duration_to_tenor",
                "floor = settings.maximum_duration_to_tenor",
            ),
            intent="Both bounds become 1.05, so any duration below 1.05x is refused.",
        ),
        Mutation(
            group="M4",
            name="M4.2 the per-leg band is widened to always accept",
            path=YIELD_CURVE,
            old=_M4_TIPS_BLOCK,
            new=_M4_TIPS_BLOCK.replace(
                "if not floor <= ratio <= ceiling:",
                "if not 0.0 <= ratio <= 100.0:",
            ),
            intent=(
                "A guard loose enough to accept a duration wrong by 10x: this is "
                "the D-055/D-057 'loosened bound still looks alive' shape."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.3 the TIPS leg is dropped from the loop",
            path=YIELD_CURVE,
            old=_M4_LOOP,
            new="""        for label, duration in (
            ("nominal", self.nominal_duration),
        ):""",
            intent=(
                "Only the nominal leg is band-checked. D-059's M4.5 was exactly "
                "this shape and it SURVIVED there, because every fixture used a "
                "bad short-leg duration."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.4 the nominal leg is dropped from the loop",
            path=YIELD_CURVE,
            old=_M4_LOOP,
            new="""        for label, duration in (
            ("tips", self.tips_duration),
        ):""",
            intent="Mirror of M4.3, so neither leg can be dropped unnoticed.",
        ),
        # -- M5: the attestation -------------------------------------------
        Mutation(
            group="M5",
            name="M5.1 the modified-duration default becomes False",
            path=YIELD_CURVE,
            old=_M5_MODIFIED_DEFAULT,
            new=_M5_MODIFIED_DEFAULT.replace("default=True", "default=False"),
            intent=(
                "The default flips, so every caller that omits the attestation "
                "gets the warning. Requires a test that omits it."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.2 the attestation warning never fires",
            path=YIELD_CURVE,
            old=_M5_MODIFIED_GUARD,
            new="    if False:\n        pass",
            intent="The warning becomes dead code while the field still exists.",
        ),
        # -- M6: the disclosure --------------------------------------------
        Mutation(
            group="M6",
            name="M6.1 the residual warning's threshold inverts",
            path=YIELD_CURVE,
            old=_M6_RESIDUAL_GUARD,
            new="    if abs(net_duration_residual) < settings.display_tolerance:",
            intent=(
                "The guard that can only fire on float noise is inverted, so it "
                "fires on the exact-zero case INSTEAD. The shipped warning is "
                "absent for every input, so this mutant ADDS a warning where "
                "there was none -- observable only by a test asserting absence."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.2 the O-59 disclosure is dropped",
            path=YIELD_CURVE,
            old=_M6_DISCLOSURE,
            new="    pass",
            intent=(
                "The only place the N*D-vs-N*P*D gap is disclosed. A test asserting "
                "the caveat is present must exist, because nothing else in the "
                "function can reveal it."
            ),
        ),
        # -- M7: the shared tenor parser -----------------------------------
        Mutation(
            group="M7",
            name="M7.1 the tenor suffix check accepts anything",
            path=YIELD_CURVE,
            old=_M7_SUFFIX,
            new="    if not text[:-1]:",
            intent=(
                "A bare number with no 'y' suffix becomes legal, so '10' names a "
                "10-year tenor. Shared with D-059's contract; both test files "
                "should kill this."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.2 the positivity check is removed",
            path=YIELD_CURVE,
            old=_M7_POSITIVE,
            new="    if years < -1e9:",
            intent=(
                "'0y' and negative tenors become legal. Note the guard is "
                "load-bearing for the band: a zero tenor divides by zero."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.3 the years are parsed without the suffix strip",
            path=YIELD_CURVE,
            old=_M7_PARSE,
            new="        years = float(text)",
            intent="'10y' raises instead of parsing, so every valid tenor breaks.",
        ),
        # -- M8: the config accessors --------------------------------------
        Mutation(
            group="M8",
            name="M8.1 the ratio floor accessor reads the ceiling",
            path=CONFIG,
            old=_M8_RATIO_FLOOR_ACCESSOR,
            new="        return float(self.breakeven_duration_ratio_max.value)",
            intent="The ratio band collapses to a point at 1.6.",
        ),
        Mutation(
            group="M8",
            name="M8.2 the ratio ceiling accessor reads the floor",
            path=CONFIG,
            old=_M8_RATIO_CEILING_ACCESSOR,
            new="        return float(self.breakeven_duration_ratio_min.value)",
            intent="Mirror of M8.1: the band collapses to a point at 0.5.",
        ),
        Mutation(
            group="M8",
            name="M8.3 the display tolerance accessor reads the ratio ceiling",
            path=CONFIG,
            old=_M8_TOLERANCE_ACCESSOR,
            new="        return float(self.breakeven_duration_ratio_max.value)",
            intent=(
                "0.01 becomes 1.6, so the definitional residual's warning "
                "threshold moves. This is D-059's M8.3 shape -- there the guard "
                "was dead and the mutant survived; here the value feeds a guard "
                "whose shipped predicate is False at both values, so SURVIVAL IS "
                "EXPECTED for the same reason. See _INERT_PROOFS."
            ),
            expect_killed=False,
            inert_proof=(
                "INERT BY UNREACHABILITY, CONDITIONAL -- measured, not argued. "
                "`display_tolerance` has exactly one consumer: the residual "
                "warning, whose predicate is `abs(net_duration_residual) >= tol`. "
                "The residual is exactly 0.0 for every input by construction, so "
                "the predicate is `0.0 >= tol` -- FALSE for every positive tol. "
                "Mutating 0.01 to 1.6 therefore "
                "leaves the predicate False in both programs on every reachable "
                "input, and the two mutants are the same program. EXECUTED: the "
                "mutant runs 31/31 in the new file, 0 failures. The caveat is the "
                "same scale condition D-059 measured (O-56): float round-trip "
                "noise in the notional multiplication can reach 9.766e-04 on a "
                "$1e12 notional, which is 9.8% of 0.01 -- so a large enough "
                "notional WOULD make the shipped warning fire and the mutant not. "
                "At the notionals the tests and the live check use ($1e6) the "
                "margin is ~10x and the exemption holds. Recorded as O-56, and "
                "this is the SECOND increment where the same float-noise margin "
                "justifies the same exemption -- which is evidence the condition "
                "is economic rather than a one-off."
            ),
        ),
        # -- M9: the honesty control ---------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the direction is built by string concatenation (CONTROL)",
            path=YIELD_CURVE,
            old=_M9_CONTROL_OLD,
            new=_M9_CONTROL_NEW,
            intent=(
                "Semantically IDENTICAL to the shipped code. SURVIVAL IS REQUIRED: "
                "if the sweep reports this killed it cannot justify its own kills."
            ),
            expect_killed=False,
            inert_proof=(
                "HONESTY CONTROL. `'longer_' + 'tips_duration'` and "
                "`'longer_tips_duration'` are the same string, so this mutation "
                "cannot change any observable. Its survival is a requirement, not "
                "a finding -- D-051's first draft lacked one and reported a false "
                "56/56, and D-059's control is what exposed a DEAD TEST inflating "
                "its first run to a false 31/31."
            ),
        ),
    ]


#: Mutations expected to survive, each of which MUST have an entry in
#: ``_INERT_PROOFS``. A name here without a proof makes the sweep exit 2.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M2.1 the ratio is published as the notional ratio (same number)",
        "M8.3 the display tolerance accessor reads the ratio ceiling",
        "M9.1 the direction is built by string concatenation (CONTROL)",
    }
)

#: The argument for each exception above. The harness refuses to certify a
#: survivor whose excuse is a label rather than a reason (O-42, built by D-056).
_INERT_PROOFS: dict[str, str] = {
    mt.name: mt.inert_proof for mt in build_mutations() if mt.inert_proof
}


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` string appearing twice silently rewrites the wrong site and the sweep
    then reports a surviving test -- a conclusion about code nobody mutated. An
    ``old`` appearing zero times means the target has drifted.

    **The ambiguity risk here is severe and specific.** D-059's
    ``CurveTradeConstructor`` and this increment's
    ``BreakevenTradeConstructor`` sit in the SAME FILE and share real text:
    ``_M4_FLOOR``/``_M4_CEILING`` are byte-identical to D-059's ``M4_FLOOR``/
    ``M4_CEILING`` anchors, and ``_M4_BAND`` is nearly identical. D-051 was
    broken by exactly this -- a sibling class with copied validator bodies made
    four targets ambiguous with no edit to the sweep file. Every anchor here is
    therefore extended past the shared prefix into text unique to this contract,
    and this gate is what proves that worked.
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
                "tests/models/test_breakeven_trade.py",
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
            "tests/models/test_breakeven_trade.py",
            "tests/models/test_curve_trade.py",
            "tests/models/test_yield_curve.py",
            "tests/test_infrastructure.py",
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

    Without this a killed sweep leaves mutated source on disk -- D-057's first
    run was stopped by a ``SIGTERM`` that bypassed the ``finally`` and had to be
    repaired by hand.
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

    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: construct_breakeven_trade (Module 15.2, D-060)")
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

    control_name = "M9.1 the direction is built by string concatenation (CONTROL)"
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
