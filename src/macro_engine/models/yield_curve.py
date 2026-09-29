"""Module 8 — yield curve analytics: slope, breakevens, and decomposition.

AGENTS.md Section 6.6 (amended by Section 22.5 for the market-implied path) and
Section 20.8. This is a Tier 1 group: every function consumes snapshot fields
directly and depends on no other model.

The interpretation that matters most here
----------------------------------------
A curve inversion is the market's most-watched recession signal, and Section
6.6 attaches the honest caveat to it: the lead is "6-24 months and variable".
That caveat is not decoration. An inversion that arrives and is followed by a
recession two years later is *indistinguishable in real time* from an inversion
followed by no recession, and a system that presents the signal without the
variance invites a user to treat it as a calendar event. The warning text is
therefore load-bearing output, not boilerplate.

The decomposition discipline
----------------------------
``decompose_yield`` splits a nominal yield into an expectations component and a
term premium. The term premium is not observable — Section 21.4 item 13 groups
it with r*, u* and potential GDP — so when no term-premium series is available
the function returns the raw yield **unchanged** and attaches a hard,
unconditional warning. It never silently presents a contaminated number as a
clean estimate. Section 22.5 states this requirement explicitly for the
market-implied path, and the same logic governs the decomposition it depends on.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)
from macro_engine.models.econometrics import compute_pca

__all__ = [
    "BreakevenInputs",
    "CrossMarketRVInputs",
    "CurveDecompositionInputs",
    "CurveSlopeInputs",
    "CurveTradeConstructor",
    "InversionHistoryInputs",
    "breakeven_inflation",
    "construct_breakeven_trade",
    "construct_cross_market_rv",
    "construct_duration_weighted_curve_trade",
    "curve_slope",
    "decompose_yield",
    "inversion_probability_adjustment",
    "yield_curve_pca",
]


class CurveSlopeInputs(FiniteInputs):
    """Two tenors from one observed curve.

    Tenor labels are validated against the supplied dict rather than defaulted,
    so a caller asking for ``"2yr"`` from a curve keyed ``"2y"`` gets a clear
    error instead of a ``KeyError`` traceback or — worse — a silent miss if the
    caller had used ``.get()``.
    """

    model_config = ConfigDict(extra="forbid")

    tenors: dict[str, float] = Field(
        description="Tenor label -> yield in PERCENT, e.g. {'2yr': 4.25, '10yr': 4.05}."
    )
    short: str = Field(default="2yr", description="Short tenor label present in `tenors`.")
    long: str = Field(default="10yr", description="Long tenor label present in `tenors`.")


class BreakevenInputs(FiniteInputs):
    """A nominal yield and its TIPS real counterpart at the same tenor."""

    model_config = ConfigDict(extra="forbid")

    nominal: float = Field(description="Nominal Treasury yield for the tenor, in percent.")
    tips_real: float = Field(description="TIPS real yield at the SAME tenor, in percent.")
    tenor: str = Field(description="Tenor label, echoed into the interpretation.")


class CurveDecompositionInputs(FiniteInputs):
    """A yield plus an optional, possibly-tenor-mismatched term premium.

    ``term_premium`` is optional-by-absence rather than defaulted-to-zero. A
    zero default would make the decomposition a silent no-op that still reports
    itself as a decomposition — the exact failure Section 22.5 forbids.
    """

    model_config = ConfigDict(extra="forbid")

    nominal_yield: float = Field(description="Observed nominal yield, in percent.")
    term_premium: float | None = Field(
        default=None,
        description=(
            "ACM-style term premium at the matched tenor, in percent. None means "
            "'no series available at this tenor' — not 'zero'."
        ),
    )
    tenor: str = Field(description="Tenor label of `nominal_yield`.")


def _slope_direction_sentence(slope_bp: float) -> str:
    """The curve slope's sign, in words, for the Section 3 ``direction`` field.

    Three states, and the middle one is real: a spread of exactly zero is a FLAT
    curve, neither normal nor inverted, and the branch that computes it already
    distinguishes ``shape == "flat"``. Consuming the same three states here keeps
    the sentence and the interpretation from disagreeing.

    Note the field's semantics (Section 3): ``direction`` says what the value
    MEANS, not the sign of the number. "Normal / flat / inverted" is the meaning
    a reader wants; "positive / zero / negative" would restate the arithmetic
    without interpreting it.
    """
    if slope_bp > 0:
        return "normal: upward-sloping (long above short)"
    if slope_bp == 0:
        return "flat: long and short coincide"
    return "inverted: downward-sloping (short above long)"


def curve_slope(inputs: CurveSlopeInputs) -> ModelResult:
    """Long-minus-short spread, the primary curve-shape measure.

    A positive spread is a normal upward-sloping curve; negative is an
    inversion, which Section 6.6 reads as the market pricing future cuts.

    Confidence is high because this is arithmetic on two observed values with
    no estimation anywhere — but it is *computed* rather than asserted as 0.9,
    per Section 22.8.
    """
    if inputs.short not in inputs.tenors:
        raise KeyError(
            f"short tenor {inputs.short!r} is not in the supplied curve; "
            f"available: {sorted(inputs.tenors)}"
        )
    if inputs.long not in inputs.tenors:
        raise KeyError(
            f"long tenor {inputs.long!r} is not in the supplied curve; "
            f"available: {sorted(inputs.tenors)}"
        )
    if inputs.short == inputs.long:
        raise ValueError(
            f"short and long tenor are both {inputs.short!r}; a spread against "
            f"itself is identically zero and measures nothing."
        )

    slope_bp = (inputs.tenors[inputs.long] - inputs.tenors[inputs.short]) * 100

    if slope_bp < 0:
        shape = "inverted"
    elif slope_bp == 0:
        shape = "flat"
    else:
        shape = "normal"

    return ModelResult(
        model_name="curve_slope",
        country="us",
        as_of=utc_now(),
        value=round(slope_bp, 1),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"{inputs.long.upper()}-{inputs.short.upper()} spread: {slope_bp:+.1f}bp ({shape})"
        ),
        context=(
            "Inversion = the market pricing future cuts. Section 6.6's historical "
            "lead is 6-24 months and variable (Module 8.1)."
        ),
        inputs_used=["yield_curve"],
        warnings=[
            "Timing lag is 6-24 months and variable — this is not a calendar signal, "
            "and an inversion that precedes a recession by two years is "
            "indistinguishable in real time from one that precedes none."
        ],
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="basis points",
        direction=_slope_direction_sentence(slope_bp),
        assumptions=[
            "Two points on the observed curve are sufficient to characterise its "
            "SHAPE. A slope is a two-point statistic by definition; it cannot "
            "distinguish a parallel shift from a twist, and a single slope says "
            "nothing about curvature.",
            "The tenors supplied are the ones the caller names, and the spread is "
            "computed at exactly those maturities. A slope between two different "
            "tenors is a different quantity, not a rescaling of this one.",
            "The curve is read from a single observation timestamp. The nominal "
            "curve is a snapshot, so it carries whatever intraday and "
            "quote-timing effects the source has — this model applies no "
            "smoothing or fitting.",
            "An inverted curve is read as the market pricing future cuts. That is "
            "an interpretation of a spread, not something the arithmetic "
            "establishes.",
        ],
        data_provenance=[
            "yield_curve — the snapshot's nominal treasury curve, an "
            "11-tenor set on a live 2026-09-17 snapshot (1mo 3.97 .. 30yr 5.29) "
            "as observed by the data layer",
            "Tenors are selected by config "
            "(instrument_selection.default_short_tenor / default_long_tenor) and "
            "resolved against the curve's actual keys; an unresolvable tenor "
            "abstains rather than substituting a different maturity",
        ],
        limitations=[
            "NOT A PROBABILITY AND NOT A TIMING SIGNAL. The historical lead over "
            "recessions is 6-24 months AND VARIABLE, so an inversion that "
            "precedes a recession by two years is, in real time, "
            "indistinguishable from one that precedes none. The lead is a "
            "statistical regularity, not a forecast horizon.",
            "TWO POINTS ONLY: this measures slope and nothing about curvature or "
            "level. A steep curve at a low level and a steep curve at a high "
            "level are the same number here, and they are different regimes.",
            "No decomposition: this is the raw spread, so it contains inflation "
            "expectations, a term premium and a real-rate component. There is no "
            "term-premium series wired (Section 22.5 defers ACM to Phase 5+), so "
            "the spread cannot be attributed among them.",
            "The curve is not adjusted for the market's own conventions around "
            "on-the-run versus off-the-run issues or bills versus coupons; the "
            "source curve is taken as given.",
            "Points-in-time: the curve carries one observation timestamp and no "
            "release or vintage datetime (Section 6, measured 2026-09-19). A "
            "backtest reading a stored curve cannot prove which revision of it "
            "it holds.",
        ],
        decision_relevance=(
            "Module 8.1's curve-shape read, carried on the thesis beside the "
            "breakevens. It is the market-shape context for an outright or "
            "curve-expression thesis, and it informs Section 16.2's Q3/Q4 market "
            "read — but it is not itself a gate."
        ),
        decision_prohibition=[
            "MUST NOT be used as a recession forecast or a timing trigger. The "
            "6-24 month, variable lead is stated in the model's own warning and "
            "in `limitations`; treating the spread as a dated signal is the "
            "error this prohibition names.",
            "MUST NOT be read as evidence about the LEVEL of rates. A slope of "
            "+100bp is consistent with a 1%/2% curve and with a 5%/6% curve, "
            "and those are different policy environments.",
            "MUST NOT be attributed to yield-curve control, QE, or any policy "
            "instrument on its own. Attributing a spread change to a cause "
            "requires the decomposition this model does not perform.",
        ],
    )


def _breakeven_direction_sentence(breakeven: float) -> str:
    """The breakeven's direction, in words, for the Section 3 ``direction`` field.

    **Deliberately refuses to state a direction.** A breakeven is an inflation
    *compensation* level in percent, and there is no target, no equilibrium and
    no neutral band in this model against which "high" or "low" could be
    defined. Calling 2.4% "above target" would import the Fed's 2% objective
    into a market-determined compensation level — two different quantities — and
    calling a rise "hawkish" would assume the move came from expectations rather
    than from the risk premium this model explicitly cannot strip out.

    So the sentence states the LEVEL and the one comparison the model can
    actually support: against zero, which is the point below which the implied
    real yield exceeds the nominal — an economic impossibility that would
    indicate a data error rather than a market view. That is a sanity statement,
    not a directional one, and saying so is more honest than manufacturing a
    direction the model has no basis for.

    A negative breakeven is not impossible in principle (it has happened in
    stressed markets, where TIPS demand distorts the real leg), but it is
    unusual enough to be worth naming rather than folding into "below average".
    """
    if breakeven > 0:
        return (
            f"{breakeven:.2f}% inflation compensation — a LEVEL, not a direction; "
            f"this model has no target or neutral band to compare it against"
        )
    if breakeven == 0:
        return "0.00% compensation — nominal and real yields coincide at this tenor"
    return (
        f"{breakeven:.2f}% NEGATIVE inflation compensation — nominal below real at "
        f"this tenor, which indicates a TIPS-liquidity distortion rather than a "
        f"market inflation view"
    )


def breakeven_inflation(inputs: BreakevenInputs) -> ModelResult:
    """Nominal minus TIPS real — the market's implied inflation compensation.

    The term "compensation" is used in the interpretation rather than
    "expectation" because the difference contains an inflation risk premium.
    Section 6.6 flags this, and the distinction has a practical consequence: a
    rising breakeven can mean the market expects more inflation OR that it
    demands more compensation for uncertainty, and the two call for opposite
    policy readings.
    """
    breakeven = inputs.nominal - inputs.tips_real

    return ModelResult(
        model_name="breakeven_inflation",
        country="us",
        as_of=utc_now(),
        value=round(breakeven, 2),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(f"{inputs.tenor} breakeven inflation compensation: {breakeven:.2f}%"),
        context=(
            f"Nominal={inputs.nominal:.2f}%, TIPS real={inputs.tips_real:.2f}%. "
            f"This is inflation COMPENSATION, not a pure expectation."
        ),
        inputs_used=["yield_curve", "tips_yields"],
        warnings=[
            "Breakeven includes an inflation risk premium and a TIPS liquidity "
            "premium — it is not pure expected inflation (Module 8.2). A rising "
            "breakeven can reflect rising uncertainty rather than rising "
            "expectations, and the two imply different policy readings."
        ],
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percent",
        direction=_breakeven_direction_sentence(breakeven),
        assumptions=[
            "Subtracting a TIPS real yield from a nominal yield of the SAME "
            "maturity isolates inflation compensation. At mismatched maturities "
            "the difference prices the curve's slope as well, which is why the "
            "orchestrator forms breakevens only at tenors present in BOTH curves.",
            "Both legs are observed market yields with no estimation step, and "
            "both are quoted on comparable conventions. A liquidity or "
            "indexation mismatch between the nominal and TIPS legs would enter "
            "the result as a bias, not as noise.",
            "The result is read as COMPENSATION, not expectation. That "
            "distinction is the model's central caveat, restated in "
            "`limitations` so a consumer that only reads this field still sees "
            "it.",
        ],
        data_provenance=[
            "yield_curve — the snapshot's nominal treasury curve at this tenor",
            "tips_yields — the snapshot's TIPS real curve, a 5-tenor set on a "
            "live 2026-09-17 snapshot (5yr 2.46 .. 30yr 3.04)",
            "The tenor is the intersection of the two curves, resolved by the "
            "orchestrator's _curve_leg; no tenor is substituted to force a match",
        ],
        limitations=[
            "NOT PURE EXPECTED INFLATION. The difference contains an inflation "
            "risk premium AND a TIPS liquidity premium. A rising breakeven can "
            "mean the market expects more inflation or that it demands more "
            "compensation for uncertainty, and the two imply OPPOSITE policy "
            "readings. This single number cannot separate them.",
            "No term-premium series is wired (Section 22.5 defers ACM to Phase "
            "5+), so the premium component cannot be quantified or removed — only "
            "named.",
            "TIPS liquidity is structurally worse than nominal Treasury "
            "liquidity, and the gap widens under stress. The breakeven therefore "
            "moves for reasons unrelated to inflation, most sharply in exactly "
            "the episodes when it would be most consulted.",
            "A single-tenor breakeven is a point on the compensation curve, not "
            "the curve. The orchestrator emits one per common tenor precisely so "
            "a reader can see the term structure rather than one number.",
            "Points-in-time: both legs carry one observation timestamp and no "
            "release or vintage datetime (Section 6, measured 2026-09-19).",
        ],
        decision_relevance=(
            "Module 8.2's inflation-compensation read, carried beside the curve "
            "slope on the thesis. It is the market's own inflation view, which "
            "Section 16.2's market read (Q3/Q4) and the model-versus-market gap "
            "draw on as context."
        ),
        decision_prohibition=[
            "MUST NOT be quoted as 'the market expects X% inflation'. The value "
            "is compensation, which includes two premia; the prohibited phrasing "
            "is stated verbatim because it is the reading a consumer is most "
            "likely to publish.",
            "MUST NOT be attributed to policy expectations alone. A breakeven "
            "move during a liquidity event is more likely a TIPS liquidity "
            "effect than a change in expected inflation.",
            "MUST NOT be compared across tenors as if the differences were pure "
            "inflation-expectations term structure: the premia vary by tenor, so "
            "the differences confound expectation and compensation.",
            "MUST NOT be used as an input to the model-implied policy path. "
            "derive_market_implied_policy_path consumes the NOMINAL curve; "
            "feeding it a breakeven would substitute an inflation-compensation "
            "measure for a nominal rate.",
        ],
    )


def decompose_yield(inputs: CurveDecompositionInputs) -> ModelResult:
    """Split a nominal yield into expectations and term premium.

    ``nominal = expectations + term_premium``

    The term premium is **not observable** (Section 21.4 item 13). When a
    term-premium estimate is supplied, this returns the expectations component
    and reports moderate confidence, because the split inherits the premium
    estimate's own model dependence. When it is absent, the raw yield is
    returned **unchanged** with a hard warning — Section 22.5 requires exactly
    this behaviour, and the alternative (treating the raw yield as the
    expectations component) presents a contaminated number as a clean one. That
    is a silent failure of the kind that only shows up as a wrong trade.
    """
    if inputs.term_premium is not None:
        expectations_component = inputs.nominal_yield - inputs.term_premium
        confidence = compute_confidence(
            ConfidenceInputs(depends_on_unobservable=True, source_independence_count=0)
        )
        value: float | dict[str, float | None] = {
            "expectations_component": round(expectations_component, 3),
            "term_premium": inputs.term_premium,
            "nominal_yield": inputs.nominal_yield,
        }
        warnings = [
            "Term premium is a MODEL ESTIMATE (ACM-style), not an observation. "
            "The split inherits its model dependence (Module 8/20.8)."
        ]
        interpretation = (
            f"{inputs.tenor} decomposition: {inputs.nominal_yield:.3f}% nominal = "
            f"{expectations_component:.3f}% expectations + {inputs.term_premium:.3f}% term premium"
        )
    else:
        expectations_component = inputs.nominal_yield
        confidence = compute_confidence(
            ConfidenceInputs(depends_on_unobservable=True, source_independence_count=0)
        )
        value = {
            "expectations_component": None,
            "term_premium": None,
            "nominal_yield": inputs.nominal_yield,
        }
        warnings = [
            "NO TERM PREMIUM AVAILABLE AT THIS TENOR — the decomposition was NOT "
            "performed. The raw yield is returned unchanged and is CONTAMINATED by "
            "term premium; it is not an expectations estimate. Section 22.5 requires "
            "this be surfaced rather than silently substituted."
        ]
        interpretation = (
            f"{inputs.tenor}: decomposition UNAVAILABLE — no term-premium estimate at "
            f"this tenor. {inputs.nominal_yield:.3f}% is the raw yield, not an "
            f"expectations component."
        )

    return ModelResult(
        model_name="decompose_yield",
        country="us",
        as_of=utc_now(),
        value=value,
        confidence=confidence,
        interpretation=interpretation,
        context=(
            "Term premium is unobservable by nature (Section 21.4 item 13). "
            "Expectations component = nominal - term premium."
        ),
        inputs_used=["nominal_yield", "term_premium"],
        warnings=warnings,
    )


class InversionHistoryInputs(FiniteInputs):
    """An observed curve slope plus how long it has been inverted.

    **Units and sign are load-bearing and cannot be recovered from two bare
    numbers**, so they are stated here: ``current_slope_bp`` is the long-minus-
    short spread in **basis points**, and is **negative when inverted** — the
    convention ``curve_slope`` returns. ``weeks_inverted`` is the length of the
    **current consecutive** inversion run; it is meaningless when the curve is
    not inverted, and is required to be zero in that case rather than ignored.

    ``base_rate_recession_prob_12mo`` is required with **no default**. Section
    15.20-B supplies ``0.15``; that value was deleted (D-049, config note)
    because the measured unconditional rate over 1976-2026 is **0.209**. A
    default would let a caller silently use a prior that is off by 40% of its own
    magnitude, and the whole point of this function is that its output is a
    *stated* base rate plus a *stated* adjustment.
    """

    model_config = ConfigDict(extra="forbid")

    current_slope_bp: float = Field(
        description=(
            "Long-minus-short spread in BASIS POINTS. Negative = inverted, "
            "matching `curve_slope`'s convention."
        )
    )
    weeks_inverted: int = Field(
        ge=0,
        description=(
            "Length of the CURRENT consecutive inversion run, in weeks. Must be "
            "0 when the curve is not inverted."
        ),
    )
    base_rate_recession_prob_12mo: float = Field(
        gt=0.0,
        lt=1.0,
        description=(
            "Unconditional P(recession within 12 months), in [0, 1]. Required: "
            "no default, because the specification's 0.15 disagrees with the "
            "measured 0.209 and a default would hide that."
        ),
    )

    @model_validator(mode="after")
    def _duration_must_match_the_sign(self) -> InversionHistoryInputs:
        """Refuse a self-contradictory pair rather than silently coercing one.

        A non-negative slope with a non-zero ``weeks_inverted`` means one of the
        two is wrong, and the function cannot tell which. The two failure modes
        it prevents are opposite and both silent:

        * A caller who reports stale duration for a curve that has since
          normalized would receive an **adjustment on a curve that is not
          inverted** — the returned probability would exceed the base rate while
          the interpretation says "not inverted".
        * A caller who passes the wrong sign convention (positive for an
          inversion) would silently take the no-adjustment branch.

        Coercing duration to zero would hide the first; ignoring the sign would
        hide the second. Raising names both.
        """
        if self.current_slope_bp >= 0 and self.weeks_inverted != 0:
            raise ValueError(
                f"current_slope_bp={self.current_slope_bp} is not an inversion "
                f"(>= 0) but weeks_inverted={self.weeks_inverted}. Either the "
                f"slope is inverted and its sign is wrong, or the duration is "
                f"stale from a previous episode; the function cannot tell which."
            )
        return self


def inversion_probability_adjustment(inputs: InversionHistoryInputs) -> ModelResult:
    """Adjust a stated recession base rate for curve-inversion depth and duration.

    Section 15.20-B. The mechanism: an inversion is the market pricing future
    cuts, and cuts follow when growth is expected to weaken. Section 6.6 attaches
    the honest caveat — the lead is **6-24 months and variable** — so this
    function deliberately caps its adjustment and never claims near-certainty.

    What this function is, stated plainly
    -------------------------------------
    It is a **heuristic placeholder, not a fitted model**, and Section 15.20-B
    says so: the mechanism is economic, the numbers are illustrative, and a
    Phase 5+ item is to replace the multiplicative form with an actual logistic
    regression. The output says this on every call. What the increment added
    (D-049) is that the placeholder now travels with the **measured** base rates
    it adjusts from, so a reader can separate the signal from the background:
    measured over 592 complete-window months, P(recession within 12 months) is
    **0.157** with a normal curve, **0.489** with an inverted one — a 3.1x ratio.

    Two design decisions worth naming
    ---------------------------------
    **The confidence is flat across every branch**, as in ``check_trilemma_tension``
    (D-048). An inverted curve does not make the *measurement* better; it makes
    the *situation* more informative. Confidence describes the evidence, and the
    evidence here is the same quality either way — so a severity-varying
    confidence would be a category error, and Section 22.8's formula produces
    one value.

    **The depth and duration factors saturate, and saturation is disclosed.**
    Beyond 100bp of depth or 26 weeks of duration the factors stop moving, so two
    materially different situations (a 30-week inversion and a 113-week one)
    return the same number. That is by design — but only because the measured
    relationship *reverses* past the duration cap, which is a finding the
    specification does not record.
    """
    settings = get_settings().yield_curve

    base_rate = inputs.base_rate_recession_prob_12mo

    if inputs.current_slope_bp >= 0:
        reached_ceiling = False
        return ModelResult(
            model_name="inversion_probability_adjustment",
            country="us",
            as_of=utc_now(),
            value={
                "adjusted_probability": base_rate,
                "base_rate": base_rate,
                "adjustment": 0.0,
                "depth_factor": 0.0,
                "duration_factor": 0.0,
                "saturated": False,
                "ceiling_binding": reached_ceiling,
            },
            confidence=compute_confidence(ConfidenceInputs()),
            interpretation=(
                f"Curve not inverted ({inputs.current_slope_bp:+.1f}bp) — "
                f"recession probability is the stated base rate, {base_rate:.1%}, "
                f"with no adjustment."
            ),
            context=(
                f"Slope={inputs.current_slope_bp:+.1f}bp. Measured unconditional "
                f"rate over {settings.base_rates.observations_measured} months: "
                f"{settings.base_rates.unconditional_12mo:.1%}."
            ),
            inputs_used=["current_slope_bp", "base_rate_recession_prob_12mo"],
            warnings=[
                "No inversion, so this is the caller's PRIOR, unchanged. It is "
                "not evidence — it is the background rate the inversion signal "
                "would have adjusted."
            ],
        )

    depth_factor = min(abs(inputs.current_slope_bp) / settings.depth_saturation, 1.0)
    duration_factor = min(inputs.weeks_inverted / settings.duration_cap_weeks, 1.0)
    adjustment = settings.max_probability_adjustment * depth_factor * duration_factor
    uncapped = base_rate + adjustment
    adjusted = min(uncapped, settings.ceiling)
    reached_ceiling = adjusted < uncapped

    saturated = (
        abs(inputs.current_slope_bp) >= settings.depth_saturation
        or inputs.weeks_inverted >= settings.duration_cap_weeks
    )
    duration_past_turn = inputs.weeks_inverted > settings.duration_cap_weeks

    return ModelResult(
        model_name="inversion_probability_adjustment",
        country="us",
        as_of=utc_now(),
        value={
            "adjusted_probability": round(adjusted, 4),
            "base_rate": base_rate,
            "adjustment": round(adjustment, 4),
            "depth_factor": round(depth_factor, 4),
            "duration_factor": round(duration_factor, 4),
            "saturated": saturated,
            "ceiling_binding": reached_ceiling,
            # The published base rates are the whole point of D-029 compliance:
            # without them a reader cannot tell 0.55 from a signal (0.489) plus
            # a prior (0.209) or from a near-coin-flip with no information.
            "inverted_base_rate": settings.base_rates.inverted_12mo,
            "not_inverted_base_rate": settings.base_rates.not_inverted_12mo,
        },
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"Recession probability (12mo): {adjusted:.1%} "
            f"(base {base_rate:.1%} + inversion adjustment {adjustment:+.1%} "
            f"from {inputs.weeks_inverted}wk at {inputs.current_slope_bp:+.1f}bp)"
        ),
        context=(
            f"Depth factor {depth_factor:.2f} (saturates at "
            f"{settings.depth_saturation:.0f}bp), duration factor "
            f"{duration_factor:.2f} (saturates at "
            f"{settings.duration_cap_weeks:.0f}wk). "
            f"Measured: inverted months carry {settings.base_rates.inverted_12mo:.1%} "
            f"vs {settings.base_rates.not_inverted_12mo:.1%} when not inverted."
        ),
        inputs_used=[
            "current_slope_bp",
            "weeks_inverted",
            "base_rate_recession_prob_12mo",
        ],
        warnings=_inversion_warnings(
            base_rate=base_rate,
            ceiling_binding=reached_ceiling,
            saturated=saturated,
            duration_past_turn=duration_past_turn,
            ceiling=settings.ceiling,
            duration_cap=settings.duration_cap_weeks,
        ),
    )


# ---------------------------------------------------------------------------
# Module 15.1 -- duration-weighted curve-trade construction
# ---------------------------------------------------------------------------


def _tenor_years(tenor: str) -> float:
    """Parse a tenor label such as ``2y`` / ``10y`` / ``30y`` into years.

    Deliberately narrow. D-058's config block records that the tenor strings
    there are interpolated into an instrument *name* and are never parsed, and
    that a consumer which does parse them must carry the years as data. This
    function is that consumer, so it accepts only the shape the config
    actually writes -- a number followed by ``y`` -- and refuses anything else
    rather than guessing. A ``"2yr"``, a ``"6m"`` or a ``"2Y"`` is a caller
    error here, not something to normalise silently.
    """
    text = tenor.strip().lower()
    if not text.endswith("y") or not text[:-1]:
        raise ValueError(
            f"tenor {tenor!r} is not a year tenor of the form '2y'/'10y'/'30y'. "
            f"This function reads the years for a duration plausibility check and "
            f"refuses to guess at any other unit."
        )
    try:
        years = float(text[:-1])
    except ValueError as exc:
        raise ValueError(
            f"tenor {tenor!r} does not carry a numeric year count before its 'y' suffix."
        ) from exc
    if years <= 0.0:
        raise ValueError(f"tenor {tenor!r} is not a positive number of years.")
    return years


class CurveTradeConstructor(BaseModel):
    """The two legs of a duration-weighted curve trade.

    Section 15.1b's shape, with three deliberate amendments.

    **1. ``duration`` means MODIFIED duration, in YEARS, and says so.** The
    specification's comment reads "modified duration of the short-tenor
    instrument" with no unit. ``bond_math.macaulay_duration`` returns
    *Macaulay* duration in *periods*, so the obvious wiring hands this
    contract a number that is neither. The notional is unaffected — the ratio
    ``D_short / D_long`` is unit-free, so a period-based caller still gets a
    correct notional and would never see the error in the output (D-059 probe
    P17/P18). What the unit *does* affect is the plausibility band below,
    which is exactly why it is stated here rather than left to a comment.

    **2. The durations are validated against their own tenors.** This is the
    check Section 15.1b's ``net_duration_residual`` cannot perform, because
    that residual is tautologically zero (see the function's docstring).

    **3. The legs must be distinct and ordered.** A steepener/flattener whose
    legs are the same point on the curve measures nothing, and a "short" leg
    longer than the "long" leg inverts the meaning of the sign.
    """

    model_config = ConfigDict(extra="forbid")

    short_tenor: str = Field(description="Near leg label, e.g. '2y'.")
    long_tenor: str = Field(description="Far leg label, e.g. '10y'.")
    short_duration: float = Field(
        gt=0.0,
        description="MODIFIED duration of the short leg, in YEARS.",
    )
    long_duration: float = Field(
        gt=0.0,
        description="MODIFIED duration of the long leg, in YEARS.",
    )
    target_notional_short: float = Field(
        gt=0.0,
        description="Desired notional of the short leg, in currency units.",
    )
    duration_is_modified: bool = Field(
        default=True,
        description=(
            "Attestation that both durations are MODIFIED, not Macaulay. The two "
            "differ by a factor of (1 + y/f), about 1-2% at current US yields, and "
            "the resulting notional error is small enough to be invisible. Because "
            "it CANNOT be detected arithmetically, the caller must state it, and a "
            "caller who is unsure sets False and gets a warning rather than a "
            "silent 1% error in the long leg."
        ),
    )
    is_steepener: bool = Field(
        default=True,
        description=(
            "The direction of the trade: True weights it as a steepener (profit "
            "from the spread widening), False as a flattener. This is a DECISION, "
            "not a derivation — the notional formula is identical either way, so "
            "it cannot be inferred from the legs. It is carried explicitly so the "
            "published `direction` is a real input rather than a constant."
        ),
    )

    @model_validator(mode="after")
    def _legs_must_be_distinct_and_ordered(self) -> CurveTradeConstructor:
        short_years = _tenor_years(self.short_tenor)
        long_years = _tenor_years(self.long_tenor)
        if short_years >= long_years:
            raise ValueError(
                f"short_tenor {self.short_tenor!r} ({short_years}y) must be strictly "
                f"inside long_tenor {self.long_tenor!r} ({long_years}y). A curve trade "
                f"whose legs coincide or are inverted measures no slope."
            )
        return self

    @model_validator(mode="after")
    def _durations_must_be_plausible_for_their_tenors(self) -> CurveTradeConstructor:
        """The check that replaces §15.1b's tautological residual.

        A modified duration cannot exceed its instrument's maturity (a 2y note
        cannot have a 2.1-year duration), and it cannot be a small fraction of
        it — the measured band across 1y..30y and coupons 1e-6..10% is
        0.1740 .. 1.0000. Bounds live in ``curve_trade:`` in config.

        Honest about its own strength: this catches unit errors, decimal-vs-
        percent mixups and order-of-magnitude transcription slips. It does NOT
        catch a 2x error at short maturities, where both legs land inside the
        band. It is a coarse net over a defect class that is otherwise
        invisible, not a precision instrument.
        """
        settings = get_settings().curve_trade
        floor = settings.minimum_duration_to_tenor
        ceiling = settings.maximum_duration_to_tenor

        for label, tenor, duration in (
            ("short", self.short_tenor, self.short_duration),
            ("long", self.long_tenor, self.long_duration),
        ):
            years = _tenor_years(tenor)
            ratio = duration / years
            if not floor <= ratio <= ceiling:
                raise ValueError(
                    f"{label}_duration {duration} is implausible for {tenor!r}: "
                    f"modified duration / tenor = {ratio:.4f}, outside the "
                    f"configured band [{floor}, {ceiling}]. A real US Treasury's "
                    f"modified duration is between 0.17x and 1.0x its maturity. "
                    f"Check the unit — this contract expects YEARS of MODIFIED "
                    f"duration, while bond_math returns PERIODS of MACAULAY "
                    f"duration."
                )
        return self


def construct_duration_weighted_curve_trade(
    inputs: CurveTradeConstructor,
) -> ModelResult:
    """Notional-weight a two-leg curve trade so net duration cancels.

    ``Notional_long = Notional_short * (Dur_short / Dur_long)``. This is what
    actually cancels level (PC1) exposure, leaving P&L driven by the spread
    change (PC2). **Equal-notional is explicitly wrong** — this function exists
    so nothing downstream builds one by mistake (Module 15.1, Section 15.1b).

    What the specification's own guard cannot do
    --------------------------------------------
    Section 15.1b publishes ``net_duration_residual`` and warns when
    ``abs(residual) >= 0.01``, described as "check duration inputs". That
    residual is **tautologically zero**:

        residual = (N_s * D_s) - (N_l * D_l)   where  N_l := N_s * (D_s / D_l)
                 = (N_s * D_s) - (N_s * (D_s / D_l) * D_l)
                 = 0     for every input, correct or not.

    It is the definition, algebraically simplified — not a check (D-059 probe
    P14). Verified: a duration wrong by a factor of ten leaves the residual at
    0.0468 and produces output indistinguishable from the correct trade. The
    only thing that ever moves it is the rounding of ``notional_long`` to two
    decimals, which is unrelated to any input error, and which makes the
    warning fire or not *on the same trade at different notional sizes*.

    So this implementation keeps the key for compatibility but states the
    residual's true status in the value, and the real check moved to the
    contract's duration/tenor plausibility band. The increment's decision
    record is D-059; the dead guard is the reason the band exists.

    What it still cannot do
    -----------------------
    **It does not verify that PC1 actually cancels.** The residual is computed
    under a parallel shift (``dy_short == dy_long``), which is the case the
    formula defines away. Whether a 2y/10y duration-weighted pair truly
    isolates the spread depends on the empirical 2y and 10y loadings on the
    first principal component, and those are not inputs here. The output says
    "net duration balances under a parallel shift", which is a statement about
    arithmetic, not about the curve.
    """
    notional_long = inputs.target_notional_short * (inputs.short_duration / inputs.long_duration)

    duration_dollars_short = inputs.target_notional_short * inputs.short_duration
    duration_dollars_long = notional_long * inputs.long_duration

    # Unrounded by design: the residual must measure the trade, not the
    # presentation. Section 15.1b rounds `notional_long` to 2dp BEFORE using it
    # here, which is the sole reason its residual is ever nonzero.
    net_duration_residual = duration_dollars_short - duration_dollars_long

    root_settings = get_settings()
    settings = root_settings.curve_trade
    tolerance = settings.display_tolerance

    warnings: list[str] = []

    # The residual is the definition. Say so, rather than implying that a
    # reader who sees ~0 has just had the durations validated.
    if abs(net_duration_residual) >= tolerance:
        warnings.append(
            f"Net duration residual {net_duration_residual:.6f} exceeds the display "
            f"tolerance {tolerance}. This is a floating-point artefact of the notional "
            f"multiplication, not evidence of a bad duration input — the residual is "
            f"zero for every input by construction. A genuinely wrong duration is "
            f"caught by the contract's duration/tenor band, not here."
        )

    if not inputs.duration_is_modified:
        warnings.append(
            "Durations were not attested as MODIFIED. If they are Macaulay durations "
            "the long leg's notional is understated by roughly the ratio "
            "(1 + y/f), about 1-2% at current US yields — small enough that no "
            "arithmetic check in this function can detect it."
        )

    # A duration-weighted curve trade is deliberately lopsided in notional: the
    # long leg is short-duration/short-tenor, so it needs fewer dollars. A
    # reader who expects two legs of similar size is looking at the wrong
    # number, and the ratio is the number that says so.
    notional_ratio = notional_long / inputs.target_notional_short

    if notional_ratio > 1.0:
        warnings.append(
            f"The long leg ({notional_long:,.2f}) is LARGER than the short leg "
            f"({inputs.target_notional_short:,.2f}), ratio {notional_ratio:.4f}. That "
            f"means the long tenor carries a SHORTER modified duration than the short "
            f"tenor, which is unusual for a curve trade and worth confirming against "
            f"the tenors: {inputs.short_tenor!r}/{inputs.long_tenor!r}."
        )

    direction = "steepener" if inputs.is_steepener else "flattener"

    # `curve_slope`-style convention: report the legs' own sizes and the ratio,
    # since the residual cannot carry that information.
    return ModelResult(
        model_name="construct_duration_weighted_curve_trade",
        country="us",
        as_of=utc_now(),
        value={
            "notional_short": inputs.target_notional_short,
            "notional_long": round(notional_long, 2),
            "notional_long_to_short_ratio": round(notional_ratio, 6),
            "duration_dollars_short": round(duration_dollars_short, 2),
            "duration_dollars_long": round(duration_dollars_long, 2),
            "net_duration_residual": round(net_duration_residual, 6),
            "net_duration_residual_is_definitional": True,
            "short_tenor": inputs.short_tenor,
            "long_tenor": inputs.long_tenor,
            "short_duration_years": inputs.short_duration,
            "long_duration_years": inputs.long_duration,
            "direction": direction,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not root_settings.is_calibrated(
                    "curve_trade.duration_to_tenor_min"
                ),
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"Short {inputs.short_tenor} notional {inputs.target_notional_short:,.2f}, "
            f"long {inputs.long_tenor} notional {notional_long:,.2f} "
            f"(duration-weighted {inputs.short_duration}/{inputs.long_duration}) — "
            f"net duration balances under a parallel shift."
        ),
        context=(
            "Duration-weighted per Module 15.1 — equal-notional would leave meaningful "
            "residual level/PC1 exposure. The net-duration residual is definitional "
            "and always zero; duration plausibility is enforced at the contract."
        ),
        inputs_used=[
            "short_tenor",
            "long_tenor",
            "short_duration",
            "long_duration",
            "target_notional_short",
        ],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Module 15.2 -- duration-matched breakeven-trade construction
# ---------------------------------------------------------------------------


class BreakevenTradeConstructor(BaseModel):
    """The two legs of a duration-matched breakeven (TIPS vs nominal) trade.

    Section 15.1b's shape (``tenor``, ``tips_duration``, ``nominal_duration``,
    ``target_notional_tips``) with four deliberate amendments, each of which
    Section 15.1b's own sample code cannot support.

    **1. ``tenor`` is validated, not free text.** The field is a bare ``str``
    in the specification and is interpolated into an interpretation string
    without ever being parsed. Here it goes through :func:`_tenor_years`,
    because the duration/tenor band needs the years — and because an
    unvalidated label would let ``"10yr"`` and ``"10y"`` name the same trade
    while publishing two different keys downstream.

    **2. Both durations are validated against the shared tenor.** This is the
    only guard the trade can carry, and it is not the one the specification's
    sibling function uses. Section 15.1b's breakeven constructor publishes
    *no* residual and has *no* ``warnings`` argument at all, so before this
    validation it had no check of any kind: a duration wrong by 10x produced a
    wrong notional, silently.

    **3. The two durations must be distinguishable — and "TIPS is longer" is
    NOT assumed.** The obvious guard is ``tips_duration > nominal_duration``,
    and D-060 probe P11 measured that it is false: over a 10y grid of 4x4
    coupons x 4 real yields x 3 breakevens, **72 of 192 cases have the nominal
    leg longer** — the ratio's realised range, recomputed through the shipped
    ``bond_math``, is **0.6820 .. 1.5528**. (An earlier draft of this docstring
    recorded 0.7624 .. 1.3790; those figures came from a simplified local
    pricer and are NOT reproducible from shipped code — O-30. The *count*, 72 of
    192, reproduces exactly.) The
    mechanism is that the two legs differ in *coupon* as well as in yield: a
    high-coupon TIPS at a high real yield prices far above par and is genuinely
    short, while a low-coupon nominal at a high yield is long. So the check is a
    symmetric band on the ratio, and the direction is
    *reported* rather than asserted.

    **4. ``duration_is_modified`` is carried, for the same reason as in
    :class:`CurveTradeConstructor`.** The ratio ``D_tips / D_nominal`` is
    unit-free, so a caller who hands over Macaulay *periods* still gets a
    notional that looks plausible — but here the error is not bounded at 1-2%:
    the two legs are converted by *different* divide-by-``(1 + y/f)`` factors,
    so a mismatch between the two legs' units is a *relative* error between
    them, not a common scaling. The unit must be stated.
    """

    model_config = ConfigDict(extra="forbid")

    tenor: str = Field(description="Shared maturity label, e.g. '10y'.")
    tips_duration: float = Field(
        gt=0.0,
        description="MODIFIED duration of the TIPS leg, in YEARS.",
    )
    nominal_duration: float = Field(
        gt=0.0,
        description="MODIFIED duration of the nominal leg, in YEARS.",
    )
    target_notional_tips: float = Field(
        gt=0.0,
        description="Desired notional of the long TIPS leg, in currency units.",
    )
    duration_is_modified: bool = Field(
        default=True,
        description=(
            "Attestation that BOTH durations are MODIFIED, not Macaulay. Unlike "
            "the curve constructor's case, a units mismatch here is not a shared "
            "scaling that partly cancels: each leg is divided by its own "
            "(1 + y/f), and the two legs have different yields, so the notional "
            "error is the RATIO of the two factors — roughly the real/nominal "
            "yield spread — and no arithmetic check in this function can see it."
        ),
    )

    @model_validator(mode="after")
    def _durations_must_be_plausible_for_the_tenor(self) -> BreakevenTradeConstructor:
        """Both legs' durations against the one maturity they share.

        A same-tenor breakeven's two legs are two *different instruments* with
        one maturity, so the per-leg band is satisfied by construction whenever
        both durations are real — which makes it necessary and not sufficient.
        The quantity that actually carries information about whether the two
        numbers belong to two legs of one trade is their ratio, checked below.
        """
        settings = get_settings().curve_trade
        floor = settings.minimum_duration_to_tenor
        ceiling = settings.maximum_duration_to_tenor
        years = _tenor_years(self.tenor)

        for label, duration in (
            ("tips", self.tips_duration),
            ("nominal", self.nominal_duration),
        ):
            ratio = duration / years
            if not floor <= ratio <= ceiling:
                raise ValueError(
                    f"{label}_duration {duration} is implausible for tenor "
                    f"{self.tenor!r}: modified duration / tenor = {ratio:.4f}, "
                    f"outside the configured band [{floor}, {ceiling}]. Both legs "
                    f"of a breakeven share this maturity, so a real US Treasury's "
                    f"modified duration is between 0.17x and 1.0x it. Check the "
                    f"unit — this contract expects YEARS of MODIFIED duration, "
                    f"while bond_math returns PERIODS of MACAULAY duration."
                )
        return self

    @model_validator(mode="after")
    def _durations_must_differ_and_stay_in_band(self) -> BreakevenTradeConstructor:
        """The ratio check — the guard Section 15.1b does not have.

        Two failure modes, refused separately because they are different
        claims. A ratio of **exactly 1.0** means the two legs are the same bond:
        the trade's net duration is zero *and* its breakeven exposure is zero,
        so it is not a breakeven trade and no notional makes it one. A ratio
        outside the configured band is a claim that the two durations do not
        belong to a TIPS and a nominal of the same maturity.

        **Stated limit:** this does not detect a swap of the two durations when
        the two are close. Swapping them in a par-like 10y case moves the ratio
        from (1/1.0) to (1.0/1) of the unchanged pair — the ratio inverts, so a
        swap *is* caught whenever the two differ; but a caller who supplies
        already-similar durations and *also* mislabels which is which gets a
        number this check cannot indict, and the output still names the legs.
        The honest reading is that the ratio is a net over transcription and
        unit errors, not a proof of correct labelling.
        """
        settings = get_settings().curve_trade
        ratio = self.tips_duration / self.nominal_duration

        if self.tips_duration == self.nominal_duration:
            raise ValueError(
                f"tips_duration and nominal_duration are both "
                f"{self.tips_duration}, so the trade has no net duration AND no "
                f"breakeven exposure — the two legs are the same instrument. A "
                f"breakeven trade exists to isolate the inflation-expectation "
                f"spread (Module 15.2); an identical pair isolates nothing."
            )

        ratio_floor = settings.minimum_breakeven_duration_ratio
        ratio_ceiling = settings.maximum_breakeven_duration_ratio
        if not ratio_floor <= ratio <= ratio_ceiling:
            raise ValueError(
                f"modified-duration ratio tips/nominal = {ratio:.4f} is outside "
                f"the configured band [{ratio_floor}, {ratio_ceiling}]. The "
                f"measured range across same-tenor US TIPS/nominal pairs is "
                f"0.76 .. 1.38 -- note that it STRADDLES 1.0, because either leg "
                f"can carry the longer duration -- so this is not a pair of legs "
                f"for one maturity. Check whether the two durations were "
                f"assigned to the wrong legs, or computed on different "
                f"conventions."
            )
        return self


def construct_breakeven_trade(inputs: BreakevenTradeConstructor) -> ModelResult:
    """Notional-weight a TIPS/nominal pair so net duration cancels.

    ``Notional_nominal = Notional_TIPS * (Dur_TIPS / Dur_nominal)``. The intent
    (Module 15.2, Section 15.1b) is that a parallel *real*-yield move cancels
    and P&L is driven by the **breakeven spread** change, isolating inflation
    expectations from real-rate direction.

    What the specification's formula actually is
    --------------------------------------------
    The rule is a pure duration ratio. The breakeven rate, the nominal yield,
    the real yield and the expected inflation rate appear nowhere on the
    right-hand side (D-060 probe P2), so the notional is a function of the two
    durations and nothing else. That is correct as far as it goes — duration is
    what converts breadths of yield into dollars — but it means the function
    cannot *verify* the property it is named after. It computes the trade that
    Module 15.2 prescribes; it does not test that the prescription achieves
    the isolation.

    What duration-matching does and does not cancel
    -----------------------------------------------
    Dollar duration is ``N * P * D``, not ``N * D``. The rule above matches
    ``N * D``, so the level cancels exactly only when **both legs price at the
    same value**. Measured through ``bond_math`` over a 600-case grid (5 tenors
    x 6 real yields x 5 breakevens x 4 coupons), a **+1bp parallel real-yield
    move with the breakeven held fixed** leaves a net P&L, per $1mm of TIPS:

    ==================  ==============================
    ``N * D`` rule      worst **-$2,394.23**
    ``N * P * D`` rule  worst **-$243.82**
    ==================  ==============================

    So the shipped rule is worse than the exact one by an order of magnitude,
    **but the exact rule is not a perfect canceller either** — $243.82 remains
    at a 30y, 8%-coupon, 0.5%-real corner, because a 1bp bump is not a
    first-order move once convexity differs between the legs. The honest
    statement is that ``N * P * D`` reduces the level residual by ~10x and does
    not eliminate it; only a duration-plus-convexity hedge would.

    The two rules' *notionals* differ by the legs' price ratio, and the shipped
    rule discounts the nominal leg by **4.43% at a 2%-coupon TIPS, 21.73% at a
    4.5% coupon and 37.56% at an 8% coupon** (10y, measured through
    ``bond_math``; the sign is negative because a high-coupon TIPS prices above
    par). Over the whole grid the shortfall runs **-2.75% .. -58.00%**, so it is
    not a rounding at any coupon: only a *low*-coupon TIPS near par is
    well-served by the specification's rule, and that is the case the
    specification's own "should be ~0" comment seems to have in mind.

    So the shipped rule is what Section 15.1b specifies, and this function
    implements it **and publishes the inputs a caller needs to switch**,
    because the two differ by more than a rounding and a caller holding a real
    book needs to know which one the desk is actually running. Whether the
    business should switch is a specification question, not an implementation
    one — **O-59**.

    What it cannot do
    -----------------
    **It does not verify that real-yield exposure cancels.** That is a claim
    about prices, and this function never sees a price. The contract carries
    durations, so the cancellation the output reports is arithmetic under the
    ``N * D`` convention. The live cross-check recomputes the residual through
    ``bond_math`` from actual coupons and yields, which is where the figures
    above come from.
    """
    root_settings = get_settings()
    settings = root_settings.curve_trade

    notional_nominal = inputs.target_notional_tips * (
        inputs.tips_duration / inputs.nominal_duration
    )

    duration_ratio = inputs.tips_duration / inputs.nominal_duration
    # The specification's sibling function publishes this ratio and this
    # function does not; without it the published pair of notionals cannot be
    # checked against the inputs that produced them.
    nominal_to_tips_ratio = notional_nominal / inputs.target_notional_tips

    duration_dollars_tips = inputs.target_notional_tips * inputs.tips_duration
    duration_dollars_nominal = notional_nominal * inputs.nominal_duration
    net_duration_residual = duration_dollars_tips - duration_dollars_nominal

    warnings: list[str] = []

    # Same disclosure as the curve constructor: the residual is the definition.
    # Section 15.1b does not publish one here at all, so a reader has nothing
    # to be misled by — but the curve trade's residual is in the same module
    # and reads the same way, and a reader who has seen that one will look for
    # this one.
    if abs(net_duration_residual) >= settings.display_tolerance:
        warnings.append(
            f"Net duration residual {net_duration_residual:.6f} exceeds the "
            f"display tolerance {settings.display_tolerance}. This is a "
            f"floating-point artefact of the notional multiplication, not "
            f"evidence of a bad duration input — the residual is zero for every "
            f"input by construction. A genuinely wrong duration is caught by the "
            f"contract's duration/tenor and duration-ratio bands, not here."
        )

    if not inputs.duration_is_modified:
        warnings.append(
            "Durations were not attested as MODIFIED. Each leg is converted by "
            "its own (1 + y/f), and the two legs have different yields, so a "
            "Macaulay-vs-modified mismatch here is a RELATIVE error between the "
            "legs — on the order of the real/nominal yield spread — rather than "
            "the small shared scaling the curve constructor warns about. No "
            "arithmetic check in this function can detect it."
        )

    # Direction is REPORTED, never assumed. Probe P11 measured 72 of 192 real
    # cases with the nominal leg longer, so a downstream reader who expects
    # "the TIPS leg always needs fewer dollars" is wrong about a third of the
    # time and the output must say which case it is looking at.
    if duration_ratio > 1.0:
        direction = "longer_tips_duration"
    elif duration_ratio < 1.0:
        direction = "longer_nominal_duration"
    else:  # pragma: no cover - refused by the contract's ratio validator
        direction = "matched"

    # The exact-rule notional differs from the shipped one by the legs' PRICE
    # ratio. This function has no prices, so it publishes the N*D form and
    # warns; the relation is derived and asserted in
    # scripts/live_breakeven_trade.py: with shipped = N_t*D_t/D_n and
    # exact = N_t*P_t*D_t/(P_n*D_n), shipped/exact = P_n/P_t, i.e.
    #     exact = shipped * P_tips / P_nom.
    # So a desk running dollar duration must SCALE DOWN by P_tips/P_nom --
    # multiply by a ratio below 1 when the TIPS trades below par. Measured over
    # 48 real configurations the correction ranges -56.4% .. +98.7% and changes
    # sign at the TIPS leg's own par price. See O-59.
    warnings.append(
        "Notional is duration-matched under the N*D convention Section 15.1b "
        "specifies. True level (PC1) cancellation needs dollar duration, "
        "N*P*D — the two differ by exactly the legs' price ratio, and the exact "
        "notional is this one scaled by P_tips/P_nom. This function cannot "
        "compute that because the contract carries no prices. Negligible when "
        "both legs are near par, material when the TIPS is trading well off par "
        "— and the sign of the correction flips at the TIPS leg's own par "
        "price, so it cannot be applied as a fixed adjustment. See O-59."
    )

    return ModelResult(
        model_name="construct_breakeven_trade",
        country="us",
        as_of=utc_now(),
        value={
            "notional_tips_long": inputs.target_notional_tips,
            "notional_nominal_short": round(notional_nominal, 2),
            "nominal_to_tips_notional_ratio": round(nominal_to_tips_ratio, 6),
            "duration_ratio_tips_to_nominal": round(duration_ratio, 6),
            "duration_dollars_tips": round(duration_dollars_tips, 2),
            "duration_dollars_nominal": round(duration_dollars_nominal, 2),
            "net_duration_residual": round(net_duration_residual, 6),
            "net_duration_residual_is_definitional": True,
            "tenor": inputs.tenor,
            "tips_duration_years": inputs.tips_duration,
            "nominal_duration_years": inputs.nominal_duration,
            "duration_direction": direction,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not root_settings.is_calibrated(
                    "curve_trade.breakeven_duration_ratio_min"
                ),
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"Long TIPS {inputs.tenor} notional {inputs.target_notional_tips:,.2f}, "
            f"short nominal {inputs.tenor} notional {notional_nominal:,.2f} "
            f"(duration-matched {inputs.tips_duration}/{inputs.nominal_duration}) — "
            f"net duration balances under a parallel shift."
        ),
        context=(
            "Duration-matched per Module 15.2 — isolates breakeven/inflation-"
            "expectations exposure from real-yield direction. The residual is "
            "definitional and always zero; duration plausibility is enforced at "
            "the contract, and the two legs are NOT assumed to be ordered by "
            "duration (measured: the nominal leg is longer in 72 of 192 real "
            "configurations)."
        ),
        inputs_used=[
            "tenor",
            "tips_duration",
            "nominal_duration",
            "target_notional_tips",
        ],
        warnings=warnings,
    )


#: Which way the hedge moves when the world gets worse. A three-way map with
#: ``unchanged`` tested FIRST, because exact equality is reachable (a caller can
#: supply the same correlation twice) and a two-way ``> 0 else "improves"`` would
#: report an unchanged correlation as an improvement — the D-052 ``_leg_direction``
#: defect, in the place where the number is the function's whole output.
HedgeDirection = Literal["degrades_under_stress", "improves_under_stress", "unchanged"]

#: Runtime-iterable mirror of :data:`HedgeDirection`, so a test can assert the
#: declared vocabulary and the producible one agree (D-045a's two halves).
_HEDGE_DIRECTIONS: tuple[str, ...] = (
    "degrades_under_stress",
    "improves_under_stress",
    "unchanged",
)

#: Where the stressed correlation came from. Section 21.1 assigns the field to
#: ``settings.yaml: risk.stress_correlation``; Section 20.12 instead hardcodes
#: ``0.9`` as a model-field default. The route is published rather than inferred,
#: because a default and a measurement of *this pair* are different claims and
#: the published number cannot distinguish them (D-043's route disclosure).
CorrelationStressedSource = Literal["caller_supplied", "config_default"]


class CrossMarketRVInputs(FiniteInputs):
    """The two legs of a duration-matched cross-market relative-value trade.

    Section 20.12's shape (``market_a``, ``market_b``, ``duration_a``,
    ``duration_b``, ``target_notional_a``, ``correlation_normal``,
    ``correlation_stressed``) with the contract Section 20.12 does not have.

    **The specification supplies no input model at all** — its sample is a bare
    ``BaseModel`` with six unconstrained fields and one literal default. So
    ``duration_b = 0`` divides by zero, ``market_a == market_b`` prices a trade
    that is long and short the same thing, and ``correlation_stressed`` silently
    becomes ``0.9`` — which is **above the normal correlation of every one of
    the eight real pairs measured** (D-062 probe P2, max ``0.820``). Each of
    those is refused or disclosed here.

    Units, because two bare floats cannot reveal a mismatch:

    * ``duration_a`` / ``duration_b`` are **MODIFIED durations in YEARS**. They
      are validated against an absolute band rather than the duration/tenor
      ratio its two siblings use: a cross-market pair has no shared maturity, so
      that ratio is undefined, and the pairwise duration ratio that replaces it
      is not a guard either — a real 3m-against-30y pair has a ratio of
      ``0.0161`` while its mirror image has ``62.21`` (D-062 probe P3).
    * ``correlation_normal`` / ``correlation_stressed`` are **pairwise Pearson
      correlations of the two legs' changes**, in ``[-1, 1]``. A pair whose
      correlation is *negative* is representable, and is where the
      specification's positive default does the most damage.
    * ``target_notional_a`` is in currency units and is the **long** leg.
    """

    model_config = ConfigDict(extra="forbid")

    market_a: str = Field(description="Descriptive label of the LONG leg, e.g. 'US IG credit'.")
    market_b: str = Field(description="Descriptive label of the SHORT leg.")
    duration_a: float = Field(
        gt=0.0,
        description="MODIFIED duration of the long leg, in YEARS.",
    )
    duration_b: float = Field(
        gt=0.0,
        description="MODIFIED duration of the short leg, in YEARS.",
    )
    target_notional_a: float = Field(
        gt=0.0,
        description="Desired notional of the LONG leg, in currency units.",
    )
    correlation_normal: float = Field(
        ge=-1.0,
        le=1.0,
        description="Pairwise correlation of the two legs' changes in normal markets.",
    )
    correlation_stressed: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description=(
            "Pairwise correlation in a stress state. ``None`` -> the configured "
            "``risk.stress_correlation``. Section 20.12 writes this as the "
            "literal default 0.9 inside the model, which Section 21 prohibits "
            "and which is not a measurement of the pair in front of you."
        ),
    )
    duration_is_modified: bool = Field(
        default=True,
        description=(
            "Attestation that BOTH durations are MODIFIED, not Macaulay. A "
            "Macaulay-periods-for-modified-years error is a ~2x factor and the "
            "absolute band cannot see it, because periods and years are the same "
            "order of magnitude at short maturities."
        ),
    )

    @model_validator(mode="after")
    def _legs_must_name_two_distinct_markets(self) -> CrossMarketRVInputs:
        """A relative-value trade needs two different things.

        Section 20.12 accepts any ``str`` for both legs and never compares them.
        Long and short the *same* market has no relative exposure, so the
        function would publish a notional, a degradation and two mandatory
        warnings about a position that cannot exist. Comparison is
        case-insensitive and whitespace-insensitive, because ``"US IG credit"``
        and ``"us ig credit "`` are the same market and a caller who typed both
        meant one.
        """
        a, b = self.market_a.strip(), self.market_b.strip()
        if not a or not b:
            raise ValueError(
                "market_a and market_b must both be non-empty labels. An empty "
                "label names no market, and the interpretation string would then "
                "describe a leg the caller never identified."
            )
        if a.casefold() == b.casefold():
            raise ValueError(
                f"market_a and market_b are the same market ({a!r}). A "
                f"cross-market relative-value trade is long one market and short "
                f"ANOTHER; with one market on both sides the relative exposure is "
                f"identically zero and there is no trade to construct. Section "
                f"20.12's sample accepts this silently."
            )
        return self

    @model_validator(mode="after")
    def _durations_must_be_plausible(self) -> CrossMarketRVInputs:
        """Each leg's modified duration against an absolute band.

        **This is the guard Section 20.12 does not have.** The specification
        publishes no residual and no ``warnings`` argument, so before this check
        a duration wrong by ten times produced a wrong notional with nothing to
        indicate it — the same silence D-060 found in Section 15.1b's breakeven
        half, reached through a different constructor.

        The band is measured, not chosen: over 80 cases spanning
        ``{3m, 2y, 5y, 10y, 30y} x {0, 2%, 4.5%, 8%} coupons x
        {0.5%, 2%, 4.5%, 8%} yields`` through the shipped ``bond_math``, real
        US Treasury modified durations run **0.4810 .. 29.9250 years**
        (D-062 probe P3).

        **Stated limit:** the band refuses an implausible duration, not a
        mislabelled one, and it cannot see a Macaulay-vs-modified mismatch at
        short maturities. That is what ``duration_is_modified`` is for.
        """
        settings = get_settings().cross_market_rv
        floor = settings.minimum_duration
        ceiling = settings.maximum_duration

        for label, duration in (
            ("duration_a", self.duration_a),
            ("duration_b", self.duration_b),
        ):
            if not floor <= duration <= ceiling:
                raise ValueError(
                    f"{label} {duration} is outside the plausible band "
                    f"[{floor}, {ceiling}] years of MODIFIED duration. Measured "
                    f"over 80 real US Treasury configurations the range is "
                    f"0.4810 (a 3m bill at 8%) to 29.9250 (a 30y zero-coupon), "
                    f"so a value here is a unit error (periods for years, or a "
                    f"percent written as a decimal) rather than a real "
                    f"instrument. Check the unit — this contract expects YEARS "
                    f"of MODIFIED duration, while bond_math returns PERIODS of "
                    f"MACAULAY duration."
                )
        return self


def construct_cross_market_rv(inputs: CrossMarketRVInputs) -> ModelResult:
    """Notional-weight two different markets so their common factor cancels.

    ``Notional_b = Notional_a * (Dur_a / Dur_b)``, long A and short B
    (Module 15.3, Section 20.12). The intent is that a move in whatever the two
    legs share cancels, leaving only the **relative** view.

    What the specification's own default does to its headline number
    -----------------------------------------------------------------
    Section 20.12 computes ``degradation = correlation_normal -
    correlation_stressed`` and describes it as the hedge degrading under stress.
    It then defaults ``correlation_stressed`` to **0.9**. Over the eight real US
    cross-market pairs measured in D-062 probe P2 the *normal* correlation runs
    **-0.623 .. 0.820**, so on the specification's own default the published
    ``hedge_degradation`` is **negative for 8 of 8 pairs** — that is, the
    specification's default asserts, silently and universally, that the hedge
    *improves* in a crisis, which is the opposite of the premise its own
    docstring states and of the LTCM mechanism it exists to encode. The measured
    *stressed* correlations (max ``0.858`` on the S&P tail, ``0.736`` on the VIX
    tail) are below 0.9 for every pair as well.

    So the number is not wrong arithmetic — it is a **sign the specification
    never checks**. This function publishes the direction as its own key, warns
    when the hedge improves, and refuses a pair whose two correlations are too
    far apart to be measurements of the same pair (``max_abs_hedge_degradation``,
    measured range 0.004 .. 0.175 on the S&P tail and 0.072 .. 0.320 on the
    VIX tail).

    Where the stressed correlation comes from
    -----------------------------------------
    ``None`` -> ``settings.risk.stress_correlation``, per Section 21.1's own
    input table. That accessor had **no consumer anywhere in the tree** until
    this function (D-062 probe P4), so the leaf was a config surface nothing
    read — which is exactly what made the default's effect invisible. The route
    is published in ``correlation_stressed_source`` rather than left to be
    inferred: a default and a measurement of *this pair* are different claims.

    What duration-matching does and does not cancel
    -----------------------------------------------
    Unchanged from its two siblings, and stated here because this function's
    *premise* is the claim: dollar duration is ``N * P * D``, not ``N * D``, so
    the common factor cancels exactly only when both legs price alike. The
    contract carries no prices, so the convention is published in ``context``
    and the relation is derived in the live cross-check. See **O-57**/**O-59**.

    What it cannot do
    -----------------
    **It cannot verify that the common factor cancels, or that the correlation
    it was handed describes this pair.** Both are claims about data this
    function never sees. It computes the trade Module 15.3 prescribes and
    reports the assumption it rests on; the measurement lives in
    ``scripts/live_cross_market_rv.py``.
    """
    root_settings = get_settings()
    settings = root_settings.cross_market_rv

    supplied = inputs.correlation_stressed
    if supplied is None:
        correlation_stressed = root_settings.risk.stress_corr
        stressed_source: CorrelationStressedSource = "config_default"
    else:
        correlation_stressed = supplied
        stressed_source = "caller_supplied"

    duration_ratio = inputs.duration_a / inputs.duration_b
    notional_b = inputs.target_notional_a * duration_ratio

    correlation_normal = inputs.correlation_normal
    degradation = correlation_normal - correlation_stressed
    degradation_bound = settings.hedge_degradation_bound
    exceeds_bound = abs(degradation) > degradation_bound

    # Three-way, and `unchanged` is FIRST because exact equality is reachable: a
    # caller may supply the same correlation twice, and `> 0 else "improves"`
    # would report that as an improvement (D-052's _leg_direction defect).
    hedge_direction: HedgeDirection
    if degradation == 0.0:
        hedge_direction = "unchanged"
    elif degradation > 0.0:
        hedge_direction = "degrades_under_stress"
    else:
        hedge_direction = "improves_under_stress"

    duration_dollars_a = inputs.target_notional_a * inputs.duration_a
    duration_dollars_b = notional_b * inputs.duration_b
    net_duration_residual = duration_dollars_a - duration_dollars_b

    warnings: list[str] = [
        # Section 20.12 mandates this one unconditionally, and the golden test
        # in Section 20.14 asserts it is always present. It is boilerplate by
        # construction, which is precisely why the CONDITIONAL warning below it
        # has to exist: a warning that always fires tells a reader nothing about
        # the trade in front of them (D-029's base-rate rule).
        "HEDGE IS A MODELING ASSUMPTION, NOT A GUARANTEE — correlation breakdown "
        "is correlated with crisis (LTCM 1998)",
        "Lower apparent risk invites HIGHER leverage — that combination is the "
        "actual LTCM failure mechanism",
        # Section 22.3: this system is US-only through Phase 4, and Section
        # 22.3.1's own blocking branch says a cross-market RV against an unbuilt
        # country system must not be fabricated. Section 20.12 labels its output
        # `country="global"`, which is the unearned genericity claim Section
        # 22.3 retracts.
        "SCOPE — the instrument set behind this constructor is US-only through "
        "Phase 4 (Section 22.3). A leg in a market whose rates system is not "
        "built cannot be hedged here, and Section 22.3.1 explicitly refuses to "
        "fabricate one.",
    ]

    if hedge_direction == "improves_under_stress":
        warnings.append(
            f"The stressed correlation ({correlation_stressed}) is BELOW the "
            f"normal one ({correlation_normal}), so the hedge reports as "
            f"IMPROVING under stress (degradation {degradation:+.3f}). That is "
            f"the state Section 20.12's own default produces for every real pair "
            f"measured, and it is the LTCM trap rather than good news: a hedge "
            f"that looks better when the world is worse invites more leverage "
            f"into exactly the position that fails. Treat the apparent "
            f"improvement as a signal to check the two correlations' basis, not "
            f"as reduced risk."
        )

    if stressed_source == "config_default":
        warnings.append(
            f"correlation_stressed was NOT supplied and fell back to the "
            f"configured risk.stress_correlation ({correlation_stressed}). That "
            f"leaf is an institutional convention, not a measurement of this "
            f"pair — measured stressed correlations over 8 real US cross-market "
            f"pairs reach 0.858 (S&P tail) and 0.736 (VIX tail), both below it, "
            f"while the normal correlations they are differenced against run "
            f"-0.623 .. 0.820. Supply the pair's own stressed correlation before "
            f"treating hedge_degradation as a measurement."
        )

    if exceeds_bound:
        warnings.append(
            f"|hedge_degradation| = {abs(degradation):.3f} exceeds the "
            f"configured plausibility bound {degradation_bound}. Over 8 real US "
            f"cross-market pairs the measured |degradation| range is "
            f"0.004 .. 0.175 (S&P tail) and 0.072 .. 0.320 (VIX tail), so a value "
            f"this large usually means the two "
            f"correlations were supplied on inconsistent bases — one a "
            f"measurement of this pair, the other a default or a different "
            f"window."
        )

    if not inputs.duration_is_modified:
        warnings.append(
            "Durations were not attested as MODIFIED. Macaulay duration is "
            "longer by (1 + y/f), and the two legs carry different yields, so a "
            "Macaulay-vs-modified mismatch here is a relative error between the "
            "legs rather than a common scaling. The absolute duration band "
            "cannot detect it at short maturities."
        )

    if abs(net_duration_residual) >= root_settings.curve_trade.display_tolerance:
        warnings.append(
            f"Net duration residual {net_duration_residual:.6f} exceeds the "
            f"display tolerance. This is a floating-point artefact of the "
            f"notional multiplication, not evidence of a bad duration input — "
            f"the residual is the notional's own definition simplified, so it is "
            f"zero up to float noise for every input, correct or not (see "
            f"net_duration_residual_is_definitional)."
        )

    return ModelResult(
        model_name="construct_cross_market_rv",
        # Section 22.3: US-only through Phase 4. ModelResult.country's own field
        # description says '"us" only through Phase 4', so Section 20.12's
        # `country="global"` contradicts the contract it is written against.
        country="us",
        as_of=utc_now(),
        value={
            "market_a_long": inputs.market_a,
            "market_b_short": inputs.market_b,
            "notional_a_long": inputs.target_notional_a,
            "notional_b_short": round(notional_b, 2),
            "duration_a_years": inputs.duration_a,
            "duration_b_years": inputs.duration_b,
            "duration_ratio_a_to_b": round(duration_ratio, 6),
            "duration_dollars_a": round(duration_dollars_a, 2),
            "duration_dollars_b": round(duration_dollars_b, 2),
            "net_duration_residual": round(net_duration_residual, 6),
            "net_duration_residual_is_definitional": True,
            "correlation_normal": correlation_normal,
            "correlation_stressed": correlation_stressed,
            "correlation_stressed_source": stressed_source,
            "hedge_degradation": round(degradation, 3),
            "hedge_direction": hedge_direction,
            "hedge_degradation_exceeds_plausible_bound": exceeds_bound,
        },
        confidence=compute_confidence(
            ConfidenceInputs(
                is_heuristic_not_calibrated=not root_settings.is_calibrated(
                    "cross_market_rv.minimum_duration_years"
                ),
                source_independence_count=0,
            )
        ),
        interpretation=(
            f"Long {inputs.market_a} {inputs.target_notional_a:,.2f}, short "
            f"{inputs.market_b} {notional_b:,.2f} (duration-matched "
            f"{inputs.duration_a}/{inputs.duration_b}) — hedge "
            f"{hedge_direction.replace('_', ' ')} "
            f"(degradation {degradation:+.3f})"
        ),
        context=(
            "Cross-market relative value per Module 15.3 — the common factor "
            "cancels only if the correlation holds, and it does not hold in "
            "crisis. The notional is duration-matched under the N*D convention "
            "Section 20.12 specifies; true level cancellation needs dollar "
            "duration N*P*D, and the two differ by exactly the legs' price "
            "ratio, which this contract cannot compute because it carries no "
            "prices (O-57/O-59)."
        ),
        inputs_used=[
            "market_a",
            "market_b",
            "duration_a",
            "duration_b",
            "target_notional_a",
            "correlation_normal",
            "correlation_stressed",
            "duration_is_modified",
        ],
        warnings=warnings,
    )


def _inversion_warnings(
    *,
    base_rate: float,
    ceiling_binding: bool,
    saturated: bool,
    duration_past_turn: bool,
    ceiling: float,
    duration_cap: float,
) -> list[str]:
    """Every caveat this function can emit, in a fixed order.

    Extracted so a test can enumerate the branches and assert each is reachable —
    a warning the suite cannot trigger is one that can be deleted without
    consequence (D-045).

    The ceiling caveat is keyed on ``ceiling_binding`` — whether the cap actually
    **changed the returned number on this call** — and not on the ceiling's own
    value. An earlier draft tested ``base_rate > 0.0 and ceiling <= 0.80``, which
    reads as a condition but is a constant: ``base_rate`` is validated ``> 0`` by
    the input model and ``ceiling`` comes from config rather than from the input,
    so the branch would have fired on every inverted call or on none, and would
    have described a cap that in the common case bound nothing. That is D-037's
    dead-branch class: a guard whose text promises discrimination and whose
    predicate cannot discriminate.
    """
    warnings = [
        "ILLUSTRATIVE heuristic, not a fitted historical model — Section 15.20-B "
        "specifies this as a mechanism-first placeholder for a Phase 5+ logistic "
        "fit. The 6-24 month timing lag is genuinely uncertain."
    ]
    if saturated:
        warnings.append(
            "One or both factors have SATURATED: different situations beyond the "
            "cap return the same probability. The duration cap in particular sits "
            "at the measured turning point — beyond it the empirical relationship "
            "REVERSES (measured P(recession within 12mo) peaks at 0.769 for "
            "26-52 weeks and falls to 0.520 beyond 52), so a long inversion is "
            "NOT treated as a stronger signal."
        )
    if duration_past_turn:
        warnings.append(
            f"Inverted for more than the {duration_cap:.0f}-week cap, so the "
            f"duration factor is pinned at its maximum while the measured rate "
            f"for this region is BELOW the peak bucket. This is the assumption "
            f"the data contradicts; it is disclosed rather than silently applied."
        )
    if ceiling_binding:
        warnings.append(
            f"The ceiling CLAMPED this result at {ceiling:.0%}: the base rate of "
            f"{base_rate:.1%} plus the full adjustment would have exceeded it, so "
            f"the reported probability is the cap and not the heuristic's output. "
            f"The cap is a policy choice — this system never claims near-certainty "
            f"about recession timing — but a clamped result carries no information "
            f"about how far past it the uncapped value lay."
        )
    return warnings


# ---------------------------------------------------------------------------
# yield_curve_pca (Section 6.6) — Module 8's consumer of Module 18's PCA
# ---------------------------------------------------------------------------

#: Section 6.6 names three components explicitly — PC1/PC2/PC3 — so the count is
#: the SPECIFICATION's rather than a tunable, and it is named once here so the
#: call and the refusal message cannot disagree about it. `compute_pca` takes an
#: `n_components` argument; this function's signature deliberately does not
#: (§6.6's signature is `yield_curve_pca(daily_changes)`), so the value is fixed
#: at the specification's and the caller cannot silently ask for a different
#: decomposition from the one §6.6 describes.
_YIELD_CURVE_COMPONENTS = 3


def _curve_tenor_years(tenor: str) -> float:
    """Parse a REGISTRY tenor label such as ``3mo`` / ``1yr`` / ``30yr`` into years.

    **Why this does not reuse the module's own :func:`_tenor_years`.** That one
    is deliberately narrow: it accepts only a number followed by ``y``
    (``"2y"``/``"10y"``), because it reads years for a duration plausibility check
    and refuses to guess at any other unit. The registry's ``treasury_curve``
    entry writes its tenors as ``1mo``/``3mo``/``6mo``/``1yr``/``2yr``/``3yr``/
    ``5yr``/``7yr``/``10yr``/``20yr``/``30yr`` — and **the sibling parser refuses
    every one of them** (measured 2026-09-24: all eleven raise). So a panel built
    from the registry, which is the only place this project names providers,
    cannot be parsed by the existing helper, and reusing it would refuse the
    correct input.

    This accepts the shapes the registry actually writes: a number followed by
    ``mo``, ``yr`` or ``y``. It refuses everything else rather than normalising,
    for the sibling's reason — a label it cannot read is a caller error, and
    guessing the unit would put a wrong maturity into the ordering the loadings
    are read across.
    """
    text = tenor.strip().lower()
    for suffix, per_year in (("mo", 1.0 / 12.0), ("yr", 1.0), ("y", 1.0)):
        if text.endswith(suffix) and text[: -len(suffix)]:
            try:
                count = float(text[: -len(suffix)])
            except ValueError as exc:
                raise ValueError(
                    f"tenor {tenor!r} does not carry a numeric count before its {suffix!r} suffix."
                ) from exc
            if count <= 0.0:
                raise ValueError(f"tenor {tenor!r} is not a positive maturity.")
            return count * per_year
    raise ValueError(
        f"tenor {tenor!r} is not a maturity label of the form '3mo'/'1yr'/'30yr', "
        f"which is the shape config/series_registry.yaml writes. A curve "
        f"component's loadings are only readable in MATURITY order, so a label "
        f"whose maturity cannot be read is refused rather than sorted arbitrarily."
    )


def _sign(value: float) -> int:
    """The sign of a loading, as ``-1``, ``0`` or ``1`` — with zero its own value.

    Not ``numpy.sign`` used loosely: the count below treats a zero loading as
    BREAKING a run rather than as agreeing with either neighbour, so the
    definition has to be stated rather than assumed.
    """
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def _sign_changes(loadings: list[float]) -> int:
    """Adjacent pairs of a MATURITY-ORDERED loading vector with different signs.

    **This is a DESCRIPTION of the loading vector, not a name for the component.**
    Section 15.20-F forbids labelling the components level/slope/curvature, and
    the count of sign changes is the fact a reader uses to make that call
    themselves. Measured 2026-09-24 on five real Treasury tenors: PC1's loadings
    change sign **0** times, PC2's once and PC3's twice — the textbook shapes.
    Reporting "0 sign changes across the maturity order" states what the vector
    DOES; reporting "the level factor" would be an interpretation this function is
    not entitled to make, and §6.6's own stub says the same thing ("confirmed via
    loadings, never auto-labeled").

    A zero loading breaks a run rather than agreeing with either neighbour, which
    is why :func:`_sign` returns 0 instead of folding it into one side.
    """
    return sum(1 for left, right in pairwise(loadings) if _sign(left) != _sign(right))


def _prepare_curve_panel(
    daily_changes: pd.DataFrame,
) -> tuple[list[str], dict[str, float]]:
    """Validate the tenor panel and return its labels in MATURITY order.

    Four refusals, each of which would otherwise produce loadings nobody can read:

    1. **not a DataFrame, or no columns** — `compute_pca` refuses these too, but a
       wrapper that let them through would report `compute_pca`'s message about a
       function the caller never invoked.
    2. **a label that is not a maturity** — the whole point of this function is
       that the loadings are read ACROSS the curve, so a panel labelled
       ``a``/``b``/``c`` has no curve to read and its "PC1" is uninterpretable.
    3. **a duplicated label** — the loadings map is keyed by tenor, so two columns
       sharing a name would silently describe fewer tenors than were supplied.
    4. **fewer than three tenors** — §6.6 names three components, and a curve with
       two points has no curvature to decompose. `compute_pca` would refuse
       ``n_components=3`` against two columns anyway; naming the reason here means
       the caller is told what the curve is missing rather than what the PCA
       could not do.
    """
    if not isinstance(daily_changes, pd.DataFrame):
        raise TypeError(
            f"daily_changes must be a pandas DataFrame, got {type(daily_changes).__name__}."
        )
    if daily_changes.shape[1] == 0:
        raise ValueError(
            "daily_changes must have at least one tenor column; it has none. A "
            "curve with no points has no shape to decompose."
        )

    duplicated = sorted(
        {str(name) for name in daily_changes.columns[daily_changes.columns.duplicated()]}
    )
    if duplicated:
        raise ValueError(
            f"daily_changes has duplicate column name(s) {duplicated}. The loadings "
            f"are keyed by tenor, so one tenor would overwrite another and the "
            f"result would describe fewer points on the curve than you supplied."
        )

    tenor_years = {str(name): _curve_tenor_years(str(name)) for name in daily_changes.columns}
    tenors = sorted(tenor_years, key=lambda name: (tenor_years[name], name))

    if len(tenors) < _YIELD_CURVE_COMPONENTS:
        raise ValueError(
            f"daily_changes has {len(tenors)} tenor(s), but Section 6.6 names "
            f"{_YIELD_CURVE_COMPONENTS} components and a curve needs at least that "
            f"many points to decompose. With fewer, one of the three would be "
            f"algebraically determined rather than measured — a 'curvature' fitted "
            f"to two points is a line. Supply at least "
            f"{_YIELD_CURVE_COMPONENTS} tenors."
        )

    return tenors, tenor_years


def yield_curve_pca(daily_changes: pd.DataFrame) -> ModelResult:
    """The yield curve's principal components, read ACROSS the maturity order.

    Section 6.6's signature, and Module 8's consumer of Module 18's
    ``compute_pca`` (D-099/D-100). §15.18's narrative calls this Module 18's
    *output*; §21.1 puts the function in **Module 8**, which is where it lives.

    **What this adds over ``compute_pca``, and why it is not a wrapper in name
    only.** Three things, each of which the generic decomposition cannot supply:

    1. **A maturity ordering.** ``compute_pca``'s loadings are keyed by column
       name, and a component's *shape* is a fact about the ORDER of those
       loadings. A panel whose columns arrive as ``30yr, 3mo, 10yr`` decomposes
       identically but reads as noise, so the tenors are parsed to years, sorted,
       and the loadings published in that order — with ``tenor_years`` beside them
       so the ordering is checkable rather than asserted.
    2. **A descriptive curve shape.** ``sign_changes`` counts, per component, the
       adjacent pairs of maturity-ordered loadings with different signs. Measured
       2026-09-24 on five real Treasury tenors: PC1 changes sign **0** times, PC2
       once, PC3 twice.
    3. **The three-component scope §6.6 names.** The signature takes no
       ``n_components``, so the count is the specification's rather than the
       caller's — a caller cannot silently ask for a different decomposition from
       the one §6.6 describes.

    **``sign_changes`` is a DESCRIPTION and NOT a label.** §15.20-F forbids
    labelling the components level/slope/curvature, and §6.6's own stub agrees
    ("confirmed via loadings, never auto-labeled"). The prohibition is at its
    sharpest here, because the curve context makes the labels feel obvious — a
    component with zero sign changes across the maturity order IS consistent with
    a level shift, and it is equally consistent with every tenor moving for an
    unrelated common reason. The count is published; the name is the reader's to
    write down, in the thesis, where it can be argued with.

    The result inherits ``compute_pca``'s warnings and limitations — they are
    conditions of this run and true here — and adds the two the curve context
    creates: a panel whose input order was not maturity order (so the reader knows
    the published order is this function's), and a panel with exactly as many
    tenors as components (where the last component is the algebraic remainder
    rather than a measured residual).
    """
    settings = get_settings()

    tenors, tenor_years = _prepare_curve_panel(daily_changes)

    # The input order is preserved for the COMPUTATION (the eigendecomposition
    # does not care about column order) and only the PRESENTATION is reordered.
    # Reordering before the fit would change nothing numerically but would make
    # the `compute_pca` context string describe a panel the caller did not pass.
    pca = compute_pca(daily_changes, n_components=_YIELD_CURVE_COMPONENTS)
    pca_published = pca.value
    assert isinstance(pca_published, dict)

    loadings_all = pca_published["loadings"]
    assert isinstance(loadings_all, dict)
    ratios_all = pca_published["explained_variance_ratios"]
    cumulative_all = pca_published["cumulative_explained_variance"]
    eigenvalues_all = pca_published["eigenvalues"]
    assert isinstance(ratios_all, list)
    assert isinstance(cumulative_all, list)
    assert isinstance(eigenvalues_all, list)

    component_names = list(loadings_all)[:_YIELD_CURVE_COMPONENTS]
    ordered_loadings: dict[str, dict[str, float]] = {}
    sign_changes: dict[str, int] = {}
    for component in component_names:
        values = loadings_all[component]
        assert isinstance(values, dict)
        # MATURITY order, which is the only order in which a component's shape is
        # readable. `tenors` came from sorting the parsed years, so this is the
        # curve's own order rather than the caller's column order.
        ordered_loadings[component] = {tenor: float(values[tenor]) for tenor in tenors}
        sign_changes[component] = _sign_changes(
            [ordered_loadings[component][tenor] for tenor in tenors]
        )

    published: dict[str, object] = {
        "tenors": tenors,
        "tenor_years": tenor_years,
        "n_tenors": len(tenors),
        "n_obs": int(pca_published["n_obs"]),
        "n_components": _YIELD_CURVE_COMPONENTS,
        "explained_variance_ratios": [float(value) for value in ratios_all],
        "cumulative_explained_variance": [float(value) for value in cumulative_all],
        "eigenvalues": [float(value) for value in eigenvalues_all],
        "loadings": ordered_loadings,
        "sign_changes": sign_changes,
        "standardisation": pca_published["standardisation"],
        "sign_rule": pca_published["sign_rule"],
    }

    warnings_ = list(pca.warnings)
    input_order = [str(name) for name in daily_changes.columns]
    if input_order != tenors:
        warnings_.append(
            f"THE INPUT COLUMNS WERE NOT IN MATURITY ORDER, so the loadings below "
            f"are published in this function's order ({', '.join(tenors)}) rather "
            f"than the order you supplied ({', '.join(input_order)}). The "
            f"decomposition is unaffected — an eigendecomposition does not depend "
            f"on column order — but a component's SHAPE does, and reading one "
            f"against the wrong axis is how a level component gets mistaken for a "
            f"slope one."
        )
    if len(tenors) == _YIELD_CURVE_COMPONENTS:
        warnings_.append(
            f"THE PANEL HAS EXACTLY AS MANY TENORS AS COMPONENTS ({len(tenors)}), so "
            f"the last component is the ALGEBRAIC REMAINDER rather than a measured "
            f"residual: the three components span the panel completely and the "
            f"cumulative variance is 1.0 by construction. Its ratio is therefore "
            f"not evidence that the curve has a third factor — add a tenor and it "
            f"will change."
        )

    total_three = float(sum(float(value) for value in ratios_all[:_YIELD_CURVE_COMPONENTS]))
    first_ratio = float(ratios_all[0]) if ratios_all else 0.0

    return ModelResult(
        model_name="yield_curve_pca",
        country="us",
        as_of=utc_now(),
        value=published,
        unit=(
            "dimensionless: explained-variance ratios are shares of the panel's "
            "total variance, loadings are unit-free directions, and tenor_years is "
            "in years"
        ),
        direction=None,
        confidence=compute_confidence(
            ConfidenceInputs(
                # The SAME leaf `compute_pca` prices, because this function's
                # disclosure inherits that threshold — the near-zero ratio below
                # which a component is reported as a numerical residual rather than
                # as a weak factor.
                is_heuristic_not_calibrated=not settings.is_calibrated(
                    "econometrics.pca_near_zero_tolerance"
                ),
                source_independence_count=0,
                # NOT unobservable: the components are COMPUTED from observed
                # yields, unlike `kalman_latent_state`'s r*. §21.4 item 13's list
                # (r*, u*, potential GDP, TFP, the term premium) does not include a
                # principal component of observed data.
                depends_on_unobservable=False,
            )
        ),
        interpretation=(
            f"{_YIELD_CURVE_COMPONENTS} principal components of {len(tenors)} tenors "
            f"({', '.join(tenors)}) over {int(pca_published['n_obs'])} daily changes. "
            f"They explain {total_three:.1%} of the panel's variance "
            f"(PC1 {first_ratio:.1%}). Sign changes across the maturity order: "
            + ", ".join(f"{name} {count}" for name, count in sign_changes.items())
            + ". Those counts describe the loading vectors; this function does not "
            "name the components — read `loadings` and name them yourself."
        ),
        context=(
            "Tenors in maturity order: "
            + ", ".join(f"{tenor} ({tenor_years[tenor]:g}y)" for tenor in tenors)
            + f". Standardisation: {pca_published['standardisation']}. Sign "
            f"convention: {pca_published['sign_rule']}. Explained-variance ratios: "
            + ", ".join(f"{float(value):.4%}" for value in ratios_all[:_YIELD_CURVE_COMPONENTS])
            + ". Cumulative: "
            + ", ".join(f"{float(value):.4%}" for value in cumulative_all[:_YIELD_CURVE_COMPONENTS])
            + f". Sample: {int(pca_published['n_obs'])} rows, {len(tenors)} tenors. "
            f"Computed by `compute_pca` on DAILY CHANGES."
        ),
        inputs_used=[f"daily_changes:{tenor}" for tenor in tenors],
        warnings=warnings_,
        assumptions=[
            "The input is DAILY CHANGES, not levels. This function cannot verify "
            "that — `compute_pca` warns when the panel's shape suggests levels, but "
            "a level panel still yields a PC1 that is a time trend dressed as a "
            "curve factor. Run a stationarity test on each level first.",
            "The tenors are MATURITY labels of the shapes the series registry "
            "writes ('3mo'/'1yr'/'30yr'), and their order is the axis a component's "
            "shape is read across. A label this function cannot parse is refused "
            "rather than sorted arbitrarily.",
            f"The components are computed on the "
            f"{pca_published['standardisation']!r} matrix, inherited from "
            f"`econometrics.pca_standardisation`. The covariance route weights each "
            f"tenor by its own variance; the correlation route gives every tenor "
            f"equal weight regardless of scale.",
        ],
        limitations=[
            *pca.limitations,
            "A COMPONENT'S SHAPE IS A PROPERTY OF THE TENOR SET, NOT OF THE CURVE "
            "IN GENERAL. The sign-change count depends on which maturities are in "
            "the panel: adding a 6-month point can introduce a change that a "
            "five-tenor panel could not show, and dropping the front end can remove "
            "one. Compare two fits' sign counts only when the tenor sets match.",
            "THREE COMPONENTS ARE A CHOICE, NOT A FINDING. §6.6 names three, so "
            "three are reported; nothing in the decomposition says the curve HAS "
            "three factors. When the panel is wider, the remaining components carry "
            "real variance — measured 2026-09-24 on five tenors, PC4 and PC5 "
            "together carried 2.3% — and `compute_pca` publishes all of them.",
        ],
        decision_prohibition=[
            "MUST NOT label the components level/slope/curvature, or any other "
            "name. §15.20-F forbids it and §6.6's own stub repeats it. The "
            "prohibition bites hardest HERE, because the curve context makes the "
            "names feel obvious: a component with zero sign changes across the "
            "maturity order is consistent with a level shift AND with every tenor "
            "moving for an unrelated common reason, and only a reader who has "
            "looked at the loadings can tell those apart. `sign_changes` is a fact "
            "about a vector; a factor name is a claim about the economy.",
            "MUST NOT be used as a signal on its own. A principal component is a "
            "direction of maximum variance, not a forecast and not a value signal: "
            "the largest variance can be the largest NOISE. §15.18's mechanism-first "
            "ordering applies here as it does to every other function in this "
            "module.",
            "MUST NOT be read across two fits as though the components were the "
            "same factor. The basis is that window's covariance, so after a regime "
            "change the ordering and the loadings both move. This is the same "
            "backward-looking hazard `test_cointegration` and `compute_pca` warn "
            "about.",
        ],
    )
