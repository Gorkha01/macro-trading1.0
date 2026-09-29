"""Mutation sweep for ``models/inflation_convergence.py`` (Module 5.3).

Each mutation reverts one correction in the classifier to a plausible
alternative, and each must be killed. The mutations are grouped by the defect
class they represent, and the most important group is **F**, which reverts
Section 15.19-D's integration — the reason this increment exists.

* **A** — the confidence denominator. Reverts the family count to the raw signal
  count, or to the specification's hardcoded literal. **A1 is the central defect
  this increment exists to prevent.**
* **B** — the conflict gate. Reverts the corrected whole-set gate to §15.19-C's
  headline/core pair test only.
* **C** — the disclosures. Drops the base-rate, degeneracy or family-ceiling
  warnings, or makes a conditional one unconditional (which would turn a signal
  into noise).
* **D** — the arithmetic. Reverts the agreeing fraction, pools flat readings into
  a side, or drops the all-flat guard.
* **E** — the published verdict. Turns the structured ``value`` back into a bare
  label (§22.9), or drops the denominator that makes it readable.
* **F** — Section 15.19-D's integration. Makes the family count *indistinguishable*
  from the signal count in the confidence term, or credits the classifier for
  evidence it did not measure.
* **G** — the family map. Re-tags a measure to the wrong family — the mutation
  that silently fabricates convergence.
* **C-1** — config literals hardcoded (the shared "no hardcoded values" mutation
  every sweep carries).

A survivor is one of four things: a weak test, an **inert** mutation, a
**broken** mutation (D-031), or a **mis-targeted** one (D-040). The runner
reports a pattern-miss separately from a survival, and it **heals before it
measures**.

Run in the FOREGROUND. The sweep owns the source file for its whole duration;
run it in the background and a restore will silently revert concurrent edits,
and a hard kill skips the ``finally`` (D-045a).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import check_only, check_only_requested, sweep_lifecycle

SRC = Path("src/macro_engine/models/inflation_convergence.py")
CONFIG_YAML = Path("config/settings.yaml")
CONFIG_PY = Path("src/macro_engine/config.py")

# --- reusable pattern fragments -------------------------------------------

# A. The confidence denominator -------------------------------------------

_CONF_FAMILIES = "                source_independence_count=independent_families,"
_CONF_SIGNALS = "                source_independence_count=total,"
_CONF_ZERO = "                source_independence_count=0,"
_CONF_LITERAL = """        confidence=0.5 if total < 6 else 0.7,"""

# B. The conflict gate -----------------------------------------------------

_WHOLE_SET_GATE = (
    '    if total > 0 and losing >= deep_conflict_share * total:\n        return "CONFLICTED"'
)
_PAIR_GATE_ONLY = """    if False:
        return "CONFLICTED\""""

# The pair gate itself, reverted to using `directions[0] * directions[1]` off a
# positional list rather than the named fields — the specification's own form.
_PAIR_GATE = """    if headline * core < 0:
        return "CONFLICTED\""""
_PAIR_GATE_DROPPED = """    if False:
        return "CONFLICTED\""""

# C. The disclosures -------------------------------------------------------

_BASE_RATE_WARNING = (
    '    if classification == "HIGH" and current_rate > settings.base_state_warning_threshold:'
)
_BASE_RATE_UNCONDITIONAL = "    if True:"
# The D-127 defect-reintroduction guard: the boundary reverts to the bare `0.75`
# the audit found, decoupling it from the leaf the comparison is made against.
_BASE_RATE_WARNING_LITERAL = (
    '    if classification == "HIGH" and current_rate > 0.75:  # noqa: PLR2004'
)
# And the inverted form: the comparison reads the leaf but flips the sense, so
# the disclosure stops firing for a HIGH base rate above the bar.
_BASE_RATE_WARNING_INVERTED = (
    '    if classification == "HIGH" and current_rate < settings.base_state_warning_threshold:'
)

_DEGENERACY_WARNING = "    if total < 5:"
_DEGENERACY_DROPPED = "    if False:"

_CEILING_ELIF = "    elif bands:"
_CEILING_DROPPED = "    elif False:"

_FLAT_WARNING = "    if flat:"
_FLAT_WARNING_DROPPED = "    if False:"

_METHOD_CAVEAT = """    warnings.append(
        "Sign test over month-over-month changes. It is a weak statistic: two "
        "measures at +0.001% and one at +5.0% read as agreement. This is a "
        "breadth indicator, not a magnitude estimate."
    )"""
