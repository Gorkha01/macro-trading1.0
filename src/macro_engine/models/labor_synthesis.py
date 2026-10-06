"""Module 6 — labor synthesis: tightness, claims significance, corroboration.

Module 6's organising idea is a **lead/lag hierarchy**, and it is the reason
these functions exist rather than being folded into one aggregate. Initial claims
and JOLTS move before the labor market does; NFP moves with it and is then
revised twice. A composite that weighted them equally would average a leading
signal against a lagging one and produce something that leads nothing.

So the weights are not a preference. ``claims 0.4, JOLTS 0.4, NFP 0.2`` is the
hierarchy stated as arithmetic, and it is what a reviewer needs to be able to
challenge.

Why "sustained uptrend" had to become two numbers
-------------------------------------------------
``claims_trend_signal`` replaces an instruction a human analyst reads in prose.
Prose cannot be tested: "sustained multi-week uptrend, not a single noisy week"
admits any reading, and the reading is chosen after seeing the chart. Module 6.1
requires it be made explicit as *both* a persistence condition (N consecutive
rising weeks) and a magnitude condition (M% above the trailing average), with
both thresholds in config.

Two conditions rather than one is the point. A single-week spike of +30% would
pass any magnitude test; a slow drift of +6% over eight weeks would pass any
persistence test. Both are noise, and only requiring both filters them.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from macro_engine.config import (
    _EXACTNESS_SUM_TOLERANCE,
    AHEDistortionThresholds,
    RevisionThresholds,
    get_settings,
)
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "AHEDistortionInputs",
    "AHEDistortionThresholds",
    "BeveridgeInputs",
    "ClaimsCorroborationInputs",
    "ClaimsTrendInputs",
    "InflationSubMeasures",
    "LaborInputs",
    "RevisionInputs",
    "RevisionThresholds",
    "TwoSurveyInputs",
    "ahe_composition_flag",
    "beveridge_curve_position",
    "beveridge_shift_tolerance",
    "claims_corroboration",
    "claims_trend_signal",
    "inflation_breadth_score",
    "labor_tightness_score",
    "nfp_revision_adjusted_read",
    "two_survey_divergence",
]

# The score's natural bounds. Module 6.4 states -100 (very loose) to +100 (very
# tight). Kept as a module constant rather than config because it is the scale's
# definition, not a tunable — changing it would change the meaning of every
# score ever recorded.
_SCORE_FLOOR = -100.0
_SCORE_CEILING = 100.0


def beveridge_shift_tolerance() -> float:
    """Module 6.2's symmetric tolerance band around the fitted Beveridge curve.

    A named accessor rather than an inline ``get_settings().beveridge...`` read
    in the model body, so the config path appears exactly once and a rename in
    ``config.py`` is a one-line change here rather than a silent miss.
    """
    return get_settings().beveridge.shift_tolerance_pp


def _ahe_thresholds() -> AHEDistortionThresholds:
    return get_settings().labor.ahe_distortion


def _revision_thresholds() -> RevisionThresholds:
    return get_settings().labor.revisions


class LaborInputs(FiniteInputs):
    """Section 6.4's four labor inputs, one per block."""

    model_config = ConfigDict(extra="forbid")

    initial_claims_4wk_avg_change_pct: float = Field(
        description=(
            "Percent change in the 4-week average of initial claims versus the "
            "prior 4-week average. POSITIVE means claims are RISING, i.e. the "
            "labor market is LOOSENING — the sign convention the score's "
            "negative multiplier exists to handle."
        )
    )
    jolts_openings_yoy_pct: float = Field(
        description="Job openings, year-over-year percent change."
    )
    jolts_quits_level_percentile: float = Field(
        ge=0.0,
        le=100.0,
        description="Quits rate as a percentile of its trailing 3-year range, 0-100.",
    )
    nfp_3m_avg: float = Field(
        description="Nonfarm payrolls 3-month average pace, in thousands per month."
    )


def _tightness_direction_sentence(score: float) -> str:
    """The tightness score's sign, in words, for the Section 3 ``direction`` field.

    Three states, and the middle one is real: a score of exactly zero is AT the
    balanced level, which is a reading and not a rounding of tightening or
    loosening. Separating it avoids the D-040 pattern where a boundary value is
    classified by whichever branch's ``else`` happens to catch it.

    A positive score means the market is TIGHT (above its balanced level), which
    is the opposite of the intuition a reader may bring from "positive = slack" —
    the same sign trap that ``slack_corroborated`` in the regime model exists to
    close.
    """
    if score > 0:
        return "tightening: labour market above its balanced level"
    if score < 0:
        return "loosening: labour market below its balanced level"
    return "neutral: at the balanced level"


def _tightness_word(score: float) -> str:
    """The one-word direction used in the interpretation string.

    Derived from the SAME published value as ``_tightness_direction_sentence`` so
    the two can never disagree (F-LAB-001). The interpretation previously used a
    bare ``score > 0`` test while ``direction`` used the three-state sentence; on
    the boundary (notably a ``-0.0`` score) the two took different branches,
    publishing ``direction='neutral'`` next to an interpretation saying
    'loosening'. Centring both on the published value removes the split.
    """
    if score > 0:
        return "tightening"
    if score < 0:
        return "loosening"
    return "neutral"


