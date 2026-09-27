"""Module 10 — Commodities: the oil balance signal (Section 6.8).

Section 6.8 (``AGENTS.md:1059``) gives ``oil_balance_signal`` a full reference
body — the **third D-096 exception** where the authority supplies the
implementation, so this is an UPGRADE that supersedes nothing. It is the
``cip_check`` / ``intervention_capacity`` / ``em_vulnerability_checklist``
answer: **a new capability**. Module 10 had no function at all; this is its
first, and it exists to feed the inflation/growth **transmission channel**
(Module 10 → Module 5/7), never to express a trade.

What the function is, and what it is NOT
----------------------------------------
The reference body is one line of arithmetic —

    tightness = -inputs.inventory_change_weekly   # draw = tightening

— wrapped in a ``ModelResult`` whose ``warnings`` say, in the specification's
own words, *"Do NOT use this as a standalone trade signal — commodities out of
production scope."* That warning is the function's entire reason for existing:
Section 6.8 scopes commodities **out of tradeable production logic**, matching
the production universe ("FX, rates, equity indices only"), and Section 21.3's
Q15 marks this a structurally enforced *"no direct trade"* domain. So the model
computes a **transmission input** — a signed oil-tightness reading a downstream
inflation model may consult — and it publishes that scoping decision in its own
``warnings`` so no consumer can mistake it for a signal.

Three corrections to the reference body
---------------------------------------
**1. The bare ``confidence=0.4`` is replaced (Section 22.8).** Section 22.8
forbids a confidence literal; the published confidence is
``compute_confidence(...) x oil_balance.reliability_cap``, the D-118/D-119
**product** shape. The cap states what the METHOD is worth; the computed half
states what THIS run's inputs are worth. They are multiplied, not ``min()``-ed,
so each half stays load-bearing — see the block comment at the multiplication.

**2. The bare ``round(tightness, 2)`` becomes a config-declared precision.**
The reference rounds to two decimals with the ``2`` inline. Rounding to a fixed
number of decimals *is* a claim about the data's resolution, and a reader should
be able to find it: ``oil_balance.value_decimals`` declares it, and the
disclosure (the deviation is in **thousand barrels**, so two decimals implies
10-barrel resolution) is in the leaf's note.

**3. ``inputs_used`` names BOTH declared inputs.** The reference lists only
``inventory_change_weekly`` even though ``opec_spare_capacity_proxy`` is a
declared field of its input model. A field that is declared but never named as
used is the D-037 shape — the reader cannot tell whether it was consumed. Here
both are named, and the spare-capacity value is carried in the output so its
role is visible (see ``value["opec_spare_capacity_mbd"]``).

⚠️ **``opec_spare_capacity_proxy`` IS NOT CALLED A "PROXY" HERE, ON PURPOSE.**
Section 6.8 names the field ``..._proxy`` and its comment says "informational
only". Measured 2026-09-29, the EIA Short-Term Energy Outlook publishes the
**actual** series — ``COPS_OPEC``, *"OPEC Total Spare Crude Oil Production
Capacity"* in million barrels per day — so "proxy" under-claims: this is the
real quantity, not a stand-in. The field keeps the specification's name (the
input contract is Section 6.8's), but the docstring and the output label it as
the measured series it is.

The two inputs, and why neither is BLOCKED
------------------------------------------
Section 6.8 names no source for either input, so under Section 21.1's default
rule (*"any input not listed above is BLOCKED by default"*) both would read as
BLOCKED. Measured 2026-09-29, both are **LIVE** through this installation's
OpenBB ``commodity`` routes — the **fifth FALSE BLOCK** this repository has
caught (D-043's class), after ``ppp_implied_rate``, ``fx_reserves_usd_bn`` and
the two EM-vulnerability legs. The wiring, the symbols and the vintage trap are
documented in ``data_layer/commodities_client.py``; this model fetches through
it and **refuses** rather than publishing a signal from a leg it could not read.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.data_layer.commodities_client import (
    CommodityReadError,
    fetch_crude_inventories,
    fetch_opec_spare_capacity,
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
    "OilBalanceInputs",
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
