"""Mutation sweep for Module 3.2's ``policy_mix_classifier``.

Each mutation reverts one D-039 correction to a plausible alternative, and each
must be killed:

* **M1** breaks the quadrant logic.
  *A mutation restoring Section 20.3's ``"MIXED" in quadrant`` substring test was
  REMOVED as inert: on the four current quadrant names the substring search and
  the boolean test are behaviourally IDENTICAL, so no test can distinguish them.
  The boolean form is still preferred — a rename would break the substring one
  silently — but a difference that does not exist cannot be swept for (D-031).*
* **M2** flips a comparison or its strictness. This is the D-034 failure mode:
  an inverted comparison produces a perfectly plausible quadrant measuring the
  opposite of what it claims.
* **M3** drops a disclosure — the base-rate frequency, the MIXED caveat, the
  config-average mismatch, and the **sign warning** for the negative-deficit
  case, which is the trap this function exists to survive.
* **M4** drops a published component, breaking the D-009 cross-field identity.
* **M5** weakens the input contract.
* **M6** restores the specification's hardcoded ``confidence=0.6`` or drops a
  stated confidence factor.
* **C1** swaps or hardcodes the config accessors.

A survivor is one of three things (D-031): a weak test, an **inert** mutation,
or a **broken** mutation. The runner reports a pattern-miss separately from a
survival, and it **heals before it measures** — an interrupted run leaves the
mutated file on disk, and a naive re-run would adopt it as the baseline.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _sweep_gate import (
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)
from _sweep_gate import run_pytest as _run_pytest_inproc

SRC = Path("src/macro_engine/models/national_accounts.py")
CONFIG = Path("src/macro_engine/config.py")

# --- M2: the comparisons ---------------------------------------------------
_FISCAL_LOOSE = (
    "    fiscal_loose = inputs.fiscal_deficit_pct_gdp > inputs.fiscal_deficit_avg_pct_gdp"
)
_MONETARY_LOOSE = "    monetary_loose = inputs.policy_rate < inputs.taylor_implied_rate"

# --- M1: the quadrant logic ------------------------------------------------
_BRANCHES = (
    "    if fiscal_loose and monetary_loose:\n"
    '        quadrant = "MAX_STIMULUS"\n'
    "    elif fiscal_loose:\n"
    '        quadrant = "MIXED_FISCAL_LOOSE_MONETARY_TIGHT"\n'
    "    elif monetary_loose:\n"
    '        quadrant = "MIXED_FISCAL_TIGHT_MONETARY_LOOSE"\n'
    "    else:\n"
    '        quadrant = "MAX_RESTRAINT"'
)
_MIXED = "    mixed = fiscal_loose != monetary_loose"

# --- M4: the base-rate read and the disclosures ----------------------------
_BASE_RATE_READ = "    quadrant_base_rate = settings.quadrant_base_rates[quadrant]"
_BASE_RATE_WARNING = (
    '        f"The policy mix is a CATEGORICAL from two threshold comparisons. Over "\n'
    '        f"{settings.base_rates.observations_measured} annual observations this "\n'
    '        f"quadrant occurred in {quadrant_base_rate:.1%} of them, which is the "\n'
    '        f"frequency a reader needs before treating it as notable (D-029).",'
)
_MIXED_WARNING = (
    "        warnings.append(\n"
    '            "MIXED quadrants mean Fed-only analysis is incomplete — fiscal is "\n'
    '            "working against monetary (Module 3.2). This is the case the module "\n'
    '            "exists for: the two MIXED quadrants together are 50.9% of the "\n'
    '            "measured history, so a mixed stance is ordinary, not exceptional."\n'
    "        )"
)
_MISMATCH_WARNING = (
    "        warnings.append(\n"
    '            f"The supplied deficit average ({inputs.fiscal_deficit_avg_pct_gdp:.2f}% "\n'
    '            f"of GDP) differs from the configured expectation "\n'
    '            f"({settings.fiscal_deficit_avg:.2f}%). The two are one measurement — "\n'
    '            f"a caller using a different window will place the same deficit in a "\n'
    '            f"different quadrant, so the disagreement is reported rather than "\n'
    '            f"silently accepted."\n'
    "        )"
)
_SIGN_WARNING = (
    "        warnings.append(\n"
    '            f"fiscal_deficit_pct_gdp is negative ({inputs.fiscal_deficit_pct_gdp:+.2f}). "\n'
    '            f"This field is POSITIVE for a deficit, so a negative value means either a "\n'
    '            f"genuine surplus or the raw FRED `FYFSGDA188S` figure supplied without "\n'
    '            f"negating it — and the second inverts every comparison silently."\n'
    "        )"
)

# --- M4: the published components -----------------------------------------
_FISCAL_KEY = '            "fiscal_loose": fiscal_loose,'
_MONETARY_KEY = '            "monetary_loose": monetary_loose,'
_MIXED_KEY = '            "mixed": mixed,'
_BASE_RATE_KEY = '            "quadrant_base_rate": quadrant_base_rate,'
_DEFICIT_KEY = '            "fiscal_deficit_pct_gdp": round(inputs.fiscal_deficit_pct_gdp, 4),'

# --- M5: the contract ------------------------------------------------------
_EXTRA_FORBID = (
    '    model_config = ConfigDict(extra="forbid")\n\n    fiscal_deficit_pct_gdp: float = Field('
)
_INPUTS_USED = '            "fiscal_deficit_avg_pct_gdp",\n            "policy_rate",'

# --- M6: confidence --------------------------------------------------------
_HEURISTIC = "            is_heuristic_not_calibrated=not _policy_mix_calibrated(),"
_UNOBSERVABLE = "            depends_on_unobservable=True,"

# --- config accessors ------------------------------------------------------
_AVG_PROP = "        return float(self.fiscal_deficit_avg_pct_gdp.value)"
_NAMES_PROP = "        return self.base_rates.rates"

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
    # --- M1: the quadrant logic ------------------------------------------
    (
        "M1a the branches reordered so fiscal-tight is tested first",
        SRC,
        _BRANCHES,
        "    if fiscal_loose and monetary_loose:\n"
        '        quadrant = "MAX_STIMULUS"\n'
        "    elif not fiscal_loose:\n"
        '        quadrant = "MIXED_FISCAL_TIGHT_MONETARY_LOOSE"\n'
        "    else:\n"
        '        quadrant = "MIXED_FISCAL_LOOSE_MONETARY_TIGHT"',
    ),
    (
        "M1b the quadrant hardcoded to MAX_STIMULUS",
        SRC,
        _BRANCHES,
        '    quadrant = "MAX_STIMULUS"',
    ),
    (
        "M1d the mixed flag inverted",
        SRC,
        _MIXED,
        "    mixed = fiscal_loose == monetary_loose",
    ),
    # --- M2: the comparisons ---------------------------------------------
    (
        "M2a the fiscal comparison made non-strict (a deficit at its average is loose)",
        SRC,
        _FISCAL_LOOSE,
        "    fiscal_loose = inputs.fiscal_deficit_pct_gdp >= inputs.fiscal_deficit_avg_pct_gdp",
    ),
    (
        "M2b the monetary comparison made non-strict",
        SRC,
        _MONETARY_LOOSE,
        "    monetary_loose = inputs.policy_rate <= inputs.taylor_implied_rate",
    ),
    (
        "M2c the fiscal comparison INVERTED (a smaller deficit is loose)",
        SRC,
        _FISCAL_LOOSE,
        "    fiscal_loose = inputs.fiscal_deficit_pct_gdp < inputs.fiscal_deficit_avg_pct_gdp",
    ),
    (
        "M2d the monetary comparison INVERTED (a higher rate is loose)",
        SRC,
        _MONETARY_LOOSE,
        "    monetary_loose = inputs.policy_rate > inputs.taylor_implied_rate",
    ),
    # --- M3: the disclosures ---------------------------------------------
    (
        "M3a the base-rate frequency dropped (D-029 disclosure)",
        SRC,
        _BASE_RATE_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M3b the MIXED caveat dropped",
        SRC,
        _MIXED_WARNING,
        "        pass",
    ),
    (
        "M3c the config-average mismatch warning dropped",
        SRC,
        _MISMATCH_WARNING,
        "        pass",
    ),
    (
        "M3d the SIGN warning dropped (the raw-FRED deficit goes unflagged)",
        SRC,
        _SIGN_WARNING,
        "        pass",
    ),
    # --- M4: the published components ------------------------------------
    (
        "M4a the fiscal_loose predicate dropped from the published value",
        SRC,
        _FISCAL_KEY,
        '            "unused_fiscal": fiscal_loose,',
    ),
    (
        "M4b the monetary_loose predicate dropped from the published value",
        SRC,
        _MONETARY_KEY,
        '            "unused_monetary": monetary_loose,',
    ),
    (
        "M4c the mixed flag dropped from the published value",
        SRC,
        _MIXED_KEY,
        '            "unused_mixed": mixed,',
    ),
    (
        "M4d the quadrant's own base rate dropped",
        SRC,
        _BASE_RATE_KEY,
        '            "quadrant_base_rate": 0.0,',
    ),
    (
        "M4e the raw deficit dropped from the published value",
        SRC,
        _DEFICIT_KEY,
        '            "fiscal_deficit_pct_gdp": 0.0,',
    ),
    # --- M5: the contract -------------------------------------------------
    (
        # D-139 rebased PolicyMixInputs onto `FiniteInputs`, which itself sets
        # `extra="forbid"` — deleting the local declaration became an EQUIVALENT
        # mutation (the base still forbids) and survived. Preserve the intent by
        # OVERRIDING the base with `extra="ignore"`.
        "M5a extra='forbid' overridden with extra='ignore' on the input model",
        SRC,
        _EXTRA_FORBID,
        '    model_config = ConfigDict(extra="ignore")\n\n    fiscal_deficit_pct_gdp: float = Field(',
    ),
    (
        "M5b an input dropped from inputs_used (it still decides the quadrant)",
        SRC,
        _INPUTS_USED,
        '            "policy_rate",',
    ),
    # --- M6: confidence ---------------------------------------------------
    (
        "M6a the heuristic factor hardcoded False",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M6b the unobservable factor hardcoded False (r* stops costing confidence)",
        SRC,
        _UNOBSERVABLE,
        "            depends_on_unobservable=False,",
    ),
    (
        "M6c confidence hardcoded to the specification's 0.6",
        SRC,
        # `confidence=confidence,` occurs in BOTH `policy_mix_classifier` and
        # `minsky_composition_drift`, so the bare line is AMBIGUOUS and
        # `str.replace(..., 1)` takes whichever comes first (D-048). This sweep
        # had no `check_targets`, so nothing noticed until D-064's
        # `tools/sweep_health.py` ran its own target check on the ungated
        # sweeps. Anchored through the policy-mix-specific published key above it.
        (
            '            "quadrant_base_rate": quadrant_base_rate,\n'
            '            "observations_measured": settings.base_rates.observations_measured,\n'
            "        },\n"
            "        confidence=confidence,"
        ),
        (
            '            "quadrant_base_rate": quadrant_base_rate,\n'
            '            "observations_measured": settings.base_rates.observations_measured,\n'
            "        },\n"
            "        confidence=0.6,"
        ),
    ),
    # --- config accessors -------------------------------------------------
    (
        "C1a the deficit average property returns a hardcoded value",
        CONFIG,
        _AVG_PROP,
        "        return 9.99",
    ),
    (
        "C1b the base-rate mapping returns a hardcoded single entry",
        CONFIG,
        _NAMES_PROP,
        '        return {"MAX_STIMULUS": 0.5}',
    ),
]


def run_tests() -> bool:
    proc = _run_pytest_inproc(
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


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only(_MUTATIONS)


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
    # The whole interrupt defence in one call (O-103): heal any sidecar a
    # killed previous run left behind, write the healed text to a sidecar
    # BEFORE the first mutation, and consume it on the way out. On win32 no
    # Python signal handler runs for SIGTERM/SIGINT, so this sidecar -- not
    # the handler -- is the defence that actually has reach here.
    with sweep_lifecycle([SRC, CONFIG]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:

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
        # The restore text comes from the helper's healed originals and is
        # never substituted per-mutation, so an interrupted loop restores
        # pristine source rather than a mutant (D-048).
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