def labor_tightness_score(inputs: LaborInputs) -> ModelResult:
    """Composite labor tightness, ``-100`` (very loose) to ``+100`` (very tight).

    ``value`` is a ``float``.

    Hand calculation at the Section 6.4 defaults:
        claims_4wk_change = -0.4%  (claims FALLING year-on-year)
        openings_yoy      = +3.0%
        quits_percentile  = 60.0
        nfp_3m_avg        = 180.0k

        claims_component = -(-0.4) * 2.0                            = +0.80
        jolts_component  = 0.5(3.0) + 0.5(60.0 - 50.0)              = 1.50 + 5.00 = +6.50
        nfp_component    = (180.0 - 150.0) / 10                     = +3.00

        score = 0.4(0.80) + 0.4(6.50) + 0.2(3.00) = 0.32 + 2.60 + 0.60 = +3.52

    Three design points worth stating, because each is a place the specification's
    sample could be transcribed into something plausible but wrong:

    * **The claims sign is inverted by a configurable multiplier**, not by a
      leading minus sign in the expression. Rising claims are *given* as a
      positive number (the natural way to report a percent change), and the
      inversion is the model. Putting the sign in the formula would hide a
      modelling decision inside arithmetic.
    * **The JOLTS percentile is centred on 50** before scaling, so that a
      market at the middle of its own three-year range contributes zero rather
      than fifty. Without centring, the JOLTS term would carry a large constant
      offset that has nothing to do with current conditions.
    * **The result is clamped**, because a composite of three unbounded inputs
      would otherwise be unbounded — and its stated range is what makes it
      comparable across time.
    """
    settings = get_settings()
    weights = settings.labor.tightness_weights
    scaling = settings.labor.tightness_scaling

    # A composite whose weights do not sum to 1 is not on the scale it claims:
    # the same inputs would produce a score that depends on how the weights were
    # written down. Checked rather than assumed, because the weights live in a
    # file anyone can edit.
    if abs(weights.total - 1.0) > _EXACTNESS_SUM_TOLERANCE:
        raise ValueError(
            f"labor.tightness_weights sum to {weights.total!r}, not 1.0. The "
            f"score is defined on the -100..+100 scale, so un-normalised weights "
            f"would silently rescale it."
        )

    claims_component = scaling.claims_multiplier_value * inputs.initial_claims_4wk_avg_change_pct
    jolts_component = (
        scaling.jolts_openings_multiplier_value * inputs.jolts_openings_yoy_pct
        + scaling.jolts_quits_multiplier_value
        * (inputs.jolts_quits_level_percentile - scaling.quits_centering_value)
    )
    nfp_component = (inputs.nfp_3m_avg - settings.labor.neutral_nfp_pace) / _nfp_scaling_divisor()

    raw_score = (
        weights.claims_value * claims_component
        + weights.jolts_value * jolts_component
        + weights.nfp_value * nfp_component
    )
    score = max(_SCORE_FLOOR, min(_SCORE_CEILING, raw_score))
    clamped = score != raw_score
    # The value a reader sees, the interpretation, and the direction must all agree.
    # Derive all three from ONE published number (F-LAB-001): round, then
    # normalise away any negative zero so "-0.0" can never be published beside a
    # 'neutral' direction and a 'loosening' interpretation.
    published = round(score, 1) + 0.0

    warnings = [
        "NFP is weighted low deliberately (0.2): it is coincident with the "
        "cycle, noisy month-to-month, and revised twice (Module 6.1). Do not "
        "let a strong payroll print override a weakening claims/JOLTS reading.",
    ]
    if clamped:
        warnings.append(
            f"The composite was clamped to {score:+.1f} from a raw {raw_score:+.2f}. "
            f"At least one component is far outside its usual range — check the "
            f"inputs before reading the score as a level."
        )

    return ModelResult(
        model_name="labor_tightness_score",
        country="us",
        as_of=utc_now(),
        value=published,
        confidence=compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)),
        interpretation=(
            f"Labor market tightness score: {published:+.1f} "
            f"({_tightness_word(published)} vs a balanced market)"
        ),
        context=(
            f"Positive = tightening, negative = loosening. Weights: claims "
            f"{weights.claims_value:.0%}, JOLTS {weights.jolts_value:.0%}, NFP "
            f"{weights.nfp_value:.0%}. Components: claims {claims_component:+.2f}, "
            f"JOLTS {jolts_component:+.2f}, NFP {nfp_component:+.2f}"
        ),
        inputs_used=[
            "initial_claims_4wk_avg_change_pct",
            "jolts_openings_yoy_pct",
            "jolts_quits_level_percentile",
            "nfp_3m_avg",
        ],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="index points, bounded to [-100, +100], zero = balanced market",
        direction=_tightness_direction_sentence(published),
        assumptions=[
            "The three components are combinable in ONE score with fixed weights "
            "(claims 0.4, JOLTS 0.4, NFP 0.2). That is a modelling choice, not a "
            "measurement: the weights are config leaves and are heuristic rather "
            "than estimated, which is why the confidence carries "
            "is_heuristic_not_calibrated=True.",
            "The claims sign is INVERTED by a configurable multiplier because "
            "falling claims mean a TIGHTENING market. The inversion is a "
            "documented, named transform rather than an implicit negation — a "
            "reader recomputing by hand must apply it.",
            "The score is a LEVEL, not a change: zero means the market sits at "
            "its balanced level, and the score does not say how fast it is "
            "moving. Two readings of +3.5 a year apart describe very different "
            "labour markets.",
            "Bounds of +/-100 are applied by clamping. A clamp is a disclosure, "
            "not an error: when it fires the raw value is preserved in a warning "
            "so the reader can see how far outside the range a component sat.",
        ],
        data_provenance=[
            "initial_claims_4wk_avg_change_pct — DOL initial claims, 4-week "
            "average, percent change year-over-year",
            "jolts_openings_yoy_pct — BLS JOLTS job openings, percent change year-over-year",
            "jolts_quits_level_percentile — BLS JOLTS quits rate, expressed as a "
            "percentile of its own history (a within-series rank, not a level)",
            "nfp_3m_avg — BLS nonfarm payrolls 3-month average change, in "
            "thousands. ABSENT on this snapshot: there is no payrolls field in "
            "MacroDataSnapshot, so the orchestrator redistributes NFP's weight "
            "across the other two components and returns that as a warning "
            "rather than passing a fabricated zero.",
        ],
        limitations=[
            "HEURISTIC, NOT CALIBRATED: the component form, the multipliers and "
            "the weights are Section 6.4's illustrative values, not estimates "
            "fitted to data. The score's LEVEL is therefore not comparable to any "
            "published tightness index, and only its sign and approximate "
            "magnitude should be read.",
            "A COMPOSITE LEVEL, NOT A GAP: unlike the output gap, there is no "
            "'potential tightness' to compare against. Zero is the balanced "
            "level by construction of the weights, not by measurement of an "
            "equilibrium.",
            "It is a SIGN-AND-MAGNITUDE summary that can hide a conflict: a "
            "strong claims reading and a weak JOLTS reading can average to a "
            "quiet-looking score. The components are printed in `context` for "
            "exactly this reason — a reader who only sees the total cannot "
            "detect it.",
            "ONE OF ITS FOUR INPUTS IS ABSENT on the live path (NFP), and its "
            "weight is redistributed. That makes the live score a different "
            "estimator from the four-input one the unit tests exercise, and the "
            "warning says so on every run where it applies.",
            "NOT INDEPENDENT OF THE GROWTH READ: JOLTS openings and claims both "
            "move with the cycle, so this score correlates with the output gap. "
            "Section 12's independence count for the thesis is computed from "
            "source families and does not treat labour and growth as disjoint.",
            "Points-in-time: claims, JOLTS and payrolls are released on "
            "different days and revised on different schedules. The latest "
            "common vintage is not enforced, and no release or vintage datetime "
            "is available on this installation (Section 6, measured 2026-09-19).",
        ],
        decision_relevance=(
            "Section 16.2's Q1 labour read, one of the three economy reads on the "
            "live path. It is the corroborating read for the growth axis: the "
            "regime classifier compares the output gap against the unemployment "
            "gap, and this score is the broader labour read the thesis publishes "
            "beside them."
        ),
        decision_prohibition=[
            "MUST NOT be compared against any external labour-market tightness "
            "index. The scale is this model's own, built from illustrative "
            "weights, and a reader who compares it to a published index reads a "
            "spurious level.",
            "MUST NOT be read as a rate of change. It is a level, and 'the score "
            "is +3.5' says nothing about whether the market is tightening or "
            "loosening — that requires two readings and their difference.",
            "MUST NOT be used as the sole justification for a tightening or "
            "loosening call when its components conflict. Read the components in "
            "`context` first (Section 12: divergence is information).",
            "MUST NOT be consumed without reading the live path's disclosure: "
            "`api_layer/orchestration.py` cannot read a payrolls series, so it "
            "feeds this block the model's own NEUTRAL pace. That makes the NFP "
            "term contribute exactly ZERO, but `weight_nfp` is still applied — so "
            "a score from that path is the claims+JOLTS sum COMPRESSED 20% toward "
            "zero, NOT a 2-block average (measured 2026-10-06; the earlier note "
            "here described an 'NFP-redistribution' the live path does not and "
            "cannot perform).",
        ],
    )


def _nfp_scaling_divisor() -> float:
    """Divisor converting a payroll-pace deviation into score points.

    Section 6.4 writes ``(nfp_3m_avg - 150) / 10``. The 10 means "a 10k
    deviation from the neutral pace is one score point", and the neutral pace is
    already in config as ``labor.neutral_nfp_pace_thousands``.

    D-139: the divisor MOVED to config as
    ``labor.tightness_scaling.nfp_divisor``. It is still a unit conversion
    rather than a tuned judgement, but it sets the scale of the whole tightness
    score — a reader cannot see it from the model body, and a silent change to
    it rescales every published score — so it belongs beside the multipliers
    that share the same role (``claims_multiplier`` and friends).
    """
    return get_settings().labor.tightness_scaling.nfp_divisor_value


class ClaimsTrendInputs(FiniteInputs):
    """One weekly claims series; both comparison windows are derived from it.

    D-022's lesson, applied structurally: the original version took a raw
    weekly series *and* a trailing average, and subtracted a 4-week mean from a
    13-week mean. Taking **one** series and deriving both windows here makes
    that class of mismatch unrepresentable — a caller cannot supply two
    windows that disagree, because the caller no longer supplies windows.
    """

    model_config = ConfigDict(extra="forbid")

    weekly_initial_claims: list[float] = Field(
        min_length=13,
        description=(
            "Weekly initial claims levels, OLDEST FIRST, in the same units "
            "throughout. The most recent 13 weeks form the trailing 3-month "
            "window from which both comparison terms are drawn: the latest "
            "reading is its LAST four observations and the baseline is its "
            "FIRST four. Any earlier values are used only for the consecutive-"
            "rise count, so a caller may pass a longer history without slicing "
            "it first."
        ),
    )


