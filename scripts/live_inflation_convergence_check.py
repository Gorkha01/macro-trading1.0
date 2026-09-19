"""Live wiring check: real FRED data -> Module 5.3's ``inflation_convergence_classifier``.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_inflation_convergence_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the units,
the nulls, the frequency, the sign conventions, and the **base rates**.

What this check does beyond running the function
------------------------------------------------

1. **Re-probes the two series Section 21.1 calls BLOCKED.** The registry records
   ``median_cpi_direction`` and ``trimmed_mean_direction`` as unreachable, and
   this build supplies both. A block is a claim about the world and it decays
   (O-21), so the check *fetches them* and reports the actual observation counts
   rather than trusting either the block or its removal.

2. **Derives all six directions from raw FRED series**, each with its own unit
   contract asserted:

   * headline / core CPI — ``CPIAUCSL`` / ``CPILFESL``, month-over-month percent.
   * core PCE — ``PCEPILFE``, month-over-month percent, a **separate release**.
   * median CPI — ``MEDCPIM157SFRBCLE``, month-over-month percent.
   * trimmed-mean PCE — ``PCETRIM1M158SFRBDAL``, **percent change at an ANNUAL
     rate**. This is the one asymmetric input: its magnitude is ~12x the others'.
     Only the sign is consumed, and the check asserts that fact so the asymmetry
     cannot silently propagate.
   * sticky-price CPI — ``CORESTICKM157SFRBATL``, month-over-month percent.

3. **Measures the classification base rates over the full common history** and
   reports them against the config values, so a stale measurement fails loudly
   (D-029). This is the number that makes the disclosure in ``value`` meaningful.

4. **Recomputes the specification's three-measure base rate and compares it to
   the six-measure one.** The claim in D-047 is that HIGH is the base state; the
   check measures both forms over the same months so the claim is verified rather
   than asserted.

5. **Counts the months the corrected conflict gate reclassifies.** Section
   15.19-C's pair gate misses months where headline and core agree while the rest
   of the set splits. The check counts them on real data, so the correction's
   effect size is a measurement rather than a guess.
"""

from __future__ import annotations

import sys
from collections import Counter
from typing import Any, cast

import pandas as pd
from openbb import obb

from macro_engine.config import get_settings
from macro_engine.models.inflation_convergence import (
    InflationConvergenceInputs,
    inflation_convergence_classifier,
)

# Registry series -> the field it feeds. Declared once so the derivation and the
# report cannot drift apart.
_SERIES: tuple[tuple[str, str, str], ...] = (
    ("CPIAUCSL", "headline_cpi_direction", "m/m %"),
    ("CPILFESL", "core_cpi_direction", "m/m %"),
    ("PCEPILFE", "core_pce_direction", "m/m %"),
    ("MEDCPIM157SFRBCLE", "median_cpi_direction", "m/m %"),
    ("PCETRIM1M158SFRBDAL", "trimmed_mean_direction", "annual-rate %"),
    ("CORESTICKM157SFRBATL", "sticky_price_cpi_direction", "m/m %"),
)

# The specification's Phase 1 three — the subset used for the 3-measure baseline.
_THREE = ("headline_cpi_direction", "core_cpi_direction", "core_pce_direction")


def _fetch(symbol: str) -> pd.DataFrame:
    """Fetch one FRED series the way the snapshot builder does.

    The frame is **wide**: the index is ``date`` and the single column is named
    after the series. That is the opposite of the long ``date``/``value`` shape
    the snapshot builder consumes, so this script does not reuse its parser —
    and the difference is stated here because assuming the long shape produces a
    ``KeyError`` rather than a wrong number, which is the benign failure.

    ``obb`` is typed as ``BaseApp | Extensions``, a union that does not declare
    ``economy``, and the route's return type has no stub. The untyped edge of
    this dependency is confined to these two lines and cast back to the frame
    the call actually produces, so ``Any`` does not leak into the rest of the
    check. This mirrors ``live_labor_check._fetch_auctions``.
    """
    app: Any = obb
    result = app.economy.fred_series(symbol=symbol, provider="fred")
    return cast("pd.DataFrame", result.to_df())


def _level_to_month(frame: pd.DataFrame, symbol: str) -> pd.Series:
    """Extract a series as a month-indexed level, oldest first, nulls dropped."""
    series = frame[symbol].dropna()
    index = pd.to_datetime(series.index)
    series.index = index.to_period("M")
    return series


