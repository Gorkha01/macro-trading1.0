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
# 2. The wiring — no sweep may lack the defence
# ---------------------------------------------------------------------------


def test_there_are_forty_one_sweeps_to_cover() -> None:
    """Pin the denominator, so a sweep silently vanishing is reported.

    The count is asserted rather than inferred: "all sweeps are covered" is
    trivially true of an empty set, which is the shape a broken glob produces.

    **40 → 41 at D-087.23**, which added `mutation_performance_record.py` — a
    sweep over the *recorded explanation* rather than over `src/`, so it is the
    first member of this set that does not mutate the engine. It carries the same
    sidecar defence as the rest, which is why it belongs in the count.
    """
    files = _sweep_files()
    assert len(files) == 41, f"expected 41 sweeps, found {len(files)}"


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
