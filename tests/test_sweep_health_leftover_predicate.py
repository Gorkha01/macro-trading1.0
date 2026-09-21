"""Guards for the leftover discriminator in ``sweep_health.py`` and the gate (O-108).

Why this file exists
--------------------
Both ``tools/sweep_health.py`` and ``scripts/_sweep_gate.py`` decide whether a
mutation is **still applied** to a file whose anchor no longer resolves. Two
causes present identically — the anchor *drifted* (the gate is off) and the
mutation *is applied* (the tree is mutated) — and conflating them sent two
sessions hunting stale anchors while a live mutant sat in the tree (D-075, D-081).

The first discriminator was ``new in text``, and **it is a predicate with a
false-positive direction**, which D-062 already records as worse than none: *"a
detector whose predicate is trivially true manufactures findings, and findings are
what make a gate ignorable."*

A mutation's replacement text is frequently **already in the shipped source**.
``mutation_lei_proxy.py``'s ``M7b`` replaces the split-reading's ``else`` body with
``lead_direction = "broad_based_advance"`` — which is the legitimate ``advance``
branch's own assignment, so it is present on a *pristine* tree. Measured over the
whole catalogue, ``new in text`` reported **52 of 622** reachable entries as
leftovers while the tree was clean. The consequence was not subtle: Step 0 of every
session reported ``SWEEP HEALTH: FAILED``, and a gate that always cries wolf is one
the operator learns to ignore (O-61/O-83's lesson).

The correct discriminator asks **what applying the mutation would do**. With ``P``
pristine and ``M = P.replace(old, new, 1)``:

* the text is ``M`` (**applied**) → ``old`` is gone, so the replace changes nothing
  and ``new``'s count is unchanged;
* the text is ``P`` (**drifted anchor**) → the replace consumes an ``old`` and
  emits a ``new``, so the count rises.

So **applied ⟺ ``old`` absent AND re-applying does not raise ``new``'s count.**

Two things are tested here, and they are different claims:

1. **Behavioural** — the predicate is correct in *both* directions, exercised
   against texts constructed so the right answer is known by construction. A
   predicate that is one-sided is exactly the defect being guarded against, so a
   one-sided test would not have caught it.
2. **Structural** — both copies of the predicate exist and neither has regressed
   to a bare membership test. The logic is duplicated because ``mypy --strict``
   cannot span ``tools/`` and ``scripts/`` (neither is a package), so nothing at
   import time keeps them in step; these assertions do.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TOOL = _ROOT / "tools" / "sweep_health.py"
_GATE = _ROOT / "scripts" / "_sweep_gate.py"


class _Discriminator(Protocol):
    """The surface this file needs from a module that owns the discriminator."""

    def _is_applied(self, text: str, old: str, new: str) -> bool: ...


def _load(path: Path, name: str) -> Any:
    """Import a module from a path, exactly the way ``tools/sweep_health.py`` does.

    **Mirroring the production loader is load-bearing, not stylistic.** A sweep
    module does two things that ``spec_from_file_location`` alone breaks:

    1. it imports its SIBLING ``_sweep_gate`` (``from _sweep_gate import ...``),
       which resolves only if ``scripts/`` is on ``sys.path`` — run as
       ``uv run python scripts/mutation_X.py`` the interpreter does that itself,
       loaded by path it does not, and the load dies
       ``ModuleNotFoundError: No module named '_sweep_gate'`` (O-62, D-082);
    2. it uses ``@dataclass``, which needs the module registered in
       ``sys.modules`` BEFORE ``exec_module`` — otherwise ``dataclasses`` resolves
       ``sys.modules[cls.__module__]`` to ``None`` and raises
       ``AttributeError: 'NoneType' object has no attribute '__dict__'``.

    Fixing only (1) still fails with (2), which is exactly what the first version
    of this helper did. Loading a *different* bundle of modules than the tool loads
    would also make the agreement check below vacuous, so this must reproduce the
    tool's loader.
    """
    added = str(path.parent)
    prepended = added not in sys.path
    if prepended:
        sys.path.insert(0, added)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # required for @dataclass, see the docstring
        spec.loader.exec_module(module)
        return module
    finally:
        if prepended:
            sys.path.remove(added)


@pytest.fixture(scope="module")
def tool_module() -> Any:
    return _load(_TOOL, "_sweep_health_under_test")


@pytest.fixture(scope="module")
def gate_module() -> Any:
    return _load(_GATE, "_sweep_gate_under_test")


# ---------------------------------------------------------------------------
# 1. Behavioural — correct in BOTH directions
# ---------------------------------------------------------------------------


#: A mutation whose ``new`` text **already exists elsewhere in the pristine
#: source**, which is the M7b shape and the whole reason the old predicate failed.
_PRISTINE = """\
def f(flag, breadth, composite):
    if flag:
        state = "decline"
    elif breadth >= 0.6 and composite > 0:
        state = "advance"
    else:
        state = "mixed"
    return state
