"""Mutation sweep for Module 1's ``check_trilemma_tension``.

Each mutation reverts one D-048 correction — or one piece of the function's
structure — to a plausible alternative, and each must be killed. The mutations
are grouped by what they attack, because a survivor's *class* tells you which
kind of test is missing (D-031).

* **M1** restores Section 15.20-A's own branch chain: one boolean too few, a
  severity swapped, the escalation collapsed.
* **M2** breaks the direction conflict — the string comparison inverted, ``None``
  treated as a conflict, the "both directions needed" guard dropped.
* **M3** restores the ``or 0`` trap and variants of it: an absent reserves
  reading treated as zero, or as a large negative.
* **M4** breaks the reserves logic — the added 1-month branch removed, the
  thresholds swapped, the boundary comparisons made inclusive.
* **M5** drops a disclosure, or a published component.
* **M6** weakens the contract — the guard, ``extra="forbid"``, the enumerated
  direction type, the country literal.
* **M7** reintroduces a hardcoded confidence, or forces the heuristic factor off.
* **C1** swaps or hardcodes the config accessors.
* **K1** inverts the threshold-ordering validator, which is the one piece of the
  config that protects a branch from being dead.

Two of the mutations are expected to **survive by design** and are named so: an
alteration that changes only a docstring cannot change behaviour, and the sweep
would be lying if it reported a kill. They are listed explicitly rather than
omitted, because "no mutation covers this" and "a mutation here is inert" are
different claims.

A survivor is one of four things (D-031, extended by D-047): a weak test, an
**inert** mutation, a **broken** mutation, or a **mis-targeted** mutation — one
that matched something other than what it was aimed at. The runner reports a
pattern-miss separately from a survival, and it **heals before it measures**:
an interrupted run leaves the mutated file on disk, and a naive re-run would
adopt it as the baseline (D-035 rule 19).

**Run this in the FOREGROUND.** The sweep rewrites `regime.py` in place, so
anything that imports the module — another test run, a live check, an ad-hoc
probe — reads a mutated classifier while the sweep is in progress. D-047's
Postscript 2 records a contaminated reading produced exactly that way; the blast
radius of this script is the whole repository, not this one file.
"""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

SRC = Path("src/macro_engine/models/regime.py")
CONFIG = Path("src/macro_engine/config.py")


# --- The shipped text each mutation targets --------------------------------
#
# Every string below was transcribed from the source with its line number noted,
# and the runner reports a pattern-MISS separately from a survival: an `old`
# string that is absent measures nothing while looking like a result. The first
# draft of this script learned that the hard way — 12 of 57 substitutions never
# matched (21%), so a fifth of the sweep was reporting kills and survivors for
# mutations that were never applied.

_CHAIN = (
    "    if all_three and direction_conflict and (depleted_3mo or broke_1mo):\n"
    '        return "CRITICAL_PEG_STRESS", depleted_3mo, broke_1mo\n'
    "    if all_three and direction_conflict:\n"
    '        return "TRILEMMA_VIOLATION", depleted_3mo, broke_1mo\n'
    "    if all_three:\n"
    '        return "TRILEMMA_TENSION", depleted_3mo, broke_1mo\n'
    '    return "NO_TENSION", depleted_3mo, broke_1mo'
)

_ALL_THREE_PROP = (
    "        return (\n"
    "            self.has_fixed_or_managed_fx\n"
    "            and self.has_free_capital_movement\n"
    "            and self.claims_monetary_independence\n"
    "        )"
)

_DIRECTION_PROP = (
    "        return (\n"
    "            self.domestic_policy_direction_needed is not None\n"
    "            and self.peg_defense_direction_required is not None\n"
    "            and self.domestic_policy_direction_needed != self.peg_defense_direction_required\n"
    "        )"
)

_DEPLETED_3MO = "    depleted_3mo = trend_3mo is not None and trend_3mo < depletion_threshold"
_BROKE_1MO = "    broke_1mo = break_1mo is not None and break_1mo < break_threshold"

_CALL_SITE = (
    "    severity, depleted_3mo, broke_1mo = _depletion_severity(\n"
    "        all_three=all_three,\n"
    "        direction_conflict=direction_conflict,\n"
    "        trend_3mo=inputs.reserves_trend_pct_change_3mo,\n"
    "        break_1mo=inputs.reserves_trend_pct_change_1mo,\n"
    "        depletion_threshold=settings.depletion_3mo,\n"
    "        break_threshold=settings.break_1mo,\n"
    "    )"
)

_BASE_RATES_BODY = (
    "    settings = get_settings().regime.trilemma\n"
    "    rates = settings.base_rates\n"
    "    if not rates.measured:\n"
    "        return None\n"
    "    return {\n"
    '        "depletion_3mo": float(rates.depletion_3mo_base_rate.value),\n'
    '        "break_1mo": float(rates.break_1mo_base_rate.value),\n'
    "    }"
)

_CALIBRATED_HELPER = (
    "    return all(\n"
    '        leaf.calibration_status != "uncalibrated_illustrative"\n'
    "        for leaf in (\n"
    "            settings.reserves_depletion_threshold_3mo,\n"
    "            settings.reserves_break_threshold_1mo,\n"
    "        )\n"
    "    )"
)

