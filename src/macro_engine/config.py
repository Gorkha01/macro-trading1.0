"""Typed configuration loader (AGENTS.md Section 3, 10.4).

Loads ``config/settings.yaml`` and ``config/series_registry.yaml`` into
validated Pydantic models, and ``.env`` into the process environment.

Design stance: **configuration errors are startup errors.** A malformed
threshold or a Kelly divisor below the mandated floor raises at load time,
not silently at 3am inside a valuation. Section 21.0 rule 3 is explicit that
inventing a "reasonable default" for an unspecified input is the single most
dangerous failure mode available to this system — so where the specification
names a value, this module either finds it in config or raises.
"""

from __future__ import annotations

import math
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "BeveridgeCurvePoint",
    "BeveridgeSettings",
    "CalibratedValue",
    "CalibrationStatus",
    "ConfidenceSettings",
    "CountrySettings",
    "CrossMarketRVSettings",
    "DrawdownTier",
    "InvalidationSettings",
    "KellySettings",
    "LeadingIndicatorSettings",
    "OpenBBSettings",
    "RegimeBaseRates",
    "RegimeRateValues",
    "RegimeSettings",
    "RiskSettings",
    "ScenarioDistributionSettings",
    "SeriesRegistry",
    "Settings",
    "TransmissionSettings",
    "ValidationSettings",
    "get_registry",
    "get_settings",
    "project_root",
]


def project_root() -> Path:
    """Repository root, resolved from this file's location.

    ``src/macro_engine/config.py`` -> up three levels. Resolved rather than
    taken from CWD so that config loading behaves identically under pytest,
    the API server, and the CLI tools.
    """
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Calibration status — the honesty mechanism for every CONFIG parameter.
# ---------------------------------------------------------------------------
CalibrationStatus = str
# Permitted values, enforced below:
#   institutional_fact        — an observable institutional convention (2% target)
#   institutional_convention  — a widely-used industry default (10% vol target)
#   conventional              — a standard textbook value
#   mechanical_rule           — a pre-committed hard rule (drawdown tiers)
#   fitted_assumption         — estimated from data, documented as such
#   judgment_parameters       — stated human judgment, versioned
#   uncalibrated_illustrative — a placeholder awaiting calibration; DO NOT trust
_VALID_CALIBRATION: frozenset[str] = frozenset(
    {
        "institutional_fact",
        "institutional_convention",
        "conventional",
        "mechanical_rule",
        "fitted_assumption",
        "judgment_parameters",
        "uncalibrated_illustrative",
    }
)


class BeveridgeCurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unemployment_rate: float = Field(ge=0.0, le=100.0)
    openings_rate: float = Field(ge=0.0, le=100.0)


# Drawdown-tier magnitude floors (Module 17.3). These exist to make the
# settings.yaml PERCENT convention checkable against Section 6.6c's FRACTION
# convention — the two differ by 100x and the type cannot tell them apart.
# A first de-risking step below 1% of drawdown, or a reduction below 1%, is a
# mis-scaled file rather than a policy, because the ladder exists to respond to
# a serious loss.
_MIN_DRAWDOWN_TIER_PCT = 1.0
_MIN_RISK_REDUCTION_PCT = 1.0


class DrawdownTier(BaseModel):
    """One pre-committed mechanical de-risking step (Module 17.3).

    **Both fields are PERCENTS** — ``drawdown_pct: 10.0`` means a 10% drawdown
    and ``risk_reduction_pct: 50.0`` means "remove half the risk". This is the
    convention of ``settings.yaml`` as a whole, and it is deliberately *not*
    Section 6.6c's, which uses fractions. The conversion happens at exactly one
    boundary (``portfolio/risk_budget.py``).

    The bounds below are ``(0, 100]`` and that range cannot by itself
    distinguish a percent from a fraction — ``0.15`` is a legal value here and
    an impossible drawdown. So a **magnitude floor** is enforced instead:
    a tier expressed as a fraction of a drawdown would be below a few percent,
    and a pre-committed de-risking ladder whose first step is a 0.1% drawdown is
    a mis-scaled file rather than a policy. The floor makes the file's
    convention checkable, which is the only thing that catches a 100x error at
    load time.
    """

    model_config = ConfigDict(extra="forbid")

    drawdown_pct: float = Field(gt=0.0, le=100.0)
    risk_reduction_pct: float = Field(gt=0.0, le=100.0)

    @model_validator(mode="after")
    def _reject_fraction_scale_entry(self) -> DrawdownTier:
        """Reject a tier that looks like a fraction in a percent field.

        The check is one-sided on purpose. A tier of ``0.15`` is almost
        certainly ``0.15`` meaning 15% written in Section 6.6c's convention,
        and it would make the ladder trigger on a 0.15% drawdown — which looks
        like a working rule and is not one. A tier of ``15.0`` is unambiguous
        enough that no bound of this shape would improve on it.
        """
        if self.drawdown_pct < _MIN_DRAWDOWN_TIER_PCT:
            raise ValueError(
                f"drawdown tier {self.drawdown_pct} is below "
                f"{_MIN_DRAWDOWN_TIER_PCT}%. These fields are PERCENTS: a 10% "
                f"drawdown is `10.0`, not `0.10`. A value this small is almost "
                f"certainly a fraction written into a percent field, which would "
                f"make the ladder trigger on a negligible move."
            )
        if self.risk_reduction_pct < _MIN_RISK_REDUCTION_PCT:
            raise ValueError(
                f"risk_reduction_pct {self.risk_reduction_pct} is below "
                f"{_MIN_RISK_REDUCTION_PCT}%. These fields are PERCENTS: a "
                f"half-size reduction is `50.0`, not `0.50`. A reduction this "
                f"small is almost certainly a fraction written into a percent "
                f"field, and it would make the rule inert."
            )
        return self


