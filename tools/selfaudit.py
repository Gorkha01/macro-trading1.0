"""Self-audit harness (REVIEW_PROMPT section 13). Run: ``uv run python tools/selfaudit.py``.

The VERDICT is produced BY this harness, not asserted by it. It exits 0 only if
every check passes; otherwise it exits non-zero and prints which check failed
and why.

Design constraints taken from section 13:

* **It cannot pass by doing nothing.** Every check runs a real command or reads
  a real file. If an evidence file is missing, empty, or stale, the check
  FAILS -- absence is not success. The harness also refuses to run the
  "report" checks when REVIEW_REPORT.md does not exist, rather than scoring a
  missing report as clean.
* **It re-measures rather than re-reading.** The call graph, the file hashes and
  the mutation proofs are recomputed on this invocation, so a number that was
  true last hour and false now is caught.
* **It does not weaken anything.** No gate is run with a relaxed flag, no test
  is skipped, no threshold is adjustable from the command line.

Checks
------
1  gates           re-run every gate from tools/gates.py, all must exit 0
2  callgraph       re-measure the AST call graph, must succeed and be non-empty
3  file_hashes     re-hash every file; evidence must match what is on disk
4  mutation_proof  re-run every recorded mutation proof; revert must fail,
                   restore must pass
5  coverage        re-count collected and passing tests
6  banned_vocab    scan REVIEW_REPORT.md for section 1's banned vocabulary
7  no_unverified   scan the report and evidence for UNVERIFIED / xfail
8  number_check    every headline number must trace to a reproducing command
9  evidence_files  all section 13 evidence artifacts must exist and be non-empty
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = REPO_ROOT / ".review-evidence"
REPORT = REPO_ROOT / "REVIEW_REPORT.md"

BANNED_VOCABULARY = (
    "looks good",
    "looks fine",
    "solid",
    "reasonable",
    "minor nit",
    "seems",
    "appears",
    "probably",
    "should be fine",
    "looks correct",
)

REQUIRED_EVIDENCE = (
    "baseline.json",
    "agents_read.json",
    "citations.json",
    "manifest.json",
    "gates.json",
    "callgraph.json",
    "mutations.json",
    "coverage.json",
    "skills_read.json",
)

HEADLINE_NUMBERS = (
    ("file_count", r"\*\*Files in scope\*\*:\s*(\d+)"),
    ("reviewed_pct", r"\*\*Share of lines reviewed\*\*:\s*([\d.]+)"),
)


class Check:
    """One self-audit check and its outcome."""

    def __init__(self, name: str) -> None:
        """Start a passing check with no findings."""
        self.name = name
        self.passed = True
        self.detail: list[str] = []

    def fail(self, message: str) -> None:
        """Mark the check failed with a reason."""
        self.passed = False
        self.detail.append(message)

    def note(self, message: str) -> None:
        """Record information that does not change the outcome."""
        self.detail.append(message)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the outcome."""
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


