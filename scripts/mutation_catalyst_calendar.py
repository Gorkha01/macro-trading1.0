"""Mutation sweep for ``next_catalyst_calendar`` (D-065).

**Run this in the FOREGROUND ONLY.** The sweep rewrites
``src/macro_engine/thesis_layer/catalysts.py`` and ``src/macro_engine/config.py``
in place, so any concurrent test run, live check or probe reads a mutated
module. The blast radius is the repository.

What this increment is really testing
-------------------------------------
Section 16.4's sample is three hardcoded strings, so almost every defect here is
about **what the function refuses to say** rather than about arithmetic:

1. **A catalyst with no date is not a catalyst.** ``M1`` removes the forward
   filter and the date construction in turn; the kill is the assertion that
   every entry parses to an ISO date.
2. **``ptic`` is a pagination total, not a count.** ``M2`` restores the reading
   of ``ptic`` as if it were the number of events. Measured live: 2806 for a
   window whose first page holds 50 rows.
3. **FRED's FOMC release is a daily feed.** ``M3`` routes the FOMC catalyst
   through FRED, where ``rid=101`` returns a row for *every calendar day*. The
   kill is the count assertion — one FOMC entry, not fifty.
4. **Flattening the Fed's HTML creates phantom meetings.** ``M4`` replaces the
   structured read with a flat-text regex over the panel. Measured: the flat
   2027 text yields two January meetings from one.
5. **A two-day meeting is dated by its LAST day.** ``M5`` dates it by the first.
6. **A failed source must not read as a quiet calendar.** ``M6`` makes the
   all-sources-failed path return ``[]`` instead of raising (D-054).

What this sweep structurally CANNOT find
----------------------------------------
1. **Whether the calendar is complete.** Section 16.4 names three catalysts;
   the sweep cannot prove no fourth official event matters. That is a
   specification judgement.
2. **Whether 120 days is the right horizon.** It is ``uncalibrated_illustrative``
   and the sweep can only prove the leaf is *read*.
3. **Whether FRED's release ids stay correct.** A renumbered release returns
   another release's dates under the configured label — measured live for
   ``rid=101``. The function warns; the sweep can pin the warning but cannot
   make FRED stop renumbering (O-74).
4. **Whether the transport survives a future FRED fingerprint change.** The
   ``httpx``/HTTP-1.1 choice is a measured fact about *today* (D-065), and no
   mutation makes it durable.

The honesty control
-------------------
``M7.1`` is semantically identical to the shipped code and **must survive**. If
the sweep reports it killed, the sweep is reporting kills it cannot justify and
no other number it prints means anything.

Anchors
-------
Every anchor is verified against the SHIPPED source by ``check_targets`` before a
single mutation is applied — present **exactly once** — and by
``check_anchor_landings``, which proves it lands in a symbol this increment owns.

``refuse_on_noop`` is set for every mutation, which is D-064's lesson 93: a
mutation whose ``old`` text is absent is reported NOT APPLIED and, in the D-064
sweep, silently left the denominator — the sweep certified ``25/27`` while two
mutations never ran. Here an unapplied mutation is a **refusal**, not a note.
"""

from __future__ import annotations

import argparse
import ast
import re
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

from _sweep_gate import run_pytest as _run_pytest_inproc
from _sweep_gate import sweep_lifecycle

REPO = Path(__file__).resolve().parent.parent
CATALYSTS = REPO / "src/macro_engine/thesis_layer/catalysts.py"
CONFIG = REPO / "src/macro_engine/config.py"

#: The test selection a surviving mutation must be *capable* of killing.
#: ``test_catalysts.py`` carries the behavioural assertions; ``config.py``
#: mutations are also visible there (the settings model is exercised by
#: ``test_release_ids_are_distinct``), so one file suffices — and a second,
#: unused target would make a kill unattributable.
PYTEST_TARGETS = ["tests/thesis_layer/test_catalysts.py"]


@dataclass(frozen=True)
class Mutation:
    """One single-substring rewrite of one file."""

    group: str
    name: str
    path: Path
    old: str
    new: str
    intent: str
    expect_killed: bool | None = None
    inert_proof: str = ""