def claims_trend_signal(inputs: ClaimsTrendInputs) -> ModelResult:
    """Whether the claims trend is a genuine deterioration, not noise.

    ``value`` is a ``dict``::

        {
          "consecutive_weeks_rising": int,
          "pct_above_trailing": float,       # rounded to 3dp
          "latest_4wk_avg": float,
          "trailing_4wk_avg": float,
          "window_weeks": int,
          "persistence_met": bool,
          "magnitude_met": bool,
          "is_signal": bool,
        }

    Module 6.1's rule, both conditions required:

    1. the 4-week moving average has risen for at least
       ``labor.claims.consecutive_weeks_threshold`` consecutive weeks, **and**
    2. the latest 4-week average sits more than
       ``labor.claims.pct_above_trailing_threshold`` above the trailing
       baseline.

    The two conditions are not redundant for the reason they look: a one-week
    spike of +30% clears any magnitude bar while failing persistence, and a
    drift of +6% over eight weeks clears any persistence bar while failing
    magnitude. Requiring both is what turns a prose instruction into a rule.

    **The two comparison terms, and why they are sliced the way they are**
    (D-022, D-024). Both are 4-week averages drawn from the same 13-week window —
    4-week against 4-week, so neither side receives more smoothing than the
    other::

        latest_4wk_avg   = mean of the window's LAST 4 weeks   (what is happening now)
        trailing_4wk_avg = mean of the window's FIRST 4 weeks  (same phase, prior quarter)

    The latest reading must be the *recent* end, because on an oldest-first
    window a rising series carries its lowest values at the front — comparing
    the leading quarter to the window mean inverts the sign, and a deteriorating
    labor market then reports a negative ``pct_above_trailing`` (measured: a
    +2%/week rise gave ``-8.8%``). The baseline must be the *leading* quarter,
    because it is the only span in the window disjoint from the latest one that
    is also a full 4 weeks. So the difference is between now and three months
    ago, same phase, no overlap.

    The persistence count and the magnitude comparison therefore run over
    **different spans**: persistence needs enough 4-week averages to count
    consecutive rises, which a 13-week window does not contain, so it is counted
    over the whole series supplied. Persistence asks "has the trend been
    sustained?"; magnitude asks "how does now compare with last quarter?".

    Confidence comes from ``compute_confidence()`` with the
    ``is_heuristic_not_calibrated`` penalty applied **in both branches**, because
    these thresholds are illustrative starting values either way. A "signal"
    verdict reached with uncalibrated thresholds is not a better-evidenced claim
    than a "no signal" one — it is merely a positive one, and letting the
    positive branch score higher would make the model systematically eager.

    The ``pct_above_trailing`` name is retained for continuity, but a **negative
    value means below**, and the interpretation wording states the direction it
    measured rather than assuming a shortfall (D-023).
    """
    weekly = inputs.weekly_initial_claims
    if len(weekly) < 13:
        raise ValueError(
            f"At least 13 weekly observations are required for a trailing "
            f"3-month window; got {len(weekly)}."
        )

    # The trailing 3-month window: the most recent 13 weeks, oldest first.
    window = weekly[-13:]
    if any(value <= 0 for value in window):
        raise ValueError(
            "Claims levels must be positive; a non-positive observation in the "
            "trailing window would make the percent comparison undefined."
        )

    # 4-week moving averages over the whole supplied series, for persistence.
    ma4 = [sum(weekly[index - 3 : index + 1]) / 4 for index in range(3, len(weekly))]

    consecutive_rising = 0
    for index in range(len(ma4) - 1, 0, -1):
        if ma4[index] > ma4[index - 1]:
            consecutive_rising += 1
        else:
            break

    # The two comparison terms: 4 weeks against 4 weeks, disjoint, same phase.
    latest_ma4 = sum(window[-4:]) / 4.0
    trailing_ma4 = sum(window[:4]) / 4.0
    pct_above_trailing = (latest_ma4 - trailing_ma4) / trailing_ma4

    settings = get_settings()
    weeks_threshold = settings.labor.claims.consecutive_weeks
    pct_threshold = settings.labor.claims.pct_above_trailing

    persistence_met = consecutive_rising >= weeks_threshold
    magnitude_met = pct_above_trailing > pct_threshold
    is_signal = persistence_met and magnitude_met

    warnings = [
        "Thresholds are illustrative starting heuristics, not calibrated "
        "against historical claims data — Phase 5+ calibration required. A "
        "'signal' verdict here is a positive result under uncalibrated "
        "thresholds, which is a weaker claim than it appears.",
        "The baseline is the SAME 4 WEEKS OF THE PRIOR QUARTER, not a week of "
        "the window and not the window mean. Comparing a 4-week mean against a "
        "13-week mean, or against the wrong end of the window, measures the "
        "slicing rather than the labor market — a +2%/week deterioration "
        "reports as -8.8% under the leading-quarter-against-mean reading "
        "(D-022, D-024).",
    ]
    above = pct_above_trailing >= 0
    period = f"{len(window)}-week window"
    if is_signal:
        interpretation = (
            f"GENUINE deterioration signal: {consecutive_rising} consecutive "
            f"weeks rising, latest 4-week average {pct_above_trailing:+.1%} "
            f"versus the same span of the prior quarter"
        )
    elif persistence_met and not magnitude_met:
        # The direction is partitioned rather than assumed (D-023): a negative
        # reading is *below* baseline, and "below the +5.0% bar" is not a
        # sentence that means anything when the measurement is negative.
        if above:
            interpretation = (
                f"NOT a signal — the trend is sustained ({consecutive_rising} "
                f"weeks rising) but the latest 4-week average is only "
                f"{pct_above_trailing:+.1%} above the same span of the prior "
                f"quarter, inside the {pct_threshold:.1%} rise bar. A slow "
                f"drift, not a deterioration."
            )
        else:
            interpretation = (
                f"NOT a signal — the latest 4-week average is BELOW the same "
                f"span of the prior quarter ({pct_above_trailing:+.1%}) and only "
                f"the most recent {consecutive_rising} weeks are rising. A "
                f"partial retracement within a still-low range, not a "
                f"deterioration."
            )
    elif magnitude_met and not persistence_met:
        interpretation = (
            f"NOT a signal — the latest 4-week average is "
            f"{pct_above_trailing:+.1%} above the same span of the prior quarter "
            f"but the rise is not sustained ({consecutive_rising} rising weeks, "
            f"{weeks_threshold} required). A single-week spike is noise "
            f"regardless of its size."
        )
    elif above:
        interpretation = (
            f"NOT a signal — neither condition met: {consecutive_rising} rising "
            f"weeks (need {weeks_threshold}) and {pct_above_trailing:+.1%} above "
            f"the prior quarter's same span (need >{pct_threshold:.1%})."
        )
    else:
        interpretation = (
            f"NOT a signal — the latest 4-week average is below the same span of "
            f"the prior quarter ({pct_above_trailing:+.1%}) with only "
            f"{consecutive_rising} rising weeks (need {weeks_threshold})."
        )

    return ModelResult(
        model_name="claims_trend_signal",
        country="us",
        as_of=utc_now(),
        value={
            "consecutive_weeks_rising": consecutive_rising,
            "pct_above_trailing": round(pct_above_trailing, 3) + 0.0,
            "latest_4wk_avg": round(latest_ma4, 1),
            "trailing_4wk_avg": round(trailing_ma4, 1),
            "window_weeks": len(window),
            "persistence_met": persistence_met,
            "magnitude_met": magnitude_met,
            "is_signal": is_signal,
        },
        confidence=compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)),
        interpretation=interpretation,
        context=(
            f"Both conditions required: >= {weeks_threshold} consecutive rising "
            f"weeks AND > {pct_threshold:.1%} above the same span of the prior "
            f"quarter. Both comparison terms are 4-week averages from the same "
            f"{period} (configurable, illustrative starting values)"
        ),
        inputs_used=["weekly_initial_claims"],
        warnings=warnings,
    )


class ClaimsCorroborationInputs(FiniteInputs):
    """The two claims readings Module 6.3 compares."""

    model_config = ConfigDict(extra="forbid")

    initial_claims_signal: bool = Field(
        description="From claims_trend_signal()['is_signal'] — rising initial claims?"
    )
    continuing_claims_rising: bool = Field(description="Whether continuing claims are rising.")


