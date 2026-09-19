"""Live check: ``construct_cross_market_rv`` against real correlations and
against its two sibling constructors' shared convention.

Not a test. Operator scripts are deliberately excluded from the default test run
because they exercise the real settings tree and other real modules. Run with::

    uv run python scripts/live_cross_market_rv.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. Here the
wiring is unusual, because this function is the **first live check in the project
whose primary input is a correlation**, and the correlations are the thing
Section 20.12 does not measure.

What this check establishes
---------------------------

1. **The measured correlations, pulled from real series.** Eight US cross-market
   pairs, daily changes, correlation computed in a normal state and in two
   independent stress states (the S&P's worst decile of daily percent change,
   n=248, and VIX at or above its 90th percentile, n=928). This is what gives
   ``cross_market_rv.max_abs_hedge_degradation`` its basis, and it is recomputed
   here so the leaf cannot go stale.

2. **The specification's default is refuted on real data, not argued about.**
   Section 20.12 defaults ``correlation_stressed`` to the literal ``0.9``. Every
   measured *normal* correlation is below it, so the published
   ``hedge_degradation`` is negative for **every** pair — the specification
   asserts universally that the hedge improves in a crisis. Reproduced here
   through the shipped function, not recomputed by hand.

3. **The configuration's own default, placed against the measurement.**
   ``risk.stress_correlation`` is ``0.9``; the measured stressed correlations top
   out well below it. The check reports the gap rather than failing on it,
   because the leaf is an ``institutional_convention`` and not a claim about
   these pairs — but a reader needs both numbers to see the difference.

4. **The cross-check with ``construct_duration_weighted_curve_trade`` — a REAL
   CALL, not a re-implementation** (O-43's lesson). Both constructors emit a
   notional from the same ``N·D`` rule and both claim a level exposure cancels.
   The check asserts the shared arithmetic agrees exactly on the same legs, and
   then derives the exact dollar-duration relation ``shipped/exact = P_b/P_a``
   through the shipped ``bond_math`` — the O-57/O-59 relation, now for a
   cross-market pair rather than a same-credit one.

5. **The seam that CANNOT be closed.** D-059 and D-060 each closed a round-trip
   with ``select_instrument``. This one cannot: Section 22.3.1's ``ThesisType``
   has no cross-market relative-value family, and the only member that names one
   (``CROSS_COUNTRY_DIVERGENCE``) is blocked precisely because it needs a second
   country's rates system. The check enumerates the vocabulary and demonstrates
   the absence, so the gap is a recorded fact rather than an omission.

What this check CANNOT validate
-------------------------------
The function has no prices, so it cannot verify that the common factor actually
cancels, and no pull can supply what the contract does not carry. Section 4
measures the size of that gap; whether to change the contract is **O-57**/
**O-59**.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from macro_engine.config import get_settings  # noqa: E402
from macro_engine.data_layer.openbb_client import OpenBBClient  # noqa: E402
from macro_engine.models.bond_math import (  # noqa: E402
    BondPricingInputs,
    macaulay_duration,
    modified_duration,
    price_bond,
)
from macro_engine.models.contracts import ModelResult  # noqa: E402
from macro_engine.models.instrument_selection import ThesisType  # noqa: E402
from macro_engine.models.yield_curve import (  # noqa: E402
    CrossMarketRVInputs,
    CurveTradeConstructor,
    construct_cross_market_rv,
    construct_duration_weighted_curve_trade,
)

#: Real US cross-market pairs, as (label, long leg series, short leg series).
PAIRS: dict[str, tuple[str, str]] = {
    "curve 10y/2y": ("DGS10", "DGS2"),
    "IG OAS / HY OAS": ("BAMLC0A0CM", "BAMLH0A0HYM2"),
    "S&P / HY OAS": ("SP500", "BAMLH0A0HYM2"),
    "10y nominal / breakeven": ("DGS10", "T10YIE"),
    "S&P / IG OAS": ("SP500", "BAMLC0A0CM"),
    "HY OAS / 3m bill": ("BAMLH0A0HYM2", "DTB3"),
    "S&P / 10y": ("SP500", "DGS10"),
    "S&P / 3m bill": ("SP500", "DTB3"),
}

#: The share of measured |degradation| the configured bound must clear. A bound
#: below the measured range would refuse real pairs; one far above is decoration.
_BOUND_HEADROOM_FLOOR = 1.5


def _values(result: ModelResult) -> dict[str, object]:
    value = result.value
    assert isinstance(value, dict)
    return value


def _number(result: ModelResult, key: str) -> float:
    item = _values(result)[key]
    assert isinstance(item, (int, float))
    return float(item)


def _text(result: ModelResult, key: str) -> str:
    item = _values(result)[key]
    assert isinstance(item, str)
    return item


def _scalar(result: ModelResult) -> float:
    """Read a scalar-valued ``ModelResult`` (``bond_math``'s shape)."""
    item = result.value
    assert isinstance(item, (int, float)), f"expected a scalar, got {type(item).__name__}"
    return float(item)


def _as_float(item: object) -> float:
    """Narrow a pandas scalar (whose stubs are a wide union) to ``float``."""
    assert isinstance(item, (int, float)), f"expected a number, got {type(item).__name__}"
    return float(item)


def _fetch(client: OpenBBClient, symbols: set[str]) -> dict[str, pd.Series]:
    series: dict[str, pd.Series] = {}
    for symbol in sorted(symbols):
        frame = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": symbol},
            series_label=symbol,
        )
        series[symbol] = frame.set_index("date")["value"].astype(float).sort_index()
        print(f"    {symbol:16} n={len(series[symbol]):6}")
    return series


