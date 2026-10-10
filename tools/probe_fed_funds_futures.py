"""Probe for a Fed-funds-futures / policy-path source — the Section 22.5 gate.

**Why this probe exists.** `AGENTS.md` §22.5 obligates Phase 5+ to REPLACE
`derive_market_implied_policy_path` with *"a real Fed-funds-futures-implied
probability distribution (Section 4/16's original intent)"*. §16's own comment
(line 1223) hedges the feasibility in the spec's own words:

    "a full Fed-funds-futures-based implied path is Phase 5+, requires a futures
     data source OpenBB may or may not expose cleanly; document as a known
     limitation if not"

So the obligation is CONDITIONAL on a data source, exactly like the FX-forward
block (D-108). This probe answers the conditional question **before** any code is
written, per §21.0 rule 3 (*no input may be invented*) and the re-probe
discipline recorded in `docs/PHASE5_DEFERRED.md` §2.5.

It is READ-ONLY and DISCOVERY-ONLY: it writes no config, changes no `status:`
field, and substitutes no series.

Run:
    uv run python tools/probe_fed_funds_futures.py
"""

from __future__ import annotations

import sys
from typing import Any

from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError

#: FRED series that describe the POLICY RATE and its EXPECTATIONS. The first
#: group is the realised effective rate; the second is the market's *forward*
#: expectation, which is the quantity §22.5 wants. Any series here that returns
#: a value is a candidate; none is written to config by this script.
POLICY_RATE_CANDIDATES: dict[str, str] = {
    "DFF": "Effective federal funds rate, daily, PERCENT (realised, NOT a forward)",
    "FEDFUNDS": "Effective federal funds rate, monthly, PERCENT (realised)",
    "EFFR": "Effective federal funds rate, daily, PERCENT (realised)",
    "IORB": "Interest on reserve balances, PERCENT (administered, not forward)",
}

#: The forward/expectations family. FRED publishes the Cleveland Fed's model
#: output and the CME-adjacent implied measures; these are the only FRED-hosted
#: objects that carry a *path* rather than a realised point.
FORWARD_EXPECTATION_CANDIDATES: dict[str, str] = {
    "EXPINF1YR": "1-year expected inflation (Cleveland Fed) — a forecast, not a policy path",
    "EXPINF2YR": "2-year expected inflation (Cleveland Fed)",
    "T5YIFR": "5y5y forward inflation expectation — a forward, but inflation not policy",
    "DFEDTARU": "Fed funds target range upper limit, PERCENT (administered)",
    "DFEDTARL": "Fed funds target range lower limit, PERCENT (administered)",
    "STICKCPIM157SFRBATL": "Atlanta Fed sticky CPI — a price measure, NOT policy",
    # The genuinely path-shaped candidates. If any of these resolve, §22.5 is
    # buildable on data already reachable on this install.
    "MICH1M": "1-month ahead expected rate — a survey expectation",
    "PCECTPI": "PCE — a price index, NOT policy",
}

#: The CME FedWatch object is the canonical source for a fed-funds-FUTURES-implied
#: probability distribution. It is NOT on FRED, so it is probed through the
#: OpenBB route registry instead (see `probe_routes`).
FUTURES_ROUTE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("fed funds futures", r"fed.?funds.*futur|futur.*fed.?funds"),
    ("any futures route", r"futur"),
    ("policy path", r"policy.?path|path.*policy"),
    ("rate probability", r"probab.*(rate|cut|hike)|(rate|cut|hike).*probab"),
    ("CME", r"\bcme\b"),
    ("swap / OIS", r"\bswap\b|\bois\b"),
)


def probe_series(symbol: str, note: str) -> dict[str, Any]:
    """Fetch one FRED symbol and classify whether it is a realised rate or a forward."""
    client = OpenBBClient()
    try:
        frame = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": symbol},
            series_label=symbol,
        )
    except OpenBBFetchError as exc:
        return {"symbol": symbol, "note": note, "error": str(exc)}
    except Exception as exc:
        return {"symbol": symbol, "note": note, "error": f"{type(exc).__name__}: {exc}"}

    if frame.empty:
        return {"symbol": symbol, "note": note, "error": "empty frame"}

    # The client returns a LONG-format frame with explicit `date` and `value`
    # columns (measured: shape (26398, 5) = date, value, series_id, source,
    # retrieved_at). Select by NAME rather than trusting position, so a change in
    # column order cannot silently turn this probe into a no-op.
    if "value" not in frame.columns or "date" not in frame.columns:
        return {
            "symbol": symbol,
            "note": note,
            "error": f"unexpected columns {list(frame.columns)}",
        }
    series = frame[["date", "value"]].dropna(subset=["value"])
    if series.empty:
        return {"symbol": symbol, "note": note, "error": "all-NaN in the 'value' column"}
    last_row = series.iloc[-1]
    last = float(last_row["value"])
    return {
        "symbol": symbol,
        "note": note,
        "rows": len(series),
        "first_date": str(series.iloc[0]["date"])[:10],
        "last_date": str(last_row["date"])[:10],
        "last_value": round(last, 4),
    }


