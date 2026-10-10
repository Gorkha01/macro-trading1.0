"""Cross-country reasoning — layer 4 of the four-layer multi-country bar.

Why this is a module and not a branch in ``instrument_selection``
-----------------------------------------------------------------
Section 22.3 defines multi-country as **four** capabilities, and Section 22.3's
own four-layer bar (``docs/PHASE5_DEFERRED.md`` §2.4.1) puts the last one — cross-
country *reasoning* — above data, reaction functions and instruments. A
cross-country thesis is not "the US engine with a second country label"; it is a
statement about the **gap between two complete country systems**, and that gap
does not exist as a quantity until both systems and a bridge between them do.

``instrument_selection`` answers *which instrument*; this module answers *is
there a divergence worth expressing, and how big is it*. Keeping the two apart is
LAW 2 (one canonical implementation per quantity) — the divergence is computed
once, here, and the selector consumes the result rather than recomputing it.

The institutional structure this reproduces
-------------------------------------------
The canonical expression of a macro divergence view is a **duration-neutral
relative-value** trade — long the bond whose yield is expected to fall more (or
rise less), short the other, sized so a *parallel* move in global yields cancels
(``quantmemo``, "Cross-Country Rates Relative Value"; Section 22.3.1's own rule
table names it: *"Cross-country policy divergence → cross-market RV (e.g., long
US 10yr, short Bund)"*). Its payoff is linear in the **spread change**, not the
level:

    P&L = (spread change, bp) * DV01_per_bp          (DV01-neutral legs)

So the reasoning owed to the trader is the **sign and magnitude of the
divergence** and whether it is inside the noise band — *not* "US 10y is 4.3% and
Bunds are 2.4%", which compares two numbers on different bases.

Three measurable legs, and the two ways a spread is fake
---------------------------------------------------------
1. **Real-rate differential** (the primary quantity here) — ``(i_a - pi_a) -
   (i_b - pi_b)``. This is the institutional headline comparison: *"a 4% policy
   rate against 5% inflation is looser than a 1% rate against zero inflation, even
   though the nominal level is far higher."* Stance asymmetry lives here, so this
   is what the verdict reads.
2. **Nominal differential** — reported beside it, because it is what the RV
   trade prices, but it MIXES expected inflation and the real rate and so is not
   on its own a divergence measure.
3. **The FX bridge** — the two currencies must be reconciled before any
   cross-currency subtraction. This module does NOT convert amounts; it requires
   the caller to state whether the pair is same-currency and refuses a
   cross-currency differential that was not converted, because an unconverted
   cross-currency spread is the archetypal fake spread (the four-layer bar's
   layer-3 trap, and ``fx_conversion``'s own reason for existing).

The two ways a cross-country thesis is WRONG, both refused
----------------------------------------------------------
* **Comparing different bases.** Two legs on different tenors or horizons is the
  definition of a fake spread. Refused here (the shared horizon is a config leaf,
  ``cross_country.comparable_horizon_quarters``).
* **Ignoring the LTCM caveat.** Section 22.3.1 says a cross-market RV trade is
  *"correlation-dependent, LTCM tail-risk caveat applies"*: in stress the two
  legs break rank and a spread stops behaving like a spread. This module PUBLISHES
  a stress-degradation disclosure rather than implying the spread is riskless.

Why this is not a relabelled single-country rule
------------------------------------------------
A single-country rule produces *a rate for one country*. This produces a *signed,
comparability-checked differential between two countries' real stances plus a
stress disclosure* — a quantity that does not exist until two complete country
systems are present. That is the §22.3 un-fakeable test, met by construction.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "CrossCountryInputs",
    "cross_country_divergence",
]

#: The verdict vocabulary. A *string* value (not a bare float) because the
#: consumer branches on it and a reader must not have to re-derive the
#: threshold from a number.
NO_MEANINGFUL_DIVERGENCE = "NO_MEANINGFUL_DIVERGENCE"
MEANINGFUL_DIVERGENCE = "MEANINGFUL_DIVERGENCE"


class CrossCountryInputs(FiniteInputs):
    """Two complete country systems, on ONE comparable basis.

    Every field is a level the caller has ALREADY derived from that country's own
    snapshot (its own policy rate, its own inflation measure, its own 10-year
    yield). This class does not fetch and does not re-derive them — it is the
    join of two derivations, so a defect in either leg is that leg's to fix, not
    this module's to hide.

    Units, because bare floats cannot reveal a mismatch:

    * ``policy_rate_*`` / ``long_rate_*`` are in **PERCENT** (e.g. ``4.25``),
      the unit ``policy_rules`` publishes and ``fx_conversion``'s callers use.
    * ``inflation_*`` is **year-over-year PERCENT**, and must be the SAME measure
      on both sides (headline vs headline) or the subtraction is meaningless —
      the caller's obligation, stated here because the class cannot see which
      measure was passed.
    * ``tenor_a`` / ``tenor_b`` are desk strings (``"10y"``). They must be
      EQUAL: a 10y-vs-2y differential is a curve trade, not a country trade, and
      the whole point of layer 4 is that the two legs are the same instrument in
      different countries.
    * ``horizon_quarters_*`` is the maturity horizon, in QUARTERS, on which each
      country's rate was measured. They must be equal AND equal to the
      configured ``cross_country.comparable_horizon_quarters``.
    * ``currency_*`` are ISO-4217 codes. They may DIFFER (that is the normal
      cross-country case) but then ``same_currency_basis`` must be ``False`` and
      ``fx_converted`` must attest the legs were reconciled — see the validator.
    """

    model_config = ConfigDict(extra="forbid")

    country_a: str = Field(description="ISO-3166 alpha-2 code of leg A (lowercase).")
    country_b: str = Field(description="ISO-3166 alpha-2 code of leg B (lowercase).")
    policy_rate_a: float = Field(description="Leg A policy rate, PERCENT.")
    policy_rate_b: float = Field(description="Leg B policy rate, PERCENT.")
    inflation_a: float = Field(description="Leg A inflation YoY, PERCENT (same measure as B).")
    inflation_b: float = Field(description="Leg B inflation YoY, PERCENT (same measure as A).")
    long_rate_a: float = Field(description="Leg A 10-year yield, PERCENT.")
    long_rate_b: float = Field(description="Leg B 10-year yield, PERCENT.")
    tenor_a: str = Field(description='Leg A desk tenor, e.g. "10y". Must equal tenor_b.')
    tenor_b: str = Field(description="Leg B desk tenor. Must equal tenor_a.")
    horizon_quarters_a: float = Field(
        gt=0.0, description="Horizon on which leg A's rate was measured, in QUARTERS."
    )
    horizon_quarters_b: float = Field(
        gt=0.0, description="Horizon on which leg B's rate was measured, in QUARTERS."
    )
    currency_a: str = Field(description="Leg A currency, ISO-4217 alpha-3.")
    currency_b: str = Field(description="Leg B currency, ISO-4217 alpha-3.")
    same_currency_basis: bool = Field(
        description=(
            "True iff both legs are already quoted in the SAME currency. When the "
            "currencies differ this MUST be False, and ``fx_converted`` must attest "
            "the reconciliation."
        )
    )
    fx_converted: bool = Field(
        default=False,
        description=(
            "Attestation that a cross-currency pair was reconciled through the FX "
            "bridge before this record was built. Ignored (and must be False) when "
            "the pair is same-currency."
        ),
    )

    @model_validator(mode="after")
    def _the_two_legs_must_be_the_same_instrument_in_two_countries(self) -> CrossCountryInputs:
        """Refuse anything that is not one instrument measured in two countries.

        Three separate refusals, each naming its own reason, because a single
        "mismatched basis" message would leave a reader unable to tell a tenor
        error from a horizon error from a country error.
        """
        if self.country_a.strip().lower() == self.country_b.strip().lower():
            raise ValueError(
                f"a cross-country differential was asked for {self.country_a!r} "
                f"against itself. Comparing a country to itself is a no-op whose "
                f"difference is zero by construction — a caller error, not a "
                f"divergence."
            )
        if self.tenor_a.strip().lower() != self.tenor_b.strip().lower():
            raise ValueError(
                f"the two legs are on different tenors ({self.tenor_a!r} vs "
                f"{self.tenor_b!r}). A {self.tenor_a}-vs-{self.tenor_b} "
                f"differential is a CURVE trade (ThesisType.CURVE_SHAPE_GAP), not "
                f"a country trade. Layer 4 compares the SAME instrument in two "
                f"countries; a cross-tenor subtraction mixes two effects and is "
                f"the definition of a fake spread."
            )
        if self.horizon_quarters_a != self.horizon_quarters_b:
            raise ValueError(
                f"the two legs are on different horizons "
                f"({self.horizon_quarters_a} vs {self.horizon_quarters_b} "
                f"quarters). A differential across two horizons compares a "
                f"near-term rate with a forward one; both legs must be measured "
                f"on the SAME horizon or the subtraction is meaningless."
            )
        same_currency = self.currency_a.strip().upper() == self.currency_b.strip().upper()
        if same_currency and self.same_currency_basis is False:
            raise ValueError(
                f"both legs are {self.currency_a.upper()} but "
                f"same_currency_basis=False. When the currencies already match, a "
                f"cross-currency basis does not exist — the flag contradicts the "
                f"codes."
            )
        if not same_currency and self.same_currency_basis:
            raise ValueError(
                f"the legs are in different currencies ({self.currency_a.upper()} "
                f"vs {self.currency_b.upper()}) but same_currency_basis=True. A "
                f"cross-currency differential MUST be reconciled through the FX "
                f"bridge; claiming a same-currency basis would silently compare "
                f"two differently-denominated numbers (Section 22.3)."
            )
        if not same_currency and not self.fx_converted:
            raise ValueError(
                f"the {self.currency_a.upper()}/{self.currency_b.upper()} pair is "
                f"cross-currency but fx_converted is False. A cross-country spread "
                f"in two currencies is the archetypal FAKE spread: the numbers are "
                f"each real but the difference is not a quantity. Route both legs "
                f"through models/fx_conversion.py first and attest fx_converted."
            )
        if same_currency and self.fx_converted:
            raise ValueError(
                f"fx_converted=True for a same-currency pair "
                f"({self.currency_a.upper()}). There is no cross-currency basis to "
                f"convert; the attestation is meaningless and signals the caller "
                f"converted a no-op."
            )
        return self


def cross_country_divergence(inputs: CrossCountryInputs) -> ModelResult:
    """Measure the signed divergence between two complete country systems.

    The real-rate differential is the primary quantity::

        real_a = policy_rate_a - inflation_a        # percent
        real_b = policy_rate_b - inflation_b        # percent
        divergence_pp = real_a - real_b             # percentage points
        divergence_bp = divergence_pp * 100

    and the nominal differential is reported beside it because it is what the RV
    trade prices::

        nominal_bp = (long_rate_a - long_rate_b) * 100

    One ``config/settings.yaml`` leaf, ``cross_country.meaningful_divergence_bp``,
    decides whether the real-rate gap clears the noise band. The value is a
    **dict** (the divergence reading), not a bare float, because the consumer —
    ``select_instrument`` — needs the verdict *and* the magnitude *and* which leg
    is the long one, and re-deriving any of them from a single number would be a
    second implementation (LAW 2).

    Parameters
    ----------
    inputs:
        See :class:`CrossCountryInputs`. Already-validated: the legs are the same
        instrument on the same horizon, and a cross-currency pair has been
        reconciled.

    Returns
    -------
    ModelResult
        ``value`` is a ``dict`` with keys ``verdict`` (``MEANINGFUL_DIVERGENCE``
        or ``NO_MEANINGFUL_DIVERGENCE``), ``divergence_bp`` (the real-rate
        differential, signed), ``nominal_spread_bp``, ``real_rate_a``,
        ``real_rate_b``, ``long_leg_country`` (the higher-real-rate country — the
        RV trade goes LONG its bonds), ``short_leg_country``, and
        ``threshold_bp``. The sign convention is stated in ``interpretation``:
        a POSITIVE ``divergence_bp`` means country A's real stance is tighter
        than country B's.
    """
    settings = get_settings().cross_country
    threshold_bp = settings.meaningful_divergence

    # The configured shared horizon is the ONE horizon both legs must use. The
    # input validator already forced the two legs to agree with EACH OTHER; this
    # check forces that agreement to be the CONFIGURED one, so a pair measured on
    # a self-consistent but wrong horizon (e.g. both on 8 quarters) is refused
    # rather than passing.
    configured_horizon = settings.comparable_horizon
    if inputs.horizon_quarters_a != configured_horizon:
        raise ValueError(
            f"the legs are measured on a {inputs.horizon_quarters_a}-quarter "
            f"horizon but cross_country.comparable_horizon_quarters is "
            f"{configured_horizon}. Both legs agreed with each other, which is "
            f"necessary but not sufficient — they must be on the CONFIGURED "
            f"horizon, or two well-matched legs can still be compared on a basis "
            f"the config does not sanction."
        )

    real_a = inputs.policy_rate_a - inputs.inflation_a
    real_b = inputs.policy_rate_b - inputs.inflation_b
    divergence_pp = real_a - real_b
    divergence_bp = divergence_pp * 100.0
    nominal_bp = (inputs.long_rate_a - inputs.long_rate_b) * 100.0

    meaningful = abs(divergence_bp) >= threshold_bp
    verdict = MEANINGFUL_DIVERGENCE if meaningful else NO_MEANINGFUL_DIVERGENCE

    # The RV trade goes LONG the country with the HIGHER real rate: its bonds
    # carry more real compensation, and the divergence view is that its yield
    # falls more (or rises less) than the other's as the gap closes. The long/short
    # assignment is DERIVED from the sign of the measured differential, never a
    # caller flag — a flag would let a caller name the wrong leg on a correct
    # number.
    if divergence_bp >= 0.0:
        long_leg_country, short_leg_country = inputs.country_a, inputs.country_b
    else:
        long_leg_country, short_leg_country = inputs.country_b, inputs.country_a

    a_tighter = "tighter" if divergence_bp >= 0.0 else "looser"
    a_code = inputs.country_a.strip().lower()
    b_code = inputs.country_b.strip().lower()

    interpretation = (
        f"{a_code.upper()} real stance {real_a:.2f}% vs {b_code.upper()} "
        f"{real_b:.2f}% — a {divergence_bp:+.0f}bp real-rate differential, "
        f"{'MEANINGFUL' if meaningful else 'inside the noise band'} against a "
        f"{threshold_bp:.0f}bp threshold. {a_code.upper()} is the {a_tighter} "
        f"real stance; the RV trade is LONG {long_leg_country.upper()} 10y / "
        f"SHORT {short_leg_country.upper()} 10y."
    )

    basis = (
        f"both legs already in {inputs.currency_a.strip().upper()}"
        if inputs.same_currency_basis
        else f"legs reconciled through the FX bridge "
        f"({inputs.currency_a.strip().upper()}/{inputs.currency_b.strip().upper()})"
    )
    context = (
        f"Nominal 10y spread {nominal_bp:+.0f}bp "
        f"({a_code.upper()} {inputs.long_rate_a:.2f}% vs {b_code.upper()} "
        f"{inputs.long_rate_b:.2f}%); {basis}. The nominal spread MIXES expected "
        f"inflation and the real rate, which is why the verdict reads the "
        f"real-rate differential and reports the nominal one beside it."
    )

    warnings = [
        "LTCM CAVEAT (Section 22.3.1): a cross-market RV trade is "
        "correlation-dependent. In stress the two legs break rank and the spread "
        "stops behaving like a spread — the two positions can lose together. The "
        "duration-neutral hedge is neutral to the LEVEL of global rates, not to a "
        "correlation breakdown.",
        "The real rate formed here is from REALIZED inflation (policy rate minus "
        "year-over-year CPI), which is backward-looking. A divergence computed "
        "from realized inflation is not the same as one from expected inflation.",
        "A duration-neutral spread is neutral only at inception: the two legs' "
        "convexities differ, so the position drifts into directional exposure and "
        "must be rebalanced.",
    ]
    if not meaningful:
        warnings.append(
            f"NO MEANINGFUL DIVERGENCE: the {divergence_bp:+.0f}bp real-rate gap "
            f"is inside the {threshold_bp:.0f}bp band. This is an honest "
            f"non-trade, not an error — the measured gap is published beside the "
            f"verdict rather than collapsed to zero."
        )

    value = {
        "verdict": verdict,
        "divergence_bp": round(divergence_bp, 4),
        "nominal_spread_bp": round(nominal_bp, 4),
        "real_rate_a": round(real_a, 4),
        "real_rate_b": round(real_b, 4),
        "long_leg_country": long_leg_country.strip().lower(),
        "short_leg_country": short_leg_country.strip().lower(),
        "threshold_bp": round(threshold_bp, 4),
    }

    return ModelResult(
        model_name="cross_country_divergence",
        country=f"{a_code}-{b_code}",
        as_of=utc_now(),
        value=value,
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=interpretation,
        context=context,
        inputs_used=[
            "policy_rate_a",
            "policy_rate_b",
            "inflation_a",
            "inflation_b",
            "long_rate_a",
            "long_rate_b",
        ],
        warnings=warnings,
        # The reasoning is a differential, and the threshold is a fitted band; the
        # confidence reflects that the neutral-rate-free real rate is observable
        # but the divergence-to-trade mapping is a judgement.
        assumptions=[
            "Both legs are the SAME instrument (tenor and horizon checked by the "
            "input validator) in two DIFFERENT countries.",
            "A cross-currency pair was reconciled through the FX bridge before this "
            "record was built (attested by fx_converted), so the two numbers are "
            "on one basis.",
            "Real rates are formed with the same inflation measure on both sides.",
            "The threshold separating a real divergence from noise is a fitted "
            "assumption, not a measurement of this pair.",
        ],
        data_provenance=[
            "policy_rate_* / inflation_* — each country's own derived policy rate "
            "and inflation measure, supplied by the caller's per-country join.",
            "long_rate_* — each country's own 10-year yield.",
            "cross_country.meaningful_divergence_bp — config leaf (the noise band)",
            "cross_country.comparable_horizon_quarters — config leaf (the shared horizon)",
        ],
        limitations=[
            "Real rates from realized inflation are backward-looking.",
            "The nominal spread is reported but is not, by itself, a divergence "
            "measure: it mixes expected inflation and the real rate.",
            "The result says a divergence EXISTS and its sign; it does not forecast "
            "whether the spread compresses.",
        ],
    )