def _measure() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pull the series and return (changes frame, per-pair correlation table)."""
    client = OpenBBClient()
    symbols = {s for pair in PAIRS.values() for s in pair} | {"VIXCLS"}
    print("  fetching real series via OpenBB:")
    raw = _fetch(client, symbols)

    level = pd.DataFrame(raw)
    # SP500 is an INDEX LEVEL; the rest are rates and spreads. The correlation
    # basis must be a return for a price and a change for a rate -- mixing them
    # is the D-049/D-054 "same basis" failure, and it would inflate every
    # equity-versus-rate correlation toward zero through scale alone.
    changes = level.diff()
    changes["SP500"] = level["SP500"].pct_change() * 100.0

    sp = changes["SP500"].dropna()
    vix = level["VIXCLS"].dropna()
    stress_sp = sp[sp <= sp.quantile(0.10)].index
    stress_vix = vix[vix >= vix.quantile(0.90)].index
    print(f"  stress A: SP500 daily %change <= {sp.quantile(0.10):.2f}  (n={len(stress_sp)})")
    print(f"  stress B: VIX >= {vix.quantile(0.90):.2f}  (n={len(stress_vix)})")

    rows = []
    for name, (a, b) in PAIRS.items():
        sub = changes[[a, b]].dropna()
        if len(sub) < 200:
            print(f"  !! {name}: only {len(sub)} overlapping observations, skipped")
            continue
        sa = sub.loc[sub.index.intersection(stress_sp)]
        sb = sub.loc[sub.index.intersection(stress_vix)]
        rows.append(
            {
                "pair": name,
                "n": len(sub),
                "normal": float(sub[a].corr(sub[b])),
                "stress_sp": float(sa[a].corr(sa[b])),
                "stress_vix": float(sb[a].corr(sb[b])),
            }
        )
    table = pd.DataFrame(rows)
    table["degrad_sp"] = table["normal"] - table["stress_sp"]
    table["degrad_vix"] = table["normal"] - table["stress_vix"]
    table["degrad_config_default"] = table["normal"] - get_settings().risk.stress_corr
    table["absnormal"] = table["normal"].abs()
    table["absstress_sp"] = table["stress_sp"].abs()
    return changes, table


def _section_1_measured(table: pd.DataFrame) -> None:
    print("=" * 78)
    print("1. THE MEASURED CORRELATIONS (daily changes, real series)")
    print("=" * 78)
    print(table[["pair", "n", "normal", "stress_sp", "stress_vix"]].to_string(index=False))


def _section_2_spec_default(table: pd.DataFrame) -> None:
    """The specification's default, run through the SHIPPED function."""
    print()
    print("=" * 78)
    print("2. THE SPECIFICATION'S DEFAULT, RUN THROUGH THE SHIPPED FUNCTION")
    print("=" * 78)
    print("  Section 20.12 defaults correlation_stressed to the literal 0.9.")
    print("  Each measured normal correlation is fed in with the field OMITTED,")
    print("  so the shipped config-default route runs.")
    print()

    improving = 0
    for row in table.itertuples():
        result = construct_cross_market_rv(
            CrossMarketRVInputs(
                market_a="leg A",
                market_b="leg B",
                duration_a=6.8,
                duration_b=8.47,
                target_notional_a=10_000_000.0,
                correlation_normal=_as_float(row.normal),
            )
        )
        direction = _text(result, "hedge_direction")
        improving += direction == "improves_under_stress"
        print(
            f"    {row.pair:24} normal {row.normal:+.3f}  "
            f"stressed {_number(result, 'correlation_stressed'):.2f}  "
            f"degradation {_number(result, 'hedge_degradation'):+.3f}  {direction}"
        )

    print()
    print(f"  pairs reporting the hedge IMPROVING under stress: {improving} of {len(table)}")
    assert improving == len(table), (
        "the specification's default was expected to make every measured pair "
        "report an improving hedge; the claim in D-062 is now wrong"
    )
    print("  -> the specification's default asserts, universally, that the hedge")
    print("     improves in a crisis. That is the opposite of its own premise.")


