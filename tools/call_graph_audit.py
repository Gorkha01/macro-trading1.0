"""Function-level call-graph audit over the PRODUCTION tree only.

Answers one question, with evidence: **for every function defined under
``src/macro_engine``, which other production function calls it, and from where?**

This is deliberately NOT the same question as ``reachability_audit.py``:

* ``reachability_audit.py`` asks whether a *model* function is reachable from the
  shipped pipeline, and it reasons about a curated list of model entry points.
* this tool asks the blunter, structural question over the WHOLE production tree:
  is this function called by any other production code at all? It is the tool for
  "we defined it — does anything run it?"

Scope, and why it matters:

* **IN scope:** every module under ``src/macro_engine``. These ship.
* **OUT of scope:** ``tests/`` and ``scripts/``. A function called only from a
  test or a live-check script is NOT wired into the product; counting those calls
  is exactly how a dead code path gets reported as integrated. The tool reports
  them separately as ``script/test-only`` so the distinction stays visible.

Resolution is import-aware rather than a bare name match, because a name match
silently merges two different functions that happen to share a name — the
"a name is not an identity" class this project keeps re-learning (O-150/O-155):

* ``from x.y import f`` then ``f()``      -> ``x.y.f``
* ``import x.y as z`` then ``z.f()``      -> ``x.y.f``
* ``from x.y import mod`` then ``mod.f()``-> ``x.y.mod.f`` (falls back to name)
* ``self.m()`` inside class ``C``         -> ``C.m``
* bare ``f()``                            -> same module first, then a UNIQUE
  production definition; an ambiguous bare name is reported, never guessed.

Usage::

    uv run python tools/call_graph_audit.py                 # full report
    uv run python tools/call_graph_audit.py --summary       # counts only
    uv run python tools/call_graph_audit.py --check-baseline# CI gate

The ``--check-baseline`` mode compares the uncalled set against
``tools/call_graph_baseline.txt`` so the number cannot drift silently.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
PKG_ROOT = SRC_ROOT / "macro_engine"
BASELINE = REPO_ROOT / "tools" / "call_graph_baseline.txt"

#: Directories that are NOT production code. A call from one of these does not
#: count as wiring, and the tool says so explicitly rather than folding them in.
NON_PRODUCTION = ("tests", "scripts", "tools", ".probe")


def module_name(path: pathlib.Path) -> str:
    """A stable identifier for a parsed file.

    Production files are named the way PYTHON names them — ``src.`` stripped —
    because the import targets written in the source are ``macro_engine.*``, and
    a key that kept the ``src.`` prefix would never match a resolved import. That
    mismatch is silent: every edge simply fails to resolve and the tool reports a
    call graph of ZERO edges, which reads exactly like "nothing is wired".

    Files outside ``src/`` (``tests/``, ``scripts/``) keep their repo-relative
    name, which is what distinguishes them in the report.
    """
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


@dataclass
class Definition:
    module: str
    qualname: str  # e.g. "f" for a function, "C.m" for a method
    lineno: int
    kind: str  # "function" | "method" | "property"

    @property
    def key(self) -> str:
        return f"{self.module}.{self.qualname}"

    @property
    def is_public(self) -> bool:
        return not self.qualname.split(".")[-1].startswith("_")


@dataclass
class CallSite:
    module: str
    enclosing: str  # qualname of the function containing the call
    lineno: int
    callee: str
    resolved: str | None = None


@dataclass
class Report:
    definitions: dict[str, Definition] = field(default_factory=dict)
    callers: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    ambiguous: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    unresolved: int = 0
    #: Attribute names accessed anywhere in production code (``x.foo``). A
    #: ``@property`` is USED by attribute access, never by a call, so a
    #: call-only graph reports every accessor in the tree as dead code.
    attr_accesses: set[str] = field(default_factory=set)


def _collect(
    paths: list[pathlib.Path],
) -> tuple[dict[str, Definition], list[CallSite], dict[str, dict[str, str]], set[str]]:
    """Return (definitions, call sites, import alias map per module, attr accesses)."""
    definitions: dict[str, Definition] = {}
    calls: list[CallSite] = []
    aliases: dict[str, dict[str, str]] = {}
    attr_accesses: set[str] = set()

    for path in paths:
        mod = module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        # --- imports: alias -> fully-qualified target ------------------------
        amap: dict[str, str] = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("macro_engine")
            ):
                for a in node.names:
                    amap[a.asname or a.name] = f"{node.module}.{a.name}"
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("macro_engine"):
                        amap[a.asname or a.name.split(".")[-1]] = a.name
        aliases[mod] = amap

        # --- definitions -----------------------------------------------------
        def visit(node: ast.AST, prefix: str, kind: str, owner: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    q = f"{prefix}{child.name}"
                    decorators = [ast.unparse(d) for d in child.decorator_list]
                    child_kind = (
                        "property"
                        if any("property" in d for d in decorators)
                        else ("method" if kind == "method" else "function")
                    )
                    d = Definition(owner, q, child.lineno, child_kind)
                    definitions[d.key] = d
                    visit(child, f"{q}.", child_kind, owner)
                elif isinstance(child, ast.ClassDef):
                    visit(child, f"{child.name}.", "method", owner)

        visit(tree, "", "function", mod)

        # --- call sites + attribute accesses ---------------------------------
        def walk(node: ast.AST, enclosing: str, owner: str = mod) -> None:
            # NOTE: recurse into EVERY child, not only the statement types we
            # name. A call usually sits inside an expression (`x = f(...)`,
            # `return g(...)`, `if h(...)`), so a walker that only descends into
            # FunctionDef/ClassDef sees almost nothing and reports a call graph
            # of zero edges — which reads exactly like "nothing is wired".
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    walk(child, child.name)
                    continue
                if isinstance(child, ast.Attribute):
                    attr_accesses.add(child.attr)
                if isinstance(child, ast.Call):
                    callee = _callee_name(child.func)
                    if callee:
                        calls.append(CallSite(owner, enclosing, child.lineno, callee))
                walk(child, enclosing)

        walk(tree, "<module>")

    return definitions, calls, aliases, attr_accesses


def _callee_name(func: ast.expr) -> str | None:
    """The dotted name being called, e.g. ``f``, ``self.m``, ``mod.f``.

    The FULL dotted path matters: ``policy_rules.taylor_rule(...)`` must resolve
    through the ``policy_rules`` import alias. Returning only the last attribute
    (``taylor_rule``) throws away the qualifier and forces every attribute call
    onto the bare-name fallback, which under-reports the call graph.
    """
    parts: list[str] = []
    node: ast.expr = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    else:
        return None
    return ".".join(reversed(parts))


def _resolve(
    call: CallSite, definitions: dict[str, Definition], aliases: dict[str, dict[str, str]]
) -> tuple[str | None, list[str]]:
    """Resolve a call to a definition key. Returns (key_or_None, candidates)."""
    amap = aliases.get(call.module, {})
    name = call.callee
    head, _, rest = name.partition(".")

    # `alias.attr...` where `alias` is an imported module or object.
    if rest and head in amap:
        cand = f"{amap[head]}.{rest}"
        if cand in definitions:
            return cand, [cand]

    # `self.m()` / `cls.m()` inside a class -> <module>.<Class>.m
    if head in ("self", "cls"):
        if not rest:
            return None, []
        parts = call.enclosing.split(".")
        if len(parts) >= 2:
            cand = f"{call.module}.{'.'.join(parts[:-1])}.{rest}"
            if cand in definitions:
                return cand, [cand]

    # an imported name used bare
    if not rest and name in amap:
        target = amap[name]
        if target in definitions:
            return target, [target]
        # `from pkg import mod` then `mod.f()`
        if f"{target}.{name}" in definitions:
            return f"{target}.{name}", [f"{target}.{name}"]

    # bare name: same module first
    same = f"{call.module}.{name}"
    if same in definitions:
        return same, [same]

    # then a UNIQUE production definition of that bare name
    leaf = name.split(".")[-1]
    candidates = [
        k
        for k, d in definitions.items()
        if d.qualname.split(".")[-1] == leaf and d.kind == "function"
    ]
    if len(candidates) == 1:
        return candidates[0], candidates
    if len(candidates) > 1:
        return None, candidates
    return None, []


def build(paths: list[pathlib.Path] | None = None) -> Report:
    if paths is None:
        paths = sorted(PKG_ROOT.rglob("*.py"))
    definitions, calls, aliases, attr_accesses = _collect(paths)
    report = Report(definitions=definitions, attr_accesses=attr_accesses)
    for call in calls:
        key, candidates = _resolve(call, definitions, aliases)
        if key:
            report.callers[key].add(f"{call.module}:{call.lineno} in {call.enclosing}")
        elif len(candidates) > 1:
            report.ambiguous[call.callee].extend(candidates)
        else:
            report.unresolved += 1
    return report


def is_used(key: str, report: Report) -> bool:
    """True if this definition is reached by production code.

    A ``@property`` is reached by ATTRIBUTE ACCESS, never by a call, so the two
    are checked separately. Collapsing them would report every accessor in the
    tree as dead code — 296 of them in ``config.py`` alone, which is the
    difference between a usable audit and a useless one.
    """
    definition = report.definitions[key]
    if definition.kind == "property":
        return definition.qualname.split(".")[-1] in report.attr_accesses
    return bool(report.callers.get(key))


def _external_callers() -> dict[str, set[str]]:
    """Calls to production functions from tests/scripts (reported separately)."""
    paths = [p for d in NON_PRODUCTION for p in (REPO_ROOT / d).rglob("*.py")]
    prod_defs, _, _, _ = _collect(sorted(PKG_ROOT.rglob("*.py")))
    _, calls, aliases, _ = _collect([p for p in paths if p.exists()])
    out: dict[str, set[str]] = defaultdict(set)
    for call in calls:
        key, _ = _resolve(call, prod_defs, aliases)
        if key:
            out[key].add(f"{call.module}:{call.lineno}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summary", action="store_true", help="counts only")
    ap.add_argument(
        "--check-baseline", action="store_true", help="fail if the uncalled set changed"
    )
    ap.add_argument("--uncalled", action="store_true", help="list only the never-called functions")
    args = ap.parse_args()

    report = build()
    defs = report.definitions
    used = {k for k in defs if is_used(k, report)}
    unused = sorted(k for k in defs if not is_used(k, report))
    unused_public = [k for k in unused if defs[k].is_public]
    unused_private = [k for k in unused if not defs[k].is_public]
    n_props = sum(1 for d in defs.values() if d.kind == "property")

    ext = _external_callers()
    ext_only = [k for k in unused if ext.get(k)]

    print(f"production modules parsed          : {len({d.module for d in defs.values()})}")
    print(f"functions/methods defined          : {len(defs)}  (of which @property: {n_props})")
    print(f"USED by other production code      : {len(used)}")
    print(f"NOT used by production code        : {len(unused)}")
    print(f"    of which PUBLIC                : {len(unused_public)}")
    print(f"    of which private (_)           : {len(unused_private)}")
    print(f"    of which called from tests/scripts only : {len(ext_only)}")
    print(f"ambiguous bare-name calls skipped  : {len(report.ambiguous)}")
    print(f"unresolved calls (external/stdlib) : {report.unresolved}")

    if args.summary:
        return 0

    if args.uncalled:
        print("\n=== NOT used by any production code (PUBLIC) ===")
        for k in unused_public:
            d = defs[k]
            tag = "  [test/script-only]" if ext.get(k) else "  [NO CALLER ANYWHERE]"
            print(f"  {d.key}  ({d.kind} @ {d.module}:{d.lineno}){tag}")
        return 0

    print("\n=== PUBLIC definitions with NO production user ===")
    for k in unused_public:
        d = defs[k]
        tag = "test/script-only" if ext.get(k) else "NO CALLER ANYWHERE"
        print(f"  {d.key:70s} {tag}")

    if args.check_baseline:
        current = "\n".join(unused) + "\n"
        if not BASELINE.exists():
            # `newline="\n"` explicitly: the default translates to `os.linesep`,
            # which writes CRLF on Windows and makes the committed baseline
            # differ from the LF form git stores — a whole-file diff on every
            # platform that touches it.
            BASELINE.write_text(current, encoding="utf-8", newline="\n")
            print(f"\nwrote baseline -> {BASELINE.relative_to(REPO_ROOT)} ({len(unused)} entries)")
            return 0
        expected = BASELINE.read_text(encoding="utf-8").split()
        new = sorted(set(unused) - set(expected))
        gone = sorted(set(expected) - set(unused))
        if new or gone:
            print("\nCALL-GRAPH DRIFT")
            for k in new:
                print(f"  NEWLY UNUSED (regression): {k}")
            for k in gone:
                print(f"  newly used (update baseline): {k}")
            return 1
        print("\nPASS -- the unused set is exactly the baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
