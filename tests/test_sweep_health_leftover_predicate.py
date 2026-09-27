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
def test_a_vanished_anchor_with_a_vanished_replacement_is_not_a_leftover(
    module_fixture: str, request: pytest.FixtureRequest
) -> None:
    """O-135: neither the anchor NOR the replacement is present — that is DRIFT.

    **The case that reported a leftover on a clean tree.** Measured at D-109:
    renaming a private helper in a swept module made one mutation's anchor and its
    replacement text both vanish, and `check_targets` printed ``MUTATION STILL
    APPLIED ... (replacement present AT THE EDIT SITE)`` — a sentence whose own
    parenthetical was false. `tools/sweep_health.py` reported **0 leftovers, 0
    committed mutants** at the same moment.

    **Why it matters:** the printed remedy is *"restore the file before
    sweeping"*, and the natural restore is ``git checkout --``, which discards
    uncommitted work — the D-086.8 incident, 97 lines. Correct answer: **not
    applied**, i.e. report the anchor as ABSENT rather than as a mutant.

    The fixture is a file in which NEITHER string occurs, which is exactly the
    post-rename state of a swept module.
    """
    module: Any = request.getfixturevalue(module_fixture)
    text = "def f():\n    return 1\n"
    old = "A_LINE_THAT_WAS_RENAMED_AWAY"
    new = "THE_REPLACEMENT_THE_SWEEP_WOULD_HAVE_WRITTEN"
    assert old not in text and new not in text, "the fixture must contain neither string"
    for label, predicate in _predicates(module):
        assert predicate(text, old, new) is False, (
            f"{label}: reported a leftover when BOTH the anchor and its replacement "
            "are absent — this is O-135, and the remedy it prints (`git checkout --`) "
            "destroys uncommitted work"
        )