# The shipped call, comments and all. The comments are part of the match on
# purpose: they are why the call is what it is, and a mutation that replaces the
# whole block cannot accidentally leave one of the two flagged factors behind.
_CONFIDENCE_CALL = (
    "    confidence = compute_confidence(\n"
    "        ConfidenceInputs(\n"
    "            data_quality_flags_present=inputs.data_quality_flags_present,\n"
    "            # The two thresholds are Section 15.20-A's literals plus one fitted\n"
    "            # assumption, none calibrated against realized outcomes.\n"
    "            is_heuristic_not_calibrated=not _trilemma_thresholds_calibrated(),\n"
    "            # NOT a call to count_independent_families(). This function consumes\n"
    "            # three manual classifications and up to two reserves observations,\n"
    "            # so there is no list of tagged ModelResults to count — the trilemma\n"
    "            # legs are not a family in the Section 15.19-D sense, because they\n"
    "            # are not measured evidence at all. Claiming a family here would be\n"
    "            # the D-027 circularity error: the function would credit itself with\n"
    "            # evidence its own caller supplied as an assertion.\n"
    "            source_independence_count=0,\n"
    "            # Whether a currency claims all three legs is unobservable in the\n"
    "            # series sense — it is an institutional classification the caller\n"
    "            # supplies, and no data can contradict it.\n"
    "            depends_on_unobservable=True,\n"
    "        )\n"
    "    )"
)

_GUARD = '    if inputs.country != "us":\n        raise NotImplementedError('

_VALUE_DICT = '        value={\n            "severity": severity,'

_FAMILY_ASSERT = "assert set(get_args(TrilemmaSeverity)) == set(TRILEMMA_SEVERITIES)"

_INPUTS_USED_TAIL = (
    '        "claims_monetary_independence",\n'
    "        *(\n"
    "            name\n"
    "            for name in (\n"
    '                "domestic_policy_direction_needed",\n'
    '                "peg_defense_direction_required",\n'
    "            )\n"
    "            if getattr(inputs, name) is not None\n"
    "        ),\n"
    "        *reserves_horizons,\n"
    "    ]"
)

# --- config.py targets ------------------------------------------------------

_CFG_DEPLETION_PROP = (
    "    def depletion_3mo(self) -> float:\n"
    '        """3-month reserves change below which depletion is asserted. Spec literal."""\n'
    "        return float(self.reserves_depletion_threshold_3mo.value)"
)

_CFG_BREAK_PROP = (
    "    def break_1mo(self) -> float:\n"
    '        """1-month reserves change below which an acute break is asserted."""\n'
    "        return float(self.reserves_break_threshold_1mo.value)"
)

# The `measured` property body is byte-identical in RegimeBaseRates (line ~1830)
# and TrilemmaBaseRates (line ~1886), so the bare one-liner is AMBIGUOUS and
# `str.replace(..., 1)` would rewrite the regime class. Anchored on the
# trilemma-specific docstring so the match is unique.
_CFG_TRILEMMA_MEASURED = (
    "    def observations_measured(self) -> int:\n"
    '        """Number of months the two rates were measured over."""\n'
    "        return int(self.observations_measured_value.value)\n"
    "\n"
    "    @property\n"
    "    def measured(self) -> bool:\n"
    '        """True once a live measurement has recorded a non-zero window."""\n'
    "        return self.observations_measured > 0"
)

_CFG_VALIDATOR = "        if self.break_1mo < self.depletion_3mo:\n            raise ValueError("


# ---------------------------------------------------------------------------
# The behavioural matrix the mutations are derived from
# ---------------------------------------------------------------------------
#
# The table below is GENERATED from facts rather than aimed by hand, because the
# first draft's 21% mis-target rate was not an accident of transcription: a
# hand-written substitution encodes an intention, and an intention can be about
# a line that is not the line that decides the behaviour. Three generators:
#
#   1. `_ALL_THREE_INPUTS` x `_DIRECTION_INPUTS` enumerate the *entire* boolean
#      input plane (8 leg combinations x 9 direction pairs). "One of the three
#      legs is ignored" and "a direction pair is collapsed" therefore cannot
#      hide behind a lucky fixture.
#   2. `_MATRIX_MUTATIONS` rewrites the *decision table itself* — each branch
#      replaced by a wrong constant. A mutation of behaviour cannot fail to
#      match the text, and cannot be satisfied by an input nobody tried.
#   3. `_SEVERITY_RESIDUE` records, per severity, the exact residue the function
#      publishes. Two of the first draft's survivors (M5m the all-three flag
#      dropped, M5n the conflict flag inverted) survived for one reason: no test
#      read those two keys. The matrix makes not-reading-them a failure.
#
# Severity reachability, stated once because the mutations depend on it: with
# all three legs claimed, the fallthrough is `TRILEMMA_TENSION`, so `NO_TENSION`
# is reachable only by dropping a leg.

