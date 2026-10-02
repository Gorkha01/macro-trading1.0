"""AST call-graph measurement (REVIEW_PROMPT sections 3, 8, 13).

Grep cannot answer "is this function wired?": it cannot tell a definition from a
call site, an import from a local name, or a decorator from a call. This module
resolves calls with the AST and classifies every function.

Classification:
  WIRED            reachable from a real entry point (an HTTP route handler).
  REACHABLE-ONLY   called by something, but nothing reachable from an entry
                   point calls it.
  ORPHAN           nothing in the tree calls it at all.
  WIRED-BUT-DEAD   a route handler in a module the app never registers, so no
                   HTTP path to it exists.

Two AST traps are handled explicitly, because both were hit before:

1. ``@router.get("/x")`` parses as a ``Call`` whose ``func`` is an ``Attribute``
   (``router.get``), not a bare ``Attribute``. A naive walker records a call to
   a function named ``get`` and may treat ``router`` as an imported module. An
   alias is only resolved when it names a module that actually exists here.
2. A call to a function defined in the SAME module resolves through the local
   symbol table, not through imports. Without that table every intra-module
   call is dropped.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
PACKAGE = "macro_engine"

ROUTE_DECORATOR_ATTRS = frozenset({"get", "post", "put", "patch", "delete", "api_route"})


def module_name_for(path: Path) -> str:
    """Dotted module name for a file under src/."""
    parts = list(path.relative_to(SRC_ROOT).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts)


class ModuleIndex:
    """Per-module local definitions and import map."""

    def __init__(self) -> None:
        """Start empty."""
        self.defs: dict[str, set[str]] = {}
        self.imports: dict[str, dict[str, str]] = {}
        self.all_modules: set[str] = set()

    def add(self, mod: str, tree: ast.Module) -> None:
        """Record one module's local definitions and absolute imports."""
        self.all_modules.add(mod)
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.ClassDef):
                names.add(node.name)
        self.defs[mod] = names

        imports: dict[str, str] = {}
        # A separate loop variable: `ast.walk` yields `AST`, while the loop
        # above binds `node` to `stmt`, and reusing the name makes mypy reject
        # the assignment rather than widen it.
        for walked in ast.walk(tree):
            if isinstance(walked, ast.ImportFrom) and walked.module and walked.level == 0:
                for alias in walked.names:
                    imports[alias.asname or alias.name] = f"{walked.module}.{alias.name}"
            elif isinstance(walked, ast.Import):
                for alias in walked.names:
                    imports[alias.asname or alias.name.split(".")[0]] = alias.name
        self.imports[mod] = imports


def classify_modules(index: ModuleIndex) -> None:
    """No-op hook kept so the index is the single source of module identity."""
    return None


def _resolve_module(target: str, index: ModuleIndex) -> str | None:
    """Map an imported dotted name onto a real module, or None."""
    if target in index.all_modules:
        return target
    if "." in target:
        head = target.rsplit(".", 1)[0]
        if head in index.all_modules:
            return head
    return None


def _qualify(mod: str, node: ast.AST, index: ModuleIndex) -> str | None:
    """Resolve a callee expression to a dotted name, or None if unresolvable."""
    if isinstance(node, ast.Name):
        name = node.id
        if name in index.defs.get(mod, set()):  # trap 2: local wins
            return f"{mod}.{name}"
        target = index.imports.get(mod, {}).get(name)
        if target is None:
            return None
        if target in index.all_modules:
            return target
        head = _resolve_module(target, index)
        return f"{head}.{name}" if head else None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        owner = node.value.id
        base = index.imports.get(mod, {}).get(owner)
        if base is not None:  # trap 1: only real module aliases
            resolved = _resolve_module(base, index)
            if resolved is not None:
                return f"{resolved}.{node.attr}"
            return None
        if owner in index.defs.get(mod, set()):
            return f"{mod}.{owner}.{node.attr}"
        return None
    return None


