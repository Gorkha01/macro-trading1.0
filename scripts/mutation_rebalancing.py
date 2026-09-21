"""Mutation sweep for ``check_rebalancing_drift`` (Module 17.3, Section 15.18, D-055).

**Run this in the FOREGROUND ONLY.** The sweep rewrites ``risk_budget.py`` and
``config.py`` in place, so any concurrent test run, live check or probe reads a
mutated module. D-047's Postscript 2 records a contaminated reading produced
exactly that way, and D-049 left the source mutated when its sweep was killed
mid-run -- the full suite then passed *with the mutation in place*. The blast
radius is the whole repository.

Why the mutations are named after defects, again
------------------------------------------------
``four_pillar_scorecard`` (D-050) and ``classify_convergence`` (D-051) had an
**enumerable** output space and derived mutations from it. ``check_rebalancing_drift``,
like ``evaluate_drawdown_rules`` (D-054), has a continuous input space and a tiny
decision space: one absolute-value comparison per budget line, plus two set
differences. So the groups below are not an enumeration -- each group is the
**repair of one documented defect** (or one contract clause), and a survivor
names the repair no test pins. The grouping, not the count, is what tells you
what is missing (D-031).

Two things this sweep would NOT have found
------------------------------------------
1. **Defect 3 is nearly invisible to mutation testing.** The unit convention
   lives in ``config.py``'s accessor and in the function's *guard*, and a
   percent-scale threshold is still a deterministic threshold. Every outcome
   test built on an explicit ``threshold=`` argument bypasses the config path
   entirely. ``M3.1``/``M3.2`` remain killable only because
   ``test_the_configured_threshold_is_a_fraction_not_a_percent`` reads the
   *shipped* config through the *shipped* loader. If this group ever reports
   survivors, the unit convention has lost its only guard.
2. **Defect 2's severity is not visible in the arithmetic at all.** An
   unbudgeted instrument changes no drift row; it changes one published *set*.
   ``M2.*`` therefore kill only on the set-membership assertions, which is why
   ``test_an_unbudgeted_instrument_is_reported_not_ignored`` and
   ``test_an_unbudgeted_instrument_does_not_create_a_drift_row`` are the two
   tests to protect -- and why killing one of them alone is not enough
   (``M2.2`` is designed to pass the first and fail the second, or vice versa).

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. This is the control whose absence let
D-051's first draft report a false 56/56.

A note on the D-054 constants
-----------------------------
``scripts/mutation_drawdown.py`` already defines ``_TIERS_*``, ``_MAX_SEVERITY``
and ``_RESOLVE_DEFAULT`` anchors. Several of the strings below are *near
neighbours* of those (both functions live in the same file and both cap at
``1.0``). Derived-anchor ambiguity is the D-048 failure mode, so every anchor
here is checked for uniqueness by ``check_targets`` before a single mutation is
applied -- and one of them (``_LOOP_GET``) had to be re-anchored on its
surrounding loop during authoring for exactly that reason.
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
#: mutants land on ``RiskSettings.rebalancing_drift`` and its accessor, and that
#: file is where the shipped YAML's round-trip through the settings model is
#: asserted.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
    "tests/portfolio/test_rebalancing_drift.py",
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
# Transcribed targets. Every one of these is a byte-for-byte copy of text in
# the shipped source; check_targets refuses to run if any has drifted.
# ---------------------------------------------------------------------------

# --- risk_budget.py, Defect 1: a missing instrument is not a zero -----------
#
# The spec's ``.get(t.instrument, 0.0)``. Re-anchored on the preceding loop
# line because the SAME expression is a legal (and now correct) read elsewhere:
# ``set(current_contributions)`` is the unbudgeted scan, and a bare
# ``current_contributions.get`` would be ambiguous if the layout ever changed.
_LOOP_GET = (
    "        seen.add(target.instrument)\n"
    "        actual = current_contributions.get(target.instrument, 0.0)"
)
_BUDGET_TARGET_FIELD = (
    "    target_risk_contribution_pct: float = Field(\n        ge=0.0,\n        le=1.0,"
)

# --- risk_budget.py, Defect 2: an instrument outside the budget ------------
#
# ``seen`` is what makes the unbudgeted set computable at all. Dropping the
# ``add`` makes ``unbudgeted`` equal every current contribution -- which is
# wrong in a way that reads as *more* careful, not less.
_SEEN_DECL = "    seen: set[str] = set()"
_SEEN_ADD = "        seen.add(target.instrument)"
_UNBUDGETED = "    unbudgeted = sorted(set(current_contributions) - seen)"

# --- risk_budget.py, Defect 3: the threshold's unit and bounds -------------
#
# ``drift_threshold_pct`` is a FRACTION despite the suffix. The guard is what
# makes the 100x error detectable -- a value above 1.0 is a percent in a
# fraction field.
_THRESHOLD_ASSIGN = (
    "    threshold = (\n"
    "        settings.risk.rebalancing_drift_threshold\n"
    "        if drift_threshold_pct is None\n"
    "        else float(drift_threshold_pct)\n"
    "    )"
)
_THRESHOLD_GUARD = "    if not 0.0 < threshold <= 1.0:"
_THRESHOLD_GUARD_BODY = (
    '            f"drift_threshold_pct must be a fraction in (0, 1], got {threshold}. "\n'
    '            f"A value above 1.0 is a percent written into a fraction field."'
)
_THRESHOLD_CAST = "        else float(drift_threshold_pct)"

# --- risk_budget.py, Defect 4: the strict boundary -------------------------
#
# ``>`` is what the specification's arrow says, and it makes the threshold
# non-binding: a drift of exactly ``threshold`` does not flag.
_DRIFT_COMPARE = "        if abs(signed) > threshold:"
_DIRECTION = '            direction: DriftDirection = "over" if signed > 0 else "under"'

# --- risk_budget.py, the drift row's two bases -----------------------------
#
# ``signed`` is the raw difference with the TARGET subtracted. Swapping the
# operands flips the sign of every row while leaving ``abs_drift`` untouched --
# so every ``direction`` inverts and nothing else moves. That is precisely the
# shape a test over absolute values alone cannot see.
_SIGNED = "        signed = actual - target.target_risk_contribution_pct"

# --- risk_budget.py, the missing / unbudgeted publication ------------------
_MISSING = (
    "    missing = [t.instrument for t in targets if t.instrument not in current_contributions]"
)

# --- risk_budget.py, the share-basis warning -------------------------------
_SUM_WARNING = "    if current_contributions and abs(total_actual - 1.0) > 0.01:"
_TOTAL_ACTUAL = "    total_actual = sum(current_contributions.values())"

# --- risk_budget.py, the outcome literal and the branch that sets it -------
_OUTCOME_TYPE = 'RebalancingOutcome = Literal["balanced", "rebalance"]'
_DIRECTION_TYPE = 'DriftDirection = Literal["over", "under"]'
_OUTCOME_ASSIGN = '    outcome: RebalancingOutcome = "rebalance" if drifted else "balanced"'

# --- risk_budget.py, the published value -----------------------------------
#
# NOTE ON THE SHARED ANCHORS. ``evaluate_drawdown_rules`` (D-054) publishes an
# ``"outcome"`` key too, from a byte-identical line, and its ``warnings`` list
# opens with the same declaration. All three ambiguities below were found by
# ``check_targets`` on the first run of this sweep -- which is the gate doing
# exactly the job D-048 built it for. The repair is to anchor each on a
# preceding line that exists ONLY in the rebalancing block, so ``str.replace``
# cannot reach back into the drawdown function.
_PUBLISHED_KEYS: dict[str, str] = {
    "outcome": '            "outcome": outcome,\n            "drifted": drifted,',
    "drifted": '            "drifted": drifted,',
    "drifted_instruments": '            "drifted_instruments": drifted_instruments,',
    "unbudgeted_instruments": '            "unbudgeted_instruments": unbudgeted,',
    "missing_instruments": '            "missing_instruments": missing,',
    "instruments_evaluated": '            "instruments_evaluated": len(targets),',
    "instruments_drifted": '            "instruments_drifted": len(drifted),',
    "drift_threshold_fraction": '            "drift_threshold_fraction": round(threshold, 6),',
}
_INSTRUMENTS_EVALUATED = '            "instruments_evaluated": len(targets),'
_DRIFTED_INSTRUMENTS = '            "drifted_instruments": drifted_instruments,'
_TOTAL_PUBLISHED = '            "total_current_contribution": round(total_actual, 6),'
_WORST_ROW = '        worst = max(drifted, key=lambda d: float(d["abs_drift"]))'

# --- risk_budget.py, the configured default --------------------------------
#
# Anchored on the guard above it as well as the assignment, because
# ``evaluate_drawdown_rules`` ships the SAME ``resolved = rules if ...`` shape
# two hundred lines earlier and ``_RESOLVE_DEFAULT`` in the drawdown sweep
# targets that one. A derived-anchor collision here would rewrite a different
# function and report a survival about code nobody mutated (D-048).
_CONFIG_DEFAULT = "        settings.risk.rebalancing_drift_threshold\n"

# --- risk_budget.py, the warnings ------------------------------------------
#
# ``warnings: list[str] = [`` appears twice in this file -- once per function.
# Anchored on the maintenance string that only the rebalancing function opens
# with, so the mutant cannot land in ``evaluate_drawdown_rules``.
_WARNING_MAINTENANCE = (
    "    warnings: list[str] = [\n"
    '        "This is PORTFOLIO risk-budget maintenance, NOT a thesis-validity check. "'
)
_WARNING_UNBUDGETED = "    if unbudgeted:"
_WARNING_MISSING = "    if missing:"
_WARNING_SUM = "    if current_contributions and abs(total_actual - 1.0) > 0.01:"

# --- risk_budget.py, the contract / identity / confidence ------------------
_MODEL_NAME = '        model_name="rebalancing_drift_check",'
_INPUTS_USED = '        inputs_used=["current_contributions", "targets"],'
_CONTEXT = (
    '            "PORTFOLIO risk-budget maintenance. Section 15.18 names the failure "\n'
    "            \"this separation prevents: conflating 'my portfolio drifted' with \"\n"
    "            \"'my thesis is wrong'.\""
)
_TARGET_CONFIG = (
    "    target_risk_contribution_pct: float = Field(\n        ge=0.0,\n        le=1.0,"
)
# The real config line, INSIDE the class body (after the docstring).
#
# The first draft of M10.1 anchored on ``class RiskBudgetTarget(BaseModel):``
# plus the docstring's opening line and inserted the mutant config BETWEEN them.
# That places the assignment BEFORE the docstring, so it becomes a class-body
# attribute that the real ``model_config`` -- 9 lines further down -- shadows.
# The mutant was therefore INERT BY ANCHORING, and the sweep reported it as an
# unexplained survivor: a "missing test" conclusion about code that had not
# actually changed. This is the D-051 lesson in a new costume -- a harness that
# cannot apply its own mutation will misclassify the result -- and it was caught
# only by probing the mutant's ``model_config`` directly instead of trusting the
# survivor count.
_TARGET_MODEL_CONFIG = (
    '    model_config = ConfigDict(extra="forbid")\n\n    instrument: str = Field('
)

# ``data_quality_flags_present=bool(missing),`` appears twice: once inside
# ``ConfidenceInputs`` and once on the ``ModelResult``. The one that matters is
# the confidence input -- the published flag is a report, the input is what
# lowers the number -- so the anchor is pinned to the ``ConfidenceInputs`` block
# by including the comment that follows it.
_QUALITY_FLAG = (
    "            data_quality_flags_present=bool(missing),\n"
    "            # The threshold is a stated convention, not a fitted estimate.\n"
    "            is_heuristic_not_calibrated=True,\n"
    "            depends_on_unobservable=False,\n"
    "        )\n"
    "    )"
)
_QUALITY_WITH_FALSE = (
    "            data_quality_flags_present=False,\n"
    "            # The threshold is a stated convention, not a fitted estimate.\n"
    "            is_heuristic_not_calibrated=True,\n"
    "            depends_on_unobservable=False,\n"
    "        )\n"
    "    )"
)
# ``is_heuristic_not_calibrated=True,`` also appears twice -- once per function.
# Anchored on the rebalancing block's own comment, which the drawdown function
# does not share.
_HEURISTIC_TRUE = (
    "            # The threshold is a stated convention, not a fitted estimate.\n"
    "            is_heuristic_not_calibrated=True,"
)
_HEURISTIC_FALSE = (
    "            # The threshold is a stated convention, not a fitted estimate.\n"
    "            is_heuristic_not_calibrated=False,"
)

# --- config.py: the accessor ----------------------------------------------
#
# ``rebalancing_drift_threshold`` is the file's only reader of this leaf. A
# hardcoded literal here would pass every test that asserts the shipped value
# (D-050's lesson) unless the test mutates the leaf and re-reads -- which is
# what ``test_the_accessor_reads_its_leaf_not_the_shipped_literal`` does.
_CFG_ACCESSOR_BODY = "        return float(self.rebalancing_drift.value)"
_CFG_FIELD = "    rebalancing_drift: CalibratedValue"


# ---------------------------------------------------------------------------
# The mutations
# ---------------------------------------------------------------------------


def _missing_instrument_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 1's repair: "not held" is not "held at zero risk".

    ``M1.1`` is the specification's own expression restored verbatim, so this
    mutation is a *regression test on the repair*. It is killable only because
    ``missing_instruments`` is published separately from the arithmetic -- the
    drift rows are IDENTICAL under both spellings at a non-zero target.
    """
    return [
        (
            "M1.1 `missing` is derived from a default-filled read (never reports absence)",
            SRC,
            _LOOP_GET,
            (
                "        seen.add(target.instrument)\n"
                "        actual = current_contributions.get(\n"
                "            target.instrument,\n"
                "            target.target_risk_contribution_pct\n"
                "            if target.instrument not in current_contributions\n"
                "            else 0.0,\n"
                "        )"
            ),
        ),
        (
            "M1.2 the default for an absent instrument becomes its TARGET (always balanced)",
            SRC,
            _LOOP_GET,
            (
                "        seen.add(target.instrument)\n"
                "        actual = current_contributions.get(\n"
                "            target.instrument, target.target_risk_contribution_pct\n"
                "        )"
            ),
        ),
        (
            "M1.3 `missing` is computed from the targets' own membership (always empty)",
            SRC,
            _MISSING,
            "    missing = [t.instrument for t in targets if False]",
        ),
        (
            "M1.4 `missing` is computed from the currents instead of the targets",
            SRC,
            _MISSING,
            "    missing = [t.instrument for t in targets if t.instrument in current_contributions]",
        ),
        (
            "M1.5 a target of exactly 0.0 is refused rather than budgeted",
            SRC,
            _BUDGET_TARGET_FIELD,
            ("    target_risk_contribution_pct: float = Field(\n        gt=0.0,\n        le=1.0,"),
        ),
    ]