_LEG_NAMES = (
    "has_fixed_or_managed_fx",
    "has_free_capital_movement",
    "claims_monetary_independence",
)
_DIRECTION_NAMES = ("domestic_policy_direction_needed", "peg_defense_direction_required")
_DIRECTION_VALUES: tuple[str | None, ...] = (None, "easing", "tightening")

#: All 8 leg combinations, keyed by a mask string of the three booleans in
#: `_LEG_NAMES` order — so `"101"` is fixed-FX and independence without free
#: capital.
_ALL_THREE_INPUTS: tuple[tuple[str, dict[str, bool]], ...] = tuple(
    (
        "".join(str(int(b)) for b in bits),
        dict(zip(_LEG_NAMES, bits, strict=True)),
    )
    for bits in itertools.product([False, True], repeat=3)
)

#: All 9 direction pairs, keyed `domestic/peg`.
_DIRECTION_INPUTS: tuple[tuple[str, dict[str, str | None]], ...] = tuple(
    (
        f"{d if d else 'none'}--{p if p else 'none'}",
        dict(zip(_DIRECTION_NAMES, (d, p), strict=True)),
    )
    for d, p in itertools.product(_DIRECTION_VALUES, repeat=2)
)

#: The severity each (legs, directions) point resolves to with reserves gone,
#: computed from the shipped rule and used to keep the generators honest: if a
#: mutation is proposed that the matrix cannot distinguish, this is how we know.
_ESCALATION_TABLE: dict[tuple[bool, bool], str] = {
    (False, False): "NO_TENSION",
    (False, True): "NO_TENSION",
    (True, False): "TRILEMMA_TENSION",
    (True, True): "TRILEMMA_VIOLATION",
}

#: Published residue per severity: which flags must stand where. `None` means
#: "not asserted by this row" — deliberately, so the table says only what it can.
_SEVERITY_RESIDUE: dict[str, dict[str, object]] = {
    "NO_TENSION": {
        "all_three_legs_claimed": False,
        "direction_conflict": False,
        "reserves_depleting_3mo": False,
        "reserves_breaking_1mo": False,
    },
    "TRILEMMA_TENSION": {
        "all_three_legs_claimed": True,
        "direction_conflict": False,
        "reserves_depleting_3mo": True,
        "reserves_breaking_1mo": False,
    },
    "TRILEMMA_VIOLATION": {
        "all_three_legs_claimed": True,
        "direction_conflict": True,
        "reserves_depleting_3mo": True,
        "reserves_breaking_1mo": False,
    },
    "CRITICAL_PEG_STRESS": {
        "all_three_legs_claimed": True,
        "direction_conflict": True,
    },
}


# ---------------------------------------------------------------------------
# The generated mutations
# ---------------------------------------------------------------------------


def _matrix_mutations() -> list[tuple[str, Path, str, str]]:
    """Mutations of the decision table, generated one branch at a time.

    Each of the four branches is replaced by a constant severity, which is the
    strongest form of "this branch is wrong": no input can be chosen that makes
    the mutation agree with the original for every branch, because the branches
    are mutually exclusive by construction. A substitution like this cannot miss
    its pattern (it rewrites the whole `if` chain), so every one of these is
    guaranteed to be a real measurement.
    """
    out: list[tuple[str, Path, str, str]] = []
    # label -> (original text, the severity it should NOT be reporting)
    #
    # The CRITICAL branch carries a six-line comment explaining CORRECTION 3, so
    # its `if` and its `return` are NOT adjacent. A mutation that assumed they
    # were is exactly the mis-targeted class this rewrite exists to eliminate.
    # Only the `return` line is targeted — which is also the line that decides
    # the severity.
    branches = {
        "cri": (
            '        return "CRITICAL_PEG_STRESS", depleted_3mo, broke_1mo',
            "CRITICAL_PEG_STRESS",
            "TRILEMMA_VIOLATION",
        ),
        "vio": (
            '        return "TRILEMMA_VIOLATION", depleted_3mo, broke_1mo',
            "TRILEMMA_VIOLATION",
            "TRILEMMA_TENSION",
        ),
        "ten": (
            '        return "TRILEMMA_TENSION", depleted_3mo, broke_1mo',
            "TRILEMMA_TENSION",
            "NO_TENSION",
        ),
    }
    for label, (original, needle, replacement) in branches.items():
        mutated = original.replace(f'return "{needle}"', f'return "{replacement}"')
        out.append(
            (
                f"MX1{label} the {needle} branch returns {replacement} instead",
                SRC,
                original,
                mutated,
            )
        )
    # The fallthrough — deleting it makes everything it served a TypeError, which
    # the tests catch; replacing it with the *most severe* label is the dangerous
    # version, because it converts "no evidence" into "maximum alarm".
    out.append(
        (
            "MX1fal the fallthrough reports CRITICAL instead of NO_TENSION",
            SRC,
            '    return "NO_TENSION", depleted_3mo, broke_1mo',
            '    return "CRITICAL_PEG_STRESS", depleted_3mo, broke_1mo',
        )
    )
    # The compound condition's two halves, each dropped.
    out.append(
        (
            "MX1c1 the acute branch drops the direction conflict",
            SRC,
            "    if all_three and direction_conflict and (depleted_3mo or broke_1mo):",
            "    if all_three and (depleted_3mo or broke_1mo):",
        )
    )
    out.append(
        (
            "MX1c2 the acute branch drops the reserves requirement",
            SRC,
            "    if all_three and direction_conflict and (depleted_3mo or broke_1mo):",
            "    if all_three and direction_conflict:",
        )
    )
    # `or` vs `and` inside the reserves clause — the two horizons conflated.
    out.append(
        (
            "MX1c3 the acute branch requires BOTH horizons (the spec's single measure)",
            SRC,
            "    if all_three and direction_conflict and (depleted_3mo or broke_1mo):",
            "    if all_three and direction_conflict and (depleted_3mo and broke_1mo):",
        )
    )
    return out