"""
_OLD = '        state = "mixed"'
_NEW = '        state = "advance"'  # note: this line ALSO exists above, as the advance branch


def _predicates(module: Any) -> list[tuple[str, Any]]:
    """Every leftover-discriminator entry point a module exposes."""
    found: list[tuple[str, Any]] = []
    fn = getattr(module, "_is_applied", None)
    if fn is not None:
        found.append((getattr(module, "__name__", "?"), fn))
    return found


_BOTH_MODULES = ["tool_module", "gate_module"]


@pytest.mark.parametrize("module_fixture", _BOTH_MODULES)
def test_a_pristine_file_is_not_called_a_leftover(
    module_fixture: str, request: pytest.FixtureRequest
) -> None:
    """THE M7b CASE: ``new`` present and anchor absent, but the tree is pristine.

    This is the false positive that broke Step 0. The mutation's replacement text
    sits in the source for an unrelated reason (it is the neighbouring branch's own
    assignment), the anchor does not match because the code has drifted, and a
    membership test reports a mutant that is not there.

    Correct answer: **not applied.**
    """
    module: Any = request.getfixturevalue(module_fixture)
    for label, predicate in _predicates(module):
        assert predicate(_PRISTINE, _OLD, _NEW) is False, (
            f"{label}: reported a leftover on a pristine file whose anchor has "
            "drifted — this is O-108's false positive, and it makes Step 0 fail "
            "on a clean tree"
        )


@pytest.mark.parametrize("module_fixture", _BOTH_MODULES)
def test_a_genuinely_applied_mutation_is_detected(
    module_fixture: str, request: pytest.FixtureRequest
) -> None:
    """The other direction: a real leftover must NOT be missed.

    A predicate fixed for the false positive by simply returning ``False`` would
    pass the test above and be useless. This is the guard against that: apply the
    mutation for real and require it to be seen.
    """
    module: Any = request.getfixturevalue(module_fixture)
    assert _OLD in _PRISTINE, "the fixture anchor must resolve, or this proves nothing"
    mutated = _PRISTINE.replace(_OLD, _NEW, 1)
    assert mutated != _PRISTINE
    for label, predicate in _predicates(module):
        assert predicate(mutated, _OLD, _NEW) is True, (
            f"{label}: MISSED a genuinely applied mutation — a leftover this "
            "predicate does not see is a mutant that survives into a commit"
        )


@pytest.mark.parametrize("module_fixture", _BOTH_MODULES)
def test_a_deletion_is_never_reported_as_a_leftover(
    module_fixture: str, request: pytest.FixtureRequest
) -> None:
    """D-062: an empty replacement makes the check vacuous, so it is *unverifiable*.

    ``"".count`` matches at every position, which is why the first version of this
    check reported a deletion as "STILL APPLIED". Such an entry must never be
    reported as a leftover; the sweeps report it as unverifiable instead.
    """
    module: Any = request.getfixturevalue(module_fixture)
    for label, predicate in _predicates(module):
        assert predicate(_PRISTINE, _OLD, "") is False, (
            f"{label}: reported a deletion mutation as a leftover (D-062)"
        )


@pytest.mark.parametrize("module_fixture", _BOTH_MODULES)
def test_a_mutation_that_is_not_idempotent_is_still_detected(
    module_fixture: str, request: pytest.FixtureRequest
) -> None:
    """A prefix-extension mutation must not defeat the discriminator.

    Measured across the real catalogue: 9 entries have ``new`` that *contains*
    ``old`` (``new = old + " / 100.0"``). For those the anchor always resolves, so
    this branch is unreachable and no predicate is consulted — but the predicate
    must also not crash or mis-report if it is handed one. Here ``old`` does *not*
    survive inside ``new``, so the branch is reachable and the answer is required
    to be correct.

    The general property: the discriminator must not assume a replacement is
    idempotent, because applying it twice is what a non-idempotent mutation does.
    """
    module: Any = request.getfixturevalue(module_fixture)
    mutated = _PRISTINE.replace(_OLD, _NEW, 1)
    for label, predicate in _predicates(module):
        # Applied → detected; pristine → not detected. Both at once, because a
        # predicate hardcoded to either answer passes a single-sided test.
        assert predicate(mutated, _OLD, _NEW) is True, f"{label}: miss"
        assert predicate(_PRISTINE, _OLD, _NEW) is False, f"{label}: false positive"


# ---------------------------------------------------------------------------
# 2. Structural — the copies exist and neither is a bare membership test
# ---------------------------------------------------------------------------


def _function_source(path: Path, name: str) -> str:
    """The source text of a top-level function, for structural assertions."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"no top-level function {name!r} in {path}")


