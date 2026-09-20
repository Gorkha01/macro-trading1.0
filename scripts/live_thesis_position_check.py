"""Live cross-check: ``translate_thesis_to_position`` against the REAL thesis path.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they exercise the real settings tree and the real
pipeline. Run with::

    uv run python scripts/live_thesis_position_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. For a
*sizing* function the wiring question is unusual and worth stating precisely,
because §9.3's input is not a series.

What is different about this live check
---------------------------------------

``live_risk_parity_check.py`` fetches a real multi-asset book and drives the
solver over an **estimated covariance**. This check cannot do that: §9.3's input
is a ``MacroThesis`` plus a risk budget, and a ``MacroThesis`` is the *output* of
five model layers, not a market object. So the wiring question is not "does it
reproduce a historical number" — it is:

    **does the function behave correctly on the theses the SYSTEM ACTUALLY
    PRODUCES today, and does it say the truth about the ones it cannot size?**

That is a strictly *harder* question than the unit tests answer, and the answer
is not the one a reader would guess. Every live US thesis today is a **NO-TRADE**
carrying the ``"NONE"`` sentinel, so the function refuses at gate 1 with a reason
that has to be right for reasons no unit test can see (the reasons are
constructed at runtime, and the no-trade branch is reached by a *different* route
than the universe branch).

The six things this check establishes
-------------------------------------

1. **The live pipeline is driven end to end.** The real memoized snapshot is
   built, ``snapshot_to_thesis_inputs`` derives the six builder arguments, and
   ``build_us_macro_thesis`` produces real theses for **all four** US thesis
   families §22.3.1 implements. Nothing here is a fixture: if the orchestration
   drifts from the builder's signature the check fails with the same
   ``TypeError`` §8.2's sample call produced.

2. **Every live thesis refuses at gate 1, and the reason is the NO-TRADE one.**
   Measured, ``status == WATCH`` on all four families, ``instrument == "NONE"``,
   ``scenario_distribution`` empty, ``scenario_sizing_permitted`` False. The
   function therefore *cannot* size anything today. That is a statement about the
   SYSTEM, not about the function, and a check that printed "PASSED" without
   saying so would let a reader believe a size was validated.

3. **Gate 2 is a REAL engine, not a formality — it fires on a thesis that
   passed gate 1.** A calibrated, in-universe thesis carrying a non-empty
   distribution still refuses, because ``scenario_sizing_permitted`` is
   ``status == "calibrated"`` and today's builder never writes ``calibrated``.
   This is the §25 prohibition being *live* rather than decorative: the gate
   would otherwise be a comment with a branch around it.

4. **The reachability census, measured rather than argued.** The 4 instruments x
   3 statuses x {empty, non-empty} cross-product is enumerated against the real
   validator, and each ``PositionTranslationOutcome`` member is counted. Three of
   the six are **unreachable from this input space**, and the check names them and
   says why that is not (yet) a defect — the exact distinction D-072 had to draw
   for a member that was unreachable *by construction*.

5. **The ``Literal`` is checked against the code, not against itself.** This is
   the D-070 discipline applied to a type: the declared member set is compared
   against the outcomes the census produces **plus** the outcomes reachable from
   the wider input space. A member no input can produce is the project's most
   frequently found defect class (D-045/D-046/D-048, O-53), and it is exactly
   what D-072 found and removed — **twice**, once for a dead mass check and once
   for a dead emptiness check.

6. **Gate 4 is re-verified as a PUBLISHED BOUND on the real config.** Across
   eight budgets from 0.01 to 1.00 the published fraction is asserted to be
   **identical** while ``permitted_risk_contribution`` tracks the allocation.
   This is the single most important live property in the increment: the first
   implementation of gate 4 *did* scale the size, and returned **0.018** where the
   answer was 0.12 — a 6.7x error that is invisible because 0.018 is a perfectly
   plausible position size.

Offline by design: the snapshot is read from the process-local cache when one
exists and built once otherwise. The check needs no *live market* fetch beyond
whatever ``get_snapshot`` itself does, because the object under validation is the
translation, not the data. "Live" here means "through the real settings tree and
the real call path", which is the part the unit tests stub out.
"""

from __future__ import annotations

import sys
from typing import Any, get_args

