"""Mutation sweep for Module 8.3's ``credit_spread_attribution``.

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/models/credit_spread.py`` and ``src/macro_engine/config.py``
in place, so any concurrent test run, live check or probe reads a mutated
module. D-049, D-057, D-060 and D-061 all left source mutated when a sweep was
killed mid-run, and the full suite then passed *with the mutation in place*. The
blast radius is the whole repository.

Why this file was rebuilt (D-061, O-62)
---------------------------------------
The D-060 audit found this sweep **exiting 1 on an unexplained survivor** and
recorded it as "``C1d`` — ``observations_measured`` hardcoded to ``0`` — a REAL
missing test, not an inert exemption". **That diagnosis was wrong, and the way it
was wrong is the point of this rebuild.**

Executing the gate that this file did not have showed **three** broken anchors,
not one:

======================================  ==========================================
anchor                                  measured state
======================================  ==========================================
``C1d``                                 **AMBIGUOUS — 8 occurrences** in
                                        ``config.py``. ``str.replace(old, new,
                                        1)`` rewrote the FIRST, which lives in
                                        ``CreditTrendBaseRates`` (line 1464).
                                        The credit-spread model reads
                                        ``CreditSpreadBaseRates`` (line 1495).
                                        The file changed, so the mutation looked
                                        applied; the tests passed, because they
                                        never touch the class that was edited.
``M4a``                                 **ABSENT** — the manual-entry warning was
                                        legitimately rewritten by **D-043**.
``M5e``                                 **ABSENT** — the
                                        ``default_rate_trend_is_manual_entry``
                                        key was renamed by **D-043**.
======================================  ==========================================

So the survivor was a **MIS-TARGET** (D-048's class — "the dangerous one,
because a pattern-miss is visible and a mis-target is not"), plus two mutations
that had silently stopped applying when the source moved under them. All three
surfaced as "weak tests" about code nobody had mutated. **The remedy is
re-anchoring, not a new test** — and the proof is that the *existing* test kills
a correctly-targeted ``C1d``: applied by hand against ``CreditSpreadBaseRates``,
the selection exits **1**; applied the way the old sweep did, it exits **0**.

This is the concrete warrant for ``check_targets``, and the second time in three
increments that a sweep's own score was the misleading part of its output.

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether the attribution is economically right.** The mutations pin the
   branch structure and the disclosures; that ``BOTH`` means what Section 20.8
   says it means is a specification claim, not an arithmetic one.

2. **The manual-input provenance.** D-043 made ``default_rate_trend`` derivable
   from FRED ``DRALACBS``, but *this function* cannot know which route a caller
   used. It publishes what it can verify (``..._is_caller_supplied`` and
   ``..._derived_route_available``); the derivation itself lives in the live
   check.

The honesty control
-------------------
``M9.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything. D-051 built the control; D-059 was the
first increment where it **fired**, exposing a dead test that had inflated the
first run to a false ``31/31``.

Anchors
-------
Every anchor is verified against the SHIPPED source by ``check_targets`` before a
single mutation is applied — present **exactly once**. Formatting drift and
source movement are both known traps (lessons 50 and 62); a long anchor over a
concatenated string is therefore **sliced from the file at import time** rather
than transcribed, so it cannot drift.
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
SRC = REPO / "src/macro_engine/models/credit_spread.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#:
#: ``tests/models/test_credit_spread.py`` carries the behavioural assertions.
#: ``tests/test_infrastructure.py`` is included because the ``config.py`` mutants
#: land on the ``BaseRates`` classes and the accessor/field-collision guard.
PYTEST_TARGETS = [
    "tests/models/test_credit_spread.py",
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


def _slice_source(path: Path, first: str, last: str) -> str:
    """Return the source text from the line containing ``first`` to ``last``.

    Raises at import if either marker is absent, so a drift is a loud failure
    rather than a silent no-op mutation. This is D-059's ``M6.2`` fix, and it is
    what makes the long anchors below safe to keep readable.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if first in ln), None)
    if start is None:
        raise RuntimeError(f"anchor start not found in {path.name}: {first!r}")
    end = next((i for i in range(start, len(lines)) if last in lines[i]), None)
    if end is None:
        raise RuntimeError(f"anchor end not found in {path.name}: {last!r}")
    return "".join(lines[start : end + 1])