@pytest.mark.parametrize("path", [_TOOL, _GATE])
def test_both_copies_of_the_discriminator_exist(path: Path) -> None:
    """The logic is duplicated for an import reason, so both copies must exist.

    ``tools/`` and ``scripts/`` are not packages, so ``mypy --strict`` cannot
    import across them (see ``_is_applied``'s docstring). That makes the
    duplication deliberate rather than accidental — and it means nothing else
    keeps the two in step.
    """
    assert "_is_applied" in path.read_text(encoding="utf-8"), (
        f"{path} no longer defines the leftover discriminator"
    )


@pytest.mark.parametrize("path", [_TOOL, _GATE])
def test_the_discriminator_is_not_a_bare_membership_test(path: Path) -> None:
    """Structural guard against regressing to ``new in text``.

    Asserted on the **return expression**, not on the presence of a substring: a
    textual guard would be a guard on the formatter (lesson 5bf). The defect being
    guarded against is a predicate that decides on membership alone, so the test
    requires the discriminator to compare ``new``'s **count** before and after
    re-applying — which is the property that makes it correct in both directions.
    """
    body = _function_source(path, "_is_applied")
    tree = ast.parse(body)
    returns = [
        node for node in ast.walk(tree) if isinstance(node, ast.Return) and node.value is not None
    ]
    assert returns, f"{path}: _is_applied has no return statement"

    # The decisive return must involve `.count(` — the count-stability test.
    decisive = [r for r in returns if "count" in ast.dump(r)]
    assert decisive, (
        f"{path}: _is_applied's returns never compare a count, so it has "
        "regressed to a membership test (O-108)"
    )


@pytest.mark.slow
def test_the_two_copies_agree_on_the_real_catalogue() -> None:
    """The tool and the gate must return the same verdict for every real entry.

    This is the test that would have caught D-086's two-reader divergence in the
    same class: two implementations of one predicate, kept in step only by
    assertion. It compares them against **git HEAD as ground truth** — the file as
    committed is pristine by definition — so the expected answer is established
    rather than inferred.

    Skipped when ``git`` is unavailable, since the ground truth depends on it.

    **Marked ``slow``, measured at ~174s** — it must ``exec`` all 40 sweeps (each
    imports the engine) to obtain the real catalogue. The three fast structural
    guards above it catch the same regression class at ~0.01s each; this one is the
    exhaustive backstop, so deselect it with ``-m "not slow"`` on a tight loop, not
    by deleting it.
    """
    # `git` is a fixed absolute-free argv with no shell and no user input, so the
    # partial-path and untrusted-input warnings do not apply here.
    if (
        subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        != 0
    ):
        pytest.skip("no git HEAD available to establish ground truth")

    tool = _load(_TOOL, "_sweep_health_agree")
    gate = _load(_GATE, "_sweep_gate_agree")

    catalogue = _real_catalogue(tool)
    assert catalogue, "the catalogue resolved to nothing; the comparison is vacuous"

    disagreements: list[str] = []
    for name, target, old, new in catalogue:
        if not new.strip() or old == new or old in new:
            continue  # unreachable branch, or nothing for these predicates to do
        rel = target.resolve().relative_to(_ROOT).as_posix()
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if proc.returncode != 0:
            continue
        pristine = proc.stdout
        if old not in pristine:
            continue
        mutated = pristine.replace(old, new, 1)
        for label, text in (("pristine", pristine), ("mutated", mutated)):
            wanted = label == "mutated"
            a = bool(tool._is_applied(text, old, new))
            b = bool(gate._is_applied(text, old, new))
            if a != b:
                disagreements.append(f"{name} [{label}]: tool={a} gate={b} (they disagree)")
            if a != wanted:
                disagreements.append(f"{name} [{label}]: tool={a}, wanted {wanted}")
            if b != wanted:
                disagreements.append(f"{name} [{label}]: gate={b}, wanted {wanted}")

    assert not disagreements, (
        "the two copies of the leftover discriminator disagree, or one is wrong:\n  "
        + "\n  ".join(disagreements[:15])
    )