def claims_corroboration(inputs: ClaimsCorroborationInputs) -> ModelResult:
    """``value`` is a ``str`` verdict; distinguishes churn from a downturn.

    Module 6.3's distinction, and it is the whole reason two claims series are
    tracked rather than one:

    * Rising initial claims with **stable** continuing claims means people are
      losing jobs and quickly finding new ones — *churn*. The labor market is
      working; it is just busier.
    * Rising initial claims with **rising** continuing claims means people are
      losing jobs and staying unemployed — a genuine downturn, because the
      re-employment mechanism has stopped absorbing the flow.

    Initial claims alone cannot tell these apart, and the difference is the
    difference between a market that is churning and one that is breaking.

    Confidence comes from ``compute_confidence()`` and is identical across the
    three branches. That is deliberate: the verdict's *classification* differs by
    branch, but the *evidence quality* does not. Three boolean-derived verdicts
    are not better evidenced because one of them is alarming, and a confidence
    that rose with severity would make the system's most alarming reading also
    its most confident one.
    """
    if inputs.initial_claims_signal and inputs.continuing_claims_rising:
        verdict = "genuine_downturn_signal"
        detail = (
            "Both series rising: workers are losing jobs and NOT being "
            "re-absorbed. The re-employment mechanism has stopped clearing the "
            "flow, which is what distinguishes a downturn from churn."
        )
        warnings = [
            "Genuine-downturn verdict rests on two weekly series, both revised. "
            "Confirm against continuing-claims duration data before treating as "
            "established.",
        ]
    elif inputs.initial_claims_signal and not inputs.continuing_claims_rising:
        verdict = "churn_not_downturn"
        detail = (
            "Initial claims rising while continuing claims are stable: workers "
            "are moving between jobs rather than out of work. Elevated churn, "
            "not a weakening labor market."
        )
        warnings = [
            "Churn verdict assumes continuing claims are genuinely STABLE and "
            "not merely lagging. Continuing claims publish with an extra week's "
            "delay, so a fresh deterioration may not yet be visible here.",
        ]
    else:
        verdict = "no_signal"
        detail = (
            "No initial-claims deterioration to corroborate. Nothing to "
            "distinguish — this is absence of evidence, not evidence of "
            "stability."
        )
        warnings = []

    return ModelResult(
        model_name="claims_corroboration",
        country="us",
        as_of=utc_now(),
        value=verdict,
        confidence=compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)),
        interpretation=f"Claims pattern: {verdict.replace('_', ' ')}",
        context=(
            f"Continuing claims add re-employment-speed information that initial "
            f"claims alone cannot (Module 6.3). {detail}"
        ),
        inputs_used=["initial_claims_signal", "continuing_claims_rising"],
        warnings=warnings,
    )


class TwoSurveyInputs(FiniteInputs):
    """Module 6.1's two-survey comparison, plus the rate that explains the gap.

    The two employment series are **not** alternatives to each other, and that is
    the point of the module: the establishment survey counts *jobs* while the
    household survey counts *people*. A person holding two jobs is two jobs but
    one employed person, so the two can diverge while both are correct.

    ``unemployment_rate_change_pp`` and ``participation_rate_change_pp`` are
    **changes** (percentage points), not levels, because Module 6.1's
    distinction is about which way each is moving, not where it sits. Passing a
    level here would produce a verdict that reads plausibly and means nothing —
    a +5.0% unemployment "change" would flag every input as rising.
    """

    model_config = ConfigDict(extra="forbid")

    nfp_change_thousands: float = Field(
        description=(
            "Establishment survey payroll change, thousands of jobs. Positive "
            "means MORE JOBS. Counts positions, so one person working two jobs "
            "contributes two."
        )
    )
    household_employment_change_thousands: float = Field(
        description=(
            "Household survey employment change, thousands of people. Positive "
            "means MORE EMPLOYED PEOPLE. Counts individuals, so it will differ "
            "from NFP whenever multiple-job holding shifts."
        )
    )
    unemployment_rate_change_pp: float = Field(
        description=(
            "Change in the unemployment RATE, in percentage points (not the "
            "level, and not a percent change). Positive means unemployment rose."
        )
    )
    participation_rate_change_pp: float = Field(
        description=(
            "Change in the labor force participation RATE, in percentage "
            "points. Positive means more people entered (or re-entered) the "
            "labor force — labor SUPPLY increasing."
        )
    )


def two_survey_divergence(inputs: TwoSurveyInputs) -> ModelResult:
    """Which survey is telling the story, and whether the gap is benign.

    ``value`` is a ``str`` verdict in one of FIVE states.

    The insight this encodes, and the reason reading NFP alone is a known error:

    * Payrolls **up** with unemployment **up** is normally read as a
      contradiction. It is not. If participation is also **up**, the labor force
      grew faster than the number of people found work — a supply expansion, not
      demand weakness. More people looking raises the numerator of the
      unemployment rate while the labor market is arguably *strengthening*.
    * The same payrolls-up / unemployment-up combination **without** a
      participation rise has no such benign explanation. Both surveys describe
      the same underlying reality and are disagreeing about it, which is an
      invitation to investigate rather than a verdict.

    Hand calculation for the four main paths::

        nfp +200, u_rate +0.1, participation +0.2
            -> PARTICIPATION_DRIVEN (payrolls up, u up, but supply explains it)

        nfp +200, u_rate +0.1, participation -0.1
            -> GENUINE_DIVERGENCE (payrolls up, u up, supply is FALLING)

        nfp -100, u_rate +0.2, participation -0.2
            -> BROAD_WEAKENING (both decline; no supply-side cover)

        nfp +200, u_rate -0.1, participation +0.1
            -> CONSISTENT_STRENGTH (jobs up, unemployment down)

        nfp -100, u_rate -0.2, participation -0.2
            -> CONSISTENT_WEAKNESS (jobs down, unemployment down; both surveys
               agree the market is weakening, so no divergence, but NOT strength)
            -> CONSISTENT_STRENGTH (jobs up, unemployment down)

    Two limits are carried in the output rather than left implied. First, the
    household employment change — the second survey's actual employment number —
    **does not enter the verdict at all**; it is reported so a reader can see
    whether the two headline employment counts agree, but the classification
    runs on NFP, unemployment and participation. Second, the thresholds are
    sign-only, so ``+1k`` and ``+500k`` classify identically. Both are recorded
    as warnings because a caller reading the verdict alone would not know either.
    """
    payrolls_up = inputs.nfp_change_thousands > 0
    unemployment_up = inputs.unemployment_rate_change_pp > 0
    participation_up = inputs.participation_rate_change_pp > 0

    # How far the two employment counts disagree. Reported, never classified on:
    # the divergence between the surveys is the module's subject, so a caller
    # needs the size of the gap even when the verdict came from elsewhere.
    survey_gap = inputs.nfp_change_thousands - inputs.household_employment_change_thousands
    surveys_agree = payrolls_up == (inputs.household_employment_change_thousands > 0)

    if payrolls_up and unemployment_up and participation_up:
        verdict = "PARTICIPATION_DRIVEN_not_weakness"
        # The benign reading is a claim about the FUTURE as much as the present:
        # it says the labor force grew. If those entrants do not find work,
        # the same numbers become the start of a weakening labor market.
        interpretation = (
            "Payrolls rose while unemployment also rose, and participation "
            "increased — the labor force grew faster than hiring absorbed it. "
            "This is labor SUPPLY entering the market, not labor DEMAND failing."
        )
        warnings = [
            "The benign reading depends on the new entrants being absorbed. If "
            "participation keeps rising while unemployment keeps rising, the "
            "same pattern becomes the leading edge of a downturn rather than a "
            "supply expansion — re-check next month before treating this as "
            "strength.",
        ]
    elif payrolls_up and unemployment_up and not participation_up:
        verdict = "GENUINE_DIVERGENCE_investigate"
        interpretation = (
            "Payrolls rose while unemployment rose and participation did NOT — "
            "there is no supply-side explanation for the gap. The two surveys "
            "are disagreeing about the same labor market."
        )
        warnings = [
            "Neither survey is wrong by construction, so one of the inputs is "
            "measuring something other than the headline suggests. Check "
            "birth-death imputation and seasonal adjustment on the payroll "
            "series, and check whether the household change came from "
            "population-control revisions, before reading a direction.",
        ]
    elif not payrolls_up and unemployment_up:
        verdict = "BROAD_WEAKENING"
        interpretation = (
            "Payrolls fell while unemployment rose — both surveys point the "
            "same way, and no supply-side expansion offsets it."
        )
        warnings = []
    elif payrolls_up and not unemployment_up:
        verdict = "CONSISTENT_STRENGTH"
        interpretation = (
            "Payrolls rose and unemployment did not, so the surveys are "
            "consistent — no divergence to explain."
        )
        warnings = []
    else:  # not payrolls_up and not unemployment_up
        # F-LAB-002: the previous flat `else` also caught a FALLING payrolls /
        # FALLING unemployment reading and labelled it CONSISTENT_STRENGTH with the
        # false statement "Payrolls rose and unemployment did not". Both surveys
        # point to a weakening market here, so it is consistent but NOT strength.
        verdict = "CONSISTENT_WEAKNESS"
        interpretation = (
            "Payrolls fell and unemployment also fell — both surveys point the "
            "same way to a weakening market, so there is no divergence to "
            "explain, but this is not strength."
        )
        warnings = []

    if not surveys_agree:
        warnings.append(
            f"The two employment counts disagree in sign: establishment "
            f"{inputs.nfp_change_thousands:+.0f}k vs household "
            f"{inputs.household_employment_change_thousands:+.0f}k. The verdict "
            f"above is reached from payrolls, unemployment and participation; "
            f"this disagreement is reported so it is not missed, but it does not "
            f"enter the classification."
        )
    warnings.append(
        "Classification is SIGN-only: a +1k payroll print and a +500k print give "
        "identical verdicts. Read the magnitudes alongside the verdict."
    )

    return ModelResult(
        model_name="two_survey_divergence",
        country="us",
        as_of=utc_now(),
        value=verdict,
        confidence=compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)),
        interpretation=interpretation,
        context=(
            f"Establishment (jobs) vs Household (people) — always check both "
            f"before concluding from NFP (Module 6.1). Survey gap: "
            f"{survey_gap:+.0f}k."
        ),
        inputs_used=[
            "nfp_change_thousands",
            "household_employment_change_thousands",
            "unemployment_rate_change_pp",
            "participation_rate_change_pp",
        ],
        warnings=warnings,
    )


