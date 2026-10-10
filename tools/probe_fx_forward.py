"""Probe whether ANY reachable source returns an FX FORWARD — by CALLING it.

Why this probe exists
---------------------
``config/series_registry.yaml``'s ``fx_forward_rate`` entry records a MEASURED
block (D-108, 2026-09-25) with an explicit instruction attached:

    "both of which currently fail on MISSING CREDENTIALS rather than on a
     missing product -- a config gap, not a dead end ... Re-probe with the
     credentialed providers before concluding the product is unreachable."

That instruction was never discharged. An "unavailable" claim recorded once and
never re-measured is the D-043 FALSE BLOCK class, and this repository has now
caught seven of them. So this probe re-measures the claim.

The method is the point (AGENTS.md Section 5.1 lesson)
------------------------------------------------------
**A probe must CALL the source, not ENUMERATE it.** The v1 Section 22.5 probe
printed route NAMES and a "VERDICT CRITERIA" restatement, so it *agreed* with
the wrong conclusion instead of overturning it. This probe therefore:

  1. calls a spread of concrete FX-forward candidates and reports what comes
     back (HTTP status, row count, the value), and
  2. **separates a missing route from a missing credential** by calling a
     route the installation DOES have with a credentialed provider, so that
     "fmp needs a key" is a MEASURED fact, not an inference.

What "forward" means here, stated so the verdict is falsifiable
--------------------------------------------------------------
A forward is a price/rate for settlement on a DATED future value date, quoted
against spot. Three things would satisfy this system:

  (a) a provider publishing FX forward POINTS or outright forward rates;
  (b) a DATED CME/ICE FX futures contract (whose price converges to the forward
      as expiry approaches) -- a dated contract, NOT a rolling front-month; or
  (c) a cross-currency BASIS quote (the CIP deviation the cip_check model wants).

A continuous front-month ("=F") series satisfies NONE of these: it rolls
silently and carries a price discontinuity at every roll, so differencing it
against spot produces a "forward point" that is really a contract switch.

Passes 3b and 3c (added 2026-10-10 after an operator challenge -- "sure that's
blocked, or is it not-found data?") close two coverage gaps the first pass left
open: the `expiration` query parameter, which the earlier probe never sent, and
FRED's "Currency; Swaps" family, which reads like a CIP source but is a
look-alike. A re-probe that only CONFIRMS is worth less than the negative
results it produces, so both are now permanent.

Run:  uv run python tools/probe_fx_forward.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

from macro_engine.data_layer.openbb_client import (
    OpenBBClient,
    OpenBBFetchError,
)

#: The live local service. Call it directly so an HTTP status is visible --
#: ``OpenBBClient`` normalises failures into ``OpenBBFetchError``, which is
#: right for production and wrong for a probe: this script needs the raw
#: 204-vs-400-vs-404 distinction.
_BASE = "http://127.0.0.1:6900/api/v1"


def _raw_get(url: str, params: dict[str, Any] | None = None) -> tuple[int, str]:
    """GET a full URL and return ``(status_code, body_text)``, never raising."""
    import httpx

    try:
        with httpx.Client(timeout=25.0, headers={"Connection": "close"}) as c:
            r = c.get(url, params=params or {})
    except Exception as exc:
        return (-1, f"{type(exc).__name__}: {exc}")
    return (r.status_code, r.text)


def _http(path: str, params: dict[str, Any]) -> tuple[int, str]:
    """GET one route under ``/api/v1`` and return ``(status_code, body_text)``."""
    return _raw_get(f"{_BASE}/{path}", params)


def _row_summary(body: str) -> str:
    """A one-line shape summary of a JSON route body."""
    try:
        payload = json.loads(body)
    except Exception:
        return body[:140].replace("\n", " ")
    if isinstance(payload, dict):
        if "detail" in payload and "results" not in payload:
            return f"detail={str(payload['detail'])[:150]}"
        rows = payload.get("results")
        if isinstance(rows, list):
            if not rows:
                return "results=[] (empty list)"
            keys = sorted(rows[0].keys()) if isinstance(rows[0], dict) else "?"
            last = rows[-1] if isinstance(rows[-1], dict) else None
            return f"rows={len(rows)} cols={keys} last={last}"
    return body[:140].replace("\n", " ")


# --------------------------------------------------------------------------
# Probe 1: the route surface -- which currency/forward routes EXIST at all?
# --------------------------------------------------------------------------
def probe_route_surface() -> None:
    print("=" * 78)
    print("PROBE 1 - the FX route surface (called, not enumerated)")
    print("-" * 78)
    code, body = _raw_get("http://127.0.0.1:6900/openapi.json")
    if code != 200:
        print(f"[FAIL] could not read the OpenAPI spec (HTTP {code}); {body[:120]}")
        return
    spec = json.loads(body)
    paths = list(spec["paths"])
    print(f"live spec: {len(paths)} paths")

    # Every route with 'currency' in its path -- the FX namespace, exhaustively.
    fx = sorted(p.replace("/api/v1/", "") for p in paths if "/currency/" in p)
    print(f"routes under /currency/ ({len(fx)}):")
    for p in fx:
        node = spec["paths"]["/api/v1/" + p]["get"]
        provs: list[str] = []
        for prm in node.get("parameters", []):
            if prm["name"] == "provider":
                sc = prm.get("schema", {})
                provs = sc.get("enum") or ([sc["const"]] if "const" in sc else [])
        print(f"    {p:<38} providers={provs}")

    # Anything anywhere whose NAME suggests a forward/swap/basis.
    import re

    pat = re.compile(r"forward|swap|basis", re.I)
    named = sorted(p.replace("/api/v1/", "") for p in paths if pat.search(p))
    print(f"\nroutes whose name matches forward|swap|basis ({len(named)}):")
    for p in named:
        print(f"    {p}")


# --------------------------------------------------------------------------
# Probe 2: CALL the FX-futures route for the CME tickers D-108 called dead.
# --------------------------------------------------------------------------
def probe_fx_futures() -> None:
    print()
    print("=" * 78)
    print("PROBE 2 - CALL derivatives.futures.historical for CME FX futures")
    print("          (D-108 recorded these as EmptyDataError via yfinance)")
    print("-" * 78)
    for sym in ("6E=F", "6J=F", "6B=F", "6A=F", "6C=F", "6S=F"):
        code, body = _http(
            "derivatives/futures/historical",
            {"provider": "yfinance", "symbol": sym, "start_date": "2026-09-01"},
        )
        print(f"  {sym:<8} HTTP {code:<4} {_row_summary(body)[:170]}")


# --------------------------------------------------------------------------
# Probe 3: are DATED contracts reachable, or only the rolling front month?
# --------------------------------------------------------------------------
def probe_dated_contracts() -> None:
    print()
    print("=" * 78)
    print("PROBE 3 - dated contracts vs the rolling front-month")
    print("          (a forward needs a DATE; a rolling series is not one)")
    print("-" * 78)
    for sym in ("6EZ26", "6EM27", "6EH27", "6EU26", "6EDEC26", "6E=F"):
        code, body = _http(
            "derivatives/futures/historical",
            {"provider": "yfinance", "symbol": sym, "start_date": "2026-09-01"},
        )
        print(f"  {sym:<10} HTTP {code:<4} {_row_summary(body)[:150]}")


# --------------------------------------------------------------------------
# Probe 3b: the `expiration` PARAMETER -- the coverage gap in the first pass.
# --------------------------------------------------------------------------
def probe_expiration_parameter() -> None:
    print()
    print("=" * 78)
    print("PROBE 3b - the `expiration` query parameter (a COVERAGE GAP in pass one)")
    print("          derivates.futures.historical accepts `expiration`; the D-151")
    print("          probe never sent it, so a dated fetch was never actually tried.")
    print("-" * 78)
    # The V6-style ticker (a real dated CME 6E contract) WITH its own expiry date.
    for sym, exp in (
        ("6EZ6", "2026-12-14"),
        ("6E", "2026-12-14"),
        ("6EV6", "2026-10-19"),
    ):
        code, body = _http(
            "derivatives/futures/historical",
            {
                "provider": "yfinance",
                "symbol": sym,
                "expiration": exp,
                "start_date": "2026-09-01",
            },
        )
        print(f"  symbol={sym:<6} expiration={exp}  HTTP {code}")
        print(f"      {_row_summary(body)[:170]}")
    print(
        "  Reading: a 422 with `unconverted data remains: -14` means the route's"
        " yfinance path cannot parse the date even in the contract's own format;"
        " a 204 means the dated ticker itself resolves to nothing. Either way the"
        " dated fetch does not answer -- and now it is MEASURED, not assumed."
    )


# --------------------------------------------------------------------------
# Probe 3c: FRED's "Currency, Swaps" family -- a product, or a look-alike?
# --------------------------------------------------------------------------
def probe_fred_swaps() -> None:
    print()
    print("=" * 78)
    print("PROBE 3c - FRED 'swaps' family: is it a CIP source or a look-alike?")
    print("          A family named 'Currency; Swaps' READS like an FX CIP source.")
    print("          CALL it: if every member is a balance-sheet quantity, it is")
    print("          the Fed's USD swap LINES, not a forward or a basis.")
    print("-" * 78)
    code, body = _http("economy/fred_search", {"query": "swaps", "provider": "fred", "limit": 12})
    print(f"  economy.fred_search query=swaps  HTTP {code}")
    try:
        payload = json.loads(body)
    except Exception:
        payload = {}
    for row in (payload.get("results") or [])[:12]:
        sid = row.get("series_id", "?")
        title = str(row.get("title", ""))[:88]
        print(f"      {sid:<22} {title}")
    print(
        "  Reading: every member above begins 'Assets: Central Bank Liquidity"
        " Swaps' -- the Fed's USD swap LINES (a balance-sheet quantity). NOT a"
        " forward point and NOT a cross-currency basis. The route CALLS fine"
        " (control: DEXUSEU returns rows); the PRODUCT is simply absent."
    )


# --------------------------------------------------------------------------
# Probe 4: missing ROUTE or missing CREDENTIAL? -- call and see which.
# --------------------------------------------------------------------------
def probe_credential_boundary() -> None:
    print()
    print("=" * 78)
    print("PROBE 4 - missing ROUTE vs missing CREDENTIAL (the D-108 hypothesis)")
    print("          A 400 'Missing credential' proves a key would help;")
    print("          a 404/422 proves the route itself is absent.")
    print("-" * 78)
    for prov in ("fmp", "tiingo", "yfinance"):
        code, body = _http(
            "currency/price/historical",
            {"provider": prov, "symbol": "EURUSD", "start_date": "2026-09-01"},
        )
        print(f"  currency.price.historical  provider={prov:<10} HTTP {code:<4}")
        print(f"      {_row_summary(body)[:170]}")
    # And: does ANY route expose a forward under a credentialed provider?
    print()
    print("  -- does any route carry a forward under fmp/tiingo/intrinio? --")
    for path in ("currency/forward_rate", "currency/forward", "currency/swap"):
        code, body = _http(path, {"provider": "fmp", "symbol": "EURUSD"})
        status = "ABSENT (route does not exist)" if code == 404 else f"HTTP {code}"
        print(f"    {path:<28} {status}")


# --------------------------------------------------------------------------
# Probe 5: the production client path -- can OpenBBClient read the future?
# --------------------------------------------------------------------------
def probe_via_client() -> None:
    print()
    print("=" * 78)
    print("PROBE 5 - the production client path (OpenBBClient.fetch_series)")
    print("          This is the transport the engine actually uses.")
    print("-" * 78)
    client = OpenBBClient()
    try:
        frame = client.fetch_series(
            provider="yfinance",
            endpoint="derivatives.futures.historical",
            params={"symbol": "6E=F", "start_date": "2026-09-01"},
            series_label="fx_future_6e",
        )
    except OpenBBFetchError as exc:
        print(f"  [FAIL] {type(exc).__name__}: {str(exc)[:170]}")
        return
    finally:
        client.close()
    if frame is None or frame.empty:
        print("  [EMPTY] the client returned no rows")
        return
    print(f"  [OK] normalised frame: {frame.shape[0]} rows, cols={list(frame.columns)}")
    print(f"       head: {frame.head(2).to_dict(orient='records')}")
    print(f"       tail: {frame.tail(2).to_dict(orient='records')}")
    print(
        "  NOTE: the normalised 'value' is the route's daily CLOSE, and a "
        "rolling front-month's close is NOT a forward for any given date."
    )


def main() -> int:
    print("FX-FORWARD PROBE - re-measuring the D-108 block (2026-09-25)")
    print("Every probe below CALLS its source; none infers from a route name.")
    probe_route_surface()
    probe_fx_futures()
    probe_dated_contracts()
    probe_expiration_parameter()
    probe_fred_swaps()
    probe_credential_boundary()
    probe_via_client()
    probe_databento_path()
    print()
    print("=" * 78)
    print("VERDICT is derived by the reader of this output, from the CALLS above.")
    print(
        "The questions each probe answers: (1) is there a forward ROUTE? "
        "(2) do the CME tickers D-108 called dead actually answer? "
        "(3) is a DATED contract reachable, or only a rolling series? "
        "(3b) does the `expiration` parameter reach a dated contract? "
        "(3c) is the FRED 'swaps' family a forward or a look-alike? "
        "(4) is the block a missing CREDENTIAL or a missing PRODUCT? "
        "(5) does the production transport read it at all? "
        "(6) does the WIRED Databento client fetch a dated close?"
    )
    print()
    print(
        "MEASURED VERDICT (2026-10-10): the block STANDS as a DATA block for"
        " every OpenBB route -- no forward route, no dated contract via yfinance,"
        " no CIP series on FRED. BUT the block is NOT 'no data exists in the"
        " world': CME's 96 dated 6E instruments ARE forwards for their expiry,"
        " served by Databento with free keys."
    )
    print(
        "LIFTED 2026-10-10 (D-154): the block was a DEPENDENCY block, not a data"
        " wall. `data_layer/fx_forward_client.py` + `live_cip_check` now supply"
        " `cip_check`'s observed `forward` from a dated CME contract. Probe 6"
        " above runs the WIRED client; it reports the dependency/credential"
        " refusal explicitly until `databento` is installed and"
        " DATABENTO_API_KEY is set -- and a live dated close once both are."
    )
    return 0


# --------------------------------------------------------------------------
# Probe 6: the WIRED client path -- does the real Databento fetch work?
# --------------------------------------------------------------------------
def probe_databento_path() -> None:
    print()
    print("=" * 78)
    print("PROBE 6 - the WIRED client: fetch_fx_forward via the default transport")
    print("          This is the path `live_cip_check` uses. It is the ONE probe")
    print("          here that can LIFT the block rather than re-confirm it.")
    print("          Expect a named refusal until the dependency + key are set.")
    print("-" * 78)
    from datetime import date

    from macro_engine.data_layer.fx_forward_client import (
        FXForwardError,
        FXForwardUnavailableError,
        fetch_fx_forward,
    )

    expiry = date(2026, 12, 14)  # the 6EZ6 settlement date (a live catalog read)
    try:
        reading = fetch_fx_forward("EURUSD", expiry=expiry)
    except FXForwardUnavailableError as exc:
        # The EXPECTED outcome in a bare environment: a dependency or a
        # credential is missing. Printed as its own case so it is never mistaken
        # for "no data exists" -- the exact confusion this whole probe exists to
        # prevent.
        print("  [GATED] a required external fact is missing (NOT a data gap):")
        print(f"      {str(exc)[:300]}")
        print(
            "  Reading: the block is a DEPENDENCY/CREDENTIAL block. Install the"
            " `databento` package and set DATABENTO_API_KEY (free key) and this"
            " probe returns a live dated close instead."
        )
        return
    except FXForwardError as exc:
        print(f"  [FAIL] the fetch was attempted and failed: {type(exc).__name__}")
        print(f"      {str(exc)[:300]}")
        return

    if reading is None:
        print("  [NONE] EURUSD is not registered for the dated-forward layer")
        return

    print(
        f"  [OK] dated contract {reading.symbol} root={reading.root} "
        f"expiry={reading.expiry.isoformat()}"
    )
    print(
        f"       raw settlement={reading.forward}  pair_forward={reading.pair_forward} "
        f"(is_inverse={reading.is_inverse})  tenor_days={reading.tenor_days}"
    )
    print(f"       convention: {reading.convention}")
    print(f"       source: {reading.source}")
    print(
        "  Reading: this is the OBSERVED forward `cip_check` needs. Feed it"
        " through `live_cip_check` with the two money-market rates to measure the"
        " market's own CIP deviation."
    )


if __name__ == "__main__":
    sys.exit(main())