def probe_routes() -> list[str]:
    """Enumerate the OpenBB route registry and return any futures-shaped routes.

    Returns an empty list when the registry is unreachable — the caller reports
    that as NOT PROBED rather than as absence, because absence of a probe is not
    evidence of absence of a route (the lesson behind `tools/openbb_reachability.py`).
    """
    import re

    try:
        from openbb import obb
    except Exception as exc:
        return [f"<registry unreachable: {type(exc).__name__}: {exc}>"]

    routes: list[str] = []

    def walk(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict) and value:
                walk(value, path)
            else:
                routes.append(path)

    # `obb.reference` is a `dict` at runtime (the stub types it as part of a
    # `BaseApp | Extensions` union), so reach it through `getattr` rather than
    # attribute access and let the walker decide. mypy's union-attr error here
    # is about the stub, not about the runtime object this probe actually sees.
    reference: Any = getattr(obb, "reference", None)
    try:
        walk(reference if isinstance(reference, dict) else dict(reference or {}), "")
    except Exception as exc:
        return [f"<registry walk failed: {type(exc).__name__}: {exc}>"]
    if not routes:
        coverage: Any = getattr(obb, "coverage", None)
        try:
            walk(coverage if isinstance(coverage, dict) else dict(coverage or {}), "")
        except Exception as exc:
            return [f"<no routes enumerated; coverage failed: {type(exc).__name__}: {exc}>"]

    matched: list[str] = []
    seen: set[str] = set()
    for label, pattern in FUTURES_ROUTE_PATTERNS:
        rx = re.compile(pattern, re.IGNORECASE)
        for route in routes:
            if rx.search(route) and route not in seen:
                seen.add(route)
                matched.append(f"[{label}] {route}")
    return matched


def main() -> int:
    print("=" * 78)
    print("PROBE: Fed-funds-futures / policy-path source (Section 22.5 gate)")
    print("READ-ONLY. Writes no config; changes no status field.")
    print("=" * 78)

    print(f"\n--- A. REALISED policy-rate series ({len(POLICY_RATE_CANDIDATES)}) ---")
    for symbol, note in POLICY_RATE_CANDIDATES.items():
        result = probe_series(symbol, note)
        if "error" in result:
            print(f"  {symbol:<12} ERROR  {note}")
            print(f"               -> {result['error'][:110]}")
        else:
            print(
                f"  {symbol:<12} OK  last={result['last_value']:<10} "
                f"rows={result['rows']:<6} {result['first_date']}..{result['last_date']}  {note}"
            )

    print(f"\n--- B. FORWARD / expectation series ({len(FORWARD_EXPECTATION_CANDIDATES)}) ---")
    for symbol, note in FORWARD_EXPECTATION_CANDIDATES.items():
        result = probe_series(symbol, note)
        if "error" in result:
            print(f"  {symbol:<22} ERROR  {note}")
            print(f"               -> {result['error'][:110]}")
        else:
            print(
                f"  {symbol:<22} OK  last={result['last_value']:<10} "
                f"rows={result['rows']:<6} {result['first_date']}..{result['last_date']}  {note}"
            )

    print("\n--- C. OpenBB route registry: any futures-shaped route? ---")
    routes = probe_routes()
    if not routes:
        print("  (no futures-shaped route found in the registry)")
    for route in routes[:40]:
        print(f"  {route}")
    if len(routes) > 40:
        print(f"  ... and {len(routes) - 40} more")

    print("\n" + "=" * 78)
    print("VERDICT CRITERIA: a Fed-funds-futures-implied DISTRIBUTION requires a")
    print("futures settlement or a CME-probability route. Group B alone gives")
    print("expectations of INFLATION or of administered rates -- none of which is")
    print("'the market's probability distribution over future POLICY RATES'.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