class BeveridgeInputs(FiniteInputs):
    """Module 6.2's Beveridge-curve position read.

    A Beveridge curve plots job openings against unemployment. The *position of
    the point* relative to the historical curve is the signal; the two rates
    individually are not. That is why ``historical_openings_at_this_u`` is an
    input rather than something this function derives: it is a point on a
    **fitted pre-shift curve**, and the fitting is a documented modelling choice
    (``config/settings.yaml`` -> ``beveridge.pre_covid_curve``), not an
    arithmetic consequence of the current unemployment rate.

    Deriving it here from a hardcoded functional form would be the classic error
    this project's no-prototyping rule exists to catch — a curve transcribed
    from a chart into a formula and then treated as data.
    """

    model_config = ConfigDict(extra="forbid")

    openings_rate_pct: float = Field(
        ge=0.0,
        description=(
            "Job openings as a percent of the labor force (JOLTS openings rate). "
            "A RATE, not a level — comparing a level against a curve fitted in "
            "rate space would produce a meaningless shift."
        ),
    )
    unemployment_rate_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="Unemployment rate, percent.",
    )
    historical_openings_at_this_u: float = Field(
        ge=0.0,
        description=(
            "The openings rate the PRE-SHIFT fitted Beveridge curve predicts at "
            "``unemployment_rate_pct``. Obtain from "
            "BeveridgeSettings.openings_at(unemployment_rate_pct), which "
            "interpolates the configured curve. Supplied as an input so the "
            "fitted curve is never re-derived inside the model."
        ),
    )


def beveridge_curve_position(inputs: BeveridgeInputs) -> ModelResult:
    """Whether the labor market sits on, outside, or inside its historical curve.

    ``value`` is a ``dict`` with ``verdict`` (``str``) and ``shift_pp``
    (``float``, percentage points).

    Why an outward shift is a different kind of problem:

    * **On the curve** means the relationship between vacancies and unemployment
      is behaving as it historically has. Whatever the current unemployment rate
      is, it is *cyclical* — demand management can move along the curve.
    * **Outward** means the same unemployment rate now coexists with MORE
      vacancies than it used to. Matching has become harder: skills, geography,
      or industry composition no longer line up. This is *structural*, and it
      implies a **higher u*** — the unemployment rate consistent with stable
      inflation has risen. That propagates directly into the Phillips curve and
      therefore the Taylor rule, which is why this function's output is not
      merely descriptive.

    Hand calculation::

        openings 5.5%, u 4.0%, historical curve predicts 4.8% at u=4.0
            shift = 5.5 - 4.8 = +0.7pp -> OUTWARD_SHIFT_structural_mismatch

        openings 4.4%, u 4.0%, curve predicts 4.8%
            shift = -0.4pp -> ON_CURVE_cyclical

    The band is asymmetric in effect but not in construction: any shift inside
    the configured tolerance is ON_CURVE, because a fitted curve estimated on
    historical data cannot resolve small dislocations. The tolerance is in
    config rather than a literal for that reason.
    """
    threshold = beveridge_shift_tolerance()
    shift = inputs.openings_rate_pct - inputs.historical_openings_at_this_u

    if shift > threshold:
        verdict = "OUTWARD_SHIFT_structural_mismatch"
        interpretation = (
            f"Beveridge curve has shifted OUTWARD by {shift:+.2f}pp — at "
            f"{inputs.unemployment_rate_pct:.1f}% unemployment there are now "
            f"{inputs.openings_rate_pct:.1f}% openings where the historical "
            f"curve predicts {inputs.historical_openings_at_this_u:.1f}%. "
            f"Matching has become structurally harder."
        )
        warnings = [
            "Structural shift implies a HIGHER u* — the unemployment rate "
            "consistent with stable inflation has risen. Propagate this to "
            "phillips_curve_inflation() before using its output; a Phillips "
            "curve still calibrated to the old u* will overstate inflationary "
            "pressure at any given unemployment rate (Module 6.2).",
            "An outward shift is measured against a curve fitted on PRE-COVID "
            "data. If the post-COVID matching technology genuinely changed, the "
            "baseline is partly stale and the shift is overstated. Treat the "
            "magnitude as directional until the curve is refitted.",
        ]
    elif shift < -threshold:
        verdict = "INWARD_SHIFT_improved_matching"
        interpretation = (
            f"Beveridge curve has shifted INWARD by {shift:+.2f}pp — at "
            f"{inputs.unemployment_rate_pct:.1f}% unemployment there are "
            f"{inputs.openings_rate_pct:.1f}% openings where the historical "
            f"curve predicts {inputs.historical_openings_at_this_u:.1f}%. "
            f"Matching has improved; the labor market is tighter than the "
            f"unemployment rate alone suggests."
        )
        warnings = [
            "Inward shift implies a LOWER u* — a given unemployment rate now "
            "carries more inflationary pressure than historically. Propagate "
            "this to phillips_curve_inflation() before using its output "
            "(Module 6.2).",
        ]
    else:
        verdict = "ON_CURVE_cyclical"
        interpretation = (
            f"Beveridge curve position is ON its historical curve "
            f"({shift:+.2f}pp, within the {threshold:.2f}pp tolerance) — the "
            f"vacancy-unemployment relationship is behaving as it historically "
            f"has, so the current reading is cyclical rather than structural."
        )
        warnings = [
            "An on-curve reading does NOT mean the curve is stable going "
            "forward, only that it has not demonstrably moved. The tolerance "
            "band is a resolution limit of the fitted curve, not an assumption "
            "that shifts smaller than it are absent.",
        ]

    return ModelResult(
        model_name="beveridge_curve_position",
        country="us",
        as_of=utc_now(),
        value={"verdict": verdict, "shift_pp": round(shift, 2)},
        confidence=compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)),
        interpretation=interpretation,
        context=(
            f"Outward shift = structural, not cyclical — implies a HIGHER u* "
            f"(Module 6.2). Measured against the configured pre-COVID fitted "
            f"curve at u={inputs.unemployment_rate_pct:.2f}%, which predicts "
            f"openings of {inputs.historical_openings_at_this_u:.2f}%."
        ),
        inputs_used=[
            "openings_rate_pct",
            "unemployment_rate_pct",
            "historical_openings_at_this_u",
        ],
        warnings=warnings,
    )


