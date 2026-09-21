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

**O-109: every check above is DIRTY-RELATIVE, and a mutant can be COMMITTED.**
This tool compares the tree against each sweep's catalogue, and the catalogues are
themselves the reference. So all of it is blind to a mutant that has been *committed*
— the tree and ``HEAD`` agree, every anchor still resolves against the corrupted
source, and ``git diff`` is empty **because the corruption is the baseline**.

Measured live (2026-09-21): ``mutation_lei_proxy.py``'s ``M7b`` had collapsed the
split reading's ``else`` branch to ``lead_direction = "broad_based_advance"`` and
was committed in ``5d4c1da "more others fixes"``. Every one of the checks below
still passed on it *except* the leftover scan, and that scan was itself reporting
a false positive for an unrelated reason (O-108) — so the two defects masked each
other. The three independent "is the tree clean?" probes agreed the tree was
clean, because against ``HEAD`` **it was**.

Step 6 below is the remedy: ask **git** whether the mutant's replacement text is
present in the COMMITTED blob. The catalogue is still the reference, but the
comparison is now anchored to a revision rather than to the working tree.

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
import contextlib
import importlib.util
import re
import subprocess
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
    # A sweep may import its SIBLINGS (``from _sweep_gate import ...``). Run as
    # ``uv run python scripts/mutation_X.py`` that works, because Python puts the
    # script's own directory on ``sys.path``. Loaded from here via
    # ``spec_from_file_location`` it does NOT, so every gated sweep died with
    # ``ModuleNotFoundError: No module named '_sweep_gate'`` -- reported as
    # IMPORT FAILED, i.e. "a sweep that cannot run is indistinguishable from a
    # sweep nobody ran" (O-62). Reproduce the interpreter's own behaviour by
    # putting ``scripts/`` on the path for the duration of the load.
    added = str(path.parent)
    prepended = added not in sys.path
    if prepended:
        sys.path.insert(0, added)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        if prepended:
            with contextlib.suppress(ValueError):
                sys.path.remove(added)
    return module, ""


