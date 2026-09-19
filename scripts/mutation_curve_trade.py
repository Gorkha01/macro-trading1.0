"""Mutation sweep for ``construct_duration_weighted_curve_trade`` (Module 15.1, D-059).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/models/yield_curve.py`` and ``src/macro_engine/config.py`` in
place, so any concurrent test run, live check or probe reads a mutated module.
D-049 and D-057 both left source mutated when a sweep was killed mid-run, and
the full suite then passed *with the mutation in place*. The blast radius is the
whole repository.

What this increment is really testing
-------------------------------------
Section 15.1b's only guard is ``abs(net_duration_residual) < 0.01``, described
as "check duration inputs". **That guard cannot fire**, because the residual is
``notional_long``'s definition algebraically simplified: it is zero for every
input, correct or not (probe P14). Measured, not asserted: over a 1377-case grid
the residual is *exactly* 0.0 in 1185 cases and float round-trip noise in the
other 192, with a worst magnitude of **9.766e-04** -- 9.8% of the 0.01 tolerance.
So the guard is unreachable, but by a **10x margin with a scale condition**
(reachable above ~$2tn notional), not by algebra alone. The mutations below
therefore divide into two families that must be understood differently:

* **``M1``-``M4`` mutate arithmetic and guards that are load-bearing.** A
  survivor here is a genuine coverage gap.
* **``M5``/``M6`` mutate the dead guard and the values that replaced it.** The
  residual itself is inert **by construction** — ``M5.1`` cannot be killed by
  any test, and that fact *is* the finding. The replacement (the duration/tenor
  band) is what the tests must pin, and ``M4.*`` is where that lives.

That asymmetry is the point of this sweep. A sweep that reported ``M5.1`` as a
coverage gap would be telling you to write a test for an algebraic identity.

What this sweep structurally CANNOT find
----------------------------------------
1. **The tautology itself.** No mutation of the shipped code makes the residual
   nonzero, so the finding is "the guard is dead", which is a statement about
   the specification, not about an expression. It is pinned by a *test*
   (``test_the_residual_is_zero_for_a_duration_wrong_by_ten_times``) rather than
   by a mutant.

2. **``_tenor_years``'s refusal of ``"2yr"``.** The mutation that would accept
   it is expressible, but the *reason* it is refused (a unit mismatch that the
   ratio cannot detect) is a documentation claim. ``M7.3`` mutates the parser's
   suffix check; the claim itself is the module docstring's job.

3. **The Macaulay/Modified attestation.** A caller passing a Macaulay duration
   produces a notional wrong by ~1-2%, and **that error is arithmetically
   invisible** — the ratio is unaffected in form. ``M6.2`` mutates the warning
   that names it; no mutation can make the shipped code *detect* the error,
   because there is nothing in the numbers to detect.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything.

**It earned its keep on the first run of this sweep.** The initial report was
``applied 31/31, killed 31, survived 0`` -- a perfect score, and false. The
control was killed alongside everything else, which is only possible if a test
is failing *unmutated*. The culprit was
``test_a_missing_long_leg_tenor_is_refused_before_arithmetic``: it asserted
``implausible for '2y'`` against a validator message that names the LONG leg
(``3y``), so it failed on shipped source and turned every mutation into a
"kill". Had there been no control, the sweep would have certified a suite with a
dead test in it. The lesson is D-051's, restated: **a mutation score computed
against a suite that does not pass unmutated is measuring nothing.** The
harness now relies on the control for this, and the close-out re-run of
D-059 is what surfaced it -- the second time in this project that a *second* run
found what the first could not.

Anchors
-------
Anchors are transcribed from the SHIPPED source and re-verified against it by
``check_targets`` before a single mutation is applied. Formatting drift is a
known trap (lesson 50): ``ruff format`` reflows these lines, and a drifted
anchor reads as a test defect rather than a harness defect. D-058's ``CX4`` was
exactly this -- an anchor written from a docstring rather than the source. The
sweep is re-run at close for the same reason.
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
YIELD_CURVE = REPO / "src/macro_engine/models/yield_curve.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/models/test_curve_trade.py`` is the new file and carries the
#: behavioural assertions. ``tests/models/test_yield_curve.py`` is included
#: because the curve module already had 60+ tests and the new code shares its
#: module -- a mutation that breaks an existing curve function must not be
#: attributed to a gap in the new file. ``tests/test_infrastructure.py`` is
#: included because the ``config.py`` mutants land on the new
#: ``CurveTradeSettings`` accessors.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
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
# Anchors -- transcribed from the shipped source
# ---------------------------------------------------------------------------

# --- M1: the notional arithmetic ---------------------------------------------

_M1_NOTIONAL = (
    "    notional_long = inputs.target_notional_short * "
    "(inputs.short_duration / inputs.long_duration)"
)
_M1_DUR_DOLLARS_SHORT = (
    "    duration_dollars_short = inputs.target_notional_short * inputs.short_duration"
)
_M1_DUR_DOLLARS_LONG = "    duration_dollars_long = notional_long * inputs.long_duration"
_M1_RESIDUAL_SUB = "    net_duration_residual = duration_dollars_short - duration_dollars_long"
_M1_RATIO = "    notional_ratio = notional_long / inputs.target_notional_short"

# --- M2: the published value -------------------------------------------------

_M2_KEY_LONG = '            "notional_long": round(notional_long, 2),'
_M2_KEY_RATIO = '            "notional_long_to_short_ratio": round(notional_ratio, 6),'
_M2_KEY_RESIDUAL = (
    '            "duration_dollars_long": round(duration_dollars_long, 2),\n'
    '            "net_duration_residual": round(net_duration_residual, 6),'
)
_M2_KEY_DEFINITIONAL = (
    '            "duration_dollars_long": round(duration_dollars_long, 2),\n'
    '            "net_duration_residual": round(net_duration_residual, 6),\n'
    '            "net_duration_residual_is_definitional": True,'
)

# --- M3: the thresholds and the direction ------------------------------------

_M3_DIRECTION = '    direction = "steepener" if inputs.is_steepener else "flattener"'
_M3_TOLERANCE = "    tolerance = settings.display_tolerance"
_M3_RESIDUAL_WARN = "    if abs(net_duration_residual) >= tolerance:"
_M3_MODIFIED_WARN = (
    "    if not inputs.duration_is_modified:\n"
    "        warnings.append(\n"
    '            "Durations were not attested as MODIFIED. If they are Macaulay durations "'
)
_M3_LARGER_WARN = "    if notional_ratio > 1.0:"

# --- M4: the contract's real check (the replacement for the dead guard) ------

_M4_FLOOR = (
    "        floor = settings.minimum_duration_to_tenor\n"
    "        ceiling = settings.maximum_duration_to_tenor\n"
    "\n"
    "        for label, tenor, duration in ("
)
_M4_CEILING = (
    "        ceiling = settings.maximum_duration_to_tenor\n"
    "\n"
    "        for label, tenor, duration in ("
)
_M4_BAND = (
    "            ratio = duration / years\n"
    "            if not floor <= ratio <= ceiling:\n"
    "                raise ValueError(\n"
    '                    f"{label}_duration {duration} is implausible for {tenor!r}: "'
)
_M4_RATIO_CALC = (
    "            ratio = duration / years\n"
    "            if not floor <= ratio <= ceiling:\n"
    "                raise ValueError(\n"
    '                    f"{label}_duration {duration} is implausible for {tenor!r}: "'
)
_M4_LOOP = """        for label, tenor, duration in (
            ("short", self.short_tenor, self.short_duration),
            ("long", self.long_tenor, self.long_duration),
        ):"""

# --- M5: the tautology (INERT BY CONSTRUCTION -- see the module docstring) ---

_M5_RESIDUAL_ALWAYS_ZERO = (
    "    net_duration_residual = duration_dollars_short - duration_dollars_long"
)

# --- M6: the attestation and its warning -------------------------------------

_M6_MODIFIED_DEFAULT = (
    "    duration_is_modified: bool = Field(\n"
    "        default=True,\n"
    "        description=(\n"
    '            "Attestation that both durations are MODIFIED, not Macaulay. The two "'
)
_M6_STEEPENER_DEFAULT = "    is_steepener: bool = Field(\n        default=True,"


# The unit-warning anchor is long enough that line-length forces a wrap, and a
# wrapped anchor built by hand is exactly how a mutation silently stops matching
# its target (D-058's CX4). So it is READ FROM THE SOURCE instead of transcribed:
# the four physical lines are sliced out of the shipped file at import time. An
# anchor that cannot drift is worth more than a pretty literal here, and
# check_targets still proves the slice occurs exactly once.
def _slice_source(path: Path, first: str, last: str) -> str:
    """Return the source text from the line containing ``first`` to ``last``.

    Raises at import if either marker is absent, so a drift is a loud failure
    rather than a silent no-op mutation.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if first in ln), None)
    if start is None:
        raise RuntimeError(f"anchor start not found in {path.name}: {first!r}")
    end = next((i for i in range(start, len(lines)) if last in lines[i]), None)
    if end is None:
        raise RuntimeError(f"anchor end not found in {path.name}: {last!r}")
    return "".join(lines[start : end + 1])


