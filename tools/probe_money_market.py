"""Probe the money-market series routes before wiring them into the snapshot.

Rationale (§21.0 rule 3, "no input may be invented"): Section 21.1 defines
`on_rrp_rate` as LIVE / FRED `RRPONTSYD`. An earlier Phase-0 audit suspected
that symbol is an ON-RRP *volume* (USD billions) rather than a *rate* (percent),
which would make it unusable as the lower bound of the SOFR/IORB corridor that
`repo_stress_check` (Section 20.2) depends on.

This probe is READ-ONLY and DISCOVERY-ONLY: it does not write config, does not
change any `status:` field, and does not substitute a series. It exists so the
question put to the human is grounded in measured values rather than suspicion.

Run:
    uv run python tools/probe_money_market.py
"""

from __future__ import annotations

import sys
from typing import Any

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError

# Candidate symbols for the corridor bounds. The first is the spec-mandated
# route for `on_rrp_rate`; the rest are the plausible corrections, listed so
# the human can pick with real numbers in front of them. None is written to
# config by this script.
CORRIDOR_CANDIDATES: dict[str, list[str]] = {
    "on_rrp_rate (spec route)": ["RRPONTSYD"],
    "repo / secured rates": ["SOFR", "SOFR99", "EFFR", "OBFR", "IORB", "TGCRRATE", "BGCRRATE"],
    "on_rrp alternatives": ["RRPONTSYAWARD", "IORB"],
}

# FRED's own units, printed for each probe so a volume cannot be mistaken for
# a rate by eye.
UNITS_NOTE: dict[str, str] = {
    "RRPONTSYD": "overnight reverse repo operations, USD BILLIONS (a VOLUME, not a rate)",
    "RRPONTSYAWARD": "ON RRP offering rate, PERCENT",
    "SOFR": "secured overnight financing rate, PERCENT",
    "EFFR": "effective federal funds rate, PERCENT",
    "OBFR": "overnight bank funding rate, PERCENT",
    "IORB": "interest on reserve balances, PERCENT",
    "TGCRRATE": "tri-party general collateral rate, PERCENT",
    "BGCRRATE": "broad general collateral rate, PERCENT",
}


def _plausible_for_a_rate(value: float) -> str:
    if 0.0 < value < 15.0:
        return "RATE-LIKE"
    if value >= 15.0:
        return "VOLUME-LIKE (far above any plausible policy rate)"
    return "IMPLAUSIBLE as a rate"


def probe(symbol: str) -> dict[str, Any]:
    client = OpenBBClient()
    try:
        frame = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": symbol},
            series_label=symbol,
        )
    except OpenBBFetchError as exc:
        return {"symbol": symbol, "error": str(exc)}

    if frame.empty:
        return {"symbol": symbol, "error": "empty frame"}

    latest = frame.iloc[-1]
    return {
        "symbol": symbol,
        "rows": len(frame),
        "latest_date": str(latest["date"])[:10],
        "latest_value": float(latest["value"]),
        "shape": _plausible_for_a_rate(float(latest["value"])),
    }


def main() -> int:
    settings = get_settings()
    print(f"openbb local first : {settings.openbb.local_first}")
    print(f"openbb base url    : {settings.openbb.base_url}")
    print()

    registry = get_registry()
    entry = registry.series.get("on_rrp_rate")
    if entry is not None:
        print(f"registry `on_rrp_rate` -> provider={entry.provider} symbol={entry.symbol}")
        print(f"registry status        : {entry.status}")
    print()

    for group, symbols in CORRIDOR_CANDIDATES.items():
        print(f"--- {group} ---")
        for symbol in symbols:
            result = probe(symbol)
            if "error" in result:
                print(f"  {symbol:<14} ERROR: {result['error'][:90]}")
                continue
            note = UNITS_NOTE.get(symbol, "")
            print(
                f"  {symbol:<14} {result['latest_value']:>12,.2f}  "
                f"@ {result['latest_date']}  rows={result['rows']:<6} "
                f"{result['shape']}"
            )
            if note:
                print(f"  {'':<14} units: {note}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