class AHEDistortionInputs(FiniteInputs):
    """Module 6.2's wage-measure distortion check.

    Average Hourly Earnings and the Employment Cost Index measure wage growth
    differently, and the difference is exactly what makes one of them
    misleading in certain conditions:

    * **AHE** divides total wages by total hours across *whoever is currently
      employed*. If low-wage jobs disappear, the remaining workforce is
      higher-paid on average and AHE rises **without anyone receiving a raise**.
      It is fast (monthly) but composition-sensitive.
    * **ECI** holds the job mix **fixed** and prices the same basket of jobs
      over time, so it cannot be moved by composition. It is the ground truth —
      but it is quarterly, so it is often not available.
    """

    model_config = ConfigDict(extra="forbid")

    ahe_growth_yoy_pct: float = Field(
        description="Average Hourly Earnings, year-over-year percent change."
    )
    eci_growth_yoy_pct: float | None = Field(
        default=None,
        description=(
            "Employment Cost Index, year-over-year percent change. Quarterly, so "
            "genuinely unavailable in two months out of three — ``None`` is an "
            "expected state, not missing data. When ``None``, the divergence "
            "test cannot run and the flag rests on composition alone."
        ),
    )
    low_wage_sector_employment_change_pct: float = Field(
        description=(
            "Employment change in low-wage sectors (leisure/hospitality, retail), "
            "percent. NEGATIVE means low-wage jobs are being lost, which is the "
            "condition that mechanically inflates AHE."
        )
    )


def ahe_composition_flag(inputs: AHEDistortionInputs) -> ModelResult:
    """Whether AHE is likely measuring composition rather than pay.

    ``value`` is a ``dict`` with ``distortion_flagged`` (``bool``) and
    ``ahe_minus_eci_pp`` (``float | None``).

    The logic is a conjunction, deliberately: AHE is only suspect when low-wage
    employment is **falling** (the mechanism) *and* either ECI confirms a
    divergence or ECI is unavailable to rule one out. Requiring the mechanism is
    what keeps this from firing on every month in which the two measures differ
    by noise.

    Hand calculation — the COVID 2020 pattern::

        ahe = +8.0%, eci = +2.5%, low_wage_change = -12.0%
            distortion_risk = (-12.0 < -1.0)                = True
            eci_divergence  = |8.0 - 2.5| = 5.5 > 0.75      = True
            flagged = True and (True or ...)                = True
            ahe_minus_eci_pp = 5.5

        ahe = +3.5%, eci = +3.3%, low_wage_change = +1.2%
            flagged = False (no composition shift to distort it)

    Note the third branch of the flag: when ECI is ``None`` **and** low-wage
    employment is falling, the flag is raised on composition alone. That is the
    conservative direction — the mechanism is present and the test that could
    clear it is unavailable, so the honest report is "suspect", not "clear".
    """
    settings = _ahe_thresholds()
    distortion_risk = inputs.low_wage_sector_employment_change_pct < settings.low_wage_decline
    eci_divergence = (
        inputs.eci_growth_yoy_pct is not None
        and abs(inputs.ahe_growth_yoy_pct - inputs.eci_growth_yoy_pct) > settings.eci_divergence
    )
    flagged = distortion_risk and (eci_divergence or inputs.eci_growth_yoy_pct is None)

    ahe_minus_eci = (
        round(inputs.ahe_growth_yoy_pct - inputs.eci_growth_yoy_pct, 2)
        if inputs.eci_growth_yoy_pct is not None
        else None
    )

    if flagged:
        if inputs.eci_growth_yoy_pct is None:
            interpretation = (
                f"Low-wage employment fell "
                f"{inputs.low_wage_sector_employment_change_pct:+.1f}% while AHE "
                f"rose {inputs.ahe_growth_yoy_pct:+.2f}%. ECI is not yet "
                f"published for this period, so the composition mechanism "
                f"cannot be ruled out — treat AHE as likely distorted."
            )
            warnings = [
                "ECI has not been published for this period. Re-run when it "
                "lands; if AHE and ECI agree there, this flag should clear.",
            ]
        else:
            interpretation = (
                f"AHE exceeds ECI by {ahe_minus_eci:+.2f}pp "
                f"({inputs.ahe_growth_yoy_pct:+.2f}% vs "
                f"{inputs.eci_growth_yoy_pct:+.2f}%) while low-wage employment "
                f"fell {inputs.low_wage_sector_employment_change_pct:+.1f}%. "
                f"The AHE reading is partly composition, not pay."
            )
            warnings = []
    elif not distortion_risk:
        interpretation = (
            f"No composition distortion expected: low-wage employment changed "
            f"{inputs.low_wage_sector_employment_change_pct:+.1f}%, which is not "
            f"a decline steep enough to shift the AHE composition "
            f"mechanically."
        )
        warnings = []
    else:
        interpretation = (
            f"Composition mechanism is present (low-wage employment "
            f"{inputs.low_wage_sector_employment_change_pct:+.1f}%) but ECI "
            f"does not confirm distortion — AHE and ECI differ by only "
            f"{ahe_minus_eci:+.2f}pp."
        )
        warnings = []

    if flagged:
        warnings.append(
            "Prefer ECI for the wage-inflation signal while this flag is set — "
            "ECI holds job mix fixed and therefore measures pay rather than "
            "composition (Module 6.2)."
        )
    if inputs.eci_growth_yoy_pct is None:
        warnings.append(
            "ECI is quarterly. Its absence is expected in most months and is "
            "reported as None rather than proxied — substituting a monthly "
            "series here would defeat the purpose of the cross-check."
        )
    warnings.append(
        "The low-wage employment change is a single aggregate; it cannot "
        "distinguish composition shift within sectors from a genuine change in "
        "pay for low-wage workers. This flag identifies where to look, not what "
        "the answer is."
    )

    return ModelResult(
        model_name="ahe_composition_flag",
        country="us",
        as_of=utc_now(),
        value={"distortion_flagged": flagged, "ahe_minus_eci_pp": ahe_minus_eci},
        confidence=compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)),
        interpretation=interpretation,
        context=(
            "Low-wage job losses inflate AHE without any individual raise "
            "(Module 6.2, COVID 2020 case). AHE is monthly but "
            "composition-sensitive; ECI is composition-safe but quarterly."
        ),
        inputs_used=[
            "ahe_growth_yoy_pct",
            "eci_growth_yoy_pct",
            "low_wage_sector_employment_change_pct",
        ],
        warnings=warnings,
    )


class RevisionInputs(FiniteInputs):
    """Module 6.1's payroll revision structure.

    Three months of the same series, not three different series: the
    establishment survey revises each month twice after first publication. So the
    "current month" figure here is the first print of the latest month, and the
    two revision fields are the amounts by which the prior two months have been
    revised **since their own first prints**.
    """

    model_config = ConfigDict(extra="forbid")

    current_month_nfp: float = Field(
        description=(
            "Latest month's nonfarm payroll change as FIRST PUBLISHED, thousands. "
            "Deliberately the first print rather than the revised figure: the "
            "point of this model is to compare the headline a reader saw against "
            "what the prior months turned out to be."
        )
    )
    prior_month_revision: float = Field(
        description=(
            "Net revision to the PRIOR month, thousands. NEGATIVE means the prior "
            "month was revised DOWN."
        )
    )
    two_months_ago_revision: float = Field(
        description=(
            "Net revision to the month TWO months back, thousands. Negative means revised down."
        )
    )


