"""Mutation sweep for ``construct_cross_market_rv`` (Module 15.3, D-062).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/models/yield_curve.py`` and ``src/macro_engine/config.py`` in
place, so any concurrent test run, live check or probe reads a mutated module.
The blast radius is the whole repository.

What this increment is really testing
-------------------------------------
Section 20.12's constructor has **no input contract and no guard of any kind**,
and its headline number has a **sign nobody checked**. ``degradation =
correlation_normal - correlation_stressed`` with ``correlation_stressed``
defaulting to a literal ``0.9`` — which is above the normal correlation of
**every one of the eight real US cross-market pairs measured** (D-062 probe P2,
max ``0.820``). So on the specification's own default the published
``hedge_degradation`` is negative for 8 of 8 pairs: it asserts, universally and
silently, that the hedge *improves* in a crisis.

That gives this sweep an unusual shape. The centre mutations (``M2``) are not
about arithmetic being wrong — they are about a **sign the specification never
checks**, which is why they are killed by a partition test rather than by a
value assertion. ``M3`` mutates the *route* by which the stressed correlation
arrived, because a default and a measurement of *this pair* are different claims
that the number alone cannot distinguish.

What this sweep structurally CANNOT find
----------------------------------------
1. **That the common factor actually cancels.** The function has no prices, so
   no mutation makes it *detect* the ``N*D``-versus-``N*P*D`` gap. That lives in
   the live cross-check (``scripts/live_cross_market_rv.py``) and ships as
   **O-57**/**O-59**; ``M6.3`` mutates the scope disclosure that carries it.

2. **That the configured ``risk.stress_correlation`` is the wrong value.** The
   sweep can prove the leaf is READ (``M3.2`` is killed only because a test
   moves it), not that ``0.9`` describes anything. The measurement is in the
   live check and the leaf's own note.

3. **The seam with ``select_instrument``.** Section 22.3.1's ``ThesisType`` has
   no cross-market RV family, so there is no route to close — a fact about the
   specification, recorded as a finding rather than testable here.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. D-059 was the first increment where
that control FIRED, exposing a dead test that had inflated the first run to a
false ``31/31``.

Anchors
-------
Every anchor is verified against the SHIPPED source by ``check_targets`` before
a single mutation is applied — present **exactly once**. This file lives in a
module that already holds two swept functions, so the ambiguity risk is the
D-060 class: ``construct_duration_weighted_curve_trade`` and
``construct_breakeven_trade`` sit in the same file, and a generic statement like
``if abs(net_duration_residual) >= ...`` now appears in **two** places. Long
anchors over concatenated strings are SLICED from the file at import time.
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
YIELD_CURVE = REPO / "src/macro_engine/models/yield_curve.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/models/test_cross_market_rv.py`` carries the behavioural assertions.
#: ``tests/models/test_curve_trade.py`` and ``tests/models/test_breakeven_trade.py``
#: are included because the new code shares a module with both, and
#: ``tests/test_infrastructure.py`` because the ``config.py`` mutants land on
#: ``CrossMarketRVSettings`` and on the accessor-collision guard.
PYTEST_TARGETS = [
    "tests/models/test_cross_market_rv.py",
    "tests/models/test_curve_trade.py",
    "tests/models/test_breakeven_trade.py",
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
# Anchors — read out of the shipped source, never transcribed from memory
# ---------------------------------------------------------------------------


def _slice_source(path: Path, first: str, last: str, *, after: str | None = None) -> str:
    """Return the source text from the line containing ``first`` to ``last``.

    ``after`` is a marker that must appear **before** ``first``; the search for
    ``first`` begins on the line after it. It exists because of a defect this
    increment found live: ``check_targets`` proves an anchor is **unique**, and
    it cannot prove the anchor is in the **right function**. ``_M8_CONFIDENCE``
    was anchored on ``confidence=compute_confidence(``, which occurs first in
    ``curve_slope`` — so the mutant rewrote a neighbouring function's confidence,
    the sweep's own selection did not cover it, and it was reported as a
    surviving test about code nobody had touched (D-048's mis-target, which
    "is not visible: the file *does* change"). Passing ``after="def
    construct_cross_market_rv("`` makes the landing site explicit and fails
    loudly at import when it drifts.
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


#: The top-level symbols this increment owns in each file. An anchor that lands
#: anywhere else is a mis-target: the mutant changes a neighbouring function, the
#: tests that would catch it are not in this sweep's selection, and the sweep
#: reports a survivor -- a conclusion about code nobody mutated.
_ALLOWED_ANCHOR_OWNERS: dict[str, frozenset[str]] = {
    "yield_curve.py": frozenset({"construct_cross_market_rv", "CrossMarketRVInputs"}),
    "config.py": frozenset({"CrossMarketRVSettings", "RiskSettings"}),
}


# --- M1: the arithmetic ------------------------------------------------------
_M1_RATIO = "    duration_ratio = inputs.duration_a / inputs.duration_b"
_M1_NOTIONAL = "    notional_b = inputs.target_notional_a * duration_ratio"
_M1_DUR_DOLLARS_B = "    duration_dollars_b = notional_b * inputs.duration_b"
_M1_RESIDUAL = "    net_duration_residual = duration_dollars_a - duration_dollars_b"

# --- M2: the three-way direction ---------------------------------------------
_M2_EQUALITY = "    if degradation == 0.0:"
_M2_POSITIVE = "    elif degradation > 0.0:"
_M2_LABEL_DEGRADES = '        hedge_direction = "degrades_under_stress"'
_M2_LABEL_IMPROVES = '        hedge_direction = "improves_under_stress"'

# --- M3: the route the stressed correlation arrived by -----------------------
_M3_SUPPLIED = "    supplied = inputs.correlation_stressed"
_M3_DEFAULT_READ = "        correlation_stressed = root_settings.risk.stress_corr"
_M3_SOURCE_DEFAULT = '        stressed_source: CorrelationStressedSource = "config_default"'
_M3_SOURCE_CALLER = '        stressed_source = "caller_supplied"'

# --- M4: the plausibility bound ----------------------------------------------
_M4_BOUND = "    degradation_bound = settings.hedge_degradation_bound"
_M4_COMPARISON = "    exceeds_bound = abs(degradation) > degradation_bound"

# --- M5: the published value -------------------------------------------------
_M5_KEY_DIRECTION = '            "hedge_direction": hedge_direction,'
_M5_KEY_SOURCE = '            "correlation_stressed_source": stressed_source,'
# The definitional key appears in ALL THREE constructors in this module, so the
# anchor is sliced through the next key, which is unique to this one.
_M5_KEY_DEFINITIONAL = _slice_source(
    YIELD_CURVE,
    '"net_duration_residual_is_definitional": True,',
    '"correlation_normal": correlation_normal,',
    after="def construct_cross_market_rv(",
)
_M5_KEY_BOUND_FLAG = '            "hedge_degradation_exceeds_plausible_bound": exceeds_bound,'
_M5_KEY_MARKET_A = '            "market_a_long": inputs.market_a,'
_M5_KEY_DEGRADATION = '            "hedge_degradation": round(degradation, 3),'

# --- M6: the warnings --------------------------------------------------------
# The three unconditional warnings are concatenated strings, so they are sliced.
_M6_LTCM = _slice_source(
    YIELD_CURVE,
    '"HEDGE IS A MODELING ASSUMPTION, NOT A GUARANTEE',
    '"is correlated with crisis (LTCM 1998)",',
)
_M6_LEVERAGE = _slice_source(
    YIELD_CURVE,
    '"Lower apparent risk invites HIGHER leverage',
    '"actual LTCM failure mechanism",',
)
_M6_SCOPE = _slice_source(
    YIELD_CURVE,
    '"SCOPE — the instrument set behind this constructor is US-only through "',
    '"fabricate one.",',
)
# The conditional warnings are guarded, so the GUARD is disabled rather than the
# message rephrased -- mutating an f-string leaves the asserted phrase alive
# (D-046).
_M6_IMPROVES_GUARD = '    if hedge_direction == "improves_under_stress":'
_M6_DEFAULT_GUARD = '    if stressed_source == "config_default":'
_M6_BOUND_GUARD = "    if exceeds_bound:"
# Shared verbatim with both siblings; sliced through the warning it guards.
_M6_ATTESTATION_GUARD = _slice_source(
    YIELD_CURVE,
    "    if not inputs.duration_is_modified:",
    '"Durations were not attested as MODIFIED. Macaulay duration is "',
    after="def construct_cross_market_rv(",
)
_M6_RESIDUAL_GUARD = (
    "    if abs(net_duration_residual) >= root_settings.curve_trade.display_tolerance:"
)

# --- M7: the input contract --------------------------------------------------
_M7_EXTRA_FORBID = '    model_config = ConfigDict(extra="forbid")\n\n    market_a: str = Field('
_M7_SAME_MARKET = "        if a.casefold() == b.casefold():"
_M7_EMPTY_LABEL = "        if not a or not b:"
_M7_DURATION_BAND = "            if not floor <= duration <= ceiling:"
# `settings.minimum_duration` is a SUBSTRING of the siblings'
# `settings.minimum_duration_to_tenor`, so the bare line counts 3x. The two-line
# form is unique to this constructor.
_M7_BAND_FLOOR = (
    "        floor = settings.minimum_duration\n        ceiling = settings.maximum_duration"
)

# --- M8: confidence and scope ------------------------------------------------
# `confidence=compute_confidence(` occurs FIRST in `curve_slope` -- the
# mis-target this increment found live. Scoped to this function.
_M8_CONFIDENCE = _slice_source(
    YIELD_CURVE,
    "        confidence=compute_confidence(",
    "        ),",
    after='            "hedge_degradation_exceeds_plausible_bound": exceeds_bound,',
)
# `country="us",` appears 8x in this module; anchored through the comment that
# only this function carries.
_M8_COUNTRY = _slice_source(
    YIELD_CURVE,
    '# `country="global"` contradicts the contract it is written against.',
    '        country="us",',
)

# --- C1: the config accessors ------------------------------------------------
_C1_MIN_DURATION = "        return float(self.minimum_duration_years.value)"
_C1_MAX_DURATION = "        return float(self.maximum_duration_years.value)"
_C1_BOUND = "        return float(self.max_abs_hedge_degradation.value)"
_C1_STRESS_CORR = "        return float(self.stress_correlation.value)"

# --- M9: the honesty control -------------------------------------------------
_M9_CONTROL_OLD = '        hedge_direction = "unchanged"'
_M9_CONTROL_NEW = '        hedge_direction = "un" + "changed"'


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: the arithmetic --------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 the duration ratio is inverted",
            path=YIELD_CURVE,
            old=_M1_RATIO,
            new="    duration_ratio = inputs.duration_b / inputs.duration_a",
            intent="The single most consequential arithmetic error available here.",
        ),
        Mutation(
            group="M1",
            name="M1.2 the notional is the other leg's duration applied to itself",
            path=YIELD_CURVE,
            old=_M1_NOTIONAL,
            new="    notional_b = inputs.duration_b * duration_ratio",
            intent="The short leg's notional stops depending on the target notional.",
        ),
        Mutation(
            group="M1",
            name="M1.3 the short leg's duration-dollars use the wrong duration",
            path=YIELD_CURVE,
            old=_M1_DUR_DOLLARS_B,
            new="    duration_dollars_b = notional_b * inputs.duration_a",
            intent="Breaks the D-009 cross-field identity the output is checked against.",
        ),
        Mutation(
            group="M1",
            name="M1.4 the residual adds instead of subtracting",
            path=YIELD_CURVE,
            old=_M1_RESIDUAL,
            new="    net_duration_residual = duration_dollars_a + duration_dollars_b",
            intent=(
                "The residual is definitional, so the shipped value is exactly "
                "zero and the mutant makes it 2*x -- a large number, which "
                "PUBLISHES A WARNING where the shipped contract publishes none. "
                "Killed by an ABSENCE assertion (D-038's 'absence half')."
            ),
        ),
        # -- M2: the three-way direction ------------------------------------
        Mutation(
            group="M2",
            name="M2.1 the equality branch is removed (unchanged becomes unreachable)",
            path=YIELD_CURVE,
            old=_M2_EQUALITY,
            new="    if False:",
            intent=(
                "An unchanged correlation falls through to the positive branch "
                "and reports as a degrading hedge. Only a fixture sitting exactly "
                "on zero sees it."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.2 the comparison becomes inclusive (unchanged still reachable)",
            path=YIELD_CURVE,
            old=_M2_EQUALITY,
            new="    if degradation >= 0.0:",
            intent=(
                "The other half of the boundary: `unchanged` is still reachable "
                "but `degrades_under_stress` is now unreachable, because zero is "
                "consumed first."
            ),
        ),
        Mutation(
            group="M2",
            name="M2.3 the comparator inverts (a degrading hedge reports as improving)",
            path=YIELD_CURVE,
            old=_M2_POSITIVE,
            new="    elif degradation < 0.0:",
            intent="The sign of the whole function's output.",
        ),
        Mutation(
            group="M2",
            name="M2.4 the two non-equal direction labels swap",
            path=YIELD_CURVE,
            old=_M2_LABEL_DEGRADES,
            new='        hedge_direction = "improves_under_stress"',
            intent=(
                "The common-case label is wrong. The default route publishes the "
                "other label, so a test covering only one direction cannot see it."
            ),
        ),
        # -- M3: the route --------------------------------------------------
        Mutation(
            group="M3",
            name="M3.1 the supplied/default branch inverts",
            path=YIELD_CURVE,
            old=_M3_SUPPLIED,
            new="    supplied = None if inputs.correlation_stressed is not None else 0.0",
            intent="A supplied value is discarded and the config default used instead.",
        ),
        Mutation(
            group="M3",
            name="M3.2 the config read is replaced by the specification's literal",
            path=YIELD_CURVE,
            old=_M3_DEFAULT_READ,
            new="        correlation_stressed = 0.9",
            intent=(
                "Section 20.12's literal default, in place of the config read. "
                "The literal EQUALS the shipped leaf, so this is INERT BY "
                "ANCHORING unless a test MOVES the leaf -- which "
                "test_the_default_route_reads_the_config_leaf_rather_than_a_literal "
                "does. See _INERT_PROOFS if it survives."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.3 the config-default source label becomes caller_supplied",
            path=YIELD_CURVE,
            old=_M3_SOURCE_DEFAULT,
            new='        stressed_source: CorrelationStressedSource = "caller_supplied"',
            intent=(
                "The route disclosure lies about which route ran, so the "
                "'was NOT supplied' warning never fires."
            ),
        ),
        Mutation(
            group="M3",
            name="M3.4 the caller-supplied source label becomes config_default",
            path=YIELD_CURVE,
            old=_M3_SOURCE_CALLER,
            new='        stressed_source = "config_default"',
            intent=(
                "Mirror of M3.3: a caller who supplied the pair's own number is "
                "told it was defaulted."
            ),
        ),
        # -- M4: the plausibility bound -------------------------------------
        Mutation(
            group="M4",
            name="M4.1 the bound accessor is replaced by a literal",
            path=YIELD_CURVE,
            old=_M4_BOUND,
            new="    degradation_bound = 0.5",
            intent=(
                "A literal equal to the shipped leaf: invisible unless the test "
                "moves the leaf, which test_the_bound_accessor_reads_the_config_leaf "
                "does."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.2 the comparison becomes inclusive",
            path=YIELD_CURVE,
            old=_M4_COMPARISON,
            new="    exceeds_bound = abs(degradation) >= degradation_bound",
            intent=(
                "Differs only on the exact bound, so the fixture must sit ON it "
                "(D-055 shipped a fixture a hair below its boundary and the "
                "mutant survived)."
            ),
        ),
        Mutation(
            group="M4",
            name="M4.3 the absolute value is dropped",
            path=YIELD_CURVE,
            old=_M4_COMPARISON,
            new="    exceeds_bound = degradation > degradation_bound",
            intent="A large NEGATIVE degradation stops being flagged -- the default's sign.",
        ),
        # -- M5: the published value ----------------------------------------
        Mutation(
            group="M5",
            name="M5.1 the hedge direction key is renamed",
            path=YIELD_CURVE,
            old=_M5_KEY_DIRECTION,
            new='            "unused_hedge_direction": hedge_direction,',
            intent="The key the whole increment exists to publish.",
        ),
        Mutation(
            group="M5",
            name="M5.2 the route key is renamed",
            path=YIELD_CURVE,
            old=_M5_KEY_SOURCE,
            new='            "unused_source": stressed_source,',
            intent="The route disclosure stops being published.",
        ),
        Mutation(
            group="M5",
            name="M5.3 the definitional flag is flipped",
            path=YIELD_CURVE,
            old=_M5_KEY_DEFINITIONAL,
            new='            "net_duration_residual_is_definitional": False,',
            intent=("The ONLY pin on the residual's status, since the value itself is a constant."),
        ),
        Mutation(
            group="M5",
            name="M5.4 the bound flag is hardcoded False",
            path=YIELD_CURVE,
            old=_M5_KEY_BOUND_FLAG,
            new='            "hedge_degradation_exceeds_plausible_bound": False,',
            intent="The published flag stops following the arithmetic.",
        ),
        Mutation(
            group="M5",
            name="M5.5 the long leg publishes the short market's label",
            path=YIELD_CURVE,
            old=_M5_KEY_MARKET_A,
            new='            "market_a_long": inputs.market_b,',
            intent="The legs are mislabelled in the output while the arithmetic is right.",
        ),
        Mutation(
            group="M5",
            name="M5.6 the degradation is published unrounded from the wrong quantity",
            path=YIELD_CURVE,
            old=_M5_KEY_DEGRADATION,
            new='            "hedge_degradation": round(correlation_normal, 3),',
            intent="Publishes one correlation as the degradation of the pair.",
        ),
        # -- M6: the warnings -----------------------------------------------
        Mutation(
            group="M6",
            name="M6.1 the mandatory LTCM warning is dropped",
            path=YIELD_CURVE,
            old=_M6_LTCM,
            new='        "Model output follows.",',
            intent="Section 20.14's golden test asserts this is ALWAYS present.",
        ),
        Mutation(
            group="M6",
            name="M6.2 the leverage warning is dropped",
            path=YIELD_CURVE,
            old=_M6_LEVERAGE,
            new='        "Model output follows.",',
            intent="The other Section 20.12 mandate.",
        ),
        Mutation(
            group="M6",
            name="M6.3 the US-only scope disclosure is dropped",
            path=YIELD_CURVE,
            old=_M6_SCOPE,
            new='        "Model output follows.",',
            intent=(
                "The only place Section 22.3's scope and the N*D-vs-N*P*D "
                "convention reach a caller."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.4 the improves-under-stress warning never fires",
            path=YIELD_CURVE,
            old=_M6_IMPROVES_GUARD,
            new="    if False:",
            intent=(
                "The conditional warning that carries the LTCM mechanism, on the "
                "exact state the specification's default produces."
            ),
        ),
        Mutation(
            group="M6",
            name="M6.5 the config-default disclosure never fires",
            path=YIELD_CURVE,
            old=_M6_DEFAULT_GUARD,
            new="    if False:",
            intent="A caller can no longer tell a default from a measurement.",
        ),
        Mutation(
            group="M6",
            name="M6.6 the plausibility-bound warning never fires",
            path=YIELD_CURVE,
            old=_M6_BOUND_GUARD,
            new="    if False:",
            intent="The bound stops being explained, only flagged.",
        ),
        Mutation(
            group="M6",
            name="M6.7 the unit-attestation warning never fires",
            path=YIELD_CURVE,
            old=_M6_ATTESTATION_GUARD,
            new="    if False:",
            intent="The only disclosure of the Macaulay-vs-modified hazard.",
        ),
        Mutation(
            group="M6",
            name="M6.8 the definitional-residual warning never fires",
            path=YIELD_CURVE,
            old=_M6_RESIDUAL_GUARD,
            new="    if False:",
            intent="Float noise in the notional multiplication stops being disclosed.",
        ),
        # -- M7: the input contract -----------------------------------------
        Mutation(
            group="M7",
            name="M7.1 extra='forbid' is overridden with extra='ignore' on the input model",
            path=YIELD_CURVE,
            old=_M7_EXTRA_FORBID,
            new='    model_config = ConfigDict(extra="ignore")\n\n    market_a: str = Field(',
            intent="A misspelled field is silently ignored instead of refused.",
        ),
        Mutation(
            group="M7",
            name="M7.2 the same-market guard is disabled",
            path=YIELD_CURVE,
            old=_M7_SAME_MARKET,
            new="        if False:",
            intent=(
                "Section 20.12 prices a trade that is long and short the same "
                "market. The shipped code refuses it."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.3 the empty-label guard is disabled",
            path=YIELD_CURVE,
            old=_M7_EMPTY_LABEL,
            new="        if False:",
            intent="An unnamed leg is accepted.",
        ),
        Mutation(
            group="M7",
            name="M7.4 the duration band is disabled",
            path=YIELD_CURVE,
            old=_M7_DURATION_BAND,
            new="            if False:",
            intent=(
                "Section 20.12 has no band at all, so a duration wrong by 10x "
                "produces a wrong notional silently."
            ),
        ),
        Mutation(
            group="M7",
            name="M7.5 the band's floor becomes the ceiling",
            path=YIELD_CURVE,
            old=_M7_BAND_FLOOR,
            new="        floor = settings.maximum_duration",
            intent="The band collapses to a point at 30y, refusing every real short leg.",
        ),
        # -- M8: confidence and scope ---------------------------------------
        Mutation(
            group="M8",
            name="M8.1 confidence is hardcoded to the specification's 0.5",
            path=YIELD_CURVE,
            old=_M8_CONFIDENCE,
            new="        confidence=0.5,",
            intent="Section 22.8 forbids a hardcoded confidence.",
        ),
        Mutation(
            group="M8",
            name="M8.2 the country becomes the specification's 'global'",
            path=YIELD_CURVE,
            old=_M8_COUNTRY,
            new='        country="global",',
            intent=(
                "Section 22.3's unearned genericity claim. ModelResult.country's "
                "own description says 'us only through Phase 4'."
            ),
        ),
        # -- C1: the config accessors ---------------------------------------
        Mutation(
            group="C1",
            name="C1.1 the duration floor accessor reads the ceiling",
            path=CONFIG,
            old=_C1_MIN_DURATION,
            new="        return float(self.maximum_duration_years.value)",
            intent="The band collapses to a point at 30y.",
        ),
        Mutation(
            group="C1",
            name="C1.2 the duration ceiling accessor reads the floor",
            path=CONFIG,
            old=_C1_MAX_DURATION,
            new="        return float(self.minimum_duration_years.value)",
            intent="Mirror of C1.1: the band collapses to a point at 0.25y.",
        ),
        Mutation(
            group="C1",
            name="C1.3 the degradation bound accessor reads the duration ceiling",
            path=CONFIG,
            old=_C1_BOUND,
            new="        return float(self.maximum_duration_years.value)",
            intent="The bound becomes 30.0, so nothing is ever flagged.",
        ),
        Mutation(
            group="C1",
            name="C1.4 the stressed-correlation accessor reads a different leaf",
            path=CONFIG,
            old=_C1_STRESS_CORR,
            new="        return float(self.rebalancing_drift.value)",
            intent=(
                "The orphan accessor this increment wires as its first consumer "
                "reads an unrelated leaf."
            ),
        ),
        # -- M9: the honesty control ----------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the unchanged label is built by string concatenation (CONTROL)",
            path=YIELD_CURVE,
            old=_M9_CONTROL_OLD,
            new=_M9_CONTROL_NEW,
            intent=(
                "Semantically IDENTICAL to the shipped code. SURVIVAL IS REQUIRED: "
                "if the sweep reports this killed it cannot justify its own kills."
            ),
            expect_killed=False,
            inert_proof=(
                "HONESTY CONTROL. `'un' + 'changed'` and `'unchanged'` are the "
                "same string, so this mutation cannot change any observable. Its "
                "survival is a requirement, not a finding -- D-051's first draft "
                "lacked one and reported a false 56/56, and D-059's control is "
                "what exposed a DEAD TEST inflating its first run to a false 31/31."
            ),
        ),
    ]


#: Mutations expected to survive, each of which MUST have an entry in
#: ``_INERT_PROOFS``. A name here without a proof makes the sweep exit 2.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M9.1 the unchanged label is built by string concatenation (CONTROL)",
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
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test -- a conclusion about code nobody mutated.

    **The ambiguity risk here is the D-060 class and it is live.** This module
    now holds THREE constructors. ``if abs(net_duration_residual) >= ...``
    appears once in ``construct_breakeven_trade`` and once here, which is why
    ``_M6_RESIDUAL_GUARD`` carries the full two-operand form rather than the
    bare comparison. D-060's own sweep was green while D-059's was broken by
    exactly this; both siblings are re-run at close for the same reason.

    It doubles as the clean-tree precondition D-060 asked for: a sweep started
    against an already-mutated tree finds its own anchor ABSENT and **refuses**
    rather than surviving.
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


def check_anchor_landings(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every anchor lands in a symbol THIS increment owns.

    ``check_targets`` proves an anchor is unique; it cannot prove the anchor is
    in the **right place**. A unique fragment belonging to a neighbouring
    function passes silently, the mutant rewrites that function instead, and the
    tests that would catch it are — by construction — not in this sweep's
    selection, so the sweep reports a **survivor** and the reader concludes the
    suite is weak.

    **That is not hypothetical: the first run of this sweep had three of them.**
    ``M5.3`` and ``M6.7`` sliced from the first occurrence of a fragment shared
    with ``construct_duration_weighted_curve_trade``, and ``M8.1`` anchored on
    ``confidence=compute_confidence(``, which occurs first in ``curve_slope``.
    The audit that found them is now this gate.

    This is D-048's mis-target class in its purest form — *"a pattern-miss is
    visible; a mis-target is not: the file does change, so the mutation looks
    applied"* — and it is the second sighting in a single session (the first
    was ``C1d`` in ``mutation_credit_spread.py``).
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
        owner = "<module>"
        for line in reversed(text[:index].splitlines()):
            if line.startswith(("def ", "class ")) and not line.startswith(
                ("    def", "    class")
            ):
                owner = line.split("(")[0].replace("def ", "").replace("class ", "")
                break
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
            continue
        # Inlined as literals rather than passed as `target` because ruff's S603
        # rule treats a variable argument as untrusted input; the loop verifies
        # existence above so the two stay in step.
        proc = _run_pytest_inproc(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/models/test_cross_market_rv.py",
                "tests/models/test_curve_trade.py",
                "tests/models/test_breakeven_trade.py",
                "tests/models/test_yield_curve.py",
                "tests/test_infrastructure.py",
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
    proc = _run_pytest_inproc(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/models/test_cross_market_rv.py",
            "tests/models/test_curve_trade.py",
            "tests/models/test_breakeven_trade.py",
            "tests/models/test_yield_curve.py",
            "tests/test_infrastructure.py",
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

    Without this a killed sweep leaves mutated source on disk -- D-057's first
    run was stopped by a ``SIGTERM`` that bypassed the ``finally`` and had to be
    repaired by hand, and D-060's incident left TWO files falsified and read as
    weak tests for hours. **D-062 reproduced it live**: an interrupted run of an
    UNRELATED legacy sweep left ``MX3d`` applied in this very module.
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

    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: construct_cross_market_rv (Module 15.3, D-062)")
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
            "code nobody mutated (D-048)."
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

    control_name = "M9.1 the unchanged label is built by string concatenation (CONTROL)"
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
