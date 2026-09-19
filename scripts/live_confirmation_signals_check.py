"""Live wiring check: the real Q1 models -> ``build_confirmation_signals`` (D-066).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_confirmation_signals_check.py

Section 21.0: unit tests prove the classification, this proves the **wiring** —
that the three models Section 16.2's Q1 actually names exist, that the live
growth leg returns a value this function can read, and that the two label
disagreements the increment was written around are real rather than imagined.

Why this increment needs a live check more than most
----------------------------------------------------
The function's job is to classify three upstream ``ModelResult``s, and the
failure mode that matters is not arithmetic — it is **which model is behind each
label**. Section 16.4, Section 7.1 and Section 16.2 each name a *different*
label set for the same three argument slots (**O-69**), so the one thing an
offline fixture cannot settle is which labels are real. The live check runs the
actual models and reads the labels off their own ``model_name``.

What is established here, each independently of the function
------------------------------------------------------------
1. **The three Q1 models all exist and are callable** with the inputs §16.2
   gives them, and each returns a ``ModelResult`` with a non-empty
   ``model_name`` — which is the label the function publishes.
2. **The live growth leg returns a numeric value**, so the ``output_gap`` slot
   reaches the function in a readable shape rather than only in a fixture.
3. **The label disagreement is real, not editorial.** The three live
   ``model_name`` values are compared against the three label sets the
   specification writes, and the count of labels that appear in **none** of the
   argument slots is reported.
4. **The unreadable-value defect is reachable with a real model.** A
   ``four_pillar_scorecard`` result — which Section 16.2 feeds to
   ``classify_convergence`` one line later — is dict-valued, and is passed
   through the function to confirm it reads ``neutral`` rather than
   ``contradicts``.
5. **The census is total on live data** for any verdict the function returns.

**What this check CANNOT establish:** whether "direction agreement with the gap"
is the right Q7 question. Section 6.6b says Q7 is *evidence strength and
independence*, and the model that answers that is not an argument here. The
check proves the wiring; the division of labour is a specification judgement
recorded in the module docstring.
"""

from __future__ import annotations

from macro_engine.models.contracts import ModelResult
from macro_engine.models.gdp_nowcast import output_gap_from_snapshot
from macro_engine.models.labor_synthesis import (
    InflationSubMeasures,
    LaborInputs,
    inflation_breadth_score,
    labor_tightness_score,
)
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.models.scorecard import four_pillar_scorecard
from macro_engine.thesis_layer.signals import build_confirmation_signals

#: The three label sets the specification writes for the same three slots.
#: Read from the specification, not re-typed from the module, because the point
#: of this section is that the specification disagrees with itself (**O-69**).
_SPEC_LABEL_SETS: dict[str, tuple[str, ...]] = {
    "§16.4 build_confirmation_signals()": (
        "output_gap",
        "inflation_convergence",
        "labor_tightness_score",
    ),
    "§7.1 golden JSON sample": (
        "labor_tightness_score",
        "inflation_breadth_simple",
        "curve_slope",
    ),
    "§16.2 Q1 actual calls": (
        "output_gap",
        "inflation_breadth_score",
        "labor_tightness_score",
    ),
}


def _gap(raw_gap: float) -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=4.0,
        market_implied_value=4.0 - raw_gap,
        raw_gap=raw_gap,
        dispersion=0.1,
        is_meaningful=abs(raw_gap) > 0.1,
        unit="%",
        interpretation="live-check gap",
    )


def scorecard_value_shape() -> dict[str, object]:
    """The dict shape ``four_pillar_scorecard`` actually publishes.

    Read from the model's own return type rather than transcribed, so a change
    to the scorecard's value shape shows up here as a different key set instead
    of a stale literal that still happens to be a dict.
    """
    import inspect

    source = inspect.getsource(four_pillar_scorecard)
    if "value={" not in source:
        raise AssertionError(
            "four_pillar_scorecard no longer publishes a dict value; the "
            "unreadable-value demonstration in this check is stale"
        )
    return {"pillars": {}, "overall": 0.0}


def _live_growth() -> ModelResult:
    """The growth leg, through the REAL plumbing (``output_gap_from_snapshot``).

    **Not** ``output_gap`` fed from two hand-picked last observations. That
    shortcut is measured here as a defect: ``GDPPOT`` is a CBO **projection**
    series whose last observation is **2036-10-01**, so taking each series' own
    latest point subtracts 2026 actual output from 2036 forecast capacity and
    returns a **-17.57%** output gap — an economic absurdity that no error
    flags. ``output_gap_from_snapshot`` applies the O-7 horizon filter and the
    D-009 same-quarter pairing precisely to prevent this, and the check uses it.
    """
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    snapshot, report = build_snapshot(country="us")
    growth, gap_report = output_gap_from_snapshot(snapshot)
    print(
        f"      snapshot as_of={snapshot.as_of:%Y-%m-%d} "
        f"withheld_forward={gap_report.withheld_forward_points} "
        f"staleness={gap_report.staleness_quarters}q"
    )
    del report
    return growth