def _real_catalogue(tool: Any) -> list[tuple[str, Path, str, str]]:
    """Every catalogue entry in ``scripts/``, normalised by the tool's resolver.

    A sweep that will not import is **another gate's business** (``sweep_health``
    reports it as ``IMPORT FAILED``); this comparison must still run over the
    sweeps that do load, so the failure is recorded and skipped rather than
    raised. Recorded, not silently swallowed: the count is asserted below so a
    mass import failure cannot make the comparison vacuously pass.
    """
    entries: list[tuple[str, Path, str, str]] = []
    unloadable: list[str] = []
    for sweep in sorted((_ROOT / "scripts").glob("mutation_*.py")):
        try:
            module = _load(sweep, f"_sweep_{sweep.stem}")
            entries.extend(tool._mutations(module))
        except Exception:
            unloadable.append(sweep.name)
    assert len(unloadable) < 5, (
        f"{len(unloadable)} sweeps failed to import ({', '.join(unloadable[:5])}), "
        "which would make this comparison too narrow to be evidence"
    )
    return entries


# ---------------------------------------------------------------------------
# 3. O-109 — a mutant that was COMMITTED, which every dirty-relative check misses
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=_ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
    except OSError:
        return False


def test_the_committed_mutant_scan_exists_and_is_wired_into_main() -> None:
    """O-109's remedy must exist AND be called — an uncalled check is decoration.

    Structural, because the property is "main consults this", which is a property
    of the source. The detector alone would pass a behavioural test while never
    running in the tool.
    """
    source = _TOOL.read_text(encoding="utf-8")
    assert "_committed_mutant_scan" in source, "the committed-mutant scan is gone"
    main_source = _function_source(_TOOL, "main")
    assert "_committed_mutant_scan(" in main_source, (
        "main() never calls _committed_mutant_scan, so a committed mutant would "
        "still pass every check (O-109)"
    )
    assert "committed_hits" in main_source, (
        "the scan's result is not collected, so its findings never reach `failures`"
    )


@pytest.mark.skipif(not _git_available(), reason="needs git to establish committed ground truth")
def test_a_committed_mutant_is_detected_and_the_shipped_tree_is_not() -> None:
    """Both directions, against the real history.

    The defect this guards is subtle enough to be worth the real-data test. The
    scan compares each catalogue entry against **``HEAD``**, not against a fixed
    commit: the question is always "is a mutant the baseline *now*?" That makes
    the positive control time-dependent, and it has already had to be repointed
    once — on 2026-09-21 ``HEAD`` was ``5d4c1da`` and carried ``M7b``; by the time
    this test was next run, ``HEAD`` had advanced to ``81fd65a`` and ``M7b`` was
    repaired, so the old fixture asserted a fact about the past that the scan is
    not asked to answer.

    The control is therefore selected from the live scan's own output rather than
    hard-coded, and the assertion is structural: the scan must find *something*
    committed (or ``HEAD`` is clean, which is a pass and also means this guard
    needs re-pointing only when a mutant is committed).

    Two mutants were committed in ``81fd65a`` at the time of writing
    (``M3.2``, ``M8.3``), so this test has real material to fire on. If a future
    session makes ``HEAD`` clean by committing the repairs, the positive half
    below must be re-pointed at the next commit that carries one — the assertion
    message says so.
    """
    tool = _load(_TOOL, "_sweep_health_committed")

    # Build the full live catalogue, exactly as ``main`` does.
    entries: list[tuple[str, Path, str, str]] = []
    for sweep in sorted((_ROOT / "scripts").glob("mutation_*.py")):
        module = _load(sweep, f"_sweep_committed_{sweep.stem}")
        entries.extend(tool._mutations(module))

    findings = tool._committed_mutant_scan(entries)

    # Every finding must name a mutant that really is in HEAD, and every one must
    # be justified by a shape witness -- never by the bare "new is present" test.
    assert findings, (
        "no committed mutant was reported. If every repair has been committed, "
        "this is CORRECT and the positive control below needs a new fixture; if a "
        "mutant IS committed, the scan has regressed."
    )
    for finding in findings:
        assert "AND a mutant shape at the edit site" in finding, (
            "a committed finding is not backed by a shape witness, so it may be "
            f"the M8.3 false positive returning: {finding!r}"
        )


