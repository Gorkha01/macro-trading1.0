"""Tests for the Module 15-16 crisis-scenario shock engine (Section 13.2).

Every assertion is a BEHAVIOUR — a published value, a refusal, a reconciliation —
never the presence of a line of source.

The units are the reason this file is thorough: three unit systems meet in the
engine (bp, percent, and "P&L percent per unit"), and two of the three would be
wrong by a factor of 100 if confused while every number still looked plausible.
"""

from __future__ import annotations

from typing import cast

import pytest

from macro_engine.config import get_settings
from macro_engine.extensions.scenario_engine import (
    FactorExposures,
    Scenario,
    ScenarioShock,
    SimulationInputs,
    _check_additivity,
    apply_scenario_shock,
    list_scenarios,
    load_scenario,
    simulate_scenario_stress,
)
from macro_engine.models.contracts import ModelResult

#: A book with one leg per configured factor. `rates = -0.04` means a 1bp FALL
#: in yields gains 0.04% of the portfolio (a modified duration of ~4 years).
_EXPOSURES = FactorExposures(
    pnl_pct_per_unit={"rates": -0.04, "credit": -0.006, "equity": 0.07, "fx": -0.10}
)


# ---------------------------------------------------------------------------
# The factor set — the prerequisite, and its order
# ---------------------------------------------------------------------------
def test_the_factor_set_is_the_specs_own_four_in_the_specs_own_order() -> None:
    """Section 17.2: *"rates, FX, credit, equity"* — and the ORDER is load-bearing.

    The exposure representation is positional, so index i of the factor set IS
    index i of every exposure vector. Reordering the config silently relabels
    every exposure, which is why the order is asserted rather than the set.
    """
    assert get_settings().scenario_engine.factor_names == ("rates", "fx", "credit", "equity")


def test_an_unknown_factor_is_refused_not_ignored() -> None:
    """A shock for a factor the book does not carry would be silently dropped."""
    with pytest.raises(ValueError, match=r"not a configured risk factor|unknown factor"):
        Scenario(
            name="x",
            shocks={
                "rates": ScenarioShock(unit="bp", value=-100),
                "vix": ScenarioShock(unit="pct", value=-50),
            },
        )


def test_exposures_must_cover_every_configured_factor() -> None:
    """A missing factor is an unanswered question, not a zero exposure."""
    with pytest.raises(ValueError, match=r"omit configured factor"):
        FactorExposures(pnl_pct_per_unit={"rates": -0.04})


def test_a_non_finite_exposure_is_refused() -> None:
    """A `nan` sensitivity would publish a `nan` P&L."""
    with pytest.raises(ValueError, match=r"non-finite"):
        FactorExposures(
            pnl_pct_per_unit={"rates": float("nan"), "credit": 0.0, "equity": 0.0, "fx": 0.0}
        )


# ---------------------------------------------------------------------------
# The units chain — hand-derived, and each step asserted
# ---------------------------------------------------------------------------
def test_a_basis_point_shock_is_applied_as_basis_points() -> None:
    """`rates = -0.04` per bp against a -300bp shock must give +12.0%.

    This is the step that would be wrong by 100 if the shock were treated as a
    yield (-300) instead of basis points, or the exposure as per-percent.
    """
    out = apply_scenario_shock(_EXPOSURES, load_scenario("gfc_2008"))
    assert "rates': 12.0" in out.context
    assert cast("float", out.value) == pytest.approx(5.35)


def test_the_published_value_equals_the_sum_of_its_own_breakdown() -> None:
    """Section 13.2's `factor_exposure_breakdown` must reconcile with the total.

    A breakdown whose parts do not sum to its whole is the same defect as a risk
    budget whose contributions do not: a reader cannot tell which leg is wrong.
    """
    out = apply_scenario_shock(_EXPOSURES, load_scenario("gfc_2008"))
    published = eval(out.context.split("factor_exposure_breakdown=")[1].split(";")[0])  # noqa: S307
    assert sum(published.values()) == pytest.approx(cast("float", out.value), abs=1e-9)


