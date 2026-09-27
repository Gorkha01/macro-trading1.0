"""Module 10 — Commodities: the oil balance signal and the gold driver (Section 6.8).

Section 6.8 (``AGENTS.md:1059``) gives ``oil_balance_signal`` a full reference
body — the **third D-096 exception** where the authority supplies the
implementation, so this is an UPGRADE that supersedes nothing. It is the
``cip_check`` / ``intervention_capacity`` / ``em_vulnerability_checklist``
answer: **a new capability**. Module 10 had no function at all; this is its
first, and it exists to feed the inflation/growth **transmission channel**
(Module 10 → Module 5/7), never to express a trade.

The module's second household is **Appendix D's gold three-layer framework**
(``gold_driver_attribution``, added at D-121), the **fourth D-096 exception** —
Appendix D (``AGENTS.md:3046``) supplies a full body for it under the heading
*"Module 10 — Gold Three-Layer Framework (taught in depth, never coded)"*.
Appendix D lands in this module rather than a new one because Appendix D's own
code comment names the file (``# src/macro_engine/models/commodities.py
(addition)``) and because Section 6.8 is Module 10's home; the two functions
share a production-scope warning and a provider family, and neither is a trade
signal.

What the functions are, and what they are NOT
---------------------------------------------
Both compute an **informational** reading that publishes the specification's own
scoping decision — *"Do NOT use this as a standalone trade signal — commodities
out of production scope"* (Section 6.8) and *"INFORMATIONAL ONLY — no commodity
positions in this system's production universe"* (Appendix D). Section 21.3's
Q15 marks commodities a structurally enforced *"no direct trade"* domain, so
each function's ``warnings`` carries that decision rather than leaving a consumer
to infer it, and neither ever populates ``trade_idea.instrument``.

Three corrections to the reference bodies
-----------------------------------------
**1. Every bare ``confidence`` literal is replaced (Section 22.8).** Section 6.8
ships ``confidence=0.4`` and Appendix D ships ``confidence=0.35``; both are
refused. Each function publishes ``compute_confidence(...) x <its own cap>``, the
D-118/D-119 **product** shape, so each half stays load-bearing — see the block
comments at the two multiplications.

**2. Every bare ``round(...)`` becomes a config-declared precision.** Rounding to
a fixed number of decimals *is* a claim about the data's resolution, and a reader
should be able to find it.

**3. ``inputs_used`` names EVERY declared input.** A field that is declared but
never named as used is the D-037 shape — the reader cannot tell whether it was
consumed. Both functions name all of theirs, and carry the values in the output
so each input's role is visible.

⚠️ **A NOTE ON APPENDIX D'S ``central_bank_net_purchases_trend``.** It is a
**measured, CONFIRMED block** — the second in this repository, after
``usd_denominated_debt_share`` (D-119) — and its block is subtler than "no such
series": the World Bank **publishes ``FI.RES.GOLD.CD`` in its indicator
catalogue, but the data route refuses the id** (message id 175, "not found. It
may have been deleted or archived"), so it serves no observations. "Present in
the catalogue" and "serves data" are different claims.
See ``data_layer/commodities_client.py`` for the probe. The leg is published as
MANUAL with a discriminating disclosure.

The two inputs of ``oil_balance_signal``, and why neither is BLOCKED
-------------------------------------------------------------------
Section 6.8 names no source for either input, so under Section 21.1's default
rule (*"any input not listed above is BLOCKED by default"*) both would read as
BLOCKED. Measured 2026-09-29, both are **LIVE** — the **fifth FALSE BLOCK** this
repository has caught (D-043's class). The wiring, the symbols and the vintage
trap are documented in ``data_layer/commodities_client.py``; this model fetches
through it and **refuses** rather than publishing a signal from a leg it could
not read. The **sixth** false-block case is the pair of live gold legs in the
same client — measured 2026-09-27.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.data_layer.commodities_client import (
    CommodityReadError,
    fetch_crude_inventories,
    fetch_opec_spare_capacity,
    fetch_real_yield,
    fetch_vix_level,
    real_yield_change_bp,
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
    "GoldDriverInputs",
    "OilBalanceInputs",
    "gold_driver_attribution",
    "oil_balance_signal",
]


class OilBalanceInputs(BaseModel):
    """The oil-market inputs Section 6.8 declares, both optionally fetched.

    Section 6.8 declares two REQUIRED floats:

    * ``inventory_change_weekly`` — *"barrels, +/- vs 5yr seasonal avg"*, i.e.
      the crude-stock LEVEL **minus** the mean level for the same week over the
      prior five years. It is a DEVIATION and is signed: positive = a build
      (more stock than the seasonal norm), negative = a draw.
    * ``opec_spare_capacity_proxy`` — *"million barrels per day"*, the EIA
      ``COPS_OPEC`` total spare-capacity series (see the module docstring for
      why "proxy" under-claims).

    Both become **optional** (``None`` = fetch it), matching
    ``EMVulnerabilityInputs`` and ``InterventionInputs``: a caller that has a
    value may supply it, and a caller that does not lets the model fetch it. The
    two are distinguishable in the output because a supplied value is disclosed
    as caller-supplied — the discipline D-117/D-118/D-119 all apply, because *a
    fabricated input must never read like a measured one.*
    """

    model_config = ConfigDict(extra="forbid")

    country: str = Field(
        default="us",
        description='ISO-3166 alpha-2 lowercase. "us" — oil balance is a US stock series.',
    )
    inventory_change_weekly: float | None = Field(
        default=None,
        description=(
            "Crude-oil stock deviation from the 5-year seasonal average, in "
            "THOUSAND BARRELS, signed (positive = build vs seasonal norm, "
            "negative = draw). None (the default) fetches the EIA WCESTUS1 "
            "weekly series and computes the deviation from its own history."
        ),
    )
    opec_spare_capacity_proxy: float | None = Field(
        default=None,
        description=(
            "OPEC total spare crude-oil production capacity, in MILLION BARRELS "
            "PER DAY. None (the default) fetches the EIA COPS_OPEC series and "
            "clips it to observations at or before the as-of date."
        ),
    )

    @model_validator(mode="after")
    def _validate_finite_and_signed(self) -> OilBalanceInputs:
        """Refuse a non-finite value on either leg.

        Both inputs are checked for NON-FINITENESS only, and neither is clamped:
        a negative inventory deviation (a draw) and a near-zero spare capacity
        are both legitimate readings. But a ``nan`` silently fails every ``>``
        and ``<`` comparison, so a nan deviation would publish a *loosening*
        verdict for an oil balance that is unknown (the D-078 class — a null
        that travels as a value).

        The inventory SIGN is deliberately not constrained to any range: the
        whole point of the deviation is that it is signed. The spare capacity is
        NOT constrained to non-negative either, because a provider that reports
        a small negative (a measurement artefact near zero, or a genuine
        over-supply beyond nameplate) should be disclosed rather than silently
        flipped — the model reports what the series says and warns.
        """
        for name, value in (
            ("inventory_change_weekly", self.inventory_change_weekly),
            ("opec_spare_capacity_proxy", self.opec_spare_capacity_proxy),
        ):
            if value is not None and (value != value or abs(value) == float("inf")):
                raise ValueError(
                    f"{name} must be finite when supplied; got {value!r}. A nan "
                    f"silently fails every comparison, so an unknown value would "
                    f"be reported as a definite reading (D-078's class)."
                )
        return self


def oil_balance_signal(inputs: OilBalanceInputs) -> ModelResult:
    """How tight the oil market is — a TRANSMISSION input, never a trade signal.

    ``tightness = -inventory_deviation`` (Section 6.8's own arithmetic): a stock
    **draw** (negative deviation) is a positive tightness, a **build** is a
    negative tightness. The sign convention is the reference implementation's and
    is stated on the output's ``direction`` too, so a consumer can act on it
    without re-deriving it from the number's sign.

    ``value`` is a dict rather than a bare float, so the reading, the
    week-over-week change it came from, and the spare-capacity figure all travel
    together — a consumer reasoning about the inflation channel wants to see
    WHICH inputs produced the tightness, not only the scalar.

    Raises ``ValueError`` when a leg cannot be fetched and the caller supplied no
    value. Deliberately: the function's single output gates a *downstream*
    inflation assessment, so a tightness computed from whichever leg happened to
    be reachable would be indistinguishable from a complete one. The refusal
    names which leg is missing and points at the client for the reason.
    """
    settings = get_settings()
    oil = settings.oil_balance

    provenance: list[str] = []
    fetched_legs = 0

    deviation: float | None = inputs.inventory_change_weekly
    inventory_disclosure: str
    if deviation is None:
        deviation, inventory_disclosure = _fetch_inventory_deviation()
        if deviation is not None:
            fetched_legs += 1
    else:
        inventory_disclosure = (
            "inventory_change_weekly SUPPLIED BY THE CALLER — unit is THOUSAND "
            "BARRELS as a signed deviation from the 5-year seasonal average, as "
            "declared by this model's input contract; the vintage is unknown."
        )
    provenance.append(inventory_disclosure)

    spare: float | None = inputs.opec_spare_capacity_proxy
    spare_disclosure: str
    if spare is None:
        spare, spare_disclosure = _fetch_spare_capacity()
        if spare is not None:
            fetched_legs += 1
    else:
        spare_disclosure = (
            "opec_spare_capacity_proxy SUPPLIED BY THE CALLER — unit is MILLION "
            "BARRELS PER DAY; no fetch was performed and the vintage is unknown."
        )
    provenance.append(spare_disclosure)

    missing: list[str] = []
    if deviation is None:
        missing.append("inventory_change_weekly")
    if spare is None:
        missing.append("opec_spare_capacity_proxy")
    if missing:
        raise ValueError(
            f"oil_balance_signal cannot compute the transmitted tightness: no "
            f"value is available for {', '.join(missing)} and none was supplied. "
            f"A tightness from one leg is not a weaker version of the signal — it "
            f"is a different claim, and this reading feeds a downstream inflation "
            f"assessment. Supply the missing value(s) explicitly to compute what "
            f"is reachable, or investigate the fetch (see commodities_client)."
        )

    # The two assertions narrow the optionals for the type checker; the `missing`
    # guard above has already refused every path on which either is None, so
    # they cannot fire. Stated rather than `cast` so a future edit that moves the
    # guard is caught here rather than silently comparing against None.
    assert deviation is not None
    assert spare is not None

    tightness = -deviation  # draw = tightening (Section 6.8)
    decimals = oil.value_decimals
    rounded_tightness = round(tightness, decimals)

    # --- confidence: two producers, both load-bearing (D-118/D-119 rule) ------
    # ⚠️ MULTIPLICATIVE, NOT `min()`. The computed half is above the cap on every
    # path, so `min()` would publish the cap everywhere and make this whole
    # compute_confidence() branch dead code — a computation that never changes an
    # output is scaffolding, not a model. Multiplying keeps each factor live: the
    # cap states what the METHOD is worth (a one-line sign flip on uncalibrated
    # EIA inputs), and the computed value states what THIS run's inputs are worth
    # relative to a perfect one, so a fetched pair beats a caller-typed pair in
    # the published number instead of the distinction being discarded.
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=fetched_legs < 2,
            is_heuristic_not_calibrated=not oil.reliability_cap_is_calibrated,
            source_independence_count=fetched_legs,
            depends_on_unobservable=False,
        )
    )
    confidence = computed * oil.reliability_value

    warnings: list[str] = [
        "Do NOT use this as a standalone trade signal — commodities are OUT of "
        "the production universe by design (Section 6.8); this reading exists "
        "ONLY to feed the inflation/growth transmission channel (Module 10 → "
        "Module 5/7).",
    ]
    if spare is not None and spare < 0.0:
        warnings.append(
            f"OPEC spare capacity was reported as {spare} mb/d, which is negative "
            f"— a measurement artefact or a genuine over-supply beyond nameplate. "
            f"Reported as the series has it; do not clamp."
        )
    if spare is not None and spare >= oil.tight_spare_threshold_value:
        warnings.append(
            f"OPEC spare capacity ({spare} mb/d) is at or above the "
            f"{oil.tight_spare_threshold_value} mb/d threshold, so the market has "
            f"buffer even if the inventory deviation reads tight — the two "
            f"inputs can disagree and the disagreement is information."
        )

    assumptions = [
        "Section 6.8's inventory input is a DEVIATION from the 5-year seasonal "
        "average, not a raw level and not a week-over-week change; the client "
        "computes it from the WCESTUS1 weekly history and this model consumes it.",
        "The spare-capacity reading is the latest OBSERVATION at or before the "
        "as-of date; the STEO's forward-dated projections are discarded, never "
        "adopted (D-116's vintage trap).",
        "The two inputs are EIA series published on weekly (inventory) and "
        "monthly (spare capacity) schedules, so their observation dates differ "
        "and the pair is a disclosed vintage, not a synchronised observation.",
    ]

    return ModelResult(
        model_name="oil_balance_signal",
        country=inputs.country,
        as_of=utc_now(),
        value={
            "tightness": rounded_tightness,
            "inventory_seasonal_deviation_thousand_barrels": round(deviation, decimals),
            "opec_spare_capacity_mbd": spare,
        },
        confidence=confidence,
        unit="thousand_barrels_seasonal_deviation",
        direction="tightening" if tightness > 0 else "loosening",
        source_family=(
            EvidenceSourceFamily.MARKET_COMMODITY
            if fetched_legs > 0
            else EvidenceSourceFamily.MANUAL_ASSESSMENT
        ),
        interpretation=(
            f"Oil market {'tightening' if tightness > 0 else 'loosening'} "
            f"(informational): crude stocks {deviation:+,.0f} thousand barrels vs "
            f"the 5-year seasonal average; OPEC spare capacity {spare} mb/d"
        ),
        context=(
            "Feeds inflation/growth transmission only — this system does not "
            "express commodity views directly (Module 10, Section 6.8)"
        ),
        inputs_used=["inventory_change_weekly", "opec_spare_capacity_proxy"],
        warnings=warnings,
        assumptions=assumptions,
        data_provenance=provenance,
    )


def _fetch_inventory_deviation() -> tuple[float | None, str]:
    """Resolve the seasonal inventory deviation, or ``None`` on failure.

    Returns ``(value, provenance)``. A fetch failure returns ``None`` rather
    than raising so the CALLER decides whether the absence is fatal — the same
    split ``intervention_capacity`` (D-118) and ``em_vulnerability_checklist``
    (D-119) use. The provenance names the level, the deviation and the baseline
    depth, because a seasonal deviation is a statement about the observation
    *and* the five years behind it.
    """
    try:
        reading = fetch_crude_inventories(as_of=utc_now().date())
    except CommodityReadError as exc:
        logger.info("oil_balance_signal: inventory fetch failed: %s", exc)
        return None, f"NOT AVAILABLE — the crude-inventory fetch failed: {exc}"

    deviation = reading.seasonal_deviation_thousand_barrels
    if deviation is None:
        return None, (
            f"NOT AVAILABLE — {reading.symbol} spans {reading.observation_count} "
            f"observations but none matched the latest week-of-year in a prior "
            f"year, so no 5-year seasonal baseline could be formed."
        )
    return deviation, (
        f"FETCHED — EIA {reading.symbol} @ {reading.observation_date}: level "
        f"{reading.level_thousand_barrels:,.0f} {reading.source_unit}, week change "
        f"{reading.change_weekly_thousand_barrels:+,.0f}, seasonal deviation "
        f"{deviation:+,.0f} vs the same week in {reading.seasonal_baseline_years} "
        f"prior year(s)"
    )


def _fetch_spare_capacity() -> tuple[float | None, str]:
    """Resolve OPEC spare capacity, or ``None`` on failure.

    Returns ``(value, provenance)``. The provenance names the observation date,
    the unit, and how many future-dated projection rows were discarded — the
    last because a reader must be able to see that the series carries forecasts
    and that this module did not adopt one as a measurement.
    """
    try:
        reading = fetch_opec_spare_capacity(as_of=utc_now().date())
    except CommodityReadError as exc:
        logger.info("oil_balance_signal: spare-capacity fetch failed: %s", exc)
        return None, f"NOT AVAILABLE — the OPEC spare-capacity fetch failed: {exc}"
    return reading.spare_capacity_mbd, (
        f"FETCHED — EIA {reading.symbol} @ {reading.observation_date}: "
        f"{reading.spare_capacity_mbd} {reading.source_unit}; "
        f"{reading.projection_rows_dropped} future-dated STEO projection row(s) "
        f"were discarded (an observation is used, never a forecast)"
    )


# =============================================================================
# Module 10.2 — Gold Three-Layer Framework (Section 6.8's Module 10, Appendix D)
# =============================================================================


class GoldDriverInputs(BaseModel):
    """The three gold drivers Appendix D declares, each optionally fetched.

    Appendix D (``AGENTS.md:3046``, *"Module 10 — Gold Three-Layer Framework
    (taught in depth, never coded)"*) declares one input per layer of the
    framework:

    * ``real_yield_change_bp`` — *"10yr TIPS yield change — PRIMARY driver"*, in
      **basis points**, signed (a RISE in real yields is a headwind for gold, so
      a positive change pushes gold DOWN through the opportunity-cost channel).
    * ``central_bank_net_purchases_trend`` — *"rising" | "flat" | "falling"*, the
      CB-reserve-diversification layer. A DISCRETE label, not a number.
    * ``crisis_indicator`` — a boolean for *"VIX spike / credit blowout /
      confidence event"*, the acute layer.

    All three become **optional** (``None`` = resolve it), matching
    ``OilBalanceInputs`` and its predecessors: a caller with a value supplies it,
    a caller without one lets the model resolve it. The two paths are
    distinguishable in the output because a supplied value is disclosed as
    caller-supplied — the D-117/D-118/D-119/D-120 discipline, because *a
    fabricated input must never read like a measured one.*

    ``real_yield_change_bp`` and ``crisis_indicator`` are LIVE (measured
    2026-09-27, ``DFII10`` and ``VIXCLS``). ``central_bank_net_purchases_trend``
    is a **measured, CONFIRMED block** — see ``data_layer/commodities_client.py``
    for the probe. So this input model is the first in the repository whose
    *default* for one field is "resolve it and you will probably get nothing".
    """

    model_config = ConfigDict(extra="forbid")

    country: str = Field(
        default="global",
        description=(
            'ISO-3166 alpha-2 lowercase, or "global". Appendix D uses "global" '
            "because gold is a global reserve asset, not a national series."
        ),
    )
    real_yield_change_bp: float | None = Field(
        default=None,
        description=(
            "Change in the 10-Year TIPS real yield, in BASIS POINTS, signed. "
            "None (the default) fetches FRED DFII10 and differences the two most "
            "recent observations. Section 6.8's oil model reports a LEVEL; this "
            "is a CHANGE, per Appendix D's own field name."
        ),
    )
    central_bank_net_purchases_trend: str | None = Field(
        default=None,
        description=(
            'One of "rising" | "flat" | "falling". None (the default) attempts '
            "no fetch because NO FREE LIVE SOURCE EXISTS (measured, see the "
            "client): the World Bank lists FI.RES.GOLD.CD in its catalogue but "
            "its data route refuses the id, so it returns no observations. A "
            "caller must supply this label, and its provenance is "
            "disclosed as caller-supplied."
        ),
    )
    crisis_indicator: bool | None = Field(
        default=None,
        description=(
            "True on a VIX spike / credit blowout / confidence event. None (the "
            "default) fetches FRED VIXCLS and compares the level to the "
            "config-declared crisis threshold."
        ),
    )

    @model_validator(mode="after")
    def _validate_finite_and_trend(self) -> GoldDriverInputs:
        """Refuse a non-finite real-yield change or a trend outside the vocabulary.

        The real-yield change is checked for NON-FINITENESS only, and is not
        clamped: a rise and a fall are both legitimate, and a large magnitude is
        the most interesting reading. But a ``nan`` silently fails every ``>``
        and ``<`` comparison, so a nan change would make the primary layer fail
        to fire for a gold move that is unknown (the D-078 class).

        The trend is checked against the SPECIFICATION'S OWN VOCABULARY
        (``"rising"``/``"flat"``/``"falling"``), because Appendix D matches on
        the exact string ``== "rising"``: a typo (``"raise"``) would silently
        fall through to "this layer is not active", which is a *different claim*
        from "the caller meant rising". Refusing is the only way a typo becomes
        visible — the same reasoning ``EMVulnerabilityInputs`` uses for its
        enumerated legs. The vocabulary is taken from ``AGENTS.md`` rather than
        invented, and the error names the permitted values.
        """
        if self.real_yield_change_bp is not None:
            value = self.real_yield_change_bp
            if value != value or abs(value) == float("inf"):
                raise ValueError(
                    f"real_yield_change_bp must be finite when supplied; got "
                    f"{value!r}. A nan silently fails every comparison, so an "
                    f"unknown change would report 'no real-yield layer' — a "
                    f"different claim from 'the layer is inert' (D-078's class)."
                )
        if self.central_bank_net_purchases_trend is not None:
            permitted = ("rising", "flat", "falling")
            if self.central_bank_net_purchases_trend not in permitted:
                raise ValueError(
                    f"central_bank_net_purchases_trend must be one of "
                    f"{permitted}; got "
                    f"{self.central_bank_net_purchases_trend!r}. Appendix D "
                    f"matches the exact string, so any other value would be "
                    f"silently read as 'this layer is inactive' rather than as a "
                    f"typo."
                )
        return self


def gold_driver_attribution(inputs: GoldDriverInputs) -> ModelResult:
    """Which layer of the three-layer framework is driving gold — never a trade.

    Appendix D's central correction, in its own words: *"Gold is a REAL-YIELD and
    CONFIDENCE hedge, NOT a simple inflation hedge — the single most important
    correction this module teaches."* The function therefore **attributes** the
    move to a layer rather than predicting a price, because each layer implies a
    different **DURABILITY**:

    * ``real_yield`` — mechanical, **reverses** if real yields reverse
    * ``cb_diversification`` — structural, slow, **durable**
    * ``crisis_confidence`` — acute, sharp, **often reverses** when the acute
      phase passes

    The layers are ordered in the output by **the specification's own decision
    order** — ``real_yield`` first, then ``cb_diversification``, then
    ``crisis_confidence`` — and ``dominant_layer`` is the first ACTIVE one.
    That ordering is a claim worth stating: Appendix D appends in that sequence
    and takes ``layers[0]``, so the tie-break is "the primary channel wins when
    several fire", not "the most recent one wins".

    ``value`` is a dict (``dominant_layer`` / ``active_layers``) rather than the
    bare string the reference returns, so a consumer can see WHICH layers fired
    and not only the winner — see the ``value`` construction for why.

    Raises ``ValueError`` only when **``real_yield_change_bp`` cannot be resolved
    and none was supplied**. The two other layers degrade differently on purpose:
    an unresolvable CB trend simply drops that layer (it is a discretionary
    judgement with no source, so its absence is the normal case), and the crisis
    leg is a boolean that defaults to "no crisis observed" only when a fetch
    succeeds and reads below threshold — a fetch FAILURE raises, because
    "VIX could not be read" and "VIX is calm" are different claims and the acute
    layer is exactly the one a reader must not see fabricated.
    """
    settings = get_settings()
    gold = settings.gold_driver

    provenance: list[str] = []
    fetched_legs = 0

    # --- Layer 1: real yield (PRIMARY) --------------------------------------
    change_bp: float | None = inputs.real_yield_change_bp
    if change_bp is None:
        change_bp, yield_disclosure = _resolve_real_yield_change()
        if change_bp is not None:
            fetched_legs += 1
    else:
        yield_disclosure = (
            "real_yield_change_bp SUPPLIED BY THE CALLER — unit is BASIS POINTS "
            "as a signed change in the 10-Year TIPS real yield, as declared by "
            "this model's input contract; no fetch was performed and the "
            "vintage is unknown."
        )
    provenance.append(yield_disclosure)

    if change_bp is None:
        raise ValueError(
            "gold_driver_attribution cannot resolve the PRIMARY layer: no "
            "real_yield_change_bp is available and none was supplied. The "
            "real-yield channel is Appendix D's primary driver, so a reading "
            "taken with it missing is not a weaker attribution — it is a "
            "different claim, and it would silently report whichever secondary "
            "layer happened to fire. Supply the change explicitly to attribute "
            "what is reachable, or investigate the fetch (see commodities_client)."
        )

    # --- Layer 2: central-bank diversification (MANUAL, measured block) -----
    trend: str | None = inputs.central_bank_net_purchases_trend
    if trend is None:
        cb_disclosure = (
            "central_bank_net_purchases_trend NOT RESOLVED — no free live source "
            "exists (measured 2026-09-27: the World Bank publishes FI.RES.GOLD.CD "
            "in its indicator catalogue but the DATA route refuses it with "
            "message id 175 'not found. It may have been deleted or archived', so "
            "it carries no observations; FI.RES.TOTL.GD.ZS is not a valid "
            "indicator id at all). "
            "The CB layer is therefore treated as INACTIVE for this reading; it "
            "is a discretionary judgement and its absence is disclosed rather "
            "than guessed."
        )
    else:
        cb_disclosure = (
            f"central_bank_net_purchases_trend SUPPLIED BY THE CALLER as "
            f"{trend!r} — this is a DISCRETIONARY label with no source, so its "
            f"provenance is a judgement, not a measurement, and it must not be "
            f"read as though it were fetched."
        )
    provenance.append(cb_disclosure)

    # --- Layer 3: crisis / confidence (VIX) ---------------------------------
    crisis: bool | None = inputs.crisis_indicator
    if crisis is None:
        crisis, crisis_disclosure = _resolve_crisis_indicator()
        if crisis is not None:
            fetched_legs += 1
    else:
        crisis_disclosure = (
            "crisis_indicator SUPPLIED BY THE CALLER — no fetch was performed; "
            "the caller asserts whether an acute confidence event is in force."
        )
    provenance.append(crisis_disclosure)

    if crisis is None:
        raise ValueError(
            "gold_driver_attribution cannot resolve the CRISIS layer: the VIX "
            "fetch failed and no crisis_indicator was supplied. 'VIX could not "
            "be read' and 'VIX is calm' are different claims, and the acute "
            "layer is the one a reader must never see fabricated. Supply the "
            "flag explicitly, or investigate the fetch."
        )

    layers = _active_layers(change_bp, trend, crisis, threshold_bp=gold.yield_change_threshold_bp)
    dominant = layers[0][0] if layers else "none_identified"

    # --- confidence: two producers, both load-bearing (D-118/D-119 rule) -----
    # ⚠️ MULTIPLICATIVE, NOT `min()`. The computed half prices THIS run's inputs
    # (how many legs were fetched, and — critically — how many INDEPENDENT
    # providers they came from); the cap states what the METHOD is worth
    # (a three-branch attribution over an uncalibrated threshold). Multiplying
    # keeps both live: `min()` would publish the cap on every path here and make
    # the computed half dead code, which is exactly the defect D-118 removed.
    #
    # ⚠️ THE INDEPENDENCE COUNT IS 1 WHEN BOTH FETCHED LEGS ARE LIVE, AND THAT IS
    #    THE POINT. DFII10 and VIXCLS are BOTH FRED series: two fetches, ONE
    #    provider. Reporting `fetched_legs` as the independence count would
    #    overstate the evidence — the same class of error as counting a signal
    #    twice — so the count is 1 for any fetched pair and 0 when nothing was
    #    fetched. The disclosure says so in words as well as in the number.
    independent_providers = 1 if fetched_legs > 0 else 0
    computed = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=fetched_legs < 2,
            is_heuristic_not_calibrated=not gold.reliability_cap_is_calibrated,
            source_independence_count=independent_providers,
            depends_on_unobservable=False,
        )
    )
    confidence = computed * gold.reliability_value

    warnings: list[str] = [
        "INFORMATIONAL ONLY — commodities are OUT of this system's production "
        "universe by design (Section 6.8); this attribution exists to explain a "
        "gold move, never to express a position in it.",
        "Appendix D's central correction: gold is a REAL-YIELD and CONFIDENCE "
        "hedge, NOT a simple inflation hedge. Read the dominant layer, not the "
        "price move, because the layer determines DURABILITY.",
    ]
    if abs(change_bp) > gold.yield_change_threshold_bp:
        warnings.append(
            f"The real-yield layer fired on a {change_bp:+.1f} bp change, above "
            f"the {gold.yield_change_threshold_bp} bp threshold. This layer is "
            f"MECHANICAL — it reverses if real yields reverse, so a gold move "
            f"attributed here is not durable on its own."
        )
    if trend == "rising":
        warnings.append(
            "The CB-diversification layer fired. This layer is STRUCTURAL and "
            "DURABLE (slow, geopolitically motivated), which is the opposite "
            "durability profile from the mechanical real-yield layer."
        )
    if crisis:
        warnings.append(
            "The crisis/confidence layer fired. This layer is ACUTE — sharp "
            "moves attributed here often REVERSE once the acute phase passes; "
            "do not extrapolate the move."
        )
    if not layers:
        warnings.append(
            "NO layer was identified: the real-yield change is inside the "
            "threshold, the CB trend is not 'rising', and no crisis is in force. "
            "'No layer identified' is a reading, not an error — but it means "
            "this framework does not explain the move, and a consumer should not "
            "read the empty attribution as 'gold is unattributed and therefore "
            "random'."
        )
    if trend is None:
        warnings.append(
            "The CB-diversification layer was NOT evaluated: no free live source "
            "for central-bank gold purchases exists (a MEASURED block), so the "
            "layer is inactive by data availability, NOT by evidence that CB "
            "buying is flat."
        )

    assumptions = [
        "Appendix D's real-yield input is a CHANGE in BASIS POINTS, not a level; "
        "the client differences the two most recent DFII10 observations and "
        "converts per-cent levels to bp by the named constant.",
        "The three layers are APPENDED IN THE SPECIFICATION'S ORDER and the "
        "dominant layer is the first active one — so when several fire, the "
        "primary (mechanical) channel is reported as dominant even though the "
        "structural layer may matter more to durability.",
        "The crisis layer is a THRESHOLD on the VIX LEVEL from config, not a "
        "compound credit-spread assessment; Appendix D names 'VIX spike / credit "
        "blowout / confidence event' and this build measures only the VIX leg.",
        "Both live legs are FRED series, so their source independence is ONE "
        "family — the confidence's source count is 1, not 2.",
    ]

    return ModelResult(
        model_name="gold_driver_attribution",
        country=inputs.country,
        as_of=utc_now(),
        value={
            "dominant_layer": dominant,
            "active_layers": [name for name, _ in layers],
            "real_yield_change_bp": round(change_bp, gold.value_decimals),
            "central_bank_net_purchases_trend": trend,
            "crisis_indicator": crisis,
        },
        confidence=confidence,
        unit="layer_attribution",
        direction=dominant,
        source_family=(
            EvidenceSourceFamily.MARKET_COMMODITY
            if fetched_legs > 0
            else EvidenceSourceFamily.MANUAL_ASSESSMENT
        ),
        interpretation=f"Gold move most likely driven by: {dominant}",
        context=(
            "Real yields primary; CB diversification structural; crisis demand "
            "acute. NOT an inflation hedge per se (Module 10.2, Appendix D)"
        ),
        inputs_used=[
            "real_yield_change_bp",
            "central_bank_net_purchases_trend",
            "crisis_indicator",
        ],
        warnings=warnings,
        assumptions=assumptions,
        data_provenance=provenance,
    )


def _active_layers(
    change_bp: float,
    trend: str | None,
    crisis: bool,
    *,
    threshold_bp: float,
) -> list[tuple[str, str]]:
    """The layers that fired, in the specification's order, with their durability.

    Extracted from :func:`gold_driver_attribution` so the three predicates are
    stated once and can be read without the surrounding plumbing. The ORDER is
    Appendix D's own append order and is load-bearing: the caller takes
    ``layers[0]`` as dominant, so this list's first element is the attribution.
    The threshold is a PARAMETER rather than a module constant so the only copy
    of it lives in config — a second literal here would be the D-118 dead-constant
    shape in reverse (a live constant shadowed by a hardcoded value).
    """
    layers: list[tuple[str, str]] = []
    if abs(change_bp) > threshold_bp:
        layers.append(
            (
                "real_yield",
                "primary — mechanical opportunity-cost channel, reverses with real yields",
            )
        )
    if trend == "rising":
        layers.append(
            (
                "cb_diversification",
                "structural — slow, durable, geopolitically motivated",
            )
        )
    if crisis:
        layers.append(
            (
                "crisis_confidence",
                "acute — sharp move, often reverses post-crisis",
            )
        )
    return layers


def _resolve_real_yield_change() -> tuple[float | None, str]:
    """Resolve the TIPS real-yield change in bp, or ``None`` on failure.

    Returns ``(value, provenance)``. A fetch failure or a series too short to
    difference both return ``None`` so the CALLER decides whether the absence is
    fatal — the same split ``oil_balance_signal`` and its predecessors use.
    """
    try:
        reading = fetch_real_yield(as_of=utc_now().date())
    except CommodityReadError as exc:
        logger.info("gold_driver_attribution: real-yield fetch failed: %s", exc)
        return None, f"NOT AVAILABLE — the real-yield fetch failed: {exc}"

    change = real_yield_change_bp(reading)
    if change is None:
        return None, (
            f"NOT AVAILABLE — {reading.symbol} returned {reading.observation_count} "
            f"observation(s) at or before the as-of date, which is fewer than the "
            f"two needed to form a CHANGE."
        )
    return change, (
        f"FETCHED — FRED {reading.symbol}: {reading.yield_percent} "
        f"{reading.source_unit} on {reading.observation_date}, prior "
        f"{reading.prior_yield_percent} on {reading.prior_observation_date} "
        f"=> change {change:+.1f} bp"
    )


def _resolve_crisis_indicator() -> tuple[bool | None, str]:
    """Resolve the crisis flag from the VIX level, or ``None`` on failure.

    Returns ``(value, provenance)``. The flag is ``level >= threshold``, with the
    threshold read from config so the number that turns a level into a boolean is
    discoverable. The provenance names the level AND the threshold, because
    "VIX 14.21 is below 30" is the whole content of the claim.
    """
    settings = get_settings()
    threshold = settings.gold_driver.crisis_vix_threshold_value
    try:
        reading = fetch_vix_level(as_of=utc_now().date())
    except CommodityReadError as exc:
        logger.info("gold_driver_attribution: VIX fetch failed: %s", exc)
        return None, f"NOT AVAILABLE — the VIX fetch failed: {exc}"

    fired = reading.level >= threshold
    return fired, (
        f"FETCHED — FRED {reading.symbol} @ {reading.observation_date}: level "
        f"{reading.level} {reading.source_unit} vs the config threshold "
        f"{threshold} => crisis_indicator={fired}"
    )
