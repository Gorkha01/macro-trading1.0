"""Mutation sweep for Module 7.5's ``simple_gdp_nowcast``.

The suite exists to prove the four corrections D-034 records are load-bearing
rather than cosmetic. Each mutation below reverts one of them to the
specification's own spelling, and each must be killed:

* **M1** reverts the **trade term's sign** — the central correction. A
  mutation that puts the specification's positive weight back on the
  net-exports percent change must be caught, because that is the defect that
  made the term wrong on 414/414 months. Killed by the two-direction tests and
  by the sign test against the raw level.
* **M2** reverts the **cadence correction**: passes a raw month through instead
  of annualizing the quarter's mean, or averages without annualizing. Killed by
  the annualization tests.
* **M3** reverts the **weights** to the specification's literals 0.6/0.3/0.1,
  making the config entries decorative. Killed by the hand-computed
  contribution test.
* **M4** breaks the **accuracy disclosure**: drops the measured error from the
  value dict, hardcodes ``beats_persistence``, or removes the warnings. Killed
  by the disclosure tests and by the recomputation test.
* **M5** weakens the **refusals**: the non-finite guard and the
  incomplete-quarter refusal.
* **M6** breaks the **quarter selection**: uses the latest key seen rather than
  the latest complete one, so the nowcast would be built from a partial quarter.
* **M7** softens the **input contract**: ``extra="forbid"`` and the optional
  cross-check field's default.

A survivor is one of three things (D-031): a weak test, an **inert** mutation
(the edit cannot change any asserted token), or a **broken** mutation (the
fragment no longer matches the source, usually because ``ruff format`` moved a
trailing comma). The runner reports pattern-miss separately from survival so
those cannot be confused.

Every pattern is matched against the pristine source read from the repo.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path("src/macro_engine/models/gdp_nowcast.py")
CONFIG = Path("src/macro_engine/config.py")

# ---------------------------------------------------------------------------
# Named fragments, so the mutation literals stay readable and under the line
# limit. Each must match the source byte-for-byte, including indentation and
# trailing commas — ruff format will reflow a fragment that only approximately
# matches, and the sweep would then silently not apply.
# ---------------------------------------------------------------------------

# --- M1: the net-exports sign ---------------------------------------------
_NET_EXPORTS_SIGN = "    net_exports_contribution = net_exports * settings.net_exports"
_NET_EXPORTS_WEIGHT_PROP = (
    '        """Share of GDP attributable to net exports — **negative** by construction.'
)
_NET_EXPORTS_RETURN = "        return float(self.net_exports_weight.value)"

# --- M2: the cadence ------------------------------------------------------
_ANNUALIZE_RETURN = "    return mean_monthly * months_per_quarter"
_ANNUALIZE_MEAN = "    mean_monthly = sum(monthly_pct_changes) / len(monthly_pct_changes)"
_COMPLETE_CHECK = "    return len(monthly_pct_changes) == months_per_quarter"

# --- M3: the weights ------------------------------------------------------
_CONSUMPTION = "    consumption_contribution = consumption * settings.consumption"
_INVESTMENT = "    investment_contribution = investment * settings.investment"

# --- M4: the accuracy disclosure ------------------------------------------
_ERROR_KEY = '        "mean_abs_error_pp": measured_error,'
_BENCHMARK_KEY = '        "persistence_mean_abs_error_pp": benchmark,'
_BEATS_KEY = '        "beats_persistence": beats_persistence,'
_BEATS_COMPUTE = "    beats_persistence = improvement > settings.persistence_improvement_threshold"
_HEADLINE_WARNING = (
    '        f"NOT A VALIDATED NOWCAST. Measured one quarter ahead on "\n'
    "        f\"{accuracy.quarters} quarters of this build's live data, this model's mean \"\n"
    '        f"absolute error is {measured_error:.3f}pp against {benchmark:.3f}pp for simply "\n'
    '        f"reporting the prior quarter\'s realised print unchanged — it ties that "\n'
    '        f"benchmark rather than beating it. The specification\'s own form was no better "\n'
    '        f"({accuracy.spec_form_correlation:+.3f} correlation with the quarter it names, "\n'
    '        f"i.e. opposite to the quantity being estimated).",'
)
_BASE_RATE_WARNING = (
    '        f"Do not read a direction from this. Realised growth was positive in "\n'
    '        f"{accuracy.realised_positive_share:.1%} of the measured quarters, so a "\n'
    "        f\"prediction of 'positive' every time scores better on sign agreement than this \"\n"
    '        f"model does. A near-constant outcome makes sign agreement uninformative; the "\n'
    '        f"error figures above are the usable content."'
)
_BASIS_WARNING = (
    '        "BASIS MISMATCH, deliberate and disclosed: retail sales and durable-goods orders "\n'
    '        "are NOMINAL, while prior_quarter_annualized is a REAL annualized rate. The "\n'
    '        "delta therefore carries a price change the base does not, so part of it is an "\n'
    '        "inflation estimate wearing a volume label. Retained because the specification "\n'
    '        "names these inputs and deflating them would need a deflator the specification "\n'
    '        "does not supply."'
)
_SIGN_WARNING = (
    '        f"Net exports enter with weight {settings.net_exports:+.3f} — NEGATIVE, because "'
)
_IMPROVEMENT = "    improvement = benchmark - measured_error"

