"""Probe: are the LEI proxy components reachable, and with what coverage?

Section 21.1 names four free components for an in-house composite built
instead of the licensed Conference Board LEI:
    claims, permits, curve slope, S&P 500.
Claims and the curve already exist in the registry. This probes the rest, plus
a few alternates, and probes the licensed series itself so the BLOCKED claim is
evidence-backed rather than assumed.

Run::

    uv run python scripts/_probe_lei.py
"""

from __future__ import annotations

from macro_engine.data_layer.openbb_client import OpenBBClient

SYMBOLS = [
    "PERMIT",
    "PERMIT1",
    "PERMITNSA",
    "HOUST",
    "SP500",
    "SP500_NASDAQ",
    "ICSA",
    "T10Y3M",
    "UMCSENT",
    "DGORDER",
    "ACDGNO",
    "AWHAETP",
    "M2SL",
    "USSLIND",
    "USLEI",
]


def main() -> None:
    client = OpenBBClient()
    for symbol in SYMBOLS:
        try:
            df = client.fetch_series(
                provider="fred",
                endpoint="economy.fred_series",
                params={"symbol": symbol},
                series_label=symbol,
            )
        except Exception as exc:  # a probe reports a failure, it does not stop
            print(f"{symbol:14s} ERROR {type(exc).__name__}: {str(exc)[:90]}")
            continue
        if df is None or df.empty:
            print(f"{symbol:14s} EMPTY")
            continue
        clean = df.loc[df["value"].notna()]
        if clean.empty:
            print(f"{symbol:14s} ALL-NULL n={len(df):5d}")
            continue
        first = clean.iloc[0]
        last = clean.iloc[-1]
        print(
            f"{symbol:14s} n={len(clean):5d} first={first['date']} ({first['value']:.5g}) "
            f"last={last['date']} ({last['value']:.5g})"
        )


if __name__ == "__main__":
    main()