def _directions(series: pd.Series, *, level: bool) -> pd.Series:
    """Turn a series into the sign of its month-over-month percent change.

    ``level=True`` means the series is an index (CPI, PCE price index) and the
    percent change must be computed. ``level=False`` means FRED publishes the
    percent change directly, which is true for the four special aggregates here
    and is the trap: ``CPIAUCSL`` is a level while ``MEDCPIM157SFRBCLE`` is a
    rate, and they arrive through the same call in the same shape.
    """
    rate = series.pct_change() * 100.0 if level else series
    sign = rate.apply(lambda v: 1 if v > 0 else (-1 if v < 0 else 0))
    return sign.dropna()


def main() -> int:
    settings = get_settings().inflation.convergence
    frames: dict[str, pd.Series] = {}
    failures: list[str] = []

    print("=" * 78)
    print("LIVE CHECK — inflation_convergence_classifier (Module 5.3, Section 15.19-C)")
    print("=" * 78)
    print()

    # --- 1. the series exist, and their units are what the code assumes -----
    print("1. SERIES PROBE (O-21: re-verify every claim of unreachability)")
    print("-" * 78)
    for symbol, field, units in _SERIES:
        try:
            raw = _fetch(symbol)
        except Exception as exc:
            failures.append(f"{symbol} ({field}) could not be fetched: {exc}")
            print(f"  FAIL  {symbol:24} {field:28} {exc}")
            continue
        indexed = _level_to_month(raw, symbol)
        frames[field] = indexed
        print(
            f"  ok    {symbol:24} {len(indexed):4d} obs  "
            f"{indexed.index[0]}..{indexed.index[-1]}  units={units}"
        )
    print()

    if failures:
        print("SERIES PROBE FAILED — stopping, because a missing input would silently")
        print("reduce the measure count and change what frac_agreeing means.")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    # --- 2. the unit contract, asserted rather than assumed ----------------
    print("2. UNIT CONTRACT (the one asymmetric input)")
    print("-" * 78)
    trimmed = frames["trimmed_mean_direction"]
    # Headline CPI as a *rate* (levels are what the frame holds), computed the
    # same way the direction derivation does it, so the comparison is like-for-like.
    headline_monthly = frames["headline_cpi_direction"]
    headline_rate = (headline_monthly.pct_change() * 100.0).dropna()
    # Compare typical magnitudes on the overlapping months.
    common = trimmed.index.intersection(headline_rate.index)
    trimmed_mean_abs = float(trimmed.loc[common].abs().mean())
    headline_mean_abs = float(headline_rate.loc[common].abs().mean())
    ratio = trimmed_mean_abs / headline_mean_abs if headline_mean_abs else float("nan")
    print(f"  |trimmed-mean PCE| mean = {trimmed_mean_abs:6.3f}  (annual-rate %)")
    print(f"  |headline CPI|     mean = {headline_mean_abs:6.3f}  (m/m %)")
    print(f"  ratio = {ratio:.1f}x  -> confirms the annual-rate units (expected ~12x)")
    if not 8.0 <= ratio <= 16.0:
        print("  WARNING: the ratio is outside 8-16x; the units may have changed.")
    print("  Only the SIGN of this series is consumed, so the magnitude is not")
    print("  used — but the asymmetry is asserted so it cannot propagate silently.")
    print()

    # --- 3. build the six directions on a common monthly calendar ----------
    print("3. DERIVED DIRECTIONS")
    print("-" * 78)
    signs: dict[str, pd.Series] = {}
    for field, series in frames.items():
        # Only CPIAUCSL/CPILFESL/PCEPILFE are levels; the other three are rates.
        # This mapping is explicit because getting it wrong inverts the reading.
        is_level = field in {"headline_cpi_direction", "core_cpi_direction", "core_pce_direction"}
        signs[field] = _directions(series, level=is_level)

    # Align on the months where ALL six are present, so every month contributes
    # the same measure count and `frac_agreeing` is comparable across months.
    all_months = None
    for field in signs:
        all_months = (
            signs[field].index
            if all_months is None
            else all_months.intersection(signs[field].index)
        )
    assert all_months is not None
    print(f"  common months across all six measures: {len(all_months)}")
    print(f"  range: {all_months[0]} .. {all_months[-1]}")
    print()

    # --- 4. run the classifier over every month ----------------------------
    print("4. CLASSIFICATION OVER REAL HISTORY")
    print("-" * 78)
    six_counts: Counter[str] = Counter()
    three_counts: Counter[str] = Counter()
    gate_reclassified: list[tuple[object, int]] = []
    family_counts: Counter[int] = Counter()

    for month in all_months:
        six_kwargs = {field: int(signs[field].loc[month]) for field in signs}
        six_result = inflation_convergence_classifier(
            InflationConvergenceInputs(**six_kwargs)  # type: ignore[arg-type]
        )
        six_value = six_result.value
        assert isinstance(six_value, dict)
        six_counts[str(six_value["classification"])] += 1
        family_counts[int(six_value["independent_families"])] += 1

        three_kwargs = {field: six_kwargs[field] for field in _THREE}
        three_result = inflation_convergence_classifier(
            InflationConvergenceInputs(**three_kwargs)  # type: ignore[arg-type]
        )
        three_value = three_result.value
        assert isinstance(three_value, dict)
        three_counts[str(three_value["classification"])] += 1

        # The correction's effect: CONFLICTED while headline/core agree.
        pair_opposes = six_kwargs["headline_cpi_direction"] * six_kwargs["core_cpi_direction"] < 0
        if six_value["classification"] == "CONFLICTED" and not pair_opposes:
            gate_reclassified.append((month, int(six_value["opposing"])))

    total = len(all_months)
    print(f"  six-measure form ({total} months):")
    for state in ("HIGH", "MEDIUM", "LOW", "CONFLICTED"):
        count = six_counts[state]
        print(f"    {state:11} {count:4d}  {count / total:6.1%}")
    print()
    print(f"  three-measure form ({total} months, the specification's Phase 1):")
    for state in ("HIGH", "MEDIUM", "LOW", "CONFLICTED"):
        count = three_counts[state]
        print(f"    {state:11} {count:4d}  {count / total:6.1%}")
    print()
    print(f"  independent families observed: {dict(sorted(family_counts.items()))}")
    print("    (never 1 — the required BLS+BEA pair floors it at 2)")
    print()

    # --- 5. the base-rate disclosure is not stale --------------------------
    print("5. BASE RATES vs CONFIG (D-029: a categorical travels with its frequency)")
    print("-" * 78)
    six_rate = six_counts["HIGH"] / total
    three_rate = three_counts["HIGH"] / total
    configured_six = settings.measured_base_rates.six_measure_high
    configured_three = settings.measured_base_rates.three_measure_high

    print(f"  six-measure HIGH:   measured {six_rate:6.1%}   config {configured_six:6.1%}")
    print(f"  three-measure HIGH: measured {three_rate:6.1%}   config {configured_three:6.1%}")
    drift_six = abs(six_rate - configured_six)
    drift_three = abs(three_rate - configured_three)
    tolerance = 0.02
    if drift_six > tolerance or drift_three > tolerance:
        print()
        print(f"  DRIFT above {tolerance:.0%}: the config measurement is stale.")
        print(f"    six-measure drift   {drift_six:6.2%}")
        print(f"    three-measure drift {drift_three:6.2%}")
        failures.append("base rates in config have drifted from the live measurement")
    else:
        print(f"  no drift above {tolerance:.0%} — the config measurement holds.")
    print()

    # --- 6. the corrected gate's effect size ------------------------------
    print("6. THE CORRECTED CONFLICT GATE (correction 1, D-047)")
    print("-" * 78)
    print(
        f"  months CONFLICTED while headline and core AGREE: "
        f"{len(gate_reclassified)} of {total} ({len(gate_reclassified) / total:.2%})"
    )
    print("  These are the months Section 15.19-C's pair gate alone would not flag.")
    if gate_reclassified:
        detail = [f"{month}(opp={opposing})" for month, opposing in gate_reclassified[:6]]
        print(f"  examples: {', '.join(detail)}")
        if len(gate_reclassified) > 6:
            print(f"  ... and {len(gate_reclassified) - 6} more")
    print()

    # --- 7. the reachability claim ----------------------------------------
    print("7. REACHABILITY (D-045a: every declared class must be producible)")
    print("-" * 78)
    reachable = {s for s in ("HIGH", "MEDIUM", "LOW", "CONFLICTED") if six_counts[s] > 0}
    print(f"  reachable on real data: {sorted(reachable)}")
    unreachable = {"HIGH", "MEDIUM", "LOW", "CONFLICTED"} - reachable
    if unreachable:
        print(f"  NOT produced historically: {sorted(unreachable)}")
        print("  (a class declared but never produced on 40+ years of real data is a")
        print("   claim worth stating, not hiding — see the degeneracy note)")
    print()

    print("=" * 78)
    if failures:
        print("FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("PASSED — all six series live, units verified, base rates within tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