def _unbudgeted_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 2's repair: an instrument with no budget line is visible.

    The two set-difference mutants are chosen so that each passes one of the
    two unbudgeted tests and fails the other. A single test asserting
    ``unbudgeted == ["eurusd"]`` would be killed by both; it is the *pair* --
    present **and** not-a-drift-row -- that pins the semantics.
    """
    return [
        (
            "M2.1 the unbudgeted set is computed as targets-minus-currents (the reverse)",
            SRC,
            _UNBUDGETED,
            "    unbudgeted = sorted(seen - set(current_contributions))",
        ),
        (
            "M2.2 the unbudgeted set is emptied (the spec's invisible direction)",
            SRC,
            _UNBUDGETED,
            "    unbudgeted = []",
        ),
        (
            "M2.3 the unbudgeted set is the whole current book, not the difference",
            SRC,
            _UNBUDGETED,
            "    unbudgeted = sorted(current_contributions)",
        ),
        (
            "M2.4 the `seen` set is never populated (every instrument reads unbudgeted)",
            SRC,
            _SEEN_ADD,
            "        pass",
        ),
        (
            "M2.5 `seen` is populated with the currents, not the targets",
            SRC,
            _SEEN_ADD,
            "        seen.add(target.instrument) if False else seen.add('')",
        ),
        (
            "M2.6 the unbudgeted set stops being sorted (set order leaks through)",
            SRC,
            _UNBUDGETED,
            "    unbudgeted = list(set(current_contributions) - seen)",
        ),
        (
            "M2.7 the order is REVERSED rather than sorted",
            SRC,
            _UNBUDGETED,
            "    unbudgeted = sorted(set(current_contributions) - seen, reverse=True)",
        ),
    ]


def _threshold_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 3's repair: the threshold is a bounded fraction from config.

    ``M3.1`` is the load-bearing unit mutant and it is the ONLY one here that a
    config-reading test can kill. ``M3.4``/``M3.5`` remove the bounds, which is
    what lets a percent value through the door -- the 100x error's entry point,
    one function over from where D-054 found it.
    """
    return [
        (
            "M3.1 the configured threshold is divided by 100 (a fraction read as a percent)",
            SRC,
            _CONFIG_DEFAULT,
            "        settings.risk.rebalancing_drift_threshold / 100.0\n",
        ),
        (
            "M3.2 the configured threshold is multiplied by 100 (a percent read as a fraction)",
            SRC,
            _CONFIG_DEFAULT,
            "        settings.risk.rebalancing_drift_threshold * 100.0\n",
        ),
        (
            "M3.3 the configured default is bypassed and a literal 0.10 is used",
            SRC,
            _CONFIG_DEFAULT,
            "        0.10\n",
        ),
        (
            "M3.4 the caller's threshold is not cast, so a Decimal/str slips through",
            SRC,
            _THRESHOLD_CAST,
            "        else drift_threshold_pct",
        ),
        (
            "M3.5 the fraction guard is removed (a percent value loads silently)",
            SRC,
            _THRESHOLD_GUARD,
            "    if not 0.0 < threshold < 1e9:",
        ),
        (
            "M3.6 the guard's upper half is dropped (a percent is accepted)",
            SRC,
            _THRESHOLD_GUARD,
            "    if not 0.0 < threshold:",
        ),
        (
            "M3.7 the guard's lower half is dropped (zero and negative thresholds load)",
            SRC,
            _THRESHOLD_GUARD,
            "    if not threshold <= 1.0:",
        ),
        (
            "M3.8 the guard raises but says nothing about the unit",
            SRC,
            _THRESHOLD_GUARD_BODY,
            '            f"bad threshold {threshold}. "',
        ),
    ]


