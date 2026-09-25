"""Mutation sweep for Section 6.7's ``cip_check`` (Module 9, Tier 5).

Every mutation below reverts one decision the implementation makes to a
plausible alternative, and each must be killed. The grouping follows the
function's own structure, because a mutation that does not correspond to a
*decision* is a mutation that cannot teach anything:

* **M1** breaks the PARITY IDENTITY — the whole point of the estimator.
  ``M1a`` swaps the two rates in the ratio, ``M1b`` substitutes the linear
  interest-differential approximation for the exact ratio, ``M1c`` multiplies
  where it should divide. Each returns a confident number that is not a parity
  deviation.
* **M2** breaks the ANNUALISATION — the sophistication the specification's stub
  omits. ``M2a`` drops the tenor scaling entirely (the D-106 class: an
  annualised number read as a period number), ``M2b`` inverts it, ``M2c``
  annualises only one leg, ``M2d`` inverts the basis's annualisation, ``M2e``
  reads the wrong rate into the domestic leg.
* **M3** breaks the SIGN — the derivation the module docstring exists to pin.
  ``M3a`` flips the deviation's numerator, ``M3b`` inverts the synthetic-rate
  ratio, ``M3c`` flips the basis's sign, ``M3d`` publishes a fraction where a
  percentage is promised.
* **M4** breaks the QUOTE CONVENTION — the silent sign inversion. ``M4a``
  disables the inversion, ``M4b`` inverts nothing when it should, ``M4c``
  inverts the condition.
* **M5** breaks the BANDS — the reachability of each label. ``M5a``/``M5b``
  collapse the three-way severity into two, ``M5c``/``M5d`` do the same to the
  funding side, ``M5e``/``M5f`` move each boundary from strict to inclusive.
* **M6** breaks the GUARDS — the finiteness, positivity, tenor and period-rate
  refusals.
* **M7** breaks the WARNINGS — each branch, and the noise floor.
* **M8** breaks the PUBLISHED VALUE or the confidence computation.
* **C1** swaps or hardcodes the config accessors and the settings validators.

A survivor is one of three things (D-031): a weak test, an **inert** mutation, or
a **broken** mutation. The runner heals before it measures — an interrupted run
leaves the mutated file on disk, and a naive re-run would adopt it as the
baseline (D-035 rule 19).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import check_targets, format_problems, sweep_lifecycle

SRC = Path("src/macro_engine/models/fx_carry.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# M1: the parity identity.
# --------------------------------------------------------------------------

_IMPLIED_FORWARD = (
    "    implied_forward = spot * (1.0 + i_domestic_period) / (1.0 + i_foreign_period)"
)

# --------------------------------------------------------------------------
# M2: the annualisation.
# --------------------------------------------------------------------------

_PERIOD_SCALE = "    period_scale = inputs.tenor_days / basis_days"
_I_D_PERIOD = "    i_domestic_period = inputs.i_domestic_annualized * period_scale"
_I_F_PERIOD = "    i_foreign_period = inputs.i_foreign_annualized * period_scale"
_BASIS_BP = "    basis_bp_annualized = basis_period / period_scale * 10_000.0"
_BASIS_DAYS_LINE = '_BASIS_DAYS: dict[str, int] = {"actual_360": 360, "actual_365": 365}'

# --------------------------------------------------------------------------
# M3: the sign.
# --------------------------------------------------------------------------

_DEVIATION_FRACTION = "    deviation_fraction = (forward - implied_forward) / implied_forward"
_DEVIATION_PCT = "    deviation_pct = deviation_fraction * 100.0"
_SYNTHETIC = "    synthetic_domestic_period = (forward / spot) * (1.0 + i_foreign_period) - 1.0"
_BASIS_PERIOD = "    basis_period = synthetic_domestic_period - i_domestic_period"

# --------------------------------------------------------------------------
# M4: the quote convention.
# --------------------------------------------------------------------------

_INVERTED_FLAG = '    inverted = inputs.quote == "foreign_per_domestic"'
_INVERT_BRANCH = (
    "    if inverted:\n        spot = 1.0 / inputs.spot\n        forward = 1.0 / inputs.forward"
)

# --------------------------------------------------------------------------
# M5: the bands.
# --------------------------------------------------------------------------

_SEVERITY_EXTREME = "    if magnitude > extreme_pct:"
_SEVERITY_NOTABLE = "    elif magnitude > notable_pct:"
_SIDE_QUIET = "    if magnitude <= notable_pct:"
_SIDE_SIGN = "    elif deviation_pct > 0.0:"

# --------------------------------------------------------------------------
# M6: the guards.
# --------------------------------------------------------------------------

_FINITE_GUARD = "            if not math.isfinite(value):"
_POSITIVE_GUARD = "            if value <= 0.0:"
_TENOR_GUARD = "        if self.tenor_days > basis_days:"
_PERIOD_RATE_GUARD = "            if 1.0 + period <= 0.0:"

# --------------------------------------------------------------------------
# M7: the warnings.
# --------------------------------------------------------------------------

_WARN_EXTREME = '    if severity == "extreme":'
_WARN_NOTABLE = '    elif severity == "notable":'

# --------------------------------------------------------------------------
# M8: the published value and the confidence.
# --------------------------------------------------------------------------

_DEVIATION_KEY = '            "deviation_pct": round(deviation_pct, 6),'
_I_D_PERIOD_KEY = '            "i_domestic_period": round(i_domestic_period, 8),'
_BASIS_KEY = '            "domestic_funding_basis_bp_annualized": round(basis_bp_annualized, 4),'
_SEVERITY_KEY = '            "severity": severity,'
_SIDE_KEY = '            "stressed_currency": side,'
_NORMALIZED_KEY = '            "normalized_to": "domestic_per_foreign",'
_INVERTED_KEY = '            "quote_was_inverted": inverted,'
_HEURISTIC_FLAG = "                is_heuristic_not_calibrated=not _thresholds_are_calibrated(),"

# --------------------------------------------------------------------------
# C1: the config accessors and validators.
# --------------------------------------------------------------------------

_NOTABLE_READ = "    notable_pct = fx_carry.notable_threshold_pct"
_EXTREME_READ = "    extreme_pct = fx_carry.extreme_threshold_pct"
_CALIBRATED_READ = '    return settings.is_calibrated("fx_carry.notable_deviation_pct")'
_NOTABLE_PROP = "        return float(self.notable_deviation_pct.value)"
_EXTREME_PROP = "        return float(self.extreme_deviation_pct.value)"
_ORDER_VALIDATOR = "        if extreme <= notable:"
_POSITIVE_VALIDATOR = "        if notable <= 0.0:"


_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- canary (CONTROL) -------------------------------------------------
    # NOT a revert of a project decision: a mutation CERTAIN to be caught, so
    # the sweep can REFUSE TO CERTIFY when it survives. A sweep whose anchors
    # resolve but whose selection no longer reaches the mutated module reports
    # every mutant as killed (D-051). The anchor is the module's FIRST
    # STATEMENT — the future import — so it does not churn the way `__all__`
    # does (O-119/O-126: an `__all__` canary was broken by an export edit and
    # reported as a LEFTOVER).
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        "from __future__ import annotations",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the parity identity -----------------------------------------
    (
        "M1a the two rates are swapped in the parity ratio",
        SRC,
        _IMPLIED_FORWARD,
        "    implied_forward = spot * (1.0 + i_foreign_period) / (1.0 + i_domestic_period)",
    ),
    (
        "M1b the linear interest-differential approximation replaces the ratio",
        SRC,
        _IMPLIED_FORWARD,
        "    implied_forward = spot * (1.0 + i_domestic_period - i_foreign_period)",
    ),
    (
        "M1c the parity ratio is multiplied instead of divided",
        SRC,
        _IMPLIED_FORWARD,
        "    implied_forward = spot / ((1.0 + i_domestic_period) / (1.0 + i_foreign_period))",
    ),
    # --- M2: the annualisation -------------------------------------------
    (
        "M2a the tenor scaling dropped (annualised rates read as period rates)",
        SRC,
        _PERIOD_SCALE,
        "    period_scale = 1.0",
    ),
    (
        "M2b the tenor scaling inverted",
        SRC,
        _PERIOD_SCALE,
        "    period_scale = basis_days / inputs.tenor_days",
    ),
    (
        "M2c only the domestic leg is annualised",
        SRC,
        _I_F_PERIOD,
        "    i_foreign_period = inputs.i_foreign_annualized",
    ),
    (
        "M2d the domestic leg reads the foreign rate",
        SRC,
        _I_D_PERIOD,
        "    i_domestic_period = inputs.i_foreign_annualized * period_scale",
    ),
    (
        "M2e the basis is annualised by multiplying instead of dividing",
        SRC,
        _BASIS_BP,
        "    basis_bp_annualized = basis_period * period_scale * 10_000.0",
    ),
    (
        "M2f the ACT/365 year is given 360 days",
        SRC,
        _BASIS_DAYS_LINE,
        '_BASIS_DAYS: dict[str, int] = {"actual_360": 360, "actual_365": 360}',
    ),
    # --- M3: the sign ----------------------------------------------------
    (
        "M3a the deviation's numerator is reversed (sign flipped)",
        SRC,
        _DEVIATION_FRACTION,
        "    deviation_fraction = (implied_forward - forward) / implied_forward",
    ),
    (
        "M3b the synthetic-rate ratio is inverted",
        SRC,
        _SYNTHETIC,
        "    synthetic_domestic_period = (spot / forward) * (1.0 + i_foreign_period) - 1.0",
    ),
    (
        "M3c the basis's sign is flipped",
        SRC,
        _BASIS_PERIOD,
        "    basis_period = i_domestic_period - synthetic_domestic_period",
    ),
    (
        "M3d the deviation is published as a fraction, not a percentage",
        SRC,
        _DEVIATION_PCT,
        "    deviation_pct = deviation_fraction",
    ),
    # --- M4: the quote convention ----------------------------------------
    (
        "M4a the inversion is disabled (every quote read as domestic-per-foreign)",
        SRC,
        _INVERTED_FLAG,
        "    inverted = False",
    ),
    (
        "M4b the branch inverts nothing (the flag is read but not acted on)",
        SRC,
        _INVERT_BRANCH,
        "    if inverted:\n        spot = inputs.spot\n        forward = inputs.forward",
    ),
    (
        "M4c the inversion condition is inverted",
        SRC,
        _INVERTED_FLAG,
        '    inverted = inputs.quote == "domestic_per_foreign"',
    ),
    # --- M5: the bands ---------------------------------------------------
    (
        "M5a the extreme band collapses onto the notable one",
        SRC,
        _SEVERITY_EXTREME,
        "    if magnitude > notable_pct:",
    ),
    (
        "M5b the notable band collapses onto the extreme one",
        SRC,
        _SEVERITY_NOTABLE,
        "    elif magnitude > extreme_pct:",
    ),
    (
        "M5c the quiet side-band extends to the extreme threshold",
        SRC,
        _SIDE_QUIET,
        "    if magnitude <= extreme_pct:",
    ),
    (
        "M5d the funding side's sign rule is reversed",
        SRC,
        _SIDE_SIGN,
        "    elif deviation_pct < 0.0:",
    ),
    (
        "M5e the extreme boundary becomes inclusive (>= instead of >)",
        SRC,
        _SEVERITY_EXTREME,
        "    if magnitude >= extreme_pct:",
    ),
    (
        "M5f the notable boundary becomes inclusive (>= instead of >)",
        SRC,
        _SEVERITY_NOTABLE,
        "    elif magnitude >= notable_pct:",
    ),
    # --- M6: the guards --------------------------------------------------
    (
        "M6a the finiteness guard removed (nan reaches the arithmetic)",
        SRC,
        _FINITE_GUARD,
        "            if False:",
    ),
    (
        "M6b a zero exchange rate is admitted",
        SRC,
        _POSITIVE_GUARD,
        "            if value < 0.0:",
    ),
    (
        "M6c the tenor guard removed (simple interest past one money-market year)",
        SRC,
        _TENOR_GUARD,
        "        if False:",
    ),
    (
        "M6d the period-rate guard is unreachable",
        SRC,
        _PERIOD_RATE_GUARD,
        "            if 1.0 + period <= -1.0:",
    ),
    # --- M7: the warnings ------------------------------------------------
    (
        "M7a the extreme warning removed",
        SRC,
        _WARN_EXTREME,
        "    if False:",
    ),
    (
        "M7b the notable warning removed",
        SRC,
        _WARN_NOTABLE,
        "    elif False:",
    ),
    # --- M8: the published value and the confidence ----------------------
    (
        "M8a the deviation is published at 2dp (the hand-computed digits are lost)",
        SRC,
        _DEVIATION_KEY,
        '            "deviation_pct": round(deviation_pct, 2),',
    ),
    (
        "M8b the domestic period rate publishes the foreign one",
        SRC,
        _I_D_PERIOD_KEY,
        '            "i_domestic_period": round(i_foreign_period, 8),',
    ),
    (
        "M8c the basis is published un-annualised (the identity breaks by the tenor)",
        SRC,
        _BASIS_KEY,
        '            "domestic_funding_basis_bp_annualized": round(basis_period, 4),',
    ),
    (
        "M8d the published severity is a constant",
        SRC,
        _SEVERITY_KEY,
        '            "severity": "none",',
    ),
    (
        "M8e the published funding side is a constant",
        SRC,
        _SIDE_KEY,
        '            "stressed_currency": "none",',
    ),
    (
        "M8f the published normalization target is the wrong space",
        SRC,
        _NORMALIZED_KEY,
        '            "normalized_to": "foreign_per_domestic",',
    ),
    (
        "M8g the inversion flag is published as a constant",
        SRC,
        _INVERTED_KEY,
        '            "quote_was_inverted": False,',
    ),
    (
        "M8h the confidence drops the heuristic penalty",
        SRC,
        _HEURISTIC_FLAG,
        "                is_heuristic_not_calibrated=False,",
    ),
    # --- C1: the config accessors and validators -------------------------
    (
        "C1a the notable band is a hardcoded literal",
        SRC,
        _NOTABLE_READ,
        "    notable_pct = 0.1",
    ),
    (
        "C1b the extreme band is a hardcoded literal",
        SRC,
        _EXTREME_READ,
        "    extreme_pct = 0.5",
    ),
    (
        "C1c the notable accessor returns the EXTREME leaf",
        CONFIG,
        _NOTABLE_PROP,
        "        return float(self.extreme_deviation_pct.value)",
    ),
    (
        "C1d the extreme accessor returns the NOTABLE leaf",
        CONFIG,
        _EXTREME_PROP,
        "        return float(self.notable_deviation_pct.value)",
    ),
    (
        "C1e the calibration helper reports calibrated unconditionally",
        SRC,
        _CALIBRATED_READ,
        "    return True",
    ),
    (
        "C1f the calibration helper reads the EXTREME leaf",
        SRC,
        _CALIBRATED_READ,
        '    return settings.is_calibrated("fx_carry.extreme_deviation_pct")',
    ),
    (
        "C1g the band-ordering validator removed",
        CONFIG,
        _ORDER_VALIDATOR,
        "        if False:",
    ),
    (
        "C1h the positive-band validator removed",
        CONFIG,
        _POSITIVE_VALIDATOR,
        "        if False:",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_cip_check.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            # `-x` is D-057's rule, not a preference: a kill is a kill, the
            # first failing test is sufficient evidence, and an interrupted
            # long run on win32 leaves every mutant applied so far on disk
            # (D-082).
            "-x",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def main() -> int:
    # The whole interrupt defence in one call (O-103): heal any sidecar a killed
    # previous run left behind, write the pristine text to a sidecar BEFORE the
    # first mutation, and consume it on the way out. On win32 no Python signal
    # handler runs for SIGTERM/SIGINT, so the sidecar — not a handler — is the
    # defence that actually has reach here.
    with sweep_lifecycle([SRC, CONFIG]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)", flush=True)
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep that cannot")
        print("prove it mutates the site it names certifies nothing.")
        return 4

    survivors: list[tuple[str, str]] = []
    try:
        for name, target, old, new in _MUTATIONS:
            pristine = originals[target]
            if old not in pristine:
                print(f"PATTERN MISSING   {name}  [{target.name}]", flush=True)
                survivors.append((name, "pattern-not-found"))
                continue
            target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
            caught = not run_tests()
            target.write_text(pristine, encoding="utf-8", newline="")
            print(f"{'KILLED' if caught else 'SURVIVED':17} {name}", flush=True)
            if not caught:
                survivors.append((name, "survived"))
    finally:
        # Belt and braces: an exception mid-mutation must never leave the tree
        # mutated. A SIGTERM on win32 still can — no handler and no ``finally``
        # gets a turn — which is the case the sidecar covers, not this.
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    print()
    print("=" * 74)
    total = len(_MUTATIONS)
    killed = total - len(survivors)
    print(f"MUTATION SWEEP — cip_check: {killed}/{total} killed", flush=True)
    print("=" * 74)
    if survivors:
        print("SURVIVORS (each is a weak test, an inert mutation, or a broken one):")
        for name, reason in survivors:
            print(f"  [{reason}] {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated module, so every
    # "killed" above is a statement about the harness rather than the suite
    # (D-051). CANARY1 is REQUIRED to be killed, not tolerated as a survivor.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3
    if survivors:
        return 1
    print("  every mutation killed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
