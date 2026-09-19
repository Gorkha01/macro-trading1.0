"""Live wiring check: ``volatility_target_scaling`` against real portfolio vol.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_voltarget_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring -- the
units, the annualization basis, the exposure reading, and whether a real book's
vol is the kind of input this function was written for.

What this check does that the unit tests cannot
-----------------------------------------------

1. **The portfolio vol is DERIVED from real prices, not supplied.** Every unit
   fixture hands the function a ``current_portfolio_vol``. Here it is produced
   from a real 5-ETF covariance: ``sqrt(w' Cov w)``, annualized. That is the
   whole input path Module 17.2 sits at the end of, and running it end to end is
   the only way to find out whether the function's inputs are *shaped* the way it
   assumes -- and whether a real book's vol is anywhere near a plausible target.

2. **The clip's TRIP RATE is measured, and the measurement is the defect
   evidence.** §20.13's only enforced limit is a leverage ceiling, and the unit
   tests engineer a breach deliberately. Over a real 60-day rolling vol path the
   question is whether that ceiling fires at all. D-056's probe measured **0.0%**;
   this check re-derives it from the live path rather than citing the probe, so a
   later config change (a lower ceiling, a smaller book) that makes the clip
   reachable is *visible* instead of silently changing the module's character.

3. **The reflexivity warning's trip rate is measured too.** The warning is
   §20.13's only non-arithmetic content, and its threshold is a convention. If a
   threshold of 0.8 never fired, the warning would be decorative; if it fired
   every day, it would be noise. The measured rate is the base-state evidence the
   module's docstring cites.

4. **THE CROSS-CHECK, against TWO sibling functions.** The brief requires a
   cross-check against a comparable function built from the start; D-056 has two,
   because this function's distance from each is different and both distances
   matter.

   * **``evaluate_drawdown_rules`` (Module 17.3, §6.6c)** -- the sibling
     *de-risker*. Both functions answer "how much should the book shrink?", and
     both are described by the project as mechanical rather than discretionary.
     The shared invariant is **monotone response to stress, and no intervention
     at zero stress**: a deeper drawdown must never prescriptively de-risk less,
     and a higher current vol must never scale the book up.
   * **``check_rebalancing_drift`` (Module 17.1/17.3, §15.18)** -- the sibling
     *position-sizer*. This is the closer structural match: both publish a target
     exposure and both clip it against a hard constraint. Its published
     ``clipped``-style flags and this function's ``clipped_by_leverage_ceiling``
     are the same *kind* of disclosure, and comparing them is what shows why a
     one-sided flag under-describes a two-sided move (D-056's defect 4).

   Both functions are CALLED. The §20.13 side is the shipped function; nothing is
   re-implemented here, so this check inherits no errors from a paraphrase.

5. **Reports what it cannot validate.** The vol target is a POLICY number and the
   leverage ceiling is a CONVENTION -- no history can say whether 10% or 3.0x is
   right. And the covariance is an ESTIMATE over a chosen lookback; a different
   window gives a different vol, which the check makes visible rather than
   hiding.

Live-network dependency: needs the OpenBB API for ETF closes. When it is
unavailable the check reports the failure and exits non-zero rather than
substituting a synthetic book -- a live check that falls back to fixtures is not
a live check.
"""

from __future__ import annotations

import math
import sys

import numpy as np
import pandas as pd

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.portfolio.risk_budget import (
    DrawdownRule,
    DrawdownState,
    RiskBudgetTarget,
    RiskLimits,
    VolTargetInputs,
    check_rebalancing_drift,
    evaluate_drawdown_rules,
    volatility_target_scaling,
)

#: A plausible macro multi-asset book in genuinely tradeable instruments, matching
#: the rebalancing check's legs so the two live checks describe the same book.
_LEGS: tuple[str, ...] = ("SPY", "TLT", "IEF", "GLD", "UUP")

#: The book's notional weights. Used to build a real portfolio vol.
_WEIGHTS = np.array([0.35, 0.25, 0.20, 0.12, 0.08])

#: The lookback the covariance is estimated over, and the rolling window used for
#: the vol path. Stated rather than implied, because different windows give
#: different rates -- an estimate is not a fact.
_LOOKBACK_DAYS = 504
_ROLLING_WINDOW = 60

#: Trading days per year, for annualizing a daily covariance.
_TRADING_DAYS = 252