from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
from macro_engine.api_layer.snapshot_provider import get_snapshot
from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    ThesisType,
)
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.portfolio.risk_budget import (
    SIGN_OFF_REQUIRED,
    PositionBinding,
    PositionTranslationOutcome,
    RiskBudgetTarget,
    RiskLimits,
    ThesisPositionInputs,
    translate_thesis_to_position,
)
from macro_engine.thesis_layer.builder import build_us_macro_thesis
from macro_engine.thesis_layer.schemas import (
    NO_PRODUCTION_INSTRUMENT,
    ConvergenceClassification,
    MacroThesis,
    MarketPricingGap,
    ProductionUniverse,
    ThesisStatus,
    TradeIdea,
)

#: The four §22.3.1 families this build implements for ``us``. The two BLOCKED
#: members (``cross_country_divergence``, ``em_vulnerability``) are excluded by
#: Section 22.3, and the two analytical-only ones are exercised through the
#: universe instead of the builder: a family §22.12 excludes should refuse on the
#: universe, not fail to build.
_LIVE_FAMILIES: tuple[ThesisType, ...] = (
    ThesisType.POLICY_PATH_GAP,
    ThesisType.CURVE_SHAPE_GAP,
    ThesisType.INFLATION_EXPECTATIONS_GAP,
    ThesisType.EQUITY_MACRO,
)

#: A real instrument §22.12 permits. **Not** an ETF ticker: measured,
#: ``ProductionUniverse`` rejects ``"SPY"``/``"TLT"``/``"GLD"`` because §22.12
#: permits index roots and futures, not ETF shares. Asserted in section 6 rather
#: than trusted, because a typo here would turn every sizing assertion below into
#: a gate-1 refusal — the same trap ``tests/portfolio/test_thesis_position.py``
#: documents.
_IN_UNIVERSE = "TY futures"

#: A real instrument §22.12 excludes (credit is analytical-only).
_OUT_OF_UNIVERSE = "US HY credit spread"

#: The interior-optimum distribution: ``p=0.45`` on a ``+5%``/``-4%`` spread has
#: a growth-optimal fraction of exactly ``0.125``, strictly inside ``[0, 1]``, so
#: Kelly — not the cap — produces the number. Measured, not derived from the
#: spec text: every *symmetric* positive-edge pair pins ``f*`` at the grid edge
#: and clips, which is why this asymmetry is required to reach ``sized_by_kelly``.
_INTERIOR: tuple[tuple[float, float], ...] = ((0.45, 0.05), (0.55, -0.04))

#: The edge-pinned distribution: a favourable ``+20%``/``-5%`` edge drives ``f*``
#: to the grid's upper edge, so the CAP produces the number. The pair of the two
#: is what makes ``binding_constraint`` observable — with only one of them the
#: field could be a constant and the check would not know.
_EDGE: tuple[tuple[float, float], ...] = ((0.70, 0.20), (0.30, -0.05))

#: Budgets swept in section 4. Chosen to straddle the shipped position cap on
#: both sides, so "tighter" and "looser" are both exercised against the real leaf.
_BUDGETS: tuple[float, ...] = (0.01, 0.05, 0.10, 0.1499, 0.15, 0.30, 0.99, 1.0)


def _scenarios(pairs: tuple[tuple[float, float], ...]) -> list[ScenarioOutcome]:
    """Build a two-branch distribution from ``(probability, payoff)`` pairs."""
    return [
        ScenarioOutcome(name=f"branch{i}", probability=p, payoff_estimate=payoff)
        for i, (p, payoff) in enumerate(pairs)
    ]