@dataclass
class Result:
    """The outcome of applying and testing one mutation."""

    mutation: Mutation
    applied: bool
    exit_code: int
    output: str = field(default="")

    @property
    def killed(self) -> bool:
        """True only for a genuine test failure.

        Exit 4 is pytest's usage error (a missing path, a plugin crash, no tests
        collected). Counting it as a kill is how D-051's first draft reported
        56/56 against a control that could not fail.
        """
        return self.exit_code not in (0, 4)


# ---------------------------------------------------------------------------
# Anchors — read out of the shipped source, never transcribed from memory
# ---------------------------------------------------------------------------


def enclosing_symbol(text: str, index: int) -> str:
    """The top-level symbol a character offset falls inside, or ``"<module>"``.

    **Deliberately duplicated from ``tools/sweep_health.py``, not imported** —
    see ``scripts/mutation_scenario_distribution.py`` for the full reason
    (``mypy --strict`` refuses the import: ``tools/`` has no ``__init__.py`` and
    the gate names both ``src tests scripts tools``, so one file becomes two
    modules). The owner is resolved by **parsing**, not by a backwards line walk,
    because a line-walk matches ``def ...`` inside a comment (D-064).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "<module>"
    offset_line = text[:index].count("\n") + 1
    enclosing: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.lineno > offset_line:
            continue
        if node.end_lineno is not None and node.end_lineno < offset_line:
            continue
        enclosing.append((node.lineno, node.name))
    if not enclosing:
        return "<module>"
    return max(enclosing)[1]


#: The top-level symbols this increment owns in each file.
_ALLOWED_ANCHOR_OWNERS: dict[str, frozenset[str]] = {
    "catalysts.py": frozenset(
        {
            "next_catalyst_calendar",
            "_fetch_fred_release",
            "_fetch_fed_fomc_meetings",
            "_http_get",
            "<module>",
        }
    ),
    "config.py": frozenset({"CatalystCalendarSettings", "Settings"}),
}

# --- M1: every entry carries a real date ------------------------------------
_FORWARD_FILTER = "        forward = [(d, n) for d, n in events if today <= d <= horizon]"
_HORIZON = "    horizon_ordinal = today.toordinal() + int(settings.horizon_days.value)"
_FRED_ENTRY = (
    '            entries.append((when, f"{label} release ({expected_name}) — {when.isoformat()}"))'
)

# --- M2: ptic is a pagination total -----------------------------------------
# D-086: `payload = json.loads(...)` is no longer unique — the FOMC documents
# command now reads a payload the same way — so this anchor carries the FRED
# release call's own following line to stay unambiguous.
_PAYLOAD = (
    "    payload = json.loads(_http_get(url, timeout=timeout))\n"
    "\n"
    "    events: list[tuple[date, str]] = []"
)
_PTIC_UNUSED = "    events: list[tuple[date, str]] = []\n    current: date | None = None"

# --- M3: FOMC comes from the Fed --------------------------------------------
# D-086: the call site now passes `as_of` as well.
_FED_CALL = "        meetings = _fetch_fed_fomc_meetings(timeout=timeout, as_of=as_of)"

# --- M4: the structured FOMC read -------------------------------------------
# D-086: the Fed's HTML parser is gone; the equivalent defect on the structured
# command is reading the meeting date from the document URL rather than the
# typed `date` field. The write is what M4 mutates.
_FED_STRUCTURED = "            when = date.fromisoformat(str(raw_date)[:10])"

# --- M5: the projections flag -----------------------------------------------
# D-086: "dated by the last day" became "the projections flag is a document".
# The equivalent defect is allowing a later `monetary_policy` row to clear a
# flag a `projections` row already set.
_LAST_DAY = "            by_date[when] = by_date.get(when, False)"

# --- M6: the all-sources-failed refusal -------------------------------------
_ANSWERED = "    if answered == 0:"

# --- M7: the honesty control ------------------------------------------------
_FED_ENTRY = '            entries.append((when, f"FOMC meeting{detail} — {when.isoformat()}"))'

# --- M8: the config accessors -----------------------------------------------
_DISTINCT = "        if len(set(ids.values())) != len(ids):"


def build_mutations() -> list[Mutation]:
    """The catalogue. Order is group-major so a partial run is interpretable."""
    return [
        # -- M1: a dated entry --------------------------------------------------
        Mutation(
            group="M1",
            name="M1.1 the forward filter is dropped (past releases returned as catalysts)",
            path=CATALYSTS,
            old=_FORWARD_FILTER,
            new="        forward = [(d, n) for d, n in events]",
            intent=(
                "Every event the source returned becomes a 'next' catalyst, "
                "including ones in the past. The kill is the date-parse plus the "
                "as-of-2026-11-01 test."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.2 the entry is the sample's dateless string",
            path=CATALYSTS,
            old=_FRED_ENTRY,
            new='            entries.append((when, f"{label} release (FRED release/dates)"))',
            intent=(
                "Restores Section 16.4's literal output: the source is named and "
                "the date is omitted. The kill is test_every_entry_carries_a_real_date."
            ),
        ),
        Mutation(
            group="M1",
            name="M1.3 the horizon is zero (no release is ever forward)",
            path=CATALYSTS,
            old=_HORIZON,
            new="    horizon_ordinal = today.toordinal()",
            intent=(
                "The horizon collapses to 'today', so the local bound admits "
                "nothing and only an event dated exactly today would survive. "
                "Every release source answers with nothing."
            ),
        ),
        # -- M2: ptic ----------------------------------------------------------
        Mutation(
            group="M2",
            name="M2.1 ptic is read as the event count (first page truncated to ptic)",
            path=CATALYSTS,
            old=_PAYLOAD,
            new=(
                "    payload = json.loads(_http_get(url, timeout=timeout))\n"
                "    _ = payload.get('ptic')\n"
                "\n"
                "    events: list[tuple[date, str]] = []"
            ),
            intent=(
                "Adds a read of ptic without changing behaviour, so this mutant is "
                "expected INERT: the point of the assertion is that ptic is never "
                "used, and a no-op read cannot be caught by a value test."
            ),
            expect_killed=False,
            inert_proof=(
                "INERT BY CONSTRUCTION — naming ptic in a dead assignment changes "
                "no observable behaviour. test_ptic_is_never_read_as_a_count pins "
                "the *outcome* (a huge ptic does not alter the entries), which is "
                "the property that matters; a mutant that merely mentions the "
                "field is not the defect."
            ),
        ),
        # -- M3: FOMC source ---------------------------------------------------
        Mutation(
            group="M3",
            name="M3.1 FOMC is read from FRED like the other three catalysts",
            path=CATALYSTS,
            old=_FED_CALL,
            new=(
                "        meetings = [\n"
                "            (d, False)\n"
                "            for d, _n in _fetch_fred_release(101, start=today,\n"
                "                end=date.fromordinal(horizon), timeout=timeout)\n"
                "        ]"
            ),
            intent=(
                "Restores the defect this increment exists to avoid: FRED's FOMC "
                "release is a DAILY press-release feed, so this yields an entry "
                "for every calendar day. The kill is the one-entry assertion."
            ),
        ),
        # -- M4: the structured FOMC read ---------------------------------------
        Mutation(
            group="M4",
            name="M4.1 the meeting date is inferred from the document URL, not read",
            path=CATALYSTS,
            old=_FED_STRUCTURED,
            new=(
                "            when = date.fromisoformat(\n"
                '                str(row.get("url", ""))[-12:-4]\n'
                "            )"
            ),
            intent=(
                "D-086's replacement for the flat-text parse defect. The Fed's "
                "document URLs are date-stamped too, so a reader that trusts the "
                "URL instead of the `date` field attributes the wrong day. The "
                "kill is test_meeting_dates_come_from_the_typed_field_not_the_url, "
                "whose payload makes the two disagree."
            ),
        ),
        # -- M5: the projections flag ------------------------------------------
        Mutation(
            group="M5",
            name="M5.1 a later policy row clears the projections flag",
            path=CATALYSTS,
            old=_LAST_DAY,
            new="            by_date[when] = False",
            intent=(
                "D-086's replacement for the last-day-dating defect. The `or` "
                "semantics of `by_date.get(when, False)` exists so a `projections` "
                "row seen BEFORE the `monetary_policy` row is not cleared by it. "
                "The kill is test_the_projections_flag_survives_a_later_policy_row."
            ),
        ),
        # -- M6: the refusal ---------------------------------------------------
        Mutation(
            group="M6",
            name="M6.1 an unreachable calendar returns [] instead of raising",
            path=CATALYSTS,
            old=_ANSWERED,
            new="    if False:",
            intent=(
                "D-054's silence failure: an empty list now means both 'quiet "
                "calendar' and 'every source is down'. The kill is the "
                "CatalystSourceError assertion."
            ),
        ),
        # -- M7: the control ---------------------------------------------------
        Mutation(
            group="M7",
            name="M7.1 the FOMC entry string is rebuilt with the same parts (CONTROL)",
            path=CATALYSTS,
            old=_FED_ENTRY,
            new=(
                '            entries.append((when, f"FOMC meeting{detail} "\n'
                '                                    f"— {when.isoformat()}"))'
            ),
            intent=(
                "CONTROL — the concatenation is re-wrapped across two f-strings "
                "but produces the identical string."
            ),
            expect_killed=False,
            inert_proof="CONTROL — semantically identical by construction.",
        ),
        # -- M8: the config guard ----------------------------------------------
        Mutation(
            group="M8",
            name="M8.1 the distinct-release-ids guard is removed",
            path=CONFIG,
            old=_DISTINCT,
            new="        if False:",
            intent=(
                "Two catalysts may share a release id, so one is published twice "
                "and another is dropped. The kill is test_release_ids_are_distinct."
            ),
        ),
    ]


_INERT_PROOFS: dict[str, str] = {
    "M2.1 ptic is read as the event count (first page truncated to ptic)": (
        "INERT BY CONSTRUCTION — see the mutation's own note."
    ),
    "M7.1 the FOMC entry string is rebuilt with the same parts (CONTROL)": (
        "CONTROL — semantically identical by construction."
    ),
}


def check_targets(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every ``old`` string is present EXACTLY ONCE.

    From D-048. ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an
    ``old`` appearing twice silently rewrites the wrong site and the sweep then
    reports a surviving test — a conclusion about code nobody mutated.
    """
    problems: list[str] = []
    by_file: dict[Path, str] = {}
    for path in {mt.path for mt in mutations}:
        by_file[path] = path.read_text(encoding="utf-8")

    for mt in mutations:
        text = by_file[mt.path]
        if mt.old == mt.new:
            problems.append(f"{mt.name}: INERT BY CONSTRUCTION (old == new)")
            continue
        count = text.count(mt.old)
        if count == 0:
            problems.append(f"{mt.name}: target ABSENT in {mt.path.name} (0 occurrences)")
        elif count > 1:
            problems.append(
                f"{mt.name}: target AMBIGUOUS in {mt.path.name} "
                f"({count} occurrences) -- str.replace would rewrite the first"
            )
    if verbose:
        print(f"check_targets: {len(mutations)} mutations, {len(problems)} problem(s)")
        for p in problems:
            print(f"  !! {p}")
    return problems


