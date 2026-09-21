"""Mutation sweep for Module 8.2's ``auction_demand_signal``.

The suite exists to prove that each D-036 correction is load-bearing rather
than decorative. Every mutation reverts one to a plausible alternative, and
each must be killed:

* **M1** mis-orders or hardcodes the verdict logic, so the published verdict
  stops following from the published flags.
* **M2** restores Section 20.8's literal thresholds in place of the config
  reads, making the config entries decorative.
* **M3** inverts a comparison sign. This is the D-034 failure mode: a
  sign-inverted term produces a perfectly plausible verdict measuring the
  opposite of what it claims.
* **M4** drops a disclosure. The manual-entry warning, the sign-convention
  warning and the base-rate warning each exist because the probe found a way
  for a reader to be misled; a mutation removes one and the suite must notice.
* **M5** drops a published component, breaking the D-009 cross-field identity
  that makes the verdict recomputable from its own output.
* **M6** weakens the input contract, so a non-positive comparison base or a
  misspelled field is accepted instead of refused.
* **M7** restores the specification's hardcoded ``confidence=0.6``, which
  Section 22.8 forbids.
* **C1** swaps or hardcodes the config accessors, including the
  field-shadows-its-own-property trap this project has hit five times.

A survivor is one of three things (D-031): a weak test, an **inert** mutation,
or a **broken** mutation. The runner reports a pattern-miss separately from a
survival so the two cannot be confused.

**This runner heals before it measures.** A sweep killed mid-run leaves the
mutated file on disk, and a naive re-run would adopt it as the baseline and
bake the corruption in permanently — which is exactly what a power loss did to
``mutation_gdp_nowcast.py`` on 2026-09-17. ``repair_leftover_mutations()``
inverts any applied mutation on startup, the sweep runs under ``try/finally``,
and a post-sweep check refuses to report success while anything is still
applied.
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

SRC = Path("src/macro_engine/models/auctions.py")
CONFIG = Path("src/macro_engine/config.py")

# ---------------------------------------------------------------------------
# Named fragments. Each must match the source byte-for-byte, including
# indentation and trailing commas — a fragment that only approximately matches
# is silently not applied, and the sweep would report a false survivor.
# ---------------------------------------------------------------------------

# --- M1: the verdict logic -------------------------------------------------
_WEAK_COMPUTE = (
    "    weak_bid_to_cover = inputs.bid_to_cover < (\n"
    "        inputs.bid_to_cover_trailing_avg * settings.weak_bid_to_cover_ratio\n"
    "    )"
)
_VERDICT_BRANCHES = (
    "    if weak_bid_to_cover and tailed:\n"
    '        verdict = "WEAK_AUCTION_term_premium_pressure"\n'
    "    elif not weak_bid_to_cover and not tailed:\n"
    '        verdict = "STRONG_AUCTION"\n'
    "    else:\n"
    '        verdict = "MIXED"'
)

# --- M2: the thresholds come from config -----------------------------------
_FADE_COMPUTE = (
    "    foreign_fading = inputs.indirect_bidder_pct < (\n"
    "        inputs.indirect_bidder_trailing_avg - settings.indirect_fade_threshold_pp\n"
    "    )"
)

# --- M3: the sign convention ----------------------------------------------
_TAIL_COMPUTE = "    tailed = inputs.stop_through_bp < settings.tail_boundary_bp"

# --- M4: the disclosures ---------------------------------------------------
_PERSISTENCE_WARNING = (
    '        "A single tailing auction can be a temporary liquidity artifact — require "\n'
    '        "persistence before concluding structural demand shift.",'
)
_MANUAL_WARNING = (
    '        "stop_through_bp is MANUAL ENTRY, not sourced: no route in this build "\n'
    '        "publishes the when-issued yield a tail is measured against (D-036). The "\n'
    '        "tailed flag is only as good as the operator\'s benchmark.",'
)
_SIGN_WARNING = (
    '        f"Sign convention: stop_through_bp is (expected - clearing), so a value "\n'
    '        f"below {settings.tail_boundary_bp:.1f}bp is a TAIL. Read the published "\n'
    "        f\"'tailed' flag rather than the raw number.\","
)
_BASE_RATE_WARNING = (
    '        f"Both flags fire often. Over {settings.base_rates.auctions_measured} live "\n'
    "        f\"10-Year auctions, 'weak bid-to-cover' fired in \"\n"
    '        f"{settings.base_rates.weak_bid_to_cover_rate:.1%} of them and \'foreign "\n'
    '        f"demand fading\' in {settings.base_rates.foreign_fading_rate:.1%}. A flag "\n'
    '        f"that fires this often is weak evidence on its own.",'
)
_STRONG_QUALIFIER = (
    "        warnings.append(\n"
    '            "The verdict is STRONG on price (bid-to-cover and tail) while "\n'
    '            "indirect demand is fading. The verdict does not incorporate the "\n'
    "            \"indirect share, so 'STRONG_AUCTION' here means the auction cleared \"\n"
    '            "well, NOT that demand composition is healthy."\n'
    "        )"
)

# --- M5: the published components (the cross-field identity) --------------
_WEAK_KEY = '            "weak_bid_to_cover": weak_bid_to_cover,'
_TAIL_KEY = '            "tailed": tailed,'
_FADING_KEY = '            "foreign_demand_fading": foreign_fading,'
_MANUAL_KEY = '            "stop_through_is_manual_entry": True,'
_RAW_BTC_KEY = '            "bid_to_cover": round(inputs.bid_to_cover, 4),'

# --- M6: the input contract ------------------------------------------------
_EXTRA_FORBID = '    model_config = ConfigDict(extra="forbid")\n\n    bid_to_cover: float = Field('
_TRAILING_BTC_FIELD = "    bid_to_cover_trailing_avg: float = Field(\n        gt=0.0,"
_TRAILING_IND_FIELD = "    indirect_bidder_trailing_avg: float = Field(\n        gt=0.0,"
_IND_BOUNDS = "    indirect_bidder_pct: float = Field(\n        ge=0.0,\n        le=100.0,"

# --- M7: confidence --------------------------------------------------------
_HEURISTIC_FACTOR = "            is_heuristic_not_calibrated=not _thresholds_calibrated(),"

# --- config accessors ------------------------------------------------------
_WINDOW_PROP = "        return int(self.trailing_window_auctions_value.value)"
_WEAK_RATIO_PROP = "        return float(self.weak_bid_to_cover_ratio_value.value)"
_FADE_PROP = "        return float(self.indirect_fade_threshold_pp_value.value)"
_TAIL_PROP = "        return float(self.tail_boundary_bp_value.value)"
_MEASURED_PROP = "        return int(self.auctions_measured_value.value)"
_WEAK_RATE_PROP = "        return float(self.weak_bid_to_cover_rate_value.value)"
_FADING_RATE_PROP = "        return float(self.foreign_fading_rate_value.value)"

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
        '__all__ = [\n    "AuctionInputs",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the verdict logic --------------------------------------------
    (
        "M1a the WEAK verdict requires a tail too (mis-ordered branches)",
        SRC,
        _VERDICT_BRANCHES,
        "    if weak_bid_to_cover and not tailed:\n"
        '        verdict = "WEAK_AUCTION_term_premium_pressure"\n'
        "    elif not weak_bid_to_cover and tailed:\n"
        '        verdict = "STRONG_AUCTION"\n'
        "    else:\n"
        '        verdict = "MIXED"',
    ),
    (
        "M1b the verdict hardcoded to STRONG regardless of the flags",
        SRC,
        _VERDICT_BRANCHES,
        '    verdict = "STRONG_AUCTION"',
    ),
    (
        "M1c the MIXED fallback removed so every auction is weak or strong",
        SRC,
        _VERDICT_BRANCHES,
        "    if weak_bid_to_cover and tailed:\n"
        '        verdict = "WEAK_AUCTION_term_premium_pressure"\n'
        "    else:\n"
        '        verdict = "STRONG_AUCTION"',
    ),
    # --- M2: thresholds from config ---------------------------------------
    (
        "M2a the fade threshold restored as the literal 3.0pp",
        SRC,
        _FADE_COMPUTE,
        "    foreign_fading = inputs.indirect_bidder_pct < (\n"
        "        inputs.indirect_bidder_trailing_avg - 3.0\n"
        "    )",
    ),
    (
        "M2b the weak bid-to-cover ratio restored as the literal 0.95",
        SRC,
        _WEAK_COMPUTE,
        "    weak_bid_to_cover = inputs.bid_to_cover < (\n"
        "        inputs.bid_to_cover_trailing_avg * 0.95\n"
        "    )",
    ),
    (
        "M2c the tail boundary restored as the literal 0.0",
        SRC,
        _TAIL_COMPUTE,
        "    tailed = inputs.stop_through_bp < 0.0",
    ),
    # --- M3: the sign convention ------------------------------------------
    (
        "M3a the tail comparison inverted (a positive stop-through is a tail)",
        SRC,
        _TAIL_COMPUTE,
        "    tailed = inputs.stop_through_bp > settings.tail_boundary_bp",
    ),
    (
        "M3b the fade comparison inverted (a share ABOVE its average is fading)",
        SRC,
        _FADE_COMPUTE,
        "    foreign_fading = inputs.indirect_bidder_pct > (\n"
        "        inputs.indirect_bidder_trailing_avg - settings.indirect_fade_threshold_pp\n"
        "    )",
    ),
    (
        "M3c the weak comparison inverted (a bid-to-cover ABOVE its average is weak)",
        SRC,
        _WEAK_COMPUTE,
        "    weak_bid_to_cover = inputs.bid_to_cover > (\n"
        "        inputs.bid_to_cover_trailing_avg * settings.weak_bid_to_cover_ratio\n"
        "    )",
    ),
    # --- M4: the disclosures ----------------------------------------------
    (
        "M4a the persistence warning dropped (Section 20.8's own caveat)",
        SRC,
        _PERSISTENCE_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4b the manual-entry disclosure dropped (a reader cannot tell what was typed)",
        SRC,
        _MANUAL_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4c the sign-convention warning dropped",
        SRC,
        _SIGN_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4d the base-rate warning dropped (D-029 disclosure)",
        SRC,
        _BASE_RATE_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4e the STRONG-while-fading qualifier dropped",
        SRC,
        _STRONG_QUALIFIER,
        "        pass",
    ),
    # --- M5: the published components -------------------------------------
    (
        "M5a the weak_bid_to_cover flag dropped from the published value",
        SRC,
        _WEAK_KEY,
        '            "unused_weak_placeholder": weak_bid_to_cover,',
    ),
    (
        "M5b the tailed flag dropped from the published value",
        SRC,
        _TAIL_KEY,
        '            "unused_tail_placeholder": tailed,',
    ),
    (
        "M5c the foreign_demand_fading flag dropped from the published value",
        SRC,
        _FADING_KEY,
        '            "unused_fading_placeholder": foreign_demand_fading,',
    ),
    (
        "M5d the manual-entry flag dropped from the published value",
        SRC,
        _MANUAL_KEY,
        '            "stop_through_is_manual_entry": False,',
    ),
    (
        "M5e the raw bid_to_cover dropped (the inputs stop being republished)",
        SRC,
        _RAW_BTC_KEY,
        '            "bid_to_cover": 0.0,',
    ),
    # --- M6: the input contract -------------------------------------------
    (
        "M6a extra='forbid' removed from the input model",
        SRC,
        _EXTRA_FORBID,
        "    bid_to_cover: float = Field(",
    ),
    (
        "M6b the bid-to-cover average guard weakened to allow zero",
        SRC,
        _TRAILING_BTC_FIELD,
        "    bid_to_cover_trailing_avg: float = Field(\n        ge=0.0,",
    ),
    (
        "M6c the indirect average guard weakened to allow zero",
        SRC,
        _TRAILING_IND_FIELD,
        "    indirect_bidder_trailing_avg: float = Field(\n        ge=0.0,",
    ),
    (
        "M6d the upper bound on the indirect share removed",
        SRC,
        _IND_BOUNDS,
        "    indirect_bidder_pct: float = Field(\n        ge=0.0,",
    ),
    # --- M7: confidence ----------------------------------------------------
    (
        "M7a the heuristic factor hardcoded False (the penalty stops applying)",
        SRC,
        _HEURISTIC_FACTOR,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M7b confidence hardcoded to the specification's 0.6",
        SRC,
        "        confidence=confidence,",
        "        confidence=0.6,",
    ),
    # --- config accessors --------------------------------------------------
    (
        "C1a trailing_window_auctions returns a hardcoded value",
        CONFIG,
        _WINDOW_PROP,
        "        return 3",
    ),
    (
        "C1b the weak ratio property returns the fade threshold (swapped)",
        CONFIG,
        _WEAK_RATIO_PROP,
        "        return float(self.indirect_fade_threshold_pp_value.value)",
    ),
    (
        "C1c the fade threshold property returns the weak ratio (swapped)",
        CONFIG,
        _FADE_PROP,
        "        return float(self.weak_bid_to_cover_ratio_value.value)",
    ),
    (
        "C1d the tail boundary property returns a hardcoded non-zero",
        CONFIG,
        _TAIL_PROP,
        "        return 0.5",
    ),
    (
        "C1e auctions_measured returns a hardcoded 0",
        CONFIG,
        _MEASURED_PROP,
        "        return 0",
    ),
    (
        "C1f the weak rate property reads the fading rate (swapped)",
        CONFIG,
        _WEAK_RATE_PROP,
        "        return float(self.foreign_fading_rate_value.value)",
    ),
    (
        "C1g the fading rate property reads the weak rate (swapped)",
        CONFIG,
        _FADING_RATE_PROP,
        "        return float(self.weak_bid_to_cover_rate_value.value)",
    ),
]


def run_tests() -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_auctions.py",
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

    A mutation is applied only when its ``old`` text is **absent** and its
    ``new`` text is **present**. Testing for ``new`` alone gives false
    positives, because several mutations' replacement strings are substrings of
    legitimate code. See the module docstring.
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
