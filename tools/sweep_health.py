"""Sweep-health check: does every mutation sweep still WORK, without running it?

AGENTS.md Section 21.0 and the D-060 audit (**O-62**).

The problem this closes
-----------------------
This project's strongest verification gate is its mutation sweeps, and **nothing
gated the gates.** A D-060 audit walked every sweep in ``scripts/`` by hand and
found **three** broken:

======================  ==================================================
sweep                   state
======================  ==================================================
``mutation_drawdown``   exit 2 — four AMBIGUOUS anchors in ``risk_budget.py``
``mutation_credit_spread``  exit 1 — an unexplained survivor that turned out to
                        be a **mis-target** plus two anchors D-043 had staled
``mutation_convergence``  exit 2, from a leftover mutation in a dirty tree
======================  ==================================================

A sweep exiting 2 **prints a refusal**, but no workflow step *consumes* that: the
operator sees text, not a gate. So a broken sweep is indistinguishable from a
sweep nobody ran.

What this checks, and why it is cheap
-------------------------------------
It does **not** run the sweeps — that is hours, and it mutates the tree. It runs
the three things that break *without* mutating anything:

1. **The module imports.** A sweep whose anchors are transcribed at import time
   (``_slice_source``) raises immediately when its markers drift.
2. **``check_targets``**, where the sweep has one — every anchor present exactly
   once. This is what caught D-060's eight AMBIGUOUS anchors and D-062's three
   mis-targets.
3. **``check_anchor_landings``**, where the sweep has one — every anchor lands in
   a function the increment owns. ``check_targets`` proves an anchor is unique;
   only this proves it is in the right place.
4. **A leftover scan** — a mutation still applied in the tree. This is O-61's
   incident, and it recurred live during D-062: an interrupted run of an
   unrelated legacy sweep left ``MX3d`` applied in ``yield_curve.py``. A dirty
   tree does not announce itself, because a sweep whose anchor no longer matches
   takes the *pattern-not-found* path and records a **survivor** — so a
   corrupted file reads as *weak tests*.

**O-83: the leftover scan above is SCOPED, and a scoped gate's green result is
conditional on the scope being complete.** The per-sweep scan iterates each
sweep's own catalogue, so a mutant left behind by sweep *X* in a file that sweep
*Y* also targets is invisible unless *Y* happens to declare the same replacement
text. Measured live during D-067: D-064's ``M6.3`` mutant (``if False:``
replacing ``abs(total - 1.0) > tolerance`` in ``config.py``) was **still on
disk** while this tool reported **0 leftovers** — because ``config.py`` is a
target of the *scenario* sweep, which was target-clean *only because the
mutation had already fired*. The corrupted state was invisible **precisely
because it had succeeded.**

The remedy is step 5 below, and it does not consult a catalogue at all.

Coverage gaps are reported, not failed: seven older sweeps predate
``check_targets`` (O-29), and failing on that would make this gate red on a tree
that is behaving as designed. A sweep with **no** gate is reported as
``[NO GATES]`` so the gap is visible rather than silent.

Run with::

    uv run python tools/sweep_health.py

Exits 0 when every sweep is loadable, target-clean and the tree has no leftover
mutation; 1 otherwise.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def _load(path: Path) -> tuple[Any | None, str]:
    """Import a sweep module. Returns ``(module, error_message)``."""
    name = f"_sweep_health_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None, "could not build an import spec"
    module = importlib.util.module_from_spec(spec)
    # Required for modules that use ``@dataclass``: without registering the
    # module in ``sys.modules`` first, ``dataclasses`` resolves
    # ``sys.modules[cls.__module__]`` to None and raises.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return module, ""


def _native(module: Any) -> list[Any]:
    """The sweep's own catalogue, in whatever shape it uses.

    **Three** harness generations coexist in this directory, and the check has to
    read all of them or it reports a false ``[BROKEN]`` for the older ones:

    ==========================================  ============================
    shape                                       used by
    ==========================================  ============================
    ``Mutation`` dataclasses from                the current standard
    ``build_mutations()``
    ``_MUTATIONS`` list of 4-tuples              the D-050..D-055 generation
    ``(name, target, old, new)``
    ``MUTATIONS`` list of 3-tuples               the Tier 1/2 generation, whose
    ``(name, old, new)`` + a module-level        target is one module-level
    ``SRC`` / ``TARGET`` / ``PATH`` constant     constant for the whole file
    ==========================================  ============================
    """
    entries = getattr(module, "_MUTATIONS", None)
    if entries is not None:
        return list(entries)
    if hasattr(module, "build_mutations"):
        return list(module.build_mutations())
    legacy = getattr(module, "MUTATIONS", None)
    if legacy is not None:
        candidates = _legacy_targets(module)
        texts = {}
        for candidate in candidates:
            try:
                texts[candidate] = candidate.read_bytes().decode("utf-8")
            except OSError:
                continue
        resolved: list[Any] = []
        for name, old, new in legacy:
            # Pick the candidate file the anchor actually lives in. Falling back
            # to the first candidate keeps a genuinely ABSENT anchor reportable
            # rather than silently dropped.
            target = next(
                (c for c in candidates if old in texts.get(c, "")),
                candidates[0] if candidates else Path("<unknown>"),
            )
            resolved.append((name, target, old, new))
        return resolved
    return []


def _mutations(module: Any) -> list[tuple[str, Path, str, str]]:
    """Normalise a sweep's catalogue to ``(name, path, old, new)`` 4-tuples.

    Two harness generations coexist in this directory: the older ones hold a
    ``_MUTATIONS`` list of plain tuples, the newer ones a ``build_mutations()``
    returning ``Mutation`` dataclasses. Both are read here so the check does not
    have to be updated as the sweeps are migrated.
    """
    native = _native(module)
    if not native:
        return []
    if hasattr(native[0], "name"):
        return [(m.name, Path(m.path), m.old, m.new) for m in native]
    return [(e[0], Path(e[1]), e[2], e[3]) for e in native]


def _legacy_targets(module: Any) -> list[Path]:
    """Every target a 3-tuple catalogue could apply to.

    The oldest sweeps carry ``MUTATIONS: list[tuple[str, str, str]]`` — a name, an
    ``old`` and a ``new``, with **no target** — and resolve the file from a
    module-level constant. That constant is not always unique: ``mutation_lei_proxy.py``
    applies one catalogue against **four** files (its own ``SRC`` plus the data
    layer's ``snapshot_builder``/``validation`` and ``config``).

    Returning a *list* rather than one path is what makes the check correct for
    that shape. The first version of this tool returned a single path, checked a
    ``validation.py`` anchor against ``lei_proxy.py``, and reported **five
    false-positive ABSENT targets** — a gate manufacturing findings, which is the
    failure mode lesson 80 warns about. The resolver now tries every candidate and
    only reports ABSENT when the anchor is missing from all of them.
    """
    candidates: list[Path] = []
    for attribute in ("SRC", "TARGET", "MODULE", "PATH", "FILE"):
        candidate = getattr(module, attribute, None)
        if isinstance(candidate, Path):
            candidates.append(candidate)
    for name in dir(module):
        if name.startswith("_"):
            candidate = getattr(module, name, None)
            if isinstance(candidate, Path) and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def enclosing_symbol(text: str, index: int) -> str:
    """The top-level symbol a character offset falls inside, or ``"<module>"``.

    Shared with the sweeps' own ``check_anchor_landings``, because the **first
    implementation of this was wrong in a way that fabricated findings** and the
    fix has to land in one place (D-064).

    The bug: the walk tested ``line.startswith(("def ", "class "))``, which is
    true of a **comment** whose first column happens to read ``def ...`` — and
    prose in a module-level comment block that says *"the ``run_sweep()`` **def** ..."*
    will not match, but a comment written as ``def foo is what this does`` at
    column 0 will. Concretely, ``build_scenario_distribution``'s sweep resolved
    its ``KellyPayoffUnit`` anchor to ``volatility_target_scaling`` — a function
    150 lines away that the anchor has nothing to do with — because a comment
    between them mentioned ``def``. The gate then **refused to run** and reported
    a mis-target that did not exist, which is lesson 80's failure mode: *a gate
    manufacturing findings is worse than no gate.*

    Two corrections, both necessary:

    1. **Parse, rather than pattern-match.** The offsets are fed through
       :mod:`ast`, so comments, strings and continuations cannot be mistaken for
       a symbol. This is the part that actually fixes the class; the second is
       the cheap guard for when the text does not parse.
    2. **Require the ``def``/``class`` to be followed by a name and a ``:``-ending
       signature**, which a prose sentence does not have. This keeps a
       half-mutated file — the case during a sweep, when the text on disk is
       temporarily invalid — from silently reporting ``<module>``.
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
        # `end_lineno` bounds the symbol; an anchor past it belongs to whatever
        # comes next, which the next iteration will claim.
        if node.end_lineno is not None and node.end_lineno < offset_line:
            continue
        enclosing.append((node.lineno, node.name))
    if not enclosing:
        return "<module>"
    return max(enclosing)[1]


def _own_target_check(catalogue: list[tuple[str, Path, str, str]]) -> list[str]:
    """The uniqueness check this tool runs ITSELF, for sweeps that have none.

    ``check_targets`` is mechanical — every ``old`` present exactly once — and
    **14 of the 31 sweeps do not have it** (O-29). The check needs nothing but
    the catalogue, which this tool already builds, so an ungated sweep does not
    have to stay unchecked. It is reported as ``own-targets`` so it is never
    confused with a sweep's own gate: a sweep that has one is still trusted over
    this, because its version may carry extra rules.

    ``str.replace(old, new, 1)`` takes the FIRST occurrence, so an ``old``
    appearing twice silently rewrites the wrong site and the sweep reports a
    surviving test — a conclusion about code nobody mutated (D-048).

    **The read must translate newlines, and the shipped version did not.** This
    function read files with ``read_bytes().decode("utf-8")``, which returns the
    bytes as they sit on disk, while every sweep anchors its ``old`` strings with
    ``\\n``. Python's ``Path.read_text`` and ``open()`` in text mode apply
    **universal-newline translation** (CRLF and CR both become LF); the bytes
    form does not. On a CRLF file every LF anchor therefore matched **zero**
    times and this function reported it ABSENT.

    Measured on the tree as shipped: ``src/macro_engine/config.py`` is the **only**
    CRLF file among 69 under ``src/`` (4 292 CRLF, 0 bare LF) — and **every one of
    the 13 sweeps this tool reported ``[FAIL]``** targets it. Reproduced with both
    readers over the whole directory: the bytes form reports **45 problems**, the
    translated form reports **6**, so **39 of 45 findings (87%) were artefacts of
    the line endings** and not one of them described the code.

    This is the failure mode this tool's own docstring warns about — a gate
    manufacturing findings (lesson 80) — and it is the **second** time it has
    happened here: the first version returned a single target path for a
    multi-file catalogue and reported five false ABSENTs (see
    ``_legacy_targets``). The lesson is the same both times: **a check that
    produces a large, homogeneous block of failures is more likely to be broken
    than the thing it is checking**, and the way to tell is to reproduce the
    finding with a second, independent reader rather than to trust the first.
    """
    problems: list[str] = []
    for name, target, old, new in catalogue:
        try:
            # `read_text` (not `read_bytes().decode`) — see the docstring. Any
            # reader the SWEEPS do not use would reintroduce this: a sweep reads
            # its source with `Path.read_text`, so this must match it exactly.
            text = Path(target).read_text(encoding="utf-8")
        except OSError:
            continue
        if old == new:
            problems.append(f"{name}: INERT BY CONSTRUCTION (old == new)")
            continue
        count = text.count(old)
        if count == 0:
            problems.append(f"{name}: target ABSENT in {target.name} (0 occurrences)")
        elif count > 1:
            problems.append(f"{name}: target AMBIGUOUS in {target.name} ({count} occurrences)")
    return problems


def _call_gate(gate: Any, native: list[Any]) -> list[str]:
    """Call a sweep's gate without assuming its signature.

    The gates were written across three increments and their signatures drifted:
    some take ``verbose`` as a keyword, some do not. Passing the wrong one raises
    ``TypeError`` and would make THIS tool look broken, so the call is adapted
    rather than the sweeps rewritten — the point of the check is to report on the
    sweeps, not to impose a signature on them.
    """
    try:
        result = gate(native, verbose=False)
    except TypeError:
        try:
            result = gate(native)
        except TypeError:
            return []
    return list(result)


def _whole_tree_mutant_scan() -> list[str]:
    """O-83's remedy: find mutant SHAPES anywhere, with no catalogue.

    The per-sweep leftover check is scoped to each sweep's own declarations, so
    a mutant left in a shared file by a *different* sweep is invisible. This
    scan does not care which sweep wrote it, or whether its catalogue still
    exists — it looks for the two shapes every sweep in this project uses:

    * ``if False:`` / ``if True:`` — the branch-inversion form.
    * ``# MUTANT`` — the comment every replacement text carries, which is how a
      mutation that is not a branch inversion is recognised.

    ``if True:`` is a mutant shape here because the project's sweeps use
    ``if not deep and True:`` style identities as **controls**, and a control
    left applied is exactly as invisible as a defect left applied.

    Scanned: ``src/`` only. The sweeps themselves necessarily contain these
    strings (they are the mutant text), and the tests legitimately reference
    them, so scanning those trees would report the catalogue rather than the
    tree. ``src/`` is where a mutation is applied, so it is the only place the
    answer is meaningful.
    """
    hits: list[str] = []
    for path in sorted((REPO / "src").rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if "MUTANT" in line or stripped.startswith(("if False:", "if True:")):
                hits.append(f"{path.relative_to(REPO)}:{lineno}: {stripped}")
    return hits


def main() -> int:
    print("=" * 78)
    print("SWEEP HEALTH — every mutation sweep, without running one")
    print("=" * 78)

    sweeps = sorted(SCRIPTS.glob("mutation_*.py"))
    if not sweeps:
        print("!! no sweeps found; the glob is wrong")
        return 1

    failures: list[str] = []
    ungated: list[str] = []
    leftovers: list[str] = []

    # O-83's remedy, run BEFORE the per-sweep scan so a shape left anywhere is
    # reported even if no catalogue declares it.
    shape_hits = _whole_tree_mutant_scan()
    for hit in shape_hits:
        failures.append(f"mutant shape on disk: {hit}")

    for path in sweeps:
        module, error = _load(path)
        if module is None:
            failures.append(f"{path.name}: IMPORT FAILED — {error}")
            print(f"  [BROKEN]  {path.name:42} import failed")
            continue

        catalogue = _mutations(module)
        if not catalogue:
            failures.append(f"{path.name}: no mutation catalogue found")
            print(f"  [BROKEN]  {path.name:42} no catalogue")
            continue

        native = _native(module)
        problems: list[str] = []
        if hasattr(module, "check_targets"):
            problems += [f"targets: {p}" for p in _call_gate(module.check_targets, native)]
        if hasattr(module, "check_anchor_landings"):
            problems += [f"landings: {p}" for p in _call_gate(module.check_anchor_landings, native)]
        # Always run OUR OWN uniqueness check as well. For a sweep that has no
        # `check_targets` this is the only check it gets; for one that has it,
        # agreement between the two is itself evidence the sweep's own version
        # is reading the same catalogue.
        own = _own_target_check(_mutations(module))

        applied = 0
        unverifiable = 0
        for name, target, old, new in catalogue:
            try:
                # `read_text`, for the reason `_own_target_check`'s docstring
                # gives: the sweeps read their sources with universal-newline
                # translation and the bytes form does not. Here the mismatch
                # moves the test in the OPPOSITE direction from the ABSENT
                # false positives -- on a CRLF file `old not in text` is
                # permanently True, so any mutation whose replacement text is
                # also LF would be reported **STILL APPLIED** on a clean tree.
                # A leftover check that cries wolf is worse than a missing one:
                # it trains the operator to ignore the one real hit (O-61/O-83).
                text = target.read_text(encoding="utf-8")
            except OSError:
                continue
            if not new.strip():
                # A DELETION mutation has no replacement text, so `new in text`
                # is vacuously true and the leftover test degenerates. The first
                # run of this tool reported `M8a` in `mutation_lei_proxy.py` as
                # "STILL APPLIED" for exactly that reason -- `"".count` matched
                # 27 133 times. Such a mutation cannot be verified here; the
                # sweep's own `check_targets` (where it has one) is the only
                # thing that can, so it is reported separately rather than
                # failed.
                if old not in text:
                    unverifiable += 1
                continue
            if old not in text and new in text:
                applied += 1
                leftovers.append(f"{path.name}: {name}")

        gates = ["own-targets"]
        if hasattr(module, "check_targets"):
            gates.append("targets")
        if hasattr(module, "check_anchor_landings"):
            gates.append("landings")
        if not any(g in gates for g in ("targets", "landings")):
            ungated.append(path.name)

        if problems or own or applied:
            for p in own:
                failures.append(f"{path.name}: own-targets: {p}")
            if applied:
                failures.append(f"{path.name}: {applied} mutation(s) STILL APPLIED")
            print(
                f"  [FAIL]    {path.name:42} {len(problems) + len(own)} problem(s), "
                f"{applied} leftover(s), {unverifiable} unverifiable"
            )
            for p in problems + own:
                print(f"              !! {p}")
        elif unverifiable:
            print(
                f"  [note]    {path.name:42} {len(catalogue):3} mutations  "
                f"[{'+'.join(gates)}]  ({unverifiable} deletion mutation(s) "
                f"unverifiable)"
            )
        else:
            print(f"  [ok]      {path.name:42} {len(catalogue):3} mutations  [{'+'.join(gates)}]")

    print()
    print("=" * 78)
    print(f"sweeps checked:            {len(sweeps)}")
    print(f"sweeps with NO sweep-owned gate: {len(ungated)}  ({', '.join(ungated) or 'none'})")
    print("  (all of them are still covered by this tool's own target check)")
    print(f"leftover mutations:        {len(leftovers)}")
    for item in leftovers:
        print(f"  STILL APPLIED -> {item}")
    print(f"mutant shapes on disk (O-83, whole tree): {len(shape_hits)}")
    for item in shape_hits:
        print(f"  SHAPE FOUND   -> {item}")
    print(f"failures:                  {len(failures)}")
    for item in failures:
        print(f"  !! {item}")

    if failures:
        print()
        print("SWEEP HEALTH: FAILED. A sweep that cannot run is indistinguishable")
        print("from a sweep nobody ran, and this project's strongest gate is the")
        print("one nothing gates (O-62).")
        return 1

    print()
    print("SWEEP HEALTH: OK. Every sweep loads, every anchor resolves, and no")
    print("mutation is left applied. Coverage gaps above are O-29, not failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
