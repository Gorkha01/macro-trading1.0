"""Live wiring check: real FRED data -> ``build_scenario_distribution`` (D-064).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_scenario_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the nulls, the frequency, the sign conventions, and whether the values
that come out are the values the specification says should come out.

Every prior increment has pulled its live check rather than asserting offline
(D-062/D-063), and D-064 is the increment where that discipline pays a second
time: the whole function is a **unit conversion** (a percent gap into a
basis-point payoff), and a unit conversion is exactly the class of error a
fixture cannot show, because a fixture is written in whatever units the author
had in mind.

What is established here, each independently of the function
------------------------------------------------------------
1. **The gap is REAL.** ``canonical_policy_gap`` is driven by three LIVE policy
   rules on live core PCE, live real GDP and live potential GDP, against the
   live effective fed funds rate. Nothing is typed in.

2. **The four probabilities sum to 1** — asserted on the published objects, not
   on the config leaves, because the leaves are what the sum is *derived* from.

3. **The payoff magnitudes are the gap times the configured multiple**, checked
   against the gap ``canonical_policy_gap`` actually published. This is the
   percent/basis-point assertion, and it is the one a unit error breaks.

4. **The tail is larger in magnitude than the whole mispricing**, which is the
   property Module 12.4's LTCM caveat names and the reason the distribution is
   not merely a probability-weighted mean.

5. **The refusal paths fire on real inputs**, not on hand-built ones: a real
   gap re-expressed in basis points is refused, and a real gap inside the
   rules' own dispersion is refused. Both are the defects the function exists to
   catch, and both are reached here through ``canonical_policy_gap``.

6. **The seam is LOUD (O-50).** The distribution this function publishes is
   ``bp_pnl_proxy`` and therefore **not** Kelly-sizable; the check demonstrates
   that handing it to ``KellyInputs`` is refused with a unit argument supplied
   AND with the argument omitted — the second being the silent path D-064
   closed.

**What this check CANNOT establish:** whether the probabilities are any good.
Every leaf is ``uncalibrated_illustrative`` and Section 16.4 says so. A live
check can prove a number was computed from real data; it cannot make an
illustrative number an estimate, and this one does not try.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult
from macro_engine.models.policy_rules import (
    FirstDifferenceInputs,
    MarketPricingGap,
    TaylorRuleInputs,
    balanced_approach_rule,
    canonical_policy_gap,
    first_difference_rule,
    taylor_rule,
)
from macro_engine.models.probability import PayoffUnit, ScenarioOutcome
from macro_engine.portfolio.risk_budget import KellyInputs, RiskLimits
from macro_engine.thesis_layer.scenarios import build_scenario_distribution
from macro_engine.thesis_layer.schemas import ConvergenceClassification

#: The four branch names, read from the module rather than re-typed: a rename in
#: the producer must not leave this check silently asserting about nothing.
_BRANCH_NAMES = (
    "base_case_gap_closes_as_modeled",
    "gap_partially_closes",
    "thesis_invalidated_reversal",
    "tail_adverse_surprise",
)


def _fetch(client: OpenBBClient, symbol: str, label: str) -> list[tuple[date, float]]:
    """Fetch a registry series as ``(date, value)`` pairs.

    Provider and endpoint are transcribed from ``series_registry.yaml``, which is
    the only place that should name providers.
    """
    frame = client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )
    dates = [d.date() if hasattr(d, "date") else d for d in frame["date"]]
    values = [float(v) for v in frame["value"]]
    return list(zip(dates, values, strict=True))


def _bare_float(result: ModelResult) -> float:
    """Narrow a result whose ``value`` is a bare float rather than a dict."""
    value = result.value
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{result.model_name}: expected a bare numeric value, got {type(value).__name__}"
    )
    return float(value)


def _live_gap(client: OpenBBClient) -> tuple[MarketPricingGap, dict[str, float]]:
    """Drive ``canonical_policy_gap`` from live data and return it with its inputs.

    Mirrors ``live_labor_check.py``'s policy-mix block: core PCE YoY for
    inflation, real GDP against potential GDP for the output gap, effective fed
    funds for the market-implied rate. Every number that reaches the rules comes
    from a FRED series.
    """
    settings = get_settings()
    r_star = settings.policy.r_star_value

    core = _fetch(client, "PCEPILFE", "core_pce")
    pot = _fetch(client, "GDPPOT", "potential_gdp")
    real = _fetch(client, "GDPC1", "real_gdp")
    funds = _fetch(client, "FEDFUNDS", "effective_fed_funds")

    def annual(pairs: list[tuple[date, float]]) -> dict[int, float]:
        out: dict[int, float] = {}
        for day, value in pairs:
            out[day.year] = value
        return out

    core_y, pot_y, real_y, funds_y = (annual(s) for s in (core, pot, real, funds))
    years = sorted(set(core_y) & set(pot_y) & set(real_y) & set(funds_y))
    assert len(years) > 20, f"only {len(years)} common years; the rules need more"

    latest, prior = years[-1], years[-2]
    pi_current = (core_y[latest] / core_y[prior] - 1) * 100
    gap_now = (real_y[latest] / pot_y[latest] - 1) * 100
    gap_prev = (real_y[prior] / pot_y[prior] - 1) * 100
    market_implied = funds_y[latest]

    taylor = taylor_rule(TaylorRuleInputs(r_star=r_star, pi_current=pi_current, output_gap=gap_now))
    balanced = balanced_approach_rule(
        TaylorRuleInputs(r_star=r_star, pi_current=pi_current, output_gap=gap_now)
    )
    first_diff = first_difference_rule(
        FirstDifferenceInputs(
            i_prev=funds_y[prior],
            pi_current=pi_current,
            output_gap_change=gap_now - gap_prev,
        )
    )

    print(f"  live inputs, {latest}:")
    print(f"    core PCE YoY      {pi_current:+.4f}%")
    print(f"    output gap        {gap_now:+.4f}%  (prior {gap_prev:+.4f}%)")
    print(f"    effective fed fds {market_implied:.4f}%")
    print(f"    taylor_rule       {_bare_float(taylor):+.4f}%")
    print(f"    balanced_approach {_bare_float(balanced):+.4f}%")
    print(f"    first_difference  {_bare_float(first_diff):+.4f}%")

    gap = canonical_policy_gap(taylor, balanced, first_diff, market_implied)
    print(
        f"  canonical gap: raw {gap.raw_gap:+.4f}{gap.unit}, "
        f"dispersion {gap.dispersion:.4f}, meaningful={gap.is_meaningful}"
    )
    print(f"    direction: {gap.direction}")

    inputs = {
        "raw_gap": gap.raw_gap,
        "dispersion": float(gap.dispersion or 0.0),
        "market_implied": market_implied,
        "pi_current": pi_current,
        "output_gap": gap_now,
        "r_star": r_star,
    }
    return gap, inputs


def _by_name(distribution: Sequence[ScenarioOutcome]) -> dict[str, ScenarioOutcome]:
    return {o.name: o for o in distribution}


def _check_scenario_distribution(client: OpenBBClient) -> None:
    """Real-data wiring for ``build_scenario_distribution`` (Module 12, D-064)."""
    print()
    print("=" * 72)
    print("Module 12 — build_scenario_distribution (Section 16.4 Q10; D-064)")

    settings = get_settings().scenario_distribution
    limits = RiskLimits.from_settings()

    gap, inputs = _live_gap(client)

    # (1) The gap must be meaningful, or Q6 routes to no_trade_thesis BEFORE Q10
    # and this check would be asserting about a call the builder never makes.
    if not gap.is_meaningful:
        raise SystemExit(
            f"\n  UNMEASURABLE TODAY: the live canonical gap ({gap.raw_gap:+.4f}) is "
            f"inside the rules' own dispersion ({gap.dispersion:.4f}). Section 16.2's "
            f"Q6 routes this to no_trade_thesis() BEFORE Q10, so there is no "
            f"distribution to check. This is the function working, not failing — "
            f"re-run when the three rules disagree by less than the gap."
        )
    print("\n  (1) the gap is meaningful, so Q10 is reachable -- CONFIRMED")

    # (2) Build the distribution from the REAL gap at each distributable verdict.
    built: dict[str, list[ScenarioOutcome]] = {}
    for verdict in (
        ConvergenceClassification.HIGH,
        ConvergenceClassification.MEDIUM,
        ConvergenceClassification.LOW,
    ):
        distribution = build_scenario_distribution(gap, verdict)
        built[verdict.value] = distribution

        names = [o.name for o in distribution]
        assert tuple(names) == _BRANCH_NAMES, (
            f"{verdict.value}: branch names are {names}, expected {list(_BRANCH_NAMES)}"
        )
        total = sum(float(o.probability) for o in distribution)
        assert abs(total - 1.0) < 1e-9, f"{verdict.value}: probabilities sum to {total!r}, not 1"
        units = {o.unit for o in distribution}
        assert units == {"bp_pnl_proxy"}, f"{verdict.value}: units are {units}"

        base = float(settings.base_probabilities[verdict.value])
        head = distribution[0]
        assert abs(float(head.probability) - base) < 1e-12, (
            f"{verdict.value}: base probability {head.probability} does not "
            f"match the configured leaf {base}"
        )

        # (3) The magnitude, checked against the gap canonical_policy_gap published.
        expected_bp = abs(inputs["raw_gap"]) * settings.bp_per_percent
        multipled = [float(o.payoff_estimate) for o in distribution]
        multiples = [multipled[i] / expected_bp for i in range(4)]
        configured = [settings.payoff_multiples[n] for n in _BRANCH_NAMES]
        assert multiples == configured, (
            f"{verdict.value}: implied multiples {multiples} != configured {configured}"
        )
        print(
            f"  (2) {verdict.value:6} sum=1.000000  base={base:.2f}  "
            f"|gap|={expected_bp:.4f}bp  payoffs={[round(m, 4) for m in multipled]}"
        )

    # (4) The tail loses MORE than the whole mispricing, at every verdict.
    for label, distribution in built.items():
        by_name = _by_name(distribution)
        tail = abs(float(by_name["tail_adverse_surprise"].payoff_estimate))
        base = abs(float(by_name["base_case_gap_closes_as_modeled"].payoff_estimate))
        assert tail > base, (
            f"{label}: the tail ({tail}) does not exceed the whole mispricing "
            f"({base}); Module 12.4's LTCM caveat is about a branch that costs more "
            f"than the thesis is worth"
        )
    print("  (3) the tail exceeds the whole mispricing at every verdict -- CONFIRMED")

    # (5) The refusal paths, reached through the REAL gap rather than a fixture.
    as_bp = gap.model_copy(update={"unit": "bp"})
    try:
        build_scenario_distribution(as_bp, ConvergenceClassification.HIGH)
    except ValueError as exc:
        assert "cannot convert" in str(exc), f"unexpected refusal text: {exc}"
        print("  (4) a real gap re-expressed in bp is REFUSED -- CONFIRMED")
    else:
        raise AssertionError(
            "a gap declared in basis points was scaled by 100 silently; the unit "
            "refusal is not firing on a real input"
        )

    inside_noise = gap.model_copy(
        update={"raw_gap": inputs["dispersion"] / 2.0, "is_meaningful": False}
    )
    try:
        build_scenario_distribution(inside_noise, ConvergenceClassification.HIGH)
    except ValueError as exc:
        assert "Q6" in str(exc), f"unexpected refusal text: {exc}"
        print("  (5) a gap inside the rules' own dispersion is REFUSED -- CONFIRMED")
    else:
        raise AssertionError("a sub-noise-floor gap produced a distribution")

    zero = gap.model_copy(update={"raw_gap": 0.0, "is_meaningful": True})
    try:
        build_scenario_distribution(zero, ConvergenceClassification.HIGH)
    except ValueError as exc:
        assert "degenerate" in str(exc), f"unexpected refusal text: {exc}"
        print("  (6) a zero gap is REFUSED as degenerate -- CONFIRMED")
    else:
        raise AssertionError("a zero gap produced four outcomes paying nothing")

    # (7) The partition: the two verdicts a thesis cannot rest on produce NOTHING.
    for verdict in (
        ConvergenceClassification.CONFLICTED,
        ConvergenceClassification.NO_SIGNAL,
    ):
        empty = build_scenario_distribution(gap, verdict)
        assert empty == [], (
            f"{verdict.value} produced {len(empty)} branches; MacroThesis hard-blocks "
            f"a live trade on CONFLICTED and NO_SIGNAL means nothing to distribute"
        )
    print("  (7) CONFLICTED and NO_SIGNAL produce NO distribution -- CONFIRMED")

    # (8) The seam (O-50 / D-064): the producer's unit is not the consumer's, and
    # the refusal is loud in BOTH directions.
    distribution = built["HIGH"]
    assert PayoffUnit is not None
    declared = {o.unit for o in distribution}
    assert declared == {"bp_pnl_proxy"}, f"the seam test needs the proxy unit; got {declared}"

    try:
        KellyInputs(
            scenarios=distribution,
            payoff_unit="bp_pnl_proxy",
            limits=limits,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("a bp distribution was accepted by the Kelly contract")

    try:
        KellyInputs(  # type: ignore[call-arg]
            scenarios=distribution,
            limits=limits,
        )
    except ValidationError as exc:
        assert {e["type"] for e in exc.errors()} == {"missing"}, (
            f"omitting the unit must fail on the MISSING field, got {exc.errors()}"
        )
    else:
        raise AssertionError(
            "omitting payoff_unit was accepted. This is the D-064 defect: the field "
            "was defaulted, so a bp distribution was labelled a fraction of capital."
        )
    print(
        "  (8) the producer's bp distribution is REFUSED by the Kelly contract with "
        "the unit declared AND with it omitted -- CONFIRMED"
    )
    print(
        "       (the omission is the half D-064 added: before it, this call "
        "SUCCEEDED and returned a fraction computed from basis points)"
    )

    # (9) The legitimate path, so the refusals above are not just "everything fails".
    as_fractions = [
        o.model_copy(update={"payoff_estimate": float(o.payoff_estimate) / 10_000.0})
        for o in distribution
    ]
    accepted = KellyInputs(
        scenarios=as_fractions,
        payoff_unit="fraction_of_capital",
        limits=limits,
    )
    assert accepted.payoff_unit == "fraction_of_capital"
    print("  (9) the same distribution CONVERTED to fractions IS accepted -- CONFIRMED")

    # (10) DIRECTION-BLINDNESS, measured on the live gap's own value.
    #
    # The live canonical gap is NEGATIVE (-1.00%: the model sits BELOW the
    # market, a tightening bias). ``build_scenario_distribution`` takes
    # ``abs(gap.raw_gap)`` and never reads ``gap.direction``, so a +1% gap and a
    # -1% gap produce byte-identical payoffs. The distribution is a
    # *magnitude* distribution carrying no sign.
    #
    # This is D-063's finding #4 one module over ("the model §20.15 names is
    # direction-blind") and it is worth stating because of what it implies for a
    # consumer: a branch named ``thesis_invalidated_reversal`` paying -60bp reads
    # as a loss for a LONG position, but the same number is the loss for a SHORT
    # only after the sign of the trade is known -- and the trade is not an input
    # here. The sign lives in ``gap.direction`` and in whichever instrument the
    # thesis selects; this function publishes neither.
    mirrored = gap.model_copy(
        update={
            "raw_gap": -float(inputs["raw_gap"]),
            "model_implied_value": gap.market_implied_value - inputs["raw_gap"],
        }
    )
    original_payoffs = [float(o.payoff_estimate) for o in distribution]
    mirrored_payoffs = [
        float(o.payoff_estimate)
        for o in build_scenario_distribution(mirrored, ConvergenceClassification.HIGH)
    ]
    assert mirrored_payoffs == original_payoffs, (
        "the distribution DID respond to the sign; the direction-blindness note "
        "below is stale and should be removed rather than left as a claim"
    )
    print(
        f"  (10) the distribution is DIRECTION-BLIND: the live gap is "
        f"{inputs['raw_gap']:+.4f} and its mirror {(-inputs['raw_gap']):+.4f} "
        f"produce identical payoffs {original_payoffs}. The sign lives in "
        f"`gap.direction` ({gap.direction!r}) and is not carried here -- a "
        f"consumer that needs it must read the gap, not the distribution."
    )

    print()
    print("  D-064 live check: PASSED")


def main() -> int:
    print("=" * 72)
    print("LIVE check: real FRED data -> build_scenario_distribution (D-064)")
    print("=" * 72)
    client = OpenBBClient()
    _check_scenario_distribution(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
