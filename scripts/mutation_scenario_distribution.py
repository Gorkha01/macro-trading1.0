"""Mutation sweep for ``build_scenario_distribution`` (Module 12, D-064).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/scenarios.py``, ``src/macro_engine/config.py``
and ``src/macro_engine/portfolio/risk_budget.py`` in place, so any concurrent
test run, live check or probe reads a mutated module. The blast radius is the
whole repository.

What this increment is really testing
-------------------------------------
Section 16.4's sample has **four** defects, and two of them are of a kind no
value assertion reaches on its own:

1. **Two branches for a five-member vocabulary.** ``M1`` attacks the partition:
   the ``else`` fall-through restored, ``CONFLICTED`` and ``NO_SIGNAL`` made
   distributable, the empty list replaced by a distribution. The kill is an
   assertion about a state the *consumer* refuses, so the partition is a
   contract between two layers and not a preference.

2. **``convergence: str`` lets a typo through a branch nobody tests.** ``M2``
   removes the boundary parse, and the kill is the ``AttributeError`` that
   replaces a refusal — ``ConvergenceClassification`` inherits from ``str``, so
   a bare ``"HIGH"`` hashes equal to the member and passes membership, then dies
   on ``.value``.

3. **The two-class collision (O-51).** ``M3`` is the only group that can reach
   it, and it does so **structurally** rather than by value: a mutant that
   re-declares a class in the thesis layer, or that drops the re-export, is a
   mutant about the *shape* of the module rather than its arithmetic. The kill
   is the identity test — the producer's object must be the consumer's class.

4. **``gap.unit`` never read.** ``M4`` removes the refusal, which reintroduces
   the silent 100x scaling. The kill is an assertion about a *raised* refusal,
   because the defect's whole character is that the wrong answer is a plausible
   number rather than an error.

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether the probabilities are any good.** Every leaf is
   ``uncalibrated_illustrative`` and Section 16.4 says so. ``M6`` can only prove
   the config leaves are *read*; no mutation makes an illustrative number an
   estimate.

2. **Whether the four branches are the right four.** The branch names come from
   Section 16.4's prose. A missing branch is a specification judgement, not a
   behaviour a mutant can expose.

3. **That the distribution is not Kelly-sizable.** That is a fact about the
   producer's ``bp_pnl_proxy`` declaration meeting the consumer's refusal, pinned
   by a test that reads both vocabularies — not by a mutant. D-064 closed the
   *silent default* that let the mismatch through; ``M7`` pins the mechanism.

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
``build_scenario_distribution`` contains three ``raise ValueError`` blocks whose
bodies are long and similar, so a short fragment from one is *unique* while
sitting in the wrong guard; every anchor here is extended to include its own
condition (**O-67**).
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
SCENARIOS = REPO / "src/macro_engine/thesis_layer/scenarios.py"
SCHEMAS = REPO / "src/macro_engine/thesis_layer/schemas.py"
CONFIG = REPO / "src/macro_engine/config.py"
RISK_BUDGET = REPO / "src/macro_engine/portfolio/risk_budget.py"
PROBABILITY = REPO / "src/macro_engine/models/probability.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/thesis_layer/test_scenario_distribution.py`` carries the behavioural
#: assertions. ``tests/portfolio/test_fractional_kelly.py`` is included because
#: the increment closes the producer/consumer seam (O-51/O-50): a mutation that
#: breaks the unit contract must not be attributed to a gap in the new file.
#: ``tests/thesis_layer/test_invalidation.py`` is included because both modules
#: import the same schemas, so a schema-identity mutation has to be visible here.
PYTEST_TARGETS = [
    "tests/thesis_layer/test_scenario_distribution.py",
    "tests/portfolio/test_fractional_kelly.py",
    "tests/thesis_layer/test_invalidation.py",
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
# Anchors — read out of the shipped source, never transcribed from memory
# ---------------------------------------------------------------------------


def enclosing_symbol(text: str, index: int) -> str:
    """The top-level symbol a character offset falls inside, or ``"<module>"``.

    **Deliberately duplicated from ``tools/sweep_health.py``, not imported.** The
    import was tried first and ``mypy --strict`` refused it:
    ``Source file found twice under different module names: "sweep_health" and
    "tools.sweep_health"`` — because ``tools/`` has no ``__init__.py`` and the
    gate names both ``src tests scripts tools``, adding it to ``sys.path`` made
    one file two modules. The alternative was an ``__init__.py`` in ``tools/``,
    which changes how every other tool is imported to fix one caller. A twelve-line
    pure function is the cheaper duplication, and its test lives in the tool.

    The owner is resolved by **parsing** rather than by walking lines backwards.
    The first implementation of this in the repository pattern-matched
    ``line.startswith(("def ", "class "))``, which is true of a **comment** whose
    first column reads ``def ...``. Concretely, this sweep's own anchor for
    ``KellyPayoffUnit`` resolved to ``volatility_target_scaling`` — a function 150
    lines away that the anchor has nothing to do with — because a comment between
    them mentioned ``def``. The gate then **refused to run** and reported a
    mis-target that did not exist: lesson 80's failure mode, *a gate
    manufacturing findings is worse than no gate* (D-064).

    Parsing also handles the case the line walk could not: an anchor past a
    symbol's ``end_lineno`` belongs to whatever comes next, so a claim of
    ownership cannot leak forward into a neighbouring function.

    ``SyntaxError`` returns ``"<module>"`` rather than raising, because during a
    sweep the text on disk is **temporarily invalid** and the check has to survive
    that rather than crash inside a ``finally`` block.
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


