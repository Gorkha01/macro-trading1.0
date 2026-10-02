"""Executable gate definitions for the macro-engine review.

Every gate here is the *exact* command mandated by REVIEW_PROMPT.md section 0.
Nothing in this module loosens, narrows, or rewrites a gate: the command list
is transcribed, not designed. The module exists so that gate results are
MEASURED by running the command and recording its real exit code, instead of
being asserted from memory or carried forward from an earlier session.

Exit codes are captured from the child process itself. A shell pipeline would
report the exit code of the last element of the pipe, which is how a red gate
gets misrecorded as green -- see REVIEW_PROMPT section 1B, "silent fallback".
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Transcribed from REVIEW_PROMPT.md section 0.2 -- the four precondition gates
# plus the two suite gates used by section 8's auto-loop. Order is meaningful:
# a gate is only meaningful if every gate before it is green.
GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ruff_check", ("uv", "run", "ruff", "check", "src/")),
    ("ruff_format", ("uv", "run", "ruff", "format", "--check", "src/")),
    ("mypy_bare", ("uv", "run", "mypy")),
    ("import_smoke", (sys.executable, "tools/import_smoke.py")),
    ("pytest_default", ("uv", "run", "pytest", "-m", "not live and not slow", "-q")),
    ("pytest_live", ("uv", "run", "pytest", "-m", "live", "-q")),
)

TAIL_LINES = 40


def _truncate(text: str, lines: int = TAIL_LINES) -> str:
    """Keep the tail of the output, which is where verdicts and summaries live."""
    parts = text.splitlines()
    if len(parts) <= lines:
        return text
    return "\n".join(parts[-lines:])


def run_gate(name: str, argv: tuple[str, ...]) -> dict[str, Any]:
    """Run one gate, returning its real exit code and captured output."""
    started = datetime.now(UTC)
    proc = subprocess.run(  # noqa: S603 - argv is a fixed literal from GATES
        list(argv),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    finished = datetime.now(UTC)
    return {
        "name": name,
        "command": " ".join(argv),
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout_tail": _truncate(proc.stdout),
        "stderr_tail": _truncate(proc.stderr),
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
    }


def run_all(names: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Run every gate (or a subset), in order, and return the aggregate record."""
    results: list[dict[str, Any]] = []
    for name, argv in GATES:
        if names is not None and name not in names:
            continue
        result = run_gate(name, argv)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {name}: exit={result['exit_code']} ({result['duration_seconds']}s)")
    passed = sum(1 for r in results if r["passed"])
    return {
        "generated_utc": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "gate_count": len(results),
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "all_passed": passed == len(results),
        "gates": results,
    }


def sha256_of(path: Path) -> str:
    """SHA-256 of a file, used to prove which bytes a measurement was taken on."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    """CLI: ``uv run python tools/gates.py [--only a,b] [--json PATH]``."""
    names: tuple[str, ...] | None = None
    out_path: Path | None = None
    i = 1
    while i < len(argv):
        if argv[i] == "--only" and i + 1 < len(argv):
            names = tuple(part.strip() for part in argv[i + 1].split(","))
            i += 2
        elif argv[i] == "--json" and i + 1 < len(argv):
            out_path = Path(argv[i + 1])
            i += 2
        else:
            print(f"unknown argument: {argv[i]}", file=sys.stderr)
            return 2
    record = run_all(names)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out_path}")
    return 0 if record["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
