"""Module 2 — bond mathematics: pricing, duration, convexity, and the repo corridor.

AGENTS.md Section 20.2 (plus Section 15.20's addendum, which is where these
signatures were first supplied). Section 16.2's algorithm calls these functions
without ever having defined them; Section 20.2 is the authoritative definition,
and it governs.

This module is the first Tier 1 group in Section 21.3's dependency table: every
function here is pure arithmetic on inputs, so nothing can block it and nothing
depends on a data fetch. That makes it the right place to establish the
conventions the rest of the models layer will follow.

Two conventions this module establishes deliberately
----------------------------------------------------
**1. ``confidence`` is computed, never asserted.** The specification's sample
code writes ``confidence=1.0`` for ``price_bond`` and ``confidence=0.5`` for
``repo_stress_check``. Section 22.8 supersedes both: "No model may hardcode
confidence going forward." Each function here therefore calls
``compute_confidence()`` with its *actual* factor states. For pure arithmetic
this yields a high value without any literal being written, which is the point —
the number is derived from the fact that no estimation was involved, not
asserted as a claim about the code's quality.

**2. Thresholds come from config, not from the specification's literals.**
Section 20.2 writes ``if spread_to_iorb_bp > 25``. That 25 is a judgment about
where plumbing stress begins, so it lives in ``settings.yaml`` under
``bond_math:`` with a documented calibration status, and the specification's
value appears there as the default. The behaviour is identical; the number is
now reviewable and changeable without editing Python.

The unit convention
-------------------
Yields and coupons are **decimals** throughout (``0.06``, not ``6.0``), matching
Section 20.2's own ``coupon_rate: float  # annual, decimal (e.g. 0.06)``. Basis
points appear only where a function's name or output explicitly says ``_bp``.
This is stated because a decimal-vs-percent confusion is the single most common
defect in bond code and it produces a plausible-looking wrong answer rather than
an error — exactly the failure class Section 21.0 warns about.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "BondPricingInputs",
    "ConvexityInputs",
    "RepoStressInputs",
    "convexity",
    "macaulay_duration",
    "modified_duration",
    "price_bond",
    "price_change_with_convexity",
    "repo_stress_check",
]


# ---------------------------------------------------------------------------
# Input contracts
# ---------------------------------------------------------------------------


class BondPricingInputs(FiniteInputs):
    """A plain-vanilla fixed-coupon bond.

    ``periods`` is the number of *coupon periods*, not years — the formulas are
    period-based and this codebase deliberately does not assume semiannual
    frequency anywhere. A caller working in years must convert explicitly, which
    keeps the frequency assumption visible at the call site rather than buried
    in a helper.
    """

    model_config = ConfigDict(extra="forbid")

    face_value: float = Field(gt=0.0, description="Redemption value, e.g. 100 or 1000.")
    coupon_rate: float = Field(
        ge=0.0, description="Annual coupon rate as a DECIMAL (0.06 = 6%), per Section 20.2."
    )
    yield_rate: float = Field(
        gt=-1.0,
        description=(
            "Annual required yield as a DECIMAL. Bounded above -1.0: at exactly "
            "-1.0 the discount factor (1+y)^t is zero and the price is either "
            "infinite or undefined."
        ),
    )
    periods: int = Field(gt=0, description="Number of coupon periods to maturity.")


class ConvexityInputs(FiniteInputs):
    """Convexity inputs, matching Section 20.2's own field names.

    Section 20.2's ``convexity()`` reads ``inputs.coupon`` (a currency amount),
    ``inputs.face_value``, ``inputs.yield_rate`` and ``inputs.n_periods`` —
    a different shape from ``BondPricingInputs``, which carries a *rate*. Both
    appear in the specification and both are preserved rather than unified,
    because unifying them would silently change what a caller passing a rate
    gets back. The distinction is real: one is a rate, one is an amount.
    """

    model_config = ConfigDict(extra="forbid")

    coupon: float = Field(ge=0.0, description="Coupon payment per period, in currency units.")
    face_value: float = Field(gt=0.0, description="Redemption value, in currency units.")
    yield_rate: float = Field(gt=-1.0, description="Yield per period, as a DECIMAL.")
    n_periods: int = Field(gt=0, description="Number of periods to maturity.")


class RepoStressInputs(FiniteInputs):
    """The four rates that define the floor-system corridor, plus the two
    corroboration inputs Section 22.11 requires before escalation.

    All four rates are REQUIRED. A corridor check with a missing leg cannot
    conclude "normal" — it can only fail to detect stress, which reads
    identically to "no stress" unless the absence is made explicit. Requiring
    all four means a caller with incomplete data gets a validation error rather
    than a false-negative all-clear on a plumbing-stress early-warning signal.

    ``persistence_days`` and ``repo_volume_change_pct`` are optional, because
    they are available on a different cadence from the rates. Their *absence* is
    meaningful and is handled explicitly in the function: without them the model
    refuses to escalate. An optional input that silently widens a decision is
    worse than a required one that fails.
    """

    model_config = ConfigDict(extra="forbid")

    sofr: float = Field(description="Secured Overnight Financing Rate, in percent.")
    iorb: float = Field(description="Interest on Reserve Balances, in percent.")
    on_rrp_rate: float = Field(description="Overnight reverse repo offering rate, in percent.")
    fed_funds_effective: float = Field(description="Effective federal funds rate, in percent.")
    persistence_days: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Consecutive days the SOFR-IORB spread has breached the threshold. "
            "Section 22.11 requires this before ACUTE_REPO_STRESS."
        ),
    )
    repo_volume_change_pct: float | None = Field(
        default=None,
        description=(
            "Percentage change in repo volume accompanying the breach. "
            "Section 22.11 requires this as corroboration."
        ),
    )


# ---------------------------------------------------------------------------
# Pricing, duration, convexity
# ---------------------------------------------------------------------------


def _price_exact(coupon: float, face_value: float, yield_rate: float, periods: int) -> float:
    """Price at full precision — the single implementation of the formula.

    Extracted so ``price_bond()`` and ``macaulay_duration()`` cannot drift
    apart. ``price_bond()`` rounds this for presentation; ``macaulay_duration()``
    consumes it unrounded, because a duration that divides by a 2-decimal price
    is wrong in the third decimal place — see the comment at that call site.
    """
    if yield_rate == 0.0:
        return coupon * periods + face_value
    annuity_factor = (1 - (1 + yield_rate) ** -periods) / yield_rate
    return coupon * annuity_factor + face_value / ((1 + yield_rate) ** periods)


def price_bond(inputs: BondPricingInputs) -> ModelResult:
    """Price a bond as the present value of its remaining cash flows.

    ``Price = SUM[C / (1+y)^t] + F / (1+y)^n`` — Section 20.2's multi-period
    formula. The ``yield_rate == 0`` branch is the algebraic limit of the
    annuity factor, not a special case invented here: the closed form divides
    by ``y``, and at exactly zero the price is the undiscounted sum.
    """
    coupon = inputs.face_value * inputs.coupon_rate
    yield_rate = inputs.yield_rate
    years_to_maturity = inputs.periods

    price = _price_exact(coupon, inputs.face_value, yield_rate, years_to_maturity)

    if price > inputs.face_value:
        relation = "premium"
    elif price < inputs.face_value:
        relation = "discount"
    else:
        relation = "at par"

    return ModelResult(
        model_name="price_bond",
        country="us",
        as_of=utc_now(),
        value=round(price, 2),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=f"Bond price: {price:.2f} ({relation} to face value)",
        context=(
            f"Face={inputs.face_value}, coupon={inputs.coupon_rate:.2%}, "
            f"yield={yield_rate:.2%}, periods={inputs.periods}"
        ),
        inputs_used=["face_value", "coupon_rate", "yield_rate", "periods"],
    )


def macaulay_duration(inputs: BondPricingInputs) -> ModelResult:
    """Macaulay duration: the present-value-weighted average time to cash flow.

    ``MacDur = SUM[t * PV(CF_t)] / Price``

    The final period's cash flow is ``coupon + face``, not just the coupon —
    the redemption is a cash flow and belongs in the weighted sum. Omitting it
    is a common error that yields a duration systematically too low, and the
    error is invisible without a hand calculation, which Section 11.1 requires.
    """
    coupon = inputs.face_value * inputs.coupon_rate
    yield_rate = inputs.yield_rate

    # Compute the price at FULL precision rather than reusing price_bond()'s
    # rounded output.
    #
    # This was a real defect, caught by hand-verification: pricing through
    # price_bond() divides by a value already rounded to 2 decimal places,
    # which returned 2.828 where the correct duration is 2.829. The error is
    # one part in ~2800 — invisible without an independent hand calculation,
    # which is precisely the failure class Section 21.0 warns about. Section
    # 20.2's own implementation computes the price unrounded, and rounding is
    # a presentation concern that must not feed back into arithmetic.
    price = _price_exact(coupon, inputs.face_value, yield_rate, inputs.periods)

    weighted = 0.0
    for period in range(1, inputs.periods + 1):
        cash_flow = coupon + (inputs.face_value if period == inputs.periods else 0.0)
        discounted = cash_flow / ((1 + yield_rate) ** period)
        weighted += period * discounted

    mac_duration = weighted / price

    return ModelResult(
        model_name="macaulay_duration",
        country="us",
        as_of=utc_now(),
        value=round(mac_duration, 3),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=f"Macaulay Duration: {mac_duration:.3f} periods",
        context=f"Bond price={price:.2f}, final cash flow includes redemption",
        inputs_used=["face_value", "coupon_rate", "yield_rate", "periods"],
    )


def modified_duration(mac_dur: float, yield_rate: float) -> ModelResult:
    """Modified duration: the price sensitivity actually used for hedging.

    ``ModDur = MacDur / (1 + y)``

    Takes ``mac_dur`` as a plain float rather than recomputing it, matching
    Section 20.2's signature. A caller who already has the Macaulay duration
    should not have to reconstruct the whole bond to convert it.
    """
    mod_duration = mac_dur / (1 + yield_rate)

    return ModelResult(
        model_name="modified_duration",
        country="us",
        as_of=utc_now(),
        value=round(mod_duration, 3),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"Modified Duration: {mod_duration:.3f} — "
            f"a 1% yield rise implies roughly a {mod_duration:.2f}% price fall"
        ),
        context=f"MacDur={mac_dur}, yield={yield_rate:.2%}",
        inputs_used=["mac_dur", "yield_rate"],
    )


def convexity(inputs: ConvexityInputs) -> ModelResult:
    """Convexity: the curvature that duration's linear approximation ignores.

    ``Convexity = SUM[t*(t+1)*PV(CF_t)] / (Price * (1+y)^2)``

    Duration treats price as a straight line in yield. It is not — it is convex,
    and the gap between the line and the curve is what this measures. The
    practical consequence is favourable to the holder in both directions, which
    is why Section 20.2 calls higher convexity "more favorable asymmetry".
    """
    pv_weighted = 0.0
    price = 0.0

    for period in range(1, inputs.n_periods + 1):
        cash_flow = inputs.coupon + (inputs.face_value if period == inputs.n_periods else 0.0)
        present_value = cash_flow / ((1 + inputs.yield_rate) ** period)
        price += present_value
        pv_weighted += period * (period + 1) * present_value

    conv = pv_weighted / (price * (1 + inputs.yield_rate) ** 2)

    return ModelResult(
        model_name="convexity",
        country="us",
        as_of=utc_now(),
        value=round(conv, 4),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=f"Convexity: {conv:.4f}",
        context=(
            "Higher convexity = more favourable asymmetry: gains exceed the "
            "linear estimate on rallies, losses fall short of it on selloffs"
        ),
        inputs_used=["coupon", "face_value", "yield_rate", "n_periods"],
    )


def price_change_with_convexity(mod_dur: float, conv: float, delta_y: float) -> ModelResult:
    """Second-order price response to a yield change.

    ``%dPrice ~= -ModDur * dy + 0.5 * Convexity * (dy)^2``

    The convexity term is quadratic in ``dy`` and therefore **always positive**,
    in both directions. That asymmetry is the entire reason a convex bond is
    worth more than a less convex one at identical duration: Section 20.2 states
    it, and ``test_price_change_with_convexity_asymmetry`` (Section 11.1) asserts
    it as an inequality rather than a shape.
    """
    linear = -mod_dur * delta_y
    convexity_adjustment = 0.5 * conv * (delta_y**2)
    total = linear + convexity_adjustment

    return ModelResult(
        model_name="price_change_with_convexity",
        country="us",
        as_of=utc_now(),
        value=round(total * 100, 4),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"Est. price change {total * 100:+.4f}% "
            f"(duration {linear * 100:+.4f}%, convexity {convexity_adjustment * 100:+.4f}%)"
        ),
        context=(
            "Convexity term is ALWAYS positive — favourable to the bondholder "
            "in both directions (Module 2.6)"
        ),
        inputs_used=["mod_dur", "conv", "delta_y"],
    )


def repo_stress_check(inputs: RepoStressInputs) -> ModelResult:
    """Floor-system corridor check — an early-warning plumbing-stress signal.

    Under the post-2008 floor system, SOFR should trade inside the
    IORB/ON-RRP corridor. A spike materially **above** IORB without a
    corresponding policy move is reserve scarcity, and Section 20.2 notes it
    "historically PRECEDES headline market stress (Sept 2019)".

    Section 22.11 mechanically softens this rule, and the softening is
    load-bearing rather than cosmetic: a single-snapshot breach is common and
    mostly noise (quarter-end, tax dates, Treasury settlement). Escalation to
    ``ACUTE_REPO_STRESS`` therefore requires **persistence** AND **volume
    corroboration**, both of which are optional parameters here. When they are
    absent the function cannot escalate — it reports the raw severity but caps
    it, and says so in a warning. The alternative, escalating on one snapshot,
    would produce a signal that fires on every quarter-end date and is
    consequently ignored.

    The corridor's own definition is also checked: if IORB is not above the
    ON-RRP rate, the inputs describe a system that is not the floor system, and
    that is surfaced rather than assumed away.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    elevated_bp = settings.scalar("bond_math.repo_stress.elevated_threshold_bp")
    acute_bp = settings.scalar("bond_math.repo_stress.acute_threshold_bp")
    persistence_required = int(settings.scalar("bond_math.repo_stress.persistence_days_required"))
    volume_threshold = settings.scalar("bond_math.repo_stress.repo_volume_change_threshold_pct")

    spread_to_iorb_bp = (inputs.sofr - inputs.iorb) * 100
    spread_to_rrp_bp = (inputs.sofr - inputs.on_rrp_rate) * 100

    warnings: list[str] = []

    # The corridor must actually exist in the inputs. If it does not, the
    # severity below is being computed against a configuration this model was
    # not designed for, and a reader must know that before using the label.
    corridor_intact = inputs.iorb > inputs.on_rrp_rate
    if not corridor_intact:
        warnings.append(
            f"Corridor not intact in the supplied inputs: IORB ({inputs.iorb}) is not "
            f"above the ON-RRP rate ({inputs.on_rrp_rate}). The floor system's defining "
            f"inequality does not hold, so this severity label is computed against a "
            f"configuration the model does not describe."
        )

    if spread_to_iorb_bp > acute_bp:
        raw_severity = "ACUTE_REPO_STRESS"
    elif spread_to_iorb_bp > elevated_bp:
        raw_severity = "ELEVATED"
    else:
        raw_severity = "NORMAL"

    # Section 22.11's persistence + volume gates. Applied only to escalation
    # above ELEVATED, which is the decision the amendment was written about.
    persistence_satisfied = (
        inputs.persistence_days is not None and inputs.persistence_days >= persistence_required
    )
    volume_satisfied = (
        inputs.repo_volume_change_pct is not None
        and abs(inputs.repo_volume_change_pct) >= volume_threshold
    )

    if raw_severity == "ACUTE_REPO_STRESS" and not (persistence_satisfied and volume_satisfied):
        severity = "ELEVATED"
        missing: list[str] = []
        if not persistence_satisfied:
            missing.append(
                f"persistence_days >= {persistence_required} (got {inputs.persistence_days!r})"
            )
        if not volume_satisfied:
            missing.append(
                f"|repo_volume_change_pct| >= {volume_threshold} "
                f"(got {inputs.repo_volume_change_pct!r})"
            )
        warnings.append(
            f"A single-snapshot breach of {spread_to_iorb_bp:+.1f}bp above IORB is not "
            f"sufficient to declare ACUTE_REPO_STRESS (Section 22.11). Unmet "
            f"corroboration: {'; '.join(missing)}. Severity reported as ELEVATED. "
            f"Quarter-end and tax dates routinely produce one-snapshot breaches."
        )
    else:
        severity = raw_severity

    if severity == "ELEVATED":
        warnings.append(
            "Plumbing stress has historically preceded headline market stress — "
            "escalate to the risk layer if this persists across sessions."
        )

    if severity == "NORMAL":
        # A NORMAL reading is not the absence of information — it is a
        # single-snapshot observation that the corridor holds right now. Saying
        # so prevents "NORMAL" from being read as "the plumbing is fine",
        # which is a stronger claim than one reading can support.
        warnings.append(
            "Within the corridor. This is a single-snapshot observation — the "
            "signal is the persistence of a breach, not its absence in one reading."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not settings.is_calibrated(
                "bond_math.repo_stress.acute_threshold_bp"
            ),
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="repo_stress_check",
        country="us",
        as_of=utc_now(),
        value={
            "severity": severity,
            "sofr_minus_iorb_bp": round(spread_to_iorb_bp, 1),
            "sofr_minus_on_rrp_bp": round(spread_to_rrp_bp, 1),
            "raw_severity_before_corroboration": raw_severity,
            "corridor_intact": corridor_intact,
        },
        confidence=confidence,
        interpretation=(
            f"Repo market: {severity} (SOFR-IORB {spread_to_iorb_bp:+.1f}bp, "
            f"SOFR-ONRRP {spread_to_rrp_bp:+.1f}bp)"
        ),
        context=(
            "Floor system: SOFR should sit at or below IORB. A persistent breach "
            "indicates reserve scarcity, the September 2019 pattern. Escalation "
            "requires both persistence and repo-volume corroboration (Section 22.11)."
        ),
        inputs_used=[
            "sofr",
            "iorb",
            "on_rrp_rate",
            "fed_funds_effective",
        ],
        warnings=warnings,
    )