def nfp_revision_adjusted_read(inputs: RevisionInputs) -> ModelResult:
    """The payroll print net of what the prior two months turned out to be.

    ``value`` is a ``dict`` with ``headline``, ``net_revisions`` and
    ``revision_adjusted`` (all ``float``, thousands).

    The reason this is a model and not a subtraction anyone would do anyway:

    * A headline "beat" accompanied by large **downward** revisions to the prior
      two months is a **weaker** picture than the headline. The month that
      beat expectations was offset by months that were previously reported as
      better than they were.
    * This is not a rounding artefact. **Revisions are largest exactly at
      cyclical turning points** — the birth-death imputation and seasonal
      factors are least reliable when the trend is changing — so the moments
      when revisions matter most are the moments they are largest. An analyst
      reading headlines alone is most misled precisely when it costs most.

    Hand calculation::

        headline +250k, revisions -120k and -80k
            net_revisions = -200k
            revision_adjusted = +250 - 200 = +50k
            misleading = (250 > 0) and (-200 < -50) = True

    The ``misleading`` condition requires BOTH a positive headline and net
    revisions below the configured threshold. A negative headline with negative
    revisions is not "misleading" — the revisions are confirming it, not
    contradicting it. Flagging that case would train a reader to ignore the flag.
    """
    settings = _revision_thresholds()
    net_revisions = inputs.prior_month_revision + inputs.two_months_ago_revision
    adjusted = inputs.current_month_nfp + net_revisions
    misleading = inputs.current_month_nfp > 0 and net_revisions < settings.misleading_net

    interpretation = (
        f"Headline {inputs.current_month_nfp:+.0f}k, net revisions to the prior "
        f"two months {net_revisions:+.0f}k, revision-adjusted {adjusted:+.0f}k"
    )

    if misleading:
        warnings = [
            f"Headline beat masked by {net_revisions:+.0f}k of net downward "
            f"revisions. The underlying picture is weaker than "
            f"{inputs.current_month_nfp:+.0f}k suggests — the revision-adjusted "
            f"read is {adjusted:+.0f}k.",
            "Revisions are largest at cyclical turning points, so a large "
            "downward revision alongside a headline beat is itself information "
            "about where in the cycle the economy sits (Module 6.1).",
        ]
    else:
        warnings = []

    warnings.append(
        "Only two months of revisions are counted. Payrolls are revised twice "
        "more over the following year via the annual benchmark, so even the "
        "revision-adjusted figure here is provisional."
    )

    return ModelResult(
        model_name="nfp_revision_adjusted_read",
        country="us",
        as_of=utc_now(),
        value={
            "headline": inputs.current_month_nfp,
            "net_revisions": net_revisions,
            "revision_adjusted": adjusted,
        },
        confidence=compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True)),
        interpretation=interpretation,
        context=(
            f"Prior-month revisions matter as much as the headline (Module 6.1). "
            f"Threshold for a misleading headline: net revisions below "
            f"{settings.misleading_net:+.0f}k alongside a positive headline."
        ),
        inputs_used=[
            "current_month_nfp",
            "prior_month_revision",
            "two_months_ago_revision",
        ],
        warnings=warnings,
    )


class InflationSubMeasures(FiniteInputs):
    """Section 6.3's three Phase 1 inflation sub-measures, all month-over-month.

    Every field is a ``m/m`` percent change in the same units as its
    counterparts, which is what makes the average in
    ``inflation_breadth_score`` meaningful. The fuller measure set (supercore,
    trimmed mean, median) requires BLS/Dallas Fed/Cleveland Fed direct sources
    that OpenBB does not carry — hence a three-measure Phase 1 proxy rather than
    the six-plus measure convergence of Module 5.3/13.2.
    """

    model_config = ConfigDict(extra="forbid")

    cpi_headline_mom: float = Field(description="CPI headline, month-over-month percent.")
    cpi_core_mom: float = Field(description="CPI core (ex food and energy), m/m percent.")
    pce_core_mom: float = Field(description="PCE core, m/m percent.")


def _breadth_direction_sentence(
    all_positive: bool,
    all_negative: bool,
    all_flat: bool,
    divergent: bool,
) -> str:
    """The breadth read's direction, in words, for the Section 3 ``direction`` field.

    Named rather than inlined because the states are genuinely distinct and a
    nested conditional collapses them: "all rising", "all falling", "all flat",
    and "measures disagree" are not a direction and its negation.

    The FLAT state is here and not folded into "disagree" because an all-zero
    reading is the opposite of a disagreement: the three measures agree exactly,
    the answer is simply "no movement". Reporting it as CONFLICTED (D-040's
    shape) told the reader the measures pull in opposing directions when in fact
    none of them moved, and it also charged the divergent confidence for a
    reading that has no divergence to charge for (D-050: a real state real data
    produces must be representable, and must be representable as itself).

    ``divergent`` is passed by the caller rather than derived from the negation
    of the other three flags, because "not all the same way" and "genuinely
    opposed" are different questions and only the second is a conflict — a
    single sign alongside zeros is convergent. Passing the caller's own
    predicate is what makes the sentence unable to disagree with the branch that
    chose the confidence.
    """
    if all_positive:
        return "rising: all three measures positive"
    if all_negative:
        return "falling: all three measures negative"
    if all_flat:
        return "flat: all three measures at zero, so there is no direction to read"
    if divergent:
        return "CONFLICTED: measures disagree in sign, so the average describes neither"
    # Not all the same way, not flat, yet no genuine opposition: the only
    # readings that moved came from one sign, so the non-neutral measures agree.
    return "convergent: measures agree on the sign of the readings that moved"