def _fetch_closes(client: OpenBBClient, symbol: str) -> pd.Series:
    """Daily closes for one ETF, oldest first.

    The client normalises every provider route to a single schema
    (``date``, ``value``, ``series_id``, ``source``, ``retrieved_at``), so the
    route's own ``close`` field arrives as ``value``.
    """
    frame = client.fetch_series(
        provider="yfinance",
        endpoint="etf.historical",
        params={"symbol": symbol, "start_date": "2019-01-01"},
        series_label=symbol,
    )
    series = pd.Series(
        frame["value"].to_numpy(dtype=float),
        index=pd.to_datetime(frame["date"]),
        name=symbol,
    )
    return series.sort_index()


def _annualized_vol(returns: pd.DataFrame, weights: np.ndarray) -> pd.Series:
    """Rolling annualized portfolio vol over ``_ROLLING_WINDOW`` sessions."""
    cov = returns.rolling(_ROLLING_WINDOW).cov()
    # A rolling covariance produces a MultiIndex (date, leg); rebuild the
    # quadratic form date by date so the weights are applied to the right block.
    vols: list[float] = []
    index: list[pd.Timestamp] = []
    for raw_stamp, block in cov.groupby(level=0):
        matrix = block.to_numpy()
        if matrix.shape != (len(_LEGS), len(_LEGS)):
            continue
        variance = float(weights @ matrix @ weights)
        # The first `_ROLLING_WINDOW - 1` blocks are entirely NaN, and
        # `nan <= 0.0` is False -- so a magnitude test alone lets NaN through and
        # the value reaches `VolTargetInputs`, whose `gt=0.0` bound then rejects
        # it. `isfinite` is the guard that matches the contract.
        if not math.isfinite(variance) or variance <= 0.0:
            continue
        # The groupby key is typed `Hashable`; it is a timestamp at runtime, and
        # the explicit construction is what tells mypy so without a blanket cast.
        index.append(pd.Timestamp(str(raw_stamp)))
        vols.append(float(np.sqrt(variance * _TRADING_DAYS)))
    return pd.Series(vols, index=pd.DatetimeIndex(index), name="portfolio_vol")