# --- M1/M3: the branch logic ------------------------------------------------
_FUNDAMENTAL = '    fundamental = inputs.default_rate_trend == "rising"'
_TECHNICAL = (
    "    technical = inputs.equity_vol_change_pct > settings.equity_vol_spike_threshold_pct"
)
_WIDENING_GUARD = "    widening_observed = inputs.hy_spread_change_bp > 0.0"
_BRANCH_ORDER = (
    "    elif fundamental and technical:\n"
    '        attribution = "BOTH"\n'
    '        durability = "elevated_concern"\n'
    "    elif fundamental:\n"
    '        attribution = "FUNDAMENTAL"\n'
    '        durability = "sticky_slow_to_reverse"'
)

# --- M2: thresholds from config ---------------------------------------------
# Must match the source byte for byte, so it cannot be reflowed for line length.
_PARALLEL = (
    "    parallel_widening = abs(differentiation_bp) <= settings.differentiation_threshold_bp"
)

# --- M4: the disclosures ----------------------------------------------------

# D-043 rewrote this warning (it is no longer "MANUAL ENTRY, not sourced" — the
# derivation route exists). The old hand-transcribed anchor went ABSENT and the
# mutation silently stopped applying. Sliced, so the next rewrite fails loudly.
_MANUAL_WARNING = _slice_source(
    SRC,
    '"default_rate_trend is a CALLER INPUT and the model cannot verify its "',
    '"who enters it by hand is half the verdict, entered as a judgement.",',
)
_DIAGNOSTIC_WARNING = (
    '        "The HY-minus-IG differentiation is a DIAGNOSTIC, not part of the "\n'
    '        "attribution. Section 20.8\'s logic reads only default_rate_trend and "\n'
    '        "equity_vol_change_pct; the two spread changes are reported because the "\n'
    '        "output would otherwise claim inputs it never used.",'
)
_BASE_RATE_WARNING = (
    '        f"Both predicates fire often. Over {settings.base_rates.observations_measured} "\n'
    # The next source line is 108 characters, and the fragment must match it
    # byte-for-byte: shortening the fragment would leave the rest of the warning
    # alive and make this mutation inert (D-035). Hence the E501 suppression.
    '        f"five-day windows, volatility rose past {settings.equity_vol_spike_threshold_pct:.0f}% "\n'
    '        f"in {settings.base_rates.equity_vol_spike_rate:.1%} of them and the high-yield "\n'
    '        f"spread widened at all in {settings.base_rates.widening_rate:.1%}. A widening "\n'
    "        f\"is the slightly LESS likely outcome, so 'spreads widened' alone is not evidence.\","
)
_NO_WIDENING_WARNING = (
    "        warnings.append(\n"
    '            f"The high-yield spread did not widen over the window "\n'
    '            f"({inputs.hy_spread_change_bp:+.1f}bp). There is nothing to attribute, "\n'
    '            f"so the attribution is NO_WIDENING rather than a cause — the "\n'
    '            f"specification would have named one anyway."\n'
    "        )"
)
_PARALLEL_WARNING = (
    "        warnings.append(\n"
    '            f"HY and IG moved within {settings.differentiation_threshold_bp:.1f}bp of "\n'
    '            f"each other ({differentiation_bp:+.1f}bp apart), which is the pattern a "\n'
    '            f"broad risk-aversion move produces. Two thirds of five-day moves are "\n'
    '            f"differentiated, so this is informative but not conclusive."\n'
    "        )"
)