def check_anchor_landings(mutations: list[Mutation], *, verbose: bool = True) -> list[str]:
    """Refuse to run unless every anchor lands in a symbol THIS increment owns.

    ``check_targets`` proves an anchor is unique; it cannot prove it is in the
    **right place** (**O-67**). Both files here hold text that is unique while
    sitting somewhere else — ``config.py`` has many ``if False:``-shaped guards
    and ``catalysts.py`` has several ``entries.append(...)`` calls.
    """
    problems: list[str] = []
    for mt in mutations:
        allowed = _ALLOWED_ANCHOR_OWNERS.get(mt.path.name)
        if allowed is None:
            problems.append(f"{mt.name}: no anchor-owner rule for {mt.path.name}")
            continue
        text = mt.path.read_text(encoding="utf-8")
        index = text.find(mt.old)
        if index < 0:
            continue  # check_targets already reports ABSENT
        owner = enclosing_symbol(text, index)
        if owner not in allowed:
            problems.append(
                f"{mt.name}: anchor lands in {owner!r}, which this increment does "
                f"not own (allowed: {sorted(allowed)})"
            )
    if verbose:
        print(f"check_anchor_landings: {len(mutations)} mutations, {len(problems)} problem(s)")
        for p in problems:
            print(f"  !! {p}")
    return problems


