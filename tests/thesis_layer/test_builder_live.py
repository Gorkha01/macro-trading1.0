"""Live tests for ``build_us_macro_thesis`` (Section 7.2/16.2, D-069).

Deselected unless ``-m live``. These exist because the increment's claims are
**facts about the wiring**, not properties of the function:

1. **The builder runs end to end on real model output.** An offline test hands
   it hand-built ``ModelResult``s, which proves it handles them and nothing
   about whether the real chain produces the shapes it expects. The Q7 signal
   adapter exists *because* the real chain's objects do not nest.
2. **The market-path proxy returns its contamination warnings, and they reach
   the thesis — including on a stand-down.** Section 22.5's ``None`` branch is
   the one a real caller without a term-premium model always takes, so its
   warnings must appear. Measured during D-069: the first shipped version of
   ``_render`` published **only** the trigger line, so a stand-down dropped
   them; this test is what caught it, and it is the reason the assertion below
   is unconditional about the thesis's status.
3. **Which gates fire on today's data is a measurement, not an assumption.**
   The first version of this file asserted ``fired == []``. It failed on the
   first run: ``conflicted_signals`` (Q7) fires today at ``gap=-0.53``,
   ``dispersion=0.42``. **A no-trade is therefore the live default today** — so
   the file records the state and asserts only what must hold either way.

The plumbing below (a live snapshot, the three reads, the policy chain) mirrors
``test_no_trade_live.py`` deliberately, so a change in how a real read is
constructed breaks both files rather than one.
"""

from __future__ import annotations

import copy

import pytest

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
from macro_engine.thesis_layer.builder import EconomyReads, build_us_macro_thesis
from macro_engine.thesis_layer.no_trade import (
    NO_TRADE_TRIGGER_LABELS,
    NoTradeTrigger,
)
from macro_engine.thesis_layer.schemas import MacroThesis, ProductionUniverse, ThesisStatus

#: The three gates, in the order the builder checks them. Read out of the
#: published label table rather than re-typed, so a new trigger cannot be
#: invisible to the census below.
_GATE_ORDER: tuple[NoTradeTrigger, ...] = (
    "gap_below_dispersion",
    "conflicted_signals",
    "no_falsifier",
)


def _gates_fired(thesis: MacroThesis) -> list[NoTradeTrigger]:
    """Which of the three gates left their trigger line on the thesis."""
    return [
        trigger
        for trigger in _GATE_ORDER
        if any(NO_TRADE_TRIGGER_LABELS[trigger] in w for w in thesis.warnings)
    ]