class CalibratedValue(BaseModel):
    """The ``{value, calibration_status, note}`` envelope used in settings.yaml.

    Every tunable parameter is wrapped in this envelope rather than written as
    a bare number. That is deliberate friction: it makes it impossible to add a
    parameter without stating whether it is a fact, a convention, or an
    uncalibrated placeholder — and ``is_calibrated()`` can then feed
    ``ConfidenceInputs.is_heuristic_not_calibrated`` automatically.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any
    calibration_status: CalibrationStatus
    note: str = ""
    source_reference: str | None = None

    @model_validator(mode="after")
    def _validate_calibration_status(self) -> CalibratedValue:
        if self.calibration_status not in _VALID_CALIBRATION:
            raise ValueError(
                f"Unknown calibration_status {self.calibration_status!r}. "
                f"Permitted: {sorted(_VALID_CALIBRATION)}"
            )
        return self

    @property
    def is_trustworthy(self) -> bool:
        """Whether this value is calibrated rather than a placeholder."""
        return self.calibration_status != "uncalibrated_illustrative"


class KellySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fractional_divisor: CalibratedValue
    min_fractional_divisor: CalibratedValue
    grid_points: CalibratedValue

    @model_validator(mode="after")
    def _enforce_fractional_kelly_floor(self) -> KellySettings:
        """AGENTS.md Section 22.6 / Finding #6: fractional Kelly is mandatory.

        Full Kelly requires the probability estimates to be exact, which they
        never are. A divisor below the configured floor means the sizing model
        is effectively running full-Kelly — reject it at load time.
        """
        divisor = float(self.fractional_divisor.value)
        floor = float(self.min_fractional_divisor.value)
        if divisor < floor:
            raise ValueError(
                f"kelly.fractional_divisor ({divisor}) is below the mandated floor "
                f"({floor}). Full-Kelly sizing is prohibited — see AGENTS.md "
                f"Section 22.6 / Finding #6."
            )
        return self

    @property
    def divisor(self) -> float:
        return float(self.fractional_divisor.value)

    @property
    def kelly_fraction_multiplier(self) -> float:
        """The fraction of full Kelly to actually bet: ``1 / divisor``."""
        return 1.0 / self.divisor

    @property
    def search_points(self) -> int:
        """Grid resolution for the expected-log-growth argmax (Section 22.6).

        Section 22.6's literal ``n_grid = 1000`` is **not** accurate enough for
        this project's published precision, and the shortfall was measured
        rather than reasoned about: on a binary bet with a closed-form optimum
        of exactly ``0.200000``, a 1000-point grid returns ``0.200200`` — an
        error of ``2e-4``, which is **400x** the 6 dp the result is rounded to.
        The published digits were therefore decided by the search rather than by
        the mathematics. ``100001`` points reproduce the closed form exactly at
        ~97 ms per call on a five-branch set, which is why the default is what
        it is and why the resolution lives here rather than in a literal.
        """
        points = int(self.grid_points.value)
        if points < 2:
            raise ValueError(
                f"kelly.grid_points ({points}) must be at least 2 — a grid of "
                f"one point cannot search, and a grid of zero points would "
                f"divide by zero when its step is computed."
            )
        return points


class CurveTradeSettings(BaseModel):
    """Module 15.1/15.2 — duration-weighted curve and breakeven construction.

    Section 15.1b's only guard is ``abs(net_duration_residual) < 0.01``, which
    cannot fire: the residual is the *definition* of ``notional_long``
    algebraically simplified, so it is zero for every input, correct or not
    (D-059 probe P14). These leaves give the function a check whose value
    depends on its inputs rather than on its own arithmetic: the ratio of each
    leg's modified duration to the tenor it claims to describe.

    The breakeven pair (D-060) guards the **ratio between the two legs**, not
    each leg against its tenor, and the reason is measured rather than
    assumed: a same-tenor breakeven's two legs share one maturity, so the
    per-leg band is satisfied by construction and the only quantity carrying
    information is how far apart the two durations are (D-060 probe P10/P11).

    See the ``curve_trade:`` block in ``config/settings.yaml`` for the
    measurement behind every bound.
    """

    model_config = ConfigDict(extra="forbid")

    duration_to_tenor_min: CalibratedValue
    duration_to_tenor_max: CalibratedValue
    net_duration_display_pct: CalibratedValue
    breakeven_duration_ratio_min: CalibratedValue
    breakeven_duration_ratio_max: CalibratedValue

    @property
    def minimum_duration_to_tenor(self) -> float:
        return float(self.duration_to_tenor_min.value)

    @property
    def maximum_duration_to_tenor(self) -> float:
        return float(self.duration_to_tenor_max.value)

    @property
    def display_tolerance(self) -> float:
        return float(self.net_duration_display_pct.value)

    @property
    def minimum_breakeven_duration_ratio(self) -> float:
        return float(self.breakeven_duration_ratio_min.value)

    @property
    def maximum_breakeven_duration_ratio(self) -> float:
        return float(self.breakeven_duration_ratio_max.value)


class CrossMarketRVSettings(BaseModel):
    """Module 15.3 — the cross-market relative-value constructor (D-062).

    Section 20.12's constructor publishes **no residual, no guard and no input
    contract**. ``duration_b = 0`` divides by zero, and a duration wrong by ten
    times produces a wrong notional silently — the same silence D-060 found in
    Section 15.1b's breakeven half, one function over.

    The band here is deliberately **not** the duration/tenor ratio its two
    siblings use. A cross-market pair has no shared maturity, so that ratio is
    undefined; and the pairwise duration ratio that replaces it is not a guard
    either, because a legitimate 3m-against-30y pair has a ratio of 0.0161 while
    its mirror image has 62.21 (D-062 probe P3). The guard that carries
    information is therefore the **absolute** modified duration of each leg.

    See the ``cross_market_rv:`` block in ``config/settings.yaml`` for the
    measurement behind every bound.
    """

    model_config = ConfigDict(extra="forbid")

    minimum_duration_years: CalibratedValue
    maximum_duration_years: CalibratedValue
    max_abs_hedge_degradation: CalibratedValue

    @property
    def minimum_duration(self) -> float:
        """Smallest plausible MODIFIED duration, in years, for one leg."""
        return float(self.minimum_duration_years.value)

    @property
    def maximum_duration(self) -> float:
        """Largest plausible MODIFIED duration, in years, for one leg."""
        return float(self.maximum_duration_years.value)

    @property
    def hedge_degradation_bound(self) -> float:
        """Bound on ``abs(correlation_normal - correlation_stressed)``.

        **Measured, not chosen** (``scripts/live_cross_market_rv.py``): over 8
        real US cross-market pairs the realised range is 0.004 .. 0.175 on the
        S&P tail and 0.072 .. 0.320 on the VIX tail, so the worst measured pair
        is 0.320 and this bound has **1.56x** headroom over it. It still refuses
        the 1.523 the specification's own default produces.
        """
        return float(self.max_abs_hedge_degradation.value)


class ScenarioDistributionSettings(BaseModel):
    """Module 12 — the explicit scenario set's numbers (D-064).

    Section 16.4 writes four probabilities and four payoff multipliers as
    literals. They move here for the usual reason, and this block carries an
    **extra** one: the four probabilities are **not independently settable**.
    Each is either ``base`` or ``(1 - base) * share``, so they sum to exactly 1
    only when the three ``remaining_share`` leaves sum to 1 — **one constraint
    across three leaves, which no leaf can carry alone** (O-41's shape). The
    constraint is asserted in :meth:`_remaining_shares_must_sum_to_one` rather
    than left to the arithmetic, because a reader who moves one leaf has no way
    to see that it moved the other three.

    Every probability here is ``uncalibrated_illustrative``, which is what
    Section 16.4 says of them — they are not estimates.
    """

    model_config = ConfigDict(extra="forbid")

    base_probability_high: CalibratedValue
    base_probability_medium: CalibratedValue
    base_probability_low: CalibratedValue
    remaining_share_partial_close: CalibratedValue
    remaining_share_reversal: CalibratedValue
    remaining_share_tail: CalibratedValue
    payoff_multiple_base: CalibratedValue
    payoff_multiple_partial_close: CalibratedValue
    payoff_multiple_reversal: CalibratedValue
    payoff_multiple_tail: CalibratedValue
    percent_to_bp: CalibratedValue

    @property
    def base_probabilities(self) -> dict[str, float]:
        """Base-case probability per **distributable** convergence verdict.

        Only ``HIGH``/``MEDIUM``/``LOW`` appear. ``CONFLICTED`` and
        ``NO_SIGNAL`` are absent **by design**: Section 16.4's ``else`` branch
        assigns both the LOW value, and a thesis cannot be built on either —
        ``MacroThesis`` hard-blocks a live trade on ``CONFLICTED`` (Section
        22.10), and ``NO_SIGNAL`` means every pillar read neutral, so there is
        nothing to distribute. Absence here is what makes that a partition
        rather than a fall-through.
        """
        return {
            "HIGH": float(self.base_probability_high.value),
            "MEDIUM": float(self.base_probability_medium.value),
            "LOW": float(self.base_probability_low.value),
        }

    @property
    def remaining_shares(self) -> dict[str, float]:
        """How ``1 - base`` is split across the three non-base branches."""
        return {
            "gap_partially_closes": float(self.remaining_share_partial_close.value),
            "thesis_invalidated_reversal": float(self.remaining_share_reversal.value),
            "tail_adverse_surprise": float(self.remaining_share_tail.value),
        }

    @property
    def payoff_multiples(self) -> dict[str, float]:
        """Each branch's payoff as a multiple of the gap."""
        return {
            "base_case_gap_closes_as_modeled": float(self.payoff_multiple_base.value),
            "gap_partially_closes": float(self.payoff_multiple_partial_close.value),
            "thesis_invalidated_reversal": float(self.payoff_multiple_reversal.value),
            "tail_adverse_surprise": float(self.payoff_multiple_tail.value),
        }

    @property
    def bp_per_percent(self) -> float:
        """Basis points in one percent. Definitional; stated so it cannot drift."""
        return float(self.percent_to_bp.value)

    @model_validator(mode="after")
    def _remaining_shares_must_sum_to_one(self) -> ScenarioDistributionSettings:
        """The one constraint three leaves share.

        Without this the four published probabilities sum to
        ``base + (1 - base) * S`` where ``S`` is the shares' sum — and ``S != 1``
        is **invisible in every leaf** while making the distribution invalid.
        ``MacroThesis`` would then raise a sum-to-one error whose message points
        at the probabilities, none of which is the leaf that moved.
        """
        total = sum(self.remaining_shares.values())
        tolerance = 1e-9
        if abs(total - 1.0) > tolerance:
            raise ValueError(
                f"scenario_distribution.remaining_share_* sum to {total!r}, not 1. "
                f"They are the split of (1 - base_probability) across the three "
                f"non-base branches, so their sum IS the total probability of the "
                f"non-base case. With S != 1 the four published probabilities do "
                f"not sum to 1 and no single leaf shows why."
            )
        return self


class CatalystCalendarSettings(BaseModel):
    """Module 13-adjacent — the forward catalyst calendar (D-065).

    Section 16.4 writes the CPI/NFP/PCE release ids and the FOMC source as
    prose, and the release ids are **not** durable: FRED renumbers releases, and
    a wrong ``rid`` does not error — it returns a *different* release's dates
    under the configured label. Measured while probing: ``rid=101`` is
    *"FOMC Press Release"*, which returns a row for **every calendar day**, so a
    reader that trusted the label would report the next FOMC as *tomorrow*,
    forever. The ids therefore live here with the release *name* each must
    return, and :func:`macro_engine.thesis_layer.catalysts.next_catalyst_calendar`
    warns when the name and the id disagree.
    """

    model_config = ConfigDict(extra="forbid")

    cpi_release_id: CalibratedValue
    nfp_release_id: CalibratedValue
    pce_release_id: CalibratedValue
    horizon_days: CalibratedValue
    http_timeout_seconds: CalibratedValue

    @property
    def cpi_id(self) -> int:
        """FRED release id for the Consumer Price Index (measured: 10)."""
        return int(self.cpi_release_id.value)

    @property
    def nfp_id(self) -> int:
        """FRED release id for the Employment Situation (measured: 50)."""
        return int(self.nfp_release_id.value)

    @property
    def pce_id(self) -> int:
        """FRED release id for Personal Income and Outlays (measured: 54)."""
        return int(self.pce_release_id.value)

    @model_validator(mode="after")
    def _release_ids_must_be_distinct(self) -> CatalystCalendarSettings:
        """Two catalysts pointing at one release would publish it twice.

        Not a hypothetical: the three ids are three bare integers, and a
        copy-paste that leaves two of them equal produces a calendar with a
        duplicate entry and a *missing* catalyst, with nothing in either leaf
        showing which one moved.
        """
        ids = {
            "cpi_release_id": self.cpi_id,
            "nfp_release_id": self.nfp_id,
            "pce_release_id": self.pce_id,
        }
        if len(set(ids.values())) != len(ids):
            raise ValueError(
                f"catalyst_calendar release ids must be distinct, got {ids!r}. "
                f"Two catalysts sharing one release id publish the same dates "
                f"twice and drop a catalyst, and no single leaf shows which."
            )
        return self


class InvalidationSettings(BaseModel):
    """Module 14 — what falsifies a thesis (D-063).

    Section 20.15's sample writes its crossing level as the literal ``< 0``
    twice and its agreement band as the string ``"reverses positive"`` inside a
    prose condition. Both move here so the sign convention is stated once.

    The interesting leaf is :attr:`supporting_agreement_class`, because it
    records a limit rather than a choice: ``inflation_convergence_classifier``
    reports agreement **strength**, not direction, so the falsifier it can
    support is an agreement *collapse* — not the "broad-based reacceleration"
    Section 20.15 attributes to it. See the ``invalidation:`` block in
    ``config/settings.yaml``.
    """

    model_config = ConfigDict(extra="forbid")

    zero_crossing_threshold: CalibratedValue
    supporting_agreement_class: CalibratedValue

    @property
    def crossing(self) -> float:
        """The level a signed signal must cross back over to falsify a thesis.

        Zero, and **definitional rather than chosen**: it is the models' own
        balance point, stated in their own contexts. It is a config leaf so the
        crossing is written once and the sign convention cannot drift.
        """
        return float(self.zero_crossing_threshold.value)

    @property
    def agreement_class_supporting_a_thesis(self) -> str:
        """The convergence verdict a thesis may rest on, as a plain string."""
        return str(self.supporting_agreement_class.value)


class InstrumentSelectionSettings(BaseModel):
    """Module 15 / 16.4 — the thesis-type → instrument routing table.

    Section 22.3.1 writes this as an ``if/elif`` chain with the instrument
    strings inline. Section 21 prohibits a literal in a model, and the reason
    is concrete here: which instrument expresses a policy-path gap is a **desk
    convention**, and re-expressing a view should not require a code change.

    The one piece of genuine arithmetic is the curve-leg separation check
    (:attr:`curve_minimum_leg_gap_years`), because Section 22.3.1's f-string
    accepted ``"2y/2y"`` — a steepener whose legs are the same point on the
    curve (D-058 probe P7).
    """

    model_config = ConfigDict(extra="forbid")

    thesis_type_routes: dict[str, Any]
    curve_default_short_tenor: CalibratedValue
    curve_default_long_tenor: CalibratedValue
    curve_minimum_leg_gap_years: CalibratedValue
    curve_maximum_leg_years: CalibratedValue
    is_heuristic_not_calibrated: CalibratedValue
    source_independence_count: CalibratedValue

    @property
    def routes(self) -> dict[str, dict[str, str]]:
        """The routing table, with the envelope's own metadata stripped out.

        ``thesis_type_routes`` is a ``mechanical_rule`` envelope carrying a
        ``calibration_status`` and a ``note`` beside its ``routes`` mapping.
        Returning only the mapping keeps the caller from having to know the
        envelope's shape, and means a future note edit cannot break the model.
        """
        raw = self.thesis_type_routes.get("routes")
        if not isinstance(raw, dict):
            raise ValueError(
                "instrument_selection.thesis_type_routes.routes is missing or not a "
                "mapping — the routing table cannot be read."
            )
        return {str(key): dict(value) for key, value in raw.items()}

    @property
    def default_short_tenor(self) -> str:
        return str(self.curve_default_short_tenor.value)

    @property
    def default_long_tenor(self) -> str:
        return str(self.curve_default_long_tenor.value)

    @property
    def minimum_leg_gap_years(self) -> float:
        return float(self.curve_minimum_leg_gap_years.value)

    @property
    def maximum_leg_years(self) -> float:
        return float(self.curve_maximum_leg_years.value)

    @property
    def heuristic_not_calibrated(self) -> bool:
        return bool(self.is_heuristic_not_calibrated.value)

    @property
    def independence_count(self) -> int:
        return int(self.source_independence_count.value)


class RiskSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_vol_annualized: CalibratedValue
    stress_correlation: CalibratedValue
    var_confidence_levels: CalibratedValue
    historical_var_lookback_days: CalibratedValue
    drawdown_thresholds: dict[str, Any]
    rebalancing_drift: CalibratedValue
    # Module 17.2's hard constraints (Section 17.3's `RiskLimits`). These were
    # literals inside a Pydantic class body in the specification, which
    # Section 21 prohibits; they live here so a policy change is a config
    # change. See `RiskLimits` in `portfolio/risk_budget.py` for the mapping.
    max_position_pct_of_portfolio: CalibratedValue
    max_factor_exposure_pct: CalibratedValue
    max_leverage: CalibratedValue
    min_liquidity_days_to_unwind: CalibratedValue
    vol_target_reflexivity_scale: CalibratedValue
    # Module 17.1's risk-budgeted weight construction (Section 9.2). The
    # optimiser's numerical settings are calibration, not code: Section 21
    # keeps them out of the function body so a change to the convergence
    # standard is a reviewable diff rather than an edit to the algorithm.
    #
    # `_value`-suffixed, unlike the leaves above, because the reader property
    # is named for the *quantity* the caller wants (`risk_parity_tolerance`)
    # and the field is named for the *envelope* it is stored in. Two leaves in
    # one class cannot share a name, and the caller-facing name is the one
    # consumers type.
    risk_parity_annualization_periods_value: CalibratedValue
    risk_parity_tolerance_value: CalibratedValue
    risk_parity_stress_shift_threshold_value: CalibratedValue
    # Section 17.4's feedback loop — the ONLY rule in the specification that
    # carries a risk-layer finding back into the thesis LIFECYCLE. `_value`-
    # suffixed because the reader is named for the quantity the caller wants.
    thesis_demotion_fraction_value: CalibratedValue

    @property
    def vol_target(self) -> float:
        return float(self.target_vol_annualized.value)

    @property
    def rebalancing_drift_threshold(self) -> float:
        """Risk-budget drift tolerance as a **fraction** (``0.10`` = 10%).

        Section 15.18's ``drift_threshold_pct`` default is ``0.10``, and the
        name says ``_pct`` while the value is a fraction — the same suffix
        ambiguity that produced D-054's 100x error one function over. Here the
        value's *magnitude* resolves it (a 0.1% drift tolerance would fire on
        every real book), so the convention is stated on the reader and the
        field is bounded, because a magnitude argument is not a contract.
        """
        return float(self.rebalancing_drift.value)

    @property
    def max_position_fraction(self) -> float:
        """Largest single position as a **fraction** (``0.15`` = 15%).

        Section 17.3 names the field ``max_position_pct_of_portfolio`` and
        defaults it to ``0.15`` -- a **fraction** despite the ``_pct`` suffix,
        which is the same suffix ambiguity that produced D-054's 100x error and
        D-055's unstated unit. The suffix is kept because it is the
        specification's field name; the *convention* is stated here and is
        enforced by ``_reject_percent_in_fraction_field`` below, because a
        stated convention is not a contract.
        """
        return float(self.max_position_pct_of_portfolio.value)

    @property
    def max_factor_exposure_fraction(self) -> float:
        """Largest single-PCA-factor exposure as a **fraction** (``0.30`` = 30%)."""
        return float(self.max_factor_exposure_pct.value)

    @property
    def max_leverage_multiple(self) -> float:
        """Gross exposure ceiling as a **multiple of capital** (``3.0`` = 3x).

        Unambiguous -- there is no ``_pct`` suffix and the unit is a ratio of
        two exposures, so no scale error is representable.
        """
        return float(self.max_leverage.value)

    @property
    def min_liquidity_days(self) -> int:
        """Days to unwind. Integer; a fractional day is not representable."""
        return int(self.min_liquidity_days_to_unwind.value)

    @property
    def reflexivity_scale_threshold(self) -> float:
        """Scale below which Module 17.2's reflexivity warning fires.

        Section 20.13 writes ``raw_scale < 0.8`` as a literal in the function
        body. It is a *policy* number -- the point at which simultaneous
        de-risking is judged systemically relevant -- so it belongs here.
        """
        return float(self.vol_target_reflexivity_scale.value)

    @property
    def stress_corr(self) -> float:
        return float(self.stress_correlation.value)

    @property
    def var_levels(self) -> list[float]:
        raw = self.var_confidence_levels.value
        return [float(x) for x in raw]

    @property
    def var_lookback_days(self) -> int:
        return int(self.historical_var_lookback_days.value)

    @property
    def risk_parity_annualization_periods(self) -> int:
        """Trading days per year for the risk-parity covariance annualisation.

        **This must agree with ``realized_vol_simple`` and with the vol-target
        block.** If the risk budget annualised at 260 and the vol target at
        252, the same book would carry two volatilities for the same
        instrument and the drift between them would look like signal. The
        agreement is asserted by tests rather than left to convention.
        """
        return int(self.risk_parity_annualization_periods_value.value)

    @property
    def risk_parity_tolerance(self) -> float:
        """Absolute convergence tolerance on the risk-contribution shares.

        Checked as ``max |RC_i - b_i|`` where the RC shares sum to 1.0, so an
        *absolute* tolerance is well-scaled and a relative one would need a
        denominator that is itself near zero for a small-budget instrument.
        """
        return float(self.risk_parity_tolerance_value.value)

    @property
    def risk_parity_stress_shift_threshold(self) -> float:
        """Largest single-weight move, as a **fraction of notional**, that is
        tolerated before the correlated-stress result escalates to a warning.

        ``0.025`` means 2.5 percentage points of the book, not 2.5% of the
        instrument's own weight. A relative test would fire spuriously on a
        small-budget leg (a 2% weight moving to 4% is a doubling but
        immaterial), so the test is absolute and stated as such.

        **The shipped value was first written as 0.05 and that made the branch
        dead code.** Measured on the live 5-ETF book, the largest single-leg
        shift under ``rho = 0.9`` ranges 1.40%..5.75% across lookbacks of
        126..1260 sessions with a median of 5.22%, so a 5% threshold sat above
        the median and never fired. The range is recorded in ``settings.yaml``;
        the point here is that the accessor's value is a *measured* breakpoint,
        not a round number.
        """
        return float(self.risk_parity_stress_shift_threshold_value.value)

    @property
    def thesis_demotion_fraction(self) -> float:
        """Section 17.4's "near-zero" bound, as a **fraction of capital**.

        ``0.03`` means 3% of capital, not 3 percentage points of some other
        quantity and not a relative test. Section 17.4 requires a live thesis
        whose proposed notional clips to "near-zero" to be demoted from
        ``CANDIDATE`` back to ``WATCH``, and "near-zero" is the only
        unquantified word in the rule — so it is the one thing that belongs
        here rather than in a function body.

        **The structure of the rule gives three bounds, and the third was
        found by measurement rather than by reading.** The first draft used
        ``0.02`` and satisfied the first two while never firing:

        * **Below the position cap.** ``max_position_fraction`` is ``0.15``. A
          demotion threshold at or above the cap would demote *every* thesis
          that reached the sizing path, which is not a risk judgement but a
          broken rule — and because the resulting status is a legal value, it
          would look like a policy rather than a bug.
        * **Strictly positive.** A threshold of zero can never fire, which
          makes Section 17.4 a declaration with no consumer — the
          declared-consumed-unreachable class this project has recorded eight
          times (D-045/D-046/D-048, O-53, and twice inside D-072 itself).
        * **Above the smallest reachable size.** Being positive is not enough:
          the published fraction is **not continuous**, so a bound can be
          positive, below the cap, and still beneath every value the sizing
          path can produce. Full Kelly is the argmax of expected log growth,
          and for a binary bet with a positive edge that objective is
          monotone, so ``f*`` pins at the domain edge and the published number
          becomes the cap; only a few asymmetric sets land strictly inside.
          The reachable published fractions on this configuration are

              ``0.02941  0.03472  0.042735  0.069445  0.125  0.15``

          so the smallest positive size is ``0.02941`` and any bound below it
          never fires. This is measured, and reprinted, by
          ``scripts/live_risk_axis_check.py``.

        All three bounds are asserted by tests against the *other* leaves and
        against the measured range rather than against literals, so a future
        change to the cap or to the Kelly divisor moves the constraint with it.
        """
        return float(self.thesis_demotion_fraction_value.value)

    @property
    def drawdown_tiers(self) -> list[DrawdownTier]:
        """Drawdown tiers, sorted ascending by trigger level.

        **These are PERCENTS, not fractions** — ``drawdown_pct: 10.0`` in
        ``settings.yaml`` means "a 10% drawdown". Section 6.6c's
        ``DrawdownRule`` uses fractions (``0.10``), so a consumer that reads
        this accessor must divide by 100. The conversion lives at exactly one
        boundary — ``portfolio/risk_budget.py``'s ``_tiers()`` — because two
        conventions for one quantity is how a 100x error becomes invisible: the
        number ``10.0`` is a legal percent and an impossible fraction, and only
        a bound can tell them apart.

        The accessor sorts rather than returning the YAML order: the rules are a
        set keyed by severity, and §6.6c's "evaluated in order" prose does not
        mean the file's order is load-bearing (it is not — the result is
        invariant under permutation).
        """
        raw = self.drawdown_thresholds.get("tiers", [])
        tiers = [DrawdownTier.model_validate(t) for t in raw]
        return sorted(tiers, key=lambda t: t.drawdown_pct)

    @model_validator(mode="after")
    def _reject_percent_in_fraction_field(self) -> RiskSettings:
        """Refuse a **percent** written into a **fraction** field (Section 21).

        Three leaves in this block carry the ``_pct`` suffix and hold
        **fractions** (``0.15``). A reader who writes ``15.0`` has made a 100x
        error, and unlike D-054's ladder the failure is *not* silence: a 1500%
        position limit is simply never reached, so the constraint becomes
        inert and every sizing decision looks compliant.

        A magnitude guard is what makes the convention **checkable at load
        time**. Without it the only thing distinguishing ``0.15`` from ``15.0``
        is a comment, and ``float`` accepts both. The bound is ``<= 1.0``
        rather than ``< 1.0`` because ``1.0`` is a legal limit (a book that may
        be fully concentrated in one position) and refusing it would make a
        real policy unrepresentable.

        **This is deliberately NOT applied to ``max_leverage``**: ``3.0`` is a
        legal multiple and a legal-looking percent, so a magnitude test would
        reject the shipped value. The unit is unambiguous there because the
        suffix and the magnitude agree.
        """
        for name, value in (
            ("max_position_pct_of_portfolio", self.max_position_fraction),
            ("max_factor_exposure_pct", self.max_factor_exposure_fraction),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(
                    f"risk.{name} is {value}, which is outside (0, 1]. These "
                    f"leaves are FRACTIONS (0.15 = 15%), not percents — a value "
                    f"above 1.0 is a percent written into a fraction field, and "
                    f"it would leave the limit permanently unreachable rather "
                    f"than failing loudly (the D-054 pattern)."
                )
        if self.max_leverage_multiple < 1.0:
            raise ValueError(
                f"risk.max_leverage is {self.max_leverage_multiple}. Gross "
                f"exposure below 1.0x is a net-cash book, not a leverage limit."
            )
        if self.min_liquidity_days < 0:
            raise ValueError(
                f"risk.min_liquidity_days_to_unwind is {self.min_liquidity_days}; "
                f"a negative unwind horizon is not a constraint."
            )
        return self

    @model_validator(mode="after")
    def _validate_var_levels(self) -> RiskSettings:
        for level in self.var_levels:
            if not 0.5 < level < 1.0:
                raise ValueError(
                    f"VaR confidence level {level} is outside the sensible range (0.5, 1.0)."
                )
        return self


class RegistrySeries(BaseModel):
    """One entry in ``series_registry.yaml``."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    endpoint: str | None = None
    symbol: str | None = None
    tenors: dict[str, str] | None = None
    description: str = ""
    frequency: str | None = None
    units: str | None = None
    seasonality: str | None = Field(
        default=None,
        description=(
            "Stated when this series' seasonal adjustment differs from a series it is "
            "routinely compared against. GDPPOT is NOT seasonally adjusted while GDPC1 is "
            "SAAR (verified on FRED 2026-09-16), and that difference is invisible in the "
            "values themselves — a reader comparing the two would have no way to know. "
            "Recording it makes the mismatch a documented limitation rather than a "
            "latent trap."
        ),
    )
    status: str = "unverified"
    snapshot_field: str | None = Field(
        default=None,
        description=(
            "Name of the attribute on MacroDataSnapshot this entry populates, when it "
            "differs from the registry key. The two genuinely do differ in places — the "
            "registry key 'treasury_curve' populates the schema field 'yield_curve' — and "
            "an implicit assumption that they always match silently dropped the entire "
            "Treasury curve from the first live snapshot build. Declaring the mapping "
            "makes the difference visible in config rather than buried in code."
        ),
    )
    decision_note: str | None = Field(
        default=None,
        description=(
            "Present when this entry's route deviates from Section 21.1 as written. "
            "Records why, so a reader of the registry alone can see the provenance "
            "without opening docs/DECISIONS.md."
        ),
    )
    forward_looking: bool = Field(
        default=False,
        description=(
            "True when the published series legitimately extends beyond today because its "
            "values are projections, not measurements. FRED GDPPOT (CBO potential output) "
            "is the canonical case: it carries roughly a decade of forward estimates, and "
            "those estimates are required for the output-gap calculation. Marking this "
            "keeps the future-dating validator from flagging ~41 legitimate points as ERROR "
            "on every snapshot."
        ),
    )
    not_a_snapshot_field: bool = Field(
        default=False,
        description=(
            "True when this entry documents a MODEL's input provenance rather than "
            "populating MacroDataSnapshot. Module 7.3's four leading-indicator components "
            "(claims, building permits, the 10y3m slope, the S&P 500) are fetched by the "
            "model's own live check and have no snapshot field. Without this flag they "
            "resolve to their own key via the ``snapshot_field or field_name`` fallback and "
            "fail ``_assert_field_exists`` — a confusing failure for an entry that was "
            "never meant to be in the snapshot. Declaring it makes the intent explicit and "
            "the failure message accurate."
        ),
    )
    signed_series: bool = Field(
        default=False,
        description=(
            "True when this series' snapshot field legitimately carries a SIGNED quantity "
            "(a spread, a change, a net balance) rather than a non-negative level. "
            "`plausible_range` describes the LEVEL, and the range check treats a breach as "
            "an ERROR — so for a signed field the level range must not be applied as a hard "
            "lower bound, or a legitimate negative value (a narrowing spread, a net "
            "tightening reading of -2%) is reported as corrupt data. "
            "`credit_spread_hy`/`credit_spread_ig` are the canonical cases: the OAS LEVEL "
            "has never been negative in the full FRED history (verified 2026-09-19: BAMLH0A0HYM2 "
            "ranges 2.59 to 4.61 over 795 observations), so [0.1, 40.0] is a correct LEVEL "
            "bound — but the same field is used to carry a spread CHANGE, and a change is "
            "legitimately negative. Declaring the field signed keeps the LEVEL range "
            "documented and authoritative while suppressing the lower-bound ERROR. "
            "This replaces the four hardcoded series tuples that used to live in "
            "validation.py (AUDIT-001)."
        ),
    )
    future_date_tolerance_days: int = Field(
        default=0,
        ge=0,
        le=7,
        description=(
            "How many calendar days a published observation may post-date the retrieval "
            "date before the future-dating validator treats it as a fault. Zero is correct "
            "for a series published with a lag (monthly, quarterly, or any daily series "
            "whose provider settles after the fact). A value of 1 is correct for a DAILY "
            "series whose provider publishes the same calendar day that the process clock "
            "is still on the previous UTC date — FRED's IORB does this, and D-030 recorded "
            "three separate occurrences of `iorb @<tomorrow>: FUTURE_OBSERVATION_DATE` "
            "before this was made a declared property of the series rather than a "
            "standing test failure."
        ),
    )
    verified_on: date | None = Field(
        default=None,
        description=(
            "Date on which this route was confirmed against live data (Section 21.0 rule 5)."
        ),
    )
    verified_value: float | None = Field(
        default=None,
        description=(
            "The value observed at verification time — the recorded evidence for `verified_on`."
        ),
    )
    verified_observation_date: date | None = Field(
        default=None,
        description=(
            "The observation date `verified_value` belongs to. Required for any series "
            "whose values span a range of dates with different meanings — for a "
            "forward_looking series, `verified_value` MUST be the latest REALISED "
            "observation, never the last point in the published series. Recording a "
            "decade-ahead projection as a verification value satisfies Section 21.0 rule 5 "
            "in letter and defeats it in purpose: it asserted potential GDP of ~29,443 "
            "when the current realised figure was 24,070.94 (DECISIONS.md D-010)."
        ),
    )
    verified_curve: dict[str, Any] | None = Field(
        default=None,
        description=(
            "For multi-leg (curve) entries: the observed value at EVERY leg. A single "
            "leg does not evidence the route, because any tenor could be mis-mapped "
            "while the leg chosen as evidence looks correct. For a forward_looking "
            "single series, this instead records the series' SHAPE — where the realised "
            "block ends and the projection block begins — which is the structure every "
            "consumer must understand to use it correctly."
        ),
    )
    plausible_range: tuple[float, float] | None = Field(
        default=None,
        description=(
            "Optional (min, max) plausibility bounds for the series level. Used by "
            "tools/manual_series_check.py to distinguish a working connection with a "
            "broken mapping (millions of zeros) from a genuinely working route."
        ),
    )

    @model_validator(mode="after")
    def _require_a_resolution_path(self) -> RegistrySeries:
        if self.symbol is None and not self.tenors:
            raise ValueError(
                "Registry entry must define either 'symbol' or 'tenors' to be resolvable."
            )
        if self.plausible_range is not None:
            low, high = self.plausible_range
            if low >= high:
                raise ValueError(
                    f"plausible_range {self.plausible_range} is not an increasing interval."
                )
        return self

    @model_validator(mode="after")
    def _verified_requires_evidence(self) -> RegistrySeries:
        """Section 21.0 rule 5: real-data validation must be RECORDED.

        A bare `status: verified` is an unbacked claim. Requiring the date and
        the observed value makes the claim checkable and makes it impossible to
        flip a series to verified as a shortcut to unblock a downstream model.
        """
        if self.status.startswith("verified"):
            if self.verified_on is None or self.verified_value is None:
                raise ValueError(
                    f"series '{self.symbol or self.tenors}' is marked '{self.status}' but "
                    "records no verified_on / verified_value evidence. Section 21.0 rule 5 "
                    "requires the retrieved value and retrieval date to be recorded."
                )
            if self.plausible_range is not None:
                low, high = self.plausible_range
                if not (low <= self.verified_value <= high):
                    raise ValueError(
                        f"series '{self.symbol}' verified_value {self.verified_value} falls "
                        f"outside its declared plausible_range {self.plausible_range}. The "
                        "bounds and the observation disagree — one of them is wrong."
                    )
        return self

    @model_validator(mode="after")
    def _forward_looking_evidence_must_be_a_realised_observation(self) -> RegistrySeries:
        """DECISIONS.md D-010, made structural.

        The defect D-010 records was accepted by `_verified_requires_evidence`
        because a Q4 2036 projection sits comfortably inside
        ``plausible_range: [1000, 100000]``. The bounds check answers "is this
        value plausible for this series", which is not the same question as "is
        this value the observation this series' verification should record".

        Two requirements close the gap for the one case where the distinction is
        both consequential and mechanically checkable:

        * A ``forward_looking`` series must declare ``verified_observation_date``
          — the date its evidence belongs to. Without it, nothing in the entry
          distinguishes a realised observation from a projection.
        * That date must lie within the *realised* block. ``verified_curve``
          records where the projection block begins (``projection_block_starts``),
          so the check is a direct comparison rather than a guess.

        This is deliberately narrow. It cannot validate the verification value
        for the ~20 ordinary series, where "the right observation" is a semantic
        judgement rather than a comparison. It does mean the specific error this
        project actually made cannot be re-entered silently.
        """
        if not self.status.startswith("verified") or not self.forward_looking:
            return self

        if self.verified_observation_date is None:
            raise ValueError(
                f"series '{self.symbol}' is marked forward_looking and verified, but records "
                "no verified_observation_date. For a series that mixes measurement with "
                "projection, the evidence value is meaningless without the date it belongs to "
                "(DECISIONS.md D-010)."
            )

        if self.verified_curve is not None:
            block_start = self.verified_curve.get("projection_block_starts")
            if isinstance(block_start, str):
                block_start = date.fromisoformat(block_start)
            if isinstance(block_start, date) and self.verified_observation_date >= block_start:
                raise ValueError(
                    f"series '{self.symbol}' records verified_observation_date "
                    f"{self.verified_observation_date}, which falls inside its own projection "
                    f"block (starts {block_start}). A projection is not evidence that the "
                    f"series carries a current value (DECISIONS.md D-010)."
                )
        return self


class BlockedSeries(BaseModel):
    """A Loophole Ledger entry (Section 21.4). Exists so failures are loud."""

    model_config = ConfigDict(extra="forbid")

    field: str
    reason: str
    opened_in: str = "OPEN_ISSUES.md"


class ReleaseCalendar(BaseModel):
    """The Section 6 release-date lookup, declared in config not code.

    Section 6 names four timestamps that are NOT interchangeable —
    ``observation_date``, ``release_datetime``, ``vintage_datetime`` and
    ``retrieved_at`` — and only the first and last are always available. This
    block is the route for the second.

    **Why it exists at all.** ``ObservationPoint.release_datetime`` was modelled
    and left ``None`` on the finding that no reachable route returns it. That
    finding was half wrong: ``economy.calendar`` was tried with ``provider=fred``
    only (which times out), when the endpoint accepts four providers and
    ``nasdaq`` works. See ``config/series_registry.yaml``'s ``release_calendar``
    comment for the full evidence.

    **Why it is opt-in and honest about failure.** The working route is
    INTERMITTENT (measured 2026-09-20: 2 of 4 identical calls succeeded). So the
    contract is: read it, retry it, and when it cannot be read leave
    ``release_datetime`` as ``None``. A scheduled date is never written in place
    of a released one, because those are different facts and Section 6's whole
    point is that a consumer can tell them apart.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Off by default. Enabling it makes every snapshot build issue a "
            "calendar request, whose route is intermittent — so a caller opts in "
            "rather than having the flakiness imposed."
        ),
    )
    provider: str = "nasdaq"
    endpoint: str = "economy.calendar"
    max_attempts: int = Field(
        default=5,
        gt=0,
        description=(
            "Attempts for THIS route, separate from the series client's retry "
            "budget. Its failure mode is a fast empty response, not a timeout, "
            "so more attempts at a shorter backoff is the right shape."
        ),
    )
    backoff_seconds: float = Field(default=1.5, ge=0.0)
    window_days_back: int = Field(default=400, gt=0)
    window_days_forward: int = Field(default=45, ge=0)
    event_map: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Provider event name -> registry series key. The provider publishes "
            "HUMAN-READABLE names ('Core PCE Price Index'), not FRED symbols, so "
            "this join cannot be derived and must be declared."
        ),
    )


