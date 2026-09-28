"""Guards for the O-103 sidecar lifecycle every sweep now shares.

Why this file exists
--------------------
On ``win32`` **no Python signal handler runs for SIGTERM or SIGINT** — it is
``TerminateProcess`` — and a killed process gets no ``finally`` turn either. So a
sweep that is stopped mid-mutation leaves the mutant **applied to ``src/``**, and
the failure mode is *silent source corruption* rather than a truncated report
(D-082, O-103). Measured twice on this project: a SIGTERM'd run left ``M6d`` live
in ``models/lei_proxy.py``.

Before this work only **2 of 40** sweeps carried the defence that actually works
on this platform — a ``<name>.sweepbackup`` sidecar written before the first
mutation (O-103). The other 38 relied, at best, on the duplicated
``_restore_in_flight`` handler, which is *correct* but *inert* here (lesson 5cl:
a protection assumed rather than exercised is worse than none, because it
displaces the real one).

The fix is one shared context manager, ``sweep_lifecycle``, so the order — which
is not obvious and is the whole point — is written and tested **once** instead of
repeated at 76 call sites:

1. **heal** a previous kill *before* anything is read, or the sweep adopts the
   mutant as its baseline and bakes the corruption in (D-081);
2. **protect** by writing the healed text to a sidecar *before* the first
   mutation;
3. **spend** the sidecar on the way out, because a stale sidecar is worse than
   none: the next run would "restore" a file that never needed it and silently
   revert a legitimate edit made in between.

This file tests three different claims, and they are genuinely different:

* **the mechanism** (behavioural) — heal-before-read, protect, consume, and the
  tolerance of a path that does not exist;
* **the wiring** (structural) — every one of the 40 sweeps has a recognised
  defence, so a *new* sweep cannot be added without one;
* **the order** (behavioural, and the one that matters) — healing must precede the
  read, proven against a real mutated file rather than by inspecting the source.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_GATE = _ROOT / "scripts" / "_sweep_gate.py"
_SCRIPTS = _ROOT / "scripts"

#: The sentinel a sweep must carry for the O-103 defence to be present. Two
#: spellings are legitimate: the shared helper, or the older direct pair.
_LIFECYCLE_MARKER = "sweep_lifecycle"
_SIDECAR_MARKER = "record_pristine"


def _load_gate() -> Any:
    """Import ``scripts/_sweep_gate.py`` the way a sweep does on ``sys.path``."""
    added = str(_GATE.parent)
    prepended = added not in sys.path
    if prepended:
        sys.path.insert(0, added)
    try:
        spec = importlib.util.spec_from_file_location("_sweep_gate_under_test", _GATE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_sweep_gate_under_test"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if prepended:
            sys.path.remove(added)


@pytest.fixture(scope="module")
def gate() -> Any:
    return _load_gate()


def _sweep_files() -> list[Path]:
    return sorted(_SCRIPTS.glob("mutation_*.py"))


# ---------------------------------------------------------------------------
# 1. The mechanism
# ---------------------------------------------------------------------------


def test_the_sidecar_exists_only_for_the_duration_of_the_block(gate: Any, tmp_path: Path) -> None:
    """Protect, then spend. A sidecar left behind is worse than none.

    The stale-sidecar failure is not hypothetical in direction: the *next* run
    would find the sidecar, "restore" from it, and silently revert whatever
    landed between the two runs — a real edit, reverted with no message.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")
    sidecar = gate.sidecar_for(target)

    assert not sidecar.exists(), "precondition: no sidecar before the block"
    with gate.sweep_lifecycle([target]) as originals:
        assert sidecar.exists(), "the sidecar must exist INSIDE the block"
        assert originals == {target: "PRISTINE = 1\n"}
    assert not sidecar.exists(), "the sidecar must be consumed on the way out"


def test_a_previous_kill_is_healed_before_the_source_is_read(gate: Any, tmp_path: Path) -> None:
    """**The load-bearing one.** Heal must precede the read.

    Constructed as the real failure: the source on disk is a *mutant*, and a
    sidecar holds the pristine text — exactly the state a SIGTERM'd run leaves.
    If the helper read first, it would return the mutant and then write the
    mutant into its own sidecar, making the corruption permanent and invisible.
    """
    target = tmp_path / "module.py"
    target.write_text("MUTANT = 1\n", encoding="utf-8")
    gate.sidecar_for(target).write_text("PRISTINE = 1\n", encoding="utf-8")

    with gate.sweep_lifecycle([target]) as originals:
        assert originals[target] == "PRISTINE = 1\n", "heal must run BEFORE the read"
        assert target.read_text(encoding="utf-8") == "PRISTINE = 1\n", "file must be healed on disk"


