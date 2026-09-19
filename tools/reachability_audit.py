"""Reachability audit — which model functions is the pipeline allowed to forget?

**Why this tool exists.** On 2026-09-19 an audit found that most of the 77 model
functions in ``src/macro_engine/models/`` are never referenced by any non-model
module. A real ``POLICY_PATH_GAP`` thesis executes 12 of them. The functions are
implemented, unit-tested, and several have mutation sweeps — they are correct.
They simply have no caller.

The headline number has moved as legs were wired: 63 at first measurement, then
62, 61, 59 after the regime, national-accounts and curve legs landed. Report the
*measured* number, never a remembered one — this docstring carried the stale 63
for a while, which is itself the class of drift the tool exists to catch.

A unit test cannot catch the gap: it tests the callee. A mutation sweep cannot
catch it: it mutates the callee. Nothing in the suite asserted that the
*pipeline calls the thing*, so the gap opened silently and stayed open. This
tool is that assertion.

**How it decides.** Two independent passes, because each has a blind spot. The
static pass runs by default; the dynamic pass is opt-in via ``--dynamic``.

1. *Static* — an AST scan for every non-model module that names a model
   function. Catches callers the dynamic pass would miss (branches not taken on
   the sample snapshot). Cannot see through aliasing or dynamic dispatch.
   Counting is by **call expression**, never by name match, because a name in a
   docstring is not a caller — the first version of this tool reported
   ``compute_confidence`` as wired on the strength of a comment in ``config.py``.
2. *Dynamic* — actually build a thesis on the persisted snapshot with every
   public model function wrapped by a recorder, and log what ran. Ground truth
   for the specific path taken, but blind to paths this snapshot does not
   exercise, and it needs the live data layer, so it is not in CI.

Neither alone is sufficient: the static pass over-reports (a name in a comment
or a ``TYPE_CHECKING`` import is not a call), and the dynamic pass under-reports
(nothing calls a branch that the sample data does not reach). Measured
2026-09-19: static finds 20 reachable, dynamic confirms 18 execute — the two
disagree on exactly the functions whose branch the sample did not take, which is
the disagreement both passes exist to expose. A function flagged by *both* is a
genuine gap.

**Tier awareness.** ``AGENTS.md`` §21.3 splits the functions into Tiers 1-4
(buildable in Phases 0-3) and Tier 5 (Phase 5+ stubs, legitimately unimplemented
or unwired). Only Tier 1-4 gaps are counted; Tier 5 is reported separately as
expected state. Without this split the tool would demand wiring for functions
the spec explicitly defers.

**The baseline gate.** ``config/reachability_baseline.txt`` pins the known,
triaged unreachable set. CI fails on a **regression** — a function that was
reachable and stopped being — and on a **stale baseline**, rather than on the
backlog itself. A gate that is red for reasons nobody intends to fix is a gate
people learn to skip; this one is red only when something changed. The same
check runs in the offline suite (``tests/test_reachability_gate.py``), so it is
asked on every run and not only when someone remembers the tool.

Usage::

    uv run python tools/reachability_audit.py              # report
    uv run python tools/reachability_audit.py --dynamic    # + what executed
    uv run python tools/reachability_audit.py --check-baseline  # CI gate
    uv run python tools/reachability_audit.py --write-baseline  # record truth
"""

from __future__ import annotations

import argparse
import ast
import importlib
import re
import sys
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "macro_engine"
MODELS = SRC / "models"
SPEC = ROOT / "AGENTS.md"
BASELINE = ROOT / "config" / "reachability_baseline.txt"

# A module outside models/ that references a model function by name is a real
# consumer only if it is part of the shipped package. Scripts are live-wiring
# checks (Section 21.0) — they prove a function works against real data, which
# is a *different* claim from "the pipeline uses it", so they are tracked and
# reported separately rather than counted as pipeline reachability.
PIPELINE_ROOT = SRC
SCRIPT_ROOTS = ("scripts", "tools")


def read_baseline() -> set[str] | None:
    """The committed set of Tier 1-4 functions known to be unreachable.

    Returns ``None`` when no baseline file exists, so a missing baseline is
    distinguishable from an empty one. That distinction matters: an empty
    baseline means "we claim nothing is unreachable", a missing one means "we
    have not decided yet", and collapsing them would let a deleted file silently
    pass the gate.
    """
    if not BASELINE.exists():
        return None
    out: set[str] = set()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            out.add(stripped)
    return out


