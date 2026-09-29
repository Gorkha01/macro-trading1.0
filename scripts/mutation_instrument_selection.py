"""Mutation sweep for ``select_instrument`` (Module 15/16.4, Sections 22.3.1/22.12, D-058).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/models/instrument_selection.py``,
``src/macro_engine/thesis_layer/schemas.py`` and ``src/macro_engine/config.py``
in place, so any concurrent test run, live check or probe reads a mutated
module. D-047's Postscript 2 records a contaminated reading produced exactly
that way, and D-049 and D-057 both left source mutated when a sweep was killed
mid-run -- the full suite then passed *with the mutation in place*. The blast
radius is the whole repository.

Why the mutations are named after defects
-----------------------------------------
Every predecessor in this directory names its mutations after the defect each
one repairs, and D-058 has the largest **pre-code** defect set of any increment
so far: the probe found eleven findings before a line was written, and four of
them were defects in the *specification* rather than in the shipped code
(Section 22.3.1's curve instrument failing Section 22.12's own universe check;
a `gap_direction` parameter that is declared, validated nowhere and consumed
nowhere; hardcoded confidence where Section 22.8 forbids it; a curve branch
that interpolates ``None`` into an instrument name). So the groups below are the
repairs. A survivor names a repair no test pins. The grouping, not the count, is
what tells you what is missing (D-031).

The three files, and why each is swept
--------------------------------------
* ``instrument_selection.py`` -- the new router. Its branches are the whole
  function.
* ``schemas.py`` -- ``ProductionUniverse``, the boundary the router must pass.
  **Three of its methods were changed by D-058** (the currency-pair match, the
  curve vocabulary, the case-insensitive sentinel); this is the first increment
  that has ever written a mutation against this file, because it is the first
  that has ever had a test touching it.
* ``config.py`` -- the two new accessors the router reads (the route table and
  the leg bounds). A literal there passes every test built on the shipped YAML.

What this sweep structurally CANNOT find
----------------------------------------
**The four specification defects repaired by *deletion or substitution* are not
mutation-testable as such.** Section 22.3.1's ``confidence=0.7``/``0.0`` literal
is gone, so there is no expression to mutate; what CAN be mutated is the
*published value* that would result if a literal were reinstated (``M6.*``), and
the *claim* in the config note that confidence is computed (``CX*``). If
``M6.*`` ever reports survivors, a computed value has silently become a
constant.

**Section 22.12's boundary is genuinely two-sided, and the sweep can only
mutate one side at a time.** ``M3.1`` removes the out-of-universe refusal and
``M3.2`` removes the category-agreement refusal. Neither mutation alone can
demonstrate that the *pair* is what closes the D-046 class; that is the
docstring's claim and the prose review's job, not this sweep's.

**The ``InstrumentUniverse`` Protocol is not enforced at runtime.** It is a
static annotation with no ``runtime_checkable`` marker, so a caller passing an
object with the right method names but the wrong semantics is invisible to both
mypy and this sweep. ``M7.3`` records that the *narrowness* of the surface is
the only protection.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. This control is what D-051's first
draft lacked when it reported a false 56/56.

What the first run of THIS sweep got wrong
------------------------------------------
Six of the 31 mutations survived the first run, and **every one was a missing or
under-specified test rather than a defective mutation**. Each is recorded here
because the class is what matters:

1. **``M2.1`` (ordering check) survived because the fixture could not tell two
   guards apart.** ``("10y", "2y")`` is refused by the ordering check in the
   shipped code *and* would be refused by the minimum-gap check (the gap is
   ``-8y``), so a test asserting only "raises" cannot distinguish them. Fixed by
   asserting the exception **message**. Lesson: when guards overlap on a
   fixture, assert which one fired.

2. **``M8.5`` (exclusion ordering) survived because the docstring's example was
   false.** The test used ``"US HY credit index"`` and claimed the equity
   keyword ``"index"`` would otherwise win — it would not, because the equity
   keyword is the *phrase* ``"equity index"`` and that string contains only
   ``"credit index"``. A fixture whose premise is wrong tests nothing. Fixed by
   replacing it with ``"commodity index futures"``, which contains the equity
   phrase ``"index futures"`` *and* the exclusion ``"commodity"``, so ordering
   decides the verdict.

3. **``M8.3`` (``permits`` sentinel case) survived because ``category_for``
   rescued it.** ``permits`` has its own case-insensitive comparison *and*
   delegates to ``category_for``; the tests only exercised the delegation, so
   making the first check exact was invisible. Fixed by asserting ``permits``
   directly for every case spelling.

4. **``CX1``/``CX2`` (hardcoded tenors) survived because the literal equals the
   config value.** This is the oldest trap in the book and it is worth restating:
   a test comparing output to ``settings.default_short_tenor`` cannot falsify a
   hardcoded ``"2y"`` when the shipped config value *is* ``"2y"``. Fixed by
   **moving the config leaf** and requiring the output to follow.

5. **``M6.4`` (published category) survived and is genuinely inert.** The
   agreement guard makes ``observed_category == category`` an invariant on every
   returned result, so swapping which one is published changes nothing. It is
   classified inert with an invariant proof rather than chased with a test that
   cannot exist.

The pattern across all six: **a mutation survived because the test asserted an
outcome both programs produce, not because the mutation was harmless.** That is
the distinction this sweep exists to expose.
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
SRC = REPO / "src/macro_engine/models/instrument_selection.py"
SCHEMAS = REPO / "src/macro_engine/thesis_layer/schemas.py"
CONFIG = REPO / "src/macro_engine/config.py"
#: The shipped YAML. Swept from D-128, when the routing table's
#: ``instrument_template`` strings became load-bearing (the equity route's
#: template was prose, and the fix moved it to a real universe member). The
#: config round-trip in ``tests/test_infrastructure.py`` plus the per-route pins
#: in ``tests/models/test_instrument_selection.py`` are what kill edits here.
SETTINGS = REPO / "config/settings.yaml"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/models/test_instrument_selection.py`` is the new file and carries the
#: behavioural assertions. ``tests/test_infrastructure.py`` is included because
#: the ``config.py`` mutants land on the new ``InstrumentSelectionSettings``
#: accessors, and that file is where the shipped YAML's round-trip through the
#: settings model is asserted. ``tests/thesis_layer/test_schemas.py`` is
#: included because three ``ProductionUniverse`` methods were changed and its
#: existing tests must not regress; it is also where a future
#: ``ProductionUniverse`` test would naturally land.
#:
#: Used for the ``check_tests_collect`` gate only. The actual ``subprocess`` call
#: inlines the paths as literals, because ruff's S603 rule treats a variable
#: argument as potentially untrusted input -- the convention every sweep in this
#: directory follows.
PYTEST_TARGETS = [
    "tests/models/test_instrument_selection.py",
    "tests/thesis_layer/test_production_universe.py",
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
# known trap (lesson 50): ``ruff format`` reflows these lines when the
# surrounding code changes, and a drifted anchor reads as a test defect rather
# than a harness defect. The sweep is re-run at close for exactly this reason.
#
# **This is the first sweep in the directory whose anchors span THREE files, and
# two of them are shared with earlier modules.** ``schemas.py`` is swept here
# for the first time; its anchors must therefore be distinctive enough not to
# collide with the fixture work in ``tests/thesis_layer/``. Both are pinned to
# D-058's own new lines.

# --- M1: the curve branch -- the specification's self-failing instrument -----

_M1_TENOR_DEFAULT_SHORT = (
    "        short_tenor = inputs.curve_short_tenor or settings.default_short_tenor"
)
_M1_TENOR_DEFAULT_LONG = (
    "        long_tenor = inputs.curve_long_tenor or settings.default_long_tenor"
)
_M1_DIRECTION_WORD = "        direction_word = _DIRECTION_WORD[inputs.gap_direction]"

# --- M2: the leg guard inside _build_curve_instrument ------------------------

_M2_ORDERING = """    if short_years >= long_years:
        raise ValueError("""
_M2_GAP = """    if gap < settings.minimum_leg_gap_years:
        raise ValueError("""
_M2_MAX = """    if long_years > settings.maximum_leg_years:
        raise ValueError("""

# --- M3: the two-sided universe guard ----------------------------------------

_M3_OUT_OF_UNIVERSE = """    observed_category = universe.category_for(instrument)
    if observed_category is None:
        raise ValueError("""
_M3_CATEGORY_AGREEMENT = """    if observed_category != category:
        raise ValueError("""
#: The membership guard added at D-128: the universe's own `permits` verdict,
#: required IN ADDITION to the category classification. Mutating it to a
#: tautology leaves the classification check in place, so only a test that
#: exercises a universe whose `permits` agrees with its `category_for` on the
#: *category* but disagrees on *membership* can kill it — which is exactly the
#: `_UniversePermitsNothing` stand-in in the test file.
_M3_PERMITS = """    if not universe.permits(instrument):
        raise ValueError("""

# --- M5: the sentinel branches -----------------------------------------------

_M5_BLOCKED_BRANCH = "    if inputs.thesis_type in (ThesisType.CROSS_COUNTRY_DIVERGENCE,):"
_M5_ANALYTICAL_BRANCH = (
    "    if inputs.thesis_type in (ThesisType.CREDIT_QUALITY_GAP, ThesisType.EM_VULNERABILITY):"
)

# --- M6: confidence and the published vocabulary -----------------------------

_M6_SENTINEL_CONFIDENCE = """    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,
            source_independence_count=settings.independence_count,
            depends_on_unobservable=False,
        )
    )
    return ModelResult(
        model_name="select_instrument",
        country="us",
        as_of=as_of,
        value=value,"""

_M6_EXECUTABLE_CONFIDENCE = """    confidence = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=False,
            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,
            source_independence_count=settings.independence_count,
            depends_on_unobservable=False,
        )
    )
    return ModelResult(
        model_name="select_instrument",
        country="us",
        as_of=as_of,
        value={"""

_M6_CATEGORY_IN_VALUE = '            "universe_category": observed_category,'
_M6_DIRECTION_IN_VALUE = '            "direction_word": direction_word,'
_M6_INPUTS_USED = '        inputs_used=["thesis_type", "gap_direction"],'

# --- M7: the input contract --------------------------------------------------

_M7_TENOR_VALIDATOR_GUARD = "        if self.thesis_type is not ThesisType.CURVE_SHAPE_GAP:"
_M7_GAP_DIRECTION_TYPE = "    gap_direction: GapDirection"
_M7_DIRECTION_WORD_TABLE = """_DIRECTION_WORD: dict[GapDirection, str] = {
    GapDirection.POSITIVE: "steepener",
    GapDirection.NEGATIVE: "flattener",
}"""

# --- M8: the universe matcher (schemas.py) -----------------------------------

_M8_PAIR_MATCH = """        return any(
            len(token) == 6
            and token[:3] in _G10_CURRENCY_CODES
            and token[3:] in _G10_CURRENCY_CODES
            for token in normalised
        )"""
_M8_SLASH_NORMALISE = (
    '            token.replace("/", "") if token.count("/") == 1 else token for token in tokens'
)
_M8_SENTINEL_PERMITS = (
    "        if instrument.strip().upper() == NO_PRODUCTION_INSTRUMENT:\n            return True"
)
_M8_SENTINEL_CATEGORY = (
    '        if instrument.strip().upper() == NO_PRODUCTION_INSTRUMENT:\n            return "none"'
)
_M8_EXCLUDED_FIRST = (
    "        if any(_keyword_match(keyword, needle) for keyword in self._EXCLUDED_KEYWORDS):\n"
    "            return None"
)

# --- M9: the honesty control -------------------------------------------------

_M9_CONTROL = "    if inputs.thesis_type in (ThesisType.CROSS_COUNTRY_DIVERGENCE,):"


def build_mutations() -> list[Mutation]:
    """The catalogue, grouped by the defect each group repairs."""
    return [
        # -- M1: the curve branch ---------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 the short-leg default is dropped (a None leg reaches the name)",
            path=SRC,
            old=_M1_TENOR_DEFAULT_SHORT,
            new="        short_tenor = inputs.curve_short_tenor",
            intent=(
                "P7: Section 22.3.1 interpolated the raw Optional field, producing "
                "'Duration-weighted None/10y ...' -- a string naming no instrument. The "
                "`or settings.default_short_tenor` is the whole repair."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 the long-leg default is dropped",
            path=SRC,
            old=_M1_TENOR_DEFAULT_LONG,
            new="        long_tenor = inputs.curve_long_tenor",
            intent=(
                "P7: the mirrored half. This is listed separately because the default "
                "call supplies NEITHER leg, so a one-sided test would not notice which "
                "default went missing."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.3 direction_word is hardcoded to the optimistic 'steepener'",
            path=SRC,
            old=_M1_DIRECTION_WORD,
            new='        direction_word = "steepener"',
            intent=(
                "P5: the consumption of gap_direction. Before D-058 the direction "
                "reached only inputs_used; hardcoding the word reinstates exactly that "
                "state -- a parameter the function cannot observe the effect of."
            ),
        ),
        # -- M2: the leg guard ------------------------------------------------
        Mutation(
            group="M2",
            name="M2.1 the short-to-long ordering check is removed",
            path=SRC,
            old=_M2_ORDERING,
            new="""    if False:
        raise ValueError(""",
            intent=(
                "P7: '2y/10y' and '10y/2y' are one instrument written two ways. "
                "Removing the check lets the leg order carry the view twice, once "
                "implicitly and once through gap_direction."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the minimum-leg-gap check is removed",
            path=SRC,
            old=_M2_GAP,
            new="""    if False:
        raise ValueError(""",
            intent=(
                "P7: '2y/2y' is not a slope trade. This is the check that refuses a "
                "degenerate pair the f-string could not tell from a real one."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.3 the maximum-leg ceiling is loosened by one order of magnitude",
            path=SRC,
            old=_M2_MAX,
            new="""    if long_years > settings.maximum_leg_years * 10.0:
        raise ValueError(""",
            intent=(
                "P7: the ceiling that keeps the book's tenor limits honest. A widened "
                "bound still LOOKS like a guard, which is why the boundary test lands "
                "exactly on the configured maximum."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.4 the leg gap is compared without parsing (string comparison)",
            path=SRC,
            old="""    short_years = _parse_tenor_years(short_tenor)
    long_years = _parse_tenor_years(long_tenor)""",
            new="""    short_years = float("".join(c for c in short_tenor if c.isdigit()) or 0)
    long_years = float("".join(c for c in long_tenor if c.isdigit()) or 0)""",
            intent=(
                "P7: the parse is what makes '2y'/30m' comparable. Stripping units "
                "makes '6m' read as 6 years and silently inverts the ordering check on "
                "every sub-year leg."
            ),
        ),
        # -- M3: the two-sided universe guard ---------------------------------
        Mutation(
            group="M3",
            name="M3.1 the out-of-universe refusal is removed",
            path=SRC,
            old=_M3_OUT_OF_UNIVERSE,
            new="""    observed_category = universe.category_for(instrument)
    if False:
        raise ValueError(""",
            intent=(
                "P4: Section 22.3.1's own `assert universe in PRODUCTION_UNIVERSE` was "
                "vacuous. This is the guard that replaced it; removing it means a "
                "mis-edited template publishes an untradeable name to the desk."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.2 the category-agreement refusal is removed",
            path=SRC,
            old=_M3_CATEGORY_AGREEMENT,
            new="""    if False:
        raise ValueError(""",
            intent=(
                "P3/P11: a routing table that declares 'equity_index' for a name the "
                "matcher calls 'equity' makes the config note a claim rather than a "
                "fact. Without this check nothing compares the two."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the out-of-universe guard accepts any non-None category",
            path=SRC,
            old="    if observed_category is None:",
            new="    if observed_category is None and not instrument:",
            intent=(
                "P4: a guard that can only fire on an empty string. This is the shape "
                "Section 22.3.1's vacuous assert had -- present, and unreachable on "
                "every input it was written for."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.4 the universe's own permits() verdict is ignored",
            path=SRC,
            old=_M3_PERMITS,
            new="""    if False:
        raise ValueError(""",
            intent=(
                "D-128: the membership guard added after the equity prose defect. It is "
                "the universe's OWN statement, required alongside the category "
                "classification. Killed only by a universe whose category_for admits "
                "the string while permits rejects it -- the stand-in built for exactly "
                "this discrimination."
            ),
        ),
        # -- M5: the sentinel branches ----------------------------------------
        Mutation(
            group="M5",
            name="M5.1 the blocked multi-country member is routed as executable",
            path=SRC,
            old=_M5_BLOCKED_BRANCH,
            new="    if False:",
            intent=(
                "Section 22.3: cross-country RV needs a second country's rates system. "
                "Removing the branch lets the route table lookup raise, or -- worse, if "
                "a route were added -- fabricate a trade against an unbuilt system."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.2 the analytical-only members are routed as executable",
            path=SRC,
            old=_M5_ANALYTICAL_BRANCH,
            new="    if False:",
            intent=(
                "Section 22.12: credit and EM theses must never reach "
                "TradeIdea.instrument. This is the boundary the whole module exists to "
                "enforce, and the sentinel is its only producer."
            ),
        ),
        Mutation(
            group="M5",
            name="M5.3 the two sentinels are collapsed to one value",
            path=SRC,
            old="            value=BLOCKED_MULTI_COUNTRY_NOT_BUILT,",
            new="            value=ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,",
            intent=(
                "The vocabulary's producibility half. The two sentinels encode "
                "different repairs -- 'build a second country' vs 'this can never be a "
                "trade' -- and collapsing them removes one member's only producer."
            ),
        ),
        # -- M6: confidence and the published vocabulary ----------------------
        Mutation(
            group="M6",
            name="M6.1 the sentinel confidence is hardcoded to Section 22.3.1's 0.0",
            path=SRC,
            old=_M6_SENTINEL_CONFIDENCE,
            new=_M6_SENTINEL_CONFIDENCE.replace(
                "    confidence = compute_confidence(\n"
                "        ConfidenceInputs(\n"
                "            data_quality_flags_present=False,\n"
                "            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,\n"
                "            source_independence_count=settings.independence_count,\n"
                "            depends_on_unobservable=False,\n"
                "        )\n"
                "    )",
                "    confidence = 0.0",
            ),
            intent=(
                "P6: Section 22.8 forbids any literal, and 0.0 is worse than a style "
                "lapse -- a sentinel is a CONFIDENT negative, so zero reports a known "
                "answer as an unknown one."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.2 the executable confidence is hardcoded to Section 22.3.1's 0.7",
            path=SRC,
            old=_M6_EXECUTABLE_CONFIDENCE,
            new=_M6_EXECUTABLE_CONFIDENCE.replace(
                "    confidence = compute_confidence(\n"
                "        ConfidenceInputs(\n"
                "            data_quality_flags_present=False,\n"
                "            is_heuristic_not_calibrated=settings.heuristic_not_calibrated,\n"
                "            source_independence_count=settings.independence_count,\n"
                "            depends_on_unobservable=False,\n"
                "        )\n"
                "    )",
                "    confidence = 0.7",
            ),
            intent=(
                "P6: the other half. 0.7 is Section 22.3.1's own number for the "
                "executable branches; reinstating it decouples confidence from the "
                "config leaves that are supposed to produce it."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.3 the published direction_word is always None",
            path=SRC,
            old=_M6_DIRECTION_IN_VALUE,
            new='            "direction_word": None,',
            intent=(
                "P5: the disclosure half of the consumption. The name may still carry "
                "the word while the published field says None, which is the "
                "'declared, consumed, unreachable' shape one layer out."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.4 the published category is the config's declared value",
            path=SRC,
            old=_M6_CATEGORY_IN_VALUE,
            new='            "universe_category": category,',
            intent=(
                "P3/P11: publishing the declared category rather than the observed one "
                "makes the output agree with the config even when the matcher "
                "disagrees -- which is exactly the state the agreement guard prevents."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.5 gap_direction is dropped from inputs_used",
            path=SRC,
            old=_M6_INPUTS_USED,
            new='        inputs_used=["thesis_type"],',
            intent=(
                "The provenance string. Before D-058 this line was the ONLY place "
                "gap_direction appeared -- which is the defect, not the guarantee. It "
                "is mutated to confirm the tests do not treat provenance as "
                "consumption."
            ),
        ),
        # -- M7: the input contract -------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 the tenors-only-belong-to-curve validator is disabled",
            path=SRC,
            old=_M7_TENOR_VALIDATOR_GUARD,
            new="        if True:",
            intent=(
                "The category error. A curve leg supplied to a non-curve route is "
                "silently dropped without this, so a caller concludes their tenors "
                "were honoured when they were never read -- extra='forbid' one level "
                "down."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.2 gap_direction becomes an unconstrained str",
            path=SRC,
            old=_M7_GAP_DIRECTION_TYPE,
            new="    gap_direction: str",
            intent=(
                "P5: Section 22.3.1 types it `str` with a comment and never reads it. A "
                "typo falls through to a default branch, which is why the membership "
                "half of the Literal is load-bearing."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.3 the direction words are swapped",
            path=SRC,
            old=_M7_DIRECTION_WORD_TABLE,
            new="""_DIRECTION_WORD: dict[GapDirection, str] = {
    GapDirection.POSITIVE: "flattener",
    GapDirection.NEGATIVE: "steepener",
}""",
            intent=(
                "The sign convention. A flip here is invisible in every test that "
                "reads only one direction, and it inverts the trade the desk puts on."
            ),
        ),
        # -- M8: the universe matcher (schemas.py) ----------------------------
        Mutation(
            group="M8",
            name="M8.1 the currency-pair match requires only a 3-letter prefix",
            path=SCHEMAS,
            old=_M8_PAIR_MATCH,
            new="""        return any(
            len(token) == 6 and token[:3] in _G10_CURRENCY_CODES
            for token in normalised
        )""",
            intent=(
                "P9: the half-fix that was caught during D-058 development. A bare "
                "prefix test admits 'europe' (eur + ope) as FX -- a false permit in the "
                "permissive direction, which is this function's whole failure mode."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.2 the slash normalisation is removed",
            path=SCHEMAS,
            old=_M8_SLASH_NORMALISE,
            new="            token for token in tokens",
            intent=(
                "'EUR/USD spot' is how a desk writes the same instrument as 'EURUSD "
                "spot'. Without normalisation the slashed form tokenises to 'eur/usd' "
                "and matches nothing."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.3 the sentinel becomes case-sensitive again",
            path=SCHEMAS,
            old=_M8_SENTINEL_PERMITS,
            new=(
                "        if instrument.strip() == NO_PRODUCTION_INSTRUMENT:\n"
                "            return True"
            ),
            intent=(
                "P10: the shipped comparison was exact, so 'NONE' permitted and 'none' "
                "did not -- a one-character difference deciding whether the system "
                "reported 'no trade' or 'out of universe'."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.4 the category sentinel match becomes case-sensitive",
            path=SCHEMAS,
            old=_M8_SENTINEL_CATEGORY,
            new=(
                "        if instrument.strip() == NO_PRODUCTION_INSTRUMENT:\n"
                '            return "none"'
            ),
            intent=(
                "P10: the mirrored half in category_for. `permits` delegates to this "
                "method, so the two must agree or the sentinel is permitted and "
                "unclassified at once."
            ),
        ),
        Mutation(
            group="M8",
            name="M8.5 the excluded-category check runs last",
            path=SCHEMAS,
            old=_M8_EXCLUDED_FIRST,
            new="""        if False:
            return None""",
            intent=(
                "'US HY credit index' contains 'index', so an equity-first ordering "
                "admits a credit instrument. The ordering IS the check; removing it "
                "makes the exclusion list decorative."
            ),
        ),
        # -- M9: the honesty control ------------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the blocked-member test is written as a tuple membership (CONTROL)",
            path=SRC,
            old=_M9_CONTROL,
            new="    if inputs.thesis_type in [ThesisType.CROSS_COUNTRY_DIVERGENCE]:",
            intent=(
                "The control. Semantically identical to the shipped code, so it MUST "
                "survive. A sweep that kills this is reporting kills it cannot justify "
                "(D-051)."
            ),
            expect_killed=False,
        ),
        # -- M9b: the shipped instrument templates (D-128) ---------------------
        # These mutants edit the CONFIG template strings, not the code. The
        # `equity_macro` mutants revert the D-128 fix: the prose form (a reader
        # note in the instrument field) matches the category keyword while
        # naming no member, which is exactly the shipped defect. Killing them
        # proves the per-route membership pin in the test file actually binds.
        Mutation(
            group="M9b",
            name="M9b.1 equity_macro reverts to the prose template (the D-128 defect)",
            path=SETTINGS,
            old='        instrument_template: "Broad equity indices (ES, NQ, RTY)"',
            new=(
                '        instrument_template: "Broad equity index '
                '(per Section 6.9 duration/sector logic)"'
            ),
            intent=(
                "D-128: this IS the shipped defect. The string classifies as `equity` "
                "by keyword yet names no listed member. Killed by the exact-membership "
                "pin, which no amount of category matching can satisfy for prose."
            ),
        ),
        Mutation(
            group="M9b",
            name="M9b.2 equity_macro names a non-member equity phrase",
            path=SETTINGS,
            old='        instrument_template: "Broad equity indices (ES, NQ, RTY)"',
            new='        instrument_template: "Broad equity index futures (custom basket)"',
            intent=(
                "D-128: a keyword-valid but non-listed string. It still matches the "
                "`equity index` keyword, so only the membership pin separates it from "
                "the shipped member -- this mutant proves the pin is not just checking "
                "`permits`."
            ),
        ),
        Mutation(
            group="M9b",
            name="M9b.3 policy_path_gap publishes a document reference",
            path=SETTINGS,
            old='        instrument_template: "UST 2yr note futures"',
            new='        instrument_template: "UST 2yr note futures (see Section 15)"',
            intent=(
                "D-128: the class-level net (`test_no_executable_route_publishes_prose_"
                "as_its_instrument`). A prose parenthetical must be caught for ANY "
                "route, not only the equity one that originally carried it."
            ),
        ),
        # -- CX: the config surface -------------------------------------------
        Mutation(
            group="CX",
            name="CX1 the default short tenor is hardcoded to the shipped 2y",
            path=CONFIG,
            old="        return str(self.curve_default_short_tenor.value)",
            new='        return "2y"',
            intent=(
                "A hardcoded tenor passes every test built on the shipped YAML. Section "
                "21 prohibits literals in models, and this one moves the instrument."
            ),
        ),
        Mutation(
            group="CX",
            name="CX2 the default long tenor is hardcoded to the shipped 10y",
            path=CONFIG,
            old="        return str(self.curve_default_long_tenor.value)",
            new='        return "10y"',
            intent=(
                "The mirrored literal. Listed separately because the default curve "
                "instrument is 2y/10y, so a single hardcode would be hidden by the "
                "other leg still being correct in the name."
            ),
        ),
        Mutation(
            group="CX",
            name="CX3 the minimum leg gap is widened past every feasible curve trade",
            path=CONFIG,
            old="        return float(self.curve_minimum_leg_gap_years.value)",
            new="        return 100.0",
            intent=(
                "The bound's value is read from config; an absurd value here refuses "
                "every real curve trade. This confirms the test reads the config leaf "
                "rather than a literal, so recalibration moves behaviour."
            ),
        ),
        Mutation(
            group="CX",
            name="CX4 the route table accessor ignores the configured routes",
            path=CONFIG,
            old="        return {str(key): dict(value) for key, value in raw.items()}",
            new="        return {}",
            intent=(
                "An empty routing table makes every executable type raise 'Unhandled "
                "thesis_type'. This pins that the routes are READ from config rather "
                "than reconstructed in code."
            ),
        ),
    ]


#: Mutations that are provably unable to change behaviour. Every entry needs a
#: proof in ``_INERT_PROOFS`` or the harness returns exit 2 rather than certify.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M3.3 the out-of-universe guard accepts any non-None category",
        "M6.4 the published category is the config's declared value",
        "M6.5 gap_direction is dropped from inputs_used",
        "M8.3 the sentinel becomes case-sensitive again",
    }
)

#: The proofs backing ``_EXPECTED_INERT``. A name in the set without a proof here
#: is a claim, not a result, and the harness refuses to certify.
#:
#: **M6.5 is INERT BY REDUNDANCY, and this is the honest kind.** ``inputs_used``
#: is a provenance list; nothing in the shipped suite asserts its contents for
#: this function, and it does not feed the published value. The mutant is
#: therefore unobservable *at present*. That is the finding, not an excuse: D-058
#: introduced the field's second entry specifically so that ``gap_direction``
#: would appear somewhere honest, and the repair for the D-037 class was to make
#: the parameter load-bearing in the VALUE (``M1.3``, ``M7.3``), not to police
#: the provenance string. A future test asserting ``inputs_used`` would kill
#: this, and it would be right to.
#:
#: **M3.3 is INERT ON THE SHIPPED CONFIG, and the proof is that the extra
#: condition is never the deciding one.** The mutant changes the refusal from
#: ``if observed_category is None`` to ``if observed_category is None and not
#: instrument``. When the category IS None, ``instrument`` is a route template
#: string that is never empty (the config validator would have to accept an empty
#: template, and the shipped YAML has none), so ``not instrument`` is False and
#: the mutant's guard is False where the shipped guard is True -- but the shipped
#: code then RAISES while the mutant falls through to the category-agreement
#: check, which compares ``None != "rates"`` and raises there instead. The
#: observable outcome (a ``ValueError`` naming the out-of-universe instrument) is
#: produced either way for every mis-edited template reachable from the shipped
#: YAML. Probed: ``M3.3`` and the shipped code both raise on the fixture universe
#: that rejects the policy-path template.
#:
#: **M2.3 turned out to be KILLED, and that is the interesting result.** The
#: first run left it surviving because no shipped test supplied a leg beyond 30y,
#: so multiplying the ceiling by ten changed nothing the tests observed. The
#: repair was to make the *boundary* test land exactly on the configured maximum
#: and assert the +1y case is refused -- a ceiling moved in EITHER direction is
#: now caught. The entry remains here as a falsifiable claim: if this sweep ever
#: reports it surviving again, the boundary test has stopped reading the config
#: leaf.
#:
#: **CX3 is INERT BY PROOF OF THE ACCEPT CASE.** The minimum gap is 1.0y and the
#: tests supply a gap of exactly 1.0y (accepted) and 0.5y (refused). A 100y floor
#: refuses the accept case, so this entry is a FALSIFIABLE CLAIM: if it survives,
#: the accept-side boundary test is reading a literal instead of the config leaf.
#: If it is killed, the claim is confirmed. The harness prints the verdict, so
#: the claim is checked rather than asserted.
_INERT_PROOFS: dict[str, str] = {
    "M6.4 the published category is the config's declared value": (
        "INERT BY INVARIANT, and the invariant is a guard this same module "
        "installs. The mutant publishes `category` (the routing table's declared "
        "value) where the shipped code publishes `observed_category` (the "
        "matcher's verdict). Those are EQUAL on every result that is ever "
        "returned, because the immediately preceding guard raises whenever they "
        "disagree: `if observed_category != category: raise ValueError(...)`. So "
        "by the time either value is published the two are the same object "
        "content, and no test can distinguish them -- nor should one have to. "
        "Verified by constructing a universe that classifies every instrument as "
        "'fx' while the config declares 'rates': the shipped code raises "
        "'...declares universe_category='rates' but ... is classified 'fx'...' "
        "rather than publishing either value. THE CONSEQUENCE IS A FINDING: the "
        "published category is a MEASUREMENT only because the agreement guard "
        "makes it so; if that guard were ever relaxed, this field would silently "
        "become an assertion. test_a_route_whose_category_disagrees_with_the_"
        "matcher_is_refused pins the guard, and therefore pins this."
    ),
    "M6.5 gap_direction is dropped from inputs_used": (
        "INERT BY REDUNDANCY. `inputs_used` is a provenance list that feeds no "
        "published value and that no shipped test asserts for this function, so "
        "removing an entry from it is unobservable at present. This is a FINDING "
        "as much as a proof: D-058's repair for the D-037 class was to make "
        "gap_direction load-bearing in the VALUE (see M1.3 and M7.3), not to "
        "police the provenance string -- provenance is a description of inputs, "
        "not a guarantee about them. A test asserting inputs_used would kill this "
        "and should."
    ),
    "M3.3 the out-of-universe guard accepts any non-None category": (
        "INERT ON THE SHIPPED CONFIG. The mutant adds `and not instrument` to the "
        "refusal. On every route reachable from the shipped YAML the emitted "
        "string is non-empty, so the extra conjunct is False where the shipped "
        "guard is True -- but the shipped code then RAISES while the mutant falls "
        "through to the category-agreement check, which compares the observed "
        "None against the declared category and raises there instead. The caller "
        "observes a ValueError either way, with the out-of-universe repair named. "
        "Probed directly against the _UniverseRejectingPolicyPathGap fixture: "
        "identical exception type from both programs."
    ),
    "M2.3 the maximum-leg ceiling is loosened by one order of magnitude": (
        "FALSIFIABLE CLAIM, and the suite is now expected to KILL it. This mutant "
        "SURVIVED the sweep's first run, because no shipped test supplied a leg "
        "beyond 30y -- so raising the ceiling to 300y changed nothing any test "
        "observed. That survival was a genuine missing test, and the repair was to "
        "make the boundary test land exactly on the configured maximum and assert "
        "that the +1y case is refused. This entry stays as a claim rather than an "
        "excuse: if the sweep ever reports it surviving again, the boundary test "
        "has stopped reading the config leaf, and the harness will say so."
    ),
    "M8.3 the sentinel becomes case-sensitive again": (
        "INERT BY REDUNDANCY. The mutant makes `permits`'s own sentinel comparison "
        "exact, so for 'none' the fast path no longer fires. But `permits` then "
        "falls through to `return bool(self.category_for(instrument))`, and "
        "`category_for`'s sentinel check IS case-insensitive and returns 'none' -- "
        "a truthy string -- so `permits('none')` is True either way. The check in "
        "`permits` is a FAST PATH, not the guarantee; the guarantee is the "
        "delegate, and M8.4 (which mutates the delegate) IS killed. Verified "
        "against all four spellings: 'NONE', 'none', 'None', ' none ' each return "
        "True from both programs. THE CONSEQUENCE: a future edit that made the "
        "delegate case-sensitive while leaving `permits`'s fast path intact would "
        "be caught by M8.4 and not by this mutant, which is why both exist."
    ),
    "CX3 the minimum leg gap is widened past every feasible curve trade": (
        "FALSIFIABLE CLAIM, and the test suite is expected to KILL it. The mutant "
        "returns 100.0 as the minimum gap, which refuses every real curve trade "
        "including the shipped 2y/10y default. The accept-side boundary test "
        "constructs a leg pair exactly one configured gap apart, so widening the "
        "bound to 100y must break that assertion -- unless the test is reading a "
        "literal instead of the config leaf, which is precisely what this entry "
        "exists to detect. If the sweep reports it surviving, the boundary test's "
        "accept case is not reading the setting and that is a defect in the test."
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

    **The ambiguity risk here is the shape of the confidence block**, which
    appears twice in the module (once in ``_sentinel_result``, once in
    ``select_instrument``) with nearly identical text. ``_M6_SENTINEL_CONFIDENCE``
    and ``_M6_EXECUTABLE_CONFIDENCE`` are therefore extended past the shared
    prefix into the distinguishing ``value=value,`` / ``value={`` line. This gate
    is what proves that extension worked.
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

    The near-miss trap for this sweep is that the new test file lives in a
    package that already holds 28 other modules, so a name that differs by one
    word collects zero tests from a plausible-looking path.
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
                "tests/models/test_instrument_selection.py",
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

    **``-x`` IS passed, and it is not optional here** (lesson 61). This selection
    takes a few seconds on a clean tree, but the rule stands: the kill signal
    must be cheap, because the cheap path is the one that gets used -- and the
    sweep that has to be killed by hand is the sweep that leaves the tree
    mutated.
    """
    proc = _run_pytest_inproc(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/models/test_instrument_selection.py",
            "tests/thesis_layer/test_production_universe.py",
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

    **``finally`` is NOT sufficient, and D-057 proved it.** ``SIGTERM`` bypasses
    Python's cleanup entirely, and D-057's first run was stopped by a process
    kill that left ``M5.2`` applied to ``risk_budget.py``. ``main`` therefore
    installs a SIGTERM/SIGINT handler that restores the in-flight mutation before
    exiting. The residual ``SIGKILL`` risk cannot be engineered away, so the
    standing rule is the module docstring's: run the sweep in the FOREGROUND, and
    if it must be stopped, verify the swept selection afterwards.
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
    # exceptions but not SIGTERM, and D-057's first run was stopped by exactly
    # that and left a mutation applied.
    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: select_instrument (Module 15/16.4, Section 22.3.1/22.12, D-058)")
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
            print(f"  {mt.group:4} {mt.path.name:26} {mt.name}")
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