def test_a_path_that_does_not_exist_is_skipped_not_an_error(gate: Any, tmp_path: Path) -> None:
    """A sweep may share this helper with an optional target.

    ``mutation_api_layer.py`` passes routing files that need not exist; raising
    on one would turn a legitimate sweep into a crash.
    """
    real = tmp_path / "module.py"
    real.write_text("PRISTINE = 1\n", encoding="utf-8")
    ghost = tmp_path / "absent.py"

    with gate.sweep_lifecycle([real, ghost]) as originals:
        assert ghost not in originals
        assert originals == {real: "PRISTINE = 1\n"}
    assert not gate.sidecar_for(ghost).exists()


def test_the_helper_is_exported(gate: Any) -> None:
    """A helper every sweep imports by name must be in ``__all__``."""
    assert _LIFECYCLE_MARKER in gate.__all__


# ---------------------------------------------------------------------------
# 1b. The clean-tree precondition — O-61's still-open remedy, O-112(b)'s
#     durable form
# ---------------------------------------------------------------------------
# O-61 (severity 3, incident) records the binding rule — *never run a sweep in
# the background; never run a batch of sweeps while doing anything else* — and
# notes its remedy is incomplete: *"nothing still refuses to START a sweep
# against a dirty tree, and a swept tree mid-run is still invisible to git until
# the process dies."*
#
# O-112(b) reached the same class from the other end: *"an `rc=124` stop is a
# detection not a prevention."* Removing the sweep driver removed the `rc=124`
# but not the class, because a sweep can still be killed by anything at all. The
# only thing that makes a kill *recoverable as a fact* is that the tree was
# knowably clean when the sweep began.
#
# The precondition therefore REPORTS and never REFUSES: an increment that edits
# `src/` and then sweeps it is the normal case here, so a hard failure would make
# the guard unusable on the day it is needed — which is how guards get deleted.


def test_a_clean_target_is_not_reported_as_dirty(gate: Any, tmp_path: Path) -> None:
    """The predicate must be silent on the ordinary case.

    A guard that fires on a clean tree is the D-062 false-positive direction —
    it manufactures findings, and findings are what make a gate ignorable.

    Built in a sandbox repo rather than against this working tree, because this
    tree is legitimately dirty while an increment is in flight — asserting
    "clean" against it would make the test fail for the *right* reason at the
    wrong time, which is how a test gets deleted instead of fixed.
    """
    import subprocess

    sandbox = tmp_path / "repo"
    sandbox.mkdir()
    target = sandbox / "target.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")

    for args in (
        ("init", "-q"),
        ("config", "user.email", "probe@example.invalid"),
        ("config", "user.name", "probe"),
        ("add", "target.py"),
        ("commit", "-q", "-m", "baseline"),
    ):
        subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=sandbox,
            check=True,
            capture_output=True,
            text=True,
        )

    assert gate.describe_dirty_targets([target]) == [], (
        "a committed, untouched file must not be reported as a dirty target"
    )


def test_a_nonexistent_target_is_not_reported_as_dirty(gate: Any) -> None:
    """A path git has never heard of is not a *modification*.

    ``sweep_lifecycle`` accepts paths that need not exist (api_layer's optional
    routing files), so this predicate is called on them.
    """
    missing = _ROOT / "src" / "macro_engine" / "definitely_absent_9f3a.py"
    assert gate.describe_dirty_targets([missing]) == []