# --- M5: the published components -------------------------------------------
_FUNDAMENTAL_KEY = '            "fundamental": fundamental,'
_TECHNICAL_KEY = '            "technical": technical,'
_WIDENING_KEY = '            "widening_observed": widening_observed,'
_DIFFERENTIATION_KEY = '            "hy_minus_ig_change_bp": round(differentiation_bp, 4),'
_PARALLEL_FLAG_KEY = '            "widenings_are_parallel": parallel_widening,'
# D-043 renamed the manual-entry key. Both halves of the provenance disclosure
# now carry a mutation: the flag itself and the derived-route availability.
_CALLER_SUPPLIED_KEY = '            "default_rate_trend_is_caller_supplied": True,'
_DERIVED_ROUTE_KEY = '            "default_rate_trend_derived_route_available": True,'
_WINDOW_KEY = '            "change_window_days": settings.change_window_days,'

# --- M6: the input contract -------------------------------------------------
_EXTRA_FORBID = '    model_config = ConfigDict(extra="forbid")\n\n    hy_spread_bp: float = Field('
_TREND_LITERAL = "    default_rate_trend: DefaultRateTrend = Field("
_HY_LEVEL_GUARD = "    hy_spread_bp: float = Field(\n        gt=0.0,"

# --- M7: confidence ---------------------------------------------------------
_HEURISTIC_FACTOR = "            is_heuristic_not_calibrated=not _thresholds_calibrated(),"

# --- C1: config accessors ---------------------------------------------------
_WINDOW_PROP = "        return int(self.change_window_days_value.value)"
_SPIKE_PROP = "        return float(self.equity_vol_spike_threshold_pct_value.value)"
_DIFF_PROP = "        return float(self.differentiation_threshold_bp_value.value)"
# `return int(self.observations_measured_value.value)` occurs EIGHT times in
# config.py — once per BaseRates class. Anchoring on the bare line made C1d
# rewrite `CreditTrendBaseRates` instead of `CreditSpreadBaseRates` (the class
# this model reads) and survive as a phantom test gap. The anchor is the
# property's own docstring line plus its body, which is unique.
_MEASURED_PROP = (
    '        """Number of overlapping change windows the three rates below were measured over."""\n'
    "        return int(self.observations_measured_value.value)"
)
_SPIKE_RATE_PROP = "        return float(self.equity_vol_spike_rate_value.value)"
_WIDENING_RATE_PROP = "        return float(self.widening_rate_value.value)"
_PARALLEL_RATE_PROP = "        return float(self.parallel_widening_rate_value.value)"