_METHOD_CAVEAT_DROPPED = "    pass"

# D. The arithmetic --------------------------------------------------------

_AGREEING_POSITIVE = "    agreeing_side = sum(1 for d in directions if d > 0)"
_AGREEING_FLAT_POOLED = "    agreeing_side = sum(1 for d in directions if d >= 0)"

_FLAT_GUARD = "    if total > 0 and losing >= deep_conflict_share * total:"
_FLAT_GUARD_DROPPED = "    if False:"

# D2b is the *inert-mutation control*: it re-adds a redundant condition that an
# earlier revision of the source carried. That revision's comment claimed the
# term was a load-bearing "degenerate guard" against the all-flat case; the
# sweep proved it inert, because `losing` is 0 when nothing moves and
# `0 >= share * total` is already False for every positive share. The term was
# removed from the source and this mutation documents *why*: it is EXPECTED TO
# SURVIVE, and the runner reports it as a known-inert case rather than a defect.
# It stays in the list deliberately — re-verified on every run, it would turn
# into a kill if a future change ever made the term matter, announcing itself.
_FLAT_GUARD_INERT = (
    "    if total > 0 and agreeing + opposing > 0 and losing >= deep_conflict_share * total:"
)

# The threshold's boundary: `>` instead of `>=` lets an exactly-at-threshold
# split through, which at n=6 means a 4-2 split stops being CONFLICTED.
_FLAT_GUARD_STRICT = "    if total > 0 and losing > deep_conflict_share * total:"

_ATTAINABLE_SET = "    return sorted({round(k / n, 6) for k in range(n + 1)})"
_ATTAINABLE_ALL = "    return sorted({round(k / 10, 6) for k in range(11)})"

# E. The published verdict -------------------------------------------------

_VERDICT_CONSTRUCT = """        value=InflationConvergenceVerdict(
            classification=classification,
            agreeing=majority,"""
_VERDICT_BARE = """        value=classification,
        # The following model is built and discarded so that the name
        # ``InflationConvergenceVerdict`` stays referenced and the mutation is a
        # pure change of what is PUBLISHED, not a code-hygiene change:
        _discarded=(InflationConvergenceVerdict(
            classification=classification,
            agreeing=majority,"""

_MEASURES_FIELD = """            attainable_fracs=attainable,
            independent_families=independent_families,"""
_MEASURES_DROPPED = """            attainable_fracs=attainable,
            independent_families=0,"""

# The D-127 `majority_direction` field (Card 19). Its anchors:
_MAJORITY_DIRECTION_FIELD = (
    "            majority_direction=_majority_direction(agreeing_side, opposing_side),"
)
_MAJORITY_DIRECTION_DROPPED = "            majority_direction=0,"
_MAJORITY_DIRECTION_INVERTED = (
    "            majority_direction=-_majority_direction(agreeing_side, opposing_side),"
)
# The helper's own sign convention (the D-127 replacement for the `agreeing` name).
_MAJORITY_HELPER = """    if up > down:
        return 1
    if down > up:
        return -1
    return 0"""
_MAJORITY_HELPER_SWAPPED = """    if up > down:
        return -1
    if down > up:
        return 1
    return 0"""
_MAJORITY_HELPER_NEVER_TIE = """    if up >= down:
        return 1
    return -1"""

_BASE_RATES_IN_VALUE = "            base_rates=base_rates,"
_BASE_RATES_EMPTY = "            base_rates={},"

# F. Section 15.19-D's integration ----------------------------------------

# The census call itself. Reverting it to `len(directions)` makes the family
# count indistinguishable from the signal count *at the point of use*, which is
# the §15.19-D defect stated as plainly as it can be.
_CENSUS_CALL = '    independent_families = int(census_value["distinct_families"])'
_CENSUS_RAW = "    independent_families = total"

# The tagging loop. Without it every measure is untagged and the census cannot
# separate families at all.
_TAG_CALL = "        results.append(tag_evidence_source(result, family))"
_TAG_DROPPED = "        results.append(result)"

# G. The family map --------------------------------------------------------

_MEDIAN_BLS = '    ("median_cpi_direction", _Family.BLS_CPI),'
_MEDIAN_DALLAS = '    ("median_cpi_direction", _Family.DALLAS_FED),'