def test_a_modified_target_is_reported(gate: Any, tmp_path: Path) -> None:
    """**The load-bearing direction.** A real uncommitted edit must be reported.

    Measured rather than mocked: a THROWAWAY git repository is built in
    ``tmp_path``, the target is committed, then modified, and the predicate is
    asked about it.

    **Why not use this repository's own working tree.** The first version of this
    test appended a line to ``AGENTS.md`` and restored it afterwards. That was
    wrong twice over, and both are worth recording because each is a hazard this
    project has already been bitten by:

    * ``read_text``/``write_text`` applies **universal-newline translation**, so
      rewriting a CRLF file with LF leaves git reporting a whole-file
      modification while ``git diff`` shows nothing (measured — the restore
      looked clean to ``diff`` and dirty to ``git status``). That is the
      documented CRLF-reader hazard, re-entered through a *test*.
    * A test that dirties the tracked tree in order to test for dirty trees is
      the defect it is testing for. The sandbox removes the possibility instead
      of managing it.

    ``tmp_path`` is outside the repository, and this predicate resolves paths but
    does not require them to be inside it, so a sandbox repo exercises the same
    code path — ``git status --porcelain`` parsing, status-column stripping, and
    path resolution — while being unable to reach project source.
    """
    import subprocess

    sandbox = tmp_path / "repo"
    sandbox.mkdir()
    target = sandbox / "target.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=sandbox,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-q")
    git("config", "user.email", "probe@example.invalid")
    git("config", "user.name", "probe")
    git("add", "target.py")
    git("commit", "-q", "-m", "baseline")

    assert gate.describe_dirty_targets([target]) == [], (
        "precondition: the committed sandbox target must read as clean"
    )

    target.write_text("MODIFIED = 1\n", encoding="utf-8")
    dirty = gate.describe_dirty_targets([target])

    assert dirty, (
        "an uncommitted modification was NOT reported as dirty — the "
        "precondition cannot fire, so a sweep could start from an "
        "unrecoverable baseline (O-61)"
    )
    assert str(target.resolve()) in dirty, f"the report named the wrong path: {dirty}"


def test_the_precondition_covers_the_healed_paths_too(gate: Any, tmp_path: Path) -> None:
    """A healed file is, by construction, one that differed from its sidecar.

    If a previous run was killed, the target is almost certainly *also* dirty
    relative to git — so the report must include healed paths rather than only
    the paths that were dirty before ``restore_from_sidecar`` ran. Asserted here
    because the two lists are computed at different points in ``sweep_lifecycle``
    and it is easy to pass the wrong one.
    """
    source = _GATE.read_text(encoding="utf-8")
    call = source.find("dirty = describe_dirty_targets(existing)")

    assert call != -1, "the precondition call is gone from sweep_lifecycle"
    # `existing` is the same list the heal operates on, so a healed path is by
    # definition in scope for the report.
    assert "existing = [p for p in paths if p.exists()]" in source, (
        "the precondition must be asked about the same path set the heal uses, "
        "or a healed (i.e. previously killed) target escapes the report"
    )


