"""Mutation sweep for Module 12.3/12.4's probability functions.

Each mutation reverts one D-042 correction to a plausible alternative, and each
must be killed:

* **M1** breaks the Bayesian arithmetic.
* **M2** breaks the likelihood ratio or its band.
* **M3** drops a disclosure.
* **M4** breaks the expected-value arithmetic, including the tail comparison's
  strictness.
* **M5** drops a published component, breaking the D-009 cross-field identity.
* **M6** weakens the input contract — the bounds are the *only* thing that
  catches a negative probability, since a sum-to-one check cannot.
* **M7** restores the specification's hardcoded ``confidence`` (0.8 and 0.6).
* **C1** hardcodes the config thresholds.

A survivor is one of four things: a weak test, an **inert** mutation, a
**broken** mutation (D-031), or a **mis-targeted** one — aimed at another
model's symbol (D-040). The runner reports a pattern-miss separately from a
survival, and it **heals before it measures**.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import check_targets, format_problems

SRC = Path("src/macro_engine/models/probability.py")
CONFIG = Path("src/macro_engine/config.py")

# --- M1: the Bayesian arithmetic -------------------------------------------
_DENOMINATOR = (
    "    p_b = inputs.likelihood_given_true * p_a + inputs.likelihood_given_false * p_not_a"
)
_POSTERIOR = "    posterior = (inputs.likelihood_given_true * p_a) / p_b"
_SHIFT = "    shift_pp = (posterior - p_a) * 100.0"

# --- M2: the likelihood ratio and its band ---------------------------------
_LR = "        likelihood_ratio: float | None = ("
_UNINFORMATIVE = (
    "    uninformative = (\n"
    "        likelihood_ratio is not None\n"
    "        and abs(likelihood_ratio - 1.0) < settings.uninformative_lr_band\n"
    "    )"
)

# --- M3: the disclosures ---------------------------------------------------
_LIKELIHOODS_WARNING = (
    '        "The posterior is only as good as the two likelihoods, and those are "\n'
    '        "usually the least defensible numbers in a thesis. A prior stated to two "\n'
    '        "decimals does not make the answer precise (Module 12.3).",'
)
_UNINFORMATIVE_WARNING = (
    "        warnings.append(\n"
    '            f"The likelihood ratio is {likelihood_ratio:.2f}, within "\n'
    '            f"{settings.uninformative_lr_band:.2f} of 1.0 — this evidence barely "\n'
    '            f"distinguishes the two hypotheses, and the {shift_pp:+.1f}pp shift is "\n'
    '            f"noise rather than an update. Do not report the posterior as a finding."\n'
    "        )"
)
_CERTAIN_WARNING = (
    "        warnings.append(\n"
    '            f"The prior is exactly {p_a:.0%}, which no evidence can move: a "\n'
    '            f"probability of 0 or 1 is a statement that no observation could "\n'
    '            f"change it, so the posterior equals the prior by construction."\n'
    "        )"
)
_AVERAGE_WARNING = (
    '        f"Expected value is an average over branches, and an average says nothing "\n'
    '        f"about any single path. The worst case here is "\n'
    '        f"{worst.payoff_estimate:+.2f} at {worst.probability:.1%}.",'
)
_TAIL_WARNING = (
    "        warnings.append(\n"
    '            f"Positive EV ({ev:+.2f}) with a tail loss of "\n'
    '            f"{worst.payoff_estimate:+.2f} — more than "\n'
    '            f"{settings.tail_loss_multiple:.0f}x the average. Size for SURVIVAL of "\n'
    '            f"the tail, not for the average: a strategy that is right on average "\n'
    '            f"and insolvent in the tail never collects the average (LTCM)."\n'
    "        )"
)
_NON_POSITIVE_WARNING = (
    "        warnings.append(\n"
    '            "Expected value is non-positive, so no sizing rule rescues it. A "\n'
    '            "negative-EV position is not made acceptable by being small."\n'
    "        )"
)

# --- M4: the expected-value arithmetic -------------------------------------
_TOTAL_PROBABILITY = "    total_probability = sum(scenario.probability for scenario in scenarios)"
_EV = "    ev = sum(scenario.probability * scenario.payoff_estimate for scenario in scenarios)"
_WORST = "    worst = min(scenarios, key=lambda scenario: scenario.payoff_estimate)"
_TAIL_DOMINATES = "    tail_dominates = ev > 0.0 and worst.payoff_estimate < -settings.tail_loss_multiple * abs(ev)"
_TOLERANCE = "    if abs(total_probability - 1.0) > settings.probability_sum_tolerance:"

# --- M5: the published components -----------------------------------------
_EVIDENCE_KEY = '            "p_evidence": round(p_b, 6),'
_INFORMATIVE_KEY = '            "evidence_informative": not uninformative,'
_CONTRIBUTIONS_KEY = '            "contributions": {'
_WORST_NAME_KEY = '            "worst_case_name": worst.name,'
_TAIL_KEY = '            "tail_dominates": tail_dominates,'

# --- M6: the contract ------------------------------------------------------
_PRIOR_BOUND = "    prior: float = Field(\n        ge=0.0,\n        le=1.0,"
_PROBABILITY_BOUND = "    probability: float = Field(\n        ge=0.0,\n        le=1.0,"

# --- M7: confidence --------------------------------------------------------
_BAYES_HEURISTIC = '            is_heuristic_not_calibrated=True,\n            source_independence_count=0,\n        )\n    )\n\n    return ModelResult(\n        model_name="bayesian_update",'

# --- config accessors ------------------------------------------------------
_BAND_PROP = "        return float(self.uninformative_lr_band_value.value)"
_TOLERANCE_PROP = "        return float(self.probability_sum_tolerance_value.value)"
_TAIL_PROP = "        return float(self.tail_loss_multiple_value.value)"

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # --- M1: the Bayesian arithmetic -------------------------------------
    (
        "M1a the denominator drops the false-hypothesis term",
        SRC,
        _DENOMINATOR,
        "    p_b = inputs.likelihood_given_true * p_a",
    ),
    (
        "M1b the posterior inverted (the evidence term over the denominator swapped)",
        SRC,
        _POSTERIOR,
        "    posterior = (inputs.likelihood_given_false * p_not_a) / p_b",
    ),
    (
        "M1c the shift reported as prior minus posterior",
        SRC,
        _SHIFT,
        "    shift_pp = (p_a - posterior) * 100.0",
    ),
    # --- M2: the likelihood ratio ----------------------------------------
    (
        "M2a the likelihood ratio inverted",
        SRC,
        _LR,
        "        likelihood_ratio: float | None = (\n"
        "            inputs.likelihood_given_false / inputs.likelihood_given_true\n"
        "            if inputs.likelihood_given_true > 0.0\n"
        "            else 0.0\n"
        "        )",
    ),
    (
        "M2b the uninformative band comparison made non-strict",
        SRC,
        _UNINFORMATIVE,
        "    uninformative = (\n"
        "        likelihood_ratio is not None\n"
        "        and abs(likelihood_ratio - 1.0) <= settings.uninformative_lr_band\n"
        "    )",
    ),
    (
        "M2c the band made ASYMMETRIC (the specification's original form)",
        SRC,
        _UNINFORMATIVE,
        "    uninformative = (\n"
        "        likelihood_ratio is not None\n"
        "        and 0.8 < likelihood_ratio < 1.25\n"
        "    )",
    ),
    # --- M3: the disclosures ---------------------------------------------
    (
        "M3a the likelihoods caveat dropped",
        SRC,
        _LIKELIHOODS_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M3b the uninformative-evidence warning dropped (Section 11.1 mandates it)",
        SRC,
        _UNINFORMATIVE_WARNING,
        "        pass",
    ),
    (
        "M3c the certain-prior warning dropped",
        SRC,
        _CERTAIN_WARNING,
        "        pass",
    ),
    (
        "M3d the average-is-not-a-path warning dropped",
        SRC,
        _AVERAGE_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M3e the tail-survival warning dropped (the LTCM lesson)",
        SRC,
        _TAIL_WARNING,
        "        pass",
    ),
    (
        "M3f the non-positive-EV warning dropped",
        SRC,
        _NON_POSITIVE_WARNING,
        "        pass",
    ),
    # --- M4: the expected-value arithmetic -------------------------------
    (
        "M4a the EV drops the probability weighting",
        SRC,
        _EV,
        "    ev = sum(scenario.payoff_estimate for scenario in scenarios)",
    ),
    (
        "M4b the worst case taken as the BEST case",
        SRC,
        _WORST,
        "    worst = max(scenarios, key=lambda scenario: scenario.payoff_estimate)",
    ),
    (
        "M4c the tail comparison made non-strict",
        SRC,
        _TAIL_DOMINATES,
        "    tail_dominates = ev > 0.0 and worst.payoff_estimate <= -settings.tail_loss_multiple * abs(ev)",
    ),
    (
        "M4d the sum tolerance ignored (any sum accepted)",
        SRC,
        _TOLERANCE,
        "    if False:",
    ),
    # --- M5: the published components ------------------------------------
    (
        "M5a the P(B) denominator dropped (the posterior stops being recomputable)",
        SRC,
        _EVIDENCE_KEY,
        '            "p_evidence": 0.0,',
    ),
    (
        "M5b the informativeness flag dropped",
        SRC,
        _INFORMATIVE_KEY,
        '            "evidence_informative": True,',
    ),
    (
        "M5c the EV contributions emptied",
        SRC,
        _CONTRIBUTIONS_KEY,
        '            "unused_contributions": {',
    ),
    (
        "M5d the worst-case name dropped",
        SRC,
        _WORST_NAME_KEY,
        '            "worst_case_name": "unknown",',
    ),
    (
        "M5e the tail-dominates flag dropped",
        SRC,
        _TAIL_KEY,
        '            "tail_dominates": False,',
    ),
    # --- M6: the contract -------------------------------------------------
    (
        "M6a the prior bound removed (a prior of 1.5 is accepted)",
        SRC,
        _PRIOR_BOUND,
        "    prior: float = Field(",
    ),
    (
        "M6b the per-scenario probability bound removed (a NEGATIVE probability is accepted)",
        SRC,
        _PROBABILITY_BOUND,
        "    probability: float = Field(",
    ),
    # --- M7: confidence ---------------------------------------------------
    (
        "M7a bayesian_update's confidence hardcoded to the specification's 0.8",
        SRC,
        "        confidence=confidence,\n        interpretation=(\n"
        '            f"Prior {p_a:.0%} -> posterior {posterior:.0%} "',
        "        confidence=0.8,\n        interpretation=(\n"
        '            f"Prior {p_a:.0%} -> posterior {posterior:.0%} "',
    ),
    (
        "M7b expected_value's confidence hardcoded to the specification's 0.6",
        SRC,
        "        confidence=confidence,\n        interpretation=(\n"
        '            f"EV {ev:+.2f}, worst case {worst.payoff_estimate:+.2f} "',
        "        confidence=0.6,\n        interpretation=(\n"
        '            f"EV {ev:+.2f}, worst case {worst.payoff_estimate:+.2f} "',
    ),
    (
        "M7c the Bayesian heuristic factor hardcoded False",
        SRC,
        _BAYES_HEURISTIC,
        "            is_heuristic_not_calibrated=False,\n"
        "            source_independence_count=0,\n"
        "        )\n"
        "    )\n\n"
        "    return ModelResult(\n"
        '        model_name="bayesian_update",',
    ),
    # --- config accessors -------------------------------------------------
    (
        "C1a the uninformative-LR band property returns a hardcoded value",
        CONFIG,
        _BAND_PROP,
        "        return 0.0",
    ),
    (
        "C1b the sum-tolerance property returns a hardcoded value",
        CONFIG,
        _TOLERANCE_PROP,
        "        return 999.0",
    ),
    (
        "C1c the tail-multiple property returns a hardcoded value",
        CONFIG,
        _TAIL_PROP,
        "        return 0.0",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_probability.py",
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
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