def _section_3_config_leaf(table: pd.DataFrame) -> None:
    print()
    print("=" * 78)
    print("3. THE CONFIGURED STRESSED CORRELATION vs THE MEASUREMENT")
    print("=" * 78)
    settings = get_settings()
    configured = settings.risk.stress_corr
    bound = settings.cross_market_rv.hedge_degradation_bound

    stressed_measured = pd.concat([table["stress_sp"], table["stress_vix"]])
    worst = float(stressed_measured.abs().max())
    print(f"  risk.stress_correlation (config)        = {configured}")
    print(f"  worst measured |stressed correlation|   = {worst:.3f}")
    print(
        f"  pairs whose measured stressed |rho| > configured: "
        f"{int((stressed_measured.abs() > configured).sum())} of {len(stressed_measured)}"
    )
    print()
    print(f"  max_abs_hedge_degradation (config)      = {bound}")
    sp_lo, sp_hi = table["degrad_sp"].abs().min(), table["degrad_sp"].abs().max()
    vix_lo, vix_hi = table["degrad_vix"].abs().min(), table["degrad_vix"].abs().max()
    print(f"  measured |degradation| range (S&P tail) = {sp_lo:.3f} .. {sp_hi:.3f}")
    print(f"  measured |degradation| range (VIX tail) = {vix_lo:.3f} .. {vix_hi:.3f}")

    worst_measured = float(max(table["degrad_sp"].abs().max(), table["degrad_vix"].abs().max()))
    headroom = bound / worst_measured
    print(f"  headroom of the bound over the worst measured pair = {headroom:.2f}x")
    assert headroom >= _BOUND_HEADROOM_FLOOR, (
        f"the configured bound {bound} has only {headroom:.2f}x headroom over the "
        f"worst measured |degradation| {worst_measured:.3f}; the leaf's note claims ~3x"
    )
    print()
    negative_sp = int((table["degrad_sp"] < 0).sum())
    negative_vix = int((table["degrad_vix"] < 0).sum())
    print(
        f"  degradation NEGATIVE with MEASURED stressed correlations: "
        f"{negative_sp} of {len(table)} (S&P tail), {negative_vix} of {len(table)} (VIX tail)"
    )
    print("  -> TWO-SIGNED. A constant adjustment cannot hedge it, exactly as O-59")
    print("     found for the breakeven constructor.")