_STICKY_BLS = '    ("sticky_price_cpi_direction", _Family.BLS_CPI),'
_STICKY_ATLANTA = '    ("sticky_price_cpi_direction", _Family.ATLANTA_FED),'

_TRIM_DALLAS = '    ("trimmed_mean_direction", _Family.DALLAS_FED),'
_TRIM_BEA = '    ("trimmed_mean_direction", _Family.BEA_PCE),'

# C-1. Config literals -----------------------------------------------------

#: ANCHORED on the preceding key, not the bare scalar. `      value: 0.8` also
#: occurs under `measured_base_rates.six_measure.high` (0.895 — no), and more to
#: the point it is the *shape* of every scalar leaf in the file, so any block
#: inserted above `convergence:` would silently redirect this mutation to the
#: wrong setting. That is D-047's rule 29 ("a mutation anchored on a bare scalar
#: will hit the wrong setting") recurring, and `check_targets` now catches it.
_YAML_HIGH = "    high_threshold:\n      value: 0.8"
_YAML_HIGH_LITERAL = "    high_threshold:\n      value: 0.7"
# The property now DERIVES the ceiling from the two confidence constants and
# cross-checks the configured entry against it. Two mutations fall out of that:
#
# C-1b  the configured cross-check disabled, so the entry goes back to being
#       dead config that nothing validates.
# C-1c  the configured value in YAML contradicted by the derivation, which the
#       cross-check must RAISE rather than silently prefer one of the two.
_PY_CEILING_CROSSCHECK = "        if configured != derived:"
_PY_CEILING_CROSSCHECK_DROPPED = "        if False:"
# The anchor MUST include the key line: `      value: 5` alone matches other
# blocks in this file (credit_spread, and any 5-valued threshold), so anchoring
# on it would silently mutate a DIFFERENT setting and leave this one intact —
# the D-040 mis-targeting defect, which the first revision of this mutation
# committed and the sweep did not catch because the wrong edit still broke
# nothing in this module's tests.
_YAML_CEILING = """    confidence_ceiling_by_independent_families:
      value: 5"""
_YAML_CEILING_WRONG = """    confidence_ceiling_by_independent_families:
      value: 3"""