def write_baseline(unreachable: set[str]) -> None:
    """Persist ``unreachable`` as the new baseline, with its own provenance."""
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# config/reachability_baseline.txt",
        "#",
        "# The Tier 1-4 model functions known to have no pipeline caller, as",
        "# measured by tools/reachability_audit.py. Regenerate with:",
        "#",
        "#     uv run python tools/reachability_audit.py --write-baseline",
        "#",
        "# WHY A BASELINE AND NOT A HARD FAIL. Every entry here is a known,",
        "# triaged finding: either Phase 4+ by endpoint (the risk/portfolio",
        "# suite) or blocked on data that no reachable route supplies (the FCI's",
        "# three missing series). Failing CI on all of them would make the gate",
        "# something people learn to ignore within a week. What the gate DOES",
        "# fail on is a REGRESSION — a function that was reachable and stopped",
        "# being — and an entry that leaves this file without being wired, which",
        "# is how a decision to drop a function gets recorded rather than",
        "# silently absorbed by a baseline refresh.",
        "#",
        "# Removing a line from this file is a claim that the function is now",
        "# reachable. The audit checks that claim.",
        "",
    ]
    lines.extend(sorted(unreachable))
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _recorded_calls() -> tuple[set[str], str | None]:
    """Build a real thesis with every model function wrapped, and log what ran.

    This is the **dynamic** half of the audit. The static pass asks *"does any
    non-model module name this function?"*; this asks *"does it actually
    execute when the pipeline runs?"* — and the two can disagree in both
    directions, which is the whole reason both exist:

    * a function whose only static caller is inside a branch the live snapshot
      never takes runs on nothing, and a static-only audit calls it wired;
    * a function invoked through ``getattr`` or a dispatch table has no static
      call site at all, and a static-only audit calls it an orphan.

    Wrapping works by replacing each public model function on its module object
    with a recorder that delegates. That catches the *direct* call — which is
    all that is needed, because the question is about the function itself, not
    about its transitive helpers.

    Returns ``(names_that_ran, error)``. On error the set is empty and the
    reason is returned, because a silent empty set would read as "nothing is
    wired" — the single most misleading possible failure for this tool.
    """
    sys.path.insert(0, str(SRC))

    ran: set[str] = set()
    modules: list[tuple[str, object]] = []
    try:
        for stem, name, _path in model_functions():
            module = importlib.import_module(f"macro_engine.models.{stem}")
            original = getattr(module, name, None)
            if original is None or not callable(original):
                continue
            modules.append((f"{stem}.{name}", _wrap(module, name, original, ran)))
    except Exception as exc:  # pragma: no cover - import environment dependent
        return set(), f"could not wrap model functions: {exc!r}"

    try:
        # The import of the pipeline happens *after* wrapping so that modules
        # which do ``from ... import func`` at import time still get the
        # recorder — otherwise a from-import would bind the original and the
        # dynamic pass would under-count.
        from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
        from macro_engine.api_layer.snapshot_provider import get_snapshot
        from macro_engine.models.instrument_selection import ThesisType
        from macro_engine.thesis_layer.builder import build_us_macro_thesis

        snapshot, _provenance = get_snapshot("us")
        inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=ThesisType.POLICY_PATH_GAP)
        build_us_macro_thesis(
            inputs.reads,
            inputs.taylor_inputs,
            inputs.first_difference_inputs,
            thesis_type=inputs.thesis_type,
            universe=inputs.universe,
            short_yield=inputs.short_yield,
            regime=inputs.regime,
        )
    except Exception as exc:  # pragma: no cover - data environment dependent
        return ran, f"thesis build failed: {exc!r}"

    return ran, None


def _wrap(module: object, name: str, original: object, ran: set[str]) -> object:
    """Replace ``module.name`` with a recorder, returning the original.

    ``functools.wraps`` is deliberately not used: the recorder must not copy
    ``__wrapped__`` or the original ``__name__``, because a caller that later
    reflects on the function would then see the original and this pass would be
    reporting on a function it is no longer calling.
    """

    def recorder(*args: object, **kwargs: object) -> object:
        ran.add(name)
        return original(*args, **kwargs)  # type: ignore[operator]

    setattr(module, name, recorder)
    return original