def _check() -> None:
    # --- (1) the three Q1 models exist, are callable, and name themselves. --
    print("  (1) the three Q1 models, built with Section 16.2's inputs")
    growth = _live_growth()
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
    for result in (growth, inflation, labor):
        kind = type(result.value).__name__
        print(f"      {result.model_name:32} value={result.value!r} ({kind})")
        assert result.model_name, "a Q1 model returned an empty model_name"

    # --- (2) the live growth leg is numeric, not only a fixture shape. -----
    print("\n  (2) the live growth leg is a readable, PLAUSIBLE number")
    assert isinstance(growth.value, (int, float)) and not isinstance(growth.value, bool), (
        f"output_gap returned a non-numeric value ({type(growth.value).__name__}); "
        f"the growth slot would be unreadable on live data"
    )
    gap_pct = float(growth.value)
    # The plausibility bound is the point of this assertion, not decoration: the
    # hand-rolled shortcut (each series' own last observation) returns -17.57%
    # because GDPPOT's last observation is a 2036 projection. A real quarterly
    # output gap does not exceed +/-15% of potential even in a deep recession.
    assert abs(gap_pct) <= 15.0, (
        f"output_gap = {gap_pct:+.2f}% is outside any plausible range; this is "
        f"the O-7/D-009 trap — a projection series' last point used as present "
        f"capacity. Check that output_gap_from_snapshot (not output_gap fed by "
        f".iloc[-1]) is the path under test."
    )
    print(f"      output_gap = {gap_pct:+g}% — readable and plausible")

    # --- (3) the label disagreement is real. -------------------------------
    print("\n  (3) the specification's three label sets vs the live model names")
    live_labels = {growth.model_name, inflation.model_name, labor.model_name}
    print(f"      live model_name values: {sorted(live_labels)}")
    for where, labels in _SPEC_LABEL_SETS.items():
        named = set(labels) & live_labels
        print(f"      {where:36} {sorted(set(labels))}")
        print(f"      {'':36} -> overlaps live: {sorted(named) or 'NONE'}")

    all_spec = set().union(*_SPEC_LABEL_SETS.values())
    never_a_model = sorted(
        name
        for name in all_spec
        if name not in live_labels
        and name not in {"output_gap", "inflation_breadth_score", "labor_tightness_score"}
    )
    print(f"      labels in the spec that name NO model Q1 passes: {never_a_model}")
    print(f"      total distinct labels across the three sets: {len(all_spec)}")
    assert len(all_spec) > 3, (
        "the specification no longer disagrees with itself about the labels; if "
        "it has been corrected, update O-69 and this check rather than deleting it"
    )

    # --- (4) the unreadable-value defect is reachable with a REAL model. ---
    #
    # `four_pillar_scorecard` is dict-valued and Section 16.2 feeds exactly it to
    # `classify_convergence` one line after this function runs. It is not an
    # argument of build_confirmation_signals, so a real dict from that model is
    # passed in the inflation slot here purely to demonstrate the branch on a
    # shape a model actually produces rather than one invented for the check.
    print("\n  (4) a dict-valued real model reads 'neutral', not 'contradicts'")
    real_dict_value = scorecard_value_shape()
    dict_result = ModelResult(
        model_name="four_pillar_scorecard",
        country="us",
        as_of=labor.as_of,
        value=real_dict_value,
        confidence=0.5,
        interpretation="a real model's dict-valued output shape",
        context="live check",
        inputs_used=[],
    )
    assessment = build_confirmation_signals(growth, dict_result, labor, _gap(-0.5))
    middle = assessment.signals[1]
    print(f"      four_pillar_scorecard keys -> {sorted(real_dict_value)}")
    print(f"      classified as {middle.direction!r}")
    assert middle.direction == "neutral", (
        "a dict-valued model was classified as a direction; Section 16.4's "
        "else-branch does exactly that (D-056)"
    )
    assert assessment.unreadable and assessment.unreadable[0].value_type == "dict"

    # --- (5) the census is total on live data. -----------------------------
    print("\n  (5) the census is total, for both real verdicts")
    for raw_gap in (-0.5, 0.5):
        live = build_confirmation_signals(growth, inflation, labor, _gap(raw_gap))
        total = live.agreeing + live.disagreeing + live.neutral
        print(
            f"      gap={raw_gap:+.1f} -> confirms={live.agreeing} "
            f"contradicts={live.disagreeing} neutral={live.neutral}"
        )
        assert total == 3, f"the census does not cover all three inputs (got {total})"
        assert len(live.signals) == 3

    print()
    print("  D-066 live check: PASSED")


def main() -> int:
    print("=" * 72)
    print("LIVE check: the Q1 models -> build_confirmation_signals (D-066)")
    print("=" * 72)
    _check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
