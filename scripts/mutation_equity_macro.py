"""Mutation sweep for Section 6.9's ``sector_rotation_prior`` — the model and
its config block.

**One function, one new module, one sweep** (D-108/D-118's shape). The labels are
partitioned by concern, not by file, because this increment adds a new model
module and a new config class but **no new data-layer client** (the function
reads no market data — its only input is a regime label):

* **``E1``-``E9``** are ``models/equity_macro.py``'s — the map, the coverage
  constants, the lookup, the fallback, the confidence, the warnings and the
  published contract.
* **``N1``-``N3``** are ``src/macro_engine/config.py``'s ``EquityMacroSettings``
  — the accessors and the two validators.

Why this module is swept at all
--------------------------------
``sector_rotation_prior`` is a LOOKUP, and a lookup's defects are silent by
construction: every row is a plausible list of sectors, and every branch returns
a well-formed result. The decisions a future edit is most likely to "simplify"
are exactly the ones this increment exists to protect:

* **the exhaustiveness of the map** over the classifier's vocabulary — the whole
  reason this function supersedes Section 6.9's six-key reference (three
  reachable states, ``slowdown`` / ``recovery`` / ``reflation``, would silently
  return the generic fallback);
* **the vocabulary refusal** — the field typed as the classifier's ``Literal``,
  which stops a misspelling reaching the ``.get``;
* **the confidence product** — which replaced the ``min()`` that would have made
  one factor dead code;
* **the prior-not-rule caveat** — the model's central claim about itself, which a
  tidy-up would move to prose.

⚠️ **Every ``old`` string below was measured at exactly one occurrence with
``str.count()`` before being written**, and the measurement (not the author's
belief about the bytes) is what this file records. The FIRST measurement pass
found the caveat warning string at **2** sites (it appears in both ``warnings``
and ``context``) and the three config accessor/validator bodies at **6** sites
each (five sibling settings blocks share byte-identical bodies — the O-145
collision). Every one was WIDENED with a distinguishing neighbour, never deleted
(D-109).

**⚠️ ``E1a`` and the canary are the two mutations that must NOT survive.**
``E1a`` removes a specification row, which is the coverage defect this function
was built to close; the canary is a syntax error, and if it survives the
selection no longer reaches the module and no kill below is evidence about the
suite (O-72, D-051) — the sweep REFUSES TO CERTIFY rather than reporting health.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _sweep_gate import (
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)

SRC = Path("src/macro_engine/models/equity_macro.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# E1: the map and the coverage constants.
# --------------------------------------------------------------------------

# The map declaration itself. A mutation that empties it makes EVERY regime fall
# back, which is the coverage hole in its purest form.
_MAP_DECL = "SECTOR_ROTATION_PRIOR: dict[str, tuple[str, ...]] = {"
# One specification row, removed. This is the increment's headline defect: the
# reference body omits three rows, so removing one from an exhaustive map proves
# the suite measures exhaustiveness rather than asserting it from the code.
_EARLY_ROW = '    "early_expansion": ("financials", "consumer_discretionary", "industrials"),'
# One extension row, removed. Distinct from the above: the extension rows are this
# build's declaration, so a mutation here proves the coverage test covers them too.
_SLOWDOWN_ROW = '    "slowdown": ("staples", "healthcare", "utilities"),'
# The specification tuple. Shortening it makes the partition test fail.
_SPEC_TUPLE = 'SPECIFICATION_REGIMES: tuple[str, ...] = (\n    "early_expansion",'
# The extension tuple. Widening it breaks the partition claim.
_EXT_TUPLE = 'SECTOR_PRIOR_EXTENSION_REGIMES: tuple[str, ...] = (\n    "slowdown",'

# --------------------------------------------------------------------------
# E2: the input field and the vocabulary refusal.
# --------------------------------------------------------------------------

# The field's Literal. Widening it back to `str` reintroduces Section 6.9's bare-
# string defect: a misspelling reaches the `.get` and receives the fallback.
_INPUT_REGIME_FIELD = "    regime_state: RegimeState = Field("

# --------------------------------------------------------------------------
# E3: the lookup, the fallback and the published container.
# --------------------------------------------------------------------------

_GET_CALL = "    sectors = SECTOR_ROTATION_PRIOR.get(regime)"
_HAS_PRIOR = "    has_prior = sectors is not None"
_PUBLISHED = (
    "    published: list[str] = list(sectors) if sectors is not None else "
    "[equity_macro.no_prior_label]"
)

# --------------------------------------------------------------------------
# E4: the confidence — the product and its four inputs.
# --------------------------------------------------------------------------

_CONF_PRODUCT = "    confidence = computed * equity_macro.reliability_value"
_COMPUTED_CALL = "    computed = compute_confidence(\n        ConfidenceInputs("
_FLAGS_PRESENT = "            data_quality_flags_present=not has_prior,"
_HEURISTIC = (
    "            is_heuristic_not_calibrated=not equity_macro.reliability_cap_is_calibrated,"
)
_SOURCE_INDEP = "            source_independence_count=1,"

# --------------------------------------------------------------------------
# E5: the warnings and the caveat.
# --------------------------------------------------------------------------
#
# ⚠️ WIDENED: the caveat string occurs TWICE in the module — once in `warnings`
# and once in `context`. The `warnings: list[str] = [` opener distinguishes the
# warning site (the `context=(` opener does the same for the other), so each is
# one site.
_CAVEAT_WARNING = (
    "    warnings: list[str] = [\n"
    '        "This is a historical BASE-RATE PRIOR, not a mechanical rule — every "'
)
_FALLBACK_WARNING = (
    '            f"Regime {regime!r} is a declared classifier state with no defined "'
)
_EXT_ASSUMPTION = '            f"The row for {regime!r} is this build\'s declaration, NOT Section "'

# --------------------------------------------------------------------------
# E6: the published contract and the module-level import assertion.
# --------------------------------------------------------------------------

_VALUE_KW = "        value=published,"
_UNIT_KW = '        unit="sector_names",'
_SOURCE_FAMILY_KW = "        source_family=EvidenceSourceFamily.MANUAL_ASSESSMENT,"
_COUNTRY_KW = '        country="us",'
_ASSERT_MAP = "assert set(get_args(RegimeState)) == set(REGIME_STATES), ("

# --------------------------------------------------------------------------
# N1-N3: the config.
#
# ⚠️ THE ACCESSOR AND VALIDATOR BODIES ARE SHARED WITH FIVE SIBLING BLOCKS.
#    `return float(self.reliability_cap.value)`,
#    `return self.reliability_cap.is_trustworthy` and
#    `if not 0.0 <= self.reliability_value <= 1.0:` each occur SIX times in
#    `config.py` (Intervention / EMVulnerability / OilBalance / Gold /
#    MetalsComplex / EquityMacro). A mutation that hardcodes a constant is a WEAK
#    test (D-031), and an anchor that matches two sites is not a mutation, it is
#    an AMBIGUITY. Each is WIDENED with a distinguishing neighbour that exists
#    only in EquityMacroSettings. WIDEN, never delete (D-109/O-145).
# --------------------------------------------------------------------------

_N1_CAP_PROP = (
    "        content of the model's own caveat.\n"
    '        """\n'
    "        return float(self.reliability_cap.value)"
)
# WIDENED with the FOLLOWING property's opener: the docstring tail is shared with
# three siblings, but `def no_prior_label` is unique to this block.
_N1_CALIBRATED_READ = (
    "        return self.reliability_cap.is_trustworthy\n"
    "\n"
    "    @property\n"
    "    def no_prior_label(self) -> str:"
)
_N2_LABEL_PROP = "        return str(self.no_prior_label_leaf.value)"
_N3_CAP_VALIDATOR = (
    '                f"equity_macro.reliability_cap is {self.reliability_value}. A "'
)
_N3_LABEL_VALIDATOR = (
    '                f"equity_macro.no_prior_label is {self.no_prior_label!r}. It is "'
)


