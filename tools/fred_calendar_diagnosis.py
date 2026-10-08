"""Why does OpenBB's FRED calendar time out? — a one-command diagnosis (O-105).

The question this answers
-------------------------
O-105 recorded that ``GET /api/v1/economy/calendar?provider=fred`` answers
**HTTP 400 ``{"detail":"FRED request failed (TimeoutError)."}``** on 3/3
attempts, and that no other provider works either. It also recorded a **root
cause**: *"FRED closes the connection for aiohttp's TLS/HTTP fingerprint, and
OpenBB's FRED provider is built on aiohttp."*

**That recorded root cause is wrong, and this tool is the receipt.** It was
measured in this project and never re-measured, so it had hardened into a fact.
It is not one: ``aiohttp`` reaches this endpoint in **~0.1 s**.

The measured cause
------------------
The discriminator is the **User-Agent string**, and it is fully deterministic
(four consecutive runs, no exceptions):

    ====================================  ==========================
    User-Agent sent                       result
    ====================================  ==========================
    ``curl/8.0``                           **200 in ~0.2 s**
    ``python-httpx/...`` (client default)  **200 in ~0.2 s**
    Chrome 131 (a real browser UA)         **TIMEOUT every time**
    Firefox 133 (a real browser UA)        **TIMEOUT every time**
    Safari 605 (a real browser UA)         **TIMEOUT every time**
    ``""`` (empty)                         **TIMEOUT every time**
    ====================================  ==========================

FRED's releases-calendar page accepts a **tool-like** User-Agent and hangs on
anything that *looks like a browser* or is **missing entirely**. The hang is a
true read timeout — the TCP connection is established and the response body
never begins — which is why it surfaces as ``TimeoutError`` and not as a 4xx.

Why OpenBB therefore fails on EVERY call, and cannot be patched from here
------------------------------------------------------------------------
``openbb_core/provider/utils/client.py::get_user_agent()`` returns
``random.choice`` of **seven real browser UA strings** and applies it
unconditionally, in three places (``client.py:126``, ``helpers.py:164`` and
``:546``). There is **no environment variable, user setting or provider
argument** that overrides it — checked. So every request OpenBB's FRED provider
makes to ``fred.stlouisfed.org`` is sent with a browser UA and is *guaranteed*
to hang, whatever the caller passes.

The proof is a patch, not an argument. Overriding that one function to return
``curl/8.0`` and re-running the **unmodified** provider:

    as-is            FAIL  FRED request failed (TimeoutError)   10.99 s
    UA -> curl/8.0   OK    rows=3     0.33 s   (release_id=10 + window)
    UA -> curl/8.0   OK    rows=106   3.13 s   (no filters, 2-day default)

Same provider class, same URL, same window, same key. **Only the UA changed.**

What this means for the project, and what it does NOT mean
----------------------------------------------------------
* It does **not** mean the project should stop using ``httpx`` + ``curl/8.0``
  in ``thesis_layer/catalysts.py``. That path was already correct and is
  **unaffected** — it does not go through OpenBB's client at all.
* It does **not** licence switching providers. The remedy identified here is
  upstream (OpenBB's UA choice); ``§16.4`` and the FRED URL are unchanged.
* It **does** close the "unknown transport failure" framing: this is a
  **deterministic, reproducible, one-line** misbehaviour in a dependency, not
  an intermittent network condition. An intermittent problem and a
  deterministic one have different remedies, and calling this intermittent is
  what let it sit.

Why this is a TOOL and not a test
---------------------------------
It makes **live network calls to a third-party host**, and their result can
change for reasons that are not regressions in this repository. A test that
fails when FRED changes its UA policy would be disabled within a week (O-88).
The tool is explicit, run on demand, and reports what it measured with the
timestamp it measured it.

Exit codes are the contract (O-88): ``0`` the diagnosis reproduced as recorded,
``1`` it did NOT reproduce (the world changed — re-measure before relying on
any of this), ``2`` the probe could not run (no network).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import httpx

#: The exact FRED releases-calendar shape ``catalysts.py`` uses, date-only.
CALENDAR_URL = "https://fred.stlouisfed.org/releases/calendar?po=1&ptic=0&vs={vs}&ve={ve}&rid={rid}"

#: The seven UAs ``openbb_core.provider.utils.client.get_user_agent`` picks from,
#: reproduced here so the probe does not import openbb (it must run even when the
#: library is broken). Verbatim, Chrome first.
_OPENBB_BROWSER_UAS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

#: The UA this project pins and which is measured to work.
_WORKING_UA = "curl/8.0"

_TIMEOUT = 12.0


@dataclass(frozen=True)
class Result:
    """One probe outcome."""

    label: str
    status: int | None
    seconds: float
    detail: str

    @property
    def served(self) -> bool:
        return self.status == 200

    @property
    def timed_out(self) -> bool:
        return self.status is None and "imeout" in self.detail


def _probe(label: str, ua: str | None) -> Result:
    """One GET with the given User-Agent (``None`` = send no UA header at all)."""
    headers: dict[str, str] = {}
    if ua is not None:
        headers["User-Agent"] = ua
    url = CALENDAR_URL.format(vs="2026-09-19", ve="2026-12-31", rid=10)
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
        return Result(
            label=label,
            status=response.status_code,
            seconds=round(time.perf_counter() - start, 2),
            detail=f"{len(response.content)} bytes",
        )
    except httpx.TimeoutException as exc:
        return Result(label, None, round(time.perf_counter() - start, 2), type(exc).__name__)
    except httpx.HTTPError as exc:
        return Result(label, None, round(time.perf_counter() - start, 2), type(exc).__name__)


def main() -> int:
    print("Why does OpenBB's FRED calendar time out? (O-105)")
    print("=" * 72)
    print(f"url              : {CALENDAR_URL.format(vs='2026-09-19', ve='2026-12-31', rid='10')}")
    print(f"per-request bound: {_TIMEOUT}s  (a hang is reported, not waited on forever)")
    print()

    print("A. the UA this project pins, and a plain library default")
    print("-" * 72)
    working: list[Result] = []
    for label, ua in (("curl/8.0 (pinned by catalysts.py)", _WORKING_UA), ("httpx default", None)):
        result = _probe(label, ua) if ua is not None else _probe(label, None)
        working.append(result)
        _print(result)

    print()
    print("B. EVERY UA openbb_core's get_user_agent() can return")
    print("-" * 72)
    broken: list[Result] = []
    for index, ua in enumerate(_OPENBB_BROWSER_UAS, start=1):
        result = _probe(f"openbb UA #{index}", ua)
        broken.append(result)
        _print(result)

    print()
    print("C. the empty UA (OpenBB sends this if get_user_agent ever returns '')")
    print("-" * 72)
    empty = _probe("empty User-Agent", "")
    _print(empty)

    print()
    print("=" * 72)
    all_working_ok = all(r.served for r in working)
    all_broken_hang = all(r.timed_out for r in [*broken, empty])
    if all_working_ok and all_broken_hang:
        print("DIAGNOSIS REPRODUCED.")
        print()
        print("  FRED serves the releases-calendar page to a TOOL-LIKE User-Agent")
        print("  and hangs on a BROWSER-LIKE or EMPTY one. openbb_core's")
        print("  get_user_agent() returns a random real-browser UA and applies it")
        print("  unconditionally, with no supported override -- so OpenBB's FRED")
        print("  provider times out on every call. This is NOT a fingerprint")
        print("  filter, NOT throttling, and NOT the aiohttp client.")
        print()
        print("  Remedy: upstream (OpenBB's UA choice). Unchanged here:")
        print("  catalysts.py already pins curl/8.0 and is unaffected.")
        return 0
    if all_working_ok:
        print("DIAGNOSIS DID NOT REPRODUCE — the browser UAs were SERVED.")
        print()
        print("  FRED's UA policy has changed, or this host is treated")
        print("  differently. The recorded explanation of O-105 must be")
        print("  re-measured before it is relied on again.")
        return 1
    print("PROBE INCONCLUSIVE — the known-good UA also failed.")
    print()
    print("  That points at the network or at FRED being down, not at the")
    print("  User-Agent hypothesis. Re-run before drawing a conclusion.")
    return 2


def _print(result: Result) -> None:
    if result.served:
        outcome = f"OK    {result.status}"
    elif result.timed_out:
        outcome = "HANG  --"
    else:
        outcome = f"FAIL  {result.status if result.status else '--'}"
    print(f"  {outcome:<9} {result.seconds:>6}s  {result.label:<34} {result.detail}")


if __name__ == "__main__":
    sys.exit(main())