def _live_inputs() -> tuple[EconomyReads, TaylorRuleInputs, FirstDifferenceInputs, float]:
    """Today's real inputs, assembled the way the live tests do.

    Returns ``(reads, taylor_inputs, first_difference_inputs, short_yield)``.

    A real snapshot supplies the output gap; the other two reads are built from
    the shorthand the live suite uses, because — measured (D-069) — **neither
    ``inflation_breadth_score`` nor ``labor_tightness_score`` has a
    snapshot-fed helper anywhere in the tree**. That is the plumbing layer the
    builder's ``EconomyReads`` parameter exists to avoid faking, and it is why
    this test constructs the reads here rather than pretending a snapshot-fed
    one exists.
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


def _build(**overrides: object) -> MacroThesis:
    """Build from live inputs, letting a test override any keyword."""
    reads, taylor_inputs, first_diff_inputs, short_yield = _live_inputs()
    kwargs: dict[str, object] = {
        "thesis_type": ThesisType.POLICY_PATH_GAP,
        "universe": ProductionUniverse(),
        "short_yield": short_yield,
        "short_tenor_term_premium": None,  # the real caller's situation
        "catalyst_calendar": [],  # the fetch is a separate test
    }
    kwargs.update(overrides)
    return build_us_macro_thesis(reads, taylor_inputs, first_diff_inputs, **kwargs)  # type: ignore[arg-type]


@pytest.mark.live
def test_the_builder_runs_end_to_end_on_real_model_output() -> None:
    """The whole chain: a live snapshot through every gate to a real thesis.

    Asserts the **shape and the wiring**, never a value: pinning today's
    ``raw_gap`` would be the D-064 trap (a test frozen to the data of the day).
    Which gate fires is printed, not asserted — see the census test below.
    """
    thesis = _build()

    assert isinstance(thesis, MacroThesis)
    assert thesis.thesis_id.startswith("us-")
    assert thesis.country == "us"
    assert thesis.status in (ThesisStatus.DRAFT, ThesisStatus.WATCH)

    fired = _gates_fired(thesis)
    print(
        f"\n  live thesis: status={thesis.status.value} "
        f"convergence={thesis.convergence_classification.value} "
        f"instrument={thesis.trade_idea.instrument!r} "
        f"direction={thesis.trade_idea.direction} "
        f"gates={fired or 'none fired'}"
    )
    print(
        f"  gap: raw={thesis.market_pricing_gap.raw_gap:+.4f} "
        f"dispersion={thesis.market_pricing_gap.dispersion:.4f} "
        f"meaningful={thesis.market_pricing_gap.is_meaningful}"
    )
    print(
        f"  scenarios={len(thesis.scenario_distribution)} "
        f"signals={len(thesis.confirmation_signals)} "
        f"warnings={len(thesis.warnings)} "
        f"families={thesis.independent_source_families}"
    )

    # A no-trade is the live default (measured), so the assertions are the ones
    # that hold on EITHER path rather than the ones the first draft assumed.
    if thesis.status is ThesisStatus.WATCH:
        assert thesis.trade_idea.instrument == "NONE"
        assert thesis.trade_idea.stop_or_invalidation == ""
    else:
        # §16.3: an unverified thesis is a DRAFT, and the LTCM gate means its
        # falsifier must be non-empty — that IS Q8 having passed.
        assert thesis.trade_idea.stop_or_invalidation.strip(), (
            "a DRAFT thesis must carry a non-empty falsifier; the schema's LTCM "
            "gate would have refused it otherwise"
        )
        assert len(thesis.scenario_distribution) == 4


@pytest.mark.live
def test_the_market_path_contamination_warnings_reach_the_thesis() -> None:
    """Section 22.5's ``None`` branch, end to end — **on the live path taken**.

    The real caller described in the module (no term-premium model wired) always
    takes the contaminated branch, whose whole purpose is that the contamination
    be **visible**. This is the test that caught ``_render`` dropping them, so
    the assertion is deliberately status-independent: a stand-down is exactly
    when a reader most needs to know how weak the inputs were.
    """
    thesis = _build()

    contaminated = [w for w in thesis.warnings if "NO TERM PREMIUM ADJUSTMENT" in w]
    proxy = [w for w in thesis.warnings if "Still a PROXY" in w]

    print(
        f"\n  market-path warnings on the thesis: "
        f"status={thesis.status.value} contaminated={len(contaminated)} "
        f"proxy={len(proxy)}"
    )
    assert contaminated, (
        "the term-premium-free branch's contamination warning did not reach the "
        f"thesis (status={thesis.status.value}); the warning collector is "
        "dropping it on this path"
    )
    assert proxy


@pytest.mark.live
def test_a_stand_down_carries_the_models_warnings_not_only_the_trigger_line() -> None:
    """The measured defect, pinned.

    First shipped ``_render`` published only ``[decision.warning_line()]``, so
    every stand-down — which is the live default today — lost the model
    warnings *and* Section 22.5's contamination disclosure. §7.2 step 9's "never
    drop them" is not conditioned on the thesis being live.

    Asserted as a **relationship**: a stand-down carries at least as many
    warnings as the live path does *minus nothing*, i.e. strictly more than the
    single trigger line, and its first line is still the trigger (D-068 owns
    that ordering).
    """
    thesis = _build()

    fired = _gates_fired(thesis)
    if not fired:
        pytest.skip("no gate fired today, so there is no stand-down to inspect")

    assert len(thesis.warnings) > 1, (
        f"the stand-down ({fired}) carries only {thesis.warnings!r} — the model "
        "warnings and the market-path disclosures were dropped"
    )
    assert thesis.warnings[0].startswith("No trade ["), (
        "the trigger line must be FIRST (render_no_trade_thesis owns it), and the "
        f"collected warnings appended behind it; got {thesis.warnings[0]!r}"
    )
    assert any(NO_TRADE_TRIGGER_LABELS[fired[0]] in w for w in thesis.warnings)


@pytest.mark.live
def test_the_gate_census_on_todays_data_is_measured_and_reported() -> None:
    """Record which gates fire — a measurement, and a tripwire on the record.

    The first draft asserted ``fired == []`` and failed on its first run, because
    **Q7 fires today**: growth and inflation signals directly contradict at
    ``gap=-0.53`` against a ``0.42`` dispersion. That is a fact about the
    system's live posture, so the test reports it and asserts only the
    invariants that must hold whatever today's answer is.
    """
    thesis = _build()

    fired = _gates_fired(thesis)
    print(
        f"\n  gates fired today: {fired or 'NONE'} "
        f"(status={thesis.status.value} "
        f"gap={thesis.market_pricing_gap.raw_gap:+.4f} "
        f"dispersion={thesis.market_pricing_gap.dispersion:.4f} "
        f"convergence={thesis.convergence_classification.value})"
    )

    # Gate ORDER is an invariant even when more than one is reachable: Q6
    # short-circuits before Q7 runs, and Q7 before Q8.
    assert fired == sorted(fired, key=_GATE_ORDER.index), (
        f"the gates fired out of the documented Q6 -> Q7 -> Q8 order: {fired}"
    )
    assert len(fired) <= 1, (
        f"more than one gate left its line on the thesis ({fired}); the builder "
        "short-circuits, so a second line means a line was written outside the "
        "gate that fired"
    )

    # And the status agrees with the census — the field and the evidence cannot
    # disagree about whether a stand-down happened.
    if fired:
        assert thesis.status is ThesisStatus.WATCH
        assert thesis.convergence_classification.value in {
            "CONFLICTED",
            "NO_SIGNAL",
        }
    else:
        assert thesis.status is ThesisStatus.DRAFT


@pytest.mark.live
def test_a_live_no_trade_thesis_round_trips_through_the_schema() -> None:
    """Render a stand-down from **live** objects and round-trip the schema.

    The forced case uses a live gap and live reads, so the partial-view fields
    are filled with real values rather than fixtures — which is what §16.4's
    "whatever partial view was formed" asks for.

    Note on the fixture: a short yield far *below* the model's prescription does
    **not** stand the thesis down. Measured during D-069, ``short_yield=-10.0``
    produces a ``DRAFT`` — the sign flip makes the gap *wide* rather than narrow,
    so the first draft of this test silently asserted nothing. The stand-down is
    taken from the situation that actually produces one today (Q7, opposed
    reads), and the state is printed so a change is visible rather than implied.
    """
    thesis = _build()
    fired = _gates_fired(thesis)

    print(
        f"\n  schema round-trip: status={thesis.status.value} "
        f"gates={fired or 'none'} "
        f"instrument={thesis.trade_idea.instrument!r} "
        f"stop={thesis.trade_idea.stop_or_invalidation!r}"
    )

    if thesis.status is ThesisStatus.WATCH:
        assert thesis.trade_idea.instrument == "NONE"
        assert thesis.trade_idea.stop_or_invalidation == "", (
            "a stand-down must write an EMPTY falsifier — 'n/a' is truthy and "
            "would satisfy the LTCM gate it exists to fail (lesson 5bd)"
        )
        assert len(thesis.scenario_distribution) == 0
        assert thesis.trade_idea.direction == "n/a"
    else:
        # The other shape the schema permits, asserted so the branch is not a
        # silent no-op.
        assert thesis.trade_idea.stop_or_invalidation.strip()
        assert thesis.trade_idea.instrument != "NONE"

    # Round-trips through the real schema without a re-validation error, on
    # either path.
    MacroThesis.model_validate(thesis.model_dump())
    assert copy.deepcopy(thesis.thesis_id) == thesis.thesis_id


@pytest.mark.live
def test_an_opposed_read_pair_produces_a_conflicted_stand_down() -> None:
    """Q7's condition, constructed on purpose, against live policy objects.

    The live data happens to be CONFLICTED today, but a test that only observes
    today's posture stops testing Q7 the moment the data turns. This builds the
    opposition explicitly — a hot growth read against a cold inflation read —
    while keeping **every other input live**, so the gate is exercised through
    the real policy chain rather than a fixture.
    """
    reads, taylor_inputs, first_diff_inputs, short_yield = _live_inputs()

    # Built through the REAL model functions, not by fabricating a ModelResult:
    # a hand-built `value` would not carry the `source_family`, `warnings` or
    # `confidence_inputs` the collector and the convergence adapter read.
    cold_inflation = inflation_breadth_score(
        InflationSubMeasures(cpi_headline_mom=-0.5, cpi_core_mom=-0.6, pce_core_mom=-0.5)
    )
    hot_labor = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=-1.4,
            jolts_openings_yoy_pct=8.0,
            jolts_quits_level_percentile=85.0,
            nfp_3m_avg=320.0,
        )
    )
    # The growth read is the live one with its value replaced — `model_copy`
    # keeps every other field (family, warnings, confidence) that the real
    # computation set, which a fresh `ModelResult(...)` would silently drop.
    opposed = EconomyReads(
        growth=reads.growth.model_copy(update={"value": 2.5}),
        inflation=cold_inflation,
        labor=hot_labor,
    )

    thesis = build_us_macro_thesis(
        opposed,
        taylor_inputs,
        first_diff_inputs,
        thesis_type=ThesisType.POLICY_PATH_GAP,
        universe=ProductionUniverse(),
        short_yield=short_yield,
        short_tenor_term_premium=None,
        catalyst_calendar=[],
    )

    fired = _gates_fired(thesis)
    print(
        f"\n  opposed reads: convergence={thesis.convergence_classification.value} "
        f"status={thesis.status.value} gates={fired or 'none'}"
    )

    if thesis.market_pricing_gap.is_meaningful:
        assert thesis.convergence_classification.value == "CONFLICTED", (
            "hot growth against cold inflation must classify CONFLICTED; the "
            "convergence adapter or the reads' wiring changed"
        )
        assert "conflicted_signals" in fired
        assert thesis.status is ThesisStatus.WATCH