def _is_applied(text: str, old: str, new: str) -> bool:
    """Is this mutation APPLIED to ``text``, or is the anchor merely absent?

    **Deliberately duplicated from ``scripts/_sweep_gate.py``, not imported.**
    ``tools/`` has no ``__init__.py`` and the gate names ``src tests scripts
    tools``, so one file would become two modules and ``mypy --strict`` refuses
    the import (the same reason ``mutation_scenario_distribution.py`` gives for
    duplicating ``enclosing_symbol``). The two copies must be kept in step; the
    test file that guards this one carries the same fixtures as the gate's.

    Both "anchor absent" cases look identical — ``old`` occurs zero times — and
    separating them is the point of the leftover check (D-075, D-081).

    **The predicate used to be ``new in text``, and that is a FALSE-POSITIVE
    direction (O-108)** — D-062 already records why this is worse than no
    detector: "a detector whose predicate is trivially true manufactures
    findings, and findings are what make a gate ignorable." A mutation's
    replacement text is often *already* in the shipped source. Measured over the
    tree: ``new in text`` reports **52 of 622** reachable entries as leftovers on
    a pristine tree. The one that broke every session's Step 0 was ``M7b``, whose
    ``new`` is ``lead_direction = "broad_based_advance"`` — the legitimate
    ``advance`` branch's own assignment.

    **The discriminator is what applying the mutation would DO.** A mutation is a
    single ``str.replace(old, new, 1)``. With ``P`` pristine and
    ``M = P.replace(old, new, 1)``:

    * the text is ``M`` (**applied**) → ``old`` is gone, so the replace finds
      nothing and ``new``'s count is **unchanged**;
    * the text is ``P`` (**drifted anchor**) → the replace consumes an ``old`` and
      emits a ``new``, so the count **rises**.

    So: **applied ⟺ ``old`` absent AND re-applying does not raise ``new``'s
    count.** It asks "would this mutation change this file?" by applying it and
    looking, needing neither a pristine reference nor idempotence.

    Measured against ground truth (``git show HEAD:<file>``, so truth is
    established rather than inferred): **0 false positives, 0 misses** over the
    622 reachable entries. The other 10 are excluded because ``old`` survives
    *inside* ``new`` (a prefix-extension like ``new = old + " / 100.0"``); there
    the anchor always resolves, this branch is never entered, and no predicate
    here is consulted.

    A deletion mutation (``new`` empty) is **not** our call: D-062 requires such
    entries be reported *unverifiable*, never as leftovers, so this returns
    ``False`` rather than manufacturing a finding.
    """
    if not new.strip():
        return False
    if text.count(old) != 0:
        return False
    return text.replace(old, new, 1).count(new) == text.count(new)


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
                # `read_text` (not `read_bytes().decode`) — the SAME fix
                # `_own_target_check` needed, and it was left un-applied here.
                #
                # This resolver decides WHICH candidate file a 3-tuple sweep's
                # anchor lives in by asking `old in text`. The bytes form does
                # not translate newlines, so on a CRLF file an LF anchor matched
                # nothing, the anchor fell through to `candidates[0]`, and
                # `_own_target_check` — which reads with `read_text` and so sees
                # the anchor — then reported it ABSENT **in the wrong file**.
                #
                # Measured: `_legacy_targets` returns four candidates for
                # `mutation_lei_proxy.py`, of which `snapshot_builder.py` (814
                # CRLF) and `config.py` (4447 CRLF) are entirely CRLF while
                # `validation.py` and `lei_proxy.py` are entirely LF. That is why
                # the false ABSENTs land on exactly the CRLF members. It is the
                # same 87%-artefact failure the `_own_target_check` docstring
                # records (lesson 80: a check manufacturing findings), in the
                # one place the earlier fix did not reach.
                texts[candidate] = candidate.read_text(encoding="utf-8")
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
            # Distinguish a DRIFTED ANCHOR from a MUTANT LEFT APPLIED. Both
            # present as "0 occurrences", and conflating them is what sent two
            # sessions hunting stale anchors while the tree was mutated.
            #
            # A leftover mutation is self-concealing by construction (O-95): the
            # mutant REPLACED the text the anchor looks for, so the anchor goes
            # to zero and the tool used to blame the anchor. The discriminator
            # is `_is_applied` -- and NOT `new in text`, which was a predicate
            # with a FALSE-POSITIVE direction (O-108): it reported 52 of 622
            # reachable entries as leftovers on a pristine tree, because a
            # mutation's replacement text is frequently already in the shipped
            # source. `M7b`'s `lead_direction = "broad_based_advance"` is the
            # legitimate advance branch's own assignment, so `new in text` was
            # trivially true and Step 0 failed on a clean tree.
            if _is_applied(text, old, new):
                problems.append(
                    f"{name}: MUTATION STILL APPLIED in {target.name} "
                    f"(anchor absent AND re-applying the mutation changes nothing "
                    f"-- this is a LEFTOVER, not a drifted anchor)"
                )
            else:
                problems.append(f"{name}: target ABSENT in {target.name} (0 occurrences)")
        elif count > 1:
            problems.append(f"{name}: target AMBIGUOUS in {target.name} ({count} occurrences)")
    return problems


def _call_gate(gate: Any, native: list[Any]) -> list[str]:
    """Call a sweep's gate without assuming its signature.

    The gates were written across three increments and their signatures drifted:
    some take ``verbose`` as a keyword, some do not. Passing the wrong one raises
    ``TypeError`` and would make THIS tool look like the broken one, so the call
    is adapted rather than the sweeps rewritten — the point of the check is to
    report on the sweeps, not to impose a signature on them.
    """
    try:
        result = gate(native, verbose=False)
    except TypeError:
        try:
            result = gate(native)
        except TypeError:
            return []
    return list(result)


#: Textual markers of an HONESTY CONTROL or an EXPECTED-KILL declaration. A sweep
#: that carries one can tell a broken baseline from a strong suite; a sweep with
#: neither cannot, which is the D-051 shape.
#:
#: **Two mechanisms are legitimate and both are accepted**, which matters because
#: the first version of this check recognised only the first and produced six
#: FALSE POSITIVES (O-107, lesson 5cm — the narrow predicate, again):
#:
#: * ``expect_killed`` — the mutation dataclass says what must happen to it, and
#:   the summary compares against that. **22 of the 40 sweeps use this.**
#: * a ``CONTROL``-bearing mutation name whose ``.killed`` is read — the D-051
#:   refusal, written explicitly. **12 of the 40 use this.**
#:
#: A sweep may use either; the check asks only whether it has **some** way to
#: notice that its own baseline is broken. Demanding one mechanism would flag
#: correct sweeps, and a gate that flags correct code is one you learn to ignore.
#:
#: The markers are **uses, not definitions**: ``.killed`` (an attribute read) and
#: ``expect_killed`` (a field consulted). This deliberately does NOT accept the
#: bare token ``killed``, because ``def killed(self) -> bool`` is the *mechanism's
#: implementation* and is present whether or not anything consults it. Measured on
#: ``mutation_risk_axis.py``: a mutant that removed both real uses still matched,
#: because the property definition remained (lesson 5cm — verify what a predicate
#: actually matched before believing its verdict).
_CONTROL_MARKERS: tuple[str, ...] = ("expect_killed", ".killed")


