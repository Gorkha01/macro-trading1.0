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

⚠️ **What the FIRST version of this probe got wrong — and why section D exists.**
It walked the OpenBB route registry and printed route-shaped strings, then closed
with *"VERDICT CRITERIA: … requires a futures settlement or a CME-probability
route"*. That is a statement of what WOULD be needed, not a finding, and it reads
like a conclusion. It cannot distinguish *"the route exists and returns a usable
curve"* from *"no such route exists"* — and a whole session duly recorded §22.5 as
*"needs data"* while the data sat behind `derivatives.futures.curve`, a route
whose NAME contains `futur`, a token the D-108 inventory grep never searched for.

**A route name is a hypothesis; only a CALL tests it.** Section D therefore
invokes the route with the symbol and prints what comes back, and the verdict is
derived from that call rather than restated. Pinned by
`tests/data_layer/test_fed_funds_futures_client.py::
test_the_probe_calls_the_route_and_does_not_only_enumerate_it`.

**Measured verdict 2026-10-10: the source EXISTS.** `ZQ` on
`derivatives.futures.curve` returns a 16-point term structure whose front
contract implies 3.88% — EQUAL to the measured `DFF`/`EFFR` and inside the
`DFEDTARL`/`DFEDTARU` range. ⚠️ 6 of those 16 rows are CORRUPT (price ~47-48 →
~52% implied, deterministic across calls); the loader REJECTS and names them.

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

#: The 30-Day Fed Funds futures root symbol, probed LIVE below. This is the
#: contract that settles to `100 - <the month's average effective rate>`, so its
#: price inverts directly into a market-implied policy rate.
#:
#: Probed with the BARE code `ZQ`: `ZQ=F` was measured to 404 on the CURVE route
#: although it resolves on the HISTORICAL route, so the bare code is what the
#: curve loader must send.
PROBE_FUTURES_SYMBOL = "ZQ"
PROBE_FUTURES_PROVIDER = "yfinance"

#: The routes worth CALLING (not merely enumerating). `curve` returns the term
#: structure in one shot; `historical` returns one contract's time series and is
#: probed to show the *settlement-price* path rather than the curve.
PROBE_FUTURES_ROUTES: tuple[str, ...] = (
    "derivatives.futures.curve",
    "derivatives.futures.historical",
)


def probe_futures_route(route: str, symbol: str) -> dict[str, Any]:
    """CALL a futures route and report what it actually returns.

    **Why this exists — and why enumerating route NAMES is not enough.** The
    first version of this probe only walked the registry and printed
    route-shaped strings. That CANNOT distinguish *"the route exists and returns
    a usable curve"* from *"no route of this shape exists"*, and its verdict
    block nudged the reader toward the second — which is how a whole session
    recorded §22.5 as *"needs data"* while the data sat behind a route whose
    name contains `futur`, a token the inventory grep never searched for.

    A route NAME is a hypothesis. This function tests it. The distinction is the
    same one the project draws everywhere else: `ls` the artifact a claim names
    rather than trusting the claim.
    """
    try:
        from openbb import obb
    except Exception as exc:
        return {"error": f"openbb unreachable: {type(exc).__name__}: {exc}"}

    # The route string "derivatives.futures.curve" resolves through obb's
    # attribute tree; walk it rather than eval so a rename fails loudly here.
    node: Any = obb
    try:
        for part in route.split("."):
            node = getattr(node, part)
    except AttributeError as exc:
        return {"error": f"route not present on obb: {exc}"}

    try:
        result = node(symbol=symbol, provider=PROBE_FUTURES_PROVIDER)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    records = getattr(result, "results", None)
    if records is None:
        return {"error": "the call returned no `.results` attribute"}

    rows: list[dict[str, Any]] = []
    for item in records:
        if hasattr(item, "model_dump"):
            rows.append(item.model_dump())
        elif isinstance(item, dict):
            rows.append(item)
        else:
            rows.append({"repr": repr(item)})

    return {"rows": rows, "count": len(rows)}


