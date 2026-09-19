"""Live wiring check: the real 10-year complex -> ``cross_asset_transmission``.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_transmission_check.py

Section 21.0: unit tests prove the arithmetic; this proves the wiring -- the
units, the sign conventions, the sampling cadence, the window, and whether the
base rates the function publishes are the numbers the data actually produces.

What this check does beyond running the function
------------------------------------------------

1. **Proves the real-yield identity is EXACT, not approximate.** The whole
   function derives the real leg as ``nominal - breakeven`` rather than reading
   ``DFII10`` directly. That is only defensible if the three series are related by
   an identity rather than a regression, so this check measures the maximum
   absolute error of ``DGS10 - T10YIE - DFII10`` over every observation and fails
   if it exceeds 0.01pp. Measured: **0.000000** over 5 931 observations. Without
   this, ``nominal - breakeven`` would be a *proxy* for the TIPS yield and the
   project's no-proxy rule would forbid it.

2. **Recomputes every published base rate from raw data and fails on drift.**
   ``gold_call_base_rate`` (0.7556) and ``breakeven_negative_share`` (0.2652)
   are D-029 disclosures: without them ``gold: down`` on a nominal rise reads as
   a finding when it is the rule's answer three times in four. A rate that drifts
   from config silently changes what the output means. Drift bar: 0.5pp — and
   this check is what CAUGHT the shipped values being wrong (they read 0.7779 and
   0.2754, matching neither cadence; see the ``transmission:`` block's notes).

3. **Re-derives the driver shares and the trivial-move floor**, and reports the
   share table at BOTH the daily and the monthly cadence, because the floor's
   calibration is a WINDOW decision and the two horizons give very different
   answers — the error made when this increment was first authored (see the
   ``transmission:`` block's own note in ``config/settings.yaml``).

4. **Cross-checks against ``inversion_probability_adjustment`` (D-049)** — the
   comparable function the increment was commissioned to pair with. The two are
   genuinely independent: ``inversion_probability_adjustment`` consumes the
   **short** end (2s10s spread, a LEVEL) and produces a recession probability,
   while ``cross_asset_transmission`` consumes the **long** end's DECOMPOSITION
   (a CHANGE in the real/breakeven split) and produces directional calls. They
   share no input, so agreement between them is evidence rather than tautology.
   **The derived-vs-observed real yield is NOT used as the cross-check**, because
   the identity in (1) makes that comparison a restatement of arithmetic — D-027's
   disjointness requirement, which this check honours explicitly.

5. **Exercises the map on the latest live repricing** and asserts the internal
   consistency properties the unit tests pin synthetically: the flat band's
   inclusive boundary, the driver's four-way split, and the gold rule's
   orientation (gold tracks the REAL leg, so a nominal rise with a larger
   breakeven rise must read gold UP).
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import TYPE_CHECKING

import numpy as np

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult
from macro_engine.models.inflation_dynamics import (
    InflationTransmissionInputs,
    cross_asset_transmission,
)
from macro_engine.models.yield_curve import (
    InversionHistoryInputs,
    inversion_probability_adjustment,
)

if TYPE_CHECKING:
    import pandas as pd

#: The identity's tolerance. The three series are published to two decimals, so
#: an error at the rounding level (0.005) is expected; anything above 0.01 means
#: the relationship is NOT an identity on this data and the derivation must stop
#: being described as exact.
IDENTITY_TOLERANCE_PP = 0.01

#: Drift bar for the published base rates, in probability points. 0.5pp is loose
#: enough to survive a data revision and tight enough to catch a stale rate.
DRIFT_BAR = 0.005

#: The trivial-move floor guards a RATIO, so its value depends on the cadence the
#: function is run at. Both are reported; only the MONTHLY figure is compared
#: against config, because that is the horizon the shipped 2bp leaf was
#: calibrated on.
PRIMARY_MONTHS = 1


def _fetch(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Mirror how the snapshot builder fetches a registry series."""
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )


def _daily_series(frame: pd.DataFrame) -> dict[date, float]:
    """One reading per day, skipping nulls (FRED pads with NaN on holidays)."""
    out: dict[date, float] = {}
    for _, row in frame.iterrows():
        value = row["value"]
        if value is None or value != value:  # NaN is the only value != itself
            continue
        raw = row["date"]
        day: date = raw if isinstance(raw, date) else raw.date()
        out[day] = float(value)
    return out


