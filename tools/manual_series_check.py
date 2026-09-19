#!/usr/bin/env python
"""Verify one series route against its real source. (AGENTS.md Section 21.1.)

Section 21.1 requires every LIVE input to have "a verified series ID (Phase 0
discipline)". A registry entry that has never been exercised is a guess wearing
a symbol name, and the failure mode is quiet: the fetch returns empty, the
snapshot records no observations, and a model treats "no data" as "no signal"
rather than "the source is wrong".

This tool is how a route earns its ``status: verified``. Run it, paste the
result into ``docs/SERIES_VERIFICATION.md``, then update the registry entry.

Usage
-----
    uv run python tools/manual_series_check.py                  # verify all
    uv run python tools/manual_series_check.py cpi_headline     # verify one
    uv run python tools/manual_series_check.py --list           # show registry

Exit codes: 0 if every checked route returned data, 1 otherwise. Non-zero on
partial failure so this can gate a CI job without parsing its output.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.openbb_client import (
    OpenBBClient,
    OpenBBClientConfig,
    OpenBBFetchError,
)
from macro_engine.models.contracts import utc_now

# Sanity bounds are read from each registry entry's `plausible_range` when
# present, falling back to no bound. Judging whether a route returns data that
# is *plausible* (not merely present) matters: a series returning millions of
# rows of zeros has a working connection and a broken mapping. Keeping the
# bounds in the registry rather than in this file means the check and the
# registry can never disagree about what a sane value looks like.
TENOR_PLAUSIBILITY: tuple[float, float] = (0.05, 20.0)  # percent; TIPS can go slightly negative


def _fmt(value: float) -> str:
    return f"{value:,.4f}"


def _bounds_for(entry: object) -> tuple[float | None, float | None]:
    """Extract the registry entry's plausible range, if it declares one."""
    raw = getattr(entry, "plausible_range", None)
    if not raw or len(raw) != 2:
        return (None, None)
    return (float(raw[0]), float(raw[1]))


def check_simple(
    entry_key: str,
    entry_symbol: str,
    provider: str,
    endpoint: str,
    client: OpenBBClient,
    bounds: tuple[float | None, float | None] = (None, None),
) -> tuple[bool, str]:
    """Fetch a single-symbol series and report on it."""
    settings = get_settings()
    start = (utc_now() - timedelta(days=365 * settings.data.lookback)).date().isoformat()
    try:
        frame = client.fetch_series(
            provider=provider,
            endpoint=endpoint,
            params={"symbol": entry_symbol, "start_date": start},
            series_label=entry_key,
        )
    except OpenBBFetchError as exc:
        return False, f"FETCH FAILED — {exc}"

    if frame.empty:
        return False, "RETURNED EMPTY"

    latest = frame.iloc[-1]
    oldest = frame.iloc[0]
    lo, hi = bounds
    verdict = "plausible"
    if lo is not None and float(latest["value"]) < lo:
        verdict = f"IMPLAUSIBLE (below {lo})"
    if hi is not None and float(latest["value"]) > hi:
        verdict = f"IMPLAUSIBLE (above {hi})"

    detail = (
        f"{len(frame)} rows | {oldest['date']} -> {latest['date']} | "
        f"latest={_fmt(float(latest['value']))} | {verdict}"
    )
    ok = verdict == "plausible"
    return ok, detail


def check_curve(
    entry_key: str,
    tenors: dict[str, str],
    provider: str,
    endpoint: str,
    client: OpenBBClient,
) -> tuple[bool, str]:
    """Fetch each tenor of a curve and report per-tenor success."""
    settings = get_settings()
    start = (utc_now() - timedelta(days=int(365 * settings.data.lookback))).date().isoformat()
    results: list[str] = []
    all_ok = True
    for tenor, symbol in tenors.items():
        try:
            frame = client.fetch_series(
                provider=provider,
                endpoint=endpoint,
                params={"symbol": symbol, "start_date": start},
                series_label=f"{entry_key}.{tenor}",
            )
            latest = float(frame.iloc[-1]["value"])
            ok_tenor = TENOR_PLAUSIBILITY[0] <= latest <= TENOR_PLAUSIBILITY[1]
            all_ok &= ok_tenor
            results.append(f"{tenor}={latest:.3f}{'' if ok_tenor else ' !!'}")
        except OpenBBFetchError:
            all_ok = False
            results.append(f"{tenor}=FAILED")
    return all_ok, " | ".join(results)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("fields", nargs="*", help="Registry field names to check (default: all)")
    parser.add_argument("--list", action="store_true", help="List registry entries and exit")
    parser.add_argument(
        "--provider-only",
        action="store_true",
        help="Skip the local-API path, use the package directly",
    )
    args = parser.parse_args()

    registry = get_registry()

    if args.list:
        print(f"{'field':<24}{'provider':<12}{'symbol':<34}status")
        print("-" * 88)
        for name, entry in sorted(registry.series.items()):
            symbol = entry.symbol or f"{len(entry.tenors or {})} tenors"
            print(f"{name:<24}{entry.provider:<12}{symbol:<34}{entry.status}")
        if registry.blocked:
            print("\nBLOCKED (no reachable source — Loophole Ledger, Section 21.4):")
            for blocked in registry.blocked:
                print(f"  {blocked.field:<26} {blocked.reason.strip()[:70]}")
        return 0

    targets = args.fields or sorted(registry.series)
    unknown = [f for f in targets if f not in registry.series]
    if unknown:
        print(f"Unknown registry field(s): {unknown}")
        print("Run with --list to see available fields.")
        return 1

    config = OpenBBClientConfig(use_local_api_first=not args.provider_only)
    client = OpenBBClient(config)
    print(f"Checking {len(targets)} series route(s). started {utc_now().isoformat()}")
    print(f"Local API first: {config.use_local_api_first} ({config.local_api_base_url})")
    print("-" * 100)

    failures: list[str] = []
    with client:
        for name in targets:
            entry = registry.series[name]
            provider = entry.provider
            endpoint = entry.endpoint or str(
                registry.defaults.get("endpoint", "economy.fred_series")
            )
            if entry.tenors:
                ok, detail = check_curve(name, entry.tenors, provider, endpoint, client)
            else:
                ok, detail = check_simple(
                    name,
                    str(entry.symbol),
                    provider,
                    endpoint,
                    client,
                    bounds=entry.plausible_range or (None, None),
                )
            marker = "OK  " if ok else "FAIL"
            print(f"[{marker}] {name:<22} {detail}")
            if not ok:
                failures.append(name)

    print("-" * 100)
    print(f"{len(targets) - len(failures)}/{len(targets)} verified.")
    if failures:
        print(f"FAILED: {failures}")
        print(
            "\nFor each failure: confirm the symbol exists at the provider, check whether "
            "the local API is running (openbb-api), and try --provider-only to isolate "
            "which path is broken. Do NOT mark a route 'verified' until it passes."
        )
        return 1
    print(
        "\nAll routes returned plausible data. "
        "Update status: verified in config/series_registry.yaml."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
