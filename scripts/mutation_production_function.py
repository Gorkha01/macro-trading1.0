"""Mutation sweep for production_function.py.

Each entry replaces a specific substring with a broken version, runs the test
file, and records whether the suite noticed. A surviving mutation is either a
weak test or an inert mutation, and the two are told apart by inspecting whether
the mutated code path is reachable at all.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import check_targets, format_problems

SRC = Path("src/macro_engine/models/production_function.py")
# The pristine copy is the file itself, read once at import. Earlier sweeps in
# this project took a /tmp backup, which Git Bash resolves to a real directory
# but a Windows Python process does not — a path that works in one shell and not
# the other is a trap, so the original is captured from the repo instead.
ORIGINAL = SRC.read_text(encoding="utf-8")

# The two-factor term assignment, split across lines so no mutation string
# exceeds the line limit. Written once and reused, so a change to the source
# formatting updates every mutation that targets it.
_KPL_TERMS = (
    "capital_term = math.pow(inputs.capital_stock, alpha)\n"
    "    labor_term = math.pow(inputs.labor_input, one_minus_alpha)"
)

# The whole zero-total warning block, including its ``warnings.append`` wrapper,
# so deleting it removes the warning rather than just its first sentence. The
# first version of this mutation replaced only the opening string, which left
# the tail of the message intact and the test's substring match still passing —
# an inert mutation that looked like a survivor.
_ZERO_TOTAL_WARNING = (
    "        warnings.append(\n"
    '            "The two growth terms sum to exactly zero, so the productivity "\n'
    '            "SHARE is undefined and reported as None rather than 0.0. The total "\n'
    '            "is known to be zero; the split between its two components is not."\n'
    "        )\n"
)

# The two contribution entries in the value dict, mutated together because a
# test asserting the cross-field identity would catch either alone.
_CONTRIBUTIONS = (
    '"labor_contribution_pp": round(labor_force_growth_pct, 2),\n'
    '            "productivity_contribution_pp": round(productivity_growth_pct, 2),'
)

MUTATIONS: list[tuple[str, str, str]] = [
    (
        "M1 exponent swap: K^a * L^a instead of K^a * L^(1-a)",
        _KPL_TERMS,
        _KPL_TERMS.replace("labor_input, one_minus_alpha", "labor_input, alpha"),
    ),
    (
        "M2 transposed exponents: K^(1-a) * L^a",
        _KPL_TERMS,
        _KPL_TERMS.replace(
            "capital_stock, alpha)\n    labor_term = math.pow(inputs.labor_input, one_minus_alpha",
            "capital_stock, one_minus_alpha)\n    labor_term = math.pow(inputs.labor_input, alpha",
        ),
    ),
    (
        "M3 alpha read from a literal instead of config",
        "alpha = settings.production_function.alpha_value",
        "alpha = 0.5",
    ),
    (
        "M4 A dropped from the product",
        "potential = inputs.total_factor_productivity * capital_term * labor_term",
        "potential = capital_term * labor_term",
    ),
    (
        "M5 unobservable penalty removed",
        "depends_on_unobservable=True,\n                # alpha is conventional",
        "depends_on_unobservable=False,\n                # alpha is conventional",
    ),
    (
        "M6 heuristic penalty removed",
        "is_heuristic_not_calibrated=True,\n                # A, K and L all descend",
        "is_heuristic_not_calibrated=False,\n                # A, K and L all descend",
    ),
    (
        "M7 A-warning removed (order test should fail)",
        '"A (total factor productivity) is the LEAST predictable and MOST "',
        '"Total factor productivity matters somewhat. "',
    ),
    (
        "M8 estimate-not-measurement warning removed",
        '"Potential GDP is a PRODUCTION-FUNCTION ESTIMATE, not observed — Module "',
        '"Potential GDP is a useful figure. "',
    ),
    (
        "M9 CRS disclosure removed from context",
        "Constant returns to scale is ASSUMED",
        "Constant returns to scale holds",
    ),
    (
        "M10 input constraint loosened: capital_stock permits zero",
        "capital_stock: float = Field(\n        gt=0.0,",
        "capital_stock: float = Field(\n        ge=0.0,",
    ),
    (
        "M11 growth: total is productivity - labor instead of +",
        "total = labor_force_growth_pct + productivity_growth_pct",
        "total = productivity_growth_pct - labor_force_growth_pct",
    ),
    (
        "M12 share reports 0.0 instead of None on zero total",
        "round(productivity_growth_pct / total, 3) if total != 0.0 else None",
        "round(productivity_growth_pct / total, 3) if total != 0.0 else 0.0",
    ),
    (
        "M13 dominance comparison made non-strict (>=)",
        "if productivity_share is not None and productivity_share > productivity_dominance:",
        "if productivity_share is not None and productivity_share >= productivity_dominance:",
    ),
    (
        "M14 dominance threshold from a literal instead of config",
        "productivity_dominance = settings.production_function.productivity_dominance",
        "productivity_dominance = 0.95",
    ),
    (
        "M15 labor-negative guard drops its productivity condition",
        "if labor_force_growth_pct < 0.0 and productivity_growth_pct > 0.0:",
        "if labor_force_growth_pct < 0.0:",
    ),
    (
        "M16 both-negative branch removed",
        "elif productivity_growth_pct < 0.0 and labor_force_growth_pct < 0.0:",
        "elif False:",
    ),
    (
        "M17 productivity-negative guard drops its labor condition",
        "elif productivity_growth_pct < 0.0 and labor_force_growth_pct > 0.0:",
        "elif productivity_growth_pct < 0.0:",
    ),
    (
        "M18 zero-total warning removed entirely",
        _ZERO_TOTAL_WARNING,
        "",
    ),
    (
        "M19 contributions not reported in the value dict",
        _CONTRIBUTIONS,
        '"labor_contribution_pp": 0.0,\n            "productivity_contribution_pp": 0.0,',
    ),
    (
        "M20 share rounded to 3 places -> 1 place",
        "round(productivity_growth_pct / total, 3) if total != 0.0 else None",
        "round(productivity_growth_pct / total, 1) if total != 0.0 else None",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_production_function.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def main() -> int:
    # A 3-tuple table against a single SRC; target made explicit.
    #
    # Refuse to measure before anything is mutated (D-048, O-29). An anchor
    # that drifted reports as a survivor, which reads as 'the suite has a
    # hole' when the truth is 'the sweep aimed at the wrong text'. A
    # LEFTOVER mutant is reported as such rather than as a drifted anchor
    # (D-081), because those two need opposite responses.
    _table = [(name, SRC, old, new) for name, old, new in MUTATIONS]
    problems = check_targets({SRC: ORIGINAL}, _table)
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
        if old not in ORIGINAL:
            print(f"PATTERN MISSING   {name}")
            survivors.append((name, "pattern-not-found"))
            continue
        SRC.write_text(ORIGINAL.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        SRC.write_text(ORIGINAL, encoding="utf-8", newline="")
        status = "KILLED" if caught else "SURVIVED"
        print(f"{status:17} {name}")
        if not caught:
            survivors.append((name, "survived"))

    print()
    killed = len(MUTATIONS) - len(survivors)
    print(f"{killed}/{len(MUTATIONS)} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