class PublicationDates(BaseModel):
    """Per-series publication timestamps read from series metadata.

    Section 6's **exact** route for ``release_datetime``, and the one that
    supersedes ``ReleaseCalendar`` as the primary source.

    **Why a second source exists.** ``release_calendar`` fills a release date by
    joining a *scheduled events calendar* to a series through a hand-written
    event-name map. That join is indirect and lossy: it only covers series whose
    release appears as a named event, and the map must be maintained by hand. It
    then turned out to be served by a route that is intermittent and currently
    edge-blocked (see ``release_calendar.py``).

    This source is direct. Every FRED series carries ``last_updated`` in its own
    metadata — the instant the source last wrote that series. It needs no event
    map, no join, and no scheduled-date inference: the provider states the
    publication time on the record itself.

    **Verified live 2026-09-20** — 42 of 42 registry symbols returned a
    ``last_updated``, 0 transport errors:

        GET /api/v1/economy/fred_search
            ?provider=fred&query=<SYMBOL>&search_type=series_id&limit=1000
        -> results[0].last_updated = "2026-09-11T08:37:49-05:00"   # CPIAUCSL

    Cross-validated against the calendar source: ``PCEPILFE`` reported
    ``last_updated`` 2026-08-26 where the events calendar dated the Core PCE
    release 2026-08-27 — a one-day gap consistent with a release date versus a
    write timestamp, which is exactly the distinction Section 6 draws.

    **This is NOT a vintage.** ``fred_search`` also returns ``realtime_start``
    and ``realtime_end``, but for every series both equal *today*: they describe
    the vintage window in force now, not which revisions existed in the past.
    Passing ``realtime_start`` as a query parameter is silently ignored (A/B
    tested: the response differed only in request ``timestamp``/``duration``).
    So this route populates ``release_datetime`` and **cannot** populate
    ``vintage_datetime``, which remains ALFRED-only and unreachable here.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "On by default, unlike `release_calendar`: this route is working and "
            "has full registry coverage, so it is the accurate source rather "
            "than an opportunistic one. It costs one request per resolved "
            "series, so a caller that wants a build with no metadata traffic "
            "can disable it."
        ),
    )
    provider: str = "fred"
    endpoint: str = "economy.fred_search"
    search_type: str = Field(
        default="series_id",
        description=(
            "The provider's search mode. 'series_id' is REQUIRED for exact "
            "lookup: 'full_text' does not reliably surface an exact symbol "
            "(verified — a 100-row full-text search for 'Unemployment Rate' "
            "did not contain UNRATE), so using it would silently drop series."
        ),
    )
    limit: int = Field(
        default=1000,
        gt=0,
        description=(
            "'series_id' search is a PREFIX match, so an exact symbol can be "
            "crowded out by longer siblings within the limit (UNRATE lost to "
            "UNRATECTH/UNRATECTL at limit=5). A high limit is how the exact row "
            "is reached; the reader still discards everything but an exact "
            "series_id match, so a large limit costs bandwidth, not correctness."
        ),
    )
    max_attempts: int = Field(default=3, gt=0)
    backoff_seconds: float = Field(default=1.0, ge=0.0)


class SeriesRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    defaults: dict[str, Any]
    series: dict[str, RegistrySeries]
    blocked: list[BlockedSeries] = Field(default_factory=list)
    release_calendar: ReleaseCalendar = Field(default_factory=ReleaseCalendar)
    publication_dates: PublicationDates = Field(default_factory=PublicationDates)

    @model_validator(mode="after")
    def _apply_defaults_to_series(self) -> SeriesRegistry:
        """Apply the ``defaults:`` block to every entry that omits a key.

        The registry declares a shared provider route once, so that ~20 series
        do not each repeat ``provider: fred``. That only works if something
        actually performs the inheritance — otherwise ``endpoint`` stays
        ``None`` on every scalar entry and each fetch fails with "no endpoint
        configured".

        This was found by live execution, not by unit tests: the config parsed
        fine and the entries looked correct, because the values were present in
        the file, just not on the objects. Section 21.0 rule 1 again.

        An entry that explicitly sets a key always wins, so a series can
        override the shared route without leaving the pattern.
        """
        for name, entry in self.series.items():
            updates: dict[str, Any] = {}
            for key in ("provider", "endpoint"):
                current = getattr(entry, key, None)
                if current is None and key in self.defaults:
                    updates[key] = self.defaults[key]
            if updates:
                self.series[name] = entry.model_copy(update=updates)
        return self

    def require_verified(self, field_name: str) -> RegistrySeries:
        """Return a series entry, refusing anything not verified in Phase 0.

        This is the enforcement point for Section 21.1's Phase 0 discipline.
        An entry present in the registry but not yet verified raises — the
        alternative is a fetch that returns empty and is silently treated as
        "no data available", which is indistinguishable from a real outage.
        """
        if field_name not in self.series:
            blocked = {b.field: b for b in self.blocked}
            if field_name in blocked:
                raise NotImplementedError(
                    f"'{field_name}' is BLOCKED with no reachable source: "
                    f"{blocked[field_name].reason} (tracked in {blocked[field_name].opened_in})"
                )
            raise KeyError(
                f"'{field_name}' is not defined in series_registry.yaml. "
                f"Section 21.0 rule 3: no input may be invented — define its source first."
            )
        entry = self.series[field_name]
        if not entry.status.startswith("verified"):
            raise NotImplementedError(
                f"'{field_name}' (-> {entry.provider}:{entry.symbol}) has status "
                f"'{entry.status}'. Section 21.1 requires a verified series ID before "
                f"use. Run tools/manual_series_check.py to verify it."
            )
        return entry


class PolicyRuleCoefficients(BaseModel):
    """Section 6.1's rule coefficients and the 22.4 ensemble thresholds."""

    model_config = ConfigDict(extra="forbid")

    taylor_output_gap_coefficient: CalibratedValue
    inflation_gap_coefficient: CalibratedValue
    first_difference_alpha: CalibratedValue
    first_difference_beta: CalibratedValue

    @property
    def taylor_output_gap_coefficient_value(self) -> float:
        return float(self.taylor_output_gap_coefficient.value)

    @property
    def inflation_gap_coefficient_value(self) -> float:
        return float(self.inflation_gap_coefficient.value)

    @property
    def first_difference_alpha_value(self) -> float:
        return float(self.first_difference_alpha.value)

    @property
    def first_difference_beta_value(self) -> float:
        return float(self.first_difference_beta.value)


class PolicyEnsembleThresholds(BaseModel):
    """Dispersion bands that decide whether the rules agree or conflict."""

    model_config = ConfigDict(extra="forbid")

    convergence_threshold_bp: CalibratedValue
    uncertainty_threshold_bp: CalibratedValue
    near_miss_tolerance_bp: CalibratedValue

    @property
    def convergence_threshold_bp_value(self) -> float:
        return float(self.convergence_threshold_bp.value)

    @property
    def uncertainty_threshold_bp_value(self) -> float:
        return float(self.uncertainty_threshold_bp.value)

    @property
    def near_miss_tolerance_bp_value(self) -> float:
        return float(self.near_miss_tolerance_bp.value)


class MarketImpliedPolicySettings(BaseModel):
    """Section 22.5's proxy confidence levels.

    Note these are *not* produced by ``compute_confidence()``. Section 22.5
    states them as literals tied to a specific methodological weakness, not as
    a function of a model's factor states, and the section is an integrated
    ``22.x Resolves Finding`` amendment — so Section 22 governs and the values
    are implemented as written. They live in config rather than in code so the
    deviation is visible and reviewable rather than looking like an oversight.
    """

    model_config = ConfigDict(extra="forbid")

    term_premium_available_confidence: CalibratedValue
    no_term_premium_confidence: CalibratedValue

    @property
    def term_premium_available_confidence_value(self) -> float:
        return float(self.term_premium_available_confidence.value)

    @property
    def no_term_premium_confidence_value(self) -> float:
        return float(self.no_term_premium_confidence.value)


class PolicySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    r_star: CalibratedValue
    pi_target: CalibratedValue
    balanced_approach_output_gap_coefficient: CalibratedValue
    rules: PolicyRuleCoefficients
    ensemble: PolicyEnsembleThresholds
    market_implied: MarketImpliedPolicySettings

    @property
    def pi_target_value(self) -> float:
        return float(self.pi_target.value)

    @property
    def r_star_value(self) -> float:
        return float(self.r_star.value)


class InflationTrajectoryBands(BaseModel):
    """Module 3's three-way split of a *projected inflation change*.

    D-053. The specification compared a quantity on the ``-0.3..+0.3`` **score
    fraction** scale against a bare literal ``0.05``, which made the band's unit
    undecidable and made ``stable`` the base state (measured: 79.1% of months,
    2001-12..2026-07). Both the estimand and the band are named here so the
    ambiguity cannot recur silently.

    ``projected_change_pp`` is the estimand: a change in **annual core
    inflation, in percentage points**, obtained by applying a fitted slope to
    the labor slack term. The bands are therefore in pp, like every other
    inflation quantity in this project.
    """

    model_config = ConfigDict(extra="forbid")

    reaccelerating_above_pp: CalibratedValue
    decelerating_below_pp: CalibratedValue

    @property
    def reaccelerating_above(self) -> float:
        return float(self.reaccelerating_above_pp.value)

    @property
    def decelerating_below(self) -> float:
        return float(self.decelerating_below_pp.value)


class InflationTrajectorySettings(BaseModel):
    """D-053 — ``project_inflation_trajectory``'s bridge and its dead band."""

    model_config = ConfigDict(extra="forbid")

    beta_core_inflation_pp_per_score_point: CalibratedValue
    bands: InflationTrajectoryBands
    fiscal_active_multiplier: CalibratedValue

    @property
    def beta_pp_per_score_point(self) -> float:
        """Percentage points of annual core inflation per labor-score point.

        The unit is in the name because the specification's defect was precisely
        a unit that was not. ``0.5`` would have meant *nothing* without it, and
        neither would ``0.043`` — the two are on different scales.
        """
        return float(self.beta_core_inflation_pp_per_score_point.value)

    @property
    def fiscal_active_scale(self) -> float:
        """Multiplier applied to the projected change when fiscal is active.

        Section 18.6 requires ``project_inflation_trajectory`` to weight the
        fiscal-transfer channel differently from the QE/reserves channel. A
        multiplier rather than a second set of bands, so the direction of the
        adjustment is a single auditable number.
        """
        return float(self.fiscal_active_multiplier.value)


class PhillipsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nairu: CalibratedValue
    beta: CalibratedValue
    trajectory: InflationTrajectorySettings

    @property
    def nairu_value(self) -> float:
        return float(self.nairu.value)

    @property
    def beta_value(self) -> float:
        return float(self.beta.value)


class ProductionFunctionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alpha: CalibratedValue
    productivity_dominance_share: CalibratedValue

    @property
    def alpha_value(self) -> float:
        """Capital share of income. Measurable in the national accounts, which is
        why it is ``conventional`` rather than illustrative."""
        return float(self.alpha.value)

    @property
    def productivity_dominance(self) -> float:
        """Share above which productivity is said to dominate potential growth.

        Section 20.3's ``growth_accounting_decomposition`` warning fires at
        ``> 0.6``. Config-supplied so the threshold is reviewable rather than a
        literal inside the model.
        """
        return float(self.productivity_dominance_share.value)


class InflationPipelineBaseRate(BaseModel):
    """Module 5.4's measured base rates for the PPI stage gradient (see D-029).

    These are the reason ``ppi_pipeline_signal`` reports a probability-like
    figure rather than a bare boolean. The specification presents
    "crude > intermediate > final demand" as if it were a signal; measured on
    this build's own three live series it holds 30.0% of months, so a reader who
    is not told that will over-read the flag.
    """

    model_config = ConfigDict(extra="forbid")

    strict_descending: CalibratedValue
    crude_above_final: CalibratedValue
    stale_after_months: CalibratedValue

    @property
    def strict_descending_rate(self) -> float:
        """P(strictly ordered crude > intermediate > final), measured."""
        return float(self.strict_descending.value)

    @property
    def crude_above_final_rate(self) -> float:
        """P(crude > final), the loosest defensible form of the claim."""
        return float(self.crude_above_final.value)

    @property
    def stale_after(self) -> int:
        """Months after which a stage reading is reported as stale."""
        return int(self.stale_after_months.value)


class GdpGdiBaseRate(BaseModel):
    """Measured frequencies of the GDP/GDI divergence flag (see D-031).

    Same disclosure rule as D-029: a boolean derived from a multi-way
    comparison over a noisy series must travel with its own measured
    frequency, otherwise a reader treats a 21.7%-of-the-time event as if it
    were unusual.

    Declared ahead of ``GdpGdiSettings`` so the settings model can reference it
    directly rather than through a forward-reference string.
    """

    model_config = ConfigDict(extra="forbid")

    significant_at_threshold: CalibratedValue
    gdp_above_gdi: CalibratedValue
    stale_after_quarters: CalibratedValue

    @property
    def significant_rate(self) -> float:
        """P(|divergence| > significance_threshold), measured."""
        return float(self.significant_at_threshold.value)

    @property
    def gdp_above_gdi_rate(self) -> float:
        """P(GDP growth > GDI growth), measured. Near 0.5 by construction."""
        return float(self.gdp_above_gdi.value)

    @property
    def stale_after(self) -> int:
        """Quarters after which a divergence reading is reported as stale."""
        return int(self.stale_after_quarters.value)


class GdpGdiSettings(BaseModel):
    """Module 7.1's thresholds and measured base rates for the GDP/GDI gap.

    Section 20.7 presents ``abs(gdp - gdi) > 1.0`` as a fixed "significance"
    test and calls the divergence a sign that "one dataset is capturing
    something the other misses". Measured against this build's own two live
    series (FRED ``GDP`` and ``GDI``, 314 usable YoY quarters), three parts of
    that framing do not survive contact with the data — see D-031:

    1. The 1.0pp threshold fires 21.7% of the time. That is a usable rate for
       a *flag*, so the threshold is retained, but it is an
       ``uncalibrated_illustrative`` boundary, not a calibrated one.
    2. The **sign** of the divergence carries essentially no information:
       GDP > GDI 47.8% of the time, GDI > GDP 52.2%. The series is mean-zero
       in growth terms (mean -0.009pp, median -0.026pp) because the two are
       two estimates of the same quantity and the discrepancy is a residual.
       A residual's sign is not a finding, so the model reports the magnitude
       and refuses to interpret the direction.
    3. "The average is often the better read" is **false as stated for
       levels** — the level wedge is persistently negative (mean -0.459% of
       GDP across 1947+, negative in seven of nine decades, -1.072% in the
       1980s) because of BEA construction and revision asymmetry. It is true
       only for growth rates. The model therefore labels the average
       explicitly as a growth-average and warns when the wedge is being read
       as a level discrepancy.
    """

    model_config = ConfigDict(extra="forbid")

    significance_threshold_pp: CalibratedValue
    divergence_base_rate: GdpGdiBaseRate
    level_wedge_mean_pct: CalibratedValue

    @property
    def significance_threshold(self) -> float:
        """|GDP - GDI| in percentage points above which the gap is flagged."""
        return float(self.significance_threshold_pp.value)

    @property
    def level_wedge_mean(self) -> float:
        """Measured mean of (GDI - GDP) / GDP in percent — a level artifact."""
        return float(self.level_wedge_mean_pct.value)


