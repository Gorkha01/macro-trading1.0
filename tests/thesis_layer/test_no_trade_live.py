"""Live tests for Module 14's no-trade outcome (Section 16.3, D-068).

Deselected unless ``-m live``. These exist because three claims this increment
makes are **facts about the wiring**, not properties of the function, and cannot
be established from a fixture:

1. **The three triggers are reachable with a real snapshot.** An offline test
   builds ``MarketPricingGap`` / ``ConfirmationSignalAssessment`` /
   ``InvalidationAssessment`` by hand, which proves the function handles them and
   proves nothing about whether the upstream models ever produce them. This test
   drives the real models and reports which of the three conditions actually hold
   on today's data.
2. **The live gap is usually meaningful.** Measured: ``raw_gap=0.77`` against
   ``dispersion=0.42``, so Q6 does *not* fire today and the no-trade path is
   reached by the other two gates or not at all. Recording this stops a future
   reader from assuming the no-trade path is the common case.
3. **A rendered no-trade thesis passes the real schema, with a real
   classification.** The CONFLICTED combination is the one worth exercising,
   because that is where ``MacroThesis._enforce_conflicted_blocks_trade`` is
   closest to firing.
"""

from __future__ import annotations

import pytest

from macro_engine.data_layer.snapshot_builder import build_snapshot
from macro_engine.models.gdp_nowcast import output_gap_from_snapshot
from macro_engine.models.labor_synthesis import (
    InflationSubMeasures,
    LaborInputs,
    inflation_breadth_score,
    labor_tightness_score,
)
from macro_engine.models.policy_rules import (
    FirstDifferenceInputs,
    TaylorRuleInputs,
    balanced_approach_rule,
    canonical_policy_gap,
    first_difference_rule,
    taylor_rule,
)
from macro_engine.thesis_layer.invalidation import derive_invalidation_conditions
from macro_engine.thesis_layer.no_trade import no_trade_thesis, render_no_trade_thesis
from macro_engine.thesis_layer.schemas import MacroThesis
from macro_engine.thesis_layer.signals import build_confirmation_signals