def _summarise_futures_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int = 20,
) -> list[str]:
    """One line per row, showing the horizon and the implied rate when derivable.

    Kept deliberately dumb: it prints the RAW columns so a reader can see the
    source's own field names, and computes `100 - price` only as an annotation.
    A probe that pre-digests the data hides the defect it exists to find.

    ``limit`` truncates the tail and SAYS SO — a probe that silently prints 250
    rows of one shape buries the 16 that matter. Rows whose price is not
    numeric are counted rather than repeated, because `historical` returns
    ``date``/``close`` rather than ``expiration``/``price`` and printing 251
    copies of "price not numeric" is noise, not evidence.
    """
    lines: list[str] = []
    non_numeric = 0
    for row in rows[:limit]:
        expiration = row.get("expiration", "?")
        price = row.get("price", "?")
        try:
            implied = f"  -> implied {100.0 - float(price):.2f}%"
        except (TypeError, ValueError):
            # `historical` has a different column set. Name the columns ONCE so
            # the reader can adapt, instead of repeating a blank line per row.
            non_numeric += 1
            implied = f"  -> price not numeric (columns: {sorted(row)[:6]})"
        lines.append(f"    {expiration}  price={price}{implied}")
    if non_numeric == len(rows[:limit]) and non_numeric:
        # Collapse the whole block: this route is not the curve route.
        return [
            f"    (this route returns no `expiration`/`price` columns; "
            f"first row's keys: {sorted(rows[0])[:8]})",
            f"    {len(rows)} row(s) total, 0 with a usable price — NOT the curve route.",
        ]
    if len(rows) > limit:
        lines.append(f"    ... and {len(rows) - limit} more row(s)")
    return lines


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

    # --- D. THE DECISIVE SECTION. Enumerating a route name proves nothing; call
    #        it. This is the step the first version of this probe was missing,
    #        and its absence is why §22.5 was mis-recorded as "needs data".
    print(f"\n--- D. LIVE CALL: {PROBE_FUTURES_SYMBOL} on the futures routes ---")
    usable = 0
    for route in PROBE_FUTURES_ROUTES:
        outcome = probe_futures_route(route, PROBE_FUTURES_SYMBOL)
        if "error" in outcome:
            print(f"  {route:<32} ERROR  {outcome['error'][:100]}")
            continue
        rows = outcome["rows"]
        print(f"  {route:<32} OK  {outcome['count']} row(s)")
        for line in _summarise_futures_rows(rows):
            print(line)
        if rows:
            usable += 1

    print("\n" + "=" * 78)
    if usable:
        print("VERDICT: a FUTURES-shaped route EXISTS and RETURNS DATA for")
        print(f"  {PROBE_FUTURES_SYMBOL} via {PROBE_FUTURES_PROVIDER}.")
        print("")
        print("  A 30-Day Fed Funds future settles to")
        print("  `100 - <the contract month's average effective funds rate>`, so")
        print("  `implied_rate = 100 - price` IS a market-implied policy rate.")
        print("  §22.5 is therefore BUILDABLE on this install — the block was a")
        print("  MISSED SOURCE, not missing data. Cross-check: the front contract's")
        print("  implied rate must EQUAL the measured DFF/EFFR and sit inside the")
        print("  DFEDTARL/DFEDTARU target range; if it does not, the symbol is")
        print("  wrong or the contract is not the one this probe assumes.")
        print("")
        print("  ⚠️ CHECK THE ROWS ABOVE FOR CORRUPTION before trusting the curve.")
        print("  Measured 2026-10-10: 6 of 16 expirations returned a price near")
        print("  47-48 (a ~52% implied policy rate) instead of 95-96 — deterministic")
        print("  across three calls, i.e. source corruption, not a market view. A")
        print("  consumer must REJECT such rows (never clamp them) and disclose the")
        print("  count. The loader in data_layer/fed_funds_futures_client.py does.")
    else:
        print("VERDICT: NO futures route returned data for")
        print(f"  {PROBE_FUTURES_SYMBOL}. §22.5 is NOT buildable on this install,")
        print("  and the block is a genuine data block (like the FX-forward one).")
        print("  Group A/B alone are NOT a substitute: they give expectations of")
        print("  INFLATION or administered rates, which are not the market's")
        print("  distribution over future POLICY RATES.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
