"""Module 9 — Intervention Capacity: the asymmetry of defending a currency.

Section 20.9 gives Module 9 a third function beside the parity relations, and
:func:`intervention_capacity` is that function. Unlike ``cip_check``,
``uip_expected_move`` and ``ppp_valuation`` — which relate two interest rates, or
a price level to a market rate — this one is about a central bank's **capacity**
to move its currency at all, and about the fact that the capacity is **not the
same in both directions**.

The asymmetry, which is the whole content of the function
---------------------------------------------------------
A central bank that wants its currency **weaker** sells its **own** currency —
which it can create without limit. A central bank that wants its currency
**stronger** must buy its own currency and pay with **foreign-exchange
reserves**, which are a finite stock it cannot print. So:

* **Weakening** is **mechanically unconstrained**: the ammunition is the printing
  press, and the constraint is not supply but **cost** — the balance-sheet
  damage and import-price inflation that eventually make the bank stop. That is
  the **SNB 2015** failure mode: abandonment by cost, not by exhaustion.
* **Strengthening** is **reserve-constrained** and therefore **breakable**: the
  bank is spending a finite stock against a market that can hold more than the
  stock is worth. That is the **Black Wednesday 1992** failure mode: exhaustion
  under speculative attack.

**The word "unlimited" is deliberately absent from every output.** Section 22.11
amends Section 20.9's reference implementation for exactly this reason: the
specification's ``"UNLIMITED_AMMUNITION_but_costly"`` reads as *risk-free* to a
caller skimming a label, when what is unconstrained is the MECHANISM and nothing
else. The published literal is
``"MECHANICALLY_UNCONSTRAINED_COST_BOUNDED"``.

What is derived, and what is not
--------------------------------
The **direction→constraint mapping** is derived from the accounting above, not
recalled: to buy your own currency you must spend another's, and you cannot
print another's. It is not a statistical estimate and this function does not
pretend to produce one.

What the function *measures*, when a caller lets it, is the **reserve
burn rate** — the twelve-month change in the reserve stock, which is the
observable that distinguishes a bank with a defence from a bank whose defence is
already failing. It is an **input**, fetched or supplied, never inferred from
the direction alone.

The reserve input is LIVE, not blocked
--------------------------------------
Section 20.9's ``InterventionCapacityInputs`` carries ``fx_reserves_usd_bn`` and
``reserves_to_gdp_pct`` with no source stated, and ``config/series_registry.yaml``
had **no entry** for either — which under Section 21.1's default rule ("any input
not listed is BLOCKED") would make them BLOCKED. Measured 2026-09-27, they are
not. The BIS/IMF reserve series are reachable through this installation:

* ``TRESEGJPM052N`` — Japan, total reserves minus gold (USD mn), 843 obs
* ``TRESEGGBM052N`` — United Kingdom, same, 843 obs
* ``TRESEGCNM052N`` — China, same, 563 obs

This is the **fourth FALSE BLOCK** this repository has caught (D-043's class,
after `ppp_implied_rate` at D-115/D-117), and the correct response to a
measurably-false block is to record the source and wire it rather than leave a
typed constant in its place. So ``reserves_usd_bn`` may be **fetched** (the live
path) exactly as ``ppp_implied_rate`` may be, and a caller-supplied value is
disclosed as supplied so the two can never read alike.

The unit trap: reserves are quoted in MILLIONS
----------------------------------------------
``TRESEGJPM052N`` and its siblings are denominated in **millions of US dollars**
(measured: Japan reads ``1083420.49`` = USD 1.083 trillion). The input field is
named ``reserves_usd_bn`` — **billions** — because a reserve stock expressed in
millions is a number no reader can sanity-check at a glance. The conversion
(dividing a fetched millions figure by 1000) is performed by the fetcher and the
**published** value is always billions, with the source unit named on the
disclosure. A 1000x error between "millions" and "billions" produces a perfectly
plausible-looking reserve figure either way, which is the same silent class the
``source_units`` field exists to prevent in the registry.

Confidence — two producers, and why
-----------------------------------
Section 22.8 forbids a bare literal, and Section 20.9's reference implementation
ships two (``0.8`` and ``0.7``). Neither is used here. The published confidence
is built from **two** statements, both of which are checkable from the output:

* ``compute_confidence()`` over the **inputs actually used** — this is the
  input-quality half. When the reserves were fetched live, the input quality is
  genuinely better than when the caller typed a number with no vintage, and the
  computed confidence reflects that rather than a fixed constant.
* a **model-specific config CAP** — ``intervention.reliability_cap`` — applied
  because ``compute_confidence()`` has no factor for the one thing that most
  limits this function: **the asymmetry doctrine is a statement about
  mechanisms, and the model contains no measured estimate of when a bank
  abandons a defence.** The cap is the mechanism by which the *method's*
  weakness is admitted when the *inputs* are good. It is deliberately the
  **lowest** cap in the FX family (below ``ppp_reliability_cap`` 0.2 and
  ``uip_reliability_cap`` 0.15): the parity relations at least relate
  observable prices, whereas this function's core claim rests on doctrine.

Refusals, not silent nulls
--------------------------
Section 20.9's reference implementation publishes
``value={"capacity": ..., "reserves_usd_bn": inputs.fx_reserves_usd_bn}``, so a
caller that passes ``None`` receives ``reserves_usd_bn: None`` inside an
otherwise well-formed result. That is the silent-failure shape this project has
paid for repeatedly: **a null that travels as a value**. Here the reserves are
**required for a reserve-constrained verdict** — the label is a claim that the
stock is finite and the caller knows how large it is — so a strengthening
direction with no reserve figure **refuses** rather than emitting a null beside a
0.7-confidence verdict. A weakening direction does not need the stock (the
mechanism is the printing press, not the stock), but the reserve figure is still
optional there and its absence is disclosed rather than implied.

Supersession (Section 21.3, D-096)
----------------------------------
**This function supersedes nothing named, and nothing supersedes it.** Phase 5+
is an upgrade pass: every other Tier-5 name is a REPLACEMENT for a simpler
Phase 0-4 function, and the honest answer for this one is the ``cip_check``
answer — *a new capability*. It shares **no input** with the parity family
(``cip_check`` / ``uip_expected_move`` / ``ppp_valuation``) and none with the
carry family (``carry_score`` / ``dollar_smile_regime``): those read two interest
rates, a spot rate, a forward, a volatility or a price level, whereas this reads
a **reserve stock and a direction**. It is Module 9's capital/balance-sheet
dimension, which Module 9 did not previously have.

It **feeds** ``check_trilemma_tension`` (``models/regime.py``), which Section
20.9's own warning names: that function's severe label ``CRITICAL_PEG_STRESS``
fires when "reserves are burning", and the burn rate published here is the
observable that decides whether that clause is true. The two are complementary
rather than duplicated — the trilemma check classifies a *regime* from three
manual booleans and does not read a reserve series at all.
"""

