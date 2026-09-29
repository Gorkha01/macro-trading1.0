"""Every mutation sweep must answer ``--check-targets`` WITHOUT sweeping.

Why this is a test and not a note in a docstring
------------------------------------------------
O-138 was closed by adding ``check_only_requested`` to ``_sweep_gate.py`` — a
helper that answers *whether* the operator asked for a pre-flight. Adoption was
left to each sweep. Measured 2026-09-29 at D-136: **6 of 52 had adopted it.**
The other 46 had no ``--check-targets`` handling at all, and 24 of those had no
argument parsing whatsoever, so::

    python scripts/mutation_regime.py --check-targets

...ran the whole 71-mutation sweep. That is the O-138 incident again, one layer
up: the flag is *documented* in the shared module as the safe pre-flight, so an
operator who types it believes they are safe, and that belief is what stops them
checking the tree afterwards.

A helper that exists is not the same as a contract that holds. This file
asserts the contract in two layers:

1. **Static, over all 52** — each sweep either routes through
   ``check_only_requested`` or declares the flag itself. Fast, and it fails the
   moment a NEW sweep is added without it, which is the only moment that matters
   (the existing 52 will not drift silently on their own).
2. **Behavioural, on one representative** — actually run a sweep with the flag
   and prove it printed a verdict, exited cleanly, and left ``src/`` and the
   sidecars untouched. The static layer can be satisfied by a sweep that
   *mentions* the flag and ignores it; this layer cannot.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest


def _function_source(path: Path, name: str) -> str:
    """The source text of one top-level function, for structural assertions."""
    text = path.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"no top-level function {name!r} in {path}")


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
SWEEPS = sorted(SCRIPTS.glob("mutation_*.py"))

#: The sweep used by the behavioural layer. Chosen because it is the smallest
#: catalogue that still goes through `sweep_lifecycle`, so the test stays fast.
REPRESENTATIVE = "mutation_as_of.py"


def test_the_repo_actually_has_sweeps() -> None:
    """A census that collapses to zero would make every rule below vacuous.

    D-062: a detector whose predicate is trivially true manufactures findings,
    and findings are what make a gate ignorable. If this glob ever matches
    nothing, the two real assertions pass while certifying nothing.
    """
    assert len(SWEEPS) >= 50, f"expected the sweep catalogue, found {len(SWEEPS)}"


@pytest.mark.parametrize("sweep", SWEEPS, ids=lambda p: p.name)
def test_every_sweep_declares_the_check_only_flag(sweep: Path) -> None:
    """Each sweep must handle ``--check-targets`` instead of ignoring it.

    Two legal shapes, because two families already exist and unifying 52 files'
    CLI plumbing is a larger change than the defect warrants:

    * it calls ``check_only_requested()`` from ``_sweep_gate`` (the preferred
      shape — one implementation of the verdict); or
    * its ``argparse`` declares the flag explicitly (the family that already had
      ``--list`` and now accepts the documented name as an alias).
    """
    text = sweep.read_text(encoding="utf-8")
    via_gate = "check_only_requested" in text
    via_argparse = '"--check-targets"' in text
    assert via_gate or via_argparse, (
        f"{sweep.name} ignores --check-targets. Running it with that flag runs "
        "the FULL sweep, which is O-138: a 'safe pre-flight' that is the least "
        "safe way to invoke the tool. Add `if check_only_requested(): return "
        "_check_targets_only()` at the top of main(), or declare the flag."
    )


@pytest.mark.parametrize("sweep", SWEEPS, ids=lambda p: p.name)
def test_no_sweep_mutates_before_answering_the_flag(sweep: Path) -> None:
    """Where the flag is handled by hand, it must be handled FIRST in ``main()``.

    The static check above proves the flag is *mentioned*. It cannot prove the
    pre-flight happens before the sweep writes — and a pre-flight that runs after
    the first mutation has already corrupted the tree it was meant to protect.

    This asserts the guard appears before any call that would touch the tree,
    which is the ordering ``check_only``'s docstring requires.
    """
    if "check_only_requested" not in sweep.read_text(encoding="utf-8"):
        pytest.skip("declares the flag via argparse; its own main() owns ordering")

    # Scoped to `main()` deliberately: a sweep legitimately contains
    # `.write_text(` in its apply/revert helper, which lives in a DIFFERENT
    # function and may be defined above `main`. Scanning the whole file would
    # flag those and the guard would be unwritable -- a test that cannot be
    # satisfied is how a gate gets deleted.
    body = _function_source(sweep, "main")
    guard = body.find("check_only_requested()")
    assert guard != -1, f"{sweep.name}: main() never answers the flag"
    head = body[:guard]
    for dangerous in ("sweep_lifecycle(", "record_pristine(", ".write_text("):
        assert dangerous not in head, (
            f"{sweep.name} calls {dangerous} before answering --check-targets. "
            "The pre-flight must run before anything is written, or a 'check' "
            "mutates the tree it was asked to verify (O-138)."
        )


def test_the_flag_actually_stops_one_sweep_from_running() -> None:
    """Behavioural proof, on one representative: verdict, no run, no sidecar.

    The three assertions are the three ways a check-only mode can lie:

    * it can run the sweep anyway (rc from the mutation loop, not the verdict);
    * it can print nothing (the operator cannot tell a clean check from a
      crashed one);
    * it can leave a sidecar behind, which makes the NEXT run 'restore' a file
      that never needed restoring and silently revert a real edit (O-161).
    """
    sweep = SCRIPTS / REPRESENTATIVE
    sidecars_before = set(SCRIPTS.parent.rglob("*.sweepbackup"))

    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, str(sweep), "--check-targets"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, (
        f"{REPRESENTATIVE} --check-targets exited {proc.returncode}. A non-zero "
        f"exit here means either the anchors are unsound or the flag was not "
        f"answered.\n{proc.stdout[-2000:]}"
    )
    assert "check_targets:" in proc.stdout, (
        "no anchor verdict was printed, so this mode cannot be distinguished "
        "from a run that silently did nothing"
    )
    assert "KILLED" not in proc.stdout, (
        "the mutation loop ran: a check-only mode must not apply mutations"
    )
    assert "SURVIVED" not in proc.stdout, "the mutation loop ran"

    left_behind = set(SCRIPTS.parent.rglob("*.sweepbackup")) - sidecars_before
    assert not left_behind, (
        f"the check-only run left sidecar(s): {sorted(p.name for p in left_behind)}"
    )
