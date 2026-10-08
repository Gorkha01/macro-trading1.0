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
    _check_additivity,
    apply_scenario_shock,
    list_scenarios,
    load_scenario,
)

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
    """Its zero is an ABSENCE of a shock, not a measurement of no exposure."""
    scenario = Scenario(name="rates_only", shocks={"rates": ScenarioShock(unit="bp", value=-100)})
    out = apply_scenario_shock(_EXPOSURES, scenario)
    # rates contributes +4.0; every other factor is an explicit 0.0.
    assert cast("float", out.value) == pytest.approx(4.0)
    assert any("NO shock" in w for w in out.warnings)


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
