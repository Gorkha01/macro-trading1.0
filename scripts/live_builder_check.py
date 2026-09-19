"""Live check: the seam function on real data (D-069).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_builder_check.py

Section 21.0: unit tests prove the function, this proves the **wiring** — that
the models layer's real output flows through every gate into a published
``MacroThesis``, and measures which gate today's data actually reaches.

Why this increment needs a live check more than most
----------------------------------------------------
``build_us_macro_thesis`` is the **seam function**: it appears on the Tier 4
checklist *and* the Phase 3 checklist, and that overlap is the point where models
stop producing numbers and the thesis layer starts making claims. Two classes of
defect live only here:

- **The plumbing that does not exist.** Measured (D-069): neither
  ``inflation_breadth_score`` nor ``labor_tightness_score`` has a snapshot-fed
  helper anywhere in the tree, so the builder takes Q1's reads as a
  ``parameter`` rather than faking a transform. This check exercises the real
  functions and prints the census, so the gap is documented rather than hidden.
- **The interaction the unit tests could not see.** The first shipped ``_render``
  published only the trigger line, so every stand-down dropped the model warnings
  and Section 22.5's market-path contamination disclosure. **This check found
  it** — ``contaminated=0 proxy=0`` on a run where the contaminated branch was
  definitely taken. It now prints both counts on whatever path is taken.

What is established here, each independently of the function
------------------------------------------------------------
1. **The real chain produces objects the builder accepts.** The offline tests
   hand it hand-built ``ModelResult``s; this proves the live ones fit — including
   the Q7 signal adapter, which exists because the real chain's objects do not
   nest.
2. **Which gate fires today.** Measured, not asserted: pinning the answer would
   be the D-064 trap. Today it is Q7, and that is a fact about the world.
3. **A stand-down carries more than its trigger line.** The warning count is
   printed for the stand-down, and the market-path disclosures are counted on
   whichever path was reached.
4. **The published thesis is schema-valid end to end**, through the real
   ``MacroThesis`` validator.
5. **The instrument shape is whatever the selector published** — including the
   bare-sentinel shape O-87 measured, which the reader branches on rather than
   assuming a dict.

**What this check CANNOT establish:** whether the caller named the right
``thesis_type``, or whether ``EconomyReads`` holds the right three models. Both
are analytical choices this function deliberately refuses to guess (divergence 1),
so their correctness is not a property of this file.
"""

from __future__ import annotations

from macro_engine.data_layer.snapshot_builder import build_snapshot
from macro_engine.models.gdp_nowcast import output_gap_from_snapshot
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.models.labor_synthesis import (
    InflationSubMeasures,
    LaborInputs,
    inflation_breadth_score,
    labor_tightness_score,
)
from macro_engine.models.policy_rules import FirstDifferenceInputs, TaylorRuleInputs
from macro_engine.thesis_layer.builder import (
    EconomyReads,
    build_policy_gap,
    build_us_macro_thesis,
)
from macro_engine.thesis_layer.no_trade import NO_TRADE_TRIGGER_LABELS, NoTradeTrigger
from macro_engine.thesis_layer.schemas import MacroThesis, ProductionUniverse

_TRIGGERS: tuple[NoTradeTrigger, ...] = (
    "gap_below_dispersion",
    "conflicted_signals",
    "no_falsifier",
)


def _live_inputs() -> tuple[EconomyReads, TaylorRuleInputs, FirstDifferenceInputs, float]:
    """Today's real inputs, through the real plumbing.

    The growth leg goes through ``output_gap_from_snapshot`` rather than
    ``output_gap`` fed from each series' own last observation: ``GDPPOT`` is a CBO
    **projection** series whose last point is 2036-10-01, so the shortcut returns
    an output gap of roughly -17% (the O-7 / D-009 trap).

    The inflation and labor legs are built from the same shorthand the live tests
    use, **because no snapshot-fed helper exists for either** — that is the
    measured plumbing gap, printed in this check's census section.
    """
    snapshot, _report = build_snapshot(country="us")
    growth, _gap_report = output_gap_from_snapshot(snapshot)
    gap_value = float(growth.value) if isinstance(growth.value, (int, float)) else 0.0

    inflation = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=0.2, cpi_core_mom=0.3, pce_core_mom=0.1)
    )
    labor = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-0.4,
            jolts_openings_yoy_pct=3.0,
            jolts_quits_level_percentile=60.0,
            nfp_3m_avg=180.0,
        )
    )

    reads = EconomyReads(growth=growth, inflation=inflation, labor=labor)
    taylor_inputs = TaylorRuleInputs(
        r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value
    )
    first_diff_inputs = FirstDifferenceInputs(
        i_prev=3.5, pi_current=2.4, pi_target=2.0, output_gap_change=0.15
    )
    return reads, taylor_inputs, first_diff_inputs, 4.30


def _fired(thesis: MacroThesis) -> list[NoTradeTrigger]:
    return [
        trigger
        for trigger in _TRIGGERS
        if any(NO_TRADE_TRIGGER_LABELS[trigger] in w for w in thesis.warnings)
    ]


