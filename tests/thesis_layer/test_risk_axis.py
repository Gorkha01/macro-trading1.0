"""D-073 — Section 17.4's risk axis: the ONE place a risk finding moves a status.

Section 17.4 is the only rule in the specification that closes the loop from the
*risk* layer back into the thesis *lifecycle*, and its sentence is a principle
with exactly one unquantified word in it:

    "A thesis whose ``sizing_logic`` output (once Phase 4+ auto-sizing exists)
     clips to near-zero against ``RiskLimits`` (e.g., liquidity constraint binds
     hard) should have its ``status`` automatically demoted from ``CANDIDATE``
     back to ``WATCH`` — a thesis that can't be sized meaningfully isn't
     actionable, regardless of conviction (directly encodes the LTCM lesson: a
     'correct' idea you can't survive-size isn't a trade yet)."

Three things about this file's job follow from that, and the third decides the
shape of most of the tests below:

1. **The rule must be reachable.** A demotion no input can cause is the
   declared-consumed-unreachable branch this project has recorded eight times
   (D-045/D-046/D-048, O-53, and twice inside D-072). One test here constructs
   the input that causes it; another proves the *shipped* configuration cannot.

2. **The demotion must not swallow adjacent findings.** A *refusal* is not a
   demotion: Section 17.4 demotes a thesis whose size is too small, while a
   translation that declined for a stated reason has said something else. If
   both collapse to one status, the reason stops travelling — and the reason is
   what a human acts on.

3. **The default must be provably inert.** ``risk_budget_target`` defaults to
   ``None``, meaning the risk axis did not run. That is a *disclosure*, not a
   silent pass, and the wording is pinned because it is the whole difference
   between "unchecked" and "checked and clear".

Two measured facts this file rests on
-------------------------------------
**On the shipped configuration, ``scenario_sizing_permitted`` is False** — the
scenario probability leaves are ``uncalibrated_illustrative``, so Section 25
forbids Kelly sizing from them. **Every** live thesis therefore refuses at
``translate_thesis_to_position``'s gate 2, which is why the demotion is pinned on
a **constructed** thesis rather than through the builder. That is a fact about
the configuration, not a defect, and asserting it is what keeps these fixtures
from silently changing meaning if the config is calibrated later.

**Today's live data stands every family down at Q6/Q7/Q8**, so no thesis reaches
the risk axis at all on the real pipeline. ``scripts/live_risk_axis_check.py``
measures that; here it is only relevant because it means the builder's own tests
cannot reach the demotion either.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.models.probability import ScenarioOutcome
from macro_engine.portfolio.risk_budget import (
    SIGN_OFF_REQUIRED,
    ProposedPosition,
    RiskBudgetTarget,
    ThesisPositionInputs,
    translate_thesis_to_position,
)
from macro_engine.thesis_layer.builder import (
    SIZING_LOGIC_PHASE_1,
    build_us_macro_thesis,
)
from macro_engine.thesis_layer.schemas import MacroThesis, ThesisStatus

from .test_builder import build_live, first_diff, live_kwargs, reads, taylor

STAMP = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
SETTINGS = get_settings()

#: The instrument ``select_instrument`` routes a policy-path gap to, so a budget
#: line built for it passes ``ThesisPositionInputs``' instrument-match check.
LIVE_INSTRUMENT = "UST 2yr note futures"


def _live_thesis(**overrides: object) -> MacroThesis:
    """A thesis built through the real builder, reaching the live path."""
    return build_live(**overrides)


#: A distribution Kelly can actually consume: probabilities sum to 1, every
#: payoff is a **fraction of capital** (``KellyInputs`` refuses ``< -1`` outright,
#: so a bp figure is rejected before any arithmetic runs), and the edge is
#: asymmetric so the growth-optimal fraction lands strictly inside ``[0, 1]``.
#:
#: The asymmetry is not decoration. A *symmetric* positive-edge pair pins ``f*``
#: at the grid's upper edge and clips, which is the measurement D-072's live
#: check recorded — so a symmetric fixture here would silently exercise the
#: position-limit path while the test claims to exercise sizing.
_INTERIOR: tuple[tuple[float, float], ...] = ((0.45, 0.05), (0.55, -0.04))


def _sizable_thesis() -> MacroThesis:
    """A thesis satisfying **every** precondition the translation checks.

    Constructed rather than built, and the construction had to be corrected once:
    the first version copied the live thesis and flipped only
    ``scenario_distribution_status`` to ``"calibrated"``. That is exactly the
    mistake this project has now recorded in the unit-error family — the *label*
    was changed and the *payload* was not. The live distribution's payoffs are bp
    figures (``-126.0``), so gate 3's ``KellyInputs`` refused the value with
    "beyond a total loss", and the failure surfaced as a ``ValidationError`` from
    a test that looked like it was testing the risk axis.

    So the distribution is **rebuilt** in the unit Kelly can use, and every other
    field mirrors what ``build_live`` produces — same instrument, same non-empty
    distribution, and an invalidation text so the LTCM schema gate is met. The
    only differences from the live thesis are the two that make sizing reachable:
    the status, and a distribution denominated in the right unit.
    """
    built = _live_thesis()
    assert built.scenario_distribution, "the live fixture stopped carrying scenarios"
    return built.model_copy(
        update={
            "scenario_distribution_status": "calibrated",
            "scenario_distribution": [
                ScenarioOutcome(
                    name=f"branch{i}",
                    probability=probability,
                    payoff_estimate=payoff,
                    unit="fraction_of_capital",
                )
                for i, (probability, payoff) in enumerate(_INTERIOR)
            ],
            "trade_idea": built.trade_idea.model_copy(update={"instrument": LIVE_INSTRUMENT}),
        }
    )


def _translate(thesis: MacroThesis, share: float = 0.12) -> ProposedPosition:
    """Run the real translation and return the proposal, as the builder does."""
    result = translate_thesis_to_position(
        ThesisPositionInputs(
            thesis=thesis,
            risk_budget_target=RiskBudgetTarget(
                instrument=thesis.trade_idea.instrument,
                target_risk_contribution_pct=share,
            ),
        )
    )
    value = result.value
    assert isinstance(value, dict)
    return ProposedPosition.model_validate(value)


#: Two-branch sets whose optima land **strictly inside** the domain rather than
#: pinning at the search edge. Every one is measured, not derived: a binary set
#: with a positive edge has monotone expected log growth, so unless the payoffs
#: are asymmetric in a specific way the argmax sits at ``f* = 1.0`` and the
#: published number is the position cap. These are the sets that do not.
_INTERIOR_CASES: tuple[tuple[tuple[float, float], ...], ...] = (
    ((0.46, 0.02), (0.54, -0.017)),
    ((0.63, 0.01), (0.37, -0.017)),
    ((0.53, 0.016), (0.47, -0.018)),
    ((0.42, 0.018), (0.58, -0.013)),
    ((0.53, 0.008), (0.47, -0.009)),
    ((0.45, 0.05), (0.55, -0.04)),
)


def _smallest_reachable_fraction() -> float:
    """The smallest POSITIVE published fraction the sizing path can produce.

    Re-derived here rather than read from a literal, because the assertion it
    feeds is the one that decides whether Section 17.4 can fire at all — and a
    literal would keep saying "yes" after the configuration moved.

    Returns the minimum over the interior cases **through the real
    ``translate_thesis_to_position``**, so the number includes the fractional
    divisor and the position cap exactly as production applies them.
    """
    smallest = float("inf")
    for pairs in _INTERIOR_CASES:
        scenarios = [
            ScenarioOutcome(
                name=f"b{i}",
                probability=probability,
                payoff_estimate=payoff,
                unit="fraction_of_capital",
            )
            for i, (probability, payoff) in enumerate(pairs)
        ]
        proposal = _translate(
            _sizable_thesis().model_copy(update={"scenario_distribution": scenarios})
        )
        if proposal.fraction_of_capital > 0.0:
            smallest = min(smallest, proposal.fraction_of_capital)
    return smallest


# ---------------------------------------------------------------------------
# 1. The default is provably inert — and says so
# ---------------------------------------------------------------------------


def test_a_thesis_built_with_no_budget_is_draft_and_unaaffected() -> None:
    """The regression guard for the whole increment.

    ``risk_budget_target`` defaults to ``None``. If that default ever started
    changing a status or a sizing sentence, every thesis this system has produced
    would change meaning without a line of model code changing.
    """
    thesis = _live_thesis()
    assert thesis.status is ThesisStatus.DRAFT
    assert thesis.trade_idea.sizing_logic == SIZING_LOGIC_PHASE_1


def test_the_default_path_publishes_that_the_risk_axis_did_not_run() -> None:
    """A default is a disclosure, not a silence.

    Without this line, a ``DRAFT`` thesis that was never sized against a book is
    **indistinguishable** from one that was sized and cleared — the "unchecked
    read as checked" direction, which is why the sentence names Section 17.4 and
    points at the parameter rather than saying something generic about risk.
    """
    thesis = _live_thesis()
    risk_lines = [w for w in thesis.warnings if "[Q12 risk]" in w]
    assert len(risk_lines) == 1, f"expected one risk-axis line, got {risk_lines!r}"
    line = risk_lines[0]
    assert "DID NOT RUN" in line
    assert "Section 17.4" in line
    assert "risk_budget_target" in line


def test_the_shipped_configuration_cannot_countenance_sizing() -> None:
    """The measurement the module docstring rests on, asserted not assumed.

    If the scenario probabilities are ever calibrated, the live path starts
    reaching the sizing gates and these fixtures change meaning. Pinning it means
    that shows up as a failure with an explanation, not as quiet drift.
    """
    thesis = _live_thesis()
    assert thesis.scenario_sizing_permitted is False, (
        "the shipped scenario probabilities became calibrated. The risk axis is "
        "now reachable through the builder on live data, which changes what the "
        "constructed fixtures in this file prove. Re-derive them."
    )
    assert thesis.scenario_distribution_status == "SCENARIO_DISTRIBUTION_UNAVAILABLE"


# ---------------------------------------------------------------------------
# 2. A supplied budget on an uncalibrated thesis REFUSES — and that is not a demotion
# ---------------------------------------------------------------------------


def test_supplying_a_budget_to_an_uncalibrated_thesis_refuses_without_demoting() -> None:
    """The reachable path, end to end through the real builder.

    The assertion that matters is the **negative** one: the status stays
    ``DRAFT``. A refusal is not a demotion — Section 17.4 demotes a thesis whose
    size is too small, and this thesis was never sized at all. Collapsing the two
    would report a sizing-prohibition finding as a risk-budget finding.
    """
    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=0.4, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        risk_budget_target=RiskBudgetTarget(
            instrument=LIVE_INSTRUMENT, target_risk_contribution_pct=0.12
        ),
        **live_kwargs(),  # type: ignore[arg-type]
    )
    assert thesis.status is ThesisStatus.DRAFT
    risk_lines = [w for w in thesis.warnings if "[Q12 risk]" in w]
    assert len(risk_lines) == 1
    line = risk_lines[0]
    assert "refused_scenarios_uncalibrated" in line
    assert "REFUSAL, not a demotion" in line


def test_the_builder_hands_the_translation_the_budget_type_it_already_takes() -> None:
    """No adapter, no second budget shape.

    The builder takes ``RiskBudgetTarget`` — the type
    ``translate_thesis_to_position`` already consumes — rather than a float or a
    bespoke record. A second shape would need a conversion, and a conversion is
    where a unit error lives (D-054's 100x, D-072's 6.7x).
    """
    thesis = build_us_macro_thesis(
        reads(growth=1.2, inflation=0.4, labor=0.8),
        taylor(output_gap=1.2),
        first_diff(output_gap_change=0.05),
        risk_budget_target=RiskBudgetTarget(
            instrument=LIVE_INSTRUMENT, target_risk_contribution_pct=0.12
        ),
        **live_kwargs(),  # type: ignore[arg-type]
    )
    assert isinstance(thesis, MacroThesis)
    assert thesis.trade_idea.instrument == LIVE_INSTRUMENT


def test_a_budget_for_a_different_instrument_is_refused_by_the_input_model() -> None:
    """The caller-error path, owned by the translation rather than the builder.

    A risk-budget line names the instrument whose risk it allocates. Sizing one
    instrument against another's allocation would publish a proposal that
    *claims* a portfolio check it never performed, with no output field showing
    the mismatch — so ``ThesisPositionInputs`` raises rather than warning.
    """
    with pytest.raises(ValidationError, match="risk_budget_target names"):
        ThesisPositionInputs(
            thesis=_sizable_thesis(),
            risk_budget_target=RiskBudgetTarget(
                instrument="TLT", target_risk_contribution_pct=0.12
            ),
        )


# ---------------------------------------------------------------------------
# 3. The two structural bounds on Section 17.4's only free number
# ---------------------------------------------------------------------------


def test_the_demotion_bound_is_below_the_position_cap_and_above_zero() -> None:
    """The value is bounded by the rule's *structure*, and the bounds differ in kind.

    * **At or above the position cap** would demote every thesis that reached the
      sizing path — not a risk judgement but a broken rule, and it would look
      like a policy because ``WATCH`` is a legal status.
    * **At or below zero** could never fire, making Section 17.4 a declaration
      with no consumer.

    Asserted against the *other config leaves* rather than literals, so a future
    change to the cap moves the constraint with it.
    """
    demotion = SETTINGS.risk.thesis_demotion_fraction
    cap = SETTINGS.risk.max_position_fraction
    assert demotion > 0.0, "a zero threshold can never fire (O-53's class)"
    assert demotion < cap, (
        f"the demotion bound ({demotion}) must sit strictly below the position "
        f"cap ({cap}); at or above it, EVERY thesis that reaches sizing demotes "
        f"and the rule stops discriminating"
    )


def test_the_demotion_bound_sits_above_the_smallest_reachable_size() -> None:
    """The third bound — the one a first draft satisfied while never firing.

    Positive and below the cap are **not sufficient**. The published fraction is
    not continuous: full Kelly pins at the domain edge for any binary set with a
    positive edge, so the reachable published sizes are a short list, and a bound
    beneath its minimum can never demote no matter how much the rule is read.

    This is the assertion that would have caught the ``0.02`` draft. It is
    checked against the **measured smallest reachable size**, which this test
    re-derives through the real translation rather than trusting a literal.
    """
    bound = SETTINGS.risk.thesis_demotion_fraction
    smallest = _smallest_reachable_fraction()
    assert smallest > 0.0, (
        "the sweep found no positive sized proposal at all — the sizing path has "
        "stopped producing sizes, which is a different problem from this check"
    )
    assert bound >= smallest, (
        f"the demotion bound ({bound}) sits BELOW the smallest size the sizing "
        f"path can produce ({smallest}), so Section 17.4 can never fire on this "
        f"configuration — the O-53 declared-unreachable class. The bound must sit "
        f"inside [{smallest}, {SETTINGS.risk.max_position_fraction}) to "
        f"discriminate."
    )


def test_the_bound_the_axis_actually_uses_splits_the_reachable_set() -> None:
    """The bound must be read from config **inside the axis**, and discriminate.

    The two tests above read the config leaf directly, which is exactly the
    blind spot a mutation sweep found: replacing the axis's *local* assignment
    with ``0.0`` or ``1.0`` leaves the leaf untouched, so an assertion that only
    reads the leaf cannot see it. Measured — ``M1.2`` survived the first run of
    ``scripts/mutation_risk_axis.py`` for precisely this reason.

    So this test drives ``_apply_risk_axis`` over the reachable range and asserts
    it produces **both** outcomes. A bound that demotes everything and a bound
    that demotes nothing are each a broken rule, and neither is visible from the
    config tree.
    """
    from macro_engine.thesis_layer.builder import _apply_risk_axis

    def outcome_for(pairs: tuple[tuple[float, float], ...]) -> ThesisStatus:
        scenarios = [
            ScenarioOutcome(
                name=f"b{i}",
                probability=probability,
                payoff_estimate=payoff,
                unit="fraction_of_capital",
            )
            for i, (probability, payoff) in enumerate(pairs)
        ]
        thesis = _sizable_thesis().model_copy(update={"scenario_distribution": scenarios})
        return _apply_risk_axis(
            thesis,
            RiskBudgetTarget(
                instrument=thesis.trade_idea.instrument,
                target_risk_contribution_pct=0.12,
            ),
        ).status

    statuses = {outcome_for(pairs) for pairs in _INTERIOR_CASES}
    assert ThesisStatus.WATCH in statuses, (
        "the axis demoted NOTHING across the reachable range. Either the bound "
        "sits below every reachable size (Section 17.4 can never fire) or the "
        "axis is not reading the configured bound at all."
    )
    assert ThesisStatus.DRAFT in statuses, (
        "the axis demoted EVERY reachable size, so the bound is at or above the "
        "position cap and the rule no longer discriminates — every thesis that "
        "survives sizing would stand down regardless of conviction."
    )


def test_the_demotion_fires_at_the_boundary_not_only_below_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 17.4 says "at or below" — the boundary itself must demote.

    A strict ``<`` demotes the same sizes as ``<=`` for every input that is not
    *exactly* on the bound, so the difference is invisible unless a test lands a
    size precisely there. Measured: ``M4.1`` (``<=`` rewritten to ``<``) survived
    the first run of ``scripts/mutation_risk_axis.py`` for exactly that reason.

    The size is pinned by measurement rather than searched for: the reachable
    published fraction ``0.02941`` is known, so the bound's accessor is
    patched to return exactly that and the axis must still demote. A ``<``
    comparison would leave this thesis ``DRAFT``.
    """
    from macro_engine.thesis_layer import builder as builder_module

    pairs = ((0.63, 0.01), (0.37, -0.017))  # measured published fraction: 0.02941
    scenarios = [
        ScenarioOutcome(
            name=f"b{i}",
            probability=probability,
            payoff_estimate=payoff,
            unit="fraction_of_capital",
        )
        for i, (probability, payoff) in enumerate(pairs)
    ]
    thesis = _sizable_thesis().model_copy(update={"scenario_distribution": scenarios})
    size = _translate(thesis).fraction_of_capital
    assert size > 0.0, "the boundary fixture stopped producing a positive size"

    # The accessor is the single read the axis performs, so patching the leaf it
    # reads is the smallest change that moves the comparison onto the boundary.
    # The leaf is patched rather than the property because the property is
    # read-only by design — the value is config-owned.
    settings = SETTINGS.risk
    monkeypatch.setattr(
        settings,
        "thesis_demotion_fraction_value",
        settings.thesis_demotion_fraction_value.model_copy(update={"value": size}),
    )
    assert settings.thesis_demotion_fraction == size, (
        "the leaf patch did not move the accessor; the boundary was not tested"
    )
    monkeypatch.setattr(
        builder_module,
        "get_settings",
        lambda: type("_S", (), {"risk": settings})(),
    )

    result = builder_module._apply_risk_axis(
        thesis,
        RiskBudgetTarget(
            instrument=thesis.trade_idea.instrument,
            target_risk_contribution_pct=0.12,
        ),
    )
    assert result.status is ThesisStatus.WATCH, (
        f"a thesis sized at exactly the bound ({size}) was not demoted. Section "
        f"17.4 says 'at or below', so the comparison must be inclusive — a strict "
        f"'<' leaves the boundary case undemoted and the rule silently narrower "
        f"than the specification."
    )


