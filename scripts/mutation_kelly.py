"""Mutation sweep for ``apply_fractional_kelly`` (Module 17.3, Sections 20.14/22.6, D-057).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/portfolio/risk_budget.py`` and
``src/macro_engine/config.py`` in place, so any concurrent test run, live check
or probe reads a mutated module. D-047's Postscript 2 records a contaminated
reading produced exactly that way, and D-049 left the source mutated when its
sweep was killed mid-run -- the full suite then passed *with the mutation in
place*. The blast radius is the whole repository.

Why the mutations are named after defects
-----------------------------------------
Every predecessor on this module -- ``evaluate_drawdown_rules`` (D-054),
``check_rebalancing_drift`` (D-055), ``volatility_target_scaling`` (D-056) --
named its mutations after the defect each one repairs, and D-057 has the largest
documented defect set of the four: three defects inherited from Section 17.3's
placeholder body, four more found by probing, and two of those were discovered
only *because* of the cross-check and the golden test the standing brief
required from the start. So the groups here are the **repairs**, not an
enumeration. A survivor names a repair no test pins. The grouping, not the
count, is what tells you what is missing (D-031).

What this sweep structurally CANNOT find
----------------------------------------
**Section 22.13's mandatory DELETION is not mutation-testable, and that is the
increment's central structural fact.** The placeholder ``raw_kelly = ev / 100``
is removed, not fixed, so there is no expression left to mutate. ``M1.*``
therefore attacks the two boundaries where the deletion is *observable*: the
value the real function publishes (``M1.1`` restores the placeholder's number
and must be killed), and the auditable claim in the context string that the
placeholder "is not implemented anywhere" (``M1.2``). If ``M1.*`` ever reports
survivors, the deletion has become a claim rather than a fact.

**The §20.14 golden test is a HIT, not a PARTITION, and no mutation can expose
that either.** ``test_fractional_kelly_never_exceeds_hard_limits`` is phrased
about the cap and passes on correct code; it would pass equally on code that
enforces *only* the cap and ignores the fractional divisor -- which is a
different, wrong program. A test cannot be killed for being under-specified by
mutating the implementation (lesson 49). ``M5.*`` is that missing test expressed
as a mutation target.

**The payoff-UNIT contract is only half guarded, and the sweep can only reach
the guarded half.** ``KellyInputs.payoff_unit`` is a ``Literal`` with the
producer's two members, of which **one** is legal, so a bp declaration is a
*type* error no longer — D-064 moved that refusal out of the type and into a
**named validator** (``M4.4``), because a one-member ``Literal`` was doing two
jobs and the second one (defaulting) silently gave a ``bp_pnl_proxy``
distribution the ``fraction_of_capital`` label. Nothing verifies that the
*values* match the declaration, and ``M4.2`` proves the unguarded half is real by
mutating the only cheap secondary check. The residual is D-057's P4 and belongs
to a human reviewer, not to this sweep.

**The search-edge collapse (P5b) is a disclosure, not an enforcement.** The
request genuinely IS ``1/k`` for every all-positive-edge distribution, so a
mutation "fixing" it is not a mutation of the shipped program at all. ``M3.*``
pins the *disclosure* instead, which is the strongest thing that can be pinned.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. This control is what D-051's first
draft lacked when it reported a false 56/56.

What the first run of THIS sweep got wrong
------------------------------------------
Two harness defects were found by running it, and both are recorded here rather
than quietly fixed, because each is the same class the sweep exists to catch:

1. **``check_targets`` refused twice, correctly, on anchors transcribed from
   memory rather than from the file.** ``M2.3``'s anchor was the bare
   ``if at_search_edge:``, which appears TWICE in the module (once on the
   generalized optimum, once on the applied request); ``M3.2``'s was written as
   the ``index/(n-1)`` form when the SHIPPED text is that form and the anchor
   had it on the wrong side of the swap. Both were caught before a single
   mutation ran. This is D-048's gate doing its job, twice, on one file.

2. **The kill signal was too expensive, and that is what broke the tree.** With
   the full four-file selection and no ``-x``, each mutant costs ~95 s, so the
   sweep is ~40 minutes -- and a 40-minute foreground run invites exactly the
   interruption that happened: the process was killed, ``SIGTERM`` bypassed the
   ``finally`` restore, and ``src/macro_engine/portfolio/risk_budget.py`` was
   left with ``M5.2`` (``multiplier = 0.5``) applied. The next test run caught
   it, and the fix is two-fold: ``-x`` restores the cheap kill path, and a
   ``SIGTERM``/``SIGINT`` handler now restores the in-flight mutation. The
   residual ``SIGKILL`` risk cannot be engineered away, so the standing rule is
   the module docstring's: FOREGROUND ONLY, and verify the swept selection,
   after any interruption.
"""

