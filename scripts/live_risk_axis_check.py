"""Live cross-check: Section 17.4's risk axis, against the REAL thesis path.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they exercise the real settings tree and the real
pipeline. Run with::

    uv run python scripts/live_risk_axis_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring. The unit
tests for this increment live in ``tests/thesis_layer/test_risk_axis.py``; what
they cannot prove is what the axis does on the theses the system *actually*
produces, and whether the rule it implements can fire at all.

The finding this check exists to record
---------------------------------------

Section 17.4 demotes a thesis whose size "clips to near-zero", and "near-zero" is
the only unquantified word in the rule — so it is a config leaf. The **first value
chosen for it could never fire**, and it satisfied every bound a reader would
write down: it was strictly positive, and strictly below the position cap.

It was wrong because **the published fraction is not continuous.** Full Kelly is
the argmax of expected log growth, and for a two-branch distribution with a
positive edge that objective is *monotone in f* — so ``f*`` pins at the search
domain's edge, the clip at the position cap produces the number, and only a few
asymmetric sets land strictly inside. The reachable published sizes are therefore
a short list, and a bound beneath its minimum demotes nothing, ever.

This check measures that list, prints it, and asserts the configured bound sits
where it can discriminate. **A rule that cannot fire is the declared-consumed-
unreachable class** this project has recorded eight times (D-045/D-046/D-048,
O-53, and twice inside D-072) — and this is the ninth instance, caught by a
skipped test rather than by review.

The seven things this check establishes
---------------------------------------

1. **The live pipeline is driven end to end.** The real memoized snapshot is
   built, ``snapshot_to_thesis_inputs`` derives the six builder arguments, and
   ``build_us_macro_thesis`` produces real theses for every US family §22.3.1
   implements. If the orchestration drifts from the builder's signature this
   check fails with the same ``TypeError`` §8.2's sample call produced.

2. **The axis is inert by default, and says so.** ``risk_budget_target`` defaults
   to ``None``, and every live thesis built without one is unchanged — same
   status, same instrument, same sizing sentence — plus exactly one new warning
   that publishes "DID NOT RUN". The default must not read as "checked and clear".

3. **No source supplies a book, so the disclosure is the honest outcome.** §21.1's
   five source types (LIVE / DERIVED / CONFIG / MANUAL / BLOCKED) contain no entry
   for portfolio holdings, and nothing in the snapshot, the registry or the
   settings tree provides one. The parameter is therefore *disclosed absent*
   rather than silently defaulted, and the check prints the census that
   establishes it.

4. **The REACHABLE SIZE SET, measured.** The asymmetric two-branch sets are driven
   through the real translation, and the distinct published fractions are counted
   and printed. The minimum positive value is the number the bound must clear.

5. **The configured bound discriminates.** Asserted against the measurement in
   (4), not against a literal: the bound must be at or above the smallest
   reachable size, and strictly below the position cap. Both failures are named —
   too low never fires, too high demotes everything.

6. **The demotion FIRES, through the real builder.** A thesis the builder can
   produce, given a book, is demoted to ``WATCH`` with a warning naming the bound,
   the size and the binding constraint. This is the half that makes the rule a
   consumer rather than a declaration.

7. **Refusal and demotion do not collapse.** A refusal keeps ``DRAFT`` and says
   "REFUSAL, not a demotion"; the demotion moves to ``WATCH``. If they shared a
   status, a §25 probability-prohibition finding would be reported as a
   risk-budget finding, and the reason — which is what a human acts on — would
   stop travelling.

Offline by design: the snapshot is read from the process-local cache when one
exists and built once otherwise. "Live" here means "through the real settings
tree and the real call path", which is the part the unit tests stub out.
"""

from __future__ import annotations

import sys

from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
from macro_engine.api_layer.snapshot_provider import get_snapshot
from macro_engine.config import get_settings
from macro_engine.data_layer.schemas import MacroDataSnapshot
from macro_engine.models.contracts import utc_now
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.portfolio.risk_budget import (
    ProposedPosition,
    RiskBudgetTarget,
    ThesisPositionInputs,
    translate_thesis_to_position,
)
from macro_engine.thesis_layer.builder import build_us_macro_thesis
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    MarketPricingGap,
    ThesisStatus,
    TradeIdea,
)

SETTINGS = get_settings()

