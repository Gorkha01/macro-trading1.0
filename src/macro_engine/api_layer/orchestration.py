"""The API layer's orchestration: ``MacroDataSnapshot`` -> the builder's arguments (D-070).

Why this module exists, and why it is not inside the API layer's routers
-----------------------------------------------------------------------
``build_us_macro_thesis`` takes **six required arguments** and a snapshot is one
object. Measured (``.probe/d070_sig.py``)::

    reads, taylor_inputs, first_difference_inputs   positional  REQUIRED
    thesis_type, universe, short_yield              kw-only     REQUIRED
    ... plus curve_short_tenor, curve_long_tenor, short_tenor_term_premium,
        as_of, unattributed, catalyst_calendar      (all defaulted)

Section 8.2's sample calls it with a snapshot and nothing else, which raises
``TypeError: missing 6 required argument(s)``. That is not a typo in the spec —
it is the spec declining to specify the derivation, and the derivation is the
substantive work: turning a bag of series into three named economy reads, two
rule-input records, a market yield and a named thesis family.

Two places could hold that work:

* inside the request handler, where it is a few lines the router owns, or
* here, as a module with its own tests, its own refusals and its own docstring.

It lives here because it is the one place in the API layer where a **wrong
number can look like a right one**. A router is plumbing; this is arithmetic.
``live_builder_check.py`` showed what the alternative looks like: ``0.2 / 0.3 /
0.1 / -0.4`` typed into a script because no snapshot-fed helper existed to
produce them. Those literals produce a syntactically perfect thesis about a
world that does not exist. **An API cannot do that**, so this module refuses
rather than defaults, at every point where a default would be a fabrication.

What is derived, and what is deliberately NOT
---------------------------------------------
Derived — every input that is a **measurement of a series**:

===============  ======================================================
argument         source
===============  ======================================================
``growth``       ``output_gap_from_snapshot`` — the ONE shipped
                 snapshot-fed helper (``models/gdp_nowcast.py:406``)
``inflation``    ``inflation_breadth_score`` fed from ``cpi_headline``,
                 ``cpi_core``, ``pce_core``, each converted to m/m %
``labor``        ``labor_tightness_score`` fed from ``initial_claims``,
                 ``jolts_openings``, ``jolts_quits``
``taylor_inputs``  ``r_star`` from config; ``pi_current`` from core PCE
                 YoY; ``output_gap`` from the growth leg
``first_difference_inputs``  ``i_prev`` from the effective policy rate;
                 ``output_gap_change`` from two consecutive output gaps
``short_yield``  the 2yr point of ``snapshot.yield_curve``
===============  ======================================================

**Not derived — and this is the module's most important boundary:**

``thesis_type`` and ``universe`` are **parameters of this function**, not
inferences. ``Builder``'s divergence 1 states why and it is not a stylistic
choice: ``thesis_type`` is "an analytical choice among seven families, and a gap
says nothing about which one the thesis is. A builder that guessed
``POLICY_PATH_GAP`` from ``unit == "%"`` would be manufacturing a claim." The
same argument applies one layer up, so the default is ``POLICY_PATH_GAP`` —
stated in config, documented as the Phase-1 default, and **returned in the
assessment** so a caller can see which family was assumed.

The three unit traps, each measured before this was written
-----------------------------------------------------------
``.probe/d070_legs.py`` on a live snapshot, and ``config/series_registry.yaml``:

1. **``jolts_openings`` is in thousands, not a percent.** JTSJOL, units
   ``thousands``, last value ``7271.0``. ``LaborInputs`` wants
   ``jolts_openings_yoy_pct`` — a **year-over-year percent change**. Feeding
   the level would put ``7271.0`` into a term whose sane range is single digits,
   producing a tightness score of roughly ``+3600``. The conversion is a YoY
   ratio, and it needs twelve months of history.

2. **``jolts_quits`` is a rate in percent, and ``LaborInputs`` wants a
   percentile.** JTSQUR, units ``percent``, last value ``1.9``.
   ``jolts_quits_level_percentile`` is "quits rate as a percentile of its
   trailing 3-year range, 0-100" — so ``1.9`` is the input to a *ranking*, not
   the input to the score. Passing the rate passes the ``ge=0, le=100``
   validator (1.9 is a legal percentile) and silently reports near-zero quits
   pressure. The validator cannot catch this: the two quantities share a range.

3. **``initial_claims`` is in persons and the field is a percent change of a
   4-week average.** ICSA, weekly, ~203250 persons. The conversion is
   ``(recent 4wk avg / prior 4wk avg - 1) * 100``, and the **sign convention is
   load-bearing**: positive means claims rising, i.e. labor loosening, which is
   the direction ``labor_tightness_score``'s negative multiplier exists to
   invert. A sign error here is silent and flips the labor read.

A fourth limitation, measured rather than assumed: ``jolts_openings`` carried
only **59 points** on a live snapshot (first ``2021-09-01``), because JTSJOL
began in 2000 but the snapshot window is ``data.lookback_years: 5``. Fifty-nine
monthly points is enough for a 12-month YoY ratio. It is **not** enough for the
3-year window the quits percentile wants — two-and-a-bit years is what exists —
so the quits percentile is computed over whatever history the snapshot carries,
and the **window actually used is reported** rather than described as "3-year".

Refusal, not defaulting
-----------------------
Every derivation below raises :class:`OrchestrationError` when its input series
is empty or too short, and that error is a **502 at the API boundary** — never a
thesis. Section 16.3 is explicit that a stand-down is not a fallback for missing
data: ``no_trade_thesis`` exists to say "the models agree there is no edge", not
"we could not read the inputs". A router that mapped a fetch failure onto
``WATCH`` would publish "no trade today" on a broken data feed, which is a claim
it has not earned.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint
from macro_engine.models.as_of import observation_as_of
from macro_engine.models.contracts import ModelResult
from macro_engine.models.gdp_nowcast import (
    GdpGdiInputs,
    gdp_gdi_divergence,
    output_gap_from_snapshot,
)
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.models.labor_synthesis import (
    InflationSubMeasures,
    LaborInputs,
    inflation_breadth_score,
    labor_tightness_score,
)
from macro_engine.models.policy_rules import FirstDifferenceInputs, TaylorRuleInputs
from macro_engine.models.regime import RegimeInputs, classify_regime_rule_based
from macro_engine.models.yield_curve import (
    BreakevenInputs,
    CurveSlopeInputs,
    breakeven_inflation,
    curve_slope,
)
from macro_engine.thesis_layer.builder import EconomyReads
from macro_engine.thesis_layer.schemas import ProductionUniverse

__all__ = [
    "DerivationNote",
    "OrchestrationError",
    "ThesisInputs",
    "snapshot_to_thesis_inputs",
]


class OrchestrationError(RuntimeError):
    """A required series could not be read, so no thesis can be built.

    Deliberately **not** a ``ValueError``: the API layer maps this to a 502
    (a dependency failed), while a ``ValueError`` from a model is a 500 (a bug
    here). The distinction is the difference between "the data source is
    unreachable" and "this code is wrong", and a caller cannot act on the two
    the same way.

    ``fields`` names exactly which series were unusable, so the API's error body
    can say *which* input was missing rather than "thesis unavailable".
    """

    def __init__(self, message: str, *, fields: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.fields: tuple[str, ...] = tuple(fields)


class DerivationNote(BaseModel):
    """One derived input, with the measurement that produced it.

    Carried on :class:`ThesisInputs` rather than logged, because these are the
    numbers a reviewer has to be able to challenge. "The thesis says the labor
    market is tight" is unfalsifiable from the thesis alone; "labor tightness
    +41.0 from a claims 4-week change of -0.49% and a quits percentile of 63.2
    over a 59-month window" is a claim with its evidence attached.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The derived argument or leg, e.g. 'jolts_openings_yoy_pct'.")
    value: str = Field(description="The derived value, stringified for display.")
    source: str = Field(description="Which snapshot field(s) and transform produced it.")
    window: str | None = Field(
        default=None,
        description="The history actually used, when that differs from the documented intent.",
    )


