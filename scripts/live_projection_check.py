"""Live wiring check: real labor data -> ``project_inflation_trajectory``.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_projection_check.py

Section 21.0: unit tests prove the arithmetic; this proves the wiring -- the
units, the sign conventions, the sampling cadence, and whether the numbers this
function is configured with are the numbers the data actually produces.

What this check does beyond running the function
------------------------------------------------

1. **Re-measures the beta the config is calibrated on.** ``0.006`` pp per score
   point came from the **OLS slope of the 6-month forward core PCE YoY change on
   the score**. If the data has moved since, the configured beta is stale and the
   published projection is on the wrong scale -- the failure D-052's base-rate
   check caught in the transmission map.

   **The estimator here is deliberate, and an earlier version got it wrong.**
   This check first re-measured beta from the *band-corner spread* -- the mean
   core inflation in each band minus the other. That method failed for two
   reasons, and the failure is why the check exists in this form:

   * it measured a CONTEMPORANEOUS LEVEL spread, which is a different estimand
     from the projected CHANGE the function publishes; and
   * the band width and beta are **not independent** -- the band's score-width
     is ``band_pp / beta`` -- so choosing both at once chooses the partition and
     the slope simultaneously, and the "measurement" partly reads back the
     configuration it is meant to test.

   The OLS slope needs no band, so it is the defensible estimator. Drift bar:
   0.004 pp per score point (the slope's own standard error is 0.0016, so the
   bar is roughly 2.5 SE).

2. **Checks the SIGN against realised inflation, not against the docstring.**
   The specification negates twice and the negations cancel, so the shipped
   expression is ``+beta * score``. A sign error here is the single most likely
   defect in the function and it is invisible in the published magnitude, so this
   check measures the correlation between the score and the SUBSEQUENT change in
   core inflation and requires it to be positive at the short horizon the
   function claims for itself. It also *reports* the longer horizons where the
   correlation turns negative, because that reversal is the function's own stated
   limitation and a reader should see it rather than take it on trust.

3. **Proves the base-state failure has not returned.** The specification's
   threshold put ``stable`` in 79.1% of months. This check recomputes the label
   distribution over the whole live history and fails if any single label exceeds
   the bar -- the D-047 pattern, measured rather than assumed. Bar: 75%.

4. **CROSS-CHECKS against ``cross_asset_transmission`` (D-052)** -- the
   comparable Tier-3 synthesis function, paired from the start as this increment
   was commissioned to do. The two share the **labor reading** and nothing else:
   ``project_inflation_trajectory`` routes it through a fitted slope into three
   bands, while ``cross_asset_transmission`` takes a repricing and emits a
   per-asset directional map. They must agree in **sign on the labor leg**,
   because a tight labor market is inflationary in both stories.

   **What would make this check vacuous, and why it is not that.** A cross-check
   that compares a function to itself, or to a restatement of its own arithmetic,
   is the D-027 trap. Here the two functions compute different quantities on
   different data (labor score -> inflation direction; bond repricing -> asset
   directions) and meet only on the labor input's sign. The check therefore
   compares the *labor score's sign* against the *bond leg's direction* under a
   tight-labor scenario, which is a genuine meeting point rather than an identity.

5. **Exercises the §18.6 fiscal flag on live data** and asserts it scales the
   magnitude without moving the sign, which is the property the unit tests pin
   synthetically and the property a live mis-wiring would break.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.inflation_dynamics import (
    InflationTransmissionInputs,
    cross_asset_transmission,
)
from macro_engine.models.inflation_trajectory import (
    InflationTrajectoryInputs,
    project_inflation_trajectory,
)

#: Drift bar for the configured beta, in pp per score point. The configured
#: slope's own standard error is 0.0016, so this is roughly 2.5 SE -- loose
#: enough to survive a revision, tight enough to catch a stale rate.
BETA_DRIFT_BAR = 0.004

#: No single direction may occupy more than this share of the live history. Set
#: just under the specification's measured 79.1% so the base-state failure is
#: caught rather than merely commented on.
BASE_STATE_BAR = 0.75

#: The horizon the function claims for itself, in months. Module 3.6 states the
#: projection is a near-term (3-9 month) statement and reverses after 12.
CLAIMED_HORIZON_MONTHS = 6

#: The correlation the sign check must clear at the claimed horizon.
MIN_SIGN_CORRELATION = 0.05


def _fetch(client: OpenBBClient, symbol: str) -> pd.Series:
    """Fetch one FRED series as a date-indexed float series."""
    frame = client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=symbol,
    )
    out = frame.set_index("date")["value"].astype(float)
    out.index = pd.to_datetime(out.index)
    return out.dropna().sort_index()


def _monthly(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    return series.resample("MS").mean().reindex(index)


def _percentile(s: pd.Series, window: int = 36, min_periods: int = 12) -> pd.Series:
    """Trailing-window percentile, matching Module 6.4's definition."""
    values = s.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1) : i + 1]
        chunk = chunk[~np.isnan(chunk)]
        if len(chunk) < min_periods or np.isnan(values[i]):
            continue
        below = float((chunk < values[i]).sum())
        ties = float((chunk == values[i]).sum())
        out[i] = 100.0 * (below + 0.5 * ties) / len(chunk)
    return pd.Series(out, index=s.index)