@pytest.mark.parametrize("module_fixture", _BOTH_MODULES)
def test_the_both_absent_fix_did_not_blind_the_true_positive(
    module_fixture: str, request: pytest.FixtureRequest
) -> None:
    """The negative control for the O-135 fix, and it is the load-bearing half.

    A predicate "fixed" by returning ``False`` more often would satisfy the test
    above and stop detecting real leftovers — the failure direction that lets a
    mutant survive into a commit. So the same shape is built with the replacement
    PRESENT and must be reported.

    The two fixtures differ in exactly one thing: whether the sweep's replacement
    text was written. That is the discriminator, so nothing else can explain a
    difference in the verdict.
    """
    module: Any = request.getfixturevalue(module_fixture)
    old = "A_LINE_THAT_WAS_RENAMED_AWAY"
    new = "THE_REPLACEMENT_THE_SWEEP_WOULD_HAVE_WRITTEN"
    mutated = f"def f():\n    {new}\n"
    assert old not in mutated and new in mutated
    for label, predicate in _predicates(module):
        assert predicate(mutated, old, new) is True, (
            f"{label}: MISSED a genuine leftover after the O-135 fix — the fix must "
            "narrow the false positive, never the true one"
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

    **Marked ``slow``, re-measured at D-110 to ~350 s** — it must ``exec`` all 46
    sweeps (each imports the engine) to obtain the real catalogue. The three fast
    structural guards above it catch the same regression class at ~0.01s each;
    this one is the exhaustive backstop, so deselect it with ``-m "not slow"`` on
    a tight loop, not by deleting it.
    """
    # D-110: this test outgrew `--timeout=300`. The catalogue grew to 45 sweeps
    # AND `mutation_fx_carry.py` grew from 71 to 114 mutations, so the per-test
    # budget in `pyproject.toml` was raised to 600 s against a measured 349.78 s.
    # A bound below the real worst case kills a CORRECT test, which is why the
    # measurement is recorded here next to the marker that hides this test from a
    # default run.
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
def test_the_committed_mutant_scan_fires_on_a_commit_that_carries_one() -> None:
    """The POSITIVE control, against frozen history rather than against ``HEAD``.

    O-109's remedy is a scan that asks **git** whether a mutation is the baseline.
    Its positive control must therefore point at a commit that *is known to carry
    a mutant* — and that commit must be named explicitly, because ``HEAD`` moves.

    **This test has now been repointed twice, and the second time taught the
    lesson worth keeping.** It first hard-coded ``5d4c1da`` (which carried ``M7b``
    in ``lei_proxy.py``); ``HEAD`` advanced, ``M7b`` was repaired, and the fixture
    began asserting a fact about the past that the scan is not asked to answer. It
    was then rewritten to select its control from the **live** scan's own output —
    which merely moved the fragility: it required ``HEAD`` to be *currently dirty*,
    so committing the repairs (the desired end state!) broke the guard.

    **A guard that needs a live defect to exist is broken by the cure.** So the
    control is now pinned to the historical commit ``81fd65a``, which is immutable
    and carries two known committed mutants (``M3.2``, ``M8.3``). The scan is run
    against that revision by *stubbing* the revision it reads, so the test says
    "given this commit, does the scan see it?" — which is the actual property, and
    is independent of what ``HEAD`` happens to be today.
    """
    tool = _load(_TOOL, "_sweep_health_committed")

    entries: list[tuple[str, Path, str, str]] = []
    for sweep in sorted((_ROOT / "scripts").glob("mutation_*.py")):
        module = _load(sweep, f"_sweep_committed_{sweep.stem}")
        entries.extend(tool._mutations(module))

    # Frozen ground truth: 81fd65a carries M3.2 (elif False: in convergence.py)
    # and M8.3 (hardcoded "convergence=HIGH" in reasoning_stream.py).
    known_dirty = "81fd65a"
    original = tool._committed_blob

    def _blob_at_known_dirty(path: Path) -> str | None:
        blob: str | None = original(path, rev=known_dirty)
        return blob

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(tool, "_committed_blob", _blob_at_known_dirty, raising=False)
        findings = tool._committed_mutant_scan(entries)
    finally:
        monkeypatch.undo()

    assert findings, (
        f"the scan found nothing in {known_dirty}, which is known to carry M3.2 "
        "and M8.3. Either the revision no longer exists (re-point the fixture at "
        "another commit that carries a mutant) or the scan has regressed."
    )
    # Every finding must be backed by a shape witness, never by the bare
    # "new is present" test that produced the M8.3 false positive.
    for finding in findings:
        assert "AND a mutant shape at the edit site" in finding, (
            "a committed finding is not backed by a shape witness, so it may be "
            f"the M8.3 false positive returning: {finding!r}"
        )


@pytest.mark.skipif(not _git_available(), reason="needs git to establish committed ground truth")
def test_the_committed_mutant_scan_reports_nothing_on_a_clean_head() -> None:
    """The NEGATIVE control: the steady state is ``0``, and it must stay ``0``.

    ``HEAD`` being clean is the **desired** end state — the whole point of O-109's
    remedy is that a session can see it is clean. A guard whose negative half
    cannot pass on a clean tree is a guard that punishes success, so this asserts
    the opposite direction explicitly: on the real current ``HEAD``, the scan
    reports **no** committed mutants.

    If this ever fails, a mutant **has been committed** and the message names the
    finding — which is exactly the alarm O-109 exists to raise.
    """
    tool = _load(_TOOL, "_sweep_health_committed")

    entries: list[tuple[str, Path, str, str]] = []
    for sweep in sorted((_ROOT / "scripts").glob("mutation_*.py")):
        module = _load(sweep, f"_sweep_committed_{sweep.stem}")
        entries.extend(tool._mutations(module))

    findings = tool._committed_mutant_scan(entries)
    assert not findings, (
        "a mutant is committed in HEAD (O-109). Repair it and commit the repair://n  "
        + "\n  ".join(findings)
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


# ---------------------------------------------------------------------------
# O-72: the tool is ENFORCED in CI, and the enforcement is itself guarded.
# ---------------------------------------------------------------------------


def _workflow_step_text(job: str) -> list[str]:
    """Every field of every step in a CI job, CONCATENATED.

    Concatenating ``name``/``run``/``uses`` rather than picking one is deliberate:
    an earlier guard in this project matched ``name or run or uses``, and the step
    it looked for was *named* differently from what its ``run`` contained, so the
    guard reported the step missing when it was present (D-087.17). Reading all
    the text removes that guess.
    """
    import yaml

    path = _ROOT / ".github" / "workflows" / "quality-gates.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = workflow["jobs"][job]["steps"]
    return [
        " ".join(str(v) for k, v in step.items() if k in {"name", "run", "uses"}) for step in steps
    ]


def test_sweep_health_runs_in_the_merge_gate() -> None:
    """A gate run only by hand is not a gate (O-72, O-63).

    ``sweep_health.py`` was the project's most valuable check and nothing invoked
    it — *"gates run by hand from prose, and prose cannot refuse"*. This asserts it
    actually runs in CI, so the habit cannot silently lapse.
    """
    steps = _workflow_step_text("quality")

    runs = [s for s in steps if "sweep_health" in s]
    assert len(runs) == 1, (
        f"expected exactly one step running `tools/sweep_health.py` in the quality "
        f"job, found {len(runs)}: {steps}. The tool exists but nothing enforces it "
        "(O-72)."
    )


def test_sweep_health_runs_before_the_test_suite() -> None:
    """Order matters: fail fast on a dirty tree, before the long step.

    A tree carrying a mutant is not worth running a two-minute suite against, and
    the suite is the expensive step. This is the opposite of the *local* habit —
    where the tool runs LAST because it is a photograph of the tree — and both are
    deliberate.
    """
    steps = _workflow_step_text("quality")

    runs = [i for i, s in enumerate(steps) if "sweep_health" in s]
    tests = [i for i, s in enumerate(steps) if "pytest" in s or "Test suite" in s]
    assert runs and tests, f"missing step(s): runs={runs} tests={tests}"
    assert runs[0] < tests[0], (
        "sweep_health must run BEFORE the offline test suite in the quality job "
        f"(step order: {steps})"
    )


def test_the_sweep_health_step_can_actually_fail_the_job() -> None:
    """No ``|| true``, no ``continue-on-error`` — the tool must be able to refuse.

    The tool already returns non-zero on a failure; an unguarded invocation is what
    lets that reach the job status. Any swallowing construct turns the gate back
    into the prose it replaced.
    """
    import yaml

    path = _ROOT / ".github" / "workflows" / "quality-gates.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    matching = [
        s
        for s in workflow["jobs"]["quality"]["steps"]
        if "sweep_health" in str(s.get("run") or "") or "sweep_health" in str(s.get("name") or "")
    ]
    assert matching, "no sweep_health step found (see the wiring test)"

    step = matching[0]
    run = str(step.get("run", ""))
    assert "|| true" not in run, f"the sweep_health step swallows failure: {run!r}"
    assert "|| exit 0" not in run, f"the sweep_health step forces success: {run!r}"
    assert not step.get("continue-on-error"), (
        f"the sweep_health step is marked continue-on-error, so a mutant cannot fail "
        f"the job: {step!r}"
    )


# ---------------------------------------------------------------------------
# The control-coverage line (O-72's first half, made visible)
# ---------------------------------------------------------------------------
# `sweep_health.py` checks the GATES, not the KILLINGS, and it stays that way --
# it cannot ask whether a resolving sweep would still kill. What it CAN see is
# which sweeps have NO way to notice that their own baseline broke: a sweep with
# neither `expect_killed` nor a `.killed` read reports "everything killed" just
# as loudly on a broken baseline as on a strong suite. That is the D-051 trap.


def test_the_control_marker_set_accepts_both_legitimate_mechanisms(
    tool_module: Any,
) -> None:
    """Both mechanisms must count, or the check flags correct sweeps (O-107).

    The FIRST version of this check recognised only a `.killed` read and
    therefore reported **six false positives** -- every one of them a sweep that
    declares its control with `expect_killed=False` instead. A gate that flags
    correct code is one the operator learns to ignore, which is the failure this
    whole family of checks exists to avoid.
    """
    markers = tool_module._CONTROL_MARKERS

    assert "expect_killed" in markers, (
        "the expect_killed mechanism is no longer recognised; sweeps using it "
        "will be reported as control-less even though they have a control"
    )
    assert any(".killed" in m for m in markers), (
        "the .killed read is no longer recognised; the 12 sweeps using the "
        "explicit D-051 refusal will be reported as control-less"
    )


def test_a_bare_method_definition_is_not_a_control_use(tool_module: Any) -> None:
    """`def killed` must NOT count as a control; `.killed` must.

    Measured on ``mutation_risk_axis.py``: a mutant that removed both real uses
    still matched the original, looser predicate, because the property
    *definition* remained. **Verify what a predicate actually matched before
    believing its verdict** (lesson 5cm), and pin the fix here so the loose
    predicate cannot come back.
    """
    markers = tool_module._CONTROL_MARKERS
    definition = "    def killed(self) -> bool://n        return True\n"

    assert not any(m in definition for m in markers), (
        "a bare method definition still matches a control marker, so removing "
        "every real use of the mechanism would not be detected"
    )
    assert any(m in "    if control.killed://n        return 2\n" for m in markers), (
        "an attribute read no longer matches, which breaks the check in the "
        "false-positive direction"
    )


def test_the_control_scan_runs_over_the_real_sweep_directory(tool_module: Any) -> None:
    """The scan must produce a POSITIVE count of recognised controls.

    The original form of this guard refused both zero AND all: *"zero means the
    predicate matches nothing; all means it matches everything."* That was right
    when the population was mixed.

    **It is now the wrong guard, and leaving it in would have failed on the
    correct tree** -- which is the failure mode this file has re-learned three
    times (a guard pinned to a transient state becomes an alarm the moment the
    state improves; D-087.14, D-087.18, and now here). The "all" half is no
    longer a pathology: O-72's first half was closed on 2026-09-21, so **all 40
    sweeps are EXPECTED to have a control**, and `all` is the success condition.

    What remains a pathology is **zero recognised matches**, which means the
    predicate itself has stopped working. That is what this asserts, and it is
    what a marker-set edit could plausibly break.
    """
    sweeps = sorted((_ROOT / "scripts").glob("mutation_*.py"))
    assert sweeps, "no sweeps found; the glob is wrong"

    matched = [p.name for p in sweeps if tool_module._control_markers(p)]
    assert matched, (
        f"the control scan matched NO control in any of {len(sweeps)} sweeps. "
        "The predicate has stopped working -- either the marker set was edited "
        "to strings that do not occur, or every sweep changed mechanism at once. "
        "Either way the coverage line is no longer a measurement."
    )
    # Both non-trivial mechanisms must still be found in the population, so a
    # marker that matches only one family cannot masquerade as full coverage.
    kinds = {m for p in sweeps for m in tool_module._control_markers(p)}
    assert len(kinds) >= 2, (
        f"only one control mechanism was found across all 40 sweeps: {kinds}. "
        "Three are legitimate (expect_killed, a .killed refusal, the CANARY1 "
        "gate); finding one suggests the others were dropped from the marker set."
    )


def test_a_control_less_sweep_is_reported_not_failed(tool_module: Any) -> None:
    """Coverage is REPORTED, never failed -- the same discipline as O-29.

    Neither mechanism is required by any specification, and turning a missing
    control into a build failure would block legitimate work on a convention that
    does not exist. The value is that the gap is VISIBLE.

    **The gap is now CLOSED (O-72's first half, 2026-09-21): all 40 sweeps carry
    a control.** This guard therefore flips from "there are gaps, prove they are
    reported" to "there are none, prove the scan still runs and the line still
    prints". Asserting the old `missing`-is-non-empty condition would now FAIL on
    the correct tree, which is the failure mode this file keeps re-learning: *a
    guard pinned to a transient state becomes a false alarm the moment the state
    improves* (D-087.14, one level up).
    """
    sweeps = sorted((_ROOT / "scripts").glob("mutation_*.py"))
    missing = [p.name for p in sweeps if not tool_module._control_markers(p)]
    text = _TOOL.read_text(encoding="utf-8")

    assert "sweeps with NO honesty control" in text, (
        "the control-coverage line is not printed; the scan exists but nothing "
        "shows it, which is the O-62 shape one level down"
    )
    assert "NO CONTROL ->" in text, "the per-sweep detail line is missing"

    # The coverage assertion, restated as an INVARIANT that is true and stays
    # true: the scan must classify EVERY sweep, and (since O-72's first half) it
    # must find none without a control. If a new sweep is added without one, the
    # count goes up and this test tells you -- it does not fail the build.
    #
    # 40 -> 41 at D-087.23 (`mutation_performance_record.py`), which carries the
    # same CANARY1 gate as the rest. 41 -> 42 at D-087.27
    # (`mutation_command_inventory.py`, O-104) -- also a CANARY1 sweep, so the
    # `missing == []` assertion below still holds without a second edit.
    # 42 -> 43 at D-092 (`mutation_econometrics.py`, Module 18) -- likewise a
    # CANARY1 sweep, so the same holds a third time.
    # 43 -> 44 at D-106 (`mutation_monte_carlo_var.py`, Module 17/models/risk.py)
    # -- the first sweep over models/risk.py, and likewise a CANARY1 sweep.
    # 44 -> 45 at D-108 (`mutation_fx_carry.py`, Module 9/models/fx_carry.py) --
    # the first sweep over a module a Tier-5 increment CREATED, and likewise a
    # CANARY1 sweep, so `missing == []` still holds without a second edit.
    # 45 -> 46 at D-118 (`mutation_intervention.py`, Module 9/models/intervention.py
    # + data_layer/reserves_client.py + the config block) -- the SECOND sweep over
    # a module a Tier-5 increment created, and likewise a CANARY1 sweep, so
    # `missing == []` still holds without a second edit.
    assert len(sweeps) == 46, f"expected 46 sweeps, found {len(sweeps)}"
    assert missing == [], (
        f"{len(missing)} sweep(s) lost their control: {missing}. O-72's first "
        "half was closed on 2026-09-21 by adding a CANARY1 gate to all 18; a new "
        "control-less sweep is a regression against that, not a coverage gap."
    )


# ---------------------------------------------------------------------------
# The O-72 canary (the third control mechanism)
# ---------------------------------------------------------------------------
# The 18 sweeps that had no control were given one in the form the task called
# for: a mutation that MUST BE KILLED. That is the OPPOSITE polarity from the
# other two mechanisms (`expect_killed=False` requires SURVIVAL; the `.killed`
# refusal fires when a survivor appears among `CONTROL`-named entries). A gate
# that recognised only the old two would report all 18 as still control-less
# after they had been fixed -- which is exactly what the FIRST run of this tool
# after the change did.


def test_the_canary_marker_is_recognised(tool_module: Any) -> None:
    """The third mechanism must count, or O-72's fix reads as a regression.

    This is **O-107's narrow predicate for the FIFTH time in this project**: the
    marker set was written when only two mechanisms existed, and a check that
    does not know about a new legitimate form reports the fixed state as broken.
    """
    markers = tool_module._CONTROL_MARKERS

    assert any("CANARY" in m or "canary" in m for m in markers), (
        "the CANARY1 gate is not a recognised control; all 18 sweeps fixed for "
        "O-72 will be reported as control-less even though they now have one"
    )


def test_every_sweep_declares_a_recognised_control(tool_module: Any) -> None:
    """All 40 sweeps, and the marker each one actually matched.

    Reported per-sweep rather than as a bare count, so a failure names the file
    and the mechanism -- the O-107 lesson (*verify what a predicate actually
    matched before believing its verdict*).
    """
    sweeps = sorted((_ROOT / "scripts").glob("mutation_*.py"))
    unmatched = [p.name for p in sweeps if not tool_module._control_markers(p)]

    assert unmatched == [], f"no recognised control in: {unmatched}"


def test_the_canary_marks_a_mutation_that_must_be_killed(tool_module: Any) -> None:
    """The canary's polarity: it is killed, and surviving REFUSES certification.

    A behavioural clone of the other two mechanisms would be useless here -- the
    point is that the canary is a **structural** kill (a syntax error stops test
    collection dead), so it cannot quietly become inert. Checked on a sample of
    the 18, in the source text, because running a sweep is minutes per file.
    """
    for stem in ("mutation_probability", "mutation_lei_proxy", "mutation_scorecard"):
        text = (_ROOT / "scripts" / f"{stem}.py").read_text(encoding="utf-8")

        assert "CANARY1" in text, f"{stem}: the canary mutation is missing"
        assert "<<<SYNTAX ERROR>>>" in text, (
            f"{stem}: the canary is no longer a structural break; a behavioural "
            "canary can become inert without anyone noticing"
        )
        assert "REFUSING TO CERTIFY: the honesty canary SURVIVED" in text, (
            f"{stem}: the canary exists but nothing acts on its survival, so it "
            "reports rather than gates (O-88: a gate row is a CLAIM, not a "
            "receipt)"
        )
        # Surviving must be a refusal, not a normal survivor.
        assert "return 3" in text, (
            f"{stem}: the canary refusal does not exit non-zero, so a sweep that "
            "tested nothing would still certify"
        )


def test_the_canary_gate_refuses_when_the_selection_is_broken(tmp_path: Path) -> None:
    """FUNCTIONAL: break the selection, and the sweep must exit 3, not 0.

    This is the guard that matters, because the other four are textual and a
    textual check cannot tell a gate that fires from one that is merely written
    down. The D-051 trap is *"every mutant reports as killed because nothing
    executes"*, and the only way to know the canary catches it is to build the
    trap and watch it trip.

    The instrument is the smallest control-bearing sweep, run from a COPY in a
    temp directory with its test selection rewritten to a module the mutation
    does not affect. Verified by hand before this test was written: exit 3, with
    the canary listed among the survivors and the refusal printed.
    """
    source = _ROOT / "scripts" / "mutation_inflation_nowcast.py"
    text = source.read_text(encoding="utf-8")
    original_target = '"tests/models/test_inflation_nowcast.py",'
    assert original_target in text, (
        "the sweep's test selection changed shape; update this test rather than "
        "deleting it -- it is the only functional proof the canary gates"
    )
    broken = text.replace(original_target, '"tests/models/test_auctions.py",', 1)
    assert broken != text

    sandbox = tmp_path / "scripts"
    sandbox.mkdir()
    # The sweep imports its gate helper from the sibling module.
    (sandbox / "_sweep_gate.py").write_text(
        (_ROOT / "scripts" / "_sweep_gate.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # D-087.27 (O-110) — THE SANDBOX MUST ACTUALLY BE ONE.
    #
    # `mutation_inflation_nowcast.py` resolves its target as a RELATIVE path
    # (`SRC = Path("src/macro_engine/models/inflation_nowcast.py")`). With
    # `cwd=_ROOT` — which is what this test used — the sweep wrote its mutant
    # into the REAL tree and relied on its own restore to undo it. That worked
    # whenever the run completed and failed whenever it was KILLED: measured on
    # 2026-09-22, a run interrupted at 78% left `confidence=0.55` sitting in
    # `src/macro_engine/models/inflation_nowcast.py` beside a `.sweepbackup`.
    # The sidecar healed it byte-exactly (the O-103 mechanism working as
    # designed) — but a TEST must not need the production safety net to avoid
    # corrupting the tree it is testing.
    #
    # The cwd must STAY `_ROOT`: the sweep shells out to
    # `pytest tests/models/test_inflation_nowcast.py`, and from a foreign cwd
    # pytest cannot collect (`tests.helpers` is unimportable and neither
    # `pythonpath` nor `testpaths` resolves — measured). Repointing the cwd
    # consequently made EVERY mutation look "killed", including the canary,
    # because `run_tests()` returned non-zero for an unrelated reason. That is
    # the D-051 trap re-entering through the fix for a different defect.
    #
    # So instead the sandbox copy is given an ABSOLUTE `SRC` inside `tmp_path`:
    # the sweep runs from the real root (tests collect) but can only write to the
    # sandbox (no mutant can reach the real tree).
    sandbox_target = tmp_path / "inflation_nowcast.py"
    sandbox_target.write_text(
        (_ROOT / "src" / "macro_engine" / "models" / "inflation_nowcast.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    # `as_posix()` so the literal carries forward slashes: on Windows `str(Path)`
    # yields backslashes, which `repr()` then escapes (`'C:\\Users\\...'`) and the
    # path-separator doubling makes the "did the replacement land" check below
    # compare two differently-escaped strings (measured — the first version of
    # this fix failed exactly there). Forward slashes are valid on Windows and
    # `Path` normalises them, so the sweep's `SRC` still resolves.
    src_literal = sandbox_target.as_posix()
    broken = broken.replace(
        'SRC = Path("src/macro_engine/models/inflation_nowcast.py")',
        f"SRC = Path({src_literal!r})",
        1,
    )
    assert src_literal in broken, (
        "the sweep's SRC declaration changed shape; update this replacement "
        "rather than deleting it -- it is what keeps the mutation inside the sandbox"
    )
    (sandbox / "mutation_inflation_nowcast.py").write_text(broken, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(sandbox / "mutation_inflation_nowcast.py")],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert proc.returncode == 3, (
        "the canary did NOT gate: with the test selection pointed at an "
        f"unrelated module the sweep still exited {proc.returncode}. Every "
        "'killed' in that run is a claim about the harness, not the suite.\n"
        f"stdout tail:\n{proc.stdout[-1500:]}"
    )
    assert "REFUSING TO CERTIFY: the honesty canary SURVIVED" in proc.stdout


# ---------------------------------------------------------------------------
# The derived sweep budget (O-112(c))
# ---------------------------------------------------------------------------
# O-112 asked for exactly this: *"no gate asserts that the driver's budget
# exceeds the sweep's measured cost, so the two can drift apart again."* The
# remedy is to DERIVE the budget from the catalogue rather than type it, so
# changing a sweep's mutation count moves the budget with it.


def test_the_budget_derives_from_the_declared_mutation_count(tool_module: Any) -> None:
    """The budget must be a FUNCTION of the catalogue, not a constant.

    O-112's defect was a flat `timeout 600` against `mutation_api_layer.py`, whose
    **42** mutations at a measured **39.73 s** each give a floor of **~1,700 s**.
    The kill was arithmetic, not bad luck. A derivation makes that class of
    mistake impossible to repeat by hand.
    """
    derive = tool_module._sweep_budget

    assert derive(100) > derive(10), "the budget does not grow with the catalogue"
    assert derive(10) < derive(100) < derive(1000), "the budget is not monotonic"


def test_the_floor_applies_to_tiny_sweeps(tool_module: Any) -> None:
    """A small catalogue must still get a usable budget.

    Three mutations at 75 s is 225 s, which is under one `uv run pytest` startup
    on a cold cache -- so the floor matters independently of the multiplier.
    """
    floor = tool_module._BUDGET_FLOOR_SECONDS

    assert tool_module._sweep_budget(0) == floor
    assert tool_module._sweep_budget(1) == floor
    assert tool_module._sweep_budget(1000) > floor


def test_the_budget_covers_the_measured_case_o112_recorded(tool_module: Any) -> None:
    """The derivation must clear the ONE case that is actually measured.

    This is the regression that matters: `mutation_api_layer.py` certifies in
    **1,066 s** and its arithmetic floor is **~1,700 s**. A budget that does not
    clear the floor would have killed the very sweep O-112 was written about.
    """
    api_layer_mutations = 42
    measured_seconds = 1066
    arithmetic_floor = 1700

    budget = tool_module._sweep_budget(api_layer_mutations)
    assert budget > measured_seconds, (
        f"the derived budget {budget} s does not clear the MEASURED cost of "
        f"{measured_seconds} s for mutation_api_layer.py, so O-112 would recur"
    )
    assert budget > arithmetic_floor, (
        f"the derived budget {budget} s does not clear the arithmetic FLOOR of "
        f"{arithmetic_floor} s, so the sweep would be killed mid-run"
    )


def test_no_pass_through_budget_constant_survives(tool_module: Any) -> None:
    """The old flat number must not be re-introduced as a literal.

    A `600` returned directly for every sweep is the D-087.11 defect verbatim.
    """
    derive = tool_module._sweep_budget
    values = {derive(n) for n in (0, 1, 5, 42, 87, 500)}

    assert len(values) > 1, (
        "the budget is constant across every catalogue size, which is exactly "
        "the flat-timeout defect O-112 recorded"
    )
    assert 600 not in {derive(42), derive(87)}, (
        "a sweep with dozens of mutations is getting a 600 s budget, which is the D-087.11 defect"
    )


def test_the_largest_real_sweep_clears_the_old_flat_budget(tool_module: Any) -> None:
    """Print the drift, and fail if it ever becomes harmless in a misleading way.

    Measured on the real directory: the largest sweep is `mutation_scorecard.py`
    at **87** mutations, whose derived budget is **6,525 s** — **10.9x** the old
    flat 600 s. The assertion is on the RELATIONSHIP, so it survives the catalogue
    growing.
    """
    sweeps = sorted((_ROOT / "scripts").glob("mutation_*.py"))
    counts = []
    for path in sweeps:
        module = _load(path, f"_budget_{path.stem}")
        counts.append((len(tool_module._mutations(module)), path.name))

    assert counts, "no sweeps found"
    biggest, name = max(counts)
    derived = tool_module._sweep_budget(biggest)

    assert derived > 600, (
        f"{name} declares {biggest} mutations but its derived budget is only "
        f"{derived} s, which the old flat 600 s would have covered -- if that is "
        f"genuinely true, delete this test rather than weaken it"
    )


def test_the_budget_table_is_actually_printed() -> None:
    """`--budgets` must produce a usable table, not just exist.

    A derivation nothing can read is O-62's shape one level down: the arithmetic
    is right and no driver author will ever see it. The driver O-112 was written
    about was a THROWAWAY in `.probe/` and no longer exists, which is precisely
    why the formula has to live somewhere durable.
    """
    result = subprocess.run(
        [sys.executable, str(_TOOL), "--budgets"],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        check=False,
    )

    assert result.returncode == 0, f"--budgets exited {result.returncode}: {result.stderr}"
    combined = result.stdout + result.stderr
    assert "budget" in combined and "mutations" in combined, (
        f"the budget table is missing from the output: {combined!r}"
    )
    # The largest sweep must be named, so the number is actionable.
    assert "mutations" in combined, "no per-sweep rows"
    assert "total wall-clock" in combined, "the serial total is missing"


def test_the_budget_constant_is_documented_with_its_reason(tool_module: Any) -> None:
    """A budget constant typed without its derivation is the defect returning.

    `75` is not a round number chosen for looks -- it is ~1.9x the one measured
    per-mutation cost (39.73 s). A future editor must be able to challenge it.
    """
    source = _TOOL.read_text(encoding="utf-8")

    assert "_BUDGET_SECONDS_PER_MUTATION = 75" in source
    assert "39.73" in source, (
        "the per-mutation constant no longer cites the measurement it came from, "
        "so a reader cannot tell whether it is earned or invented"
    )
    assert "O-112" in source, "the constant does not name the issue it closes"


# ---------------------------------------------------------------------------
# Every sweep must be able to START (O-62)
# ---------------------------------------------------------------------------
# O-62 states the failure mode exactly: *"a sweep that cannot run is
# indistinguishable from a sweep nobody ran."*
#
# Measured on 2026-09-22, and it was not hypothetical: `HEAD` was in a state
# where `mutation_inflation_nowcast.py` exited **4 on every invocation**, because
# two of its twenty anchors (M5, M6) were written against a source text the file
# no longer contained. The module under test had been changed from
# `data_quality_flags_present=True` to `False` without the anchors or the
# docstring being updated, so:
#
#   * the sweep was silently DISABLED — all 20 mutations would have been reported
#     as survivors had it been allowed to run, and instead it refused entirely;
#   * the 2 tests that pinned the intended behaviour were FAILING on `HEAD`;
#   * `tools/sweep_health.py` — the repository's headline gate, the one run LAST —
#     exited 1 and reported two phantoms as "source corruption".
#
# The recorded snapshot said `0 leftovers, 0 failures, OK`, which is the D-087.23
# defect class once more: a state that was never re-measured after the tree it
# described changed under it.
#
# These tests ask the question that snapshot failed to ask — *can each sweep
# still resolve its own anchors?* — by loading every catalogue and running the
# SAME predicate the sweeps run, against the SHIPPED text.


def _as_entry(entry: tuple[object, ...]) -> tuple[str, Path, str, str] | None:
    """Narrow an untrusted catalogue row to the 4-tuple every sweep uses.

    ``None`` for anything that is not exactly ``(str, path-like, str, str)``.
    Written as a real predicate rather than a bare ``assert`` so mypy narrows in
    the callers, and so a malformed row is *reported* by the tests below instead
    of crashing the guard that is supposed to find malformed rows.
    """
    if len(entry) != 4:
        return None
    name, target, old, new = entry
    if not isinstance(name, str) or not isinstance(old, str) or not isinstance(new, str):
        return None
    if not isinstance(target, (str, Path)):
        return None
    return name, Path(target), old, new


def _all_catalogues() -> list[tuple[str, list[tuple[object, ...]]]]:
    """Load every sweep's mutation table, skipping ones that cannot be loaded.

    Entries are typed ``tuple[object, ...]`` rather than the 4-tuple the sweeps
    actually use, because these tables are **untrusted input**: they come from
    modules this test does not own, and a malformed entry is exactly the kind of
    thing a guard over 42 hand-written catalogues must survive rather than crash
    on. The narrowing below is therefore real work, not ceremony.

    An import failure is caught by `sweep_health.py` itself and is not this
    test's claim, so it is skipped here rather than reported twice — and skipped
    **without `except: continue`**, which ruff flags as `S112` for a reason this
    project has already recorded: a silent skip makes a broken module look like a
    module with nothing in it. The error is collected and asserted on instead.
    """
    found: list[tuple[str, list[tuple[object, ...]]]] = []
    broken: list[str] = []
    for path in sorted((_ROOT / "scripts").glob("mutation_*.py")):
        spec = importlib.util.spec_from_file_location(f"_cat_{path.stem}", path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            broken.append(f"{path.name}: no loader")
            continue
        module = importlib.util.module_from_spec(spec)
        # Required for modules that use `@dataclass`: without registering the
        # module in `sys.modules` first, `dataclasses` resolves
        # `sys.modules[cls.__module__]` to None and raises
        # `AttributeError: 'NoneType' object has no attribute '__dict__'`.
        # Measured — this is exactly how the first version of this helper failed
        # on the sweeps that declare dataclasses. `tools/sweep_health.py` carries
        # the same line for the same reason.
        sys.modules[spec.name] = module
        added = str(_ROOT / "scripts")
        prepended = added not in sys.path
        if prepended:
            sys.path.insert(0, added)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # returned and asserted on, not swallowed
            broken.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        finally:
            if prepended:
                sys.path.remove(added)
        table = getattr(module, "_MUTATIONS", None)
        if callable(table):
            table = table()
        if table:
            found.append((path.name, list(table)))

    assert not broken, (
        "these sweep modules could not be imported, so their catalogues were "
        "NOT checked (a sweep that cannot run is indistinguishable from one "
        "nobody ran — O-62):\n  " + "\n  ".join(broken)
    )
    return found


def test_every_sweep_catalogue_resolves_against_the_shipped_source() -> None:
    """**The O-62 guard.** No catalogue may name an anchor the tree does not hold.

    Asserted per sweep so a failure names the sweep, and asserted against the
    shipped text so the check cannot be satisfied by a stale sidecar.

    A drifted anchor is NOT a cosmetic problem: it disables the mutation, and a
    disabled mutation reports as a survivor that never ran. The measured
    instance exited 4 and turned the headline health gate red.
    """
    catalogues = _all_catalogues()
    assert catalogues, "no sweep catalogues could be loaded; the glob is wrong"

    unresolved: list[str] = []
    malformed: list[str] = []
    for name, table in catalogues:
        for raw in table:
            row = _as_entry(raw)
            if row is None:
                malformed.append(f"{name}: malformed catalogue row {raw!r}")
                continue
            mutation, target, old, _new = row
            if not target.exists():
                unresolved.append(f"{name}: {mutation} — TARGET ABSENT ({target})")
                continue
            text = target.read_text(encoding="utf-8")
            if text.count(old) == 0:
                unresolved.append(f"{name}: {mutation} — anchor resolves 0 times in {target.name}")

    assert not malformed, (
        "these catalogue rows are not (name, target, old, new), so they were not "
        "checked at all:\n  " + "\n  ".join(malformed)
    )
    assert not unresolved, (
        "these sweeps cannot START because their anchors no longer match the "
        "shipped source (O-62 — a sweep that cannot run looks like a sweep "
        "nobody ran):\n  " + "\n  ".join(unresolved)
    )


def test_no_sweep_catalogue_holds_a_leftover_shaped_anchor() -> None:
    """The mirror: an anchor whose ``new`` is already shipped is a leftover.

    `_is_applied`'s discriminator, applied to every catalogue entry against the
    shipped text. This is the *false*-direction companion to the test above: one
    asks "can the sweep start", this asks "is the tree already mutated". The
    M5/M6 incident had both readings available and the recorded snapshot asserted
    neither.
    """
    leftovers: list[str] = []
    for name, table in _all_catalogues():
        for raw in table:
            row = _as_entry(raw)
            if row is None:
                continue  # the test above reports malformed rows
            mutation, target, old, new = row
            if not target.exists() or not new.strip():
                continue
            text = target.read_text(encoding="utf-8")
            if text.count(old) == 0 and new in text:
                leftovers.append(f"{name}: {mutation} — `new` text is SHIPPED")

    assert not leftovers, (
        "these catalogues describe the tree as already-mutated, which is the "
        "leftover signal — either the tree carries a mutant or the anchor is "
        "written against a text that no longer exists (the M5/M6 shape):\n  "
        + "\n  ".join(leftovers)
    )