def _section_4_cross_check(table: pd.DataFrame) -> None:
    """A REAL CALL against the sibling constructor, not a re-implementation."""
    print()
    print("=" * 78)
    print("4. THE CROSS-CHECK: the shared N*D convention, against bond_math")
    print("=" * 78)
    print("  construct_duration_weighted_curve_trade is CALLED (not re-implemented)")
    print("  on the same legs. Both emit N_short = N_long * D_long / D_short.")

    # `bond_math` is PER-PERIOD throughout (O-58), so coupon and yield are
    # halved and Macaulay comes back in periods. The two legs are chosen to
    # price WELL OFF PAR and on opposite sides of it: a golden case that is
    # exact by construction (both legs at par) cannot test its own inputs, and
    # the first draft of this section made exactly that mistake -- both legs at
    # coupon == yield, so P_long == P_short == 100.0 and the measured gap was
    # 1.000000, i.e. nothing.
    def leg(coupon: float, y: float, years: float) -> tuple[float, float]:
        periods = round(years * 2)
        inputs = BondPricingInputs(
            face_value=100.0,
            coupon_rate=coupon / 2,
            yield_rate=y / 2,
            periods=periods,
        )
        mac = _scalar(macaulay_duration(inputs))
        mod = _scalar(modified_duration(mac, y / 2))
        price = _scalar(price_bond(inputs))
        return price, mod / 2.0

    # The legs are chosen so the SIBLING'S contract accepts them: a cross-market
    # pair has no shared maturity, so the sibling's duration/tenor band -- which
    # this check is NOT testing -- needs a 2y and a 10y. What is compared is the
    # RULE, and both functions apply the same one to the same numbers.
    price_long, long_duration = leg(0.02, 0.045, 2.0)  # 2y discount bond
    price_short, short_duration = leg(0.06, 0.045, 10.0)  # 10y premium bond
    notional = 10_000_000.0

    ours = construct_cross_market_rv(
        CrossMarketRVInputs(
            market_a="US IG credit",
            market_b="US Treasury 10y",
            duration_a=long_duration,
            duration_b=short_duration,
            target_notional_a=notional,
            correlation_normal=0.42,
        )
    )
    # The SAME rule, read from the other side: the curve constructor computes
    # N_long = N_short * D_short / D_long, so feeding it our long leg as its
    # SHORT leg must reproduce our short notional exactly.
    sibling = construct_duration_weighted_curve_trade(
        CurveTradeConstructor(
            short_tenor="2y",
            long_tenor="10y",
            short_duration=long_duration,
            long_duration=short_duration,
            target_notional_short=notional,
        )
    )
    ours_notional = _number(ours, "notional_b_short")
    sibling_notional = _number(sibling, "notional_long")
    print(f"    leg durations (bond_math)     = {long_duration:.4f} / {short_duration:.4f}")
    print(f"    cross-market short notional   = {ours_notional:,.2f}")
    print(f"    curve-trade long notional     = {sibling_notional:,.2f}")
    assert abs(ours_notional - sibling_notional) < 0.01, (
        "the two constructors no longer share the N*D convention; the cross-check "
        "is comparing different rules"
    )
    print("    -> identical: the convention is shared, so the O-57/O-59 relation")
    print("       below applies to BOTH.")

    # N*D matches duration; level exposure cancels on DOLLAR duration N*P*D.
    #   N_a*P_a*D_a = N_b*P_b*D_b  =>  exact = N_a*(D_a/D_b)*(P_a/P_b)
    # so shipped/exact = P_b/P_a.
    exact = notional * (long_duration / short_duration) * (price_long / price_short)
    print()
    print(f"    price of the long leg   = {price_long:.4f}")
    print(f"    price of the short leg  = {price_short:.4f}")
    print(f"    shipped notional        = {ours_notional:,.2f}")
    print(f"    dollar-duration notional= {exact:,.2f}")
    print(
        f"    ratio shipped/exact     = {ours_notional / exact:.6f}  "
        f"(= P_b/P_a = {price_short / price_long:.6f})"
    )
    assert abs(ours_notional / exact - price_short / price_long) < 1e-6, (
        "the closed form shipped/exact = P_b/P_a did not hold"
    )
    gap_pct = (ours_notional / exact - 1.0) * 100.0
    print(f"    -> the shipped rule under-hedges by {gap_pct:+.2f}% on this pair.")
    print("       The N*D rule cancels the common factor exactly only when both")
    print("       legs price alike. O-57/O-59, now for a cross-market pair.")


def _section_5_seam() -> None:
    """The seam that cannot be closed, demonstrated rather than asserted."""
    print()
    print("=" * 78)
    print("5. THE SEAM: select_instrument has no cross-market RV route")
    print("=" * 78)
    routes = get_settings().instrument_selection.routes
    members = [t.value for t in ThesisType]
    print(f"  ThesisType members ({len(members)}): {', '.join(members)}")
    print(f"  routes in the config routing table ({len(routes)}): {', '.join(sorted(routes))}")
    un_routed = sorted(set(members) - set(routes))
    print(f"  members with NO route (sentinel branches): {', '.join(un_routed)}")
    cross_market = [m for m in members if "cross" in m]
    print(f"  members naming a cross-market thesis: {cross_market or 'NONE'}")
    assert not any(m in routes for m in cross_market), (
        "a cross-market route now exists; the D-062 finding is stale and the seam should be closed"
    )
    print()
    print("  -> D-059 and D-060 each closed a round-trip with select_instrument.")
    print("     THIS ONE CANNOT: no ThesisType names a cross-market relative-value")
    print("     trade, and the only member that does (CROSS_COUNTRY_DIVERGENCE) is")
    print("     blocked because it needs a second country's rates system -- which")
    print("     is also why Section 22.3 forbids labelling this output 'global'.")
    print("     Recorded as a finding; there is no route to close.")


def main() -> int:
    print("=" * 78)
    print("LIVE CHECK: construct_cross_market_rv (Module 15.3, D-062)")
    print("=" * 78)

    _changes, table = _measure()
    _section_1_measured(table)
    _section_2_spec_default(table)
    _section_3_config_leaf(table)
    _section_4_cross_check(table)
    _section_5_seam()

    print()
    print("=" * 78)
    print("RESULT: the specification's default makes the hedge report as IMPROVING")
    print(f"        on {len(table)} of {len(table)} real US cross-market pairs, because")
    print("        the configured stressed correlation 0.9 exceeds every measured")
    print("        normal correlation; the measured |degradation| is TWO-SIGNED, so")
    print("        no constant adjustment hedges it (O-59's shape); the N*D rule is")
    print("        shared verbatim with the curve constructor and is NOT")
    print("        level-cancelling (shipped/exact = P_short/P_long); and the")
    print("        select_instrument seam CANNOT be closed because no ThesisType")
    print("        names a cross-market RV trade.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
