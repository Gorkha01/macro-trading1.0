"""Mutation sweep for Module 18's ``run_regression``.

The suite exists to prove that each guard is **load-bearing** rather than
decorative. Section 15.18 makes three claims about this function, and every
mutation below is aimed at one of them:

* **Mechanism first.** ``require_mechanism`` is a required argument, so M1
  removes the substance check that gives it teeth. If the suite does not catch
  M1, the gate is a keyword argument and nothing more.
* **Confidence is computed, never asserted.** M2 removes the heuristic penalty
  from ``compute_confidence``'s inputs (Section 22.8's prohibition). If the
  suite does not catch M2, the derivation is decoration and a literal would
  pass just as well.
* **Report, never repair.** M6-M10 and M16-M17 remove the refusals. Each one
  turns a hard stop into a silent wrong answer — the failure mode Section 3
  exists to prevent.

The remaining mutations target the two warning paths and the two structural
claims that are easy to get subtly wrong: M3 gives the intercept a variance
inflation factor (which makes the textbook cutoff of 10 meaningless), M11 flips
the collinearity comparison so it fires on *independent* regressors, M12 returns
an empty dict where the contract says ``None``, M13 reports
``adj_r_squared = r_squared``, M14 drops the standing stationarity caveat, M15
removes the causal-reading prohibition, and M18 makes ``value`` disagree with
``beta``.

A survivor is one of three things (D-031): a weak test, an **inert** mutation
(the edit cannot change any asserted token), or a **broken** mutation (the
fragment no longer matches the source, usually because ``ruff format`` moved a
trailing comma). The runner reports a pattern miss separately from a survival so
those cannot be confused.

**CANARY1 is required to be KILLED** (O-72). If it survives, the test selection
no longer reaches the mutated module and every "killed" above is a statement
about the harness rather than about the suite — the D-051 trap. The runner
refuses to certify in that case.

Every pattern is matched against the pristine source read from the repo.
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

SRC = Path("src/macro_engine/models/econometrics.py")

PYTEST_TARGETS = [
    "tests/models/test_econometrics.py",
]

# ---------------------------------------------------------------------------
# Named fragments, so the mutation literals stay readable and under the line
# limit. Each must match the source byte-for-byte, including indentation and
# trailing commas — ruff format will reflow a fragment that only approximately
# matches, and the sweep would then silently not apply it.
# ---------------------------------------------------------------------------

_CONFIDENCE_PENALTY = "                is_heuristic_not_calibrated=not _thresholds_calibrated(),"

_INTERCEPT_EXCLUSION = "        if str(name) == _INTERCEPT_NAME:\n            continue"

_VIF_GENEXPR = (
    "            ((name, value) for name, value in vif.items() if value > vif_concern_threshold),"
)

_STATIONARITY_LIMITATION = (
    '        "Stationarity is NOT tested here. Regressing one non-stationary level on "'
)

_CAUSAL_PROHIBITION = (
    "        decision_prohibition=[\n"
    '            "Do not read a fitted coefficient as a causal effect. OLS on "'
)

# ---------------------------------------------------------------------------
# The catalogue. ``(name, old, new)``.
# ---------------------------------------------------------------------------

MUTATIONS: list[tuple[str, str, str]] = [
    # ---------------------------------------------------------------- canary
    (
        "CANARY1 model_name renamed",
        '        model_name="run_regression",',
        '        model_name="regression",  # MUTANT CANARY1',
    ),
    # ------------------------------------------------- the mechanism gate
    (
        "M1 mechanism length gate made decorative",
        "    if len(stripped) < minimum:",
        "    if False:  # MUTANT M1 -- the gate becomes decorative",
    ),
    # ------------------------------------------------------- confidence
    (
        "M2 heuristic penalty dropped from compute_confidence",
        _CONFIDENCE_PENALTY,
        "                is_heuristic_not_calibrated=False,  # MUTANT M2",
    ),
    # ------------------------------------------------------------ the VIFs
    (
        "M3 intercept given a variance inflation factor",
        _INTERCEPT_EXCLUSION,
        "        if False:  # MUTANT M3 -- the intercept gets a VIF too\n            continue",
    ),
    (
        "M11 collinearity comparison inverted (fires on independent regressors)",
        _VIF_GENEXPR,
        "            ((name, value) for name, value in vif.items() if value < vif_concern_threshold),  # MUTANT M11",
    ),
    (
        "M12 empty dict reported where the contract says None",
        "    vif = _variance_inflation_factors(design) if x_frame.shape[1] > 1 else None",
        "    vif = _variance_inflation_factors(design) if x_frame.shape[1] > 1 else {}  # MUTANT M12",
    ),
    # ----------------------------------------------------------- warnings
    (
        "M4 perfect-fit warning dropped",
        "    if math.isclose(r_squared, 1.0, rel_tol=0.0, abs_tol=1e-12):",
        "    if False:  # MUTANT M4",
    ),
    (
        "M5 weak-mechanism warning dropped",
        "    if r_squared < low_r_squared_threshold:",
        "    if False:  # MUTANT M5",
    ),
    # ---------------------------------------------------------- refusals
    (
        "M6 rank check removed (perfect collinearity no longer refused)",
        "    if rank < n_params:",
        "    if False:  # MUTANT M6 -- perfect collinearity is no longer refused",
    ),
    (
        "M7 non-finite guard removed from y",
        "    if not bool(np.isfinite(y_f.to_numpy()).all()):",
        "    if False:  # MUTANT M7",
    ),
    (
        "M8 constant-regressor guard removed",
        "    if constant_columns:",
        "    if False:  # MUTANT M8",
    ),
    (
        "M9 minimum-observations floor removed",
        "    if len(y_f) < minimum_observations:",
        "    if False:  # MUTANT M9",
    ),
    (
        "M10 residual-dof check removed",
        "    if n_obs <= n_params:",
        "    if False:  # MUTANT M10",
    ),
    (
        "M16 index-equality check removed",
        "    if not y.index.equals(X.index):",
        "    if False:  # MUTANT M16",
    ),
    (
        "M17 numeric guard removed from y",
        "    if is_bool_dtype(y.dtype) or not is_numeric_dtype(y.dtype):",
        "    if False:  # MUTANT M17",
    ),
    # ------------------------------------------- reasoning-object fields
    (
        "M13 adj_r_squared reported as r_squared",
        "        adj_r_squared=adj_r_squared,",
        "        adj_r_squared=r_squared,  # MUTANT M13",
    ),
    (
        "M14 standing stationarity caveat dropped",
        _STATIONARITY_LIMITATION,
        '        "Mutant removed the stationarity caveat. "  # MUTANT M14',
    ),
    (
        "M15 causal-reading prohibition replaced",
        _CAUSAL_PROHIBITION,
        "        decision_prohibition=[  # MUTANT M15\n"
        '            "Coefficients may be read as causal effects. OLS on "',
    ),
    (
        "M18 value no longer carries the coefficient map",
        "        value=beta,",
        "        value=r_squared,  # MUTANT M18",
    ),
]


def run_tests() -> bool:
    """Whether the pinned selection passes with the current tree.

    The test path is a literal rather than a constant because ruff's S603 rule
    treats a variable argument to ``subprocess`` as potentially untrusted input
    and cannot see that a pinned constant is safe.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_econometrics.py",
            "-q",
            "--no-header",
            "-m",
            "not live",
            "-p",
            "no:randomly",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _iter_mutations() -> list[tuple[str, Path, str, str]]:
    """Pair every mutation with its target file.

    Single-target today, but kept as a function so adding a second file (a
    config mutation, say) does not require rewriting the runner.
    """
    return [(name, SRC, old, new) for name, old, new in MUTATIONS]


def main() -> int:
    # The whole interrupt defence in one call (O-103): heal any sidecar a killed
    # previous run left behind, write the pristine text to a sidecar BEFORE the
    # first mutation, and consume it on the way out. On win32 no Python signal
    # handler runs for SIGTERM/SIGINT, so the sidecar -- not a handler -- is the
    # defence that actually has reach here.
    with sweep_lifecycle([SRC]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    # Refuse to measure before anything is mutated (D-048, O-29). An anchor that
    # drifted reports as a survivor, which reads as "the suite has a hole" when
    # the truth is "the sweep aimed at the wrong text". A LEFTOVER mutant is
    # reported as such rather than as a drifted anchor (D-081), because those
    # two need opposite responses.
    table = _iter_mutations()
    problems = check_targets(originals, table)
    print(f"check_targets: {len(table)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

    survivors: list[tuple[str, str]] = []
    try:
        for name, target, old, new in _iter_mutations():
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
        # Belt and braces: an exception mid-mutation must never leave the tree
        # mutated. A SIGTERM on win32 still can -- no handler and no ``finally``
        # gets a turn -- which is the case the sidecar covers, not this.
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    print()
    total = len(MUTATIONS)
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
