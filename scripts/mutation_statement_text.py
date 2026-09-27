"""Mutation sweep for Section 20.4's ``statement_text_diff`` — the model and its
config block.

**One function, one sweep** (D-108/D-118's shape). The labels are partitioned by
concern, not by file, because this increment adds a model function and a config
class but **no new data-layer client** (the function reads no market data — its
only inputs are two supplied texts):

* **``M1``-``M3``** are the marker MATCHING in ``_count_marker_occurrences`` —
  the case-folding, the per-occurrence count, and the empty-result contract.
* **``D1``-``D5``** are the DIFF arithmetic — entering/leaving, the per-occurrence
  net, the tilt formula, and the direction naming (including the tie branch).
* **``C1``-``C3``** are the CONFIDENCE — the product, the cap, and the two
  factors that feed it.
* **``R1``-``R2``** are the REFUSALS — the blank-text guard and the token floor.
* **``W1``-``W3``** are the DISCLOSURES and the published contract.
* **``N1``-``N3``** are ``config.py``'s ``StatementTextSettings`` — the accessors
  and the validator guards.

Why this module is swept at all
--------------------------------
``statement_text_diff`` is a TEXT DIFF, and a text diff's defects are silent by
construction: every comparison returns a well-formed result, and a wrong answer
looks exactly like a right one. The decisions a future edit is most likely to
"simplify" are exactly the ones this increment exists to protect:

* **the signed, bounded tilt** — replacing the ratio with a raw count would make
  a long statement's tilt incomparable to a short one's;
* **the exhaustive direction vocabulary** — the tie branch
  (``MIXED_BOTH_DIRECTIONS_NET_FLAT``) is reachable only when two equal-and-
  opposite moves cancel, and collapsing it into the ``else`` would label a tie
  as a one-sided tilt;
* **the two refusals** — a blank statement or a sub-floor one is a partial input
  (D-054), not a statement that says nothing;
* **the confidence cap** — which replaced the §22.8 base rate that would have
  implied far more certainty than a keyword diff earns.

⚠️ **Every ``old`` string below was measured at exactly one occurrence with
``str.count()`` before being written**, and the measurement (not the author's
belief about the bytes) is what this file records. The FIRST measurement pass
found two anchors that occur TWICE — ``confidence = compute_confidence(`` and
``source_independence_count=0,`` both also appear in ``qe_qt_stance`` — and each
was WIDENED with a distinguishing neighbour, never deleted (D-109).

**⚠️ ``M1a`` and the canary are the two mutations that must NOT survive.**
``M1a`` removes the case-folding, which silently misses every marker the Fed
capitalizes differently from the list; the canary is a syntax error, and if it
survives the selection no longer reaches the module and no kill below is evidence
about the suite (O-72, D-051) — the sweep REFUSES TO CERTIFY rather than
reporting health.
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

SRC = Path("src/macro_engine/models/policy_rules.py")
CONFIG = Path("src/macro_engine/config.py")

# --------------------------------------------------------------------------
# M1-M3: the marker matching.
# --------------------------------------------------------------------------

# The case-fold AND the whitespace collapse. Removing the `.lower()` makes every
# marker that the Fed capitalizes ("the Committee judges that ... is prepared to
# raise") miss the lower-cased vocabulary — a silent zero on every diff.
_FOLDED = '    folded = " ".join(text.lower().split())'
# The per-occurrence count. Replacing `.count()` with a membership test (`in`)
# makes a doubled-then-single phrase read as UNCHANGED.
_COUNT_CALL = "        occurrences = folded.count(marker)"
# The count ARITHMETIC. Doubling it changes the published `hawkish_net` /
# `dovish_net` / `net_tilt`, so the count is what feeds the diff rather than a
# presence flag. (The "only non-zero markers" guard, `if occurrences:`, is NOT
# mutated: it only decides whether a zero enters an internal dict that is then
# compared with `>`/`<` and summed — both are zero-insensitive, so no observable
# field changes and the mutation is EQUIVALENT, which is not a coverage hole.)

# --------------------------------------------------------------------------
# D1-D5: the diff arithmetic and the direction naming.
# --------------------------------------------------------------------------

# The entering predicate. Flipping `>` to `>=` makes a marker present in both
# texts count as ENTERED.
_ENTERED = "    entered = [m for m in ordered if current_counts.get(m, 0) > prior_counts.get(m, 0)]"
# The leaving predicate.
_LEFT = "    left = [m for m in ordered if current_counts.get(m, 0) < prior_counts.get(m, 0)]"
# The union key set. Using only the prior's keys misses a marker present ONLY in
# the current text — i.e. every pure addition.
_NET_KEYS = "    keys = set(prior_counts) | set(current_counts)"
# The tilt. The signed, bounded ratio. Replacing it with the raw numerator makes
# tilt unbounded and length-dependent.
_TILT = "        tilt = (hawkish_net - dovish_net) / (abs(hawkish_net) + abs(dovish_net))"
# The tie branch. Collapsing it (deleting it) sends an exact cancellation into
# the `else` — a confident one-sided tilt on a tie.
_TIE = '            direction = "MIXED_BOTH_DIRECTIONS_NET_FLAT"'
# The direction reduction's two legs. Each leg keeps a side's REMOVAL on the
# correct side of the ledger: a hawkish phrase LEAVING is a move in the dovish
# direction (so `dovish_ward` reads `hawkish_net < 0`), and a dovish phrase
# LEAVING is hawkish-ward (so `hawkish_ward` reads `dovish_net < 0`). Dropping
# either leg re-creates the one genuine MODEL defect this increment found: a
# hawkish removal labelled MORE_HAWKISH.
_HAWKISH_WARD = "        hawkish_ward = hawkish_net > 0 or dovish_net < 0"
_DOVISH_WARD = "        dovish_ward = hawkish_net < 0 or dovish_net > 0"

# --------------------------------------------------------------------------
# C1-C3: the confidence.
# --------------------------------------------------------------------------

# ⚠️ WIDENED: `confidence = compute_confidence(` occurs TWICE (also in
# `qe_qt_stance`). The anchor carries the unique first factor line below it.
_CONF_BLOCK = (
    "    confidence = compute_confidence(\n"
    "        ConfidenceInputs(\n"
    "            # Both vocabularies are uncalibrated_illustrative: the marker list is\n"
    "            # a starting vocabulary, not a measured one.\n"
    "            is_heuristic_not_calibrated=not settings.vocabularies_are_calibrated,"
)
# The heuristic factor. Hardcoding it False claims the vocabulary is calibrated.
_HEUR_FACTOR = "            is_heuristic_not_calibrated=not settings.vocabularies_are_calibrated,"
# The cap. Dropping it lets the §22.8 base rate publish far more certainty than a
# keyword diff earns.
_CAP = "    confidence = round(min(confidence, settings.confidence_cap), 3)"

# --------------------------------------------------------------------------
# R1-R2: the refusals.
# --------------------------------------------------------------------------

# The blank-text guard (input model). Removing it makes an empty statement a
# valid input that reports every marker as newly entered on one side.
_BLANK_GUARD = "            if not getattr(self, name).strip():"
# The token floor (the function). Removing it lets a truncated statement diff as
# if it were whole (D-054).
_FLOOR_GUARD = "        if len(text.split()) < settings.min_tokens:"

# --------------------------------------------------------------------------
# W1-W3: the disclosures and the published contract.
# --------------------------------------------------------------------------

# The weak-evidence disclosure, the model's central claim about itself.
_WEAK_DISCLOSURE = '        "A marker diff is WEAK evidence: the Committee writes language that "'
# The illustrative-vocabulary disclosure.
_VOCAB_DISCLOSURE = '        f"The marker vocabulary is uncalibrated_illustrative: these are the "'
# The published model name. A drift here breaks every consumer keyed on it.
_MODEL_NAME = '        model_name="statement_text_diff",'

# --------------------------------------------------------------------------
# N1-N3: the config accessors and validators.
# --------------------------------------------------------------------------

# The hawkish accessor's lower-casing. Dropping it publishes the markers in the
# stored case, which the (case-folded) matcher would then never match.
_HAWK_ACCESSOR = "        return tuple(str(m).lower() for m in self.hawkish_markers_value.value)"
# The disjointness guard. Removing it lets a phrase sit on both sides, where it
# cancels itself and the net tilt misses the change entirely.
_DISJOINT_GUARD = "        overlap = set(hawkish) & set(dovish)"
# The AND of the two vocabularies' calibration (the D-124 shape). Weakening it to
# an OR makes one illustrative side read as calibrated.
_VOCAB_AND = (
    "        return (\n"
    "            self.hawkish_markers_value.is_trustworthy and self.dovish_markers_value.is_trustworthy\n"
    "        )"
)

_MUTATIONS: list[tuple[str, Path, str, str]] = [
    # --- the canary (O-72) -------------------------------------------------
    (
        "CANARY1 the module literal is replaced with a syntax error (CONTROL)",
        SRC,
        "_BP_PER_PP = 100.0",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1-M3: the marker matching ---------------------------------------
    (
        "M1a the case-folding (and whitespace collapse) is dropped",
        SRC,
        _FOLDED,
        "    folded = text",
    ),
    (
        "M1b the count is replaced by a membership test (devig)",
        SRC,
        _COUNT_CALL,
        "        occurrences = 1 if marker in folded else 0",
    ),
    (
        "M2a the occurrence count is doubled (wrong multiplicity in the diff)",
        SRC,
        _COUNT_CALL,
        "        occurrences = 2 * folded.count(marker)",
    ),
    (
        "M2b the case-folding is dropped but the collapse kept",
        SRC,
        _FOLDED,
        '    folded = " ".join(text.split())',
    ),
    # --- D1-D5: the diff arithmetic and the direction naming ---------------
    (
        "D1a entering uses >= so a common marker counts as ENTERED",
        SRC,
        _ENTERED,
        "    entered = [m for m in ordered if current_counts.get(m, 0) >= prior_counts.get(m, 0)]",
    ),
    (
        "D1b leaving uses <= so a common marker counts as LEFT",
        SRC,
        _LEFT,
        "    left = [m for m in ordered if current_counts.get(m, 0) <= prior_counts.get(m, 0)]",
    ),
    (
        "D2a the net key set uses only the PRIOR text (misses pure additions)",
        SRC,
        _NET_KEYS,
        "    keys = set(prior_counts)",
    ),
    (
        "D2b the leaving predicate is dropped (removals invisible)",
        SRC,
        _LEFT,
        "    left = []",
    ),
    (
        "D3a the tilt is the raw numerator (unbounded, length-dependent)",
        SRC,
        _TILT,
        "        tilt = float(hawkish_net - dovish_net)",
    ),
    (
        "D3b the tilt sign is inverted (hawkish reads as dovish)",
        SRC,
        _TILT,
        "        tilt = (dovish_net - hawkish_net) / (abs(hawkish_net) + abs(dovish_net))",
    ),
    (
        "D4a the exact-cancellation tie branch is collapsed into the else",
        SRC,
        _TIE,
        '            direction = "DOVISH_TILT_WITH_HAWKISH_REMOVALS"',
    ),
    (
        "D4b MORE_HAWKISH and MORE_DOVISH are swapped",
        SRC,
        '            direction = "MORE_HAWKISH"',
        '            direction = "MORE_DOVISH"',
    ),
    (
        "D5a the UNCHANGED branch is dropped, so a no-move statement is tilted",
        SRC,
        '        direction: StatementDiffDirection = "UNCHANGED"',
        '        direction: StatementDiffDirection = "MORE_HAWKISH"',
    ),
    (
        "D6a the dovish-ward leg drops 'a hawkish removal is dovish-ward'",
        SRC,
        _DOVISH_WARD,
        "        dovish_ward = dovish_net > 0",
    ),
    (
        "D6b the hawkish-ward leg drops 'a dovish removal is hawkish-ward'",
        SRC,
        _HAWKISH_WARD,
        "        hawkish_ward = hawkish_net > 0",
    ),
    # --- C1-C3: the confidence ---------------------------------------------
    (
        "C1a the confidence is hardcoded (bypasses the §22.8 product)",
        SRC,
        _CONF_BLOCK,
        "    confidence = 0.35\n"
        "    _dead_conf = compute_confidence(\n"
        "        ConfidenceInputs(\n"
        "            # Both vocabularies are uncalibrated_illustrative: the marker list is\n"
        "            # a starting vocabulary, not a measured one.\n"
        "            is_heuristic_not_calibrated=not settings.vocabularies_are_calibrated,",
    ),
    (
        "C1b the heuristic factor is hardcoded False (vocabulary claimed calibrated)",
        SRC,
        _HEUR_FACTOR,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "C2a the cap is dropped (base rate published uncapped)",
        SRC,
        _CAP,
        "    confidence = round(confidence, 3)",
    ),
    (
        "C2b the cap is applied before the round but with a hardcoded ceiling",
        SRC,
        _CAP,
        "    confidence = round(min(confidence, 0.99), 3)",
    ),
    # --- R1-R2: the refusals ----------------------------------------------
    (
        "R1a the blank-text guard is removed (empty statement accepted)",
        SRC,
        _BLANK_GUARD,
        "            if False:",
    ),
    (
        "R1b the blank-text guard checks only the current text",
        SRC,
        _BLANK_GUARD,
        '            if name != "current_text" and not getattr(self, name).strip():',
    ),
    (
        "R2a the token floor is removed (a truncated statement diffs as whole)",
        SRC,
        _FLOOR_GUARD,
        "        if False:",
    ),
    # --- W1-W3: the disclosures and the published contract ----------------
    (
        "W1a the weak-evidence disclosure is dropped",
        SRC,
        _WEAK_DISCLOSURE,
        '        "A marker diff is evidence: the Committee writes language that "',
    ),
    (
        "W2a the illustrative-vocabulary disclosure is dropped",
        SRC,
        _VOCAB_DISCLOSURE,
        '        f"The marker vocabulary is illustrative: these are the "',
    ),
    (
        "W3a the published model name drifts",
        SRC,
        _MODEL_NAME,
        '        model_name="statement_diff",',
    ),
    (
        "W3b the net tilt is dropped from the published value",
        SRC,
        '            "net_tilt": round(tilt, 4),',
        '            "tilt": round(tilt, 4),',
    ),
    # --- N1-N3: the config accessors and validators ------------------------
    (
        "N1a the hawkish accessor drops the lower-casing",
        CONFIG,
        _HAWK_ACCESSOR,
        "        return tuple(str(m) for m in self.hawkish_markers_value.value)",
    ),
    (
        "N2a the disjointness guard is removed (overlapping vocabulary)",
        CONFIG,
        _DISJOINT_GUARD,
        "        overlap = set()",
    ),
    (
        "N3a the vocabulary-calibration flag ORs its two legs",
        CONFIG,
        _VOCAB_AND,
        "        return (\n"
        "            self.hawkish_markers_value.is_trustworthy\n"
        "            or self.dovish_markers_value.is_trustworthy\n"
        "        )",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_policy_rules.py",
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


def _sweep() -> int:
    with sweep_lifecycle([SRC, CONFIG]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    # The interrupt defence and the heal-from-sidecar step both live in
    # `sweep_lifecycle`, which the caller has already entered: `originals` is the
    # HEALED text. A hand-rolled "did a mutation survive on disk" pass is not
    # only redundant here, it is hazardous — a mutation whose `new` string is a
    # substring of legitimate code (D2a's is a prefix of the real
    # `_net_marker_change` line) reads as a leftover and gets "repaired",
    # mutating a clean tree. The sidecar is the authority; nothing local should
    # second-guess it.
    problems = check_targets(originals, _MUTATIONS)
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)", flush=True)
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep that cannot")
        print("prove it mutates the site it names certifies nothing (D-048, O-29).")
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
        f"MUTATION SWEEP — statement_text (statement_text_diff + "
        f"StatementTextSettings): {killed}/{total} killed",
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


def main() -> int:
    if check_only_requested():
        return _check_targets_only()
    return _sweep()


if __name__ == "__main__":
    sys.exit(main())