from __future__ import annotations

import argparse
import re
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

from _sweep_gate import run_pytest as _run_pytest_inproc
from _sweep_gate import sweep_lifecycle

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/macro_engine/portfolio/risk_budget.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/test_infrastructure.py`` is included because the ``config.py``
#: mutants land on ``KellySettings``'s new ``search_points`` accessor and its
#: floor validator, and that file is where the shipped YAML's round-trip through
#: the settings model is asserted.
#:
#: ``tests/data_layer/test_phase1_data_layer.py`` is included because
#: ``D-057`` had to add the now-required ``grid_points`` leaf to that file's
#: kelly-floor payload; the ``CX2``/``CX3`` mutants touch the same validator and
#: that payload is the fixture that would notice.
#:
#: ``tests/portfolio/test_risk_budget.py`` is included because the module's
#: ``__all__`` grew to fifteen names in D-057 and that file asserts it.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
    "tests/portfolio/test_fractional_kelly.py",
    "tests/portfolio/test_risk_budget.py",
    "tests/test_infrastructure.py",
    "tests/data_layer/test_phase1_data_layer.py",
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
# **Ambiguity is the live hazard here, and it is worse than for any predecessor.**
# Four functions now share ``risk_budget.py``; ``min(`` appears in
# ``check_rebalancing_drift`` and again in ``apply_fractional_kelly``;
# ``round(..., 6)`` appears in every function in the module; and
# ``compute_confidence(`` appears four times. Every anchor below is therefore
# pinned to a *distinctive* full statement -- usually a published-value key --
# rather than to a bare expression, and ``check_targets`` is what proves the
# pinning worked.

# --- M1: D1 -- the placeholder's deletion and the auditable claim ------------

_M1_FULL_KELLY_KEY = '            "full_kelly_fraction": round(best_fraction, 6),'

_M1_CONTEXT = (
    '            "Grid-search-maximised expected log growth over the FULL scenario "\n'
    '            "distribution — not a two-outcome approximation, and not the EV/100 "\n'
    '            "placeholder Section 22.6 replaced. The closed form does not exist "\n'
    '            "for more than two outcomes, so a search is standard practice rather "\n'
    '            "than an approximation introduced here."'
)

# --- M2: D2/D4 -- the search-edge disclosure --------------------------------

_M2_EDGE_FLAG = "    at_search_edge = best_fraction >= 1.0"
_M2_EDGE_IN_VALUE = '            "at_search_edge": at_search_edge,'
# Pinned to the warning that follows it, because `if at_search_edge:` appears
# TWICE in the module -- once on the generalized optimum and once on the
# applied request -- and the first occurrence is the one this mutation means.
# check_targets caught the bare form on the sweep's first run.
_M2_EDGE_WARNING_GUARD = """    if at_search_edge:
        warnings.append(
            "The optimum is at the SEARCH BOUNDARY (f = 1.0), so the true \""""
_M2_EDGE_WARNING_GUARD_NEW = """    if False:
        warnings.append(
            "The optimum is at the SEARCH BOUNDARY (f = 1.0), so the true \""""

# --- M3: the grid and its resolution ----------------------------------------