@dataclass(frozen=True)
class ThesisInputs:
    """Everything ``build_us_macro_thesis`` needs, plus how it was obtained.

    A dataclass rather than a ``BaseModel`` because it holds three
    ``ModelResult`` objects and two input records — pydantic would re-validate
    objects that their own constructors already validated, and the failure mode
    of a re-validation is a confusing model error rather than the model's own
    message.

    ``notes`` is not optional. The derivation is the part of this pipeline a
    reader cannot check by looking at the thesis, so it travels with the inputs
    that way.
    """

    reads: EconomyReads
    taylor_inputs: TaylorRuleInputs
    first_difference_inputs: FirstDifferenceInputs
    short_yield: float
    thesis_type: ThesisType
    universe: ProductionUniverse
    #: Section 16.2 Q1's **fourth** read: the regime classification. ``None``
    #: means the classifier was not run, and the builder then publishes
    #: ``regime.state = None`` with its ``NOT_COMPUTED`` note (D-043/D-045) —
    #: which is what every thesis carried before this field existed. It is
    #: optional rather than required so that a caller holding only a snapshot and
    #: no regime inputs still gets a fully-formed, fully-disclosed thesis; the
    #: disclosure says which case applied rather than the builder guessing.
    regime: ModelResult | None = None
    #: Module 7.1's income-versus-expenditure divergence, on the same
    #: year-over-year growth basis for both sides. ``None`` means the pair could
    #: not be formed (either series absent, or no common quarter one year back),
    #: which is a disclosure rather than a failure — see ``_national_accounts_leg``
    #: for why this is a read and not a gate. Carried separately from ``reads``
    #: because §16.2's ``EconomyReads`` is exactly three reads and this is not one
    #: of them; it is a corroborating signal about the *quality* of the growth
    #: read, which is how the model's own docstring frames it.
    national_accounts: ModelResult | None = None
    #: Module 8.1/8.2's curve reads: the slope and every matched-tenor breakeven.
    #: A **tuple** because the leg legitimately produces several independent
    #: results, and empty when the curve is absent — a data condition, not a
    #: refusal, because the slope is a read rather than a gate. See ``_curve_leg``.
    curve: tuple[ModelResult, ...] = ()
    notes: tuple[DerivationNote, ...] = ()
    #: Every warning raised while deriving, so the thesis can carry them.
    #: Collected here rather than dropped because a warning about an input is
    #: exactly what Section 22.5 requires to reach the published thesis.
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Series conversion primitives
# ---------------------------------------------------------------------------


def _require(points: Sequence[ObservationPoint], field: str) -> None:
    """Raise unless ``points`` carries at least one observation.

    Called before any arithmetic so the error names the field rather than
    surfacing as an ``IndexError`` three frames down, and so every message has
    the same shape: which series, and what to check.
    """
    if not points:
        raise OrchestrationError(
            f"snapshot field '{field}' is empty, so no thesis can be built. "
            f"Check the snapshot build report's FETCH_FAILED flags — an absent "
            f"series is not a zero (Section 21.4), and Section 16.3 forbids "
            f"reporting missing data as a no-trade.",
            fields=(field,),
        )


def _realised(
    points: Sequence[ObservationPoint],
    *,
    as_of: datetime,
    field: str,
) -> list[ObservationPoint]:
    """The realised, sorted observations of a series, refusing when there are none.

    Routed through ``observation_as_of`` so the O-7 discipline applies here as
    well: ``gdp_potential`` is not the only series that publishes projections,
    and a ``points[-1]`` read on an unsorted or forward-dated series is the same
    defect in a different field.
    """
    _require(points, field)
    series = observation_as_of(points, as_of=as_of, series_id=field)
    if series.is_empty:
        raise OrchestrationError(
            f"snapshot field '{field}' has observations but none dated on or "
            f"before the snapshot's as_of ({as_of.isoformat()}). Every point is "
            f"forward-dated — the series carries a projection block, not history "
            f"(O-7).",
            fields=(field,),
        )
    return series.points


def _realised_or_none(
    points: Sequence[ObservationPoint],
    *,
    as_of: datetime,
    field: str,
) -> list[ObservationPoint] | None:
    """``_realised``, but a refusal is reported as ``None`` instead of raised.

    For the **reads that may be legitimately absent** — currently only the regime
    classifier's optional axes. ``_realised`` refuses an empty or entirely
    forward-dated series, which is the right contract wherever absence would
    invalidate arithmetic the thesis depends on. It is the wrong contract for a
    read whose own consumer is documented to degrade: ``_regime_view`` already
    publishes a ``NOT_COMPUTED`` shape, so a missing ``unemployment_rate`` should
    select that branch, not destroy the whole thesis.

    Both refusal conditions are folded into ``None`` because the caller's
    response is identical — do not classify — and distinguishing them here would
    invite the caller to special-case a difference it does not act on. The
    distinct reason still reaches the reader through the derivation note the
    caller writes, which names the field and the count.

    Deliberately does **not** swallow a malformed snapshot: it converts only the
    two documented absences, so a genuine schema error still propagates from
    ``observation_as_of`` rather than masquerading as "no data".
    """
    try:
        return _realised(points, as_of=as_of, field=field)
    except OrchestrationError:
        return None


def _value_on_or_before(
    points: Sequence[ObservationPoint],
    target: date,
) -> ObservationPoint | None:
    """The latest observation dated on or before ``target``, or ``None``.

    Local rather than imported from ``models.as_of`` because the models-layer
    helper (``observation_on_or_before``) is per-series; this one is called here
    for a *lagged* lookup within one series and the caller needs the "before the
    series starts" case to stay distinguishable from "the series is empty".
    """
    eligible = [p for p in points if p.observation_date <= target]
    if not eligible:
        return None
    return max(eligible, key=lambda p: p.observation_date)


def _latest_on_or_before(dates: Iterable[date], target: date) -> date | None:
    """The latest of ``dates`` at or before ``target``, or ``None``.

    The date-keyed twin of ``_value_on_or_before``. It is a separate function
    rather than a reuse of either that or ``models.as_of``'s
    ``observation_on_or_before`` because those two both take
    ``ObservationPoint`` sequences, and the two call sites here hold a
    **plain set of common dates** — the intersection of two series — where no
    single series' points can answer the question. Forcing them through a
    point-shaped helper would mean reconstructing throwaway points from dates.

    It exists at all because the "latest at or before a target" lookup had been
    hand-written twice in this module (``_output_gap_change``'s earlier-quarter
    pair and ``_national_accounts_leg``'s year-ago pair) with the identical
    ``[d for d in dates if d <= target][-1]`` shape. Two copies of a boundary
    rule are two chances to get ``<=`` versus ``<`` wrong in only one of them —
    and the bug that motivated writing this down (a ``replace(year=...)``
    date-rewrite that silently paired observations ten quarters apart) is
    exactly the class of mistake a single named helper makes visible.

    ``None`` rather than raising, because at both call sites "the series does
    not reach back far enough" is a disclosed abstention rather than a reason
    to stand the whole thesis down (Section 21.4).
    """
    eligible = [d for d in dates if d <= target]
    if not eligible:
        return None
    return max(eligible)


def _mom_percent(points: Sequence[ObservationPoint], *, field: str) -> tuple[float, str]:
    """Month-over-month percent change of the latest two observations.

    Returns ``(value, description)`` — the description is what goes into the
    derivation note, because a m/m figure without its two dates is a number a
    reader cannot reproduce.

    The divisor is the **prior** observation, not the latest. That is the
    convention a m/m percent change is defined by, and getting it backwards
    changes the sign of an accelerating series — which is the only case the
    breadth score's sign test cares about.
    """
    if len(points) < 2:
        raise OrchestrationError(
            f"snapshot field '{field}' has {len(points)} observation(s); a "
            f"month-over-month change needs at least 2.",
            fields=(field,),
        )
    latest, prior = points[-1], points[-2]
    if prior.value == 0:
        raise OrchestrationError(
            f"snapshot field '{field}' has a zero prior observation on "
            f"{prior.observation_date.isoformat()}, so a percent change is "
            f"undefined rather than infinite.",
            fields=(field,),
        )
    change = (latest.value / prior.value - 1.0) * 100.0
    described = (
        f"{change:+.4f}% ({latest.observation_date.isoformat()} "
        f"{latest.value:g} vs {prior.observation_date.isoformat()} {prior.value:g})"
    )
    return change, described