def _thesis(
    *,
    instrument: str = _IN_UNIVERSE,
    status: str = "calibrated",
    scenarios: list[ScenarioOutcome] | None = None,
) -> MacroThesis:
    """The smallest ``MacroThesis`` the schema accepts, shaped as the builder shapes one.

    Deliberately **not** a copy of the unit-test fixture: it lives here so the
    operator script does not depend on the test package, and it is checked
    against the real ``MacroThesis`` validator on every construction (a schema
    change makes this check fail rather than silently pass a stale shape).
    """
    direction = "n/a" if instrument == NO_PRODUCTION_INSTRUMENT else "long"
    return MacroThesis(
        thesis_id="us-2026-09-20-livecheck",
        country="us",
        created_at=utc_now(),
        as_of=utc_now(),
        regime={"state": None},
        growth_view={"output_gap": None},
        inflation_view={"breadth_score": None},
        policy_view={},
        market_pricing_gap=MarketPricingGap(
            model_implied_value=4.5,
            market_implied_value=4.0,
            raw_gap=0.5,
            unit="%",
            dispersion=0.1,
            is_meaningful=True,
            interpretation="model 50bp above market",
        ),
        confirmation_signals=[],
        convergence_classification=ConvergenceClassification.HIGH,
        trade_idea=TradeIdea(
            instrument=instrument,
            direction=direction,
            timeframe="6-12 months",
            sizing_logic="Phase 1: human-determined",
            stop_or_invalidation="growth read turns negative for two consecutive prints",
        ),
        scenario_distribution=[] if scenarios is None else scenarios,
        scenario_distribution_status=status,  # type: ignore[arg-type]
        status=ThesisStatus.DRAFT,
        warnings=[],
    )


def _translate(
    thesis: MacroThesis,
    *,
    budget: float | None = None,
    budget_instrument: str | None = None,
) -> ModelResult:
    """Call the function under validation with the real input type."""
    target = (
        None
        if budget is None
        else RiskBudgetTarget(
            instrument=budget_instrument or thesis.trade_idea.instrument,
            target_risk_contribution_pct=budget,
        )
    )
    return translate_thesis_to_position(
        ThesisPositionInputs(thesis=thesis, risk_budget_target=target)
    )


def _value(result: ModelResult) -> dict[str, Any]:
    """Narrow ``ModelResult.value`` to a dict. Assert, never cast.

    ``ModelResult.value`` is typed as a union (a result may carry a scalar), so
    indexing needs a narrowing step. ``dict[str, Any]`` rather than
    ``dict[str, object]`` because mypy --strict rejects ``float(values["x"])`` on
    the latter — the same narrowing ``live_kelly_check.py`` uses.
    """
    value = result.value
    assert isinstance(value, dict), f"expected a dict value, got {type(value).__name__}"
    return value


def _as_float(result: ModelResult, key: str) -> float:
    """Read a scalar off the published value; rejects bool for the same reason."""
    entry = _value(result)[key]
    assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
        f"value[{key!r}] is {type(entry).__name__}, not numeric"
    )
    return float(entry)


def _as_str(result: ModelResult, key: str) -> str:
    """Read a string off the published value."""
    entry = _value(result)[key]
    assert isinstance(entry, str), f"value[{key!r}] is {type(entry).__name__}, not a str"
    return entry


def _live_theses() -> list[tuple[ThesisType, MacroThesis]]:
    """Build one real thesis per implemented US family, through the real pipeline.

    The snapshot is obtained with its provenance, and a **wholly failed** build
    raises rather than returning an empty snapshot (§8's contract), so a failure
    here is a genuine wiring failure — never a silent fall-back to fixtures.
    """
    snapshot, _provenance = get_snapshot()
    built: list[tuple[ThesisType, MacroThesis]] = []
    for family in _LIVE_FAMILIES:
        inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=family)
        thesis = build_us_macro_thesis(
            inputs.reads,
            inputs.taylor_inputs,
            inputs.first_difference_inputs,
            thesis_type=inputs.thesis_type,
            universe=inputs.universe,
            short_yield=inputs.short_yield,
            regime=inputs.regime,
        )
        built.append((family, thesis))
    return built


def _census() -> tuple[dict[str, list[str]], int]:
    """Enumerate 4 instruments x 3 statuses x {empty, non-empty} against the schema.

    Returns the cells that produced each ``PositionTranslationOutcome`` member,
    plus the count of cells the ``MacroThesis`` validator REFUSED. The refused
    count is reported rather than hidden: ``_enforce_scenario_status_matches_distribution``
    is two-directional, so 8 of the 24 nominal cells are not constructible, and a
    census that silently skipped them would understate the space it enumerated.
    """
    instruments: dict[str, str] = {
        "in-universe": _IN_UNIVERSE,
        "out-of-universe": _OUT_OF_UNIVERSE,
        "no-trade-sentinel": NO_PRODUCTION_INSTRUMENT,
        "analytical-sentinel": ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    }
    statuses: dict[str, str] = {
        "unavailable": "SCENARIO_DISTRIBUTION_UNAVAILABLE",
        "calibrated": "calibrated",
        "empty_no_trade": "empty_no_trade",
    }
    full = _scenarios(_INTERIOR)

    seen: dict[str, list[str]] = {member: [] for member in get_args(PositionTranslationOutcome)}
    refused_by_schema = 0
    for instrument_name, instrument in instruments.items():
        for status_name, status in statuses.items():
            for label, scenarios in (("nonempty", full), ("empty", [])):
                if status == "empty_no_trade":
                    distribution: list[ScenarioOutcome] = []
                else:
                    distribution = scenarios
                try:
                    thesis = _thesis(instrument=instrument, status=status, scenarios=distribution)
                except ValueError:
                    refused_by_schema += 1
                    continue
                outcome = _as_str(_translate(thesis), "outcome")
                seen[outcome].append(f"{instrument_name}/{status_name}/{label}")
    return seen, refused_by_schema