def test_the_demotion_bound_is_a_fraction_not_a_percent() -> None:
    """The unit trap that has cost this project four increments (D-054/055/057).

    The value is a fraction. Read as a percent it would be 0.03% of capital, below
    which no position would ever be — a silent no-op. The magnitude resolves it,
    and the magnitude is asserted rather than argued.
    """
    demotion = SETTINGS.risk.thesis_demotion_fraction
    assert 0.0 < demotion < 0.10, (
        f"{demotion} is outside the range a *fraction* of capital could occupy; a "
        f"value in the tens would be a percent wearing the fraction's name"
    )


# ---------------------------------------------------------------------------
# 4. Refusal and demotion are different findings — the distinction, as a pair
# ---------------------------------------------------------------------------


def test_a_refusal_and_a_sized_proposal_are_different_in_kind() -> None:
    """Both start from a live ``DRAFT`` with a budget; they must not converge.

    The refusal has ``fraction_of_capital == 0.0`` and an outcome beginning
    ``refused_``; the sized proposal has a positive fraction and a reason that
    says what *produced* the number. If these ever became one shape, a reader
    could not tell "we declined to size this" from "we sized it" — two findings
    calling for different actions.
    """
    refusing = _live_thesis()
    refused = _translate(refusing, share=0.12)
    assert refused.outcome.startswith("refused_")
    assert refused.fraction_of_capital == 0.0

    sized = _translate(_sizable_thesis(), share=0.12)
    assert not sized.outcome.startswith("refused_")
    assert sized.fraction_of_capital > 0.0
    assert refused.reason != sized.reason