def _leg_mutations() -> list[tuple[str, Path, str, str]]:
    """One mutation per leg of `all_three`, generated from `_LEG_NAMES`.

    Each of the three branches is dropped AND replaced by `True`, because a
    conjunction can be broken in two directions: dropping a leg makes the
    property too permissive (two legs read as three), pinning it to `True` makes
    it too permissive in the other way (any input reads as three). A test that
    only ever supplies all-three-true cannot tell either from the original, and
    the leg enumeration exists to make that impossible.
    """
    out: list[tuple[str, Path, str, str]] = []
    for i, leg in enumerate(_LEG_NAMES):
        lines = [
            "        return (\n",
            "            self.has_fixed_or_managed_fx\n",
            "            and self.has_free_capital_movement\n",
            "            and self.claims_monetary_independence\n",
            "        )",
        ]
        # Drop the leg entirely.
        dropped = [line for j, line in enumerate(lines) if j != i + 1]
        dropped[-1] = lines[-1]  # keep the closing paren
        out.append(
            (
                f"MX2leg{i + 1} `all_three` drops the {leg} leg",
                SRC,
                _ALL_THREE_PROP,
                "".join(dropped).rstrip("\n"),
            )
        )
        # Replace the leg with a literal True.
        pinned = list(lines)
        pinned[i + 1] = "            and True  # mutated\n"
        out.append(
            (
                f"MX2pin{i + 1} `all_three` pins the {leg} leg to True",
                SRC,
                _ALL_THREE_PROP,
                "".join(pinned).rstrip("\n"),
            )
        )
    return out


def _direction_mutations() -> list[tuple[str, Path, str, str]]:
    """The direction property broken six ways, one per failure mode.

    The surviving `M2c` in the first draft was "the conflict ignores one
    direction entirely" — a mutation whose replacement was a *string* the file
    did not contain, so it was counted as applied for the wrong reason. These
    are written against the transcribed property text, and the direction
    enumeration in the test suite is what makes them killable.
    """
    return [
        (
            "MX3a the comparison inverted (agreement reads as conflict)",
            SRC,
            _DIRECTION_PROP,
            _DIRECTION_PROP.replace("!=", "=="),
        ),
        (
            "MX3b an unassessed direction counts as a conflict",
            SRC,
            _DIRECTION_PROP,
            "        return (\n"
            "            self.domestic_policy_direction_needed\n"
            "            != self.peg_defense_direction_required\n"
            "        )",
        ),
        (
            "MX3c only the domestic direction is required",
            SRC,
            _DIRECTION_PROP,
            "        return (\n"
            "            self.domestic_policy_direction_needed is not None\n"
            "            and self.domestic_policy_direction_needed\n"
            "            != self.peg_defense_direction_required\n"
            "        )",
        ),
        (
            "MX3d only the peg direction is required",
            SRC,
            _DIRECTION_PROP,
            "        return (\n"
            "            self.peg_defense_direction_required is not None\n"
            "            and self.domestic_policy_direction_needed\n"
            "            != self.peg_defense_direction_required\n"
            "        )",
        ),
        (
            "MX3e every assessed pair is a conflict (the comparison removed)",
            SRC,
            _DIRECTION_PROP,
            "        return (\n"
            "            self.domestic_policy_direction_needed is not None\n"
            "            and self.peg_defense_direction_required is not None\n"
            "        )",
        ),
        (
            "MX3f the conflict is never reported",
            SRC,
            _DIRECTION_PROP,
            "        return False",
        ),
    ]