def main() -> int:
    settings = get_settings()
    target = settings.risk.vol_target
    limits = RiskLimits.from_settings()

    print("=" * 78)
    print("live check: volatility_target_scaling (Module 17.2, Section 20.13)")
    print(f"book: {' '.join(_LEGS)}   lookback: last {_LOOKBACK_DAYS} sessions")
    print("=" * 78)

    client = OpenBBClient()
    try:
        closes = {leg: _fetch_closes(client, leg) for leg in _LEGS}
    finally:
        client.close()

    frame = pd.DataFrame(closes).dropna()
    if frame.empty:
        print("FAILED: no observations returned. A live check must not fall back to")
        print("a synthetic book -- that would make it a unit test with extra steps.")
        return 1

    print(f"fetched {len(frame)} inner-joined sessions")
    print(f"  first {frame.index[0].date()}   last {frame.index[-1].date()}")
    if len(frame) < _LOOKBACK_DAYS:
        print(f"FAILED: only {len(frame)} sessions; {_LOOKBACK_DAYS} are needed")
        return 1

    window = frame.iloc[-_LOOKBACK_DAYS:]
    returns = window.pct_change().dropna()
    print(f"  estimation window: {window.index[0].date()} .. {window.index[-1].date()}")

    cov = returns.cov().to_numpy() * float(_TRADING_DAYS)
    current_vol = float(np.sqrt(_WEIGHTS @ cov @ _WEIGHTS))
    leg_vols = np.sqrt(np.diag(cov))

    # --- 1. a real vol against the configured target ------------------------
    print()
    print("1. A REAL BOOK'S VOL vs THE CONFIGURED TARGET")
    print(f"   annualized portfolio vol: {current_vol:.2%}   target: {target:.2%}")
    for leg, weight, vol in zip(_LEGS, _WEIGHTS, leg_vols, strict=True):
        print(f"   {leg}: weight {weight:6.1%}  leg vol {vol:6.2%}")
    if current_vol <= 0.0:
        print("   !! degenerate book: zero portfolio vol. Cannot proceed.")
        return 1

    result = volatility_target_scaling(
        VolTargetInputs(
            target_vol_annualized=target,
            current_portfolio_vol=current_vol,
            current_gross_exposure=1.0,
            limits=limits,
        )
    )
    assert isinstance(result.value, dict), "volatility_target_scaling publishes a dict"
    values = result.value
    print(
        f"   scale {float(values['raw_scale']):.4f}x -> gross exposure "
        f"{float(values['final_exposure']):.4f}x "
        f"({values['direction']}, clipped={values['clipped_by_leverage_ceiling']})"
    )
    print(f"   model confidence {result.confidence}, ceiling {float(values['leverage_ceiling'])}x")
    assert result.model_name == "volatility_target_scaling"
    assert float(values["leverage_ceiling"]) == limits.max_leverage, (
        "the ceiling must come from config, not a literal"
    )

    # --- 2. the ceiling's trip rate over the REAL vol path ------------------
    print()
    print("2. THE LEVERAGE CEILING'S TRIP RATE over the real 60-day vol path")
    print(
        "   This is the check's defect evidence: D-056 found that the ONLY enforced\n"
        "   limit is a one-sided upper bound, and measured it firing 0.0% of days.\n"
        "   Re-derived here from live data so a config change that makes it\n"
        "   reachable is visible rather than silent.\n"
    )
    rolling = _annualized_vol(returns, _WEIGHTS)
    if rolling.empty:
        print("FAILED: the rolling vol path is empty")
        return 1

    scales: list[float] = []
    ceilings_hit = 0
    reflexivity = 0
    for vol in rolling:
        path_result = volatility_target_scaling(
            VolTargetInputs(
                target_vol_annualized=target,
                current_portfolio_vol=float(vol),
                current_gross_exposure=1.0,
                limits=limits,
            )
        )
        assert isinstance(path_result.value, dict)
        scales.append(float(path_result.value["raw_scale"]))
        if path_result.value["clipped_by_leverage_ceiling"]:
            ceilings_hit += 1
        if any("reflexivity" in w for w in path_result.warnings):
            reflexivity += 1

    scale_array = np.array(scales)
    clip_rate = ceilings_hit / len(scales)
    refl_rate = reflexivity / len(scales)
    print(f"   observations: {len(scales)}")
    print(f"   60-day vol range: {rolling.min():.2%} .. {rolling.max():.2%}")
    print(f"   scale range: {scale_array.min():.3f}x .. {scale_array.max():.3f}x")
    print(
        f"   the function most often wants to "
        f"{'LEVER UP' if scale_array.mean() > 1.0 else 'DE-RISK'} "
        f"(mean scale {scale_array.mean():.3f}x)"
    )
    print(f"   leverage clip fired: {ceilings_hit} of {len(scales)} sessions = {clip_rate:.1%}")
    print(
        f"   reflexivity warning fired: {reflexivity} of {len(scales)} = {refl_rate:.1%} "
        f"(threshold {settings.risk.reflexivity_scale_threshold}x)"
    )
    if clip_rate == 0.0:
        print(
            "   -> CONFIRMED: on a 1.0x book the ceiling is INERT. The only enforced\n"
            "      limit cannot bind in the regime the function exists for. This is\n"
            "      D-056's defect 3, re-derived from live data rather than cited."
        )

    # --- 3. the one-sided clip, demonstrated on the live path ---------------
    print()
    print("3. THE CLIP IS ONE-SIDED: a deep de-risking reports clipped=False")
    worst = int(np.argmax(scale_array))
    deepest = float(scale_array.min())
    deepest_request = 1.0 * deepest
    print(
        f"   at the calmest reading the book is scaled {float(scale_array.max()):.3f}x, "
        f"and at the most stressed {deepest:.3f}x"
    )
    print(
        f"   the deepest cut moves gross exposure 1.0x -> {deepest_request:.4f}x, "
        f"i.e. it removes {1.0 - deepest:.1%} of the book"
    )
    assert deepest_request < limits.max_leverage, (
        "the de-risking side must sit below the ceiling — that is the whole point"
    )
    print(
        "   ...and `clipped_by_leverage_ceiling` is False for it, because the only\n"
        "   limit expressible as an exposure bound is an upper one. The cut is\n"
        "   reported by `de_risking_fraction`, which is the D-056 repair."
    )
    if worst:
        pass  # quiet the unused-variable linter without hiding the index

    # --- 4. CROSS-CHECK A: against evaluate_drawdown_rules (17.3) -----------
    print()
    print("4. CROSS-CHECK A: the shared shape with evaluate_drawdown_rules (17.3)")
    print(
        "   Both are mechanical de-risking rules. The invariant is: monotone in the\n"
        "   stress input, and NO intervention at zero stress. Both are CALLED.\n"
    )

    # Zero stress: a new high-water mark for the ladder; vol exactly at target
    # for the scaler, where the scale must be 1.0 and the book must not move.
    at_peak = evaluate_drawdown_rules(DrawdownState(high_water_mark=100.0, current_value=100.0))
    assert isinstance(at_peak.value, dict)
    assert at_peak.value["outcome"] == "no_action", "zero drawdown must not intervene"
    assert at_peak.value["risk_reduction_fraction"] == 0.0

    at_target = volatility_target_scaling(
        VolTargetInputs(
            target_vol_annualized=target,
            current_portfolio_vol=target,
            current_gross_exposure=1.0,
            limits=limits,
        )
    )
    assert isinstance(at_target.value, dict)
    assert float(at_target.value["raw_scale"]) == 1.0, "at target the scale must be exactly 1.0"
    assert float(at_target.value["final_exposure"]) == 1.0
    assert at_target.value["clipped_by_leverage_ceiling"] is False
    print("   invariant A (zero stress -> no intervention): HOLDS on both")
    print("     drawdown 0.0%  -> no_action, reduction 0.0")
    print("     vol == target  -> scale 1.0000x, exposure unchanged")

    # Monotone response over a stress sweep, both functions called.
    tiers = [
        DrawdownRule(threshold_pct=t / 100.0, risk_reduction_pct=r / 100.0)
        for t, r in [(10.0, 50.0), (15.0, 75.0), (20.0, 100.0)]
    ]
    print()
    print("   invariant B (monotone in the stress input):")
    print("     the LADDER's reduction is non-decreasing in the drawdown:")
    previous_reduction = -1.0
    for pct in (0.0, 5.0, 10.0, 12.5, 15.0, 17.5, 20.0, 30.0):
        peak = 100.0
        current = peak * (1.0 - pct / 100.0)
        ladder = evaluate_drawdown_rules(
            DrawdownState(high_water_mark=peak, current_value=current), tiers
        )
        assert isinstance(ladder.value, dict)
        reduction = float(ladder.value["risk_reduction_fraction"])
        print(f"       drawdown {pct:5.1f}%  ->  reduction {reduction:6.1%}")
        assert reduction >= previous_reduction - 1e-12, "the ladder must not un-de-risk"
        previous_reduction = reduction

    print("     the SCALER's scale is non-increasing in current vol:")
    previous_scale = float("inf")
    for vol in (target * f for f in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)):
        scaled = volatility_target_scaling(
            VolTargetInputs(
                target_vol_annualized=target,
                current_portfolio_vol=vol,
                current_gross_exposure=1.0,
                limits=limits,
            )
        )
        assert isinstance(scaled.value, dict)
        scale = float(scaled.value["raw_scale"])
        print(f"       current_vol {vol:6.1%}  ->  scale {scale:5.3f}x")
        assert scale <= previous_scale + 1e-12, "a vol target must not scale UP into stress"
        previous_scale = scale
    print("     both are monotone in their own stress input, in opposite directions")

    # --- 5. CROSS-CHECK B: against check_rebalancing_drift (17.1/17.3) ------
    print()
    print("5. CROSS-CHECK B: the shared shape with check_rebalancing_drift (17.3)")
    print(
        "   The closer structural match: both publish a target exposure, both clip\n"
        "   it against a hard constraint, and both publish a flag about whether the\n"
        "   constraint BOUND. Comparing the two flags is what makes D-056's defect 4\n"
        "   visible: a flag that describes one side of a two-sided move.\n"
    )

    # Build an on-budget book from real risk shares, then ask both functions
    # about the same underlying position move.
    #
    # **This book has a negative risk share, and the D-055 check found the same
    # thing on the same legs.** UUP's marginal risk contribution is negative
    # (it is a dollar diversifier against this book), and
    # ``RiskBudgetTarget`` bounds ``target_risk_contribution_pct`` to ``[0, 1]``,
    # so a diversifying leg has NO legal target. The legs are partitioned so the
    # budget is one the contract can hold, and the excluded leg is named rather
    # than clamped to zero -- clamping would assert a diversifier carries no risk.
    # The retained shares are then RENORMALISED, because the function's own
    # sum-to-one rule requires it and the first run of the D-055 check proved the
    # warning is real.
    raw_shares = (_WEIGHTS * (cov @ _WEIGHTS)) / current_vol
    share_map = dict(zip(_LEGS, (float(s) for s in raw_shares), strict=True))
    negatives = {leg: s for leg, s in share_map.items() if s < 0.0}
    if negatives:
        print()
        print("   !! CONTRACT LIMITATION FOUND BY THIS CHECK (same as the D-055 check):")
        for leg, share in negatives.items():
            print(f"      {leg} carries a NEGATIVE risk share {share:+.2%} — a diversifier")
        print("      RiskBudgetTarget bounds its target to [0, 1], so a diversifying leg")
        print("      has no legal target. It is excluded below and reported, not clamped.")
    kept = {leg: s for leg, s in share_map.items() if s >= 0.0}
    kept_mass = sum(kept.values())
    normalised = {leg: s / kept_mass for leg, s in kept.items()}
    targets = [
        RiskBudgetTarget(instrument=leg, target_risk_contribution_pct=share)
        for leg, share in normalised.items()
    ]
    on_budget = check_rebalancing_drift(normalised, targets)
    assert isinstance(on_budget.value, dict)
    assert on_budget.value["outcome"] == "balanced", (
        "a book whose contributions ARE the targets must read balanced"
    )
    print()
    print("   invariant A (no stress -> no intervention) holds for the drift check too")
    print(
        f"     outcome {on_budget.value['outcome']!r}, drifted "
        f"{on_budget.value['instruments_drifted']}/{on_budget.value['instruments_evaluated']}"
    )

    # A real drift: move 10pp of notional from equity into duration.
    drifted_weights = _WEIGHTS.copy()
    drifted_weights[0] -= 0.10
    drifted_weights[1] += 0.10
    drifted_cov = returns.cov().to_numpy() * float(_TRADING_DAYS)
    drifted_vol = float(np.sqrt(drifted_weights @ drifted_cov @ drifted_weights))
    drifted_raw = (drifted_weights * (drifted_cov @ drifted_weights)) / drifted_vol
    drifted_map = dict(zip(_LEGS, (float(s) for s in drifted_raw), strict=True))
    # Same partition AND the same renormalisation as the target budget, so the
    # drift is measured on a comparable share vector.
    drifted_kept = {leg: s for leg, s in drifted_map.items() if leg in normalised}
    drifted_mass = sum(drifted_kept.values())
    drifted_shares = {leg: s / drifted_mass for leg, s in drifted_kept.items()}
    drift = check_rebalancing_drift(drifted_shares, targets)
    assert isinstance(drift.value, dict)
    print()
    print("   a 10pp notional move SPY -> TLT, both functions asked about it:")
    print(
        f"     drift check:  outcome {drift.value['outcome']!r}, "
        f"{drift.value['instruments_drifted']}/{drift.value['instruments_evaluated']} drifted"
    )
    print(f"     vol scaler:   the book's vol moves {current_vol:.2%} -> {drifted_vol:.2%}")

    # The shared disclosure comparison -- the point of this cross-check.
    print()
    print("   invariant C: the constraint-bound disclosure, compared")
    print(
        "     drift check publishes per-instrument drift rows and a set of "
        "triggered instruments;\n"
        "     it reports the SIZE and the DIRECTION of every move."
    )
    print(
        "     the vol scaler publishes ONE flag, `clipped_by_leverage_ceiling`,\n"
        "     which is False on the entire de-risking side — so on its own it\n"
        "     reads as 'no constraint engaged' while the book is being cut."
    )
    assert len(drift.value["drifted"]) >= 1, "the 10pp move must produce at least one row"
    print(
        f"     the drift check would have reported the scaler's cut: it publishes\n"
        f"     {len(drift.value['drifted'])} row(s) with signed magnitudes and directions."
    )
    print(
        "     -> the repair in D-056 is `de_risking_fraction`, which is the vol\n"
        "        scaler's equivalent of a drift row's magnitude."
    )

    # --- 6. what this check cannot validate ---------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * The vol TARGET (10%) is a policy number and the leverage CEILING\n"
        "    (3.0x) is a convention. No history can say whether either is right;\n"
        "    the check can only confirm the configured values are the ones used."
    )
    print(
        "  * The covariance is an ESTIMATE over a chosen lookback. A different\n"
        "    window gives a different vol and therefore a different scale, which\n"
        "    is why the window is printed above rather than assumed."
    )
    print(
        "  * The clip's 0.0% trip rate is a fact about THIS book at 1.0x gross. It\n"
        "    is NOT a claim that the ceiling is useless — a levered book reaches it\n"
        "    immediately. What the rate establishes is that the only enforced limit\n"
        "    cannot bind in the regime the function exists for, which is the defect.\n"
        "    Measured over the real path rather than cited from the probe."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
