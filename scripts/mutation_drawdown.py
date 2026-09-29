"""Mutation sweep for ``evaluate_drawdown_rules`` (Module 17.3, Section 6.6c, D-054).

**Run this in the FOREGROUND ONLY.** The sweep rewrites ``risk_budget.py`` and
``config.py`` in place, so any concurrent test run, live check or probe reads a
mutated module. D-047's Postscript 2 records a contaminated reading produced
exactly that way, and D-049 left the source mutated when its sweep was killed
mid-run -- the full suite then passed *with the mutation in place*. The blast
radius is the whole repository.

Why this function's sweep is shaped differently from D-050's
-------------------------------------------------------------
``four_pillar_scorecard`` (D-050) and ``classify_convergence`` (D-051) both had
an **enumerable** output space, so their mutations were derived from that space.
This function's state space is *continuous* -- it takes two floats -- but its
*decision* space is tiny: one scalar comparison against three thresholds, and a
max over the triggered set. So the mutations below are not derived from an
enumeration. They are named after **the five defects the module docstring
records**, and each group is the repair of one defect. When a mutation survives,
its group names the defect whose repair no test pins. That is the same
discipline D-051's sweep adopted, and for the same reason: it is the grouping,
not the count, that tells you what is missing (D-031).

The one thing this sweep would NOT have found
----------------------------------------------
**Defect 1 is invisible to mutation testing of this module.** The unit mismatch
(spec fractions vs config percents) lives in ``_tiers()`` -- and a mutated
``_tiers()`` that returns percent-scale rules is *still a deterministic ladder*.
Every outcome test written against a fraction-scale fixture passes, because the
fixture bypasses the config path. ``M1.2`` and ``M1.3`` below attack
``_tiers()`` anyway, and they are killed only because
``test_the_default_tiers_are_fractions_not_percents`` reads the *shipped* config
through the *shipped* loader and asserts the reachable outcome set. That is the
test worth protecting: if the sweep ever reports ``M1.*`` survivors, the unit
convention has lost its only guard.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. This is the control whose absence let
D-051's first draft report a false 56/56.
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
#: ``tests/test_infrastructure.py`` is included because the three ``config.py``
#: mutants land on ``DrawdownTier`` and ``RiskSettings.drawdown_tiers``, and that
#: file is where the shipped YAML's round-trip is asserted. (It is also where
#: ``drawdown_thresholds`` was already touched with a different payload shape --
#: the reason the shipped block never parsed through the accessor.)
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention the other sweeps in
#: this directory follow.
PYTEST_TARGETS = [
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
# Transcribed targets. Every one of these is a byte-for-byte copy of text in
# the shipped source; check_targets refuses to run if any has drifted.
# ---------------------------------------------------------------------------

# --- risk_budget.py, Defect 1: the unit conversion boundary ----------------

_TIERS_THRESHOLD = "            threshold_pct=float(tier.drawdown_pct) / 100.0,"
_TIERS_REDUCTION = "            risk_reduction_pct=float(tier.risk_reduction_pct) / 100.0,"
_TIERS_SORT = "        for tier in settings.risk.drawdown_tiers"

# --- risk_budget.py, Defect 2: the rule bounds -----------------------------

_RULE_THRESHOLD_FIELD = "    threshold_pct: float = Field(\n        gt=0.0,\n        le=1.0,"
_RULE_REDUCTION_FIELD = "    risk_reduction_pct: float = Field(\n        gt=0.0,\n        le=1.0,"

# --- risk_budget.py, Defect 3: the ordering claim --------------------------

_TRIGGERED = "    triggered = [rule for rule in rules if drawdown_pct >= rule.threshold_pct]"
_BOUNDARY = "if drawdown_pct >= rule.threshold_pct"
_RETURN_NONE = "    if not triggered:\n        return None"

# --- risk_budget.py, Defect 4: severity vs threshold -----------------------

_MAX_SEVERITY = "    return max(triggered, key=lambda rule: rule.risk_reduction_pct)"

# --- risk_budget.py, Defect 5: the ambiguous 0.0 ---------------------------

_OUTCOME_TYPE = 'RuleOutcome = Literal["no_action", "reduce_risk", "stop_trading"]'
_NO_ACTION_ASSIGN = '        outcome: RuleOutcome = "no_action"'
_STOP_GATE = '        outcome = "stop_trading" if reduction >= 1.0 else "reduce_risk"'
_ZERO_REDUCTION = "        reduction = 0.0"

# --- risk_budget.py, the drawdown derivation ------------------------------

_DRAWDOWN = "        return (self.high_water_mark - self.current_value) / self.high_water_mark"
_HWM_BOUND = "    high_water_mark: float = Field(\n        gt=0.0,"

# --- risk_budget.py, the published value -----------------------------------

_PUBLISHED_BLOCK = (
    '            "risk_reduction_fraction": round(reduction, 6),\n'
    '            "outcome": outcome,\n'
    '            "drawdown_fraction": round(drawdown, 6),\n'
    '            "triggered_threshold_fraction": (\n'
    "                round(trigger.threshold_pct, 6) if trigger is not None else None\n"
    "            ),"
)

_PUBLISHED_KEYS: dict[str, str] = {
    "risk_reduction_fraction": '            "risk_reduction_fraction": round(reduction, 6),',
    # `"outcome": outcome,` appears once per classifier in risk_budget.py
    # (drawdown and rebalancing), so the anchor is extended through the key that
    # precedes it, which is drawdown-specific. D-060's audit found this AMBIGUOUS
    # and the sweep REFUSED TO RUN; sweep_health.py now reports it.
    "outcome": (
        '            "risk_reduction_fraction": round(reduction, 6),\n'
        '            "outcome": outcome,'
    ),
    "drawdown_fraction": '            "drawdown_fraction": round(drawdown, 6),',
}

_TIERS_TRIGGERED = (
    '            "tiers_triggered": sum(1 for rule in resolved if drawdown >= rule.threshold_pct),'
)

# --- risk_budget.py, the configured default ---------------------------------
#
# Anchored on ``drawdown = state.drawdown_pct`` as well as the assignment,
# because ``resolve_drawdown_rule`` ships the SAME ``if rules is None`` two-liner.
# Without the anchor, ``str.replace`` would rewrite ``resolve_drawdown_rule``'s
# default instead -- which is a legal mutation of a different function, and the
# sweep would report a survival about code nobody mutated.

_RESOLVE_DEFAULT = (
    "    resolved = rules if rules is not None else _tiers()\n    drawdown = state.drawdown_pct"
)

# --- risk_budget.py, the warnings ------------------------------------------

# `warnings: list[str] = [` appears five times in risk_budget.py -- once per
# function. Anchored through the drawdown-specific first warning.
_WARNING_CONVICTION = (
    "    warnings: list[str] = [\n"
    '        "This overrides thesis conviction — a thesis believed correct does NOT "'
)
_WARNING_NEGATIVE_EQ = "    if drawdown > 1.0:"
_WARNING_ABOVE_HWM = "    if drawdown < 0.0:"
_WARNING_CALLER = "    if rules is not None:"

# --- risk_budget.py, the contract / identity / confidence ------------------

_STATE_CONFIG = '    model_config = ConfigDict(extra="forbid")\n\n    high_water_mark: float = Field(\n        gt=0.0,'
_MODEL_NAME = '        model_name="drawdown_rule_check",'
# `country="us",` appears five times in risk_budget.py; anchored through the
# model name that precedes it.
_COUNTRY = '        model_name="drawdown_rule_check",\n        country="us",'
_INPUTS_USED = '        inputs_used=["high_water_mark", "current_value"],'

_HEURISTIC = (
    "            data_quality_flags_present=False,\n"
    "            # The tiers are a stated convention, not a calibrated estimate, so\n"
    "            # the heuristic marker is set. This is the honest reading: nothing\n"
    "            # in this function was fitted to data.\n"
    "            is_heuristic_not_calibrated=True,"
)
_HEURISTIC_OFF = (
    "            data_quality_flags_present=False,\n            is_heuristic_not_calibrated=False,"
)
# `depends_on_unobservable=False,` also appears five times in risk_budget.py, and
# `is_heuristic_not_calibrated=True,` alone is not distinguishing. The anchor is
# therefore `_HEURISTIC` plus the line below it: the comment block inside
# `_HEURISTIC` is drawdown-specific.
_UNOBSERVABLE = _HEURISTIC + "\n            depends_on_unobservable=False,"

# --- config.py, the DrawdownTier guard and the accessor --------------------

_CFG_FLOOR_DRAWDOWN = (
    "        if self.drawdown_pct < _MIN_DRAWDOWN_TIER_PCT:\n"
    "            raise ValueError(\n"
    '                f"drawdown tier {self.drawdown_pct} is below "'
)
_CFG_FLOOR_REDUCTION = (
    "        if self.risk_reduction_pct < _MIN_RISK_REDUCTION_PCT:\n"
    "            raise ValueError(\n"
    '                f"risk_reduction_pct {self.risk_reduction_pct} is below "'
)
_CFG_TIER_UPPER = "    drawdown_pct: float = Field(gt=0.0, le=100.0)"
_CFG_ACCESSOR_SORT = "        return sorted(tiers, key=lambda t: t.drawdown_pct)"
# The accessor was hardened with a default (`get("tiers", [])`) so a settings
# block that omits the key yields the empty ladder rather than a `KeyError`
# traceback. The mutation surface is unchanged — "stop reading the YAML" is
# still what CX5 asserts — so the anchor tracks the current default form. When
# this anchor was left in its pre-default form it matched 0 occurrences, and a
# sweep reporting `target ABSENT` cannot detect the mutant it exists to kill
# (O-95).
_CFG_ACCESSOR_READS = '        raw = self.drawdown_thresholds.get("tiers", [])'


# ---------------------------------------------------------------------------
# The mutations
# ---------------------------------------------------------------------------


def _unit_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 1's repair: the 100x unit boundary.

    These are the mutations that matter most, and they are the ones the harness
    would NOT catch on its own. A percent-scale ladder is still a deterministic
    ladder, so every outcome test built on a fraction fixture passes regardless.
    Only ``test_the_default_tiers_are_fractions_not_percents`` -- which reads the
    shipped config through the shipped loader -- fails. If a mutation in this
    group survives, that test has been weakened.
    """
    return [
        (
            "M1.1 the config's percent is not converted to a fraction",
            SRC,
            _TIERS_THRESHOLD,
            "            threshold_pct=float(tier.drawdown_pct),",
        ),
        (
            "M1.2 only the reduction is converted, the threshold is not",
            SRC,
            _TIERS_REDUCTION,
            "            risk_reduction_pct=float(tier.risk_reduction_pct),",
        ),
        (
            "M1.3 the conversion is applied twice (100x too small)",
            SRC,
            _TIERS_THRESHOLD,
            "            threshold_pct=float(tier.drawdown_pct) / 10000.0,",
        ),
        (
            "M1.4 the accessor is bypassed and the raw YAML dict is read",
            SRC,
            _TIERS_SORT,
            "        for tier in settings.risk.drawdown_thresholds.get('tiers', [])",
        ),
    ]