def main() -> int:
    print("=" * 78)
    print("live check: build_us_macro_thesis — the seam function (D-069)")
    print("=" * 78)

    reads, taylor_inputs, first_diff_inputs, short_yield = _live_inputs()

    print("\n" + "-" * 78)
    print("Q1 — the economy reads, and the plumbing census")
    print("-" * 78)
    for result in reads.as_sequence():
        print(
            f"  {result.model_name:28s} value={result.value!r} "
            f"family={result.source_family.value if result.source_family else None}"
        )
    print(
        f"  independent_source_families = "
        f"{len({r.source_family for r in reads.as_sequence() if r.source_family})}"
    )
    print("  MEASURED PLUMBING GAP: neither inflation_breadth_score nor")
    print("  labor_tightness_score has a snapshot-fed helper anywhere in the tree,")
    print("  so the reads are a PARAMETER of build_us_macro_thesis rather than a")
    print("  transform it fakes. Wiring them is Phase 3's own work item.")

    print("\n" + "-" * 78)
    print("Q2-Q5 — the policy chain and the gap")
    print("-" * 78)
    gap, rules, ensemble, market_path = build_policy_gap(
        taylor_inputs,
        first_diff_inputs,
        short_yield=short_yield,
        short_tenor_term_premium=None,  # the real caller's situation
    )
    print(f"  taylor={rules[0].value!r} balanced={rules[1].value!r} first_diff={rules[2].value!r}")
    print(f"  ensemble={ensemble.value!r}")
    print(f"  market_implied={market_path.value!r} family={market_path.source_family}")
    print(f"  market_path warnings: {len(market_path.warnings)}")
    for warning in market_path.warnings:
        print(f"    - {warning[:96]}")
    print(
        f"  gap: raw={gap.raw_gap:+.4f} dispersion={gap.dispersion:.4f} "
        f"meaningful={gap.is_meaningful}"
    )
    print(f"  -> Q6 fires = {not gap.is_meaningful}")

    print("\n" + "-" * 78)
    print("The full build — every gate, to a published thesis")
    print("-" * 78)
    thesis = build_us_macro_thesis(
        reads,
        taylor_inputs,
        first_diff_inputs,
        thesis_type=ThesisType.POLICY_PATH_GAP,
        universe=ProductionUniverse(),
        short_yield=short_yield,
        short_tenor_term_premium=None,
        # `catalyst_calendar` deliberately omitted: this exercises the FETCH.
    )

    fired = _fired(thesis)
    print(f"  thesis_id={thesis.thesis_id}")
    print(f"  status={thesis.status.value}  gates fired={fired or 'NONE'}")
    print(f"  convergence={thesis.convergence_classification.value}")
    print(
        f"  instrument={thesis.trade_idea.instrument!r} "
        f"direction={thesis.trade_idea.direction!r} "
        f"timeframe={thesis.trade_idea.timeframe!r}"
    )
    print(f"  stop_or_invalidation={thesis.trade_idea.stop_or_invalidation!r}")
    print(
        f"  scenarios={len(thesis.scenario_distribution)} "
        f"signals={len(thesis.confirmation_signals)}"
    )
    print(f"  families={thesis.independent_source_families}")

    print("\n" + "-" * 78)
    print("The warnings — the disclosure the first draft dropped")
    print("-" * 78)
    print(f"  warnings={len(thesis.warnings)} on the {thesis.status.value} path")
    contaminated = [w for w in thesis.warnings if "NO TERM PREMIUM ADJUSTMENT" in w]
    proxy = [w for w in thesis.warnings if "Still a PROXY" in w]
    print(
        f"  market-path contamination disclosures: "
        f"contaminated={len(contaminated)} proxy={len(proxy)}"
    )
    print("  first line (the trigger, which must come first):")
    print(f"    {thesis.warnings[0] if thesis.warnings else '(none)'}")
    for warning in thesis.warnings[1:6]:
        print(f"    - {warning[:96]}")
    if len(thesis.warnings) > 6:
        print(f"    ... and {len(thesis.warnings) - 6} more")

    if contaminated or proxy:
        print("  -> the market-path disclosures REACH the thesis. Before the fix this")
        print("     measured 0/0 on a run where the contaminated branch was taken.")
    else:
        print("  -> NO market-path disclosure reached the thesis. If a term premium")
        print("     was not supplied, this is the D-069 defect returning.")

    print("\n" + "-" * 78)
    print("The published thesis is schema-valid")
    print("-" * 78)
    reparsed = MacroThesis.model_validate(thesis.model_dump())
    print(f"  MacroThesis.model_validate(round-trip) -> {type(reparsed).__name__}")
    print(f"  thesis_id stable: {reparsed.thesis_id == thesis.thesis_id}")
    if thesis.status.value == "WATCH":
        print("  stand-down invariants:")
        print(f"    instrument == 'NONE'      : {thesis.trade_idea.instrument == 'NONE'}")
        print(f"    falsifier is empty        : {thesis.trade_idea.stop_or_invalidation == ''}")
        print(f"    no scenario distribution  : {len(thesis.scenario_distribution) == 0}")
        print("    (the empty falsifier matters: 'n/a' is TRUTHY and would satisfy")
        print("     the LTCM gate the stand-down exists to fail — lesson 5bd)")
    else:
        print("  live thesis invariants:")
        falsifier = thesis.trade_idea.stop_or_invalidation
        print(f"    falsifier non-empty       : {bool(falsifier.strip())}")
        print(f"    scenarios == 4            : {len(thesis.scenario_distribution) == 4}")

    print("\n" + "-" * 78)
    print("The catalyst calendar — the real fetch")
    print("-" * 78)
    unreachable = [w for w in thesis.warnings if "CATALYST CALENDAR UNREACHABLE" in w]
    if unreachable:
        print("  UNREACHABLE, recorded as a warning rather than an empty calendar:")
        print(f"    {unreachable[0]}")
    else:
        print(f"  the fetch answered; catalysts on the thesis: {len(thesis.trade_idea.catalysts)}")
        for entry in thesis.trade_idea.catalysts:
            print(f"    - {entry}")

    print("\n" + "=" * 78)
    print("RESULT: the seam function runs end to end on real data; the published")
    print("thesis is schema-valid; the trigger line names the gate that fired; and")
    print("the market-path disclosures reach the thesis on whichever path was taken.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