class GdpNowcastAccuracy(BaseModel):
    """Measured accuracy of the crude nowcast, and of its benchmark (D-034/D-035).

    The specification's `simple_gdp_nowcast` was written as a placeholder, so
    it carries no accuracy claim and its output publishes none. Measured
    one quarter ahead — the horizon the function actually claims — on 136
    quarters of this build's own live data, the specification's formula
    **anti-correlates** with realised quarterly growth (-0.170) and ties doing
    nothing at all (2.9327pp vs the benchmark's 2.9329pp). That number is the
    single most important thing a consumer of this model can be told, so it is
    a first-class config leaf rather than a sentence in a docstring — it must
    travel with every output and be recomputable by the live check.

    Two sets of figures are recorded because they answer different questions:
    the *specification's* form (what the design would have scored) and the
    *shipped, corrected* form (what this code scores). Keeping only the second
    would hide that the correction was made for a measured reason.

    **Every figure here was recomputed on 2026-09-17 (D-035).** The figures
    first recorded on 2026-09-17 (D-034) were measured on the wrong estimand: a
    cumulative form that credited the model with its whole available window of
    monthly changes rather than the single quarter it nowcasts. That inflation
    produced `mean_abs_error_pp = 7.747` against a true 2.930, and a
    `correlation_with_realised` of +0.108 against a true -0.169. The live
    check's recomputation caught it; the tolerance was not widened. The sign
    of the central finding is unchanged, but the corrected form's margin over
    persistence is 0.003pp rather than the 4.8pp first recorded.
    """

    model_config = ConfigDict(extra="forbid")

    mean_abs_error_pp: CalibratedValue
    persistence_mean_abs_error_pp: CalibratedValue
    correlation_with_realised: CalibratedValue
    spec_form_correlation_with_realised: CalibratedValue
    quarters_measured: CalibratedValue
    realised_positive_rate: CalibratedValue
    delta_overweighting_ratio_value: CalibratedValue
    gdpnow_published_mean_abs_error_pp: CalibratedValue

    @property
    def mean_abs_error(self) -> float:
        """Mean |nowcast - realised| of the corrected form, in percentage points."""
        return float(self.mean_abs_error_pp.value)

    @property
    def persistence_mean_abs_error(self) -> float:
        """Mean |prior_quarter_annualized - realised|, the bar to clear."""
        return float(self.persistence_mean_abs_error_pp.value)

    @property
    def correlation(self) -> float:
        """corr(corrected nowcast, realised SAAR growth) over the measured window."""
        return float(self.correlation_with_realised.value)

    @property
    def spec_form_correlation(self) -> float:
        """corr(specification's form, realised SAAR growth) — the rejected form.

        Negative on this build: the formula the specification supplies moves
        opposite to the quantity it claims to estimate. Recorded so the
        correction cannot be mistaken for a stylistic preference.
        """
        return float(self.spec_form_correlation_with_realised.value)

    @property
    def quarters(self) -> int:
        """Quarters the accuracy figures were measured over."""
        return int(self.quarters_measured.value)

    @property
    def realised_positive_share(self) -> float:
        """Share of measured quarters where realised growth was positive.

        The base rate any "sign agreement" claim must clear. Reported because
        the specification's form agrees on the sign 85.3% of the time, which
        reads as skill until set against this 89.7% — where it becomes worse
        than always predicting growth.

        NOTE the field is named ``realised_positive_rate`` and NOT
        ``realised_positive_share``: a property may not share its own field's
        name. Defining ``share`` as both meant ``self.realised_positive_share``
        inside the property resolved to the property itself, so the accessor
        returned the whole ``CalibratedValue`` envelope and every downstream
        comparison would have compared a float to a model. Pydantic does not
        reject the collision at class-definition time, so this is the
        config-accessor trap this project has now hit four times — caught here
        by reading the value rather than assuming it.
        """
        return float(self.realised_positive_rate.value)

    @property
    def delta_overweighting_ratio(self) -> float:
        """|delta| / |the change delta predicts| — the D-035 finding, corrected.

        The adjustment averages 1.4727pp in absolute value against 2.9153pp of
        quarterly movement, a ratio of **0.5052**: it carries half the magnitude
        of what it predicts. The delta is therefore NOT too small — it is too
        large for how little it knows. ``corr(delta, realised change)`` is
        +0.1727, so the correction fixed the sign, but R^2 is only 0.0298:
        applying a 3%-of-variance signal at full weight adds more noise than
        information, which is why this model scores 0.11pp WORSE than
        persistence.

        **This property was called `delta_inertness_ratio` earlier on
        2026-09-17 and reported 0.005.** That figure was an artefact of
        reconstructing realised growth from ``GDPC1`` with a compounded power
        transform rather than reading ``A191RL1Q225SBEA``, the series the model
        actually consumes; in that sample the annualized monthly percent changes
        came out two orders of magnitude too small. The correction is recorded
        rather than quietly applied, because the wrong value supported a wrong
        conclusion — "the delta is inert" instead of "the delta is over-weighted"
        — and only the second one tells a reader what to do about it.

        NOTE the field is named ``delta_overweighting_ratio_value`` and NOT
        ``delta_overweighting_ratio``: a property may not share its own field's
        name, or ``self.X`` inside the property resolves to the property. This
        is the config-accessor trap this project has now hit five times.
        """
        return float(self.delta_overweighting_ratio_value.value)

    @property
    def gdpnow_published_mean_abs_error(self) -> float:
        """Mean |FRED GDPNOW - realised SAAR growth|, in percentage points.

        The published figure is a FINAL per-quarter record, not a real-time
        nowcast, so this is its error as a record of the quarter rather than as
        a forecast made in it. Disclosed so the cross-check gap is not read as
        the model's own error.
        """
        return float(self.gdpnow_published_mean_abs_error_pp.value)


class GdpNowcastSettings(BaseModel):
    """Module 7.5's expenditure weights and the measured accuracy record.

    Section 6.5 supplies literal weights of 0.6 / 0.3 / 0.1 on retail sales,
    durable-goods orders and the trade balance, and a docstring asserting that
    the Atlanta Fed's published GDPNow has "no free API" so the figure must be
    entered by hand. Five problems were measured against this build's live data
    before the function was written; see D-034.

    **1. The weights are not expenditure shares.** They sum to 1.0 as though
    the three inputs were the whole of GDP. Actual 2026 Q2 BEA shares are
    consumption ~67.9%, investment ~18.2%, net exports ~-3.1% — summing to
    ~83.0%. So the specification's numbers are not a share allocation, and
    two of them are wrong in kind: **the net-exports weight must be negative**
    (net exports are subtracted from GDP), and durable-goods orders — whose
    month-over-month change is 3-4x more volatile than retail sales' — carry
    half retail sales' weight.

    The specification's 0.6/0.3/0.1 is retained in this model's ``note`` as the
    rejected alternative, because a reader comparing the two needs both.

    **2. The trade term was sign-inverted on every observation.** FRED
    ``BOPGSTB`` is the US goods-and-services balance and is negative in 100% of
    its 415 observations. A *percent change* of an all-negative series has the
    opposite sign to a contribution: a widening deficit (contractionary) yields
    a positive percent change which the specification's +0.1 weight **adds** to
    growth. Measured over 414 months the deficit widened 227 times (54.8%) and
    narrowed 187 (45.2%) — so the term was wrong on 414/414 months, not
    intermittently. `trade_balance_weight` is therefore negative, which turns
    the percent change into a contribution.

    **3. Cadence.** The three inputs are month-over-month percentages; the base
    is a quarterly annualized rate. One month's change has no quarter-equivalent
    without annualizing (x12) and averaging the quarter's three months, which
    `_quarter_annualized_mom` does.

    **4. Basis.** Retail sales and durable-goods orders are nominal; the base is
    real. Two anonymous floats cannot express that, so the input contract states
    it and the model warns rather than silently mixing them (D-031).

    **5. The published figure IS reachable, contrary to the docstring.** FRED
    ``GDPNOW`` returns 61 live observations (2011-07..2026-07, one per quarter,
    median gap 92 days, zero consecutive repeats). It is a final per-quarter
    record rather than a live in-quarter nowcast — its own mean absolute error
    against the realised print is recorded here — but it is sourceable, so the
    prescribed manual-entry route is unnecessary and the cross-check is live.
    ``NOWCAST``, ``GDPNOWC1`` and ``ATLGDPNOW`` all return empty frames and were
    rejected by probe.
    """

    model_config = ConfigDict(extra="forbid")

    consumption_weight: CalibratedValue
    investment_weight: CalibratedValue
    net_exports_weight: CalibratedValue
    months_per_quarter_value: CalibratedValue
    accuracy: GdpNowcastAccuracy
    persistence_improvement_threshold_pp: CalibratedValue

    @property
    def consumption(self) -> float:
        """Share of GDP attributable to personal consumption expenditures."""
        return float(self.consumption_weight.value)

    @property
    def investment(self) -> float:
        """Share of GDP attributable to private investment."""
        return float(self.investment_weight.value)

    @property
    def net_exports(self) -> float:
        """Share of GDP attributable to net exports — **negative** by construction.

        The sign is the correction. Net exports are subtracted from GDP, so a
        positive weight here would make a widening trade deficit raise the
        nowcast, which is the defect D-034 records.
        """
        return float(self.net_exports_weight.value)

    @property
    def months_per_quarter(self) -> int:
        """Months in a quarter, for annualizing a monthly change."""
        return int(self.months_per_quarter_value.value)

    @property
    def persistence_improvement_threshold(self) -> float:
        """Improvement in mean absolute error, in pp, required to claim skill.

        Deliberately set at a level the measured model does **not** clear. The
        best weight in the sweep (0.1) improved mean absolute error by 0.11pp
        against a 2.915pp benchmark, on 137 observations — inside noise, and
        fitted on the same points that measure it (D-027's circularity). Setting
        the bar below the achieved value would turn a null result into a
        claimed one.
        """
        return float(self.persistence_improvement_threshold_pp.value)


class AuctionBaseRates(BaseModel):
    """The measured frequency of Module 8.2's two derivable flags (D-029).

    A flag produced by a noisy comparison must travel with its own base rate,
    or a reader cannot tell a signal from a coin flip. These were measured over
    the live 10-Year auction history; see ``AuctionDemandSettings`` for what
    could and could not be measured.
    """

    model_config = ConfigDict(extra="forbid")

    auctions_measured_value: CalibratedValue
    weak_bid_to_cover_rate_value: CalibratedValue
    foreign_fading_rate_value: CalibratedValue

    @property
    def auctions_measured(self) -> int:
        """Number of auctions the two rates below were measured over."""
        return int(self.auctions_measured_value.value)

    @property
    def weak_bid_to_cover_rate(self) -> float:
        """Share of measured auctions whose bid-to-cover fell below 0.95x its trailing average."""
        return float(self.weak_bid_to_cover_rate_value.value)

    @property
    def foreign_fading_rate(self) -> float:
        """Share of measured auctions whose indirect share fell >3pp below its average."""
        return float(self.foreign_fading_rate_value.value)


class AuctionDemandSettings(BaseModel):
    """Module 8.2's thresholds, its window, and the measured base rates.

    Section 20.8 supplies three literals — ``0.95`` on the bid-to-cover ratio,
    ``3.0`` percentage points on the indirect-bidder share, and a bare ``< 0``
    on the stop-through — and **no trailing-average window at all**. Each is
    moved here and given a calibration status: a threshold that decides a
    categorical verdict is a parameter, not a constant.

    **The tail input is MANUAL, not LIVE, contrary to Section 21.1.** The
    registry names "TreasuryDirect auction results API" as ``stop_through_bp``'s
    source. That route was inspected column by column — all 91 of them on the
    ``note`` security type — and it carries **no when-issued or expected-yield
    field**. The three yields it does expose (``low_yield``,
    ``avg_median_yield``, ``high_yield``) are within-auction statistics: they
    agree with one another to within ~0.0005 on every one of 703 auctions, so
    none of them can stand in for the market's *pre-auction* expectation that a
    tail is measured against. The caller supplies the gap, and the model marks
    it as manual entry in its output. See **D-036**.

    **The window is a judgement, not a measurement.** Six auctions is roughly
    six months for a 10-Year note (which auctions monthly) and two quarters for
    a 2/5/7-Year. The two base rates below are stable across 4, 6 and 12, which
    is why the window is recorded as a convention rather than fitted — a
    parameter that does not move the answer should not be presented as if it
    were estimated.
    """

    model_config = ConfigDict(extra="forbid")

    trailing_window_auctions_value: CalibratedValue
    weak_bid_to_cover_ratio_value: CalibratedValue
    indirect_fade_threshold_pp_value: CalibratedValue
    tail_boundary_bp_value: CalibratedValue
    base_rates: AuctionBaseRates

    @property
    def trailing_window_auctions(self) -> int:
        """How many prior auctions the trailing average is taken over."""
        return int(self.trailing_window_auctions_value.value)

    @property
    def weak_bid_to_cover_ratio(self) -> float:
        """Multiple of the trailing average below which bid-to-cover counts as weak."""
        return float(self.weak_bid_to_cover_ratio_value.value)

    @property
    def indirect_fade_threshold_pp(self) -> float:
        """Percentage points below its trailing average at which indirect demand is fading."""
        return float(self.indirect_fade_threshold_pp_value.value)

    @property
    def tail_boundary_bp(self) -> float:
        """The stop-through level at or above which an auction did not tail.

        Zero, and it is **definitional rather than estimated**: a tail is a
        negative stop-through by construction, so there is no free parameter
        here to calibrate. It is a config leaf anyway so the boundary is stated
        once and the sign convention cannot drift.
        """
        return float(self.tail_boundary_bp_value.value)


class CreditTrendBaseRates(BaseModel):
    """The measured frequency of each `default_rate_trend` value.

    **These were UNMEASURABLE until D-043.** Section 21.1 marks
    `default_rate_trend` MANUAL, so no history existed to classify and recording
    a trend frequency would have meant inventing one. With the trend now derived
    from FRED `DRALACBS`, the `fundamental` predicate's base rate becomes a
    measured quantity for the first time.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    rising_rate_value: CalibratedValue
    stable_rate_value: CalibratedValue
    falling_rate_value: CalibratedValue

    @property
    def observations_measured(self) -> int:
        """Four-quarter delinquency changes the rates below were measured over."""
        return int(self.observations_measured_value.value)

    @property
    def rates(self) -> dict[str, float]:
        """Every trend's measured frequency, keyed by the trend value."""
        return {
            "rising": float(self.rising_rate_value.value),
            "stable": float(self.stable_rate_value.value),
            "falling": float(self.falling_rate_value.value),
        }


class CreditSpreadBaseRates(BaseModel):
    """The measured frequency of Module 8.3's three derivable flags (D-029).

    A threshold comparison that decides a categorical attribution must travel
    with the rate at which it fires, or a reader cannot tell a signal from a
    coin flip. Measured over the live series; see ``CreditSpreadSettings`` for
    what could and could not be measured.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    equity_vol_spike_rate_value: CalibratedValue
    widening_rate_value: CalibratedValue
    parallel_widening_rate_value: CalibratedValue

    @property
    def observations_measured(self) -> int:
        """Number of overlapping change windows the three rates below were measured over."""
        return int(self.observations_measured_value.value)

    @property
    def equity_vol_spike_rate(self) -> float:
        """Share of windows in which equity volatility rose past the spike threshold."""
        return float(self.equity_vol_spike_rate_value.value)

    @property
    def widening_rate(self) -> float:
        """Share of windows in which the high-yield spread widened at all."""
        return float(self.widening_rate_value.value)

    @property
    def parallel_widening_rate(self) -> float:
        """Share of windows in which HY and IG moved within the differentiation band."""
        return float(self.parallel_widening_rate_value.value)


class CreditSpreadSettings(BaseModel):
    """Module 8.3's thresholds, its window, and the measured base rates.

    Section 20.8 supplies one literal — ``20`` on the equity-volatility change —
    and **no change window at all**, even though every input is a *change* over
    some period. The window is therefore the most consequential unspecified
    parameter in this function: the same 20% volatility threshold fires at
    **1.8%** of daily windows, **10.2%** of five-day windows and **18.2%** of
    twenty-one-day windows. All three are recorded in the note so the choice is
    visible rather than buried.

    **Two inputs need opposite unit conversions, which is the hazard here.**
    The two credit spreads are in *percent* and must be multiplied by 100 to
    reach the basis points their input is denominated in; VIX is a *level* in
    index points, and the model's input is a percent *change* of it. Applying
    one conversion to both would be a 100x error on one of them, producing a
    perfectly plausible attribution of the wrong kind — the pairing-axis defect
    (D-035). Both conversions are asserted in the live check.

    **``default_rate_trend`` is MANUAL**, per Section 21.1: *"No clean free
    real-time series. Human assessment or raise."* It is one of the two
    predicates that decide the attribution, so the verdict rests partly on a
    hand-entered judgement, and the live check cannot exercise every branch.
    """

    model_config = ConfigDict(extra="forbid")

    change_window_days_value: CalibratedValue
    equity_vol_spike_threshold_pct_value: CalibratedValue
    differentiation_threshold_bp_value: CalibratedValue
    delinquency_trend_band_pp_value: CalibratedValue
    trend_base_rates: CreditTrendBaseRates
    base_rates: CreditSpreadBaseRates

    @property
    def change_window_days(self) -> int:
        """Trading days over which every input's change is measured."""
        return int(self.change_window_days_value.value)

    @property
    def equity_vol_spike_threshold_pct(self) -> float:
        """Percent rise in equity volatility that counts as a spike."""
        return float(self.equity_vol_spike_threshold_pct_value.value)

    @property
    def delinquency_trend_band_pp(self) -> float:
        """Four-quarter delinquency move, in pp, beyond which the trend is not flat.

        **This band decides whether the STABLE state is reachable.** At the
        smallest candidate it occurred 3.1% of the time, which is the dead-branch
        problem D-037 and D-040 both found; at the shipped 0.10pp it is 21.0%.
        """
        return float(self.delinquency_trend_band_pp_value.value)

    @property
    def differentiation_threshold_bp(self) -> float:
        """Basis points within which HY and IG count as moving together.

        Used ONLY by the published diagnostic. The specification's attribution
        never reads the two spread inputs, so this threshold cannot change the
        verdict — see the model's docstring.
        """
        return float(self.differentiation_threshold_bp_value.value)


class InflationConvergenceBaseRates(BaseModel):
    """Measured frequencies of each convergence classification (Module 5.3).

    Published because Section D-029 requires a categorical to travel with its
    own measured frequency: without these a reader cannot tell a finding from
    the base state, and here the base state dominates.
    """

    model_config = ConfigDict(extra="forbid")

    three_measure: dict[str, CalibratedValue]
    six_measure: dict[str, CalibratedValue]
    measure_up_share: dict[str, CalibratedValue]

    @property
    def three_measure_high(self) -> float:
        """Share of 522 real months the spec's three-measure form returned HIGH."""
        return float(self.three_measure["high"].value)

    @property
    def six_measure_high(self) -> float:
        """Share of the same months the six-measure form returned HIGH."""
        return float(self.six_measure["high"].value)

    @property
    def up_share(self) -> dict[str, float]:
        """Per-measure share of months whose m/m change is positive.

        The root cause of the HIGH base rate: a sign test over series that rise
        88-98% of the time is near-constant by construction.
        """
        return {k: float(v.value) for k, v in self.measure_up_share.items()}


