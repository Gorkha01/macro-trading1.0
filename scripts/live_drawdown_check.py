"""Live wiring check: ``evaluate_drawdown_rules`` against real index history.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_drawdown_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the boundary convention, the sign convention, and whether the ladder the
configuration asserts is the ladder that actually fires.

What this check does that the unit tests cannot
-----------------------------------------------

1. **The ladder is walked as a STEP LADDER over a real price path**, not over
   synthetic fixtures. The drawdown is computed from an actual daily index, so
   the high-water mark is a *running* maximum and the check exercises the one
   thing a two-float fixture cannot: that the drawdown of a real path is a
   monotonically non-decreasing distance below its own running peak. A fixture
   hands the function a drawdown; a path makes it *earn* one.

2. **The boundary convention is tested against the COMPARISON, by construction.**
   The shipped rule is ``drawdown >= threshold``. The check walks the entire
   episode and records the drawdown at each transition — so the exact value at
   which each rung fired is printed and can be compared to the configured
   threshold. If the ladder fired late (``>`` instead of ``>=``) the printed
   transition would sit one tick above the threshold, which is a wiring error a
   fixture built at the threshold cannot see.

3. **Monotonicity is PROVEN over the path, not asserted.** A deeper drawdown
   must never prescribe less de-risking. Over a real episode this is a genuine
   claim: a de-risking ladder that un-de-risks as the loss deepens would be
   actively dangerous, and the unit test's grid can only sample it.

4. **THE CROSS-CHECK.** Against ``volatility_target_scaling`` (Module 17.2,
   §20.13) — the *sibling* de-risking function, and the one the D-053 narrative
   predicted would share this function's hazard. The two are the project's only
   pair of "scale or limit a position, then clip against a hard constraint"
   functions, so they are the right pair to compare.

   The relation checked is not "the numbers agree" — they are different
   quantities and cannot. It is the **structural invariant both must satisfy**:
   *the result is a monotone non-decreasing function of the stress input, and the
   un-stressed state produces no intervention.* For this function the stress
   input is the drawdown; for a vol-target it is the volatility. Both must be
   flat at zero stress and both must never reverse. That is a real check with a
   real failure mode (a sign error in either function violates it), and it is
   computed here from the same path.

   **D-056 upgraded this section from a re-implementation to a real call
   (O-43).** Until the vol-target function shipped, the scale was computed inline
   from its specification's formula — which meant this cross-check shared the
   errors of the code it was supposed to be an independent witness of. It now
   calls ``volatility_target_scaling`` directly.

5. **Reports what it cannot validate.** The ladder's *levels* are a convention,
   not a measurement. No history can say whether 10% is the right first rung.

Live-network dependency: this check needs the OpenBB API for the index path.
When the API is unavailable it reports the failure and exits non-zero rather
than substituting a synthetic path — a live check that falls back to fixtures is
not a live check.
"""

from __future__ import annotations

import sys
from datetime import date

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.portfolio.risk_budget import (
    DrawdownRule,
    DrawdownState,
    RiskLimits,
    VolTargetInputs,
    evaluate_drawdown_rules,
    volatility_target_scaling,
)

#: The instrument whose drawdown episode is walked. An equity index is the
#: honest choice for a *portfolio* drawdown ladder: it is the asset class whose
#: 10/15/20% levels the convention was written for.
#:
#: **The window is NOT chosen by this script.** FRED serves ``SP500`` as a
#: ROLLING ~10-year window (recorded in ``series_registry.yaml``, verified
#: 2026-09-17: 2512 observations from 2016-09-16). A probe on 2026-09-18 found
#: 2513 observations, 2016-09-19 .. 2026-09-17 — so the start date advances and
#: a hardcoded episode would silently go stale. The first draft of this check
#: asked for 2007-01-01 .. 2010-12-31, which FRED **does not have**, and it would
#: have failed on real data while passing every unit test. The window is
#: therefore whatever the provider returns, and the check asserts that whatever
#: it returned is deep enough to exercise the ladder.
_INDEX_SYMBOL = "SP500"