def main() -> int:
    settings = get_settings()
    limits = RiskLimits.from_settings()
    cap = limits.max_position_pct_of_portfolio
    divisor = settings.kelly.divisor

    print("=" * 78)
    print("live check: translate_thesis_to_position (Module 17.4, Section 9.3)")
    print(f"config: divisor {divisor}  position cap {cap}")
    print(
        f"literal: {len(get_args(PositionTranslationOutcome))} outcomes  "
        f"{len(get_args(PositionBinding))} bindings"
    )
    print("=" * 78)

    # --- 1. the REAL pipeline, end to end ----------------------------------
    print()
    print("1. THE REAL PIPELINE: snapshot -> orchestration -> builder -> translator")
    print(
        "   Six builder arguments derived by snapshot_to_thesis_inputs, the builder\n"
        "   called with its real (six-argument) signature, one thesis per implemented\n"
        "   US family. Nothing here is a fixture.\n"
    )
    live = _live_theses()
    assert len(live) == len(_LIVE_FAMILIES), "one thesis per family, or the loop lied"

    live_outcomes: list[str] = []
    for family, thesis in live:
        idea = thesis.trade_idea
        result = _translate(thesis)
        outcome = _as_str(result, "outcome")
        live_outcomes.append(outcome)
        print(
            f"   {family.value:30s} status={thesis.status.value:6s} "
            f"scen={thesis.scenario_distribution_status:16s} "
            f"n={len(thesis.scenario_distribution)} "
            f"instr={idea.instrument!r:8s} -> {outcome}"
        )
    assert len(set(live_outcomes)) == 1, (
        "all four live families must reach the same outcome, or the description "
        "of today's system below is wrong for at least one of them"
    )
    assert live_outcomes[0] == "refused_not_a_trade", (
        f"every live US thesis today is a NO-TRADE; measured {live_outcomes[0]!r}. "
        f"If this changes, the paragraphs in section 1 and WHAT THIS CHECK CANNOT "
        f"VALIDATE are stale and must be rewritten -- a check that keeps printing "
        f"the old story after the system moves is worse than no check."
    )
    assert all(t.trade_idea.instrument == NO_PRODUCTION_INSTRUMENT for _, t in live), (
        "the refusal must come from the no-trade sentinel, not from a coincidence "
        "of the universe matcher"
    )
    print()
    print("   -> ALL FOUR refuse at GATE 1 with the no-trade sentinel. The function")
    print("      cannot size anything the system produces today, and the reason it")
    print("      gives is the Q6/Q7/Q8 stand-down sentence, not the universe one.")

    # --- 2. the two sentinels are different strings -------------------------
    print()
    print("2. THE TWO SENTINELS, and why the check distinguishes them")
    print(
        "   Measured fact, contradicted by four doc sites until D-072 (**O-93**):\n"
        "   NO_PRODUCTION_INSTRUMENT == 'NONE' but the analytical-only sentinel is\n"
        "   its OWN NAME. TradeIdea.is_trade tests only the first, so the analytical\n"
        "   sentinel passes is_trade=True -- it reads as a live trade in an\n"
        "   unexecutable instrument, which is why gate 1 needs BOTH checks.\n"
    )
    assert NO_PRODUCTION_INSTRUMENT == "NONE", (
        "the no-trade sentinel is the literal 'NONE'; four docs claimed the "
        "analytical sentinel was also 'NONE', which was a documentation defect "
        "(O-93) rather than a code fact"
    )
    assert ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT != NO_PRODUCTION_INSTRUMENT

    universe = ProductionUniverse()
    permits = {
        name: universe.permits(name)
        for name in (
            _IN_UNIVERSE,
            "EURUSD",
            "SPY",
            "TLT",
            "GLD",
            _OUT_OF_UNIVERSE,
            NO_PRODUCTION_INSTRUMENT,
            ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
        )
    }
    for name, permitted in permits.items():
        print(f"   permits({name!r:42s}) = {permitted}")
    assert permits[_IN_UNIVERSE], "the sizing fixture must be IN the universe"
    assert permits["EURUSD"], "Section 22.12: FX is a permitted category"
    assert not permits[_OUT_OF_UNIVERSE], "Section 22.12 excludes credit"
    assert not permits[ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT], (
        "the analytical sentinel is NOT executable -- this is what makes gate 1's "
        "second check load-bearing rather than decorative"
    )
    # The trap the check exists to catch: ETF shares are NOT permitted. A sizing
    # assertion built on a ticker would be a gate-1 refusal wearing a pass.
    assert not any(permits[t] for t in ("SPY", "TLT", "GLD")), (
        "ETF shares are out of universe by design -- if this ever changes, the "
        "fixture choice in this file stops being a guard and becomes an accident"
    )
    print("   -> the universe separates FX/futures/index roots from ETF shares and")
    print("      credit, and the analytical sentinel is refused by it. The no-trade")
    print("      sentinel is NOT -- it is a legal instrument value (O-53).")
    print(f"      permits('NONE') = {permits[NO_PRODUCTION_INSTRUMENT]} is exactly why")
    print("      gate 1 cannot rely on the universe alone.")

    # --- 3. gate 2 fires on a thesis that passed gate 1 ---------------------
    print()
    print("3. GATE 2 IS LIVE, not a comment with a branch around it")
    print(
        "   A calibrated, in-universe, non-empty thesis reaches gate 1's second\n"
        "   check and passes. It STILL refuses -- because Section 25 permits Kelly\n"
        "   sizing only from a calibrated distribution, and the live builder never\n"
        "   writes that status.\n"
    )
    uncalibrated = _thesis(
        status="SCENARIO_DISTRIBUTION_UNAVAILABLE", scenarios=_scenarios(_INTERIOR)
    )
    result = _translate(uncalibrated)
    assert _as_str(result, "outcome") == "refused_scenarios_uncalibrated", (
        "the §25 prohibition must be an enforced gate, not a documented intent"
    )
    assert _as_float(result, "fraction_of_capital") == 0.0
    print(f"   outcome: {_as_str(result, 'outcome')}")
    print(f"   reason:  {_value(result)['reason'][:150]}...")
    print("   -> the gate subsumes the old 'is there a distribution?' check: the")
    print("      predicate is status-only, and the schema ties status to the")
    print("      distribution. That fact is what made D-072's third gate dead code.")

    # --- 4. gate 4 is a PUBLISHED BOUND, never a multiplier -----------------
    print()
    print("4. GATE 4: the budget is PUBLISHED, never applied")
    print(
        "   The first implementation of this gate multiplied a capital fraction by\n"
        "   a risk share and returned 0.018 where the answer is 0.12 -- a 6.7x\n"
        "   understatement that is invisible because 0.018 is a plausible size.\n"
        "   The invariant asserted here is that NO budget changes the published\n"
        "   fraction, while permitted_risk_contribution tracks the allocation.\n"
    )
    sized = _thesis(status="calibrated", scenarios=_scenarios(_INTERIOR))
    base_result = _translate(sized)
    assert _as_str(base_result, "outcome") == "sized_by_kelly", (
        f"the interior fixture must reach sized_by_kelly; measured "
        f"{_as_str(base_result, 'outcome')!r}. A symmetric pair pins f* at the grid "
        f"edge and clips, so the asymmetry is load-bearing."
    )
    base = _as_float(base_result, "fraction_of_capital")
    print(
        f"   reference: f*={_as_float(base_result, 'requested_fraction_of_capital'):.6f} "
        f"/ {divisor} = {base:.6f}  (cap {cap})"
    )
    print()
    print("   budget   published fraction   binding          permitted_rc   same?")
    for budget in _BUDGETS:
        with_budget = _translate(sized, budget=budget)
        fraction = _as_float(with_budget, "fraction_of_capital")
        binding = _as_str(with_budget, "binding_constraint")
        # Named `bound_rc` rather than `permitted`: `permitted` is bound to a BOOL
        # by section 2's universe loop, and reusing the name here made mypy
        # --strict read this as a bool assignment. The collision is a real
        # readability hazard too -- `permits` (the universe dictionary) and
        # `permitted` (a risk bound) are different quantities one letter apart,
        # which is the kind of naming a reader has to re-derive at every use.
        bound_rc = _as_float(with_budget, "permitted_risk_contribution")
        same = fraction == base
        budget_label = f"{budget:.4f}"
        print(f"   {budget_label:8s} {fraction:18.10f}   {binding:15s}  {bound_rc:12.4f}   {same}")
        assert same, (
            f"the risk budget scaled the size: {budget} moved the published "
            f"fraction from {base} to {fraction}. A risk share is not convertible "
            f"to a notional without a covariance (Section 9.3 supplies none), and "
            f"this is the D-072 unit error returning."
        )
        assert bound_rc == budget, "permitted_risk_contribution must BE the allocation"
        assert binding == "kelly", (
            "the binding constraint names what produced the NUMBER; a risk budget "
            "that did not produce it must not claim to have"
        )
    print("   -> 8 of 8 budgets leave the NUMBER untouched and the BOUND tracking.")
    print("      The allocation is identical to permitted_risk_contribution in every")
    print("      row, which is what makes 'published, not applied' measurable.")

    # --- 5. the binding constraint distinguishes two producers ---------------
    print()
    print("5. binding_constraint NAMES THE PRODUCER, and changes with the input")
    print(
        "   Two theses with the SAME instrument, status and budget but different\n"
        "   distributions reach two different bindings. With only one of them the\n"
        "   field could be a constant and this check would not know -- the O-89\n"
        "   pattern, where a 'live branch' is proved by varying the input rather\n"
        "   than by reading the code.\n"
    )
    edge_result = _translate(_thesis(status="calibrated", scenarios=_scenarios(_EDGE)))
    edge_binding = _as_str(edge_result, "binding_constraint")
    edge_fraction = _as_float(edge_result, "fraction_of_capital")
    edge_requested = _as_float(edge_result, "requested_fraction_of_capital")
    interior_binding = _as_str(base_result, "binding_constraint")
    print(
        f"   interior p=0.45 +5%/-4%  -> {interior_binding:15s} "
        f"frac={base:.6f} req={_as_float(base_result, 'requested_fraction_of_capital'):.6f}"
    )
    print(
        f"   edge     p=0.70 +20%/-5% -> {edge_binding:15s} "
        f"frac={edge_fraction:.6f} req={edge_requested:.6f}"
    )
    assert interior_binding == "kelly", "the interior optimum is Kelly's number"
    assert edge_binding == "position_limit", (
        "the edge-pinned optimum exceeds the cap, so the CAP produced the number"
    )
    assert edge_fraction == cap, "a clipped size must equal the cap exactly"
    assert edge_requested > cap, (
        "the pre-clip request must be published ABOVE the cap, or D-057's P5 "
        "(a binding cap destroying conviction information) is back"
    )
    # And the binding does not move when a budget arrives: two facts, two fields.
    for budget in (0.12, 0.02):
        moved = _translate(_thesis(status="calibrated", scenarios=_scenarios(_EDGE)), budget=budget)
        assert _as_str(moved, "binding_constraint") == "position_limit", (
            "a budget that is tighter than the cap must NOT take over the binding: "
            "the cap produced the number and the budget is the binding POLICY. A "
            "draft that set binding='missing_risk_budget' discarded that fact."
        )
    print("   -> the binding tracks the PRODUCER and survives a budget on both sides")
    print(f"      of the cap ({cap}). Two facts, two fields.")

    # --- 6. the reachability census -----------------------------------------
    print()
    print("6. REACHABILITY CENSUS: 4 instruments x 3 statuses x {empty, non-empty}")
    print()
    seen, refused_by_schema = _census()
    print(
        f"   nominal cells: 24   schema-refused: {refused_by_schema}   "
        f"measured: {sum(len(v) for v in seen.values())}"
    )
    print()
    for member in get_args(PositionTranslationOutcome):
        cells = seen[member]
        example = cells[0] if cells else "--"
        print(f"   {member:34s} {len(cells):2d} cell(s)   {example}")
    unreached = [member for member in get_args(PositionTranslationOutcome) if not seen[member]]
    print()
    print(f"   unreachable from this space: {unreached}")
    assert sum(len(v) for v in seen.values()) + refused_by_schema == 24, (
        "the census must account for every cell -- a silent skip understates the "
        "space it claims to have enumerated"
    )
    # `refused_not_a_trade` and `refused_scenarios_uncalibrated` carry the space.
    # `clipped_by_position_limit` needs the artificial favourable edge; the two
    # remaining refusals and `sized_by_kelly` need inputs the census grid does not
    # vary (see below).
    assert "refused_not_a_trade" in seen, "gate 1 must be reachable"
    assert "refused_scenarios_uncalibrated" in seen, "gate 2 must be reachable"

    # --- 7. the declared Literal vs the code -------------------------------
    print()
    print("7. THE DECLARED Literal, checked against the CODE (the D-070 discipline)")
    print(
        "   D-070's lesson one type over: a declaration is a CLAIM. The members\n"
        "   that this census does not reach are re-checked against the code paths\n"
        "   and code comments, and each must have a named producer.\n"
    )
    # The three the census grid does not reach, with the reason each IS reachable
    # from the wider input space. Asserted by driving it, not by asserting the
    # claim: a member whose only evidence is a comment is the defect class itself.
    print("   member                        produced by")
    print(f"   {'refused_not_a_trade':30s} gate 1 (2 sub-branches: sentinel / universe)")
    print(f"   {'refused_scenarios_uncalibrated':30s} gate 2")
    print(f"   {'refused_no_edge':30s} gate 3, Kelly's own zero-growth decision")

    no_edge = _thesis(
        status="calibrated",
        scenarios=_scenarios((("0.50", 0.02), ("0.50", -0.10))),  # type: ignore[arg-type]
    )
    no_edge_result = _translate(no_edge)
    assert _as_str(no_edge_result, "outcome") == "refused_no_edge", (
        "gate 3 must be reachable by a positive-EV-but-zero-growth distribution: "
        "a positive expected VALUE is not sufficient (LTCM's positions were +EV)"
    )
    print(f"   {'refused_no_risk_budget':30s} gate 4, a ZERO allocation")
    zero_budget = _translate(
        _thesis(status="calibrated", scenarios=_scenarios(_INTERIOR)), budget=0.0
    )
    assert _as_str(zero_budget, "outcome") == "refused_no_risk_budget", (
        "a zero allocation is a decision, not a small number -- it must be its own "
        "outcome rather than a multiplier of zero"
    )
    assert _as_float(zero_budget, "permitted_risk_contribution") == 1.0, (
        "nothing was sized, so nothing bounded it; the refusal reports 1.0"
    )
    print(f"   {'sized_by_kelly':30s} gate 3 with an INTERIOR optimum")
    print(f"   {'clipped_by_position_limit':30s} gate 3 clipped by the cap")
    print()
    assert set(get_args(PositionTranslationOutcome)) == {
        "refused_not_a_trade",
        "refused_scenarios_uncalibrated",
        "refused_no_edge",
        "refused_no_risk_budget",
        "sized_by_kelly",
        "clipped_by_position_limit",
    }, (
        "the member set changed. Re-derive the producers for the new member(s) in "
        "this section before accepting the change: a member with no producer is "
        "D-045/D-046/D-048/O-53, and D-072 removed two of exactly that."
    )
    print("   -> all 6 members have a demonstrated producer, and the declared set is")
    print("      asserted rather than read back. 'Exhaustive' is the claim this")
    print("      section exists to keep honest.")

    # --- 8. the sign-off gate survives EVERY outcome ------------------------
    print()
    print("8. THE SIGN-OFF GATE survives every outcome, including the refusals")
    print(
        "   Section 9.3's constant is the whole difference between a reasoning\n"
        "   layer and a signal generator (Section 1.1). A caller that strips it, or\n"
        "   an edit that rewords it at one site, changes what the output promises\n"
        "   without changing a number in it.\n"
    )
    every_outcome = [
        # The no-trade STAND-DOWN proper: the sentinel AND `empty_no_trade`, which
        # is the pair the builder produces and the only combination that reaches
        # gate 1's sentinel branch. A sentinel with a non-empty distribution is a
        # different (schema-legal, builder-impossible) input and reaches gate 1's
        # explicit comparison too -- but labelling THIS row "gate 1 (sentinel)"
        # while passing `status="calibrated"` measured gate 2 instead, on the
        # check's first run: the label was a claim the input did not support.
        (
            "gate 1 (sentinel)",
            _translate(_thesis(instrument=NO_PRODUCTION_INSTRUMENT, status="empty_no_trade")),
        ),
        (
            "gate 1 (universe)",
            _translate(
                _thesis(
                    instrument=_OUT_OF_UNIVERSE,
                    status="calibrated",
                    scenarios=_scenarios(_INTERIOR),
                )
            ),
        ),
        (
            "gate 2",
            _translate(
                _thesis(status="SCENARIO_DISTRIBUTION_UNAVAILABLE", scenarios=_scenarios(_INTERIOR))
            ),
        ),
        ("gate 3 (no edge)", no_edge_result),
        ("gate 4 (zero budget)", zero_budget),
        ("gate 3 (sized)", base_result),
        ("gate 3 (clipped)", edge_result),
    ]
    zero_size_on_refusal = 0
    for label, output in every_outcome:
        outcome = _as_str(output, "outcome")
        assert SIGN_OFF_REQUIRED in output.warnings, (
            f"{label} -> {outcome} dropped the mandated sign-off sentence"
        )
        if outcome.startswith("refused_"):
            zero_size_on_refusal += 1
            assert _as_float(output, "fraction_of_capital") == 0.0
            assert _as_float(output, "requested_fraction_of_capital") == 0.0
            assert _as_float(output, "notional_fraction_after_constraints") == 0.0
            assert _as_str(output, "binding_constraint") == "none"
        print(f"   {label:22s} -> {outcome:32s} sign-off: YES")
    assert zero_size_on_refusal == 5, (
        f"expected 5 refusal paths; measured {zero_size_on_refusal}. "
        f"live_kelly_check.py prints 'A refusal without a reason is "
        f"indistinguishable from a bug' -- and a refusal with a size is worse."
    )
    print("   -> every path carries the sentence, and all 5 refusals publish three")
    print("      zeros and binding='none'. The three-field check is the M8.1 repair:")
    print("      the shipped guard tested two fields, and a refusal carrying a")
    print("      requested_fraction_of_capital=0.05 was ACCEPTED.")

    # --- 9. what this check cannot validate --------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * Whether the SIZING IS RIGHT. Nothing here can say whether p=0.45 is\n"
        "    the correct belief. Section 4 validates the arithmetic over a stated\n"
        "    distribution, which is strictly weaker than the size being correct --\n"
        "    the same limit live_kelly_check.py states about its own probabilities."
    )
    print(
        "  * Whether the PROBABILITIES ARE CALIBRATED. Every live thesis is\n"
        "    refused at gate 1, so no live distribution has ever been sized from.\n"
        "    The calibrated path is exercised on a constructed distribution, which\n"
        "    means the SHIPPED system has never produced a size -- a fact about\n"
        "    this system that a green tick would otherwise hide."
    )
    print(
        "  * Q12's EXPOSURE HALF. The function sizes ONE instrument against a\n"
        "    stated budget and does not verify the resulting book's factor\n"
        "    concentration, which needs the axe's loadings (Module 18, Phase 5+).\n"
        "    That is the O-93 half this increment deliberately does not answer, and\n"
        "    the output says so on every result."
    )
    print(
        "  * Whether the RISK BUDGET IS REACHABLE. Gate 4 has no covariance, so it\n"
        "    cannot know whether a 12% risk allocation is achievable in this\n"
        "    instrument at this size. `compute_risk_parity_weights` is the function\n"
        "    that can answer it; this one publishes the bound and says so."
    )
    print(
        "  * Whether the WIRING EXISTS. The function is not yet called from\n"
        "    `thesis_layer/builder.py`: the risk axis's hook is a SEPARATE increment\n"
        "    (D-072's docstring says why -- the hook changes the builder's signature,\n"
        "    and shipping the function first lets the hook be reviewed as wiring\n"
        "    rather than as wiring PLUS an algorithm). Nothing in this check proves\n"
        "    the translator is reachable from the API."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
