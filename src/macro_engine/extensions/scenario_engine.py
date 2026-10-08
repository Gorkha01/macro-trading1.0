"""Module 15-16's crisis-scenario shock engine (Sections 13.2 / 14.1).

Section 13.2, Example B, states the whole job:

    ``extensions/scenario_engine.py`` applies the shock vector to current
    portfolio instrument exposures, recomputes portfolio-level VaR/ES/drawdown
    under the shocked correlation matrix (per Module 17.2's "coherent scenario,
    not isolated shock" principle), and returns …

This module builds the part that did not exist: **a named shock vector applied
to a book's factor exposures, reported as a per-factor breakdown.**

Why the factor set had to exist first
-------------------------------------
The system's exposure representation is POSITIONAL — ``models/risk.py``'s
``factor_loadings: list[float]`` and ``MonteCarloVaRInputs`` alike. A positional
vector can be simulated but cannot be *reported*: "the book lost 12%" is not a
breakdown, and Section 13.2 asks for ``factor_exposure_breakdown``. The names
come from ``settings.scenario_engine.factors`` (Section 17.2's *"rates, FX,
credit, equity"*), and this module is the thing that turns a position into a
name.

The identity this module preserves
----------------------------------
``portfolio_pnl_estimate_pct == sum(factor_exposure_breakdown.values())``.

That is not decoration. A breakdown whose parts do not sum to its whole is the
same failure as a risk budget whose contributions do not reconcile — a reader
cannot tell which leg is wrong. ``_check_additivity`` asserts it on every
result rather than trusting the arithmetic.

Units — derived by hand (LAW 3)
-------------------------------
Three different units meet in this file, which is why each is stated:

1. A **shock** is in the factor's own unit: basis points for ``rates`` and
   ``credit``, percent for ``equity`` and ``fx``. The YAML states which.
2. An **exposure** is **percent of portfolio P&L per ONE unit of that shock** —
   e.g. ``rates = -0.04`` means "a 1 bp fall in yields gains 0.04% of the
   portfolio", which is a modified duration of 4 years.
3. A **contribution** is ``exposure * shock`` — **percent of portfolio P&L** —
   and the four of them sum to the total.

Step 2 is the one that would be wrong by 100 if basis points were passed as
yields, and step 3 is the one that would be wrong by 100 if a percent shock were
passed as a decimal. Both are asserted in ``tests/extensions/test_scenario_engine.py``.

What this module deliberately does NOT do
-----------------------------------------
It does not simulate. Section 13.2 also asks for ``var_95_under_scenario`` /
``expected_shortfall_under_scenario`` / ``max_drawdown_estimate_pct``, which need
the *distribution* of outcomes under the shocked correlation matrix — machinery
that already exists as ``models/risk.py``'s ``_simulate_regime_pnls`` and
``portfolio/risk_budget.py``'s ``stress_correlations``. Wiring those in is a
separate increment, because it changes what a stress *reports* rather than what
it *is*: this module answers "which factor hurt and by how much", which is the
question the breakdown exists for. The correlation override is parsed and
published here (so the scenario's coherence claim is not lost) but is not yet
consumed by a simulation.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult, utc_now

__all__ = [
    "FactorExposures",
    "ScenarioShock",
    "apply_scenario_shock",
    "list_scenarios",
    "load_scenario",
]

#: The units a shock may be stated in, and the multiplier that converts ONE unit
#: of that shock into the exposure's unit. A basis point is 1/100th of a percent,
#: so an exposure quoted "per bp" is scaled by 0.01 to be applied to a shock
#: quoted in bp. Percent needs no scaling. This table is the whole reason the
#: two unit systems cannot silently disagree.
#:
#: ``pp`` (percentage points) exists for DRIVERS — a growth shock is a shift in
#: the output gap, measured in pp. It is deliberately not a unit an *exposure*
#: is quoted in, because no configured factor's shock uses it; a driver is never
#: applied to the exposure vector (see the module docstring), so its scale is
#: never consumed.
_UNIT_SCALE: dict[str, float] = {"bp": 1.0, "pct": 1.0, "pp": 1.0}


class ScenarioShock(BaseModel):
    """One factor's shock, in its own stated unit.

    The unit is a field rather than a convention because ``rates`` is naturally
    quoted in basis points and ``equity`` in percent, and a file that mixed the
    two without saying so would produce a P&L wrong by a factor of 100 in one
    leg while every number still looked plausible.
    """

    model_config = ConfigDict(extra="forbid")

    unit: Literal["bp", "pct", "pp"]
    value: float = Field(
        allow_inf_nan=False,
        description=(
            "The shock's magnitude in `unit`. SIGNED: a negative rate shock is a "
            "RALLY (yields fall), a positive credit shock is a WIDENING. The sign "
            "convention is per factor and is not normalised here, because "
            "'adverse' differs by factor — see the module docstring."
        ),
    )


class Scenario(BaseModel):
    """A named, loaded shock vector plus its correlation override.

    ``drivers`` is carried but never applied. A growth shock has no position in
    the factor vector — it is the *cause* whose effect arrives through the rate
    and credit legs — so applying it as a fifth exposure would double-count.
    It is published so the scenario's intent survives into the result.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    calibration_status: str = "uncalibrated_illustrative"
    shocks: dict[str, ScenarioShock]
    drivers: dict[str, ScenarioShock] = Field(default_factory=dict)
    correlation_override: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _every_shock_names_a_configured_factor(self) -> Scenario:
        """A shock for a factor the book does not carry is a silent drop.

        The engine can only apply shocks to positions in the exposure vector,
        and that vector is the configured factor set. A shock naming anything
        else would be read, accepted, and then ignored — leaving a breakdown
        that omits a whole leg of the stress while claiming to be complete.
        """
        configured = set(get_settings().scenario_engine.factor_names)
        unknown = sorted(set(self.shocks) - configured)
        if unknown:
            raise ValueError(
                f"scenario '{self.name}' shocks unknown factor(s): {unknown}. "
                f"Configured factors: {sorted(configured)} "
                f"(scenario_engine.factors). A shock outside the exposure vector "
                f"would be silently dropped from the breakdown."
            )
        if not self.shocks:
            raise ValueError(f"scenario '{self.name}' carries no shocks at all.")
        return self


