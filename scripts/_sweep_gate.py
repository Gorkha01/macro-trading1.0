"""The shared ``check_targets`` gate: refuse to sweep a site you cannot prove.

**Why this module exists rather than 14 copies of the same function.**

``str.replace(old, new, 1)`` takes the FIRST occurrence. An ``old`` string that
appears twice therefore rewrites the *wrong site*, the file still changes, the
mutation *looks* applied, the tests still pass (they never exercised the mutated
path), and the sweep reports a SURVIVOR. The conclusion drawn is "the suite is
weak" when the truth is "the sweep aimed at the wrong symbol." That is D-048's
finding, and it is strictly worse than a pattern miss, because a miss is visible.

An ``old`` appearing ZERO times has two causes with **opposite remedies**, and
separating them is the whole point of this gate:

* the anchor **drifted** - the source moved out from under it, so the mutation
  cannot be applied and **this gate is off**; or
* the mutation is **still applied** - the anchor is absent *because the mutant
  replaced it*, and **the tree is mutated**.

They present identically as "0 occurrences". D-075 and D-081 both show the cost of
conflating them: two sessions hunted "stale anchors" while a live mutant sat in
the tree wearing that costume. The discriminator is the mutation's own replacement
text - a leftover has ``new`` present.

**This gate must live IN the sweep, not only in ``tools/sweep_health.py``.** The
external tool already runs an equivalent check, but a gate that exists only there
does not protect anyone who runs a sweep directly - and running a sweep directly
is the normal case. ``mutation_regime.py``'s own comment block records the
consequence: its anchors were ambiguous and "worked by luck" until an *external*
tool noticed.

Usage - both families of sweep in this directory reduce to 4-tuples::

    from _sweep_gate import check_targets, format_problems
    ...
    problems = check_targets(originals, _MUTATIONS)      # or _iter_mutations()
    print(f"check_targets: {len(_MUTATIONS)} mutations, {len(problems)} problem(s)")
    if problems:
        print(format_problems(problems))
        print()
        print("REFUSING TO RUN: fix the anchors above first. A sweep that")
        print("cannot prove it mutates the site it names certifies nothing.")
        return 4

Pass ``originals`` (the per-file pristine text the runner already read) so the
gate reads exactly what the sweep will mutate. Passing them is also what keeps
this consistent with ``tools/sweep_health.py``: the read must use
``Path.read_text`` / a text-mode open, because Python applies **universal-newline
translation** (CRLF to LF) and the sweeps anchor their ``old`` strings with
``\\n``. A bytes-based reader turns every LF anchor into a false ABSENT - measured
once at 87% of one tool's findings, all artefacts.

**The second obligation: a sweep must survive being killed.**

The ``finally`` block restores the file on a normal exit and on a Python
exception - but **not on ``SIGTERM``**, which terminates the process without
unwinding. And ``SIGTERM`` is exactly what a sweep gets in ordinary use, because
piping it anywhere truncating (``| head -n 8``, ``| grep``) closes the pipe and
kills the writer. Measured three times in one session: each time the tree was
left holding a mutant, and twice the leftover went unnoticed for a while.

``install_signal_restore`` closes that hole, and it is the *reason this module
holds two things rather than one*: both exist so that a gated sweep cannot lie -
the gate stops it from certifying a mutation it never applied, and the handler
stops it from leaving one behind. ``mutation_api_layer.py`` proved the design
(D-057 first run was killed by a ``SIGTERM`` that bypassed the ``finally``;
D-062 found the leftover with ``tools/sweep_health.py``; O-83 noted that scan is
per-sweep, so a leftover in a shared file is invisible). This is the
generalisation of that fix, so the older sweeps can share it.

Usage::

    from _sweep_gate import check_targets, format_problems, install_signal_restore
    ...
    install_signal_restore()                      # once, in main()
    ...
    try:
        target.write_text(pristine.replace(old, new, 1), ...)
        _SET_IN_FLIGHT(target, pristine)           # immediately after the write
        caught = not run_tests()
    finally:
        target.write_text(pristine, ...)
        _CLEAR_IN_FLIGHT()
"""

