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

**M19 and M20 were added after a post-commit review** found two silent-failure
paths in the column *names*: a caller column literally named ``const`` silently
overwrote the intercept in ``beta`` (the fit reported fewer coefficients than were
supplied, and raised nothing), and a duplicated label reached a pandas dtype check
as an ``AttributeError`` rather than a refusal. Both are now guarded, and both
guards are swept — a guard added in response to a review is exactly the kind that
is never exercised again.

A survivor is one of three things (D-031): a weak test, an **inert** mutation
(the edit cannot change any asserted token), or a **broken** mutation (the
fragment no longer matches the source, usually because ``ruff format`` moved a
trailing comma). The runner reports a pattern miss separately from a survival so
those cannot be confused.

A fourth case was forced by this increment: **inert by route**. M34's guard is
correct but unreachable, because statsmodels trips the critical-value guard first
on every input the API accepts. Rather than contort a fixture to reach it or
delete a live defence, the survivor is listed in ``INERT_BY_ROUTE`` with its
measurement; the runner refuses to certify a stale, dangling or unexplained
entry, so the exemption cannot outlive its reason (see that dict's comment).

**M33-M55 are Module 18's third function, ``test_cointegration``.** They are
aimed at the three failure modes §15.20-F exists to close: a verdict reported
from a degenerate fit (M33-M35), a half-life whose AR(1) algebra or alias
boundary is wrong (M36-M41), and a mandatory warning or regime check that
degrades into prose (M42-M50). M51-M53 target comparison direction and the
``n_obs`` contract; M54 the method dispatch; M55 the Johansen p-value alias.

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

_CONFIDENCE_PENALTY = (
    "                # apparent precision (Section 22.8).\n"
    "                is_heuristic_not_calibrated=not _r_squared_floor_is_calibrated(),"
)

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
        "                # apparent precision (Section 22.8).\n"
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
    # ------------------------------------- the column-NAME guards (D-092 review)
    (
        "M19 const-name collision guard removed",
        "    if _INTERCEPT_NAME in {str(name) for name in X.columns}:",
        "    if False:  # MUTANT M19 -- a `const` column may silently overwrite the intercept",
    ),
    (
        "M20 duplicate-name guard removed",
        "    if duplicated_names:",
        "    if False:  # MUTANT M20 -- a duplicated label may reach the pandas dtype check",
    ),
    # ------------------------------------------- test_stationarity (D-094)
    #
    # M21 is the one that matters. The two tests have INVERTED nulls, so writing
    # the two booleans the other way round transposes every verdict the function
    # ever produces — and the function would still run, still return numbers, and
    # still look entirely healthy. Nothing but a test that pins the DIRECTION can
    # catch it.
    (
        "M21 the inverted nulls transposed (ADF/KPSS booleans swapped)",
        "    adf_rejects_unit_root = adf_p_value < alpha\n"
        "    kpss_rejects_stationarity = kpss_p_value < alpha",
        "    adf_rejects_unit_root = kpss_p_value < alpha  # MUTANT M21\n"
        "    kpss_rejects_stationarity = adf_p_value < alpha",
    ),
    (
        "M22 the two inconclusive verdicts collapsed into one",
        '        verdict = "inconclusive_conflict"\n'
        "    else:\n"
        '        verdict = "inconclusive_low_power"',
        '        verdict = "inconclusive_low_power"  # MUTANT M22\n'
        "    else:\n"
        '        verdict = "inconclusive_low_power"',
    ),
    (
        "M23 conflict warning dropped",
        '    if verdict == "inconclusive_conflict":',
        "    if False:  # MUTANT M23",
    ),
    (
        "M24 low-power warning dropped",
        '    if verdict == "inconclusive_low_power":',
        "    if False:  # MUTANT M24",
    ),
    (
        "M25 KPSS clipping disclosure dropped",
        "    if kpss_clipped:",
        "    if False:  # MUTANT M25 -- a clipped p-value would read as an exact one",
    ),
    (
        "M26 rank-deficiency disclosure dropped",
        "    if adf_ill_conditioned:",
        "    if False:  # MUTANT M26",
    ),
    (
        "M27 the clip flag published as a constant False",
        '            "kpss_p_value_is_clipped": kpss_clipped,',
        '            "kpss_p_value_is_clipped": False,  # MUTANT M27',
    ),
    (
        "M28 the significance level dropped from the published value",
        '            "significance_level": alpha,',
        '            "significance_level": 0.05,  # MUTANT M28 -- a literal, not the setting used',
    ),
    (
        "M29 the low-power limitation dropped",
        '        "ADF has LOW POWER against a near-unit-root alternative, so \'fails to "',
        '        "MUTANT M29 removed the low-power limitation. "',
    ),
    (
        "M30 constant-series guard removed from the stationarity path",
        "    if math.isclose(float(values.max()), float(values.min()), rel_tol=0.0, abs_tol=0.0):",
        "    if False:  # MUTANT M30",
    ),
    (
        "M31 stationarity observation floor removed",
        "    if len(values) < minimum:",
        "    if False:  # MUTANT M31",
    ),
    (
        "M32 non-finite guard removed from the stationarity path",
        "    if not bool(np.isfinite(values.to_numpy()).all()):",
        "    if False:  # MUTANT M32",
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
    # ------------------------------------------- test_cointegration (D-097)
    #
    # The three SILENT-FAILURE paths found by probing `coint` before the function
    # was written. Each mutation removes a refusal that stands between statsmodels'
    # plausible-looking wrong number and the published result — so each is a
    # candidate for the D-092/D-093/D-094 failure mode, where the defect is not a
    # crash but a number that LOOKS COMPLETE.
    #
    # M33 is the one to watch. `coint` returns `coint_t = -inf` with `pvalue = 0.0`
    # and only a `CollinearityWarning`; without this guard the result carries an
    # infinitely significant statistic from a degenerate regression, and every
    # published field downstream stays finite and well-formed.
    (
        "M33 collinearity / non-finite-statistic refusal removed (silent failure #1)",
        "    if collinear or not math.isfinite(statistic):",
        "    if False:  # MUTANT M33 -- -inf sails through as infinite significance",
    ),
    (
        "M34 non-finite p-value refusal removed",
        "    if not math.isfinite(p_value):\n"
        "        raise ValueError(\n"
        '            f"The cointegration test returned a non-finite p-value ({p_value!r}) "',
        "    if False:  # MUTANT M34\n"
        "        raise ValueError(\n"
        '            f"The cointegration test returned a non-finite p-value ({p_value!r}) "',
    ),
    # Silent failure #2: with trend="n" the criticals come back [nan, nan, nan]
    # and EVERY comparison against NaN is False — so the verdict silently becomes
    # "cannot reject" whatever the statistic.
    (
        "M35 NaN critical-value refusal removed (silent failure #2)",
        "    if not all(math.isfinite(value) for value in critical_values):",
        "    if False:  # MUTANT M35 -- NaN criticals make every comparison False",
    ),
    # Silent failure #3: the half-life alias region. Both gates refuse a fitted
    # slope outside (-1, 0), where the formula returns a plausible wrong number.
    (
        "M36 half-life sign gate removed (a non-reverting spread gets an H)",
        "    if phi >= 0.0:",
        "    if False:  # MUTANT M36 -- phi >= 0 would yield a NEGATIVE half-life",
    ),
    (
        "M37 half-life aliasing gate removed (silent failure #3)",
        "    if phi <= -1.0:",
        "    if False:  # MUTANT M37 -- an alternating spread gets H < 0.693",
    ),
    # The formula's sign. `H = -ln(2)/phi`; dropping the minus gives a NEGATIVE
    # half-life for the reversion case, which is why M36/M37 exist — but this
    # mutation is what proves the tests check the DERIVATION and not just the sign.
    (
        "M38 half-life formula sign dropped (-ln2/phi -> ln2/phi)",
        '        "periods": round(-math.log(2.0) / phi, 8),',
        '        "periods": round(math.log(2.0) / phi, 8),  # MUTANT M38',
    ),
    # The common real-world error: using the persistence rho = 1 + phi where the
    # COMPLEMENT belongs. The result is a plausible positive number of the wrong
    # magnitude, so only a test that computes the formula independently catches it.
    (
        "M39 half-life computed from rho instead of phi",
        '        "periods": round(-math.log(2.0) / phi, 8),',
        '        "periods": round(math.log(2.0) / (1.0 + phi), 8),  # MUTANT M39',
    ),
    # The two-tier disclosure. Removing it leaves a half-life longer than the
    # sample reading as a measured convergence horizon.
    (
        "M40 long-half-life disclosure removed",
        "    if float(periods) >= float(n_obs):",
        "    if False:  # MUTANT M40",
    ),
    (
        "M41 quarter-of-sample disclosure removed",
        "    if float(periods) > float(n_obs) / 4.0:",
        "    if False:  # MUTANT M41",
    ),
    # The regime-stability check: the floor decides "not_tested", and the support
    # comparison is what distinguishes `unstable` from the other two verdicts.
    (
        "M42 regime-stability observation floor removed",
        "    if split_at < minimum or (len(y) - split_at) < minimum:",
        "    if False:  # MUTANT M42 -- an untested half reports as a comparison",
    ),
    (
        "M43 regime-stability support comparison inverted",
        "    elif supports[0] and supports[1]:",
        "    elif not (supports[0] and supports[1]):  # MUTANT M43",
    ),
    # The multiple-testing obligation. Section 15.18-F makes it a COUNT, so both
    # the family-wise rate and the corrected size are computed and quoted; these
    # mutations substitute the two classic shortcuts.
    (
        "M44 family-wise rate approximated by m*alpha",
        "    family_wise = 1.0 - (1.0 - alpha) ** family_size",
        "    family_wise = alpha * family_size  # MUTANT M44 -- wrong at large m",
    ),
    (
        "M45 corrected size given as alpha/m",
        "    corrected = 1.0 - (1.0 - alpha) ** (1.0 / family_size)",
        "    corrected = alpha / family_size  # MUTANT M45",
    ),
    (
        "M46 assumed family size frozen at a literal",
        '        "family_size": family_size,',
        '        "family_size": 10,  # MUTANT M46 -- no longer the configured count',
    ),
    # The two MANDATORY warnings, and the ordering that keeps them undroppable.
    (
        "M47 backward-looking warning dropped",
        '        "COINTEGRATION IS A BACKWARD-LOOKING ESTIMATE THAT BREAKS IN REGIME "\n'
        '        "CHANGE. This statistic describes the sample window it was computed on; "',
        '        "MUTANT M47 removed the mandatory (a) warning. "',
    ),
    (
        "M48 multiple-testing warning dropped",
        '        f"MULTIPLE PAIRWISE TESTS NEED A MULTIPLE-TESTING CORRECTION. Section "',
        '        f"MUTANT M48 removed the multiple-testing warning. "',
    ),
    # The FOURTH silent failure, found in THIS increment by probing: the
    # `coint_johansen` ComplexWarnings escape the public function unless captured.
    # Under `-W error` they become an exception on every Johansen call.
    (
        "M49 Johansen warnings left uncaptured (the leak)",
        "    with warnings.catch_warnings(record=True) as caught:\n"
        '        warnings.simplefilter("always")\n'
        "        result = coint_johansen(",
        "    if True:  # MUTANT M49 -- nothing is captured, so the warnings escape\n"
        "        result = coint_johansen(",
    ),
    (
        "M50 captured-warning disclosure dropped",
        "        if discarded_imaginary > 0:",
        "        if False:  # MUTANT M50 -- captured but silently discarded",
    ),
    # The two critical-value comparisons. A transposition INVERTS every verdict
    # while the function keeps running and every published field stays well-formed.
    (
        "M51 Engle-Granger rejection comparison transposed",
        "    is_rejected = statistic < critical_values[position]",
        "    is_rejected = statistic > critical_values[position]  # MUTANT M51",
    ),
    (
        "M52 Johansen rejection comparison transposed",
        "    is_rejected = statistic > thresholds[position]",
        "    is_rejected = statistic < thresholds[position]  # MUTANT M52",
    ),
    # `n_obs` was WRONG on the Johansen path before this increment — it read the
    # spread's length, which is zero there, publishing `n_obs = 0` beside a
    # statistic computed from hundreds of rows.
    (
        "M53 n_obs taken from the spread length rather than the input",
        '        "n_obs": n_obs,\n'
        "        # The half-life is a nested mapping rather than a bare float",
        '        "n_obs": len(spread),  # MUTANT M53 -- zero on the Johansen path\n'
        "        # The half-life is a nested mapping rather than a bare float",
    ),
    (
        "M54 method validation removed",
        "    selection = _validate_cointegration_method(method)",
        "    selection = method  # MUTANT M54 -- an unknown method reaches the dispatch",
    ),
    (
        "M55 Johansen p-value reported as a number instead of NaN",
        "    return statistic, math.nan, thresholds, is_rejected, discarded_imaginary",
        "    return statistic, 0.0, thresholds, is_rejected, discarded_imaginary  # MUTANT M55",
    ),
]


# Survivors that are INERT BY ROUTE — the guard is real and correct, but no input
# the public API accepts can reach it, so no test can kill the mutation. Listing
# one here is a claim that has to survive the same scrutiny as a test: the reason
# must name the MEASUREMENT, not the intuition, and `_run_sweep` refuses to
# certify if an entry is stale (its mutation is now killed), dangling (its
# mutation no longer exists) or unexplained (< 40 characters). Without that
# closure the dict is just a place to hide a dead gate (D-031's third category).
INERT_BY_ROUTE: dict[str, str] = {
    "M34 non-finite p-value refusal removed": (
        "MEASURED INERT-BY-CONSTRUCTION. `coint` terminates before its p-value can "
        "go non-finite: whenever the first-step regression degenerates, the "
        "MacKinnon critical values come back as (nan, nan, nan) FIRST, so the "
        "critical-value guard (M35) raises and M34's branch is never evaluated. "
        "Re-measured on 93 (configuration x trend) combinations -- independent "
        "random walks (n = 30..1600 x 4 seeds), near-collinear pairs at scales "
        "1e-9/1e-12/1e-15/0.0 (the silent-failure-#1 shape), constant y, "
        "constant x, and y identical to x, each across trend='c'/'ct'/'n' -- "
        "returning 31 configurations with non-finite critical values and ZERO "
        "with a non-finite p-value. The guard is kept as defence against a future "
        "statsmodels release rather than deleted, and this entry documents why no "
        "test can be written for it. The NaN-critical-value route IS reached "
        "directly by "
        "`test_the_non_finite_guards_fire_when_the_route_is_reached` (which kills "
        "M35), so the family is proven live even though this member is not."
    ),
}


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
        marker = "  SURVIVOR (inert-by-route)" if name in INERT_BY_ROUTE else f"  SURVIVOR ({why})"
        print(f"{marker}: {name}")
        if name in INERT_BY_ROUTE:
            print(f"      {INERT_BY_ROUTE[name]}")

    # `INERT_BY_ROUTE` has to be a CLOSED statement, not a shrug. A survivor that
    # is merely "expected" is indistinguishable from a dead gate, so every entry
    # is checked for a stated reason and the set is checked for staleness: an
    # entry whose mutation is now KILLED is a stale exemption, and one whose
    # mutation no longer exists in the table is a dangling one. Both would let a
    # real hole hide behind a comment (D-031's third category, wired up).
    # The arities differ on purpose and are a real trap: `MUTATIONS` is the bare
    # table (3-tuples) while `_iter_mutations()` pairs each with its target file
    # (4-tuples). Both were written as 4-tuples on the first pass and both raised
    # `ValueError` -- after the sweep had already run, so the kill count printed
    # and the certification never did. An unpacking error here is not cosmetic
    # (D-031): it means a run that measured everything cannot say what it found.
    killed_names = {name for name, _, _, _ in _iter_mutations()} - {name for name, _ in survivors}
    stale = INERT_BY_ROUTE.keys() & killed_names
    dangling = INERT_BY_ROUTE.keys() - {name for name, _, _ in MUTATIONS}
    unexplained = {name for name, reason in INERT_BY_ROUTE.items() if len(reason) < 40}
    for name in sorted(stale):
        print()
        print(f"REFUSING TO CERTIFY: {name} is listed INERT_BY_ROUTE but was KILLED.")
        print("  The exemption is stale — the suite now catches it, so the entry")
        print("  must go. A stale exemption is a comment that outlived its reason.")
    for name in sorted(dangling):
        print()
        print(f"REFUSING TO CERTIFY: {name} is in INERT_BY_ROUTE but not in MUTATIONS.")
    for name in sorted(unexplained):
        print()
        print(f"REFUSING TO CERTIFY: {name} has no stated reason in INERT_BY_ROUTE.")
    if stale or dangling or unexplained:
        return 5

    # Only the UNEXPLAINED survivors are failures. A guard whose route the public
    # API provably cannot reach is inert, and saying so — with a measurement — is
    # more honest than contorting a fixture to reach it (D-031).
    unexplained_survivors = [name for name, _ in survivors if name not in INERT_BY_ROUTE]

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

    if unexplained_survivors:
        print()
        print(f"{len(unexplained_survivors)} UNEXPLAINED survivor(s) remain.")
    return 0 if not unexplained_survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