# D-035 additions: the over-weighting disclosure is now load-bearing, so it gets
# its own mutation group.
_OVERWEIGHT_KEY = '        "delta_overweighting_ratio": delta_overweighting,'
_OVERWEIGHT_WARNING = (
    '        f"The reason is structural, not a tuning failure. The adjustment term is "\n'
    '        f"{delta_overweighting:.1%} of the magnitude of the change it exists to predict — "\n'
    '        f"|delta| averages {abs(delta):.4f}pp against {benchmark:.4f}pp of quarterly "\n'
    '        f"movement — while correlating with that change at only "\n'
    '        f"{accuracy.correlation:+.3f} (R^2 "\n'
    '        f"{accuracy.correlation**2:.3f}). The term carries a signal of the "\n'
    '        f"right sign at roughly half the needed size, so applying it at full weight adds "\n'
    '        f"more noise than information. Shrinking a correctly-signed term has a real "\n'
    '        f"optimum; fitting that optimum on the same quarters that measure it recovers "\n'
    '        f"only 0.0395pp (D-027\'s circularity), so the weights are left unfitted.",'
)
_TIE_PHRASE = (
    '        f"reporting the prior quarter\'s realised print unchanged — it ties that "\n'
    '        f"benchmark rather than beating it. The specification\'s own form was no better "'
)

# --- M5: the refusals -----------------------------------------------------
_FINITE_GUARD = "    if not isfinite(inputs.prior_quarter_annualized):"
_NO_USABLE_GUARD = "    if not usable:"

# --- M6: quarter selection ------------------------------------------------
_TARGET = "    target = usable[-1]"

# --- M7: the input contract ----------------------------------------------
_EXTRA_FORBID = '    model_config = ConfigDict(extra="forbid")\n\n    retail_sales_mom:'
_PUBLISHED_DEFAULT = "    published_gdpnow: float | None = Field(\n        default=None,"