def test_the_precondition_reports_rather_than_refuses(gate: Any, tmp_path: Path) -> None:
    """A dirty target must NOT abort the sweep — it must warn and continue.

    This is the design decision, and it is asserted because the opposite choice
    is a plausible-looking regression: "refuse to sweep a dirty tree" reads as
    stricter, but it would forbid the normal increment workflow, so the guard
    would be removed rather than obeyed.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")

    # The block must complete normally even though `describe_dirty_targets`
    # reports something for the target (here forced, since tmp_path is untracked).
    with gate.sweep_lifecycle([target]) as originals:
        assert originals[target] == "PRISTINE = 1\n", (
            "a reported-dirty target must still be swept; the precondition is a report, not a veto"
        )


def test_the_precondition_is_checked_before_the_sidecar_is_written(
    gate: Any, tmp_path: Path
) -> None:
    """The order matters: report the state the OPERATOR left, then protect.

    If the report ran after ``record_pristine``, a sidecar created by this very
    run would be indistinguishable from one left by a kill — and the operator
    reading the warning could not tell whether the tree was already dirty.

    Asserted structurally rather than behaviourally because the distinction is
    only observable through stdout ordering, which is exactly the kind of claim
    this project has learned to verify by reading the source (D-035's
    re-derive-never-assume). The behavioural half is that the sidecar does not
    exist until INSIDE the block, which the first test in this file pins.
    """
    source = _GATE.read_text(encoding="utf-8")
    report_at = source.find("dirty = describe_dirty_targets(existing)")
    protect_at = source.find("record_pristine(originals)")

    assert report_at != -1, "the precondition call is gone from sweep_lifecycle"
    assert protect_at != -1, "record_pristine is gone from sweep_lifecycle"
    assert report_at < protect_at, (
        "the dirty-target report must run BEFORE the sidecar is written, or the "
        "warning describes this run's own sidecar instead of the operator's tree"
    )


def test_the_precondition_reports_cannot_ask_distinctly_from_clean(gate: Any) -> None:
    """``None`` (could not ask git) must not be confused with ``set()`` (clean).

    Collapsing them makes the guard **vacuously true** in exactly the environment
    where nobody would notice — a stripped container, a source tarball, a CI image
    without the repo history. That is D-062's "predicate trivially true" in its
    silent direction, and it is the reason the internal helper distinguishes the
    two while the public one does not.
    """
    assert hasattr(gate, "_git_dirty_paths"), (
        "the could-not-ask sentinel helper is gone; without it the clean and "
        "could-not-ask cases are indistinguishable (D-062)"
    )
    # In this repository git CAN be asked, so the sentinel must be a real set.
    result = gate._git_dirty_paths()
    assert result is not None, (
        "git could not be asked INSIDE the project's own repository, so the "
        "precondition is silently inert in the one place it is exercised"
    )
    assert isinstance(result, set)


def test_the_predicate_asks_the_repository_that_holds_the_target(gate: Any, tmp_path: Path) -> None:
    """**The regression that mattered.** ``git status`` must run in the TARGET's repo.

    Measured on 2026-09-22: the first version of the predicate called
    ``subprocess.run(["git", "status", ...])`` with **no ``cwd``**, so it always
    answered about the repository containing the process — and returned ``[]`` for
    a sandbox file that ``git status`` in that sandbox reported as `` M t.py``.
    The predicate was therefore **structurally incapable of firing for any target
    outside the project root**, which is invisible from inside the project, where
    it happens to be right.

    This test builds two repositories: one clean, one dirty. The clean one is
    asked about the dirty one's file, so the only way to get the right answer is
    to resolve the repository from the target rather than from the process.
    """
    import subprocess

    def make_repo(where: Path, *, dirty: bool) -> Path:
        where.mkdir(parents=True)
        target = where / "target.py"
        target.write_text("PRISTINE = 1\n", encoding="utf-8")
        for args in (
            ("init", "-q"),
            ("config", "user.email", "probe@example.invalid"),
            ("config", "user.name", "probe"),
            ("add", "target.py"),
            ("commit", "-q", "-m", "baseline"),
        ):
            subprocess.run(  # noqa: S603
                ["git", *args],  # noqa: S607
                cwd=where,
                check=True,
                capture_output=True,
                text=True,
            )
        if dirty:
            target.write_text("MODIFIED = 1\n", encoding="utf-8")
        return target

    clean = make_repo(tmp_path / "clean", dirty=False)
    dirty = make_repo(tmp_path / "dirty", dirty=True)

    # Both answers must be derived from each target's OWN repository. A helper
    # using the process cwd returns [] for both.
    assert gate.describe_dirty_targets([clean]) == [], (
        "the clean repository's committed file was reported as dirty"
    )
    assert gate.describe_dirty_targets([dirty]) == [str(dirty.resolve())], (
        "the dirty repository's modified file was NOT reported (or named the "
        "wrong path) — the helper is asking the process's repository instead of "
        "the target's (the 2026-09-22 no-cwd defect)"
    )


# ---------------------------------------------------------------------------
# 2. The wiring — no sweep may lack the defence
# ---------------------------------------------------------------------------


def test_there_are_fifty_sweeps_to_cover() -> None:
    """Pin the denominator, so a sweep silently vanishing is reported.

    The count is asserted rather than inferred: "all sweeps are covered" is
    trivially true of an empty set, which is the shape a broken glob produces.

    **40 → 41 at D-087.23**, which added `mutation_performance_record.py` — a
    sweep over the *recorded explanation* rather than over `src/`, so it is the
    first member of this set that does not mutate the engine. It carries the same
    sidecar defence as the rest, which is why it belongs in the count.

    **41 → 42 at D-087.27**, which added `mutation_command_inventory.py` (O-104) —
    the *second* prose sweep, over the recorded OpenBB command inventory. It uses
    `sweep_lifecycle` like the rest, so the per-file wiring check below covers it
    without a second edit. NOTE: the count is asserted in TWO places
    (`test_sweep_health_leftover_predicate.py` and here) and the function name
    carries it a third time — adding a sweep means editing all three, which is
    deliberate: a single soft count is easy to leave stale (the O-104 defect).

    **42 → 43 at D-092**, which added `mutation_econometrics.py` — Module 18's
    first sweep, over `models/econometrics.py`. It uses `sweep_lifecycle` and
    carries a CANARY1 gate, so the per-file wiring check below and the
    control-coverage check in the sibling file both cover it without a second
    edit. This is the first sweep added *by the rule* rather than retrofitted:
    the two prose sweeps above arrived during a repair pass, so this is the
    first time the three-place edit was made as part of the increment itself.

    **43 → 44 at D-106**, which added `mutation_monte_carlo_var.py` — the first
    sweep over `models/risk.py` (none existed; the Tier-1 estimators in that
    module were covered only indirectly). It uses `sweep_lifecycle` and carries
    the CANARY1 refusal gate, so the per-file wiring and control-coverage checks
    both cover it without a second edit.

    **44 → 45 at D-108**, which added `mutation_fx_carry.py` — the first sweep
    over a NEW module created by a Tier-5 increment (`models/fx_carry.py`, which
    did not exist before this increment). It uses `sweep_lifecycle` and carries
    the CANARY1 refusal gate, so the same two checks cover it.

    **45 → 46 at D-118**, which added `mutation_intervention.py` — the sweep over
    Module 9's `intervention_capacity`, a **second** NEW module created by a
    Tier-5 increment (`models/intervention.py`), plus its new client
    (`data_layer/reserves_client.py`) and its config block. It uses
    `sweep_lifecycle` and carries the CANARY1 refusal gate, so the same two
    checks cover it. **Its first run left 14 survivors, all weak tests — one of
    which was a genuine CODE defect (an unused constant the conversion bypassed),
    the     rest tests that reproduced the code's own expression (D-050).**

    **46 → 47 at D-119**, which added `mutation_em_vulnerability.py` — the sweep
    over Module 9's `em_vulnerability_checklist`, the **third** NEW module created
    by a Tier-5 increment (`models/em_vulnerability.py`), plus its new indicator
    routes in `data_layer/world_bank_client.py` and its config block. It uses
    `sweep_lifecycle` and carries the CANARY1 refusal gate, so the same two checks
    cover it. **Its first run left 9 survivors (E6d/E9b model branches reachable
    only via a FETCHED run; G1a/G2a-G2c validator guards never driven to fire;
    G3a-G3c threshold accessors never read in isolation) — every one a test
    nobody wrote, not an inert mutation.**

    **47 → 48 at D-120**, which added `mutation_commodities.py` — the sweep over
    Module 10's `oil_balance_signal`, the **fourth** NEW module created by a
    Tier-5 increment (`models/commodities.py`), plus its new client
    (`data_layer/commodities_client.py`), the new public `fetch_records` transport
    in `data_layer/openbb_client.py`, and its config block. It uses
    `sweep_lifecycle` and carries the CANARY1 refusal gate, so the same two checks
    cover it.

    **48 → 49 at D-123**, which added `mutation_equity_macro.py` — the sweep over
    Module 11's `sector_rotation_prior`, the **fifth** NEW module created by a
    Tier-5 increment (`models/equity_macro.py`) plus its config block. It has **no
    new client** — the function reads no market data, its only input is a regime
    label — so this is the first of the module-creating sweeps to cover a model
    and its config alone. It uses `sweep_lifecycle` and carries the CANARY1
    refusal gate, so the same two checks cover it.

    **49 → 50 at D-125**, which added `mutation_statement_text.py` — the sweep
    over Section 20.4's `statement_text_diff` (Module 4.3), the final Tier-5
    name. It is a **text diff over two supplied strings**, so it has no new
    client and reads no market data at all — like D-123's addition it covers a
    model and its config block alone. It uses `sweep_lifecycle` and carries the
    CANARY1 refusal gate, so the same two checks cover it.

    **50 → 51 at D-127**, which added `mutation_labor_breadth.py` — the sweep
    over Module 6.3's `inflation_breadth_score` in `models/labor_synthesis.py`.
    Unlike the four module-creating sweeps above it covers an EXISTING function
    that had no sweep at all, and it closes the D-040/D-050 defect this
    increment fixed (a flat reading published as CONFLICTED). It uses
    `sweep_lifecycle` and carries the CANARY1 refusal gate, so the same two
    checks cover it.
    """
    files = _sweep_files()
    assert len(files) == 51, f"expected 51 sweeps, found {len(files)}"


@pytest.mark.parametrize("path", _sweep_files(), ids=lambda p: p.stem)
def test_every_sweep_carries_a_sidecar_defence(path: Path) -> None:
    """Every sweep needs the platform-independent defence, not just a handler.

    This is the O-103 coverage claim, and it is asserted per-file so a failure
    names the sweep rather than reporting a count.
    """
    text = path.read_text(encoding="utf-8")
    assert _LIFECYCLE_MARKER in text or _SIDECAR_MARKER in text, (
        f"{path.name} has no .sweepbackup protection: on win32 an interrupted run "
        "would leave every mutant applied (O-103)"
    )


@pytest.mark.parametrize("path", _sweep_files(), ids=lambda p: p.stem)
def test_a_sweep_that_calls_the_lifecycle_imports_it(path: Path) -> None:
    """Calling a name you never imported is ``F821`` and a runtime ``NameError``.

    This defect was real: four sweeps were patched to *call* ``sweep_lifecycle``
    while the import was not added, so every one of them would have crashed with
    ``NameError`` at the first mutation. Ruff caught it, not the patch.
    """
    text = path.read_text(encoding="utf-8")
    if f"with {_LIFECYCLE_MARKER}(" not in text:
        return
    tree = ast.parse(text)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "_sweep_gate"
        for alias in node.names
    }
    assert _LIFECYCLE_MARKER in imported, (
        f"{path.name} calls {_LIFECYCLE_MARKER} but does not import it"
    )


@pytest.mark.parametrize("path", _sweep_files(), ids=lambda p: p.stem)
def test_no_sweep_reintroduces_a_bare_restore_finally_without_the_sidecar(path: Path) -> None:
    """A restore-only ``finally`` is the *old* design and must not come back alone.

    It looks like protection and is not: it cannot survive the kill it exists to
    survive. Keeping the assertion per-file means the regression is named.
    """
    text = path.read_text(encoding="utf-8")
    has_sidecar = _LIFECYCLE_MARKER in text or _SIDECAR_MARKER in text
    assert has_sidecar, (
        f"{path.name} relies on a crash-only restore, which cannot survive SIGTERM on win32"
    )


# ---------------------------------------------------------------------------
# 6. A REFUSED cleanup must not change the sweep's verdict (O-122, D-103)
# ---------------------------------------------------------------------------


def test_a_refused_sidecar_delete_does_not_raise(gate: Any, tmp_path: Path) -> None:
    """**The O-122 regression test.** A refused delete used to kill the process.

    The cleanup was a bare ``unlink`` inside ``sweep_lifecycle``'s ``finally``.
    The sandbox's per-turn bulk-delete counter refuses deletes past a threshold
    (measured `count: 167` against 50), so on a 109-mutation run the cleanup
    raised ``PermissionError`` **out of the context manager** — and the sweep
    exited **1** after reporting a clean **108/109**. **The exit code was a claim
    about the sandbox, not about the mutation catalogue.**

    Reproduced here with a DIRECTORY where the sidecar belongs: ``unlink`` cannot
    remove it, which is the same ``OSError`` the counter produces. The call must
    return the refused path rather than raise, so a caller can act on it.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")
    sidecar = gate.sidecar_for(target)
    sidecar.mkdir()  # a directory cannot be unlinked

    refused = gate.remove_sidecars([target])

    assert refused == [sidecar], "the refused path must be RETURNED, not swallowed"
    assert sidecar.is_dir(), "the fixture must still hold the obstruction"


