"""Does the configured OpenBB base URL actually SERVE? (O-111(a), D-087.15.)

The gap this closes
-------------------
O-111 recorded that **nothing checked whether the configured OpenBB URL was
alive**. `settings.yaml` was pinned to ``:6901`` for a day, that port is *bound*
and answers **502 Bad Gateway** on every data route, and the consequence was
silent and expensive: a snapshot build retried **42 series x 3 attempts** against
the 502 and exceeded **400 s** (on ``:6900`` the same build is **83 s**), and
**three coverage tests skipped** with *"local OpenBB service not reachable"* —
so a dead endpoint **deleted coverage without failing anything**.

The lesson was already written down as **5cq** (*a port that is BOUND is not a
port that SERVES*) but there was no command that applied it. This is that command.

Why this is a TOOL and not a test
---------------------------------
The three coverage tests skip when the service is down, and that is **correct**:
an external dependency being unavailable is not a regression in this repository,
and a test that fails for it gets disabled within a week (O-88). But a *skip* is
exactly what made the outage invisible — it cannot distinguish "I chose to run
offline" from "the thing I depend on has been dead for a day".

So the honest fix is not to make those tests fail. It is a **separate, explicit
probe** which answers one question, loudly, when asked:

    does the URL this project is configured to call actually serve?

It is meant to be run **before** a live run (as a Step-0 companion) and by CI's
scheduled live job — the two moments when "is the service up?" is the question
that matters and nobody is currently asking it.

What "serves" means here — and why it is three checks, not one
-------------------------------------------------------------
Reachability alone is not enough, and the distinction matters because `:6901`
was **reachable**:

1. **REACHABLE** — a TCP/HTTP connection completes at all. `:6901` passes this.
2. **ANSWERS** — ``GET /openapi.json`` returns **200** with a parseable document
   naming at least one path. `:6901` **fails here** on data routes; this is the
   check that catches it. A port that is bound but returns 502 is *not serving*.
3. **AGREES WITH CONFIG** — the probe is asking the URL the project is actually
   configured to use (``settings.openbb.base_url``), not a literal. This is
   O-113's lesson applied to the probe itself: a health check with its own
   hard-coded host would go on passing after the config moved.

Exit codes (the O-88 discipline: a row is a claim, so the code must be readable)
-------------------------------------------------------------------------------
======================  ==========================================================
``0``                   the configured service serves; prints what it found
``1``                   the configured service does **not** serve; prints the
                        distinction (unreachable vs reachable-but-not-answering)
``2``                   the probe itself could not run (misconfiguration)
======================  ==========================================================
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

# ``src`` is not installed when tools are run directly (the same bootstrap the
# other probes in this directory use).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from macro_engine.config import get_settings

#: Short on purpose. A health probe that hangs is a worse gate than one that
#: fails: the whole point is to turn a 40-minute mystery into an immediate
#: error, so it must not itself become the slow thing.
_CONNECT_TIMEOUT = 5.0

#: The document every FastAPI service publishes. Chosen over a data route
#: because it needs no query parameters, so the probe measures the service
#: rather than its use of any particular endpoint.
_OPENAPI_PATH = "/openapi.json"


class ProbeResult:
    """One probe's outcome, carrying the *reason* rather than just a bool.

    The class exists because ``reachable=True, serves=False`` is the entire
    finding of O-111 — a boolean cannot express it, and the original failure was
    precisely that nobody distinguished the two.
    """

    def __init__(
        self,
        *,
        url: str,
        reachable: bool,
        status_code: int | None,
        path_count: int,
        detail: str,
        elapsed_s: float,
    ) -> None:
        self.url = url
        self.reachable = reachable
        self.status_code = status_code
        self.path_count = path_count
        self.detail = detail
        self.elapsed_s = elapsed_s

    @property
    def serves(self) -> bool:
        """``True`` only when the service answered with a usable document."""
        return self.reachable and self.status_code == 200 and self.path_count > 0


def probe(base_url: str | None = None) -> ProbeResult:
    """Ask whether ``base_url`` (default: the configured one) actually serves.

    ``base_url`` is accepted so the probe can be pointed at a *different*
    instance deliberately — for example to confirm which of two bound ports is
    the live one, which is how D-087.10 settled this the first time.
    """
    if base_url is None:
        base_url = get_settings().openbb.base_url
    url = f"{base_url.rstrip('/')}{_OPENAPI_PATH}"

    started = time.perf_counter()
    try:
        resp = httpx.get(url, timeout=_CONNECT_TIMEOUT)
    except httpx.HTTPError as exc:
        # Transport-level failure: nothing answered, so the port is not even
        # reachable. This is the *less* dangerous state, because a refused
        # connection fails fast and loudly.
        return ProbeResult(
            url=url,
            reachable=False,
            status_code=None,
            path_count=0,
            detail=f"{type(exc).__name__}: {exc}",
            elapsed_s=time.perf_counter() - started,
        )

    elapsed = time.perf_counter() - started

    # REACHABLE but not 200 — O-111's exact case. ``:6901`` completed the
    # connection and returned 502 on data routes, which is why "can I connect"
    # was never a sufficient question.
    if resp.status_code != 200:
        return ProbeResult(
            url=url,
            reachable=True,
            status_code=resp.status_code,
            path_count=0,
            detail=(
                f"reachable but answered HTTP {resp.status_code} — a bound port "
                "that does not serve the API (this is the O-111 failure mode)"
            ),
            elapsed_s=elapsed,
        )

    try:
        payload: Any = resp.json()
    except ValueError as exc:
        return ProbeResult(
            url=url,
            reachable=True,
            status_code=200,
            path_count=0,
            detail=f"HTTP 200 but the body is not JSON: {exc}",
            elapsed_s=elapsed,
        )

    paths = payload.get("paths") if isinstance(payload, dict) else None
    if not isinstance(paths, dict) or not paths:
        # 200 with no usable paths is the reachable-but-empty case, which
        # ``_openapi_paths()`` deliberately distinguishes from "could not ask".
        # Collapsing them is what makes an empty service look healthy.
        return ProbeResult(
            url=url,
            reachable=True,
            status_code=200,
            path_count=0,
            detail=(
                "HTTP 200 but no 'paths' in the document — reachable-but-empty, "
                "which is not the same as serving"
            ),
            elapsed_s=elapsed,
        )

    return ProbeResult(
        url=url,
        reachable=True,
        status_code=200,
        path_count=len(paths),
        detail=f"serving {len(paths)} paths",
        elapsed_s=elapsed,
    )


def main() -> int:
    base = get_settings().openbb.base_url
    result = probe()

    print("OpenBB reachability probe (O-111(a))")
    print("=" * 62)
    print(f"configured base URL : {base}  (settings.openbb.base_url)")
    print(f"probed              : {result.url}")
    print(f"reachable           : {result.reachable}")
    print(f"http status         : {result.status_code}")
    print(f"paths               : {result.path_count}")
    print(f"elapsed             : {result.elapsed_s:.2f}s")
    print("-" * 62)

    if result.serves:
        print(f"REACHABILITY: OK — {result.detail}.")
        print()
        print("The configured OpenBB URL serves. Live tests and any snapshot")
        print("build will exercise the real service.")
        return 0

    print(f"REACHABILITY: FAILED — {result.detail}.")
    print()
    if result.reachable:
        print("This is the DANGEROUS case and the one O-111 recorded: the port is")
        print("BOUND, so every reachability-style check passes, but it does not")
        print("serve the API. Consequences while this is true:")
        print("  - coverage tests SKIP ('service not reachable'), silently")
        print("    deleting their assertions without failing anything (O-62)")
        print("  - a snapshot build retries every series against the failure and")
        print("    can exceed 400s where a healthy build is ~83s")
        print()
        print("Check `openbb.local_api_base_url` in config/settings.yaml, and if")
        print("two ports are bound, probe BOTH — do not infer health from binding.")
    else:
        print("Nothing answered. Start the OpenBB Platform API, or correct")
        print("`openbb.local_api_base_url` / the OPENBB_API_URL override if the")
        print("service runs elsewhere.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