# --- config-side fragments -------------------------------------------------
_ACCURACY_PROP_MEAN = "        return float(self.mean_abs_error_pp.value)"
_ACCURACY_PROP_BENCH = "        return float(self.persistence_mean_abs_error_pp.value)"
_ACCURACY_PROP_CORR = "        return float(self.correlation_with_realised.value)"
_ACCURACY_PROP_QUARTERS = "        return int(self.quarters_measured.value)"
_ACCURACY_PROP_SHARE = "        return float(self.realised_positive_rate.value)"
_ACCURACY_PROP_GDPNOW = "        return float(self.gdpnow_published_mean_abs_error_pp.value)"
_SPEC_CORR_PROP = "        return float(self.spec_form_correlation_with_realised.value)"
_THRESHOLD_PROP = "        return float(self.persistence_improvement_threshold_pp.value)"

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # --- M1: the trade term's sign (D-034's central correction) -----------
    (
        "M1a net-exports sign reverted to the spec's positive weight",
        SRC,
        _NET_EXPORTS_SIGN,
        "    net_exports_contribution = net_exports * abs(settings.net_exports)",
    ),
    (
        "M1b net-exports contribution hardcoded positive",
        SRC,
        _NET_EXPORTS_SIGN,
        "    net_exports_contribution = abs(net_exports * settings.net_exports)",
    ),
    (
        "M1c net-exports contribution dropped entirely",
        SRC,
        _NET_EXPORTS_SIGN,
        "    net_exports_contribution = 0.0",
    ),
    (
        "M1d config net-exports weight made positive (spec's +0.1 sign)",
        CONFIG,
        _NET_EXPORTS_RETURN,
        "        return abs(float(self.net_exports_weight.value))",
    ),
    (
        "M1e config net-exports property returns the raw envelope-less 0.10",
        CONFIG,
        _NET_EXPORTS_RETURN,
        "        return 0.10",
    ),
    # --- M2: the cadence --------------------------------------------------
    (
        "M2a annualization dropped — raw mean returned",
        SRC,
        _ANNUALIZE_RETURN,
        "    return mean_monthly",
    ),
    (
        "M2b annualization is geometric instead of linear (1+m)^12 style scale",
        SRC,
        _ANNUALIZE_RETURN,
        "    return ((1 + mean_monthly / 100) ** months_per_quarter - 1) * 100",
    ),
    (
        "M2c mean replaced by the LAST month (the spec's single-month form)",
        SRC,
        _ANNUALIZE_MEAN,
        "    mean_monthly = monthly_pct_changes[-1]",
    ),
    (
        "M2d completeness accepts a partial quarter (>= instead of ==)",
        SRC,
        _COMPLETE_CHECK,
        "    return len(monthly_pct_changes) >= 1",
    ),
    (
        "M2e completeness accepts an over-long quarter (>= instead of ==)",
        SRC,
        _COMPLETE_CHECK,
        "    return len(monthly_pct_changes) >= months_per_quarter",
    ),
    # --- M3: the weights --------------------------------------------------
    (
        "M3a consumption weight reverted to the spec's literal 0.6",
        SRC,
        _CONSUMPTION,
        "    consumption_contribution = consumption * 0.6",
    ),
    (
        "M3b investment weight reverted to the spec's literal 0.3",
        SRC,
        _INVESTMENT,
        "    investment_contribution = investment * 0.3",
    ),
    (
        "M3c consumption and investment shares swapped",
        SRC,
        _CONSUMPTION,
        "    consumption_contribution = consumption * settings.investment",
    ),
    (
        "M3d consumption share applied without the delta being summed",
        SRC,
        _CONSUMPTION,
        "    consumption_contribution = consumption * settings.consumption / 100.0",
    ),
    # --- M4: the accuracy disclosure --------------------------------------
    (
        "M4a measured error dropped from the value dict",
        SRC,
        _ERROR_KEY,
        '        "mean_abs_error_pp_unused": measured_error,',
    ),
    (
        "M4b persistence benchmark dropped from the value dict",
        SRC,
        _BENCHMARK_KEY,
        '        "persistence_mean_abs_error_pp_unused": benchmark,',
    ),
    (
        "M4c beats_persistence hardcoded True",
        SRC,
        _BEATS_KEY,
        '        "beats_persistence": True,',
    ),
    (
        "M4d beats_persistence comparison inverted",
        SRC,
        _BEATS_COMPUTE,
        "    beats_persistence = improvement < settings.persistence_improvement_threshold",
    ),
    (
        "M4e improvement sign flipped (benchmark + measured)",
        SRC,
        _IMPROVEMENT,
        "    improvement = benchmark + measured_error",
    ),
    (
        "M4f headline 'not a validated nowcast' warning emptied",
        SRC,
        _HEADLINE_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4g the tie-not-a-win phrase removed from the headline warning (D-035)",
        SRC,
        _TIE_PHRASE,
        '        f"reporting the prior quarter\'s realised print unchanged. "',
    ),
    (
        "M4k the over-weighting ratio key dropped from the published value (D-035)",
        SRC,
        _OVERWEIGHT_KEY,
        '        "unused_overweighting_placeholder": delta_overweighting,',
    ),
    (
        "M4l the structural-reason warning dropped (a reader would hunt for a weight)",
        SRC,
        _OVERWEIGHT_WARNING,
        '        f"Model output follows. "',
    ),
    (
        "M4h base-rate warning dropped (D-029 disclosure)",
        SRC,
        _BASE_RATE_WARNING,
        '        f"Realised growth was positive in some quarters. "',
    ),
    (
        "M4i basis-mismatch warning dropped",
        SRC,
        _BASIS_WARNING,
        '        "Retail sales and durable-goods orders are monthly. "',
    ),
    (
        "M4j net-exports sign disclosure dropped",
        SRC,
        _SIGN_WARNING,
        '        f"Net exports enter the estimate. "',
    ),
    # --- M5: the refusals -------------------------------------------------
    (
        "M5a non-finite base guard removed",
        SRC,
        _FINITE_GUARD,
        "    if False:",
    ),
    (
        "M5b no-usable-quarter refusal removed (falls through to usable[-1])",
        SRC,
        _NO_USABLE_GUARD,
        "    if not usable and False:",
    ),
    # --- M6: quarter selection --------------------------------------------
    (
        "M6a target takes the LATEST key seen, not the latest complete one",
        SRC,
        _TARGET,
        "    target = usable[0]",
    ),
    # --- M7: the input contract -------------------------------------------
    (
        "M7a extra='forbid' removed from the input model",
        SRC,
        _EXTRA_FORBID,
        "    retail_sales_mom:",
    ),
    (
        "M7b published_gdpnow given a truthy default instead of None",
        SRC,
        _PUBLISHED_DEFAULT,
        "    published_gdpnow: float | None = Field(\n        default=0.0,",
    ),
    # --- config accessors --------------------------------------------------
    (
        "C1a mean_abs_error property returns a hardcoded value",
        CONFIG,
        _ACCURACY_PROP_MEAN,
        "        return 1.0",
    ),
    (
        "C1b persistence benchmark property returns the measured error (swapped)",
        CONFIG,
        _ACCURACY_PROP_BENCH,
        "        return float(self.mean_abs_error_pp.value)",
    ),
    (
        "C1c correlation property reads the spec-form leaf (swapped)",
        CONFIG,
        _ACCURACY_PROP_CORR,
        "        return float(self.spec_form_correlation_with_realised.value)",
    ),
    (
        "C1d quarters property returns a hardcoded 0",
        CONFIG,
        _ACCURACY_PROP_QUARTERS,
        "        return 0",
    ),
    (
        "C1e realised_positive_share property reads the wrong leaf",
        CONFIG,
        _ACCURACY_PROP_SHARE,
        "        return float(self.quarters_measured.value)",
    ),
    (
        "C1f gdpnow published error property returns a hardcoded 0.0",
        CONFIG,
        _ACCURACY_PROP_GDPNOW,
        "        return 0.0",
    ),
    (
        "C1g spec-form correlation property returns the corrected form's value",
        CONFIG,
        _SPEC_CORR_PROP,
        "        return float(self.correlation_with_realised.value)",
    ),
    (
        "C1h persistence improvement threshold property returns 0.0",
        CONFIG,
        _THRESHOLD_PROP,
        "        return 0.0",
    ),
]