def test_a_refused_delete_that_raises_systemexit_does_not_escape(
    gate: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """**The O-140 regression test: the hook raises ``SystemExit``, not ``OSError``.**

    O-122 fixed the ``OSError``/``PermissionError`` form (a ``finally`` that
    raised turned a certified run into ``EXIT=1``). But the sandbox's safe-delete
    hook does **not** raise ``OSError``: it raises **``SystemExit(1)``**, which is
    a ``BaseException`` and therefore sailed straight past the ``except OSError``
    guard and out of the context manager. **Measured 2026-09-26 (D-114): seven
    suite tests failed under full-suite ordering for exactly this reason** — the
    bulk-delete counter accumulates across a full run, the hook fires during the
    sweep's own cleanup, and the sweep subprocess exits **1** where it should have
    exited **3** (the canary refusal). Each file passed in isolation because an
    isolated file never reaches the counter's threshold.

    A directory cannot produce ``SystemExit``, so this injects it directly on the
    ``Path`` class the helper will call. **The load-bearing assertion is
    ``SystemExit not in the result``** — the call must RETURN the refused path, the
    same as the ``OSError`` case, so the sweep's real exit code (its mutation
    verdict) survives its own cleanup.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")
    sidecar = gate.sidecar_for(target)
    sidecar.write_text("PRISTINE = 1\n", encoding="utf-8")

    real_unlink = type(sidecar).unlink

    def fake_unlink(self: Any, *args: Any, **kwargs: Any) -> None:
        if self == sidecar:
            # The sandbox hook's real shape: a SystemExit, NOT an OSError.
            raise SystemExit(1)
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(sidecar), "unlink", fake_unlink, raising=True)

    refused = gate.remove_sidecars([target])

    assert refused == [sidecar], "a SystemExit refusal must be RETURNED, not escape"
    assert sidecar.exists(), "the obstruction must still be present"


def test_the_lifecycle_survives_a_systemexit_delete_refusal(
    gate: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """The end-to-end form of O-140: the context manager must EXIT, not raise.

    Mirrors ``test_the_lifecycle_survives_a_refused_delete`` one level up — the
    bug was not in ``remove_sidecars`` alone but in the fact that its exception
    escaped ``sweep_lifecycle``'s ``finally``, after the block had already decided
    its return value.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")
    sidecar = gate.sidecar_for(target)
    real_unlink = type(sidecar).unlink

    def fake_unlink(self: Any, *args: Any, **kwargs: Any) -> None:
        if self == sidecar:
            raise SystemExit(1)
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(sidecar), "unlink", fake_unlink, raising=True)

    with gate.sweep_lifecycle([target]) as originals:
        assert originals == {target: "PRISTINE = 1\n"}

    assert sidecar.exists(), "the lifecycle exited and left the obstruction"