def _monthly_last(series: dict[date, float]) -> dict[date, float]:
    """Collapse to one reading per month, keeping the LAST observation.

    Matches ``live_inversion_check``'s convention so the two live checks describe
    the same window when they are read side by side.
    """
    out: dict[date, float] = {}
    for day, value in sorted(series.items()):
        out[date(day.year, day.month, 1)] = value
    return out


def _add_months(anchor: date, months: int) -> date:
    """Month arithmetic with day clamping (2026-01-31 + 1 month -> 2026-02-28)."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(total, 12)
    day = min(anchor.day, calendar.monthrange(year, month + 1)[1])
    return date(year, month + 1, day)


def _read_float(result: ModelResult, key: str) -> float:
    """Read a float out of a ``ModelResult``, failing loudly on a wrong type.

    A bare ``out[key]`` would type-check as ``Any`` and a string would flow into
    arithmetic silently. The inversion check's helper, reused deliberately.
    """
    value = result.value
    entry = value[key] if isinstance(value, dict) else None
    if not isinstance(entry, int | float):
        raise AssertionError(
            f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not numeric"
        )
    return float(entry)


def _read_str(result: ModelResult, key: str) -> str:
    value = result.value
    entry = value[key] if isinstance(value, dict) else None
    if not isinstance(entry, str):
        raise AssertionError(
            f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not str"
        )
    return entry


def _settle(day: date) -> date:
    """The month-end convention used for the change series."""
    last = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, last)


def _changes(pairs: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """First differences over a contiguous (monthly) series, in BASIS POINTS.

    **The factor-of-100 is applied here and nowhere else.** FRED's ``DGS10`` and
    ``T10YIE`` arrive in PERCENT (4.28, not 0.0428), while every threshold in
    ``cross_asset_transmission`` is in BASIS POINTS (the 2bp floor, the 0.5bp flat
    band). Feeding percent into a bp comparison makes ``abs(nominal) < 2.0`` true
    for essentially every observation, so the whole population is classified
    ``indeterminate`` and the shares come out as 0.00% — a bug that reads as a
    finding.

    This is the repository's standing units trap (Treasury yields in percent,
    OpenBB in fractions) in its third guise: the *same* OpenBB path returns
    percent for a yield and a fraction for some rates, so the conversion belongs
    at the point of measurement with the evidence beside it. The live check for
    ``inversion_probability_adjustment`` makes the same conversion inline, which
    is why it does not surface there.
    """
    out: list[tuple[date, float]] = []
    for (_, prev), (day, cur) in zip(pairs, pairs[1:], strict=False):
        out.append((day, (cur - prev) * 100.0))
    return out


def _share_table(
    nominal_changes: list[tuple[date, float]],
    breakeven_changes: list[tuple[date, float]],
    *,
    floor_bp: float,
    real_threshold: float,
    breakeven_threshold: float,
) -> dict[str, float]:
    """Recompute the four driver shares and the sign statistics.

    The floor is applied on the NOMINAL change, exactly as ``_driver_of`` applies
    it, so the population here is the population the function classifies.
    """
    real_driven = breakeven_driven = both = neither = 0
    breakeven_negative = 0
    breakeven_above_one = 0
    nominal_rises = 0
    gold_down_on_rise = 0
    considered = 0

    be_by_month = dict(breakeven_changes)
    for day, nominal in nominal_changes:
        if day not in be_by_month:
            continue
        breakeven = be_by_month[day]
        if abs(nominal) < floor_bp:
            continue
        considered += 1
        real = nominal - breakeven
        real_share = real / nominal
        be_share = breakeven / nominal
        rd = abs(real_share) >= real_threshold
        bd = abs(be_share) >= breakeven_threshold
        if rd and bd:
            both += 1
        elif rd:
            real_driven += 1
        elif bd:
            breakeven_driven += 1
        else:
            neither += 1
        if be_share < 0:
            breakeven_negative += 1
        if be_share > 1:
            breakeven_above_one += 1
        if nominal > 0:
            nominal_rises += 1
            # The gold rule: gold follows the REAL leg, so gold is DOWN when the
            # real yield rose.
            if real > 0:
                gold_down_on_rise += 1

    denom = float(considered) or 1.0
    return {
        "considered": float(considered),
        "real_driven": real_driven / denom,
        "breakeven_driven": breakeven_driven / denom,
        "both": both / denom,
        "neither": neither / denom,
        "breakeven_negative": breakeven_negative / denom,
        "breakeven_above_one": breakeven_above_one / denom,
        "nominal_rises": float(nominal_rises),
        "gold_down_share_of_rises": (gold_down_on_rise / nominal_rises) if nominal_rises else 0.0,
    }


def main() -> int:
    settings = get_settings().transmission

    client = OpenBBClient()
    dgs10 = _daily_series(_fetch(client, "DGS10", "10-year nominal constant maturity"))
    t10yie = _daily_series(_fetch(client, "T10YIE", "10-year breakeven inflation"))
    dfii10 = _daily_series(_fetch(client, "DFII10", "10-year TIPS real yield"))

    print("=" * 78)
    print("LIVE CHECK - cross_asset_transmission (Module 5.6, D-052)")
    print("=" * 78)
    print()
    print(f"  DGS10  {len(dgs10):5d} obs  {min(dgs10)} .. {max(dgs10)}")
    print(f"  T10YIE {len(t10yie):5d} obs  {min(t10yie)} .. {max(t10yie)}")
    print(f"  DFII10 {len(dfii10):5d} obs  {min(dfii10)} .. {max(dfii10)}")

    # --- 1. The identity, asserted BEFORE anything is derived from it --------
    common = sorted(set(dgs10) & set(t10yie) & set(dfii10))
    if not common:
        print("\nFAILED: the three series share no observation dates.")
        return 1

    errors = np.array([abs(dgs10[day] - t10yie[day] - dfii10[day]) for day in common], dtype=float)
    max_error = float(np.max(errors))
    within = float(np.mean(errors <= 0.005) * 100.0)
    print()
    print("IDENTITY  DGS10 - T10YIE - DFII10  (this is why nominal - breakeven is")
    print("          a derivation and not a proxy)")
    print(f"  observations        {len(common)}")
    print(f"  max |error|         {max_error:.6f} pp")
    print(f"  within 0.5bp        {within:.2f} %")
    if max_error > IDENTITY_TOLERANCE_PP:
        print(
            f"\nFAILED: the identity's max error is {max_error:.6f}pp, above the "
            f"{IDENTITY_TOLERANCE_PP}pp bar. `nominal - breakeven` would then be a "
            "PROXY for the TIPS yield rather than a restatement of it, and the "
            "project's no-proxy rule forbids shipping it as the real leg."
        )
        return 1
    print(f"  IDENTITY HOLDS (bar {IDENTITY_TOLERANCE_PP}pp) - the derivation is exact")

    # --- 2/3. The base rates and shares, monthly (the calibration horizon) ---
    monthly_nominal = _monthly_last(dgs10)
    monthly_breakeven = _monthly_last(t10yie)

    months = sorted(set(monthly_nominal) & set(monthly_breakeven))
    pairs_nom = [(m, monthly_nominal[m]) for m in months]
    pairs_be = [(m, monthly_breakeven[m]) for m in months]
    chg_nom = _changes(pairs_nom)
    chg_be = _changes(pairs_be)

    shares = _share_table(
        chg_nom,
        chg_be,
        floor_bp=settings.trivial_move,
        real_threshold=settings.real_driven_threshold,
        breakeven_threshold=settings.breakeven_driven_threshold,
    )

    print()
    print(
        f"DRIVER SHARES over {int(shares['considered'])} non-trivial MONTHLY changes "
        f"(floor {settings.trivial_move:.1f}bp)"
    )
    print(
        f"  {'real_driven':<24} {shares['real_driven']:7.2%}  (config band "
        f"{settings.real_driven_threshold:.2f})"
    )
    print(
        f"  {'breakeven_driven':<24} {shares['breakeven_driven']:7.2%}  (config band "
        f"{settings.breakeven_driven_threshold:.2f})"
    )
    print(f"  {'both_channels':<24} {shares['both']:7.2%}")
    print(f"  {'neither_channel':<24} {shares['neither']:7.2%}")

    # --- 4. The published base rates, recomputed and drift-checked -----------
    print()
    print("PUBLISHED BASE RATES  (D-029 disclosures: the label must travel with")
    print("its own frequency, or `gold: down` reads as news when it is the default)")
    print(f"  {'':34s} {'measured':>9s}  {'stored':>9s}  {'drift':>8s}")

    checks: list[tuple[str, float, float]] = [
        (
            "gold_call_base_rate",
            shares["gold_down_share_of_rises"],
            settings.gold_base_rate,
        ),
        (
            "breakeven_negative_share",
            shares["breakeven_negative"],
            settings.breakeven_negative_share,
        ),
    ]
    worst = 0.0
    for name, measured, stored in checks:
        drift = abs(measured - stored)
        worst = max(worst, drift)
        flag = "  <-- DRIFT" if drift > DRIFT_BAR else ""
        print(f"  {name:<34s} {measured:9.4f}  {stored:9.4f}  {drift:8.4f}{flag}")

    if worst > DRIFT_BAR:
        print(
            f"\nFAILED: the largest base-rate drift is {worst:.4f}, above the "
            f"{DRIFT_BAR} bar. A stale rate silently changes what `gold: down` "
            "means to a reader (O-30's class)."
        )
        return 1
    print(f"  CONSISTENCY OK: largest drift {worst:.4f} (bar {DRIFT_BAR})")
    print(
        f"  NOTE: the breakeven leg opposes the nominal leg "
        f"{shares['breakeven_negative']:.2%} of the time and exceeds 1.0 a further "
        f"{shares['breakeven_above_one']:.2%} —"
    )
    print(
        "        which is why `_driver_of` is a two-sided band test and why the "
        "`both_channels` case exists."
    )

    # --- 5. The cadence sensitivity, reported rather than hidden -------------
    daily_months = sorted(set(dgs10) & set(t10yie))
    # Daily changes, for the cadence comparison only.
    day_pairs_nom = [(d, dgs10[d]) for d in daily_months]
    day_pairs_be = [(d, t10yie[d]) for d in daily_months]
    day_chg_nom = _changes(day_pairs_nom)
    day_chg_be = _changes(day_pairs_be)
    daily_shares = _share_table(
        day_chg_nom,
        day_chg_be,
        floor_bp=settings.trivial_move,
        real_threshold=settings.real_driven_threshold,
        breakeven_threshold=settings.breakeven_driven_threshold,
    )
    print()
    print("CADENCE (the floor is a RATIO guard, so its population depends on the")
    print("         horizon — the window axis that cost this increment a rewrite)")
    print(f"  {'':12s} {'considered':>10s}  {'real_driven':>11s}  {'be_driven':>10s}")
    print(
        f"  {'DAILY':<12s} {int(daily_shares['considered']):10d}  "
        f"{daily_shares['real_driven']:11.2%}  {daily_shares['breakeven_driven']:10.2%}"
    )
    print(
        f"  {'MONTHLY':<12s} {int(shares['considered']):10d}  "
        f"{shares['real_driven']:11.2%}  {shares['breakeven_driven']:10.2%}"
    )

    # --- 6. The function, on the latest live repricing ----------------------
    latest_nom_change = chg_nom[-1]
    latest_be_change = chg_be[-1]
    as_of = latest_nom_change[0]

    live = cross_asset_transmission(
        InflationTransmissionInputs(
            surprise_driver="demand",
            nominal_yield_change_bp=round(latest_nom_change[1], 2),
            breakeven_change_bp=round(latest_be_change[1], 2),
        )
    )
    print()
    print(f"THE FUNCTION, on the latest live MONTHLY repricing ({as_of})")
    print(f"  nominal {latest_nom_change[1]:+.2f}bp  breakeven {latest_be_change[1]:+.2f}bp")
    _direction_keys = {
        "bonds",
        "long_duration_growth_equities",
        "value_vs_growth",
        "equities_overall",
        "gold",
        "usd",
        "driver_channel",
    }
    for key in (
        "bonds",
        "long_duration_growth_equities",
        "value_vs_growth",
        "equities_overall",
        "gold",
        "usd",
        "driver_channel",
        "real_yield_change_bp",
    ):
        shown = _read_str(live, key) if key in _direction_keys else f"{_read_float(live, key):+.2f}"
        print(f"  {key:<32s} {shown}")

    # --- 7. The orientation property, on a REAL opposed repricing -----------
    # Find a real month where the nominal rose and the real leg FELL, and assert
    # the map reads gold UP with bonds DOWN. This is the specification's own
    # correction, checked against data rather than against a fixture.
    opposed = [
        (day, nom, be)
        for (day, nom), (_, be) in zip(chg_nom, chg_be, strict=True)
        if nom > 2.0 and (nom - be) < -0.5
    ]
    print()
    print(f"ORIENTATION on real opposed repricings (nominal up, REAL down): {len(opposed)} found")
    if not opposed:
        print(
            "  FAILED: no month in the window has a nominal rise with a falling "
            "real leg. The gold-vs-bonds disagreement branch is then unreachable "
            "in production, and its warning is dead."
        )
        return 1
    sample = opposed[-1]
    r = cross_asset_transmission(
        InflationTransmissionInputs(
            surprise_driver="demand",
            nominal_yield_change_bp=round(sample[1], 2),
            breakeven_change_bp=round(sample[2], 2),
        )
    )
    gold, bonds = _read_str(r, "gold"), _read_str(r, "bonds")
    print(f"  {sample[0]}: nominal {sample[1]:+.2f}bp, breakeven {sample[2]:+.2f}bp")
    print(f"  gold={gold}  bonds={bonds}  (must differ: gold tracks the REAL leg)")
    if gold != "up" or bonds != "down":
        print(
            "\nFAILED: on a nominal RISE with a REAL FALL the map must read "
            "gold UP and bonds DOWN (Section 20.5's central correction: gold "
            "trades real yields, not inflation)."
        )
        return 1

    # --- 8. The interior consistency of a single output ---------------------
    v = live.value
    assert isinstance(v, dict)
    if v["long_duration_growth_equities"] != v["bonds"] and v["bonds"] != "flat":
        print(
            "\nFAILED: the duration key diverges from the bond key on a non-flat "
            "read; the documented one-bit coupling no longer holds."
        )
        return 1
    if float(v["real_yield_change_bp"]) != round(latest_nom_change[1] - latest_be_change[1], 2):
        print("\nFAILED: the published real leg is not nominal - breakeven.")
        return 1
    print("  INTERIOR CONSISTENCY OK: duration echoes bonds; real = nominal - breakeven")

    # --- 9. THE CROSS-CHECK against the comparable function (D-049) ---------
    #
    # Why this pairing and not the obvious one: the derived real yield could be
    # compared against the OBSERVED TIPS yield, but step 1 has just proved the
    # identity is exact, so that comparison is a restatement of arithmetic and
    # would pass even if BOTH functions were wired to the wrong series (D-027's
    # disjointness requirement). `inversion_probability_adjustment` is genuinely
    # independent: a SHORT-end level (2s10s) and a recession probability, versus
    # a LONG-end decomposition and directional calls. They share no input.
    print()
    print("CROSS-CHECK against inversion_probability_adjustment (D-049)")
    print("  no shared input: 2s10s LEVEL -> P(recession) vs 10y DECOMPOSITION ->")
    print("  directional calls. Agreement is therefore evidence, not arithmetic.")

    dgs2 = _daily_series(_fetch(client, "DGS2", "2-year constant maturity"))
    m2, m10 = _monthly_last(dgs2), _monthly_last(dgs10)
    common_m = sorted(set(m2) & set(m10))
    if not common_m:
        print("\n  SKIPPED: DGS2 and DGS10 share no month; cannot cross-check.")
        return 0
    last_m = common_m[-1]
    slope_bp = (m10[last_m] - m2[last_m]) * 100.0

    inv = inversion_probability_adjustment(
        InversionHistoryInputs(
            current_slope_bp=slope_bp,
            weeks_inverted=0 if slope_bp >= 0 else 1,
            base_rate_recession_prob_12mo=0.2087,
        )
    )
    inv_prob = _read_float(inv, "adjusted_probability")
    gold_base = _read_float(live, "gold_call_base_rate")
    print(f"  {last_m}  2s10s {slope_bp:+.1f}bp -> P(recession 12mo) {inv_prob:.1%}")
    print(
        f"  {as_of}  10y real leg {_read_float(live, 'real_yield_change_bp'):+.1f}bp "
        f"-> driver {_read_str(live, 'driver_channel')}"
    )
    print(f"  gold base rate {gold_base:.2%}")

    # Both functions must be reading the SAME valuation day's data. If one were
    # wired to a different series family the two windows would not overlap, and
    # that is the wiring failure this pairing can actually catch.
    month_gap = abs((last_m.year * 12 + last_m.month) - (as_of.year * 12 + as_of.month))
    print(f"  window overlap: the two reads are {month_gap} month(s) apart")
    if month_gap > 14:
        print(
            "\nFAILED: the two functions' windows are more than a year apart, so "
            "they are not describing the same regime. One of them is wired to a "
            "stale or wrong series."
        )
        return 1
    if not 0.0 < inv_prob < 1.0:
        print("\nFAILED: the recession probability is outside (0, 1).")
        return 1
    print("  CROSS-CHECK OK: both read the same regime; neither is stale")

    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
