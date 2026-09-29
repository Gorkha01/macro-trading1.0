"""Mutation sweep for ``inflation_breadth_score`` (``labor_synthesis.py``, Module 6.3).

This function had no sweep, and it carried a real defect the unit suite could
not see: an all-zero reading (three flat m/m prints, producible on the live path
via the orchestrator's ``_inflation_leg``) took the divergent branch because the
code tested "not all the same way" rather than "genuinely opposed". The result
was a FLAT month published as ``CONFLICTED`` with the divergent confidence 0.3.
The fix splits the divergent predicate into a real opposition test and adds a
flat state. This sweep exists so the split cannot be silently re-collapsed:

* **M1** restores the original sign-blind predicate — ``divergent`` becomes the
  negation of ``same_direction``, so a flat reading is divergent again (D-040).
* **M2** breaks the flat state — dropping ``all_flat``, or making the
  direction helper fall through to CONFLICTED on a flat read.
* **M3** breaks the confidence link — hardcoding it, or swapping which state
  takes the convergent vs divergent value.
* **M4** drops a disclosure (the flat warning, the sign-test warning).
* **M5** drops a published field so the read stops being recomputable (D-009).
* **C1** hardcodes a config accessor.

A survivor is one of three things (D-031): a weak test, an **inert** mutation, or
a **broken** mutation. The runner reports a pattern-miss separately from a
survival, and it **heals before it measures** (D-035 rule 19 / O-103): on win32
the sidecar, not a signal handler, is the interrupt defence with real reach.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import (
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)

SRC = Path("src/macro_engine/models/labor_synthesis.py")
CONFIG = Path("src/macro_engine/config.py")

# --- M1: the divergent predicate (the defect) ------------------------------
_SIGNS = (
    "    all_positive = all(value > 0 for value in values)\n"
    "    all_negative = all(value < 0 for value in values)\n"
    "    all_flat = all(value == 0 for value in values)\n"
    "    same_direction = all_positive or all_negative"
)
_DIVERGENT = (
    "    divergent = any(value > 0 for value in values) and any(value < 0 for value in values)"
)
_CONFIDENCE = "    confidence = breadth.divergent if divergent else breadth.convergent"

# --- M2: the flat state and the direction helper ---------------------------
_FLAT_SENTENCE = (
    "    if all_flat:\n"
    '        return "flat: all three measures at zero, so there is no direction to read"'
)
_FLAT_BRANCH = "    elif all_flat:"

# --- M4: the disclosures ---------------------------------------------------
_FLAT_WARNING = '            "All three sub-measures are exactly flat (0.00% m/m). This is NOT a "'
_SIGN_TEST_WARNING = '        "Convergence is a SIGN test and therefore weak: three measures at "'

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- O-72 canary (CONTROL) --------------------------------------------
    # A mutation CERTAIN to be caught, so the sweep REFUSES TO CERTIFY when it
    # survives: a canary survivor means the test selection no longer reaches the
    # mutated module, so every "killed" below is a statement about the harness
    # (D-051). It replaces a module literal with a SYNTAX ERROR, so the kill is
    # STRUCTURAL rather than incidental.
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        '__all__ = [\n    "AHEDistortionInputs",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the divergent predicate (the centrepiece) --------------------
    (
        "M1a divergent reverts to the sign-blind negation of same_direction",
        SRC,
        _DIVERGENT,
        "    divergent = not same_direction",
    ),
    (
        "M1b divergent drops the positive half (only a negative triggers it)",
        SRC,
        _DIVERGENT,
        "    divergent = any(value < 0 for value in values)",
    ),
    (
        "M1c divergent drops the negative half (only a positive triggers it)",
        SRC,
        _DIVERGENT,
        "    divergent = any(value > 0 for value in values)",
    ),
    (
        "M1d divergent widened to any non-zero reading (a single sign conflicts with zeros)",
        SRC,
        _DIVERGENT,
        "    divergent = any(value != 0 for value in values)",
    ),
    # --- M2: the flat state -----------------------------------------------
    (
        "M2a the all_flat flag is forced off (flat readings lose their state)",
        SRC,
        "    all_flat = all(value == 0 for value in values)",
        "    all_flat = False",
    ),
    (
        "M2b the flat branch is dropped, so a flat read falls past the divergent test",
        SRC,
        _FLAT_BRANCH,
        "    elif False:",
    ),
    (
        "M2c the flat direction sentence is removed",
        SRC,
        _FLAT_SENTENCE,
        "    if False:\n"
        '        return "flat: all three measures at zero, so there is no direction to read"',
    ),
    (
        "M2d all_flat redefined as all-non-positive (a negative read is 'flat')",
        SRC,
        "    all_flat = all(value == 0 for value in values)",
        "    all_flat = all(value <= 0 for value in values)",
    ),
    (
        "M2e the flat state is folded into the divergent branch (D-040 re-introduced)",
        SRC,
        _DIVERGENT,
        "    divergent = not same_direction\n"
        "    all_flat = all(value == 0 for value in values) and False",
    ),
    # --- M3: the confidence link ------------------------------------------
    (
        "M3a the confidence is hardcoded to the convergent value",
        SRC,
        _CONFIDENCE,
        "    confidence = breadth.convergent",
    ),
    (
        "M3b the confidence is hardcoded to the divergent value",
        SRC,
        _CONFIDENCE,
        "    confidence = breadth.divergent",
    ),
    (
        "M3c the confidence is the spec's literal 0.5",
        SRC,
        _CONFIDENCE,
        "    confidence = 0.5",
    ),
    # --- M4: the disclosures ----------------------------------------------
    (
        "M4a the flat warning is removed",
        SRC,
        _FLAT_WARNING,
        '            "REMOVED-DISCLOSURE-PLACEHOLDER",',
    ),
    (
        "M4b the sign-test disclosure is removed",
        SRC,
        _SIGN_TEST_WARNING,
        '        "REMOVED-DISCLOSURE-PLACEHOLDER",',
    ),
    # --- M5: the published fields -----------------------------------------
    (
        "M5a the direction field is dropped from the result",
        SRC,
        "        direction=_breadth_direction_sentence(all_positive, all_negative, all_flat, divergent),",
        "        direction=None,",
    ),
    (
        "M5b the unit field is dropped from the result",
        SRC,
        '        unit="percent, month-over-month (an AVERAGE across three measures)",',
        '        unit="",',
    ),
    (
        "M5c the value is not rounded (raw float leaks the arithmetic)",
        SRC,
        "        value=round(average, 4),",
        "        value=average * 1000.0,",
    ),
    # --- C1: config accessors ---------------------------------------------
    # NOTE: a mutant that hardcodes the convergent value to ``0.5`` would be
    # INERT by construction (the shipped config value IS 0.5), so it would
    # report as a survivor for a reason that is not a test gap. An inert
    # mutation is not evidence (D-031), so it is not listed; the accessor is
    # instead probed by SWAPPING the two leaves, which is observable.
    (
        "C1a the two breadth confidences are swapped",
        SRC,
        _CONFIDENCE,
        "    confidence = breadth.convergent if divergent else breadth.divergent",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_labor_synthesis.py",
            "tests/models/test_reasoning_contract.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only(_MUTATIONS)


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
    with sweep_lifecycle([SRC]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    pristine_src = originals[SRC]

    _table = [(name, path, old, new) for name, path, old, new in _MUTATIONS]
    problems = check_targets({SRC: pristine_src}, _table)
    print(f"check_targets: {len(_table)} mutations, {len(problems)} problem(s)", flush=True)
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

    survivors: list[tuple[str, str]] = []
    for name, _path, old, new in _MUTATIONS:
        if old not in pristine_src:
            print(f"PATTERN MISSING   {name}", flush=True)
            survivors.append((name, "pattern-not-found"))
            continue
        SRC.write_text(pristine_src.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        SRC.write_text(pristine_src, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}", flush=True)
        if not caught:
            survivors.append((name, "survived"))

    print()
    print(f"{len(_MUTATIONS) - len(survivors)}/{len(_MUTATIONS)} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