def _absurdity_mutations() -> list[tuple[str, Path, str, str]]:
    """The two legs of the specification's convergence failure, on the reserves tests.

    "Absence read as zero" is the `or 0` class: it converts a missing measure
    into a measured calm, which is the D-031 missing-data-as-a-value defect. Its
    mirror — absence read as a large negative — is worse in the other direction,
    and a naive guard written against the first alone will not stop it.
    """
    return [
        (
            "MX4a the specification's `or 0` restored on the 3-month test",
            SRC,
            _DEPLETED_3MO,
            "    depleted_3mo = (trend_3mo or 0.0) < depletion_threshold",
        ),
        (
            "MX4b an absent 3-month reading defaults to a large negative",
            SRC,
            _DEPLETED_3MO,
            "    depleted_3mo = (trend_3mo if trend_3mo is not None else -99.0) "
            "< depletion_threshold",
        ),
        (
            "MX4c the specification's `or 0` restored on the 1-month test",
            SRC,
            _BROKE_1MO,
            "    broke_1mo = (break_1mo or 0.0) < break_threshold",
        ),
        (
            "MX4d an absent 1-month reading defaults to a large negative",
            SRC,
            _BROKE_1MO,
            "    broke_1mo = (break_1mo if break_1mo is not None else -99.0) < break_threshold",
        ),
        (
            "MX4e the 3-month boundary made inclusive",
            SRC,
            _DEPLETED_3MO,
            "    depleted_3mo = trend_3mo is not None and trend_3mo <= depletion_threshold",
        ),
        (
            "MX4f the 1-month boundary made inclusive",
            SRC,
            _BROKE_1MO,
            "    broke_1mo = break_1mo is not None and break_1mo <= break_threshold",
        ),
        (
            "MX4g the 3-month guard dropped against a NaN reading",
            SRC,
            _DEPLETED_3MO,
            "    depleted_3mo = trend_3mo is not None and not (trend_3mo >= depletion_threshold)",
        ),
    ]


def _config_mutations() -> list[tuple[str, Path, str, str]]:
    """The accessors and the ordering validator, in `config.py`.

    These are the mutations that cannot be killed from the model's own test file
    unless the tests read through the accessors — which is the D-035 rule about
    synthetic leaves being distinct. The shipped-literal mutation is the `C1a`
    pattern that never matched in the first draft because the property is one
    line, not the two the mutation assumed.
    """
    return [
        (
            "CX1 the 3-month threshold accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_DEPLETION_PROP,
            "    def depletion_3mo(self) -> float:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return -0.10",
        ),
        (
            "CX2 the 1-month threshold accessor hardcodes the shipped literal",
            CONFIG,
            _CFG_BREAK_PROP,
            "    def break_1mo(self) -> float:\n"
            "        # mutation: the shipped literal replaces the accessor\n"
            "        return -0.07",
        ),
        (
            "CX3 the two threshold accessors swap their leaves",
            CONFIG,
            _CFG_DEPLETION_PROP + "\n\n    @property\n" + _CFG_BREAK_PROP,
            "    def depletion_3mo(self) -> float:\n"
            "        # mutation: reads the 1-month leaf\n"
            "        return float(self.reserves_break_threshold_1mo.value)\n"
            "\n"
            "    @property\n"
            "    def break_1mo(self) -> float:\n"
            "        # mutation: reads the 3-month leaf\n"
            "        return float(self.reserves_depletion_threshold_3mo.value)",
        ),
        (
            "CX7 `measured` is hardcoded False (a measured base rate reads as absent)",
            CONFIG,
            # The trilemma block's own `measured`, NOT the regime block's: the
            # property body is byte-identical in both, and the bare one-liner
            # matches RegimeBaseRates first — so an unanchored mutation rewrites
            # the wrong class and is later reported as a survivor of a change
            # that never touched the code under test.
            _CFG_TRILEMMA_MEASURED,
            "        return False",
        ),
        (
            "CX4 `measured` is hardcoded True (an unmeasured base rate reads as measured)",
            CONFIG,
            _CFG_TRILEMMA_MEASURED,
            "        return True",
        ),
        (
            "CX5 the ordering validator inverted (the pair must now be REVERSED)",
            CONFIG,
            _CFG_VALIDATOR,
            "        if self.break_1mo > self.depletion_3mo:\n            raise ValueError(",
        ),
        (
            "CX6 the ordering validator removed (build passes with a dead branch)",
            CONFIG,
            _CFG_VALIDATOR,
            "        if False:\n            raise ValueError(",
        ),
    ]