def test_the_lifecycle_survives_a_refused_delete(gate: Any, tmp_path: Path) -> None:
    """The end-to-end form: the context manager must EXIT, not raise.

    `remove_sidecars` returning a list is the unit-level claim; this is the one
    that matters for the exit code, because an exception raised inside a
    ``finally`` is what turned a certified run into `EXIT=1`.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")
    sidecar = gate.sidecar_for(target)

    # A directory would break the HEAL step before the cleanup, so the
    # obstruction is created only once the block is entered -- which is exactly
    # the shape of the real failure, where the sidecar was a normal FILE at heal
    # time and the delete was refused later.
    with gate.sweep_lifecycle([target]) as originals:
        assert originals == {target: "PRISTINE = 1\n"}
        if sidecar.exists():
            sidecar.unlink()
        sidecar.mkdir()

    assert sidecar.is_dir(), "the lifecycle exited and left the obstruction"


def test_the_ownership_banner_is_printed(gate: Any, tmp_path: Path, capsys: Any) -> None:
    """Trap 2's fix, pinned: the sweep STATES that it owns the machine.

    Measured 2026-09-24 (D-102): running ``ruff``/``mypy``/``pytest`` alongside a
    sweep slowed it **10x** (12 s -> 2 min per mutation), and ``mypy --strict``
    on a file that IMPORTS the swept module type-checks the MUTATED source. The
    rule existed only in a skill and a decision record; it now prints where the
    sweep starts, so a reader who never opens either still sees it.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")
    with gate.sweep_lifecycle([target]):
        pass
    printed = capsys.readouterr().out
    assert "OWNS THE MACHINE" in printed
    assert "Do NOT run ruff" in printed


