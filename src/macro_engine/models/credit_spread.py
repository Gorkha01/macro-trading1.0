"""Module 8.3 — attributing a credit spread widening to fundamental or technical cause.

Section 20.8's premise is the whole point of the function: a spread widening is
either **fundamental** (default risk genuinely rising) or **technical**
(risk-aversion / flight-to-quality, LTCM-1998 style), and the two have
**opposite forward implications** — fundamental widening is sticky, panic
widening snaps back. Treating them as one signal is the error the module exists
to prevent.

Four things had to be settled before the function could be written. See
**D-037**.

**1. The specification's `BOTH` branch was unreachable.** As written:

    fundamental = default_rate_trend == "rising"
    technical   = equity_vol_change_pct > 20 AND default_rate_trend != "rising"

``fundamental`` requires the trend to be ``"rising"`` and ``technical`` requires
it not to be, so the two predicates are **mutually exclusive by construction**
and the branch that reports ``BOTH`` / ``elevated_concern`` could never execute.
Enumerating the specification's logic over its entire declared input space
returns only three attributions, never four. The exclusion is dropped here,
which makes all four reachable — the presence of the ``BOTH`` branch with its
own durability shows that is what was intended, and a credit deterioration
*with* a volatility spike is a real and important state.

**2. Three of the five inputs were inert.** ``hy_spread_change_bp`` and
``ig_spread_change_bp`` appear in the specification **only** in ``inputs_used``
— never in the logic — and ``hy_spread_bp`` is only echoed. So the function as
specified would attribute *widening* **without ever checking that spreads
widened**: a week of tightening would still return ``FUNDAMENTAL``. This model
verifies widening before attributing it, and reports ``NO_WIDENING`` otherwise.

**3. The two spread inputs ship as a disclosed diagnostic, not a predicate.**
Per the decision of 2026-09-17 they are published — the HY-minus-IG
differentiation, and whether the two moved together — but they do **not** decide
the attribution, which stays on the specification's trend-and-volatility logic.
The reason to publish them at all is that a reader cannot otherwise see the two
inputs the output claims to have used, and the differentiation is economically
meaningful: idiosyncratic credit stress widens HY relative to IG, while a
flight-to-quality widens both. **A consumer must not read it as part of the
verdict**, and a warning says so.

**4. Two adjacent inputs need OPPOSITE unit conversions.** The credit spreads
are in *percent* and must be multiplied by 100 to reach basis points; VIX is a
*level* in index points and the input is a percent *change* of it. Applying one
conversion to both is a 100x error on one of them, and the result is a perfectly
plausible attribution of the wrong kind — the pairing-axis defect (D-035). Both
conversions are asserted in the live check and in a unit test.

**One input is MANUAL.** Section 21.1: *"No clean free real-time series. Human
assessment or raise."* ``default_rate_trend`` is one of the two predicates that
decide the attribution, so the verdict rests partly on a hand-entered judgement
and the live check cannot exercise every branch. The output says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

if TYPE_CHECKING:
    from macro_engine.config import CreditSpreadSettings

__all__ = [
    "Attribution",
    "CreditSpreadInputs",
    "DefaultRateTrend",
    "Durability",
    "credit_spread_attribution",
]

#: The attribution vocabulary, as a closed set rather than a bare ``str``
#: (D-029: a ``str`` lets a typo fall through to whichever branch is written
#: last, and ``extra="forbid"`` cannot catch it because the field *is* given).
#:
#: ``NO_WIDENING`` is **added** by this implementation. Section 20.8 has four
#: values and none of them fits "there was nothing to attribute", which is the
#: case its own logic would mis-report. See the module docstring.
Attribution = Literal[
    "FUNDAMENTAL",
    "TECHNICAL_RISK_AVERSION",
    "BOTH",
    "UNCLEAR",
    "NO_WIDENING",
]

#: How long the widening is expected to last. Section 20.8's four values plus
#: the one that pairs with ``NO_WIDENING``.
Durability = Literal[
    "sticky_slow_to_reverse",
    "can_snap_back_sharply",
    "elevated_concern",
    "investigate",
    "not_applicable",
]

#: The trend vocabulary. Typed, because a bare ``str`` accepts ``"Rising"`` and
#: any typo, each of which silently selects the ``else`` branch and reports
#: ``UNCLEAR`` — a wrong answer that looks like a considered one.
DefaultRateTrend = Literal["rising", "stable", "falling"]


class CreditSpreadInputs(BaseModel):
    """One observation of credit conditions, over a stated window.

    Every change is over the SAME window — ``change_window_days`` in config,
    five trading days by default. The window is a property of how the caller
    built these numbers, not of this function, so it is stated in the field
    descriptions and published in the output rather than inferred.
    """

    model_config = ConfigDict(extra="forbid")

    hy_spread_bp: float = Field(
        gt=0.0,
        description=(
            "High-yield OAS LEVEL in basis points. Context only — the "
            "specification's attribution does not read it, and neither does "
            "this implementation. Published so a reader can see the level the "
            "change happened from."
        ),
    )
    hy_spread_change_bp: float = Field(
        description=(
            "Change in the high-yield OAS over the window, in BASIS POINTS. "
            "The source series is in PERCENT, so a caller reading it directly "
            "must multiply by 100 — passing percent as bp is a 100x error that "
            "still produces a plausible attribution."
        ),
    )
    ig_spread_change_bp: float = Field(
        description=(
            "Change in the investment-grade OAS over the same window, in BASIS "
            "POINTS, from a series that is also in percent. Used for the "
            "published differentiation diagnostic only — it does not decide "
            "the attribution."
        ),
    )
    equity_vol_change_pct: float = Field(
        description=(
            "PERCENT change in equity volatility over the same window. Note "
            "this is a change of a LEVEL, not a level: the source series is in "
            "index points and must be divided through, not multiplied by 100."
        ),
    )
    default_rate_trend: DefaultRateTrend = Field(
        description=(
            "MANUAL ENTRY. The direction of default risk, per Section 21.1 — "
            "there is no clean free real-time series. One of the two predicates "
            "that decide the attribution."
        ),
    )


def credit_spread_attribution(inputs: CreditSpreadInputs) -> ModelResult:
    """Attribute a credit spread widening to a fundamental or technical cause.

    Section 20.8. Returns a four-way attribution with its expected durability,
    plus a disclosed diagnostic describing how the two spreads moved relative
    to each other.

    Confidence is computed from the stated factors (Section 22.8), never
    asserted. Both thresholds are ``uncalibrated_illustrative``, so the model
    takes the heuristic penalty automatically through ``Settings.is_calibrated()``.
    """
    settings = _credit_spread_settings()

    fundamental = inputs.default_rate_trend == "rising"
    # The specification ANDs this with `default_rate_trend != "rising"`, which
    # made the BOTH branch unreachable. Dropped; see the module docstring.
    technical = inputs.equity_vol_change_pct > settings.equity_vol_spike_threshold_pct

    # The check the specification omits entirely: it attributes WIDENING without
    # ever reading a spread change.
    widening_observed = inputs.hy_spread_change_bp > 0.0
    differentiation_bp = inputs.hy_spread_change_bp - inputs.ig_spread_change_bp
    parallel_widening = abs(differentiation_bp) <= settings.differentiation_threshold_bp

    attribution: Attribution
    durability: Durability
    if not widening_observed:
        # Refuse rather than substitute: there is no widening to attribute, and
        # reporting FUNDAMENTAL or UNCLEAR would imply an attribution was made.
        attribution = "NO_WIDENING"
        durability = "not_applicable"
    elif fundamental and technical:
        attribution = "BOTH"
        durability = "elevated_concern"
    elif fundamental:
        attribution = "FUNDAMENTAL"
        durability = "sticky_slow_to_reverse"
    elif technical:
        attribution = "TECHNICAL_RISK_AVERSION"
        durability = "can_snap_back_sharply"
    else:
        attribution = "UNCLEAR"
        durability = "investigate"

    warnings = [
        # The manual-input disclosure: a reader comparing two runs must know
        # which of the five numbers a human typed.
        "default_rate_trend is a CALLER INPUT and the model cannot verify its "
        "provenance. Section 21.1 marks it MANUAL, but a free route exists as of "
        "D-043 — the live check derives it from the FRED delinquency rate "
        "(`DRALACBS`), whose four-quarter direction leads default risk. A caller "
        "who enters it by hand is half the verdict, entered as a judgement.",
        # The diagnostic must not be mistaken for a predicate.
        "The HY-minus-IG differentiation is a DIAGNOSTIC, not part of the "
        "attribution. Section 20.8's logic reads only default_rate_trend and "
        "equity_vol_change_pct; the two spread changes are reported because the "
        "output would otherwise claim inputs it never used.",
        # D-029: the flags travel with their own measured frequency.
        f"Both predicates fire often. Over {settings.base_rates.observations_measured} "
        f"five-day windows, volatility rose past {settings.equity_vol_spike_threshold_pct:.0f}% "
        f"in {settings.base_rates.equity_vol_spike_rate:.1%} of them and the high-yield "
        f"spread widened at all in {settings.base_rates.widening_rate:.1%}. A widening "
        f"is the slightly LESS likely outcome, so 'spreads widened' alone is not evidence.",
    ]

    if not widening_observed:
        warnings.append(
            f"The high-yield spread did not widen over the window "
            f"({inputs.hy_spread_change_bp:+.1f}bp). There is nothing to attribute, "
            f"so the attribution is NO_WIDENING rather than a cause — the "
            f"specification would have named one anyway."
        )

    if parallel_widening and widening_observed:
        warnings.append(
            f"HY and IG moved within {settings.differentiation_threshold_bp:.1f}bp of "
            f"each other ({differentiation_bp:+.1f}bp apart), which is the pattern a "
            f"broad risk-aversion move produces. Two thirds of five-day moves are "
            f"differentiated, so this is informative but not conclusive."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _thresholds_calibrated(),
            # One market, one provider for the three sourced series.
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="credit_spread_attribution",
        country="us",
        as_of=utc_now(),
        value={
            "attribution": attribution,
            "expected_durability": durability,
            # The predicates, published so the attribution is RECOMPUTABLE from
            # the output rather than trusted (the D-009 cross-field identity).
            "fundamental": fundamental,
            "technical": technical,
            "widening_observed": widening_observed,
            "hy_spread_bp": round(inputs.hy_spread_bp, 4),
            "hy_spread_change_bp": round(inputs.hy_spread_change_bp, 4),
            "ig_spread_change_bp": round(inputs.ig_spread_change_bp, 4),
            "equity_vol_change_pct": round(inputs.equity_vol_change_pct, 4),
            "default_rate_trend": inputs.default_rate_trend,
            "default_rate_trend_is_caller_supplied": True,
            # The derived route exists but this function cannot know which was
            # used, so it states the fact it can verify: the caller supplied it.
            "default_rate_trend_derived_route_available": True,
            # The diagnostic. Reported, never decisive.
            "hy_minus_ig_change_bp": round(differentiation_bp, 4),
            "widenings_are_parallel": parallel_widening,
            "change_window_days": settings.change_window_days,
            "equity_vol_spike_rate": settings.base_rates.equity_vol_spike_rate,
            "widening_rate": settings.base_rates.widening_rate,
            # The parallel-widening base rate is published because the flag it
            # belongs to is published: a reader told "these moved together"
            # needs the frequency. It was previously a config leaf no code path
            # read, which a mutation sweep caught.
            "parallel_widening_rate": settings.base_rates.parallel_widening_rate,
            "observations_measured": settings.base_rates.observations_measured,
        },
        confidence=confidence,
        interpretation=(
            f"Spread widening attributed to: {attribution} ({durability})"
            + ("" if widening_observed else " — no widening to attribute")
        ),
        context=(
            "Fundamental vs technical widening have OPPOSITE forward "
            "implications (Module 8.3, LTCM 1998). The HY-minus-IG "
            "differentiation is reported alongside the verdict, not folded into it."
        ),
        inputs_used=[
            "hy_spread_bp",
            "hy_spread_change_bp",
            "ig_spread_change_bp",
            "equity_vol_change_pct",
            "default_rate_trend",
        ],
        warnings=warnings,
    )


def _thresholds_calibrated() -> bool:
    """Whether Module 8.3's decision thresholds are calibrated or placeholders."""
    from macro_engine.config import get_settings

    settings = get_settings()
    return settings.is_calibrated(
        "credit_spread.equity_vol_spike_threshold_pct_value"
    ) and settings.is_calibrated("credit_spread.differentiation_threshold_bp_value")


def _credit_spread_settings() -> CreditSpreadSettings:
    """Read Module 8.3's thresholds and base rates. Lazy to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().credit_spread