# A mutation whose name carries this marker is *expected* to survive, because the
# condition it reintroduces is genuinely redundant. It is not a weak test and it
# is not a defect: it is a recorded finding held under continuous verification.
_EXPECTED_INERT = "[INERT BY DESIGN]"


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
        '__all__ = [\n    "CONVERGENCE_CLASSES",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- A: the confidence denominator (the point of the increment) --------
    (
        "A1 the confidence denominator reverts to the raw SIGNAL count",
        SRC,
        _CONF_FAMILIES,
        _CONF_SIGNALS,
    ),
    (
        "A2 the confidence denominator zeroed (independence never credited)",
        SRC,
        _CONF_FAMILIES,
        _CONF_ZERO,
    ),
    (
        "A3 the specification's hardcoded confidence restored",
        SRC,
        """        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=True,
                # Section 15.19-D's integration requirement: the FAMILY count,
                # not len(directions). compute_confidence already credits this,
                # and suppressing it would be the D-027 circularity error in
                # reverse — the classifier would refuse to recognise evidence
                # its own caller had just measured.
                source_independence_count=independent_families,
            )
        ),""",
        _CONF_LITERAL,
    ),
    # --- B: the conflict gate ---------------------------------------------
    (
        "B1 the corrected whole-set gate disabled (pair gate only)",
        SRC,
        _WHOLE_SET_GATE,
        _PAIR_GATE_ONLY,
    ),
    (
        "B2 the specification's own pair gate disabled as well (never conflicted)",
        SRC,
        _PAIR_GATE,
        _PAIR_GATE_DROPPED,
    ),
    # --- C: the disclosures -----------------------------------------------
    (
        "C1 the base-rate disclosure made unconditional (a HIGH constant becomes noise)",
        SRC,
        _BASE_RATE_WARNING,
        _BASE_RATE_UNCONDITIONAL,
    ),
    (
        "C2 the base-rate disclosure dropped entirely",
        SRC,
        _BASE_RATE_WARNING,
        "    if False:",
    ),
    (
        "C3 the threshold-degeneracy disclosure dropped",
        SRC,
        _DEGENERACY_WARNING,
        _DEGENERACY_DROPPED,
    ),
    (
        "C4 [INERT BY DESIGN] the family-ceiling disclosure dropped (branch unreachable)",
        SRC,
        _CEILING_ELIF,
        _CEILING_DROPPED,
    ),
    (
        "C5 the flat-reading exclusion disclosure dropped",
        SRC,
        _FLAT_WARNING,
        _FLAT_WARNING_DROPPED,
    ),
    (
        "C6 the always-on method caveat dropped",
        SRC,
        _METHOD_CAVEAT,
        _METHOD_CAVEAT_DROPPED,
    ),
    # --- D: the arithmetic -------------------------------------------------
    (
        "D1 flat readings pooled into the agreeing side (inflates convergence)",
        SRC,
        _AGREEING_POSITIVE,
        _AGREEING_FLAT_POOLED,
    ),
    (
        "D2 the whole-set conflict gate disabled entirely",
        SRC,
        _FLAT_GUARD,
        _FLAT_GUARD_DROPPED,
    ),
    (
        "D2b [INERT BY DESIGN] a redundant all-flat term re-added to the gate",
        SRC,
        _FLAT_GUARD,
        _FLAT_GUARD_INERT,
    ),
    (
        "D2c the conflict threshold made strict (exactly-at-threshold escapes)",
        SRC,
        _FLAT_GUARD,
        _FLAT_GUARD_STRICT,
    ),
    # NOTE on D2c's kill: `>=` and `>` differ only where `share * total` is an
    # integer, i.e. only at n=4 (threshold 1.0). At n=3, 5 and 6 the threshold is
    # 0.75, 1.25 and 1.5 and no integer `losing` ever equals it, so the mutation
    # is inert there. The kill therefore rests entirely on
    # `test_the_conflict_boundary_is_inclusive`, which is the only test that
    # exercises n=4. If that test is ever weakened, this mutation survives and
    # the runner says so.
    (
        "D3 attainable_fracs reports a fixed grid instead of multiples of 1/n",
        SRC,
        _ATTAINABLE_SET,
        _ATTAINABLE_ALL,
    ),
    # --- E: the published verdict -----------------------------------------
    (
        "E1 the structured verdict replaced by a bare label (Section 22.9)",
        SRC,
        _VERDICT_CONSTRUCT,
        _VERDICT_BARE,
    ),
    (
        "E2 the independent-family count dropped from the value",
        SRC,
        _MEASURES_FIELD,
        _MEASURES_DROPPED,
    ),
    (
        "E3 the measured base rates dropped from the value",
        SRC,
        _BASE_RATES_IN_VALUE,
        _BASE_RATES_EMPTY,
    ),
    # --- F: Section 15.19-D's integration ---------------------------------
    (
        "F1 the family count replaced by the measure count at the point of use",
        SRC,
        _CENSUS_CALL,
        _CENSUS_RAW,
    ),
    (
        "F2 the tagging call dropped (every measure untagged)",
        SRC,
        _TAG_CALL,
        _TAG_DROPPED,
    ),
    # --- G: the family map -------------------------------------------------
    (
        "G1 median CPI re-tagged to the Dallas Fed (publisher-based mapping)",
        SRC,
        _MEDIAN_BLS,
        _MEDIAN_DALLAS,
    ),
    (
        "G2 sticky-price CPI re-tagged to the Atlanta Fed (its publisher)",
        SRC,
        _STICKY_BLS,
        _STICKY_ATLANTA,
    ),
    (
        "G3 trimmed-mean PCE re-tagged to BEA (its microdata source)",
        SRC,
        _TRIM_DALLAS,
        _TRIM_BEA,
    ),
    # --- C-1: config literals ---------------------------------------------
    (
        "C-1a the HIGH threshold hardcoded instead of read from config",
        CONFIG_YAML,
        _YAML_HIGH,
        _YAML_HIGH_LITERAL,
    ),
    (
        "C-1b the configured-vs-derived cross-check disabled (dead config again)",
        CONFIG_PY,
        _PY_CEILING_CROSSCHECK,
        _PY_CEILING_CROSSCHECK_DROPPED,
    ),
    (
        "C-1c the configured ceiling contradicted by the confidence constants",
        CONFIG_YAML,
        _YAML_CEILING,
        _YAML_CEILING_WRONG,
    ),
    # --- Card 19 (D-127): the leaf-driven threshold ------------------------
    # The base-state boundary was a bare `0.75` in the source, silently coupled
    # to `measured_base_rates` (the leaf that moves). C1/C2 above already cover
    # the *code* edit; these cover the *reason* it was a defect: a literal that
    # cannot track the leaf.
    (
        "C-2a the base-state boundary reverts to the literal 0.75 (the D-127 defect)",
        SRC,
        _BASE_RATE_WARNING,
        _BASE_RATE_WARNING_LITERAL,
    ),
    (
        "C-2b the base-state comparison sense inverted (fires below the bar)",
        SRC,
        _BASE_RATE_WARNING,
        _BASE_RATE_WARNING_INVERTED,
    ),
    # --- Card 19 (D-127): `majority_direction` ----------------------------
    (
        "D-1a majority_direction dropped (the sign becomes unrecoverable)",
        SRC,
        _MAJORITY_DIRECTION_FIELD,
        _MAJORITY_DIRECTION_DROPPED,
    ),
    (
        "D-1b majority_direction sign inverted",
        SRC,
        _MAJORITY_DIRECTION_FIELD,
        _MAJORITY_DIRECTION_INVERTED,
    ),
    (
        "D-1c the majority helper's sign convention swapped",
        SRC,
        _MAJORITY_HELPER,
        _MAJORITY_HELPER_SWAPPED,
    ),
    (
        "D-1d the majority helper never reports a tie",
        SRC,
        _MAJORITY_HELPER,
        _MAJORITY_HELPER_NEVER_TIE,
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_inflation_convergence.py",
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


def check_targets(originals: dict[Path, str]) -> list[str]:
    """Refuse to run if any mutation's target text is missing or AMBIGUOUS.

    Back-ported from `mutation_trilemma.py` (D-048), where six mutations were
    found to be silently rewriting the **wrong function**: their `old` text
    occurred twice in the file and ``str.replace(old, new, 1)`` took the first
    occurrence. They were reported as survivors — i.e. as weak tests — when they
    had never touched the code under test.

    A mis-target is more dangerous than a pattern-miss. The file *does* change,
    so the mutation looks applied; the tests then pass, because they were never
    exercising the mutated path; and the conclusion drawn is that the suite is
    weak, when in fact the mutation was pointed at the wrong symbol. A miss is
    visible; this is not.

    Both checks are fatal: the sweep exits rather than reporting a number it
    cannot stand behind.
    """
    problems: list[str] = []
    for name, target, old, new in _MUTATIONS:
        text = originals[target]
        count = text.count(old)
        if count == 0:
            problems.append(f"ABSENT: {name}  [{target}]")
        elif count > 1:
            problems.append(f"AMBIGUOUS (x{count}): {name}  [{target}]")
        if old == new:
            problems.append(f"INERT BY CONSTRUCTION (old == new): {name}")
    return problems


def _applied_mutations(
    originals: dict[Path, str],
) -> list[tuple[str, Path, str, str]]:
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
    # O-103: heal, protect, spend in one call. On win32 no Python signal
    # handler runs for SIGTERM/SIGINT, so the sidecar -- not a handler -- is
    # the defence with real reach here.
    with sweep_lifecycle([SRC, CONFIG_YAML, CONFIG_PY]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:

    # Refuse to measure with a broken table (D-048).
    problems = check_targets(originals)
    if problems:
        print("REFUSING TO RUN — the mutation table does not point at unique, present text:")
        for problem in problems:
            print(f"  {problem}")
        print()
        print("Fix the table (anchor ambiguous targets on surrounding unique context)")
        print("and re-run. Any number this script would report is meaningless.")
        return 3

    repaired = repair_leftover_mutations(originals)
    if repaired:
        print("REPAIRED left over from an interrupted run:")
        for name in repaired:
            print(f"  reverted -> {name}")
        print()

    survivors: list[tuple[str, str]] = []
    inert: list[str] = []
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
            if not caught and _EXPECTED_INERT in name:
                print(f"{'INERT (expected)':17} {name}")
                inert.append(name)
            else:
                print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
                if not caught:
                    survivors.append((name, "survived"))
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8", newline="")

    leftover = _applied_mutations({p: p.read_text(encoding="utf-8") for p in originals})
    if leftover:
        print()
        print("ERROR: a mutation is still applied after the sweep:")
        for name, _, _, _ in leftover:
            print(f"  STILL APPLIED -> {name}")
        return 2

    print()
    total = len(_MUTATIONS)
    killed = total - len(survivors) - len(inert)
    print(f"{killed}/{total - len(inert)} killed ({len(inert)} inert by design)")
    for name in inert:
        print(f"  INERT (expected survivor): {name}")
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

    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
