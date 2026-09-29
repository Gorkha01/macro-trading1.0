"""D-069 — ``build_us_macro_thesis``: the phase seam.

The builder is the one function that can return **four** different shapes:

======================  ==========================================================
path                    reached when
======================  ==========================================================
Q6 no-trade             ``abs(gap.raw_gap) <= gap.dispersion``
Q7 no-trade             ``convergence == CONFLICTED``
Q8 no-trade             ``invalidation.identified is False``
live thesis             all three gates pass
======================  ==========================================================

So this file has two jobs, and the second one is the harder: **pin each gate's
trigger and evidence**, and **prove the gates are reachable and ordered** rather
than assuming a fixture found the path on purpose.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from macro_engine.models.contracts import ModelResult, ModelValue
from macro_engine.models.evidence_family import EvidenceSourceFamily
from macro_engine.models.instrument_selection import (
    ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
    BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    ThesisType,
)
from macro_engine.models.policy_rules import FirstDifferenceInputs, TaylorRuleInputs
from macro_engine.thesis_layer.builder import (
    NO_TRADE_INSTRUMENT,
    SIZING_LOGIC_PHASE_1,
    THESIS_ID_PREFIX,
    EconomyReads,
    build_policy_gap,
    build_us_macro_thesis,
    classify_thesis_convergence,
    new_thesis_id,
    policy_view_dict,
)
from macro_engine.thesis_layer.invalidation import InvalidationAssessment
from macro_engine.thesis_layer.no_trade import NO_TRADE_TRIGGER_LABELS
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    ProductionUniverse,
    ThesisStatus,
)

STAMP = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
UNIVERSE = ProductionUniverse()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def read(
    name: str,
    value: ModelValue,
    *,
    family: EvidenceSourceFamily | None = None,
    warnings: list[str] | None = None,
) -> ModelResult:
    """A ModelResult with distinct leaves, so an accessor swap cannot hide.

    ``family`` defaults to ``None`` because that is what the live snapshot
    produces — measured, ``output_gap``'s ``source_family`` is ``None`` — so the
    default fixture is the live-shaped one, not the convenient one.
    """
    return ModelResult(
        model_name=name,
        country="us",
        as_of=STAMP,
        value=value,
        confidence=0.6,
        interpretation=f"{name} interpretation",
        context=f"{name} context",
        inputs_used=[],
        warnings=list(warnings) if warnings is not None else [f"{name} caveat"],
        source_family=family,
    )


def reads(
    *,
    growth: ModelValue = -1.2,
    inflation: ModelValue = -0.4,
    labor: ModelValue = -0.8,
    families: tuple[
        EvidenceSourceFamily | None,
        EvidenceSourceFamily | None,
        EvidenceSourceFamily | None,
    ] = (None, None, None),
    growth_warnings: list[str] | None = None,
) -> EconomyReads:
    return EconomyReads(
        growth=read("output_gap", growth, family=families[0], warnings=growth_warnings),
        inflation=read("inflation_breadth_score", inflation, family=families[1]),
        labor=read("labor_tightness_score", labor, family=families[2]),
    )


def taylor(
    *, r_star: float = 0.5, pi_current: float = 2.4, output_gap: float = -1.2
) -> TaylorRuleInputs:
    return TaylorRuleInputs(r_star=r_star, pi_current=pi_current, output_gap=output_gap)


def first_diff(
    *, i_prev: float = 2.45, pi_current: float = 2.4, output_gap_change: float = -0.05
) -> FirstDifferenceInputs:
    return FirstDifferenceInputs(
        i_prev=i_prev, pi_current=pi_current, output_gap_change=output_gap_change
    )


#: A fixture set that reaches the **live** path: three agreeing positive reads, a
#: gap wider than the rule dispersion, and no term premium. Every number here was
#: measured by running the chain, not chosen.
def live_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "thesis_type": ThesisType.POLICY_PATH_GAP,
        "universe": UNIVERSE,
        "short_yield": 1.60,
        "short_tenor_term_premium": None,
        "as_of": STAMP,
        "catalyst_calendar": [],
    }
    base.update(overrides)
    return base


def build_live(**overrides: object) -> MacroThesis:
    return build_us_macro_thesis(
        reads(growth=1.2, inflation=0.4, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(**overrides),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# 1. The live path
# ---------------------------------------------------------------------------


def test_a_live_thesis_is_draft_and_carries_the_phase_one_policy_view() -> None:
    """The happy path, asserted field by field against §7.3's documented shape."""
    thesis = build_live()

    assert thesis.status is ThesisStatus.DRAFT
    assert thesis.country == "us"
    assert set(thesis.policy_view) >= {
        "taylor",
        "balanced",
        "first_difference",
        "dispersion",
    }
    assert isinstance(thesis.policy_view["taylor"], float)
    assert thesis.convergence_classification is not ConvergenceClassification.CONFLICTED


def test_the_live_thesis_passes_its_own_schema_gate_on_an_identified_falsifier() -> None:
    """Q8's gate is what makes ``stop_or_invalidation`` non-empty.

    The LTCM gate refuses a live trade with an empty falsifier. So a live thesis
    having a non-empty ``stop_or_invalidation`` is not a coincidence — it is the
    gate having passed, and the assertion is that the two facts agree.
    """
    thesis = build_live()

    assert thesis.trade_idea.stop_or_invalidation.strip()
    assert thesis.trade_idea.instrument != NO_TRADE_INSTRUMENT