def _model_contract_mutations() -> list[tuple[str, Path, str, str]]:
    """The contract, the family, the call site, the base rates, the confidence.

    **Every `old` string here must be unique within its target file.** Six
    mutations in an earlier draft were not, and all six silently mutated the
    WRONG function: `country="us",` appears in both `output_gap_from_snapshot`
    and `check_trilemma_tension`, as do `source_independence_count=0,` and
    `depends_on_unobservable=True,`. ``str.replace(old, new, 1)`` rewrote the
    first occurrence — `output_gap_from_snapshot` — leaving the trilemma
    function untouched, and all six were then reported as survivors of a
    mutation that had never been applied to the code under test.

    That is the purest form of D-031's **mis-targeted** survivor, and it is
    invisible without a uniqueness check: the mutation looks applied (the file
    did change), the tests look weak (they pass), and a reviewer reading the
    survivor list draws the wrong conclusion about the suite. The runner now
    refuses an ambiguous target outright — see `_assert_targets_stable`.
    """
    return [
        (
            "NX1 the country guard removed (any country silently labelled us)",
            SRC,
            _GUARD,
            "    if False:\n        raise NotImplementedError(",
        ),
        (
            "NX2 the guard inverted (us is refused, every other country passes)",
            SRC,
            _GUARD,
            '    if inputs.country == "us":\n        raise NotImplementedError(',
        ),
        (
            "NX3 the result country follows the input instead of the guard",
            SRC,
            # Anchored on the model name so the match is unique: the bare
            # `country="us",` also occurs in output_gap_from_snapshot.
            '        model_name="check_trilemma_tension",\n        country="us",',
            '        model_name="check_trilemma_tension",\n        country=inputs.country,',
        ),
        (
            "NX4 the manual-assessment family replaced by a market family",
            SRC,
            "        source_family=EvidenceSourceFamily.MANUAL_ASSESSMENT,",
            "        source_family=EvidenceSourceFamily.MARKET_PRICE,",
        ),
        (
            "NX5 the severity/family agreement assertion removed",
            SRC,
            _FAMILY_ASSERT,
            "assert True  # mutation removed the D-045a guard",
        ),
        (
            "NX6 the call site feeds the 3-month reading as the 1-month measure",
            SRC,
            _CALL_SITE,
            _CALL_SITE.replace(
                "        break_1mo=inputs.reserves_trend_pct_change_1mo,\n",
                "        break_1mo=inputs.reserves_trend_pct_change_3mo,\n",
            ),
        ),
        (
            "NX7 the call site feeds the 1-month reading as the 3-month measure",
            SRC,
            _CALL_SITE,
            _CALL_SITE.replace(
                "        trend_3mo=inputs.reserves_trend_pct_change_3mo,\n",
                "        trend_3mo=inputs.reserves_trend_pct_change_1mo,\n",
            ),
        ),
        (
            "NX8 the call site passes the 1-month threshold as the depletion threshold",
            SRC,
            _CALL_SITE,
            _CALL_SITE.replace(
                "        depletion_threshold=settings.depletion_3mo,\n",
                "        depletion_threshold=settings.break_1mo,\n",
            ),
        ),
        (
            "NX9 the call site passes the 3-month threshold as the break threshold",
            SRC,
            _CALL_SITE,
            _CALL_SITE.replace(
                "        break_threshold=settings.break_1mo,\n",
                "        break_threshold=settings.depletion_3mo,\n",
            ),
        ),
        (
            "NX10 the unmeasured case returns an empty dict instead of None",
            SRC,
            "    if not rates.measured:\n        return None",
            "    if not rates.measured:\n        return {}",
        ),
        (
            "NX11 the depletion base rate reads the break leaf",
            SRC,
            '        "depletion_3mo": float(rates.depletion_3mo_base_rate.value),',
            '        "depletion_3mo": float(rates.break_1mo_base_rate.value),',
        ),
        (
            "NX11b the break base rate reads the depletion leaf",
            SRC,
            '        "break_1mo": float(rates.break_1mo_base_rate.value),',
            '        "break_1mo": float(rates.depletion_3mo_base_rate.value),',
        ),
        (
            "NX11c the published base rates are the two leaves SWAPPED",
            SRC,
            '        "depletion_3mo": float(rates.depletion_3mo_base_rate.value),\n'
            '        "break_1mo": float(rates.break_1mo_base_rate.value),',
            '        "depletion_3mo": float(rates.break_1mo_base_rate.value),\n'
            '        "break_1mo": float(rates.depletion_3mo_base_rate.value),',
        ),
        (
            "NX12 the calibration helper uses `any` instead of `all`",
            SRC,
            _CALIBRATED_HELPER,
            _CALIBRATED_HELPER.replace("return all(", "return any("),
        ),
        (
            "NX13 the calibration helper tests for a specific status",
            SRC,
            _CALIBRATED_HELPER,
            _CALIBRATED_HELPER.replace(
                ' != "uncalibrated_illustrative"',
                ' == "mechanical_rule"',
            ),
        ),
        (
            "NX14 the heuristic factor forced off (a hardcoded confidence by omission)",
            SRC,
            # Anchored on the comment that precedes it in this function only.
            "            # assumption, none calibrated against realized outcomes.\n"
            "            is_heuristic_not_calibrated=not _trilemma_thresholds_calibrated(),",
            "            # assumption, none calibrated against realized outcomes.\n"
            "            is_heuristic_not_calibrated=False,",
        ),
        (
            "NX15 the unobservable factor forced off",
            SRC,
            # Anchored on the preceding comment: the bare line also appears in
            # output_gap_from_snapshot.
            "            # supplies, and no data can contradict it.\n"
            "            depends_on_unobservable=True,",
            "            # supplies, and no data can contradict it.\n"
            "            depends_on_unobservable=False,",
        ),
        (
            "NX16 an independent family credited (the D-027 circularity restored)",
            SRC,
            # Anchored on the preceding comment, for the same reason as NX15.
            "            # evidence its own caller supplied as an assertion.\n"
            "            source_independence_count=0,",
            "            # evidence its own caller supplied as an assertion.\n"
            "            source_independence_count=1,",
        ),
        (
            "NX17 a hardcoded confidence restored (the specification's 0.7)",
            SRC,
            _CONFIDENCE_CALL,
            "    confidence = 0.7",
        ),
        (
            "NX18 the data-quality flag dropped from the confidence inputs",
            SRC,
            # Anchored on the trilemma-specific comment that precedes it.
            "            # The two thresholds are Section 15.20-A's literals plus one fitted\n"
            "            # assumption, none calibrated against realized outcomes.\n"
            "            is_heuristic_not_calibrated=not _trilemma_thresholds_calibrated(),\n"
            "            # NOT a call to count_independent_families(). This function consumes\n"
            "            # three manual classifications and up to two reserves observations,\n"
            "            # so there is no list of tagged ModelResults to count — the trilemma\n"
            "            # legs are not a family in the Section 15.19-D sense, because they\n"
            "            # are not measured evidence at all. Claiming a family here would be\n"
            "            # the D-027 circularity error: the function would credit itself with\n"
            "            # evidence its own caller supplied as an assertion.\n"
            "            source_independence_count=0,\n",
            "            # The two thresholds are Section 15.20-A's literals plus one fitted\n"
            "            # assumption, none calibrated against realized outcomes.\n"
            "            is_heuristic_not_calibrated=not _trilemma_thresholds_calibrated(),\n"
            "            # NOT a call to count_independent_families(). This function consumes\n"
            "            # three manual classifications and up to two reserves observations,\n"
            "            # so there is no list of tagged ModelResults to count — the trilemma\n"
            "            # legs are not a family in the Section 15.19-D sense, because they\n"
            "            # are not measured evidence at all. Claiming a family here would be\n"
            "            # the D-027 circularity error: the function would credit itself with\n"
            "            # evidence its own caller supplied as an assertion.\n"
            "            source_independence_count=0,\n"
            "            data_quality_flags_present=False,  # mutation: the real input dropped\n",
        ),
        (
            "NX19 the published severity key renamed",
            SRC,
            _VALUE_DICT,
            '        value={\n            "state": severity,',
        ),
        (
            "NX20 the published all-three flag dropped",
            SRC,
            '            "all_three_legs_claimed": all_three,\n',
            "",
        ),
        (
            "NX21 the published conflict flag inverted",
            SRC,
            '            "direction_conflict": direction_conflict,',
            '            "direction_conflict": not direction_conflict,',
        ),
        (
            "NX22 the published 3-month depletion flag inverted",
            SRC,
            '            "reserves_depleting_3mo": depleted_3mo,',
            '            "reserves_depleting_3mo": not depleted_3mo,',
        ),
        (
            "NX23 the published 1-month break flag inverted",
            SRC,
            '            "reserves_breaking_1mo": broke_1mo,',
            '            "reserves_breaking_1mo": not broke_1mo,',
        ),
        (
            "NX24 the published base rates always empty",
            SRC,
            '            "base_rates": base_rates,',
            '            "base_rates": None,',
        ),
        (
            "NX25 the published 3-month threshold hardcoded",
            SRC,
            '            "depletion_threshold_3mo": settings.depletion_3mo,',
            '            "depletion_threshold_3mo": -0.10,',
        ),
        (
            "NX26 the published 1-month threshold hardcoded",
            SRC,
            '            "break_threshold_1mo": settings.break_1mo,',
            '            "break_threshold_1mo": -0.07,',
        ),
        (
            "NX27 `inputs_used` lists every input whether supplied or not",
            SRC,
            _INPUTS_USED_TAIL,
            '        "claims_monetary_independence",\n'
            '        "domestic_policy_direction_needed",\n'
            '        "peg_defense_direction_required",\n'
            "        *reserves_horizons,\n"
            "    ]",
        ),
    ]


