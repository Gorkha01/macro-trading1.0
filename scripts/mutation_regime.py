"""Mutation sweep for Module 3's ``classify_regime_rule_based``.

Each mutation reverts one D-045 correction to a plausible alternative, and each
must be killed:

* **M1** restores Section 6.2's own branch chain. ``M1a`` is the sweep's most
  important mutation: if the reachability test does not catch the specification's
  logic, the correction is decoration. ``M1b`` narrows only the ``recession``
  guard (the deep-contraction-with-rising-inflation defect), and ``M1c``
  collapses the grid back to the specification's single-level structure so the
  three unreachable states return.
* **M2** breaks the bands — hardcoding one, making an edge exclusive, or
  dropping the neutral band so a flat reading is classified by fallthrough.
* **M3** breaks the hysteresis — the growth-momentum band and the sign split
  inside it, which is what makes a revision of a few basis points unable to flip
  the label.
* **M4** breaks the corroboration logic — the sign pairing that a naive
  implementation gets backwards, and the zero-is-not-evidence rule.
* **M5** drops a disclosure.
* **M6** drops a published component, so the state stops being recomputable.
* **M7** weakens the input contract.
* **M8** restores the specification's hardcoded ``confidence=0.5`` or forces the
  heuristic factor off.
* **C1** swaps or hardcodes the config accessors.

A survivor is one of three things (D-031): a weak test, an **inert** mutation, or
a **broken** mutation. The runner reports a pattern-miss separately from a
survival, and it **heals before it measures** — an interrupted run leaves the
mutated file on disk, and a naive re-run would adopt it as the baseline (D-035
rule 19).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path("src/macro_engine/models/regime.py")
CONFIG = Path("src/macro_engine/config.py")

# --- M1: the branch logic --------------------------------------------------
# The three band tests, as shipped.
_GROWTH_AND_STATE = (
    '    if growth == "deep_contraction":\n'
    '        return "recession"\n'
    '    if growth == "contraction":\n'
    '        if inflation == "rising":\n'
    '            return "stagflation"\n'
    "        # Falling or flat momentum below trend. Split slowdown from recovery on\n"
    "        # the DIRECTION of the gap, which is the only thing that distinguishes\n"
    "        # them: recovery needs the gap to be closing.\n"
    '        if inflation == "falling" and gap_change is not None and gap_change > 0.0:\n'
    '            return "recovery"\n'
    '        return "slowdown"'
)

_RECESSION_GUARD = '    if growth == "deep_contraction":\n        return "recession"'

# The `_growth_axis` function body, as shipped.
_GROWTH_AXIS = (
    "    if gap < settings_recession:\n"
    '        return "deep_contraction"\n'
    "    if gap < settings_weak:\n"
    '        return "contraction"\n'
    '    return "above_trend"'
)

# The `_inflation_axis` function body, as shipped.
_INFLATION_AXIS = (
    "    if trend > neutral_band:\n"
    '        return "rising"\n'
    "    if trend < -neutral_band:\n"
    '        return "falling"\n'
    '    return "flat"'
)

# The at-trend / near-trend block, as shipped.
_AT_TREND_BLOCK = (
    "    if abs(gap) <= momentum_band:\n"
    "        # AT TREND: the gap is inside the hysteresis band. Which state this is\n"
    "        # depends on WHERE in the band, and the sign is the only thing that\n"
    "        # separates an economy still climbing into trend from one that has\n"
    "        # settled onto it — Section 6.2's own distinction between\n"
    "        # `early_expansion` and `mid_expansion`, kept, but read against the\n"
    "        # band rather than against a bare zero so it survives a revision.\n"
    '        if inflation == "rising":\n'
    "            # At trend with inflation turning up: reflation, not expansion.\n"
    '            return "reflation"\n'
    "        if gap < 0.0:\n"
    "            # Below potential but inside the band, inflation not rising:\n"
    "            # activity is climbing back toward trend. This is the state the\n"
    "            # specification declared and could not reach.\n"
    '            return "early_expansion"\n'
    '        return "mid_expansion"'
)

# --- M4: the corroboration logic -------------------------------------------
_CORROBORATION = (
    "        if self.output_gap == 0.0 or self.unemployment_gap == 0.0:\n"
    "            return False\n"
    "        return (self.output_gap < 0.0) == (self.unemployment_gap > 0.0)"
)
_ZERO_GUARD = (
    "        if self.output_gap == 0.0 or self.unemployment_gap == 0.0:\n            return False\n"
)

# --- M5/M6: disclosures and published components ---------------------------
_BASE_RATE_ABSENT_WARNING = (
    '"NO BASE RATE AVAILABLE: the published state frequencies have not been "'
)
_MOMENTUM_DISCLOSURE = (
    '"The inflation axis is MOMENTUM (3-month annualized change), not the level: "'
)
_FLAT_WARNING = 'f"Inflation momentum is FLAT ({inputs.inflation_trend_3m:+.2f}pp, inside the "'
_AT_TREND_WARNING = 'f"The output gap is AT TREND ({inputs.output_gap:+.2f}%, inside the "'
_RECESSION_WARNING = '"RECESSION is a severe label returned by a threshold comparison on a "'
_RECOVERY_UNDECIDABLE = (
    '"SLOWDOWN, NOT RECOVERY — the distinction was not decidable. This reading "'
)
_DISAGREE_WARNING = 'f"SLACK MEASURES DISAGREE: the output gap ({inputs.output_gap:+.2f}%) "'

_STATE_KEY = '            "state": state,'
_AXIS_KEYS = '            "growth_axis": growth,\n            "inflation_axis": inflation,'
_CORROB_KEY = '            "slack_corroborated": inputs.slack_corroborated,'
_BASE_RATE_KEY = '            "state_base_rate": state_base_rate,'
_AXIS_BASE_RATE_KEY = '            "rising_inflation_base_rate": axis_base_rate,'
_AXIS_BASE_RATE_WARNING = (
    "        warnings.append(\n"
    '            f"INFLATION-AXIS BASE RATE: over the same '
    '{base_rates.observations_measured} "'
)

# --- M7: the contract ------------------------------------------------------
_EXTRA_FORBID = '    model_config = ConfigDict(extra="forbid")\n\n    output_gap: float = Field('
_INPUTS_USED = (
    "        inputs_used=[\n"
    '            "output_gap",\n'
    '            "inflation_yoy",\n'
    '            "inflation_trend_3m",\n'
    '            "unemployment_gap",\n'
    "        ],"
)

# --- M8: confidence --------------------------------------------------------
_HEURISTIC = "            is_heuristic_not_calibrated=not _thresholds_calibrated(),"
# Each of these two lines occurs in BOTH `classify_regime_rule_based` and
# `check_trilemma_tension`, so the bare statement is AMBIGUOUS (D-048).
# `str.replace(..., 1)` happens to take the first, which IS the intended
# function — so these worked by luck, and this sweep had no `check_targets`
# to notice the day that luck ran out. D-064's `tools/sweep_health.py`
# found them by running its own target check on the ungated sweeps; each
# anchor is now extended through the regime-specific comment above it.
_INDEPENDENCE = (
    "            # Two surveys of ONE concept (slack), not two independent concepts.\n"
    "            source_independence_count=0,"
)
_UNOBSERVABLE = (
    "            # unemployment_gap against unobservable u*.\n"
    "            depends_on_unobservable=True,"
)

# --- config accessors ------------------------------------------------------
_RECESSION_PROP = "        return float(self.recession_output_gap_max.value)"
_WEAK_PROP = "        return float(self.weak_growth_output_gap_max.value)"
_NEUTRAL_BAND_PROP = "        return float(self.neutral_inflation_trend_band_pp.value)"
_MOMENTUM_BAND_PROP = "        return float(self.growth_momentum_band_pp.value)"
# Targets RegimeBaseRates.rate_map specifically. A bare token like
# `return self.base_rates` would match OTHER models' properties first, and the
# mutation would survive for the wrong reason — the D-031 scoping rule.
_REGIME_RATE_ENTRY = '            "slowdown": float(self.rates.slowdown_value.value),'
# The axis-base-rate property. A hardcoded return here would make the published
# disclosure and the warning constant, so the fixture's 0.775 would not follow.
_AXIS_BASE_RATE_PROP = "        return float(self.measured_rising_inflation_rate.value)"

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # --- M1: the branch logic --------------------------------------------
    (
        "M1a Section 6.2's single-level chain restored (three states die)",
        SRC,
        _GROWTH_AND_STATE,
        '    if growth == "deep_contraction" and inflation == "falling":\n'
        '        return "recession"\n'
        '    if growth == "contraction" and inflation == "rising":\n'
        '        return "stagflation"\n'
        '    if growth == "deep_contraction":\n'
        '        return "late_expansion"\n'
        '    if growth == "above_trend" and inflation == "falling":\n'
        '        return "disinflation"\n'
        '    if growth == "above_trend" and inflation != "rising":\n'
        '        return "mid_expansion"\n'
        '    return "early_expansion"',
    ),
    (
        "M1b the recession guard requires falling inflation (the spec's own narrow guard)",
        SRC,
        _RECESSION_GUARD,
        '    if growth == "deep_contraction" and inflation == "falling":\n'
        '        return "recession"',
    ),
    (
        "M1c recession demoted to require contraction depth twice (stagflation wins deep)",
        SRC,
        _RECESSION_GUARD,
        '    if growth == "deep_contraction" and inflation == "rising":\n'
        '        return "reflation"\n'
        '    if growth == "deep_contraction":\n'
        '        return "recession"',
    ),
    (
        "M1d the recovery split removed (recovery becomes unreachable again)",
        SRC,
        _GROWTH_AND_STATE,
        '    if growth == "deep_contraction":\n'
        '        return "recession"\n'
        '    if growth == "contraction":\n'
        '        if inflation == "rising":\n'
        '            return "stagflation"\n'
        '        return "slowdown"',
    ),
    # --- M2: the bands ---------------------------------------------------
    (
        "M2a the inflation axis band hardcoded to zero (the spec's bare comparison)",
        SRC,
        _INFLATION_AXIS,
        "    if trend > 0.0:\n"
        '        return "rising"\n'
        "    if trend < 0.0:\n"
        '        return "falling"\n'
        '    return "flat"',
    ),
    (
        "M2b the inflation band's edges made exclusive (a boundary flips bucket)",
        SRC,
        _INFLATION_AXIS,
        "    if trend >= neutral_band:\n"
        '        return "rising"\n'
        "    if trend <= -neutral_band:\n"
        '        return "falling"\n'
        '    return "flat"',
    ),
    (
        "M2c the growth bands made inclusive (the boundary value becomes a recession)",
        SRC,
        _GROWTH_AXIS,
        "    if gap <= settings_recession:\n"
        '        return "deep_contraction"\n'
        "    if gap <= settings_weak:\n"
        '        return "contraction"\n'
        '    return "above_trend"',
    ),
    (
        "M2d the growth bands collapsed to one (contraction merges into deep)",
        SRC,
        _GROWTH_AXIS,
        "    if gap < settings_recession:\n"
        '        return "deep_contraction"\n'
        '    return "above_trend"',
    ),
    # --- M3: the hysteresis ----------------------------------------------
    (
        "M3a the momentum band hardcoded to a wide value (at-trend never fires)",
        SRC,
        _AT_TREND_BLOCK,
        "    if abs(gap) <= 1e9:\n"
        '        if inflation == "rising":\n'
        '            return "reflation"\n'
        '        return "mid_expansion"',
    ),
    (
        "M3b the sign split inside the band made inclusive of zero on the wrong side",
        SRC,
        _AT_TREND_BLOCK,
        "    if abs(gap) <= momentum_band:\n"
        '        if inflation == "rising":\n'
        '            return "reflation"\n'
        "        if gap <= 0.0:\n"
        '            return "early_expansion"\n'
        '        return "mid_expansion"',
    ),
    (
        "M3c early_expansion folded into mid_expansion (the catch-all returns)",
        SRC,
        _AT_TREND_BLOCK,
        "    if abs(gap) <= momentum_band:\n"
        '        if inflation == "rising":\n'
        '            return "reflation"\n'
        '        return "mid_expansion"',
    ),
    # --- M4: the corroboration logic --------------------------------------
    (
        "M4a the two slack measures paired with the SAME sign (the D-031 trap)",
        SRC,
        _CORROBORATION,
        "        if self.output_gap == 0.0 or self.unemployment_gap == 0.0:\n"
        "            return False\n"
        "        return (self.output_gap < 0.0) == (self.unemployment_gap < 0.0)",
    ),
    (
        "M4b a zero gap counted as corroboration (product-of-signs behaviour)",
        SRC,
        _ZERO_GUARD,
        "        if False:\n            return False\n",
    ),
    (
        "M4c the corroboration flag hardcoded True",
        SRC,
        _CORROBORATION,
        "        return True",
    ),
    # --- M5: the disclosures ---------------------------------------------
    (
        "M5a the absent-base-rate disclosure dropped",
        SRC,
        _BASE_RATE_ABSENT_WARNING,
        '"Base rate pending."',
    ),
    (
        "M5b the momentum-not-level disclosure dropped",
        SRC,
        _MOMENTUM_DISCLOSURE,
        '"See documentation."',
    ),
    (
        "M5c the flat-momentum disclosure dropped",
        SRC,
        _FLAT_WARNING,
        'f"Momentum reading noted ({inputs.inflation_trend_3m:+.2f}pp)."',
    ),
    (
        "M5d the at-trend disclosure dropped",
        SRC,
        _AT_TREND_WARNING,
        'f"Gap noted ({inputs.output_gap:+.2f}%)."',
    ),
    (
        "M5e the recession caveat dropped",
        SRC,
        _RECESSION_WARNING,
        '"Recession label applied."',
    ),
    (
        "M5f the undecidable-recovery disclosure dropped",
        SRC,
        _RECOVERY_UNDECIDABLE,
        '"Slowdown label applied."',
    ),
    (
        "M5g the slack-disagreement disclosure dropped",
        SRC,
        _DISAGREE_WARNING,
        'f"Slack readings: {inputs.output_gap:+.2f} and {inputs.unemployment_gap:+.2f}."',
    ),
    # --- M6: the published components -------------------------------------
    (
        "M6a the state dropped from the published value",
        SRC,
        _STATE_KEY,
        '            "state": "unknown",',
    ),
    (
        "M6b the two axes dropped (the label stops being auditable)",
        SRC,
        _AXIS_KEYS,
        '            "growth_axis": "unknown",\n            "inflation_axis": "unknown",',
    ),
    (
        "M6c the corroboration flag hardcoded in the published value",
        SRC,
        _CORROB_KEY,
        '            "slack_corroborated": True,',
    ),
    (
        "M6d the state's own base rate dropped",
        SRC,
        _BASE_RATE_KEY,
        '            "state_base_rate": 0.0,',
    ),
    (
        "M6e the inflation-axis base rate dropped from the published value",
        SRC,
        _AXIS_BASE_RATE_KEY,
        '            "rising_inflation_base_rate": None,',
    ),
    (
        "M6f the axis-base-rate warning dropped (the axis artefact goes undisclosed)",
        SRC,
        _AXIS_BASE_RATE_WARNING,
        "        pass",
    ),
    # --- M7: the contract -------------------------------------------------
    (
        "M7a extra='forbid' removed from the input model",
        SRC,
        _EXTRA_FORBID,
        "    output_gap: float = Field(",
    ),
    (
        "M7b unemployment_gap dropped from inputs_used (the inert-input class)",
        SRC,
        _INPUTS_USED,
        "        inputs_used=[\n"
        '            "output_gap",\n'
        '            "inflation_yoy",\n'
        '            "inflation_trend_3m",\n'
        "        ],",
    ),
    # --- M8: confidence ---------------------------------------------------
    (
        "M8a the heuristic factor hardcoded False",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M8b the two slack measures claimed as independent sources",
        SRC,
        _INDEPENDENCE,
        "            source_independence_count=1,",
    ),
    (
        "M8c the unobservable dependence dropped",
        SRC,
        _UNOBSERVABLE,
        "            depends_on_unobservable=False,",
    ),
    (
        "M8d confidence hardcoded to the specification's 0.5",
        SRC,
        # Same AMBIGUITY as the two above: `confidence=confidence,` is also in
        # `check_trilemma_tension`. Anchored through the regime-specific key.
        (
            '            "rising_inflation_base_rate": axis_base_rate,\n'
            "        },\n"
            "        confidence=confidence,"
        ),
        (
            '            "rising_inflation_base_rate": axis_base_rate,\n'
            "        },\n"
            "        confidence=0.5,"
        ),
    ),
    # --- config accessors -------------------------------------------------
    (
        "C1a the recession threshold hardcoded in its property",
        CONFIG,
        _RECESSION_PROP,
        "        return -1.5",
    ),
    (
        "C1b the weak-growth threshold hardcoded in its property",
        CONFIG,
        _WEAK_PROP,
        "        return -0.5",
    ),
    (
        "C1c the neutral band hardcoded in its property",
        CONFIG,
        _NEUTRAL_BAND_PROP,
        "        return 0.0",
    ),
    (
        "C1d the momentum band hardcoded in its property",
        CONFIG,
        _MOMENTUM_BAND_PROP,
        "        return 0.0",
    ),
    (
        "C1e the regime rate mapping entry hardcoded instead of read from config",
        CONFIG,
        _REGIME_RATE_ENTRY,
        '            "slowdown": 0.5,',
    ),
    (
        "C1f the axis base rate hardcoded in its property",
        CONFIG,
        _AXIS_BASE_RATE_PROP,
        "        return 0.9375",
    ),
    # --- M7: the growth-axis vocabulary ----------------------------------
    # The axis is a published contract. A member nothing can produce is the
    # D-037 dead-branch class at the type level, so the removal of `at_trend`
    # needs a mutation that re-adds it: a test asserting membership must be
    # able to fail.
    (
        "M7a the growth axis re-declares an unreachable `at_trend` member",
        SRC,
        'GrowthAxis = Literal["deep_contraction", "contraction", "above_trend"]',
        'GrowthAxis = Literal["deep_contraction", "contraction", "at_trend", "above_trend"]',
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_regime.py",
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

    repaired = repair_leftover_mutations(originals)
    if repaired:
        print("REPAIRED left over from an interrupted run:")
        for name in repaired:
            print(f"  reverted -> {name}")
        print()

    survivors: list[tuple[str, str]] = []
    try:
        for name, target, old, new in _MUTATIONS:
            pristine = originals[target]
            if old not in pristine:
                print(f"PATTERN MISSING   {name}  [{target.name}]")
                survivors.append((name, "pattern-not-found"))
                continue
            target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
            caught = not run_tests()
            target.write_text(pristine, encoding="utf-8", newline="")
            print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
            if not caught:
                survivors.append((name, "survived"))
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
    total = len(_MUTATIONS)
    print(f"{total - len(survivors)}/{total} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