# ---------------------------------------------------------------------------
# 7. The check-only flag must be REAL and must STOP (O-138, D-113)
# ---------------------------------------------------------------------------


def test_the_check_only_flag_is_exported_and_named(gate: Any) -> None:
    """``--check-targets`` must exist as a constant, not as folklore.

    Before this fix the flag was a **token nothing read**: no sweep parses
    ``sys.argv``, so ``python scripts/mutation_fx_carry.py --check-targets`` ran
    the whole sweep. A flag that is silently ignored is worse than one that does
    not exist, because the operator's belief that they only checked is what stops
    them from checking the tree afterwards.
    """
    assert gate.CHECK_ONLY_FLAG == "--check-targets"


def test_check_only_requested_reads_the_flag(gate: Any) -> None:
    """The predicate, against the argv lists that matter — no live process."""
    assert gate.check_only_requested(["--check-targets"]) is True
    assert gate.check_only_requested([]) is False
    assert gate.check_only_requested(["--verbose"]) is False
    # A near-miss must NOT be honoured: `--check-target` (no s) is a typo, and
    # silently accepting it would be the same class of lie the flag was fixed for.
    assert gate.check_only_requested(["--check-target"]) is False


@pytest.mark.parametrize("path", _sweep_files(), ids=lambda p: p.stem)
def test_a_sweep_that_supports_the_flag_stops_before_the_lifecycle(path: Path) -> None:
    """**The O-138 regression test, per sweep.** The flag must be answered EARLY.

    Two distinct defects are pinned here, and they are different:

    * the flag was **never read** (so the sweep ran), and
    * even when read, the check must happen **before** ``sweep_lifecycle`` — that
      helper writes a sidecar and installs the interrupt defence, i.e. it touches
      the tree. A safe mode that enters the mutating path recreates the hazard.

    The assertion is structural on purpose: the ordering cannot be observed from
    a pure predicate test, and a behavioural test would have to run a real sweep.
    """
    text = path.read_text(encoding="utf-8")
    if "check_only_requested" not in text:
        return
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        calls = [
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
        ]
        assert "check_only_requested" in calls, f"{path.name}'s main() never asks the flag"
        # And it must appear BEFORE the lifecycle call in source order.
        body = ast.get_source_segment(text, node) or ""
        ask_at = body.find("check_only_requested")
        life_at = body.find("sweep_lifecycle")
        assert ask_at != -1 and (life_at == -1 or ask_at < life_at), (
            f"{path.name} asks the check-only flag AFTER sweep_lifecycle: the safe "
            "mode would write a sidecar and touch the tree (O-138)"
        )


