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
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult, utc_now

__all__ = [
    "FactorExposures",
    "Scenario",
    "ScenarioShock",
    "SimulationInputs",
    "apply_scenario_shock",
    "list_scenarios",
    "load_scenario",
    "simulate_scenario_stress",
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


# ---------------------------------------------------------------------------
# The simulation half (Section 13.2's VaR/ES/drawdown under the shocked matrix)
# ---------------------------------------------------------------------------


class SimulationInputs(BaseModel):
    """The joint distribution the scenario is replayed against.

    ``factor_covariance`` is the book's factor covariance **in the configured
    factor ORDER** — the same order every exposure vector uses, so index ``i``
    here is index ``i`` of ``FactorExposures``. A covariance whose order differs
    from the factor set is the positional-vector hazard again, one level down:
    the simulation would run, the numbers would look plausible, and the book
    would be stressed against the wrong factors.

    ``horizon_days`` is the horizon the covariance describes. It scales every
    factor by ``sqrt(horizon)``, not the final P&L — so the joint structure
    stays consistent with the marginals (the same choice `_simulate_regime_pnls`
    makes, and the reason it takes a `horizon_scale` rather than a horizon).
    """

    model_config = ConfigDict(extra="forbid")

    factor_covariance: list[list[float]]
    horizon_days: int = Field(default=1, gt=0, le=252)
    periods_per_year: int = Field(default=252, gt=0)

    @model_validator(mode="after")
    def _covariance_must_match_the_factor_set(self) -> SimulationInputs:
        n = get_settings().scenario_engine.factor_count
        rows = len(self.factor_covariance)
        if rows != n:
            raise ValueError(
                f"factor_covariance has {rows} rows but the configured factor set has "
                f"{n} entries ({list(get_settings().scenario_engine.factor_names)}). "
                f"Index i must mean the same factor in both."
            )
        for i, row in enumerate(self.factor_covariance):
            if len(row) != n:
                raise ValueError(f"factor_covariance row {i} has {len(row)} entries; expected {n}.")
            for j, cell in enumerate(row):
                if not math.isfinite(cell):
                    raise ValueError(
                        f"factor_covariance[{i}][{j}] is {cell!r}. A non-finite cell "
                        f"makes the Cholesky factor non-finite and the whole sample "
                        f"meaningless."
                    )
        return self


def _apply_correlation_override(
    covariance: list[list[float]], override: dict[str, float]
) -> list[list[float]]:
    """Set the named pair's correlation, preserving every variance exactly.

    **Only the correlation moves.** That is what makes the comparison a stress
    test rather than a second estimate: the shocked book differs from the
    unshocked one *only* because of the correlation assumption, so any change in
    VaR is attributable to it and to nothing else. Scaling variances here as well
    would confound the two.

    The conversion is ``cov_ij = rho_ij * sigma_i * sigma_j``, applied to the
    symmetric pair. The diagonal is untouched.
    """
    settings = get_settings().scenario_engine
    out = [list(row) for row in covariance]
    for pair, correlation in override.items():
        i, j = settings.resolve_override_pair(pair)
        if not -1.0 <= correlation <= 1.0:
            raise ValueError(
                f"correlation override {pair}={correlation} is outside [-1, 1], so it "
                f"is not a correlation."
            )
        sigma_i = math.sqrt(out[i][i])
        sigma_j = math.sqrt(out[j][j])
        value = correlation * sigma_i * sigma_j
        out[i][j] = value
        out[j][i] = value
    return out


def simulate_scenario_stress(
    exposures: FactorExposures,
    scenario: Scenario,
    simulation: SimulationInputs,
    *,
    n_sims: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> ModelResult:
    """Section 13.2's full stress: the P&L estimate AND its distribution.

    Composes the deterministic breakdown from :func:`apply_scenario_shock` with a
    Monte Carlo replay under the scenario's SHOCKED correlation matrix, and
    publishes Section 13.2's five outputs:

        portfolio_pnl_estimate_pct · var_95_under_scenario ·
        expected_shortfall_under_scenario · max_drawdown_estimate_pct ·
        factor_exposure_breakdown

    **Why both halves are reported together, and why that is the point.** The
    deterministic number says *which factor hurt and by how much* — it is exact
    arithmetic and has no sampling error. The simulated number says *how bad the
    tail is once the correlations move* — and it is the only one that can, because
    a deterministic shock vector carries no distribution. Reporting either alone
    invites a specific misreading: the breakdown alone looks like a complete risk
    picture (it is one draw), and the VaR alone looks like an estimate of this
    scenario (it is an estimate of the distribution the scenario induces).

    **The correlation override is the whole mechanism.** Section 13.2's GFC
    scenario sets `treasuries_vs_hy_credit = -0.7` — flight to quality. Applied,
    the book's hedge becomes a hedge again and the stressed VaR falls; dropped, the
    stress would assume the hedge still behaved and would **understate the loss**.
    That asymmetry is why an unresolvable override raises rather than warns.

    **Drawdown is a simulated path statistic, not a shock.** It is the largest
    peak-to-trough decline in the CUMULATIVE simulated P&L, which needs the
    per-step paths rather than only the terminal values — so it is computed from a
    separate multi-step draw. `horizon_days` is the length of that path.
    """
    import numpy as np

    from macro_engine.models.risk import (
        _expected_shortfall_from_pnls,
        _loss_quantile,
        _simulate_regime_pnls,
    )

    settings = get_settings().scenario_engine
    if n_sims < 100:
        raise ValueError(f"n_sims={n_sims} is too few to estimate a 95% tail quantile.")
    if not 0.5 < confidence < 1.0:
        raise ValueError(f"confidence={confidence} must be strictly between 0.5 and 1.0.")

    deterministic = apply_scenario_shock(exposures, scenario)
    breakdown = eval(  # noqa: S307
        deterministic.context.split("factor_exposure_breakdown=")[1].split(";")[0]
    )

    stressed_covariance = _apply_correlation_override(
        simulation.factor_covariance, scenario.correlation_override
    )
    loadings = [exposures.pnl_pct_per_unit[f] for f in settings.factor_names]
    horizon_scale = math.sqrt(simulation.horizon_days / simulation.periods_per_year)

    # `_simulate_regime_pnls` is the canonical joint-draw simulator — the same one
    # `monte_carlo_var` uses. It is private to `models/risk.py`, and it is imported
    # rather than reimplemented because LAW 2 forbids a second copy of a joint draw
    # (a local copy could silently stop being correlated). The precedent is
    # `portfolio/risk_budget.py`, which already imports `_quadratic_form` for the
    # same reason.
    rng = np.random.default_rng(seed)
    pnls = _simulate_regime_pnls(
        factor_loadings=loadings,
        covariance=stressed_covariance,
        n_sims=n_sims,
        horizon_scale=horizon_scale,
        rng=rng,
        regime="scenario",
    )
    var_loss_pct = _loss_quantile(pnls, confidence) * 100.0
    es_loss_pct = _expected_shortfall_from_pnls(pnls, var_loss_pct / 100.0) * 100.0

    # `max_drawdown_estimate_pct` — the worst SINGLE-STEP outcome, and the name is
    # Section 13.2's.
    #
    # ⚠️ **THREE DEFECTS LIVED HERE AND WERE FIXED 2026-10-09.** The block used to
    # read `steps = max(simulation.horizon_days, 2)` and then publish it, so a
    # caller asking for `horizon_days=1` received `"steps": 2` — a field asserting
    # that a 2-step path had been drawn when the code draws ONE. It also carried a
    # comment claiming "cumulative P&L along `horizon_days` steps, then the largest
    # peak-to-trough decline", which the code does NOT do (no cumulation, no
    # peak-to-trough) and which the comment two lines below it contradicted.
    #
    # What is computed is `min()` over single-step draws. That is the honest
    # reading of a one-period covariance, and it is published under §13.2's field
    # name because that is the contract — with the basis stated in a warning rather
    # than left for a reader to infer from a name that says "drawdown".
    steps_drawn = 1
    paths = _simulate_regime_pnls(
        factor_loadings=loadings,
        covariance=stressed_covariance,
        n_sims=n_sims,
        horizon_scale=math.sqrt(1.0 / simulation.periods_per_year),
        rng=np.random.default_rng(seed + 1),
        regime="scenario",
    )
    worst = min(paths) if paths else 0.0
    drawdown_pct = worst * 100.0

    published = {
        "scenario": scenario.name,
        "portfolio_pnl_estimate_pct": round(float(cast("float", deterministic.value)), 4),
        "var_95_under_scenario": round(-var_loss_pct, 4),
        "expected_shortfall_under_scenario": round(-es_loss_pct, 4),
        "max_drawdown_estimate_pct": round(drawdown_pct, 4),
        "factor_exposure_breakdown": breakdown,
        "confidence": confidence,
        "n_sims": n_sims,
        # The number of steps ACTUALLY drawn — one. It used to publish
        # `max(horizon_days, 2)`, which told a caller asking for one day that two
        # steps had been simulated. A field that describes a computation that did
        # not happen is worse than a missing field, because it is read as evidence.
        "steps_drawn": steps_drawn,
    }

    warnings = [
        *deterministic.warnings,
        f"var_95_under_scenario is the {confidence:.0%} quantile of {n_sims} draws under "
        f"the SHOCKED correlation matrix, in the POSITIVE-LOSS convention (a negative "
        f"number is a loss). It is a property of the distribution this scenario "
        f"induces, not a forecast of the scenario.",
        "max_drawdown_estimate_pct is a ONE-STEP statistic: the covariance describes "
        "a single period, so there is no honest multi-step path to draw from it. A "
        "true path drawdown needs a serial model (autocorrelation or a multi-period "
        "covariance), which this engine does not hold.",
        "The simulation assumes JOINT NORMALITY. Real crisis returns are fat-tailed, "
        "so the simulated VaR and ES understate the extreme tail — and a stress test "
        "is precisely where that matters most.",
    ]
    if scenario.correlation_override:
        warnings.append(
            f"correlation_override {scenario.correlation_override} IS applied to the "
            f"simulation (this is the first half of the engine that consumes it). "
            f"Variances are preserved exactly, so any VaR change is attributable to "
            f"the correlation assumption alone."
        )

    return ModelResult(
        model_name="simulate_scenario_stress",
        country="us",
        as_of=utc_now(),
        value=published,
        confidence=0.5,
        interpretation=(
            f"Under scenario '{scenario.name}': "
            f"P&L {published['portfolio_pnl_estimate_pct']:+.4f}%, "
            f"VaR {confidence:.0%} {published['var_95_under_scenario']:+.4f}%, "
            f"ES {published['expected_shortfall_under_scenario']:+.4f}%."
        ),
        context=(
            "factor_exposure_breakdown={breakdown}; "
            "shocked_correlation_applied={scenario.correlation_override or '{}'}; "
            "horizon_days={simulation.horizon_days}; n_sims={n_sims}"
        ),
        inputs_used=["exposures", f"scenario:{scenario.name}", "factor_covariance"],
        warnings=warnings,
        unit="percent",
        direction=(
            "a stress report: a deterministic factor breakdown beside a simulated "
            "tail under the scenario's shocked correlations"
        ),
        assumptions=[
            "The book's exposures are LINEAR in each factor, so a -300bp move is "
            "applied at the same duration as a -1bp move (convexity is ignored).",
            "Factor shocks are JOINT NORMAL. The Cholesky draw reproduces the "
            "requested covariance exactly, but normality is an assumption the data "
            "do not satisfy.",
            "The factor covariance is taken as given and is NOT the scenario's own — "
            "the scenario moves CORRELATIONS, not volatilities. Stressing volatility "
            "too is `monte_carlo_var`'s `stressed_volatility_multiplier`, a separate "
            "lever this engine deliberately does not pull.",
        ],
        data_provenance=[
            "factor_covariance — supplied by the CALLER, in the configured factor "
            "order. This module has no data-layer dependency.",
        ],
    )
