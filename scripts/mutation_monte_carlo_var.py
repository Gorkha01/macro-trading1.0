"""Mutation sweep for Section 17.1's ``monte_carlo_var`` (Module 17, Tier 5, D-106).

Every mutation below reverts one decision the implementation makes to a
plausible alternative, and each must be killed. The grouping follows the
function's own structure, because a mutation that does not correspond to a
*decision* is a mutation that cannot teach anything:

* **M1** breaks the CORRELATION INDUCTION — the whole point of the estimator.
  ``M1a`` draws each factor independently (the specification's
  ``scenario_generator`` failure mode), ``M1b`` uses an identity factor, and
  ``M1c`` drops the sqrt-time scaling. Any of these produces a confident number
  with no correlation or the wrong horizon in it.
* **M2** breaks the STRESS COMPOSITION — the finding that put
  ``stressed_volatility_multiplier`` in the config. ``M2a`` omits the volatility
  multiple (correlation-only stress), ``M2b`` applies it to only the first
  factor, and ``M2c`` applies the correlation stress to the NORMAL matrix.
* **M3** breaks the SIGN CONVENTION — the positive-loss convention. ``M3a``
  returns the raw return-space quantile (negative), ``M3b`` flips the ES tail
  selection.
* **M4** breaks the GUARDS — the non-PSD refusal, the transform/target pairing,
  the zero-volatility pruning, the all-zero refusal.
* **M5** breaks the WARNINGS — the tail census, the diversification escalation,
  the fallback disclosure, the LTCM note.
* **M6** breaks the REPRODUCIBILITY contract — the published seed, or the
  shared-stream draw.
* **M7** breaks the PUBLISHED VALUE — the amount scaling, the ratio, the
  published keys.
* **M8** weakens the input contract or the confidence computation.
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

from _sweep_gate import (
    _clear_in_flight,
    _set_in_flight,
    check_targets,
    format_problems,
    install_signal_restore,
    line_buffer_stdout,
    record_pristine,
    restore_from_sidecar,
)

SRC = Path("src/macro_engine/models/risk.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# M1: the correlation induction (the estimator's reason to exist).
# --------------------------------------------------------------------------

# The Cholesky application, as shipped.
_CHOLESKY_APPLY = (
    "    correlated = z @ np.asarray(factor, dtype=float).T\n"
    "    factor_pnl = correlated * horizon_scale"
)

# The sqrt-time scale, as shipped.
_HORIZON_SCALE = "    factor_pnl = correlated * horizon_scale"

# The Cholesky factor itself. Written with DOUBLE quotes because ruff-format
# rewrites the single quotes it was authored with — an anchor that assumes the
# pre-format text resolves to nothing and reports as a drifted anchor (this
# sweep's own M1b taught that here).
_CHOLESKY_FACTOR = (
    "        return cast(\n"
    '            "list[list[float]]",\n'
    "            np.linalg.cholesky(np.asarray(covariance, dtype=float)).tolist(),\n"
    "        )"
)

# A factor load the simulation reads.
_COVARIANCE_FROM_FACTOR = "_correlation_to_covariance(correlations, normal_vols)"

# --------------------------------------------------------------------------
# M2: the stress composition (volatility AND correlation).
# --------------------------------------------------------------------------

_VOL_MULT = (
    "    stressed_vols = [vol * settings.stressed_volatility_multiplier for vol in normal_vols]"
)

# The stress transform call.
_STRESS_CALL = "        stressed_cov = stress_correlations(\n            stressed_cov_pre, stressed_correlation, only_correlations_that_rise=True\n        )"

# --------------------------------------------------------------------------
# M3: the sign convention and the tail.
# --------------------------------------------------------------------------

_LOSS_QUANTILE = "    return -_quantile(ordered, 1.0 - confidence)"

_ES_TAIL = "    tail = [value for value in pnls if value <= -var_loss]"

# --------------------------------------------------------------------------
# M4: the guards.
# --------------------------------------------------------------------------

_ALL_ZERO_GUARD = (
    "    if not live:\n"
    "        raise ValueError(\n"
    '            "Every factor volatility is zero, so there is no risk to "\n'
    '            "simulate. A zero-volatility book has zero VaR at every "\n'
    '            "confidence level, which is a statement about the inputs rather "\n'
    '            "than a risk estimate."\n'
    "        )"
)

_ZERO_VOL_PRUNE = "    live = [i for i, vol in enumerate(inputs.factor_volatilities) if vol != 0.0]"

_NO_TRANSFORM_GUARD = (
    "        if stressed_correlation is None:\n"
    "            raise ValueError(\n"
    '                "stress_correlations was not supplied and no "\n'
    '                "stressed_correlation target was given, so the stressed regime "\n'
    '                "would differ from the normal one only by the volatility "\n'
    '                "multiple. Pass the production stress transform (from "\n'
    '                "portfolio/risk_budget.py) — a correlation-breakdown warning "\n'
    '                "that does not actually break any correlation is the LTCM "\n'
    '                "failure mode, not its detection."\n'
    "            )"
)

_NON_PSD_RAISE = (
    "    except np.linalg.LinAlgError as error:\n"
    "        raise ValueError(\n"
    '            f"The {regime} correlation matrix is not a valid joint "'
)

# --------------------------------------------------------------------------
# M5: the warnings.
# --------------------------------------------------------------------------

_TAIL_WARNING = (
    "    if tail_draws < settings.min_tail_draws:\n"
    "        warnings.append(\n"
    '            f"Only {tail_draws:.1f} of {n_sims} draws are expected beyond the "'
)

_DIV_WARNING = "    if div_stressed > settings.stress_diversification_warning:"

_FALLBACK_WARNING = '            f"No stress_correlations transform was supplied, so a uniform "'

_LTCM_NOTE = (
    '        "The normal-vs-stressed VaR gap is the LTCM correlation-breakdown "\n'
    '        "signal (Section 18.2): a large ratio means the book\'s risk depends on "\n'
    '        "correlations holding."'
)

# --------------------------------------------------------------------------
# M6: reproducibility.
# --------------------------------------------------------------------------

_SEED_PUBLISHED = '            "seed": seed,'
_UNIFORM_TARGET = "        if stressed_correlation is None:\n            raise ValueError("

#: The fallback's stress direction (D-129). The audit found this line shipped as
#: ``min`` — reading "raise toward target" as "cap at target" — so a normal book
#: (rho 0.3) kept 0.3 under a 0.9 stress and an already-correlated pair was
#: LOWERED. ``M4e`` reverts ``max`` to ``min`` so the defect cannot return
#: silently: it is the D-126 ``C2b`` defect-reintroduction shape.
_UNIFORM_RAISE = "            raised = max(correlations[i][j], target)"

# --------------------------------------------------------------------------
# M7: the published value.
# --------------------------------------------------------------------------

_VAR_AMOUNT = '            "var_normal_amount": round(var_normal_loss * inputs.portfolio_value, 2),'
_RATIO_PUBLISHED = (
    '            "stressed_to_normal_ratio": (None if math.isnan(ratio) else round(ratio, 6)),'
)
_RATIO_GUARD = "    if var_normal_loss > 0.0:\n        ratio = var_stressed_loss / var_normal_loss"

# --------------------------------------------------------------------------
# M8: the contract and the confidence.
# --------------------------------------------------------------------------

_HEURISTIC_FLAG = "            is_heuristic_not_calibrated=True,"
_DQ_FLAG = "            data_quality_flags_present=tail_draws < settings.min_tail_draws,"
_DIAGONAL_GUARD = (
    "            if abs(diagonal - 1.0) > 1e-9:\n"
    "                raise ValueError(\n"
    '                    f"normal_correlations[{i}][{i}] is {diagonal}. The diagonal "'
)
_SYMMETRY_GUARD = "                if abs(a - b) > 1e-12:"

# --------------------------------------------------------------------------
# C1: the config accessors.
# --------------------------------------------------------------------------

_N_SIMS_PROP = "        return int(self.n_sims_value.value)"
_SEED_PROP = "        return int(self.seed_value.value)"
_VOL_MULT_PROP = "        return float(self.stressed_volatility_multiplier_value.value)"
_DIV_WARN_PROP = "        return float(self.stress_diversification_warning_value.value)"
_TAIL_FOR = "        return n_sims * (1.0 - confidence)"


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
    # --- M1: the correlation induction -----------------------------------
    (
        "M1a independent draws per factor (the spec's scenario_generator failure)",
        SRC,
        _CHOLESKY_APPLY,
        "    correlated = z\n    factor_pnl = correlated * horizon_scale",
    ),
    (
        "M1b the Cholesky factor is the identity (correlation ignored)",
        SRC,
        _CHOLESKY_FACTOR,
        "        return [\n            [1.0 if i == j else 0.0 for j in range(len(covariance))]\n            for i in range(len(covariance))\n        ]",
    ),
    (
        "M1c sqrt-time scaling dropped (horizon has no effect)",
        SRC,
        _HORIZON_SCALE,
        "    factor_pnl = correlated * 1.0",
    ),
    (
        "M1d the portfolio P&L ignores the loadings (weights have no effect)",
        SRC,
        '    return cast("list[float]", (factor_pnl @ loadings).tolist())',
        '    return cast("list[float]", factor_pnl[:, 0].tolist())',
    ),
    # --- M2: the stress composition --------------------------------------
    (
        "M2a the volatility multiple omitted (correlation-only stress)",
        SRC,
        _VOL_MULT,
        "    stressed_vols = [vol * 1.0 for vol in normal_vols]",
    ),
    (
        "M2b the volatility multiple applied to only the first factor",
        SRC,
        _VOL_MULT,
        "    stressed_vols = [\n"
        "        (normal_vols[0] * settings.stressed_volatility_multiplier, *normal_vols[1:])[i]\n"
        "        for i in range(len(normal_vols))\n"
        "    ]",
    ),
    (
        "M2c the correlation stress applied to the NORMAL matrix (stress is a no-op)",
        SRC,
        _STRESS_CALL,
        "        stressed_cov = stress_correlations(\n"
        "            normal_cov, stressed_correlation, only_correlations_that_rise=True\n"
        "        )",
    ),
    (
        "M2d only_correlations_that_rise disabled (hedges get forced positive)",
        SRC,
        "        stressed_cov = stress_correlations(\n"
        "            stressed_cov_pre, stressed_correlation, only_correlations_that_rise=True\n"
        "        )",
        "        stressed_cov = stress_correlations(\n"
        "            stressed_cov_pre, stressed_correlation, only_correlations_that_rise=False\n"
        "        )",
    ),
    # --- M3: the sign convention and the tail ----------------------------
    (
        "M3a the return-space quantile returned (sign convention inverted)",
        SRC,
        _LOSS_QUANTILE,
        "    return _quantile(ordered, 1.0 - confidence)",
    ),
    (
        "M3b the ES tail selected above the boundary instead of below",
        SRC,
        _ES_TAIL,
        "    tail = [value for value in pnls if value >= -var_loss]",
    ),
    (
        "M3c the ES mean sign flipped",
        SRC,
        "    return -sum(tail) / len(tail)",
        "    return sum(tail) / len(tail)",
    ),
    (
        "M3d the loss quantile reads the wrong tail fraction",
        SRC,
        "    return -_quantile(ordered, 1.0 - confidence)",
        "    return -_quantile(ordered, confidence)",
    ),
    # --- M4: the guards --------------------------------------------------
    (
        "M4a the all-zero book returns 0.0 instead of refusing",
        SRC,
        _ALL_ZERO_GUARD,
        "    if not live:\n        return ModelResult(\n"
        '            model_name="monte_carlo_var",\n'
        '            country="us",\n'
        "            as_of=utc_now(),\n"
        '            value={"var_normal_pct": 0.0},\n'
        "            confidence=0.0,\n"
        '            interpretation="zero",\n'
        '            context="zero",\n'
        "            inputs_used=[],\n"
        "            warnings=[],\n"
        "        )",
    ),
    (
        "M4b the zero-volatility factor is NOT pruned (singular matrix survives)",
        SRC,
        _ZERO_VOL_PRUNE,
        "    live = list(range(len(inputs.factor_volatilities)))",
    ),
    (
        "M4c the transform-less call is allowed silently",
        SRC,
        _NO_TRANSFORM_GUARD,
        "        if stressed_correlation is None:\n            stressed_correlation = 0.0",
    ),
    (
        "M4d a non-PSD matrix is silently floored instead of refused",
        SRC,
        _NON_PSD_RAISE,
        "    except np.linalg.LinAlgError as error:\n"
        "        import numpy as _np\n"
        "        _m = _np.asarray(covariance, dtype=float)\n"
        "        _w, _v = _np.linalg.eigh(_m)\n"
        "        _w = _np.clip(_w, 1e-8, None)\n"
        "        _fixed = (_v * _w) @ _v.T\n"
        "        return cast(\n"
        "            'list[list[float]]',\n"
        "            _np.linalg.cholesky(_fixed).tolist(),\n"
        "        )\n"
        "    except ValueError as error:\n"
        "        raise ValueError(\n"
        '            f"The {regime} correlation matrix is not a valid joint "',
    ),
    (
        "M4e the uniform stress CAPS at the target (max reverted to min, D-129)",
        SRC,
        _UNIFORM_RAISE,
        "            raised = min(correlations[i][j], target)",
    ),
    # --- M5: the warnings ------------------------------------------------
    (
        "M5a the tail census warning removed",
        SRC,
        _TAIL_WARNING,
        "    if tail_draws < 0.0:\n"
        "        warnings.append(\n"
        '            f"Only {tail_draws:.1f} of {n_sims} draws are expected beyond the "',
    ),
    (
        "M5b the diversification warning never fires",
        SRC,
        _DIV_WARNING,
        "    if div_stressed > 1.0:",
    ),
    (
        "M5c the fallback disclosure removed",
        SRC,
        _FALLBACK_WARNING,
        '            f"transform absent, using uniform target "',
    ),
    (
        "M5d the LTCM note removed",
        SRC,
        _LTCM_NOTE,
        '        "unused note."',
    ),
    # --- M6: reproducibility --------------------------------------------
    (
        "M6a the published seed is a constant, not the one used",
        SRC,
        _SEED_PUBLISHED,
        '            "seed": settings.seed,',
    ),
    (
        "M6b the published seed is absent",
        SRC,
        _SEED_PUBLISHED,
        '            "seed_unused": seed,',
    ),
    (
        "M6c the stressed regime draws from a DIFFERENT seed stream",
        SRC,
        '        rng=np.random.default_rng(seed),\n        regime="stressed",',
        '        rng=np.random.default_rng(seed + 1),\n        regime="stressed",',
    ),
    # --- M7: the published value -----------------------------------------
    (
        "M7a the VaR amount is double-scaled (percentage times value twice)",
        SRC,
        _VAR_AMOUNT,
        '            "var_normal_amount": round(var_normal_loss * 100 * inputs.portfolio_value, 2),',
    ),
    (
        "M7b the percentage is published as an amount (units swapped)",
        SRC,
        '            "var_normal_pct": round(var_normal_loss * 100, 4),',
        '            "var_normal_pct": round(var_normal_loss, 4),',
    ),
    (
        "M7c the stressed-to-normal ratio inverted",
        SRC,
        _RATIO_GUARD,
        "    if var_normal_loss > 0.0:\n        ratio = var_normal_loss / var_stressed_loss",
    ),
    (
        "M7d the ratio published as None unconditionally",
        SRC,
        _RATIO_PUBLISHED,
        '            "stressed_to_normal_ratio": None,',
    ),
    (
        "M7e the diversification ratios swapped between regimes",
        SRC,
        '            "diversification_ratio_normal": round(div_normal, 6),',
        '            "diversification_ratio_normal": round(div_stressed, 6),',
    ),
    # --- M8: the contract and the confidence -----------------------------
    (
        "M8a the heuristic marker dropped (confidence overstated)",
        SRC,
        _HEURISTIC_FLAG,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M8b the data-quality flag dropped (confidence overstated)",
        SRC,
        _DQ_FLAG,
        "            data_quality_flags_present=False,",
    ),
    (
        "M8c the unit-diagonal guard removed (a covariance matrix passes)",
        SRC,
        _DIAGONAL_GUARD,
        "            if False:\n"
        "                raise ValueError(\n"
        '                    f"normal_correlations[{i}][{i}] is {diagonal}. The diagonal "',
    ),
    (
        "M8d the symmetry guard removed",
        SRC,
        _SYMMETRY_GUARD,
        "                if False:",
    ),
    (
        "M8e the fallback target range guard removed",
        SRC,
        "    if not -1.0 <= target <= 1.0:",
        "    if not -10.0 <= target <= 10.0:",
    ),
    # --- C1: the config accessors ----------------------------------------
    (
        "C1a n_sims read as a hardcoded constant",
        CONFIG,
        _N_SIMS_PROP,
        "        return int(1000)",
    ),
    (
        "C1b seed read as a hardcoded constant",
        CONFIG,
        _SEED_PROP,
        "        return int(1)",
    ),
    (
        "C1c stressed volatility multiplier hardcoded to 1.0",
        CONFIG,
        _VOL_MULT_PROP,
        "        return 1.0",
    ),
    (
        "C1d the diversification warning threshold hardcoded to 1.0 (never fires)",
        CONFIG,
        _DIV_WARN_PROP,
        "        return 1.0",
    ),
    (
        "C1e the tail census counts the WRONG tail (pre-quantile)",
        CONFIG,
        _TAIL_FOR,
        "        return n_sims * confidence",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_monte_carlo_var.py",
            "tests/models/test_risk.py",
            "tests/portfolio/test_risk_budget.py",
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
    # FIRST: a kill from here on must leave a log behind (O-124).
    line_buffer_stdout()
    # A truncated pipe closes stdout and kills this process; the sidecar is the
    # win32-safe defence (install_signal_restore cannot fire on win32).
    install_signal_restore()

    originals: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in {SRC, CONFIG}}

    for path in restore_from_sidecar(sorted(originals)):
        print(f"RESTORED {path.name} from sidecar (previous run was killed)")
        originals[path] = path.read_text(encoding="utf-8")
        print()

    record_pristine(originals)

    repaired = repair_leftover_mutations(originals)
    if repaired:
        print("REPAIRED left over from an interrupted run:")
        for name in repaired:
            print(f"  reverted -> {name}")
        print()

    # Refuse to measure before anything is mutated (D-048, O-29). A drifted
    # anchor reports as a survivor, which reads as "the suite has a hole" when
    # the truth is "the sweep aimed at the wrong text".
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)")
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
                print(f"PATTERN MISSING   {name}  [{target.name}]")
                survivors.append((name, "pattern-not-found"))
                continue
            target.write_text(pristine.replace(old, new, 1), encoding="utf-8", newline="")
            _set_in_flight(target, pristine)
            caught = not run_tests()
            target.write_text(pristine, encoding="utf-8", newline="")
            _clear_in_flight()
            print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
            if not caught:
                survivors.append((name, "survived"))
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")
            _clear_in_flight()

    print()
    print("=" * 74)
    total = len(_MUTATIONS)
    killed = total - len(survivors)
    print(f"MUTATION SWEEP — monte_carlo_var: {killed}/{total} killed")
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
