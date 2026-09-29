"""Module 3 — national accounts: identities, index numbers, and monetary diagnostics.

AGENTS.md Section 20.3 and Section 20.5. Tier 1: pure arithmetic on supplied
inputs, no dependency on another model.

Why the identity functions are not trivia
-----------------------------------------
``savings_investment_identity`` looks like an accounting tautology and is
included for exactly that reason. ``(S - I) + (T - G) = (X - M)`` is an
identity — it cannot be violated by reality, only by a *thesis*. Its purpose is
to test proposals, not to predict: if a proposed trade-balance view implies a
current-account path that the saving and fiscal positions cannot arithmetically
produce, the view is incoherent before any forecast is attempted. Section 20.3
states it as "the current account is NOT an independent policy variable".

The index-number trio and what the gap between them means
--------------------------------------------------------
``laspeyres_index`` weights by *base*-period quantities; ``paasche_index`` by
*current*-period quantities; ``fisher_index`` is the geometric mean of the two.
The spread between Laspeyres and Paasche is not noise — it is the substitution
bias made visible. Laspeyres overstates inflation when consumers substitute away
from goods whose prices rose, because it holds the old basket fixed. The Fisher
index exists to split that difference, and Section 20.5 notes these are
"reference implementations for testing", which is why they take explicit
quantity vectors rather than reading a price index from the snapshot.

The quantity-theory trap
------------------------
``quantity_theory_implied_inflation`` is a diagnostic, not a forecast, and the
warning text says so at length. The mechanism is the interesting part: QE in
2009-2015 raised M enormously and produced almost no inflation because V
collapsed. COVID raised M *and* fiscal transfers kept V from collapsing, so P
moved. Any model that reads M growth as inflation is reproducing the failed
2010s prediction, so the warning is the substance rather than a disclaimer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

if TYPE_CHECKING:
    from macro_engine.config import MinskySettings, PolicyMixSettings

__all__ = [
    "FisherIndexInputs",
    "IndexNumberInputs",
    "MinskyCompositionInputs",
    "MinskyStage",
    "OpeningsToUnemployedInputs",
    "PolicyMixInputs",
    "PolicyMixQuadrant",
    "QuantityTheoryInputs",
    "SavingsInvestmentInputs",
    "fisher_index",
    "gdp_deflator",
    "laspeyres_index",
    "minsky_composition_drift",
    "openings_to_unemployed_ratio",
    "paasche_index",
    "policy_mix_classifier",
    "quantity_theory_implied_inflation",
    "savings_investment_identity",
]


class SavingsInvestmentInputs(FiniteInputs):
    """The four sectoral balances, in one consistent unit and period.

    No unit is declared because none is required — the identity is homogeneous
    of degree one, so currency levels and percent-of-GDP both work. What DOES
    matter is that all four are in the same unit; mixing them silently produces
    a balanced-looking nonsense. That cannot be checked from inside, so it is
    stated here as the caller's obligation.
    """

    model_config = ConfigDict(extra="forbid")

    private_saving: float = Field(description="S. Same unit as the other three.")
    private_investment: float = Field(description="I. Same unit as the other three.")
    tax_revenue: float = Field(description="T. Same unit as the other three.")
    government_spending: float = Field(description="G. Same unit as the other three.")


class QuantityTheoryInputs(FiniteInputs):
    """Growth rates for the exchange equation, all in percent."""

    model_config = ConfigDict(extra="forbid")

    money_supply_growth_pct: float = Field(description="%dM — money stock growth.")
    velocity_change_pct: float = Field(description="%dV — change in velocity of circulation.")
    real_output_growth_pct: float = Field(description="%dY — real output growth.")


class IndexNumberInputs(BaseModel):
    """A basket priced at two dates, with the quantity vector for one of them."""

    model_config = ConfigDict(extra="forbid")

    base_prices: dict[str, float] = Field(description="Item -> price in the base period.")
    base_quantities: dict[str, float] = Field(description="Item -> quantity in the base period.")
    current_prices: dict[str, float] = Field(description="Item -> price in the current period.")
    current_quantities: dict[str, float] = Field(
        default_factory=dict,
        description="Item -> quantity in the current period. Required by Paasche only.",
    )


class FisherIndexInputs(FiniteInputs):
    """The two index values to combine."""

    model_config = ConfigDict(extra="forbid")

    laspeyres: float = Field(gt=0.0, description="Laspeyres index value. Must be positive.")
    paasche: float = Field(gt=0.0, description="Paasche index value. Must be positive.")


class OpeningsToUnemployedInputs(FiniteInputs):
    """The two labor-market levels behind the ratio."""

    model_config = ConfigDict(extra="forbid")

    job_openings_thousands: float = Field(ge=0.0, description="JOLTS openings, thousands.")
    unemployed_persons_thousands: float = Field(
        gt=0.0,
        description=(
            "Unemployed persons, thousands. Strictly positive: the ratio's "
            "denominator, and zero unemployed persons is not an observable "
            "state for the US series."
        ),
    )


def savings_investment_identity(inputs: SavingsInvestmentInputs) -> ModelResult:
    """``(S - I) + (T - G) = (X - M)`` — the sectoral balances identity.

    Returns both component balances and their sum, because the components are
    what a thesis actually argues about. "The fiscal balance is the entire
    current account" is a claim about ``fiscal_balance`` relative to
    ``implied_current_account``, and it is only checkable if both are returned.
    """
    private_balance = inputs.private_saving - inputs.private_investment
    fiscal_balance = inputs.tax_revenue - inputs.government_spending
    implied_ca = private_balance + fiscal_balance

    if implied_ca < 0:
        ca_description = "deficit"
    elif implied_ca > 0:
        ca_description = "surplus"
    else:
        ca_description = "balanced"

    return ModelResult(
        model_name="savings_investment_identity",
        country="us",
        as_of=utc_now(),
        value={
            "private_balance": round(private_balance, 4),
            "fiscal_balance": round(fiscal_balance, 4),
            "implied_current_account": round(implied_ca, 4),
        },
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"Implied current account: {implied_ca:+,.4f} ({ca_description}) = "
            f"private balance {private_balance:+,.4f} + fiscal balance {fiscal_balance:+,.4f}"
        ),
        context=(
            "An IDENTITY, not a forecast: (S-I) + (T-G) = (X-M). Use it to test "
            "whether a trade-balance thesis is arithmetically coherent with the "
            "saving and fiscal positions (Module 3.1)."
        ),
        inputs_used=["private_saving", "private_investment", "tax_revenue", "government_spending"],
        warnings=[
            "All four inputs must share one unit and one period. The identity is "
            "homogeneous, so a unit mismatch still balances and produces a "
            "plausible-looking wrong answer."
        ],
    )


def quantity_theory_implied_inflation(inputs: QuantityTheoryInputs) -> ModelResult:
    """``%dP ~= %dM + %dV - %dY`` from ``M x V = P x Y``.

    A DIAGNOSTIC, deliberately not a forecast. Section 20.2's own note is
    explicit and is reproduced in the warnings rather than softened: velocity is
    the term that makes naive "money printing causes inflation" predictions fail,
    and it is unstable.
    """
    implied = (
        inputs.money_supply_growth_pct + inputs.velocity_change_pct - inputs.real_output_growth_pct
    )

    return ModelResult(
        model_name="quantity_theory_implied_inflation",
        country="us",
        as_of=utc_now(),
        value=round(implied, 2),
        confidence=compute_confidence(
            ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=0)
        ),
        interpretation=f"Identity-implied price-level change: {implied:+.2f}%",
        context=(
            f"Money growth {inputs.money_supply_growth_pct:+.2f}% + velocity change "
            f"{inputs.velocity_change_pct:+.2f}% - real output growth "
            f"{inputs.real_output_growth_pct:+.2f}%"
        ),
        inputs_used=[
            "money_supply_growth_pct",
            "velocity_change_pct",
            "real_output_growth_pct",
        ],
        warnings=[
            "Velocity instability makes this a DIAGNOSTIC ONLY — never use it as a "
            "standalone inflation forecast (Module 1.5/2.2). The QE of 2009-2015 "
            "raised M sharply with almost no price response because V collapsed; "
            "the 2020-21 episode moved P because fiscal transfers supported V. "
            "The same M growth produced opposite outcomes."
        ],
    )


def _validate_basket(
    name: str, prices: dict[str, float], quantities: dict[str, float] | None
) -> None:
    """Refuse baskets whose item sets disagree.

    A missing or extra item is the difference between weighting the same basket
    and weighting two different ones, and the arithmetic of an index number
    cannot detect the difference — it produces a number either way.
    """
    if not prices:
        raise ValueError(f"{name} prices are empty; an index over no items is undefined.")
    if quantities is None:
        raise ValueError(f"{name} quantities are empty; an index needs a weighting basket.")
    missing_from_prices = set(quantities) - set(prices)
    if missing_from_prices:
        raise ValueError(
            f"{name}: quantities reference items absent from prices: {sorted(missing_from_prices)}"
        )
    missing_from_quantities = set(prices) - set(quantities)
    if missing_from_quantities:
        raise ValueError(
            f"{name}: prices reference items absent from quantities: "
            f"{sorted(missing_from_quantities)}"
        )


def laspeyres_index(inputs: IndexNumberInputs) -> ModelResult:
    """Base-quantity-weighted price index.

    ``L = SUM[p_t * q_0] / SUM[p_0 * q_0] * 100``

    Overstates inflation when consumers substitute away from items whose prices
    rose, because the basket is frozen at base-period quantities. That bias is
    the reason the Fisher index exists, and comparing this against Paasche is
    how the bias is measured rather than assumed.
    """
    _validate_basket("base", inputs.base_prices, inputs.base_quantities)
    _validate_basket("current", inputs.current_prices, inputs.current_quantities)

    base_cost = sum(
        inputs.base_prices[item] * inputs.base_quantities[item] for item in inputs.base_prices
    )
    if base_cost == 0:
        raise ValueError("Base-period basket cost is zero; the index is undefined.")

    current_cost_at_base_quantities = sum(
        inputs.current_prices[item] * inputs.base_quantities[item] for item in inputs.base_prices
    )
    index = current_cost_at_base_quantities / base_cost * 100

    return ModelResult(
        model_name="laspeyres_index",
        country="us",
        as_of=utc_now(),
        value=round(index, 4),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=f"Laspeyres index: {index:.4f} (base = 100)",
        context=(
            f"Base basket cost={base_cost:.4f}, same basket at current prices="
            f"{current_cost_at_base_quantities:.4f}"
        ),
        inputs_used=["base_prices", "base_quantities", "current_prices"],
        warnings=[
            "Upward-biased relative to a cost-of-living index: base-period "
            "quantities ignore substitution toward goods whose relative prices fell."
        ],
    )


def paasche_index(inputs: IndexNumberInputs) -> ModelResult:
    """Current-quantity-weighted price index.

    ``P = SUM[p_t * q_t] / SUM[p_0 * q_t] * 100``

    Downward-biased relative to a cost-of-living index, for the mirror-image
    reason: it already assumes the substitution that Laspeyres ignores.
    """
    _validate_basket("current", inputs.current_prices, inputs.current_quantities)
    _validate_basket("base", inputs.base_prices, inputs.base_quantities)

    current_cost = sum(
        inputs.current_prices[item] * inputs.current_quantities[item]
        for item in inputs.current_prices
    )
    base_cost_at_current_quantities = sum(
        inputs.base_prices[item] * inputs.current_quantities[item] for item in inputs.current_prices
    )
    if base_cost_at_current_quantities == 0:
        raise ValueError("Base-period cost of the current basket is zero; the index is undefined.")

    index = current_cost / base_cost_at_current_quantities * 100

    return ModelResult(
        model_name="paasche_index",
        country="us",
        as_of=utc_now(),
        value=round(index, 4),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=f"Paasche index: {index:.4f} (base = 100)",
        context=(
            f"Current basket cost={current_cost:.4f}, same basket at base prices="
            f"{base_cost_at_current_quantities:.4f}"
        ),
        inputs_used=["base_prices", "current_prices", "current_quantities"],
        warnings=[
            "Downward-biased relative to a cost-of-living index: it credits "
            "substitution that a fixed-basket measure cannot.",
        ],
    )


def fisher_index(inputs: FisherIndexInputs) -> ModelResult:
    """Geometric mean of Laspeyres and Paasche.

    ``F = sqrt(L * P)``

    The geometric mean is the point, not an averaging convention: because
    Laspeyres is upward-biased and Paasche downward-biased, the geometric mean
    largely cancels the two and is the index actually used where accuracy
    matters. Section 20.5 specifies it explicitly.
    """
    index = (inputs.laspeyres * inputs.paasche) ** 0.5
    spread = inputs.laspeyres - inputs.paasche

    return ModelResult(
        model_name="fisher_index",
        country="us",
        as_of=utc_now(),
        value=round(index, 4),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=(
            f"Fisher index: {index:.4f} "
            f"(Laspeyres {inputs.laspeyres:.4f}, Paasche {inputs.paasche:.4f})"
        ),
        context=(
            f"Geometric mean cancels the opposing substitution biases. "
            f"Laspeyres-Paasche spread: {spread:+.4f} index points."
        ),
        inputs_used=["laspeyres", "paasche"],
    )


def gdp_deflator(nominal_gdp: float, real_gdp: float) -> ModelResult:
    """``Deflator = nominal / real * 100`` — the broadest domestic price measure.

    Distinct from CPI and PCE by construction rather than by measurement: the
    deflator covers everything in GDP, including investment and government
    consumption, whereas CPI covers a household consumption basket that includes
    imports. That difference is why the deflator and CPI can diverge for months
    without either being wrong.
    """
    if real_gdp == 0:
        raise ValueError("real_gdp is zero; the deflator is undefined.")

    deflator = nominal_gdp / real_gdp * 100

    return ModelResult(
        model_name="gdp_deflator",
        country="us",
        as_of=utc_now(),
        value=round(deflator, 3),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=f"GDP deflator: {deflator:.3f} (base year = 100)",
        context=(
            f"Nominal={nominal_gdp:,.3f}, Real={real_gdp:,.3f}. Covers all of GDP, "
            f"including investment and government consumption."
        ),
        inputs_used=["gdp_nominal", "gdp_real"],
        warnings=[
            "Not comparable to CPI or PCE as a level: different coverage (domestic "
            "production vs consumer basket), different treatment of imports, and "
            "usually a different base year. Compare growth rates, not levels."
        ],
    )


def openings_to_unemployed_ratio(inputs: OpeningsToUnemployedInputs) -> ModelResult:
    """Job openings per unemployed worker — the Fed's preferred tightness gauge.

    Section 20.3's bands: above 1.5 very tight, above 1.0 tight, above 0.7
    balanced, else slack. Those are judgment boundaries, so they live in config
    and are read here rather than written as literals.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    very_tight = settings.scalar("labor.openings_ratio.very_tight_threshold")
    tight = settings.scalar("labor.openings_ratio.tight_threshold")
    balanced = settings.scalar("labor.openings_ratio.balanced_threshold")

    ratio = inputs.job_openings_thousands / inputs.unemployed_persons_thousands

    if ratio > very_tight:
        tightness = "VERY_TIGHT"
    elif ratio > tight:
        tightness = "TIGHT"
    elif ratio > balanced:
        tightness = "BALANCED"
    else:
        tightness = "SLACK"

    return ModelResult(
        model_name="openings_to_unemployed_ratio",
        country="us",
        as_of=utc_now(),
        value=round(ratio, 3),
        confidence=compute_confidence(ConfidenceInputs()),
        interpretation=f"Openings per unemployed worker: {ratio:.2f} ({tightness})",
        context=(
            f"Openings={inputs.job_openings_thousands:,.0f}k, "
            f"Unemployed={inputs.unemployed_persons_thousands:,.0f}k. "
            f"Explicitly cited by the Fed as a preferred tightness gauge (Module 6.2)."
        ),
        inputs_used=["job_openings_thousands", "unemployed_persons_thousands"],
    )