from __future__ import annotations

import signal
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = [
    "check_targets",
    "format_problems",
    "install_signal_restore",
    "record_pristine",
    "restore_from_sidecar",
    "sidecar_for",
    "sweep_lifecycle",
]

#: The mutation currently written to disk, so a signal handler can undo it.
_PENDING: list[tuple[Path, str] | None] = [None]

#: Sidecar suffix. The pristine text is written here BEFORE the first mutation,
#: so a run killed without any chance to unwind can still be restored.
SIDECAR_SUFFIX = ".sweepbackup"


def _set_in_flight(path: Path, original: str) -> None:
    """Record the file as mutated, so an interrupt can restore it."""
    _PENDING[0] = (path, original)


def _clear_in_flight() -> None:
    """Record that no mutation is on disk."""
    _PENDING[0] = None


def _restore_on_signal(signum: int, _frame: object) -> None:
    """Undo an in-flight mutation, then exit. Installed for SIGTERM/SIGINT."""
    pending = _PENDING[0]
    if pending is not None:
        path, original = pending
        try:
            path.write_text(original, encoding="utf-8", newline="")
        except OSError as exc:  # pragma: no cover - best effort on the way out
            print(f"!! interrupted - COULD NOT restore {path.name}: {exc}")
        else:
            print(f"\n!! interrupted (signal {signum}) - restored {path.name}")
    raise SystemExit(128 + signum)


def install_signal_restore() -> None:
    """Install the in-flight restore for ``SIGTERM`` / ``SIGINT``.

    Idempotent, and safe to call unconditionally: a sweep that never sets an
    in-flight mutation simply has nothing to restore.

    **On Windows this does nothing, and that is not a bug in this function.**
    Measured: on ``win32``, neither ``SIGTERM`` nor ``SIGINT`` ever reaches a
    Python-level handler - ``os.kill(pid, SIGTERM)`` maps to
    ``TerminateProcess`` and the process dies without unwinding, and a
    "handled" ``SIGINT`` still surfaces as an uncaught ``KeyboardInterrupt``
    (exit 2, not the handler's ``SystemExit(130)``). Both were verified with
    self-kill probes; the handler body was never entered.

    That makes the handler a POSIX-only convenience, and makes
    :func:`record_pristine` / :func:`restore_from_sidecar` the *actual*
    defence - they depend on nothing but the filesystem.
    """
    if not hasattr(signal, "SIGTERM"):  # pragma: no cover - non-POSIX
        return
    signal.signal(signal.SIGTERM, _restore_on_signal)
    signal.signal(signal.SIGINT, _restore_on_signal)


def sidecar_for(path: Path) -> Path:
    """The sidecar that holds ``path``'s pristine text."""
    return path.with_name(path.name + SIDECAR_SUFFIX)


def record_pristine(paths: dict[Path, str]) -> list[Path]:
    """Persist each path's pristine text to a sidecar before any mutation.

    This is the platform-independent half of the interrupt defence. A sweep that
    is killed mid-run - by a truncating pipe on POSIX, or by *anything* on
    Windows - leaves mutated source and a sidecar next to it. The next run (or
    :func:`restore_from_sidecar`, or ``tools/sweep_health.py``) can then restore
    the exact bytes without having to recognise *which* mutation was applied,
    which is what makes it strictly stronger than inverting a catalogue match.

    Returns the sidecars written.
    """
    written: list[Path] = []
    for path, text in paths.items():
        sidecar = sidecar_for(path)
        sidecar.write_text(text, encoding="utf-8", newline="")
        written.append(sidecar)
    return written


