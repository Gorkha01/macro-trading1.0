"""Mutation sweep for inflation_nowcast.py (``project_shelter_cpi``).

The tests would pass just as happily under the specification's spelling, so this
sweep exists mainly to prove the **vintage index** guard is load-bearing: M1
reverts to ``[-lag_months]`` exactly as the Section 20 sample writes it, and the
suite must catch that.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import (
    check_targets,
    format_problems,
    sweep_lifecycle,
)

SRC = Path('C:/Users/Hp/Documents/macro/.pytest_g1/test_the_canary_gate_refuses_w0/inflation_nowcast.py')
# Read the pristine copy from the repo rather than a /tmp backup: a /tmp path
# resolves in Git Bash but not in a Windows Python process.

_VINTAGE_INDEX = "vintage_index_from_end = lag_months + 1"

MUTATIONS: list[tuple[str, str, str]] = [
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
        '__all__ = [\n    "ShelterLagInputs",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    (
        "M1 vintage index reverts to the spec's [-lag] (reads one month early)",
        _VINTAGE_INDEX,
        "vintage_index_from_end = lag_months",
    ),
    (
        "M2 vintage index reads the current month",
        _VINTAGE_INDEX,
        "vintage_index_from_end = 1",
    ),
    (
        "M3 lag read from a literal instead of config",
        "lag_months = settings.inflation.shelter_lag",
        "lag_months = 12",
    ),
    (
        "M4 required length is lag, not lag+1",
        "required_points = lag_months + 1",
        "required_points = lag_months",
    ),
    (
        "M5 insufficient-data branch substitutes the oldest point instead of None",
        "            value=None,\n            confidence=compute_confidence(\n"
        "                ConfidenceInputs(data_quality_flags_present=True),\n            ),",
        "            value=round(history[-1], 2) if history else None,\n"
        "            confidence=compute_confidence(\n"
        "                ConfidenceInputs(data_quality_flags_present=True),\n            ),",
    ),
    (
        "M6 insufficient-data confidence hardcoded to the spec's 0.0",
        "ConfidenceInputs(data_quality_flags_present=True),",
        "ConfidenceInputs(data_quality_flags_present=False),",
    ),
    (
        "M7 normal-path confidence hardcoded",
        "confidence=compute_confidence(ConfidenceInputs()),\n        interpretation=(",
        "confidence=0.55,\n        interpretation=(",
    ),
    (
        "M8 converged tolerance read from a literal instead of config",
        "converged_tolerance = settings.inflation.shelter_converged_tolerance",
        "converged_tolerance = 0.0",
    ),
    (
        "M9 converged comparison made exclusive (<= becomes <)",
        "if abs(gap) <= converged_tolerance:",
        "if abs(gap) < 0:",
    ),
    (
        "M10 direction inverted: gap < 0 reported as reaccelerating",
        '    elif gap < 0:\n        direction = "cooling"',
        '    elif gap < 0:\n        direction = "reaccelerating"',
    ),
    (
        "M11 direction inverted: gap > 0 reported as cooling",
        '        direction = "reaccelerating"',
        '        direction = "cooling"',
    ),
    (
        "M12 reversed-case wording dropped (exact match reported as cooling)",
        'if abs(gap) <= converged_tolerance:\n        direction = "converged"',
        'if False:\n        direction = "converged"',
    ),
    (
        "M13 excess-history warning removed",
        "if len(history) > required_points:",
        "if False:",
    ),
    (
        "M14 lag-assumption warning removed",
        '"Mechanical lag projection — assumes historical lease-turnover dynamics "',
        '"A projection. "',
    ),
    (
        "M15 shelter-share warning removed",
        '"Shelter is roughly a third of CPI, so this projection drives a large "',
        '"Shelter matters. "',
    ),
    (
        "M16 vintage warning drops the config-provenance clause",
        'f"supplied history). The lag is a config parameter, not a measured "',
        'f"supplied history). The lag is not a measured "',
    ),
    (
        "M17 converged warning removed",
        '    if direction == "converged":\n        warnings.append(',
        "    if False:\n        warnings.append(",
    ),
    (
        "M18 gap not reported in context",
        'f"{inputs.current_cpi_shelter_yoy_pct:.2f}% = {gap:+.2f}pp. "',
        'f"{inputs.current_cpi_shelter_yoy_pct:.2f}%. "',
    ),
    (
        "M19 input model admits an unknown field (extra=forbid removed)",
        '    model_config = ConfigDict(extra="forbid")\n\n    market_rent_growth_yoy_pct',
        "    market_rent_growth_yoy_pct",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_auctions.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def main() -> int:
    # The whole interrupt defence in one call (O-103): heal, protect, spend.
    # On win32 no Python signal handler runs for SIGTERM/SIGINT, so the
    # sidecar -- not a handler -- is the defence with real reach here.
    with sweep_lifecycle([SRC]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    pristine_src = originals[SRC]

    # A 3-tuple table against a single SRC; target made explicit.
    #
    # Refuse to measure before anything is mutated (D-048, O-29). An anchor
    # that drifted reports as a survivor, which reads as 'the suite has a
    # hole' when the truth is 'the sweep aimed at the wrong text'. A
    # LEFTOVER mutant is reported as such rather than as a drifted anchor
    # (D-081), because those two need opposite responses.
    _table = [(name, SRC, old, new) for name, old, new in MUTATIONS]
    problems = check_targets({SRC: pristine_src}, _table)
    print(f"check_targets: {len(_table)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

    survivors: list[tuple[str, str]] = []
    for name, old, new in MUTATIONS:
        if old not in pristine_src:
            print(f"PATTERN MISSING   {name}")
            survivors.append((name, "pattern-not-found"))
            continue
        SRC.write_text(pristine_src.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        SRC.write_text(pristine_src, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
        if not caught:
            survivors.append((name, "survived"))

    print()
    print(f"{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed")
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