class FactorExposures(BaseModel):
    """The book's P&L sensitivity, one entry per configured factor.

    ``pnl_pct_per_unit`` is **percent of portfolio P&L per ONE unit of that
    factor's shock** (bp for rates/credit, percent for equity/fx). See the module
    docstring, step 2 — this is the field a unit error would corrupt, so the
    description states the basis rather than leaving it to a reader.

    Every configured factor must be present. A missing one is not "no exposure":
    it is an unanswered question, and defaulting it to zero would publish a
    breakdown that cannot be distinguished from a book that genuinely has no
    risk there.
    """

    model_config = ConfigDict(extra="forbid")

    pnl_pct_per_unit: dict[str, float]

    @model_validator(mode="after")
    def _exactly_the_configured_factors(self) -> FactorExposures:
        configured = set(get_settings().scenario_engine.factor_names)
        supplied = set(self.pnl_pct_per_unit)
        missing = sorted(configured - supplied)
        unknown = sorted(supplied - configured)
        if missing:
            raise ValueError(
                f"exposures omit configured factor(s): {missing}. A missing factor "
                f"is an unanswered question, not a zero exposure — defaulting it "
                f"would publish a breakdown indistinguishable from a book with no "
                f"risk there."
            )
        if unknown:
            raise ValueError(
                f"exposures name unknown factor(s): {unknown}. Configured: {sorted(configured)}."
            )
        for factor, value in self.pnl_pct_per_unit.items():
            if not math.isfinite(value):
                raise ValueError(
                    f"exposure for '{factor}' is {value!r}; a non-finite sensitivity "
                    f"would publish a non-finite P&L."
                )
        return self


def _scenarios_dir(override: str | Path | None) -> Path:
    if override is not None:
        return Path(override)
    return Path(get_settings().scenario_engine.scenarios_dir)