# ---------------------------------------------------------------------------
# Module 3.2 — the fiscal/monetary policy mix
# ---------------------------------------------------------------------------

#: The four quadrants of Module 3.2's 2x2, as a closed vocabulary (D-029).
PolicyMixQuadrant = Literal[
    "MAX_STIMULUS",
    "MIXED_FISCAL_LOOSE_MONETARY_TIGHT",
    "MIXED_FISCAL_TIGHT_MONETARY_LOOSE",
    "MAX_RESTRAINT",
]


class PolicyMixInputs(FiniteInputs):
    """The two fiscal quantities and the two monetary ones the 2x2 compares.

    **The fiscal sign convention is the trap.** ``fiscal_deficit_pct_gdp`` is
    stated as **positive for a deficit**, which is the opposite of the source
    series: FRED ``FYFSGDA188S`` is negative for a deficit (-5.77 for 2025,
    -14.48 for 2020, negative in 83 of its 97 observations). A caller who feeds
    the raw FRED figure inverts the comparison — a LARGER deficit is MORE
    negative, so ``deficit > average`` would report the most stimulative budgets
    in the sample as the tightest fiscal policy. The live check negates the
    series and asserts the sign before use.
    """

    model_config = ConfigDict(extra="forbid")

    fiscal_deficit_pct_gdp: float = Field(
        description=(
            "Federal deficit as % of GDP, POSITIVE for a deficit and negative "
            "for a surplus. The source series uses the opposite sign, so a "
            "caller reading FRED `FYFSGDA188S` directly must negate it."
        ),
    )
    fiscal_deficit_avg_pct_gdp: float = Field(
        description=(
            "The trailing average the deficit is judged against, same sign "
            "convention. Section 21.1 sources it from "
            "`settings.yaml: policy_mix.fiscal_deficit_avg_pct_gdp`; the model "
            "checks the supplied value against that expectation and warns on a "
            "mismatch, because the two are one measurement."
        ),
    )
    policy_rate: float = Field(
        description="The actual policy rate, in percent. May be negative (ZIRP).",
    )
    taylor_implied_rate: float = Field(
        description=(
            "The Taylor rule's implied rate, in percent — DERIVED from "
            "`taylor_rule` (Module 4.1). Monetary policy is called loose when "
            "the actual rate sits BELOW this."
        ),
    )