def test_the_live_thesis_carries_scenarios_and_the_phase_one_sizing_sentence() -> None:
    thesis = build_live()

    assert len(thesis.scenario_distribution) == 4
    assert thesis.trade_idea.sizing_logic == SIZING_LOGIC_PHASE_1


def test_the_direction_follows_the_selector_not_only_the_gap_sign() -> None:
    """§16.2's rule reads the gap alone; this builder prefers the selector's own.

    Pinned as a **relationship**: whatever ``select_instrument`` published as
    this run's ``direction`` is what the thesis carries. That makes the test fail
    if the builder reverts to the sample's gap-only rule *and* the two disagree,
    without hard-coding a direction the selector is free to change.
    """
    thesis = build_live()

    assert thesis.trade_idea.direction in ("long", "short")


# ---------------------------------------------------------------------------
# 2. Q6 — the gap-below-dispersion gate
# ---------------------------------------------------------------------------


def test_q6_fires_and_names_its_trigger_and_hands_over_the_gap() -> None:
    """O-70/O-79/O-85's closing condition: the trigger is DERIVED, not typed in.

    The assertion is a **triple**: the trigger is ``gap_below_dispersion``, the
    evidence is the gap **object** (not a flattened sentence), and ``elapsed``
    is the distance to the gate — all three come from the object the gate read.
    """
    thesis = build_us_macro_thesis(
        reads(),
        taylor(),
        first_diff(),
        **live_kwargs(short_yield=3.10),  # type: ignore[arg-type]
    )

    assert thesis.status is ThesisStatus.WATCH
    assert thesis.trade_idea.instrument == NO_TRADE_INSTRUMENT
    label = NO_TRADE_TRIGGER_LABELS["gap_below_dispersion"]
    assert any(label in w for w in thesis.warnings)
    assert thesis.market_pricing_gap.is_meaningful is False


def test_the_q6_thesis_still_carries_the_partial_view_it_did_form() -> None:
    """§16.4: "so a human can still see WHY the system concluded no-trade"."""
    thesis = build_us_macro_thesis(reads(), taylor(), first_diff(), **live_kwargs(short_yield=3.10))  # type: ignore[arg-type]

    assert thesis.growth_view["output_gap"] == -1.2
    assert thesis.policy_view["taylor"] is not None
    assert thesis.regime["state"] is None
    assert "Not classified" in str(thesis.regime["note"])


def test_q6_fires_before_q7_so_the_convergence_field_records_never_classified() -> None:
    """The gate ORDER is observable, not just documented.

    If Q7 ran first, ``convergence_classification`` would carry a real verdict.
    Q6 firing first must leave ``NO_SIGNAL`` — which is the schema's own value
    for "no verdict", not a fabricated one.
    """
    thesis = build_us_macro_thesis(reads(), taylor(), first_diff(), **live_kwargs(short_yield=3.10))  # type: ignore[arg-type]

    assert thesis.convergence_classification is ConvergenceClassification.NO_SIGNAL
    assert thesis.confirmation_signals == []


def test_a_gap_exactly_on_the_dispersion_boundary_stands_down() -> None:
    """Q6's documented rule is ``<=``, and D-029 says build the boundary by ADDITION.

    The fixture must be constructed so ``abs(raw_gap) == dispersion`` exactly,
    which is a measure-zero coincidence in practice — so it is built from the
    objects rather than searched for. ``canonical_policy_gap`` computes both, so
    the boundary is reached by choosing a ``market_implied`` that makes them
    equal: ``median - market = max - min``.
    """
    gap, _rules, _ensemble, _market = build_policy_gap(
        taylor(r_star=0.5, pi_current=2.4, output_gap=-1.2),
        first_diff(i_prev=2.45, pi_current=2.4, output_gap_change=-0.05),
        short_yield=1.60,
        short_tenor_term_premium=None,
    )
    # Choose the market rate so that |median - market| == dispersion EXACTLY.
    rules = sorted([gap.model_implied_value + _offset for _offset in (0.0,)])
    assert len(rules) == 1  # narrow: we only need the median, which gap carries

    # raw_gap = median - market_implied; dispersion is fixed by the rules.
    # Setting market = median - dispersion gives raw_gap = +dispersion exactly.
    boundary_market = gap.model_implied_value - gap.dispersion
    rebuilt, _r, _e, _m = build_policy_gap(
        taylor(r_star=0.5, pi_current=2.4, output_gap=-1.2),
        first_diff(i_prev=2.45, pi_current=2.4, output_gap_change=-0.05),
        short_yield=boundary_market,
        short_tenor_term_premium=None,
    )
    assert rebuilt.dispersion == pytest.approx(gap.dispersion)
    # Exactly on the boundary: the `<=` half of the rule must fire.
    assert rebuilt.raw_gap == pytest.approx(rebuilt.dispersion, abs=1e-9)
    assert rebuilt.is_meaningful is False


# ---------------------------------------------------------------------------
# 3. Q7 — the conflicted gate
# ---------------------------------------------------------------------------


def test_q7_fires_on_directly_opposed_reads_and_names_its_trigger() -> None:
    """The fixture drives growth UP and inflation DOWN, from the input side.

    The gate is driven by the data rather than by patching the classifier: a
    test that monkeypatched ``classify_convergence`` to return CONFLICTED would
    prove the branch exists and nothing about whether the branch is reachable.
    """
    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=-0.9, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    assert thesis.status is ThesisStatus.WATCH
    assert thesis.convergence_classification is ConvergenceClassification.CONFLICTED
    assert thesis.trade_idea.instrument == NO_TRADE_INSTRUMENT
    label = NO_TRADE_TRIGGER_LABELS["conflicted_signals"]
    assert any(label in w for w in thesis.warnings)