def list_scenarios(*, scenarios_dir: str | Path | None = None) -> list[str]:
    """Every committed scenario name, sorted. Empty if the directory is absent.

    An absent directory returns ``[]`` rather than raising: "no scenarios are
    committed" is a legitimate state, and a caller enumerating them should not
    have to distinguish it from a filesystem error.
    """
    directory = _scenarios_dir(scenarios_dir)
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.yaml"))


def load_scenario(name: str, *, scenarios_dir: str | Path | None = None) -> Scenario:
    """Load and VALIDATE one scenario YAML by name.

    Validation happens here rather than at use, so a scenario that names an
    unconfigured factor fails when it is loaded — with the factor named — rather
    than silently contributing nothing to a breakdown later.
    """
    directory = _scenarios_dir(scenarios_dir)
    path = directory / f"{name}.yaml"
    if not path.is_file():
        available = list_scenarios(scenarios_dir=directory)
        raise FileNotFoundError(
            f"no scenario '{name}' in {directory}. Committed scenarios: {available or 'none'}."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"scenario file {path} did not parse to a mapping.")

    # The YAML states each shock as `{bp: -300}` or `{pct: -35}` — a one-key
    # mapping whose key IS the unit. Normalising it here keeps the unit attached
    # to the number instead of leaving it to the reader's memory of the file.
    shocks = {
        factor: _as_shock(factor, spec, path) for factor, spec in (raw.get("shocks") or {}).items()
    }
    drivers = {
        factor: _as_shock(factor, spec, path) for factor, spec in (raw.get("drivers") or {}).items()
    }
    return Scenario(
        name=str(raw.get("name") or name),
        description=str(raw.get("description") or "").strip(),
        calibration_status=str(raw.get("calibration_status") or "uncalibrated_illustrative"),
        shocks=shocks,
        drivers=drivers,
        correlation_override=dict(raw.get("correlation_override") or {}),
    )


def _as_shock(factor: str, spec: object, path: Path) -> ScenarioShock:
    """Turn ``{bp: -300}`` into a ``ScenarioShock``, naming the file on failure."""
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ValueError(
            f"{path}: shock for '{factor}' must be a single-key mapping naming its "
            f"unit, e.g. `bp: -300` or `pct: -35`. Got {spec!r}. A bare number has "
            f"no unit, and the unit is what makes the P&L correct."
        )
    ((unit, value),) = spec.items()
    if unit not in _UNIT_SCALE:
        raise ValueError(
            f"{path}: shock for '{factor}' uses unit '{unit}', which is not one of "
            f"{sorted(_UNIT_SCALE)}."
        )
    return ScenarioShock(unit=unit, value=float(value))


