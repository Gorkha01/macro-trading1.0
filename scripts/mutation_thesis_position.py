"""Mutation sweep for ``translate_thesis_to_position`` (Module 17.4, Section 9.3, D-072).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/portfolio/risk_budget.py`` in place, so any concurrent test
run, live check or probe reads a mutated module. D-047's Postscript 2 records a
contaminated reading produced exactly that way, and D-049 left the source
mutated when its sweep was killed mid-run -- the full suite then passed *with the
mutation in place*. The blast radius is the whole repository.

Why the mutations are named after defects
-----------------------------------------
Every predecessor on this module named its mutations after the defect each one
repairs -- ``evaluate_drawdown_rules`` (D-054), ``check_rebalancing_drift``
(D-055), ``volatility_target_scaling`` (D-056), ``apply_fractional_kelly``
(D-057) -- and this sweep is the strictest of the five, because D-072's defect
set is qualitatively different: **three of its five defects were wrong REASONS
rather than wrong numbers**, and no numeric assertion can catch a wrong reason.
So the groups here are the **repairs**, and a survivor names a repair no test
pins. The grouping, not the count, is what tells you what is missing (D-031).

The three defect classes this sweep is built around
---------------------------------------------------
1. **A capital fraction multiplied by a risk fraction.** ``M3.*``. Measured on
   the shipped config the draft returned **0.018** for a 12% risk allocation
   against a 15% position cap, where the answer is 0.12 -- a **6.7x**
   understatement that is invisible because 0.018 is a plausible position size.
2. **A right outcome with a wrong reason.** ``M2.*``. ``"HY credit spread"`` is
   not ``"NONE"``, so the thesis calls itself a trade; refused as
   ``refused_scenarios_uncalibrated`` it reads "calibrate your probabilities"
   when the truth is "the desk cannot execute this". The outcome alone was
   already right, so only the *reason* can be asserted.
3. **A fact that overwrites a different fact.** ``M4.*``. Assigning
   ``binding = "missing_risk_budget"`` on the no-budget path **discarded** the
   clipping, so a thesis sized at the cap reported "no budget" and a reader
   could not tell whether any limit had bound.

What this sweep structurally CANNOT find
----------------------------------------
**The removed gate is not mutation-testable, and that is the increment's central
structural fact.** Gate 3's emptiness branch and the ``refused_no_scenarios``
``Literal`` member were **deleted**, not fixed, so there is no expression left to
mutate. ``M6.1`` therefore attacks the two boundaries where the deletion is
*observable*: the ``Literal`` no longer containing the member, and the
enumeration that proves no input can reach it. If ``M6.*`` ever reports
survivors, the deletion has become a claim rather than a fact.

**"The risk budget is not applied" is a NEGATIVE and no mutation can express
it.** The shipped gate 4 does *nothing* to the number. There is no statement to
break. ``M3.1``/``M3.2`` reintroduce the arithmetic in its two plausible forms
and must be killed; beyond that, the assertion lives in
``test_the_risk_budget_does_not_scale_the_notional`` and in the
``notional_fraction_after_constraints`` invariant, which is an *invariant* proof
rather than an unreachability proof (O-55's distinction).

**Section 9.3's sign-off gate is a contract term, not a computation.**
``M7.1`` mutates the constant's own text; ``M7.2`` removes it from one warning
list. A future edit that deleted it from *every* path while leaving the field
would be caught by ``test_the_sign_off_gate_is_on_every_outcome`` -- which is why
that test iterates ``_every_outcome()`` rather than asserting on one path.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. This control is what D-051's first
draft lacked when it reported a false 56/56.

What the first run of THIS sweep got wrong
------------------------------------------
Recorded here rather than quietly fixed, because a harness defect and a test
defect produce the same signature and only the diagnosis separates them.
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
SRC = REPO / "src/macro_engine/portfolio/risk_budget.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/portfolio/test_thesis_position.py`` is the increment's own file and the
#: primary kill surface.
#:
#: ``tests/portfolio/test_risk_budget.py`` is included because this module's
#: ``__all__`` grew by six names in D-072 and that file asserts the exact set --
#: so a silently dropped re-export dies here rather than at an import site in a
#: downstream consumer.
#:
#: ``tests/portfolio/test_fractional_kelly.py`` is included because gate 3 *calls*
#: ``apply_fractional_kelly``, and ``M5.1`` mutates the value that call is given
#: (``thesis.scenario_distribution``). A mutant that changed which scenarios are
#: sized must be caught by this function's file or by Kelly's, and including both
#: makes the kill attributable rather than accidental.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
    "tests/portfolio/test_thesis_position.py",
    "tests/portfolio/test_risk_budget.py",
    "tests/portfolio/test_fractional_kelly.py",
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
# **Ambiguity is the live hazard, and it is worse here than for any predecessor.**
# Five functions now share ``risk_budget.py``. ``compute_confidence(`` appears
# five times; ``round(..., 6)`` in the three earlier functions and
# ``round(..., 10)`` in this one; ``min(`` in ``check_rebalancing_drift``,
# ``apply_fractional_kelly`` and ``volatility_target_scaling``;
# ``_refuse(`` five times inside this function alone. Every anchor below is
# therefore pinned to a *distinctive* multi-line statement -- usually the
# published-value key or the full refusal reason -- and ``check_targets`` is what
# proves the pinning worked rather than assuming it.

# --- M1: the universe check (defect 2 -- right outcome, wrong reason) --------

_M1_UNIVERSE_GUARD = """    if not universe.permits(idea.instrument):
        return _refuse(
            thesis=thesis,
            outcome="refused_not_a_trade","""
_M1_UNIVERSE_ALLOW = """    if not universe.permits(idea.instrument):
        return _refuse(
            thesis=thesis,
            outcome="refused_scenarios_uncalibrated","""

_M1_SENTINEL_CHECK = (
    "    if not idea.is_trade or idea.instrument == ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT:"
)

# --- M2: the refusal reasons (defect 3 -- the reason IS the contract) --------

_M2_UNIVERSE_REASON = """                f"{idea.instrument!r} is not in the production execution "
                f"universe (Section 22.12): it matches no permitted category "
                f"(rates, FX, broad equity indices) and/or matches an excluded "
                f"one. A trade idea whose instrument the desk cannot put on "
                f"cannot be sized — the correct result is the analytical read "
                f"the universe already gave, not a notional.\""""

_M2_UNIVERSE_REASON_NEW = """                f"{idea.instrument!r} could not be sized because its scenario "
                f"probabilities are not calibrated (Section 25). Calibrate the "
                f"distribution and re-run.\""""

_M2_NOTRADE_REASON = """                "The thesis is a NO-TRADE (instrument is the no-trade sentinel): "
                "Q6, Q7 or Q8 stood the sentence down, and Section 16.3 makes "
                "that a first-class outcome. There is nothing to size, and "
                "sizing it would manufacture the position the stand-down refused.\""""

_M2_NOTRADE_REASON_NEW = """                "The thesis carries no scenario branches, so there is no "
                "distribution for Kelly to maximise over.\""""

# --- M3: the unit error (defect 1 -- THE central repair) --------------------

_M3_BINDING_ASSIGN = """    binding: PositionBinding = (
        "position_limit" if kelly_outcome == "clipped_by_position_limit" else "kelly"
    )"""

_M3_BINDING_MULTIPLY = """    binding: PositionBinding = (
        "position_limit" if kelly_outcome == "clipped_by_position_limit" else "kelly"
    )
    fraction = min(1.0, permitted) * fraction"""

_M3_PERMITTED_INIT = "    permitted = 1.0"
_M3_PERMITTED_MULTIPLY = """    permitted = 1.0
    fraction = min(1.0, inputs.risk_budget_target.target_risk_contribution_pct) * fraction"""

_M3_FINAL_FRACTION = "    final_fraction = fraction"
_M3_FINAL_FRACTION_SCALED = "    final_fraction = fraction * permitted"

# --- M4: the missing budget must not overwrite the binding (defect 4) -------

_M4_BINDING_NAMES = """    binding: PositionBinding = (
        "position_limit" if kelly_outcome == "clipped_by_position_limit" else "kelly"
    )"""

_M4_RISK_BUDGET_MISSING = "    risk_budget_missing = target is None"
_M4_RISK_BUDGET_MISSING_NEW = """    risk_budget_missing = target is None
    binding = "none" if risk_budget_missing else binding  # type: ignore[assignment]"""

_M4_BUDGET_WARNING = """        budget_warnings.append(
            "No portfolio-level risk budget was supplied, so the Q12 check did "
            "NOT run: nothing verified that this position's risk fits the "
            "book's existing allocation. The size below is constrained only by "
            "the position cap — read this as 'unchecked', not as 'checked and "
            "clear'."
        )"""

_M4_BUDGET_WARNING_NEW = """        budget_warnings.append(
            "Ran with the position cap as the only constraint."
        )"""

# --- M5: which scenarios are sized, and the division by the divisor ---------

_M5_SCENARIOS = "            scenarios=list(thesis.scenario_distribution),"
_M5_SCENARIOS_NEW = """            scenarios=[
                s for s in thesis.scenario_distribution if s.payoff_estimate > 0.0
            ],"""

# --- M6: the removed gate (a DELETION, observable only at its boundaries) --

_M6_LITERAL = """PositionTranslationOutcome = Literal[
    "refused_not_a_trade",
    "refused_scenarios_uncalibrated",
    "refused_no_edge","""
_M6_LITERAL_READDED = """PositionTranslationOutcome = Literal[
    "refused_not_a_trade",
    "refused_scenarios_uncalibrated",
    "refused_no_scenarios",
    "refused_no_edge","""

# --- M7: the sign-off gate (Section 9.3's contract term) -------------------

_M7_CONSTANT = "PROPOSAL ONLY — this is not an order and not an instruction to trade. "
_M7_CONSTANT_WEAK = "A sizing suggestion from the macro reasoning engine. "
_M7_WARNING_FIRST = """    warnings = [
        SIGN_OFF_REQUIRED,
        *kelly.warnings,
        *budget_warnings,
    ]"""
_M7_WARNING_NONE = """    warnings = [
        *kelly.warnings,
        *budget_warnings,
    ]"""

# --- M8: the output invariants (refusals carry no size) --------------------


# The anchor is the WHOLE three-field guard, and it must stay in step with it:
# the sweep's first run found the guard was missing its third field, so the
# repair changed this text and `check_targets` correctly refused the next run
# with "target ABSENT" rather than mutating a site that no longer existed.
_M8_REFUSAL_SIZE_GUARD = """            if (
                self.fraction_of_capital != 0.0
                or self.requested_fraction_of_capital != 0.0
                or self.notional_fraction_after_constraints != 0.0
            ):"""
_M8_REFUSAL_SIZE_GUARD_NEW = """            if (
                self.fraction_of_capital != 0.0
                and self.requested_fraction_of_capital != 0.0
                and self.notional_fraction_after_constraints != 0.0
            ):"""


_M8_REFUSAL_BINDING_GUARD = """            if self.binding_constraint != "none":"""
_M8_REFUSAL_BINDING_GUARD_NEW = """            if False:"""

_M8_MONOTONE_GUARD = (
    "        if self.notional_fraction_after_constraints > self.fraction_of_capital + 1e-12:"
)

_M8_ZERO_BUDGET = """        if target_share <= 0.0:"""
_M8_ZERO_BUDGET_NEW = """        if target_share < 0.0:"""

# --- M10: the declared member set (the D-070 discipline, one type over) ----

# The set is asserted in TWO places now: the unit suite's reachability guard and
# the live check's section 7. Both must see a member added without a producer.
_M10_DECLARED_SET = """    "sized_by_kelly",
    "clipped_by_position_limit",
]"""
_M10_DECLARED_SET_DRIFTED = """    "sized_by_kelly",
    "clipped_by_position_limit",
    "sized_by_risk_budget",
]"""

# The two docstrings that make a COUNTING claim about the member set. They are
# mutated together because either one alone drifting is the defect: a reader who
# trusts the type docstring and a reader who trusts the function docstring must
# be told the same thing, and neither is checked by a type.
#
# The FIRST anchor is the sentence D-072 had to repair on the live check's first
# run: the type docstring said "nine members" for a `Literal` that had six, and
# had said nine since the draft, through a repair that removed three.
_M10_DOCSTRING_COUNT = """        "waiting". The six members are exhaustive over the refusal and sizing
        paths, and the ``Literal`` is what makes that checkable."""
_M10_DOCSTRING_COUNT_DRIFTED = """        "waiting". The nine members are exhaustive over the refusal and sizing
        paths, and the ``Literal`` is what makes that checkable."""

# The SECOND anchor is the *four*-gate sentence in the function's own gate list,
# which D-072 rewrote to four.
_M10_GATE_COUNT = "**four**, not five: a gate that"
_M10_GATE_COUNT_NEW = "**five**, not four: a gate that"


def build_mutations() -> list[Mutation]:
    """The catalogue, grouped by the defect each group repairs."""
    return [
        # -- M1: the universe check (defect 2) --------------------------------
        Mutation(
            group="M1",
            name="M1.1 the universe check refuses as a calibration problem",
            path=SRC,
            old=_M1_UNIVERSE_GUARD,
            new=_M1_UNIVERSE_ALLOW,
            intent=(
                "Defect 2: the right outcome with the WRONG REASON. This is the "
                "shipped state of the first draft -- an out-of-universe "
                "instrument refused as `refused_scenarios_uncalibrated`, which "
                "tells the reader to calibrate probabilities when the desk "
                "cannot execute the instrument at all. The outcome is unchanged, "
                "so only the interpretation can kill it."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 the universe check is removed entirely",
            path=SRC,
            old=_M1_UNIVERSE_GUARD,
            new="""    if False:
        return _refuse(
            thesis=thesis,
            outcome="refused_not_a_trade",""",
            intent=(
                "Defect 2, the omission: without the universe check an "
                "out-of-universe instrument falls through to the calibration "
                "gate and `refused_not_a_trade` is never produced for it."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.3 the analytical-only sentinel is not compared",
            path=SRC,
            old=_M1_SENTINEL_CHECK,
            new="    if not idea.is_trade:",
            intent=(
                "The second of gate 1's two checks. `is_trade` compares only "
                "against `NO_PRODUCTION_INSTRUMENT`, so removing the explicit "
                "sentinel comparison routes the analytical-only string to the "
                "universe check. **This mutant SURVIVED the sweep's first run**, "
                "because `ProductionUniverse.permits` is False for that string "
                "too and both checks reach the same outcome -- they differ only "
                "in REASON. The missing assertion was the sentinel branch's own "
                "phrase; see `test_an_analytical_only_instrument_is_refused_as_"
                "a_trade`. It is the increment's defect class in miniature: a "
                "right outcome with a wrong reason, surviving a suite that "
                "asserted the outcome."
            ),
        ),
        # -- M2: the refusal reasons (defect 3) -------------------------------
        Mutation(
            group="M2",
            name="M2.1 the out-of-universe reason blames calibration",
            path=SRC,
            old=_M2_UNIVERSE_REASON,
            new=_M2_UNIVERSE_REASON_NEW,
            intent=(
                "The reason is the contract. A reader's REPAIR is implied by the "
                "reason, so a reason naming the wrong cause sends them to fix "
                "the wrong thing -- which is defect 2 restated at the prose "
                "level, and is what `test_an_out_of_universe_instrument_is_"
                "refused_as_a_trade_not_as_a_data_gap` asserts."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the NO-TRADE reason is swapped for the removed gate's",
            path=SRC,
            old=_M2_NOTRADE_REASON,
            new=_M2_NOTRADE_REASON_NEW,
            intent=(
                "Section 16.3 makes NO TRADE first-class, so its reason must "
                "name the stand-down. This mutant pastes in the text of the gate "
                "D-072 deleted, which would be a claim about a check that no "
                "longer exists."
            ),
        ),
        # -- M3: the unit error (defect 1) ------------------------------------
        Mutation(
            group="M3",
            name="M3.1 the risk budget scales the notional (the 6.7x error)",
            path=SRC,
            old=_M3_PERMITTED_INIT,
            new=_M3_PERMITTED_MULTIPLY,
            intent=(
                "Defect 1, restored: `multiplier = min(1.0, risk_share)` "
                "multiplies a CAPITAL fraction by a RISK fraction. Measured on "
                "the shipped config: 0.018 where the answer is 0.12. This is the "
                "increment's central repair and must die."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2 the risk budget scales via permitted",
            path=SRC,
            old=_M3_FINAL_FRACTION,
            new=_M3_FINAL_FRACTION_SCALED,
            intent=(
                "Defect 1 by a different route: instead of a `min()` multiplier "
                "the budget is applied at the end. Same unit error, same 6.7x, "
                "different site -- which is exactly the shape a single-site fix "
                "would miss."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the binding constraint ignores the clip",
            path=SRC,
            old=_M3_BINDING_ASSIGN,
            new="""    binding: PositionBinding = (
        "kelly" if kelly_outcome == "clipped_by_position_limit" else "kelly"
    )""",
            intent=(
                "The binding names what produced the NUMBER. A constant `kelly` "
                "means a position sized at the cap reports that no limit bound, "
                "so a reader cannot tell a capped view from an uncapped one -- "
                "which is D-057's P5 arriving through the binding field."
            ),
        ),
        # -- M4: a fact overwriting a different fact (defect 4) ---------------
        Mutation(
            group="M4",
            name="M4.1 a missing budget overwrites the binding constraint",
            path=SRC,
            old=_M4_RISK_BUDGET_MISSING,
            new=_M4_RISK_BUDGET_MISSING_NEW,
            intent=(
                "Defect 4, restored: the first draft assigned the binding to "
                "'missing_risk_budget' on the no-budget path, DISCARDING the "
                "clipping. Every unbudgeted thesis then rejected the cap's "
                "provenance and reported 'no budget' instead."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 the missing-budget warning is weakened",
            path=SRC,
            old=_M4_BUDGET_WARNING,
            new=_M4_BUDGET_WARNING_NEW,
            intent=(
                "The warning is the ONLY carrier of the fact that the Q12 check "
                "did not run -- the binding field legitimately says "
                "'position_limit' on that path. Delete the sentence and the "
                "output reads as 'checked and clear'."
            ),
        ),
        # -- M5: which scenarios are sized ------------------------------------
        Mutation(
            group="M5",
            name="M5.1 only the profitable branches are sized",
            path=SRC,
            old=_M5_SCENARIOS,
            new=_M5_SCENARIOS_NEW,
            intent=(
                "Section 22.6's optimum is defined over an EXHAUSTIVE set. "
                "Filtering to the positive branches removes the losses that "
                "make Kelly's answer finite, so the size rises on exactly the "
                "views that should be smallest."
            ),
        ),
        # -- M6: the removed gate (a deletion) --------------------------------
        Mutation(
            group="M6",
            name="M6.1 the unreachable outcome member is reinstated",
            path=SRC,
            old=_M6_LITERAL,
            new=_M6_LITERAL_READDED,
            intent=(
                "D-072 DELETED `refused_no_scenarios`, so there is nothing left "
                "to mutate -- only the declaration. Reinstating the member makes "
                "it a declared, consumed, unreachable branch (D-045/D-046/D-048, "
                "O-53) and `test_every_outcome_member_is_reachable` is the "
                "guard."
            ),
        ),
        # -- M7: the sign-off gate --------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 the sign-off gate no longer denies executability",
            path=SRC,
            old=_M7_CONSTANT,
            new=_M7_CONSTANT_WEAK,
            intent=(
                "Section 1.1's distinction between a reasoning layer and a "
                "signal generator rests on these words. Weakened to 'a sizing "
                "suggestion', a caller reading the proposal in isolation has "
                "nothing telling them it is not an instruction."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.2 the sign-off gate is dropped from the sizing path",
            path=SRC,
            old=_M7_WARNING_FIRST,
            new=_M7_WARNING_NONE,
            intent=(
                "The gate is a CONTRACT TERM, so it must survive every path. "
                "This removes it from the one path where a real number is "
                "published -- the path a consumer is most likely to act on."
            ),
        ),
        # -- M8: the output invariants ----------------------------------------
        Mutation(
            group="M8",
            name="M8.1 a refusal may carry a non-zero size",
            path=SRC,
            old=_M8_REFUSAL_SIZE_GUARD,
            new=_M8_REFUSAL_SIZE_GUARD_NEW,
            intent=(
                "An `or` relaxed to an `and`: a refusal carrying only ONE "
                "non-zero number now validates. **This mutant SURVIVED the "
                "sweep's first run and found a real hole** -- the shipped guard "
                "tested `fraction_of_capital` and "
                "`notional_fraction_after_constraints` but never "
                "`requested_fraction_of_capital`, and the two it did test are "
                "written together on every path, so no input the suite exercised "
                "distinguished the `or` from an `and`. Measured: a refusal with "
                "`requested_fraction_of_capital=0.05` was ACCEPTED. `D-072`'s "
                "repair adds the third field to the guard and the parameterised "
                "test that asserts each of the three alone."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.2 a refusal may name a binding constraint",
            path=SRC,
            old=_M8_REFUSAL_BINDING_GUARD,
            new=_M8_REFUSAL_BINDING_GUARD_NEW,
            intent=(
                "A constraint cannot have produced a size that was not "
                "produced. With the guard disabled a refusal can claim the cap "
                "bound it."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.3 constraints may increase the notional",
            path=SRC,
            old=_M8_MONOTONE_GUARD,
            new="        if False:",
            intent=(
                "Limits reduce exposure. The invariant is what would catch a "
                "future edit that let the risk budget lever a position UP -- the "
                "direction that looks like success."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.4 a zero risk budget is treated as small rather than as a decision",
            path=SRC,
            old=_M8_ZERO_BUDGET,
            new=_M8_ZERO_BUDGET_NEW,
            intent=(
                "'The book allocated this instrument no risk' is not 'the "
                "allocation reduced the size by 100%'. With `< 0.0` a zero "
                "budget flows into the sizing arithmetic instead of getting its "
                "own outcome."
            ),
        ),
        # -- M10: the declared member set (D-070's discipline, one type over) --
        Mutation(
            group="M10",
            name="M10.1 a Literal member is declared with no producer",
            path=SRC,
            old=_M10_DECLARED_SET,
            new=_M10_DECLARED_SET_DRIFTED,
            intent=(
                "D-072 DELETED two members this way (`refused_no_scenarios` and a "
                "reconciliation member), so the shape of the defect is fresh. "
                "`sized_by_risk_budget` reads like a plausible fourth sizing path "
                "and no gate produces it -- the declared-consumed-unreachable "
                "branch (D-045/D-046/D-048, O-53). Both the unit suite's "
                "reachability guard AND the live check's section 7 assert the "
                "declared set, so the kill is attributable to whichever runs."
            ),
        ),
        Mutation(
            group="M10",
            name="M10.2 the type docstring miscounts the members",
            path=SRC,
            old=_M10_DOCSTRING_COUNT,
            new=_M10_DOCSTRING_COUNT_DRIFTED,
            intent=(
                "**This is the live check's FIRST RUN defect, reproduced as a "
                "mutant.** The docstring shipping with D-072 said 'nine members' "
                "for a `Literal` that had six -- and had said nine since the "
                "draft, through a repair that removed three members. A type "
                "cannot check a sentence, and the live check's section 7 exists "
                "to refuse exactly this. If this survives, section 7 is "
                "decoration."
            ),
        ),
        Mutation(
            group="M10",
            name="M10.3 the gate count in the docstring is reversed",
            path=SRC,
            old=_M10_GATE_COUNT,
            new=_M10_GATE_COUNT_NEW,
            intent=(
                "The function's own gate list says 'there are four, not five' -- "
                "the sentence a maintainer reads before deciding whether to add a "
                "gate. Reversed, it licenses reinstating dead code. The live "
                "check's section 6 counts the gates' outcomes, so a fifth gate "
                "with no producer is visible there; a docstring that merely "
                "*claims* four is not."
            ),
        ),
        # -- M9: the honesty control ------------------------------------------
        Mutation(
            group="M9",
            name="M9.1 CONTROL -- `None is None` in an equivalent form",
            path=SRC,
            old=_M4_RISK_BUDGET_MISSING,
            new="    risk_budget_missing = (target is None) and True",
            intent=(
                "Semantically identical to the shipped code, so it MUST "
                "survive. If the sweep reports it killed, the sweep is "
                "reporting kills it cannot justify and no other number it "
                "prints means anything (the D-051 false 56/56)."
            ),
            expect_killed=False,
        ),
    ]


#: Mutations that are provably unable to change behaviour. Every entry needs a
#: proof in ``_INERT_PROOFS`` or the harness returns exit 2 rather than certify.
_EXPECTED_INERT: frozenset[str] = frozenset()

#: The proofs backing ``_EXPECTED_INERT``. A name in the set without a proof here
#: is a claim, not a result, and the harness refuses to certify.
#:
#: **This sweep declares NOTHING inert, and that is deliberate.** Its predecessor
#: (D-057's) carried four entries, of which one was a *conditional* claim rather
#: than a proof, and D-055/D-056 each carried an unreachability proof. The
#: question O-52 and O-55 raise is whether those proofs belong in a sweep's
#: allow-list at all when the project's own standard is that **an invariant
#: should be a test** (`test_a_route_whose_category_disagrees_with_the_matcher_is_
#: refused` is the precedent, from D-058). Rather than add proofs, this sweep
#: closes the same holes with tests, so there is nothing left to exempt:
#:
#: * the "gate 4 does not apply the budget" NEGATIVE is pinned by
#:   ``test_the_risk_budget_does_not_scale_the_notional`` and by the
#:   ``notional_fraction_after_constraints`` invariant;
#: * the removed gate's unreachability is pinned by
#:   ``test_an_empty_distribution_is_unreachable_so_its_outcome_was_removed``;
#: * the index-vs-pct conversion in the characterisation test is pinned by
#:   ``test_no_notional_relation_holds_between_weight_and_risk_share``.
#:
#: The honest consequence: if a mutation below survives, the answer is a missing
#: test, never an exemption. That is the standard the module docstring states and
#: this is the sweep that holds it.
_INERT_PROOFS: dict[str, str] = {}


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test -- a conclusion about code nobody mutated. An
    ``old`` appearing zero times means the target has drifted and the mutation
    is not testing what its name says.

    **The ambiguity hazard is at its highest in this file.** Five functions share
    ``risk_budget.py``; ``compute_confidence(`` appears five times, ``_refuse(``
    five times inside this function alone, ``binding: PositionBinding`` twice in
    the anchors above (``M3.3`` and ``M4.1`` deliberately share ``M4``'s
    neighbour), and ``permitted = 1.0`` could in principle appear elsewhere. Every
    anchor is a distinctive multi-line statement and this gate is what proves it.
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
    call inlines.
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
                "tests/portfolio/test_thesis_position.py",
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
    slice came out a few dozen characters long and the gate reported every target
    as un-inlined. The marker below must therefore not be quotable, and the
    search starts from a fixed offset past this function.

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

    **``-x`` IS passed.** The selection is ~25 s on a clean tree; without ``-x``
    every mutant runs it to completion for information entirely contained in the
    first failure. D-056's sweep used ``-x`` for the same reason, and its absence
    in D-057's first draft is why a run had to be killed by hand -- which left
    ``M5.2`` mutated in ``src/``. The lesson: the kill signal must be cheap,
    because the cheap path is the one that gets used.
    """
    # -- the executed selection (read by check_declaration_matches_run) --
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/portfolio/test_thesis_position.py",
            "tests/portfolio/test_risk_budget.py",
            "tests/portfolio/test_fractional_kelly.py",
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
    parser.add_argument("--group", help="run only this mutation group, e.g. M3")
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
    print("mutation sweep: translate_thesis_to_position (Module 17.4, Section 9.3, D-072)")
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