def _is_route(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if a function is decorated as an HTTP route handler."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in ROUTE_DECORATOR_ATTRS:
            return True
    return False


def build() -> dict[str, Any]:
    """Measure the call graph and classify every function."""
    index = ModuleIndex()
    trees: dict[str, ast.Module] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        mod = module_name_for(path)
        if not mod:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        trees[mod] = tree
        index.add(mod, tree)
    classify_modules(index)

    funcs: dict[str, dict[str, Any]] = {}
    edges: dict[str, list[str]] = {}
    unresolved = 0

    for mod, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qual = f"{mod}.{node.name}.{item.name}"
                        funcs[qual] = {
                            "module": mod,
                            "name": item.name,
                            "lineno": item.lineno,
                            "is_route": _is_route(item),
                            "is_public": not item.name.startswith("_"),
                            "classification": "",
                        }
                        edges[qual] = [
                            t
                            for t in (
                                _qualify(mod, c.func, index)
                                for c in ast.walk(item)
                                if isinstance(c, ast.Call)
                            )
                            if t is not None
                        ]
                        unresolved += sum(
                            1
                            for c in ast.walk(item)
                            if isinstance(c, ast.Call) and _qualify(mod, c.func, index) is None
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{mod}.{node.name}"
                funcs.setdefault(
                    qual,
                    {
                        "module": mod,
                        "name": node.name,
                        "lineno": node.lineno,
                        "is_route": _is_route(node),
                        "is_public": not node.name.startswith("_"),
                        "classification": "",
                    },
                )
                edges[qual] = [
                    t
                    for t in (
                        _qualify(mod, c.func, index)
                        for c in ast.walk(node)
                        if isinstance(c, ast.Call)
                    )
                    if t is not None
                ]
                unresolved += sum(
                    1
                    for c in ast.walk(node)
                    if isinstance(c, ast.Call) and _qualify(mod, c.func, index) is None
                )

    roots = sorted(q for q, f in funcs.items() if f["is_route"])

    app_modules: set[str] = set()
    app_path = SRC_ROOT / PACKAGE / "api_layer" / "app.py"
    app_text = app_path.read_text(encoding="utf-8") if app_path.exists() else ""
    for mod in trees:
        if "api_layer" in mod and mod.rsplit(".", 1)[-1] in app_text:
            app_modules.add(mod)

    reachable: set[str] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt in edges.get(cur, []):
            if nxt not in reachable:
                stack.append(nxt)

    called = {t for ts in edges.values() for t in ts}
    counts: dict[str, int] = {k: 0 for k in ("WIRED", "REACHABLE-ONLY", "ORPHAN", "WIRED-BUT-DEAD")}
    for qual, info in funcs.items():
        if qual in reachable:
            if info["is_route"] and app_modules and info["module"] not in app_modules:
                info["classification"] = "WIRED-BUT-DEAD"
            else:
                info["classification"] = "WIRED"
        elif qual in called:
            info["classification"] = "REACHABLE-ONLY"
        else:
            info["classification"] = "ORPHAN"
        counts[info["classification"]] += 1

    public = [q for q, f in funcs.items() if f["is_public"]]
    public_counts: dict[str, int] = {k: 0 for k in counts}
    for q in public:
        public_counts[funcs[q]["classification"]] += 1

    return {
        "generated_by": "tools/callgraph.py",
        "n_modules": len(trees),
        "n_functions": len(funcs),
        "n_public_functions": len(public),
        "n_edges": sum(len(v) for v in edges.values()),
        "n_unresolved_dropped": unresolved,
        "roots": roots,
        "app_registered_api_modules": sorted(app_modules),
        "counts_all": counts,
        "counts_public": public_counts,
        "n_reachable": len(reachable),
        "nodes": funcs,
        "edges": {k: sorted(set(v)) for k, v in edges.items()},
    }


def main() -> int:
    """Write .review-evidence/callgraph.json."""
    graph = build()
    out = REPO_ROOT / ".review-evidence" / "callgraph.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    print(
        f"modules={graph['n_modules']} functions={graph['n_functions']} "
        f"public={graph['n_public_functions']} edges={graph['n_edges']} "
        f"unresolved={graph['n_unresolved_dropped']}"
    )
    print(f"counts_all={graph['counts_all']}")
    print(f"counts_public={graph['counts_public']}")
    print(f"roots={len(graph['roots'])} reachable={graph['n_reachable']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