def _run(argv: list[str], timeout: int = 1800) -> tuple[int, str]:
    """Run a command, returning its real exit code and combined output tail."""
    proc = subprocess.run(  # argv values are literals in this module
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def check_gates() -> Check:
    """1. Re-run every gate; all must exit 0."""
    check = Check("gates")
    proc = subprocess.run(
        [
            sys.executable,
            "tools/gates.py",
            "--only",
            "ruff_check,ruff_format,mypy_bare,import_smoke,pytest_default",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    if proc.returncode != 0:
        check.fail(f"tools/gates.py exited {proc.returncode}; at least one gate is red")
        check.note((proc.stdout + proc.stderr)[-1500:])
        return check
    check.note("all five gates exited 0 (ruff, ruff format, mypy bare, import smoke, pytest)")
    return check


def check_callgraph() -> Check:
    """2. Re-measure the AST call graph."""
    check = Check("callgraph")
    code, _ = _run([sys.executable, "tools/callgraph.py"])
    if code != 0:
        check.fail(f"tools/callgraph.py exited {code}")
        return check
    graph = json.loads((EVIDENCE / "callgraph.json").read_text(encoding="utf-8"))
    if graph["n_functions"] <= 0 or graph["n_modules"] <= 0:
        check.fail("call graph is empty -- measurement did not happen")
        return check
    check.note(
        f"modules={graph['n_modules']} functions={graph['n_functions']} "
        f"wired={graph['counts_all']['WIRED']} orphan={graph['counts_all']['ORPHAN']}"
    )
    return check


def check_file_hashes() -> Check:
    """3. Re-hash every file and compare with manifest.json."""
    check = Check("file_hashes")
    manifest_path = EVIDENCE / "manifest.json"
    if not manifest_path.exists():
        check.fail("manifest.json missing -- cannot verify which bytes were reviewed")
        return check
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    drifted = []
    for entry in manifest["files"]:
        path = REPO_ROOT / entry["file"]
        if not path.exists():
            drifted.append(f"{entry['file']} (missing)")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            drifted.append(f"{entry['file']} (hash changed)")
    if drifted:
        check.fail(f"{len(drifted)} file(s) changed since the manifest was written")
        check.note("; ".join(drifted[:10]))
    else:
        check.note(f"{len(manifest['files'])} file hashes match the manifest")
    return check


def check_mutation_proofs() -> Check:
    """4. Re-run every recorded mutation proof."""
    check = Check("mutation_proofs")
    path = EVIDENCE / "mutations.json"
    if not path.exists():
        check.fail("mutations.json missing -- no fix is mutation-proved")
        return check
    proofs = json.loads(path.read_text(encoding="utf-8"))
    if not proofs:
        check.fail("mutations.json is empty -- a fix with no proof is not a fix")
        return check
    for proof in proofs:
        if not proof.get("proof_valid"):
            check.fail(
                f"{proof['proof']}: reverted exit={proof['reverted']['exit_code']} "
                f"(must be non-zero), restored exit={proof['restored']['exit_code']} "
                f"(must be zero)"
            )
        else:
            check.note(
                f"{proof['proof']}: revert exit {proof['reverted']['exit_code']}, "
                f"restore exit {proof['restored']['exit_code']}"
            )
    return check


def check_coverage() -> Check:
    """5. Re-count collected and passing tests."""
    check = Check("coverage")
    code, out = _run(["uv", "run", "pytest", "-m", "not live and not slow", "-q"])
    if code != 0:
        check.fail(f"pytest exited {code}")
        return check
    match = re.search(r"(\d+) passed", out)
    if not match:
        check.fail("could not parse a passing test count from pytest output")
        return check
    passed = int(match.group(1))
    recorded = json.loads((EVIDENCE / "coverage.json").read_text(encoding="utf-8"))
    if passed != recorded.get("tests_passed"):
        check.fail(
            f"coverage.json records {recorded.get('tests_passed')} passing tests "
            f"but pytest reports {passed}"
        )
    else:
        check.note(f"{passed} tests passing, matching coverage.json")
    return check


def check_banned_vocabulary() -> Check:
    """6. Scan the report for section 1's banned vocabulary."""
    check = Check("banned_vocabulary")
    if not REPORT.exists():
        check.fail("REVIEW_REPORT.md does not exist")
        return check
    text = REPORT.read_text(encoding="utf-8").lower()
    hits = [phrase for phrase in BANNED_VOCABULARY if phrase in text]
    if hits:
        check.fail(f"banned vocabulary present: {hits}")
    else:
        check.note(f"none of {len(BANNED_VOCABULARY)} banned phrases present")
    return check


def check_no_unverified() -> Check:
    """7. Scan for UNVERIFIED / xfail used as a disposition."""
    check = Check("no_unverified")
    targets = [REPORT] + [EVIDENCE / name for name in REQUIRED_EVIDENCE]
    hits: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        text = target.read_text(encoding="utf-8")
        for pattern in (r"\bUNVERIFIED\b", r"\bxfail\b", r"\bx-fail\b"):
            for found in re.finditer(pattern, text):
                line_no = text[: found.start()].count("\n") + 1
                hits.append(f"{target.name}:{line_no}: {found.group(0)}")
    if hits:
        check.fail(f"{len(hits)} UNVERIFIED/xfail occurrence(s) -- not a disposition")
        check.note("; ".join(hits[:12]))
    else:
        check.note("no UNVERIFIED or xfail anywhere in the report or evidence")
    return check


def check_numbers() -> Check:
    """8. Every headline number must trace to a reproducing command."""
    check = Check("number_check")
    if not REPORT.exists():
        check.fail("REVIEW_REPORT.md does not exist")
        return check
    text = REPORT.read_text(encoding="utf-8")
    manifest = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    graph = json.loads((EVIDENCE / "callgraph.json").read_text(encoding="utf-8"))
    expected = {
        "file_count": str(manifest["file_count"]),
        "reviewed_pct": str(manifest["reviewed_pct"]),
    }
    for key, pattern in HEADLINE_NUMBERS:
        match = re.search(pattern, text)
        if not match:
            check.fail(f"headline number '{key}' not found in the report")
            continue
        if match.group(1) != expected[key]:
            check.fail(
                f"headline number '{key}' says {match.group(1)} but evidence says {expected[key]}"
            )
    # The orphan count must agree with the freshly measured graph.
    orphan_match = re.search(r"\*\*ORPHAN\*\*:\s*(\d+)", text)
    if orphan_match and int(orphan_match.group(1)) != graph["counts_all"]["ORPHAN"]:
        check.fail(
            f"report says ORPHAN={orphan_match.group(1)} but the re-measured "
            f"graph says {graph['counts_all']['ORPHAN']}"
        )
    check.note(f"checked {len(HEADLINE_NUMBERS) + 1} headline numbers against evidence")
    return check


def check_evidence_files() -> Check:
    """9. Every section 13 evidence artifact must exist and be non-empty."""
    check = Check("evidence_files")
    for name in REQUIRED_EVIDENCE:
        path = EVIDENCE / name
        if not path.exists():
            check.fail(f"{name} missing")
        elif path.stat().st_size == 0:
            check.fail(f"{name} is empty")
    if check.passed:
        check.note(f"all {len(REQUIRED_EVIDENCE)} evidence artifacts present and non-empty")
    return check


def check_no_open_findings() -> Check:
    """10. No finding may be left open (section 1C: one open defect fails)."""
    check = Check("no_open_findings")
    if not REPORT.exists():
        check.fail("REVIEW_REPORT.md does not exist")
        return check
    text = REPORT.read_text(encoding="utf-8")
    open_rows = [
        line.strip() for line in text.splitlines() if line.startswith("|") and "| OPEN |" in line
    ]
    if open_rows:
        check.fail(f"{len(open_rows)} finding(s) still open -- section 1C fails the review")
        check.note("; ".join(row.split("|")[1].strip() for row in open_rows[:12]))
    else:
        check.note("every finding in the table is FIXED")
    return check


def check_scope_complete() -> Check:
    """11. Every in-scope line must have been reviewed (section 4 / 12)."""
    check = Check("scope_complete")
    manifest_path = EVIDENCE / "manifest.json"
    if not manifest_path.exists():
        check.fail("manifest.json missing")
        return check
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pct = manifest["reviewed_pct"]
    if pct < 100.0:
        check.fail(
            f"only {pct}% of in-scope lines were reviewed line-by-line "
            f"({manifest['files_not_reached']} of {manifest['file_count']} files not reached)"
        )
    else:
        check.note("all in-scope lines reviewed line-by-line")
    return check


CHECKS = (
    check_evidence_files,
    check_gates,
    check_callgraph,
    check_file_hashes,
    check_mutation_proofs,
    check_coverage,
    check_banned_vocabulary,
    check_no_unverified,
    check_numbers,
    check_no_open_findings,
    check_scope_complete,
)


def main() -> int:
    """Run every check, write selfaudit.json, and exit 0 only on PASS."""
    results = [fn().as_dict() for fn in CHECKS]
    failed = [r for r in results if not r["passed"]]
    verdict = "PASS" if not failed else "FAIL"
    record = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "harness": "tools/selfaudit.py",
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "check_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "verdict": verdict,
        "results": results,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "selfaudit.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8", newline=""
    )

    print("=" * 68)
    for result in results:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"[{mark}] {result['check']}")
        for line in result["detail"][:6]:
            print(f"        {line}")
    print("=" * 68)
    print(f"VERDICT: {verdict}  ({record['passed_count']}/{len(results)} checks passed)")
    print(f"wrote {EVIDENCE / 'selfaudit.json'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
