"""Mutation sweep for ``as_of.py`` (point-in-time discipline, Section 5.5 / O-7).

Why this sweep exists
---------------------
An audit found ``models/as_of.py`` had **no dedicated test and no sweep** — it
was exercised only through its five consumers, so none of its own contracts
failed loudly if broken. ``tests/models/test_as_of.py`` now pins the contracts;
this sweep proves those pins are **load-bearing** rather than decorative by
reverting each documented behaviour and requiring a kill.

The module is small but genuinely branched: a date split, a sort, a default
clock, an empty-vs-withheld distinction, and a horizon reduction. Each has a
mutant below.

Design notes
------------
* The two consumers most sensitive to a silent change are the ones whose own
  behaviour would move if the filter moved — but this sweep pins the module in
  isolation (``tests/models/test_as_of.py``), because that file is where the
  contracts live. Including the consumer suites would slow the sweep without
  strengthening it: a consumer that passes while ``as_of`` is broken is the very
  hole this sweep closes.
* ``CANARY1`` replaces a module-level binding with a syntax error, so the kill
  is STRUCTURAL (``tests/`` cannot collect) rather than incidental. If it
  survives, the test selection no longer reaches the module and every other
  "killed" is a statement about the harness, not the suite (D-051).
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

SRC = Path("src/macro_engine/models/as_of.py")

# Named fragments keep the mutation literals under the line limit (E501) and
# out of the way of the reader. Each must match the pristine source byte-for-
# byte, including indentation -- ruff format will reflow an approximate match
# and the sweep would then silently not apply (lesson 5es).
_CUTOFF = "    cutoff = moment.date()"
_REALISED = "    realised = [p for p in points if p.observation_date <= cutoff]"
_WITHHELD = "    withheld_points = [p for p in points if p.observation_date > cutoff]"
_SORT = "    realised.sort(key=lambda p: p.observation_date)"
_HORIZON = (
    "        withheld_horizon=max((p.observation_date for p in withheld_points), default=None),"
)
_SERIES_ID = '        series_id=series_id or (points[0].series_id if points else "unknown"),'
_EMPTY_PROP = "        return not self.points"
_LATEST_PROP = "        return self.points[-1] if self.points else None"
_WAS_TRUNCATED = "        return self.withheld > 0"
_ON_OR_BEFORE_FILTER = "        (p for p in points if p.observation_date <= target),"
_ON_OR_BEFORE_SORT = "        key=lambda p: p.observation_date,"
_ON_OR_BEFORE_RETURN = "    return eligible[-1] if eligible else None"
_LATEST_OBS = "    return observation_as_of(points, as_of=as_of).latest"
_DEFAULT_CLOCK = "    moment = as_of or utc_now()"

MUTATIONS: list[tuple[str, str, str]] = [
    # -- O-72 canary (CONTROL) ---------------------------------------------
    (
        "CANARY1 the module binding is replaced with a syntax error (CONTROL)",
        "__all__ = [",
        "__CANARY__ = <<<SYNTAX ERROR>>>",
    ),
    # --- Contract 1: the same-day inclusion boundary ----------------------
    # The centrepiece. `<=` includes a same-day stamp; `<` excludes it. These
    # two mutants are opposites so a passing suite cannot be passing by luck on
    # one direction only.
    (
        "M1a same-day observations excluded (<= becomes <)",
        _REALISED,
        "    realised = [p for p in points if p.observation_date < cutoff]",
    ),
    (
        "M1b same-day observations double-counted (>= in the withheld split)",
        _WITHHELD,
        "    withheld_points = [p for p in points if p.observation_date >= cutoff]",
    ),
    # --- Contract 2: the date, not the timestamp --------------------------
    (
        "M2a the cutoff uses the full datetime, not the calendar date",
        _CUTOFF,
        "    cutoff = moment",  # a datetime; `date <= datetime` raises
    ),
    # --- Contract 5: no silent truncation; sorted oldest-first -------------
    (
        "M3a the sort is removed (provider order is trusted)",
        _SORT,
        "    pass  # sort removed",
    ),
    (
        "M3b the sort is newest-first (latest becomes the oldest point)",
        _SORT,
        "    realised.sort(key=lambda p: p.observation_date, reverse=True)",
    ),
    (
        "M3c the withheld horizon reports the MINIMUM future date, not the max",
        _HORIZON,
        "        withheld_horizon=min(\n"
        "            (p.observation_date for p in withheld_points), default=None\n"
        "        ),",
    ),
    (
        "M3d the withheld count is dropped (silent truncation)",
        "        withheld=len(withheld_points),",
        "        withheld=0,",
    ),
    # --- Contract 4: empty is a hard stop ---------------------------------
    (
        "M4a is_empty reports the wrong sense (not -> truthy)",
        _EMPTY_PROP,
        "        return bool(self.points)",
    ),
    (
        "M4b latest returns the last point even when empty (IndexError traps it)",
        _LATEST_PROP,
        "        return self.points[-1]",
    ),
    (
        "M4c was_truncated reports the wrong sense",
        _WAS_TRUNCATED,
        "        return self.withheld < 0",
    ),
    # --- Contract 3: on_or_before vs as_of asymmetry ----------------------
    (
        "M5a on_or_before routes through today's cutoff (the asymmetry lost)",
        _ON_OR_BEFORE_FILTER,
        "        (p for p in points if p.observation_date <= utc_now().date()),",
    ),
    (
        "M5b on_or_before sorts newest-first (returns the oldest)",
        _ON_OR_BEFORE_SORT,
        "        key=lambda p: p.observation_date, reverse=True,",
    ),
    (
        "M5c on_or_before returns the FIRST eligible point, not the last",
        _ON_OR_BEFORE_RETURN,
        "    return eligible[0] if eligible else None",
    ),
    # --- The one-line helper inherits the hard stop -----------------------
    (
        "M6a latest_observation falls back to a zero-valued point (a fabricated 0.0)",
        _LATEST_OBS,
        "    latest = observation_as_of(points, as_of=as_of).latest\n"
        "    return latest or ObservationPoint(\n"
        "        observation_date=as_of.date() if as_of else utc_now().date(),\n"
        "        value=0.0,\n"
        '        series_id="unknown",\n'
        "        retrieved_at=utc_now(),\n"
        "    )",
    ),
    # --- The default clock ------------------------------------------------
    (
        "M7a the as_of default is a fixed literal instead of now",
        _DEFAULT_CLOCK,
        "    moment = as_of or datetime(2026, 1, 1, tzinfo=UTC)",
    ),
    # --- The series_id fallback -------------------------------------------
    (
        "M8a a derived series silently re-uses the source series_id",
        _SERIES_ID,
        '        series_id="unknown",',
    ),
]


def run_tests() -> bool:
    # The test path is a literal, not a constant, because ruff's S603 rule
    # treats a variable argument to ``subprocess`` as untrusted input.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/models/test_as_of.py",
            "-q",
            "--no-header",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _check_targets_only() -> int:
    """Print the anchor verdict and STOP, touching nothing (O-138)."""
    return check_only([(name, SRC, old, new) for name, old, new in MUTATIONS])


def main() -> int:
    # O-138: the check-only mode must be answered BEFORE the lifecycle
    # writes, and before ANY file is read -- see check_only's docstring.
    if check_only_requested():
        return _check_targets_only()
    with sweep_lifecycle([SRC]) as originals:
        return _run_sweep(originals)


def _run_sweep(originals: dict[Path, str]) -> int:
    pristine_src = originals[SRC]

    _table = [(name, SRC, old, new) for name, old, new in MUTATIONS]
    problems = check_targets({SRC: pristine_src}, _table)
    print(f"check_targets: {len(_table)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep")
        print("that cannot prove it mutates the site it names certifies")
        print("nothing (D-048, O-29).")
        return 4

    survivors: list[tuple[str, str]] = []
    for name, old, new in MUTATIONS:
        if old not in pristine_src:
            print(f"PATTERN MISSING   {name}")
            survivors.append((name, "pattern-not-found"))
            continue
        SRC.write_text(pristine_src.replace(old, new, 1), encoding="utf-8", newline="")
        caught = not run_tests()
        SRC.write_text(pristine_src, encoding="utf-8", newline="")
        print(f"{'KILLED' if caught else 'SURVIVED':17} {name}")
        if not caught:
            survivors.append((name, "survived"))

    print()
    print(f"{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} killed")
    for name, why in survivors:
        print(f"  SURVIVOR ({why}): {name}")
    if any(name.startswith("CANARY1 ") for name, _ in survivors):
        print()
        print("REFUSING TO CERTIFY: the honesty canary SURVIVED.")
        print("  !! CANARY1 -- the test selection no longer reaches the mutated")
        print("     module, so no kill above is evidence about the suite (O-72).")
        return 3

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