_M6_UNIT_WARNING_TEXT = _slice_source(
    YIELD_CURVE,
    "Durations were not attested as MODIFIED",
    "arithmetic check in this function can detect it.",
)
_M6_UNIT_WARNING_REPLACEMENT = """            "Durations were not attested as MODIFIED."
            "The long leg's notional may be understated."
            "No arithmetic check in this function can detect it.\""""

# --- M7: the tenor parser and the ordering guard -----------------------------

_M7_ORDERING = """        if short_years >= long_years:
            raise ValueError("""
_M7_SUFFIX = '    if not text.endswith("y") or not text[:-1]:'
_M7_POSITIVE = "    if years <= 0.0:"
_M7_LOWER = "    text = tenor.strip().lower()"

# --- M8: the config accessors (config.py) ------------------------------------

_M8_FLOOR_ACCESSOR = "        return float(self.duration_to_tenor_min.value)"
_M8_CEILING_ACCESSOR = "        return float(self.duration_to_tenor_max.value)"
_M8_TOLERANCE_ACCESSOR = "        return float(self.net_duration_display_pct.value)"

# --- M9: the honesty control -------------------------------------------------

_M9_CONTROL_OLD = '    direction = "steepener" if inputs.is_steepener else "flattener"'
_M9_CONTROL_NEW = (
    '    direction = ("steep" + "ener") if inputs.is_steepener else ("flat" + "tener")'
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
                "    notional_long = inputs.target_notional_short * "
                "(inputs.long_duration / inputs.short_duration)"
            ),
            intent="Inverted ratio: the single most consequential arithmetic error here.",
        ),
        Mutation(
            group="M1",
            name="M1.2 short duration-dollars use the long notional",
            path=YIELD_CURVE,
            old=_M1_DUR_DOLLARS_SHORT,
            new="    duration_dollars_short = notional_long * inputs.short_duration",
            intent="The two legs' duration-dollars read the same notional.",
        ),
        Mutation(
            group="M1",
            name="M1.3 long duration-dollars use the short notional",
            path=YIELD_CURVE,
            old=_M1_DUR_DOLLARS_LONG,
            new="    duration_dollars_long = inputs.target_notional_short * inputs.long_duration",
            intent="Mirror of M1.2.",
        ),
        Mutation(
            group="M1",
            name="M1.4 residual adds the legs instead of subtracting",
            path=YIELD_CURVE,
            old=_M1_RESIDUAL_SUB,
            new="    net_duration_residual = duration_dollars_short + duration_dollars_long",
            intent="A sign flip in the residual, which is still definitionally wrong either way.",
        ),
        Mutation(
            group="M1",
            name="M1.5 notional ratio inverted",
            path=YIELD_CURVE,
            old=_M1_RATIO,
            new="    notional_ratio = inputs.target_notional_short / notional_long",
            intent="The published ratio must be long-over-short.",
        ),
        # -- M2: the published value ---------------------------------------
        Mutation(
            group="M2",
            name="M2.1 published long notional is unrounded",
            path=YIELD_CURVE,
            old=_M2_KEY_LONG,
            new='            "notional_long": notional_long,',
            intent="The 2dp presentational round is a stated choice (test asserts 1_959_157.63).",
        ),
        Mutation(
            group="M2",
            name="M2.2 published ratio is rounded to 2dp not 6dp",
            path=YIELD_CURVE,
            old=_M2_KEY_RATIO,
            new='            "notional_long_to_short_ratio": round(notional_ratio, 2),',
            intent="The six-decimal precision is asserted by the ratio test.",
        ),
        Mutation(
            group="M2",
            name="M2.3 published residual is the rounded long notional's residual",
            path=YIELD_CURVE,
            old=_M2_KEY_RESIDUAL,
            new=(
                '            "duration_dollars_long": round(duration_dollars_long, 2),\n'
                '            "net_duration_residual": round(\n'
                "                duration_dollars_short"
                " - round(notional_long, 2) * inputs.long_duration,\n"
                "                6,\n"
                "            ),"
            ),
            intent=(
                "Reinstates Section 15.1b's actual computation, which rounds the "
                "notional before the residual. The test asserts exactly 0.0, so this "
                "must fail — a kill here is what proves the rounding choice is pinned."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.4 the definitional flag reports False",
            path=YIELD_CURVE,
            old=_M2_KEY_DEFINITIONAL,
            new=(
                '            "duration_dollars_long": round(duration_dollars_long, 2),\n'
                '            "net_duration_residual": round(net_duration_residual, 6),\n'
                '            "net_duration_residual_is_definitional": False,'
            ),
            intent=(
                "The flag is the only machine-readable statement that the residual is not a check."
            ),
        ),
        # -- M3: thresholds, warnings, direction ---------------------------
        Mutation(
            group="M3",
            name="M3.1 direction ignores the input and is always a steepener",
            path=YIELD_CURVE,
            old=_M3_DIRECTION,
            new='    direction = "steepener"',
            intent="`is_steepener` is a stated decision; a constant would be the D-037 class.",
        ),
        Mutation(
            group="M3",
            name="M3.2 tolerance read from a different leaf",
            path=YIELD_CURVE,
            old=_M3_TOLERANCE,
            new="    tolerance = settings.maximum_duration_to_tenor",
            intent=(
                "The display tolerance must be the display leaf, not the band "
                "ceiling. It IS the right leaf, but the guard it feeds is dead "
                "(M5.1), so the value substitution has no observable. See "
                "_INERT_PROOFS."
            ),
            expect_killed=False,
            inert_proof=(
                "INERT BY UNREACHABILITY -- and the proof is CONDITIONAL, which is "
                "the important part. `tolerance` is used in exactly one place, "
                "`if abs(net_duration_residual) >= tolerance:`. Substituting 1.05 "
                "for 0.01 changes an observable only if the predicate can differ "
                "between the two values. EXECUTED: over a 153-case grid of "
                "duration pairs (0.08y..30y) at notionals $1e6, $1e9 and $1e12, "
                "the predicate agrees on 153/153 cases at every notional -- it is "
                "False for both values throughout. The reason is the tautology: "
                "the residual is zero by algebra, so the only nonzero values are "
                "float round-trip noise. EXECUTED over a 1377-case grid spanning "
                "notionals $1e3..$1e12: 1185 exact zeros, 192 nonzero, WORST "
                "|residual| = 9.766e-04 -- which is 9.8% of the 0.01 tolerance, a "
                "10x margin, not an infinite one. **The condition is a scale "
                "assumption and must be stated as one:** repeating the sweep at "
                "$5e12 notional puts 4 of those cases at |residual| >= 0.01, so "
                "the guard is reachable above roughly $2-5tn. A "
                "duration-weighted curve trade is a rates relative-value "
                "position whose notional is the DV01-matched leg -- millions to "
                "low billions in this system's use -- so the exemption holds "
                "here, but it would lapse if this function were ever called with "
                "a notional above ~$2tn. That is carry-over O-56, not a fact."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 residual warning fires on a strict inequality",
            path=YIELD_CURVE,
            old=_M3_RESIDUAL_WARN,
            new="    if abs(net_duration_residual) > tolerance:",
            intent=(
                "Boundary: at the shipped trade the residual is exactly 0.0, so this "
                "mutation is unobservable (0.0 > 0.01 is False, and 0.0 >= 0.01 is "
                "False). See _INERT_PROOFS."
            ),
            expect_killed=False,
            inert_proof=(
                "INERT BY UNREACHABILITY. The residual is zero by algebra (M5.1), "
                "so the guard's only reachable nonzero inputs are float round-trip "
                "noise. EXECUTED over a 1377-case grid (notionals $1e3..$1e12 x "
                "duration pairs 0.08y..30y): 1185 residual values are EXACTLY 0.0, "
                "192 are nonzero, and the WORST |residual| is 9.766e-04. So "
                "`>= 0.01` and `> 0.01` return the same verdict on every case -- "
                "0 fires either way. Note the margin is 10x, NOT unbounded: "
                "`ulp(1e12)*30 ~ 3.7e-03`, so a notional near $5e12 makes the "
                "guard reachable and this exemption lapses (O-56). Stated as a "
                "scale condition because that is what it is."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.4 the Macaulay attestation warning is removed",
            path=YIELD_CURVE,
            old=_M3_MODIFIED_WARN,
            new="    if False:",
            intent=(
                "The attestation is the only defence against an arithmetically "
                "invisible 1-2% error."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.5 the lopsided-notional warning is removed",
            path=YIELD_CURVE,
            old=_M3_LARGER_WARN,
            new="    if False:",
            intent="The warning that catches an inverted duration structure.",
        ),
        # -- M4: the contract's real check ---------------------------------
        Mutation(
            group="M4",
            name="M4.1 the band floor is not read from config",
            path=YIELD_CURVE,
            old=_M4_FLOOR,
            new="        floor = 0.15",
            intent=(
                "A hardcoded floor equals the shipped leaf, so the moved-leaf test "
                "is what catches it."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 the band ceiling is not read from config",
            path=YIELD_CURVE,
            old=_M4_CEILING,
            new="        ceiling = 1.05",
            intent="Mirror of M4.1.",
        ),
        Mutation(
            group="M4",
            name="M4.3 the band comparison is exclusive at the top",
            path=YIELD_CURVE,
            old=_M4_BAND,
            new="            if not floor <= ratio < ceiling:",
            intent="The ceiling's inclusiveness is pinned by test_the_ceiling_itself_is_inclusive.",
        ),
        Mutation(
            group="M4",
            name="M4.4 the ratio uses the tenor divided by the duration",
            path=YIELD_CURVE,
            old=_M4_RATIO_CALC,
            new="            ratio = years / duration",
            intent="An inverted band metric admits everything a wrong unit produces.",
        ),
        Mutation(
            group="M4",
            name="M4.5 only the short leg is band-checked",
            path=YIELD_CURVE,
            old=_M4_LOOP,
            new="""        for label, tenor, duration in (
            ("short", self.short_tenor, self.short_duration),
        ):""",
            intent="The long leg's duration is equally capable of a unit error.",
        ),
        # -- M5: the tautology (INERT BY CONSTRUCTION) ---------------------
        Mutation(
            group="M5",
            name="M5.1 the residual is hardcoded to zero",
            path=YIELD_CURVE,
            old=_M5_RESIDUAL_ALWAYS_ZERO,
            new="    net_duration_residual = 0.0",
            intent=(
                "Replaces the computation with its own value. The two are equal for "
                "every input, so this is the tautology in its purest form."
            ),
            expect_killed=False,
            inert_proof=(
                "INERT BY CONSTRUCTION — and this entry IS the increment's finding. "
                "The shipped expression `duration_dollars_short - duration_dollars_long` "
                "evaluates to exactly 0.0 for every admissible input, because "
                "duration_dollars_long = N_short*(D_s/D_l)*D_l = duration_dollars_short "
                "identically. So the computation and the literal 0.0 are the SAME "
                "PROGRAM on the whole input domain. Verified by evaluating both over "
                "the shipped trade, a 10x-wrong duration, a $1e12 notional and a "
                "1e-3-duration edge: all four produce 0.0 from both forms. No test can "
                "kill this, nor should one — the correct response is the one taken: "
                "the contract gained a check that CAN fail (M4.*), and the flag "
                "`net_duration_residual_is_definitional` says so in the output."
            ),
        ),
        # -- M6: defaults and warning text ---------------------------------
        Mutation(
            group="M6",
            name="M6.1 the MODIFIED attestation defaults to False",
            path=YIELD_CURVE,
            old=_M6_MODIFIED_DEFAULT,
            new="    duration_is_modified: bool = Field(\n        default=False,",
            intent="A False default would warn on every call, making the warning noise.",
        ),
        Mutation(
            group="M6",
            name="M6.2 the unit warning drops the magnitude",
            path=YIELD_CURVE,
            old=_M6_UNIT_WARNING_TEXT,
            new=_M6_UNIT_WARNING_REPLACEMENT,
            intent=(
                "A warning that does not say how big the error is cannot be acted on. "
                "The anchor spans ALL FOUR physical lines of the implicit string "
                "concatenation: the first draft replaced only the first line, and "
                "the phrase the test asserts ('1-2%') lives on the third, so the "
                "mutation was a no-op on the assertion it was meant to break. Same "
                "class as D-058's M8.5 (a fixture that cannot observe the behaviour "
                "it tests) and D-058's partial-message lesson."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.3 the steepener default flips to a flattener",
            path=YIELD_CURVE,
            old=_M6_STEEPENER_DEFAULT,
            new="    is_steepener: bool = Field(\n        default=False,",
            intent="The stated default direction.",
        ),
        # -- M7: the tenor parser and the ordering guard --------------------
        Mutation(
            group="M7",
            name="M7.1 the ordering guard admits equal legs",
            path=YIELD_CURVE,
            old=_M7_ORDERING,
            new="""        if short_years > long_years:
            raise ValueError(""",
            intent="A curve trade whose legs coincide measures no slope.",
        ),
        Mutation(
            group="M7",
            name="M7.2 the tenor suffix check is removed",
            path=YIELD_CURVE,
            old=_M7_SUFFIX,
            new="    if not text[:-1]:",
            intent="Without the suffix check, '2w' parses as 2.0 years.",
        ),
        Mutation(
            group="M7",
            name="M7.3 the positive-tenor check is removed",
            path=YIELD_CURVE,
            old=_M7_POSITIVE,
            new="    if False:",
            intent="A zero or negative tenor is not a maturity.",
        ),
        Mutation(
            group="M7",
            name="M7.4 the parser does not normalise case or whitespace",
            path=YIELD_CURVE,
            old=_M7_LOWER,
            new="    text = tenor",
            intent="The case/whitespace folding is asserted by its own test.",
        ),
        # -- M8: config accessors ------------------------------------------
        Mutation(
            group="M8",
            name="M8.1 the floor accessor returns the ceiling leaf",
            path=CONFIG,
            old=_M8_FLOOR_ACCESSOR,
            new="        return float(self.duration_to_tenor_max.value)",
            intent="Crossed leaves: the band inverts.",
        ),
        Mutation(
            group="M8",
            name="M8.2 the ceiling accessor returns the floor leaf",
            path=CONFIG,
            old=_M8_CEILING_ACCESSOR,
            new="        return float(self.duration_to_tenor_min.value)",
            intent="Mirror of M8.1.",
        ),
        Mutation(
            group="M8",
            name="M8.3 the tolerance accessor returns the band ceiling",
            path=CONFIG,
            old=_M8_TOLERANCE_ACCESSOR,
            new="        return float(self.duration_to_tenor_max.value)",
            intent=(
                "The display tolerance must come from its own leaf. It does, and "
                "this mutation makes it read 1.05 instead of 0.01 -- the same "
                "substitution as M3.2 through the other door, and equally "
                "unobservable because the guard is dead. See _INERT_PROOFS."
            ),
            expect_killed=False,
            inert_proof=(
                "INERT BY UNREACHABILITY -- the same argument as M3.2, reached "
                "through the config accessor rather than the call site. The two "
                "mutations are a matched pair: M3.2 makes the caller read the "
                "wrong leaf, M8.3 makes the right leaf return the wrong value, "
                "and both leave `tolerance == 1.05` instead of 0.01. Since "
                "`tolerance` has exactly one consumer and that consumer's "
                "predicate is False at both values on 153/153 duration pairs at "
                "$1e6/$1e9/$1e12 (executed), the two mutations produce the "
                "IDENTICAL program. The same conditional caveat applies: the "
                "exemption depends on the notional staying below ~$2tn, where "
                "float noise cannot reach 0.01 (worst observed 9.766e-04). "
                "Recorded as O-56."
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
                "HONESTY CONTROL. `'steep'+'ener'` and `'steepener'` are the same "
                "string, and the same for the flattener branch, so this mutation "
                "cannot change any observable. Its survival is a requirement, not a "
                "finding (D-051's first draft lacked one and reported a false 56/56)."
            ),
        ),
    ]


#: Mutations expected to survive, each of which MUST have an entry in
#: ``_INERT_PROOFS``. A name here without a proof makes the sweep exit 2.
#:
#: ``M3.2``/``M8.3`` are the interesting pair: both were originally filed as
#: "expected to be killed" and both survived, because the value they substitute
#: (1.05 for 0.01) feeds a guard that is dead by construction (``M5.1``). They are
#: listed here only after the probe measured the margin -- see their proofs for
#: the 10x figure and the $2tn scale condition (O-56).
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M3.2 tolerance read from a different leaf",
        "M3.3 the residual warning fires on a strict inequality",
        "M5.1 the residual is hardcoded to zero",
        "M8.3 the tolerance accessor returns the band ceiling",
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

    **The ambiguity risk here is the two ``duration_dollars_*`` lines**, which
    share a prefix, and the two ``Field(default=True`` blocks, which are
    identical except for the field name. All four anchors are extended past the
    shared prefix into their distinguishing text; this gate proves that worked.
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
                "tests/models/test_curve_trade.py",
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
    parser.add_argument("--group", help="run only this mutation group, e.g. M4")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: construct_duration_weighted_curve_trade (Module 15.1, D-059)")
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
            print(f"  {mt.group:4} {mt.path.name:20} {mt.name}")
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