def run_tests() -> bool:
    # The test path is a literal, not a constant, because ruff's S603 rule
    # treats a variable argument to ``subprocess`` as potentially untrusted
    # input and cannot see that a pinned constant is safe.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_gdp_nowcast.py",
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

    A mutation is *applied* only when its ``old`` text is **absent** and its
    ``new`` text is **present**. Testing for the ``new`` text alone gives false
    positives, because several mutations' ``new`` strings are substrings of
    legitimate code — ``C1b``'s replacement is literally the body of ``C1a``'s
    real accessor. Requiring the ``old`` text to be gone is what distinguishes
    a mutation from the original it shadows.

    This matters because a power loss during a sweep leaves the mutated file on
    disk (the restore never runs). Without this check the NEXT run would read
    the mutated file as ``originals`` and write it back after every mutation —
    baking the corruption in permanently and reporting the mutation as
    ``PATTERN MISSING``. That is exactly what happened on 2026-09-17, when a
    laptop shutdown left ``M5b`` (the no-usable-quarter refusal disabled)
    applied in ``gdp_nowcast.py``.
    """
    found: list[tuple[str, Path, str, str]] = []
    for name, target, old, new in _MUTATIONS:
        text = originals[target]
        if old not in text and new in text:
            found.append((name, target, old, new))
    return found


def repair_leftover_mutations(originals: dict[Path, str]) -> list[str]:
    """Invert any mutation left applied by an interrupted run.

    The repair is possible without a backup because each mutation records both
    directions: replacing its ``new`` text with its ``old`` text restores the
    original exactly. Self-healing beats refusing to start, because the
    operator's most likely response to a refusal is to re-run anyway.
    """
    repaired: list[str] = []
    for name, target, old, new in _applied_mutations(originals):
        originals[target] = originals[target].replace(new, old, 1)
        target.write_text(originals[target], encoding="utf-8", newline="")
        repaired.append(name)
    return repaired


def main() -> int:
    originals: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in {SRC, CONFIG}}

    # Heal before measuring. See ``_applied_mutations`` for why this is not
    # optional: a stale mutation would otherwise be adopted as the baseline.
    repaired = repair_leftover_mutations(originals)
    if repaired:
        print("REPAIRED left over from an interrupted run:")
        for name in repaired:
            print(f"  reverted -> {name}")
        print()

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
        # Belt and braces: an exception or a Ctrl-C mid-mutation must never
        # leave the tree mutated. A power loss still can, which is what the
        # repair pass at the top of this function is for.
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