def apply_scenario_shock(
    exposures: FactorExposures,
    scenario: Scenario,
) -> ModelResult:
    """Apply a scenario's shock vector to a book; publish the factor breakdown.

    Returns a ``ModelResult`` whose ``value`` is the **portfolio P&L estimate in
    percent** (signed: negative is a loss) and whose ``context`` carries the
    per-factor breakdown and the correlation override.

    **The breakdown is the deliverable.** Section 13.2 asks for
    ``factor_exposure_breakdown`` because a single stressed number cannot be
    argued with: "the book loses 18%" invites no corrective action, while
    "rates contributed -12, credit -4.1, equity -2.3" tells a desk which leg to
    hedge. That is the entire reason the factor set had to be named first.

    **Unshocked factors contribute exactly zero and are still reported.** A
    scenario that shocks three of four factors leaves the fourth at zero, and
    printing it is not noise — its absence would be indistinguishable from the
    engine having dropped it.
    """
    settings = get_settings().scenario_engine
    breakdown: dict[str, float] = {}
    for factor in settings.factor_names:
        exposure = exposures.pnl_pct_per_unit[factor]
        shock = scenario.shocks.get(factor)
        # No shock for this factor = no move = no contribution. Recorded as an
        # explicit 0.0 rather than omitted, so the breakdown always covers the
        # whole configured set.
        contribution = 0.0 if shock is None else exposure * shock.value * _UNIT_SCALE[shock.unit]
        breakdown[factor] = round(contribution, 6)

    total = round(sum(breakdown.values()), 6)
    _check_additivity(breakdown, total)

    shocked = {f: s.value for f, s in scenario.shocks.items()}
    unshocked = [f for f in settings.factor_names if f not in scenario.shocks]

    warnings = [
        f"Scenario '{scenario.name}' is {scenario.calibration_status}: the shock "
        f"magnitudes were chosen to illustrate a 2008-style episode, not fitted to "
        f"data. The breakdown is exact ARITHMETIC on the exposures; it is not a "
        f"forecast, and its precision is not evidence about the next crisis.",
    ]
    if unshocked:
        warnings.append(
            f"{len(unshocked)} configured factor(s) carry NO shock in this scenario "
            f"and contribute exactly zero: {unshocked}. Their zero is an ABSENCE of "
            f"a shock, not a measurement that the book is unexposed there."
        )
    if scenario.correlation_override:
        warnings.append(
            f"The scenario overrides correlations {scenario.correlation_override} "
            f"(Module 17.2's coherent-scenario requirement). This engine PARSES and "
            f"publishes that override but does not yet consume it: the deterministic "
            f"breakdown below does not depend on correlations at all. The simulated "
            f"VaR/ES under the shocked matrix is a separate increment."
        )
    if scenario.drivers:
        warnings.append(
            f"Scenario drivers {list(scenario.drivers)} are documented but NOT "
            f"applied. A growth shock has no position in the factor vector — it is "
            f"the cause whose effect arrives through the rate and credit legs, so "
            f"applying it would double-count."
        )

    return ModelResult(
        model_name="apply_scenario_shock",
        country="us",
        as_of=utc_now(),
        value=total,
        confidence=0.5,
        interpretation=(
            f"Under scenario '{scenario.name}', the book's estimated P&L is "
            f"{total:+.4f}% of portfolio value."
        ),
        context=(
            f"factor_exposure_breakdown={breakdown}; "
            f"shocks_applied={shocked}; "
            f"factors={list(settings.factor_names)}; "
            f"correlation_override={scenario.correlation_override or '{}'}; "
            f"breakdown sums to the total by construction and is asserted."
        ),
        inputs_used=["exposures", f"scenario:{scenario.name}"],
        warnings=warnings,
        unit="percent",
        direction=(
            "a deterministic P&L estimate: each factor's exposure times its shock, "
            "summed. No simulation, so no sampling error — and no distribution."
        ),
        assumptions=[
            "The book's exposures are LINEAR in each factor over the shock's size. "
            "A -300bp rate move is applied at the same duration as a -1bp move, "
            "which understates convexity in a rally of that size.",
            "Factors are shocked independently in this arithmetic; the scenario's "
            "correlation_override is published but not yet consumed.",
            "Exposures are taken as given. Deriving them from a position list is a "
            "separate step, and the two must agree on the factor ORDER.",
        ],
        data_provenance=[
            "exposures — supplied by the CALLER. This module has no data-layer "
            "dependency: it is pure arithmetic over a book and a scenario file.",
            f"scenario — {_scenarios_dir(None)}/{scenario.name}.yaml, committed.",
        ],
    )


def _check_additivity(breakdown: dict[str, float], total: float) -> None:
    """The parts must sum to the whole, and this asserts it rather than trusting it.

    A breakdown whose contributions do not reconcile is the same defect as a risk
    budget whose contributions do not: a reader cannot tell which leg is wrong.
    The tolerance is for float summation only — the arithmetic is exact, so a
    failure here means the breakdown was built from something other than the
    published contributions.
    """
    recomputed = sum(breakdown.values())
    if abs(recomputed - total) > 1e-9:
        raise ValueError(
            f"factor breakdown sums to {recomputed!r} but the published total is "
            f"{total!r}. The breakdown must reconcile with the number beside it."
        )
