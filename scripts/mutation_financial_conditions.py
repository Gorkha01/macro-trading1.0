"""Mutation sweep for Module 12's ``compute_fci``.

Each mutation reverts one D-038 correction to a plausible alternative, and each
must be killed:

* **M1** breaks the standardization. ``M1a`` is the important one: it removes
  the division by ``std``, producing exactly the **raw-deviation composite that
  Section 22.7 / Finding #7 exists to correct** — the placeholder Section 22.13
  says must not exist. If the suite does not catch it, the correction is
  decoration.
* **M2** breaks the orientation. Section 22.7 negates the equity term; an
  inversion flips the index's whole interpretation while leaving every number
  plausible (the D-034 failure mode).
* **M3** breaks the config linkage or the component-set contract.
* **M4** drops a disclosure — including the *absent* NFCI cross-check, which
  must be as loud as a divergence.
* **M5** drops a published component, breaking the D-009 cross-field identity.
* **M6** weakens the input contract, or removes the weights-sum-to-one guard.
* **M7** restores the specification's hardcoded ``confidence=0.4``.
* **C1** swaps or hardcodes the config accessors.

A survivor is one of three things (D-031): a weak test, an **inert** mutation,
or a **broken** mutation. The runner reports a pattern-miss separately from a
survival, and it **heals before it measures** — an interrupted run leaves the
mutated file on disk, and a naive re-run would adopt it as the baseline (see
``mutation_gdp_nowcast.py`` for the incident).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import check_targets, format_problems

SRC = Path("src/macro_engine/models/financial_conditions.py")
CONFIG = Path("src/macro_engine/config.py")

# ---------------------------------------------------------------------------
# Named fragments. Each must match byte-for-byte.
# ---------------------------------------------------------------------------

# --- M1: the standardization (Finding #7) ---------------------------------
_Z_SCORE = "        return (self.value - self.mean) / self.std"
_MEAN = "        return (self.value - self.mean) / self.std"

# --- M2: the orientation --------------------------------------------------
_NEGATED_CONST = '_NEGATED_COMPONENTS: frozenset[FCIComponentName] = frozenset({"equity_index"})'
_SIGN = "        sign = -1.0 if name in _NEGATED_COMPONENTS else 1.0"

# --- M3: the config linkage and the set contract --------------------------
_WEIGHTS_READ = "    weights = settings.component_weights"
_SET_CHECK = (
    "    configured = set(settings.component_names)\n"
    "    modelled = set(components)\n"
    "    if configured != modelled:\n"
    "        raise ValueError(\n"
    '            f"fci.weights.components is {sorted(configured)} but the model carries "\n'
    '            f"{sorted(modelled)}. The two must be the same set — a component on one "\n'
    '            f"side only is silently dropped from, or added to, the composite."\n'
    "        )"
)
_FCI_SUM = "    fci = sum(contributions.values())"
_CONTRIB = "        contributions[name] = sign * weights[name] * z"
_TIGHTER = "    tighter_than_average = fci > 0.0"

# --- M4: the disclosures --------------------------------------------------
_WEIGHTS_WARNING = (
    '        "Weights are illustrative defaults, not calibrated against the Chicago "\n'
    '        "Fed\'s NFCI methodology. Cross-check before this feeds any thesis at "\n'
    '        "meaningful confidence.",'
)
_WINDOW_WARNING = (
    '        f"The z-scores are computed over a {inputs.standardization_window_years}-year "\n'
    '        f"window, which is bounded by data availability rather than chosen: the "\n'
    '        f"high-yield spread series returns only ~3 years on this build. A component "\n'
    '        f"standardised over a different window is not comparable, so every "\n'
    '        f"component must use the same one.",'
)
_ABSENT_WARNING = (
    "        warnings.append(\n"
    '            "NFCI cross-check NOT PERFORMED: no `nfci_value` was supplied. "\n'
    '            "Section 21.1 calls this cross-check mandatory, so the composite is "\n'
    '            "uncorroborated and must not be used at size."\n'
    "        )"
)
_MISMATCH_WARNING = (
    "        warnings.append(\n"
    '            f"The declared standardization window is "\n'
    '            f"{inputs.standardization_window_years} years but config expects "\n'
    '            f"{settings.standardization_window_years}. The model cannot verify which "\n'
    '            f"window was actually used; it reports the declared one and flags the "\n'
    '            f"disagreement."\n'
    "        )"
)

# --- M5: the published components -----------------------------------------
_Z_KEY = '            "z_scores": {name: round(z, 4) for name, z in z_scores.items()},'
_CONTRIB_KEY = (
    '            "contributions": {name: round(c, 4) for name, c in contributions.items()},'
)
_NEGATED_KEY = '            "negated_components": sorted(_NEGATED_COMPONENTS),'
_CHECKED_KEY = '            "nfci_cross_checked": inputs.nfci_value is not None,'
_TIGHTER_KEY = '            "tighter_than_average": tighter_than_average,'

# --- M6: the input contract -----------------------------------------------
_EXTRA_FORBID = '    model_config = ConfigDict(extra="forbid")\n\n    value: float = Field('
_STD_FIELD = "    std: float = Field(\n        gt=0.0,"
_WINDOW_FIELD = "    standardization_window_years: int = Field(\n        gt=0,"

# --- M7: confidence -------------------------------------------------------
_HEURISTIC = "            is_heuristic_not_calibrated=not _weights_calibrated(),"

# --- config accessors -----------------------------------------------------
_SUM_GUARD = "        if abs(total - 1.0) > 1e-9:"
_WEIGHTS_PROP = '        raw = self.weights.get("components", {})'
_NAMES_PROP = "        return tuple(self.component_weights)"
_WINDOW_PROP = "        return int(self.standardization_window_years_value.value)"
_NFCI_PROP = "        return float(self.nfci_divergence_threshold_value.value)"

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # --- M1: the standardization -----------------------------------------
    (
        "M1a the division by std REMOVED (the raw-deviation placeholder)",
        SRC,
        _Z_SCORE,
        "        return self.value - self.mean",
    ),
    (
        "M1b the mean not subtracted (z-scores the level, not the deviation)",
        SRC,
        _MEAN,
        "        return self.value / self.std",
    ),
    (
        "M1c the z-score hardcoded to zero",
        SRC,
        _Z_SCORE,
        "        return 0.0",
    ),
    # --- M2: the orientation ---------------------------------------------
    (
        "M2a the equity term NOT negated (the index inverts)",
        SRC,
        _NEGATED_CONST,
        "_NEGATED_COMPONENTS: frozenset[FCIComponentName] = frozenset()",
    ),
    (
        "M2b the credit spread negated instead of equity",
        SRC,
        _NEGATED_CONST,
        '_NEGATED_COMPONENTS: frozenset[FCIComponentName] = frozenset({"credit_spread_hy"})',
    ),
    (
        "M2c every component negated",
        SRC,
        _SIGN,
        "        sign = -1.0",
    ),
    (
        "M2d no component negated",
        SRC,
        _SIGN,
        "        sign = 1.0",
    ),
    # --- M3: the config linkage and the set contract ---------------------
    (
        "M3a the weights hardcoded instead of read from config",
        SRC,
        _WEIGHTS_READ,
        '    weights = {"policy_rate": 0.25, "credit_spread_hy": 0.25, "term_premium": 0.2,'
        ' "equity_index": 0.2, "usd_index": 0.1}',
    ),
    (
        "M3b the component-set mismatch check removed",
        SRC,
        _SET_CHECK,
        "    pass",
    ),
    (
        "M3c the composite taken as the FIRST contribution, not the sum",
        SRC,
        _FCI_SUM,
        "    fci = next(iter(contributions.values()))",
    ),
    (
        "M3d the contribution sign dropped from the arithmetic",
        SRC,
        _CONTRIB,
        "        contributions[name] = weights[name] * z",
    ),
    (
        "M3e the tighter-than-average comparison made non-strict",
        SRC,
        _TIGHTER,
        "    tighter_than_average = fci >= 0.0",
    ),
    # --- M4: the disclosures ---------------------------------------------
    (
        "M4a the illustrative-weights warning dropped",
        SRC,
        _WEIGHTS_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4b the window caveat dropped",
        SRC,
        _WINDOW_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4c the ABSENT cross-check warning dropped (silence reads as corroboration)",
        SRC,
        _ABSENT_WARNING,
        "        pass",
    ),
    (
        "M4d the window-mismatch warning dropped",
        SRC,
        _MISMATCH_WARNING,
        "        pass",
    ),
    # --- M5: the published components ------------------------------------
    (
        "M5a the z-scores dropped from the published value",
        SRC,
        _Z_KEY,
        '            "z_scores": {},',
    ),
    (
        "M5b the contributions dropped (the identity stops being checkable)",
        SRC,
        _CONTRIB_KEY,
        '            "contributions": {},',
    ),
    (
        "M5c the orientation disclosure dropped",
        SRC,
        _NEGATED_KEY,
        '            "negated_components": [],',
    ),
    (
        "M5d the cross-check flag hardcoded True",
        SRC,
        _CHECKED_KEY,
        '            "nfci_cross_checked": True,',
    ),
    (
        "M5e the tighter-than-average flag dropped",
        SRC,
        _TIGHTER_KEY,
        '            "tighter_than_average": False,',
    ),
    # --- M6: the input contract ------------------------------------------
    (
        "M6a extra='forbid' removed from the component model",
        SRC,
        _EXTRA_FORBID,
        "    value: float = Field(",
    ),
    (
        "M6b the positive-std guard weakened to allow zero",
        SRC,
        _STD_FIELD,
        "    std: float = Field(\n        ge=0.0,",
    ),
    (
        "M6c the positive-window guard weakened to allow zero",
        SRC,
        _WINDOW_FIELD,
        "    standardization_window_years: int = Field(\n        ge=0,",
    ),
    # --- M7: confidence ---------------------------------------------------
    (
        "M7a the heuristic factor hardcoded False (the penalty stops applying)",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M7b confidence hardcoded to the specification's 0.4",
        SRC,
        "        confidence=confidence,",
        "        confidence=0.4,",
    ),
    # --- config accessors -------------------------------------------------
    (
        "C1a the weights-sum-to-one guard removed",
        CONFIG,
        _SUM_GUARD,
        "        if abs(total - 1.0) > 1e9:",
    ),
    (
        "C1c the component weights hardcoded",
        CONFIG,
        _WEIGHTS_PROP,
        '        raw = {"policy_rate": 1.0}',
    ),
    (
        "C1d component_names returns a hardcoded single component",
        CONFIG,
        _NAMES_PROP,
        '        return ("policy_rate",)',
    ),
    (
        "C1e standardization_window_years returns a hardcoded value",
        CONFIG,
        _WINDOW_PROP,
        "        return 10",
    ),
    (
        "C1f the NFCI threshold returns a hardcoded value",
        CONFIG,
        _NFCI_PROP,
        "        return 99.0",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_financial_conditions.py",
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
    """Find mutations currently sitting in the tree.

    Applied means its ``old`` text is **absent** and its ``new`` text is
    **present** — testing for ``new`` alone gives false positives, because
    several replacement strings are substrings of legitimate code.
    """
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
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