def restore_from_sidecar(paths: list[Path]) -> list[Path]:
    """Restore any ``paths`` whose sidecar exists, then delete the sidecar.

    Safe to call on a clean tree: a path with no sidecar is left untouched.
    Returns the paths actually restored, so a caller can report them rather
    than silently repairing.
    """
    restored: list[Path] = []
    for path in paths:
        sidecar = sidecar_for(path)
        if not sidecar.exists():
            continue
        path.write_text(sidecar.read_text(encoding="utf-8"), encoding="utf-8", newline="")
        sidecar.unlink()
        restored.append(path)
    return restored


@contextmanager
def sweep_lifecycle(paths: Iterable[Path]) -> Iterator[dict[Path, str]]:
    """The full interrupt defence in ONE call: heal, protect, spend (O-103).

    Every sweep needs the same three steps around its mutation loop, and before
    this helper each of the 38 that lacked them would have had to repeat a
    three-call dance at two different places in ``main()`` - 76 edit sites, each
    an opportunity to invert the order or forget the cleanup. The order is what
    matters and it is not obvious, so it belongs in one tested function:

    1. **HEAL** -- ``restore_from_sidecar`` runs FIRST, before anything is read.
       A previous run killed mid-mutation left mutated source AND a sidecar; if
       the sweep read the source before healing, it would adopt the mutant as its
       baseline and bake the corruption in permanently. That is the D-081 /
       "a mutant wearing its costume" failure, and it is silent.
    2. **PROTECT** -- ``record_pristine`` writes the (now healed) text to a
       sidecar BEFORE the first mutation. On win32 this is the *only* defence
       that works: no Python signal handler runs for SIGTERM/SIGINT, so neither
       the registered handler nor the sweep's own ``finally`` gets a turn.
    3. **SPEND** -- on exit, each sidecar is deleted. Leaving one behind would
       make the NEXT run "restore" a file that never needed it, silently
       reverting a legitimate edit made in between. A stale sidecar is worse
       than none.

    Yields the pristine text of every path, healed, so the caller's ``originals``
    and the sidecars can never disagree.

    Any ``Path`` may be passed; a path that does not exist is skipped, which lets
    a sweep share this helper with an optional target (api_layer's routing files).

    ``missing_ok`` on the unlink because step 3 runs in a ``finally``: if
    ``restore_from_sidecar`` or the sweep itself already consumed a sidecar, the
    cleanup must not raise on the way out.
    """
    existing = [p for p in paths if p.exists()]

    healed = restore_from_sidecar(existing)
    originals: dict[Path, str] = {p: p.read_text(encoding="utf-8") for p in existing}

    record_pristine(originals)
    try:
        if healed:
            # Reported rather than silent: "this run started from a healed tree"
            # is a fact the operator needs, because a previous run was killed.
            print("HEALED from sidecar (a previous run was killed):")
            for path in healed:
                print(f"  restored -> {path.name}")
            print()
        yield originals
    finally:
        for path in existing:
            sidecar_for(path).unlink(missing_ok=True)


def check_targets(
    originals: dict[Path, str],
    table: list[tuple[str, Path, str, str]],
) -> list[str]:
    """Return one message per mutation whose anchor cannot be applied uniquely.

    ``originals`` maps each target path to its pristine text. A path missing from
    the mapping is read from disk, so a caller that holds only some files still
    gets a complete answer.

    Three refusals, all of them making the sweep's result meaningless:

    * ``old == new`` - **inert by construction**: it applies cleanly, changes
      nothing, and the survivor it reports says nothing about the suite.
    * ``0 occurrences`` - split into **leftover** (``new`` present: the tree is
      mutated) and **absent** (a drifted anchor: the gate is off).
    * ``>1 occurrences`` - **ambiguous**: ``str.replace`` rewrites the first, so
      the mutation may land on a different function than its name claims.
    """
    cache: dict[Path, str] = dict(originals)
    problems: list[str] = []

    for name, target, old, new in table:
        path = Path(target)
        if path not in cache:
            try:
                cache[path] = path.read_text(encoding="utf-8")
            except OSError as exc:
                problems.append(f"{name}: target UNREADABLE ({path.name}: {exc})")
                continue
        text = cache[path]

        if old == new:
            problems.append(f"{name}: INERT BY CONSTRUCTION (old == new)")
            continue

        count = text.count(old)
        if count == 0:
            if _is_applied(text, old, new):
                problems.append(
                    f"{name}: MUTATION STILL APPLIED in {path.name} (anchor absent, "
                    "replacement present AT THE EDIT SITE - this is a LEFTOVER, not a "
                    "drifted anchor; restore the file before sweeping)"
                )
            else:
                problems.append(f"{name}: target ABSENT in {path.name} (0 occurrences)")
        elif count > 1:
            problems.append(
                f"{name}: target AMBIGUOUS in {path.name} ({count} occurrences) - "
                "str.replace would rewrite the first"
            )

    return problems