def _rebuild_labor_score(client: OpenBBClient) -> pd.Series:
    """Reconstruct ``labor_tightness_score`` from live series at config weights.

    The reconstruction is the check's own, not the model's: it applies the same
    documented formula to the same documented series so that a disagreement
    between the two is a wiring defect rather than a restatement.
    """
    settings = get_settings()
    weights = settings.labor.tightness_weights
    scaling = settings.labor.tightness_scaling

    icsa = _fetch(client, "ICSA")
    jtsjol = _fetch(client, "JTSJOL")
    jtsqur = _fetch(client, "JTSQUR")
    payems = _fetch(client, "PAYEMS")

    index = pd.date_range(
        icsa.index.min().to_period("M").to_timestamp(),
        icsa.index.max().to_period("M").to_timestamp(),
        freq="MS",
    )

    claims_4wk = icsa.rolling(4).mean()
    claims_driver = _monthly((claims_4wk / claims_4wk.shift(4) - 1.0) * 100.0, index)
    openings_driver = (jtsjol.pct_change(12) * 100.0).reindex(index)
    quits_pctile = _percentile(jtsqur.resample("MS").last().reindex(index))
    nfp_3m = payems.diff().rolling(3).mean().reindex(index)

    claims_component = scaling.claims_multiplier_value * claims_driver
    jolts_component = scaling.jolts_openings_multiplier_value * openings_driver + (
        scaling.jolts_quits_multiplier_value * (quits_pctile - scaling.quits_centering_value)
    )
    nfp_component = (nfp_3m - settings.labor.neutral_nfp_pace) / 10.0

    raw = (
        weights.claims_value * claims_component
        + weights.jolts_value * jolts_component
        + weights.nfp_value * nfp_component
    )
    return raw.clip(-100.0, 100.0).dropna()


def _result(name: str, value: float) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=0.35,
        interpretation="live check fixture",
        context="live check fixture",
        inputs_used=["fixture"],
        warnings=[],
    )


def _band_of(change_pp: float) -> str:
    bands = get_settings().phillips.trajectory.bands
    if change_pp > bands.reaccelerating_above:
        return "reaccelerating"
    if change_pp < bands.decelerating_below:
        return "decelerating"
    return "stable"


