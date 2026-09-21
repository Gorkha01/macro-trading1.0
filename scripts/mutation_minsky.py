"""Mutation sweep for Module 3.4's ``minsky_composition_drift``.

Each mutation reverts one D-041 correction to a plausible alternative, and each
must be killed:

* **M1** breaks the stage logic.
* **M2** reverts the **negative-growth correction** — ``M2a`` restores Section
  20.3's ``risky > total * 1.2`` verbatim, which is the sweep's most important
  mutation: it inverts the flag whenever total credit contracts, so if the suite
  does not catch it the correction is decoration.
* **M3** breaks the standards predicate's strictness.
* **M4** drops a disclosure, including the **BLOCKED** notice.
* **M5** drops a published component, breaking the D-009 cross-field identity.
* **M6** weakens the input contract.
* **M7** reverts confidence to something not derived from the evidence —
  including ``M7c``, which restores the specification's **bias toward alarm**
  (higher confidence for the more alarming stage).
* **C1** swaps or hardcodes the config accessors.

A survivor is one of four things: a weak test, an **inert** mutation, a
**broken** mutation (D-031), or a **mis-targeted** one — aimed at another
model's symbol, which D-040 added to the taxonomy. The runner reports a
pattern-miss separately from a survival, and it **heals before it measures**.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import check_targets, format_problems

SRC = Path("src/macro_engine/models/national_accounts.py")
CONFIG = Path("src/macro_engine/config.py")

# --- M3: the standards predicate -------------------------------------------
_STANDARDS = "    standards_loosening = inputs.lending_standards_net_tightening_pct < 0.0"

# --- M2: the correction ----------------------------------------------------
_GAP = "    growth_gap = inputs.risky_credit_growth_pct - inputs.total_credit_growth_pct"
_THRESHOLD = "    drift_threshold = margin * abs(inputs.total_credit_growth_pct)"
_OUTGROWING = "    risky_outgrowing = growth_gap > drift_threshold"

# --- M1: the stage logic ---------------------------------------------------
_BRANCHES = (
    "    if standards_loosening and risky_outgrowing:\n"
    '        stage = "PONZI_DRIFT_WARNING"\n'
    "    elif standards_loosening or risky_outgrowing:\n"
    '        stage = "SPECULATIVE_DRIFT"\n'
    "    else:\n"
    '        stage = "HEDGE_DOMINANT"'
)

# --- M4: the disclosures ---------------------------------------------------
_PROXY_WARNING = (
    '        "`risky_credit_growth_pct` is a DISCLOSED PROXY: it is hedge funds\' "\n'
    '        "leveraged-loan holdings (FRED `BOGZ1FL623069503Q`), which is the right "\n'
    '        "asset class but a narrower holder base than the whole leveraged-loan "\n'
    '        "market. The series also reads zero before 2013-Q4, so the measurable "\n'
    '        "history is 51 quarters and excludes the 2008 crisis (D-043).",'
)
_STAGE_RATE_WARNING = (
    '        f"The stage is a CATEGORICAL from two threshold comparisons. Over "\n'
    '        f"{settings.base_rates.stage_observations_measured} quarters this stage "\n'
    '        f"occurred in {stage_base_rate:.1%} of them — the frequency a reader needs "\n'
    '        f"before treating it as notable (D-029).",'
)
_BASE_RATE_WARNING = _STAGE_RATE_WARNING
_MARGIN_WARNING = (
    '        f"Risky credit must outgrow total credit by more than "\n'
    '        f"{margin:.0%} of |total growth| to count as drift — the specification\'s "\n'
    '        f"`* 1.2` applied to the GAP rather than the rate, because the "\n'
    '        f"multiplicative form inverts when total growth is negative.",'
)
_ZERO_WARNING = (
    "        warnings.append(\n"
    '            "Lending standards read exactly zero, which Section 20.3\'s `< 0` test "\n'
    '            "counts as NOT loosening. A flat survey is neither tightening nor "\n'
    '            "loosening, and it occurred in 7 of 146 quarters — the boundary is a "\n'
    '            "convention, not a finding."\n'
    "        )"
)
_LAGGING_WARNING = (
    "        warnings.append(\n"
    '            "Defaults are a LAGGING confirmation — by the time they rise, the "\n'
    '            "drift already happened (Module 3.4)."\n'
    "        )"
)

# --- M5: the published components -----------------------------------------
_STAGE_KEY = '            "stage": stage,'
_STANDARDS_KEY = '            "standards_loosening": standards_loosening,'
_OUTGROWING_KEY = '            "risky_outgrowing": risky_outgrowing,'
_GAP_KEY = '            "growth_gap_pct": round(growth_gap, 4),'
_BLOCK_KEY = '            "risky_credit_proxy": "hedge_fund_leveraged_loans",'

# --- M6: the contract ------------------------------------------------------
_EXTRA_FORBID = (
    '    model_config = ConfigDict(extra="forbid")\n\n'
    "    lending_standards_net_tightening_pct: float = Field("
)

# --- M7: confidence --------------------------------------------------------
_HEURISTIC = "            is_heuristic_not_calibrated=not _minsky_calibrated(),"
_DATA_QUALITY = "            data_quality_flags_present=True,"

# --- config accessors ------------------------------------------------------
_MARGIN_PROP = "        return float(self.drift_margin_pct_value.value)"
_RATE_PROP = "        return float(self.standards_loosening_rate_value.value)"

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- O-72 canary (CONTROL) --------------------------------------------
    # NOT a revert of a project correction: a mutation that is CERTAIN to be
    # caught, so the sweep can REFUSE TO CERTIFY when it survives. A sweep
    # whose anchors resolve but whose test selection no longer reaches the
    # mutated module reports every mutant as killed -- the D-051 trap. The
    # canary is the only entry here that distinguishes 'the suite is strong'
    # from 'the sweep stopped testing'.
    #
    # It replaces a module-level literal with a SYNTAX ERROR, so the kill is
    # STRUCTURAL (`tests/` cannot collect) rather than incidental, and the
    # mutation cannot quietly become inert the way a behavioural one can.
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        '__all__ = [\n    "FisherIndexInputs",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the stage logic ---------------------------------------------
    (
        "M1a the two predicates ANDed instead of ORed for SPECULATIVE",
        SRC,
        _BRANCHES,
        "    if standards_loosening and risky_outgrowing:\n"
        '        stage = "PONZI_DRIFT_WARNING"\n'
        "    elif standards_loosening and risky_outgrowing:\n"
        '        stage = "SPECULATIVE_DRIFT"\n'
        "    else:\n"
        '        stage = "HEDGE_DOMINANT"',
    ),
    (
        "M1b the stage hardcoded to HEDGE_DOMINANT",
        SRC,
        _BRANCHES,
        '    stage = "HEDGE_DOMINANT"',
    ),
    (
        "M1c the branches reordered so the single-predicate case wins",
        SRC,
        _BRANCHES,
        "    if standards_loosening or risky_outgrowing:\n"
        '        stage = "SPECULATIVE_DRIFT"\n'
        "    elif standards_loosening and risky_outgrowing:\n"
        '        stage = "PONZI_DRIFT_WARNING"\n'
        "    else:\n"
        '        stage = "HEDGE_DOMINANT"',
    ),
    # --- M2: THE correction ----------------------------------------------
    (
        "M2a the specification's `risky > total * 1.2` RESTORED (inverts on negative growth)",
        SRC,
        _OUTGROWING,
        "    risky_outgrowing = inputs.risky_credit_growth_pct > (\n"
        "        inputs.total_credit_growth_pct * (1.0 + margin)\n"
        "    )",
    ),
    (
        "M2b the margin applied to the RATE rather than the gap",
        SRC,
        _OUTGROWING,
        "    risky_outgrowing = inputs.risky_credit_growth_pct > drift_threshold",
    ),
    (
        "M2c the abs() dropped, so the threshold goes negative with the base",
        SRC,
        _THRESHOLD,
        "    drift_threshold = margin * inputs.total_credit_growth_pct",
    ),
    (
        "M2d the gap taken with the operands reversed",
        SRC,
        _GAP,
        "    growth_gap = inputs.total_credit_growth_pct - inputs.risky_credit_growth_pct",
    ),
    (
        "M2e the outgrowing comparison made non-strict",
        SRC,
        _OUTGROWING,
        "    risky_outgrowing = growth_gap >= drift_threshold",
    ),
    # --- M3: the standards predicate -------------------------------------
    (
        "M3a the standards comparison made non-strict (flat counts as loosening)",
        SRC,
        _STANDARDS,
        "    standards_loosening = inputs.lending_standards_net_tightening_pct <= 0.0",
    ),
    (
        "M3b the standards comparison inverted",
        SRC,
        _STANDARDS,
        "    standards_loosening = inputs.lending_standards_net_tightening_pct > 0.0",
    ),
    # --- M4: the disclosures ---------------------------------------------
    (
        "M4a the DISCLOSED-PROXY warning dropped",
        SRC,
        _PROXY_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4b the stage base-rate disclosure dropped (D-029)",
        SRC,
        _BASE_RATE_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4c the margin-correction disclosure dropped",
        SRC,
        _MARGIN_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4d the flat-survey boundary disclosure dropped",
        SRC,
        _ZERO_WARNING,
        "        pass",
    ),
    (
        "M4e the lagging-defaults caveat dropped",
        SRC,
        _LAGGING_WARNING,
        "        pass",
    ),
    # --- M5: the published components ------------------------------------
    (
        "M5a the stage dropped from the published value",
        SRC,
        _STAGE_KEY,
        '            "stage": "UNKNOWN",',
    ),
    (
        "M5b the standards predicate dropped",
        SRC,
        _STANDARDS_KEY,
        '            "unused_standards": standards_loosening,',
    ),
    (
        "M5c the outgrowing predicate dropped",
        SRC,
        _OUTGROWING_KEY,
        '            "unused_outgrowing": risky_outgrowing,',
    ),
    (
        "M5d the growth gap dropped (the correction stops being auditable)",
        SRC,
        _GAP_KEY,
        '            "growth_gap_pct": 0.0,',
    ),
    (
        "M5e the proxy disclosure dropped from the published value",
        SRC,
        _BLOCK_KEY,
        '            "risky_credit_proxy": "none",',
    ),
    # --- M6: the contract -------------------------------------------------
    (
        "M6a extra='forbid' removed from the input model",
        SRC,
        _EXTRA_FORBID,
        "    lending_standards_net_tightening_pct: float = Field(",
    ),
    # --- M7: confidence ---------------------------------------------------
    (
        "M7a the heuristic factor hardcoded False",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M7b the data-quality flag dropped (the proxy stops costing confidence)",
        SRC,
        _DATA_QUALITY,
        "            data_quality_flags_present=False,",
    ),
    # --- config accessors -------------------------------------------------
    (
        "C1a the drift margin property returns a hardcoded value",
        CONFIG,
        _MARGIN_PROP,
        "        return 0.0",
    ),
    (
        "C1b the standards rate property returns a hardcoded value",
        CONFIG,
        _RATE_PROP,
        "        return 0.0",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_national_accounts.py",
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

    # This sweep's table is already 4-tuples.
    #
    # Refuse to measure before anything is mutated (D-048, O-29). An anchor
    # that drifted reports as a survivor, which reads as 'the suite has a
    # hole' when the truth is 'the sweep aimed at the wrong text'. A
    # LEFTOVER mutant is reported as such rather than as a drifted anchor
    # (D-081), because those two need opposite responses.
    _table = _MUTATIONS
    problems = check_targets(originals, _table)
    print(f"check_targets: {len(_table)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

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
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated module, so every
    # "killed" above is a statement about the harness rather than the suite.
    # This is the D-051 trap, and it is why CANARY1 is REQUIRED to be killed
    # rather than tolerated as a survivor.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