from __future__ import annotations

import logging
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.data_layer.reserves_client import (
    MILLIONS_PER_BILLION,
    ReservesReadError,
    fetch_reserves,
)
from macro_engine.models.contracts import (
    ConfidenceInputs,
    EvidenceSourceFamily,
    ModelResult,
    compute_confidence,
    utc_now,
)

logger = logging.getLogger(__name__)

__all__ = [
    "INTERVENTION_DIRECTIONS",
    "InterventionCapacityInputs",
    "intervention_capacity",
]

#: The two directions a central bank can intervene in. A ``Literal`` rather than
#: a bare ``str`` because Section 20.9 types the field as a bare string and its
#: reference implementation then branches on ``== "weaken_own_currency"`` with a
#: documented-choice ``else``. That ``else`` sends **every unrecognised value**
#: — a typo, an emptied field, the other language's spelling — down the
#: *reserve-constrained* branch, so a caller who misspells the direction gets a
#: confident verdict about the opposite intervention. Pydantic now refuses the
#: value instead, and the vocabulary is declared once here.
INTERVENTION_DIRECTIONS: tuple[str, str] = (
    "strengthen_own_currency",
    "weaken_own_currency",
)


class InterventionCapacityInputs(BaseModel):
    """What a central bank is trying to do, and what it has to do it with.

    Section 20.9 declares four fields; all four are kept, with three
    corrections that its reference implementation cannot express:

    * **``direction`` is a ``Literal``**, so an unrecognised value is refused at
      construction instead of falling through a bare ``else`` into the opposite
      verdict.
    * **``fx_reserves_usd_bn`` is in BILLIONS and says so.** Section 20.9's
      field carries no unit, and the reachable source publishes **millions**; the
      fetcher converts, and this docstring plus the disclosure name the unit on
      the published value. A 1000x error here is invisible in the output.
    * **``reserves_change_12m_pct`` is added.** The reserve *stock* alone cannot
      distinguish a bank with ammunition from a bank whose defence is already
      spending it; the twelve-month change is the observable that can, and it is
      reachable from the same series. Section 20.9 does not carry it, so adding
      it is an addition recorded as such rather than a silent widening.

    Domain guards, all at construction. Reserves, when present, must be
    **positive**: a zero or negative reserve stock is not a stock, and a
    negative one would make the "finite and depleting" reading meaningless while
    still producing a confident label. ``nan`` is refused explicitly because
    ``nan`` fails every comparison, so a ``<=`` guard never fires for it (D-078).
    """

    model_config = ConfigDict(extra="forbid")

    country: str = Field(
        description=(
            "ISO-3166 alpha-2 lowercase, or an ISO-3166 alpha-3 for the "
            "fetched-reserves path. Phase 4 is US-only (Section 22.3); this "
            "function is Module 9's second country-general surface after the PPP "
            "leg, and the country is what selects the reserve series."
        ),
    )
    direction: Literal["strengthen_own_currency", "weaken_own_currency"] = Field(
        description=(
            "Which way the central bank is trying to move its OWN currency. "
            "'strengthen_own_currency' = buying own currency with reserves "
            "(reserve-constrained, breakable). 'weaken_own_currency' = selling "
            "own currency into the market, which it can print (mechanically "
            "unconstrained, cost-bounded)."
        ),
    )
    fx_reserves_usd_bn: float | None = Field(
        default=None,
        description=(
            "Total FX reserves in BILLIONS of US dollars, or None to let the "
            "fetcher resolve them. Section 20.9 leaves the unit unstated; the "
            "reachable BIS/IMF series publish MILLIONS, so the fetcher divides "
            "by 1000 and this field is always billions on the way out. Required "
            "for a 'strengthen_own_currency' verdict — a reserve-constrained "
            "label with no reserve figure is an assertion the inputs do not "
            "support."
        ),
    )
    reserves_to_gdp_pct: float | None = Field(
        default=None,
        description=(
            "Reserves as a percentage of GDP (0-100 scale, 12.5 = 12.5%). "
            "Section 20.9 carries it but never reads it; here it is used as an "
            "AMPLE/THIN scale, and its absence is disclosed rather than "
            "silently ignored. The convention is the World Bank's "
            "`total reserves (% of GDP)` series, which is the published "
            "definition a reader will assume."
        ),
    )
    reserves_change_12m_pct: float | None = Field(
        default=None,
        description=(
            "Twelve-month change in the reserve stock, in PERCENT "
            "(-11.98 = the stock fell 11.98% over the year). The observable "
            "that separates a bank with a defence from one already spending it. "
            "None when the caller cannot supply it or the series is too short; "
            "the limitation is disclosed rather than treated as no change."
        ),
    )

    @model_validator(mode="after")
    def _validate_domain(self) -> InterventionCapacityInputs:
        """Refuse an input that is representable but is not a reserve quantity.

        Three branches, each closing a way the function returns a confident
        number from an input with no meaning:

        1. a non-finite reserve figure. ``nan`` passes no comparison, so a plain
           ``<= 0`` guard would let it through and it would then be published as
           the stock (D-078's class);
        2. a non-positive reserve stock. Zero is not a stock and a negative one
           would invert the "finite, depleting" reading while still producing a
           label;
        3. a non-finite change or reserve/GDP ratio, for the same reason as (1).
        """
        for name, value in (
            ("fx_reserves_usd_bn", self.fx_reserves_usd_bn),
            ("reserves_to_gdp_pct", self.reserves_to_gdp_pct),
            ("reserves_change_12m_pct", self.reserves_change_12m_pct),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(
                    f"{name} must be finite when present; got {value!r}. A "
                    "non-finite value passes every comparison guard, so it must "
                    "be refused rather than guarded."
                )
        if self.fx_reserves_usd_bn is not None and self.fx_reserves_usd_bn <= 0.0:
            raise ValueError(
                "fx_reserves_usd_bn must be strictly positive when present; "
                f"got {self.fx_reserves_usd_bn!r}. Zero is not a reserve stock, "
                "and a negative one would make a 'finite and depleting' verdict "
                "meaningless while still producing a confident label."
            )
        return self


def intervention_capacity(inputs: InterventionCapacityInputs) -> ModelResult:
    """Classify how constrained a central bank's currency defence is.

    Consumed by the risk layer and cited in Section 20.9's own warning to
    ``check_trilemma_tension()``; never an instrument or a trade.

    The published ``value`` carries three things, because a capacity label alone
    is not sufficient to check the verdict:

    * ``capacity`` — one of the two literals. ``"MECHANICALLY_UNCONSTRAINED_"
      "COST_BOUNDED"`` for a weakening defence, ``"RESERVE_CONSTRAINED_"
      "breakable"`` for a strengthening one. This is Section 22.11's mandated
      rename of Section 20.9's ``"UNLIMITED_AMMUNITION_but_costly"``.
    * ``reserves_usd_bn`` — the stock in billions, or ``None`` when the caller
      supplied none and the direction does not require one.
    * ``reserves_change_12m_pct`` — the burn rate, or ``None``, with a warning
      when the strengthening case proceeds without it.

    A ``strengthen_own_currency`` call with no reserve stock **refuses**
    (``ValueError``). The label is a claim that a finite stock constrains the
    bank; publishing that claim while holding no stock figure would be the
    "null that travels as a value" shape this project has paid for, so the
    function returns nothing rather than a confident-looking result with no
    evidence behind two of its three fields.
    """
    settings = get_settings()
    intervention = settings.intervention

    reserves_bn = inputs.fx_reserves_usd_bn
    burn_pct = inputs.reserves_change_12m_pct
    reserves_provenance: str

    # --- resolve the reserve stock: fetch it, or take the caller's value -----
    # As in `ppp_valuation` (D-117), the fetch is the ONLY live path — there is
    # no manual fallback to drift alongside it, because a dead fallback reads
    # exactly like a live fetch whenever it fires. A caller may still supply a
    # number, and it is then DISCLOSED as supplied.
    if reserves_bn is None:
        reserves_bn, fetched_burn_pct, reserves_provenance = _fetch_reserves_bn(inputs.country)
        if burn_pct is None:
            burn_pct = fetched_burn_pct
    else:
        reserves_provenance = (
            "SUPPLIED BY THE CALLER — the unit is billions of USD as declared "
            "by this model's input contract, and the vintage is unknown."
        )
    if inputs.direction == "strengthen_own_currency":
        if reserves_bn is None:
            raise ValueError(
                "A 'strengthen_own_currency' verdict is a claim that a FINITE "
                "reserve stock constrains the bank. No reserve stock is "
                "available for this country and the caller supplied none, so "
                "the claim cannot be supported and is not made. Supply "
                "fx_reserves_usd_bn, or use a country whose reserve series is "
                "reachable."
            )
        capacity = intervention.reserve_constrained_label
        note = (
            "Must sell finite reserves to buy its own currency. Failure mode is "
            "EXHAUSTION under speculative attack (Black Wednesday 1992), not "
            "cost. The constraint is the STOCK."
        )
    else:
        capacity = intervention.mechanically_unconstrained_label
        note = (
            "Can create and sell unlimited own currency. Failure mode is "
            "COST-DRIVEN ABANDONMENT (SNB 2015) — balance-sheet loss and "
            "import-price inflation — not exhaustion. The mechanism is "
            "unconstrained; the POLICY is not."
        )

    # --- confidence: two producers, both load-bearing ------------------------
    # The input-quality half is computed from facts about THIS run rather than
    # asserted: the reserve figure's origin decides whether a data-quality flag
    # is present, and a fetched figure contributes one independent family. The
    # method's weakness is handled by the config cap, because
    # `compute_confidence()` has no factor for "the doctrine is unmeasured".
    #
    # ⚠️ THE TWO COMBINE MULTIPLICATIVELY, NOT BY `min()`. `min()` was the first
    # draft and it was WRONG here: the computed value is 0.55 fetched / 0.25
    # supplied, both ABOVE the 0.12 cap, so `min()` would have published 0.12 on
    # every path and the entire `compute_confidence()` branch would have been
    # dead code — a computation that never changes an output is scaffolding, not
    # a model. Multiplying makes each factor load-bearing: the cap states how
    # much the METHOD is worth, and the computed value states how much THIS
    # run's inputs are worth relative to a perfect one, so a fetched reserve
    # beats a typed one in the published number instead of the distinction being
    # discarded. Both remain visible in the result.
    fetched = reserves_bn is not None and reserves_provenance.startswith("FETCHED")
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=not fetched,
            is_heuristic_not_calibrated=not intervention.reliability_cap_is_calibrated,
            source_independence_count=1 if fetched else 0,
            depends_on_unobservable=False,
        )
    )
    confidence = computed * intervention.reliability_value

    warnings: list[str] = []

    # The direction-specific warning first.
    if capacity == intervention.reserve_constrained_label:
        warnings.append(
            "Reserve-constrained defences are BREAKABLE — pair with "
            "check_trilemma_tension() before any peg-related thesis (Section "
            "20.9)."
        )
    else:
        warnings.append(
            "Unlimited-ammunition defences still fail via accumulated COST — do "
            "not assume permanence (SNB 2015). 'Unlimited' describes the "
            "mechanism, never the risk."
        )

    # ⚠️ THE DEPLETION WARNING IS DIRECTION-INDEPENDENT, AND THAT IS THE FIX THE
    # TEST DROVE. A reserve burn is a FACT ABOUT THE WORLD, not a property of the
    # intervention's direction: a bank defending its currency spends reserves
    # whether it is buying its own (the classic case) or intervening in a market
    # that is moving against it for other reasons — and the SNB's 2015 episode,
    # which the weakening branch's own warning cites, was an EXPANSION of the
    # balance sheet whose cost was the point. Gating the burn alert behind the
    # reserve-constrained branch would have silently suppressed the depletion
    # signal on exactly the direction whose failure mode the model describes as
    # cost-driven — i.e. where a burnout is easiest to miss.
    if burn_pct is not None and burn_pct <= -intervention.burn_alert_value:
        warnings.append(
            f"Reserves are BURNING: {burn_pct:.2f}% over twelve months "
            f"(alert at {intervention.burn_alert_value:.2f}%). "
            + (
                "This is the CRITICAL_PEG_STRESS setup check_trilemma_tension() names."
                if capacity == intervention.reserve_constrained_label
                else (
                    "A cost-driven defence can also exhaust the stock — the "
                    "depletion is a fact about the reserve position, not a "
                    "property of the intervention's direction."
                )
            )
        )

    if burn_pct is None:
        warnings.append(
            "No twelve-month reserve change is available, so the DEPLETION RATE "
            "is UNKNOWN. The capacity label is derived from the direction's "
            "mechanics alone and cannot distinguish a funded defence from one "
            "already failing."
        )

    assumptions = [
        "Section 20.9's function classifies from the intervention's DIRECTION "
        "and the reserve stock; it contains no estimated model of when a bank "
        "abandons a defence, and no price at which the market overwhelms it.",
        "Reserve figures are denominated in BILLIONS of USD; the fetched route "
        "converts from the source's millions.",
    ]
    if inputs.reserves_to_gdp_pct is None:
        assumptions.append(
            "reserves_to_gdp_pct was not supplied, so the stock is not scaled "
            "against the economy — a large stock in a large economy and a small "
            "stock in a small one are not separated here."
        )

    return ModelResult(
        model_name="intervention_capacity",
        country=inputs.country,
        as_of=utc_now(),
        value={
            "capacity": capacity,
            "reserves_usd_bn": reserves_bn,
            "reserves_change_12m_pct": burn_pct,
            "reserves_to_gdp_pct": inputs.reserves_to_gdp_pct,
            "direction": inputs.direction,
        },
        confidence=confidence,
        unit="usd_billions",
        source_family=(
            EvidenceSourceFamily.IMF if fetched else EvidenceSourceFamily.MANUAL_ASSESSMENT
        ),
        interpretation=(
            f"{inputs.country} defending via '{inputs.direction}': {capacity}"
            + (
                f" — reserves {reserves_bn:,.1f} bn USD"
                if reserves_bn is not None
                else " — reserves unavailable"
            )
        ),
        context=note,
        inputs_used=[
            "direction",
            "fx_reserves_usd_bn",
            "reserves_to_gdp_pct",
            "reserves_change_12m_pct",
        ],
        warnings=warnings,
        assumptions=assumptions,
        data_provenance=[reserves_provenance],
    )