def policy_mix_classifier(inputs: PolicyMixInputs) -> ModelResult:
    """Place the policy stance in Module 3.2's fiscal/monetary 2x2.

    Section 20.3's premise: naive Fed-only analysis misses half the picture when
    fiscal pulls the opposite direction — the post-2022 disinflation case, where
    fiscal was loose while monetary tightened. The two MIXED quadrants are
    exactly that situation, and the model says so on every one of them.

    Confidence is computed from the stated factors (Section 22.8), never
    asserted. ``depends_on_unobservable=True`` is a **fact about the
    computation**, not a feeling about the answer: the Taylor-implied rate is
    built on ``r*`` and potential GDP, both unobservable by nature (Section 21.4
    item 13), and the fiscal half rests on an uncalibrated trailing average.
    """
    settings = _policy_mix_settings()

    # Positive-for-a-deficit on both sides. See the field descriptions.
    fiscal_loose = inputs.fiscal_deficit_pct_gdp > inputs.fiscal_deficit_avg_pct_gdp
    monetary_loose = inputs.policy_rate < inputs.taylor_implied_rate

    quadrant: PolicyMixQuadrant
    if fiscal_loose and monetary_loose:
        quadrant = "MAX_STIMULUS"
    elif fiscal_loose:
        quadrant = "MIXED_FISCAL_LOOSE_MONETARY_TIGHT"
    elif monetary_loose:
        quadrant = "MIXED_FISCAL_TIGHT_MONETARY_LOOSE"
    else:
        quadrant = "MAX_RESTRAINT"

    # "Mixed" is fiscal and monetary DISAGREEING — tested on the booleans rather
    # than by searching the quadrant name for "MIXED". A substring test happens
    # to work on today's names and breaks silently the moment one is renamed.
    mixed = fiscal_loose != monetary_loose

    quadrant_base_rate = settings.quadrant_base_rates[quadrant]
    warnings = [
        f"The policy mix is a CATEGORICAL from two threshold comparisons. Over "
        f"{settings.base_rates.observations_measured} annual observations this "
        f"quadrant occurred in {quadrant_base_rate:.1%} of them, which is the "
        f"frequency a reader needs before treating it as notable (D-029).",
    ]

    if mixed:
        warnings.append(
            "MIXED quadrants mean Fed-only analysis is incomplete — fiscal is "
            "working against monetary (Module 3.2). This is the case the module "
            "exists for: the two MIXED quadrants together are 50.9% of the "
            "measured history, so a mixed stance is ordinary, not exceptional."
        )

    if (
        abs(inputs.fiscal_deficit_avg_pct_gdp - settings.fiscal_deficit_avg)
        > settings.deficit_mismatch_tolerance
    ):
        warnings.append(
            f"The supplied deficit average ({inputs.fiscal_deficit_avg_pct_gdp:.2f}% "
            f"of GDP) differs from the configured expectation "
            f"({settings.fiscal_deficit_avg:.2f}%). The two are one measurement — "
            f"a caller using a different window will place the same deficit in a "
            f"different quadrant, so the disagreement is reported rather than "
            f"silently accepted."
        )

    if inputs.fiscal_deficit_pct_gdp < 0.0:
        # The sign trap, caught at the point of use rather than trusted.
        warnings.append(
            f"fiscal_deficit_pct_gdp is negative ({inputs.fiscal_deficit_pct_gdp:+.2f}). "
            f"This field is POSITIVE for a deficit, so a negative value means either a "
            f"genuine surplus or the raw FRED `FYFSGDA188S` figure supplied without "
            f"negating it — and the second inverts every comparison silently."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The deficit average is uncalibrated_illustrative in settings.yaml.
            is_heuristic_not_calibrated=not _policy_mix_calibrated(),
            # The Taylor-implied rate rests on r* and potential GDP, both
            # unobservable by nature (Section 21.4 item 13).
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="policy_mix_classifier",
        country="us",
        as_of=utc_now(),
        value={
            "quadrant": quadrant,
            # The two predicates, published so the quadrant is RECOMPUTABLE from
            # the output rather than trusted (the D-009 cross-field identity).
            "fiscal_loose": fiscal_loose,
            "monetary_loose": monetary_loose,
            "mixed": mixed,
            "fiscal_deficit_pct_gdp": round(inputs.fiscal_deficit_pct_gdp, 4),
            "fiscal_deficit_avg_pct_gdp": round(inputs.fiscal_deficit_avg_pct_gdp, 4),
            "policy_rate": round(inputs.policy_rate, 4),
            "taylor_implied_rate": round(inputs.taylor_implied_rate, 4),
            "quadrant_base_rate": quadrant_base_rate,
            "observations_measured": settings.base_rates.observations_measured,
        },
        confidence=confidence,
        interpretation=f"Policy mix: {quadrant}",
        context=(
            f"Fiscal {'loose' if fiscal_loose else 'tight'} / "
            f"Monetary {'loose' if monetary_loose else 'tight'} vs Taylor-implied. "
            f"A trade or policy thesis built on monetary stance alone is "
            f"incomplete when the two disagree (Module 3.2)."
        ),
        inputs_used=[
            "fiscal_deficit_pct_gdp",
            "fiscal_deficit_avg_pct_gdp",
            "policy_rate",
            "taylor_implied_rate",
        ],
        warnings=warnings,
    )