def _bound_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 2's repair: ``(0, 1]`` on both rule fields.

    An unbounded ``float`` accepts ``5.0`` ("remove 500% of the risk") and
    ``-1.0`` ("add risk"), and the function would publish either as a mechanical
    de-risking instruction.
    """
    return [
        (
            "M2.1 the threshold's bounds are removed",
            SRC,
            _RULE_THRESHOLD_FIELD,
            "    threshold_pct: float = Field(\n        gt=-1e9,\n        le=1e9,",
        ),
        (
            "M2.2 the reduction's upper bound is removed (a 500% reduction loads)",
            SRC,
            _RULE_REDUCTION_FIELD,
            "    risk_reduction_pct: float = Field(\n        gt=0.0,\n        le=1e9,",
        ),
        (
            "M2.3 the reduction's lower bound is removed (a NEGATIVE reduction loads)",
            SRC,
            _RULE_REDUCTION_FIELD,
            "    risk_reduction_pct: float = Field(\n        gt=-1e9,\n        le=1.0,",
        ),
    ]


def _ordering_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 3's repair: the result is invariant, not order-dependent.

    Each of these makes the answer depend on the rule list's order, which the
    shipped implementation does not. ``M3.4`` is the one to watch: mutating
    ``>=`` to ``>`` moves every boundary by an epsilon, which no test over
    non-boundary draws would notice.
    """
    return [
        (
            "M3.1 first-match wins instead of the most severe",
            SRC,
            _MAX_SEVERITY,
            "    return triggered[0]",
        ),
        (
            "M3.2 the least severe triggered rule wins",
            SRC,
            _MAX_SEVERITY,
            "    return min(triggered, key=lambda rule: rule.risk_reduction_pct)",
        ),
        (
            "M3.3 the rules are iterated in the order supplied, taking the last",
            SRC,
            _MAX_SEVERITY,
            "    return triggered[-1]",
        ),
        (
            "M3.4 the threshold comparison is strict (`>` not `>=`)",
            SRC,
            _TRIGGERED,
            "    triggered = [rule for rule in rules if drawdown_pct > rule.threshold_pct]",
        ),
        (
            "M3.5 the comparison is inclusive on the WRONG side (threshold >= drawdown)",
            SRC,
            _BOUNDARY,
            "if rule.threshold_pct >= drawdown_pct",
        ),
        (
            "M3.6 the empty-trigger guard returns the first rule instead of None",
            SRC,
            _RETURN_NONE,
            "    if not triggered:\n        return rules[0] if rules else None",
        ),
    ]


