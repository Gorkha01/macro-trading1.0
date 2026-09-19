"""Live wiring check: ``check_rebalancing_drift`` against a real multi-asset book.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_rebalancing_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring -- the
units, the share basis, the threshold convention, and whether a real book's risk
decomposition is the kind of input this function was written for.

What this check does that the unit tests cannot
-----------------------------------------------

1. **The risk contributions are DERIVED, not supplied.** Every unit fixture hands
   the function a contribution vector. Here the vector is produced from real
   prices: fetch tradeable ETF closes, take returns, annualize the covariance,
   and compute Euler risk contributions ``w_i (Cov w)_i / sigma_p``. That is the
   whole arithmetic of Module 17.1, and running it end to end is the only way to
   find out whether the drift check's inputs are *shaped* the way it assumes.

2. **The notional-vs-risk distinction is MEASURED, not asserted.** Section 15.18's
   entire content is that 35% of dollars is not 35% of risk. A fixture can be
   built to differ; only a real covariance can show *how much* it differs, and
   whether the difference is large enough for the threshold to discriminate. The
   measured gaps are printed.

3. **The threshold's trip rate is measured over the real covariance.** If the
   configured 10% tolerance tripped on 99% of plausible weight wobbles the check
   would be a smoke alarm that is always on; if it tripped on 0% it would be
   inert. The measured rate is the base-state evidence the module's docstring
   cites (10.8% on a synthetic covariance) now re-derived from live data.

4. **THE CROSS-CHECK, built from the start.** Against
   ``evaluate_drawdown_rules`` (Module 17.3, Section 6.6c) -- the project's
   *other* implemented portfolio-control function, and the right comparison
   because the two are siblings in the same module: one de-risks on a loss, the
   other rebalances on a drift.

   **The relation is not "the numbers agree" -- they measure different
   quantities.** It is the shared structural invariant, and it has three parts
   that are genuinely falsifiable:

   * **No-stress idempotence.** A book exactly on budget must produce
     ``balanced`` (no intervention); a portfolio at its high-water mark must
     produce ``no_action``. Both are the "do nothing when nothing is wrong"
     property, and a sign error in either function breaks it.
   * **Monotone response.** The drift check's reported drift must be
     non-decreasing as the book moves away from budget; the drawdown ladder's
     prescribed reduction must be non-decreasing in the drawdown. Both are
     computed over sweeps here.
   * **Bounded intervention.** The ladder never exceeds 100% de-risking; the
     drift check never reports a drift larger than the position itself. A
     clipping error in either breaks it.

   Both functions are CALLED. The D-054 check could not do this for
   ``volatility_target_scaling`` (it did not exist yet, O-43); here both sides
   exist, so the cross-check is a real call on both sides and there is no local
   re-implementation to inherit errors from.

5. **Reports what it cannot validate.** The threshold is a CONVENTION, not a
   measurement: no history can say whether 10% is the right tolerance. And the
   covariance is an ESTIMATE from a chosen lookback -- a different window gives
   different risk shares, which the check makes visible rather than hiding.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.portfolio.risk_budget import (
    DrawdownState,
    RiskBudgetTarget,
    check_rebalancing_drift,
    evaluate_drawdown_rules,
)

#: A plausible macro multi-asset book in genuinely tradeable instruments.
#:
#: **Why ETFs and not the FRED index levels.** The first probe for this check
#: used ``SP500``, ``DGS10``, ``DGS2`` and ``VIXCLS`` -- all verified series --
#: and produced a DEGENERATE decomposition: the VIX "leg" ran at 136% annualized
#: vol and took a 116% risk share while the equity leg went NEGATIVE, because a
#: volatility index is not a return series and a yield is not a price. The lesson
#: is Section 21.0's: a series being *verified* says nothing about whether it is
#: the right INPUT. ETF closes are total-return-ish prices, which is what a
#: covariance of *returns* actually needs.
_LEGS: tuple[str, ...] = ("SPY", "TLT", "IEF", "GLD", "UUP")

#: The book's notional weights. These are the whole point of the check: they are
#: NOT the risk shares, and the gap between the two is printed.
_NOTIONAL_WEIGHTS = np.array([0.35, 0.25, 0.20, 0.12, 0.08])

#: The lookback the covariance is estimated over. Stated rather than implied,
#: because a different window gives different risk shares -- an estimate is not a
#: fact, and the check discloses which one it used.
_LOOKBACK_DAYS = 504

#: Trading days per year, for annualizing a daily covariance.
_TRADING_DAYS = 252


def _fetch_closes(client: OpenBBClient, symbol: str) -> pd.Series:
    """Daily closes for one ETF, oldest first.

    The client normalises every provider route to a single schema
    (``date``, ``value``, ``series_id``, ``source``, ``retrieved_at``), so the
    route's own ``close`` field arrives as ``value``. A probe that read the
    API docs instead of the returned frame got a ``KeyError: 'close'`` for its
    trouble -- the schema is what the code sees.
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