def _policy_mix_calibrated() -> bool:
    """Whether the deficit average is calibrated or an illustrative placeholder."""
    from macro_engine.config import get_settings

    return get_settings().is_calibrated("policy_mix.fiscal_deficit_avg_pct_gdp")


def _policy_mix_settings() -> PolicyMixSettings:
    """Read Module 3.2's deficit average and quadrant base rates. Lazy, to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().policy_mix


# ---------------------------------------------------------------------------
# Module 3.4 — Minsky composition drift
# ---------------------------------------------------------------------------

#: The three stages of the credit cycle, as a closed vocabulary (D-029).
MinskyStage = Literal["PONZI_DRIFT_WARNING", "SPECULATIVE_DRIFT", "HEDGE_DOMINANT"]


class MinskyCompositionInputs(FiniteInputs):
    """Lending standards and the two credit-growth rates the drift is read from.

    **Two of these three inputs are BLOCKED by Section 21.1**, which says of
    `risky_credit_growth_pct` and `total_credit_growth_pct`: *"No clean free
    series for leveraged-loan growth. Raise NotImplementedError; log in
    OPEN_ISSUES.md. Do NOT substitute total credit growth as a proxy."*

    So this model cannot be run against live data on this build, and the
    specification's own instruction is a substitution ban rather than a proxy
    permission. The values are still accepted as **externally supplied** floats,
    because the function is pure arithmetic and the block is about *sourcing*,
    not about the logic — but a consumer must know that nothing in this system
    produced them. See D-041 and O-20.
    """

    model_config = ConfigDict(extra="forbid")

    lending_standards_net_tightening_pct: float = Field(
        description=(
            "Net percentage of banks tightening lending standards (SLOOS "
            "`DRTSCILM`), in percent. NEGATIVE means net LOOSENING. This is the "
            "one input Section 21.1 marks LIVE. Note that a reading of exactly "
            "zero counts as NOT loosening, which occurred in 7 of 146 quarters."
        ),
    )
    risky_credit_growth_pct: float = Field(
        description=(
            "Growth in leveraged-loan / subprime-equivalent credit, in percent. "
            "**BLOCKED** — Section 21.1 provides no free series and forbids "
            "substituting total credit growth for it."
        ),
    )
    total_credit_growth_pct: float = Field(
        description=(
            "Growth in total credit, in percent. **BLOCKED**, same as above. "
            "Negative values are common in contractions — 3.3% of measured "
            "weeks — and are where the specification's comparison breaks."
        ),
    )


def minsky_composition_drift(inputs: MinskyCompositionInputs) -> ModelResult:
    """Classify credit-cycle composition drift (Module 3.4, Section 20.3).

    The specification's premise: the **warning sign is composition drift** toward
    speculative/Ponzi financing, visible in loosening standards plus risky credit
    outgrowing total credit — **not high credit growth per se**, which can be
    perfectly healthy hedge-borrower expansion.

    **One correction, and it matters most when it matters most.** Section 20.3
    tests ``risky_credit_growth_pct > total_credit_growth_pct * 1.2``. Multiplying
    a **negative** base by 1.2 makes it *more* negative, so the flag fires when
    risky credit is shrinking **fastest**:

        total -10%, risky -11%  ->  -11 > -12  ->  "outgrowing"  (WRONG)

    Risky credit falling faster than total is **de-risking**, and negative total
    growth occurs in **3.3%** of measured weeks — including 2009-09, the crisis
    the module exists to flag. The margin is applied to the **gap** instead:
    ``(risky - total) > margin * |total|``, which is identical to the
    specification's form whenever total growth is positive.

    **Confidence is computed from evidence, not from the conclusion.** Section
    20.3 hardcodes 0.6 for PONZI_DRIFT_WARNING, 0.45 for SPECULATIVE_DRIFT and
    0.5 for HEDGE_DOMINANT — so it is *more* confident when it says something is
    wrong. That is a bias toward alarm with no stated basis; confidence here
    reflects the inputs' quality, which does not depend on which stage comes out.

    **Two of the three inputs are BLOCKED** (Section 21.1). No live run is
    possible, the stage's base rate cannot be measured, and the output says so.
    """
    settings = _minsky_settings()
    margin = settings.drift_margin_pct

    standards_loosening = inputs.lending_standards_net_tightening_pct < 0.0

    # The sign-safe form. See the docstring and settings.yaml.
    growth_gap = inputs.risky_credit_growth_pct - inputs.total_credit_growth_pct
    drift_threshold = margin * abs(inputs.total_credit_growth_pct)
    risky_outgrowing = growth_gap > drift_threshold

    stage: MinskyStage
    if standards_loosening and risky_outgrowing:
        stage = "PONZI_DRIFT_WARNING"
    elif standards_loosening or risky_outgrowing:
        stage = "SPECULATIVE_DRIFT"
    else:
        stage = "HEDGE_DOMINANT"

    stage_base_rate = settings.base_rates.stage_rates[stage]
    warnings = [
        # The proxy, named on every call. D-043 lifted the block; it did not
        # remove the reason a reader needs to know what the measure is.
        "`risky_credit_growth_pct` is a DISCLOSED PROXY: it is hedge funds' "
        "leveraged-loan holdings (FRED `BOGZ1FL623069503Q`), which is the right "
        "asset class but a narrower holder base than the whole leveraged-loan "
        "market. The series also reads zero before 2013-Q4, so the measurable "
        "history is 51 quarters and excludes the 2008 crisis (D-043).",
        f"The stage is a CATEGORICAL from two threshold comparisons. Over "
        f"{settings.base_rates.stage_observations_measured} quarters this stage "
        f"occurred in {stage_base_rate:.1%} of them — the frequency a reader needs "
        f"before treating it as notable (D-029).",
        f"The only input that can be sourced is lending standards, which net "
        f"loosened in {settings.base_rates.standards_loosening_rate:.1%} of "
        f"{settings.base_rates.observations_measured} SLOOS quarters.",
        f"Risky credit must outgrow total credit by more than "
        f"{margin:.0%} of |total growth| to count as drift — the specification's "
        f"`* 1.2` applied to the GAP rather than the rate, because the "
        f"multiplicative form inverts when total growth is negative.",
    ]

    if inputs.lending_standards_net_tightening_pct == 0.0:
        warnings.append(
            "Lending standards read exactly zero, which Section 20.3's `< 0` test "
            "counts as NOT loosening. A flat survey is neither tightening nor "
            "loosening, and it occurred in 7 of 146 quarters — the boundary is a "
            "convention, not a finding."
        )

    if stage == "PONZI_DRIFT_WARNING":
        warnings.append(
            "Defaults are a LAGGING confirmation — by the time they rise, the "
            "drift already happened (Module 3.4)."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The margin is uncalibrated_illustrative in settings.yaml.
            is_heuristic_not_calibrated=not _minsky_calibrated(),
            # Raised because the risky-credit measure is a DISCLOSED PROXY: a
            # narrower holder base than the asset class, and only 51 usable
            # quarters. That is a data-quality caveat confidence should carry.
            data_quality_flags_present=True,
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="minsky_composition_drift",
        country="us",
        as_of=utc_now(),
        value={
            "stage": stage,
            # The predicates, published so the stage is RECOMPUTABLE from the
            # output rather than trusted (the D-009 cross-field identity).
            "standards_loosening": standards_loosening,
            "risky_outgrowing": risky_outgrowing,
            "growth_gap_pct": round(growth_gap, 4),
            "drift_threshold_pct": round(drift_threshold, 4),
            "lending_standards_net_tightening_pct": round(
                inputs.lending_standards_net_tightening_pct, 4
            ),
            "risky_credit_growth_pct": round(inputs.risky_credit_growth_pct, 4),
            "total_credit_growth_pct": round(inputs.total_credit_growth_pct, 4),
            "drift_margin_pct": margin,
            "standards_loosening_base_rate": settings.base_rates.standards_loosening_rate,
            "observations_measured": settings.base_rates.observations_measured,
            # Measurable only since D-043 lifted the block. Before that there was
            # no history to classify and recording a rate would have meant
            # inventing one.
            "stage_base_rate": stage_base_rate,
            "stage_observations_measured": settings.base_rates.stage_observations_measured,
            "risky_credit_proxy": "hedge_fund_leveraged_loans",
        },
        confidence=confidence,
        interpretation=f"Credit cycle composition: {stage}",
        context=(
            "Composition drift, not aggregate credit growth, is the leading "
            "indicator (Module 3.4). The risky-credit measure is hedge funds' "
            "leveraged-loan holdings — a disclosed proxy, right asset class and "
            "narrower holder base (D-043)."
        ),
        inputs_used=[
            "lending_standards_net_tightening_pct",
            "risky_credit_growth_pct",
            "total_credit_growth_pct",
        ],
        warnings=warnings,
    )


def _minsky_calibrated() -> bool:
    """Whether Module 3.4's drift margin is calibrated or an illustrative placeholder."""
    from macro_engine.config import get_settings

    return get_settings().is_calibrated("minsky.drift_margin_pct_value")


def _minsky_settings() -> MinskySettings:
    """Read Module 3.4's margin and base rate. Lazy, to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().minsky