def test_the_sized_proposal_never_exceeds_the_position_cap() -> None:
    """The LTCM hard-limit assertion, on the input the builder hands the axis.

    ``RiskLimits.max_position_pct_of_portfolio`` must override any sizing
    arithmetic regardless of conviction — Section 15 Module 1's rule and
    Section 20.14's mandated golden test.
    """
    proposal = _translate(_sizable_thesis(), share=0.12)
    cap = SETTINGS.risk.max_position_fraction
    assert proposal.notional_fraction_after_constraints <= cap + 1e-12
    assert proposal.fraction_of_capital <= cap + 1e-12


def test_every_result_carries_the_sign_off_contract() -> None:
    """Section 9.3's gate, on the object the builder's axis reads.

    A risk axis that produced a size without the sign-off contract would turn a
    reasoning layer into a signal generator — Section 1.1's whole distinction.
    """
    thesis = _sizable_thesis()
    result = translate_thesis_to_position(
        ThesisPositionInputs(
            thesis=thesis,
            risk_budget_target=RiskBudgetTarget(
                instrument=thesis.trade_idea.instrument,
                target_risk_contribution_pct=0.12,
            ),
        )
    )
    assert SIGN_OFF_REQUIRED in result.warnings


# ---------------------------------------------------------------------------
# 5. The demotion fires — and the shipped builder cannot reach it, which is why
#    the fixture above is constructed
# ---------------------------------------------------------------------------


