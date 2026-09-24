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

import shutil
import signal
import subprocess
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = [
    "check_targets",
    "describe_dirty_targets",
    "format_problems",
    "install_signal_restore",
    "line_buffer_stdout",
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


def _git_dirty_paths(cwd: Path | None = None) -> set[Path] | None:
    """Every path git reports as modified/untracked, as resolved ``Path`` objects.

    ``cwd`` selects **which repository is asked**, and passing it is not
    optional in practice: without it git answers about the repository containing
    the *process*'s working directory, so a sweep run from one tree while
    targeting another would be told about the wrong one. Measured — the first
    version of this helper had no ``cwd`` and returned ``[]`` for a file that
    ``git status`` in its own repository reported as `` M t.py``, i.e. the
    predicate was structurally incapable of firing for any target outside the
    project root. Defaults to the process cwd, which is what a sweep wants,
    because a sweep is run from the repository it mutates.

    ``None`` means **"could not ask"** — no git, no repository, a timeout, or a
    non-zero exit — and it is deliberately distinct from ``set()`` ("asked, and
    the tree is clean"). Collapsing the two would make this precondition
    *vacuously true* in exactly the environment where it is hardest to notice
    (a stripped container, a source tarball), which is D-062's "a detector whose
    predicate is trivially true manufactures findings" in its silent direction.

    ``--porcelain`` is used rather than ``git status`` because it is stable
    across git versions and prints ``XY<space>PATH`` with no decoration; the
    ``-z`` variant is avoided because its NUL-separated stream with rename
    records is more machinery than this needs. Paths are resolved **relative to
    the repository root git reports**, not to ``cwd``, because ``git status``
    prints paths relative to the root and a nested invocation would otherwise
    mis-resolve every entry.
    """
    root = _git_root(cwd)
    if root is None:
        return None

    try:
        # `shutil.which` rather than the bare name so S607 ("partial executable
        # path") is answered honestly instead of suppressed, and `noqa: S603`
        # because the argv here is three LITERALS plus a resolved interpreter
        # path — nothing in it comes from the tree, the environment or a caller.
        # Same suppression, same reason, as `mutation_api_layer.py`'s
        # collect-only run.
        proc = subprocess.run(  # noqa: S603
            [shutil.which("git") or "git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None

    dirty: set[Path] = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        # ``XY PATH`` — the status is two characters and then a space.
        raw = line[3:].strip()
        if not raw:
            continue
        if " -> " in raw:  # a rename; the NEW name is the one on disk
            raw = raw.split(" -> ", 1)[1]
        if raw.startswith('"') and raw.endswith('"') and len(raw) > 1:
            raw = raw[1:-1]  # git quotes paths containing spaces or non-ASCII
        dirty.add((root / raw).resolve())
    return dirty


def _git_root(cwd: Path | None = None) -> Path | None:
    """The repository root containing ``cwd``, or ``None`` if there is none.

    Needed because ``git status --porcelain`` prints paths **relative to the
    repository root**, while ``cwd`` may be any subdirectory. Resolving
    porcelain entries against ``cwd`` would work only when the sweep happens to
    be invoked from the root, which is why this is asked separately rather than
    assumed.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            [shutil.which("git") or "git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    return Path(top).resolve() if top else None


def describe_dirty_targets(paths: Iterable[Path]) -> list[str]:
    """The declared targets that are ALREADY modified relative to ``HEAD``.

    **This is O-61's still-open remedy, and it is the durable form of O-112(b).**

    A sweep is an in-place corruption of the working tree that is undone on the
    way out. That is safe only if the tree it started from was the tree it thinks
    it started from. Start from a dirty target and two things go wrong at once:
    the sidecar records the *dirty* text as pristine, so the heal path restores
    the wrong bytes; and the sweep's diffs become indistinguishable from the
    operator's own edits, so `git status` can no longer be used to see what a
    killed run left behind. O-61 is the incident record (severity 3) and its
    binding rule — *never run a sweep in the background; never run a batch of
    sweeps while doing anything else* — is unchanged by any of this.

    O-112(b) phrased the same concern from the other end: *"an ``rc=124`` stop is
    a detection not a prevention."* Removing the driver removed the ``rc=124``,
    but it did not remove the class — a sweep can still be killed by anything,
    and the only thing that makes a kill recoverable is that the tree was
    knowably clean when it began.

    **Reports, never refuses.** A legitimate increment *is* a dirty tree: the
    operator edits ``src/`` and then sweeps it, and every sweep in this project
    targets a file the same increment touched. A hard failure here would make the
    guard unusable on the day it is needed, which is how a guard gets deleted.
    The caller prints the result loudly; the sidecar remains the actual defence.

    The repository is chosen from the **first target's parent**, so a caller
    testing against a sandbox tree gets the sandbox's answer rather than the
    project's. A target that git has never heard of is not a *modification* and
    is therefore never reported.

    Returns an empty list both when the targets are clean and when git could not
    be asked — this is a *report*, so an unanswered question is not a finding.
    Use :func:`_git_dirty_paths` directly if you need to distinguish the two.
    """
    candidates = list(paths)
    if not candidates:
        return []
    # Ask the repository that actually contains the targets. Using the process
    # cwd would be correct for a normal sweep and silently wrong for every other
    # caller (measured: it reported `[]` for a genuinely modified sandbox file).
    cwd = candidates[0].parent if candidates[0].is_absolute() else None
    dirty = _git_dirty_paths(cwd)
    if dirty is None:
        return []
    return sorted(str(p) for p in candidates if p.resolve() in dirty)


def record_pristine(paths: dict[Path, str]) -> list[Path]:
    """Persist each path's pristine text to a sidecar before any mutation.

    This is the platform-independent half of the interrupt defence. A sweep that
    is killed mid-run - by a truncating pipe on POSIX, or by *anything* on
    Windows - leaves mutated source and a sidecar next to it. The next run (or
    :func:`restore_from_sidecar`, or ``tools/sweep_health.py``) can then restore
    the exact bytes without having to recognise *which* mutation was applied,
    which is what makes it strictly stronger than inverting a catalogue match.

    **A sidecar is only as good as the text it was told was pristine, and that is
    the whole failure mode this function sits at the centre of.** Measured on
    2026-09-22: a sweep was killed while the tree already held two mutants
    (``M5``/``M6``); the next run healed from the sidecar, which had faithfully
    recorded that *already-mutated* text, and so reintroduced both mutants as the
    new baseline. ``check_targets`` refused (exit 4) and the tree was recovered
    from the index — the layered defence held — but the sidecar itself had become
    a carrier of corruption rather than a defence against it.

    The countermeasure lives at the call site, not here: ``sweep_lifecycle``
    emits :func:`describe_dirty_targets` **before** this runs, so the operator is
    told that the text about to be enshrined as "pristine" is not what ``HEAD``
    says. This function deliberately does not refuse — it cannot tell a mutation
    from a legitimate uncommitted edit, and D-048's lesson is that a gate which
    cannot prove its claim must report rather than decide.

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


def line_buffer_stdout() -> None:
    """Make this process's stdout line-buffered, so a killed run keeps its log.

    **Measured 2026-09-24 (D-101/D-102): a sweep redirected to a file loses its
    ENTIRE log when it is killed.** Python block-buffers stdout when it is not a
    tty, so a run SIGTERM'd after 36 mutations left a **zero-byte** log while the
    sidecar correctly preserved the tree — the *recovery* worked and the
    *evidence* did not. `mutation_econometrics.py` was fixed with `flush=True` on
    its four progress prints, and a census then found that **42 of the 43 sweeps
    had no `flush` anywhere**, so every one of them had the same hole.

    Fixing 42 files by hand is 42 chances to miss one, so the fix lives HERE, in
    the helper every sweep calls before it mutates anything: one `reconfigure`
    covers the whole catalogue, including sweeps written later.

    `getattr` rather than `sys.stdout.reconfigure` directly because `sys.stdout`
    is typed as `TextIO`, which does not declare `reconfigure`; the attribute is
    present on the real `TextIOWrapper` and absent under a captured stream, where
    the callable check skips it rather than raising.
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(line_buffering=True)


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

    Steps 1 and 2 are read-only w.r.t. the tree's *diffability*: between them the
    step-0 report (below) is emitted, because after step 2 a killed run is no
    longer distinguishable by inspection alone.

    **The step-0 report: was this tree clean when the sweep began?** — O-61's
    remedy, printed rather than enforced (see :func:`describe_dirty_targets` for
    why it reports and does not refuse). It runs *before* ``restore_from_sidecar``
    so that the answer describes the state the operator left, not the state this
    function is about to repair, and it covers the ``healed`` paths too: a sidecar
    implies a previous kill, which is precisely when a reader most needs to know
    the target is not what `HEAD` says.

    Yields the pristine text of every path, healed, so the caller's ``originals``
    and the sidecars can never disagree.

    Any ``Path`` may be passed; a path that does not exist is skipped, which lets
    a sweep share this helper with an optional target (api_layer's routing files).

    ``missing_ok`` on the unlink because step 3 runs in a ``finally``: if
    ``restore_from_sidecar`` or the sweep itself already consumed a sidecar, the
    cleanup must not raise on the way out.
    """
    # FIRST, before any file is read or written: a kill from here on must
    # leave a log behind (see `line_buffer_stdout`).
    line_buffer_stdout()

    existing = [p for p in paths if p.exists()]

    dirty = describe_dirty_targets(existing)
    if dirty:
        # Reported, not silent, and NOT a refusal: an increment that edits a file
        # and then sweeps it is the normal case here.
        print("DIRTY TARGET (O-61): this sweep starts from an uncommitted tree.")
        for item in dirty:
            print(f"  modified -> {item}")
        print("  A kill here cannot be told apart from your own edit by `git")
        print("  status` alone; check the `.sweepbackup` sidecars before")
        print("  concluding the tree is what you think it is.")
        print()

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