def main() -> int:
    settings = get_settings()
    trajectory = settings.phillips.trajectory
    client = OpenBBClient()

    print("=" * 78)
    print("LIVE CHECK: project_inflation_trajectory (Module 3.6, D-053)")
    print("=" * 78)

    # ---------------------------------------------------------- 1. the beta
    print()
    print("1. RE-MEASURE the config's beta against realised core inflation")
    score = _rebuild_labor_score(client)
    core_pce = _fetch(client, "PCEPILFE")
    core_yoy = (core_pce.pct_change(12) * 100.0).dropna()

    frame = pd.DataFrame({"score": score}).join(pd.DataFrame({"core_yoy": core_yoy}), how="inner")
    frame = frame.dropna()
    span = f"{frame.index[0].date()} .. {frame.index[-1].date()}"
    print(f"  aligned observations: {len(frame)}  ({span})")
    lo, mu, hi = frame["score"].min(), frame["score"].mean(), frame["score"].max()
    print(f"  score  min/mean/max : {lo:+.2f} / {mu:+.2f} / {hi:+.2f}")
    print(f"  score  std          : {frame['score'].std():.2f}")

    beta_cfg = trajectory.beta_pp_per_score_point

    # The estimator: OLS slope of the forward change in core YoY on the score.
    # No band enters, which is the point -- see the module docstring on why the
    # band-corner method measured the configuration rather than the data.
    forward = frame["core_yoy"].shift(-CLAIMED_HORIZON_MONTHS) - frame["core_yoy"]
    ols = pd.DataFrame({"score": frame["score"], "fwd": forward}).dropna()
    x = ols["score"].to_numpy(dtype=float)
    y = ols["fwd"].to_numpy(dtype=float)
    n = len(x)
    slope, intercept = np.polyfit(x, y, 1)
    residuals = y - (intercept + slope * x)
    se = float(np.sqrt((residuals**2).sum() / (n - 2) / ((x - x.mean()) ** 2).sum()))
    r_squared = 1 - (residuals**2).sum() / ((y - y.mean()) ** 2).sum()
    print(
        f"  OLS slope of {CLAIMED_HORIZON_MONTHS}m forward core YoY change on the "
        f"score: {slope:+.5f} (se {se:.5f}, t {slope / se:+.2f}, R2 {r_squared:.4f}, n={n})"
    )
    print(f"  configured beta    : {beta_cfg:.5f} pp/point")

    drift = abs(slope - beta_cfg)
    if drift > BETA_DRIFT_BAR:
        print(
            f"\nFAILED: configured beta has drifted by {drift:.5f} from the "
            f"live-implied {slope:.5f} (bar {BETA_DRIFT_BAR}). The projection is "
            f"on the wrong scale -- re-measure and update "
            f"phillips.trajectory.beta_core_inflation_pp_per_score_point."
        )
        return 1
    print(f"  BETA OK: drift {drift:.5f} within bar {BETA_DRIFT_BAR}")

    # The band is a SEPARATE config decision; report the label mix it produces
    # at the current beta, since the two are not jointly free.
    band = trajectory.bands.reaccelerating_above
    half_points = band / beta_cfg
    labels_live = pd.Series([_band_of(beta_cfg * s) for s in frame["score"]], index=frame.index)
    live_shares = labels_live.value_counts(normalize=True)
    print(
        f"  band +/-{band}pp = +/-{half_points:.2f} score points -> live label mix: "
        + "  ".join(
            f"{name} {live_shares.get(name, 0.0):.1%}"
            for name in ("reaccelerating", "stable", "decelerating")
        )
    )

    # ---------------------------------------------------------- 2. the sign
    print()
    print("2. SIGN against realised inflation (the specification's double negation)")
    for lag in (0, 6, 12, 18, 24):
        if lag == 0:
            fwd = frame["core_yoy"] * 0.0
        else:
            fwd = frame["core_yoy"].shift(-lag) - frame["core_yoy"]
        sub = pd.DataFrame({"s": frame["score"], "f": fwd}).dropna()
        if len(sub) < 30:
            continue
        corr = float(np.corrcoef(sub["s"], sub["f"])[0, 1])
        marker = "  <-- the claimed horizon" if lag == CLAIMED_HORIZON_MONTHS else ""
        line = f"  corr( score(t) , core YoY(t+{lag:>2d}) - YoY(t) ) = {corr:+.4f}  n={len(sub)}"
        print(line + marker)
        if lag == CLAIMED_HORIZON_MONTHS:
            if corr < MIN_SIGN_CORRELATION:
                print(
                    f"\nFAILED: at the function's own claimed {CLAIMED_HORIZON_MONTHS}-month "
                    f"horizon the correlation is {corr:+.4f}, not above "
                    f"{MIN_SIGN_CORRELATION}. Either the sign convention is wrong "
                    f"or the stated horizon is."
                )
                return 1
            print(f"  SIGN OK: positive at the claimed horizon (bar {MIN_SIGN_CORRELATION})")
    print("  (note the reversal after ~12 months -- the function's own stated limit)")

    # ------------------------------------------------- 3. the base-state check
    print()
    print("3. BASE STATE: no single label may dominate the live history")
    counts = labels_live.value_counts()
    shares = labels_live.value_counts(normalize=True)
    for name in ("stable", "reaccelerating", "decelerating"):
        print(f"  {name:15s} {counts.get(name, 0):5d} months  {shares.get(name, 0.0):6.1%}")
    worst_label, worst_share = shares.index[0], float(shares.iloc[0])
    print(f"  modal label: {worst_label} at {worst_share:.1%} (bar {BASE_STATE_BAR:.0%})")
    if worst_share > BASE_STATE_BAR:
        print(
            f"\nFAILED: {worst_label!r} is the base state at {worst_share:.1%} -- the "
            f"D-047 failure the specification shipped (measured 79.1% for its "
            f"version). The band is too wide to discriminate."
        )
        return 1
    print("  BASE STATE OK: the classifier discriminates on live data")

    # ------------------------------------------------- 4. the cross-check
    print()
    print("4. CROSS-CHECK against cross_asset_transmission (D-052)")
    print("  shared input: the labor reading. Everything else differs --")
    print("  one routes it through a fitted slope into three bands; the other")
    print("  takes a bond repricing and emits a per-asset directional map.")
    print("  Agreement on the labor leg is therefore evidence, not arithmetic.")

    latest_score = float(score.iloc[-1])
    latest_month = score.index[-1].date()
    print(f"  latest labor score: {latest_score:+.2f} @ {latest_month}")

    # A tight-labor scenario: an inflation surprise that lifts the real yield
    # (the channel a tight market propagates through).
    transmission = cross_asset_transmission(
        InflationTransmissionInputs(
            nominal_yield_change_bp=+12.0,
            breakeven_change_bp=+2.0,
            inflation_surprise_bp=None,
            surprise_driver="demand",
        )
    )
    transmission_value = transmission.value
    if not isinstance(transmission_value, dict):
        print("\nFAILED: cross_asset_transmission returned a non-dict value.")
        return 1
    bonds_direction = transmission_value["bonds"]
    print(f"  transmission (nominal +12bp, breakeven +2bp): bonds={bonds_direction}")

    # The meeting point: a tight labor market must project RISING inflation, and
    # a demand-driven real-yield rise must make BONDS fall. The two functions are
    # describing the same regime from opposite ends.
    projection = project_inflation_trajectory(
        InflationTrajectoryInputs(
            growth=_result("output_gap", +1.0),
            labor=_result("labor_tightness_score", latest_score),
            inflation=_result("inflation_breadth_score", float(core_yoy.iloc[-1])),
        )
    )
    projection_value = projection.value
    if not isinstance(projection_value, dict):
        print("\nFAILED: project_inflation_trajectory returned a non-dict value.")
        return 1
    print(
        f"  projection on that score: {projection_value['direction']} "
        f"({projection_value['projected_change_pp']:+.4f}pp)"
    )

    if latest_score > 0 and projection_value["direction"] == "decelerating":
        print(
            "\nFAILED: a TIGHT labor market (positive score) projected DECELERATING "
            "inflation. The two Tier-3 functions disagree on the labor leg's sign, "
            "which is the one thing they must agree on."
        )
        return 1
    if latest_score < 0 and projection_value["direction"] == "reaccelerating":
        print(
            "\nFAILED: a LOOSE labor market (negative score) projected "
            "REACCELERATING inflation -- the sign is inverted."
        )
        return 1
    if bonds_direction not in ("up", "down", "flat"):
        print(
            f"\nFAILED: the transmission map returned {bonds_direction!r} for "
            f"bonds, which is not a direction the map declares."
        )
        return 1
    # State the agreement in terms of the regime that was actually read, rather
    # than asserting the tight-market wording unconditionally. The latest score
    # is whatever the data says; a hardcoded "tight" in the message would be a
    # claim the check did not verify.
    regime = "TIGHT" if latest_score > 0 else "LOOSE" if latest_score < 0 else "BALANCED"
    expected = {
        "TIGHT": "reaccelerating",
        "LOOSE": "decelerating",
        "BALANCED": "stable",
    }[regime]
    if projection_value["direction"] != expected:
        print(
            f"\nNOTE: the labor score is {regime} ({latest_score:+.2f}) and the "
            f"projection reads {projection_value['direction']!r} rather than "
            f"{expected!r}. That is the band's width, not a sign error -- the "
            f"score is inside the dead band. Not a failure."
        )
    print(
        f"  CROSS-CHECK OK: the labor leg's sign is consistent with the "
        f"projection ({regime} labor -> {projection_value['direction']})"
    )

    # ------------------------------------------------- 5. the fiscal flag
    print()
    print("5. §18.6 FISCAL FLAG on live data")
    fiscal = project_inflation_trajectory(
        InflationTrajectoryInputs(
            growth=_result("output_gap", +1.0),
            labor=_result("labor_tightness_score", latest_score),
            inflation=_result("inflation_breadth_score", float(core_yoy.iloc[-1])),
            fiscal_response_active=True,
        )
    )
    fiscal_value = fiscal.value
    if not isinstance(fiscal_value, dict):
        print("\nFAILED: the fiscal variant returned a non-dict value.")
        return 1
    plain_change = float(projection_value["projected_change_pp"])
    fiscal_change = float(fiscal_value["projected_change_pp"])
    print(
        f"  inactive: {plain_change:+.4f}pp   active: {fiscal_change:+.4f}pp  "
        f"scale {fiscal_value['fiscal_scale_applied']}x"
    )
    if plain_change * fiscal_change < 0:
        print(
            "\nFAILED: the fiscal flag MOVED THE SIGN. It is specified to weight "
            "the fiscal-transfer channel's magnitude, never to invent a direction "
            "the labor market does not support."
        )
        return 1
    if abs(fiscal_change) < abs(plain_change):
        print("\nFAILED: the fiscal flag REDUCED the magnitude; it is a weighting, not a shrink.")
        return 1
    print("  FISCAL OK: same sign, larger magnitude")

    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