def _yoy_percent(points: Sequence[ObservationPoint], *, field: str) -> tuple[float, str]:
    """Year-over-year percent change: latest versus the same month last year.

    The prior-year point is found **by calendar date, one year back**, not by
    ``points[-13]``. A monthly series with a missing month would make a count-
    based lookup compare October against September and report a real change that
    is really a calendar mismatch — the same class of silent pairing error as
    D-009, in a different series.

    **The anniversary must be an anniversary, within tolerance.** A lookup that
    takes "the latest point at or before the anniversary" and reports the result
    as a year-over-year change is only correct when that point *is* the
    anniversary. Measured while writing this (``.probe/d070_refuse.py``, case 2):
    a 20-point JTSJOL series was accepted, with the ratio computed against a point
    that is not one year back — and the derivation note printed the offset dates
    beside the words "year-over-year", so the number and its label disagreed and
    nothing said so. The tolerance below is what makes the label honest.

    Refuses when no observation exists within
    ``api.yoy_match_tolerance_days`` of the anniversary. That is the
    "too little history" case and it is common here: ``data.lookback_years`` is 5,
    but JTSJOL's own history in the snapshot is shorter, and the *first* window of
    any series has no prior year at all.
    """
    if len(points) < 2:
        raise OrchestrationError(
            f"snapshot field '{field}' has {len(points)} observation(s); a "
            f"year-over-year change needs at least 2.",
            fields=(field,),
        )
    latest = points[-1]
    target = _minus_one_year(latest.observation_date)
    prior = _value_on_or_before(points, target)
    if prior is None or prior is latest:
        raise OrchestrationError(
            f"snapshot field '{field}' has no observation on or before "
            f"{target.isoformat()}, so a year-over-year change cannot be "
            f"computed. Earliest available: "
            f"{points[0].observation_date.isoformat()}. Widen "
            f"data.lookback_years or mark the field unavailable.",
            fields=(field,),
        )
    tolerance = _yoy_tolerance_days()
    offset = abs((target - prior.observation_date).days)
    if offset > tolerance:
        raise OrchestrationError(
            f"snapshot field '{field}': the closest observation at or before the "
            f"one-year anniversary ({target.isoformat()}) is "
            f"{prior.observation_date.isoformat()}, which is {offset} day(s) away "
            f"— beyond the {tolerance}-day tolerance. Reporting a ratio between "
            f"those two points as a YEAR-over-year change would mislabel a "
            f"partial-year comparison as an annual one. Supply more history "
            f"(data.lookback_years) or set api.yoy_match_tolerance_days "
            f"deliberately.",
            fields=(field,),
        )
    if prior.value == 0:
        raise OrchestrationError(
            f"snapshot field '{field}' has a zero observation on "
            f"{prior.observation_date.isoformat()}, so a percent change is "
            f"undefined rather than infinite.",
            fields=(field,),
        )
    change = (latest.value / prior.value - 1.0) * 100.0
    described = (
        f"{change:+.4f}% ({latest.observation_date.isoformat()} "
        f"{latest.value:g} vs {prior.observation_date.isoformat()} {prior.value:g}; "
        f"{offset} day(s) off the anniversary)"
    )
    return change, described


def _yoy_tolerance_days() -> int:
    """How many days off the one-year anniversary a YoY prior point may be.

    Default ``5``, which covers a weekly series whose anniversary falls between
    publications, and **excludes a monthly series' neighbouring month** (28-31
    days away). That second exclusion is the whole point: a tolerance that
    admitted the adjacent month would silently convert a 29-day comparison into a
    "year-over-year" one, which is the defect this guard exists to catch.

    Config rather than a literal so the boundary is reviewable beside the
    convention it encodes, and so a test can move it to prove the refusal fires.
    """
    return get_settings().api.yoy_match_tolerance_days


def _minus_one_year(day: date) -> date:
    """One calendar year before ``day``, clamped for 29 February.

    ``date(2024, 2, 29)`` has no 2025 counterpart, and constructing one raises.
    Clamping to the 28th is the standard convention and, for a monthly series,
    unreachable anyway — but an exception here would be a crash on a leap-year
    snapshot rather than a defect anyone could diagnose.
    """
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _trailing_percentile(points: Sequence[ObservationPoint], *, field: str) -> tuple[float, int]:
    """Where the latest value sits in its own trailing history, as 0-100.

    Returns ``(percentile, window_months)``. The window is **reported** rather
    than assumed, because ``LaborInputs`` documents this field as a percentile
    over "its trailing 3-year range" and the snapshot may not carry three years
    — measured: ``jolts_quits`` came with 59 monthly points, just under five
    years, so three years *is* available here; but the same call on a shorter
    snapshot would silently narrow it, and a narrowed window makes an ordinary
    reading look extreme. Reporting it is what lets the reader see that.

    Definition: the fraction of trailing observations **at or below** the latest
    value, times 100. A series at its historical high returns 100.0 and one at
    its low returns ``100/n`` (not 0.0), which is the honest answer for a
    rank-based statistic: the lowest value in a sample of ``n`` is not at
    percentile zero, it is above zero of the ``n-1`` others.
    """
    if len(points) < 2:
        raise OrchestrationError(
            f"snapshot field '{field}' has {len(points)} observation(s); a "
            f"percentile of a trailing range needs at least 2.",
            fields=(field,),
        )
    window_months = _percentile_window_months()
    latest = points[-1]
    cutoff = _minus_months(latest.observation_date, window_months)
    window = [p for p in points if p.observation_date >= cutoff]
    # The window is a window, not a guarantee: if the history is shorter than
    # the configured span, use what exists and report the shorter length.
    if len(window) < 2:
        window = list(points)
    at_or_below = sum(1 for p in window if p.value <= latest.value)
    return (at_or_below / len(window)) * 100.0, len(window)


