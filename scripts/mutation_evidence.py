"""Mutation sweep for Module 13's evidence-family functions.

Each mutation reverts one correction in ``models/evidence.py`` to a plausible
alternative, and each must be killed:

* **M1** makes the count count RESULTS instead of FAMILIES — the central defect
  the module exists to prevent, and the one that looks most reasonable.
* **M2** silently drops untagged results instead of reporting them, or assumes
  them independent.
* **M3** drops the published tally components, so the count loses its
  denominator or its auditability.
* **M4** reverts the tag to a warnings string, which is §15.19-D's own
  mechanism and therefore the most important mutation in the file.
* **M5** drops a disclosure.
* **M6** weakens the tag contract — mutation, or a silent re-tag overwrite.
* **M7** restores the specification's bare-``int`` return.
* **C1** hardcodes a config-derived value.

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

from _sweep_gate import (
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)

SRC = Path("src/macro_engine/models/evidence.py")
CONTRACTS = Path("src/macro_engine/models/contracts.py")
ENUM = Path("src/macro_engine/models/evidence_family.py")

# --- reusable pattern fragments -------------------------------------------

_COUNT_LOOP = """    for r in tagged_results:
        family = r.source_family
        if family is None:
            continue
        if family.value in seen:
            duplicates += 1
        else:
            seen.add(family.value)"""

_COUNT_RESULTS = """    for r in tagged_results:
        duplicates += 1"""

_UNTAGGED_LINE = "    untagged = sum(1 for r in tagged_results if r.source_family is None)"
_UNTAGGED_ZERO = "    untagged = 0"

_DISTINCT_LINE = "    distinct = len(seen)"
_DISTINCT_TOTAL = "    distinct = len(tagged_results)"

_TALLY_CONSTRUCT = """        value=EvidenceTally(
            distinct_families=distinct,
            families=families,
            tagged=len(tagged_results) - untagged,
            untagged=untagged,
            duplicate_results=duplicates,
        ).model_dump(),"""

_TALLY_BARE = """        value=distinct,"""

_TALLY_NO_FAMILIES = """        value=EvidenceTally(
            distinct_families=distinct,
            families=[],
            tagged=len(tagged_results) - untagged,
            untagged=untagged,
            duplicate_results=duplicates,
        ).model_dump(),"""

_TALLY_NO_UNTAGGED = """        value=EvidenceTally(
            distinct_families=distinct,
            families=families,
            tagged=len(tagged_results),
            untagged=untagged,
            duplicate_results=duplicates,
        ).model_dump(),"""

_TALLY_NO_DUPES = """        value=EvidenceTally(
            distinct_families=distinct,
            families=families,
            tagged=len(tagged_results) - untagged,
            untagged=untagged,
            duplicate_results=0,
        ).model_dump(),"""

_TYPED_FIELD = """    source_family: EvidenceSourceFamily | None = Field(
        default=None,"""
_NO_FIELD = """    source_family: str | None = Field(
        default=None,"""

_REEXPORT_LINE = "from macro_engine.models.evidence_family import EvidenceSourceFamily"
_REEXPORT_LOCAL = (
    "class EvidenceSourceFamily(str, Enum):  # type: ignore[no-redef]\n"
    '    """A forked copy — the defect under test."""\n\n'
    '    BLS_CPI = "bls_cpi"'
)

_REFUSE_RETAG = """    if existing is not None and existing != family:
        raise ValueError("""
_SILENT_RETAG = """    if False:
        raise ValueError("""

_COPY_LINE = '    tagged = model_result.model_copy(update={"source_family": family})'
_MUTATE_LINE = "    tagged = model_result\n    tagged.source_family = family"

_EMPTY_WARNING = """        warnings.append(
            "NO RESULTS SUPPLIED: the family count is zero because the list was "
            "empty, which is not the same as a measured absence of independence."
        )"""
_EMPTY_WARNING_DROPPED = "        pass"

_UNTAGGED_WARNING = """    if untagged:"""
_UNTAGGED_WARNING_DROPPED = """    if False:"""

_ONE_FAMILY_WARNING = """    if distinct == 1 and len(tagged_results) > 1 and not untagged:"""
_ONE_FAMILY_WARNING_DROPPED = """    if False:"""

_CONF_INPUTS = """        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )"""
_CONF_CIRCULAR = """        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=distinct,
        )"""

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
        '__all__ = [\n    "EvidenceSourceFamily",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the count counts the wrong thing ------------------------------
    (
        "M1a the count counts RESULTS instead of distinct FAMILIES",
        SRC,
        _COUNT_LOOP,
        _COUNT_RESULTS,
    ),
    (
        "M1b distinct set to the raw result count (redundancy ignored)",
        SRC,
        _DISTINCT_LINE,
        _DISTINCT_TOTAL,
    ),
    # --- M2: untagged handling --------------------------------------------
    (
        "M2a untagged results silently reported as zero",
        SRC,
        _UNTAGGED_LINE,
        _UNTAGGED_ZERO,
    ),
    (
        "M2b untagged results assumed independent (counted as families)",
        SRC,
        _COUNT_LOOP,
        """    for r in tagged_results:
        family = r.source_family
        if family is None:
            seen.add(f"untagged_{id(r)}")
            continue
        if family.value in seen:
            duplicates += 1
        else:
            seen.add(family.value)""",
    ),
    # --- M3: the published tally ------------------------------------------
    (
        "M3a the tally replaced by a bare int (Section 22.9 violation)",
        SRC,
        _TALLY_CONSTRUCT,
        _TALLY_BARE,
    ),
    (
        "M3b the family membership list dropped from the tally",
        SRC,
        _TALLY_CONSTRUCT,
        _TALLY_NO_FAMILIES,
    ),
    (
        "M3c the tagged denominator wrong (untagged folded in)",
        SRC,
        _TALLY_CONSTRUCT,
        _TALLY_NO_UNTAGGED,
    ),
    (
        "M3d the collapsed-vote count dropped (redundancy invisible)",
        SRC,
        _TALLY_CONSTRUCT,
        _TALLY_NO_DUPES,
    ),
    # --- M4: the tag channel (§15.19-D's own mechanism) --------------------
    (
        "M4a the typed source_family field becomes a plain untyped string",
        CONTRACTS,
        _TYPED_FIELD,
        _NO_FIELD,
    ),
    (
        "M4b the enum loses its str base (values stop round-tripping from JSON)",
        ENUM,
        "class EvidenceSourceFamily(str, Enum):",
        "class EvidenceSourceFamily(Enum):",
    ),
    # --- M5: disclosures ---------------------------------------------------
    (
        "M5a the empty-list disclosure dropped",
        SRC,
        _EMPTY_WARNING,
        _EMPTY_WARNING_DROPPED,
    ),
    (
        "M5b the untagged-results disclosure dropped",
        SRC,
        _UNTAGGED_WARNING,
        _UNTAGGED_WARNING_DROPPED,
    ),
    (
        "M5c the one-family-false-convergence disclosure dropped",
        SRC,
        _ONE_FAMILY_WARNING,
        _ONE_FAMILY_WARNING_DROPPED,
    ),
    # --- M6: the tag contract ---------------------------------------------
    (
        "M6a the conflicting re-tag refusal removed (silent overwrite)",
        SRC,
        _REFUSE_RETAG,
        _SILENT_RETAG,
    ),
    (
        "M6b tagging mutates its argument instead of copying",
        SRC,
        _COPY_LINE,
        _MUTATE_LINE,
    ),
    # --- M7: the confidence source ---------------------------------------
    (
        "M7a the census credits itself for the families it found (circular)",
        SRC,
        _CONF_INPUTS,
        _CONF_CIRCULAR,
    ),
    (
        "M7b the heuristic penalty dropped from the census confidence",
        SRC,
        """        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )""",
        """        ConfidenceInputs(
            is_heuristic_not_calibrated=False,
            source_independence_count=0,
        )""",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_evidence.py",
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
    # The whole interrupt defence in one call (O-103): heal any sidecar a killed
    # previous run left behind, write the healed text to a sidecar BEFORE the
    # first mutation, and consume it on the way out. On win32 no Python signal
    # handler runs for SIGTERM/SIGINT, so the sidecar -- not a handler -- is the
    # defence that actually has reach here.
    with sweep_lifecycle([SRC, CONTRACTS, ENUM]) as originals:
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

    leftover = _applied_mutations({p: p.read_text(encoding="utf-8") for p in originals})
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

    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
