"""Report the GitHub Actions verdict for a local commit, without `gh`.

`gh` is not installed in this environment. The credential is recovered from the
git credential helper — the same one a push authenticates with — and the run is
looked up by the **full 40-character sha**: a 7-character prefix returns
``total_count: 0``, which reads exactly like "CI has not started yet" and has
already cost time misreading it.

Usage:
    python tools/ci_status.py            # HEAD
    python tools/ci_status.py <sha>      # any full or resolvable sha
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import httpx

REPO = "Gorkha01/macro-trading"
API = "https://api.github.com"
_TIMEOUT_SECONDS = 60.0


def _token() -> str:
    """Recover the GitHub token the same way a push does.

    Refuses rather than falling back to an anonymous request: an unauthenticated
    call to this API succeeds on a public repo but returns rate-limited or
    partial data, which would read as a verdict.
    """
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stdout.splitlines():
        if line.lower().startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("no github credential available from `git credential fill`")


def _get(token: str, path: str) -> dict[str, Any]:
    """GET a GitHub API path and return the decoded object."""
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{API}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "macro-ci-status",
            },
        )
        response.raise_for_status()
        payload: Any = response.json()
    # A non-object payload is a real failure, not an empty result: reporting it
    # as "no runs" would be indistinguishable from "not pushed yet".
    if not isinstance(payload, dict):
        raise SystemExit(f"github returned a non-object payload for {path}")
    return payload


def _resolve(sha_arg: str | None) -> str:
    """Resolve any user-supplied sha to its FULL 40-character form."""
    argument = sha_arg if sha_arg is not None else "HEAD"
    proc = subprocess.run(
        ["git", "rev-parse", argument], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"cannot resolve {argument!r} to a commit")
    return proc.stdout.strip()


def _verdict(status: str | None, fallback: str) -> str:
    return status if status else fallback


def main(argv: list[str]) -> int:
    full = _resolve(argv[1] if len(argv) > 1 else None)
    token = _token()
    print(f"sha {full}")
    runs = _get(token, f"/repos/{REPO}/actions/runs?head_sha={full}").get("workflow_runs", [])
    if not runs:
        print("no workflow run found for this sha (is it pushed?)")
        return 1
    for run in runs:
        run_id = run["id"]
        print(
            f"run {run_id}  {run['name']}  "
            f"{_verdict(run.get('conclusion'), str(run['status']))}  "
            f"({run['html_url']})"
        )
        jobs = _get(token, f"/repos/{REPO}/actions/runs/{run_id}/jobs").get("jobs", [])
        for job in jobs:
            print(f"  [{_verdict(job.get('conclusion'), str(job['status']))}] {job['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
