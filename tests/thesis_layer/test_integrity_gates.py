"""Section 25/26/27 of the economic-integrity directive — the sizing gates.

The directive is blunt about this area, and each clause is pinned by a test:

**§25 — scenario probabilities must be REAL.**
*"Scenario probabilities must be real; if they cannot be justified, return
``SCENARIO_DISTRIBUTION_UNAVAILABLE`` and MUST NOT calculate Kelly position
sizing."* Measured today: every probability leaf is ``uncalibrated_illustrative``
(§16.4's literals), so every live thesis is ``SCENARIO_DISTRIBUTION_UNAVAILABLE``
and ``scenario_sizing_permitted`` is False. Pinned by
:class:`TestScenarioDistributionUnavailable`.

**§26 — payoffs must be normalized portfolio-return FRACTIONS.**
*"Payoffs must be normalized portfolio return fractions; never pass
``bp_pnl_proxy`` into a production sizer."* The producer publishes
``bp_pnl_proxy``; the sizer accepts only ``fraction_of_capital`` and raises
otherwise. Pinned by :class:`TestPayoffUnitDiscipline`.

**§27 — Kelly must BLOCK on invalid inputs.**
*"Kelly must block (``KELLY_BLOCKED``) on invalid inputs."* Pinned by
:class:`TestKellyBlocks`.

The file also records the **structural** fact that makes §25/§27 achievable
rather than aspirational: the Kelly *primitives* are not reachable from the
thesis or the API layer, so there is no live path on which an unsizable
distribution could be sized by accident. See
:func:`test_kelly_is_not_reachable_from_the_thesis_or_api_layers`.

**D-073 amended that second statement, and the amendment narrows it rather than
removing it.** Through Phase 3 the guard forbade *any* import from
``risk_budget`` into these layers — a proxy for §25 that was correct only while
the risk layer did not exist. Section 17.4 now mandates the edge, so the guard
forbids the primitives and enumerates the one permitted surface
(``translate_thesis_to_position`` and the types it consumes). The receipt that
§25 still holds on the new path is behavioural and lives beside it:
:func:`test_section_25_gate_precedes_kelly_on_the_translation_path`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from macro_engine.models.probability import ScenarioOutcome
from macro_engine.portfolio.risk_budget import KellyInputs, RiskLimits, apply_fractional_kelly
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    MarketPricingGap,
    TradeIdea,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _gap() -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=4.94,
        market_implied_value=4.67,
        raw_gap=0.27,
        unit="%",
        interpretation="model above market",
        is_meaningful=True,
        dispersion=1.00,
    )


def _distribution() -> list[ScenarioOutcome]:
    """A well-formed ``bp_pnl_proxy`` distribution, summing to 1."""
    return [
        ScenarioOutcome(
            name="base_case_gap_closes_as_modeled",
            probability=0.55,
            payoff_estimate=27.0,
            unit="bp_pnl_proxy",
        ),
        ScenarioOutcome(
            name="gap_partially_closes",
            probability=0.225,
            payoff_estimate=10.8,
            unit="bp_pnl_proxy",
        ),
        ScenarioOutcome(
            name="thesis_invalidated_reversal",
            probability=0.175,
            payoff_estimate=-16.2,
            unit="bp_pnl_proxy",
        ),
        ScenarioOutcome(
            name="tail_adverse_surprise",
            probability=0.05,
            payoff_estimate=-54.0,
            unit="bp_pnl_proxy",
        ),
    ]


def _as_fractions() -> list[ScenarioOutcome]:
    """The same branches, denominated in FRACTIONS of capital (§26's production form).

    ``27bp`` becomes ``0.0027``, which is what ``apply_fractional_kelly``
    requires and what ``bp_pnl_proxy`` deliberately is not.
    """
    return [
        s.model_copy(update={"payoff_estimate": s.payoff_estimate / 10_000.0})
        for s in _distribution()
    ]


def _thesis(**overrides: object) -> MacroThesis:
    params: dict[str, object] = {
        "thesis_id": "us-test-0001",
        "regime": {"state": "late_expansion"},
        "growth_view": {"output_gap": 0.83},
        "inflation_view": {"breadth_score": 0.5},
        "policy_view": {"model_implied": 4.94},
        "market_pricing_gap": _gap(),
        "convergence_classification": ConvergenceClassification.HIGH,
        "trade_idea": TradeIdea(
            instrument="Duration-weighted 2y/10y UST steepener",
            direction="long",
            timeframe="6-12 months",
            stop_or_invalidation="gap closes below dispersion",
        ),
        "scenario_distribution": _distribution(),
        "scenario_distribution_status": "SCENARIO_DISTRIBUTION_UNAVAILABLE",
    }
    params.update(overrides)
    return MacroThesis(**params)  # type: ignore[arg-type]


class TestScenarioDistributionUnavailable:
    """§25 — an illustrative distribution is published but is NOT sizing-grade."""

    def test_a_live_thesis_from_illustrative_probabilities_is_unavailable(self) -> None:
        """The status is stamped from config, and today config says illustrative."""
        thesis = _thesis()

        assert thesis.scenario_distribution_status == "SCENARIO_DISTRIBUTION_UNAVAILABLE"
        assert thesis.scenario_sizing_permitted is False

    def test_only_a_calibrated_status_permits_sizing(self) -> None:
        """The falsifiable half — a hardcoded False would fail this."""
        calibrated = _thesis(scenario_distribution_status="calibrated")
        assert calibrated.scenario_sizing_permitted is True

        unavailable = _thesis(scenario_distribution_status="SCENARIO_DISTRIBUTION_UNAVAILABLE")
        assert unavailable.scenario_sizing_permitted is False

        empty = _thesis(scenario_distribution=[], scenario_distribution_status="empty_no_trade")
        assert empty.scenario_sizing_permitted is False

    def test_the_default_status_is_the_unsafe_one_refused(self) -> None:
        """A thesis built without stating provenance must NOT be silently sized.

        The field defaults to ``empty_no_trade``, so an object that never
        declares its distribution's provenance reads as "nothing to size", never
        as "sizing permitted". This is the fail-closed direction.
        """
        thesis = MacroThesis(
            thesis_id="us-test-0002",
            regime={"state": "late_expansion"},
            growth_view={"output_gap": 0.83},
            inflation_view={"breadth_score": 0.5},
            policy_view={"model_implied": 4.94},
            market_pricing_gap=_gap(),
            convergence_classification=ConvergenceClassification.HIGH,
            trade_idea=TradeIdea(
                instrument="UST 10y",
                direction="long",
                stop_or_invalidation="x",
            ),
            # scenario_distribution and its status both left at their defaults
        )
        assert thesis.scenario_distribution_status == "empty_no_trade"
        assert thesis.scenario_sizing_permitted is False

    def test_a_status_that_disagrees_with_the_distribution_is_refused(self) -> None:
        """Both disagreement directions raise — the status is load-bearing."""
        # A non-empty distribution declared empty would hide it from a reader.
        with pytest.raises(ValidationError, match="empty_no_trade"):
            _thesis(scenario_distribution_status="empty_no_trade")

        # An empty distribution declared calibrated would claim one that is absent.
        with pytest.raises(ValidationError, match="is empty"):
            _thesis(scenario_distribution=[], scenario_distribution_status="calibrated")


class TestPayoffUnitDiscipline:
    """§26 — ``bp_pnl_proxy`` must never reach a production sizer."""

    def test_the_producer_publishes_bp_pnl_proxy(self) -> None:
        """The scenario producer's unit is a proxy, and says so."""
        distribution = _distribution()
        assert {s.unit for s in distribution} == {"bp_pnl_proxy"}

    def test_the_sizer_refuses_a_bp_distribution(self) -> None:
        """Passing the producer's own output straight to the sizer raises.

        This is §26's whole content: the two units are not interchangeable, and
        the sizer refuses rather than converting, because a bp payload scaled
        into a fraction is a silent 100x-class error.
        """
        with pytest.raises(ValidationError):
            KellyInputs(
                scenarios=_distribution(),
                payoff_unit="bp_pnl_proxy",
                limits=RiskLimits.from_settings(),
            )

    def test_the_sizer_accepts_only_fraction_of_capital(self) -> None:
        """A fraction-denominated set is accepted; that is the production form."""
        inputs = KellyInputs(
            scenarios=_as_fractions(),
            payoff_unit="fraction_of_capital",
            limits=RiskLimits.from_settings(),
        )
        assert inputs.payoff_unit == "fraction_of_capital"


class TestKellyBlocks:
    """§27 — Kelly must block on invalid inputs."""

    def test_a_fraction_denominated_set_sizes(self) -> None:
        """The happy path, so the block tests below are not vacuous."""
        result = apply_fractional_kelly(
            KellyInputs(
                scenarios=_as_fractions(),
                payoff_unit="fraction_of_capital",
                limits=RiskLimits.from_settings(),
            )
        )
        assert result.model_name == "apply_fractional_kelly"
        assert isinstance(result.value, dict)
        assert result.value["fraction_of_capital"] > 0.0

    def test_an_empty_scenario_set_cannot_reach_the_sizer(self) -> None:
        """An empty set is refused at the input boundary, not silently sized."""
        with pytest.raises(ValidationError):
            KellyInputs(
                scenarios=[],
                payoff_unit="fraction_of_capital",
                limits=RiskLimits.from_settings(),
            )

    def test_a_bp_set_cannot_reach_the_sizer(self) -> None:
        """§26 and §27 together: the wrong unit is a blocked input."""
        with pytest.raises(ValidationError):
            KellyInputs(
                scenarios=_distribution(),
                payoff_unit="bp_pnl_proxy",
                limits=RiskLimits.from_settings(),
            )


def test_kelly_is_not_reachable_from_the_thesis_or_api_layers() -> None:
    """The structural fact that makes §25/§27 hold on every live path.

    §16.2 Q11 is *"Phase 1: human-determined; Phase 4+: fractional_kelly"*. The
    guard asserted, through Phase 3, that the thesis builder imported nothing
    from ``risk_budget`` at all — because in Phase 3 the risk layer did not
    exist and any import would have built a Phase 4 layer early.

    **D-073 is the Phase 4 wiring this docstring anticipated, and the guard is
    amended rather than deleted — narrowed to the property that actually
    protects §25.** The original assertion ("no import at all") was a proxy for
    the real requirement, and the proxy stopped being the right test the moment
    Section 17.4 mandated the edge. The real requirement is:

        **the Kelly *primitives* must not be reachable from the thesis or API
        layers, and the one import that IS permitted must arrive with §25's gate
        already checked on its path.**

    So the guard now does three things, and the third is new — it is a stronger
    test than the one it replaces, not a weaker one:

    1. **``apply_fractional_kelly`` / ``KellyInputs`` stay forbidden** anywhere
       under ``thesis_layer/`` and ``api_layer/``. A builder that called the
       Kelly primitive directly would bypass every gate in
       ``translate_thesis_to_position`` — including §25's — and this is the
       assertion that notices.
    2. **An ``import *`` from ``risk_budget`` stays forbidden**, because it
       would satisfy (1) textually while making every primitive reachable.
    3. **The permitted names are enumerated**, and the import must be exactly
       that set: the translation entry point and the types it consumes. A future
       addition to the builder's import list fails here and must be justified.

    §25's gate on the new path was re-checked when this amendment was made, and
    the result is asserted below rather than asserted-in-prose: the builder's
    only call into ``risk_budget`` is ``translate_thesis_to_position``, whose
    **gate 2 refuses an uncalibrated distribution before Kelly is reached**
    (measured: ``refused_scenarios_uncalibrated`` on the live fixture, whose
    shipped probabilities are ``uncalibrated_illustrative``).
    """
    #: The Kelly primitives. Reachable from ``portfolio/``, never from here.
    forbidden_names = {"apply_fractional_kelly", "KellyInputs"}
    #: The permitted surface: the translation entry point and the types it
    #: consumes. Exactly this set — an addition is a decision, not a detail.
    permitted_names = {
        "translate_thesis_to_position",
        "ThesisPositionInputs",
        "RiskBudgetTarget",
        "ProposedPosition",
    }

    offenders: list[str] = []
    permitted_uses: list[str] = []
    wildcard_imports: list[str] = []

    for sub in ("thesis_layer", "api_layer"):
        for path in (_REPO_ROOT / "src" / "macro_engine" / sub).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if not (node.module and "risk_budget" in node.module):
                        continue
                    if node.names and node.names[0].name == "*":
                        wildcard_imports.append(f"{path.name}:{node.lineno}")
                        continue
                    for alias in node.names:
                        name = alias.name
                        if name in forbidden_names:
                            offenders.append(f"{path.name}:{node.lineno} ({name})")
                        elif name in permitted_names:
                            permitted_uses.append(f"{path.name}:{node.lineno} ({name})")
                        else:
                            offenders.append(f"{path.name}:{node.lineno} ({name} UNKNOWN)")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if "risk_budget" in alias.name:
                            # A bare `import macro_engine.portfolio.risk_budget`
                            # makes the whole module reachable by attribute.
                            offenders.append(f"{path.name}:{node.lineno} (module import)")

    assert not wildcard_imports, (
        f"a wildcard import from the sizer appears at {wildcard_imports}. It would "
        f"satisfy a name-based check while making {sorted(forbidden_names)} "
        f"reachable — the check must see the names, not a star."
    )
    assert not offenders, (
        f"a Kelly primitive or an unlisted name is reachable from the thesis/API "
        f"path at {offenders}. Section 25's gate lives inside the translation; a "
        f"direct call reaches Kelly without it. Permitted names are exactly "
        f"{sorted(permitted_names)} (D-073)."
    )
    # The positive half: the permitted edge must actually be used, and only by
    # the builder. Without this, deleting the feature would also make the guard
    # pass — a guard that a removal satisfies is not guarding the thing.
    assert permitted_uses, (
        "no permitted risk-budget import was found. Section 17.4's hook is the "
        "reason this guard was amended; removing the import without removing the "
        "guard would leave the amendment unexplained."
    )
    assert all(entry.startswith("builder.py") for entry in permitted_uses), (
        f"the risk-budget import appears outside the builder: {permitted_uses}. "
        f"§17.4 wires the risk axis at the seam, and nowhere else."
    )


def test_section_25_gate_precedes_kelly_on_the_translation_path() -> None:
    """The receipt for the guard above: §25 is checked BEFORE Kelly is reached.

    The amendment in D-073 permits the builder to import the translation, so the
    question the guard cannot answer structurally — *does the new path still
    honour §25?* — is answered here **behaviourally**, on the live fixture.

    The fixture's distribution is ``uncalibrated_illustrative``, so Section 25
    forbids sizing from it. If the translation reached Kelly anyway, the refusal
    would carry a different outcome; the assertion is therefore on the **reason**
    as well as the outcome, because a refusal for the wrong cause is
    indistinguishable from a refusal for the right one (lesson 5bn).
    """
    from macro_engine.portfolio.risk_budget import (
        ProposedPosition,
        RiskBudgetTarget,
        ThesisPositionInputs,
        translate_thesis_to_position,
    )

    thesis = _thesis()
    assert thesis.scenario_sizing_permitted is False, (
        "the fixture began permitting sizing; this test's premise is gone and the "
        "§25 receipt must be re-derived"
    )
    result = translate_thesis_to_position(
        ThesisPositionInputs(
            thesis=thesis,
            risk_budget_target=RiskBudgetTarget(
                instrument=thesis.trade_idea.instrument,
                target_risk_contribution_pct=0.12,
            ),
        )
    )
    value = result.value
    assert isinstance(value, dict)
    proposal = ProposedPosition.model_validate(value)
    assert proposal.outcome == "refused_scenarios_uncalibrated"
    assert proposal.fraction_of_capital == 0.0
    assert "Section 25" in proposal.reason