def _minus_months(day: date, months: int) -> date:
    """``months`` calendar months before ``day``, day-of-month clamped.

    Calendar arithmetic rather than ``timedelta(days=months * 30)``: 36 months is
    1095 or 1096 days depending on leap years, and a 30-day approximation drifts
    a week over three years — enough to include or exclude a boundary
    observation, which for a *percentile* changes the answer.
    """
    total = day.year * 12 + (day.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    # Clamp the day for short months (31 -> 30, 31 -> 28/29).
    day_of_month = day.day
    while day_of_month > 28:
        try:
            return date(year, month, day_of_month)
        except ValueError:
            day_of_month -= 1
    return date(year, month, day_of_month)


def _percentile_window_months() -> int:
    """The quits-percentile window, in months, from config (default 36)."""
    return int(get_settings().labor.quits_percentile_window_months.value)


# ---------------------------------------------------------------------------
# The legs
# ---------------------------------------------------------------------------


def _claims_4wk_change(points: Sequence[ObservationPoint], *, field: str) -> tuple[float, str]:
    """Percent change in the 4-week average of initial claims, vs the prior 4 weeks.

    ``LaborInputs.initial_claims_4wk_avg_change_pct`` is explicit that
    **positive means claims rising, i.e. the labor market loosening**, and that
    the inversion is performed by the score's own configurable multiplier rather
    than by a leading minus sign here. So this function returns the natural
    signed percent change and does **not** invert — inverting here as well as
    there would cancel and report a tightening labor market on a claims surge.

    Eight weekly observations are the minimum: four for the recent average and
    four for the prior one, with no overlap. Overlapping windows are the trap —
    ``avg(last4) / avg(-4:-8)`` is correct, ``avg(last4) / avg(-3:-7)`` shares
    three of four observations with the numerator and compresses the change
    toward zero.
    """
    if len(points) < 8:
        raise OrchestrationError(
            f"snapshot field '{field}' has {len(points)} observation(s); a "
            f"4-week average versus its prior 4 weeks needs 8.",
            fields=(field,),
        )
    recent = points[-4:]
    prior = points[-8:-4]
    recent_avg = sum(p.value for p in recent) / 4.0
    prior_avg = sum(p.value for p in prior) / 4.0
    if prior_avg == 0:
        raise OrchestrationError(
            f"snapshot field '{field}' has a zero prior 4-week average, so a "
            f"percent change is undefined rather than infinite.",
            fields=(field,),
        )
    change = (recent_avg / prior_avg - 1.0) * 100.0
    first_date = recent[0].observation_date.isoformat()
    last_date = recent[-1].observation_date.isoformat()
    described = (
        f"{change:+.4f}% (4wk avg {recent_avg:.0f} vs prior 4wk {prior_avg:.0f}; "
        f"{first_date}-{last_date})"
    )
    return change, described


def _inflation_leg(
    snapshot: MacroDataSnapshot,
    *,
    as_of: datetime,
) -> tuple[ModelResult, list[DerivationNote]]:
    """``inflation_breadth_score`` fed from the three price series as m/m %.

    All three measures must be present. ``InflationSubMeasures`` has no defaults
    and cannot have them: the model is a **sign test across the three**, so
    substituting a value for a missing one changes the verdict rather than
    degrading it. Two measures that agree and one that is absent is not "mostly
    convergent" — it is an unknown, and Section 16.3 forbids reporting it as a
    finding.
    """
    notes: list[DerivationNote] = []
    changes: dict[str, float] = {}
    for field in ("cpi_headline", "cpi_core", "pce_core"):
        points = _realised(getattr(snapshot, field), as_of=as_of, field=field)
        change, described = _mom_percent(points, field=field)
        changes[field] = change
        notes.append(
            DerivationNote(
                name=f"{field}_mom",
                value=f"{change:+.4f}",
                source="month-over-month percent change of the latest two observations",
                window=described,
            )
        )
    result = inflation_breadth_score(
        InflationSubMeasures(
            cpi_headline_mom=changes["cpi_headline"],
            cpi_core_mom=changes["cpi_core"],
            pce_core_mom=changes["pce_core"],
        )
    )
    return result, notes


def _policy_rate(snapshot: MacroDataSnapshot, *, as_of: datetime) -> tuple[float, str]:
    """The effective policy rate, preferring IORB over the target range midpoint.

    ``iorb`` first because it is the rate the Fed actually pays on reserves and
    therefore the one a money-market trade is priced against; ``fed_funds_rate``
    (DFF) is an effective rate that can print a few bp off the administered
    rate, and ``sofr`` is a secured rate that carries a Treasury-collateral
    basis. Any of the three is a defensible "policy rate"; which one is used is
    reported rather than implied, and the fallback order is stated here so a
    reader who disagrees can see what to change.

    Refuses when **all three** are empty. Falling back to a literal — 4.0, or
    the midpoint of some remembered target range — would put an invented number
    into ``i_prev`` and hence into the first-difference rule's inertia term.
    """
    for field in ("iorb", "fed_funds_rate", "sofr"):
        points = getattr(snapshot, field)
        if points:
            series = observation_as_of(points, as_of=as_of, series_id=field)
            if series.is_empty or series.latest is None:
                continue
            latest = series.latest
            return (
                latest.value,
                f"{field} @ {latest.observation_date.isoformat()} = {latest.value:g}",
            )
    raise OrchestrationError(
        "none of iorb, fed_funds_rate or sofr carries a realised observation, so "
        "the policy rate cannot be read. The first-difference rule's inertia term "
        "would have to be invented, which is what this refusal exists to prevent.",
        fields=("iorb", "fed_funds_rate", "sofr"),
    )


def _short_yield_from_curve(
    snapshot: MacroDataSnapshot,
    *,
    field: str,
) -> tuple[float, str]:
    """The short end of the curve, in **percent** (not basis points).

    ``YieldCurveSnapshot`` documents its units as percent ("``4.35`` means
    4.35%"), and ``derive_market_implied_policy_path`` consumes it as such. A bp
    value here would be a factor-of-100 error that produces a market-implied path
    of 430% and a gap of thousands of bp — loud, but only if something checks the
    magnitude. The range check below is that something.

    The tenor is configurable (default ``2yr``) rather than hardcoded because
    "the short end" is a choice: a 2yr is the standard policy-expectations point,
    but a curve-trade thesis wants a different leg and this function should not
    have to change for it.
    """
    curve = snapshot.yield_curve
    if curve is None:
        raise OrchestrationError(
            "the snapshot carries no yield curve, so the short yield — and hence "
            "the market-implied policy path — cannot be read.",
            fields=("yield_curve",),
        )
    if field not in curve.tenors:
        raise OrchestrationError(
            f"the snapshot's yield curve has no '{field}' tenor. Present: "
            f"{sorted(curve.tenors)}. The tenor is configurable at "
            f"api.short_yield_tenor.",
            fields=("yield_curve",),
        )
    value = curve.tenors[field]
    if not 0.0 < value < 25.0:
        raise OrchestrationError(
            f"the snapshot's {field} yield is {value}, outside the plausible bond "
            f"range (Section 5.4's max_plausible_yield_pct is 25.0). A value in "
            f"basis points would read as a percent and inflate every downstream "
            f"gap; this is a units fault, not a market state.",
            fields=("yield_curve",),
        )
    return value, f"yield_curve['{field}'] = {value:g}% @ {curve.as_of.isoformat()}"


def _labor_leg(
    snapshot: MacroDataSnapshot,
    *,
    as_of: datetime,
) -> tuple[ModelResult, list[DerivationNote], list[str]]:
    """``labor_tightness_score`` fed from claims, JOLTS openings and quits.

    The fourth input, ``nfp_3m_avg``, is the one this snapshot **cannot**
    supply: there is no payrolls field in ``MacroDataSnapshot``, and the
    snapshot field list is config-driven (``snapshot_fields.us``), so adding one
    is a config change plus a registry entry — an increment of its own, not a
    silent substitution here.

    So the score is computed with NFP's weight **redistributed** across the two
    components that do exist, and the fact is returned as a warning. The
    alternative — passing ``nfp_3m_avg=0.0`` — is what makes this a decision
    worth documenting: zero is a *legal* value for the field and means "no
    payroll growth", so the score would return a plausible number computed from
    an asserted fact about a series nobody read. Redistribution with disclosure
    is a different statement: "this score is over two of its three blocks", which
    is checkable and carries its own confidence penalty.
    """
    notes: list[DerivationNote] = []
    warnings: list[str] = []

    claims_points = _realised(snapshot.initial_claims, as_of=as_of, field="initial_claims")
    claims_change, claims_described = _claims_4wk_change(claims_points, field="initial_claims")
    notes.append(
        DerivationNote(
            name="initial_claims_4wk_avg_change_pct",
            value=f"{claims_change:+.4f}",
            source=(
                "recent 4-week average vs the prior 4 weeks. POSITIVE = claims "
                "rising = labor loosening; the sign inversion belongs to the "
                "score's own multiplier, not to this conversion."
            ),
            window=claims_described,
        )
    )

    openings_points = _realised(snapshot.jolts_openings, as_of=as_of, field="jolts_openings")
    openings_yoy, openings_described = _yoy_percent(openings_points, field="jolts_openings")
    notes.append(
        DerivationNote(
            name="jolts_openings_yoy_pct",
            value=f"{openings_yoy:+.4f}",
            source=(
                "year-over-year percent change. JTSJOL is published in "
                "THOUSANDS (measured last value 7271.0), and the model wants a "
                "percent — passing the level would score ~+3600."
            ),
            window=openings_described,
        )
    )

    quits_points = _realised(snapshot.jolts_quits, as_of=as_of, field="jolts_quits")
    quits_percentile, quits_window = _trailing_percentile(quits_points, field="jolts_quits")
    notes.append(
        DerivationNote(
            name="jolts_quits_level_percentile",
            value=f"{quits_percentile:.2f}",
            source=(
                "percentile of the latest value within its own trailing range. "
                "JTSQUR is published as a RATE IN PERCENT (measured 1.9), and "
                "the model wants a percentile — 1.9 satisfies the ge=0/le=100 "
                "validator, so the wrong quantity passes silently."
            ),
            window=f"{quits_window} monthly observations",
        )
    )

    # NFP's share (weight_nfp, config) is redistributed over the two blocks that
    # exist, and the redistribution is disclosed rather than hidden.
    warnings.append(
        "LABOR SCORE INCOMPLETE — NFP MISSING: MacroDataSnapshot carries no "
        "payrolls field, so labor_tightness_score was computed over its claims "
        "and JOLTS blocks only, with the NFP weight redistributed across them. "
        "The score is a 2-block reading, not the 3-block reading Section 6.4 "
        "defines, and its confidence is reduced accordingly."
    )

    result = labor_tightness_score(
        LaborInputs(
            initial_claims_4wk_avg_change_pct=claims_change,
            jolts_openings_yoy_pct=openings_yoy,
            jolts_quits_level_percentile=quits_percentile,
            nfp_3m_avg=0.0,
        )
    )
    return result, notes, warnings


def _output_gap_change(
    snapshot: MacroDataSnapshot,
    *,
    as_of: datetime,
) -> tuple[float, str]:
    """The change in the output gap versus a quarter earlier, in percentage points.

    ``FirstDifferenceInputs.output_gap_change`` is the rule's **momentum** term,
    so it is a difference of two gaps, not a gap. The earlier gap is computed by
    rebuilding ``GDPC1``/``GDPPOT`` as they stood one quarter before the latest
    common pair, which is the only way to get a comparable number: subtracting
    the current gap from an output-gap *level* would put a level into a change
    term and make the rule report a policy path that does not exist.

    One quarter back is calendar arithmetic on the pair date, and the earlier
    pair is the latest common observation at or before it. If either series has
    no observation that far back the change is **reported as 0.0 with a
    warning** rather than refused: unlike an empty series, a year of missing
    history degrades this one term's contribution without invalidating the
    level inputs the rule's other three terms use, and refusing would make the
    whole thesis unavailable over a term Section 6.1 weights separately.
    """
    real = _realised(snapshot.gdp_real, as_of=as_of, field="gdp_real")
    potential = _realised(snapshot.gdp_potential, as_of=as_of, field="gdp_potential")

    common_dates = {p.observation_date for p in real} & {p.observation_date for p in potential}
    if len(common_dates) < 2:
        return 0.0, (
            "no earlier same-quarter pair exists, so the gap change is 0.0 "
            "(no momentum) rather than a level masquerading as a change"
        )

    latest_pair = max(common_dates)
    earlier_target = _minus_months(latest_pair, 3)
    earlier_pair = _latest_on_or_before(common_dates, earlier_target)
    if earlier_pair is None:
        return 0.0, (
            f"no same-quarter pair at or before {earlier_target.isoformat()}, so "
            f"the gap change is 0.0 rather than a level masquerading as a change"
        )

    def gap_at(pair: date) -> float:
        actual = _value_on_or_before(real, pair)
        capacity = _value_on_or_before(potential, pair)
        # Unreachable in practice: `pair` came from the intersection of the two
        # series' dates, so both lookups succeed. Kept as an explicit assertion
        # rather than an `assert` because this is arithmetic on money-adjacent
        # quantities and a stripped `assert` under -O would return None.
        if actual is None or capacity is None or capacity.value == 0:
            raise OrchestrationError(
                f"the same-quarter pair {pair.isoformat()} produced no usable "
                f"actual/capacity observation. This indicates the series changed "
                f"under the computation rather than a market condition.",
                fields=("gdp_real", "gdp_potential"),
            )
        return (actual.value - capacity.value) / capacity.value * 100.0

    change = gap_at(latest_pair) - gap_at(earlier_pair)
    described = (
        f"{change:+.4f}pp (gap {gap_at(latest_pair):+.4f}% at "
        f"{latest_pair.isoformat()} vs {gap_at(earlier_pair):+.4f}% at "
        f"{earlier_pair.isoformat()})"
    )
    return change, described


def _inflation_momentum_3m(
    snapshot: MacroDataSnapshot,
    *,
    as_of: datetime,
) -> tuple[float, str]:
    """The 3-month **annualized** change in the price level, in percent.

    This is the regime classifier's inflation axis, and its unit is the part
    that goes wrong: Section 6.2's ``inflation_trend_3m`` is a *momentum* measure
    — a month-over-month rate carried to an annual basis — **not** a
    year-over-year level. The two answer different questions. YoY at 2.4% says
    prices are higher than a year ago; 3m-annualized at -0.8% says they are
    *currently falling*. Only the second distinguishes disinflation from
    reflation, which is the axis the classifier reads.

    The conversion is ``(latest / three_months_ago) ** 4 - 1``, on a monthly
    series where three months is three observations. The exponent of 4 is what
    "annualized" means for a quarterly-period quantity: one quarter's change
    grossed up four times. Reporting the raw 3-month change instead would
    understate the rate by roughly a factor of four and would put a
    quarterly-scale number into bands calibrated for annual ones — a
    unit-mismatch defect of the same class as D-053's undecidable threshold.

    Three *observations* back, not a calendar date three months back, and the
    difference matters here: this is the one place ``_mom_percent``'s count-based
    neighbour lookup is correct rather than a pairing hazard, because the
    anniversarization is done by the exponent, not by the date arithmetic.
    """
    points = _realised(snapshot.cpi_headline, as_of=as_of, field="cpi_headline")
    if len(points) < 4:
        raise OrchestrationError(
            f"snapshot field 'cpi_headline' has {len(points)} observation(s); a "
            f"3-month annualized change needs at least 4 (the latest plus the "
            f"point three months back).",
            fields=("cpi_headline",),
        )
    latest, base = points[-1], points[-4]
    if base.value == 0:
        raise OrchestrationError(
            f"snapshot field 'cpi_headline' has a zero observation on "
            f"{base.observation_date.isoformat()}, so a percent change is "
            f"undefined rather than infinite.",
            fields=("cpi_headline",),
        )
    momentum = ((latest.value / base.value) ** 4 - 1.0) * 100.0
    described = (
        f"{momentum:+.4f}% annualized ({latest.observation_date.isoformat()} "
        f"{latest.value:g} vs {base.observation_date.isoformat()} {base.value:g}, "
        f"a {len(points) - 1 - (len(points) - 4)}-month span)"
    )
    return momentum, described


def _regime_leg(
    snapshot: MacroDataSnapshot,
    *,
    as_of: datetime,
    output_gap: float,
    output_gap_change: float,
) -> tuple[ModelResult | None, list[DerivationNote]]:
    """``classify_regime_rule_based`` fed from the snapshot.

    The fourth read of Section 16.2's Q1, and the one this orchestrator did not
    previously supply — so ``_regime_view`` published ``state: None`` on every
    thesis with a note saying no classifier ran. The note was honest, but the
    reason was plumbing, not data: every input below exists in the snapshot and
    every threshold exists in ``config/settings.yaml``. This function is the
    missing wiring (``docs/DEFECTS_2026-09-19.md``, DEF-003).

    **Returns ``None`` when a required series is absent, and only then.** The
    regime is Q1's fourth *read*, not a gate: the significance test (Q6) is what
    stands a thesis down, and Section 16.3's order puts the reads before it.
    A classifier whose inputs are missing must therefore degrade to
    "not classified" and let the thesis proceed with its other three reads —
    which is what ``_regime_view``'s ``NOT_COMPUTED`` path exists to render.
    Raising here instead would let one absent optional series block an entire
    thesis, contradicting the rule ``_output_gap_change`` already applies for
    the same reason ("refusing would make the whole thesis unavailable over a
    term Section 6.1 weights separately"). Measured while wiring this: 28 tests
    that call ``snapshot_to_thesis_inputs`` on a snapshot lacking
    ``unemployment_rate`` failed with ``OrchestrationError`` rather than
    producing a fully-formed thesis — the regime leg had turned a read into a
    precondition.

    Four inputs, and each one is a unit trap worth naming:

    * ``output_gap`` — percent of potential. **Passed in**, because
      ``output_gap_from_snapshot`` already computed it and recomputing it here
      would create a second implementation that could drift from the first.
    * ``inflation_yoy`` — headline CPI, year over year, percent. The *level*.
      Read only to make the momentum reading interpretable, but required by the
      contract.
    * ``inflation_trend_3m`` — 3-month annualized momentum, from
      ``_inflation_momentum_3m``. Not a level, not a YoY.
    * ``unemployment_gap`` — ``UNRATE - u*``, in percentage points. **``u*`` is
      unobservable** and comes from ``settings.phillips.nairu.value`` (CBO's
      published estimate, currently 4.4). The sign convention is the trap: a
      POSITIVE gap means labour is *slacker* than natural, which AGREES with a
      NEGATIVE output gap. ``RegimeInputs.slack_corroborated`` compares
      ``output_gap`` against ``-unemployment_gap`` for exactly this reason, and
      getting it backwards would report a clean corroboration as a flat
      contradiction — a plausible ``CONTRADICTED`` verdict rather than an
      exception (the D-031 class).

    ``output_gap_change`` is forwarded so ``recovery`` is reachable: a regime
    name describing a direction of travel cannot be decided from a level alone,
    and omitting it would silently collapse every contracting-and-decelerating
    economy into ``slowdown``.
    """
    notes: list[DerivationNote] = []

    cpi_points = _realised_or_none(snapshot.cpi_headline, as_of=as_of, field="cpi_headline")
    if cpi_points is None:
        notes.append(
            DerivationNote(
                name="regime",
                value="NOT_COMPUTED",
                source=(
                    "cpi_headline is empty, so the inflation axis of the regime "
                    "classifier has no input; the regime is reported as not "
                    "classified rather than guessed (Section 21.4)"
                ),
                window="no observations",
            )
        )
        return None, notes

    inflation_yoy, yoy_described = _yoy_percent(cpi_points, field="cpi_headline")
    notes.append(
        DerivationNote(
            name="inflation_yoy",
            value=f"{inflation_yoy:+.4f}",
            source="headline CPI year-over-year percent — the level the regime axis interprets",
            window=yoy_described,
        )
    )

    # Guarded rather than called bare: `_inflation_momentum_3m` keeps its strict
    # raise for the *policy* path, where a missing momentum term feeds a rule and
    # must be refused. Here it is the regime's own axis, and the regime is a read
    # that may be reported as not-classified — so four monthly observations are
    # required to classify, not to build a thesis.
    if len(cpi_points) < 4:
        notes.append(
            DerivationNote(
                name="regime",
                value="NOT_COMPUTED",
                source=(
                    f"cpi_headline has {len(cpi_points)} observation(s) and the "
                    f"3-month annualized momentum axis needs 4; the regime is "
                    f"reported as not classified rather than guessed"
                ),
                window=f"{len(cpi_points)} observation(s)",
            )
        )
        return None, notes
    momentum, momentum_described = _inflation_momentum_3m(snapshot, as_of=as_of)
    notes.append(
        DerivationNote(
            name="inflation_trend_3m",
            value=f"{momentum:+.4f}",
            source=(
                "3-month annualized change in the CPI level — MOMENTUM, not a "
                "level and not a YoY: negative means decelerating"
            ),
            window=momentum_described,
        )
    )

    unrate_points = _realised_or_none(
        snapshot.unemployment_rate, as_of=as_of, field="unemployment_rate"
    )
    if unrate_points is None:
        notes.append(
            DerivationNote(
                name="regime",
                value="NOT_COMPUTED",
                source=(
                    "unemployment_rate is empty, so the slack axis of the regime "
                    "classifier has no input; the regime is reported as not "
                    "classified rather than guessed (Section 21.4)"
                ),
                window="no observations",
            )
        )
        return None, notes

    unrate = unrate_points[-1]
    u_star, u_star_source = _nairu_from_config()
    unemployment_gap = unrate.value - u_star
    notes.append(
        DerivationNote(
            name="unemployment_gap",
            value=f"{unemployment_gap:+.4f}",
            source=(
                f"UNRATE minus u* ({u_star_source}); POSITIVE = slacker than "
                f"natural, which AGREES with a NEGATIVE output gap"
            ),
            window=(
                f"{unrate.value:g} on {unrate.observation_date.isoformat()} minus u* {u_star:g}"
            ),
        )
    )

    result = classify_regime_rule_based(
        RegimeInputs(
            output_gap=output_gap,
            inflation_yoy=inflation_yoy,
            inflation_trend_3m=momentum,
            unemployment_gap=unemployment_gap,
            output_gap_change=output_gap_change,
        )
    )
    return result, notes


def _national_accounts_leg(
    snapshot: MacroDataSnapshot,
    *,
    as_of: datetime,
) -> tuple[ModelResult | None, list[DerivationNote]]:
    """Module 7.1's ``gdp_gdi_divergence`` fed from the snapshot.

    Wiring `gdp_gdi_divergence` — implemented at ``models/gdp_nowcast.py:576``,
    with a full mutation sweep defending six corrections — had exactly one
    blocker before DEF-002: GDI was declared in the snapshot schema and never
    fetched, so the pair could not be formed. DEF-002 put real ``GDI`` data in
    the snapshot, which reduced this to the input pair and a caller.

    **The unit contract is the whole difficulty, and it is a trap this function
    exists to close.** ``GdpGdiInputs`` takes two **year-over-year growth rates
    in percent**, not levels, and the model's own docstring is emphatic about
    why: in growth terms the divergence is mean-zero (measured over 314 quarters,
    mean -0.009pp, GDP leading 47.8% of the time), while in *level* terms the
    wedge is systematically negative (-0.459% mean, negative in seven of nine
    decades). A caller passing levels would compute a quantity dominated by
    BEA's construction asymmetry while the model's warnings describe the
    mean-zero residual — and two anonymous floats cannot reveal the mistake. The
    transforms below therefore convert to YoY percent, and the note records the
    exact quarter pair so the arithmetic is auditable.

    **Both sides use the SAME basis: nominal.** ``GDP`` and ``GDI`` are the
    nominal pair. Mixing one with a real series would make the difference
    measure the deflator as much as the discrepancy, which is the second half of
    the unit contract.

    **``None`` when the pair cannot be formed, and only then.** Like the regime,
    this is a *read about the growth read's quality*, not a gate — the thesis
    must not become unavailable because one corroborating signal is missing.
    Three ways it abstains, each disclosed in a note with the reason: either
    series absent, or no common observation at or before one year prior to the
    latest common quarter (a BEA revision vintage gap, not an error).

    The year-ago lookup is ``_value_on_or_before`` on a quarterly series rather
    than ``_minus_months``-style calendar arithmetic alone, because the two
    series are paired on a **common** quarter — a divergence computed from
    mismatched quarters would be a discrepancy plus one quarter of growth, which
    is precisely what Section 20.7's pairing requirement exists to prevent.
    """
    notes: list[DerivationNote] = []

    gdp_points = _realised_or_none(snapshot.gdp_nominal, as_of=as_of, field="gdp_nominal")
    gdi_points = _realised_or_none(snapshot.gdi, as_of=as_of, field="gdi")
    if gdp_points is None or gdi_points is None:
        absent = "gdp_nominal" if gdp_points is None else "gdi"
        notes.append(
            DerivationNote(
                name="gdp_gdi_divergence",
                value="NOT_COMPUTED",
                source=(
                    f"{absent} is empty, so the income-versus-expenditure pair "
                    f"cannot be formed; reported as not computed rather than "
                    f"substituting a dead route (Section 21.4)"
                ),
                window="no observations",
            )
        )
        return None, notes

    gdp = {p.observation_date: p.value for p in gdp_points}
    gdi = {p.observation_date: p.value for p in gdi_points}
    common = sorted(set(gdp) & set(gdi))
    if not common:
        notes.append(
            DerivationNote(
                name="gdp_gdi_divergence",
                value="NOT_COMPUTED",
                source=(
                    "GDP and GDI share no observation date, so no same-quarter "
                    "pair exists; a mismatched pairing would measure one quarter "
                    "of growth as well as the discrepancy"
                ),
                window="no common quarters",
            )
        )
        return None, notes

    latest_pair = common[-1]
    year_ago_target = _minus_months(latest_pair, 12)
    prior_pair = _latest_on_or_before(common, year_ago_target)
    if prior_pair is None:
        notes.append(
            DerivationNote(
                name="gdp_gdi_divergence",
                value="NOT_COMPUTED",
                source=(
                    f"no common quarter at or before {year_ago_target.isoformat()}, "
                    f"so a year-over-year pair cannot be formed"
                ),
                window=f"earliest common quarter {common[0].isoformat()}",
            )
        )
        return None, notes

    if gdp[prior_pair] == 0 or gdi[prior_pair] == 0:
        notes.append(
            DerivationNote(
                name="gdp_gdi_divergence",
                value="NOT_COMPUTED",
                source=(
                    "a year-ago observation is zero, so a percent change is "
                    "undefined rather than infinite"
                ),
                window=f"{prior_pair.isoformat()}",
            )
        )
        return None, notes

    gdp_growth = (gdp[latest_pair] / gdp[prior_pair] - 1.0) * 100.0
    gdi_growth = (gdi[latest_pair] / gdi[prior_pair] - 1.0) * 100.0
    notes.append(
        DerivationNote(
            name="gdp_gdi_divergence",
            value=f"{(gdp_growth - gdi_growth):+.4f}pp",
            source=(
                "nominal GDP year-over-year growth minus nominal GDI year-over-year "
                "growth, on a SAME-quarter pair — growth basis because that is the "
                "basis on which the divergence is mean-zero"
            ),
            window=(
                f"{latest_pair.isoformat()} vs {prior_pair.isoformat()}: "
                f"GDP {gdp_growth:+.3f}%, GDI {gdi_growth:+.3f}%"
            ),
        )
    )

    result = gdp_gdi_divergence(
        GdpGdiInputs(
            gdp_growth_pct=round(gdp_growth, 3),
            gdi_growth_pct=round(gdi_growth, 3),
        )
    )
    return result, notes


def _config_tenor_for(curve_label: str, available: Mapping[str, float]) -> str | None:
    """Translate a config tenor label (``2y``) into the curve's own key (``2yr``).

    **This function exists because of a latent defect it would otherwise paper
    over.** The system carries TWO tenor vocabularies and, until this leg was
    wired, nothing had ever put them side by side:

    * ``config/settings.yaml``'s ``curve_default_short_tenor``/``long_tenor`` are
      ``2y``/``10y``. That spelling is CORRECT for its purpose — the value is
      interpolated into a desk instrument name, and
      ``"Duration-weighted 2y/10y UST steepener"`` is how a desk writes it.
      ``D-058`` recorded that these strings are "interpolated into an instrument
      *name* and are never parsed", which was true precisely because no consumer
      had ever compared them to curve data.
    * The snapshot's ``yield_curve.tenors`` and ``tips_yields.tenors`` are keyed
      ``2yr``/``10yr``/``5yr``, from the registry's ``2yr: DGS2`` mapping and
      FRED's own tenor spelling. ``data_layer/validation.py`` reads
      ``tenors["2yr"]`` and ``tenors["10yr"]``, so the data layer's vocabulary is
      ``yr``.

    Measured, before this helper existed: ``curve_slope`` fed the config labels
    raised ``KeyError: short tenor '2y' is not in the supplied curve; available:
    ['10yr', '1mo', ..., '2yr', ...]``. The trap is that the *natural* fix —
    changing the config to ``2yr`` — would break the instrument name, and the
    *other* natural fix — changing the data keys — would break the registry and
    the validation layer. Neither vocabulary is wrong; they answer different
    questions, and the translation was simply missing.

    **Why this is a defect and not a nuisance.** ``validation.py`` guards its
    2s10s check with ``if "2yr" in tenors and "10yr" in tenors:``. A vocabulary
    mismatch there does not raise — the guard is simply False and the check
    **silently does not run**. That is the same silent-no-op class as the
    ``if not points:`` guard that could never fire in ``_regime_leg``: a
    conditional that fails open looks like a passing check.

    Returns ``None`` when no mapping is clear, so the caller abstains rather than
    guessing — a wrong tenor is a wrong number, not a missing one.
    """
    # Exact match first: the common case is a caller who already speaks the
    # curve's vocabulary, and it must not be second-guessed.
    if curve_label in available:
        return curve_label

    # ``2y`` -> ``2yr``: the config's spelling, with the registry's suffix.
    # Only applied when the result is an actual key, so an unexpected label
    # returns None instead of a plausible-looking near-miss.
    if not curve_label.endswith("yr") and curve_label.endswith("y"):
        candidate = f"{curve_label}r"
        if candidate in available:
            return candidate
    return None


def _curve_leg(
    snapshot: MacroDataSnapshot,
) -> tuple[list[ModelResult], list[DerivationNote]]:
    """Modules 8.1/8.2: the curve slope and the breakevens, from the live curve.

    Returns a **list** rather than one result because this leg legitimately
    produces several independent reads that a reader wants separately: the
    slope is a shape statement, each breakeven is an inflation-compensation
    statement at a named tenor. Neither is a prerequisite for the other, so
    folding them into one result would hide which one was computed.

    **The data is real and was previously unconsumed.** Live on 2026-09-17, the
    snapshot carries an 11-tenor nominal curve (1mo 3.97 .. 30yr 5.29) and a
    5-tenor TIPS curve (5yr 2.46 .. 30yr 3.04). ``curve_slope``,
    ``breakeven_inflation`` and ``decompose_yield`` were all implemented,
    unit-tested and in the unreferenced set (DEF-004): the data existed, the
    models existed, and the consumers did not run.

    **Scope: slope and breakevens, NOT the decomposition.** ``decompose_yield``
    needs an ACM-style term premium, and no term-premium series is wired
    (Section 22.5 defers it to Phase 5+). Passing ``term_premium=None`` is
    *supported* by ``CurveDecompositionInputs`` and is the honest input — but
    the function's own contract says ``None`` means "no series available at this
    tenor", so calling it would produce a result that publishes an expectations
    component while disclosing that the premium was absent. Section 22.5's whole
    point is that this is disclosed rather than fabricated, so it is left
    unwired for now and named as the remaining gap rather than half-done.

    Empty when the curve is absent. A snapshot without a curve is a data
    condition, and the slope is a read, not a gate.
    """
    notes: list[DerivationNote] = []
    results: list[ModelResult] = []

    curve = snapshot.yield_curve
    if curve is None or not curve.tenors:
        notes.append(
            DerivationNote(
                name="curve_slope",
                value="NOT_COMPUTED",
                source=(
                    "yield_curve is absent or carries no tenors, so no spread can "
                    "be formed; reported as not computed rather than guessed "
                    "(Section 21.4)"
                ),
                window="no curve",
            )
        )
        return results, notes

    tenors = curve.tenors
    resolved: dict[str, str] = {}
    for role, label in (
        ("short", get_settings().instrument_selection.default_short_tenor),
        ("long", get_settings().instrument_selection.default_long_tenor),
    ):
        key = _config_tenor_for(label, tenors)
        if key is not None:
            resolved[role] = key

    if "short" not in resolved or "long" not in resolved:
        missing = [role for role in ("short", "long") if role not in resolved]
        notes.append(
            DerivationNote(
                name="curve_slope",
                value="NOT_COMPUTED",
                source=(
                    f"the configured {'/'.join(missing)} curve tenor is not a key on "
                    f"the live curve, and no unambiguous mapping exists; abstaining "
                    f"rather than substituting a different tenor"
                ),
                window=f"available: {sorted(tenors)}",
            )
        )
        return results, notes

    short_key, long_key = resolved["short"], resolved["long"]
    slope = curve_slope(CurveSlopeInputs(tenors=tenors, short=short_key, long=long_key))
    results.append(slope)
    notes.append(
        DerivationNote(
            name="curve_slope",
            value=f"{short_key}/{long_key}",
            source=(
                "long-minus-short spread on the observed curve, in basis points "
                "— the primary curve-shape measure (Module 8.1)"
            ),
            window=(
                f"as_of {curve.as_of.isoformat()}: "
                f"{long_key} {tenors[long_key]:.2f}% - {short_key} {tenors[short_key]:.2f}%"
            ),
        )
    )

    # -- The breakevens. Only tenors present in BOTH curves can produce one: the
    #    model subtracts a real yield from a nominal yield at the SAME tenor, and
    #    a mismatch would silently price the curve's slope into the breakeven.
    tips = snapshot.tips_yields
    if tips is None or not tips.tenors:
        notes.append(
            DerivationNote(
                name="breakeven_inflation",
                value="NOT_COMPUTED",
                source="tips_yields is absent, so no real yield is available to subtract",
                window="no TIPS curve",
            )
        )
        return results, notes

    common = sorted(set(tenors) & set(tips.tenors))
    if not common:
        notes.append(
            DerivationNote(
                name="breakeven_inflation",
                value="NOT_COMPUTED",
                source=(
                    "the nominal and TIPS curves share no tenor, so no breakeven can "
                    "be formed at a matched maturity"
                ),
                window=f"nominal {sorted(tenors)}, TIPS {sorted(tips.tenors)}",
            )
        )
        return results, notes

    for tenor in common:
        results.append(
            breakeven_inflation(
                BreakevenInputs(
                    nominal=tenors[tenor],
                    tips_real=tips.tenors[tenor],
                    tenor=tenor,
                )
            )
        )
    notes.append(
        DerivationNote(
            name="breakeven_inflation",
            value=f"{len(common)} tenor(s)",
            source=(
                "nominal minus TIPS real at each matched tenor — inflation "
                "COMPENSATION, which contains an inflation risk premium"
            ),
            window=f"tenors {common} as_of {curve.as_of.isoformat()}",
        )
    )
    return results, notes


def _nairu_from_config() -> tuple[float, str]:
    """``u*``, which is unobservable, plus a source string naming that fact.

    Section 21.4 item 13 lists the natural rate among the quantities this system
    is required to admit it does not know. It is a config value with
    ``calibration_status: uncalibrated_illustrative``, tracked to CBO's published
    estimate — not fitted here. The models layer propagates the unobservability
    into confidence wherever it is consumed; this function's job is only to
    resolve it and to say where it came from, so the derivation note cannot
    present a placeholder as a measurement.
    """
    value = float(get_settings().phillips.nairu.value)
    return value, "u* from config (phillips.nairu, uncalibrated_illustrative, CBO estimate)"


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def snapshot_to_thesis_inputs(
    snapshot: MacroDataSnapshot,
    *,
    thesis_type: ThesisType | None = None,
    universe: ProductionUniverse | None = None,
    short_yield_tenor: str | None = None,
    curve_short_tenor: str | None = None,
    curve_long_tenor: str | None = None,
    short_tenor_term_premium: float | None = None,
) -> ThesisInputs:
    """Derive every ``build_us_macro_thesis`` argument from ``snapshot``.

    Parameters
    ----------
    snapshot:
        The assembled snapshot. Must be a US one — the check is explicit rather
        than assumed, because ``country`` is a label and Section 22.3 forbids
        letting a label imply capability.
    thesis_type:
        Which analytical family. ``None`` uses
        ``api.default_thesis_type`` from config (``POLICY_PATH_GAP``), and the
        assumption is recorded in ``notes``. **Not inferred from the data** —
        see the module docstring's boundary section.
    universe:
        The production execution universe. ``None`` uses
        ``ProductionUniverse()``'s documented defaults (§22.12).
    short_yield_tenor:
        Curve tenor for the short yield. ``None`` uses ``api.short_yield_tenor``
        (default ``2yr``).
    curve_short_tenor / curve_long_tenor:
        The curve legs, when the thesis family is a curve trade. Forwarded, not
        inferred: which two tenors a curve expression uses is part of the
        expression.
    short_tenor_term_premium:
        Section 22.5's term-premium adjustment. ``None`` is the honest input and
        is what §22.5 expects: ``derive_market_implied_policy_path`` discloses
        the contamination on its own result rather than this function inventing
        an adjustment.

    Returns
    -------
    ThesisInputs
        Every argument the builder takes, their derivation notes, and every
        warning raised while deriving them. The *required* set is the six the
        builder cannot proceed without (three reads, two rule records, the short
        yield); ``regime`` and ``national_accounts`` are optional reads that
        degrade to ``None`` with a ``NOT_COMPUTED`` note rather than refusing.

    Raises
    ------
    OrchestrationError
        A required series was empty, too short, forward-dated, or implausible.
        **This is a refusal, not a default** — the API maps it to 502, and
        Section 16.3 forbids mapping it onto ``WATCH``.
    """
    if snapshot.country != "us":
        raise NotImplementedError(
            f"the API layer is implemented for country 'us' only; got "
            f"'{snapshot.country}' (Section 22.3 / Finding #3). This is not a "
            f"label to re-point: a different country needs its own series set, "
            f"its own reaction function and its own instrument universe."
        )

    settings = get_settings()
    as_of = snapshot.as_of

    # -- The two deliberate parameters. Resolved, then recorded.
    resolved_type = thesis_type or ThesisType(settings.api.default_thesis_type)
    resolved_universe = universe if universe is not None else ProductionUniverse()
    resolved_tenor = short_yield_tenor or settings.api.short_yield_tenor

    notes: list[DerivationNote] = []
    warnings: list[str] = []

    # -- Q1's three reads.
    growth, gap_report = output_gap_from_snapshot(snapshot)
    notes.append(
        DerivationNote(
            name="growth (output_gap)",
            value=f"{growth.value!r}",
            source="output_gap_from_snapshot — the one shipped snapshot-fed helper",
            window=(
                f"same-quarter pair {gap_report.actual_date} / {gap_report.potential_date}; "
                f"{gap_report.withheld_forward_points} forward-dated point(s) withheld (O-7); "
                f"{gap_report.withheld_unpaired_points} realised point(s) unpaired (D-009)"
            ),
        )
    )
    warnings.extend(gap_report.warnings())

    inflation, inflation_notes = _inflation_leg(snapshot, as_of=as_of)
    notes.extend(inflation_notes)

    labor, labor_notes, labor_warnings = _labor_leg(snapshot, as_of=as_of)
    notes.extend(labor_notes)
    warnings.extend(labor_warnings)

    reads = EconomyReads(growth=growth, inflation=inflation, labor=labor)

    # -- Q3/Q4's market read.
    short_yield, short_described = _short_yield_from_curve(snapshot, field=resolved_tenor)
    notes.append(
        DerivationNote(
            name="short_yield",
            value=f"{short_yield:g}",
            source="yield curve, in percent (never basis points)",
            window=short_described,
        )
    )

    # -- Q5's two rule-input records. `pi_current` is drawn from the same
    #    m/m-derived core PCE series the inflation leg used, annualised by the
    #    ratio of two YoY points — the Taylor rule reads a LEVEL WHERE THE
    #    INFLATION LEG READS A CHANGE, and deriving it from the m/m alone would
    #    put a one-month rate into a rule calibrated on a twelve-month one.
    pce_points = _realised(snapshot.pce_core, as_of=as_of, field="pce_core")
    pi_current, pi_described = _yoy_percent(pce_points, field="pce_core")
    notes.append(
        DerivationNote(
            name="pi_current",
            value=f"{pi_current:+.4f}",
            source="core PCE year-over-year percent — the level the Taylor rule reads",
            window=pi_described,
        )
    )

    # The output gap the Taylor rule will read. Refused rather than defaulted
    # (Section 21.0 rule 3, D-078): `output_gap_from_snapshot` documents a float
    # value, so a non-numeric one means the function changed shape — and the old
    # `else 0.0` would have handed the policy rule an output gap of *exactly
    # zero*, i.e. "the economy is precisely at potential", a coordinate claim
    # about the economy invented from a value that carried none. A `nan` reaches
    # the same place by a different route (`isinstance(nan, float)` is True), so
    # the check is on FINITENESS and not only on type (lesson 5cc).
    if not isinstance(growth.value, int | float) or not isfinite(float(growth.value)):
        raise TypeError(
            f"output_gap_from_snapshot returned a {type(growth.value).__name__} "
            f"({growth.value!r}) for value; the Taylor rule needs a finite output "
            "gap in percent. A missing gap must be reported as unavailable, never "
            "substituted with 0.0 — a zero output gap is a specific statement "
            "about capacity utilisation, not an absence of one."
        )
    output_gap_value = float(growth.value)
    gap_change, gap_change_described = _output_gap_change(snapshot, as_of=as_of)
    notes.append(
        DerivationNote(
            name="output_gap_change",
            value=f"{gap_change:+.4f}",
            source="difference of two same-quarter output gaps, one quarter apart",
            window=gap_change_described,
        )
    )

    r_star, r_star_source = _r_star_from_config()

    # -- Q1's fourth read: the regime (Module 3). Derived here because both
    #    inputs it needs from the growth axis (`output_gap` level and its
    #    one-quarter change) have just been computed above, and re-deriving them
    #    inside `_regime_leg` would create a second implementation free to drift.
    regime, regime_notes = _regime_leg(
        snapshot,
        as_of=as_of,
        output_gap=output_gap_value,
        output_gap_change=gap_change,
    )
    notes.extend(regime_notes)
    # `None` means "not classified" — a missing optional series, not a failure.
    # Its warnings are then absent by construction, so the guard is what keeps
    # the degradation from turning into an `AttributeError` on the way out.
    if regime is not None:
        warnings.extend(str(w) for w in regime.warnings)

    # -- Module 7.1's national-accounts divergence (Section 20.7). A read about
    #    the growth read's quality rather than a fourth economy read, so it is
    #    derived here and carried beside `reads` — see `_national_accounts_leg`.
    national_accounts, national_notes = _national_accounts_leg(snapshot, as_of=as_of)
    notes.extend(national_notes)
    if national_accounts is not None:
        warnings.extend(str(w) for w in national_accounts.warnings)

    # -- Modules 8.1/8.2: the curve reads. The snapshot already carries a real
    #    11-tenor nominal curve and a 5-tenor TIPS curve; these models had no
    #    caller (DEF-004), so the data was fetched and never consumed.
    curve_results, curve_notes = _curve_leg(snapshot)
    notes.extend(curve_notes)
    for curve_result in curve_results:
        warnings.extend(str(w) for w in curve_result.warnings)

    policy_rate, policy_described = _policy_rate(snapshot, as_of=as_of)
    notes.append(
        DerivationNote(
            name="i_prev",
            value=f"{policy_rate:g}",
            source="effective policy rate, preferred order iorb > fed_funds_rate > sofr",
            window=policy_described,
        )
    )

    taylor_inputs = TaylorRuleInputs(
        r_star=r_star,
        pi_current=pi_current,
        pi_target=None,  # the model's own config target, not a second literal
        output_gap=output_gap_value,
    )
    first_difference_inputs = FirstDifferenceInputs(
        i_prev=policy_rate,
        pi_current=pi_current,
        pi_target=None,
        output_gap_change=gap_change,
    )
    notes.append(
        DerivationNote(
            name="r_star",
            value=f"{r_star:g}",
            source=r_star_source,
            window=None,
        )
    )

    # -- The curve legs, forwarded only when the family is a curve trade. A
    #    curve tenor pair on an outright thesis is a parameter that nothing
    #    reads — D-037's inert-input class — so it is not defaulted in.
    if resolved_type is ThesisType.CURVE_SHAPE_GAP:
        notes.append(
            DerivationNote(
                name="curve legs",
                value=f"{curve_short_tenor} -> {curve_long_tenor}",
                source="forwarded from the caller; a curve expression names its own legs",
                window=None,
            )
        )
    elif curve_short_tenor is not None or curve_long_tenor is not None:
        warnings.append(
            "CURVE LEGS IGNORED: curve_short_tenor/curve_long_tenor were supplied "
            f"but the thesis type is {resolved_type.value}, so nothing reads them. "
            "Reported rather than dropped because a caller who set them expected "
            "them to matter (D-037's inert-input class)."
        )

    notes.append(
        DerivationNote(
            name="thesis_type",
            value=resolved_type.value,
            source=(
                "assumed from api.default_thesis_type"
                if thesis_type is None
                else "supplied by the caller"
            ),
            window=None,
        )
    )

    if short_tenor_term_premium is not None:
        notes.append(
            DerivationNote(
                name="short_tenor_term_premium",
                value=f"{short_tenor_term_premium:g}",
                source="supplied by the caller",
                window=None,
            )
        )

    return ThesisInputs(
        reads=reads,
        taylor_inputs=taylor_inputs,
        first_difference_inputs=first_difference_inputs,
        short_yield=short_yield,
        thesis_type=resolved_type,
        universe=resolved_universe,
        regime=regime,
        national_accounts=national_accounts,
        curve=tuple(curve_results),
        notes=tuple(notes),
        warnings=tuple(warnings),
    )


def _r_star_from_config() -> tuple[float, str]:
    """``r*`` from config, with the calibration status named in the source.

    ``r*`` is unobservable — Section 22.8's ``unobservable_penalty`` exists
    precisely because of inputs like this — so the honest thing to record is not
    the number but *where the number came from*. A caller reading "r_star: 0.5
    (policy.r_star, uncalibrated_illustrative)" knows exactly how much weight it
    can carry; "r_star: 0.5" invites it to be treated as a measurement.
    """
    settings = get_settings()
    r_star = float(settings.policy.r_star.value)
    status = settings.policy.r_star.calibration_status
    return r_star, f"policy.r_star ({status}) — an UNOBSERVABLE input, per Section 22.8"


#: Why month arithmetic is done on ``(year, month)`` rather than with
#: ``timedelta(days=months * 30)``. Kept as a module constant beside the helper
#: that implements it, so a reader grepping for "why not timedelta" finds the
#: answer here rather than having to reconstruct it from the call sites.
#:
#: This is documentation of a decision that was made while drafting, not a
#: guard: an earlier version of ``_minus_months`` used a 30-day approximation
#: and was replaced before the module shipped.
_CALENDAR_ARITHMETIC_NOTE = (
    "Month arithmetic is done on (year, month), never on timedelta(days=months*30): "
    "36 months is 1095 or 1096 days depending on leap years, and a 30-day "
    "approximation drifts a week over three years — enough to move a boundary "
    "observation in or out of a percentile window."
)