def check_tests_collect() -> list[str]:
    """Prove the test selection actually collects tests BEFORE the sweep runs.

    A bad target path makes pytest exit **4**, and exit 4 is not a kill. Without
    this gate a typo'd path produces a false 100%-killed report (D-051).
    """
    problems: list[str] = []
    for target in PYTEST_TARGETS:
        if not (REPO / target).exists():
            problems.append(f"test target ABSENT: {target}")
    if problems:
        return problems
    proc = _run_pytest_inproc(
        # The path is inlined as a literal rather than passed via PYTEST_TARGETS
        # because ruff's S603 treats a variable list as possible untrusted input.
        # It is the same string; ``check_tests_collect`` already asserted the
        # path exists, so the two cannot drift.
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/thesis_layer/test_catalysts.py",
            "-m",
            "not live",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        problems.append(f"test selection does not collect (pytest exit {proc.returncode})")
        return problems
    match = re.search(r"(\d+)\s+tests? collected", proc.stdout)
    if not match or int(match.group(1)) == 0:
        problems.append("test selection collects ZERO tests")
    return problems


def run_pytest() -> tuple[int, str]:
    """Run the targeted tests. Non-zero means the mutation was killed.

    Exit code **4** is pytest's "usage error / no tests collected", which is not
    a kill. ``-x`` is passed and is not optional (lesson 61): the kill signal
    must be cheap, because the cheap path is the one that gets used.
    """
    proc = _run_pytest_inproc(
        # Inlined literal, per the S603 note in ``check_tests_collect``.
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "tests/thesis_layer/test_catalysts.py",
            "-m",
            "not live",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


#: The mutation currently written to disk, so a signal handler can undo it.
_IN_FLIGHT: list[tuple[Path, str] | None] = [None]


def _restore_in_flight(_signum: int, _frame: object) -> None:
    """Undo an in-flight mutation, then exit. Installed for SIGTERM/SIGINT.

    Without this a killed sweep leaves mutated source on disk — D-057's first run
    was stopped by a ``SIGTERM`` that bypassed the ``finally``, and D-062 caught a
    leftover (`MX3d`) with ``tools/sweep_health.py``'s scan.
    """
    pending = _IN_FLIGHT[0]
    if pending is not None:
        path, original = pending
        path.write_text(original, encoding="utf-8", newline="")
        print(f"\n!! interrupted -- restored {path.name} from the in-flight mutation")
    raise SystemExit(130)


def apply_and_test(mutation: Mutation) -> Result:
    """Apply one mutation, run the selection, restore the file."""
    original = mutation.path.read_text(encoding="utf-8")
    mutated = original.replace(mutation.old, mutation.new, 1)
    if mutated == original:
        return Result(mutation=mutation, applied=False, exit_code=-1)

    _IN_FLIGHT[0] = (mutation.path, original)
    try:
        mutation.path.write_text(mutated, encoding="utf-8", newline="")
        code, out = run_pytest()
    finally:
        mutation.path.write_text(original, encoding="utf-8", newline="")
        _IN_FLIGHT[0] = None
    return Result(mutation=mutation, applied=True, exit_code=code, output=out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="run only this mutation group, e.g. M1")
    parser.add_argument(
        "--check-targets",
        dest="check_targets",
        action="store_true",
        help="alias for --list: the sweep-wide check-only flag (O-138)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the mutation catalogue and the check_targets verdict, then exit",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _restore_in_flight)
    signal.signal(signal.SIGINT, _restore_in_flight)

    print("=" * 78)
    print("mutation sweep: next_catalyst_calendar (D-065)")
    print("FOREGROUND ONLY -- this rewrites files under src/ while it runs.")
    print("=" * 78)

    mutations = build_mutations()
    problems = check_targets(mutations)
    if problems:
        print(
            "\nREFUSING TO RUN: check_targets found absent or ambiguous targets. "
            "A sweep that mutates the wrong site reports survivors that mean "
            "nothing (D-048)."
        )
        return 2

    landing_problems = check_anchor_landings(mutations)
    if landing_problems:
        print(
            "\nREFUSING TO RUN: an anchor lands in a function this increment does "
            "not own. The mutant would rewrite a neighbour, the tests that catch it "
            "are not in this selection, and the sweep would report a survivor about "
            "code nobody mutated (O-67)."
        )
        return 2

    test_problems = check_tests_collect()
    if test_problems:
        print("\nREFUSING TO RUN: the test selection is broken, so exit codes")
        print("would not distinguish a kill from a harness error:")
        for p in test_problems:
            print(f"  !! {p}")
        return 2
    print(f"test selection collects cleanly: {', '.join(PYTEST_TARGETS)}")

    if args.list or args.check_targets:
        for mt in mutations:
            print(f"  {mt.group:4} {mt.path.name:20} {mt.name}")
        return 0

    if args.group:
        mutations = [mt for mt in mutations if mt.group == args.group]
        if not mutations:
            print(f"no mutations in group {args.group}")
            return 2
        print(f"restricted to group {args.group}: {len(mutations)} mutation(s)")

    # O-103: the sidecar is the interrupt defence with real reach here. On
    # win32 no Python signal handler runs for SIGTERM/SIGINT and a killed
    # process gets no `finally` turn, so `_restore_in_flight` above cannot
    # fire. This runs after the early returns so a run that mutates nothing
    # leaves no sidecar behind, and it heals a previous kill BEFORE the
    # baseline is read -- reading first would adopt a mutant as the baseline
    # (D-081).
    with sweep_lifecycle(sorted({mt.path for mt in mutations})):
        return _run_sweep(mutations)


def _run_sweep(mutations: list[Mutation]) -> int:
    results: list[Result] = []
    for mt in mutations:
        print(f"\n--- {mt.group} {mt.name}")
        res = apply_and_test(mt)
        results.append(res)
        if not res.applied:
            print("    NOT APPLIED (no-op)")
        elif res.killed:
            first_fail = next(
                (ln for ln in res.output.splitlines() if ln.startswith("FAILED")),
                "(see output)",
            )
            print(f"    KILLED  {first_fail}")
        else:
            print("    SURVIVED")

    killed = sum(1 for r in results if r.applied and r.killed)
    survived = [r for r in results if r.applied and not r.killed]
    noop = [r for r in results if not r.applied]

    print("\n" + "=" * 78)
    print(f"applied {len(results) - len(noop)} / {len(results)}")
    print(f"killed  {killed}")
    print(f"survived {len(survived)}")

    # D-064's lesson 93: a mutation that was never APPLIED silently leaves the
    # denominator, and a sweep that does not say so can certify a run it did not
    # perform. The D-064 sweep printed "applied 25 / 27" and still certified.
    if noop:
        print("\nREFUSING TO CERTIFY: the following mutations were NOT APPLIED.")
        print("Their target text produced no change, so they tested nothing and")
        print("their absence from the survivor list is not evidence (lesson 93).")
        for r in noop:
            print(f"  !! {r.mutation.name}")
        return 2

    defects: list[str] = []
    if survived:
        print("\nsurvivors, classified:")
        for r in survived:
            name = r.mutation.name
            proof = r.mutation.inert_proof or _INERT_PROOFS.get(name, "")
            if not proof:
                defects.append(name)
                print(f"  [NO PROOF] {name}")
                continue
            tag = "control" if "CONTROL" in name else "inert"
            print(f"  [{tag}] {name}")
            for line in proof.splitlines():
                print(f"           {line}")

    print()
    if defects:
        print(
            "REFUSING TO CERTIFY: the following survivors carry no proof. An "
            "exemption must be an argument, not a label (O-42)."
        )
        for d in defects:
            print(f"  !! {d}")
        return 2

    control_name = "M7.1 the FOMC entry string is rebuilt with the same parts (CONTROL)"
    control = next((r for r in results if r.mutation.name == control_name), None)
    if control is not None and control.killed:
        print(
            "REFUSING TO CERTIFY: the honesty control was killed. The sweep is "
            "reporting kills it cannot justify, so no other number means anything."
        )
        return 2

    print("RESULT: every survivor is either expected or proven inert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