def _mutation_table() -> list[tuple[str, Path, str, str]]:
    """The full table: generated matrix mutations first, then the aimed ones.

    Order matters only for readability — the runner applies one at a time from a
    clean copy — but the *count* matters: the generated mutations are the ones
    that cannot miss, and they are listed first so a future reader can see how
    much of the sweep is guaranteed to be measuring something.
    """
    return [
        *_matrix_mutations(),
        *_leg_mutations(),
        *_direction_mutations(),
        *_absurdity_mutations(),
        *_model_contract_mutations(),
        *_config_mutations(),
    ]


#: The table the runner iterates. Built at import time so a generated mutation
#: whose `old` text is absent from the source is visible in the MISS list rather
#: than silently dropped.
_MUTATIONS: list[tuple[str, Path, str, str]] = _mutation_table()

#: Mutations that cannot be killed because they cannot change behaviour. Named
#: explicitly so a silent survivor is not confused with a known-inert one.
#:
#: Each entry must carry its proof. "We could not write a failing test" is NOT
#: the same claim as "the two programs are equivalent", and only the second
#: justifies being on this list.
_EXPECTED_INERT: frozenset[str] = frozenset(
    {
        # PROOF (tested in `test_the_or_zero_form_is_behaviourally_disagreeable...`):
        # for a threshold `t <= 0`, `(x or 0.0) < t` and `x is not None and x < t`
        # agree for every x. Both trilemma thresholds are reserves-DEPLETION
        # thresholds and are therefore negative, and `test_the_thresholds_cannot_cross_zero`
        # keeps them so. The rewrite only diverges when `t > 0`.
        #
        # This is a LATENT defect, not a harmless rewrite: the equivalence is
        # contingent on the sign of a config value. The mutation stays in the
        # table precisely so that the contingency is recorded — if a threshold
        # ever crosses zero, this entry becomes wrong and the sweep will start
        # reporting a survivor that must then be killed.
        "MX4a the specification's `or 0` restored on the 3-month test",
        "MX4c the specification's `or 0` restored on the 1-month test",
    }
)


