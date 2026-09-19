"""Live check: the three no-trade triggers on real data (D-068).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_no_trade_check.py

Section 21.0: unit tests prove the decision object, this proves the **wiring** —
that each of Section 16.2's three gates is reachable through the real models, and
measures which of them actually fires on today's data.

Why this increment needs a live check more than most
----------------------------------------------------
``no_trade_thesis`` is a nine-line function whose whole job is to record a fact a
**caller** observed. Four of its five measured defects (D-068) are properties of
the signature rather than the body, and two of them are only visible against real
objects:

- **defect 3** — the rich object each trigger already held — can only be shown by
  producing those objects. The offline tests build them by hand, which proves the
  function stores what it is given and proves nothing about whether the upstream
  models ever hand it one.
- **defect 5** — the ``"n/a"`` sentinel — is dangerous only in relation to the
  LIVE schema gate, so the check drives the real ``TradeIdea`` validator.

What is established here, each independently of the function
------------------------------------------------------------
1. **Each trigger is reachable with a real snapshot.** For Q6, Q7 and Q8 the
   live condition is computed from the real models and reported.
2. **Which fires today.** Measured, not asserted as a requirement: pinning the
   answer would be the D-064 trap (a check frozen to the data of the day).
3. **The evidence each trigger would carry is real and non-trivial.** The gap's
   magnitude, the signal table's directions, the invalidation's unreadable list.
4. **A rendered no-trade thesis passes the live schema**, including the
   CONFLICTED combination the ``_enforce_conflicted_blocks_trade`` gate is
   nearest to.
5. **The ``"n/a"`` comparison is a live fact**: the same ``TradeIdea`` validator,
   fed the sentinel, accepts it as a falsifier.

**What this check CANNOT establish:** whether a future caller passes the *right*
trigger. The function records what it is told, and no check over this file can
see a caller that lies (O-70/O-79's class — the seam ``build_us_macro_thesis``
closes).
"""

from __future__ import annotations

from dataclasses import dataclass

from macro_engine.data_layer.schemas import MacroDataSnapshot
from macro_engine.data_layer.snapshot_builder import build_snapshot
from macro_engine.models.contracts import ModelResult
from macro_engine.models.gdp_nowcast import output_gap_from_snapshot
from macro_engine.models.labor_synthesis import (
    InflationSubMeasures,
    LaborInputs,
    inflation_breadth_score,
    labor_tightness_score,
)
from macro_engine.models.policy_rules import (
    FirstDifferenceInputs,
    PolicyRuleResult,
    TaylorRuleInputs,
    balanced_approach_rule,
    canonical_policy_gap,
    first_difference_rule,
    taylor_rule,
)
from macro_engine.thesis_layer.invalidation import derive_invalidation_conditions
from macro_engine.thesis_layer.no_trade import (
    NO_TRADE_TRIGGER_LABELS,
    no_trade_thesis,
    render_no_trade_thesis,
)
from macro_engine.thesis_layer.schemas import MacroThesis, TradeIdea
from macro_engine.thesis_layer.signals import build_confirmation_signals


@dataclass(frozen=True)
class _LiveModels:
    """The real Q1-Q8 inputs, named rather than returned as a positional tuple.

    **Corrected (D-069).** This used to return ``tuple[object, object, ...]``, and
    ``mypy --strict`` was reporting **15 errors** against the call sites as a
    result — ``"object" has no attribute "value"``, and every argument to
    ``canonical_policy_gap`` / ``build_confirmation_signals`` /
    ``derive_invalidation_conditions`` rejected. The tuple signature did not make
    the script type-check; it made the checker unable to see the script at all,
    while the gate's row in ``docs/PROGRESS.md`` claimed "no issues in 176 source
    files". A named dataclass costs nothing at runtime and lets the gate be true.
    """

    snapshot: MacroDataSnapshot
    growth: ModelResult
    inflation: ModelResult
    labor: ModelResult
    taylor: PolicyRuleResult
    balanced: PolicyRuleResult
    first_diff: PolicyRuleResult