def _is_applied(text: str, old: str, new: str) -> bool:
    """Is this mutation APPLIED to ``text``, or is the anchor merely absent?

    Both cases present as ``old`` occurring zero times, and separating them is the
    whole point of ``check_targets`` (D-075, D-081: two sessions hunted "stale
    anchors" while a live mutant sat in the tree wearing that costume).

    **The first discriminator here was ``new in text``, and it is a predicate with
    a FALSE-POSITIVE DIRECTION — which D-062 already says is worse than none: "a
    detector whose predicate is trivially true manufactures findings, and findings
    are what make a gate ignorable."** Measured over the whole tree: it reports
    **52 of 622** reachable catalogue entries as leftovers on a *pristine* tree.
    The one that failed every session's Step 0 is ``mutation_lei_proxy.py``'s
    ``M7b``: it replaces the split reading's ``else`` body with
    ``lead_direction = "broad_based_advance"``, and **that line is in the shipped
    source already**, because it is the legitimate ``advance`` branch's own
    assignment. Membership cannot tell "``new`` is here because the mutant wrote
    it" from "``new`` was always here".

    **The discriminator is what applying the mutation would DO.**

    A mutation is a single ``str.replace(old, new, 1)``. Let ``P`` be the pristine
    text and ``M = P.replace(old, new, 1)`` the mutated one; we hold one of them and
    must say which. Apply the mutation to what we hold and count:

    * the text is ``M`` (**applied**) → the anchor ``old`` is gone, so the replace
      finds nothing and changes nothing: ``new``'s count is **unchanged**;
    * the text is ``P`` (**drifted anchor**) → the anchor is present, so the
      replace consumes it and emits a ``new``: the count **rises**.

    So: **applied ⟺ ``old`` is absent AND re-applying does not raise ``new``'s
    count.** It asks "would this mutation change this file?" by actually applying
    it and looking, so it needs neither a pristine reference nor an assumption that
    the mutation is idempotent.

    Measured against ground truth (``git show HEAD:<file>`` as ``P``, so truth is
    established rather than inferred), over the **622** of 632 catalogue entries
    for which this branch is reachable: **0 false positives, 0 misses.** The other
    10 are excluded because ``old`` survives *inside* ``new`` (a prefix-extension
    such as ``new = old + " / 100.0"``); for those the anchor always resolves, this
    branch is never entered, and no predicate here is consulted.

    A deletion mutation (``new`` empty) is **not** our call: it cannot be verified
    this way, and D-062 requires such entries be reported *unverifiable*, never as
    leftovers — so it returns ``False`` rather than manufacturing a finding.
    """
    if not new.strip():
        return False
    if text.count(old) != 0:
        return False
    return text.replace(old, new, 1).count(new) == text.count(new)


def format_problems(problems: list[str], *, indent: str = "  !! ") -> str:
    """Render the gate's findings for a sweep's own stdout."""
    return "\n".join(f"{indent}{p}" for p in problems)