def check_targets(originals: dict[Path, str]) -> list[str]:
    """Refuse to run if any mutation's target text is missing or AMBIGUOUS.

    Two failure modes this catches, both of which produce a confident-looking
    result that means nothing:

    1. **Absent** — the source moved and the `old` string no longer appears. The
       mutation is reported as a pattern-MISS, which the runner already handles.

    2. **Ambiguous** — the `old` string appears MORE THAN ONCE in the file, so
       ``str.replace(old, new, 1)`` rewrites whichever occurrence comes first.
       This is the D-031 mis-targeted class in its purest form and it is far
       more dangerous than a miss, because the file *does* change: the mutation
       looks applied, the tests then pass (they were never exercising the
       mutated code path), and the survivor list says the suite is weak when in
       fact the mutation was pointed at the wrong function.

       Six mutations here hit exactly this — `country="us",`,
       `source_independence_count=0,`, `depends_on_unobservable=True,` and the
       `measured` property body all occur in both `output_gap_from_snapshot` /
       `RegimeBaseRates` and their trilemma equivalents. Every one of them was
       silently mutating the wrong symbol and being reported as a weak test.

    Both checks are fatal: the sweep exits rather than reporting a number it
    cannot stand behind.
    """
    problems: list[str] = []
    for name, target, old, new in _MUTATIONS:
        text = originals[target]
        count = text.count(old)
        if count == 0:
            problems.append(f"ABSENT: {name}  [{target}]")
        elif count > 1:
            problems.append(f"AMBIGUOUS (x{count}): {name}  [{target}]")
        if old == new:
            problems.append(f"INERT BY CONSTRUCTION (old == new): {name}")
    return problems


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_trilemma.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _applied_mutations(originals: dict[Path, str]) -> list[tuple[str, Path, str, str]]:
    """Find mutations currently in the tree: ``old`` absent AND ``new`` present."""
    found: list[tuple[str, Path, str, str]] = []
    for name, target, old, new in _MUTATIONS:
        text = originals[target]
        if old not in text and new in text:
            found.append((name, target, old, new))
    return found


def repair_leftover_mutations(originals: dict[Path, str]) -> list[str]:
    """Invert any mutation left applied by an interrupted run."""
    repaired: list[str] = []
    for name, target, old, new in _applied_mutations(originals):
        originals[target] = originals[target].replace(new, old, 1)
        target.write_text(originals[target], encoding="utf-8", newline="")
        repaired.append(name)
    return repaired


def main() -> int:
    originals: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in {SRC, CONFIG}}

    # Refuse to measure with a broken table. A mis-targeted mutation is worse
    # than a missing one: it changes the file, so it looks applied, and the
    # surviving-test conclusion is then drawn about code nobody mutated.
    problems = check_targets(originals)
    if problems:
        print("REFUSING TO RUN — the mutation table does not point at unique, present text:")
        for problem in problems:
            print(f"  {problem}")
        print()
        print("Fix the table (anchor ambiguous targets on surrounding unique context)")
        print("and re-run. Any number this script would report is meaningless.")
        return 3

    repaired = repair_leftover_mutations(originals)
    if repaired:
        print("REPAIRED left over from an interrupted run:")
        for name in repaired:
            print(f"  reverted -> {name}")
        print()

    survived: list[tuple[str, str]] = []
    try:
        for name, target, old, new in _MUTATIONS:
            pristine = originals[target]
            if old not in pristine:
                print(f"PATTERN MISSING   {name}  [{target.name}]")
                survived.append((name, "pattern-not-found"))
                continue
            target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
            caught = not run_tests()
            target.write_text(pristine, encoding="utf-8", newline="")
            print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
            if not caught:
                survived.append((name, "survived"))
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    leftover = _applied_mutations({p: p.read_text(encoding="utf-8") for p in {SRC, CONFIG}})
    if leftover:
        print()
        print("ERROR: a mutation is still applied after the sweep:")
        for name, _, _, _ in leftover:
            print(f"  STILL APPLIED -> {name}")
        return 2

    print()
    unexpected = [(n, w) for n, w in survived if n not in _EXPECTED_INERT]
    total = len(_MUTATIONS)
    print(f"{total - len(survived)}/{total} killed")
    if _EXPECTED_INERT:
        print(f"({len(_EXPECTED_INERT)} expected-inert by design)")
    for name, why in unexpected:
        print(f"  SURVIVOR ({why}): {name}")
    return 0 if not unexpected else 1


if __name__ == "__main__":
    raise SystemExit(main())