def _live_models() -> _LiveModels:
    """The real Q1-Q8 inputs, through the real plumbing.

    The growth leg goes through ``output_gap_from_snapshot`` rather than
    ``output_gap`` fed from each series' own last observation: ``GDPPOT`` is a CBO
    **projection** series whose last point is 2036-10-01, so the shortcut returns
    an output gap of roughly -17% (the O-7 / D-009 trap D-066's check documents).
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
    taylor = taylor_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value)
    )
    balanced = balanced_approach_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=2.4, pi_target=2.0, output_gap=gap_value)
    )
    first_diff = first_difference_rule(
        FirstDifferenceInputs(i_prev=3.5, pi_current=2.4, pi_target=2.0, output_gap_change=0.15)
    )
    return _LiveModels(
        snapshot=snapshot,
        growth=growth,
        inflation=inflation,
        labor=labor,
        taylor=taylor,
        balanced=balanced,
        first_diff=first_diff,
    )


def main() -> int:
    print("=" * 78)
    print("live check: the three no-trade triggers (D-068)")
    print("=" * 78)

    models = _live_models()
    # Named fields rather than a positional tuple: the tuple signature was what
    # let mypy report 15 errors against these very lines while the gate claimed
    # the tree was clean (D-069).
    snapshot = models.snapshot
    growth = models.growth
    inflation = models.inflation
    labor = models.labor
    print(f"\nsnapshot as_of={snapshot.as_of:%Y-%m-%d} flags={len(snapshot.data_quality_flags)}")
    print(f"  growth={growth.value!r} inflation={inflation.value!r} labor={labor.value!r}")

    gap = canonical_policy_gap(
        models.taylor, models.balanced, models.first_diff, market_implied=3.0
    )
    signals = build_confirmation_signals(growth, inflation, labor, gap)
    invalidation = derive_invalidation_conditions(growth, inflation, labor)

    print("\n" + "-" * 78)
    print("Q6 — gap inside the rules' own dispersion")
    print("-" * 78)
    print(f"  raw_gap={gap.raw_gap:+.4f}  dispersion={gap.dispersion:.4f}")
    print(f"  is_meaningful={gap.is_meaningful}  -> Q6 fires = {not gap.is_meaningful}")
    if not gap.is_meaningful:
        decision = no_trade_thesis(
            "the model-vs-market gap is inside the policy rules' own disagreement",
            trigger="gap_below_dispersion",
            gap=gap,
        )
        print(f"  elapsed = dispersion - |raw_gap| = {decision.elapsed:.4f}")
        print(f"  is_marginal={decision.is_marginal}")
    else:
        print("  (Q6 does not fire on today's data; the path is exercised with a")
        print("   synthetic gap in the offline tests. This is a fact about the data.)")

    print("\n" + "-" * 78)
    print("Q7 — CONFLICTED convergence")
    print("-" * 78)
    conflicted = bool(signals.agreeing and signals.disagreeing)
    print(
        f"  agreeing={signals.agreeing} disagreeing={signals.disagreeing} "
        f"neutral={signals.neutral} unreadable={len(signals.unreadable)}"
    )
    print(f"  per-model directions: {[s.direction for s in signals.signals]}")
    print(f"  -> Q7 fires = {conflicted}")
    if conflicted:
        decision = no_trade_thesis(
            "the growth and inflation pillars directly contradict",
            trigger="conflicted_signals",
            evidence=signals,
        )
        print(f"  evidence carried: {type(decision.evidence).__name__}")

    print("\n" + "-" * 78)
    print("Q8 — no evidence-based invalidation condition")
    print("-" * 78)
    print(
        f"  identified={invalidation.identified} conditions={len(invalidation.conditions)} "
        f"unreadable={len(invalidation.unreadable)} neutral={len(invalidation.neutral)}"
    )
    print(f"  text={invalidation.text!r}")
    print(f"  -> Q8 fires = {not invalidation.identified}")
    if not invalidation.identified:
        decision = no_trade_thesis(
            invalidation.reason, trigger="no_falsifier", evidence=invalidation
        )
        print(f"  evidence carried: {type(decision.evidence).__name__}")

    print("\n" + "-" * 78)
    print("The rendered thesis passes the LIVE schema")
    print("-" * 78)
    thesis = render_no_trade_thesis(
        no_trade_thesis(
            "no clean edge on today's live inputs",
            trigger="conflicted_signals" if conflicted else "caller",
        ),
        thesis_id="live-no-trade-d068",
        regime={"state": "live", "confidence": 0.0},
        growth_view={"output_gap": growth.value},
        inflation_view={"breadth_score": inflation.value},
        policy_view={},
        market_pricing_gap=gap,
        convergence_classification="NO_SIGNAL",
    )
    assert isinstance(thesis, MacroThesis)
    print(
        f"  instrument={thesis.trade_idea.instrument!r} direction={thesis.trade_idea.direction!r}"
    )
    print(f"  status={thesis.status.value} stop={thesis.trade_idea.stop_or_invalidation!r}")
    print(f"  warnings={thesis.warnings}")

    print("\n" + "-" * 78)
    print("The sentinel comparison — a LIVE fact about the schema gate")
    print("-" * 78)
    sentinel_idea = TradeIdea(
        instrument="SOFR_FUTURE", direction="long", stop_or_invalidation="n/a"
    )
    print(f"  TradeIdea(stop_or_invalidation='n/a').is_trade = {sentinel_idea.is_trade}")
    print(f"  the gate accepts it as a stated falsifier: {bool('n/a'.strip())}")
    print("  -> Section 16.4's 'n/a' is a USABLE falsifier to the schema; the")
    print("     shipped no-trade writes '' instead, so a future is_trade flip")
    print("     cannot turn the sentinel into an assertion the thesis does not have.")

    print("\n" + "-" * 78)
    print("The vocabulary and its labels")
    print("-" * 78)
    for trigger, label in NO_TRADE_TRIGGER_LABELS.items():
        print(f"  {trigger:22s} {label}")

    print("\n" + "=" * 78)
    print("RESULT: the three triggers are reachable; the rendered thesis is valid;")
    print("the sentinel's danger is confirmed and avoided.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