class InflationConvergenceSettings(BaseModel):
    """Module 5.3 (Section 15.19-C) — the convergence classifier's parameters.

    See ``config/settings.yaml``'s ``inflation.convergence`` block for the
    measurement notes. Two entries are corrections rather than transcription:

    * ``deep_conflict_share_threshold`` — the specification gates CONFLICTED on
      ``headline * core < 0`` alone, which reports HIGH in months where three
      other measures oppose.
    * ``min_independent_families_per_band`` — Section 15.19-D's integration
      requirement, made operational. A band cannot be claimed on fewer
      independent source families than this, however many measures agree.
    """

    model_config = ConfigDict(extra="forbid")

    high_threshold: CalibratedValue
    medium_threshold: CalibratedValue
    deep_conflict_share_threshold: CalibratedValue
    min_independent_families_per_band: dict[str, int]
    confidence_ceiling_by_independent_families: CalibratedValue
    measured_base_rates: InflationConvergenceBaseRates

    @property
    def high(self) -> float:
        """Agreement fraction at or above which the reading is HIGH.

        Section 15.19-C's literal ``0.8``. Degenerate at three measures, where
        it requires unanimity — see the config note.
        """
        return float(self.high_threshold.value)

    @property
    def medium(self) -> float:
        """Agreement fraction at or above which the reading is MEDIUM."""
        return float(self.medium_threshold.value)

    @property
    def deep_conflict_share(self) -> float:
        """Losing-side share at or above which CONFLICTED fires regardless of pair.

        The corrected gate. A genuine conflict is a property of how the whole
        measure set splits, not of two particular members.
        """
        return float(self.deep_conflict_share_threshold.value)

    def min_families(self, band: str) -> int:
        """Independent source families required before ``band`` may be claimed."""
        return int(self.min_independent_families_per_band[band])

    @property
    def families_for_full_credit(self) -> int:
        """Independent families at which the confidence credit saturates.

        **Derived, not carried.** The saturating family count is
        ``ceil(cap / bonus)`` — where ``cap`` is
        ``confidence.source_independence_bonus_cap`` and ``bonus`` is
        ``confidence.source_independence_bonus`` — because
        ``compute_confidence`` credits ``count * bonus`` capped at ``cap``.

        This property previously read the configured
        ``confidence_ceiling_by_independent_families`` directly, and that value
        was wrong: it said 3 while the constants saturate at 5. Nothing read the
        property, so nothing caught it — the D-040 mis-targeted-mutation survivor
        C-1b in ``scripts/mutation_inflation_convergence.py``. It is now computed
        from the two constants that actually govern the credit, so the two cannot
        disagree.

        The configured entry is still read, as a cross-check: if it contradicts
        the derived value, that is a configuration error and is raised rather
        than silently preferring one of the two.
        """
        confidence = get_settings().confidence
        bonus = float(confidence.source_independence_bonus.value)
        cap = float(confidence.source_independence_bonus_cap.value)
        derived = math.ceil(cap / bonus) if bonus > 0 else 0

        configured = int(self.confidence_ceiling_by_independent_families.value)
        if configured != derived:
            raise ValueError(
                f"inflation.convergence.confidence_ceiling_by_independent_families "
                f"is configured as {configured} but the confidence constants "
                f"(bonus={bonus}, cap={cap}) saturate at {derived} families. "
                "Update the config entry to match the arithmetic."
            )
        return derived


class InflationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shelter_lag_months: CalibratedValue
    breadth: InflationBreadthSettings
    convergence: InflationConvergenceSettings
    shelter_converged_tolerance_pp: CalibratedValue
    pipeline_base_rate: InflationPipelineBaseRate
    pipeline_gradient_tolerance_pp: CalibratedValue

    @property
    def shelter_lag(self) -> int:
        """The lease-turnover lag in months, from config.

        Read by ``project_shelter_cpi``. Deliberately not a field on
        ``ShelterLagInputs``: a signature default would be a second source of
        truth that wins whenever a caller omits it.
        """
        return int(self.shelter_lag_months.value)

    @property
    def shelter_converged_tolerance(self) -> float:
        """Gap in pp below which the shelter projection is called converged.

        The specification's binary cooling/reaccelerating test classifies an
        exact match as "reaccelerating", asserting a direction change where
        none exists. This threshold gives the third state a width.
        """
        return float(self.shelter_converged_tolerance_pp.value)

    @property
    def pipeline_gradient_tolerance(self) -> float:
        """Separation in pp below which the PPI stage gradient is called absent.

        Module 5.4's ordering test is strict, so an exact three-way tie reports
        "no clear upstream gradient" while a 0.01pp difference reports that
        pressure is building. This band gives the reported direction a dead
        zone without altering the underlying comparison.
        """
        return float(self.pipeline_gradient_tolerance_pp.value)


class BeveridgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pre_covid_curve: dict[str, Any]
    shift_tolerance: BeveridgeShiftTolerance

    @property
    def shift_tolerance_pp(self) -> float:
        """Dead-band in percentage points; a shift inside it is ON_CURVE."""
        return self.shift_tolerance.shift

    @property
    def points(self) -> list[BeveridgeCurvePoint]:
        raw = self.pre_covid_curve.get("points", [])
        return [BeveridgeCurvePoint.model_validate(p) for p in raw]

    def openings_at(self, unemployment_rate: float) -> float:
        """Linear interpolation of the fitted pre-COVID curve.

        Extrapolates flat beyond the fitted range rather than inventing a
        slope — the curve is a documented fitted assumption, and a fabricated
        slope outside its support would be a guess dressed as a model.
        """
        pts = sorted(self.points, key=lambda p: p.unemployment_rate)
        if not pts:
            raise KeyError("beveridge.pre_covid_curve has no points to interpolate.")
        if unemployment_rate <= pts[0].unemployment_rate:
            return pts[0].openings_rate
        if unemployment_rate >= pts[-1].unemployment_rate:
            return pts[-1].openings_rate
        for lower, upper in zip(pts, pts[1:], strict=False):
            if lower.unemployment_rate <= unemployment_rate <= upper.unemployment_rate:
                span = upper.unemployment_rate - lower.unemployment_rate
                if span == 0:
                    return lower.openings_rate
                frac = (unemployment_rate - lower.unemployment_rate) / span
                return lower.openings_rate + frac * (upper.openings_rate - lower.openings_rate)
        return pts[-1].openings_rate


class OpeningsRatioThresholds(BaseModel):
    """Module 6.2's openings-per-unemployed bands (Section 20.3)."""

    model_config = ConfigDict(extra="forbid")

    very_tight_threshold: CalibratedValue
    tight_threshold: CalibratedValue
    balanced_threshold: CalibratedValue


class LaborTightnessWeights(BaseModel):
    """Section 6.4's composite weights over the three labor blocks.

    Note the ordering claim this encodes: claims and JOLTS carry 0.4 each while
    NFP carries 0.2. That is the model — leadership — expressed as arithmetic.

    ``calibration_status`` on the block is ignored by the accessors below; the
    per-component values carry their own status, and ``CalibratedValue``
    requires a status on each leaf.
    """

    model_config = ConfigDict(extra="forbid")

    claims: CalibratedValue
    jolts: CalibratedValue
    nfp: CalibratedValue

    @property
    def claims_value(self) -> float:
        return float(self.claims.value)

    @property
    def jolts_value(self) -> float:
        return float(self.jolts.value)

    @property
    def nfp_value(self) -> float:
        return float(self.nfp.value)

    @property
    def total(self) -> float:
        """Sum of the weights, so a caller can refuse an un-normalised composite."""
        return self.claims_value + self.jolts_value + self.nfp_value


class LaborTightnessScaling(BaseModel):
    """Section 6.4's per-component scalings and the JOLTS centring offset.

    The block-level ``calibration_status`` and ``note`` in YAML are metadata for
    a reviewer; the ``CalibratedValue`` leaves below are what the models read.
    """

    model_config = ConfigDict(extra="forbid")

    claims_multiplier: CalibratedValue
    jolts_openings_multiplier: CalibratedValue
    jolts_quits_multiplier: CalibratedValue
    quits_centering: CalibratedValue

    @property
    def claims_multiplier_value(self) -> float:
        return float(self.claims_multiplier.value)

    @property
    def jolts_openings_multiplier_value(self) -> float:
        return float(self.jolts_openings_multiplier.value)

    @property
    def jolts_quits_multiplier_value(self) -> float:
        return float(self.jolts_quits_multiplier.value)

    @property
    def quits_centering_value(self) -> float:
        return float(self.quits_centering.value)


class ClaimsThresholds(BaseModel):
    """Module 6.1's explicit two-condition rule, replacing "sustained uptrend"."""

    model_config = ConfigDict(extra="forbid")

    consecutive_weeks_threshold: CalibratedValue
    pct_above_trailing_threshold: CalibratedValue

    @property
    def consecutive_weeks(self) -> int:
        return int(self.consecutive_weeks_threshold.value)

    @property
    def pct_above_trailing(self) -> float:
        return float(self.pct_above_trailing_threshold.value)


class InflationBreadthSettings(BaseModel):
    """Section 6.3's Phase 1 breadth confidences."""

    model_config = ConfigDict(extra="forbid")

    convergent_confidence: CalibratedValue
    divergent_confidence: CalibratedValue

    @property
    def convergent(self) -> float:
        return float(self.convergent_confidence.value)

    @property
    def divergent(self) -> float:
        return float(self.divergent_confidence.value)


class BeveridgeShiftTolerance(BaseModel):
    """Module 6.2's dead-band around the fitted Beveridge curve.

    A single value rather than an asymmetric pair: the tolerance exists because
    a curve fitted on historical data has finite resolution, and resolution is
    not direction-dependent. Symmetric is the honest shape.
    """

    model_config = ConfigDict(extra="forbid")

    shift_pp: CalibratedValue

    @property
    def shift(self) -> float:
        return float(self.shift_pp.value)


class AHEDistortionThresholds(BaseModel):
    """Module 6.2's two conditions for flagging AHE composition distortion."""

    model_config = ConfigDict(extra="forbid")

    low_wage_decline_pct: CalibratedValue
    eci_divergence_pp: CalibratedValue

    @property
    def low_wage_decline(self) -> float:
        """Decline in low-wage employment that makes distortion mechanically possible."""
        return float(self.low_wage_decline_pct.value)

    @property
    def eci_divergence(self) -> float:
        """AHE-minus-ECI gap beyond which the two measures are diverging."""
        return float(self.eci_divergence_pp.value)


class TwoSurveySettings(BaseModel):
    """Module 6.1's two-survey divergence thresholds.

    Sign-only by construction: Module 6.1's decision rule is about which
    direction each measure moved, not by how much. The block therefore holds no
    numeric threshold today — it exists so that the band becomes configurable
    without a code change if a dead-band is ever calibrated in Phase 5+, rather
    than being a literal buried in a comparison.
    """

    model_config = ConfigDict(extra="forbid")

    min_meaningful_change_thousands: CalibratedValue

    @property
    def min_meaningful_change(self) -> float:
        """Movement below which a survey change is treated as flat."""
        return float(self.min_meaningful_change_thousands.value)


class RevisionThresholds(BaseModel):
    """Module 6.1's threshold for calling a headline beat misleading."""

    model_config = ConfigDict(extra="forbid")

    misleading_net_thousands: CalibratedValue

    @property
    def misleading_net(self) -> float:
        """Net two-month revision below which a positive headline is misleading."""
        return float(self.misleading_net_thousands.value)


class LaborSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    neutral_nfp_pace_thousands: CalibratedValue
    openings_ratio: OpeningsRatioThresholds
    tightness_weights: LaborTightnessWeights
    tightness_scaling: LaborTightnessScaling
    claims: ClaimsThresholds
    two_survey: TwoSurveySettings
    ahe_distortion: AHEDistortionThresholds
    revisions: RevisionThresholds
    quits_percentile_window_months: CalibratedValue = CalibratedValue(
        value=36.0,
        calibration_status="institutional_convention",
        note=(
            "Trailing window for jolts_quits_level_percentile. Section 6.4 says "
            "'its trailing 3-year range'; three years is 36 months and the "
            "convention is the specification's own. It is config rather than a "
            "literal because the snapshot may carry less history than the window "
            "asks for (the API layer reports the window it actually used), and a "
            "narrowed window makes an ordinary reading look extreme — so moving "
            "it must not require editing Python."
        ),
    )

    @property
    def quits_percentile_window(self) -> int:
        """The quits-percentile window in whole months (default 36)."""
        return int(self.quits_percentile_window_months.value)

    @property
    def neutral_nfp_pace(self) -> float:
        return float(self.neutral_nfp_pace_thousands.value)


class QEStanceBaseRates(BaseModel):
    """The measured frequency of Module 4.1's three stances (D-029, D-040).

    The stance is a categorical produced by a threshold comparison, so it
    travels with the frequency at which each value occurs.

    **The NEUTRAL_HOLD rate is the interesting one.** Under Section 20.4's own
    ``balance_sheet_change_3mo == 0`` test it is **0.0%** — the branch is
    unreachable, because a balance sheet measured in millions of dollars never
    changes by exactly zero over thirteen weeks. The rate below is measured
    under the relative band that replaces it.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    qe_expanding_rate_value: CalibratedValue
    qt_contracting_rate_value: CalibratedValue
    neutral_hold_rate_value: CalibratedValue
    reserve_drain_while_qt_rate_value: CalibratedValue

    @property
    def observations_measured(self) -> int:
        """Number of weekly observations the rates below were measured over."""
        return int(self.observations_measured_value.value)

    @property
    def rates(self) -> dict[str, float]:
        """Every stance's measured frequency, keyed by the stance name."""
        return {
            "QE_EXPANDING": float(self.qe_expanding_rate_value.value),
            "QT_CONTRACTING": float(self.qt_contracting_rate_value.value),
            "NEUTRAL_HOLD": float(self.neutral_hold_rate_value.value),
        }

    @property
    def reserve_drain_while_qt_rate(self) -> float:
        """Share of QT weeks in which reserves ALSO fell over the same window."""
        return float(self.reserve_drain_while_qt_rate_value.value)


class QEStanceSettings(BaseModel):
    """Module 4.1's neutral band, the RRP drain threshold, and the base rates.

    Section 20.4 supplies **no tolerance** — it tests the balance-sheet change
    against exactly zero — and no threshold for when the ON RRP buffer counts
    as drained. Both are added here, with their measured consequences recorded.
    """

    model_config = ConfigDict(extra="forbid")

    neutral_band_pct_value: CalibratedValue
    rrp_drained_threshold_bn_value: CalibratedValue
    base_rates: QEStanceBaseRates

    @property
    def neutral_band_pct(self) -> float:
        """Percentage of the balance-sheet level inside which the stance is flat.

        Relative rather than absolute because the balance sheet has ranged from
        $0.7T to $9.0T over the sample; an absolute tolerance would mean
        different things at different times.
        """
        return float(self.neutral_band_pct_value.value)

    @property
    def rrp_drained_threshold_bn(self) -> float:
        """ON RRP level, in billions, below which the buffer counts as drained."""
        return float(self.rrp_drained_threshold_bn_value.value)


class ProbabilitySettings(BaseModel):
    """Module 12.3/12.4's thresholds.

    Section 20.11 supplies three literals — an uninformative-likelihood-ratio
    band, a tail-loss multiple, and a probability-sum tolerance — and hardcodes
    ``confidence`` at 0.8 and 0.6. The literals are externalized here; the
    confidences go through ``compute_confidence()``.
    """

    model_config = ConfigDict(extra="forbid")

    uninformative_lr_band_value: CalibratedValue
    probability_sum_tolerance_value: CalibratedValue
    tail_loss_multiple_value: CalibratedValue

    @property
    def uninformative_lr_band(self) -> float:
        """How far a likelihood ratio must sit from 1.0 to count as informative.

        Symmetric, where Section 20.11 writes the band as two asymmetric
        constants. See the note in settings.yaml.
        """
        return float(self.uninformative_lr_band_value.value)

    @property
    def probability_sum_tolerance(self) -> float:
        """How far a scenario set's probabilities may sum from 1.0 before refusal."""
        return float(self.probability_sum_tolerance_value.value)

    @property
    def tail_loss_multiple(self) -> float:
        """How large the worst case must be, as a multiple of |EV|, to warn."""
        return float(self.tail_loss_multiple_value.value)


class MinskyBaseRates(BaseModel):
    """Module 3.4's one measurable frequency.

    **Only one of the model's predicates rests on a live input.** Section 21.1
    marks `risky_credit_growth_pct` and `total_credit_growth_pct` BLOCKED, so no
    history exists to classify and the STAGE base rate cannot be measured —
    recording one would mean inventing it. The standards predicate is live
    (SLOOS `DRTSCILM`), so its frequency is measured and published, and the
    absence of the other is stated rather than filled.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    standards_loosening_rate_value: CalibratedValue
    stage_observations_measured_value: CalibratedValue
    ponzi_drift_warning_rate_value: CalibratedValue
    speculative_drift_rate_value: CalibratedValue
    hedge_dominant_rate_value: CalibratedValue

    @property
    def observations_measured(self) -> int:
        """Quarterly SLOOS observations the standards rate was measured over."""
        return int(self.observations_measured_value.value)

    @property
    def stage_observations_measured(self) -> int:
        """Quarters the three STAGE rates were measured over.

        **These were unmeasurable until D-043.** While the credit-growth inputs
        were blocked there was no history to classify, so no stage frequency could
        be recorded without inventing one. Lifting the block made them measurable.
        """
        return int(self.stage_observations_measured_value.value)

    @property
    def stage_rates(self) -> dict[str, float]:
        """Every stage's measured frequency, keyed by the stage name."""
        return {
            "PONZI_DRIFT_WARNING": float(self.ponzi_drift_warning_rate_value.value),
            "SPECULATIVE_DRIFT": float(self.speculative_drift_rate_value.value),
            "HEDGE_DOMINANT": float(self.hedge_dominant_rate_value.value),
        }

    @property
    def standards_loosening_rate(self) -> float:
        """Share of quarters in which lending standards net LOOSENED."""
        return float(self.standards_loosening_rate_value.value)


class MinskySettings(BaseModel):
    """Module 3.4's drift margin and the one measurable base rate.

    Section 20.3 tests ``risky > total * 1.2``, which **inverts when total
    growth is negative**. The margin is applied to the gap instead — see
    ``drift_margin_pct``.
    """

    model_config = ConfigDict(extra="forbid")

    drift_margin_pct_value: CalibratedValue
    base_rates: MinskyBaseRates

    @property
    def drift_margin_pct(self) -> float:
        """How far risky credit must outpace total, as a fraction of |total growth|.

        The specification's ``* 1.2`` expressed as a margin. Applied as
        ``(risky - total) > margin * |total|`` so it is sign-safe: the
        multiplicative form makes a negative base MORE negative, firing the
        "outgrowing" flag exactly when risky credit is shrinking fastest.
        """
        return float(self.drift_margin_pct_value.value)


class RegimeRateValues(BaseModel):
    """The nine measured state frequencies, as ``CalibratedValue`` envelopes.

    Split from :class:`RegimeBaseRates` only so the YAML nests the way every
    other measured-rate block in this file does (``base_rates: {rates: {...}}``)
    — the envelope carries the ``calibration_status`` obligation that
    ``fitted_assumption`` states these are properties of *these* series over
    *this* window, not constants of the economy.
    """

    model_config = ConfigDict(extra="forbid")

    early_expansion_value: CalibratedValue
    mid_expansion_value: CalibratedValue
    late_expansion_value: CalibratedValue
    slowdown_value: CalibratedValue
    recession_value: CalibratedValue
    recovery_value: CalibratedValue
    disinflation_value: CalibratedValue
    reflation_value: CalibratedValue
    stagflation_value: CalibratedValue


