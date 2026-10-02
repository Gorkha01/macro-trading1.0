"""Import-smoke gate: prove every module under src/ imports cleanly.

REVIEW_PROMPT section 0.2 lists an import smoke as a precondition gate but does
not give the command, so this module defines it. The definition is deliberately
the strictest one available: import every module, individually, in a fresh
subprocess-free sequence, and fail on the FIRST failure rather than counting
successes. A module that raises on import cannot be reviewed line by line, so
anything short of "every module imports" is not a gate at all.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"


def candidate_modules() -> list[str]:
    """Every importable module under src/, sorted for deterministic output."""
    names: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT)
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1][: -len(".py")]
        if not parts:
            continue
        names.append(".".join(parts))
    return sorted(set(names))


def main() -> int:
    """Import every module; return 0 only if all of them imported."""
    modules = candidate_modules()
    failed: list[tuple[str, str]] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - the point is to report ANY failure
            failed.append((name, traceback.format_exc(limit=6)))
    print(f"modules: {len(modules)}, failed: {len(failed)}")
    for name, tb in failed:
        print(f"\n--- FAILED: {name}\n{tb}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.path.insert(0, str(SRC_ROOT))
    raise SystemExit(main())