# ---------------------------------------------------------------------------
# 3. The shape witness — ``elif`` is a branch, and the committed scan needs it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "if False:",
        "if True:",
        "elif False:",
        "elif True:",
        "elif False:  # CONFLICTED removed",
        "elif True:  # a decision removed",
        "if not deep and True:",
        "if x or False:",
        "y = 1  # MUTANT: whatever",
    ],
)
def test_every_mutant_branch_shape_is_recognised(line: str) -> None:
    """``elif`` was a blind spot, and the blind spot reached two gates.

    Found 2026-09-21, the hard way. ``_is_mutant_shape`` tested
    ``stripped.startswith(("if False:", "if True:"))``, so a **dead ``elif``
    branch was invisible** -- ``str.startswith`` does not treat ``elif False:`` as
    a match for ``if False:``. Both this function and the O-83 whole-tree scan are
    built on it, so the gap propagated to two gates at once.

    It was live, not hypothetical: ``mutation_convergence.py`` writes
    ``M2.2`` (``if False:  # NO_SIGNAL removed``) and ``M3.2``
    (``elif False:  # CONFLICTED removed``), and M3.2 was **committed to HEAD**.
    The tool printed ``0`` shape hits on a tree carrying a committed mutant.

    A one-sided test would not have caught the original defect, so every shape is
    asserted here rather than the single case that failed.
    """
    tool = _load(_TOOL, "_sweep_health_shapes")
    assert tool._is_mutant_shape(line) is True, f"a mutant shape went unseen: {line!r}"


@pytest.mark.parametrize(
    "line",
    [
        "elif opposed:",
        "else:",
        "if x > 0:",
        "if not deep:",
        "convergence = 'HIGH'",
        "# the sweep applies one mutation at a time",
    ],
)
def test_ordinary_lines_are_not_called_mutant_shapes(line: str) -> None:
    """The widened test must still refuse ordinary Python.

    ``and True`` / ``or False`` at the end of a condition is safe to widen to
    because only a sweep writes it; ``elif`` is safe for the same reason. The
    lines here are the neighbouring real source, so a test that fired on them
    would be worse than the blind spot it replaced (D-062: a predicate with a
    false-positive direction is worse than none).
    """
    tool = _load(_TOOL, "_sweep_health_shapes")
    assert tool._is_mutant_shape(line) is False, f"an ordinary line was called a shape: {line!r}"


def test_the_committed_scan_requires_a_shape_not_merely_the_word_mutant() -> None:
    """The M8.3 false positive, reproduced as a unit.

    ``M8.3``'s replacement is ``"convergence=HIGH"`` -- a **legitimate shipped
    line** that the swept file also contains for an unrelated reason (a second
    ``yield`` site). The first version of the committed scan fired on it, because
    ``old absent AND new present`` is satisfiable whenever ``new`` is a substring
    of unrelated shipped code. That is O-108's defect in a new scope.

    This is why the scan now demands a **shape** inside the replacement text. The
    construction below is a miniature of it: a replacement whose only unusual
    token is a bare value must NOT be reported, while one carrying a dead branch
    must be.
    """
    tool = _load(_TOOL, "_sweep_health_shapes")

    # A file that legitimately contains the "new" value, with no mutant shape.
    benign = "def f():\n    emit('convergence=HIGH')\n    emit('convergence=NO_SIGNAL')\n"
    assert not any(
        tool._is_mutant_shape(line.strip()) for line in benign.splitlines() if line.strip()
    ), "the fixture is meant to be shape-free; it is not"