class RegimeBaseRates(BaseModel):
    """The measured frequency of each of Module 3's nine regime states (D-029).

    The regime is a categorical produced from threshold comparisons on two
    continuous axes, so per D-029 it must travel with the frequency at which
    each value occurs. This matters more here than in most of the system: the
    classifier's central defect (see ``models/regime.py``) is that **four of its
    nine declared states are unreachable**, and a base rate of exactly ``0.0``
    is the *observable signature* of an unreachable branch. Publishing the
    frequencies is therefore not decoration — it is how the reachability claim
    becomes checkable on live data rather than only in a unit test.

    ``observations_measured == 0`` means **not yet measured**, and every rate
    reads ``0.0`` in that state. A consumer must check the count before
    treating a zero rate as a measured frequency of zero; the model does.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    rates: RegimeRateValues

    @property
    def observations_measured(self) -> int:
        """Number of observations the nine rates below were measured over."""
        return int(self.observations_measured_value.value)

    @property
    def measured(self) -> bool:
        """True once a live measurement has recorded a non-zero window."""
        return self.observations_measured > 0

    @property
    def rate_map(self) -> dict[str, float]:
        """Every state's measured frequency, keyed by the state name.

        A mapping rather than nine accessors so the model looks a state up by
        the name it just produced — the names and the rates cannot drift apart
        without the lookup failing loudly.
        """
        return {
            "early_expansion": float(self.rates.early_expansion_value.value),
            "mid_expansion": float(self.rates.mid_expansion_value.value),
            "late_expansion": float(self.rates.late_expansion_value.value),
            "slowdown": float(self.rates.slowdown_value.value),
            "recession": float(self.rates.recession_value.value),
            "recovery": float(self.rates.recovery_value.value),
            "disinflation": float(self.rates.disinflation_value.value),
            "reflation": float(self.rates.reflation_value.value),
            "stagflation": float(self.rates.stagflation_value.value),
        }


class TrilemmaBaseRates(BaseModel):
    """The measured firing frequency of the two reserves thresholds (D-029).

    Both thresholds produce a **categorical** — "reserves are depleting" — from
    a comparison on one continuous series, so per D-029 the categorical must
    travel with the frequency at which the comparison fires. This is what
    separates a *precondition* from a *signal*, and the measured values make the
    distinction concrete: the specification's 3-month rule fires on roughly a
    tenth of all UK months, so it cannot be read as a crisis indicator on its
    own.

    The window is **not** the same for the two measures, so each carries its own
    observation count rather than sharing one. ``measured`` is ``False`` when
    ``observations_measured`` is zero, and every rate then reads ``0.0`` — a
    consumer must check the flag before treating zero as a measured zero; the
    model does.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    depletion_3mo_base_rate: CalibratedValue
    break_1mo_base_rate: CalibratedValue
    note: str = ""

    @property
    def observations_measured(self) -> int:
        """Number of months the two rates were measured over."""
        return int(self.observations_measured_value.value)

    @property
    def measured(self) -> bool:
        """True once a live measurement has recorded a non-zero window."""
        return self.observations_measured > 0


class TrilemmaReferenceEpisode(BaseModel):
    """The historical episode the trilemma live check validates against (D-048).

    Kept in config rather than in the live-check script because it is a claim
    about the **world**, not about the test: the reserves series, the date, and
    the severity the function is expected to report. A live check that hardcoded
    its own expectation could be "fixed" by editing the expectation; one that
    reads it from config cannot (the version-controlled diff is the audit trail).

    ``country`` is ``gb`` — deliberately not the ``us`` of the guarded function.
    Section 22.3 makes this build US-only through Phase 4, and for ``us`` the
    fixed-FX leg is never satisfied, so the point below the guard can never be
    exercised by a US input. See the increment note in ``DECISIONS.md`` (D-048).
    """

    model_config = ConfigDict(extra="forbid")

    country: str
    reserves_series: str
    event_date: str
    expected_severity: str
    expected_month: str
    note: str = ""


class InversionBaseRates(BaseModel):
    """The MEASURED forward recession rates that travel with every output (D-029).

    Section 15.20-B's heuristic infers a recession probability from inversion
    depth and duration, and Section 20.x's rule is that a probability presented
    to a reader must carry the **base rate it is an adjustment to** — or the
    number is a coin flip wearing a percentage sign.

    These are measured from real history in the live check (DGS2/DGS10 vs
    ``USREC``), not asserted. The unconditional rate is the anchor the function
    adjusts *from*; the inverted and non-inverted rates are the split that shows
    the signal carries information at all.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    unconditional_12mo_rate: CalibratedValue
    not_inverted_12mo_rate: CalibratedValue
    inverted_12mo_rate: CalibratedValue
    note: str = ""

    @property
    def observations_measured(self) -> int:
        """Months with a COMPLETE 12-month forward window in the measurement."""
        return int(self.observations_measured_value.value)

    @property
    def unconditional_12mo(self) -> float:
        """P(recession within 12 months), all months, no conditioning."""
        return float(self.unconditional_12mo_rate.value)

    @property
    def not_inverted_12mo(self) -> float:
        """P(recession within 12 months) when the curve is NOT inverted."""
        return float(self.not_inverted_12mo_rate.value)

    @property
    def inverted_12mo(self) -> float:
        """P(recession within 12 months) when the curve IS inverted."""
        return float(self.inverted_12mo_rate.value)

    @property
    def measured(self) -> bool:
        """True once a live measurement has recorded a non-zero window."""
        return self.observations_measured > 0


class InversionEpisode(BaseModel):
    """One reference inversion episode, for the live check to reproduce.

    Config rather than a script constant because the episode is a claim about the
    **world**: a check that hardcoded its own expectation could be "fixed" by
    editing the expectation, whereas one that reads it from config cannot.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    expected_start: str
    expected_end: str
    expected_weeks_approx: int
    expected_min_slope_bp: float
    note: str = ""


class YieldCurveSettings(BaseModel):
    """Module 8's inversion→recession heuristic (Section 15.20-B, D-049).

    Section 15.20-B supplies this function with **hardcoded** confidences
    (``0.3`` and ``0.35``) and five literals — the depth cap (100bp), the
    duration cap (26 weeks), the maximum adjustment (0.35pp), the hard ceiling
    (0.80) and a default base rate (0.15). The confidences are refused
    (Section 22.8 makes ``compute_confidence()`` the only producer); the
    literals are externalized here. The default base rate is **deleted**, not
    externalized: it is a *measured* quantity, and a shipped default invites a
    caller to use a stale prior instead of measuring one.

    **Two empirical findings shaped what is configurable, and both come from
    the live check recorded in D-049. The numbers below are the SECOND
    measurement; the first draft of this note carried a different table and was
    wrong, because it was computed before the forward-window definition had been
    settled. That is recorded rather than quietly corrected — see the note on the
    ``t+1 .. t+12`` window below.**

    1. **Depth is monotone in the outcome; duration is not.** Measured on
       1976-2026 with complete 12-month forward windows (n=592),
       P(recession within 12 months) rises with depth across every bucket
       (0.412 / 0.417 / 0.552 / 0.857) — but by duration it is **hump-shaped**
       (0.250 / 0.286 / 0.412 / **0.769** / 0.520), peaking at 26-52 weeks and
       FALLING beyond it. The falling bucket is dominated by the 2022-2024
       inversion, which ran ~113 weeks and has not been followed by a recession.
    2. **The specification's 26-week duration cap therefore sits exactly at the
       peak of the hump.** Whether that was deliberate is unrecorded; the effect
       is that the spec's mechanism never enters the region where its own
       monotonicity assumption is contradicted by the data. That is why the cap
       is retained as the *default* and the extending behaviour is opt-in.

    **The forward window is ``t+1 .. t+12`` and excludes ``t``.** This is not a
    detail: including ``t`` counts a recession *already underway* as a forecast,
    which moved the unconditional rate from 0.2095 to 0.2196 and the non-inverted
    rate from 0.1566 to 0.1687 while leaving the inverted rate at 0.4894
    untouched. A validation that checked only the inverted rate — the one the
    function consumes — would have passed with the wrong window and published
    two wrong rates beside it.

    ``duration_saturation_cap`` is thus the load-bearing threshold it always
    was, and it now carries a note explaining that beyond it the measured
    relationship reverses — so a future calibration can decide deliberately
    rather than by accident.
    """

    model_config = ConfigDict(extra="forbid")

    depth_saturation_bp: CalibratedValue
    duration_saturation_cap: CalibratedValue
    max_adjustment: CalibratedValue
    probability_ceiling: CalibratedValue
    base_rates: InversionBaseRates
    reference_episodes: dict[str, InversionEpisode]

    @property
    def depth_saturation(self) -> float:
        """Inversion depth, in bp, at which the depth factor reaches 1.0.

        Named differently from the field ``depth_saturation_bp`` so there is no
        ambiguity — but the point that matters is the *body* of the
        ``model_validator`` below: naming a local ``depth_saturation_weeks``
        there shadows this class's property of the same name, because a
        ``model_validator(mode="after")`` is an ordinary function in the class
        body's scope and its locals win inside its own frame only. That shadow
        is invisible outside the validator, so the property still reads as
        declared and consumed — which is why ``test_yield_curve.py`` asserts the
        identity.
        """
        return float(self.depth_saturation_bp.value)

    @property
    def duration_cap_weeks(self) -> float:
        """Weeks inverted at which the duration factor reaches 1.0.

        **The name is deliberately not ``duration_saturation_weeks``.** Pydantic
        raises ``NameError: Field name "duration_saturation_weeks" shadows an
        attribute`` the moment a property shares a name with a model field, so
        the collision this increment actually hit was not property-vs-field but
        **local-vs-property**: an earlier draft of
        ``_ceiling_must_be_reachable_and_binding`` wrote

            low, high = self.max_probability_adjustment, 1.0 + self.max_probability_adjustment

        which reads ``max_probability_adjustment`` *inside the validator's own
        frame*, where attribute access is resolved normally and correctly. The
        bug is subtler than shadowing: ``self.`` never sees a class-body local,
        so the validator was never the problem — the failure was that the
        property it relied on was redefined *by the same edit* that added the
        validator. See D-049.

        What this property must never do is name itself after a field. The
        pairing is therefore enforced rather than remembered:
        ``test_config_properties_are_not_shadowed_by_fields`` sweeps the whole
        settings tree and asserts that no ``property`` shares a name with a
        ``model_field`` in any settings group, which is the class-wide form of
        the defect.
        """
        return float(self.duration_saturation_cap.value)

    @property
    def max_probability_adjustment(self) -> float:
        """The largest amount the inversion signal may add to the base rate."""
        return float(self.max_adjustment.value)

    @property
    def ceiling(self) -> float:
        """Hard cap on the returned probability — the system never claims certainty."""
        return float(self.probability_ceiling.value)

    @model_validator(mode="after")
    def _ceiling_must_be_reachable_and_binding(self) -> YieldCurveSettings:
        """The ceiling must be reachable — dead config reads as a constraint and is none.

        Two ways a ceiling can be vestigial, both silent without this check:

        * **Below the adjustment range** — if ``ceiling <= max_adjustment`` the
          ceiling binds even at a zero base rate, so ``base_rate`` is ignored for
          every input and the function becomes a constant. The base rate would be
          a decorative parameter.
        * **Above every attainable value** — if the ceiling exceeds
          ``1.0 + max_adjustment`` it can never bind, because a probability cannot
          exceed 1.0. It reads as a safety rail while constraining nothing, which
          is D-037's dead-branch class expressed in config.

        So the ceiling must sit strictly inside ``(max_adjustment, 1 + max_adjustment)``
        — above the adjustment floor, and low enough to actually bind at a high
        base rate. Both halves are asserted here rather than in a test alone,
        because a config file is where the mistake is made.

        **This validator must not name a local after one of the class's own
        properties.** An earlier draft wrote ``duration_saturation_weeks`` as a
        local here; because a ``model_validator(mode="after")`` body is executed
        as an ordinary function in the enclosing namespace, that local shadowed
        the property of the same name *inside this frame only* — and the failure
        surfaced far away, as ``TypeError: unsupported operand type(s) for /:
        'int' and 'CalibratedValue'`` in ``inversion_probability_adjustment``.
        The reader of either file alone cannot see it. Locals here are therefore
        prefixed ``_`` and never repeat a member name; ``test_no_validator_
        shadows_a_property`` asserts the property identity to keep it that way.
        """
        _low = float(self.max_adjustment.value)
        _high = 1.0 + _low
        _ceiling = float(self.probability_ceiling.value)
        if not _low < _ceiling < _high:
            raise ValueError(
                f"yield_curve.probability_ceiling ({_ceiling}) must lie "
                f"strictly between max_adjustment ({_low}) and "
                f"1 + max_adjustment ({_high}): below the lower bound it binds for "
                f"every input and makes the base rate decorative; above the upper "
                f"bound it can never bind and is dead config."
            )
        return self


class PillarRuleSettings(BaseModel):
    """The bands used to DERIVE the four pillar directions from real series.

    Section 20.11 takes the directions as given ints, so the specification never
    says where a ``+1`` comes from — which means a live check that supplies its
    own inputs verifies nothing about the wiring. These bands let the check
    compute all four pillars from FRED, so the series-to-verdict path is
    exercised end to end.

    They are **not** part of §20.11 and are not presented as specification
    values. The derivation rules themselves (which sign means what) are stated in
    prose in the check's docstring, next to the arithmetic that applies them,
    because the sign is the part that has gone wrong elsewhere in this project.
    """

    model_config = ConfigDict(extra="forbid")

    unemployment_change_band: CalibratedValue
    inflation_change_band: CalibratedValue
    yield_change_band: CalibratedValue
    real_rate_change_band: CalibratedValue


class ScorecardSettings(BaseModel):
    """Module 12.2's four-pillar scorecard gates (Section 20.11).

    The specification writes `agree_frac >= 0.9`, `agree_frac >= 0.75`, `>= 3`
    and `>= 2` as literals. Two of those are **not the thresholds they appear to
    be**, because `agree_frac`'s denominator is the number of NON-NEUTRAL pillars
    (1..4), which makes the reachable ratios `{1.0} / {0.5, 1.0} / {0.667, 1.0} /
    {0.5, 0.75, 1.0}` by `n`. So no ratio ever falls in `[0.9, 1.0)`, and `0.9`
    is indistinguishable from `1.0`.

    The gates are therefore exposed as **dissent counts** — what the fractions
    were reaching for, without the granularity cliff — while the fraction itself
    is still published on every result. See D-050.

    ``measured_conflicted_share`` is a **measurement over the input space**, not
    a threshold: it exists so an output can disclose whether `CONFLICTED` is a
    finding about this read or the base state of four pillars.
    """

    model_config = ConfigDict(extra="forbid")

    max_dissenting_pillars_high: CalibratedValue
    max_dissenting_pillars_medium: CalibratedValue
    min_independent_families_high: CalibratedValue
    min_independent_families_medium: CalibratedValue
    measured_conflicted_share: CalibratedValue
    pillar_rules: PillarRuleSettings

    @property
    def high_dissent_ceiling(self) -> int:
        """Dissenters permitted and still `HIGH`. Zero — i.e. unanimity."""
        return int(self.max_dissenting_pillars_high.value)

    @property
    def medium_dissent_ceiling(self) -> int:
        """Dissenters permitted and still `MEDIUM`. One."""
        return int(self.max_dissenting_pillars_medium.value)

    @property
    def high_family_floor(self) -> int:
        """Independent families required for `HIGH` (Section 15.19-D's example)."""
        return int(self.min_independent_families_high.value)

    @property
    def medium_family_floor(self) -> int:
        """Independent families required for `MEDIUM`."""
        return int(self.min_independent_families_medium.value)

    @property
    def conflicted_base_share(self) -> float:
        """Share of the admissible input space that classifies `CONFLICTED`."""
        return float(self.measured_conflicted_share.value)

    @model_validator(mode="after")
    def _dissent_ceilings_must_be_ordered(self) -> ScorecardSettings:
        _high = int(self.max_dissenting_pillars_high.value)
        _medium = int(self.max_dissenting_pillars_medium.value)
        if _high > _medium:
            raise ValueError(
                f"scorecard.max_dissenting_pillars_high ({_high}) must not exceed "
                f"max_dissenting_pillars_medium ({_medium}): HIGH is the STRICTER "
                "verdict, so it cannot tolerate more dissent than MEDIUM. Inverting "
                "them would make the MEDIUM band unreachable and silently promote "
                "every MEDIUM read to HIGH."
            )
        if _high < 0:
            raise ValueError(
                f"scorecard.max_dissenting_pillars_high ({_high}) cannot be "
                "negative — a dissenter count is a count."
            )
        if _medium > 3:
            raise ValueError(
                f"scorecard.max_dissenting_pillars_medium ({_medium}) exceeds the "
                "three dissenters a four-pillar read can produce without the "
                "pillars opposing one another, which is CONFLICTED and never "
                "reaches this gate. A ceiling above 3 is dead config."
            )
        return self


class ConvergenceSettings(BaseModel):
    """Module 12's general convergence classifier gates (Section 22.10).

    The specification's version writes ``frac >= 0.8`` and ``frac >= 0.6`` as
    literals, and its ``frac`` has two problems that make both thresholds
    **unable to express what the prose describes**:

    * The denominator is ``len(directions)`` — the WHOLE signal list, neutrals
      included — while Section 22.10's own corrected version divides by the
      non-neutral count. A neutral signal is not evidence for either direction,
      so counting it dilutes agreement in proportion to how much of the input
      is neutral. Section 12 splits the same input differently from Section
      22.10; only one can be right, and the non-neutral denominator is the one
      both the Module 5 classifier and ``four_pillar_scorecard`` already use.
    * ``CONFLICTED`` is tested first and consumes every opposed read, so past
      that gate every non-neutral signal points the same way and the reachable
      agreement fraction is exactly ``1.0``. ``0.8`` and ``0.6`` are therefore
      the same test — D-050's fifth defect, structural to the gate order.

    The gates are exposed as **dissent counts** plus a **family floor**, which
    is what the fractions were reaching for, while the fraction itself is still
    published on every result. See the module docstring and D-051.
    """

    model_config = ConfigDict(extra="forbid")

    max_dissenting_signals_high: CalibratedValue
    max_dissenting_signals_medium: CalibratedValue
    min_independent_families_high: CalibratedValue
    min_independent_families_medium: CalibratedValue
    measured_conflicted_share: CalibratedValue

    @property
    def high_dissent_ceiling(self) -> int:
        """Dissenters permitted and still ``HIGH``. Zero — i.e. unanimity."""
        return int(self.max_dissenting_signals_high.value)

    @property
    def medium_dissent_ceiling(self) -> int:
        """Dissenters permitted and still ``MEDIUM``. One."""
        return int(self.max_dissenting_signals_medium.value)

    @property
    def high_family_floor(self) -> int:
        """Independent families required for ``HIGH``."""
        return int(self.min_independent_families_high.value)

    @property
    def medium_family_floor(self) -> int:
        """Independent families required for ``MEDIUM``."""
        return int(self.min_independent_families_medium.value)

    @property
    def conflicted_base_share(self) -> float:
        """Share of the admissible input space that classifies ``CONFLICTED``."""
        return float(self.measured_conflicted_share.value)

    @model_validator(mode="after")
    def _gates_must_be_ordered(self) -> ConvergenceSettings:
        _high = int(self.max_dissenting_signals_high.value)
        _medium = int(self.max_dissenting_signals_medium.value)
        if _high > _medium:
            raise ValueError(
                f"convergence.max_dissenting_signals_high ({_high}) must not exceed "
                f"max_dissenting_signals_medium ({_medium}): HIGH is the STRICTER "
                "verdict, so it cannot tolerate more dissent than MEDIUM. Inverting "
                "them would make the MEDIUM band unreachable and silently promote "
                "every MEDIUM read to HIGH."
            )
        if _high < 0:
            raise ValueError(
                f"convergence.max_dissenting_signals_high ({_high}) cannot be "
                "negative — a dissenter count is a count."
            )
        if _medium > 1:
            raise ValueError(
                f"convergence.max_dissenting_signals_medium ({_medium}) exceeds one "
                "dissenter. Following CONFLICTED, every non-neutral signal points the "
                "same way, so the only reachable dissenter count is 0 — a ceiling "
                "above 1 is dead config, and above 1 it would also make CONFLICTED "
                "unreachable."
            )
        _fam_high = int(self.min_independent_families_high.value)
        _fam_medium = int(self.min_independent_families_medium.value)
        if _fam_high < _fam_medium:
            raise ValueError(
                f"convergence.min_independent_families_high ({_fam_high}) must not be "
                f"below min_independent_families_medium ({_fam_medium}): HIGH demands "
                "at least as much independence as MEDIUM."
            )
        if _fam_medium < 1:
            raise ValueError(
                f"convergence.min_independent_families_medium ({_fam_medium}) must be "
                "at least 1 — zero families is the degenerate case where every read "
                "qualifies."
            )
        return self


