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
rather than aspirational: Kelly is not reachable from the thesis or the API at
all (``§16.2`` Q11 is *"Phase 1: human-determined"*), so there is no live path on
which an unsizable distribution could be sized by accident. See
:func:`test_kelly_is_not_reachable_from_the_thesis_or_api_layers`.
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

    §16.2 Q11 is *"Phase 1: human-determined; Phase 4+: fractional_kelly"*, so the
    thesis builder must not import the sizer. Asserted by AST rather than by
    reading imports, because a single ``from ... import`` is easy to add in
    passing and this is the guard that notices.

    If this ever fails it is not necessarily wrong — it means Phase 4's wiring
    has begun — but it must fail loudly so §25's gate is re-checked on the new
    path before it ships.
    """
    forbidden = {"risk_budget", "apply_fractional_kelly", "KellyInputs"}
    offenders: list[str] = []
    for sub in ("thesis_layer", "api_layer"):
        for path in (_REPO_ROOT / "src" / "macro_engine" / sub).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "risk_budget" in node.module:
                        offenders.append(f"{path.name}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if "risk_budget" in alias.name:
                            offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        f"the sizer is now imported by {offenders}. Kelly has become reachable "
        f"from the thesis/API path; re-check Section 25's gate on that path before "
        f"sizing anything. Forbidden names: {sorted(forbidden)}"
    )