def _boundary_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 4's repair: the strict boundary, disclosed rather than inferred.

    ``M4.1`` is the one-line change from ``>`` to ``>=``; it moves the trip
    point by an epsilon that no non-boundary draw can detect, which is why
    ``test_the_threshold_boundary_is_strict_not_inclusive`` builds its fixture
    by ADDITION (``0.25 + 0.10``) rather than subtraction.
    """
    return [
        (
            "M4.1 the comparison becomes inclusive (`>=` not `>`)",
            SRC,
            _DRIFT_COMPARE,
            "        if abs(signed) >= threshold:",
        ),
        (
            "M4.2 the comparison uses the SIGNED drift (a whole book drifts one way)",
            SRC,
            _DRIFT_COMPARE,
            "        if signed > threshold:",
        ),
        (
            "M4.3 the comparison is inverted (on-budget instruments flag)",
            SRC,
            _DRIFT_COMPARE,
            "        if abs(signed) < threshold:",
        ),
        (
            "M4.4 the comparison drops the absolute value's complement",
            SRC,
            _DRIFT_COMPARE,
            "        if abs(signed) > threshold or True:",
        ),
        (
            "M4.5 the direction test is inverted (over reads as under)",
            SRC,
            _DIRECTION,
            '            direction: DriftDirection = "under" if signed > 0 else "over"',
        ),
        (
            "M4.6 the direction test is inclusive at zero (a zero drift reads as over)",
            SRC,
            _DIRECTION,
            '            direction: DriftDirection = "over" if signed >= 0 else "under"',
        ),
    ]


def _arithmetic_mutations() -> list[tuple[str, Path, str, str]]:
    """The drift arithmetic itself.

    ``M5.1`` swaps the operands of the subtraction. It leaves every
    ``abs_drift`` identical and every ``direction`` inverted, so it is invisible
    to any test that only reads magnitudes -- and it is the single most
    consequential silent error available in this function, because it makes the
    over/under report backwards while looking exactly as confident.
    """
    return [
        (
            "M5.1 the signed drift's operands are swapped (every direction inverts)",
            SRC,
            _SIGNED,
            "        signed = target.target_risk_contribution_pct - actual",
        ),
        (
            "M5.2 the drift is a RATIO of the target, not a difference",
            SRC,
            _SIGNED,
            "        signed = actual / (target.target_risk_contribution_pct or 1.0) - 1.0",
        ),
        (
            "M5.3 the total contribution is the TARGET total, not the current total",
            SRC,
            _TOTAL_ACTUAL,
            "    total_actual = sum(t.target_risk_contribution_pct for t in targets)",
        ),
        (
            "M5.4 the total contribution is only the BUDGETED instruments' risk",
            SRC,
            _TOTAL_ACTUAL,
            "    total_actual = sum(v for k, v in current_contributions.items() if k in seen)",
        ),
    ]


def _outcome_mutations() -> list[tuple[str, Path, str, str]]:
    """The ``RebalancingOutcome`` literal and the branch that sets it.

    Every mutation here collapses a distinction the partition exists to keep.
    ``M6.1`` removes ``balanced`` from the TYPE, which no runtime assertion can
    see; ``test_the_declared_outcome_set_is_pinned_to_the_type`` is the only
    thing standing between that change and a silent contract break (D-045a).
    """
    return [
        (
            "M6.1 the outcome literal loses `balanced`",
            SRC,
            _OUTCOME_TYPE,
            'RebalancingOutcome = Literal["rebalance"]',
        ),
        (
            "M6.2 the outcome literal loses `rebalance`",
            SRC,
            _OUTCOME_TYPE,
            'RebalancingOutcome = Literal["balanced"]',
        ),
        (
            "M6.3 the outcome literal loses `rebalance_mildly` (extra member exists)",
            SRC,
            _OUTCOME_TYPE,
            'RebalancingOutcome = Literal["balanced", "rebalance", "rebalance_mildly"]',
        ),
        (
            "M6.4 the direction literal loses `under`",
            SRC,
            _DIRECTION_TYPE,
            'DriftDirection = Literal["over"]',
        ),
        (
            "M6.5 the outcome branch is inverted (balanced when drifted)",
            SRC,
            _OUTCOME_ASSIGN,
            '    outcome: RebalancingOutcome = "balanced" if drifted else "rebalance"',
        ),
        (
            "M6.6 the outcome is hardcoded to `balanced`",
            SRC,
            _OUTCOME_ASSIGN,
            '    outcome: RebalancingOutcome = "balanced"',
        ),
    ]


def _published_mutations() -> list[tuple[str, Path, str, str]]:
    """The published ``value``.

    Two of these are semantic rather than cosmetic and deserve naming:
    ``M7.2`` publishes the *target* list under ``drifted_instruments`` -- a
    value an operator would read as "these are the ones out of line", which is
    the opposite of the truth on a balanced book. ``M7.3`` reports the count of
    instruments *evaluated* under the *drifted* key.
    """
    mutations: list[tuple[str, Path, str, str]] = [
        (
            "M7.1 the worst-drift row is chosen by SIGNED rather than absolute drift",
            SRC,
            _WORST_ROW,
            '        worst = max(drifted, key=lambda d: float(d["signed_drift"]))',
        ),
        (
            "M7.2 drifted_instruments publishes the TARGET list, not the drifted ones",
            SRC,
            _DRIFTED_INSTRUMENTS,
            '            "drifted_instruments": [t.instrument for t in targets],',
        ),
        (
            "M7.3 instruments_evaluated counts the drifted rows instead",
            SRC,
            _INSTRUMENTS_EVALUATED,
            '            "instruments_evaluated": len(drifted),',
        ),
        (
            "M7.4 the total contribution is published as a percent",
            SRC,
            _TOTAL_PUBLISHED,
            '            "total_current_contribution": round(total_actual * 100.0, 6),',
        ),
    ]
    for key, line in _PUBLISHED_KEYS.items():
        renamed = line.replace(f'"{key}"', f'"{key}_v2"')
        mutations.append(
            (
                f"M7.5 the published key {key!r} is renamed",
                SRC,
                line,
                renamed,
            )
        )
    return mutations


def _shared_join_mutation() -> list[tuple[str, Path, str, str]]:
    """``seen`` must be the join key between the two scans, not a local count.

    Not a defect repair -- a **structural** mutation. If ``seen`` stops being
    the thing both the per-target loop and the set difference consult, the two
    halves of the function can disagree about which instruments exist, and the
    ``unbudgeted`` set silently becomes a statement about nothing.
    """
    return [
        (
            "M8.1 `seen` is reset each iteration (only the LAST target ever counts as budgeted)",
            SRC,
            _LOOP_GET,
            (
                "        seen.add(target.instrument)\n"
                "        seen = {target.instrument}\n"
                "        actual = current_contributions.get(target.instrument, 0.0)"
            ),
        )
    ]


def _warning_mutations() -> list[tuple[str, Path, str, str]]:
    """The disclosures. Each branch deleted, never a wording change.

    The project's standing position (D-049, D-050) is that warning *text* is not
    the safety mechanism -- the warning *branch* is. Wording mutants are
    therefore not in this sweep: they are not expected to be killed, and
    counting them would inflate the denominator with mutations nobody wants a
    test for.

    ``M9.3`` deletes the sum-to-one warning, which is the ONLY thing that tells
    a caller their dollar figures were read as shares. The arithmetic beneath it
    is unchanged, so a test that only checks the drift rows cannot kill it.
    """
    return [
        (
            "M9.2 the maintenance-separation warning list is emptied",
            SRC,
            _WARNING_MAINTENANCE,
            (
                "    warnings: list[str] = []\n"
                "    _maintenance: list[str] = [\n"
                '        "This is PORTFOLIO risk-budget maintenance, NOT a thesis-validity check. "'
            ),
        ),
        (
            "M9.3 the sum-to-one warning branch is deleted",
            SRC,
            _WARNING_SUM,
            "    if False:",
        ),
        (
            "M9.4 the unbudgeted-instruments warning branch is deleted",
            SRC,
            _WARNING_UNBUDGETED,
            "    if False:",
        ),
        (
            "M9.5 the missing-instruments warning branch is deleted",
            SRC,
            _WARNING_MISSING,
            "    if False:",
        ),
    ]


def _contract_mutations() -> list[tuple[str, Path, str, str]]:
    """The contract: ``extra="forbid"``, identity, ``inputs_used``, the context."""
    return [
        (
            "M10.1 extra=forbid is dropped from RiskBudgetTarget",
            SRC,
            _TARGET_MODEL_CONFIG,
            '    model_config = ConfigDict(extra="allow")\n\n    instrument: str = Field(',
        ),
        (
            "M10.2 the model name changes",
            SRC,
            _MODEL_NAME,
            '        model_name="drift_check",',
        ),
        (
            "M10.3 inputs_used names a published key instead of the raw inputs",
            SRC,
            _INPUTS_USED,
            '        inputs_used=["drifted_instruments"],',
        ),
        (
            "M10.4 the structural-separation context is emptied",
            SRC,
            _CONTEXT,
            '            ""',
        ),
    ]


def _confidence_mutations() -> list[tuple[str, Path, str, str]]:
    """Section 22.8: ``compute_confidence`` is the ONLY producer.

    ``M11.1`` hardcodes the number the stated facts happen to produce on a clean
    book, so it is invisible to any test that does not make a *flag move it*.
    ``M11.2`` is the sharper one: it breaks the coupling between the published
    flag and the confidence input, so a missing instrument degrades the output
    without degrading the stated confidence in it.
    """
    return [
        (
            "M11.1 confidence is hardcoded to the clean-book value",
            SRC,
            (
                "    confidence = compute_confidence(\n"
                "        ConfidenceInputs(\n"
                "            data_quality_flags_present=bool(missing),\n"
                "            # The threshold is a stated convention, not a fitted estimate.\n"
                "            is_heuristic_not_calibrated=True,\n"
                "            depends_on_unobservable=False,\n"
                "        )\n"
                "    )"
            ),
            "    confidence = 0.5",
        ),
        (
            "M11.2 a data-quality flag no longer moves the confidence input",
            SRC,
            _QUALITY_FLAG,
            _QUALITY_WITH_FALSE,
        ),
        (
            "M11.3 the heuristic marker is switched off (confidence rises to base)",
            SRC,
            _HEURISTIC_TRUE,
            _HEURISTIC_FALSE,
        ),
    ]


def _config_mutations() -> list[tuple[str, Path, str, str]]:
    """``config.py``: the accessor and the leaf's presence.

    ``CX1`` hardcodes the shipped value in the accessor. That is the D-050
    failure mode exactly -- a test asserting the shipped constant cannot see a
    literal -- and only the mutate-the-leaf-then-re-read test kills it. ``CX2``
    deletes the field, which the settings model's ``extra="forbid"`` must catch
    as an unknown-key error rather than a silently-dropped value.
    """
    return [
        (
            "CX1 the accessor hardcodes the shipped value instead of reading the leaf",
            CONFIG,
            _CFG_ACCESSOR_BODY,
            "        return 0.10",
        ),
        (
            "CX2 the accessor reads a different leaf (stress_correlation)",
            CONFIG,
            _CFG_ACCESSOR_BODY,
            "        return float(self.stress_correlation.value)",
        ),
        (
            "CX3 the accessor drops the float() cast",
            CONFIG,
            _CFG_ACCESSOR_BODY,
            "        return self.rebalancing_drift.value",
        ),
    ]


def _control_mutation() -> list[tuple[str, Path, str, str]]:
    """The honesty control. MUST survive.

    ``abs(signed) > threshold`` re-spelled with a redundant float literal is the
    same comparison on the same values, so it cannot change behaviour. If the
    sweep reports this killed, the sweep is reporting kills it cannot justify
    and no other number it prints can be trusted. (D-051's first draft reported a
    false 56/56 against a control; this is that lesson, carried.)

    The control is a *semantic* identity claim, not a string that rewrites to
    itself -- ``check_targets`` refuses the latter as INERT BY CONSTRUCTION.
    """
    return [
        (
            "M9.1 the strict comparison is re-spelled with a literal, semantically identical",
            SRC,
            _DRIFT_COMPARE,
            "        if abs(signed) > (threshold):",
        )
    ]


def build_mutations() -> list[Mutation]:
    raw = [
        *_missing_instrument_mutations(),
        *_unbudgeted_mutations(),
        *_threshold_mutations(),
        *_boundary_mutations(),
        *_arithmetic_mutations(),
        *_outcome_mutations(),
        *_published_mutations(),
        *_shared_join_mutation(),
        *_warning_mutations(),
        *_contract_mutations(),
        *_confidence_mutations(),
        *_config_mutations(),
        *_control_mutation(),
    ]
    return [
        Mutation(
            group=name.split()[0],
            name=name,
            path=path,
            old=old,
            new=new,
            intent="",
            # The control must carry its flag through. D-054's first run dropped
            # it here -- `build_mutations` reconstructed every Mutation from the
            # 4-tuple and silently discarded `expect_killed` -- so a
            # semantically-identical control was reported as an unexplained
            # DEFECT survivor. The survival was correct; the *classification*
            # was a harness bug, and it is the same class as D-051's false
            # 56/56: a harness that cannot tell a control from a defect will
            # mislead about both.
            expect_killed=False if name.startswith("M9.1 ") else None,
        )
        for name, path, old, new in raw
    ]


#: Mutations that cannot be killed because they cannot change behaviour.
#: Every entry must carry a PROOF -- "we could not write a failing test" is not
#: the same claim as "the two programs are equivalent", and only the second
#: belongs here.
#:
#: **D-055 adds the first entry this repository has ever carried**, after three
#: increments (D-053, D-054) shipped this set deliberately EMPTY. The entry is
#: not a concession -- it is a *positive* result: M4.6 was written as a mutation
#: and the probe showed the branch it attacks is unreachable, so the mutation
#: says something true about the function rather than something missing about
#: the tests. D-053 carried the empty-set discipline as O-42; that obligation is
#: discharged by this entry, and the discipline now has a worked example.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M4.6 the direction test is inclusive at zero (a zero drift reads as over)",
        "CX3 the accessor drops the float() cast",
    }
)

#: The proofs that back ``_EXPECTED_INERT``. A name in the set without a proof
#: here is a claim, not a result, and the harness prints them together.
#:
#: **The two proofs are of different strengths, and the difference is stated
#: rather than hidden.** M4.6's is *unconditional*: no input whatsoever can
#: reach the mutated branch. CX3's is *conditional on the shipped configuration*:
#: ``CalibratedValue.value`` is a ``float`` today, so ``float(v) is v`` holds and
#: the cast is the identity -- but a future config that stores the leaf as a
#: string or a ``Decimal`` would make the cast load-bearing again and this proof
#: would evaporate. Both are honest equivalence claims; only one of them is
#: permanent, and a reader deserves to know which is which.
_INERT_PROOFS: dict[str, str] = {
    "M4.6 the direction test is inclusive at zero (a zero drift reads as over)": (
        "UNCONDITIONAL. A drift row is appended ONLY inside "
        "`if abs(signed) > threshold:`, and the guard above it enforces "
        "`threshold > 0.0`. So every row satisfies abs(signed) > threshold > 0, "
        "which excludes signed == 0 from the direction test's input domain "
        "entirely. `signed > 0` and `signed >= 0` are therefore the same "
        "predicate on every reachable input -- the two programs agree on the "
        "whole domain, and the domain is characterisable in one sentence."
    ),
    "CX3 the accessor drops the float() cast": (
        "CONDITIONAL ON THE SHIPPED CONFIG. Probed: the leaf's runtime type is "
        "builtins.float, and `float(v) is v` is True for it, so the cast is the "
        "identity on every value the shipped settings.yaml can produce. The "
        "mutant is therefore unkillable *today*. It is NOT unkillable in "
        "general: the cast is a type contract, and a leaf that ever becomes a "
        "str or Decimal would make it load-bearing and this proof would stop "
        "applying. Recorded as a conditional rather than an unconditional "
        "equivalence because the difference is exactly the kind of thing a "
        "later reader would mistake."
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

    **Every increment since D-048 has had at least one target re-anchored here,
    and this one is no exception:** ``_LOOP_GET`` was originally the bare
    ``actual = current_contributions.get(target.instrument, 0.0)`` line, which
    is unique *today* but sits beside a second ``.get``-shaped read; and
    ``_CONFIG_DEFAULT`` had to be pinned to the config-leaf line rather than the
    ``threshold = (`` block, because ``evaluate_drawdown_rules`` ships a
    structurally identical ``... if X is not None else ...`` expression two
    hundred lines earlier in the same file. Both are the *derived anchor* class
    of D-048, caught before a number was printed.
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

    For this sweep the trap is a near-miss rather than a missing file:
    ``tests/portfolio/test_rebalancing_drift.py`` is a NEW file in a package
    created one increment ago by D-054. A stale ``__init__.py``, a wrong
    directory name or a name that differs from the file by one word would
    collect zero tests from a path that looks entirely plausible.
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
                "tests/portfolio/test_rebalancing_drift.py",
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
            "--no-header",
            "tests/portfolio/test_rebalancing_drift.py",
            "tests/test_infrastructure.py",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the tests, restore the file. Foreground only.

    The restore reads from the in-memory ``original`` rather than a backup file.
    An earlier version copied to a temp file first and Windows refused the
    cleanup (``WinError 32``, the file still held by a process), which aborted
    the sweep after its first mutation. The in-memory restore is not merely
    simpler: it is what makes the ``finally`` unconditional, so a crash inside
    ``run_pytest`` still puts the shipped source back. A sweep that can leave
    ``src/`` mutated is the D-049 failure mode with extra steps.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M4")
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("mutation sweep: check_rebalancing_drift (Module 17.3, Section 15.18, D-055)")
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