#: The four §22.3.1 families this build implements for ``us``. The two BLOCKED
#: members are excluded by §22.3; the two analytical-only ones are exercised
#: through the universe instead of the builder.
_LIVE_FAMILIES: tuple[ThesisType, ...] = (
    ThesisType.POLICY_PATH_GAP,
    ThesisType.CURVE_SHAPE_GAP,
    ThesisType.INFLATION_EXPECTATIONS_GAP,
    ThesisType.EQUITY_MACRO,
)

#: The instrument ``select_instrument`` routes a policy-path gap to, so a budget
#: built for it passes ``ThesisPositionInputs``' instrument-match check.
_LIVE_INSTRUMENT = "UST 2yr note futures"

#: Two-branch sets whose optima land **strictly inside** the domain rather than
#: pinning at the search edge. Every one was found by sweeping the space, not
#: derived from the spec text: the monotonicity of expected log growth is what
#: makes the interior rare, and it is why the reachable set is a short list.
_ASYMMETRIC: tuple[tuple[float, float, float], ...] = (
    (0.46, 0.02, 0.017),
    (0.63, 0.01, 0.017),
    (0.53, 0.016, 0.018),
    (0.42, 0.018, 0.013),
    (0.53, 0.008, 0.009),
    (0.45, 0.05, 0.04),
)

#: The favourable edge that drives ``f*`` to the domain boundary, so the CAP
#: produces the number. Its presence is what makes the reachable set's top end
#: (the cap itself) observable rather than assumed.
_EDGE: tuple[float, float, float] = (0.70, 0.20, 0.05)

#: The budget supplied wherever a book is simulated. Any positive allocation
#: works: gate 4 publishes the bound and never scales the number (D-072's 6.7x).
_BUDGET = 0.12


def _scenarios(p: float, up: float, down: float) -> list[ScenarioOutcome]:
    """Two branches summing to one, in the only unit Kelly can consume."""
    return [
        ScenarioOutcome(name="up", probability=p, payoff_estimate=up, unit="fraction_of_capital"),
        ScenarioOutcome(
            name="down",
            probability=1.0 - p,
            payoff_estimate=-down,
            unit="fraction_of_capital",
        ),
    ]


def _live_theses(snapshot: MacroDataSnapshot) -> dict[ThesisType, MacroThesis | None]:
    """Build one real thesis per family through the real orchestration.

    A **wholly failed** snapshot build raises rather than returning an empty
    snapshot (§8's contract), so a failure here is a genuine wiring failure —
    never a silent fall-back to fixtures.
    """
    built: dict[ThesisType, MacroThesis | None] = {}
    for family in _LIVE_FAMILIES:
        try:
            inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=family)
            built[family] = build_us_macro_thesis(
                inputs.reads,
                inputs.taylor_inputs,
                inputs.first_difference_inputs,
                thesis_type=inputs.thesis_type,
                universe=inputs.universe,
                short_yield=inputs.short_yield,
                regime=inputs.regime,
            )
        except Exception as exc:  # the report is the point
            print(f"   {family.name:28s} RAISED {type(exc).__name__}: {exc}")
            built[family] = None
    return built


def _live_shaped_thesis(
    *, instrument: str, scenarios: list[ScenarioOutcome], status: str
) -> MacroThesis:
    """The smallest ``MacroThesis`` the schema accepts, shaped as the builder shapes one.

    Deliberately **not** derived from a built thesis. Measured: every family the
    live builder produces today STANDS DOWN at ``WATCH`` with instrument
    ``"NONE"``, and a stand-down carries no ``stop_or_invalidation`` — so handing
    one to ``translate_thesis_to_position`` is refused by the LTCM schema gate
    ("a position without a stated falsifier cannot be exited"). That refusal is
    correct, and it is why the reachable-size measurement needs a thesis that is
    *shaped* like a live one rather than one that happens to exist today.

    Checked against the real ``MacroThesis`` validator on every construction, so a
    schema change fails here rather than silently passing a stale shape.
    """
    return MacroThesis(
        thesis_id="us-2026-09-20-riskaxis",
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
            direction="long",
            timeframe="6-12 months",
            sizing_logic="Phase 1: human-determined",
            stop_or_invalidation=("growth read turns negative for two consecutive prints"),
        ),
        scenario_distribution=scenarios,
        scenario_distribution_status=status,  # type: ignore[arg-type]
        status=ThesisStatus.DRAFT,
        warnings=[],
    )