def _slice_source(path: Path, first: str, last: str, *, after: str | None = None) -> str:
    """Return the source text from the line containing ``first`` to ``last``.

    ``after`` scopes the search to a symbol, because ``check_targets`` proves an
    anchor is *unique* and not that it is in the *right function* (**O-67**).
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    base = 0
    if after is not None:
        anchor = next((i for i, ln in enumerate(lines) if after in ln), None)
        if anchor is None:
            raise RuntimeError(f"anchor scope not found in {path.name}: {after!r}")
        base = anchor + 1
    start = next((i for i in range(base, len(lines)) if first in lines[i]), None)
    if start is None:
        raise RuntimeError(f"anchor start not found in {path.name}: {first!r}")
    end = next((i for i in range(start, len(lines)) if last in lines[i]), None)
    if end is None:
        raise RuntimeError(f"anchor end not found in {path.name}: {last!r}")
    return "".join(lines[start : end + 1])


#: The top-level symbols this increment owns in each file.
#:
#: ``<module>`` appears where the anchor is a **module-level constant this
#: increment introduced** rather than a statement inside the function:
#: ``_DISTRIBUTABLE`` and ``_CONVERTIBLE_GAP_UNITS`` in ``scenarios.py``, and
#: ``KellyPayoffUnit`` in ``risk_budget.py``. Those are the increment's own
#: vocabulary — a mutant that widens a *partition constant* is a mutant about
#: this function's contract even though it is not textually inside the function.
#: The rule states that explicitly rather than being loosened to accept anything.
_ALLOWED_ANCHOR_OWNERS: dict[str, frozenset[str]] = {
    "scenarios.py": frozenset({"build_scenario_distribution", "<module>"}),
    "config.py": frozenset({"ScenarioDistributionSettings", "Settings"}),
    "schemas.py": frozenset({"<module>"}),
    "risk_budget.py": frozenset({"KellyInputs", "KellyPayoffUnit", "<module>"}),
    "probability.py": frozenset({"ScenarioOutcome", "PayoffUnit"}),
}

# --- M1: the partition (the fall-through class) -----------------------------
_DISTRIBUTABLE = (
    "        ConvergenceClassification.HIGH,\n"
    "        ConvergenceClassification.MEDIUM,\n"
    "        ConvergenceClassification.LOW,"
)
_EMPTY_RETURN = "    if verdict not in _DISTRIBUTABLE:\n        return []"
_PARSE = "    verdict = ConvergenceClassification(convergence)"

# --- M2: the boundary parse -------------------------------------------------
# (shares `_PARSE` with M1's parse removal; kept in its own group by intent)

# --- M3: the single definition (O-51) ---------------------------------------
_REEXPORT_GAP = "from macro_engine.models.policy_rules import MarketPricingGap as MarketPricingGap"
_REEXPORT_SCENARIO = (
    "from macro_engine.models.probability import ScenarioOutcome as ScenarioOutcome"
)

# --- M4: the unit refusal ---------------------------------------------------
_UNIT_GUARD = "    if gap.unit not in _CONVERTIBLE_GAP_UNITS:"
_CONVERTIBLE = 'frozenset({"%"})'

# --- M5: the magnitude and the zero guard -----------------------------------
_MAGNITUDE = "    magnitude_bp = abs(gap.raw_gap) * settings.bp_per_percent"
_ZERO_GUARD = "    if magnitude_bp == 0.0:"
_MEANINGFUL_GUARD = "    if not gap.is_meaningful:"

# --- M6: the config accessors -----------------------------------------------
_BASE_PROBS = '        return {\n            "HIGH": float(self.base_probability_high.value),'
_SHARES_TAIL = '            "tail_adverse_surprise": float(self.remaining_share_tail.value),'
_BP_PER_PERCENT = "        return float(self.percent_to_bp.value)"
_SUM_GUARD = "        if abs(total - 1.0) > tolerance:"

# --- M7: the payoff wiring --------------------------------------------------
_BASE_MULTIPLE = "            payoff_estimate=magnitude_bp * multiples[_BASE],"
_UNIT_FIELD = (
    '            payoff_estimate=magnitude_bp * multiples[_BASE],\n            unit="bp_pnl_proxy",'
)
_REMAINING = "    remaining = 1.0 - base"

# --- M8: the contract + the honesty control ---------------------------------
# The four-branch return, used by the control. The control must be a *real*
# rewrite that leaves the program's meaning alone: an `old == new` no-op is
# never APPLIED, so it can neither survive nor be killed, and a control that
# cannot fail proves nothing (D-051's 56/56 against a dead control).
_TAIL_DESCRIPTION = (
    '                "Adverse tail: the gap moves against the position by MORE than the "\n'
    '                "whole mispricing. Positive expected value says nothing about "\n'
    '                "surviving this branch (Module 12.4, LTCM 1998)."'
)
_TAIL_CONTROL = (
    '                "Adverse tail: the gap moves against the position by MORE "\n'
    '                "than the whole mispricing. Positive expected value says "\n'
    '                "nothing about surviving this branch (Module 12.4, LTCM 1998)."'
)

# --- M9: the unit seam (O-50) -----------------------------------------------
_UNIT_REQUIRED = "    payoff_unit: KellyPayoffUnit = Field("
_UNIT_REFUSAL = "        if self.payoff_unit != _KELLY_UNIT:"
_UNIT_VOCABULARY = 'KellyPayoffUnit = Literal["bp_pnl_proxy", "fraction_of_capital"]'


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: the partition ---------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 the partition collapses to a fall-through (the spec's two-branch else)",
            path=SCENARIOS,
            old=_DISTRIBUTABLE,
            new="        ConvergenceClassification.LOW,",
            intent=(
                "Restores Section 16.4's `else`: CONFLICTED and NO_SIGNAL now "
                "receive a tradeable distribution. The kill is the consumer's "
                "refusal, so the test must read the contract and not the value."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 the empty return becomes a distribution for every verdict",
            path=SCENARIOS,
            old=_EMPTY_RETURN,
            new="    if False:\n        return []",
            intent=(
                "Every verdict produces four branches, including the two the "
                "vocabulary says cannot carry a thesis. D-052's 'a guard must be "
                "a PARTITION, not a HIT'."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.3 CONFLICTED is added to the distributable set",
            path=SCENARIOS,
            old=_DISTRIBUTABLE,
            new=(
                "        ConvergenceClassification.HIGH,\n"
                "        ConvergenceClassification.MEDIUM,\n"
                "        ConvergenceClassification.LOW,\n"
                "        ConvergenceClassification.CONFLICTED,"
            ),
            intent=(
                "Narrower than M1.1: only the one verdict MacroThesis hard-blocks "
                "becomes distributable, which is the defect that actually matters."
            ),
        ),
        # -- M2: the boundary parse ----------------------------------------
        Mutation(
            group="M2",
            name="M2.1 the boundary parse is removed (a bare string reaches .value)",
            path=SCENARIOS,
            old=_PARSE,
            new="    verdict = convergence  # type: ignore[assignment]",
            intent=(
                "`ConvergenceClassification` inherits from `str`, so a bare "
                "'HIGH' hashes equal to the member and passes membership -- then "
                "dies on `.value` with AttributeError. A typo becomes a crash "
                "instead of a refusal."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the verdict is taken from a lowercased name",
            path=SCENARIOS,
            old=_PARSE,
            new="    verdict = ConvergenceClassification(convergence.upper())",
            intent=(
                "A case-insensitive parse: 'high' is now accepted and silently "
                "becomes HIGH. This is the defect one step milder -- the spec's "
                "problem was that a typo fell into the wrong branch rather than "
                "being refused."
            ),
        ),
        # -- M3: the single definition (O-51) ------------------------------
        Mutation(
            group="M3",
            name="M3.1 the ScenarioOutcome re-export is removed",
            path=SCHEMAS,
            old=_REEXPORT_SCENARIO + "\n",
            new="",
            intent=(
                "The producer's output class is no longer importable from the "
                "thesis layer, so the schema contract has one layer and not two. "
                "The kill is the module import failing in the selection."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2 the MarketPricingGap re-export is removed",
            path=SCHEMAS,
            old=_REEXPORT_GAP + "\n",
            new="",
            intent=(
                "Same at the gap: `canonical_policy_gap`'s class stops being "
                "reachable from the layer `build_scenario_distribution` lives in."
            ),
        ),
        # -- M4: the unit refusal ------------------------------------------
        Mutation(
            group="M4",
            name="M4.1 the unit refusal is removed (unknown units are scaled silently)",
            path=SCENARIOS,
            old=_UNIT_GUARD,
            new="    if False:",
            intent=(
                "Restores the spec's unconditional `* 100`: a caller supplying an "
                "already-basis-point gap is scaled again, silently. The wrong "
                "answer is a plausible number, which is why this is D-054/D-060's "
                "unit class rather than an error class."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 the convertible-unit set admits a basis-point gap",
            path=SCENARIOS,
            old=_CONVERTIBLE,
            new='frozenset({"%", "bp"})',
            intent=(
                "Widens the contract instead of removing it: a 'bp' gap is now "
                "accepted and still multiplied by 100, so the error is a factor "
                "of 100 in the opposite direction."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.3 the conversion factor is inverted",
            path=SCENARIOS,
            old=_MAGNITUDE,
            new="    magnitude_bp = abs(gap.raw_gap) / settings.bp_per_percent",
            intent="1% becomes 0.01bp instead of 100bp -- the 100x ladder, inverted.",
        ),
        # -- M5: the guards that must fire ---------------------------------
        Mutation(
            group="M5",
            name="M5.1 the sub-noise-floor refusal is removed",
            path=SCENARIOS,
            old=_MEANINGFUL_GUARD,
            new="    if False:",
            intent=(
                "A distribution is built over a gap inside the policy rules' own "
                "dispersion -- the false-confidence failure Module 12.2 exists to "
                "prevent."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.2 the zero-magnitude refusal is removed",
            path=SCENARIOS,
            old=_ZERO_GUARD,
            new="    if False:",
            intent=(
                "A degenerate distribution is published: four outcomes differing "
                "only in their probabilities, every payoff zero."
            ),
        ),
        # -- M6: the config accessors --------------------------------------
        Mutation(
            group="M6",
            name="M6.1 the base probability for HIGH is read from the LOW leaf",
            path=CONFIG,
            old=_BASE_PROBS,
            new=('        return {\n            "HIGH": float(self.base_probability_low.value),'),
            intent=(
                "The highest-convergence verdict is given the lowest base case, so "
                "the ordering that makes the distribution meaningful is reversed."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.2 the payoff-unit conversion factor defaults to 1.0",
            path=CONFIG,
            old=_BP_PER_PERCENT,
            new="        return 1.0",
            intent="The whole ladder disappears: a 1% gap pays 1bp.",
        ),
        Mutation(
            group="M6",
            name="M6.3 the sum-to-one constraint on the remaining shares is removed",
            path=CONFIG,
            old=_SUM_GUARD,
            new="        if False:",
            intent=(
                "The one constraint three leaves share stops being asserted, so "
                "the four published probabilities sum to base + (1-base)*S with "
                "S != 1 -- invisible in every leaf (O-41's shape)."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.4 the tail share is read from the reversal leaf",
            path=CONFIG,
            old=_SHARES_TAIL,
            new='            "tail_adverse_surprise": float(self.remaining_share_reversal.value),',
            intent=(
                "Two of the three shares become identical, so the shares no "
                "longer sum to one UNLESS the validator catches it -- this "
                "mutation tests the validator and the tail's own value at once."
            ),
        ),
        # -- M7: the wiring ------------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 `remaining` is not subtracted from the base",
            path=SCENARIOS,
            old=_REMAINING,
            new="    remaining = 1.0",
            intent=(
                "Every non-base probability is its share of ONE rather than of "
                "(1 - base), so the four sum to more than one."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.2 the base branch is paid the partial-close multiple",
            path=SCENARIOS,
            old=_BASE_MULTIPLE,
            new="            payoff_estimate=magnitude_bp * multiples[_PARTIAL],",
            intent=(
                "The branch that pays the WHOLESALE gap pays 40% of it. The "
                "distribution's expected value moves and the shape inverts."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.3 the published unit becomes the Kelly-sizable one",
            path=SCENARIOS,
            old=_UNIT_FIELD,
            new=(
                "            payoff_estimate=magnitude_bp * multiples[_BASE],\n"
                '            unit="fraction_of_capital",'
            ),
            intent=(
                "The distribution declares itself a fraction of capital while "
                "carrying basis-point magnitudes -- the exact mismatch the unit "
                "field exists to make visible (O-50)."
            ),
        ),
        # -- M9: the unit seam (O-50) --------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the payoff_unit field is given a default again",
            path=RISK_BUDGET,
            old=_UNIT_REQUIRED,
            new=(
                '    payoff_unit: KellyPayoffUnit = Field(\n        default="fraction_of_capital",'
            ),
            intent=(
                "**The defect D-064 exists to close.** With a default the field "
                "is optional and a bp-valued distribution is silently labelled a "
                "fraction of capital -- D-057's failure toward silence, reached "
                "through the guard D-057 added. The kill is the required-field "
                "assertion, NOT the bp-declaration test (which supplies the very "
                "argument whose absence is the defect)."
            ),
        ),
        Mutation(
            group="M9",
            name="M9.2 the consumer vocabulary drops a member the producer publishes",
            path=RISK_BUDGET,
            old=_UNIT_VOCABULARY,
            new='KellyPayoffUnit = Literal["fraction_of_capital"]',
            intent=(
                "The pre-D-064 declaration: the consumer's vocabulary silently "
                "omits a member the producer publishes. Under the old arrangement "
                "this was invisible — the two `Literal`s agreed by inspection and "
                "a deleted member simply stopped being accepted at the type level, "
                "which reads as validation rather than as a narrowing. The kill is "
                "`test_the_consumer_vocabulary_is_derived_from_the_producers`, "
                "which asserts set equality between the two vocabularies rather "
                "than a remembered subset."
            ),
        ),
        Mutation(
            group="M9",
            name="M9.3 the named unit refusal is removed",
            path=RISK_BUDGET,
            old=_UNIT_REFUSAL,
            new="        if False:",
            intent=(
                "The type admits two members and now nothing refuses one, so a "
                "declared bp distribution is accepted and sized as if its payoffs "
                "were fractions of capital."
            ),
        ),
        # -- M8: the honesty control ---------------------------------------
        Mutation(
            group="M8",
            name="M8.1 the tail description is re-wrapped across the same three literals (CONTROL)",
            path=SCENARIOS,
            old=_TAIL_DESCRIPTION,
            new=_TAIL_CONTROL,
            intent=(
                "A **real** rewrite that changes no character of the concatenated "
                "string: the same six-line description is split at different "
                "points across the same implicit concatenation, so the runtime "
                "value is byte-identical. This MUST survive. If it is reported "
                "KILLED, the kill is coming from something other than the "
                "assertions -- a collection error, a stale `.pyc`, a missing "
                "dependency -- and every other kill in this run is suspect "
                "(D-051/D-062)."
            ),
            inert_proof=(
                "CONTROL: the three literals concatenate to the identical string, "
                "so no assertion can distinguish the mutant from the shipped code."
            ),
        ),
    ]


#: Survivors that are expected, with the argument for why (O-42).
_INERT_PROOFS: dict[str, str] = {
    "M8.1 the tail description is re-wrapped across the same three literals (CONTROL)": (
        "CONTROL — semantically identical by construction."
    ),
}


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test — a conclusion about code nobody mutated.

    The control (``M8.1``) is deliberately ``old == new`` and is reported as
    INERT BY CONSTRUCTION, which is the exempt path rather than an oversight.
    """
    problems: list[str] = []
    by_file: dict[Path, str] = {}
    for path in {mt.path for mt in mutations}:
        by_file[path] = path.read_text(encoding="utf-8")

    for mt in mutations:
        text = by_file[mt.path]
        if mt.old == mt.new:
            if "CONTROL" in mt.name:
                continue
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
    **right place** (**O-67**). ``build_scenario_distribution`` holds three
    ``raise ValueError`` blocks with long similar bodies and the module holds
    several ``return float(...)`` accessors, so a fragment from one is unique
    while sitting in the wrong guard.

    The owner is resolved by :func:`tools.sweep_health.enclosing_symbol`, which
    parses the file rather than pattern-matching lines. This sweep is why that
    function exists: a first draft walked backwards for a line starting with
    ``def``/``class`` and resolved **this module's own comment prose** as the
    enclosing symbol, reporting a mis-target for an anchor that had not moved
    (D-064). A gate that manufactures findings is worse than no gate (lesson 80).
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
        path = REPO / target
        if not path.exists():
            problems.append(f"test target ABSENT: {target}")
    if problems:
        return problems
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/thesis_layer/test_scenario_distribution.py",
            "tests/portfolio/test_fractional_kelly.py",
            "tests/thesis_layer/test_invalidation.py",
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
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/thesis_layer/test_scenario_distribution.py",
            "tests/portfolio/test_fractional_kelly.py",
            "tests/thesis_layer/test_invalidation.py",
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
    print("mutation sweep: build_scenario_distribution (Module 12, D-064)")
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

    control_name = (
        "M8.1 the tail description is re-wrapped across the same three literals (CONTROL)"
    )
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