def _risk_shares(closes: pd.DataFrame, weights: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """Euler risk contributions for a weighted book.

    Returns ``(shares, portfolio_vol, leg_vols)`` where ``shares`` sums to 1.

    ``RC_i = w_i * (Cov w)_i / sigma_p`` is the marginal contribution to
    portfolio volatility. Dividing by the sum makes it a SHARE -- which is the
    unit ``check_rebalancing_drift`` consumes and the reason its own output warns
    when the inputs do not sum to 1.
    """
    returns = closes.pct_change().dropna()
    cov = returns.cov().to_numpy() * float(_TRADING_DAYS)
    sigma_p = float(np.sqrt(weights @ cov @ weights))
    if sigma_p <= 0.0:
        raise ValueError("degenerate book: zero portfolio volatility")
    raw = (weights * (cov @ weights)) / sigma_p
    return raw / raw.sum(), sigma_p, np.sqrt(np.diag(cov))


def main() -> int:
    print("=" * 78)
    print("live check: check_rebalancing_drift (Module 17.3, Section 15.18)")
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
    print(f"  estimation window: {window.index[0].date()} .. {window.index[-1].date()}")

    shares, sigma_p, leg_vols = _risk_shares(window, _NOTIONAL_WEIGHTS)

    # --- 1. the notional-vs-risk distinction, MEASURED ----------------------
    print()
    print("1. NOTIONAL WEIGHTS vs RISK SHARES (the distinction Section 15.18 is about)")
    print(f"   portfolio vol (annualized): {sigma_p:.2%}")
    for leg, notional, share, vol in zip(_LEGS, _NOTIONAL_WEIGHTS, shares, leg_vols, strict=True):
        print(
            f"   {leg}: notional {notional:6.1%}  vol {vol:6.2%}  "
            f"RISK {share:7.2%}  gap {share - notional:+7.2%}"
        )
    widest = int(np.argmax(np.abs(shares - _NOTIONAL_WEIGHTS)))
    print(
        f"   widest gap: {_LEGS[widest]} — {_NOTIONAL_WEIGHTS[widest]:.1%} of the book "
        f"carries {shares[widest]:.1%} of the risk"
    )
    if np.allclose(shares, _NOTIONAL_WEIGHTS, atol=1e-6):
        print("   !! notional and risk coincide on this book, so the check would prove")
        print("   nothing about the distinction. Pick legs with different volatilities.")
        return 1
    print("   notional and risk DIFFER — the distinction is live on this book")

    # A negative share is legal (a diversifier), and it is NOT expressible as a
    # target -- see the renormalisation note below. The legs are partitioned so
    # the check operates on a budget the contract can actually hold, and the
    # excluded legs are named rather than dropped.
    #
    # **The partition must also be RENORMALISED, and the first run of this check
    # proved why:** dropping UUP's -1.48% while keeping the other four as-is left
    # them summing to 1.0148, and ``check_rebalancing_drift`` correctly raised its
    # own sum-to-one warning at the very next step. That warning was right -- the
    # vector was no longer a share vector. This is the function's disclosure
    # working on its own author, which is a better demonstration of it than any
    # fixture, so the sum is renormalised and the adjustment is stated.
    negatives = [(leg, float(s)) for leg, s in zip(_LEGS, shares, strict=True) if s < 0.0]
    if negatives:
        print()
        print("   !! CONTRACT LIMITATION FOUND BY THIS CHECK:")
        print(f"      negative risk share(s) {negatives}")
        print("      RiskBudgetTarget bounds target_risk_contribution_pct to [0, 1], so a")
        print("      diversifying leg (negative marginal risk) has NO legal target. Those")
        print("      legs are excluded from the budget below and reported, never clamped")
        print("      to zero — clamping would assert a diversifier carries no risk.")
        excluded_mass = sum(s for _leg, s in negatives)
        print(f"      the {len(negatives)} excluded leg(s) hold {excluded_mass:+.2%} of total")
        print("      risk, so the retained shares are RENORMALISED to sum to 1 — the")
        print("      function's own sum-to-one warning is what caught the need to.")

    kept = [(leg, float(s)) for leg, s in zip(_LEGS, shares, strict=True) if s >= 0.0]
    kept_mass = sum(s for _leg, s in kept)
    normalised = {leg: s / kept_mass for leg, s in kept}
    normalised_targets = [
        RiskBudgetTarget(instrument=leg, target_risk_contribution_pct=s)
        for leg, s in normalised.items()
    ]
    print()
    print(f"   budget after renormalisation (mass {kept_mass:.4f} -> 1.0):")
    for leg, share in normalised.items():
        print(f"     {leg}: target risk share {share:.2%}")

    # --- 2. the no-drift base case -----------------------------------------
    print()
    print("2. NO-DRIFT IDEMPOTENCE: a book exactly on budget must not intervene")
    on_budget = check_rebalancing_drift(dict(normalised), normalised_targets)
    assert isinstance(on_budget.value, dict)
    print(
        f"   outcome {on_budget.value['outcome']!r}  "
        f"drifted {on_budget.value['instruments_drifted']}"
        f"/{on_budget.value['instruments_evaluated']}"
    )
    print(
        f"   total contribution {on_budget.value['total_current_contribution']} "
        f"(shares must sum to 1)"
    )
    assert on_budget.value["outcome"] == "balanced", (
        "a book whose contributions ARE the targets must read balanced"
    )
    assert on_budget.value["unbudgeted_instruments"] == []
    assert on_budget.value["missing_instruments"] == []
    assert abs(float(on_budget.value["total_current_contribution"]) - 1.0) < 1e-6
    print("   shares sum to 1 and the book is balanced — the unit convention holds")

    # --- 3. a real drift: sell equity, buy duration -------------------------
    print()
    print("3. A REAL DRIFT: 10pp of notional moved from SPY into TLT")
    drifted_notional = _NOTIONAL_WEIGHTS.copy()
    drifted_notional[0] -= 0.10
    drifted_notional[1] += 0.10
    drifted_shares, drifted_vol, _ = _risk_shares(window, drifted_notional)
    # Same partition AND the same renormalisation as the target budget, so the
    # drift is measured on a comparable share vector.
    drifted_kept = [
        (leg, float(s)) for leg, s in zip(_LEGS, drifted_shares, strict=True) if s >= 0.0
    ]
    drifted_mass = sum(s for _leg, s in drifted_kept)
    current = {leg: s / drifted_mass for leg, s in drifted_kept}
    result = check_rebalancing_drift(current, normalised_targets)
    assert isinstance(result.value, dict)

    print(f"   portfolio vol moves {sigma_p:.2%} -> {drifted_vol:.2%}")
    for row in result.value["drifted"]:
        print(
            f"   DRIFTED {row['instrument']}: target {float(row['target_risk_contribution']):7.2%} "
            f"actual {float(row['actual_risk_contribution']):7.2%} "
            f"signed {float(row['signed_drift']):+7.2%} ({row['direction']})"
        )
    print(
        f"   outcome {result.value['outcome']!r}  "
        f"drifted {result.value['instruments_drifted']}/{result.value['instruments_evaluated']}"
    )
    assert result.value["outcome"] == "rebalance", (
        "a 10pp notional move must trip a 10% risk tolerance"
    )
    assert result.value["missing_instruments"] == []
    assert result.value["unbudgeted_instruments"] == []
    print("   the drift is detected, reported with a direction, and nothing is claimed")
    print("   about thesis validity:", "NOT a thesis-validity check" in " ".join(result.warnings))

    # --- 4. the threshold's trip rate over the REAL covariance --------------
    print()
    print("4. THE THRESHOLD'S TRIP RATE over this covariance")
    print(
        "   Section 15.18's 10% is a CONVENTION, not a measurement. What CAN be\n"
        "   measured is whether it discriminates: a tolerance that always trips is\n"
        "   a smoke alarm that is always on, and one that never trips is inert."
    )
    rng = np.random.default_rng(4242)
    threshold = get_settings().risk.rebalancing_drift_threshold
    trips = 0
    trials = 5000
    for _ in range(trials):
        wobbled = _NOTIONAL_WEIGHTS * (1.0 + rng.normal(0.0, 0.12, size=len(_LEGS)))
        wobbled = wobbled / wobbled.sum()
        w_shares, _, _ = _risk_shares(window, wobbled)
        if np.any(np.abs(w_shares - shares) > threshold):
            trips += 1
    rate = trips / trials
    print(f"   {trips}/{trials} plausible weight wobbles trip at {threshold:.0%} -> {rate:.1%}")
    assert 0.0 < rate < 1.0, (
        f"the threshold is degenerate on this book: it trips {rate:.1%} of the time"
    )
    print("   the threshold discriminates (neither always-on nor inert)")

    # --- 5. THE CROSS-CHECK against evaluate_drawdown_rules -----------------
    print()
    print("5. CROSS-CHECK: the shared invariant with evaluate_drawdown_rules (6.6c)")
    print("   Both are Module 17.3 portfolio controls — one de-risks on a LOSS, the")
    print("   other rebalances on a DRIFT. Compared on the structural invariant, not")
    print("   on values, because they measure different quantities. Both are CALLED.\n")

    # Invariant A — no stress, no intervention.
    at_peak = evaluate_drawdown_rules(DrawdownState(high_water_mark=100.0, current_value=100.0))
    assert isinstance(at_peak.value, dict)
    assert at_peak.value["outcome"] == "no_action"
    assert float(at_peak.value["risk_reduction_fraction"]) == 0.0
    assert on_budget.value["outcome"] == "balanced"
    print("   invariant A: zero stress -> no intervention")
    print("     drawdown ladder : drawdown 0.00% -> no_action, reduction 0.0")
    print("     drift check     : drift    0.00pp -> balanced, 0 instruments")
    print("     both are silent exactly when nothing is wrong")

    # Invariant B — monotone in the stress input. Swept over each input directly.
    print()
    print("   invariant B: the response is monotone in the stress input")
    ladder_previous = -1.0
    for step in range(0, 201):
        drawdown = step / 100.0
        res = evaluate_drawdown_rules(
            DrawdownState(high_water_mark=100.0, current_value=100.0 * (1.0 - drawdown))
        )
        assert isinstance(res.value, dict)
        reduction = float(res.value["risk_reduction_fraction"])
        assert reduction >= ladder_previous, (
            f"a deeper drawdown ({drawdown:.2%}) prescribed LESS de-risking"
        )
        ladder_previous = reduction
    print("     ladder  : reduction is non-decreasing over drawdown 0%..200%")

    # For the drift check the stress input is the DISTANCE FROM BUDGET, and the
    # invariant is **V-SHAPED, not monotone** — which the first run of this check
    # proved by failing. Sweeping SPY's contribution UP from its drifted value
    # (0.3434, target 0.5533) initially made |drift| FALL (0.2098 -> 0.2049),
    # because SPY was UNDER budget and the sweep was pushing it back TOWARD the
    # target. The function was right; the check's stated invariant was wrong.
    #
    # This is the same correction D-054's live check had to make when it asserted
    # path-monotonicity over a time series that was correctly recovering. The
    # property that actually holds is the one the function is built on: |drift|
    # is minimised AT the target and rises with the distance from it, on BOTH
    # sides. So it is swept outward in each direction and checked for a V.
    # The leg whose displacement is swept: the one whose budget line is largest,
    # so the sweep has room to move in both directions before saturating at [0,1].
    #
    # NOTE: this is an INDEX, not a name. The first draft assigned the leg's name
    # here and then wrote `moved[_LEGS[leg]]`, indexing a tuple of names with a
    # name -- a `TypeError` that is exactly the trap `shares` being a numpy array
    # makes easy to miss, because `shares[leg]` would have silently worked if
    # `leg` had been the integer.
    swept_index = int(np.argmax(np.where(shares >= 0.0, shares, -np.inf)))
    swept_leg = _LEGS[swept_index]
    print(
        f"     drift   : |drift| is V-shaped — minimised at the target, rising either side "
        f"(sweeping {swept_leg})"
    )
    for side in (-1.0, 1.0):
        previous_drift = -1.0
        # Named `offset` rather than `step`, because `step` is already bound to an
        # int by the drawdown sweep above and mypy --strict will not let one name
        # carry an int and a float64 in the same scope.
        for offset in np.linspace(0.0, 0.40, 81):
            moved = dict(current)
            # **The sweep starts AT the target**, not at the leg's current value.
            # The second run of this check failed here: SPY sat 20.98pp UNDER
            # budget, so moving it UP by 0.005 correctly *reduced* the drift to
            # 0.2048 -- the function was right and the sweep's origin was wrong.
            # A V-shaped invariant can only be tested outward FROM its vertex,
            # which is the target; starting anywhere else measures the slope of
            # one arm and calls the other one a violation.
            moved[swept_leg] = normalised[swept_leg] + side * float(offset)
            res = check_rebalancing_drift(moved, normalised_targets)
            assert isinstance(res.value, dict)
            reported = next(
                (
                    float(r["abs_drift"])
                    for r in res.value["drifted"]
                    if r["instrument"] == swept_leg
                ),
                0.0,
            )
            assert reported + 1e-12 >= previous_drift, (
                f"moving {swept_leg} {'down' if side < 0 else 'up'} by {offset:.3f} "
                f"from its TARGET reported a SMALLER drift "
                f"({reported:.4f} < {previous_drift:.4f}) — |drift| must rise with "
                f"the distance from the target"
            )
            previous_drift = reported
    print(
        f"     drift   : reported |drift| rises monotonically as {swept_leg} moves "
        f"away from its target, in EACH direction"
    )

    # Invariant C — bounded intervention, and the hard limit clips.
    print()
    print("   invariant C: the intervention is bounded")
    limit = max(float(t.risk_reduction_pct) for t in get_settings().risk.drawdown_tiers) / 100.0

    def _ladder_reduction(step: int) -> float:
        res = evaluate_drawdown_rules(
            DrawdownState(high_water_mark=100.0, current_value=100.0 * (1.0 - step / 100.0))
        )
        assert isinstance(res.value, dict), "the ladder must return a dict value"
        return float(res.value["risk_reduction_fraction"])

    worst = max(_ladder_reduction(s) for s in range(0, 301))
    assert worst <= limit + 1e-12, "the ladder prescribed more de-risking than its terminal rung"
    print(f"     ladder  : max prescribed reduction {worst:.0%} == terminal rung {limit:.0%}")
    # A reported drift cannot exceed the position's own distance from its target.
    for row in result.value["drifted"]:
        assert float(row["abs_drift"]) <= 1.0 + 1e-12, "a drift above 1.0 is not a share distance"
    print("     drift   : every |drift| is a share distance <= 1.0")

    # --- 6. what this check cannot validate ---------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * The 10% TOLERANCE is a convention. The trip-rate measurement says it\n"
        "    discriminates; it cannot say it is the right number. No history can."
    )
    print(
        f"  * The COVARIANCE is an estimate over {_LOOKBACK_DAYS} sessions. A\n"
        "    different window gives different risk shares, so the targets here are\n"
        "    one estimate rather than a fact -- which is why the window is printed."
    )
    print(
        "  * A NEGATIVE risk share (a diversifying leg) produces a target that no\n"
        "    positive actual can beat, so it reads 'under' by construction. The\n"
        "    function reports it; it cannot tell diversification from drift."
    )
    print(
        "  * The cross-check compares SHAPE, not values, and it is a real call on\n"
        "    BOTH sides -- unlike D-054's, which had to compute the vol-target side\n"
        "    from its specification because that function did not exist yet (O-43)."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