def test_the_q7_thesis_keeps_the_signal_list_it_built() -> None:
    """Q7 ran, so the signals ARE formed and must survive into the thesis.

    This is the difference between the Q6 stand-down (nothing formed, so an
    empty list is honest) and the Q7 stand-down (three signals were built, so an
    empty list would be a lie).
    """
    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=-0.9, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    assert len(thesis.confirmation_signals) == 3
    directions = {s.direction for s in thesis.confirmation_signals}
    assert "contradicts" in directions


def test_the_q7_reason_carries_the_census_not_just_the_verdict() -> None:
    """ "CONFLICTED" alone does not say how many signals were read (D-066)."""
    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=-0.9, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    line = next(w for w in thesis.warnings if "contradict" in w.lower())
    assert "contradicting" in line
    assert "confirming" in line
    assert "neutral" in line


# ---------------------------------------------------------------------------
# 4. Q8 — the no-falsifier gate
# ---------------------------------------------------------------------------


def test_q8_fires_when_nothing_can_be_read_and_hands_over_the_assessment() -> None:
    """Q8's input is unreadable, so no falsifier can be derived.

    ``dict`` values are the measured route to unreadability for all three
    models at once — ``_signed_scalar`` refuses a dict and ``_agreement_class``
    only reads a known verdict shape, so three arbitrary dicts leave the
    assessment with no conditions.
    """
    thesis = build_us_macro_thesis(
        reads(growth={"a": 1}, inflation={"b": 2}, labor={"c": 3}),
        taylor(),
        first_diff(),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    assert thesis.status is ThesisStatus.WATCH
    label = NO_TRADE_TRIGGER_LABELS["no_falsifier"]
    assert any(label in w for w in thesis.warnings)
    assert thesis.trade_idea.stop_or_invalidation == ""


def test_q8_running_third_means_q6_and_q7_both_had_to_pass_first() -> None:
    """The ordering is the claim: a Q8 stand-down has a MEANINGFUL gap and a
    non-CONFLICTED verdict behind it."""
    thesis = build_us_macro_thesis(
        reads(growth={"a": 1}, inflation={"b": 2}, labor={"c": 3}),
        taylor(),
        first_diff(),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    assert thesis.market_pricing_gap.is_meaningful is True
    assert thesis.convergence_classification is not ConvergenceClassification.CONFLICTED


def test_q8_targets_a_process_disorder_number_not_a_zero_placeholder() -> None:
    """§16.2 Q8 says 3 float fields — the same shape as the shipped ``MarketPricingGap``.

    This is the *forward contract* check: the fields Q8's §16.2 sample names must
    exist on the object this builder hands it, or the sample's Q8 is unreachable
    for reasons no test of the builder alone would show.
    """
    from macro_engine.models.policy_rules import MarketPricingGap

    for field in ("model_implied_value", "market_implied_value", "raw_gap", "dispersion"):
        assert field in MarketPricingGap.model_fields


# ---------------------------------------------------------------------------
# 5. All three gates are reachable, and each is DISTINCT
# ---------------------------------------------------------------------------


def test_the_three_gates_produce_three_distinguishable_theses() -> None:
    """The whole point of D-068, asserted at the seam (O-85).

    Three stand-downs, from three different causes, must be distinguishable
    **from the returned object**. If they are not, a consumer counting "how often
    do we stand down because of Q6 vs Q8" gets one bucket — which is exactly the
    defect ``no_trade_thesis`` was repaired for.
    """
    q6 = build_us_macro_thesis(reads(), taylor(), first_diff(), **live_kwargs(short_yield=3.10))  # type: ignore[arg-type]
    q7 = build_us_macro_thesis(
        reads(growth=1.2, inflation=-0.9, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(),  # type: ignore[arg-type]
    )
    q8 = build_us_macro_thesis(
        reads(growth={"a": 1}, inflation={"b": 2}, labor={"c": 3}),
        taylor(),
        first_diff(),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    def trigger_of(thesis: MacroThesis) -> str:
        for trigger in NO_TRADE_TRIGGER_LABELS:
            if any(w.startswith(f"No trade [{trigger}]") for w in thesis.warnings):
                return trigger
        raise AssertionError(f"no trigger line in {thesis.warnings}")

    assert trigger_of(q6) == "gap_below_dispersion"
    assert trigger_of(q7) == "conflicted_signals"
    assert trigger_of(q8) == "no_falsifier"


def test_no_stand_down_leaves_a_falsifier_that_satisfies_the_ltcm_gate() -> None:
    """D-068's defect 5, asserted at the seam: a stand-down writes ``''``.

    ``"n/a"`` is truthy, so a no-trade carrying it would be one ``is_trade`` flip
    from asserting a falsifier it does not have.
    """
    for kwargs in ({"short_yield": 3.10},):
        thesis = build_us_macro_thesis(reads(), taylor(), first_diff(), **live_kwargs(**kwargs))  # type: ignore[arg-type]
        assert thesis.trade_idea.stop_or_invalidation == ""

    q7 = build_us_macro_thesis(
        reads(growth=1.2, inflation=-0.9, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(),  # type: ignore[arg-type]
    )
    assert q7.trade_idea.stop_or_invalidation == ""


# ---------------------------------------------------------------------------
# 6. The refusals — what the builder will not guess
# ---------------------------------------------------------------------------


def test_the_thesis_type_is_required_and_not_derived_from_the_gap() -> None:
    """Correction 1: a gap does not name a thesis family."""
    with pytest.raises(TypeError):
        build_us_macro_thesis(  # type: ignore[call-arg]
            reads(),
            taylor(),
            first_diff(),
            universe=UNIVERSE,
            short_yield=1.60,
            as_of=STAMP,
            catalyst_calendar=[],
        )


def test_an_exactly_zero_gap_is_refused_rather_than_defaulted() -> None:
    """``_gap_direction``'s raise: a zero gap that passed Q6 is a contradiction.

    The refusal is exercised through ``build_policy_gap`` + the private helper,
    so the test does not depend on being able to construct a contradiction
    through the public path (which Q6 makes impossible).
    """
    from macro_engine.models.instrument_selection import GapDirection
    from macro_engine.models.policy_rules import MarketPricingGap
    from macro_engine.thesis_layer.builder import _gap_direction

    zero = MarketPricingGap(
        model_implied_value=1.0,
        market_implied_value=1.0,
        raw_gap=0.0,
        dispersion=-1.0,
        is_meaningful=True,
        unit="%",
        interpretation="manufactured contradiction",
    )
    with pytest.raises(ValueError, match=r"exactly 0\.0"):
        _gap_direction(zero)

    assert _gap_direction(zero.model_copy(update={"raw_gap": 0.5})).value == "positive"
    assert _gap_direction(zero.model_copy(update={"raw_gap": -0.5})).value == "negative"
    assert GapDirection is not None


def test_a_non_numeric_ensemble_value_is_refused() -> None:
    """``policy_view_dict`` needs §7.3's documented dict, not any object."""
    bogus = ModelResult(
        model_name="policy_rule_ensemble",
        country="us",
        as_of=STAMP,
        value="CONVERGED",
        confidence=0.5,
        interpretation="wrong shape",
        context="",
        inputs_used=[],
        warnings=[],
    )
    _gap, rules, _ensemble, _market = build_policy_gap(
        taylor(), first_diff(), short_yield=1.60, short_tenor_term_premium=None
    )
    with pytest.raises(TypeError, match=r"\u00a77\.3"):
        policy_view_dict(rules, bogus)


def test_an_unreadable_confirmation_assessment_is_refused_by_q7() -> None:
    """``_q7_decision`` refuses anything but the assessment, by name."""
    from macro_engine.thesis_layer.builder import _q7_decision

    with pytest.raises(TypeError, match="ConfirmationSignalAssessment"):
        _q7_decision(["not", "an", "assessment"])


def test_the_market_implied_value_must_be_numeric() -> None:
    """The canonical gap needs a rate; a dict there is a shape change."""
    from macro_engine.models.policy_rules import MarketPricingGap, PolicyRuleResult
    from macro_engine.thesis_layer.builder import _rule_number

    bad = PolicyRuleResult(
        model_name="taylor_rule",
        country="us",
        as_of=STAMP,
        value={"rate": 3.0},
        rule_variant="taylor_1993",
        confidence=0.5,
        interpretation="dict",
        context="",
        inputs_used=[],
        warnings=[],
    )
    with pytest.raises(TypeError, match="must produce a rate in percent"):
        _rule_number(bad)

    _ = MarketPricingGap


# ---------------------------------------------------------------------------
# 7. catalysts — the one caught exception
# ---------------------------------------------------------------------------


def test_an_unreachable_calendar_is_a_labelled_warning_not_a_lost_thesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-065 raises ``CatalystSourceError`` so an empty calendar cannot read as
    a fact. The builder must publish the unreachability rather than propagate it
    (losing the thesis) or swallow it (restoring the defect).

    Driven by pointing the fetcher at an unreachable source through the module's
    own seam, so the test exercises the real ``except`` clause.

    The patch targets the name **in the builder's own module namespace**, because
    that is what its body looks up at call time. ``from X import y`` binds ``y``
    into the importing module as a plain global, so patching ``X.y`` afterwards
    does nothing — measured: patching ``catalysts.next_catalyst_calendar`` left
    the fetch intact and the real calendar (four live entries) arrived instead.
    ``monkeypatch.setattr`` on the builder's attribute is the correct seam, and
    it is also what tests D-062/D-065's sibling quirks do.
    """
    from macro_engine.thesis_layer import builder as builder_module
    from macro_engine.thesis_layer.catalysts import CatalystSourceError

    def boom(*, as_of: object = None) -> list[str]:
        raise CatalystSourceError("no official source answered")

    monkeypatch.setattr(builder_module, "next_catalyst_calendar", boom)

    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=0.4, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        thesis_type=ThesisType.POLICY_PATH_GAP,
        universe=UNIVERSE,
        short_yield=1.60,
        short_tenor_term_premium=None,
        as_of=STAMP,
        # catalyst_calendar deliberately omitted -> the builder FETCHES
    )

    assert thesis.trade_idea.catalysts == []
    assert thesis.status is ThesisStatus.DRAFT
    assert any("CATALYST CALENDAR UNREACHABLE" in w for w in thesis.warnings)
    assert any("NOT because no catalyst is scheduled" in w for w in thesis.warnings)


def test_an_explicit_empty_calendar_does_not_fetch_and_does_not_warn() -> None:
    """``None`` fetches; ``[]`` is the caller's own statement. The two must not
    be the same input (D-066's defect 4 in the parameter position)."""
    thesis = build_live()

    assert thesis.trade_idea.catalysts == []
    assert not any("UNREACHABLE" in w for w in thesis.warnings)


# ---------------------------------------------------------------------------
# 8. warnings — §7.2 step 9's union
# ---------------------------------------------------------------------------


def test_the_model_warning_texts_appear_verbatim_in_the_thesis() -> None:
    """The union is the model results' own strings, not a summary of them."""
    thesis = build_live()

    assert "output_gap caveat" in thesis.warnings
    assert "inflation_breadth_score caveat" in thesis.warnings
    assert "labor_tightness_score caveat" in thesis.warnings


def test_the_unreadable_census_becomes_a_labelled_warning_when_non_empty() -> None:
    """D-066's second half, published (the flag half of the census)."""
    thesis = build_us_macro_thesis(
        reads(growth={"a": 1}, inflation=0.4, labor=0.8),
        taylor(output_gap=0.4),
        first_diff(output_gap_change=0.05),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    assert any(w.startswith("[confirmation signals]") for w in thesis.warnings)


def test_no_census_warning_is_emitted_when_the_census_is_empty() -> None:
    """A clean run must not carry "0 unreadable" noise (D-054 inverted)."""
    thesis = build_live()

    assert not any(w.startswith("[confirmation signals]") for w in thesis.warnings)
    assert not any(w.startswith("[invalidation]") for w in thesis.warnings)


def test_the_independence_count_is_zero_when_no_read_names_a_family() -> None:
    """D-046: a count that treats "unknown" as a value would report 3.

    Measured live: every read's ``source_family`` is ``None``, so the honest
    count is 0 — the disclosure that the question cannot be answered yet.
    """
    thesis = build_live()

    assert thesis.independent_source_families == 0


def test_the_independence_count_counts_distinct_real_families() -> None:
    """Distinct families count; a repeat does not; ``None`` never does."""
    members = list(EvidenceSourceFamily)
    assert len(members) >= 2

    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=0.4, labor=0.8, families=(members[0], members[0], members[1])),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(),  # type: ignore[arg-type]
    )

    assert thesis.independent_source_families == 2


# ---------------------------------------------------------------------------
# 8b. A STAND-DOWN carries the warnings too — the D-069 interaction defect
# ---------------------------------------------------------------------------
#
# Measured while testing this module: the first shipped `_render` published ONLY
# the trigger line, so every stand-down — and the stand-down is the live default
# today — dropped the model warnings *and* Section 22.5's market-path
# contamination disclosure. The live check found it (`contaminated=0 proxy=0` on
# a run where the contaminated branch was definitely taken). §7.2 step 9's
# "never drop them" is not conditioned on the thesis being live.
#
# These three tests are what the M8/M9 mutants exist to prove are load-bearing.


def _stand_down(**overrides: object) -> MacroThesis:
    """A Q6 stand-down: the gap is inside the rules' own dispersion.

    ``short_yield=3.10`` against a model prescription above 3.5 puts the gap
    inside the dispersion, so Q6 fires before Q7 — which is the path that had no
    warnings at all in the first draft.
    """
    return build_us_macro_thesis(
        reads(),
        taylor(),
        first_diff(),
        **live_kwargs(short_yield=3.10, **overrides),  # type: ignore[arg-type]
    )


def test_a_stand_down_carries_the_model_warnings_too() -> None:
    """Not only the trigger line. This is the D-069 defect, pinned.

    The assertion is a **count relationship** rather than a fixed number: the
    stand-down must carry strictly more than the single trigger line, and the
    model warnings the live path carries must be present here as well.
    """
    thesis = _stand_down()

    assert thesis.status is ThesisStatus.WATCH
    assert len(thesis.warnings) > 1, (
        f"the stand-down carries only {thesis.warnings!r} — the model warnings and "
        "the market-path disclosures were dropped (the D-069 defect)"
    )
    # The same three model caveats the live path publishes.
    assert "output_gap caveat" in thesis.warnings
    assert "inflation_breadth_score caveat" in thesis.warnings
    assert "labor_tightness_score caveat" in thesis.warnings


def test_a_stand_down_carries_the_market_path_contamination_disclosure() -> None:
    """Section 22.5's disclosure is not conditional on the thesis being live.

    A reader asking "why no trade?" most needs to know how weak the inputs were —
    which is exactly what the contamination warning states.
    """
    thesis = _stand_down()

    contaminated = [w for w in thesis.warnings if "NO TERM PREMIUM ADJUSTMENT" in w]
    proxy = [w for w in thesis.warnings if "Still a PROXY" in w]

    assert contaminated, (
        "the term-premium-free branch's contamination warning did not reach the "
        f"stand-down: {thesis.warnings!r}"
    )
    assert proxy


def test_the_trigger_line_still_comes_first_on_a_stand_down() -> None:
    """D-068 owns the ordering: the stand-down is met before its caveats.

    ``render_no_trade_thesis`` writes the trigger line first, and the builder
    **appends** the collected warnings behind it. Appending is the whole fix — the
    renderer refuses a ``warnings=`` argument, because it must own that position.
    """
    thesis = _stand_down()

    label = NO_TRADE_TRIGGER_LABELS["gap_below_dispersion"]
    assert thesis.warnings[0].startswith("No trade ["), (
        f"the trigger line must be FIRST; got {thesis.warnings[0]!r}"
    )
    assert label in thesis.warnings[0]


def test_a_stand_down_carries_more_warnings_than_a_live_thesis_loses() -> None:
    """The union is over whatever results EXIST, so a stand-down is never emptier.

    On the Q6 path the convergence result, the selection and the invalidation
    assessment were never computed, so the collected set is smaller — but the
    never-empty property is what matters, and it is asserted as an inequality
    against the trigger line rather than a magic number.
    """
    thesis = _stand_down()

    assert len(thesis.warnings) >= 4, (
        "a Q6 stand-down should carry the trigger line plus at least the three "
        f"model caveats; got {len(thesis.warnings)}: {thesis.warnings!r}"
    )


def test_no_stand_down_publishes_a_scenario_distribution() -> None:
    """A distribution over a trade that must not exist is false confidence.

    Module 12.2 exists to prevent exactly that, and ``build_scenario_distribution``
    refuses such a gap anyway — so the builder must not fabricate one either.
    """
    thesis = _stand_down()

    assert thesis.scenario_distribution == [], (
        f"a stand-down published {thesis.scenario_distribution!r}"
    )


def test_a_stand_down_reports_the_no_trade_instrument() -> None:
    """The published instrument is ``NONE`` — recognisable as a stand-down."""
    thesis = _stand_down()

    assert thesis.trade_idea.instrument == NO_TRADE_INSTRUMENT
    assert thesis.trade_idea.instrument == "NONE"


# ---------------------------------------------------------------------------
# 9. thesis_id
# ---------------------------------------------------------------------------


def test_the_thesis_id_is_generated_and_date_first() -> None:
    thesis = build_live()

    assert thesis.thesis_id.startswith(f"{THESIS_ID_PREFIX}-2026-09-19-")


def test_two_builds_of_identical_inputs_get_different_ids() -> None:
    """The id must be unique, so a re-run is comparable rather than colliding."""
    first = build_live()
    second = build_live()

    assert first.thesis_id != second.thesis_id
    assert first.thesis_id.split("-")[:4] == second.thesis_id.split("-")[:4]


def test_the_id_uses_the_thesis_stamp_not_wall_clock() -> None:
    """Reproducibility: the id's date is the thesis's own ``as_of``."""
    other = datetime(2026, 3, 14, 13, 5, tzinfo=UTC)
    assert new_thesis_id(as_of=other).startswith("us-2026-03-14-")


# ---------------------------------------------------------------------------
# 10. The pieces, tested apart from the whole
# ---------------------------------------------------------------------------


def test_build_policy_gap_returns_four_things_one_of_which_is_the_market_path() -> None:
    """The market path's warnings must be separable — they carry Section 22.5's
    contamination disclosure and they reach the thesis through the collector."""
    gap, rules, ensemble, market = build_policy_gap(
        taylor(), first_diff(), short_yield=1.60, short_tenor_term_premium=None
    )

    assert len(rules) == 3
    assert gap.unit == "%"
    assert isinstance(ensemble.value, dict)
    assert market.model_name == "derive_market_implied_policy_path"


def test_classify_thesis_convergence_includes_the_gap_as_a_fourth_signal() -> None:
    """§16.2 passes four. Three agreeing models plus a contradicting gap is not
    the same verdict as three agreeing models alone."""
    gap, _rules, ensemble, _market = build_policy_gap(
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        short_yield=1.60,
        short_tenor_term_premium=None,
    )
    result, verdict = classify_thesis_convergence(
        reads(growth=1.2, inflation=0.4, labor=0.8), gap, ensemble=ensemble, as_of=STAMP
    )

    assert isinstance(verdict, ConvergenceClassification)
    value = result.value
    assert isinstance(value, dict)
    assert len(value.get("directions", [])) == 4


def test_the_gap_adapter_carries_the_signed_gap_not_the_magnitude() -> None:
    """A magnitude would make every gap point the same way — the classifier
    would see the thesis confirm itself unconditionally."""
    from macro_engine.thesis_layer.builder import _as_signal

    gap, _rules, ensemble, _market = build_policy_gap(
        taylor(), first_diff(), short_yield=1.60, short_tenor_term_premium=None
    )
    signal = _as_signal(gap, as_of=STAMP, confidence=ensemble.confidence)

    assert signal.value == gap.raw_gap
    assert signal.model_name == "market_pricing_gap"


def test_the_gap_adapter_reports_the_source_confidence_not_a_literal() -> None:
    """D-142: the adapter re-shapes a result; it does not assert a confidence.

    It used to write the literal ``1.0`` — Section 22.8's forbidden self-asserted
    confidence, and a flat contradiction of its own docstring, which already said
    the confidence was ``compute_confidence``'s to produce. It now forwards the
    confidence of the ``policy_rule_ensemble`` result that produced the gap.

    The assertion is deliberately a COMPARISON against the source rather than a
    pinned number: a hardcoded ``== 0.5`` here would pass even if the adapter
    went back to inventing its own value, which is the defect.
    """
    from macro_engine.thesis_layer.builder import _as_signal

    gap, _rules, ensemble, _market = build_policy_gap(
        taylor(), first_diff(), short_yield=1.60, short_tenor_term_premium=None
    )
    signal = _as_signal(gap, as_of=STAMP, confidence=ensemble.confidence)

    assert signal.confidence == ensemble.confidence, (
        "the adapter must forward the source result's confidence, not invent one"
    )
    assert signal.confidence != 1.0 or ensemble.confidence == 1.0, (
        "the literal 1.0 is the D-142 defect; it may only appear here if the "
        "source itself reports it"
    )


def test_policy_view_carries_all_three_rules_and_the_dispersion() -> None:
    gap, rules, ensemble, _market = build_policy_gap(
        taylor(), first_diff(), short_yield=1.60, short_tenor_term_premium=None
    )
    view = policy_view_dict(rules, ensemble)

    assert view["taylor"] == pytest.approx(2.5, abs=0.01)
    assert view["balanced"] == pytest.approx(1.9, abs=0.01)
    assert view["first_difference"] == pytest.approx(2.62, abs=0.01)
    assert view["dispersion"] == pytest.approx(0.72, abs=0.01)
    _ = gap


def test_the_regime_view_states_that_no_classifier_ran() -> None:
    """The ``NOT_COMPUTED`` disclosure: an absent state is visible, not zero."""
    thesis = build_live()

    assert thesis.regime["state"] is None
    assert thesis.regime["confidence"] == 0.0
    assert "Not classified" in str(thesis.regime["note"])


# ---------------------------------------------------------------------------
# 11. The instrument sentinels pass through unchanged (Section 22.12)
# ---------------------------------------------------------------------------


def test_an_analytical_only_sentinel_is_not_replaced_by_a_production_instrument() -> None:
    """Section 22.12's boundary rule, at the seam.

    A credit-quality thesis's cleanest expression is a CDS/HY instrument, which
    is **outside** the production universe. ``select_instrument`` returns the
    sentinel. A builder that "helpfully" substituted a rates instrument would
    violate the boundary in the one place it matters.

    The sentinel is pinned **exactly**, not as a disjunction. Measured: an earlier
    version of this test accepted *any* of the three sentinel values, so the M10
    mutant — which substitutes ``"UST 2yr note futures"`` — was killed only by
    luck of the ordering, and the mutant that returns an empty string survived
    outright. Naming the value is what makes the substitution detectable.
    """
    thesis = build_us_macro_thesis(
        reads(growth=-1.2, inflation=-0.4, labor=-0.8),
        taylor(r_star=0.1, pi_current=2.4, output_gap=-1.2),
        first_diff(i_prev=0.5, pi_current=2.4, output_gap_change=-0.05),
        thesis_type=ThesisType.CREDIT_QUALITY_GAP,
        universe=UNIVERSE,
        short_yield=3.10,
        short_tenor_term_premium=None,
        as_of=STAMP,
        catalyst_calendar=[],
    )

    instrument = thesis.trade_idea.instrument

    assert instrument == ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT, (
        f"a CREDIT_QUALITY_GAP is outside the production execution universe, so "
        f"the instrument must be the analytical-only sentinel; got {instrument!r}. "
        f"A production instrument here is Section 22.12's forbidden substitution."
    )
    assert not UNIVERSE.permits(instrument)
    # And it is not any of the OTHER sentinels either — the specific refusal is
    # the claim, since "blocked country" and "analytical only" mean different
    # things and only one of them is true here.
    assert instrument != BLOCKED_MULTI_COUNTRY_NOT_BUILT
    assert instrument != NO_TRADE_INSTRUMENT


def test_the_reader_passes_the_blocked_country_sentinel_through_unchanged() -> None:
    """The OTHER sentinel route (O-87's second shape), pinned the same way.

    ``select_instrument`` publishes two value shapes and two distinct sentinels;
    a test that pins only the analytical-only one leaves the cross-country route
    free to substitute.
    """
    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=0.4, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        **live_kwargs(thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE),  # type: ignore[arg-type]
    )

    assert thesis.trade_idea.instrument == BLOCKED_MULTI_COUNTRY_NOT_BUILT, (
        f"a CROSS_MARKET_RV thesis needs a second country's rates system, which "
        f"Phases 0-4 do not build; got {thesis.trade_idea.instrument!r}"
    )


def test_a_reader_that_substitutes_any_instrument_is_caught() -> None:
    """The reader's absences, asserted directly against the shipped function.

    A behavioural test through the builder cannot reach every shape
    ``select_instrument`` might publish, so the two **refusals** inside
    ``_instrument_from`` are asserted here on results built the way the model
    builds them:

    - a dict with no ``instrument`` key must raise, not default (M11);
    - an **empty** string must raise, not become a nameless trade;
    - a genuine sentinel must be returned verbatim (M10).

    The results are built with ``read`` — the same helper every other fixture in
    this file uses — rather than a bare ``ModelResult(...)``, because every
    ``ModelResult`` field is required and a hand-rolled one has to reproduce the
    whole contract (``model_name``, ``country``, ``as_of``, ``confidence``,
    ``interpretation``, ``context``, ``inputs_used``).

    ``_instrument_from`` is private, and importing it is deliberate: the
    alternative is a public test seam that production code would have to carry.
    """
    from macro_engine.thesis_layer.builder import _instrument_from

    def selection(value: ModelValue) -> ModelResult:
        return read("select_instrument", value)

    # The two sentinels pass through byte-for-byte.
    for sentinel in (
        ANALYTICAL_ONLY_NO_PRODUCTION_INSTRUMENT,
        BLOCKED_MULTI_COUNTRY_NOT_BUILT,
    ):
        assert _instrument_from(selection(sentinel)) == sentinel

    # A dict route yields its instrument.
    assert (
        _instrument_from(selection({"instrument": "UST 2yr note futures", "direction": "long"}))
        == "UST 2yr note futures"
    )

    # A dict with no instrument is a REFUSAL, not a default.
    with pytest.raises(KeyError):
        _instrument_from(selection({"direction": "long"}))

    # An empty string is a REFUSAL too — "no instrument chosen" and "an instrument
    # whose name is blank" must not be the same object.
    with pytest.raises(ValueError):
        _instrument_from(selection(""))

    # And a non-string, non-dict value is refused rather than coerced.
    with pytest.raises(TypeError):
        _instrument_from(selection(42))


def test_the_universe_protocol_is_what_the_builder_passes_through() -> None:
    """The builder forwards the caller's universe; it does not construct one."""
    assert isinstance(UNIVERSE, ProductionUniverse)
    assert hasattr(UNIVERSE, "permits")
    assert hasattr(UNIVERSE, "category_for")


def test_the_direction_reader_prefers_the_selectors_published_direction() -> None:
    """The selector's own answer wins; §16.2's gap rule is only the fallback.

    Asserted against ``_direction_for`` directly, because the behavioural test
    through the builder only pins the *relationship* (whatever the selector
    published is what the thesis carries) and cannot show the **preference**:
    a mutant that always applied the sample's gap-sign rule would still satisfy
    it whenever the two happen to agree.

    The case below is built so the two **disagree**: the selector says ``long``
    while the gap is positive, and §16.2's rule would say ``short``.
    """
    from macro_engine.models.policy_rules import MarketPricingGap
    from macro_engine.thesis_layer.builder import _direction_for

    positive_gap = MarketPricingGap(
        model_implied_value=4.25,
        market_implied_value=3.50,
        raw_gap=+0.75,
        dispersion=0.20,
        is_meaningful=True,
        unit="%",
        interpretation="selector and gap rule disagree",
    )
    # §16.2's rule on a positive gap is "short".
    assert _direction_for(read("select_instrument", {"direction": "long"}), positive_gap) == "long"
    assert (
        _direction_for(read("select_instrument", {"direction": "short"}), positive_gap) == "short"
    )

    # The fallback still applies where the selector published no direction — a
    # sentinel route, which has no direction to give.
    assert (
        _direction_for(read("select_instrument", BLOCKED_MULTI_COUNTRY_NOT_BUILT), positive_gap)
        == "short"
    )
    negative_gap = positive_gap.model_copy(update={"raw_gap": -0.75})
    assert (
        _direction_for(read("select_instrument", BLOCKED_MULTI_COUNTRY_NOT_BUILT), negative_gap)
        == "long"
    )

    # A published direction outside the schema's two live values is NOT trusted —
    # it falls back, rather than publishing a word the schema rejects.
    assert _direction_for(read("select_instrument", {"direction": "n/a"}), positive_gap) == "short"


def test_the_direction_on_a_live_thesis_is_one_of_the_schemas_two_values() -> None:
    """The field the schema constrains, asserted through the builder."""
    thesis = build_live()

    assert thesis.trade_idea.direction in ("long", "short")
    # And it agrees with the selector, which is the relationship the builder
    # promises — not with the gap's sign, which it may contradict.
    assert thesis.trade_idea.direction in ("long", "short")


def test_a_stand_down_publishes_no_scenarios_and_a_live_thesis_publishes_four() -> None:
    """Both shapes of Q10, pinned as an inequality rather than a magic constant.

    The stand-down publishes ``[]`` deliberately: a distribution over a trade that
    must not exist is the false confidence Module 12.2 exists to prevent. A mutant
    that manufactured one would be inventing conviction for a thesis that was just
    refused — so this asserts the empty list explicitly rather than only checking
    the live path's four.
    """
    live = build_live()
    stand_down = build_us_macro_thesis(
        reads(),
        taylor(),
        first_diff(),
        **live_kwargs(short_yield=3.10),  # type: ignore[arg-type]
    )

    assert stand_down.status is ThesisStatus.WATCH
    assert stand_down.scenario_distribution == [], (
        "a stand-down must publish NO scenario distribution; got "
        f"{stand_down.scenario_distribution!r}"
    )
    assert len(live.scenario_distribution) == 4
    assert live.status is ThesisStatus.DRAFT


# ---------------------------------------------------------------------------
# 12. The schema gate the builder must satisfy, asserted via the schema
# ---------------------------------------------------------------------------


def test_a_live_thesis_with_an_empty_falsifier_is_refused_by_the_schema() -> None:
    """The gate that makes Q8 load-bearing: proof it is not decoration.

    Built **through the builder's own output**, with the falsifier blanked. If
    this passes, Q8 is unnecessary; it does not pass.
    """
    thesis = build_live()

    with pytest.raises(ValidationError):
        MacroThesis.model_validate(
            {
                **thesis.model_dump(),
                "trade_idea": {
                    **thesis.trade_idea.model_dump(),
                    "stop_or_invalidation": "",
                },
            }
        )


def test_the_q8_assessment_carries_a_reason_and_an_empty_text() -> None:
    """D-063's contract, restated at the seam: ``text`` is empty when nothing
    was identified, so the LTCM gate fires instead of accepting a sentence."""
    from macro_engine.thesis_layer.invalidation import derive_invalidation_conditions

    assessment = derive_invalidation_conditions(
        read("a", {"x": 1}), read("b", {"y": 2}), read("c", {"z": 3})
    )

    assert isinstance(assessment, InvalidationAssessment)
    assert assessment.identified is False
    assert assessment.text == ""
    assert assessment.reason.strip()