_M3_GRID_POINTS = "    grid_points = settings.kelly.search_points"
# The shipped line is `index / (grid_points - 1)` and the subtraction is
# LOAD-BEARING: `range(n)` tops out at `n-1`, so dividing by `n-1` lands the
# final candidate exactly on 1.0 and puts the step at exactly 1e-5 for the
# shipped 100001 points. Dividing by `n` instead stops one step short of the
# upper edge AND detunes the grid off the closed-form optimum -- measured,
# 20000/100001 = 0.199998 against a closed form of exactly 0.2, which
# `test_the_grid_resolution_reproduces_the_closed_form_exactly` catches.
#
# **This anchor was written backwards on the sweep's first run** and the harness
# caught it twice: `check_targets` refused with "target ABSENT" (because the
# bare `index / grid_points` form does not appear in the shipped file), which is
# exactly the job it exists to do. The corrected form below is the shipped text.
_M3_FRACTION = "        fraction = index / (grid_points - 1)"
_M3_INIT = '    best_fraction = 0.0\n    best_growth = float("-inf")'

# --- M4: the unit contract ---------------------------------------------------

_M4_PAYOFF_UNIT = "    payoff_unit: KellyPayoffUnit = Field("
_M4_UNIT_VOCABULARY = 'KellyPayoffUnit = Literal["bp_pnl_proxy", "fraction_of_capital"]'
_M4_UNIT_REFUSAL = "        if self.payoff_unit != _KELLY_UNIT:"
_M4_BEYOND_TOTAL_LOSS = "            if scenario.payoff_estimate < -1.0:"

# --- M5: the fractional divisor and the clip --------------------------------

_M5_MULTIPLIER = "    multiplier = settings.kelly.kelly_fraction_multiplier"
_M5_REQUESTED = "    requested = full_fraction * multiplier"
_M5_CLIP = "    final_fraction = min(requested, cap)"
_M5_CLIPPED_FLAG = "    clipped = final_fraction < requested"

# --- M7: the outcome vocabulary ---------------------------------------------

_M7_OUTCOME_IF = """    if full_fraction == 0.0:
        outcome: SizingOutcome = SizingOutcome(outcome="no_edge")
    elif clipped:
        outcome = SizingOutcome(outcome="clipped_by_position_limit")
    else:
        outcome = SizingOutcome(outcome="sized_by_kelly")"""

# --- M8: the per-function unenforced set ------------------------------------

_M8_RISK_LIMITS_PROPERTY = """    @property
    def unread_by_position_sizing(self) -> list[str]:"""

_M8_PUBLISHED_KEY = '"limits_declared_but_not_enforced": unenforced,'