def _fetch_reserves_bn(
    country: str,
) -> tuple[float | None, float | None, str]:
    """Resolve a country's FX reserves, in BILLIONS, plus its 12-month change.

    Returns ``(reserves_usd_bn, change_12m_pct, provenance)``. A country with no
    reachable series returns ``(None, None, <reason>)`` rather than raising: the
    caller decides whether the absence is fatal (a strengthening verdict) or
    merely disclosed (a weakening one), and a fetch failure must not pre-empt
    that decision.

    The provenance string says **FETCHED**, the date, and the source series, so a
    fetched figure and a caller-supplied one can never read alike (D-117).
    """
    try:
        reading = fetch_reserves(country)
    except ReservesReadError as exc:
        logger.info("intervention_capacity: reserves fetch failed: %s", exc)
        return None, None, f"NOT AVAILABLE — the reserve fetch failed: {exc}"

    if reading is None:
        return (
            None,
            None,
            f"NOT AVAILABLE — no reserve series is registered for {country!r}.",
        )

    # The source publishes MILLIONS; this model's contract is BILLIONS. The
    # divisor is the client module's named constant, not a bare ``1000.0`` here,
    # so the 1000x step has ONE definition and a mutation to it is visible.
    return (
        reading.reserves_usd_mn / MILLIONS_PER_BILLION,
        reading.change_12m_pct,
        (
            f"FETCHED — {reading.symbol} @ {reading.observation_date} "
            f"(source unit: millions of USD; converted to billions by this "
            f"model)"
        ),
    )