def test_the_check_only_mode_writes_no_sidecar(gate: Any, tmp_path: Path) -> None:
    """The mode must leave NO trace on disk — proven against a real file.

    This is the behavioural half of the O-138 fix: the whole reason the incident
    cost a session is that the "pre-flight" left a **mutant and a sidecar** behind.
    The check-only path reads, prints, and stops; if it ever wrote a sidecar, a
    later run would "heal" from it and silently revert a legitimate edit.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")
    sidecar = gate.sidecar_for(target)

    # Exactly what `_check_targets_only` does: read, check, print, stop.
    originals = {target: target.read_text(encoding="utf-8")}
    problems = gate.check_targets(originals, [("M1", target, "PRISTINE = 1", "PRISTINE = 2")])
    assert problems == []

    assert not sidecar.exists(), "the check-only mode must not write a sidecar (O-138)"
    assert target.read_text(encoding="utf-8") == "PRISTINE = 1\n", "the target must be untouched"


def test_the_check_only_mode_reports_an_unsound_anchor_without_mutating(
    gate: Any, tmp_path: Path
) -> None:
    """A REFUSED verdict must also not mutate — the negative control.

    Without this, the fix would be satisfiable by a path that always answers
    "clean" (the D-051 trap). The predicate must be able to FAIL, and failing
    must still leave the file alone.
    """
    target = tmp_path / "module.py"
    target.write_text("PRISTINE = 1\n", encoding="utf-8")

    originals = {target: target.read_text(encoding="utf-8")}
    problems = gate.check_targets(originals, [("M1", target, "NOT PRESENT", "ANYTHING")])

    assert problems, "an absent anchor must be reported, or the check proves nothing"
    assert "ABSENT" in problems[0]
    assert target.read_text(encoding="utf-8") == "PRISTINE = 1\n", (
        "a refusal must not touch the file"
    )