def _control_markers(path: Path) -> list[str]:
    """Which control mechanisms this sweep's SOURCE text mentions.

    Reads the raw text rather than introspecting the module, because the two
    mechanisms live at different depths (a dataclass field vs. a local variable
    in ``main()``) and only one of them is visible on the imported object. A
    textual check is weaker than a structural one, so it is deliberately used
    only to REPORT COVERAGE — never to fail a sweep — which is the same
    discipline the O-29 sweep-owned-gate line already follows.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [marker for marker in _CONTROL_MARKERS if marker in text]


#: Seconds allowed per mutation when deriving a driver's wall-clock budget.
#:
#: **This is a MEASURED constant, not a round number, and that distinction is the
#: whole point of O-112.** The deleted ``.probe/run_all_sweeps.sh`` carried a flat
#: ``timeout 600`` for all 40 sweeps, so ``mutation_api_layer.py`` — **42**
#: mutations, each spawning a fresh interpreter over four test files at
#: **39.73 s** measured — had a floor of **~1,700 s**. The kill was **arithmetic,
#: not bad luck**: ``rc=124`` at 601 s, and on win32 a killed sweep leaves every
#: mutant applied so far on disk. Re-run alone with a real budget it CERTIFIES in
#: **1,066 s**.
#:
#: The constant is deliberately generous (**75 s**, ~1.9x the one measured
#: per-mutation cost) because the failure it guards against is a **kill**, whose
#: cost is source corruption, while the cost of an over-generous budget is only
#: that a hung sweep takes longer to be noticed. **Erring toward generous is
#: correct here.**
_BUDGET_SECONDS_PER_MUTATION = 75

#: The floor, so a tiny sweep still gets a usable budget. Three mutations at 75 s
#: is 225 s, which is under the time one `uv run pytest` startup can take on a
#: cold cache, so the floor matters independently of the multiplier.
_BUDGET_FLOOR_SECONDS = 300


def _sweep_budget(declared: int) -> int:
    """The wall-clock budget a driver must give a sweep declaring ``declared`` mutations.

    **O-112(c) asked for exactly this**: *"no gate asserts that the driver's budget
    exceeds the sweep's measured cost, so the two can drift apart again."* The
    remedy is to make the budget **derived from the catalogue** rather than typed
    by hand, so it cannot drift: change a sweep's mutation count and the budget
    moves with it.

    The drift O-112 recorded was not hypothetical — a flat 600 s against a sweep
    whose floor was ~1,700 s is a **guaranteed** kill, and its ``SUMMARY.txt`` row
    was written **indistinguishable from a real result** (O-62 in the harness
    itself).
    """
    return max(_BUDGET_FLOOR_SECONDS, declared * _BUDGET_SECONDS_PER_MUTATION)


def _is_mutant_shape(stripped: str) -> bool:
    """Does this stripped source line carry a mutant shape?

    Two shapes, and the second is the one that nearly cost this gate its
    credibility:

    * ``# MUTANT`` — the trailing comment every replacement text in this project
      carries, which is how a mutation that is not a branch inversion is
      recognised.
    * A **branch-inversion or identity control**. The original test here was
      ``stripped.startswith(("if False:", "if True:"))``. That catches the bare
      forms but **misses the compound ones**, and the compounds are what this
      project actually writes: ``if not deep and True:`` (``M10.1``, the honesty
      control in ``routes_health.py``) and ``if x or False:`` are identity
      controls whose whole point is to be semantically identical to the shipped
      code, so applying one changes no behaviour and no test can detect it. The
      ``and True`` / ``and False`` / ``or True`` / ``or False`` suffix is only
      ever written by a sweep.

    Measured live: an interrupted ``mutation_api_layer.py`` run left
    ``if not deep and True:`` applied in ``routes_health.py``. The prefix test
    above did not see it, so this tool printed ``0`` shape hits and **SWEEP
    HEALTH: OK** on a tree that had a control mutant on disk. The independent
    ``grep`` did see it, which is how the false OK was caught. A gate that can
    print OK on a mutated tree is worse than no gate, because it is trusted —
    so the detection is now by *structure* rather than by prefix.

    **``elif`` is a second blind spot, found 2026-09-21 the same way.** The
    prefix tuple above is ``("if False:", "if True:")`` and ``str.startswith``
    does not treat ``elif False:`` as a match, so a **dead ``elif`` branch is
    invisible**. That is not a hypothetical shape: ``mutation_convergence.py``
    writes both ``M2.2`` (``if False:  # NO_SIGNAL removed``) and ``M3.2``
    (``elif False:  # CONFLICTED removed``), and ``M3.2`` is the mutant that is
    committed to ``HEAD``. Both this function *and* the O-83 whole-tree scan are
    built on it, so the blind spot propagated to two gates. Verified:
    ``_is_mutant_shape('elif False:')`` returned ``False`` while
    ``_is_mutant_shape('if False:')`` returned ``True``. Widening the tuple to
    include ``elif`` closes it without loosening the test — ``elif True:`` and
    ``elif False:`` are, like their ``if`` forms, things only a sweep writes.
    """
    if "MUTANT" in stripped:
        return True
    if stripped.startswith(("if False:", "if True:", "elif False:", "elif True:")):
        return True
    # The compound identity form: ``... and True`` / ``... or False`` at the end
    # of a condition. Matching the bare boolean literal is what makes this safe
    # to widen -- ``and True`` is not something a person writes in a condition
    # they intend, and a sweep is the only other writer.
    return bool(re.search(r"\s(?:and|or)\s(?:True|False)\s*:", stripped))


def _whole_tree_mutant_scan() -> list[str]:
    """O-83's remedy: find mutant SHAPES anywhere, with no catalogue.

    The per-sweep leftover check is scoped to each sweep's own declarations, so
    a mutant left in a shared file by a *different* sweep is invisible. This
    scan does not care which sweep wrote it, or whether its catalogue still
    exists — it looks for the shapes every sweep in this project uses. Those
    shapes are defined by ``_is_mutant_shape``: the ``# MUTANT`` comment, a
    branch inversion, and the compound identity form (``and True`` etc.) that
    the original prefix test missed.

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
            if _is_mutant_shape(stripped):
                hits.append(f"{path.relative_to(REPO)}:{lineno}: {stripped}")
    return hits


def _committed_blob(rel: str, *, rev: str = "HEAD") -> str | None:
    """The committed text of ``rel`` at ``rev``, or ``None`` if git cannot supply it.

    Returns ``None`` rather than raising whenever git is absent, the repo has no
    ``HEAD``, or the path is untracked: a tool that refuses to run because it
    cannot reach git would be a gate nobody can run in a fresh clone, which is
    O-62's failure mode again.

    ``rev`` exists so the **positive control can be pinned to a historical commit**
    (see ``tests/test_sweep_health_leftover_predicate.py``). Selecting the control
    from the live scan instead made the guard require ``HEAD`` to be *currently
    dirty*, so committing a repair — the desired end state — broke it. A frozen
    revision says "given this commit, does the scan see it?", which is the actual
    property and does not move when history advances.
    """
    try:
        proc = subprocess.run(
            ["git", "show", f"{rev}:{rel}"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _committed_mutant_scan(catalogue: list[tuple[str, Path, str, str]]) -> list[str]:
    """O-109's remedy: is a mutant's replacement text in the COMMITTED source?

    Every other check in this file compares the working tree against the sweeps'
    catalogues, so all of them share one blind spot: **a mutant that has been
    committed is the baseline.** ``git diff`` is empty, each anchor still resolves
    against the corrupted text, and the tree is "clean" by every dirty-relative
    measure. The catalogue's own declaration is what gives it away — a mutation is
    *supposed* to be absent from the shipped source, so its replacement text being
    present in ``HEAD`` is a defect regardless of what the working tree says.

    **The predicate, and the mistake it took two attempts to get right.** The
    first version tested ``old not in committed and new in committed``, reasoning
    that a mutation's replacement text has no business being in the shipped
    source. That is true, and it is *not sufficient*: it is the same defect this
    file already fixed once for the working-tree path (O-108), and the committed
    path reintroduced it, because it is the same logical error in a new scope.
    A catalogue's ``new`` text is frequently a **superset or a substring of a
    legitimate shipped line**. ``M8.3`` replaces
    ``f"convergence={thesis.convergence_classification.value}"`` with the fixed
    string ``"convergence=HIGH"`` — and the shipped ``reasoning_stream.py``
    contains *both*, because they are two different ``yield`` sites (a live one
    and the stood-down one). ``old`` is absent from ``HEAD`` for an unrelated
    reason (the live site's expression differs), ``new`` is present for an
    unrelated reason (the other site), and the conjunction fires on a file that
    is entirely correct. Measured 2026-09-21: **1 of the 2 findings was this
    false positive.**

    So the reduction to a *finding* requires a witness that is specific to the
    edit site: the committed blob must carry a **mutant shape**
    (``_is_mutant_shape``) *inside the region where ``new`` lands*. That is not a
    weaker test but a stronger one, and it needs no reconstruction of the
    pristine text:

    * ``M3.2`` — ``HEAD``'s ``convergence.py`` carries
      ``elif False:  # CONFLICTED removed``, a dead branch. Shape found at the
      site ⇒ genuine committed mutant.
    * ``M8.3`` — ``HEAD``'s ``reasoning_stream.py`` has ``convergence=HIGH`` as a
      live, reachable statement with no dead branch. No shape at the site ⇒
      **not** a mutant, and the anchor-absence is a drifted anchor by another name.

    ``_is_applied(committed, ...)`` must NOT be used here. Against the committed
    blob it reduces to ``text.count(old) == 0 and new.count == new.count``, which
    is ``new in text`` — the very trivially-true test being corrected. It is only
    meaningful against the file that would be *edited*.

    **This check would have caught the 2026-09-21 incident.** ``M7b``'s
    replacement, ``lead_direction = "broad_based_advance"``, sits in the
    committed ``lei_proxy.py`` where the ``mixed`` arm belongs — and that arm is
    a genuine branch inversion, so the shape witness fires.
    """
    findings: list[str] = []
    blobs: dict[Path, str | None] = {}
    for name, target, old, new in catalogue:
        if not new.strip() or old == new:
            continue
        if target not in blobs:
            try:
                rel = target.resolve().relative_to(REPO.resolve()).as_posix()
            except ValueError:
                blobs[target] = None
            else:
                blobs[target] = _committed_blob(rel)
        committed = blobs[target]
        if committed is None or old in committed:
            continue
        # The witness must be a mutant SHAPE, and it must be present in the
        # committed blob *as a line of its own*. ``_is_mutant_shape`` is the
        # project's structural test (O-107), so an ordinary line cannot satisfy
        # this. Matching against the blob's stripped lines (rather than against
        # the indented ``new`` text) is what makes the check indentation-proof:
        # a catalogue entry and the committed source can differ in leading
        # whitespace without the finding being lost.
        committed_shapes = {
            line.strip() for line in committed.splitlines() if _is_mutant_shape(line.strip())
        }
        for line in new.splitlines():
            stripped = line.strip()
            if stripped and _is_mutant_shape(stripped) and stripped in committed_shapes:
                findings.append(
                    f"{name}: the committed {target.name} already carries this "
                    f"mutation's replacement text AND a mutant shape at the edit "
                    f"site (old absent from HEAD, {stripped!r} present) — a mutant "
                    f"was COMMITTED, so every dirty-relative check is blind to it"
                )
                break
    return findings


def main() -> int:
    print("=" * 78)
    print("SWEEP HEALTH — every mutation sweep, without running one")
    print("=" * 78)

    sweeps = sorted(SCRIPTS.glob("mutation_*.py"))
    if not sweeps:
        print("!! no sweeps found; the glob is wrong")
        return 1

    # O-112(c): a driver's budget typed by hand drifts from the work it guards.
    # `--budgets` prints the DERIVED budget for every sweep, so a driver (or a
    # re-created one -- the D-087 probe's was a throwaway and is gone) is written
    # from arithmetic rather than from a round number. Read-only and optional, so
    # the default check stays as cheap as before.
    if "--budgets" in sys.argv:
        total = 0
        print()
        print(f"{'budget':>8}  {'mutations':>9}  sweep")
        for path in sweeps:
            module, error = _load(path)
            if module is None:
                print(f"{'?':>8}  {'?':>9}  {path.name}  (IMPORT FAILED: {error})")
                continue
            declared = len(_mutations(module))
            budget = _sweep_budget(declared)
            total += budget
            print(f"{budget:>8}  {declared:>9}  {path.name}")
        print()
        print(f"total wall-clock if run serially: {total} s (~{total / 3600:.1f} h)")
        print(
            f"derived as max({_BUDGET_FLOOR_SECONDS}, declared x "
            f"{_BUDGET_SECONDS_PER_MUTATION}) — O-112: a flat round number is a "
            f"guaranteed kill for the larger sweeps"
        )
        return 0

    failures: list[str] = []
    ungated: list[str] = []
    leftovers: list[str] = []
    # O-72's first half, made VISIBLE rather than remembered. A sweep with no
    # control mechanism cannot distinguish "my suite is strong" from "my baseline
    # is broken" -- both present as everything-killed, which is the D-051 trap
    # (a sweep reported 31/31 on a broken baseline and killed its own control).
    # This tool checks GATES, not KILLINGS, and stays that way; what it CAN see
    # is which sweeps have no way to notice. Reported as coverage, never failed:
    # see `_control_markers`. Coverage gaps here are O-72, not failures.
    no_control: list[str] = []
    # ``[budget, sweep name, declared mutations]`` for the largest sweep, filled
    # in the loop below. A list rather than three scalars so the closure-free
    # assignment stays local to `main()`.
    largest_budget: list[Any] = [0, "", 0]
    # Every catalogue entry, so O-109's committed-mutant scan can run over the
    # whole tree once rather than per sweep (a mutant in a SHARED file may be
    # declared only by the sweep that is not the one that left it -- O-83).
    all_entries: list[tuple[str, Path, str, str]] = []

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
        all_entries.extend(catalogue)

        if not _control_markers(path):
            no_control.append(path.name)

        # O-112(c): track the LARGEST derived budget, so the summary states the
        # number a driver must clear rather than leaving it to be re-derived by
        # hand (which is how a flat 600 s got written against a 1,700 s floor).
        budget = _sweep_budget(len(catalogue))
        if budget > largest_budget[0]:
            largest_budget[:] = [budget, path.name, len(catalogue)]

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
            if _is_applied(text, old, new):
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

    # O-109's remedy. Runs AFTER the loop because it needs the whole catalogue,
    # and it is the ONLY check here that is not dirty-relative: a mutant that was
    # committed makes every other check in this tool pass while the shipped source
    # is corrupted.
    committed_hits = _committed_mutant_scan(all_entries)
    for hit in committed_hits:
        failures.append(f"committed mutant: {hit}")

    print()
    print("=" * 78)
    print(f"sweeps checked:            {len(sweeps)}")
    print(f"sweeps with NO sweep-owned gate: {len(ungated)}  ({', '.join(ungated) or 'none'})")
    print("  (all of them are still covered by this tool's own target check)")
    print(f"sweeps with NO honesty control (O-72): {len(no_control)}")
    if no_control:
        print("  (a control-less sweep cannot see its own baseline break -- the")
        print("   D-051 trap. Coverage gap, not a failure: neither mechanism is")
        print("   required, but ONE of them is what makes 'all killed' mean anything.)")
        for item in no_control:
            print(f"  NO CONTROL -> {item}")
    else:
        print("  (every sweep can distinguish a strong suite from a broken baseline)")
    print(f"leftover mutations:        {len(leftovers)}")
    budget_value, budget_sweep, budget_declared = largest_budget
    print(
        f"largest sweep budget (O-112): {budget_value} s  "
        f"({budget_sweep}, {budget_declared} mutations)"
    )
    print(
        f"  derived as max({_BUDGET_FLOOR_SECONDS}, declared x "
        f"{_BUDGET_SECONDS_PER_MUTATION}). A driver budget BELOW this number is a"
    )
    print("  GUARANTEED kill, not bad luck -- and on win32 a killed sweep leaves")
    print("  every mutant applied so far on disk. Run `--budgets` for the full table.")
    for item in leftovers:
        print(f"  STILL APPLIED -> {item}")
    print(f"mutant shapes on disk (O-83, whole tree): {len(shape_hits)}")
    for item in shape_hits:
        print(f"  SHAPE FOUND   -> {item}")
    print(f"committed mutants (O-109, vs HEAD): {len(committed_hits)}")
    for item in committed_hits:
        print(f"  IN COMMITTED SOURCE -> {item}")
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
    print("mutation is left applied. Coverage gaps above are O-29 and O-72, not")
    print("failures -- this tool reports what it can SEE, and it cannot see whether")
    print("a resolving sweep would still KILL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