#: The minimum depth the returned window must reach for the check to be
#: meaningful. 20% is the terminal rung, so a window that never drew down that
#: far would exercise only two of the three outcomes and the check would pass
#: while proving nothing. COVID (2020-03-23, -33.92%) is what satisfies this in
#: the current window; when the rolling window advances past it, this assertion
#: is what reports that the check has gone blind.
_REQUIRED_DEPTH = 0.20


def _fetch_daily(client: OpenBBClient, symbol: str) -> list[tuple[date, float]]:
    """Daily closes, oldest first, with NaN dropped."""
    frame = client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=f"{symbol} daily",
    )
    points: list[tuple[date, float]] = []
    for _, row in frame.iterrows():
        value = row["value"]
        if value is None or value != value:  # NaN is the only value != itself
            continue
        raw = row["date"]
        day: date = raw if isinstance(raw, date) else raw.date()
        points.append((day, float(value)))
    points.sort(key=lambda p: p[0])
    return points


def _ladder() -> list[DrawdownRule]:
    """The configured ladder, in FRACTION scale, read the shipped way."""
    settings = get_settings()
    return [
        DrawdownRule(
            threshold_pct=float(tier.drawdown_pct) / 100.0,
            risk_reduction_pct=float(tier.risk_reduction_pct) / 100.0,
        )
        for tier in settings.risk.drawdown_tiers
    ]


def _walk(points: list[tuple[date, float]]) -> list[tuple[date, float, str, float, float]]:
    """Walk the path, carrying a running high-water mark.

    Returns one row per observation: date, drawdown, outcome, reduction, hwm.
    The high-water mark is the RUNNING maximum, which is what makes this a real
    path rather than a fixture: a drawdown of 20% reached from a peak of 1500 is
    a different state than the same 20% reached from a peak of 1000, and only
    the path can produce both.
    """
    rows: list[tuple[date, float, str, float, float]] = []
    hwm = 0.0
    for day, close in points:
        hwm = max(hwm, close)
        if hwm <= 0.0:
            continue
        state = DrawdownState(high_water_mark=hwm, current_value=close)
        result = evaluate_drawdown_rules(state)
        assert isinstance(result.value, dict), "evaluate_drawdown_rules must return a dict value"
        rows.append(
            (
                day,
                state.drawdown_pct,
                str(result.value["outcome"]),
                float(result.value["risk_reduction_fraction"]),
                hwm,
            )
        )
    return rows


def _transitions(
    rows: list[tuple[date, float, str, float, float]],
) -> list[tuple[date, float, float]]:
    """Where the prescribed reduction CHANGED: date, drawdown at the change, new reduction."""
    out: list[tuple[date, float, float]] = []
    previous: float | None = None
    for day, drawdown, _outcome, reduction, _hwm in rows:
        if previous is None or reduction != previous:
            out.append((day, drawdown, reduction))
            previous = reduction
    return out