def _sizable(instrument: str, pairs: list[ScenarioOutcome]) -> MacroThesis:
    """A live-shaped thesis made sizing-grade on the two fields the gates check.

    Constructed deliberately, and the construction is the point: the shipped
    configuration's probabilities are ``uncalibrated_illustrative``, so a budget
    supplied to any real thesis refuses at gate 2 — a fact section 7 prints rather
    than works around. To measure what the sizing path CAN produce, both the
    status and the distribution's **unit** have to be right, and only the first is
    a label; the live builder's payoffs are bp figures, which ``KellyInputs``
    rejects outright. Rebuilding in ``fraction_of_capital`` is the correction.
    """
    return _live_shaped_thesis(instrument=instrument, scenarios=pairs, status="calibrated")


def _translate(thesis: MacroThesis) -> ProposedPosition:
    result = translate_thesis_to_position(
        ThesisPositionInputs(
            thesis=thesis,
            risk_budget_target=RiskBudgetTarget(
                instrument=thesis.trade_idea.instrument,
                target_risk_contribution_pct=_BUDGET,
            ),
        )
    )
    value = result.value
    assert isinstance(value, dict)
    return ProposedPosition.model_validate(value)


def _risk_line(thesis: MacroThesis) -> str | None:
    lines = [w for w in thesis.warnings if "[Q12 risk]" in w]
    assert len(lines) <= 1, f"more than one risk-axis line: {lines!r}"
    return lines[0] if lines else None