def _severity_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 4: severity-max vs threshold-max.

    The shipped ladder is monotone in both fields, so the two agree on every
    triggered subset of the *default* set -- which is why a test over the
    defaults cannot tell them apart. ``test_an_early_break_implementation_would_disagree``
    is the only test that can kill M4.1, and it needs a caller-supplied
    non-monotone rule set to do it.
    """
    return [
        (
            "M4.1 the key becomes the THRESHOLD rather than the severity",
            SRC,
            _MAX_SEVERITY,
            "    return max(triggered, key=lambda rule: rule.threshold_pct)",
        ),
        (
            "M4.2 the key becomes the rule's position in the list",
            SRC,
            _MAX_SEVERITY,
            "    return max(triggered, key=lambda rule: rules.index(rule))",
        ),
    ]


def _outcome_mutations() -> list[tuple[str, Path, str, str]]:
    """Defect 5's repair: the ambiguous ``0.0``.

    ``risk_reduction_fraction == 0.0`` is produced both by "nothing triggered"
    and (were the contract weaker) by "a rule prescribed no reduction". Each
    mutation collapses a distinction the ``RuleOutcome`` literal exists to keep.
    ``M5.3`` is the one with consequences: dropping ``stop_trading`` makes a full
    stop-out indistinguishable from a partial de-risking.
    """
    return [
        (
            "M5.1 the outcome literal loses `stop_trading`",
            SRC,
            _OUTCOME_TYPE,
            'RuleOutcome = Literal["no_action", "reduce_risk"]',
        ),
        (
            "M5.2 the outcome literal loses `no_action`",
            SRC,
            _OUTCOME_TYPE,
            'RuleOutcome = Literal["reduce_risk", "stop_trading"]',
        ),
        (
            "M5.3 the stop-trading gate fires at 0.99 instead of 1.0",
            SRC,
            _STOP_GATE,
            '        outcome = "stop_trading" if reduction >= 0.99 else "reduce_risk"',
        ),
        (
            "M5.4 the no-trigger branch reports `reduce_risk` rather than `no_action`",
            SRC,
            _NO_ACTION_ASSIGN,
            '        outcome: RuleOutcome = "reduce_risk"',
        ),
        (
            "M5.5 the no-trigger reduction returns 1.0 instead of 0.0",
            SRC,
            _ZERO_REDUCTION,
            "        reduction = 1.0",
        ),
    ]


def _derivation_mutations() -> list[tuple[str, Path, str, str]]:
    """The drawdown arithmetic itself, and the ``hwm > 0`` bound.

    ``M6.1`` inverts the sign, which is the single most consequential arithmetic
    error available here: a gain would read as a loss and the ladder would
    de-risk into a rally. ``M6.3`` moves the division by the wrong operand.
    """
    return [
        (
            "M6.1 the drawdown's sign is inverted (a gain reads as a loss)",
            SRC,
            _DRAWDOWN,
            "        return (self.current_value - self.high_water_mark) / self.high_water_mark",
        ),
        (
            "M6.2 the drawdown is max'd at zero (a new high is no longer disclosed)",
            SRC,
            _DRAWDOWN,
            (
                "        return max(0.0, (self.high_water_mark - self.current_value) "
                "/ self.high_water_mark)"
            ),
        ),
        (
            "M6.3 the drawdown is divided by the CURRENT value, not the peak",
            SRC,
            _DRAWDOWN,
            "        return (self.high_water_mark - self.current_value) / self.current_value",
        ),
        (
            "M6.4 the high-water-mark positivity bound is removed",
            SRC,
            _HWM_BOUND,
            "    high_water_mark: float = Field(\n        gt=-1e9,",
        ),
    ]


def _published_mutations() -> list[tuple[str, Path, str, str]]:
    """The published ``value``.

    Several keys decide the reading, so a rename is not cosmetic:
    ``triggered_threshold_fraction`` reports the rung's *threshold* while sitting
    under a key that says so, and ``M7.1`` makes it report the *reduction*
    instead -- two different quantities an operator would read identically.
    """
    mutations: list[tuple[str, Path, str, str]] = [
        (
            "M7.1 triggered_threshold_fraction reports the REDUCTION instead",
            SRC,
            _PUBLISHED_BLOCK,
            (
                '            "risk_reduction_fraction": round(reduction, 6),\n'
                '            "outcome": outcome,\n'
                '            "drawdown_fraction": round(drawdown, 6),\n'
                '            "triggered_threshold_fraction": (\n'
                "                round(trigger.risk_reduction_pct, 6) if trigger is not None else None\n"
                "            ),"
            ),
        ),
        (
            "M7.2 tiers_triggered counts the rules EVALUATED, not triggered",
            SRC,
            _TIERS_TRIGGERED,
            '            "tiers_triggered": sum(1 for rule in resolved if True),',
        ),
    ]
    for key, line in _PUBLISHED_KEYS.items():
        mutations.append(
            (
                f"M7.3 the published key {key!r} is renamed",
                SRC,
                line,
                line.replace(f'"{key}"', f'"{key}_v2"'),
            )
        )
    return mutations


def _resolve_default_mutation() -> list[tuple[str, Path, str, str]]:
    """The configured ladder must be the DEFAULT, not something a caller opts into."""
    return [
        (
            "M8.1 an omitted rule list means NO rules rather than the config",
            SRC,
            _RESOLVE_DEFAULT,
            (
                "    resolved = rules if rules is not None else []\n"
                "    drawdown = state.drawdown_pct"
            ),
        )
    ]


def _warning_mutations() -> list[tuple[str, Path, str, str]]:
    """The disclosures. Each branch deleted, never a wording change.

    The project's standing position (D-049, D-050) is that warning *text* is not
    the safety mechanism -- the warning *branch* is. Wording mutants are
    therefore not in this sweep at all: they are not expected to be killed and
    counting them would inflate the denominator with mutations nobody wants a
    test for.
    """
    return [
        (
            "M9.2 the conviction-override warning list is emptied",
            SRC,
            _WARNING_CONVICTION,
            (
                "    warnings: list[str] = []\n"
                "    _conviction: list[str] = [\n"
                '        "This overrides thesis conviction — a thesis believed correct does NOT "'
            ),
        ),
        (
            "M9.3 the negative-equity warning branch is deleted",
            SRC,
            _WARNING_NEGATIVE_EQ,
            "    if False:",
        ),
        (
            "M9.4 the above-high-water-mark warning branch is deleted",
            SRC,
            _WARNING_ABOVE_HWM,
            "    if False:",
        ),
        (
            "M9.5 the caller-supplied-rules warning branch is deleted",
            SRC,
            _WARNING_CALLER,
            "    if False:",
        ),
    ]


def _contract_mutations() -> list[tuple[str, Path, str, str]]:
    """The contract: ``extra="forbid"``, the model identity, ``inputs_used``."""
    return [
        (
            "M10.1 extra=forbid is dropped from DrawdownState",
            SRC,
            _STATE_CONFIG,
            '    model_config = ConfigDict(extra="allow")\n\n    high_water_mark: float = Field(\n        gt=0.0,',
        ),
        (
            "M10.2 the model name changes",
            SRC,
            _MODEL_NAME,
            '        model_name="drawdown_ladder",',
        ),
        (
            "M10.3 the country label changes",
            SRC,
            _COUNTRY,
            '        model_name="drawdown_rule_check",\n        country="uk",',
        ),
        (
            "M10.4 inputs_used names a derived quantity instead of the raw fields",
            SRC,
            _INPUTS_USED,
            '        inputs_used=["drawdown_fraction"],',
        ),
    ]


def _confidence_mutations() -> list[tuple[str, Path, str, str]]:
    """Section 22.8: ``compute_confidence`` is the ONLY producer.

    ``M11.1`` is the specification's own sketch -- it hardcoded ``0.7`` -- so
    this mutation restores the defect verbatim. ``M11.2`` suppresses the
    heuristic marker, which raises the number to the base without any fact
    changing.
    """
    return [
        (
            "M11.1 confidence is hardcoded to the spec sketch's literal",
            SRC,
            (
                "    confidence = compute_confidence(\n"
                "        ConfidenceInputs(\n"
                "            data_quality_flags_present=False,\n"
                "            # The tiers are a stated convention, not a calibrated estimate, so\n"
                "            # the heuristic marker is set. This is the honest reading: nothing\n"
                "            # in this function was fitted to data.\n"
                "            is_heuristic_not_calibrated=True,\n"
                "            depends_on_unobservable=False,\n"
                "        )\n"
                "    )"
            ),
            "    confidence = 0.7",
        ),
        (
            "M11.2 the heuristic marker is switched off (confidence rises to base)",
            SRC,
            _HEURISTIC,
            _HEURISTIC_OFF,
        ),
        (
            "M11.3 an unobservable-dependence penalty is applied",
            SRC,
            _UNOBSERVABLE,
            _UNOBSERVABLE.replace("depends_on_unobservable=False", "depends_on_unobservable=True"),
        ),
    ]


def _config_mutations() -> list[tuple[str, Path, str, str]]:
    """``config.py``: the fraction-scale guard and the accessor.

    ``CX1``/``CX2`` are the guard that makes the file's percent convention
    *checkable* -- the only thing in the repository that catches a 100x error at
    load time. ``CX4`` removes the sort, which the shipped file cannot detect
    because it happens to be sorted already.
    """
    return [
        (
            "CX1 the drawdown-tier magnitude floor is removed",
            CONFIG,
            _CFG_FLOOR_DRAWDOWN,
            "        if False:\n            raise ValueError(\n"
            '                f"drawdown tier {self.drawdown_pct} is below "',
        ),
        (
            "CX2 the risk-reduction magnitude floor is removed",
            CONFIG,
            _CFG_FLOOR_REDUCTION,
            "        if False:\n            raise ValueError(\n"
            '                f"risk_reduction_pct {self.risk_reduction_pct} is below "',
        ),
        (
            "CX3 the tier's upper bound is removed",
            CONFIG,
            _CFG_TIER_UPPER,
            "    drawdown_pct: float = Field(gt=0.0, le=1e9)",
        ),
        (
            "CX4 the accessor stops sorting (file order leaks through)",
            CONFIG,
            _CFG_ACCESSOR_SORT,
            "        return tiers",
        ),
        (
            "CX5 the accessor stops reading the YAML and hardcodes the shipped tiers",
            CONFIG,
            _CFG_ACCESSOR_READS,
            (
                "        raw = [\n"
                '            {"drawdown_pct": 10.0, "risk_reduction_pct": 50.0},\n'
                '            {"drawdown_pct": 15.0, "risk_reduction_pct": 75.0},\n'
                '            {"drawdown_pct": 20.0, "risk_reduction_pct": 100.0},\n'
                "        ]"
            ),
        ),
    ]


def _control_mutation() -> list[tuple[str, Path, str, str]]:
    """The honesty control. MUST survive.

    ``drawdown > 1.0`` re-spelled as ``drawdown > 1.00`` is the same comparison
    on the same float, so it cannot change behaviour. If the sweep reports this
    killed, the sweep is reporting kills it cannot justify and no other number it
    prints can be trusted. (D-051's first draft reported a false 56/56 against a
    control; this is that lesson, carried.)

    The wording-warning mutant has been deliberately LEFT OUT. An earlier draft
    of ``_warning_mutations`` contained a mutation whose ``old`` and ``new`` were
    identical -- inert by construction rather than merely by behaviour -- and
    ``check_targets`` refuses those. A control must be a *semantic* identity
    claim, not a string that rewrites to itself.
    """
    return [
        (
            "M9.1 the negative-equity bound is re-spelled, semantically identical",
            SRC,
            _WARNING_NEGATIVE_EQ,
            "    if drawdown > 1.00:",
        )
    ]


def build_mutations() -> list[Mutation]:
    raw = [
        *_unit_mutations(),
        *_bound_mutations(),
        *_ordering_mutations(),
        *_severity_mutations(),
        *_outcome_mutations(),
        *_derivation_mutations(),
        *_published_mutations(),
        *_resolve_default_mutation(),
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
            # The control must carry its flag through. The FIRST run of this
            # sweep dropped it here -- `build_mutations` reconstructed every
            # Mutation from the 4-tuple and silently discarded `expect_killed`
            # -- so the semantically-identical control was reported as an
            # unexplained DEFECT survivor. The survival was correct; the
            # *classification* was a harness bug, and it is the same class as
            # D-051's false 56/56: a harness that cannot tell a control from a
            # defect will mislead about both.
            expect_killed=False if name.startswith("M9.1 ") else None,
        )
        for name, path, old, new in raw
    ]


#: Mutations that cannot be killed because they cannot change behaviour.
#: Every entry must carry a PROOF -- "we could not write a failing test" is not
#: the same claim as "the two programs are equivalent", and only the second
#: belongs here.
#:
#: **This set is deliberately EMPTY**, and that is a stronger statement than a
#: populated one: nothing in this increment is excused from having a test. D-053
#: took the same position and carried it as O-42, because nothing in the harness
#: enforces the discipline -- only the reviewer does. The control (M9.1) is
#: handled by ``expect_killed=False`` instead, because a control is not inert: it
#: is *equivalent*, and its survival is evidence about the harness rather than
#: about the code.
_EXPECTED_INERT: frozenset[str] = frozenset()


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048, and this is the gate that makes the rest of the sweep mean
    anything. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` string appearing twice silently rewrites the wrong site and the sweep
    then reports a surviving test -- a conclusion about code nobody mutated. An
    ``old`` appearing zero times means the target has drifted and the mutation is
    not testing what its name says.

    **D-054 is the third increment in a row where this gate earned its place.**
    Two distinct targets in this sweep had to be re-anchored during authoring --
    ``_MAX_SEVERITY``'s sibling in ``resolve_drawdown_rule`` duplicated the
    trigger comprehension, so ``_TRIGGERED`` was ambiguous until it was anchored
    on its own leading whitespace. And at CLOSE, ``ruff format`` reflowed the
    ``_PUBLISHED_BLOCK``. Both were caught here, before a number was printed.
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
    producing a false 56/56. ``tests/test_config.py`` does NOT exist in this
    repository -- the first draft of that sweep named it, and this gate is what
    caught it before a single mutation was applied.

    For this sweep the trap is a near-miss rather than a missing file:
    ``tests/portfolio/`` is a NEW package created by D-054. A stale ``__init__.py``
    or a wrong directory name would collect zero tests from a path that looks
    entirely plausible.
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
                "tests/portfolio/test_risk_budget.py",
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
            "tests/portfolio/test_risk_budget.py",
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


def _insertion_points(text: str) -> list[str]:
    """Every line a mutation could have left behind, for the leftover check."""
    return text.splitlines()


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
    print("mutation sweep: evaluate_drawdown_rules (Module 17.3, Section 6.6c, D-054)")
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
