"""Mutation sweep for Module 4.1's ``qe_qt_stance``.

Each mutation reverts one D-040 correction to a plausible alternative, and each
must be killed:

* **M1** restores Section 20.4's own stance logic — including the ``> 0`` /
  ``< 0`` / else chain whose ``else`` branch requires a change of **exactly
  zero**. That is the dead-branch defect, and ``M1a`` is the sweep's most
  important mutation: if the reachability test does not catch it, the band
  correction is decoration.
* **M2** breaks the band itself — hardcoding it, making it exclusive, or
  dropping the relative scaling that makes it meaningful across a balance sheet
  that has ranged from $0.7T to $9.0T.
* **M3** breaks the scarcity logic, which is what the specification's own
  warning ("reserve scarcity is not predictable ex-ante") is about.
* **M4** drops a disclosure.
* **M5** drops a published component, breaking the D-009 cross-field identity.
* **M6** weakens the input contract.
* **M7** restores the specification's hardcoded ``confidence=0.75``.
* **C1** swaps or hardcodes the config accessors.

A survivor is one of three things (D-031): a weak test, an **inert** mutation,
or a **broken** mutation. The runner reports a pattern-miss separately from a
survival, and it **heals before it measures** — an interrupted run leaves the
mutated file on disk, and a naive re-run would adopt it as the baseline.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _sweep_gate import (
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)
from _sweep_gate import run_pytest as _run_pytest_inproc

SRC = Path("src/macro_engine/models/policy_rules.py")
CONFIG = Path("src/macro_engine/config.py")

# --- M1/M2: the stance and the band ---------------------------------------
_CHANGE_PCT = (
    "    change_pct = inputs.balance_sheet_change_3mo / inputs.balance_sheet_level * 100.0"
)
_BRANCHES = (
    "    if change_pct > band:\n"
    '        stance = "QE_EXPANDING"\n'
    "    elif change_pct < -band:\n"
    '        stance = "QT_CONTRACTING"\n'
    "    else:\n"
    '        stance = "NEUTRAL_HOLD"'
)

# --- M3: the scarcity logic ------------------------------------------------
_RESERVES_DRAINING = "    reserves_draining = inputs.reserve_balances_change_3mo < 0.0"
_RRP_DRAINED = "        rrp_drained = inputs.on_rrp_level < settings.rrp_drained_threshold_bn"
_DIRECT_DRAIN = '    direct_reserve_drain = stance == "QT_CONTRACTING" and reserves_draining'

# --- M4: the disclosures ---------------------------------------------------
_BASE_RATE_WARNING = (
    '        f"The stance is a CATEGORICAL from one threshold comparison. Over "\n'
    '        f"{settings.base_rates.observations_measured} weekly observations this "\n'
    '        f"stance occurred in {stance_base_rate:.1%} of them, which is the "\n'
    '        f"frequency a reader needs before treating it as notable (D-029).",'
)
_BAND_WARNING = (
    '        f"The stance is decided by the balance-sheet change measured against a "\n'
    '        f"+/-{band:.2f}% band, not against zero. Section 20.4\'s `== 0` test made "\n'
    '        f"NEUTRAL_HOLD unreachable: the thirteen-week change of a balance sheet "\n'
    '        f"measured in millions is never exactly zero.",'
)
_QT_WARNING = (
    "        warnings.append(\n"
    '            "QT active — monitor repo_stress_check() (Module 4.2). Reserve "\n'
    '            "scarcity is not predictable ex-ante (September 2019), and QT is "\n'
    "            \"harder to calibrate than QE because the 'ample reserves' level is \"\n"
    '            "unknown."\n'
    "        )"
)
_DRAIN_WARNING = (
    "        warnings.append(\n"
    '            f"Reserves FELL ({inputs.reserve_balances_change_3mo:+,.0f}mn) while the "\n'
    '            f"balance sheet contracted, so QT is draining reserves directly rather "\n'
    '            f"than drawing down the ON RRP facility. This is the ordinary case "\n'
    '            f"during QT ({settings.base_rates.reserve_drain_while_qt_rate:.1%} of QT "\n'
    '            f"weeks), not an exceptional one — what makes it dangerous is the RRP "\n'
    '            f"buffer being gone, not the drain itself."\n'
    "        )"
)
_ABSENT_WARNING = (
    "        warnings.append(\n"
    '            "ON RRP level NOT SUPPLIED, so the scarcity assessment is incomplete. "\n'
    '            "Whether QT is draining the RRP buffer or reserves directly cannot be "\n'
    '            "determined from the balance sheet alone — the buffer is the whole "\n'
    '            "question."\n'
    "        )"
)

# --- M5: the published components -----------------------------------------
_STANCE_KEY = '            "stance": stance,'
_CHANGE_PCT_KEY = '            "balance_sheet_change_pct": round(change_pct, 4),'
_LEVEL_KEY = '            "balance_sheet_level": round(inputs.balance_sheet_level, 4),'
_DRAIN_KEY = '            "direct_reserve_drain": direct_reserve_drain,'
_BASE_RATE_KEY = '            "stance_base_rate": stance_base_rate,'

# --- M6: the contract ------------------------------------------------------
_EXTRA_FORBID = (
    '    model_config = ConfigDict(extra="forbid")\n\n    balance_sheet_level: float = Field('
)
_LEVEL_FIELD = "    balance_sheet_level: float = Field(\n        gt=0.0,"
_INPUTS_USED = '            "reserve_balances",\n            "reserve_balances_change_3mo",'

# --- M7: confidence --------------------------------------------------------
_HEURISTIC = "            is_heuristic_not_calibrated=not _qe_stance_calibrated(),"

# --- config accessors ------------------------------------------------------
_BAND_PROP = "        return float(self.neutral_band_pct_value.value)"
_RRP_PROP = "        return float(self.rrp_drained_threshold_bn_value.value)"
# Targets QEStanceBaseRates.rates specifically. The first version of this
# mutation pointed at `return self.base_rates.rates`, which is
# PolicyMixSettings.quadrant_base_rates -- a DIFFERENT model's property, not
# covered by this sweep's tests, so it survived for the wrong reason.
_QE_RATE_ENTRY = '            "QE_EXPANDING": float(self.qe_expanding_rate_value.value),'

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
        '__all__ = [\n    "BalanceSheetInputs",',
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- M1: the stance logic --------------------------------------------
    (
        "M1a the specification's `> 0 / < 0 / else` restored (NEUTRAL_HOLD dies)",
        SRC,
        _BRANCHES,
        "    if change_pct > 0.0:\n"
        '        stance = "QE_EXPANDING"\n'
        "    elif change_pct < 0.0:\n"
        '        stance = "QT_CONTRACTING"\n'
        "    else:\n"
        '        stance = "NEUTRAL_HOLD"',
    ),
    (
        "M1b the stance hardcoded to QE_EXPANDING",
        SRC,
        _BRANCHES,
        '    stance = "QE_EXPANDING"',
    ),
    (
        "M1c the branches reordered so QT is tested first against the wrong sign",
        SRC,
        _BRANCHES,
        "    if change_pct < band:\n"
        '        stance = "QT_CONTRACTING"\n'
        "    elif change_pct > -band:\n"
        '        stance = "QE_EXPANDING"\n'
        "    else:\n"
        '        stance = "NEUTRAL_HOLD"',
    ),
    # --- M2: the band ----------------------------------------------------
    (
        "M2a the band hardcoded to 0.0 (the specification's dead branch, by another route)",
        SRC,
        _BRANCHES,
        "    if change_pct > 0.0:\n"
        '        stance = "QE_EXPANDING"\n'
        "    elif change_pct < -0.0:\n"
        '        stance = "QT_CONTRACTING"\n'
        "    else:\n"
        '        stance = "NEUTRAL_HOLD"',
    ),
    (
        "M2b the upper band made exclusive (exactly at the band is QE)",
        SRC,
        _BRANCHES,
        "    if change_pct >= band:\n"
        '        stance = "QE_EXPANDING"\n'
        "    elif change_pct <= -band:\n"
        '        stance = "QT_CONTRACTING"\n'
        "    else:\n"
        '        stance = "NEUTRAL_HOLD"',
    ),
    (
        "M2c the change left ABSOLUTE rather than relative to the level",
        SRC,
        _CHANGE_PCT,
        "    change_pct = inputs.balance_sheet_change_3mo",
    ),
    # --- M3: the scarcity logic ------------------------------------------
    (
        "M3a the scarcity flag drops the QT requirement",
        SRC,
        _DIRECT_DRAIN,
        "    direct_reserve_drain = reserves_draining",
    ),
    (
        "M3b the reserves-draining comparison inverted",
        SRC,
        _RESERVES_DRAINING,
        "    reserves_draining = inputs.reserve_balances_change_3mo > 0.0",
    ),
    (
        "M3c the RRP drained comparison inverted",
        SRC,
        _RRP_DRAINED,
        "        rrp_drained = inputs.on_rrp_level > settings.rrp_drained_threshold_bn",
    ),
    # --- M4: the disclosures ---------------------------------------------
    (
        "M4a the base-rate frequency dropped (D-029 disclosure)",
        SRC,
        _BASE_RATE_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4b the band-correction disclosure dropped",
        SRC,
        _BAND_WARNING,
        '        "Model output follows.",',
    ),
    (
        "M4c the QT repo-stress warning dropped",
        SRC,
        _QT_WARNING,
        "        pass",
    ),
    (
        "M4d the direct-reserve-drain warning dropped",
        SRC,
        _DRAIN_WARNING,
        "        pass",
    ),
    (
        "M4e the ABSENT-RRP disclosure dropped (silence reads as reassurance)",
        SRC,
        _ABSENT_WARNING,
        "        pass",
    ),
    # --- M5: the published components ------------------------------------
    (
        "M5a the stance dropped from the published value",
        SRC,
        _STANCE_KEY,
        '            "stance": "UNKNOWN",',
    ),
    (
        "M5b the relative change dropped (the stance stops being recomputable)",
        SRC,
        _CHANGE_PCT_KEY,
        '            "balance_sheet_change_pct": 0.0,',
    ),
    (
        "M5c the balance-sheet level dropped (the declared-but-unread input, again)",
        SRC,
        _LEVEL_KEY,
        '            "balance_sheet_level": 0.0,',
    ),
    (
        "M5d the scarcity flag dropped from the published value",
        SRC,
        _DRAIN_KEY,
        '            "direct_reserve_drain": False,',
    ),
    (
        "M5e the stance's own base rate dropped",
        SRC,
        _BASE_RATE_KEY,
        '            "stance_base_rate": 0.0,',
    ),
    # --- M6: the contract -------------------------------------------------
    (
        # D-139 rebased BalanceSheetInputs onto `FiniteInputs`, which itself sets
        # `extra="forbid"` — deleting the local declaration became an EQUIVALENT
        # mutation (the base still forbids) and survived. Preserve the intent by
        # OVERRIDING the base with `extra="ignore"`.
        "M6a extra='forbid' overridden with extra='ignore' on the input model",
        SRC,
        _EXTRA_FORBID,
        '    model_config = ConfigDict(extra="ignore")\n\n    balance_sheet_level: float = Field(',
    ),
    (
        "M6b the positive-level guard weakened to allow zero",
        SRC,
        _LEVEL_FIELD,
        "    balance_sheet_level: float = Field(\n        ge=0.0,",
    ),
    (
        "M6c the two reserve inputs dropped from inputs_used",
        SRC,
        _INPUTS_USED,
        '            "reserve_balances_change_3mo",',
    ),
    # --- M7: confidence ---------------------------------------------------
    (
        "M7a the heuristic factor hardcoded False",
        SRC,
        _HEURISTIC,
        "            is_heuristic_not_calibrated=False,",
    ),
    (
        "M7b confidence hardcoded to the specification's 0.75",
        SRC,
        # **This one was a genuine MIS-TARGET.** `confidence=confidence,` occurs
        # first in `derive_market_implied_policy_path` and second in
        # `qe_qt_stance`, so the bare line rewrote the WRONG function — and
        # because this sweep's selection covers the whole file, a test for the
        # other function could have "killed" it, reporting a kill for a mutation
        # that never touched the subject (D-048). O-29's cost, made visible by
        # D-064's `tools/sweep_health.py`.
        (
            '            "stance_base_rate": stance_base_rate,\n'
            '            "observations_measured": settings.base_rates.observations_measured,\n'
            "        },\n"
            "        confidence=confidence,"
        ),
        (
            '            "stance_base_rate": stance_base_rate,\n'
            '            "observations_measured": settings.base_rates.observations_measured,\n'
            "        },\n"
            "        confidence=0.75,"
        ),
    ),
    # --- config accessors -------------------------------------------------
    (
        "C1a the neutral band property returns a hardcoded value",
        CONFIG,
        _BAND_PROP,
        "        return 0.0",
    ),
    (
        "C1b the RRP threshold property returns a hardcoded value",
        CONFIG,
        _RRP_PROP,
        "        return 0.0",
    ),
    (
        "C1c the QE rate mapping entry hardcoded instead of read from config",
        CONFIG,
        _QE_RATE_ENTRY,
        '            "QE_EXPANDING": 1.0,',
    ),
]


def run_tests() -> bool:
    proc = _run_pytest_inproc(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_policy_rules.py",
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


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only(_MUTATIONS)


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
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