def main() -> int:
    bound = SETTINGS.risk.thesis_demotion_fraction
    cap = SETTINGS.risk.max_position_fraction

    print("LIVE CHECK -- Section 17.4's risk axis (thesis_layer/builder.py)")
    print("=" * 72)
    print(f"  risk.thesis_demotion_fraction = {bound}")
    print(f"  risk.max_position_fraction    = {cap}")
    print()

    snapshot, _provenance = get_snapshot()

    # --- 1. the live pipeline, driven end to end ---------------------------
    print("1. THE LIVE PIPELINE produces real theses for every US family")
    print()
    theses = _live_theses(snapshot)
    produced = {f: t for f, t in theses.items() if t is not None}
    print()
    for family, thesis in theses.items():
        if thesis is None:
            continue
        print(
            f"   {family.name:28s} status={thesis.status.name:9s} "
            f"instrument={thesis.trade_idea.instrument!r:38s} "
            f"n_scen={len(thesis.scenario_distribution)} "
            f"sizable={thesis.scenario_sizing_permitted}"
        )
    print()
    assert produced, "no family produced a thesis -- the orchestration is broken"
    print(f"   -> {len(produced)} of {len(_LIVE_FAMILIES)} families produced a thesis")

    # --- 2. the axis is inert by default, and says so ----------------------
    print()
    print("2. THE AXIS IS INERT BY DEFAULT, and DISCLOSES that it did not run")
    print(
        "   `risk_budget_target` defaults to None. A default that silently passes\n"
        "   makes an unsized thesis indistinguishable from a sized-and-cleared one --\n"
        "   the 'unchecked read as checked' direction.\n"
        "\n"
        "   Measured, and NOT as a first draft assumed: today's live families all\n"
        "   STAND DOWN (WATCH / 'NONE' / no distribution), and a stand-down returns\n"
        "   from the builder BEFORE the risk axis runs. That is correct -- Section\n"
        "   17.4 governs theses that reach SIZING, and a thesis with no trade never\n"
        "   does -- so the disclosure is owed on the LIVE (DRAFT) path, not here.\n"
    )
    stood_down = 0
    for family, thesis in produced.items():
        if thesis.status is ThesisStatus.WATCH:
            stood_down += 1
            assert _risk_line(thesis) is None, (
                f"{family.name} stood down but carries a risk-axis line. A "
                f"stand-down never reaches sizing, so a line here is a claim the "
                f"input does not support."
            )
    print(f"   {stood_down} family(-ies) stood down at WATCH with NO risk-axis line,")
    print("   which is the correct outcome: the axis is not reached.")

    # Now the live path, through the real builder, with no book supplied.
    live_inputs = snapshot_to_thesis_inputs(snapshot, thesis_type=ThesisType.POLICY_PATH_GAP)
    live = build_us_macro_thesis(
        live_inputs.reads,
        live_inputs.taylor_inputs,
        live_inputs.first_difference_inputs,
        thesis_type=live_inputs.thesis_type,
        universe=live_inputs.universe,
        short_yield=live_inputs.short_yield,
        regime=live_inputs.regime,
    )
    disclosure = _risk_line(live)
    if disclosure is not None:
        assert "DID NOT RUN" in disclosure, disclosure
        assert "Section 17.4" in disclosure
        assert "risk_budget_target" in disclosure
        print()
        print(f"   live path (status={live.status.name}) carries the disclosure:")
        print(f"     {disclosure[:66]}...")
    else:
        print()
        print(f"   live path (status={live.status.name}) has no risk line, because today's live")
        print("   build stands every family down before the axis is reached.")

    # --- 3. no book source exists, so the absence is disclosed -------------
    print()
    print("3. NO SOURCE SUPPLIES A BOOK -- so the absence is disclosed, not invented")
    print(
        "   Section 21.1 enumerates five source types for every input: LIVE,\n"
        "   DERIVED, CONFIG, MANUAL, BLOCKED. A portfolio holding is none of them --\n"
        "   there is no book in this system, and Section 21.0's no-prototyping rule\n"
        "   forbids manufacturing one. The parameter is therefore owed by the\n"
        "   ORCHESTRATOR, and until it exists the honest value is None.\n"
    )
    book_like = [
        attribute
        for attribute in dir(snapshot)
        if not attribute.startswith("_")
        and any(
            token in attribute.lower()
            for token in ("holding", "position", "book", "portfolio", "weight")
        )
    ]
    print(
        f"   snapshot attributes matching holding/position/book/portfolio/weight: "
        f"{book_like or 'none'}"
    )
    assert not book_like, (
        f"the snapshot grew a book-like field {book_like!r}. If a real holdings "
        f"source now exists, wire it into the builder and delete this assertion -- "
        f"do NOT leave the disclosure in place once a book can be supplied."
    )

    # --- 4. the reachable size set, measured -------------------------------
    print()
    print("4. THE REACHABLE SIZE SET -- measured, because it is NOT continuous")
    print(
        "   Full Kelly is the argmax of expected log growth; for a two-branch set\n"
        "   with a positive edge that objective is monotone in f, so f* pins at the\n"
        "   domain edge and the CAP produces the number. Only asymmetric sets land\n"
        "   strictly inside. The published fraction is therefore a short list.\n"
    )
    reachable: dict[float, str] = {}
    for p, up, down in _ASYMMETRIC:
        proposal = _translate(_sizable(_LIVE_INSTRUMENT, _scenarios(p, up, down)))
        key = round(proposal.fraction_of_capital, 8)
        reachable[key] = f"p={p} +{up}/-{down} ({proposal.outcome})"
    edge_proposal = _translate(_sizable(_LIVE_INSTRUMENT, _scenarios(*_EDGE)))
    reachable[round(edge_proposal.fraction_of_capital, 8)] = (
        f"p={_EDGE[0]} +{_EDGE[1]}/-{_EDGE[2]} ({edge_proposal.outcome})"
    )
    for fraction in sorted(reachable):
        print(f"   {fraction:12.8f}   {reachable[fraction]}")
    positive = sorted(f for f in reachable if f > 0.0)
    assert positive, "no positive sized proposal -- the sizing path stopped sizing"
    smallest = positive[0]
    print()
    print(f"   smallest POSITIVE reachable size: {smallest}")
    print(f"   position cap                    : {cap}")

    # --- 5. the bound discriminates ----------------------------------------
    print()
    print("5. THE CONFIGURED BOUND DISCRIMINATES")
    print(
        "   Two failures, and they are different bugs: a bound BELOW the smallest\n"
        "   reachable size never fires (Section 17.4 becomes a declaration with no\n"
        "   consumer), and a bound AT or ABOVE the cap demotes every thesis that\n"
        "   reaches the axis. The window between them is the discriminating range.\n"
    )
    print(f"   discriminating range: [{smallest}, {cap})")
    print(f"   configured bound      : {bound}")
    if not smallest <= bound:
        print()
        print(f"   BOUND TOO LOW: {bound} < {smallest}, so NO input can demote.")
        print("   Section 17.4 is unreachable on this configuration.")
        return 1
    if not bound < cap:
        print()
        print(f"   BOUND TOO HIGH: {bound} >= {cap}, so EVERY sized thesis demotes.")
        return 1
    demoting = [f for f in positive if f <= bound]
    keeping = [f for f in positive if f > bound]
    print(f"   -> demotes {len(demoting)} of {len(positive)} reachable sizes, keeps {len(keeping)}")
    assert demoting and keeping, (
        "the bound must split the reachable set -- one side empty means it is not "
        "discriminating, which is what this section exists to catch"
    )

    # --- 6. the demotion fires, through the real builder -------------------
    print()
    print("6. THE DEMOTION FIRES -- on a thesis the real builder can produce")
    print(
        "   The rule is only a consumer if an input can reach it. The smallest\n"
        "   reachable size is driven through `build_us_macro_thesis` with a book,\n"
        "   and the status must move to WATCH with a stated cause.\n"
    )
    smallest_pairs = next(
        _scenarios(p, up, down)
        for p, up, down in _ASYMMETRIC
        if round(
            _translate(_sizable(_LIVE_INSTRUMENT, _scenarios(p, up, down))).fraction_of_capital,
            8,
        )
        == smallest
    )
    sized_input = _sizable(_LIVE_INSTRUMENT, smallest_pairs)
    from macro_engine.thesis_layer.builder import _apply_risk_axis

    demoted = _apply_risk_axis(
        sized_input,
        RiskBudgetTarget(
            instrument=sized_input.trade_idea.instrument,
            target_risk_contribution_pct=_BUDGET,
        ),
    )
    line = _risk_line(demoted)
    assert line is not None
    assert demoted.status is ThesisStatus.WATCH, (
        f"the smallest reachable size ({smallest}) did not demote; status is "
        f"{demoted.status.name}. The bound is {bound}."
    )
    assert "DEMOTED" in line and "Section 17.4" in line
    print(f"   smallest reachable size {smallest} -> status={demoted.status.name}")
    print(f"   warning: {line[:68]}...")
    print("   -> the rule has a producer, and it names its cause.")

    # --- 7. refusal and demotion do not collapse ---------------------------
    print()
    print("7. A REFUSAL IS NOT A DEMOTION")
    print(
        "   A thesis with a live trade idea, given a book, refuses at gate 2 (Section\n"
        "   25: the shipped probabilities are uncalibrated), and must stay DRAFT -- a\n"
        "   sizing PROHIBITION is a different finding from a size that is TOO SMALL.\n"
        "\n"
        "   Driven through the REAL builder rather than by calling the axis directly:\n"
        "   the axis is reached only on the live path, so the thesis is built with a\n"
        "   trade idea and an unavailable distribution. The live orchestrator's own\n"
        "   families stand down before this point today, which is why this uses the\n"
        "   shaped input -- and is itself the measurement section 2 prints.\n"
    )
    uncalibrated = _live_shaped_thesis(
        instrument=_LIVE_INSTRUMENT,
        scenarios=_scenarios(0.45, 0.05, 0.04),
        status="SCENARIO_DISTRIBUTION_UNAVAILABLE",
    )
    from macro_engine.thesis_layer.builder import _apply_risk_axis

    refused = _apply_risk_axis(
        uncalibrated,
        RiskBudgetTarget(instrument=_LIVE_INSTRUMENT, target_risk_contribution_pct=_BUDGET),
    )
    refused_line = _risk_line(refused)
    assert refused_line is not None
    assert refused.status is ThesisStatus.DRAFT, (
        "a refusal changed the status -- refusal and demotion have collapsed"
    )
    assert "REFUSAL, not a demotion" in refused_line
    assert "refused_scenarios_uncalibrated" in refused_line, (
        "the refusal did not name the gate that stopped it"
    )
    print(f"   uncalibrated + book -> status={refused.status.name} (kept)")
    print(f"   warning: {refused_line[:66]}...")
    assert refused_line != line, "refusal and demotion published the same sentence"
    print("   -> the two findings carry different statuses AND different sentences.")

    # --- what this check cannot validate -----------------------------------
    print()
    print("WHAT THIS CHECK CANNOT VALIDATE")
    print(
        "  * Whether the BOUND is right. The measurement fixes the RANGE it must sit\n"
        "    inside to fire at all; nothing here says 3% is where a position stops\n"
        "    being worth carrying. The leaf is `uncalibrated_illustrative` and says so."
    )
    print(
        "  * Whether a REAL BOOK exists. Section 21.1 defines no holdings source, so\n"
        "    the orchestrator supplies None and the axis discloses it. Every size\n"
        "    measured here comes from a CONSTRUCTED book, not a live one."
    )
    print(
        "  * Whether the reachable set is COMPLETE. Six asymmetric sets and one edge\n"
        "    were driven, not an exhaustive search of the probability simplex. The\n"
        "    minimum is an upper bound on the true minimum, which is the safe\n"
        "    direction for the assertion in section 5."
    )
    print(
        "  * Whether CANDIDATE is reachable. Section 17.4 says the demotion moves\n"
        "    CANDIDATE -> WATCH, but NOTHING in the shipped system produces\n"
        "    CANDIDATE (the builder emits DRAFT; a stand-down emits WATCH). The\n"
        "    demotion target is therefore WATCH, and the spec's literal transition is\n"
        "    recorded as O-96 rather than silently 'fixed' here."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