def test_no_shipped_input_reaches_the_demotion_so_the_fixture_is_constructed() -> None:
    """The honest statement of a limitation, written as an executable claim.

    Every live thesis refuses before a size exists (Section 25), and every
    stand-down never reaches the axis. So **no input to the shipped builder
    produces a demotion**, and a reader who assumed the tests above run "the real
    path" would be wrong in a way that makes them look stronger than they are.

    This test fails if that ever stops being true — which is the signal to
    re-derive the constructed fixtures rather than keep them.
    """
    for thesis_type in ThesisType:
        thesis = _live_thesis(thesis_type=thesis_type)
        # A stand-down (WATCH) never reaches the risk axis, and a live thesis
        # (DRAFT) reaches it and refuses. Neither can demote.
        assert thesis.status in {ThesisStatus.DRAFT, ThesisStatus.WATCH}
        if thesis.status is ThesisStatus.DRAFT:
            risk_lines = [w for w in thesis.warnings if "[Q12 risk]" in w]
            assert len(risk_lines) == 1
            assert "DID NOT RUN" in risk_lines[0] or "refused" in risk_lines[0], (
                "a live thesis reached the risk axis and neither declined nor "
                "refused — the demotion may have become reachable through the "
                "builder, in which case this file's constructed fixture should be "
                "replaced by a built one"
            )