def test_additivity_is_asserted_not_trusted() -> None:
    """The guard fires when the breakdown and the total disagree."""
    with pytest.raises(ValueError, match=r"must reconcile"):
        _check_additivity({"rates": 1.0, "equity": 1.0}, 99.0)


# ---------------------------------------------------------------------------
# The scenario loader
# ---------------------------------------------------------------------------
def test_the_committed_gfc_scenario_loads_and_is_disclosed_as_uncalibrated() -> None:
    """The spec's own example, committed verbatim — and labelled illustrative."""
    assert "gfc_2008" in list_scenarios()
    scenario = load_scenario("gfc_2008")
    assert scenario.shocks["rates"].unit == "bp"
    assert scenario.shocks["rates"].value == pytest.approx(-300.0)
    assert scenario.calibration_status == "uncalibrated_illustrative"
    assert any(
        "uncalibrated_illustrative" in w
        for w in apply_scenario_shock(_EXPOSURES, scenario).warnings
    )


def test_a_driver_is_carried_but_never_applied() -> None:
    """A growth shock has no position in the factor vector.

    It is the cause whose effect arrives through the rate and credit legs, so
    applying it as a fifth exposure would double-count the move. The engine must
    carry it for the scenario's intent and disclose that it did not apply it.
    """
    scenario = load_scenario("gfc_2008")
    assert "growth_shock" in scenario.drivers
    out = apply_scenario_shock(_EXPOSURES, scenario)
    assert any("drivers" in w and "NOT applied" in w for w in out.warnings)
    # And the driver's -4.0 pp is absent from the arithmetic.
    assert cast("float", out.value) == pytest.approx(5.35)


def test_an_unshocked_factor_is_reported_as_an_explicit_zero() -> None:
    """Its zero is an ABSENCE of a shock, not a measurement of no exposure.

    ⚠️ **This test was WEAK and a mutation survived it — measured 2026-10-09.**
    It originally asserted only the published VALUE and the warning, so a mutant
    that **omitted** every unshocked factor from the breakdown passed: the total
    was still 4.0 and the warning still fired. The breakdown is the deliverable
    and its COMPLETENESS is the behaviour, so that is what is now asserted.
    """
    scenario = Scenario(name="rates_only", shocks={"rates": ScenarioShock(unit="bp", value=-100)})
    out = apply_scenario_shock(_EXPOSURES, scenario)

    # rates contributes +4.0; every other factor is an explicit 0.0.
    assert cast("float", out.value) == pytest.approx(4.0)
    assert any("NO shock" in w for w in out.warnings)

    # THE ASSERTION THE MUTANT SURVIVED WITHOUT: the breakdown covers EVERY
    # configured factor, with the unshocked ones present and exactly zero.
    breakdown = eval(  # noqa: S307
        out.context.split("factor_exposure_breakdown=")[1].split(";")[0]
    )
    assert set(breakdown) == set(get_settings().scenario_engine.factor_names)
    for factor in ("fx", "credit", "equity"):
        assert breakdown[factor] == 0.0, factor


def test_a_missing_scenario_names_what_is_committed() -> None:
    """A FileNotFoundError a caller can act on, not a bare path."""
    with pytest.raises(FileNotFoundError, match=r"gfc_2008"):
        load_scenario("no_such_scenario")


def test_a_shock_without_a_unit_is_refused() -> None:
    """A bare number has no unit, and the unit is what makes the P&L correct."""
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "bare.yaml"
        path.write_text("name: bare\nshocks:\n  rates: -300\n", encoding="utf-8", newline="")
        with pytest.raises(ValueError, match=r"single-key mapping naming its unit"):
            load_scenario("bare", scenarios_dir=tmp)