def inflation_breadth_score(measures: InflationSubMeasures) -> ModelResult:
    """Phase 1 three-measure breadth proxy. ``value`` is a ``float`` in percent.

    "Breadth" asks whether inflation pressure is broad or concentrated. With
    three headline measures the crude version is: do they all point the same
    way? If headline, core CPI, and core PCE all rise together, the pressure is
    unlikely to be one volatile component. If core CPI rises while core PCE
    falls, something measure-specific is driving the difference and the reading
    should not be treated as a trend.

    Hand calculation for ``+0.2, +0.3, +0.1``:
        same direction (all positive) -> convergent
        average = (0.2 + 0.3 + 0.1) / 3 = +0.2

    Two honest limitations, both carried in the output rather than left implied:

    * Three measures is a **proxy**, not the six-plus measure convergence of
      Module 5.3/13.2. The confidence is low accordingly.
    * "Same direction" is a **sign test**, which is a weak statistic. Two of
      three measures at +0.001% and one at +5.0% is reported as convergent. The
      interpretation states the average so a reader can see the magnitudes, and
      the limitation is a warning.

    **Four states, not two.** Convergent-rising and convergent-falling are the
    same-direction cases; **flat** is the case where all three are exactly zero
    (agreement, no direction, and the convergent confidence); **divergent** is
    the case where the measures genuinely oppose. The divergent state is entered
    only when a positive AND a negative reading both exist — never merely when
    "not all the same way", which an all-zero reading also satisfies and which
    would report a flat month as a conflict (D-040). A zero reading is not
    evidence for either direction, per AGENTS.md Resolution Finding #10's
    ``classify_convergence``: it is ignored when scoring agreement, so a reading
    with a single sign and zeros is convergent, not conflicted.

    The confidence in the divergent branch is lower **by config**, not by a
    literal, and is not produced by ``compute_confidence()`` because Section 6.3
    defines it as a property of this specific convergence test rather than of
    the model's factor states (the same exception as Section 22.5's proxy).
    """
    values = [measures.cpi_headline_mom, measures.cpi_core_mom, measures.pce_core_mom]
    all_positive = all(value > 0 for value in values)
    all_negative = all(value < 0 for value in values)
    all_flat = all(value == 0 for value in values)
    # A reading is divergent only when the measures actually pull in OPPOSING
    # directions. The negation of "all one way" is not that: an all-zero reading
    # satisfies neither `all_positive` nor `all_negative`, yet nothing opposes
    # anything. Requiring a sign on both sides is what makes the divergent
    # branch mean what its wording says (D-040: a `>0`/`else` pair that reports
    # a flat market as a move; D-050: a real state real data produces — three
    # flat m/m prints, reachable on the live path — must be representable as
    # itself).
    divergent = any(value > 0 for value in values) and any(value < 0 for value in values)
    average = sum(values) / len(values)

    breadth = get_settings().inflation.breadth
    confidence = breadth.divergent if divergent else breadth.convergent

    if all_positive:
        interpretation = (
            f"Convergent inflation signal across headline CPI, core CPI and core "
            f"PCE — all three rising, average {average:+.2f}% m/m"
        )
        warnings: list[str] = []
    elif all_negative:
        interpretation = (
            f"Convergent inflation signal across headline CPI, core CPI and core "
            f"PCE — all three falling, average {average:+.2f}% m/m"
        )
        warnings = []
    elif all_flat:
        interpretation = (
            f"Flat inflation reading across headline CPI, core CPI and core PCE "
            f"— all three at 0.00% m/m, average {average:+.2f}% m/m"
        )
        warnings = [
            "All three sub-measures are exactly flat (0.00% m/m). This is NOT a "
            "disagreement — the measures agree, that inflation did not move this "
            "month. It is also not breadth evidence: a flat reading at the "
            "reporting precision can hide offsetting movements inside each "
            "measure, so no direction is claimed (Section 6.3, Module 13).",
        ]
    elif divergent:
        interpretation = (
            f"Divergent inflation signal across headline CPI, core CPI and core "
            f"PCE, average {average:+.2f}% m/m"
        )
        warnings = [
            "Sub-measures disagree — per Module 13, investigate the source of "
            "the divergence before treating this as a trend. The average of "
            "opposing readings describes neither.",
        ]
    else:
        # One sign moved, the rest are exactly flat. Not a conflict (no
        # opposition) and not full convergence either — the moved readings agree
        # with each other, and the zero reads are not evidence either way
        # (Resolution Finding #10's non-neutral rule).
        interpretation = (
            f"Convergent inflation signal across headline CPI, core CPI and core "
            f"PCE — the readings that moved agree in sign, the rest are flat, "
            f"average {average:+.2f}% m/m"
        )
        warnings = [
            "Some sub-measures printed exactly flat (0.00% m/m) while the rest "
            "moved one way. A flat reading is not evidence for either direction "
            "(Resolution Finding #10), so it neither counts toward agreement nor "
            "triggers a conflict; the direction is read from the measures that "
            "moved. Confirm the flat prints are genuinely flat rather than "
            "rounded near-zero readings before relying on the breadth.",
        ]

    warnings.append(
        "Phase 1 three-measure proxy. Full six-plus measure convergence "
        "(supercore, trimmed mean, median) requires BLS/Dallas Fed/Cleveland Fed "
        "direct sources and is a Phase 5+ upgrade (Module 5.3/13.2)."
    )
    warnings.append(
        "Convergence is a SIGN test and therefore weak: three measures at "
        "+0.01% read as convergent just as three at +0.5% do. Compare the "
        "reported average against recent history before treating convergence as "
        "evidence of breadth."
    )

    return ModelResult(
        model_name="inflation_breadth_score",
        country="us",
        as_of=utc_now(),
        value=round(average, 4) + 0.0,
        confidence=confidence,
        interpretation=interpretation,
        context=(
            "Phase 1 simple 3-measure breadth; full 6+ measure convergence deferred to Phase 5"
        ),
        inputs_used=["cpi_headline_mom", "cpi_core_mom", "pce_core_mom"],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percent, month-over-month (an AVERAGE across three measures)",
        direction=_breadth_direction_sentence(all_positive, all_negative, all_flat, divergent),
        assumptions=[
            "Three measures are a sufficient proxy for breadth. Full six-plus "
            "measure convergence (supercore, trimmed mean, median) needs "
            "BLS/Dallas Fed/Cleveland Fed direct sources and is a Phase 5+ "
            "upgrade — this is a deliberate, named substitution, not a silent "
            "one (Section 10).",
            "'Breadth' is operationalised as a SIGN TEST: do all three point the "
            "same way. A sign test discards magnitude, which is the weak "
            "statistic the next limitation names.",
            "The three m/m readings are comparable because all three are "
            "month-over-month percent changes. Mixing a m/m with a YoY would "
            "make the average meaningless, and the units alone would not reveal "
            "it.",
            "The confidence is a property of THIS convergence test, read from "
            "config, and is deliberately NOT produced by compute_confidence() "
            "(Section 6.3's exception, the same as Section 22.5's proxy). A "
            "reader comparing this confidence to a compute_confidence() value is "
            "comparing two different things.",
            "The divergent branch is entered ONLY on genuine directional "
            "OPPOSITION: at least one positive AND at least one negative "
            "reading. A zero reading is not evidence for either direction "
            "(AGENTS.md Resolution Finding #10's `classify_convergence` rule), "
            "so it neither counts toward agreement nor triggers conflict, and an "
            "all-zero reading is FLAT — an agreement with no direction — "
            "carrying the convergent confidence because there is no divergence "
            "to penalise. Reading 'not all the same way' as 'divergent' would "
            "report a motionless month as a conflict (D-040/D-050).",
        ],
        data_provenance=[
            "cpi_headline_mom — CPIAUCSL (BLS headline CPI) m/m percent, computed "
            "in the orchestrator's _inflation_leg",
            "cpi_core_mom — CPILFESL (BLS core CPI) m/m percent, same",
            "pce_core_mom — PCEPILFE (BEA core PCE) m/m percent, same",
            "All three read at the snapshot's own as_of, not wall-clock time",
        ],
        limitations=[
            "WEAK STATISTIC: a sign test. Three measures at +0.001% read as "
            "'convergent' exactly as three at +5.0% do, so convergence alone says "
            "nothing about the size of the pressure. The average must be compared "
            "against recent history before convergence is treated as evidence.",
            "THREE MEASURES, NOT SIX-PLUS: Module 5.3/13.2's full convergence test "
            "is a Phase 5+ upgrade. Three measures is a proxy whose confidence is "
            "low by construction.",
            "The three measures are not fully independent: headline CPI contains "
            "core CPI's components, and CPI and PCE share underlying source data "
            "even though they are different agencies (BLS and BEA). Agreement "
            "between them is therefore weaker evidence than three genuinely "
            "disjoint measurements would be.",
            "The average in `value` is an ARITHMETIC mean of the three m/m "
            "readings, which is not a price index: on a divergent reading it "
            "averages opposing movements and describes neither. Use it as a "
            "central-tendency indicator, not as an inflation rate.",
            "A FLAT reading (all three at 0.00%) leaves `value` at 0.00 and "
            "claims no direction. That is an honest 'no movement at this "
            "measurement resolution', not evidence that inflation is absent: at "
            "the reported precision a +0.004% and a -0.004% reading both print "
            "as 0.00%, so offsetting sub-measure movements can hide inside a "
            "flat print.",
            "Points-in-time: m/m changes are computed from the two most recent "
            "observations, so a revision to either changes the reading. The O-7 "
            "filter applies upstream but is SUFFICIENT BUT NOT SOUND "
            "(models/as_of.py), and no vintage datetime exists on this "
            "installation (Section 6, measured 2026-09-19).",
        ],
        decision_relevance=(
            "Section 16.2's Q1 inflation read (via the orchestrator's "
            "_inflation_leg) and the Module 3 regime classifier's inflation axis "
            "input. The sign convention is load-bearing for the regime: the "
            "classifier reads inflation MOMENTUM, so a 'falling' breadth read is "
            "what makes 'disinflation' reachable."
        ),
        decision_prohibition=[
            "MUST NOT be read as an inflation RATE. `value` is an average of "
            "three month-over-month changes, not a level and not an annualised "
            "rate. Quoting it as 'inflation is X%' misreads the unit by a factor "
            "of twelve at least.",
            "MUST NOT be treated as evidence of breadth when the measures "
            "diverge. On the divergent branch the value is published but the "
            "interpretation and the warning both say it describes neither "
            "movement, and Module 13 requires the divergence be investigated "
            "rather than averaged.",
            "MUST NOT be read as a CONFLICT when the reading is FLAT. All three "
            "at 0.00% is agreement with no direction, and the ``direction`` "
            "field says 'flat' rather than 'CONFLICTED'. A consumer keying off "
            "the word 'CONFLICTED' to trigger a divergence investigation must "
            "not fire on a motionless month (D-040/D-050).",
            "MUST NOT have its confidence compared against a "
            "compute_confidence() value: this confidence comes from config and "
            "answers a different question (Section 6.3).",
            "MUST NOT be used as the sole input to a regime label. Section 21's "
            "regime_tension flag exists precisely because a label resting on one "
            "axis is a weaker claim, and this is only one of the two axes.",
        ],
    )