def model_functions() -> list[tuple[str, str, Path]]:
    """``(module_stem, func_name, path)`` for every public model function."""
    out: list[tuple[str, str, Path]] = []
    for path in sorted(MODELS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = _parsed(path)
        if tree is None:  # pragma: no cover - unparseable model module
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                out.append((path.stem, node.name, path))
    return out


def spec_tiers() -> dict[str, int]:
    """Map function name -> Tier number, parsed from the spec's Tier blocks."""
    if not SPEC.exists():  # pragma: no cover - spec is always present
        return {}
    text = SPEC.read_text(encoding="utf-8")
    tiers: dict[str, int] = {}
    for match in re.finditer(r"\*\*Tier (\d)[^\n]*\*\*(.*?)(?=\n\*\*Tier |\n---)", text, re.S):
        tier = int(match.group(1))
        for name in re.findall(r"`([a-z_0-9]+)`", match.group(2)):
            tiers[name] = tier
    return tiers


def _candidate_files() -> list[tuple[Path, str]]:
    """Every repo Python file worth scanning, as ``(path, repo-relative-name)``.

    Computed **once** and cached. The first version re-ran ``ROOT.rglob("*.py")``
    inside the per-function reference scan, so a 77-function audit walked the
    tree 77 times — 7,549 files each time, almost all of them inside ``.venv``.
    It appeared to hang; it was just O(functions x files) for no reason.
    """
    global _CANDIDATES
    if _CANDIDATES is not None:
        return _CANDIDATES

    out: list[tuple[Path, str]] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith((".venv/", "build/", "dist/", "node_modules/")):
            continue
        out.append((path, rel))
    out.sort(key=lambda pair: pair[1])
    _CANDIDATES = out
    return out


_CANDIDATES: list[tuple[Path, str]] | None = None


def _parsed(path: Path) -> ast.Module | None:
    """Parse ``path`` once and cache the tree; ``None`` if it will not parse.

    **This is the fix for the real bottleneck.** Caching the candidate *list*
    (above) solved walking the tree 79 times, but every ``_references`` call
    still re-*parsed* all 205 files — measured 2.8s per function, so ~220s for
    a single audit. That was tolerable when ``_references`` ran once per
    function; adding the same-module resolution (which calls it again per
    caller) would have doubled it into a tool nobody runs. Parsing is pure and
    the tree is immutable, so it caches perfectly.

    A file that fails to parse is cached as ``None`` rather than retried, so a
    syntax error costs one attempt instead of one per function.
    """
    global _PARSE_CACHE
    if path not in _PARSE_CACHE:
        try:
            _PARSE_CACHE[path] = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            _PARSE_CACHE[path] = None
    return _PARSE_CACHE[path]


_PARSE_CACHE: dict[Path, ast.Module | None] = {}


def _local_calls(name: str, module: Path) -> list[str]:
    """``ast.Call`` sites for ``name`` *inside its own defining module*.

    Returns the enclosing top-level function name for each hit, so the caller
    can ask "is whoever calls this itself wired?" — one hop, which is all that
    is needed to stop misreporting a private-ish helper as an orphan. Counts
    only real call expressions, for the same reason `_references` does: prose
    and imports are how the tool lied to itself in its first version.
    """
    tree = _parsed(module)
    if tree is None:  # pragma: no cover - unparseable module
        return []

    out: list[str] = []
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(parent):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            matched = (isinstance(callee, ast.Name) and callee.id == name) or (
                isinstance(callee, ast.Attribute) and callee.attr == name
            )
            if matched:
                out.append(parent.name)
                break
    return out


def _references(name: str, defining_module: Path) -> dict[str, list[str]]:
    """Where ``name`` is actually *called*, split by pipeline vs script vs test.

    **Only call expressions count.** A first version of this tool matched the
    bare name against each line and therefore counted docstring prose and
    ``TYPE_CHECKING`` imports as consumers — it reported ``compute_confidence``
    as wired on the strength of a comment in ``config.py``, and
    ``four_pillar_scorecard`` on the strength of a sentence. That is the same
    class of error as the defect this tool hunts (a claim that looks like
    evidence but is not), so the match is now an AST walk for ``ast.Call`` whose
    callee resolves to the name, which cannot be satisfied by prose.
    """
    hits: dict[str, list[str]] = {
        "pipeline": [],
        "script": [],
        "test": [],
        "intra": [],
        "local": [],
    }

    for path, rel in _candidate_files():
        if path == defining_module:
            # Docstring prose in the defining module is not a caller — but a
            # same-module ``ast.Call`` IS, and skipping the file wholesale made
            # the tool wrong about helpers. Measured 2026-09-19: the newly added
            # ``regime_tension`` is called at ``regime.py:598`` from inside
            # ``classify_regime_rule_based``, which IS wired — yet the tool
            # reported it as a true orphan, because line 140 dropped the file
            # before the AST walk. A same-module call is real evidence; it is
            # simply weaker than a pipeline call, so it goes in its own bucket
            # and is resolved against the caller's own reachability below.
            hits["local"] = _local_calls(name, path)
            continue

        tree = _parsed(path)
        if tree is None:  # pragma: no cover - unparseable file
            continue

        linenos: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            matched = (isinstance(callee, ast.Name) and callee.id == name) or (
                isinstance(callee, ast.Attribute) and callee.attr == name
            )
            if matched:
                linenos.append(node.lineno)

        if not linenos:
            continue

        if rel.startswith("tests/") or "/tests/" in rel:
            key = "test"
        elif rel.startswith(SCRIPT_ROOTS):
            key = "script"
        elif path.is_relative_to(MODELS):
            # A model calling another model is intra-layer composition, not
            # pipeline reachability. Counting it would call `price_bond` "wired"
            # whenever some other model uses it — but the thesis still would not.
            key = "intra"
        elif path.is_relative_to(PIPELINE_ROOT):
            key = "pipeline"
        else:
            continue
        for lineno in linenos:
            hits[key].append(f"{rel}:{lineno}")

    return hits


def _local_caller_is_reachable(
    local_callers: list[str],
    funcs: list[tuple[str, str, Path]],
) -> bool:
    """Whether any same-module caller of a helper is itself pipeline-wired.

    One hop only, deliberately. Following the chain further would start
    counting a helper two removes from the thesis as "wired", which is the
    over-claiming failure this tool exists to prevent; one hop covers the real
    case (a wired public function delegating to a helper) without inventing
    reachability that does not exist.
    """
    if not local_callers:
        return False
    by_name = {name: path for _mod, name, path in funcs}
    for caller in local_callers:
        path = by_name.get(caller)
        if path is None:
            continue
        if _references(caller, path)["pipeline"]:
            return True
    return False


class AuditVerdict(TypedDict):
    """The audit's classification, typed so callers get real element types.

    A plain ``dict[str, object]`` would force every caller to cast, and a cast
    is exactly where a test stops checking what it looks like it checks.
    """

    wired: list[str]
    script_only: list[tuple[str, list[str]]]
    orphaned: list[str]
    unreachable: set[str]
    funcs: list[tuple[str, str, Path]]


def classify() -> AuditVerdict:
    """The audit's whole verdict, as data.

    **Extracted so the report and the test cannot disagree.** The test suite
    asserts properties of this classification, and a test that reimplemented
    the rules would be free to drift from the tool it is supposedly checking —
    which is the same failure mode as a test that mirrors a bug instead of
    catching it. There is exactly one implementation of "is this reachable?",
    and both callers use it.
    """
    tiers = spec_tiers()
    funcs = model_functions()

    wired: list[str] = []
    script_only: list[tuple[str, list[str]]] = []
    orphaned: list[str] = []

    for _mod, name, path in funcs:
        hits = _references(name, path)
        if hits["pipeline"]:
            wired.append(f"{name:44} <- {hits['pipeline'][0]}")
        elif hits["script"]:
            script_only.append((name, hits["script"]))
        elif _local_caller_is_reachable(hits["local"], funcs):
            # A same-module helper called by a function that is itself wired is
            # NOT an orphan — it runs on every thesis. Reported separately from
            # the directly-wired set so the stronger evidence stays legible.
            wired.append(f"{name:44} <- {path.name} (via {', '.join(sorted(hits['local']))})")
        else:
            orphaned.append(name)

    # Tier 5 is Phase 5+ by spec, so it is legitimately unwired and must not be
    # counted as a Phase 0-3 obligation.
    unreachable = {
        name
        for name in ([b[0] if isinstance(b, tuple) else b for b in script_only] + orphaned)
        if tiers.get(name) != 5
    }

    return AuditVerdict(
        wired=wired,
        script_only=script_only,
        orphaned=orphaned,
        unreachable=unreachable,
        funcs=funcs,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "run the baseline gate: exit non-zero if the unreachable set has "
            "REGRESSED or the baseline is stale (see config/reachability_baseline.txt)"
        ),
    )
    parser.add_argument(
        "--check-baseline",
        action="store_true",
        help="same as --strict, named explicitly for CI readability",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="regenerate config/reachability_baseline.txt from the current tree",
    )
    parser.add_argument(
        "--dynamic",
        action="store_true",
        help=(
            "also run the dynamic pass: build a real thesis with every model "
            "function wrapped, and report what executed. Needs the live "
            "snapshot, so it is opt-in."
        ),
    )
    args = parser.parse_args()

    verdict = classify()
    tiers = spec_tiers()
    funcs = verdict["funcs"]
    wired = verdict["wired"]
    script_only = verdict["script_only"]
    orphaned = verdict["orphaned"]

    print(f"model functions defined          : {len(funcs)}")
    print(f"called from the shipped pipeline : {len(wired)}")
    print(f"called only from scripts/tools   : {len(script_only)}")
    print(f"no caller anywhere               : {len(orphaned)}")
    print()

    # --- dynamic pass (opt-in; needs the persisted snapshot) ---------------
    if args.dynamic:
        ran, error = _recorded_calls()
        print("=== DYNAMIC PASS — model functions that actually EXECUTED ===")
        if error is not None:
            print(f"  UNAVAILABLE: {error}")
            print("  (an empty set here would misread as 'nothing is wired', so")
            print("   the failure is reported as itself rather than as a result.)")
        else:
            print(f"  executed: {len(ran)}")
            for name in sorted(ran):
                print(f"    {name}")
            static_only = {
                entry.split()[0] for entry in wired if not entry.split()[0].startswith("  ")
            } - {n.split(".")[-1] for n in ran}
            if static_only:
                print()
                print("  statically wired but did NOT execute on this snapshot:")
                print("  (correct when the branch needs data this run lacked —")
                print("   listed so the difference is visible, not assumed.)")
                for name in sorted(static_only):
                    print(f"    {name}")
        print()

    def tier_of(name: str) -> int | None:
        return tiers.get(name)

    def split_by_tier(names: list[str]) -> tuple[list[str], list[str]]:
        gap: list[str] = []
        deferred: list[str] = []
        for name in names:
            tier = tier_of(name)
            (deferred if tier == 5 else gap).append(name)
        return sorted(gap), sorted(deferred)

    print("=== WIRED INTO THE PIPELINE ===")
    for entry in sorted(wired):
        print(f"  {entry}")

    for label, bucket in (("SCRIPT-ONLY", script_only), ("NO CALLER", orphaned)):
        if not bucket:
            continue
        names = [b[0] if isinstance(b, tuple) else b for b in bucket]
        gap, deferred = split_by_tier(names)
        # The two buckets are NOT the same severity, and labelling both
        # "PHASE 0-3 GAP" told the reader they were (measured 2026-09-19: the
        # first draft printed 34 and 25 under one identical heading). A
        # script-only function has a live cross-check in ``scripts/`` proving it
        # runs against real data (Section 21.0) — it is missing a *pipeline*
        # caller and nothing else. An orphan has no caller of any kind. The
        # remediations differ too: the first is "add the leg", the second is
        # "decide whether this function has a place at all".
        if label == "SCRIPT-ONLY":
            headline = "Tier 1-4 — live-checked but no pipeline caller"
            note = (
                "Each has a live cross-check in scripts/ proving the wiring\n"
                "against real data; what is missing is the thesis calling it."
            )
        else:
            headline = "Tier 1-4 — no caller anywhere (true orphans)"
            note = (
                "Nothing calls these: no pipeline caller, no live check, no\n"
                "other model. For each, decide wire-or-defer."
            )
        print()
        print(f"=== {label} — {headline}: {len(gap)} ===")
        for name in gap:
            tier = tier_of(name)
            print(f"  [Tier {tier if tier else '?'}] {name}")
        print(f"  ({note})")
        print()
        print(f"=== {label} — Tier 5 (Phase 5+ by spec): {len(deferred)} ===")
        for name in deferred:
            print(f"  {name}")

    gap_total = 0
    script_gap = 0
    orphan_gap = 0
    for bucket in (script_only, orphaned):
        names = [b[0] if isinstance(b, tuple) else b for b in bucket]
        count = len(split_by_tier(names)[0])
        gap_total += count
        if bucket is script_only:
            script_gap = count
        else:
            orphan_gap = count

    print()
    print("=" * 74)
    print(f"Tier 1-4 functions with no pipeline caller: {gap_total}")
    print("=" * 74)
    print(f"  of which live-checked, missing a pipeline leg : {script_gap}")
    print(f"  of which true orphans (no caller anywhere)    : {orphan_gap}")
    if gap_total:
        print()
        print("These are specified for Phases 0-3 and implemented, but the thesis")
        print("never calls them. Either wire them or move them to a later phase")
        print("in AGENTS.md 21.3 — but do not leave them silently unreachable.")
        print()
        print("Caveat the count does not encode: AGENTS.md 1787 assigns the")
        print("Risk/Portfolio modules (historical_var, expected_shortfall,")
        print("parametric_var, realized_vol_simple, portfolio_volatility_*,")
        print("marginal_risk_contributions) the endpoint '(Phase 4+)', and 9.2/")
        print("9.3 defer compute_risk_parity_weights and translate_thesis_to_")
        print("position to Phase 4. Those are Tier 1-2 in 21.3 (so this tool")
        print("counts them) but Phase 4+ by endpoint. Treating them as Phase 0-3")
        print("wiring obligations would be wrong; see docs/DEFECTS_2026-09-19.md.")

    # --- the baseline gate (DEFECTS item 3) --------------------------------
    unreachable_now: set[str] = verdict["unreachable"]

    if args.write_baseline:
        write_baseline(unreachable_now)
        print()
        print(f"Wrote {len(unreachable_now)} entries to {BASELINE.relative_to(ROOT)}")
        return 0

    if args.check_baseline or args.strict:
        baseline = read_baseline()
        if baseline is None:
            print()
            print("=" * 74)
            print(f"BASELINE MISSING: {BASELINE.relative_to(ROOT)} does not exist.")
            print("=" * 74)
            print("Cannot tell a regression from the status quo without it. Create")
            print("it once with --write-baseline, review the result, commit it.")
            return 1

        regressions = sorted(unreachable_now - baseline)
        newly_wired = sorted(baseline - unreachable_now)

        print()
        print("=" * 74)
        print("BASELINE GATE")
        print("=" * 74)
        print(f"  baseline size            : {len(baseline)}")
        print(f"  measured now             : {len(unreachable_now)}")
        if not regressions and not newly_wired:
            print("  REGRESSIONS              : none")
            print("  newly wired (update baseline): none")
            print()
            print("  PASS — the unreachable set is exactly the baseline.")
        if regressions:
            print(f"  REGRESSIONS ({len(regressions)}) — reachable, now are not:")
            for name in regressions:
                print(f"    + {name}")
            print()
            print("  FAIL — a function that the pipeline could reach no longer can.")
            print("  Either restore the caller or, if the removal was deliberate,")
            print("  regenerate the baseline so the decision is recorded.")
        if newly_wired:
            print(f"  NEWLY WIRED ({len(newly_wired)}) — no longer unreachable:")
            for name in newly_wired:
                print(f"    - {name}")
            print()
            print("  Not a failure, but the baseline is now stale. Run")
            print("  --write-baseline and commit, so the next regression is")
            print("  measured against the current truth.")

        if regressions or newly_wired:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