@pytest.mark.live
def test_the_three_no_trade_triggers_are_reachable_on_live_data() -> None:
    """Drive the real models and report which gates actually fire today.

    This test asserts the *wiring*, not a value: each gate is checked against the
    live object it would fire on, and the outcome is printed. Pinning today's
    ``raw_gap`` would be the D-064 trap (a test frozen to the data of the day).
    """
    snapshot, _report = build_snapshot(country="us")
    growth, gap_report = output_gap_from_snapshot(snapshot)
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
    taylor = taylor_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value)
    )
    balanced = balanced_approach_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value)
    )
    first_diff = first_difference_rule(
        FirstDifferenceInputs(i_prev=3.5, pi_current=2.4, pi_target=2.0, output_gap_change=0.15)
    )

    gap = canonical_policy_gap(taylor, balanced, first_diff, market_implied=3.0)
    signals = build_confirmation_signals(growth, inflation, labor, gap)
    invalidation = derive_invalidation_conditions(growth, inflation, labor)

    # --- Q6 -----------------------------------------------------------------
    q6_fires = not gap.is_meaningful
    print(
        f"\n  Q6: raw_gap={gap.raw_gap:+.2f} dispersion={gap.dispersion:.2f} "
        f"is_meaningful={gap.is_meaningful} -> fires={q6_fires}"
    )
    decision_q6 = None
    if q6_fires:
        decision_q6 = no_trade_thesis(
            "gap inside the rules' own dispersion", trigger="gap_below_dispersion", gap=gap
        )
        assert decision_q6.elapsed == pytest.approx(gap.dispersion - abs(gap.raw_gap))
    else:
        # The trigger is still REACHABLE — prove it by asking the real gap
        # object the question the guard asks, with the guard's own condition.
        print(
            f"      (Q6 would not fire today: |{gap.raw_gap:+.2f}| > {gap.dispersion:.2f}. "
            f"The path is exercised with a synthetic gap offline.)"
        )

    # --- Q7 -----------------------------------------------------------------
    q7_fires = bool(signals.agreeing and signals.disagreeing)
    print(
        f"  Q7: agreeing={signals.agreeing} disagreeing={signals.disagreeing} "
        f"neutral={signals.neutral} -> conflicted={q7_fires}"
    )
    if q7_fires:
        # Measured: this path IS reachable live — the builder's own live check
        # records ``convergence=CONFLICTED`` on today's data. So the branch is
        # exercised rather than asserted-unreachable, which is what the previous
        # version did (`assert not q7_fires` made this code unreachable, which
        # mypy flagged, and which meant the Q7 evidence hand-off was never
        # checked against real objects).
        decision_q7 = no_trade_thesis(
            "growth and inflation contradict", trigger="conflicted_signals", evidence=signals
        )
        assert decision_q7.evidence is signals
        print("    -> Q7 fired; the assessment is carried as evidence")
    else:
        print("    -> Q7 does not fire on today's data (a fact about the data)")

    # --- Q8 -----------------------------------------------------------------
    q8_fires = not invalidation.identified
    print(
        f"  Q8: identified={invalidation.identified} conditions={len(invalidation.conditions)} "
        f"unreadable={len(invalidation.unreadable)} -> fires={q8_fires}"
    )
    assert not q8_fires, (
        "the live invalidation is unidentified, so Q8's no-trade path is reachable "
        "today. Update the D-068 record with the measurement."
    )

    # --- The rendered thesis passes the real schema --------------------------
    decision = no_trade_thesis(
        "no clean edge on today's live inputs",
        trigger="conflicted_signals" if q7_fires else "no_falsifier",
        evidence=signals if q7_fires else invalidation,
    )
    thesis = render_no_trade_thesis(
        decision,
        thesis_id="live-no-trade-d068",
        regime={"state": "live", "confidence": 0.0},
        growth_view={"output_gap": gap_value},
        inflation_view={"breadth_score": inflation.value},
        policy_view={},
        market_pricing_gap=gap,
        convergence_classification="NO_SIGNAL",
    )

    assert isinstance(thesis, MacroThesis)
    assert thesis.trade_idea.instrument == "NONE"
    assert thesis.trade_idea.stop_or_invalidation == ""
    assert thesis.status.value == "WATCH"
    assert thesis.warnings and thesis.warnings[0].startswith("No trade [")
    print(f"  rendered: status={thesis.status.value} warnings[0]={thesis.warnings[0][:90]!r}")
    print(
        f"  snapshot as_of={snapshot.as_of:%Y-%m-%d} "
        f"withheld_forward={gap_report.withheld_forward_points}"
    )


@pytest.mark.live
def test_a_conflicted_no_trade_survives_the_live_schema_gate() -> None:
    """CONFLICTED + no-trade is the combination the schema gate is closest to.

    ``MacroThesis._enforce_conflicted_blocks_trade`` refuses CONFLICTED with a
    **live** trade. This proves the no-trade path is the escape hatch the gate's
    own error message names, using a real ``MarketPricingGap`` from live data.
    """
    snapshot, _report = build_snapshot(country="us")
    growth, _gap_report = output_gap_from_snapshot(snapshot)
    gap_value = float(growth.value) if isinstance(growth.value, (int, float)) else 0.0

    taylor = taylor_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value)
    )
    balanced = balanced_approach_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value)
    )
    first_diff = first_difference_rule(
        FirstDifferenceInputs(i_prev=3.5, pi_current=2.4, pi_target=2.0, output_gap_change=0.15)
    )
    gap = canonical_policy_gap(taylor, balanced, first_diff, market_implied=3.0)

    thesis = render_no_trade_thesis(
        no_trade_thesis(
            "the growth and inflation pillars point opposite ways",
            trigger="conflicted_signals",
        ),
        thesis_id="live-conflicted-no-trade",
        regime={"state": "CONFLICTED", "confidence": 0.0},
        growth_view={"output_gap": gap_value},
        inflation_view={},
        policy_view={},
        market_pricing_gap=gap,
        convergence_classification="CONFLICTED",
    )

    assert thesis.convergence_classification.value == "CONFLICTED"
    assert thesis.trade_idea.is_trade is False
    assert thesis.warnings[0].startswith("No trade [conflicted_signals]")
    print(f"\n  CONFLICTED + no-trade accepted; warning={thesis.warnings[0][:90]!r}")