class TrilemmaSettings(BaseModel):
    """Module 1's trilemma check — thresholds and the reference episode (D-048).

    Section 15.20-A specifies this function with two **hardcoded** confidences
    (``0.7`` / ``0.6`` / ``0.4`` / ``0.8``) and a bare ``<-0.10`` reserves test.
    The hardcoded confidences are refused — Section 22.8 makes
    ``compute_confidence()`` the only producer of a confidence value — and the
    threshold is retained but now carries the **measured base rate** it fires at,
    because a 10% drawdown rule is far more common than a peg crisis.

    The second threshold (``reserves_break_threshold_1mo``) is **not in the
    specification**. It exists because the specified 3-month trend **misses the
    crisis month of the specification's own worked example**: at 1992-09 the UK's
    3-month reserves change is only ``-5.37%``, comfortably inside ``-10%``, and
    the breach first appears the following month. A 1-month measure fires on the
    crisis month itself. Both are kept because they carry different information
    — on the Korean 1997 episode each fires without the other.
    """

    model_config = ConfigDict(extra="forbid")

    reserves_depletion_threshold_3mo: CalibratedValue
    reserves_break_threshold_1mo: CalibratedValue
    confidence_penalty_for_manual_trilemma_booleans: CalibratedValue
    base_rates: TrilemmaBaseRates
    reference_episode: TrilemmaReferenceEpisode

    @property
    def depletion_3mo(self) -> float:
        """3-month reserves change below which depletion is asserted. Spec literal."""
        return float(self.reserves_depletion_threshold_3mo.value)

    @property
    def break_1mo(self) -> float:
        """1-month reserves change below which an acute break is asserted."""
        return float(self.reserves_break_threshold_1mo.value)

    @model_validator(mode="after")
    def _thresholds_must_be_ordered(self) -> TrilemmaSettings:
        """The 1-month break threshold must be *shallower* than the 3-month one.

        The 1-month measure is noisier, so requiring a **steeper** drop over one
        month than over three would make the acute-break branch a strict subset
        of the depletion branch — it could never fire alone, and the
        contemporaneous detection this increment adds would be dead code. The
        ordering is what keeps the two branches distinguishable.
        """
        if self.break_1mo < self.depletion_3mo:
            raise ValueError(
                f"regime.trilemma.reserves_break_threshold_1mo "
                f"({self.break_1mo}) must not be steeper than "
                f"reserves_depletion_threshold_3mo ({self.depletion_3mo}): a "
                f"stricter 1-month test than the 3-month test makes the "
                f"acute-break branch unreachable."
            )
        return self


class RegimeSettings(BaseModel):
    """Module 3's rule-based regime classifier bands (Section 6.2).

    Six thresholds, externalised from the specification's sample code so the
    bands are reviewable together and so a test can assert the classifier's
    **coverage** — that every declared state is reachable and no point in the
    input plane falls outside all of them.

    The two properties below are the derived quantities the classifier
    actually compares against; the raw leaves are kept so a reader can see the
    specification's literals unaltered.
    """

    model_config = ConfigDict(extra="forbid")

    recession_output_gap_max: CalibratedValue
    weak_growth_output_gap_max: CalibratedValue
    late_expansion_output_gap_min: CalibratedValue
    disinflation_output_gap_max: CalibratedValue
    neutral_inflation_trend_band_pp: CalibratedValue
    growth_momentum_band_pp: CalibratedValue
    measured_rising_inflation_rate: CalibratedValue
    base_rates: RegimeBaseRates
    trilemma: TrilemmaSettings

    @property
    def recession_gap(self) -> float:
        """Output gap below which, with falling inflation, the state is recession."""
        return float(self.recession_output_gap_max.value)

    @property
    def weak_growth_gap(self) -> float:
        """Upper bound of the negative-output-gap bands. Appears in two rules."""
        return float(self.weak_growth_output_gap_max.value)

    @property
    def late_expansion_gap(self) -> float:
        """Output gap above which, with rising inflation, the state is late expansion."""
        return float(self.late_expansion_output_gap_min.value)

    @property
    def disinflation_gap(self) -> float:
        """Upper bound of the near-trend output-gap band."""
        return float(self.disinflation_output_gap_max.value)

    @property
    def neutral_inflation_band(self) -> float:
        """Inflation momentum within this many pp of zero is FLAT, not rising or falling."""
        return float(self.neutral_inflation_trend_band_pp.value)

    @property
    def growth_momentum_band(self) -> float:
        """Output gap within this many pp of zero is AT TREND for state selection."""
        return float(self.growth_momentum_band_pp.value)

    @property
    def rising_inflation_base_rate(self) -> float:
        """Measured share of periods in which the inflation axis reads ``rising``.

        Published because it is the number that makes the state base rates
        interpretable: if the axis reads ``rising`` in 93.75% of a sixty-year
        window, then every state that requires a non-rising axis is rare by
        construction rather than by economic fact.

        The classifier reports this on **every** output, so a reader who sees
        ``late_expansion`` knows whether that label is a finding or a
        near-constant. It is config rather than a literal because the
        no-hardcoded-values rule applies to disclosures too, and because a
        test must be able to move it to prove the warning reads it.
        """
        return float(self.measured_rising_inflation_rate.value)

    @model_validator(mode="after")
    def _bands_must_be_ordered(self) -> RegimeSettings:
        """The output-gap bands must partition in the order the rules assume.

        The classifier's branches assume ``recession_gap < weak_growth_gap <
        disinflation_gap < late_expansion_gap``. If a future edit inverts two of
        them, individual rules still evaluate — each is a self-contained
        comparison — but the bands overlap, one branch becomes unreachable, and
        the state a point lands in depends on branch *order* rather than on its
        position. That is silent: no rule raises, and the model keeps returning
        a plausible label. This check turns it into a startup error.
        """
        ordered = [
            self.recession_gap,
            self.weak_growth_gap,
            self.disinflation_gap,
            self.late_expansion_gap,
        ]
        if ordered != sorted(ordered):
            raise ValueError(
                f"regime output-gap bands are not strictly ordered: "
                f"recession_gap={self.recession_gap}, weak_growth_gap={self.weak_growth_gap}, "
                f"disinflation_gap={self.disinflation_gap}, "
                f"late_expansion_gap={self.late_expansion_gap}. They must satisfy "
                f"recession < weak_growth < disinflation < late_expansion, or the "
                f"branches overlap and a state becomes unreachable by position."
            )
        return self

    @model_validator(mode="after")
    def _bands_must_be_non_negative(self) -> RegimeSettings:
        """A negative half-width inverts the comparison it is used in.

        Both bands are used as ``abs(x) <= band``. With a negative band the test
        can never be true, so the flat/at-trend case silently stops existing —
        the same shape of defect as the specification's unreachable branches.
        """
        for name, band in (
            ("neutral_inflation_trend_band_pp", self.neutral_inflation_band),
            ("growth_momentum_band_pp", self.growth_momentum_band),
        ):
            if band < 0:
                raise ValueError(
                    f"regime.{name} ({band}) must not be negative: it is a half-width "
                    f"compared as abs(x) <= band, so a negative value makes the branch "
                    f"unreachable."
                )
        return self


class PolicyMixBaseRates(BaseModel):
    """The measured frequency of each of Module 3.2's four quadrants (D-029).

    The quadrant is a categorical produced by two threshold comparisons, so per
    D-029 it must travel with the frequency at which each value occurs — a
    quadrant that fired 80% of the time would carry no information.

    Measured over **annual** observations, because the deficit series is annual.
    """

    model_config = ConfigDict(extra="forbid")

    observations_measured_value: CalibratedValue
    max_stimulus_rate_value: CalibratedValue
    mixed_fiscal_loose_monetary_tight_rate_value: CalibratedValue
    mixed_fiscal_tight_monetary_loose_rate_value: CalibratedValue
    max_restraint_rate_value: CalibratedValue

    @property
    def observations_measured(self) -> int:
        """Number of annual observations the four rates below were measured over."""
        return int(self.observations_measured_value.value)

    @property
    def rates(self) -> dict[str, float]:
        """Every quadrant's measured frequency, keyed by the quadrant name.

        A mapping rather than four accessors so the model can look a quadrant up
        by the name it just produced — the names and the rates cannot drift apart
        without the lookup failing loudly.
        """
        return {
            "MAX_STIMULUS": float(self.max_stimulus_rate_value.value),
            "MIXED_FISCAL_LOOSE_MONETARY_TIGHT": float(
                self.mixed_fiscal_loose_monetary_tight_rate_value.value
            ),
            "MIXED_FISCAL_TIGHT_MONETARY_LOOSE": float(
                self.mixed_fiscal_tight_monetary_loose_rate_value.value
            ),
            "MAX_RESTRAINT": float(self.max_restraint_rate_value.value),
        }


class PolicyMixSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fiscal_deficit_avg_pct_gdp: CalibratedValue
    base_rates: PolicyMixBaseRates

    @property
    def fiscal_deficit_avg(self) -> float:
        """Trailing average federal deficit, as % of GDP, **positive for a deficit**.

        The source series is negative for a deficit, so both this value and the
        model's field are stated as positive-deficit quantities. A caller
        supplying the raw FRED figure inverts every comparison.
        """
        return float(self.fiscal_deficit_avg_pct_gdp.value)

    @property
    def quadrant_base_rates(self) -> dict[str, float]:
        """Every quadrant's measured frequency, keyed by quadrant name."""
        return self.base_rates.rates


class LeadingIndicatorSettings(BaseModel):
    """Module 7.3's leading-indicator PROXY (see ``models/lei_proxy.py``).

    **This is not the Conference Board LEI.** That series is licensed and FRED
    ``USLEI`` returns an empty frame on this build (probed 2026-09-17), and
    Section 21.1 states that an in-house composite built from free components
    **must not be called "LEI"**. So the licensed input is BLOCKED and the
    ``MANUAL`` route Section 21.1 offers for it is refused: a figure a human
    types in cannot be refreshed, versioned or validated, and Section 21.0
    requires exactly that evidence.

    What this build does instead is the third path Section 21.1 names — an
    in-house composite over live free components — reported under its own name.
    """

    model_config = ConfigDict(extra="forbid")

    breadth_threshold: CalibratedValue
    breadth_null_rate: CalibratedValue
    component_series: dict[str, Any]

    @property
    def breadth_threshold_value(self) -> float:
        """Share of components that must decline for a broad-based reading.

        Section 20.7's literal ``0.6``. Externalized because the threshold and
        its base rate are **one measurement**: re-calibrating one without
        recomputing the other silently misreports how often the flag fires.
        """
        return float(self.breadth_threshold.value)

    @property
    def null_rate(self) -> float:
        """Documented null-model frequency for the 4-component case.

        A combinatorial figure, not a measured hit rate — the model recomputes
        it exactly for whatever component count it is handed, so this entry is
        documentation rather than the value read at runtime.
        """
        return float(self.breadth_null_rate.value)


class RepoStressThresholds(BaseModel):
    """Module 2 floor-system corridor thresholds (Section 20.2).

    Nested rather than flattened because the four values only mean anything
    together: the persistence requirement exists solely to gate the acute
    threshold, so keeping them adjacent in the model mirrors that coupling.
    """

    model_config = ConfigDict(extra="forbid")

    elevated_threshold_bp: CalibratedValue
    acute_threshold_bp: CalibratedValue
    persistence_days_required: CalibratedValue
    repo_volume_change_threshold_pct: CalibratedValue


class CurveThresholds(BaseModel):
    """Curve orientation bands (Module 8)."""

    model_config = ConfigDict(extra="forbid")

    inversion_threshold_bp: CalibratedValue
    deep_inversion_threshold_bp: CalibratedValue
    steep_threshold_bp: CalibratedValue


class DurationSettings(BaseModel):
    """Unit-conversion factors for duration reporting."""

    model_config = ConfigDict(extra="forbid")

    convexity_reporting_scale: CalibratedValue


class BondMathSettings(BaseModel):
    """Module 2's thresholds, externalized out of the function bodies."""

    model_config = ConfigDict(extra="forbid")

    repo_stress: RepoStressThresholds
    curve: CurveThresholds
    duration: DurationSettings


class BayesianSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likelihoods: dict[str, Any]

    @property
    def version(self) -> int:
        return int(self.likelihoods.get("version", 0))

    @property
    def table(self) -> dict[str, Any]:
        return dict(self.likelihoods.get("table", {}))

    def require_likelihoods(self, evidence_type: str) -> tuple[float, float]:
        """Look up ``P(evidence|true)`` and ``P(evidence|false)``.

        Raises when the table is empty or the evidence type is missing. This
        is the enforcement point for Section 21.1's rule that likelihood
        ratios are "stated, versioned, and reviewable — not chosen per-call":
        a missing entry fails loudly instead of defaulting to 0.5/0.5, which
        would silently render the Bayesian update a no-op.
        """
        table = self.table
        if not table:
            raise NotImplementedError(
                "bayesian.likelihoods.table is empty. Populating it requires historical "
                "evidence-vs-outcome data (Phase 5+). Refusing to invent likelihood "
                "ratios — see AGENTS.md Section 21.1."
            )
        if evidence_type not in table:
            raise KeyError(
                f"No likelihood entry for evidence type '{evidence_type}'. "
                f"Known types: {sorted(table)}"
            )
        entry = table[evidence_type]
        return float(entry["likelihood_given_true"]), float(entry["likelihood_given_false"])


class FCISettings(BaseModel):
    """Module 12's financial-conditions composite: weights, window, cross-check bar.

    Section 22.7 / Finding #7 governs: every component is z-scored **before**
    weighting, because percent, basis-point and index-point units are not
    comparable as raw deviations — which is what the superseded Section 20.12
    version did.

    **The ``averages`` block that used to live here has been removed.** It
    stored trailing means for three of the five components, **no standard
    deviations at all**, and no window. Measured against the live series it was
    materially wrong: ``credit_spread_hy_avg`` was **4.0** against a measured
    **3.12**, an error of more than two standard deviations, which would have
    scored today's spread at **z = -2.95** instead of **-0.85** and reported
    conditions as far looser than they are. Freezing a denominator is what let
    it drift. Section 22.7 takes the mean and the standard deviation as
    **parameters**, so the caller computes them over this window and nothing is
    frozen. See **D-038**.

    ``average_for()`` went with the block. It raised ``KeyError`` for
    ``equity_index`` and ``usd_index`` — the two components it had no entry for
    — so it was a latent crash on a surface the model needs.
    """

    model_config = ConfigDict(extra="forbid")

    weights: dict[str, Any]
    standardization_window_years_value: CalibratedValue
    nfci_divergence_threshold_value: CalibratedValue

    @model_validator(mode="after")
    def _weights_must_sum_to_one(self) -> FCISettings:
        """Refuse to load a weight set that does not sum to 1.0.

        A non-summing set silently rescales the whole composite, which moves
        every downstream threshold's meaning without changing any code. It is
        caught at load time rather than at use because there is no correct
        behaviour to fall back on — the number would still look like an FCI.
        """
        weights = self.component_weights
        # No separate empty check: with no components the sum is 0.0 and the
        # guard below already raises. A mutation sweep proved that guard inert
        # (removing it changed nothing observable), and inert code is removed
        # rather than kept for a marginally better message (D-031).
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"fci.weights.components sums to {total!r}, not 1.0. A composite whose "
                f"weights do not sum to one is silently rescaled, which moves the meaning "
                f"of every threshold downstream. Got: {weights}"
            )
        return self

    @property
    def component_weights(self) -> dict[str, float]:
        """The per-component weights, in declaration order."""
        raw = self.weights.get("components", {})
        return {k: float(v) for k, v in raw.items()}

    @property
    def component_names(self) -> tuple[str, ...]:
        """The component names, in declaration order.

        Exposed so the model iterates the CONFIGURED set rather than a literal
        list of its own — a component added to config but not to the model (or
        the reverse) is then a visible mismatch rather than a silent omission.
        """
        return tuple(self.component_weights)

    @property
    def standardization_window_years(self) -> int:
        """Trailing window, in years, over which every component's mean and std are computed."""
        return int(self.standardization_window_years_value.value)

    @property
    def nfci_divergence_threshold(self) -> float:
        """Absolute NFCI divergence beyond which the cross-check warns."""
        return float(self.nfci_divergence_threshold_value.value)


class DataSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_store_path: str
    persist_parquet: bool
    lookback_years: CalibratedValue

    @property
    def lookback(self) -> int:
        return int(self.lookback_years.value)


class CountrySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: list[str]
    implemented: list[str]

    @model_validator(mode="after")
    def _no_false_genericity_claim(self) -> CountrySettings:
        """AGENTS.md Section 22.3 / Finding #3.

        A country in ``enabled`` but not ``implemented`` would be a claim of
        capability that has not been earned. Rather than allow that state,
        reject it: the honest representation of "we plan to support this" is a
        documented roadmap entry, not a config flag that silently produces a
        US-shaped thesis with a foreign label.
        """
        unimplemented = set(self.enabled) - set(self.implemented)
        if unimplemented:
            raise ValueError(
                f"country.enabled lists {sorted(unimplemented)} but country.implemented does "
                f"not. No function may claim country-genericity it has not earned "
                f"(AGENTS.md Section 22.3 / Finding #3)."
            )
        return self


class OpenBBSettings(BaseModel):
    """OpenBB transport settings.

    No URL, port, timeout or retry count is hardcoded in Python. Swapping the
    fetch path (local API vs package) or pointing at a remote OpenBB instance
    is a config change, not a code change.
    """

    model_config = ConfigDict(extra="forbid")

    local_api_base_url: CalibratedValue
    use_local_api_first: CalibratedValue
    max_retries: CalibratedValue
    backoff_seconds: CalibratedValue
    timeout_seconds: CalibratedValue
    verify_ssl: CalibratedValue

    @property
    def base_url(self) -> str:
        """Base URL, with the environment variable taking precedence.

        ``OPENBB_API_URL`` overrides the YAML value so a deployment can
        redirect the client without editing a committed file.
        """
        override = os.environ.get("OPENBB_API_URL")
        return override or str(self.local_api_base_url.value)

    @property
    def local_first(self) -> bool:
        return bool(self.use_local_api_first.value)

    @property
    def retries(self) -> int:
        return int(self.max_retries.value)

    @property
    def backoff(self) -> float:
        return float(self.backoff_seconds.value)

    @property
    def timeout(self) -> float:
        return float(self.timeout_seconds.value)

    @property
    def ssl_verify(self) -> bool:
        return bool(self.verify_ssl.value)


class ValidationSettings(BaseModel):
    """Bounds at which a value stops being a market state and becomes a fault."""

    model_config = ConfigDict(extra="forbid")

    unemployment_min: CalibratedValue
    unemployment_max: CalibratedValue
    stale_series_days: CalibratedValue
    max_plausible_yield_pct: CalibratedValue
    implausible_long_end_inversion_bp: CalibratedValue
    scenario_probability_tolerance: CalibratedValue
    fed_total_assets_min_millions: CalibratedValue
    reserve_balances_min_millions: CalibratedValue
    on_rrp_volume_max_billions: CalibratedValue

    @property
    def fed_total_assets_min(self) -> float:
        return float(self.fed_total_assets_min_millions.value)

    @property
    def reserve_balances_min(self) -> float:
        return float(self.reserve_balances_min_millions.value)

    @property
    def on_rrp_volume_max(self) -> float:
        return float(self.on_rrp_volume_max_billions.value)

    @property
    def unemployment_bounds(self) -> tuple[float, float]:
        return (float(self.unemployment_min.value), float(self.unemployment_max.value))

    @property
    def stale_days(self) -> int:
        return int(self.stale_series_days.value)

    @property
    def max_yield(self) -> float:
        return float(self.max_plausible_yield_pct.value)

    @property
    def long_end_inversion_floor(self) -> float:
        return float(self.implausible_long_end_inversion_bp.value)

    @property
    def prob_tolerance(self) -> float:
        return float(self.scenario_probability_tolerance.value)