def test_the_correlation_override_is_published_but_disclosed_as_unconsumed() -> None:
    """Module 17.2's coherence claim must not be lost — nor overclaimed."""
    scenario = load_scenario("gfc_2008")
    out = apply_scenario_shock(_EXPOSURES, scenario)
    assert "treasuries_vs_hy_credit" in out.context
    assert any("does not yet consume it" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# The simulation half (Section 13.2's VaR/ES/drawdown under the shocked matrix)
# ---------------------------------------------------------------------------

#: A plausible DAILY factor covariance, in the configured order
#: (rates, fx, credit, equity). Rates most volatile, fx least.
_COV = [
    [4.0e-4, -1.2e-5, 6.0e-5, -2.0e-5],
    [-1.2e-5, 3.6e-5, -4.0e-6, 1.0e-5],
    [6.0e-5, -4.0e-6, 9.0e-4, -1.5e-5],
    [-2.0e-5, 1.0e-5, -1.5e-5, 2.5e-4],
]


def _sim(scenario: Scenario, *, n_sims: int = 20000, seed: int = 0) -> ModelResult:
    return simulate_scenario_stress(
        _EXPOSURES,
        scenario,
        SimulationInputs(factor_covariance=_COV, horizon_days=1),
        n_sims=n_sims,
        seed=seed,
    )


def test_the_correlation_override_is_consumed_and_shrinks_the_tail() -> None:
    """Section 13.2's `treasuries_vs_hy_credit = -0.7` is flight to quality.

    The book is long treasuries (a negative `rates` exposure) and short credit.
    Inverting their correlation means the treasury leg rallies as credit sells
    off, so the hedge WORKS and the tail must be SMALLER than without the
    override. The direction is the assertion: a drop of the wrong sign would mean
    the override was applied backwards, which is the failure that matters.
    """
    scenario = load_scenario("gfc_2008")
    without = _sim(scenario.model_copy(update={"correlation_override": {}}))
    with_override = _sim(scenario)

    plain_var = cast("float", without.value_dict()["var_95_under_scenario"])
    hedged_var = cast("float", with_override.value_dict()["var_95_under_scenario"])
    # Published NEGATIVE (Section 13.2's own example: -22.1), so a LESS negative
    # number is a SMALLER loss. The hedge working means the tail shrinks, i.e.
    # hedged_var > plain_var. (An earlier version of this test asserted `<` and
    # was wrong: the code was right and the sign reasoning here was not.)
    assert hedged_var > plain_var
    assert any("IS applied" in w for w in with_override.warnings)


def test_an_unresolvable_override_pair_raises_rather_than_being_dropped() -> None:
    """A dropped override would run the stress with the hedge intact.

    That understates the loss, and a stress test that flatters the book is worse
    than none because it is believed.
    """
    with pytest.raises(ValueError, match=r"not a configured factor|not a pair"):
        get_settings().scenario_engine.resolve_override_pair("treasuries_vs_vix")


def test_a_self_correlated_override_pair_is_refused() -> None:
    """A factor's correlation with itself is 1 by definition."""
    with pytest.raises(ValueError, match=r"SAME factor twice"):
        get_settings().scenario_engine.resolve_override_pair("rates_vs_treasuries")


def test_the_covariance_must_match_the_configured_factor_set() -> None:
    """Index i must mean the same factor in the covariance and the exposures."""
    with pytest.raises(ValueError, match=r"configured factor set has"):
        SimulationInputs(factor_covariance=[[1.0, 0.0], [0.0, 1.0]])


def test_a_non_finite_covariance_cell_is_refused() -> None:
    bad = [row[:] for row in _COV]
    bad[1][1] = float("nan")
    with pytest.raises(ValueError, match=r"non-finite"):
        SimulationInputs(factor_covariance=bad)


def test_the_report_publishes_all_five_of_section_13_2s_outputs() -> None:
    """§13.2 names five fields; the report must carry every one."""
    out = _sim(load_scenario("gfc_2008"))
    published = out.value_dict()
    for field in (
        "portfolio_pnl_estimate_pct",
        "var_95_under_scenario",
        "expected_shortfall_under_scenario",
        "max_drawdown_estimate_pct",
        "factor_exposure_breakdown",
    ):
        assert field in published, field
    # ES is at least as severe as VaR — a tail mean beyond the quantile.
    assert published["expected_shortfall_under_scenario"] <= published["var_95_under_scenario"]
    # And the deterministic breakdown still reconciles with its own total.
    assert sum(published["factor_exposure_breakdown"].values()) == pytest.approx(
        published["portfolio_pnl_estimate_pct"], abs=1e-6
    )


def test_the_simulation_is_seeded_and_reproducible() -> None:
    """A stress report that moved between runs could not be argued with."""
    a = _sim(load_scenario("gfc_2008"), seed=7)
    b = _sim(load_scenario("gfc_2008"), seed=7)
    assert a.value_dict()["var_95_under_scenario"] == b.value_dict()["var_95_under_scenario"]


def test_the_one_step_drawdown_limitation_is_disclosed() -> None:
    """A one-period covariance has no honest multi-step path."""
    out = _sim(load_scenario("gfc_2008"))
    assert any("ONE-STEP" in w for w in out.warnings)
    assert any("JOINT NORMALITY" in w for w in out.warnings)


def test_the_published_step_count_is_the_number_actually_drawn() -> None:
    """A published field must describe the computation that ran.

    ⚠️ **DEFECT FOUND AND FIXED 2026-10-09.** The report used to publish
    `"steps": max(horizon_days, 2)`, so a caller asking for `horizon_days=1`
    received `steps: 2` — a field asserting that a two-step path had been drawn
    when the code draws ONE. Worse, the block's own comment claimed "cumulative
    P&L along `horizon_days` steps, then the largest peak-to-trough decline",
    which the code does not do and which the comment two lines below contradicted.

    A field that describes a computation that did not happen is worse than a
    missing field, because it is read as evidence.
    """
    out = _sim(load_scenario("gfc_2008"))
    published = out.value_dict()
    assert published["steps_drawn"] == 1
    # And the field is not merely present-but-stale: it must agree with the horizon
    # the covariance can support.
    assert "steps" not in published, "the old mis-describing field is gone"


def test_max_drawdown_is_the_worst_single_step_outcome_not_a_path_statistic() -> None:
    """§13.2 names the field; the BASIS is what must not be implied.

    The value is `min()` over single-step draws — the worst one-step outcome. It
    is published under §13.2's name, so the warning is what carries the basis.
    """
    out = _sim(load_scenario("gfc_2008"))
    published = out.value_dict()
    # In the positive-loss convention a drawdown is the most negative outcome.
    assert published["max_drawdown_estimate_pct"] <= published["portfolio_pnl_estimate_pct"]


# ---------------------------------------------------------------------------
# Section 9.4's library — all four case studies, each encoding its own crisis
# ---------------------------------------------------------------------------
def test_the_whole_library_is_committed() -> None:
    """AGENTS.md §9.4 names four scenarios; all four must load."""
    assert list_scenarios() == [
        "black_wednesday",
        "covid_2020",
        "gfc_2008",
        "ltcm_1998",
    ]


def test_each_scenario_encodes_a_different_correlation_response() -> None:
    """The library's value is that the four crises are not one crisis relabelled.

    A set of scenarios that all assumed the same flight-to-quality response
    would be one scenario written four times. Measured: -0.1 / -0.3 / -0.7 /
    -0.8, from the mildest (1992, an FX event) to the strongest (1998, the
    correlation-breakdown episode).
    """
    overrides = {
        name: load_scenario(name).correlation_override["treasuries_vs_hy_credit"]
        for name in list_scenarios()
    }
    assert len(set(overrides.values())) == 4, overrides
    assert overrides["black_wednesday"] > overrides["covid_2020"] > overrides["gfc_2008"]
    assert overrides["ltcm_1998"] == min(overrides.values())


def test_black_wednesday_is_an_fx_event_not_an_equity_one() -> None:
    """1992 was a currency crisis: sterling broke, UK equities ROSE.

    A scenario that dumped equities would be 2008 with a different label, and the
    library exists so different crises can be replayed AS THEMSELVES.
    """
    scenario = load_scenario("black_wednesday")
    assert scenario.shocks["fx"].value < 0
    assert scenario.shocks["equity"].value > 0
    assert abs(scenario.shocks["credit"].value) < 50


def test_every_scenario_shocks_all_four_factors() -> None:
    """A scenario that leaves a factor unshocked is a decision, not an accident.

    All four committed scenarios move all four factors, so no leg of the book is
    silently assumed unmoved by the crisis.
    """
    for name in list_scenarios():
        assert set(load_scenario(name).shocks) == set(
            get_settings().scenario_engine.factor_names
        ), name


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