_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # -- canary (CONTROL) -------------------------------------------------
    # NOT a revert of a project decision: a mutation CERTAIN to be caught, so the
    # sweep can REFUSE TO CERTIFY when it survives. The anchor is the module's
    # FIRST STATEMENT — the future import — so it does not churn (O-119/O-126).
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        "from __future__ import annotations",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- E1: the map and the coverage constants --------------------------
    (
        "E1a a specification row is removed (three states fall back)",
        SRC,
        _EARLY_ROW,
        "",
    ),
    (
        "E1b an extension row is removed (a reachable state falls back)",
        SRC,
        _SLOWDOWN_ROW,
        "",
    ),
    (
        "E1c the whole map is emptied (every regime falls back)",
        SRC,
        _MAP_DECL,
        "SECTOR_ROTATION_PRIOR: dict[str, tuple[str, ...]] = {}\n_UNUSED_MAP = {",
    ),
    (
        "E1d the specification-regime tuple is shortened",
        SRC,
        _SPEC_TUPLE,
        'SPECIFICATION_REGIMES: tuple[str, ...] = (\n    "early_expansion",\n    "mid_expansion",',
    ),
    (
        "E1e the extension-regime tuple is widened to include a specification row",
        SRC,
        _EXT_TUPLE,
        'SECTOR_PRIOR_EXTENSION_REGIMES: tuple[str, ...] = (\n    "slowdown",\n    "early_expansion",',
    ),
    # --- E2: the input field and the vocabulary refusal ------------------
    (
        "E2a the field is widened to accept any string (Section 6.9's bare-str defect)",
        SRC,
        _INPUT_REGIME_FIELD,
        "    regime_state: str = Field(",
    ),
    # --- E3: the lookup, the fallback and the container ------------------
    (
        "E3a the lookup always misses (every regime falls back)",
        SRC,
        _GET_CALL,
        "    sectors = None",
    ),
    (
        "E3b the has_prior flag is inverted",
        SRC,
        _HAS_PRIOR,
        "    has_prior = sectors is None",
    ),
    (
        "E3c the fallback label is a constant instead of the config leaf",
        SRC,
        _PUBLISHED,
        "    published: list[str] = list(sectors) if sectors is not None else ['UNKNOWN']",
    ),
    (
        "E3d the published value is the map's own tuple, not a fresh list",
        SRC,
        _PUBLISHED,
        "    published: list[str] = "
        "list(sectors) if sectors is not None else [equity_macro.no_prior_label]\n"
        "    published = sectors  # type: ignore[assignment]",
    ),
    # --- E4: the confidence ----------------------------------------------
    (
        "E4a the confidence is summed instead of multiplied (the cap stops bounding)",
        SRC,
        _CONF_PRODUCT,
        "    confidence = computed + equity_macro.reliability_value",
    ),
    (
        "E4b the computed half is dropped (a bare cap literal)",
        SRC,
        _CONF_PRODUCT,
        "    confidence = equity_macro.reliability_value",
    ),
    (
        "E4c the data-quality flag is inverted (a missing prior looks better)",
        SRC,
        _FLAGS_PRESENT,
        "            data_quality_flags_present=has_prior,",
    ),
    (
        "E4d the heuristic penalty is dropped",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "E4e the independence credit is removed",
        SRC,
        _SOURCE_INDEP,
        "            source_independence_count=0,",
    ),
    (
        "E4f the computed confidence never runs",
        SRC,
        _COMPUTED_CALL,
        "    computed = 0.5\n    _unused = compute_confidence(\n        ConfidenceInputs(",
    ),
    # --- E5: the warnings and the caveat ---------------------------------
    (
        "E5a the prior-not-rule caveat warning is removed",
        SRC,
        _CAVEAT_WARNING,
        "    warnings: list[str] = [\n        _dropped_caveat()",
    ),
    (
        "E5b the fallback disclosure warning is removed",
        SRC,
        _FALLBACK_WARNING,
        '            f"Regime {regime!r} has no prior "',
    ),
    (
        "E5c the extension-origin assumption is removed",
        SRC,
        _EXT_ASSUMPTION,
        '            f"The row for {regime!r} is a declaration. "',
    ),
    # --- E6: the published contract and the import assertion -------------
    (
        "E6a the published value is not the looked-up sectors",
        SRC,
        _VALUE_KW,
        "        value=equity_macro.no_prior_label,",
    ),
    (
        "E6b the unit is published as something else",
        SRC,
        _UNIT_KW,
        '        unit="sectors",',
    ),
    (
        "E6c the source family is claimed as market data",
        SRC,
        _SOURCE_FAMILY_KW,
        "        source_family=EvidenceSourceFamily.BLS_EMPLOYMENT_SITUATION,",
    ),
    (
        "E6d the country is a constant other than the US",
        SRC,
        _COUNTRY_KW,
        '        country="de",',
    ),
    (
        "E6e the vocabulary-agreement assertion compares against the WRONG set",
        SRC,
        _ASSERT_MAP,
        "assert set(get_args(RegimeState)) == set(SPECIFICATION_REGIMES), (",
    ),
    # --- N1-N3: the config -----------------------------------------------
    (
        "N1a the reliability accessor returns the no-prior label leaf",
        CONFIG,
        _N1_CAP_PROP,
        "        return float(self.no_prior_label_leaf.value)",
    ),
    (
        "N1b the calibration helper reports calibrated unconditionally",
        CONFIG,
        _N1_CALIBRATED_READ,
        "        return True\n\n    @property\n    def no_prior_label(self) -> str:",
    ),
    (
        "N2a the no-prior accessor returns the reliability cap",
        CONFIG,
        _N2_LABEL_PROP,
        "        return str(self.reliability_cap.value)",
    ),
    (
        "N3a the cap-range validator removed",
        CONFIG,
        _N3_CAP_VALIDATOR,
        '                f"equity_macro.reliability_cap is {self.reliability_value}. A "\n'
        "            )\n"
        "        _dead_validator_guard = True",
    ),
    (
        "N3b the empty-label validator removed",
        CONFIG,
        _N3_LABEL_VALIDATOR,
        '                f"equity_macro.no_prior_label is {self.no_prior_label!r}. It is "\n'
        "            )\n"
        "        _dead_validator_guard = True",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_equity_macro.py",
            "tests/test_infrastructure.py",
            "-q",
            "--no-header",
            # `-x` is D-057's rule, not a preference: a kill is a kill, the first
            # failing test is sufficient evidence, and an interrupted long run on
            # win32 leaves every mutant applied so far on disk (D-082).
            "-x",
            "-m",
            "not live",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138).

    **Must run BEFORE ``sweep_lifecycle``.** That helper writes a sidecar and
    installs the interrupt defence — i.e. it writes to the tree. A mode whose
    entire purpose is to be the SAFE pre-flight must not enter the path that
    mutates (O-138).

    Exit code is **0 for a clean verdict and 4 for problems** — the same 4 the
    sweep itself returns on a refusal.
    """
    originals = {p: p.read_text(encoding="utf-8") for p in (SRC, CONFIG) if p.exists()}
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)", flush=True)
    if problems:
        print(format_problems(problems))
        print()
        print("ANCHORS UNSOUND: fix the anchors above before sweeping. A sweep that")
        print("cannot prove it mutates the site it names certifies nothing.")
        return 4
    print()
    print("Anchors sound: every mutation resolves to exactly one site. No mutation")
    print("was applied and no sidecar was written (O-138 — this mode stops here).")
    return 0


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle writes.
    if check_only_requested():
        return _check_targets_only()

    # The whole interrupt defence in one call (O-103): heal any sidecar a killed
    # previous run left behind, write the pristine text to a sidecar BEFORE the
    # first mutation, and consume it on the way out.
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
    print(
        f"MUTATION SWEEP — equity_macro (sector_rotation_prior + "
        f"EquityMacroSettings): {killed}/{total} killed",
        flush=True,
    )
    print("=" * 74)
    if survivors:
        print("SURVIVORS (each is a weak test, an inert mutation, or a broken one):")
        for name, reason in survivors:
            print(f"  [{reason}] {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing (D-051). CANARY1 is REQUIRED to be killed, not tolerated.
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