class ConfidenceSettings(BaseModel):
    """Parameters of the single confidence rule (Section 22.8).

    Section 22.8 states the formula is "itself an illustrative starting
    formula (documented as such) — Phase 5+ calibrates it against realized
    forecast accuracy". Because it is explicitly calibratable, its constants
    belong in config where the calibration can happen, not baked into the
    function body.
    """

    model_config = ConfigDict(extra="forbid")

    base: CalibratedValue
    data_quality_flag_penalty: CalibratedValue
    heuristic_penalty: CalibratedValue
    unobservable_penalty: CalibratedValue
    source_independence_bonus: CalibratedValue
    source_independence_bonus_cap: CalibratedValue
    floor: CalibratedValue
    ceiling: CalibratedValue

    @property
    def values(self) -> dict[str, float]:
        return {
            "base": float(self.base.value),
            "data_quality_flag_penalty": float(self.data_quality_flag_penalty.value),
            "heuristic_penalty": float(self.heuristic_penalty.value),
            "unobservable_penalty": float(self.unobservable_penalty.value),
            "source_independence_bonus": float(self.source_independence_bonus.value),
            "source_independence_bonus_cap": float(self.source_independence_bonus_cap.value),
            "floor": float(self.floor.value),
            "ceiling": float(self.ceiling.value),
        }

    @model_validator(mode="after")
    def _ceiling_must_be_reachable(self) -> ConfidenceSettings:
        """The ceiling must be attainable by a fully-corroborated model.

        If ``base + bonus_cap < ceiling``, no input can ever produce the
        ceiling, and the stated "clamp to [floor, ceiling]" is describing an
        upper bound the function is incapable of reaching. That is not a
        conservative choice — it is a mismatch between documented structure and
        actual arithmetic, which is precisely the class of silent inconsistency
        this system exists to eliminate.
        """
        base = float(self.base.value)
        cap = float(self.source_independence_bonus_cap.value)
        ceiling = float(self.ceiling.value)
        if base + cap < ceiling:
            raise ValueError(
                f"confidence.source_independence_bonus_cap ({cap}) is too small for the "
                f"ceiling ({ceiling}) to ever be reachable: base ({base}) + cap ({cap}) = "
                f"{base + cap} < {ceiling}. Either raise the cap or lower the ceiling."
            )
        return self

    @model_validator(mode="after")
    def _floor_below_base(self) -> ConfidenceSettings:
        """A floor above the base would make the base term meaningless."""
        base = float(self.base.value)
        floor = float(self.floor.value)
        if floor >= base:
            raise ValueError(f"confidence.floor ({floor}) must be below confidence.base ({base}).")
        return self


class TransmissionSettings(BaseModel):
    """Module 5.6's cross-asset transmission thresholds (Section 20.5, D-052).

    Section 20.5 contains **no configurable parameter at all** — its whole map
    is a chain of literals (``> 0``, three hardcoded option strings, and a
    hardcoded ``confidence=0.45``). Under Section 21's "no literals in models"
    rule every threshold the map *uses* has to be named here, and two of the
    three are thresholds the specification uses **without noticing**:

    * The ``flat_band_bp`` band exists because ``"down" if x > 0 else "up"``
      reports an exactly-zero change as ``up``. Measured live, DGS10 is exactly
      unchanged on **459 of 5 930** daily changes (7.7%) and T10YIE on **965**
      (16.3%), so the specification's ``else`` is not a rare fallthrough — it
      is a wrong sign on a seventh of observations. See D-040 for the same
      defect class (a neutral branch that a continuous series does not take).
    * The driver bands exist because the split of a nominal move into its real
      and breakeven legs is the *measurement* of which channel drove it, and
      Section 20.5's own gold paragraph argues from that split without ever
      computing it. Section 20.5 instead accepts a ``surprise_driver``
      categorical and never uses it for anything but the equity key.
    """

    model_config = ConfigDict(extra="forbid")

    flat_band_bp: CalibratedValue
    real_driven_share: CalibratedValue
    breakeven_driven_share: CalibratedValue
    trivial_move_bp: CalibratedValue
    measured_gold_down_on_nominal_rise_share: CalibratedValue
    measured_breakeven_negative_share: CalibratedValue

    @property
    def flat_band(self) -> float:
        """Basis points below which a leg is reported ``flat`` rather than up/down."""
        return float(self.flat_band_bp.value)

    @property
    def real_driven_threshold(self) -> float:
        """Share of the nominal move the real leg must account for to be the driver."""
        return float(self.real_driven_share.value)

    @property
    def breakeven_driven_threshold(self) -> float:
        """Share of the nominal move the breakeven leg must account for to be the driver."""
        return float(self.breakeven_driven_share.value)

    @property
    def trivial_move(self) -> float:
        """Basis points below which the driver split is reported ``indeterminate``."""
        return float(self.trivial_move_bp.value)

    @property
    def gold_base_rate(self) -> float:
        """Measured share of nominal-yield rises on which the gold rule says DOWN.

        Published on every output because it is the map's **modal** answer: a
        ``gold: down`` call on a nominal rise is what this rule says roughly
        three times in four, so the label alone reads as a finding when it is
        closer to the base state (D-029's base-rate rule, reached again here).
        """
        return float(self.measured_gold_down_on_nominal_rise_share.value)

    @property
    def breakeven_negative_share(self) -> float:
        """Measured share of moves where the breakeven leg opposes the nominal leg."""
        return float(self.measured_breakeven_negative_share.value)

    @model_validator(mode="after")
    def _bands_must_be_ordered_and_satisfiable(self) -> TransmissionSettings:
        """Refuse a config whose bands no observation could satisfy, or are inverted.

        Three conditions, each of which makes some part of the map dead:

        * **`trivial_move_bp` must exceed `flat_band_bp`.** The trivial-move
          floor guards the *ratio* ``real / nominal``; the flat band guards the
          *sign* of a leg. The ratio's denominator is at least as sensitive, so
          a floor below the flat band would let a ``flat`` leg be divided into
          and classified — the map would report a driver for a move it also
          reported as not having happened.
        * **Each driver share must be in ``(0, 1]``.** At ``0`` every move is
          attributed to both channels; above ``1`` no move can ever reach the
          band (a share of the nominal move cannot exceed 1 unless the legs
          oppose, and a band above 1 makes even that case unreachable). Both
          are D-047's "a threshold no input can satisfy" defect.
        * **The flat band cannot be negative.** A negative band makes ``< band``
          unreachable for an absolute value, so no leg would ever be ``flat``.
        """
        flat = float(self.flat_band_bp.value)
        trivial = float(self.trivial_move_bp.value)
        real_share = float(self.real_driven_share.value)
        be_share = float(self.breakeven_driven_share.value)

        if flat < 0:
            raise ValueError(
                f"transmission.flat_band_bp ({flat}) cannot be negative. The band is "
                "compared against an ABSOLUTE change, so a negative band is "
                "unsatisfiable and every leg would be reported as moving."
            )
        if trivial <= flat:
            raise ValueError(
                f"transmission.trivial_move_bp ({trivial}) must exceed "
                f"flat_band_bp ({flat}). The trivial-move floor guards a RATIO whose "
                "denominator is the nominal change; a floor at or below the flat band "
                "would let a leg reported as `flat` be divided into and classified."
            )
        shares = (("real_driven_share", real_share), ("breakeven_driven_share", be_share))
        for name, share in shares:
            if not 0.0 < share <= 1.0:
                raise ValueError(
                    f"transmission.{name} ({share}) must lie in (0, 1]. At 0 every "
                    "move is attributed to this channel; above 1 the band is "
                    "unreachable and the channel becomes dead config."
                )
        return self


class ApiSettings(BaseModel):
    """The HTTP service's own parameters (Section 8, D-070).

    Section 8.4 states the security posture as prose — "bind to 127.0.0.1, no
    authentication, permissive CORS for the local Workspace only" — and prose is
    the wrong home for a bind address. A host or port written into
    ``uvicorn.run(...)`` is a deployment decision made in a code review of a
    Python file; here it is a config value with its rationale beside it, and the
    no-auth posture is a **statement in config** rather than an absence of code
    that a reader has to infer.

    Every field is stated, none inferred. The two that matter:

    * **``host`` defaults to the loopback address and the validator refuses
      ``0.0.0.0``.** Section 8.4 pairs a permissive CORS policy with a
      loopback-only bind, and those two decisions are only safe *together*:
      ``allow_origins=["*"]`` on a wildcard-bound socket is an open relay to
      every endpoint, including ``/thesis/{country}`` which runs a live snapshot
      build. The validator makes the pair inseparable rather than leaving the
      safety of one to the memory of whoever edits the other.
    * **``default_thesis_type`` is a config value, not a function default.**
      The API layer must name a ``ThesisType`` to call the builder (measured:
      it is a required keyword) and the honest representation of "the API has a
      Phase-1 default" is a config leaf a reviewer can see, not a keyword
      argument buried in a call site.
    """

    model_config = ConfigDict(extra="forbid")

    host_value: CalibratedValue = CalibratedValue(
        value="127.0.0.1",
        calibration_status="institutional_fact",
        note="Bind address. Loopback only — Section 8.4.",
    )
    port_value: CalibratedValue = CalibratedValue(
        value=8000.0,
        calibration_status="institutional_convention",
    )
    cors_origins_value: CalibratedValue = CalibratedValue(
        value=["http://127.0.0.1:8000", "http://localhost:8000"],
        calibration_status="institutional_convention",
        note=(
            "Permitted browser origins. Section 8.4 permits a permissive policy "
            "BECAUSE the bind is loopback-only; the validator below enforces that "
            "the two travel together."
        ),
    )
    dashboard_series_limit_value: CalibratedValue = CalibratedValue(
        value=12.0,
        calibration_status="uncalibrated_illustrative",
        note=(
            "How many series /dashboard_data returns per family. A cap rather "
            "than everything, because the endpoint's payload is the snapshot's "
            "full history and an unbounded response is a denial of service "
            "against the caller's own browser."
        ),
    )
    snapshot_max_age_hours_value: CalibratedValue = CalibratedValue(
        value=24.0,
        calibration_status="uncalibrated_illustrative",
        note=(
            "Beyond this, a memoized snapshot is reported as STALE in the "
            "response's disclosure rather than silently served. A served "
            "snapshot must be distinguishable from a fresh one — the D-069 "
            "lesson that a cached answer with no age attached is a claim about "
            "the present made from the past."
        ),
    )
    memoize_snapshots_value: CalibratedValue = CalibratedValue(
        value=True,
        calibration_status="institutional_convention",
        note=(
            "Reuse the last built snapshot within snapshot_max_age_hours. "
            "MEASURED context: a full live snapshot build took 223.6s over the "
            "local OpenBB API and 9.5s in-process (settings.openbb."
            "use_local_api_first), so a request-per-build design makes the "
            "endpoint unusable for a Workspace UI that polls. The cache is "
            "disclosed on every response, never silent."
        ),
    )
    short_yield_tenor_value: CalibratedValue = CalibratedValue(
        value="2yr",
        calibration_status="institutional_convention",
        note=(
            "Curve tenor used as the short yield (the policy-expectations "
            "point). Config rather than a literal because a curve-trade thesis "
            "wants a different leg and the orchestration should not change for it."
        ),
    )
    default_thesis_type_value: CalibratedValue = CalibratedValue(
        value="policy_path_gap",
        calibration_status="uncalibrated_illustrative",
        note=(
            "The family the API assumes when the caller names none. Stated in "
            "config because the orchestration must pass SOMETHING — the builder "
            "requires it — and an assumption a caller cannot see is exactly the "
            "'manufacturing a claim' failure the builder's divergence 1 warns "
            "about."
        ),
    )
    yoy_match_tolerance_days_value: CalibratedValue = CalibratedValue(
        value=5.0,
        calibration_status="institutional_convention",
        note=(
            "How many days off the one-year anniversary a year-over-year prior "
            "point may be. Measured reason for the guard: a 20-point JTSJOL "
            "series was accepted and its ratio reported as 'year-over-year' "
            "against a point that was not one year back (D-070 probe case 2). "
            "Five days covers a weekly series whose anniversary falls between "
            "publications and EXCLUDES a monthly series' neighbouring month "
            "(28-31 days away) — that exclusion is the whole point, because "
            "admitting the adjacent month silently converts a 29-day comparison "
            "into an annual one."
        ),
    )

    @property
    def host(self) -> str:
        """The bind address (loopback by default; see the validator below)."""
        return str(self.host_value.value)

    @property
    def port(self) -> int:
        return int(self.port_value.value)

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_value.value
        if not isinstance(raw, list):  # pragma: no cover - a YAML shape fault
            raise TypeError(
                f"api.cors_origins must be a list of origin strings; got "
                f"{type(raw).__name__}. A bare string would be iterated "
                f"character-by-character by Starlette's CORS middleware."
            )
        return [str(origin) for origin in raw]

    @property
    def dashboard_series_limit(self) -> int:
        return int(self.dashboard_series_limit_value.value)

    @property
    def snapshot_max_age_hours(self) -> float:
        return float(self.snapshot_max_age_hours_value.value)

    @property
    def memoize_snapshots(self) -> bool:
        return bool(self.memoize_snapshots_value.value)

    @property
    def short_yield_tenor(self) -> str:
        return str(self.short_yield_tenor_value.value)

    @property
    def default_thesis_type(self) -> str:
        return str(self.default_thesis_type_value.value)

    @property
    def yoy_match_tolerance_days(self) -> int:
        """Days off the one-year anniversary a YoY prior point may be (default 5)."""
        return int(self.yoy_match_tolerance_days_value.value)

    @model_validator(mode="after")
    def _permissive_cors_requires_loopback_bind(self) -> ApiSettings:
        """A permissive CORS policy is only safe on a loopback bind (Section 8.4).

        Not a style check. ``/thesis/{country}`` triggers a snapshot build and a
        full model chain; with no authentication anywhere in the service, the
        bind address **is** the access control. A wildcard bind plus a permissive
        origin list means any page the user visits can drive this service and
        read its output — and the failure is invisible, because the service works
        perfectly while it is happening.
        """
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            permissive = "*" in self.cors_origins or len(self.cors_origins) > 4
            if permissive:
                raise ValueError(
                    f"api.host is '{self.host}' (not loopback) while "
                    f"api.cors_origins is permissive ({self.cors_origins}). "
                    "Section 8.4 pairs a permissive CORS policy with a "
                    "loopback-only bind, and the service has NO authentication — "
                    "the bind address is the access control. Either bind to "
                    "127.0.0.1 or narrow cors_origins to the exact origins that "
                    "may reach it."
                )
        return self

    @property
    def loopback_only(self) -> bool:
        """Whether the configured bind keeps the service off the network.

        Published because a caller reading a response should be able to tell
        whether the service it is talking to is reachable by anything other than
        this machine — the safety property Section 8.4 relies on, exposed as a
        value rather than left to be inferred from the host string.
        """
        return self.host in {"127.0.0.1", "localhost", "::1"}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    openbb: OpenBBSettings
    country: CountrySettings
    policy: PolicySettings
    phillips: PhillipsSettings
    production_function: ProductionFunctionSettings
    inflation: InflationSettings
    transmission: TransmissionSettings
    gdp_gdi: GdpGdiSettings
    gdp_nowcast: GdpNowcastSettings
    auction_demand: AuctionDemandSettings
    credit_spread: CreditSpreadSettings
    beveridge: BeveridgeSettings
    labor: LaborSettings
    risk: RiskSettings
    kelly: KellySettings
    instrument_selection: InstrumentSelectionSettings
    curve_trade: CurveTradeSettings
    cross_market_rv: CrossMarketRVSettings
    invalidation: InvalidationSettings
    catalyst_calendar: CatalystCalendarSettings
    scenario_distribution: ScenarioDistributionSettings
    bond_math: BondMathSettings
    yield_curve: YieldCurveSettings
    regime: RegimeSettings
    scorecard: ScorecardSettings
    convergence: ConvergenceSettings
    policy_mix: PolicyMixSettings
    qe_qt: QEStanceSettings
    minsky: MinskySettings
    probability: ProbabilitySettings
    leading_indicator: LeadingIndicatorSettings
    bayesian: BayesianSettings
    fci: FCISettings
    data: DataSettings
    validation: ValidationSettings
    confidence: ConfidenceSettings
    api: ApiSettings
    snapshot_fields: dict[str, list[str]]

    def scalar(self, path: str) -> float:
        """Fetch a ``a.b.c`` path whose leaf is a ``{value: <number>}`` envelope.

        Convenience for the many config leaves shaped that way. Raises with
        the full path on a miss so a typo produces an actionable message
        rather than a mystifying ``None`` propagating into an arithmetic
        expression.

        Accepts BOTH envelope spellings that appear in ``settings.yaml``: a raw
        mapping (``{value: 1.5, calibration_status: ...}``) and a validated
        ``CalibratedValue`` model. The model case was a real defect — every
        block whose fields were declared as ``CalibratedValue`` in this module
        was unreachable via ``scalar()``, and the failure surfaced only when a
        model tried to read one, not at load time.
        """
        node = self._resolve(path)
        if isinstance(node, CalibratedValue):
            return float(node.value)
        if isinstance(node, dict) and "value" in node:
            return float(node["value"])
        if isinstance(node, int | float):
            return float(node)
        raise KeyError(
            f"Config path '{path}' does not resolve to a scalar value; got {type(node).__name__}"
        )

    def calibrated(self, path: str) -> CalibratedValue:
        """Fetch a path as a full ``CalibratedValue`` envelope."""
        node = self._resolve(path)
        if not isinstance(node, dict):
            raise KeyError(f"Config path '{path}' is not a calibrated envelope.")
        return CalibratedValue.model_validate(node)

    def is_calibrated(self, path: str) -> bool:
        """Whether a config leaf is calibrated or an illustrative placeholder.

        Consumed as ``ConfidenceInputs.is_heuristic_not_calibrated`` so that a
        model which leans on a placeholder reports LOW confidence about it,
        rather than inheriting the placeholder's apparent precision.

        Handles BOTH spellings of a calibrated leaf: a validated
        ``CalibratedValue`` model and a raw mapping. Checking only the mapping
        was a real defect with a silent, systematic consequence — every block
        whose fields were typed as ``CalibratedValue`` reported
        ``is_calibrated() == False``, so models leaning on illustrative
        placeholders received NO heuristic penalty. The misreporting was in the
        safe-looking direction (confidence too high), which is exactly the
        direction Section 22.8 exists to prevent.
        """
        node = self._resolve(path)
        if isinstance(node, CalibratedValue):
            return node.calibration_status not in {None, "uncalibrated_illustrative"}
        if isinstance(node, dict):
            return node.get("calibration_status") not in {None, "uncalibrated_illustrative"}
        return False

    def _resolve(self, path: str) -> Any:
        node: Any = self
        for part in path.split("."):
            if isinstance(node, BaseModel):
                if not hasattr(node, part):
                    raise KeyError(f"Config path '{path}' has no component '{part}'.")
                node = getattr(node, part)
            elif isinstance(node, dict):
                if part not in node:
                    raise KeyError(f"Config path '{path}' has no component '{part}'.")
                node = node[part]
            else:
                raise KeyError(
                    f"Config path '{path}' cannot descend into {type(node).__name__} at '{part}'."
                )
        return node


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Required config file missing: {path}. "
            f"Settings are not defaulted in code — see AGENTS.md Section 21.1."
        )
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse to a mapping (got {type(data).__name__}).")
    return data


@lru_cache(maxsize=1)
def get_settings(config_dir: Path | None = None) -> Settings:
    """Load and validate ``config/settings.yaml``. Cached per process."""
    base = config_dir or (project_root() / "config")
    env_path = project_root() / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    raw = _load_yaml(base / "settings.yaml")
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_registry(config_dir: Path | None = None) -> SeriesRegistry:
    """Load and validate ``config/series_registry.yaml``. Cached per process."""
    base = config_dir or (project_root() / "config")
    raw = _load_yaml(base / "series_registry.yaml")
    return SeriesRegistry.model_validate(raw)


def env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable, honouring the ``.env`` file.

    Secrets (API keys) live here, never in YAML — YAML is committed, ``.env``
    is not.
    """
    return os.environ.get(name, default)