def test_a_demoted_thesis_moves_to_watch_and_says_why() -> None:
    """Section 17.4's rule itself, fired through the real translation.

    The input is the **smallest sized proposal the configuration can produce**,
    which is the case the bound exists to catch — a thesis that survives every
    gate and still comes out too small to carry its own decision. The assertion
    is on both halves of the finding: the status moves, and the warning names the
    bound, the size and the binding constraint. A status that moved without a
    stated cause is the failure direction O-86 names one layer up, where ``WATCH``
    cannot distinguish "no edge" from "waiting".

    The first draft of this test skipped unless the shipped config happened to
    produce a small size, and it always skipped — a permanently-skipped test is
    the declared-unreachable class wearing a green tick. It now pins the size it
    needs and asserts the rule fires on it.
    """
    from macro_engine.thesis_layer.builder import _apply_risk_axis

    bound = SETTINGS.risk.thesis_demotion_fraction
    smallest = _smallest_reachable_fraction()
    assert 0.0 < smallest <= bound, (
        f"the smallest reachable size ({smallest}) is not at or below the bound "
        f"({bound}), so this test cannot demonstrate the rule. That is the "
        f"condition `test_the_demotion_bound_sits_above_the_smallest_reachable_"
        f"size` reports on; fixing the bound there is what makes this pass."
    )

    thesis = _sizable_thesis().model_copy(
        update={
            "scenario_distribution": [
                ScenarioOutcome(
                    name=f"b{i}",
                    probability=probability,
                    payoff_estimate=payoff,
                    unit="fraction_of_capital",
                )
                for i, (probability, payoff) in enumerate(_INTERIOR_CASES[0])
            ]
        }
    )
    result = _apply_risk_axis(
        thesis,
        RiskBudgetTarget(
            instrument=thesis.trade_idea.instrument,
            target_risk_contribution_pct=0.12,
        ),
    )
    assert result.status is ThesisStatus.WATCH
    demotion_lines = [w for w in result.warnings if "DEMOTED" in w]
    assert len(demotion_lines) == 1
    line = demotion_lines[0]
    assert "Section 17.4" in line
    assert "binding constraint" in line


def test_the_risk_axis_leaves_the_thesis_untouched_when_no_budget_is_supplied() -> None:
    """Every field except ``warnings`` must be identical — provenance included.

    ``model_copy`` is used rather than a rebuild, so the id, the stamp and the
    nested trade idea survive. A rebuild would mint a new ``thesis_id`` and make
    the risk axis look like a second thesis.
    """
    from macro_engine.thesis_layer.builder import _apply_risk_axis

    thesis = _live_thesis()
    result = _apply_risk_axis(thesis, None)
    assert result.thesis_id == thesis.thesis_id
    assert result.as_of == thesis.as_of
    assert result.status is thesis.status
    assert result.trade_idea == thesis.trade_idea
    assert len(result.warnings) == len(thesis.warnings) + 1
    assert result.warnings[:-1] == thesis.warnings