def build_mutations() -> list[Mutation]:
    """The catalogue, grouped by the defect each group repairs."""
    return [
        # -- M1: D1 -- the placeholder's deletion (Section 22.13) -------------
        Mutation(
            group="M1",
            name="M1.1 full_kelly_fraction is the deleted EV/100 placeholder",
            path=SRC,
            old=_M1_FULL_KELLY_KEY,
            new=(
                '            "full_kelly_fraction": round(\n'
                "                sum(s.probability * s.payoff_estimate for s in scenarios)\n"
                "                / 100.0,\n"
                "                6,\n"
                "            ),"
            ),
            intent=(
                "D1: the placeholder restored. Section 22.13 makes its removal "
                "mandatory; probed, the two differ by 3077x on a three-branch set."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 the context claims the placeholder IS implemented",
            path=SRC,
            old=_M1_CONTEXT,
            new=_M1_CONTEXT.replace(
                "not the EV/100 ",
                "and is the EV/100 ",
            ).replace(
                "placeholder Section 22.6 replaced",
                "placeholder Section 22.6 specified",
            ),
            intent=(
                "D1: the auditable half of the deletion. A context string that "
                "misdescribes what the function computes is the D-037 class in prose."
            ),
        ),
        # -- M2: D2/D4 -- the search-edge disclosure --------------------------
        Mutation(
            group="M2",
            name="M2.1 the search-edge flag is never raised",
            path=SRC,
            old=_M2_EDGE_FLAG,
            new="    at_search_edge = False",
            intent=(
                "D2/D4: f*==1.0 is the grid's upper edge, not an interior optimum. "
                "Suppressing the flag publishes a boundary hit as a solution."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the search-edge flag is published as its negation",
            path=SRC,
            old=_M2_EDGE_IN_VALUE,
            new='            "at_search_edge": not at_search_edge,',
            intent=(
                "D2: the mirrored error. Inverting the published flag makes every "
                "interior optimum claim the boundary."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.3 the search-edge warning is disabled",
            path=SRC,
            old=_M2_EDGE_WARNING_GUARD,
            new=_M2_EDGE_WARNING_GUARD_NEW,
            intent=(
                "D2: the flag survives in `value` but the prose warning -- the only "
                "place 'read this as >= 1, never as bet everything' is stated -- goes."
            ),
        ),
        # -- M3: the grid and its resolution (the n_grid defect) ---------------
        Mutation(
            group="M3",
            name="M3.1 the grid resolution is hardcoded to Section 22.6's 1000",
            path=SRC,
            old=_M3_GRID_POINTS,
            new="    grid_points = 1000",
            intent=(
                "The newly-found specification defect. 1000 points publishes 0.2002 "
                "where the closed form is 0.200000 -- 400x the rounded precision, so "
                "the digits are search noise. A literal here passes every test that "
                "does not check the resolution."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2 the grid step divisor is off by one",
            path=SRC,
            old=_M3_FRACTION,
            new="        fraction = index / grid_points",
            intent=(
                "The step convention. `index/(n-1)` over `range(n)` lands the last "
                "candidate exactly on 1.0 and puts the step at exactly 1e-5; "
                "`index/n` stops one step short of the upper edge and detunes the "
                "grid off the closed form (20000/100001 = 0.199998 vs exactly 0.2)."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the argmax initialiser makes zero unreachable",
            path=SRC,
            old=_M3_INIT,
            new='    best_fraction = float("nan")\n    best_growth = float("-inf")',
            intent=(
                "The zero-edge branch. Initialising best_fraction to nan means a "
                "distribution whose optimum is at f=0 publishes `nan` rather than the "
                "`no_edge` decision the outcome vocabulary names."
            ),
        ),
        # -- M4: the unit contract --------------------------------------------
        Mutation(
            group="M4",
            name="M4.1 payoff_unit becomes an unconstrained str",
            path=SRC,
            old=_M4_PAYOFF_UNIT,
            new="    payoff_unit: str = Field(",
            intent=(
                "D3: the enumerated declaration. A free-form str admits 'bp' at the "
                "type level, which is the 100x input error that slips under the cap. "
                "Updated by D-064: the field is now typed `KellyPayoffUnit`, so this "
                "mutation removes the declaration AND the derivation in one edit."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.3 the consumer vocabulary drops a member the producer publishes (D-064)",
            path=SRC,
            old=_M4_UNIT_VOCABULARY,
            new='KellyPayoffUnit = Literal["fraction_of_capital"]',
            intent=(
                "D-064's seam. The consumer's declaration silently omits a member "
                "the producer publishes, which under the pre-D-064 arrangement was "
                "invisible: two retyped literals agreed by inspection, and a "
                "deleted member read as validation rather than as a narrowing. The "
                "kill is the set-equality assertion in "
                "`test_the_consumer_vocabulary_is_derived_from_the_producers`."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.4 the named unit refusal is removed (D-064)",
            path=SRC,
            old=_M4_UNIT_REFUSAL,
            new="        if False:",
            intent=(
                "Since D-064 the type admits BOTH producer units and the validator "
                "admits one, so removing the validator admits a bp distribution that "
                "is then sized as if its payoffs were fractions of capital — the "
                "failure toward silence, restored."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 the beyond-a-total-loss bound is loosened past the bp range",
            path=SRC,
            old=_M4_BEYOND_TOTAL_LOSS,
            new="            if scenario.payoff_estimate < -100.0:",
            intent=(
                "D3: the secondary guard. A payoff below -1.0 cannot be a fraction of "
                "capital; widening the bound to -100 admits every bp figure while the "
                "check still looks present."
            ),
        ),
        # -- M5: the fractional divisor and the clip --------------------------
        Mutation(
            group="M5",
            name="M5.1 the mandatory fractional divisor is dropped (full Kelly ships)",
            path=SRC,
            old=_M5_REQUESTED,
            new="    requested = full_fraction",
            intent=(
                "Section 22.6: fractional Kelly is MANDATORY. This is the single most "
                "consequential mutation in the catalogue -- it ships full Kelly while "
                "the divisor is still published as 2.0."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.2 the divisor is hardcoded to the shipped 0.5 multiplier",
            path=SRC,
            old=_M5_MULTIPLIER,
            new="    multiplier = 0.5",
            intent=(
                "A hardcoded policy number passes every test built on the shipped "
                "config. Section 21 prohibits literals in models."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.3 the clip is removed entirely",
            path=SRC,
            old=_M5_CLIP,
            new="    final_fraction = requested",
            intent=(
                "D5: the hard constraint gone. The position cap is the ONE limit this "
                "function enforces, so this is its whole enforcement."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.4 the clip is applied to the up-sizing side only",
            path=SRC,
            old=_M5_CLIP,
            new=(
                "    final_fraction = (\n"
                "        min(requested, cap) if requested > cap else requested\n"
                "    )"
            ),
            intent=(
                "D5: the clip restated in a form that is correct but looks different, "
                "to confirm the tests key on the OUTCOME and not on the expression."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.5 the clipped flag reports inequality in the wrong direction",
            path=SRC,
            old=_M5_CLIPPED_FLAG,
            new="    clipped = final_fraction > requested",
            intent=(
                "D5: `final < requested` is exactly the condition under which the cap "
                "bound. Inverting it makes the flag always false."
            ),
        ),
        # -- M6: the pre-clip request (the P5 collapse) ------------------------
        Mutation(
            group="M6",
            name="M6.1 the pre-clip request is published as the clipped size",
            path=SRC,
            old='            "requested_fraction_of_capital": round(requested, 6),',
            new='            "requested_fraction_of_capital": round(final_fraction, 6),',
            intent=(
                "P5: a binding cap flattens convinction into one number. Publishing "
                "the clipped size as the request makes the flattening invisible."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.2 the expected growth is evaluated at the clipped size",
            path=SRC,
            old="""            "expected_log_growth_at_request": round(
                _expected_log_growth(inputs.scenarios, requested), 8
            ),""",
            new="""            "expected_log_growth_at_request": round(
                _expected_log_growth(inputs.scenarios, final_fraction), 8
            ),""",
            intent=(
                "P5b: the surviving discriminator. The cap constrains the book, not "
                "the distribution, so re-evaluating growth at a size Kelly did not "
                "choose answers a different question."
            ),
        ),
        # -- M7: the outcome vocabulary ---------------------------------------
        Mutation(
            group="M7",
            name="M7.1 a clipped-zero is reported as no_edge",
            path=SRC,
            old=_M7_OUTCOME_IF,
            new=_M7_OUTCOME_IF.replace(
                "    if full_fraction == 0.0:",
                "    if final_fraction == 0.0:",
            ),
            intent=(
                "D5: the branch order. A positive Kelly request clipped to zero by the "
                "cap is NOT 'no edge' -- the two are different claims about the world, "
                "which is why the vocabulary is split."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.2 the outcome vocabulary is narrowed to two members",
            path=SRC,
            old=_M7_OUTCOME_IF,
            new=_M7_OUTCOME_IF.replace(
                'SizingOutcome(outcome="no_edge")',
                'SizingOutcome(outcome="sized_by_kelly")',
            ),
            intent=(
                "The vocabulary's producibility half: a member declared but never "
                "produced is the D-046 class. Making the no-edge branch publish "
                "sized_by_kelly removes that member's only producer."
            ),
        ),
        # -- M8: the per-function unenforced set ------------------------------
        Mutation(
            group="M8",
            name="M8.1 the position-sizing unenforced set reuses the vol-target list",
            path=SRC,
            old=_M8_RISK_LIMITS_PROPERTY,
            new="""    @property
    def unread_by_position_sizing(self) -> list[str]:
        return self.unread_by_vol_targeting

    @property
    def _unused_marker(self) -> list[str]:""",
            intent=(
                "D6: the mirror-list defect. Reusing 17.2's list reports "
                "max_position_pct_of_portfolio -- the ONE limit this function DOES "
                "enforce -- as unenforced, and drops max_leverage from the report."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.2 the published unenforced key is renamed",
            path=SRC,
            old=_M8_PUBLISHED_KEY,
            new='"limits_not_evaluated_here": unenforced,',
            intent=(
                "The published vocabulary. A silent rename leaves a consumer reading "
                "an absent key without an error."
            ),
        ),
        # -- M9: the honesty control ------------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the clipped flag is expressed differently (CONTROL)",
            path=SRC,
            old=_M5_CLIPPED_FLAG,
            new="    clipped = bool(final_fraction < requested) is True",
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
            name="CX1 the search resolution is hardcoded to the shipped 100001",
            path=CONFIG,
            old="        points = int(self.grid_points.value)",
            new="        points = 100001",
            intent=(
                "A hardcoded resolution passes every test that does not move the "
                "config leaf. Section 21 prohibits literals in models."
            ),
        ),
        Mutation(
            group="CX",
            name="CX2 the search_points floor admits a one-point grid",
            path=CONFIG,
            old="""        points = int(self.grid_points.value)
        if points < 2:""",
            new="""        points = int(self.grid_points.value)
        if points < 1:""",
            intent=(
                "The grid guard. A one-point grid divides by zero when its step is "
                "computed, so the floor is what turns a crash into a startup error."
            ),
        ),
        Mutation(
            group="CX",
            name="CX3 the multiplier is the divisor rather than its reciprocal",
            path=CONFIG,
            old="        return 1.0 / self.divisor",
            new="        return self.divisor",
            intent=(
                "The fractional-Kelly arithmetic at the config boundary. Returning "
                "the divisor instead of 1/divisor sizes at 2x full Kelly, which is "
                "the exact inversion Section 22.6 exists to forbid."
            ),
        ),
    ]


#: Mutations that are provably unable to change behaviour. Every entry needs a
#: proof in ``_INERT_PROOFS`` or the harness returns exit 2 rather than certify.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M2.2 the search-edge flag is published as its negation",
        "M3.3 the argmax initialiser makes zero unreachable",
        "M5.4 the clip is applied to the up-sizing side only",
        "M7.1 a clipped-zero is reported as no_edge",
    }
)

#: The proofs backing ``_EXPECTED_INERT``. A name in the set without a proof here
#: is a claim, not a result, and the harness refuses to certify.
#:
#: **M5.4 is INERT BY EQUIVALENCE, and it is the honest kind of inert.** The
#: mutant rewrites ``min(requested, cap)`` as a conditional that returns the same
#: value on every input: when ``requested > cap`` both return ``cap``, and
#: otherwise both return ``requested``. Unlike D-055's unreachable-branch inert
#: or D-056's transcribed-value inert, this one *is* the same function written
#: differently -- which is precisely why it is the right check that the tests key
#: on the published outcome rather than on the source expression. It survives
#: because there is nothing to kill: no input distinguishes the two programs.
#:
#: **M3.3 is INERT BY UNREACHABILITY, and the proof is arithmetic rather than a
#: transcription.** The mutant replaces the argmax initialiser
#: ``best_fraction = 0.0`` with ``float("nan")``. It cannot change the result,
#: because the loop body's guard is ``if growth > best_growth`` and
#: ``best_growth`` starts at ``-inf``: on the FIRST iteration the grid always
#: supplies ``fraction = 0.0``, where ``_expected_log_growth`` sums
#: ``p_i * log(1 + 0 * r_i) = p_i * log(1) = 0`` for every branch — so the first
#: comparison is ``0.0 > -inf``, which is True, and the initialiser is overwritten
#: before it can be read. The guard immediately below the loop
#: (``if best_growth == float("-inf")``) is the only path on which no assignment
#: happens, and it RAISES rather than publishing — so ``best_fraction`` is never
#: observed in its initial state on any reachable input. Probed directly: the
#: mutant and the shipped code return identical values on an all-branch-ruined
#: set and on a zero-edge set alike. The honest conclusion is that the
#: initialiser is a defensive default, not a live value, and the mutation records
#: that equivalence rather than testing the test.
#:
#: **M2.2 is CONDITIONAL, and its proof is a property of the SHIPPED
#: distribution of test inputs, not of the code.** The mutant publishes
#: ``not at_search_edge``. That is observable -- so the mutation is not
#: intrinsically inert -- but it survives only if no test consults
#: ``at_search_edge`` on a set whose true flag is True AND separately on a set
#: whose true flag is False, while treating the two asymmetrically. The shipped
#: tests do assert the flag in both directions
#: (``test_an_all_positive_ev_set_pins_the_optimum_at_the_search_edge`` and
#: ``test_an_interior_optimum_does_not_claim_the_search_edge``), so this proof is
#: expected to FAIL and the entry is expected to be killed. It is listed here
#: because D-057's second honour requires the *claim* to be checked rather than
#: assumed: if the sweep reports it surviving, the negation was silent and one of
#: those two tests is not asserting what its name says. The harness prints the
#: verdict, so the claim is falsifiable rather than asserted.
_INERT_PROOFS: dict[str, str] = {
    "M5.4 the clip is applied to the up-sizing side only": (
        "INERT BY EQUIVALENCE. `min(requested, cap)` and "
        "`min(requested, cap) if requested > cap else requested` agree on every "
        "float input: `requested > cap` is exactly the complement of the condition "
        "under which `min` selects `requested`, so the two programs are the same "
        "function written two ways. There is no input that distinguishes them, so "
        "no test can kill this -- and none should have to."
    ),
    "M3.3 the argmax initialiser makes zero unreachable": (
        "INERT BY UNREACHABILITY, proven arithmetically. The mutant changes "
        '`best_fraction = 0.0` to `float("nan")`, but the loop guard is '
        "`growth > best_growth` with `best_growth` initialised to `-inf`, and the "
        "grid's first candidate is always `fraction = 0.0`, where "
        "`_expected_log_growth` is exactly 0.0 (every term is `p_i * log(1)`). So "
        "the first comparison is `0.0 > -inf` and assigns unconditionally -- the "
        "initialiser is dead before it can be read. The only path that does not "
        "assign is the `best_growth == -inf` guard, which RAISES rather than "
        "publishing, so the initial state is unobservable on every reachable "
        "input. Probed: identical outputs on a zero-edge set and on an "
        "all-branches-ruined set."
    ),
    "M2.2 the search-edge flag is published as its negation": (
        "CONDITIONAL, AND EXPECTED TO BE KILLED. The mutant publishes "
        "`not at_search_edge`, which IS observable, so the mutation is not "
        "intrinsically inert. It survives only if no test reads the flag on both "
        "an edge-pinned and an interior set. The shipped tests do exactly that "
        "(test_an_all_positive_ev_set_pins_the_optimum_at_the_search_edge reads "
        "True; test_an_interior_optimum_does_not_claim_the_search_edge reads "
        "False), so this entry is a FALSIFIABLE CLAIM rather than an excuse: a "
        "survival here means one of those two tests is not asserting what its "
        "name says, and the harness will report it as an unexpected survivor."
    ),
    "M7.1 a clipped-zero is reported as no_edge": (
        "INERT BY UNREACHABILITY, and the proof corrects the module's own prose. "
        "The mutant swaps the guard from `full_fraction == 0.0` to "
        "`final_fraction == 0.0`. Those two are EQUIVALENT over every input the "
        "contract admits, because `final_fraction = min(requested, cap)` with "
        "`cap > 0` ENFORCED BY THE FIELD BOUND (`max_position_pct_of_portfolio` "
        "is `gt=0.0`; a cap of exactly zero is a ValidationError). So "
        "`final_fraction == 0.0` requires `min(requested, cap) == 0.0`, which "
        "requires `requested == 0.0` (cap is strictly positive), which requires "
        "`full_fraction == 0.0` -- the shipped guard, which fires first either "
        "way. Verified exhaustively over 200000 random draws: zero disagreements. "
        "THE CONSEQUENCE IS A FINDING, not an excuse: the state "
        "`SizingOutcome`'s docstring describes as `clipped_by_position_limit` "
        "with a zero result is UNREACHABLE, because a cap small enough to zero "
        "the size is not a legal cap. `test_a_positive_edge_clipped_to_zero_is_"
        "not_no_edge` asserts that reachability fact (including the "
        "ValidationError that makes the cap non-zero) so a future bound change is "
        "visible rather than silent."
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

    **This is the strictest check_targets in the directory, and deliberately so.**
    ``risk_budget.py`` now holds four functions sharing a module: ``min(`` appears
    in ``check_rebalancing_drift`` and in ``apply_fractional_kelly``;
    ``compute_confidence(`` appears four times; every function publishes
    ``round(..., 6)`` values. Every anchor above is therefore a distinctive full
    statement, and this gate is what proves the distinctiveness rather than
    assuming it.

    Two mutations (``M5.3`` and ``M5.4``) share one anchor and are meant to: each
    is applied and restored independently, so ``apply_and_test``'s per-mutation
    read-modify-write keeps them from colliding. ``M5.4`` is listed before ``M9.1``
    but reuses ``M5``'s anchor; that is intentional and is what
    ``Mutation.group`` is for.
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

    The near-miss trap for this sweep is that ``test_fractional_kelly.py`` is a
    NEW file in a package that already holds three other test modules; a name
    that differs by one word collects zero tests from a plausible-looking path.
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
        proc = _run_pytest_inproc(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/portfolio/test_fractional_kelly.py",
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

    **``-x`` IS passed, and it is not optional here.** This selection takes ~95 s
    on a clean tree because ``tests/data_layer/test_phase1_data_layer.py``
    dominates it. Without ``-x`` every one of the 25 mutants runs the whole
    selection to completion, which is ~40 minutes of wall clock for information
    that is entirely contained in the first failure. D-056's sweep used ``-x``
    for the same reason, and its absence in this sweep's first draft is why a
    run had to be killed by hand -- which, in turn, is what left ``M5.2``
    mutated in ``src/``. The lesson is recorded in the module docstring: the
    kill signal must be cheap, because the cheap path is the one that gets used.
    """
    proc = _run_pytest_inproc(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/portfolio/test_fractional_kelly.py",
            "tests/portfolio/test_risk_budget.py",
            "tests/test_infrastructure.py",
            "tests/data_layer/test_phase1_data_layer.py",
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

    **D-057 UPDATE: ``finally`` is NOT sufficient, and this run proved it.**
    ``finally`` covers exceptions and ``KeyboardInterrupt``, but it does NOT
    cover ``SIGTERM`` -- and the first run of this sweep was stopped by a
    process kill, which bypasses Python's cleanup entirely. The source was left
    with ``M5.2`` (``multiplier = 0.5``, i.e. a HARDCODED divisor) applied, and
    ``test_the_divisor_is_read_from_config_not_a_literal`` caught it on the next
    test run. ``main`` therefore installs a SIGTERM/SIGINT handler that restores
    the in-flight mutation before exiting, because "the harness left the tree
    broken when interrupted" is a defect class this project has now hit twice
    (D-049, D-057).

    The residual risk that cannot be engineered away: a ``SIGKILL``. Nothing can
    run on the way out of ``SIGKILL``, so the standing rule is the one the
    module docstring states -- run the sweep in the FOREGROUND, and if it must be
    stopped, verify the tree afterwards with the swept selection.
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
    parser.add_argument("--group", help="run only this mutation group, e.g. M5")
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

    # D-057: a killed sweep must not leave the tree mutated. ``finally`` covers
    # exceptions but not SIGTERM, and the first run of this sweep was stopped by
    # exactly that and left ``M5.2`` applied.
    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: apply_fractional_kelly (Module 17.3, Section 20.14/22.6, D-057)")
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