# --- M9: the honesty control ------------------------------------------------
_CONTROL_OLD = '        attribution = "BOTH"'
_CONTROL_NEW = '        attribution = "BO" + "TH"'


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: the branch logic ------------------------------------------
        Mutation(
            group="M1",
            name="M1a the specification's exclusion RESTORED (makes BOTH dead code again)",
            path=SRC,
            old=_TECHNICAL,
            new=(
                "    technical = (\n"
                "        inputs.equity_vol_change_pct > settings.equity_vol_spike_threshold_pct\n"
                '        and inputs.default_rate_trend != "rising"\n'
                "    )"
            ),
            intent=(
                "The D-037 fix reverted. `BOTH` becomes unreachable, which is the "
                "single most important mutation in this file: if the reachability "
                "test does not catch it, the fix is decoration."
            ),
        ),
        Mutation(
            group="M1",
            name="M1b the BOTH branch is moved below FUNDAMENTAL",
            path=SRC,
            old=_BRANCH_ORDER,
            new=(
                "    elif fundamental:\n"
                '        attribution = "FUNDAMENTAL"\n'
                '        durability = "sticky_slow_to_reverse"\n'
                "    elif fundamental and technical:\n"
                '        attribution = "BOTH"\n'
                '        durability = "elevated_concern"'
            ),
            intent=(
                "Ordering: `fundamental and technical` is swallowed by the earlier "
                "`fundamental` branch, so BOTH is dead while its text survives."
            ),
        ),
        # -- M2: the thresholds --------------------------------------------
        Mutation(
            group="M2",
            name="M2a the spike threshold literal restored (Section 20.8's 20.0)",
            path=SRC,
            old="settings.equity_vol_spike_threshold_pct\n\n    # The check",
            new="20.0\n\n    # The check",
            intent=(
                "Section 20.8's literal in place of the config read. The literal "
                "equals the shipped config value, so this is INERT BY ANCHORING "
                "unless a fixture MOVES the leaf — see the config test."
            ),
        ),
        Mutation(
            group="M2",
            name="M2b the differentiation threshold literal restored",
            path=SRC,
            old=_PARALLEL,
            new="    parallel_widening = abs(differentiation_bp) <= 10.0",
            intent="The config read replaced by the specification's literal.",
        ),
        # -- M3: comparisons and strictness --------------------------------
        Mutation(
            group="M3",
            name="M3a the widening guard admits an unchanged spread",
            path=SRC,
            old=_WIDENING_GUARD,
            new="    widening_observed = inputs.hy_spread_change_bp >= 0.0",
            intent=(
                "A flat spread is attributed rather than refused. The fixture must "
                "sit exactly on 0.0 for `>` and `>=` to differ."
            ),
        ),
        Mutation(
            group="M3",
            name="M3b the spike comparison made strict (exactly the threshold is not a spike)",
            path=SRC,
            old=_TECHNICAL,
            new=_TECHNICAL.replace("pct > settings", "pct >= settings"),
            intent="A boundary fixture exactly on the threshold is required to see this.",
        ),
        Mutation(
            group="M3",
            name="M3c the fundamental predicate inverted (a falling trend is fundamental)",
            path=SRC,
            old=_FUNDAMENTAL,
            new='    fundamental = inputs.default_rate_trend != "rising"',
            intent="The predicate's sign, which decides half the attribution.",
        ),
        Mutation(
            group="M3",
            name="M3d the parallel band made strict (exactly the threshold is not parallel)",
            path=SRC,
            old=_PARALLEL,
            new=_PARALLEL.replace("<= settings", "< settings"),
            intent="Strictness at the band edge; needs a fixture exactly on the threshold.",
        ),
        # -- M4: the disclosures -------------------------------------------
        Mutation(
            group="M4",
            name="M4a the caller-input disclosure dropped (half the verdict is hand-entered)",
            path=SRC,
            old=_MANUAL_WARNING,
            new='        "Model output follows.",',
            intent=(
                "The D-043-rewritten disclosure. Re-pointed in D-061 after the old "
                "anchor went ABSENT when D-043 changed the source."
            ),
        ),
        Mutation(
            group="M4",
            name="M4b the diagnostic disclaimer dropped (a reader may treat it as a predicate)",
            path=SRC,
            old=_DIAGNOSTIC_WARNING,
            new='        "Model output follows.",',
            intent="A disclosure with no arithmetic consequence at all.",
        ),
        Mutation(
            group="M4",
            name="M4c the base-rate warning dropped (D-029 disclosure)",
            path=SRC,
            old=_BASE_RATE_WARNING,
            new='        "Model output follows.",',
            intent=(
                "D-029's rule: a threshold comparison that decides a categorical "
                "must travel with the rate at which it fires."
            ),
        ),
        Mutation(
            group="M4",
            name="M4d the no-widening warning dropped",
            path=SRC,
            old=_NO_WIDENING_WARNING,
            new="        pass",
            intent="The refusal path loses its explanation.",
        ),
        Mutation(
            group="M4",
            name="M4e the parallel-widening warning dropped",
            path=SRC,
            old=_PARALLEL_WARNING,
            new="        pass",
            intent="The diagnostic warning becomes dead code.",
        ),
        # -- M5: the published components ----------------------------------
        Mutation(
            group="M5",
            name="M5a the fundamental predicate dropped from the published value",
            path=SRC,
            old=_FUNDAMENTAL_KEY,
            new='            "unused_fundamental": fundamental,',
            intent="Breaks the D-009 cross-field identity: the verdict is no longer recomputable.",
        ),
        Mutation(
            group="M5",
            name="M5b the technical predicate dropped from the published value",
            path=SRC,
            old=_TECHNICAL_KEY,
            new='            "unused_technical": technical,',
            intent="Mirror of M5a for the other predicate.",
        ),
        Mutation(
            group="M5",
            name="M5c the widening flag dropped from the published value",
            path=SRC,
            old=_WIDENING_KEY,
            new='            "unused_widening": widening_observed,',
            intent="The flag that distinguishes NO_WIDENING from a real attribution.",
        ),
        Mutation(
            group="M5",
            name="M5d the differentiation dropped (the diagnostic stops being published)",
            path=SRC,
            old=_DIFFERENTIATION_KEY,
            new='            "hy_minus_ig_change_bp": 0.0,',
            intent="A published diagnostic replaced by a constant.",
        ),
        Mutation(
            group="M5",
            name="M5e the caller-supplied flag set False",
            path=SRC,
            old=_CALLER_SUPPLIED_KEY,
            new='            "default_rate_trend_is_caller_supplied": False,',
            intent=(
                "The D-043 replacement key. Re-pointed in D-061; the old anchor "
                "named the retired `..._is_manual_entry` key and went ABSENT."
            ),
        ),
        Mutation(
            group="M5",
            name="M5f the change window dropped from the published value",
            path=SRC,
            old=_WINDOW_KEY,
            new='            "change_window_days": 0,',
            intent="A published window replaced by a constant that no window can equal.",
        ),
        Mutation(
            group="M5",
            name="M5g the derived-route availability flag set False",
            path=SRC,
            old=_DERIVED_ROUTE_KEY,
            new='            "default_rate_trend_derived_route_available": False,',
            intent=(
                "NEW in D-061: this published key had NO mutation and NO test, so "
                "it was a disclosure that could have been deleted without "
                "consequence (the D-045 rule). A companion test now pins it."
            ),
        ),
        Mutation(
            group="M5",
            name="M5h the parallel-widening flag set False",
            path=SRC,
            old=_PARALLEL_FLAG_KEY,
            new='            "widenings_are_parallel": False,',
            intent=(
                "NEW in D-061: published and asserted, but previously unmutable. "
                "A mutation only proves something when the mutant can be caught."
            ),
        ),
        # -- M6: the input contract ----------------------------------------
        Mutation(
            group="M6",
            name="M6a extra='forbid' removed from the input model",
            path=SRC,
            old=_EXTRA_FORBID,
            new="    hy_spread_bp: float = Field(",
            intent="A misspelled field is silently ignored instead of refused.",
        ),
        Mutation(
            group="M6",
            name="M6b the trend typed as a bare str instead of a Literal",
            path=SRC,
            old=_TREND_LITERAL,
            new="    default_rate_trend: str = Field(",
            intent=(
                "D-029's enumerated-field rule: a bare str lets a typo fall "
                "through to the permissive branch."
            ),
        ),
        Mutation(
            group="M6",
            name="M6c the spread-level guard weakened to allow zero",
            path=SRC,
            old=_HY_LEVEL_GUARD,
            new="    hy_spread_bp: float = Field(\n        ge=0.0,",
            intent="A zero spread level becomes legal, so the unit convention is unpinned.",
        ),
        # -- M7: confidence ------------------------------------------------
        Mutation(
            group="M7",
            name="M7a the heuristic factor hardcoded False (the penalty stops applying)",
            path=SRC,
            old=_HEURISTIC_FACTOR,
            new="            is_heuristic_not_calibrated=False,",
            intent="Section 22.8: an uncalibrated threshold must not be scored as calibrated.",
        ),
        Mutation(
            group="M7",
            name="M7b confidence hardcoded to the specification's 0.45",
            path=SRC,
            old="        confidence=confidence,",
            new="        confidence=0.45,",
            intent=(
                "Section 22.8 forbids a hardcoded confidence. Note the assertion "
                "must be on a DISCRIMINATING property: the computed value could "
                "coincide with 0.45 on some config."
            ),
        ),
        # -- C1: config accessors ------------------------------------------
        Mutation(
            group="C1",
            name="C1a change_window_days returns a hardcoded value",
            path=CONFIG,
            old=_WINDOW_PROP,
            new="        return 1",
            intent="The window is the most consequential unspecified parameter here.",
        ),
        Mutation(
            group="C1",
            name="C1b the spike threshold property returns a hardcoded value",
            path=CONFIG,
            old=_SPIKE_PROP,
            new="        return 1.0",
            intent="A hardcoded threshold at a value no fixture uses.",
        ),
        Mutation(
            group="C1",
            name="C1c the differentiation threshold returns a hardcoded value",
            path=CONFIG,
            old=_DIFF_PROP,
            new="        return 1.0",
            intent="Mirror of C1b for the diagnostic band.",
        ),
        Mutation(
            group="C1",
            name="C1d observations_measured returns a hardcoded 0",
            path=CONFIG,
            old=_MEASURED_PROP,
            new=(
                '        """Number of overlapping change windows the three rates '
                'below were measured over."""\n'
                "        return 0"
            ),
            intent=(
                "D-029's disclosure number. **Re-anchored in D-061**: the bare "
                "body line occurs 8x in config.py, so the old anchor rewrote "
                "`CreditTrendBaseRates` and survived as a phantom gap. With the "
                "anchor extended to the docstring it lands on "
                "`CreditSpreadBaseRates`, and the EXISTING test kills it."
            ),
        ),
        Mutation(
            group="C1",
            name="C1e the spike rate property reads the widening rate (swapped)",
            path=CONFIG,
            old=_SPIKE_RATE_PROP,
            new="        return float(self.widening_rate_value.value)",
            intent="A swap between two same-typed leaves; only DISTINCT fixture values see it.",
        ),
        Mutation(
            group="C1",
            name="C1f the widening rate property reads the parallel rate (swapped)",
            path=CONFIG,
            old=_WIDENING_RATE_PROP,
            new="        return float(self.parallel_widening_rate_value.value)",
            intent="The second leg of the swap chain.",
        ),
        Mutation(
            group="C1",
            name="C1g the parallel rate property reads the widening rate (swapped)",
            path=CONFIG,
            old=_PARALLEL_RATE_PROP,
            new="        return float(self.widening_rate_value.value)",
            intent="The third leg of the swap chain.",
        ),
        # -- M9: the honesty control ---------------------------------------
        Mutation(
            group="M9",
            name="M9.1 the BOTH label is built by string concatenation (CONTROL)",
            path=SRC,
            old=_CONTROL_OLD,
            new=_CONTROL_NEW,
            intent=(
                "Semantically IDENTICAL to the shipped code. SURVIVAL IS REQUIRED: "
                "if the sweep reports this killed it cannot justify its own kills."
            ),
            expect_killed=False,
            inert_proof=(
                "HONESTY CONTROL. `'BO' + 'TH'` and `'BOTH'` are the same string, "
                "so this mutation cannot change any observable. Its survival is a "
                "requirement, not a finding — D-051's first draft lacked one and "
                "reported a false 56/56, and D-059's control is what exposed a "
                "DEAD TEST inflating its first run to a false 31/31."
            ),
        ),
    ]


#: Mutations expected to survive, each of which MUST have an entry in
#: ``_INERT_PROOFS``. A name here without a proof makes the sweep exit 2.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        "M9.1 the BOTH label is built by string concatenation (CONTROL)",
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
    reports a surviving test — a conclusion about code nobody mutated. An ``old``
    appearing zero times means the target has drifted or the source moved.

    **This gate found three defects in this file the moment it was added** (D-061):
    ``C1d`` was AMBIGUOUS (8 occurrences, first in the wrong class), and ``M4a``
    and ``M5e`` were ABSENT because D-043 had rewritten the source under them.
    All three had been reported as weak tests. See the module docstring.

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
                "tests/models/test_credit_spread.py",
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
            "tests/models/test_credit_spread.py",
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

    Without this a killed sweep leaves mutated source on disk — D-057's first run
    was stopped by a ``SIGTERM`` that bypassed the ``finally`` and had to be
    repaired by hand, and D-060's incident left TWO files falsified and read as
    weak tests for hours.
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
    print("mutation sweep: credit_spread_attribution (Module 8.3, D-061 repair)")
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

    control_name = "M9.1 the BOTH label is built by string concatenation (CONTROL)"
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
