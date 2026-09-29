"""Mutation sweep for the RECORDED OPENBB COMMAND INVENTORY (O-104).

**What is mutated here is the record, not the engine — and that is the point.**

Every other sweep in this directory mutates a line of ``src/macro_engine`` and asks
whether the test suite notices. This one mutates the **recorded command inventory**
(the docs' count of OpenBB commands the engine issues) and asks whether
``tests/test_openbb_command_inventory.py`` notices.

The count is load-bearing in the way an inventory always is: it is the number a
reviewer reads to decide whether the OpenBB surface is being used or left idle, and
**O-104's residual defect was that the number was wrong.** It said *2 of 201* while
the tree issued **4** — because D-086 applied two of the audit's five changes and
nothing re-read the count. A record that no test reads drifts silently; that is the
whole lesson of D-087.23, and this file is the second application of it.

**Two directions are mutated, because the guard has two halves.**

* The **prose** half: the count as stated on ``docs/PROGRESS.md``.
* The **derivation** half: the registry, which is where the command set actually
  comes from. Mutating the registry proves the guard is not merely a string match
  against a number typed in its own header — it must *derive* the set.

The mutations are graded, not merely inverted:

* ``CANARY1`` — a **syntax error** in the guard module itself, so the kill is
  STRUCTURAL. If it survives, the sweep is testing nothing (the D-051 trap).
* ``M1`` — the count reverted to the **stale live claim** (*2 of 201*, bare, no
  supersession marker). This is the exact regression O-104 had.
* ``M2`` — a **new command added to the registry** while the recorded count stays
  at 4. The failure arriving from the *other* side: a capability the record does not
  mention. A guard that only forbid the old string would let this through.
* ``M3`` — a **substitution**: one live command swapped for another, count still 4.
  Catches a guard that compares only the total.
* ``M4`` — the **disabled calendar made live**: `release_calendar.enabled` flipped to
  `true`, which must move the count to 5 and fail. Catches a census that swept every
  `endpoint:` line regardless of its gate — overstating coverage by exactly what the
  gate exists to remove.
* ``M5`` — the **supersession marker stripped** from the corrected sentence, leaving
  the honest figure but as a bare claim. The O-107 adjacent test: the same text must
  pass *with* the marker and fail *without* it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from _sweep_gate import (
    check_only,
    check_only_requested,
    check_targets,
    format_problems,
    sweep_lifecycle,
)

PROGRESS = Path("docs/PROGRESS.md")
REGISTRY = Path("config/series_registry.yaml")
GUARD = Path("tests/test_openbb_command_inventory.py")

#: Which file each mutation edits, stated explicitly. A name-prefix rule would be
#: the fragile-predicate mistake (O-107); a typo here fails loudly in
#: `check_targets` ("pattern-not-found") rather than silently mutating nothing.
_TARGETS: dict[str, Path] = {
    "CANARY1 the guard module is replaced with a syntax error (CONTROL)": GUARD,
    "M1 the stale '2 of 201' row restored as a live current claim": PROGRESS,
    "M2 a new registry command added while the recorded count stays 4": REGISTRY,
    "M3 a live command substituted for another, count unchanged": REGISTRY,
    "M4 the disabled calendar re-enabled, making it a live command": REGISTRY,
    "M5 the supersession marker stripped, leaving the old figure as a bare claim": PROGRESS,
}

# The corrected row, as it must read. Every prose mutation below is a transform of
# a SLICE of this text, so a drift in the shipped wording makes the anchor miss and
# the sweep refuses (D-048) rather than silently testing nothing.
#
# NOTE the anchor is the WHOLE table row, not just the figure: M1 needs to restore
# the *bare* row, which differs from the corrected row in more than the number.
_CORRECTED_ROW = "| OpenBB commands the engine uses | **6 of 201** — `fred_series`, `fred_search`, `fixedincome.government.yield_curve` (D-086 change 1), `economy.fomc_documents` (D-086 change 2), `commodity.petroleum_status_report` + `commodity.short_term_energy_outlook` (D-120) · *superseded: 4 of 201 at D-086/D-087.27; 2 of 201 as measured at D-084, before two of the five §8 changes were applied* |"

# The stale row, verbatim from what the tree carried before this increment.
_STALE_ROW = "| OpenBB commands the engine uses | **2 of 201** (`fred_series`, `fred_search`) |"

# The registry anchors. Kept as narrow, unique slices so `check_targets` can prove
# a single site each (an ambiguous anchor rewrites the wrong entry).
_SERIES_ANCHOR = "  building_permits:\n    provider: fred\n    symbol: PERMIT\n"

# A NEW command for M2: point an existing series at a dedicated route. `equity_volatility`
# is chosen because §4.1 lists `cboe/equity/price/historical` as a real alternative for
# it -- so this is a *plausible* future change, not a synthetic one.
_M2_OLD = "  equity_volatility:\n    provider: fred\n    symbol: VIXCLS\n"
_M2_NEW = (
    "  equity_volatility:\n"
    "    provider: cboe\n"
    "    symbol: VIXCLS\n"
    "    endpoint: equity.price.historical\n"
)

# The disabled-calendar anchor for M4.
_M4_OLD = "release_calendar:\n  enabled: false\n  provider: nasdaq\n"
_M4_NEW = "release_calendar:\n  enabled: true\n  provider: nasdaq\n"

# The supersession clause for M5 -- stripped, leaving the honest figure as a bare
# claim alongside the current one.
_M5_OLD = " · *superseded: 4 of 201 at D-086/D-087.27; 2 of 201 as measured at D-084, before two of the five §8 changes were applied* |"
_M5_NEW = " |"

MUTATIONS: list[tuple[str, str, str]] = [
    # -- O-72 canary (CONTROL) --------------------------------------------
    # A mutation CERTAIN to be caught, so the sweep can REFUSE TO CERTIFY when it
    # survives. The guard module is replaced with a syntax error, so the kill is
    # STRUCTURAL (the guard cannot be imported by any selection) rather than
    # incidental. A canary that parses is INERT and would be reported KILLED while
    # proving nothing -- so the pre-flight below asserts it breaks the parse.
    (
        "CANARY1 the guard module is replaced with a syntax error (CONTROL)",
        "def test_the_command_set_is_derived_not_empty() -> None:",
        "def test_the_command_set_is_derived_not_empty( -> None:\n    pass\n\ndef _unused() -> None:",
    ),
    # -- M1: the stale live claim, restored verbatim ----------------------
    (
        "M1 the stale '2 of 201' row restored as a live current claim",
        _CORRECTED_ROW,
        _STALE_ROW,
    ),
    # -- M2: a new command the record does not mention --------------------
    # The registry gains a dedicated route for `equity_volatility`; the count is now
    # 5 and the recorded row still says 4. A guard that only forbade the old string
    # would pass this, which is O-104 arriving from the other direction.
    (
        "M2 a new registry command added while the recorded count stays 4",
        _M2_OLD,
        _M2_NEW,
    ),
    # -- M3: a substitution that keeps the count --------------------------
    # Count-stable, set-changing. Catches a guard that compares only the total.
    (
        "M3 a live command substituted for another, count unchanged",
        "    endpoint: economy.fred_series\n    tenors:\n      5yr: DFII5",
        "    endpoint: fixedincome.government.tips_yields\n    tenors:\n      5yr: DFII5",
    ),
    # -- M4: the gate ignored ---------------------------------------------
    # `release_calendar.enabled: true` moves the calendar into the live set, so a
    # derivation that ignores `enabled` counts 5 and must fail. This is the check
    # that keeps the census from overstating coverage.
    (
        "M4 the disabled calendar re-enabled, making it a live command",
        _M4_OLD,
        _M4_NEW,
    ),
    # -- M5: the supersession marker stripped -----------------------------
    # The honest figure stays, the "superseded:" framing goes. The same number must
    # be permitted WITH the marker and forbidden WITHOUT it (the O-107 lesson).
    (
        "M5 the supersession marker stripped, leaving the old figure as a bare claim",
        _M5_OLD,
        _M5_NEW,
    ),
]


def run_tests() -> bool:
    """The guard itself. One selection on purpose.

    Unlike the performance sweep there is no *second* test to select: this guard
    reads the registry through the real loader and the docs as text, so nothing it
    touches needs a config-parity companion. The canary is a syntax error in the
    guard *module*, which the selection reaches directly.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_openbb_command_inventory.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _parses(text: str) -> bool:
    """Whether ``text`` is loadable YAML -- used to prove the registry anchor is real.

    Only the registry mutations need this; it answers the one question their validity
    depends on (that the mutated registry still parses, so the guard's failure is
    about the *content* and not about a broken file).
    """
    try:
        yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return True


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only([(name, _TARGETS[name], old, new) for name, old, new in MUTATIONS])


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
    # The whole interrupt defence in one call (O-103): heal, protect, spend.
    # On win32 no Python signal handler runs for SIGTERM/SIGINT, so the sidecar --
    # not a handler -- is the defence with real reach here.
    with sweep_lifecycle([PROGRESS, REGISTRY]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    pristine = dict(originals)

    # Refuse to measure before anything is mutated (D-048, O-29). An anchor that
    # drifted reports as a survivor, which reads as 'the guard has a hole' when the
    # truth is 'the sweep aimed at the wrong text'.
    #
    # The target of each mutation is declared in `_TARGETS` rather than inferred
    # from the name, because a name-prefix rule ("M1/M5 are prose") is exactly the
    # fragile kind of predicate this project has been burned by (O-107).
    table = [(name, _TARGETS[name], old, new) for name, old, new in MUTATIONS]
    # `check_targets` reads a path not present in `originals` from disk, so the
    # canary's target (the guard module, not a swept document) is resolvable.
    problems = check_targets(pristine, table)
    print(f"check_targets: {len(table)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

    # VERIFY THE PROTECTION BEFORE CREDITING IT (lesson 5cl). The canary is only a
    # control if it actually breaks the guard module's import. Asserted here rather
    # than assumed, so a canary that quietly became a valid edit stops the sweep
    # instead of being credited with a kill it did not earn.
    canary_text = GUARD.read_text(encoding="utf-8")
    canary_old, canary_new = MUTATIONS[0][1], MUTATIONS[0][2]
    if canary_old not in canary_text:
        print("REFUSING TO RUN: the canary anchor is absent from the guard module;")
        print("the control is not installed, so a green run would mean nothing (O-72).")
        return 4
    # A canary that still COMPILES is inert: it would be reported KILLED while
    # proving nothing about the selection (the D-051 trap). `compile()` answers the
    # one question its validity depends on, cheaply and without running anything.
    try:
        compile(canary_text.replace(canary_old, canary_new, 1), "<canary>", "exec")
    except SyntaxError:
        pass
    else:
        print("REFUSING TO RUN: the CANARY no longer breaks the guard module's parse.")
        print("  !! A canary that compiles is INERT -- it would be reported")
        print("     KILLED while proving nothing about the selection. Make the")
        print("     mutation a real syntax error before trusting a run.")
        return 4

    # The registry mutations must keep the file PARSEABLE -- otherwise their kills
    # would be structural (the registry loader throws) rather than about content,
    # which would make them indistinguishable from the canary.
    registry_text = pristine[REGISTRY]
    for name, old, new in MUTATIONS:
        if _TARGETS[name] != REGISTRY:
            continue
        if not _parses(registry_text.replace(old, new, 1)):
            print(f"REFUSING TO RUN: {name} breaks the registry YAML parse.")
            print("  !! A registry mutation must stay parseable, or its kill is")
            print("     structural and proves nothing about the derivation.")
            return 4

    survivors: list[tuple[str, str]] = []
    for name, old, new in MUTATIONS:
        target = _TARGETS[name]
        text = target.read_text(encoding="utf-8")
        if old not in text:
            print(f"PATTERN MISSING   {name}")
            survivors.append((name, "pattern-not-found"))
            continue
        target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        # Restore from the pristine copy held in memory -- never `git checkout --`
        # (D-086.8 lost 97 lines that way). The canary's target is not in the swept
        # set, so its pristine text is the copy read during the pre-flight.
        baseline = pristine.get(target, canary_text)
        target.write_text(baseline, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
        if not caught:
            survivors.append((name, "survived"))

    print()
    print(f"{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    # O-72's canary gate. A canary that SURVIVES means the sweep ran but tested
    # nothing: its selection no longer reaches the mutated file, so every 'killed'
    # above is a statement about the harness rather than the guard.
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     file, so no kill above is evidence about the guard (O-72).")
        return 3

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