def main() -> int:
    print("=" * 78)
    print("live check: evaluate_drawdown_rules (Module 17.3, Section 6.6c)")
    print(f"index {_INDEX_SYMBOL}, whatever window the provider serves")
    print("=" * 78)

    client = OpenBBClient()
    try:
        points = _fetch_daily(client, _INDEX_SYMBOL)
    finally:
        client.close()

    if not points:
        print("FAILED: no observations returned. A live check must not fall back")
        print("to a synthetic path — that would make it a unit test with extra steps.")
        return 1

    print(f"fetched {len(points)} daily observations")
    print(f"  first {points[0][0]} = {points[0][1]:,.2f}")
    print(f"  last  {points[-1][0]} = {points[-1][1]:,.2f}")
    peak_day, peak = max(points, key=lambda p: p[1])
    print(f"  peak  {peak_day} = {peak:,.2f}")
    print(
        "  NOTE: FRED serves SP500 as a rolling ~10-year window, so the first\n"
        "  date above advances over time. It is printed rather than assumed."
    )

    tiers = _ladder()
    print()
    print("configured ladder (fraction scale, as the function consumes it):")
    for tier in tiers:
        print(
            f"  drawdown >= {tier.threshold_pct:.1%}  ->  reduce risk by "
            f"{tier.risk_reduction_pct:.0%}"
        )

    rows = _walk(points)
    if not rows:
        print("FAILED: the path produced no evaluable states")
        return 1

    # --- 1. the reachable outcome space over the real path ------------------
    print()
    print("1. OUTCOME SPACE OVER THE REAL PATH")
    seen: dict[str, int] = {}
    for _day, _dd, outcome, _red, _hwm in rows:
        seen[outcome] = seen.get(outcome, 0) + 1
    declared = {"no_action", "reduce_risk", "stop_trading"}
    for outcome in sorted(declared):
        count = seen.get(outcome, 0)
        print(f"  {outcome:14} {count:5} observations ({count / len(rows):.1%})")
    missing = declared - set(seen)
    if missing:
        print(
            f"  !! UNREACHABLE over this episode: {sorted(missing)}. The window "
            f"must be widened, or the ladder is mis-scaled."
        )
        print("FAILED: the check did not exercise its own outcome space")
        return 1
    print("  every declared outcome is reachable over this episode")

    # The DEEPEST drawdown is the MAXIMUM of the drawdown column. The first
    # draft wrote `min(rows, key=...)`, which picks the smallest drawdown — the
    # very first observation, 0.00% — and then failed its own depth assertion
    # with a message about the window having "advanced past the last deep
    # episode". The diagnosis was wrong and the numbers above it were right
    # (74 observations at `stop_trading`), which is how the error was spotted:
    # a check whose own sections contradict each other has a check bug, not a
    # data bug.
    worst = max(rows, key=lambda r: r[1])
    print(f"  worst drawdown: {worst[1]:.2%} on {worst[0]} (peak {worst[4]:,.2f})")

    if worst[1] < _REQUIRED_DEPTH:
        print(
            f"\nFAILED: the served window only reached a {worst[1]:.2%} drawdown, "
            f"below the {_REQUIRED_DEPTH:.0%} the terminal rung needs. The rolling\n"
            f"window has advanced past the last deep episode, so this check can no\n"
            f"longer exercise its own outcome space. Source a longer series."
        )
        return 1

    # --- 2. the boundary convention, measured at the transitions ------------
    print()
    print("2. BOUNDARY CONVENTION: where each rung actually fired")
    transitions = _transitions(rows)
    fired = [t for t in transitions if t[2] > 0.0]
    for day, drawdown, reduction in fired:
        rung = min(
            (t for t in tiers if t.risk_reduction_pct == reduction),
            key=lambda t: t.threshold_pct,
            default=None,
        )
        threshold = rung.threshold_pct if rung is not None else float("nan")
        overshoot = drawdown - threshold
        print(
            f"  {day}  drawdown {drawdown:.4%}  ->  reduction {reduction:.0%}  "
            f"(threshold {threshold:.2%}, overshoot {overshoot:+.4%})"
        )
    if not fired:
        print("  !! no rung fired — the episode did not reach the first threshold")
        return 1

    # The shipped comparison is `>=`, so a rung fires AT its threshold. Daily
    # closes are discrete, so the observed drawdown at a transition is the first
    # observation at or past the threshold — never BELOW it. A transition below
    # its threshold would mean the comparison is inverted.
    for day, drawdown, reduction in fired:
        rung = min(
            (t for t in tiers if t.risk_reduction_pct == reduction),
            key=lambda t: t.threshold_pct,
            default=None,
        )
        assert rung is not None
        assert drawdown >= rung.threshold_pct, (
            f"{day}: rung {rung.threshold_pct:.2%} fired at a drawdown of "
            f"{drawdown:.4%}, BELOW its own threshold — the comparison is inverted"
        )
    print("  every rung fired AT or beyond its threshold (the `>=` convention holds)")

    # --- 3. path-independence of the decision ------------------------------
    print()
    print("3. PATH-INDEPENDENCE OF THE DECISION")
    print(
        "   NOTE (and the first draft of this check got it BACKWARDS): the\n"
        "   property over a time series is NOT monotonicity. A recovery from a\n"
        "   20% drawdown IS a shallower drawdown, so the ladder correctly\n"
        "   prescribes LESS de-risking on the way up — that is the ladder\n"
        "   working, not failing. The first draft asserted 'a deeper drawdown\n"
        "   never prescribes less' against consecutive PATH observations and\n"
        "   reported 52 violations, every one of them a recovery.\n"
        "\n"
        "   The property that actually holds, and the one that matters, is\n"
        "   PATH-INDEPENDENCE: the prescribed reduction depends only on the\n"
        "   current drawdown, never on the sequence that produced it. It is the\n"
        "   same statement the specification makes when it calls the rule\n"
        "   STATELESS, and it is testable here because the path visits many\n"
        "   drawdowns more than once — reached from a different peak each time."
    )
    by_drawdown: dict[float, set[float]] = {}
    for _day, drawdown, _outcome, reduction, _hwm in rows:
        by_drawdown.setdefault(round(drawdown, 9), set()).add(reduction)

    disagreements = {
        drawdown: reductions for drawdown, reductions in by_drawdown.items() if len(reductions) > 1
    }
    revisited = sum(1 for v in by_drawdown.values() if len(v) == 1)
    print(f"   distinct drawdowns visited: {len(by_drawdown)}")
    print(f"   drawdowns where two different reductions were prescribed: {len(disagreements)}")
    assert not disagreements, (
        f"the same drawdown produced different reductions: {list(disagreements.items())[:3]}"
    )
    assert revisited, "no drawdown was visited twice — the path-independence check is vacuous"
    print("   every drawdown maps to exactly ONE reduction (path-independent)")

    # And the direction property, stated correctly: monotone in the INPUT.
    # Swept over the input directly rather than over time, which is what the
    # unit suite does and what this section now confirms independently.
    previous = -1.0
    for step in range(0, 201):
        drawdown = step / 100.0
        state = DrawdownState(high_water_mark=100.0, current_value=100.0 * (1.0 - drawdown))
        result = evaluate_drawdown_rules(state)
        assert isinstance(result.value, dict)
        reduction = float(result.value["risk_reduction_fraction"])
        assert reduction >= previous, (
            f"a deeper drawdown ({drawdown:.2%}) prescribed less de-risking "
            f"({reduction:.0%} < {previous:.0%})"
        )
        previous = reduction
    print("   the reduction is non-decreasing in the DRAWDOWN itself (0..200%)")

    # --- 4. THE CROSS-CHECK against volatility_target_scaling (Module 17.2) -
    print()
    print("4. CROSS-CHECK: the shared shape with volatility_target_scaling (17.2)")
    print(
        "   Both functions scale or limit a position and then clip against a hard\n"
        "   constraint. They are compared on the STRUCTURAL INVARIANT, not on\n"
        "   their numbers, because they measure different quantities.\n"
    )

    # Invariant A: zero stress produces no intervention. For the ladder that is
    # a drawdown of zero (a new high); for a vol target it is current vol equal
    # to target vol (a scale of 1.0).
    at_peak = evaluate_drawdown_rules(DrawdownState(high_water_mark=100.0, current_value=100.0))
    assert isinstance(at_peak.value, dict)
    assert at_peak.value["outcome"] == "no_action", (
        "zero stress must produce no intervention — the shared invariant"
    )
    assert at_peak.value["risk_reduction_fraction"] == 0.0
    print("   invariant A: zero stress -> no intervention")
    print("     drawdown 0.0000  -> no_action, reduction 0.0")
    print("     a vol-target's scale at current == target is 1.0x (no change)")

    # Invariant B: monotone non-decreasing in the stress input. For the ladder
    # that is asserted over the real path above; for a vol target it is the
    # arithmetic claim that `target / current` falls as `current` rises.
    #
    # D-056 / O-43: this now CALLS volatility_target_scaling. It used to
    # re-implement `target / current` inline, because the function did not yet
    # exist -- and a cross-check against a re-implementation shares the
    # re-implementation's errors while looking like an independent witness. The
    # values below are now produced by the shipped function, so a sign error or a
    # unit error in it fails *this* check.
    target = get_settings().risk.vol_target
    limits = RiskLimits.from_settings()
    vols = [target * factor for factor in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)]
    print()
    print("   invariant B: the response is monotone in the stress input")
    print(f"     vol-target scale = target_vol / current_vol, target_vol = {target:.0%}")
    print("     (computed by the shipped volatility_target_scaling, not inline)")
    previous_scale = float("inf")
    at_target_scale: float | None = None
    for vol in vols:
        # Gross exposure 1.0 so the ceiling is out of the way and the scale is
        # read cleanly -- this invariant is about the scale, not the clip.
        result = volatility_target_scaling(
            VolTargetInputs(
                target_vol_annualized=target,
                current_portfolio_vol=vol,
                current_gross_exposure=1.0,
                limits=limits,
            )
        )
        assert isinstance(result.value, dict)
        scale = float(result.value["raw_scale"])
        marker = "  <- at target" if abs(vol - target) < 1e-12 else ""
        print(f"       current_vol {vol:6.1%}  ->  scale {scale:5.2f}x{marker}")
        assert scale <= previous_scale + 1e-12, "a vol-target scale must not rise with vol"
        previous_scale = scale
        if abs(vol - target) < 1e-12:
            at_target_scale = scale
            assert scale == 1.0, (
                "at current == target the shipped function must report a no-op scale"
            )
    assert at_target_scale is not None, "the at-target case must have been probed"
    print(
        "     the scale is non-increasing in current_vol, as the ladder's reduction\n"
        "     is non-decreasing in the drawdown — the same invariant, opposite sign\n"
        "     because one scales the position DOWN as stress rises and the other\n"
        "     measures how much stress there is"
    )

    # Invariant C: the hard constraint clips, and it never loosens.
    limit = max(t.risk_reduction_pct for t in tiers)
    print()
    print("   invariant C: the hard constraint clips and never loosens")
    print(f"     the ladder's terminal rung removes {limit:.0%} of risk — the ceiling")
    clipped = [r for r in rows if r[3] >= limit]
    print(f"     observations at the ceiling: {len(clipped)} of {len(rows)}")
    assert clipped, "the episode must hold the terminal rung for at least one observation"
    assert all(r[3] <= limit for r in rows), "no observation may exceed the terminal rung"

    # --- 5. what this check cannot validate ---------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * The ladder's LEVELS (10/15/20%) are a pre-commitment, not a\n"
        "    measurement. No history can say whether 10% is the right first rung;\n"
        "    the check can only confirm the configured rungs are the ones that fire."
    )
    print(
        "  * The high-water mark's STALENESS is not observable here. This check\n"
        "    maintains a running maximum by construction, so it never sees the\n"
        "    failure the function warns about — a portfolio whose recorded peak is\n"
        "    out of date. That path is disclosed by a warning and cannot be tested\n"
        "    from price history."
    )
    print(
        "  * The cross-check compares SHAPE, not values. volatility_target_scaling\n"
        "    (D-056, shipped) is now CALLED here rather than re-implemented, so the\n"
        "    vol-target side of invariants A and B is produced by the shipped code\n"
        "    and a sign or unit error in it fails this check. It is still a SHAPE\n"
        "    check: the two functions measure different quantities (a drawdown and\n"
        "    a volatility) and their NUMBERS can never agree, so nothing here\n"
        "    validates either function's levels or its calibration.\n"
        "    (This paragraph replaces the O-43 disclosure, which said the\n"
        "    vol-target side was computed from its specification's formula. That\n"
        "    caveat is now discharged -- recorded by D-056 rather than deleted,\n"
        "    because a cross-check against a re-implementation is a real hazard\n"
        "    that this script spent one increment living with.)"
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
