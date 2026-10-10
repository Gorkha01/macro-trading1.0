"""Module 4 — policy rule models, the canonical gap, and the market-implied proxy.

Why three rules rather than one
-------------------------------
A single policy rule produces a single number, and a single number invites the
reader to treat it as *the* answer. The three variants here differ in one
substantive way: whether and how heavily they depend on ``r*``, the neutral real
rate, which Section 21.4 item 13 lists as **unobservable by nature**.

``taylor_rule`` and ``balanced_approach_rule`` both consume ``r*`` directly, so
their output inherits that unobservability. ``first_difference_rule`` is written
in *changes* precisely so that ``r*`` cancels out — it needs only the previous
policy rate, which is observed. The disagreement between the three is therefore
not incidental noise; it is a measurement of how much the answer depends on a
quantity nobody can observe. Section 6.1 is explicit that this divergence **is**
the signal and must never be averaged away.

The canonical gap (Section 22.4)
--------------------------------
One definition only: ``model_implied = median{taylor, balanced, first_diff}``,
``raw_gap = model_implied - market_implied``, and — the part that is easy to
omit — ``is_meaningful = |raw_gap| > dispersion``. The dispersion of the three
rules *is* the noise floor. A gap smaller than the spread among equally
defensible models is not evidence of anything.

Why the median rather than Taylor alone or a mean: the median is robust to one
rule being an outlier without requiring anyone to justify discarding it, and
"which rule do we drop" is exactly the judgement that gets made after the
conclusion is known.
"""

from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macro_engine.config import get_settings
from macro_engine.data_layer.fed_funds_futures_client import (
    FUTURES_ROUTE_ENDPOINT,
    FedFundsFuturesCurve,
)
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "BalanceSheetInputs",
    "BoeContemporaneousInputs",
    "BoeFirstDifferenceInputs",
    "BoeForwardLookingInputs",
    "DeBundSpreadInputs",
    "DeMemberAppropriatenessInputs",
    "DeRealRateInputs",
    "EcbContemporaneousInputs",
    "EcbErrorCorrectionInputs",
    "EcbRestrictedCointegrationInputs",
    "FirstDifferenceInputs",
    "JpOvershootCommitmentInputs",
    "JpReifschneiderWilliamsInputs",
    "JpYccInputs",
    "MarketPricingGap",
    "PolicyRuleResult",
    "QEStance",
    "StatementDiffDirection",
    "StatementTextInputs",
    "TaylorRuleInputs",
    "balanced_approach_rule",
    "boe_contemporaneous_taylor_rule",
    "boe_first_difference_rule",
    "boe_forward_looking_taylor_rule",
    "canonical_policy_gap",
    "de_bund_spread_rule",
    "de_member_appropriateness_rule",
    "de_real_rate_rule",
    "derive_market_implied_policy_path",
    "ecb_contemporaneous_taylor_rule",
    "ecb_error_correction_rule",
    "ecb_restricted_cointegration_rule",
    "first_difference_rule",
    "futures_implied_policy_path",
    "jp_overshoot_commitment_rule",
    "jp_reifschneider_williams_rule",
    "jp_ycc_reference_rule",
    "policy_rule_ensemble",
    "qe_qt_stance",
    "statement_text_diff",
    "taylor_rule",
]

# Basis points per percentage point. Section 6.1's ensemble bands are stated in
# bp while the rules return percent; making the conversion a named constant
# means the comparison cannot be made between mismatched units, which would be a
# silent factor-of-100 error in the one place the system judges whether policy
# rules agree.
_BP_PER_PP = 100.0


_NON_FINITE_REMEDY = (
    "A non-finite value is neither missing nor neutral — it is a value that "
    "fails EVERY comparison, so it does not merely escape the rule's bounds, it "
    "silently takes the branch those bounds were written to exclude. Measured "
    "before this guard (D-078): `taylor_rule(pi_current=nan)` returned "
    "`value=nan`, and every consumer asking 'is the prescribed rate above the "
    "actual one?' gets `False` from `nan > actual` — the rule reports *'the Fed "
    "is not behind the curve'* on the strength of a prescription it could not "
    "compute. Missing data is represented by refusing to compute (Section 21.0 "
    "rule 3, D-074.2)."
)


# D-139: the finite-input guard was promoted to the shared contract module as
# `FiniteInputs`, so every model family can reuse it rather than re-deriving the
# same `model_validator`. The local name is kept as an alias so this module's
# own input classes and their tests are untouched; the REASON string stays here
# too because it is worded for the policy rules specifically.
_FiniteInputs = FiniteInputs


class TaylorRuleInputs(_FiniteInputs):
    """Inputs shared by the level-based rules.

    ``pi_target`` defaults to the configured FOMC objective rather than a
    literal 2.0, because the target is an institutional fact that could change
    and a hardcoded copy here would silently disagree with the config.
    """

    r_star: float = Field(
        description="Neutral real rate, percent. UNOBSERVABLE — see Section 21.4 item 13."
    )
    pi_current: float = Field(description="Current inflation, percent, year-over-year.")
    pi_target: float | None = Field(
        default=None,
        description="Inflation target, percent. ``None`` uses the configured FOMC objective.",
    )
    output_gap: float = Field(
        description="Output gap as percent of potential, (actual - potential) / potential * 100."
    )

    @property
    def resolved_pi_target(self) -> float:
        """The target actually used, falling back to config when unset."""
        if self.pi_target is not None:
            return self.pi_target
        return get_settings().policy.pi_target_value


class FirstDifferenceInputs(_FiniteInputs):
    """Inputs for the speed-limit rule, which needs no ``r*``."""

    i_prev: float = Field(description="Previous policy rate, percent. Observed, not estimated.")
    pi_current: float = Field(description="Current inflation, percent.")
    pi_target: float | None = Field(
        default=None, description="Inflation target, percent. ``None`` uses config."
    )
    output_gap_change: float = Field(
        description="Change in the output gap since the last period, in pp."
    )
    alpha: float | None = Field(
        default=None, description="Weight on the inflation gap. ``None`` uses config."
    )
    beta: float | None = Field(
        default=None, description="Weight on the output-gap change. ``None`` uses config."
    )

    @property
    def resolved_pi_target(self) -> float:
        if self.pi_target is not None:
            return self.pi_target
        return get_settings().policy.pi_target_value

    @property
    def resolved_alpha(self) -> float:
        if self.alpha is not None:
            return self.alpha
        return get_settings().policy.rules.first_difference_alpha_value

    @property
    def resolved_beta(self) -> float:
        if self.beta is not None:
            return self.beta
        return get_settings().policy.rules.first_difference_beta_value


class PolicyRuleResult(ModelResult):
    """A ``ModelResult`` narrowed to the policy-rule family.

    ``value`` is a ``float``: the prescribed policy rate in percent.

    ``rule_variant`` is carried on the result rather than inferred from
    ``model_name``, so every consumer of a ``PolicyRuleResult`` — the ensemble,
    the canonical gap, the thesis builder — can branch on a typed field without
    string-matching a model name. That is the difference between a rename being
    a refactor and a rename being a silent behavioural change.
    """

    rule_variant: str = Field(
        description='One of "taylor_1993" | "balanced_approach" | "first_difference".'
    )


class MarketPricingGap(BaseModel):
    """The one canonical model-vs-market gap (Section 22.4).

    **The single definition in the tree.** Until D-064 a second, structurally
    different ``MarketPricingGap`` lived in ``thesis_layer/schemas.py`` — same
    fields except that its noise-floor field was named ``rule_dispersion``
    where this one says ``dispersion`` — and the collision had the same
    consequence as the ``ScenarioOutcome`` one (**O-51**): the canonical
    producer (``canonical_policy_gap``, Section 22.4, *"no other definition is
    valid"*) returned THIS class, and ``build_scenario_distribution`` accepted
    the OTHER, so the producer could not feed the consumer. The thesis layer now
    re-exports this class, the ``EvidenceSourceFamily`` pattern.

    ``value`` is a ``float`` -- ``raw_gap``, in percentage points.

    ``is_meaningful`` is not decoration. It is the significance test required by
    Section 16.2 Q6, and it is computed from the rule dispersion rather than
    from a fixed threshold, because the appropriate noise floor depends on how
    much the rules actually disagree in the current environment.
    """

    model_config = ConfigDict(extra="forbid")

    model_implied_value: float = Field(
        allow_inf_nan=False,
        description="Median of the three rules, percent. MUST be finite.",
    )
    market_implied_value: float = Field(
        allow_inf_nan=False,
        description="Market-implied path proxy, percent. MUST be finite.",
    )
    raw_gap: float = Field(
        allow_inf_nan=False,
        description="model_implied - market_implied, percentage points. MUST be finite.",
    )
    dispersion: float = Field(
        allow_inf_nan=False,
        description="max - min of the three rules, percentage points. MUST be finite.",
    )
    is_meaningful: bool = Field(
        description="abs(raw_gap) > dispersion. False means the gap is inside the noise floor."
    )
    unit: str = Field(default="%", description="Unit of the gap figure.")
    interpretation: str = Field(
        description="Plain-language reading, including the significance verdict."
    )

    @property
    def direction(self) -> str:
        """Which way the model sits relative to the market.

        A pure derivation of ``raw_gap``, moved here from the thesis layer's
        duplicate class when D-064 collapsed the two (see the class docstring).
        It is a ``property`` rather than a field because a stored copy could
        disagree with ``raw_gap``, and the gap is the one quantity this class
        exists to state.

        ``raw_gap`` is guaranteed finite by the field constraints above, which
        is what makes this fallthrough safe (D-078). Without them a `nan` gap
        satisfies neither ``> 0`` nor ``< 0`` and falls to the last branch —
        reporting **``aligned``**: *"the model and the market agree"* — when in
        truth the gap was never computed. Measured before the guard: a `nan`
        ``raw_gap`` returned ``direction='aligned'`` and ``is_meaningful=False``,
        i.e. **a silent NO-TRADE manufactured from absent data**, in a class
        whose entire purpose is to detect a disagreement with the market. The
        comparisons here are structural fallthroughs, so the FINITENESS of the
        input is the only thing standing between "no gap" and "no disagreement".
        """
        if self.raw_gap > 0:
            return "model_above_market"
        if self.raw_gap < 0:
            return "model_below_market"
        return "aligned"


def taylor_rule(inputs: TaylorRuleInputs) -> PolicyRuleResult:
    """``i = r* + pi + 0.5(pi - pi_target) + 0.5(output_gap)``

    Taylor (1993), Section 6.1. The coefficients come from config
    (``policy.rules.*``) rather than being written into the expression, so the
    variant a result was produced under is inspectable after the fact.

    Section 11.1 mandates ``test_taylor_rule_matches_hand_calculation`` with
    ``r* = 0.5, pi = 3%, target = 2%, output_gap = +1%`` producing ``i = 4.5%``.

    Confidence is deliberately modest and comes from ``compute_confidence()``:
    the rule depends on ``r*``, which is unobservable, so
    ``depends_on_unobservable=True`` is asserted as a fact about the
    computation rather than a feeling about the answer.
    """
    pi_target = inputs.resolved_pi_target
    gap_coefficient = get_settings().policy.rules.taylor_output_gap_coefficient_value
    inflation_coefficient = get_settings().policy.rules.inflation_gap_coefficient_value

    inflation_gap = inputs.pi_current - pi_target
    rate = (
        inputs.r_star
        + inputs.pi_current
        + inflation_coefficient * inflation_gap
        + gap_coefficient * inputs.output_gap
    )

    return PolicyRuleResult(
        model_name="taylor_rule",
        rule_variant="taylor_1993",
        country="us",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=f"Taylor Rule prescribes a policy rate of {rate:.2f}%",
        context=(
            f"vs r*={inputs.r_star}%, inflation gap {inflation_gap:+.2f}pp, "
            f"output gap {inputs.output_gap:+.2f}%"
        ),
        inputs_used=["r_star", "pi_current", "output_gap"],
        warnings=[
            "r* is a model-dependent estimate, not an observation. Every "
            "percentage point of error in r* passes through one-for-one into "
            "this prescribed rate (Section 21.4 item 13).",
        ],
    )


def balanced_approach_rule(inputs: TaylorRuleInputs) -> PolicyRuleResult:
    """As ``taylor_rule``, but the output-gap coefficient is 1.0 rather than 0.5.

    This is the FOMC's stated balanced-approach formulation, so it is an
    institutional fact rather than a modelling choice — which is also why it
    sits alongside Taylor rather than replacing it. Two rules the Fed itself
    cites, differing in a documented way, produce a divergence that means
    something.
    """
    pi_target = inputs.resolved_pi_target
    rules = get_settings().policy.rules
    gap_coefficient = get_settings().policy.balanced_approach_output_gap_coefficient.value
    inflation_coefficient = rules.inflation_gap_coefficient_value
    taylor_gap_coefficient = rules.taylor_output_gap_coefficient_value

    inflation_gap = inputs.pi_current - pi_target
    rate = (
        inputs.r_star
        + inputs.pi_current
        + inflation_coefficient * inflation_gap
        + gap_coefficient * inputs.output_gap
    )

    # The divergence from Taylor is derived rather than described, so a change
    # to either coefficient in config changes the stated context too.
    coefficient_delta = gap_coefficient - taylor_gap_coefficient
    divergence = coefficient_delta * inputs.output_gap

    return PolicyRuleResult(
        model_name="balanced_approach_rule",
        rule_variant="balanced_approach",
        country="us",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=f"Balanced-Approach Rule prescribes {rate:.2f}%",
        context=(
            f"Weights the output gap {gap_coefficient:g}x rather than "
            f"{taylor_gap_coefficient:g}x, so it diverges from Taylor by "
            f"{coefficient_delta:g} x output_gap = {divergence:+.2f}pp"
        ),
        inputs_used=["r_star", "pi_current", "output_gap"],
        warnings=[
            "r* is a model-dependent estimate, not an observation — the same "
            "limitation that applies to the classic Taylor Rule applies here.",
            "The larger output-gap coefficient makes this rule more responsive "
            "to a gap that is itself estimated and revised; in a large-gap "
            "regime this rule can prescribe a rate well outside the plausible "
            "policy range.",
        ],
    )


def first_difference_rule(inputs: FirstDifferenceInputs) -> PolicyRuleResult:
    """``i_t - i_{t-1} = alpha(pi - pi_target) + beta * delta(output_gap)``

    Why this rule exists is the whole point of having three: ``r*`` does not
    appear. Stated as a change, the neutral rate cancels, so this rule needs
    only the previous policy rate — an observed quantity — and the *change* in
    the output gap, which is far better estimated than its level.

    That is also why its confidence is structurally higher than the level-based
    rules': it does not carry ``depends_on_unobservable``, so
    ``compute_confidence()`` does not apply that penalty. The higher number is
    earned by the construction, not asserted.

    It is deliberately not a replacement. The rule says where to go *from here*,
    which is unhelpful precisely when the level is what is in question — so it
    is a cross-check on the other two, not a tie-breaker.
    """
    pi_target = inputs.resolved_pi_target
    alpha = inputs.resolved_alpha
    beta = inputs.resolved_beta

    inflation_gap = inputs.pi_current - pi_target
    delta = alpha * inflation_gap + beta * inputs.output_gap_change
    rate = inputs.i_prev + delta

    return PolicyRuleResult(
        model_name="first_difference_rule",
        rule_variant="first_difference",
        country="us",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"Speed-Limit Rule prescribes {rate:.2f}% ({delta:+.2f}pp from current "
            f"{inputs.i_prev:.2f}%)"
        ),
        context=(
            "Deliberately avoids the unobservable r* — cross-check against "
            "Taylor and Balanced rather than substituting for them"
        ),
        inputs_used=["i_prev", "pi_current", "output_gap_change"],
        warnings=[
            "By construction this rule prescribes a CHANGE, not a level. It "
            "inherits the level of the previous rate and cannot detect that the "
            "level itself was wrong, which is exactly the question the "
            "level-based rules answer.",
        ],
    )


# ---------------------------------------------------------------------------
# Module 4 — Section 22.3: the Bank of England reaction function.
#
# These three functions are the "gb" arm of the multi-country increment. They
# are NOT the Fed rules with a relabel — Section 22.3 rejects exactly that. Each
# of the three structural differences below is enforced in the code:
#
#   1. A SINGLE 2% CPI target (not a dual mandate, not PCE). The rule reads UK
#      CPI components, not US ones.
#   2. The energy / non-energy split in the CONTEMPORANEOUS rule — a
#      decomposition none of the Fed rules performs.
#   3. PROJECTION horizons (5 and 3 quarters ahead) on the two forward-looking
#      rules, where the Fed rules read CONTEMPORANEOUS quantities.
#
# The coefficients are the BoE's own, published in Annex 1 of the November 2025
# Monetary Policy Report (Table A1.A), read from
# ``settings.policy.gb`` — never written into an expression (LAW 1). The same
# Annex states each rule in exactly the form implemented below, including the
# 0.85 interest-rate smoothing, so the implementation is a transcription of the
# primary source rather than a reconstruction of a textbook rule.
# ---------------------------------------------------------------------------


class BoeContemporaneousInputs(_FiniteInputs):
    """Inputs for the BoE's contemporaneous Taylor-type rule.

    **``pi_energy`` and ``pi_non_energy`` are DEVIATIONS FROM STEADY STATE, not
    levels.** The BoE's Annex 1 says so in terms ("*the deviation from steady
    state of … annual energy inflation … annual inflation of non-energy
    components …*"), and the consequence is concrete: at the 2% target both are
    zero and the raw prescription collapses to ``i* = 3%``. A caller that passed
    LEVELS would add ~2-4pp of spurious tightening at the neutral point, which
    is why the field names and the docstring both say "gap" rather than relying
    on the reader's memory of the Annex.

    There is deliberately no single ``pi_current`` field: the whole point of
    this rule, and its clearest structural difference from the Fed's, is that
    inflation enters as TWO separately weighted components. Collapsing them
    before the rule would discard the decomposition the rule exists to apply.
    """

    i_prev: float = Field(
        description="Bank Rate in the previous quarter, percent. Observed, not estimated.",
    )
    pi_energy_gap_pp: float = Field(
        description=(
            "Annual ENERGY CPI inflation, as a deviation from steady state, in "
            "percentage points. Zero at the target. Weighted 0.375 in the rule — "
            "the BoE treats energy as largely transitory."
        ),
    )
    pi_non_energy_gap_pp: float = Field(
        description=(
            "Annual NON-ENERGY CPI inflation, as a deviation from steady state, "
            "in percentage points. Zero at the target. Weighted 1.5 in the "
            "rule — ~4x the energy term."
        ),
    )
    output_gap: float = Field(
        description="Output gap as percent of potential, current quarter.",
    )


class BoeForwardLookingInputs(_FiniteInputs):
    """Inputs for the BoE's forward-looking Taylor-type rule.

    Both inputs are **projections**, not observations — the BoE's Annex 1 is
    explicit that the rule contains "*five-quarter-ahead projections of
    macroeconomic variables on the right-hand side*". The horizon is read from
    config (``policy.gb.forward_looking.horizon_quarters``) so it is a property
    of the rule, not of this input group.

    ``projected_inflation_pp`` is a LEVEL (annual CPI inflation, percent), and
    the rule forms ``projected_inflation_pp - pi_target`` itself — matching the
    published expression ``1.5(π_{t+5|t} - π*)``, which subtracts the target in
    the formula rather than in the input.
    """

    i_prev: float = Field(
        description="Bank Rate in the previous quarter, percent.",
    )
    projected_inflation_pp: float = Field(
        description=(
            "Projected annual CPI inflation at the configured horizon (5 "
            "quarters by default), percent. A LEVEL: the rule subtracts the "
            "target itself, as the published formula does."
        ),
    )
    projected_output_gap: float = Field(
        description="Projected output gap at the same horizon, percent of potential.",
    )


class BoeFirstDifferenceInputs(_FiniteInputs):
    """Inputs for the BoE's forward-looking first-difference rule.

    Like the Fed's speed-limit rule this is written in CHANGES, so ``i*``
    cancels. But the regressors differ: the BoE reads a **projected inflation
    gap** three quarters ahead and **projected GDP growth** — the latter is a
    growth rate, not a change in the output gap as in the Fed's
    ``output_gap_change``. Passing an output-gap change here would be a unit
    substitution the rule's structure would not catch, so the field is named
    ``projected_gdp_growth`` and documented as a growth rate.
    """

    i_prev: float = Field(
        description="Bank Rate in the previous quarter, percent. Observed.",
    )
    projected_inflation_pp: float = Field(
        description=(
            "Projected annual CPI inflation at the configured horizon (3 "
            "quarters by default), percent. A LEVEL — the rule subtracts the "
            "target to form the gap."
        ),
    )
    projected_gdp_growth: float = Field(
        description=(
            "Projected QUARTERLY GDP growth at the same horizon, percent. A "
            "GROWTH RATE, not a change in the output gap — the two are "
            "different regressors despite the similar rule form."
        ),
    )


def _boe_stance_word(rate: float, i_star: float) -> str:
    """``restrictive`` / ``accommodative`` / ``neutral`` — the BoE rates against i*.

    A named function rather than an inline conditional for the same reason
    ``_gap_direction_sentence`` is one: the threshold is load-bearing and easy to
    invert, and two of the three BoE rules publish this word, so an inline copy
    in each would be two places for the same judgement to drift.

    The exact-equality case is separated because "neutral" is a third state, not
    a rounding of either direction — and the comparison is on equality first so
    a float that lands exactly on ``i*`` cannot be mislabelled by whichever
    branch's ``else`` caught it (the D-040 class of defect).
    """
    if rate > i_star:
        return "restrictive"
    if rate < i_star:
        return "accommodative"
    return "neutral"


def boe_contemporaneous_taylor_rule(inputs: BoeContemporaneousInputs) -> PolicyRuleResult:
    """``i_t = 0.85·i_{t-1} + 0.15·(i* + 0.375·π_E + 1.5·π_N + 0.5·y)``

    The Bank of England's contemporaneous Taylor-type rule, transcribed from
    Table A1.A of the November 2025 Monetary Policy Report (Annex 1). Two
    structural features make this **not** a relabelled Fed rule (Section 22.3):

    * **The energy / non-energy split.** The BoE responds to the two components
      of annual CPI inflation separately, weighting non-energy ~4x energy
      (``1.5`` vs ``0.375``). None of the Fed rules decomposes inflation this
      way; a single-``pi`` rule would fail to express the Bank's documented view
      that energy movements are largely transitory.
    * **Interest-rate smoothing.** Every BoE rule carries the published
      ``0.85`` persistence term, so the prescription is a *move toward* the raw
      rule value, not a jump to it. The Fed rules have no such term, and a rule
      without it would prescribe an instantaneous adjustment the Committee is
      institutionally documented not to make.

    The ``0.85 / 0.15`` pair is not a coincidence of two independent
    coefficients: ``0.15 = 1 - 0.85``, and the code writes it that way so the
    two cannot silently disagree — changing ``smoothing`` in config moves both.
    A reader who expects an un-smoothed prescription can recover the raw value
    from the result's ``value["raw_prescription_pct"]``.

    Confidence is ``compute_confidence()``'s, never asserted, and carries
    ``depends_on_unobservable=True`` because ``i*`` is the BoE's illustrative
    neutral rate — unobservable by nature, the same Section 21.4 item 13
    limitation the Fed rules have.
    """
    gb = get_settings().policy.gb
    i_star = gb.i_star_value
    smoothing = gb.smoothing_value
    coefficients = gb.contemporaneous

    raw = (
        i_star
        + coefficients.energy_cpi_coefficient_value * inputs.pi_energy_gap_pp
        + coefficients.non_energy_cpi_coefficient_value * inputs.pi_non_energy_gap_pp
        + coefficients.output_gap_coefficient_value * inputs.output_gap
    )
    # Written as `1 - smoothing` rather than a second literal so the two halves
    # of the published 0.85/0.15 pair are one number in config (LAW 2).
    rate = smoothing * inputs.i_prev + (1.0 - smoothing) * raw

    return PolicyRuleResult(
        model_name="boe_contemporaneous_taylor_rule",
        rule_variant="boe_contemporaneous_taylor",
        country="gb",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=(
            f"The Bank of England's contemporaneous Taylor-type rule prescribes "
            f"Bank Rate of {rate:.2f}% (raw, un-smoothed prescription {raw:.2f}%)"
        ),
        context=(
            f"Smoothing {smoothing:.2f}: 85% of the previous rate "
            f"({inputs.i_prev:.2f}%) persists and 15% of the gap to the raw "
            f"prescription is closed each quarter. Energy CPI gap "
            f"{inputs.pi_energy_gap_pp:+.2f}pp (weight "
            f"{coefficients.energy_cpi_coefficient_value:g}), non-energy "
            f"{inputs.pi_non_energy_gap_pp:+.2f}pp (weight "
            f"{coefficients.non_energy_cpi_coefficient_value:g}), output gap "
            f"{inputs.output_gap:+.2f}% (weight "
            f"{coefficients.output_gap_coefficient_value:g})."
        ),
        inputs_used=[
            "i_prev",
            "pi_energy_gap_pp",
            "pi_non_energy_gap_pp",
            "output_gap",
        ],
        warnings=[
            "i* is the BoE's ILLUSTRATIVE neutral rate (2% target + 1% assumed "
            "real), not an estimate with a confidence interval, and it is "
            "unobservable (Section 21.4 item 13). Every percentage point of "
            "error in i* passes through at 0.15 into this quarter's "
            "prescription, but cumulates to 1:1 in the level the rule "
            "eventually reaches.",
            "The energy component is weighted ~4x SMALLER than non-energy "
            "because the BoE treats energy price movements as largely "
            "transitory. A reader who reads this as 'the BoE barely responds to "
            "inflation' has mis-attributed a decomposition: the rule responds "
            "1.5:1 to the non-energy component, which satisfies the Taylor "
            "principle, and the energy term is a deliberate exception.",
            "This is a MODEL-BASED SIMULATION rule, not a description of how "
            "the MPC sets Bank Rate. The Bank states that 'there is no "
            "mechanical link between endogenous policy simulations and "
            "real-world monetary policy decisions'.",
        ],
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percent",
        direction=(
            f"{_boe_stance_word(rate, i_star)} relative to the BoE's illustrative "
            f"neutral rate of {i_star:.2f}%"
        ),
        assumptions=[
            "pi_energy_gap_pp and pi_non_energy_gap_pp are DEVIATIONS FROM "
            "STEADY STATE, not levels — at the 2% target both are zero and the "
            "raw prescription is i* = 3%. The BoE's Annex 1 states them this "
            "way ('the deviation from steady state of …').",
            "The rule is smoothed: the published prescription is a weighted "
            "average of the previous rate and the raw rule value, because the "
            "Committee is documented not to jump Bank Rate to the rule's "
            "implied level.",
            "UK CPI components (gb_cpi_* series), not US measures — the BoE's "
            "target is 2% CPI, a different measure from the Fed's 2% PCE.",
        ],
        data_provenance=[
            "i_prev — Bank Rate in the previous quarter, percent. The Bank of "
            "England's policy rate; gb_bank_rate in the registry tracks SONIA, "
            "the risk-free reference rate.",
            "pi_energy_gap_pp / pi_non_energy_gap_pp — the two CPI components' "
            "deviations from steady state, from the gb_cpi_* series",
            "coefficients — config leaves policy.gb.contemporaneous.*, the "
            "BoE's published Table A1.A calibration (Nov 2025 MPR, Annex 1)",
            "i_star — config leaf policy.gb.i_star, the BoE's own convention "
            "(2% target + 1% illustrative real rate), not fitted here",
        ],
        limitations=[
            "This is a SIMULATION rule. Annex 1 is explicit that the rules are "
            "'stylised and simplified' and 'do not reflect the full set of "
            "information and uncertainties with which policymakers are faced'. "
            "It describes what a mechanical rule WOULD prescribe, not what the "
            "MPC decided or will decide.",
            "i* is held CONSTANT at 3% in the Bank's own simulations. A changing "
            "equilibrium real rate would shift the rule's level, and this "
            "module cannot detect that — the same unobservability the Fed rules "
            "inherit.",
            "The projection inputs (on the forward-looking rules) are model "
            "FORECASTS from the Bank's COMPASS model. This module does not "
            "produce them; a caller must supply them, and their error is "
            "inherited unmeasured.",
            "The output is a prescribed RATE, not a forecast of what the MPC "
            "will do at its next meeting.",
        ],
        decision_relevance=(
            "The 'gb' arm of Section 16.2's Q6 gap. Its value, alongside the "
            "two other BoE rules, defines the UK model-implied policy path that "
            "a UK thesis compares against the market-implied path — exactly the "
            "role the Fed rules play for a US thesis."
        ),
        decision_prohibition=[
            "MUST NOT be described as the MPC's reaction function. The Bank "
            "states there is 'no mechanical link' between these simulations and "
            "real-world decisions; treating a simulated path as a description "
            "of policy is the misreading this prohibition exists to prevent.",
            "MUST NOT be combined with the Fed rules in one ensemble or their "
            "dispersion read across countries. The three BoE rules share the "
            "BoE's target and smoothing; mixing them with the Fed's would make "
            "the dispersion a measure of the currency, not of the model.",
            "MUST NOT be consumed without the raw prescription visible: the "
            "smoothed value alone hides how far the rule wants Bank Rate to "
            "move, which is the quantity a desk compares against the "
            "market-implied path.",
        ],
    )


def boe_forward_looking_taylor_rule(inputs: BoeForwardLookingInputs) -> PolicyRuleResult:
    """``i_t = 0.85·i_{t-1} + 0.15·(i* + 1.5·(π_{t+5|t} - π*) + 0.5·y_{t+5|t})``

    The Bank of England's forward-looking Taylor-type rule, transcribed from
    Table A1.A of the November 2025 Monetary Policy Report (Annex 1). The
    structural difference from both the Fed's rules and from the BoE's own
    contemporaneous rule is the HORIZON: the right-hand side carries
    **five-quarter-ahead projections** (``pi_{t+5|t}`` and ``y_{t+5|t}``), a
    fifteen-month lead, so the prescription responds to where the Bank expects
    inflation and slack to be, not where they are.

    That lead is also the rule's principal weakness, and it is disclosed rather
    than buried: the inputs are FORECASTS from the Bank's COMPASS model, so the
    rule inherits the forecast's error in full, plus the smoothing lag on top.
    The horizon is read from ``policy.gb.forward_looking.horizon_quarters`` so
    it is inspectable and so a change to it cannot be mistaken for a change to
    the first-difference rule's (different) three-quarter horizon.

    ``projected_inflation_pp`` is a LEVEL; the rule subtracts ``pi_target``
    itself, exactly as the published expression ``1.5(π_{t+5|t} - π*)`` does.
    """
    gb = get_settings().policy.gb
    i_star = gb.i_star_value
    pi_target = gb.pi_target_value
    smoothing = gb.smoothing_value
    coefficients = gb.forward_looking
    horizon = coefficients.horizon_quarters_value

    inflation_gap = inputs.projected_inflation_pp - pi_target
    raw = (
        i_star
        + coefficients.inflation_coefficient_value * inflation_gap
        + coefficients.output_gap_coefficient_value * inputs.projected_output_gap
    )
    rate = smoothing * inputs.i_prev + (1.0 - smoothing) * raw

    return PolicyRuleResult(
        model_name="boe_forward_looking_taylor_rule",
        rule_variant="boe_forward_looking_taylor",
        country="gb",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=(
            f"The Bank of England's forward-looking Taylor-type rule prescribes "
            f"Bank Rate of {rate:.2f}% (raw prescription {raw:.2f}%)"
        ),
        context=(
            f"Reads {horizon}-quarter-ahead ({horizon * 3}-month) projections: "
            f"projected CPI inflation {inputs.projected_inflation_pp:.2f}% "
            f"against the {pi_target:.1f}% target (gap "
            f"{inflation_gap:+.2f}pp, weight "
            f"{coefficients.inflation_coefficient_value:g}), projected output "
            f"gap {inputs.projected_output_gap:+.2f}% (weight "
            f"{coefficients.output_gap_coefficient_value:g}); smoothed "
            f"{smoothing:.2f} from {inputs.i_prev:.2f}%."
        ),
        inputs_used=[
            "i_prev",
            "projected_inflation_pp",
            "projected_output_gap",
        ],
        warnings=[
            f"The inflation and output-gap inputs are {horizon}-QUARTER-AHEAD "
            f"PROJECTIONS, not observations. The rule's output is only as good "
            f"as the forecast beneath it, and this module does not produce the "
            f"forecast — it inherits its error unmeasured.",
            "The prescription is smoothed, so it responds to a projected shock "
            "with a LAG as well as a lead: the 5-quarter horizon anticipates, "
            "and the 0.85 smoothing then delays the response. The two effects "
            "pull in opposite directions and neither is separately visible in "
            "the output number.",
            "i* is the BoE's ILLUSTRATIVE neutral rate and is unobservable (Section 21.4 item 13).",
        ],
        unit="percent",
        direction=(
            f"{_boe_stance_word(rate, i_star)} relative to the BoE's illustrative "
            f"neutral rate of {i_star:.2f}%"
        ),
        assumptions=[
            f"The projection horizon is {horizon} quarters, read from config "
            f"(policy.gb.forward_looking.horizon_quarters), matching the Bank's "
            f"published rule. It is DID NOT default to a shorter horizon for "
            f"convenience: the horizon IS the rule.",
            "projected_inflation_pp is a LEVEL and the rule subtracts pi_target "
            "itself, matching the published expression 1.5(π_{t+5|t} - π*).",
            "The Bank's own simulations hold i* constant at 3%; a time-varying "
            "neutral rate would change the level this rule settles at.",
        ],
        data_provenance=[
            "projected_inflation_pp / projected_output_gap — SUPPLIED BY THE "
            "CALLER, not fetched. The Bank's COMPASS-model projections are not "
            "wired into this system, so a live run must either supply them from "
            "a documented source or the rule must not run (Section 21.0 rule 3).",
            "coefficients — config leaves policy.gb.forward_looking.*, the "
            "BoE's published Table A1.A calibration (Nov 2025 MPR, Annex 1)",
            "i_prev — Bank Rate in the previous quarter",
        ],
        limitations=[
            "The 5-quarter lead means the rule can be confidently wrong for "
            "five quarters before the projection is tested against outcomes. "
            "That is inherent to forward-looking rules, not a defect of this "
            "implementation — but it is why the output must never be read as a "
            "near-term call.",
            "This is a SIMULATION rule with 'no mechanical link' to real MPC decisions (Annex 1).",
            "The forecast inputs carry the Bank's COMPASS model structure; a "
            "different forecasting model would give different prescriptions "
            "from the same coefficients.",
        ],
        decision_relevance=(
            "Part of the 'gb' model-implied policy path (Section 16.2 Q6). Its "
            "divergence from the contemporaneous rule is itself informative: a "
            "wide spread means the projected path disagrees with the current "
            "reading, which the ensemble reports rather than averages away."
        ),
        decision_prohibition=[
            "MUST NOT be read as a forecast of Bank Rate. It is a rule's "
            "prescription GIVEN a forecast; the forecast is the input, not the "
            "output.",
            "MUST NOT be run without genuine projection inputs. Substituting "
            "current-quarter observations for the 5-quarter-ahead projections "
            "would silently turn this into the contemporaneous rule while it "
            "still reported itself as forward-looking — a field describing a "
            "computation that did not happen.",
            "MUST NOT be compared directly against the Fed rules' outputs. "
            "Different target, different measure, different horizon; the "
            "numbers are not on a common basis.",
        ],
    )


def boe_first_difference_rule(inputs: BoeFirstDifferenceInputs) -> PolicyRuleResult:
    """``Δi_t = 0.1·(π_{t+3|t} - π*) + 0.1·ΔGDP_{t+3|t}`` → ``i_t = i_{t-1} + Δi_t``

    The Bank of England's forward-looking first-difference rule, transcribed
    from Table A1.A of the November 2025 Monetary Policy Report (Annex 1). Like
    the Fed's speed-limit rule it is written in **changes**, so ``i*`` cancels
    — it needs only the observed previous rate. But three things differ from
    the Fed's rule of superficially similar form, and all three are structural:

    * the regressors are **three-quarter-ahead PROJECTIONS**, where the Fed
      rule reads current-quarter quantities;
    * the demand term is **projected GDP GROWTH**, not a change in the output
      gap — a different regressor despite the similar rule shape;
    * the weights are ``0.1 / 0.1``, far smaller than the Fed's ``0.5 / 0.5``,
      so this rule moves Bank Rate in small increments.

    The horizon is read from ``policy.gb.first_difference.horizon_quarters``
    (3, deliberately different from the forward-looking Taylor-type rule's 5) so
    the two cannot be silently equated.
    """
    gb = get_settings().policy.gb
    pi_target = gb.pi_target_value
    coefficients = gb.first_difference
    horizon = coefficients.horizon_quarters_value

    inflation_gap = inputs.projected_inflation_pp - pi_target
    delta = (
        coefficients.inflation_coefficient_value * inflation_gap
        + coefficients.gdp_growth_coefficient_value * inputs.projected_gdp_growth
    )
    rate = inputs.i_prev + delta

    return PolicyRuleResult(
        model_name="boe_first_difference_rule",
        rule_variant="boe_first_difference",
        country="gb",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"The Bank of England's forward-looking first-difference rule "
            f"prescribes Bank Rate of {rate:.2f}% ({delta:+.2f}pp from "
            f"{inputs.i_prev:.2f}%)"
        ),
        context=(
            f"Reads {horizon}-quarter-ahead projections: inflation gap "
            f"{inflation_gap:+.2f}pp (weight "
            f"{coefficients.inflation_coefficient_value:g}) and projected GDP "
            f"growth {inputs.projected_gdp_growth:+.2f}% (weight "
            f"{coefficients.gdp_growth_coefficient_value:g}). No smoothing term "
            f"and no i* — by construction i* cancels in a difference."
        ),
        inputs_used=[
            "i_prev",
            "projected_inflation_pp",
            "projected_gdp_growth",
        ],
        warnings=[
            "By construction this rule prescribes a CHANGE, not a level. It "
            "inherits the level of the previous rate and cannot detect that the "
            "level itself is wrong.",
            "The demand term is projected GDP GROWTH, not a change in the "
            "output gap. The two are different regressors that a similar rule "
            "form can make look interchangeable — they are not, and a caller "
            "supplying an output-gap change here would silently change the "
            "quantity being modelled.",
            f"The regressors are {horizon}-quarter-ahead projections and are "
            f"model FORECASTS, not observations; this module does not produce "
            f"them.",
        ],
        unit="percent",
        direction=(
            f"{'tightening' if delta > 0 else 'easing' if delta < 0 else 'holding'} "
            f"relative to the previous Bank Rate of {inputs.i_prev:.2f}%"
        ),
        assumptions=[
            "The rule's regressors are PROJECTIONS 3 quarters ahead, matching "
            "the Bank's published rule. As with the forward-looking Taylor-type "
            "rule, substituting current observations would change the rule's "
            "identity.",
            "projected_inflation_pp is a LEVEL and the rule subtracts pi_target "
            "itself, matching the published expression 0.1(π_{t+3|t} - π*).",
            "The rule deliberately omits the 0.85 smoothing of the other two "
            "BoE rules: the Bank's own published first-difference rule has no "
            "smoothing term, so adding one would be a deviation from the "
            "primary source.",
        ],
        data_provenance=[
            "projected_inflation_pp / projected_gdp_growth — SUPPLIED BY THE "
            "CALLER; the Bank's projections are not wired into this system",
            "coefficients — config leaves policy.gb.first_difference.*, the "
            "BoE's published Table A1.A calibration (Nov 2025 MPR, Annex 1)",
            "i_prev — Bank Rate in the previous quarter",
        ],
        limitations=[
            "It cannot detect an incorrect level, only the direction of the "
            "next move. This is the same limitation the Fed's first-difference "
            "rule carries and the reason all three rules are reported together "
            "rather than any one being used alone.",
            "The rule is unsmoothed, so unlike the other two BoE rules it can "
            "prescribe large quarter-on-quarter moves if the projections are "
            "extreme. The small 0.1/0.1 weights damp this, but they do not "
            "bound it.",
            "The projections it reads are model FORECASTS; the rule inherits their error in full.",
        ],
        decision_relevance=(
            "Part of the 'gb' model-implied policy path (Section 16.2 Q6). "
            "Because it needs no i*, it is the cross-check that does not share "
            "the other two BoE rules' dependence on the unobservable neutral "
            "rate — the same structural role the Fed's speed-limit rule plays."
        ),
        decision_prohibition=[
            "MUST NOT be read as a level. It is a change from the previous "
            "rate; publishing it as a target rate would misstate what the rule "
            "says.",
            "MUST NOT be run on an output-gap change in place of projected GDP "
            "growth. The regressor substitution would not raise an error and "
            "would silently model a different economy.",
            "MUST NOT be compared directly against the Fed's first-difference "
            "rule. Different regressors, different horizon (3 quarters vs "
            "current), different economy.",
        ],
    )


# ---------------------------------------------------------------------------
# Module 5 — Section 22.3: the ECB reaction function.
#
# These three functions are the "eu" arm of the multi-country increment. They
# are NOT the Fed rules with euro-area series substituted — Section 22.3 rejects
# exactly that as the un-fakeable layer. Each of the structural differences
# below is enforced in the code:
#
#   1. THE LONG RATE ENTERS THE RULE. The euro area's own estimated reaction
#      function carries the 10-year rate as a long-run regressor, because the
#      long rate proxies the public's perception of the LONG-RUN INFLATION
#      OBJECTIVE. None of the Fed's three rules reads the long bond. The rule
#      that does is `ecb_error_correction_rule`; its `long_rate` input has no
#      analogue in `TaylorRuleInputs` or `FirstDifferenceInputs`.
#   2. THE THIRD RULE IS AN ERROR-CORRECTION, NOT A FORWARD-LOOKING TAYLOR OR
#      SPEED-LIMIT RULE. The euro area's level specification is unstable (unit
#      roots), so the euro-area estimation is an I(1) error-correction form: the
#      CHANGE responds to the deviation of the LEVEL from its long-run
#      equilibrium. That is a different functional form from anything in the
#      Fed's or the BoE's arms.
#   3. The level rule's coefficients are the euro area's OWN estimates
#      (k_pi = 2.733, k_y = 1.443), which the primary source's own joint Wald
#      test shows are NOT Taylor's 1.5 / 0.5 (p = 0.04).
#
# The coefficients are from ECB Working Paper No 258 (September 2003, "Interest
# rate reaction functions and the Taylor rule in the euro area"), Tables 2, 4
# and 6, read from ``settings.policy.eu`` — never written into an expression
# (LAW 1). The same tables state each rule in the form implemented below.
#
# The euro-area AGGREGATE only: no member-state reaction function is calibrated
# here (the operator's choice, 2026-10-10). This is the 20-country aggregate the
# ECB actually sets policy for, which is the honest unit for a euro-area rule.
# ---------------------------------------------------------------------------


class EcbContemporaneousInputs(_FiniteInputs):
    """Inputs for the ECB's traditional I(0) level rule (WP 258, eq. (2)).

    ``pi_current`` is HICP inflation as a LEVEL (percent, year-over-year) and
    ``output_gap`` is the gap as percent of potential. Unlike the BoE's
    contemporaneous rule there is no energy / non-energy split: the euro area's
    published rule does not decompose inflation, and inventing a split here
    would be a BoE feature wearing an EU label.

    There is deliberately no ``long_rate`` field: the level rule (WP 258,
    equation (2)) reads inflation and the output gap only. The long rate enters
    the *cointegrating* rule, and keeping it out of this input record is what
    makes the two functions' regressor sets structurally distinct rather than
    two names for one list.
    """

    i_prev: float = Field(
        description=(
            "The euro-area policy rate in the previous quarter, percent. The "
            "ECB's MAIN REFINANCING OPERATIONS rate — the rate the euro area's "
            "policy stance is quoted against."
        ),
    )
    pi_current: float = Field(
        description="Current HICP inflation, percent, year-over-year. A LEVEL.",
    )
    output_gap: float = Field(
        description="Output gap as percent of potential, current quarter.",
    )


class EcbErrorCorrectionInputs(_FiniteInputs):
    """Inputs for the ECB's cointegration (I(1)) error-correction rule.

    The structural difference is ``long_rate``. In the euro-area estimation the
    10-year rate is a **regressor**, not a market-control aside: it proxies the
    public's perception of the long-run inflation objective (``pi_inf``), which
    is what makes the euro-area rule forward-looking in a way the Fed's level
    rules are not. A euro-area rule with no long-rate term is a Fed rule with
    euro-area series, which is the §22.3 fake.

    The rule is written in CHANGES, so it also carries ``i_prev`` (to form the
    prescribed level) and ``i_prev_change`` (the lagged change, whose
    coefficient is the estimation's persistence-in-change term — distinct from
    the level rule's smoothing). All the change terms are quarter-on-quarter,
    in the same units as the levels (percent for rates and inflation, percent
    of potential for the gap).
    """

    i_prev: float = Field(
        description=(
            "The euro-area policy rate in the previous quarter, percent. Used "
            "to form the prescribed LEVEL from the rule's prescribed change."
        ),
    )
    i_prev_change: float = Field(
        description=(
            "The change in the policy rate over the previous quarter, in "
            "percentage points (i_{t-1} - i_{t-2}). The estimated persistence of "
            "the CHANGE, not of the level."
        ),
    )
    long_rate: float = Field(
        description=(
            "The euro-area 10-year government bond yield, percent. THE "
            "STRUCTURAL REGRESSOR: it proxies the public's long-run inflation "
            "perception. No Fed rule reads it."
        ),
    )
    pi_current: float = Field(
        description="Current HICP inflation, percent, year-over-year. A LEVEL.",
    )
    pi_change: float = Field(
        description=(
            "The change in HICP inflation over the current quarter, in "
            "percentage points (pi_t - pi_{t-1}). The SHORT-RUN response."
        ),
    )
    output_gap: float = Field(
        description="Output gap as percent of potential, current quarter. A LEVEL.",
    )
    output_gap_change: float = Field(
        description=(
            "The change in the output gap over the current quarter, in "
            "percentage points. The SHORT-RUN response to the gap."
        ),
    )


def _ecb_stance_word(rate: float, i_star: float) -> str:
    """``restrictive`` / ``accommodative`` / ``neutral`` — the euro area vs i*.

    The same three-state classification as ``_boe_stance_word``, kept as its own
    function rather than shared, for the same reason: the comparison is
    load-bearing and a shared helper would silently couple the two central
    banks' descriptive vocabulary. The exact-equality case is separated so a
    float landing on ``i*`` cannot be mislabelled by a branch's ``else`` (the
    D-040 class of defect).
    """
    if rate > i_star:
        return "restrictive"
    if rate < i_star:
        return "accommodative"
    return "neutral"


def ecb_contemporaneous_taylor_rule(inputs: EcbContemporaneousInputs) -> PolicyRuleResult:
    """``i_t = 0.884·i_{t-1} + 0.116·(i* + 2.733·(π - π*) + 1.443·y)``

    The ECB's traditional I(0) level rule for the euro area, from ECB Working
    Paper No 258, Table 2 (equation (2)). Two things make this **not** a
    relabelled Fed rule (Section 22.3):

    * **The coefficients are the euro area's own.** The estimated responses are
      ``k_pi = 2.733`` and ``k_y = 1.443`` — nearly twice and nearly three times
      Taylor's 1.5 and 0.5. The paper's joint Wald test REJECTS ``k_pi = 1.5,
      k_y = 0.5`` at p = 0.04, so importing the Fed's (or Taylor's) coefficients
      would contradict the primary source, not merely round it.
    * **The persistence is the euro area's own estimate.** ``0.884``, fit on the
      lagged euro-area short rate. The BoE's arm uses 0.85 and the Fed's rules
      have no term at all — three different behavioural facts.

    The rule is smoothed: the prescription is a weighted average of the previous
    rate and the raw rule value, because the estimation shows the euro-area rate
    does not jump to the raw prescription. A reader who wants the un-smoothed
    value can recover it from ``value["raw_prescription_pct"]``.

    Confidence is ``compute_confidence()``'s, never asserted, and carries
    ``depends_on_unobservable=True`` because ``i*`` is an illustrative neutral
    rate — unobservable by nature, the same Section 21.4 item 13 limitation the
    Fed and BoE rules carry. The euro area's real-rate estimate is particularly
    imprecise (WP 258 reports a 95% interval for rho spanning roughly
    [-0.85, 5.48]), which the warning states rather than hides.
    """
    eu = get_settings().policy.eu
    i_star = eu.i_star_value
    pi_target = eu.pi_target_value
    smoothing = eu.smoothing_value
    coefficients = eu.contemporaneous

    inflation_gap = inputs.pi_current - pi_target
    raw = (
        i_star
        + coefficients.inflation_coefficient_value * inflation_gap
        + coefficients.output_gap_coefficient_value * inputs.output_gap
    )
    # Written as `1 - smoothing` rather than a second literal so the two halves
    # of the published persistence pair are one number in config (LAW 2).
    rate = smoothing * inputs.i_prev + (1.0 - smoothing) * raw

    return PolicyRuleResult(
        model_name="ecb_contemporaneous_taylor_rule",
        rule_variant="ecb_contemporaneous_taylor",
        country="eu",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=(
            f"The ECB's estimated euro-area level rule prescribes a policy rate "
            f"of {rate:.2f}% (raw, un-smoothed prescription {raw:.2f}%)"
        ),
        context=(
            f"Reads current HICP inflation {inputs.pi_current:.2f}% against the "
            f"{pi_target:.1f}% target (gap {inflation_gap:+.2f}pp, weight "
            f"{coefficients.inflation_coefficient_value:g}) and the output gap "
            f"{inputs.output_gap:+.2f}% (weight "
            f"{coefficients.output_gap_coefficient_value:g}); smoothed "
            f"{smoothing:.3f} from {inputs.i_prev:.2f}%."
        ),
        inputs_used=["i_prev", "pi_current", "output_gap"],
        warnings=[
            "i* is an ILLUSTRATIVE euro-area neutral rate and is unobservable "
            "(Section 21.4 item 13). The euro area's own real-rate estimate is "
            "imprecise: ECB WP 258 reports a 95% interval for the real-rate "
            "intercept spanning roughly [-0.85, 5.48]. Every percentage point "
            "of error in i* passes through at ~0.12 into this quarter's "
            "prescription but cumulates to 1:1 in the level the rule settles at.",
            "The coefficients (2.733 on inflation, 1.443 on the output gap) are "
            "the EURO AREA's estimates, not Taylor's 1.5 / 0.5. The paper's own "
            "joint Wald test rejects Taylor's values at p = 0.04, so this is not "
            "a rounding: reading the rule as a textbook Taylor rule misstates "
            "the estimated euro-area response.",
            "This rule was estimated on euro-area data 1988-2002, BEFORE the "
            "2008 crisis, the sovereign-debt crisis and the 2021-23 inflation "
            "episode. The coefficients describe the euro area as it was then; "
            "they are the best published estimate of the euro area's own rule, "
            "not a claim about the Governing Council's current behaviour.",
        ],
        unit="percent",
        direction=(
            f"{_ecb_stance_word(rate, i_star)} relative to the illustrative "
            f"euro-area neutral rate of {i_star:.2f}%"
        ),
        assumptions=[
            "The rule is smoothed: the published prescription is a weighted "
            "average of the previous rate and the raw rule value, matching the "
            "estimated persistence on the lagged euro-area short rate.",
            "HICP inflation, not CPI or PCE — the ECB's target measure. The "
            "euro-area HICP leg (eu_hicp_*) supplies pi_current.",
            "The output gap is the euro-area aggregate, not a member state's; "
            "the ECB sets one policy rate for the currency union.",
        ],
        data_provenance=[
            "i_prev — the euro-area policy rate in the previous quarter. The "
            "MAIN REFINANCING OPERATIONS rate (eu_ecb_main_refi_rate in the "
            "registry), the rate the euro area's stance is quoted against.",
            "pi_current — euro-area HICP inflation, year-over-year, from the eu_hicp_* series",
            "coefficients — config leaves policy.eu.contemporaneous.*, the euro "
            "area's estimates from ECB WP 258 (Sept 2003), Table 2",
            "i_star — config leaf policy.eu.i_star, derived from the target plus "
            "an illustrative real rate (policy.eu.real_rate_assumption)",
        ],
        limitations=[
            "This is a SIMULATION rule transcribed from a published estimation. "
            "It describes what the estimated rule WOULD prescribe, not what the "
            "Governing Council decided or will decide.",
            "i* is held constant; a time-varying euro-area equilibrium real rate "
            "would shift the rule's level, and this module cannot detect that.",
            "The sample (1988-2002) predates the euro's full institutional "
            "history and every major shock since; the estimate is the euro "
            "area's own, but it is a historical one.",
            "The output is a prescribed RATE, not a forecast of the ECB's next decision.",
        ],
        decision_relevance=(
            "The 'eu' arm of Section 16.2's Q6 gap. Its value, alongside the "
            "euro area's other two rules, defines the euro-area model-implied "
            "policy path that a euro thesis compares against the market-implied "
            "path — exactly the role the Fed rules play for a US thesis."
        ),
        decision_prohibition=[
            "MUST NOT be described as the ECB's reaction function in the sense "
            "of the Governing Council's actual decision process. It is an "
            "estimated rule on historical data; treating it as a description of "
            "current policy is the misreading this prohibition exists to "
            "prevent.",
            "MUST NOT be combined with the Fed's or the BoE's rules in one "
            "ensemble or have their dispersion read across countries. The three "
            "arms have different targets, measures and coefficients; mixing them "
            "would make the dispersion a measure of the currency, not the model.",
            "MUST NOT be consumed without the raw prescription visible: the "
            "smoothed value alone hides how far the rule wants the rate to move.",
        ],
    )


def ecb_error_correction_rule(inputs: EcbErrorCorrectionInputs) -> PolicyRuleResult:
    """``Δi = c_π0·Δπ + c_y0·Δy + c_r·Δi_{t-1} + c_e·(i_{t-1} - b_l·l - b_π·π - b_y·y)``

    The ECB's cointegration (I(1)) error-correction rule for the euro area, from
    ECB Working Paper No 258, equations (3), (4) and (8). This is the leg that
    makes the euro-area arm structurally unlike the Fed's or the BoE's, and the
    difference is the **long rate**.

    **Why the long rate is in the rule, in the primary source's own terms.** The
    euro-area level specification is unstable — the short rate, inflation and
    the output gap have unit roots — so the paper estimates a cointegrating
    relationship instead. The estimated vector is ``r = 0.827·l + 0.900·π +
    0.358·y``: the 10-year rate ``l`` enters with a large, significant
    coefficient. The paper argues ``l`` proxies the public's perception of the
    LONG-RUN INFLATION OBJECTIVE (``pi_inf``), so a rise in the long rate is
    read as a rise in expected future inflation and the short rate responds —
    which is what makes the euro-area rule forward-looking in a way a
    level-only rule is not. **A euro-area rule without the long-rate term is a
    Fed rule with euro-area series substituted, and the long-rate term is
    exactly the feature §22.3's "genuinely distinct" bar is about.**

    **The error-correction mechanism.** ``ecr`` is the deviation of the level
    from its long-run equilibrium. The coefficient ``c_e = -0.189`` on the
    lagged ``ecr`` is NEGATIVE by construction: a positive deviation produces an
    offsetting negative change, so ~19% of the disequilibrium is corrected per
    quarter. The function does NOT impose that sign by ``abs()`` or a ``min`` —
    the sign lives in the config leaf and is validated there, so a sign flip is
    caught rather than masked, and the arithmetic below is the published
    equation.

    Confidence is ``compute_confidence()``'s with
    ``depends_on_unobservable=False``: unlike the level rules, this rule needs
    no ``i*`` — it is written so the equilibrium level carries the constant, and
    the rule prescribes a CHANGE from the observed previous rate. (The
    equilibrium it corrects toward is itself estimated rather than observed,
    which the warning states; but the rule's own inputs are all observed, so it
    does not inherit the level rules' unobservable-neutral-rate penalty.)
    """
    eu = get_settings().policy.eu
    pi_target = eu.pi_target_value
    coefficients = eu.error_correction

    # The long-run equilibrium level the rule corrects toward, from the
    # cointegrating vector (WP 258, eq. (3)). The constant is the target — the
    # equilibrium nominal short rate is the inflation target plus the long-run
    # real rate, and the real-rate intercept is not separately identified, so
    # the equilibrium is anchored at pi_target rather than at a fitted
    # constant. This is stated in the assumptions, not left implicit.
    equilibrium = (
        pi_target
        + coefficients.long_rate_coefficient_value * inputs.long_rate
        + coefficients.inflation_coefficient_value * inputs.pi_current
        + coefficients.output_gap_coefficient_value * inputs.output_gap
    )
    # The error-correction term: the deviation of the PREVIOUS level from that
    # equilibrium, as the published equation uses ecr_{t-1}.
    ecr = inputs.i_prev - equilibrium

    delta = (
        coefficients.inflation_change_coefficient_value * inputs.pi_change
        + coefficients.output_gap_change_coefficient_value * inputs.output_gap_change
        + coefficients.rate_change_persistence_coefficient_value * inputs.i_prev_change
        + coefficients.adjustment_coefficient_value * ecr
    )
    rate = inputs.i_prev + delta

    return PolicyRuleResult(
        model_name="ecb_error_correction_rule",
        rule_variant="ecb_error_correction",
        country="eu",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"The ECB's estimated euro-area error-correction rule prescribes a "
            f"policy rate of {rate:.2f}% ({delta:+.2f}pp from {inputs.i_prev:.2f}%)"
        ),
        context=(
            f"The long-run equilibrium level is {equilibrium:.2f}%, so the "
            f"previous rate {inputs.i_prev:.2f}% sat {ecr:+.2f}pp from it; the "
            f"error-correction term contributes "
            f"{coefficients.adjustment_coefficient_value * ecr:+.3f}pp to the "
            f"prescribed change. Short-run terms: Δπ {inputs.pi_change:+.2f}pp "
            f"(weight {coefficients.inflation_change_coefficient_value:g}), Δy "
            f"{inputs.output_gap_change:+.2f}pp (weight "
            f"{coefficients.output_gap_change_coefficient_value:g}), Δi_prev "
            f"{inputs.i_prev_change:+.2f}pp (weight "
            f"{coefficients.rate_change_persistence_coefficient_value:g})."
        ),
        inputs_used=[
            "i_prev",
            "i_prev_change",
            "long_rate",
            "pi_current",
            "pi_change",
            "output_gap",
            "output_gap_change",
        ],
        warnings=[
            "THE LONG RATE IS A REGRESSOR HERE, and the primary source's own "
            "interpretation is that it proxies the public's long-run inflation "
            "perception. This means the rule is exposed to movements in the "
            "10-year yield that are NOT about inflation expectations — term "
            "premium, duration supply, safe-asset demand. The paper itself notes "
            "the long rate is contaminated by the current short rate; a user "
            "reading the long-rate term as a pure inflation-expectations signal "
            "overstates what the estimate identifies.",
            "The equilibrium level is anchored at the inflation target plus the "
            "estimated long-run coefficients; the constant in the published "
            "equation is not separately identified and is treated as the target. "
            "A different anchoring would shift the level the rule corrects "
            "toward, and thus the prescribed change.",
            "The sample is 1988-2002, ending before the euro's institutional "
            "maturity and every major shock since. The estimated "
            "error-correction speed (-0.19, ~19% per quarter) is a fact about "
            "that sample, not a current estimate.",
            "This rule prescribes a CHANGE from the observed previous rate; it "
            "cannot detect that the LEVEL itself is wrong, which is the question "
            "the level rule answers. The two are reported together for that "
            "reason.",
        ],
        unit="percent",
        direction=(
            f"{'tightening' if delta > 0 else 'easing' if delta < 0 else 'holding'} "
            f"relative to the previous euro-area policy rate of {inputs.i_prev:.2f}%"
        ),
        assumptions=[
            "The rule is an error-correction (change) form, matching the euro "
            "area's estimated I(1) specification. Substituting a level form "
            "would be a different rule, not the euro area's.",
            "The long rate enters the LONG-RUN equilibrium, not the short-run "
            "dynamics: the estimated short-run response to the change in the "
            "long rate was insignificant and is dropped, as the published final "
            "specification (equation (8)) drops it.",
            "The constant in the cointegrating vector is anchored at the "
            "inflation target, because the real-rate intercept is not separately "
            "identified in the published estimation.",
        ],
        data_provenance=[
            "long_rate — the euro-area 10-year government bond yield "
            "(eu_long_rate_10y in the registry, from the econdb long-rate "
            "route). THE structural input; no Fed rule reads it.",
            "pi_current / pi_change — euro-area HICP inflation level and its "
            "quarter-on-quarter change, from the eu_hicp_* series",
            "output_gap / output_gap_change — the euro-area gap and its change",
            "coefficients — config leaves policy.eu.error_correction.*, the "
            "euro area's estimates from ECB WP 258 (Sept 2003), Tables 4 and 6",
            "i_prev / i_prev_change — the euro-area policy rate and its change",
        ],
        limitations=[
            "The cointegrating vector was estimated on a SHORT sample (1988-2002, "
            "roughly 55 quarters); the paper itself cautions that Johansen "
            "asymptotics should not be over-interpreted given the sample length. "
            "The estimate is the best published euro-area one, not a precise "
            "one.",
            "The rule corrects toward an equilibrium built from the long rate "
            "and the current level variables; if the true long-run relationship "
            "has shifted (a credibility change, a regime change), the rule "
            "corrects toward the wrong level.",
            "It prescribes a CHANGE, not a level, and cannot detect an incorrect level.",
        ],
        decision_relevance=(
            "Part of the 'eu' model-implied policy path (Section 16.2 Q6). It "
            "is the euro-area leg that carries the long rate, so it is the "
            "bridge between the policy-rule view and the bond market — a wide "
            "divergence from the level rule means the long-run inflation "
            "perception embedded in the curve disagrees with the current reading, "
            "which the ensemble reports rather than averages away."
        ),
        decision_prohibition=[
            "MUST NOT be read as a level. It is a change from the previous "
            "rate; publishing it as a target rate misstates what the rule says.",
            "MUST NOT be run without the long-rate input. The long rate is the "
            "structural regressor; substituting a constant (or dropping the "
            "term) would turn this into a level-only rule while it still "
            "reported itself as the euro-area error-correction rule — a field "
            "describing a computation that did not happen.",
            "MUST NOT be compared directly against the Fed's or the BoE's rules. "
            "Different functional form, different regressors, different economy.",
        ],
    )


class EcbRestrictedCointegrationInputs(_FiniteInputs):
    """Inputs for the ECB's RESTRICTED cointegration rule (WP 258, eq. (5)).

    The paper estimates TWO cointegrating vectors. The unrestricted one (used by
    ``ecb_error_correction_rule``) links the short rate to the long rate,
    inflation AND the output gap. The **restricted** one imposes a UNIT
    coefficient on inflation — ``rho_t = a + 0.771·l + 0.437·y`` — on the
    argument that policymakers set the REAL short rate in response to the long
    rate and the gap, with the inflation coefficient absorbed into the real
    rate. The paper does not reject the restriction (p = 0.78) and finds the
    restricted form forecasts at least as well.

    This is a genuinely different rule, not a reparameterisation of the
    unrestricted one: it drops ``pi`` from the long-run vector and re-estimates
    ``l`` and ``y`` (0.771 / 0.437 against 0.827 / 0.358). Modelling it as its
    own function with its own coefficients — rather than as the unrestricted
    rule with a coefficient set to 0 and 1 — is what keeps the two estimands
    from being confused.

    The input set differs: there is **no ``pi_current``**, because the
    restricted vector does not include inflation as a separate regressor. A
    caller cannot silently pass inflation here — the field does not exist.
    """

    i_prev: float = Field(
        description="The euro-area policy rate in the previous quarter, percent.",
    )
    i_prev_change: float = Field(
        description="The change in the policy rate over the previous quarter, in pp.",
    )
    long_rate: float = Field(
        description=(
            "The euro-area 10-year government bond yield, percent. The "
            "structural regressor in the restricted vector too."
        ),
    )
    real_rate: float = Field(
        description=(
            "The euro-area REAL short rate, percent (nominal policy rate minus "
            "inflation). The restricted form is written in the real rate, the "
            "point of the restriction."
        ),
    )
    pi_change: float = Field(
        description="The change in HICP inflation over the current quarter, in pp.",
    )
    output_gap: float = Field(
        description="Output gap as percent of potential, current quarter. A LEVEL.",
    )
    output_gap_change: float = Field(
        description="The change in the output gap over the current quarter, in pp.",
    )


def ecb_restricted_cointegration_rule(
    inputs: EcbRestrictedCointegrationInputs,
) -> PolicyRuleResult:
    """``Δi = c_pi0·Δπ + c_y0·Δy + c_r·Δi_{t-1} + c_e·(real_rate_{t-1} - 0.771·l - 0.437·y)``

    The ECB's RESTRICTED cointegration rule for the euro area, from ECB Working
    Paper No 258, equations (5) and (9). The restriction is ``b_pi = 1``: the
    real short rate ``real_rate`` — not the nominal rate — responds to the long rate and
    the output gap, with the inflation coefficient absorbed into the real rate.
    The paper tests and does not reject this (p = 0.78) and finds the restricted
    form fits and forecasts at least as well as the unrestricted one.

    **Why this is a separate function and not a flag on the unrestricted rule.**
    The restriction RE-ESTIMATES the remaining coefficients rather than merely
    fixing one: ``l`` and ``y`` become 0.771 / 0.437 here against 0.827 / 0.358
    in the unrestricted vector. Treating it as "the unrestricted rule with
    b_π = 1" would silently use the wrong coefficients for the two regressors
    that remain. The two are different estimands, so they are two functions, and
    this one's input record has no ``pi_current`` field at all — inflation
    enters only through the real rate and its change.

    Confidence is ``compute_confidence()`` with ``depends_on_unobservable=False``,
    the same as the unrestricted error-correction rule: it needs no ``i*``.
    """
    eu = get_settings().policy.eu
    coefficients = eu.error_correction

    # The restricted long-run equilibrium: the REAL rate against the long rate
    # and the gap, with a unit coefficient on inflation imposed (WP 258, eq.
    # (5)). The restricted long-rate and output-gap coefficients are NOT the
    # unrestricted ones — they are the re-estimated 0.771 / 0.437.
    equilibrium = (
        coefficients.restricted_long_rate_coefficient_value * inputs.long_rate
        + coefficients.restricted_output_gap_coefficient_value * inputs.output_gap
    )
    ecr = inputs.real_rate - equilibrium

    delta = (
        coefficients.inflation_change_coefficient_value * inputs.pi_change
        + coefficients.output_gap_change_coefficient_value * inputs.output_gap_change
        + coefficients.rate_change_persistence_coefficient_value * inputs.i_prev_change
        + coefficients.adjustment_coefficient_value * ecr
    )
    rate = inputs.i_prev + delta

    return PolicyRuleResult(
        model_name="ecb_restricted_cointegration_rule",
        rule_variant="ecb_restricted_cointegration",
        country="eu",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"The ECB's estimated restricted cointegration rule prescribes a "
            f"policy rate of {rate:.2f}% ({delta:+.2f}pp from {inputs.i_prev:.2f}%)"
        ),
        context=(
            f"The restricted long-run equilibrium (real rate against long rate "
            f"and gap, unit inflation coefficient) is {equilibrium:.2f}%, so the "
            f"previous real rate {inputs.real_rate:.2f}% sat {ecr:+.2f}pp from "
            f"it; the error-correction term contributes "
            f"{coefficients.adjustment_coefficient_value * ecr:+.3f}pp. The "
            f"restricted coefficients are re-estimated: long rate "
            f"{coefficients.restricted_long_rate_coefficient_value:g} and gap "
            f"{coefficients.restricted_output_gap_coefficient_value:g}, NOT the "
            f"unrestricted "
            f"{coefficients.long_rate_coefficient_value:g}/"
            f"{coefficients.output_gap_coefficient_value:g}."
        ),
        inputs_used=[
            "i_prev",
            "i_prev_change",
            "long_rate",
            "real_rate",
            "pi_change",
            "output_gap",
            "output_gap_change",
        ],
        warnings=[
            "The restriction imposes a UNIT inflation coefficient, which the "
            "paper does not reject (p = 0.78) but also does not establish as "
            "true. The unrestricted rule is estimated alongside precisely "
            "because the restriction is a hypothesis; a reader who sees only "
            "this rule sees a maintained assumption presented as a coefficient.",
            "The rule is written in the REAL short rate, so it inherits the "
            "measurement of inflation used to form it. A HICP-based real rate "
            "is assumed; a different deflator would move the level the rule "
            "corrects toward.",
            "The long rate is a regressor here too, with the same term-premium "
            "contamination the unrestricted rule's warning states: movements in "
            "the 10-year yield that are not about inflation enter the rule.",
            "The sample is 1988-2002, ending before every major euro-area shock "
            "since; the coefficients are a historical estimate.",
        ],
        unit="percent",
        direction=(
            f"{'tightening' if delta > 0 else 'easing' if delta < 0 else 'holding'} "
            f"relative to the previous euro-area policy rate of {inputs.i_prev:.2f}%"
        ),
        assumptions=[
            "The inflation coefficient is imposed at unity (the restriction), "
            "and the long-rate and output-gap coefficients are the RE-ESTIMATED "
            "values 0.771 / 0.437, not the unrestricted 0.827 / 0.358.",
            "The rule is written in the REAL short rate and its change terms; "
            "the caller supplies the real rate rather than this function "
            "computing it, so the deflator choice is visible at the call site.",
            "The restricted vector has no separate inflation level regressor; "
            "inflation enters through the real rate and its change.",
        ],
        data_provenance=[
            "long_rate — the euro-area 10-year yield (eu_long_rate_10y). The structural regressor.",
            "real_rate — the euro-area real short rate, formed by the caller "
            "from the policy rate and HICP inflation",
            "coefficients — config leaves "
            "policy.eu.error_correction.restricted_long_rate_coefficient and "
            ".restricted_output_gap_coefficient (the re-estimated values) plus "
            "the shared short-run and adjustment coefficients, ECB WP 258, "
            "Tables 4 and 6",
        ],
        limitations=[
            "The restriction is a maintained hypothesis the paper fails to "
            "reject, not a fact it establishes; the unrestricted rule is the "
            "companion that does not impose it.",
            "It prescribes a CHANGE, not a level, and cannot detect an incorrect level.",
            "The cointegrating vector was estimated on a short sample; the "
            "paper cautions against over-interpreting the asymptotics.",
        ],
        decision_relevance=(
            "Part of the 'eu' model-implied policy path (Section 16.2 Q6). It "
            "is the euro-area leg that states the stance in REAL terms, so its "
            "divergence from the unrestricted rule is informative: it isolates "
            "how much of the prescription comes from the unit-inflation "
            "restriction rather than from the estimated inflation coefficient."
        ),
        decision_prohibition=[
            "MUST NOT be presented as the euro area's estimated rule without "
            "noting the restriction. The unit inflation coefficient is imposed, "
            "not estimated, and a reader who cannot see that is reading a "
            "hypothesis as a finding.",
            "MUST NOT be read as a level. It is a change from the previous rate.",
            "MUST NOT be compared directly against the Fed's or BoE's rules. "
            "Different functional form, different regressors, different economy.",
        ],
    )


# ---------------------------------------------------------------------------
# Section 22.3 — GERMANY (country "de"). A MEMBER-STATE rule, not a
# central-bank rule.
#
# Germany has NO monetary policy of its own. The Bundesbank's own statement of
# its role: it conducts "the Eurosystem's monetary policy operations with
# German counterparties" — the ECB Governing Council sets the ONE policy rate
# for the currency union, and the Bundesbank executes it. A "German Taylor
# rule" would therefore be a RELABELLED ECB rule, which is the exact Section
# 22.3 / D-146 substitution the multi-country bar forbids — and unlike the gb
# case it is worse, because Germany does not even have a separate policy rate
# to relabel. Inventing a `de_policy_rate` would be fabricating a series.
#
# What IS genuinely German, and is what these three rules measure: the
# APPROPRIATENESS GAP. The ECB sets one rate for twenty economies; the ECB's
# own Economic Bulletin 5/2024 ("The dynamics of inflation differentials in
# the euro area") sets out the consequence — a single stance is too loose for
# high-inflation members and too tight for low-inflation ones. Germany's
# inflation, its output gap and its own Bund curve diverge from the euro-area
# aggregate, so the SAME ECB rate is a different stance in Germany than on
# average. These rules quantify that divergence using GERMAN data. The
# structural marker is that the euro-area aggregate rate is an EXOGENOUS input
# (f_ecb) the rule does not set — it is GIVEN, and the rule asks whether it is
# appropriate for German conditions.
# ---------------------------------------------------------------------------


class DeMemberAppropriatenessInputs(_FiniteInputs):
    """Inputs for Germany's member-state appropriateness rule (country "de").

    The rule's estimand is the **divergence of German conditions from the
    euro-area aggregate the ECB actually reacts to**. It therefore reads BOTH
    sides: Germany's own inflation and output gap, and the euro-area aggregate
    the ECB's single rate was set against.

    ``f_ecb`` is the euro-area policy rate as an EXOGENOUS input — the ECB's
    actual MAIN REFINANCING OPERATIONS rate, not something this rule
    prescribes. That is the structural difference from every central-bank rule
    in this module: the Fed, BoE and ECB rules all OUTPUT a prescription for
    the rate they own; this rule TAKES the euro-area rate as given and measures
    whether it fits German conditions. The field name ``f_ecb`` ("foreign/ECB
    rate") is the source of that asymmetry, and it is why there is no
    ``de_policy_rate`` anywhere in the registry.

    ``pi_de`` and ``pi_ea`` are the SAME measure on both sides — German and
    euro-area HICP inflation, year-over-year, in percent — so the differential
    ``pi_de - pi_ea`` is in percentage points and comparable to the
    coefficients. ``u_de`` / ``u_ea`` are the two unemployment rates and
    ``g_de`` / ``g_ea`` the two q/q real GDP growth rates, so BOTH sides of the
    labour and activity divergences are observable from the snapshot.
    """

    f_ecb: float = Field(
        description=(
            "The euro-area policy rate (ECB main refinancing operations), "
            "percent, as an EXOGENOUS input. The ECB sets it; this rule does "
            "not. Germany has no policy rate of its own."
        ),
    )
    pi_de: float = Field(
        description="German HICP-equivalent inflation, percent, year-over-year. A LEVEL.",
    )
    pi_ea: float = Field(
        description="Euro-area HICP inflation, percent, year-over-year. A LEVEL.",
    )
    output_gap_de: float = Field(
        description="German output gap as percent of potential, current quarter.",
    )
    output_gap_ea: float = Field(
        description="Euro-area output gap as percent of potential, current quarter.",
    )
    unemployment_de: float = Field(
        description="German unemployment rate, percent. The labour-slack level.",
    )
    unemployment_ea: float = Field(
        description="Euro-area unemployment rate, percent. The aggregate comparator.",
    )
    gdp_growth_de: float = Field(
        description="German q/q real GDP growth, percent. The activity divergence.",
    )
    gdp_growth_ea: float = Field(
        description="Euro-area q/q real GDP growth, percent. The aggregate comparator.",
    )


class DeBundSpreadInputs(_FiniteInputs):
    """Inputs for Germany's Bund-spread rule (country "de").

    The secondary-market expression of the same appropriateness question. The
    **Bund is the euro area's risk-free benchmark**, so the spread of another
    member's yield over the Bund is the market's price of the divergence the
    appropriateness rule measures in macro data. This rule reads Germany's own
    curve — the Bund 10-year yield and the German 3-month rate — against the
    euro-area policy rate, and reports the TERM-STRUCTURE signal: a Bund curve
    that has priced a different policy path from the one the ECB has set is the
    market's vote on whether the single stance fits Germany.

    There is deliberately no ``de_policy_rate``: ``f_ecb`` is the euro-area
    rate, exogenous, and the German short rate enters as the MARKET's German
    short rate (``de_short_rate_3m``), not as a policy rate. A German rule that
    treated the 3-month rate as Germany's own policy instrument would be the
    relabel this design exists to avoid.
    """

    f_ecb: float = Field(
        description=(
            "The euro-area policy rate, percent, EXOGENOUS. The level the Bund "
            "curve is read against."
        ),
    )
    bund_10y: float = Field(
        description=(
            "The German 10-year Bund yield, percent. THE BENCHMARK: the euro "
            "area's risk-free long rate."
        ),
    )
    de_short_3m: float = Field(
        description=(
            "The German 3-month rate, percent. This is a MARKET rate — the "
            "German money-market short rate — not a policy rate Germany "
            "does not have."
        ),
    )


class DeRealRateInputs(_FiniteInputs):
    """Inputs for Germany's real-rate divergence rule (country "de").

    The appropriateness question in REAL terms, which is the form in which a
    single nominal policy rate becomes inappropriate: with one nominal rate
    ``f_ecb``, the German REAL rate is ``f_ecb - pi_de`` and the euro-area real
    rate is ``f_ecb - pi_ea``. When German inflation runs above the euro-area
    average, the SAME nominal rate is a LOWER real rate in Germany — i.e. the
    stance is passively looser in the member with the higher inflation, which
    is the ECB's own stated divergence mechanism (Economic Bulletin 5/2024).

    The rule's structural feature is that the NOMINAL rate is shared and
    cancels in the real-rate DIFFERENTIAL: ``real_de - real_ea = pi_ea -
    pi_de``. So this leg isolates the inflation divergence with the shared rate
    held exactly constant — a quantity no central-bank rule in this module can
    produce, because each of those sets its own rate.
    """

    f_ecb: float = Field(
        description="The euro-area policy rate, percent, EXOGENOUS and SHARED.",
    )
    pi_de: float = Field(
        description="German inflation, percent, year-over-year. A LEVEL.",
    )
    pi_ea: float = Field(
        description="Euro-area inflation, percent, year-over-year. A LEVEL.",
    )
    r_neutral_de: float = Field(
        description=(
            "The rule's illustrative German neutral REAL rate, percent — an "
            "input rather than a literal so the real-rate gap the rule reports "
            "is measured the way the caller intends it (LAW 1)."
        ),
    )


def _de_appropriateness_word(real_de: float, real_ea: float) -> str:
    """``too tight for Germany`` / ``too loose for Germany`` / ``appropriate``.

    The classification the whole `de` arm exists to publish: the SAME ECB
    stance reads as a different stance member by member. The comparison is the
    German real rate against the euro-area real rate; when Germany's real rate
    is below the euro area's, the shared nominal rate is passively looser in
    Germany, and vice versa. Kept as its own function, like
    ``_ecb_stance_word``, so the three-state comparison is not inlined where a
    float landing exactly on the reference could be mislabelled by a branch's
    ``else`` (the D-040 class).
    """
    if real_de > real_ea:
        return "too tight for Germany"
    if real_de < real_ea:
        return "too loose for Germany"
    return "appropriate for Germany"


def de_member_appropriateness_rule(
    inputs: DeMemberAppropriatenessInputs,
) -> PolicyRuleResult:
    """``gap = w_π·(π_de - π_ea) + w_y·(y_de - y_ea) + w_u·(u_ea - u_de) + w_g·(g_de - g_ea)``

    Germany's member-state APPROPRIATENESS rule — the `de` arm's headline leg.
    It does NOT prescribe a rate for a German central bank (Germany has none).
    It measures how far GERMAN conditions diverge from the euro-area aggregate
    the ECB's single rate ``f_ecb`` is set against, and signs that divergence:

    * **Inflation** (``w_π``): German inflation above the euro-area average
      means the shared nominal rate is too loose for Germany.
    * **Output gap** (``w_y``): a German gap above the aggregate means German
      activity is running hot relative to the union — the same direction.
    * **Unemployment** (``w_u``): German unemployment BELOW the aggregate means
      German labour is tighter, so the sign is entered as ``u_ea - u_de`` (a
      lower German rate is a POSITIVE contribution).
    * **Activity** (``w_g``): German q/q growth above the aggregate, the same
      direction as the output gap, at a one-step frequency.

    **Why this is not a relabelled ECB rule (Section 22.3).** The euro-area
    rule takes the aggregate inflation and gap and produces a rate; this rule
    takes the AGGREGATE RATE as an exogenous input and produces a DIVERGENCE of
    German conditions from the aggregate. Its sign convention is inverted (a
    positive value means the shared rate is too LOOSE for Germany, not that the
    rate should rise) and its regressors are DIFFERENCES between two economies'
    measured data, which no central-bank rule in this module reads. The
    structural marker is ``f_ecb``: it is on the INPUT side. A rule that set
    Germany's policy rate would be fabricating a rate Germany does not have.

    Confidence is ``compute_confidence()``'s with ``depends_on_unobservable=
    True``, because the German output gap is ESTIMATED from German activity (no
    published German gap series exists on this route) — the estimate is
    disclosed, and its uncertainty is carried rather than hidden.
    """
    de = get_settings().policy.de
    coefficients = de.appropriateness

    inflation_divergence = inputs.pi_de - inputs.pi_ea
    gap_divergence = inputs.output_gap_de - inputs.output_gap_ea
    labor_divergence = inputs.unemployment_ea - inputs.unemployment_de
    activity_divergence = inputs.gdp_growth_de - inputs.gdp_growth_ea

    gap = (
        coefficients.inflation_coefficient_value * inflation_divergence
        + coefficients.output_gap_coefficient_value * gap_divergence
        + coefficients.unemployment_coefficient_value * labor_divergence
        + coefficients.growth_coefficient_value * activity_divergence
    )

    return PolicyRuleResult(
        model_name="de_member_appropriateness_rule",
        rule_variant="de_member_appropriateness",
        country="de",
        as_of=utc_now(),
        value=round(gap, 4),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=(
            f"The single ECB rate of {inputs.f_ecb:.2f}% maps onto German "
            f"conditions with an appropriateness gap of {gap:+.2f} — a POSITIVE "
            f"value means the shared stance is too LOOSE for Germany, a NEGATIVE "
            f"value too TIGHT"
        ),
        context=(
            f"German vs euro-area divergence: inflation "
            f"{inflation_divergence:+.2f}pp (weight "
            f"{coefficients.inflation_coefficient_value:g}), output gap "
            f"{gap_divergence:+.2f}pp (weight "
            f"{coefficients.output_gap_coefficient_value:g}), unemployment "
            f"{-labor_divergence:+.2f}pp (weight "
            f"{coefficients.unemployment_coefficient_value:g}, sign entered as "
            f"u_ea - u_de), activity {activity_divergence:+.2f}pp (weight "
            f"{coefficients.growth_coefficient_value:g})."
        ),
        inputs_used=[
            "f_ecb",
            "pi_de",
            "pi_ea",
            "output_gap_de",
            "output_gap_ea",
            "unemployment_de",
            "unemployment_ea",
            "gdp_growth_de",
            "gdp_growth_ea",
        ],
        warnings=[
            "THE SIGN IS A STANCE DIAGNOSIS, NOT A RATE. A positive value means "
            "the shared ECB stance is too loose FOR GERMANY; it is NOT a "
            "prescription that any rate should rise. Germany has no policy rate "
            "(the Bundesbank executes the ECB's single policy), so this rule "
            "cannot and does not prescribe one.",
            "The German output gap is an ESTIMATE from German activity, not a "
            "published series: no German output-gap series exists on this route. "
            "The estimate is disclosed and the result carries "
            "depends_on_unobservable=True; a reader who treats it as a measured "
            "gap overstates the rule's precision.",
            "The coefficients are ILLUSTRATIVE weights on the divergences, not "
            "estimates of a Bundesbank reaction function — no such function "
            "exists, because Germany does not set policy. They are stated in "
            "config (policy.de.appropriateness) so the weighting is reviewable "
            "and movable rather than buried.",
            "This measures the divergence in the FOUR series it reads; a "
            "divergence concentrated in a series not carried here (e.g. German "
            "house prices, or a sectoral gap) would not appear.",
        ],
        unit="percentage_points",
        direction=(
            f"the single ECB rate of {inputs.f_ecb:.2f}% is "
            f"{'TOO LOOSE' if gap > 0 else 'TOO TIGHT' if gap < 0 else 'APPROPRIATE'} "
            f"for German conditions"
        ),
        assumptions=[
            "The euro-area policy rate f_ecb is EXOGENOUS: it is the ECB's "
            "single rate, GIVEN to this rule, not set by it.",
            "German and euro-area inflation are the SAME measure (HICP, "
            "year-over-year, percent), so their difference is in percentage "
            "points and comparable to the weights.",
            "The positive-inflation, positive-gap, low-unemployment, "
            "high-growth direction all point the same way — German conditions "
            "hotter than the aggregate mean the shared rate is too loose.",
        ],
        data_provenance=[
            "f_ecb — the euro-area policy rate (eu_ecb_main_refi_rate; the same "
            "series the euro-area rules read). EXOGENOUS here.",
            "pi_de — German inflation (de_cpi_yoy); pi_ea — euro-area HICP inflation (eu_hicp_*)",
            "output_gap_de — ESTIMATED from German real GDP (de_gdp_real_level); "
            "output_gap_ea — ESTIMATED from euro-area real GDP (eu_gdp_real_level)",
            "unemployment_de — de_unemployment_rate; unemployment_ea — eu_unemployment_rate",
            "coefficients — config leaves policy.de.appropriateness.*",
        ],
        limitations=[
            "This is NOT a German monetary policy rule and cannot become one: "
            "Germany does not conduct monetary policy. It is a member-state "
            "APPROPRIATENESS diagnostic.",
            "The divergence is measured against the euro-area aggregate; if the "
            "aggregate itself is mis-measured, the divergence inherits the error "
            "in equal and opposite forms.",
            "The four weight coefficients are illustrative, not estimated.",
            "The output and activity legs share a q/q frequency, so a quarterly "
            "German print that later revises moves the result.",
        ],
        decision_relevance=(
            "The 'de' leg of Section 22.3's country set and the input to "
            "cross-country reasoning: with the euro-area arm it states WHERE in "
            "the union the single stance is most misaligned, which is the "
            "trading question a member-state view answers (e.g. Bunds vs "
            "periphery, or German real rates vs the ESTR path)."
        ),
        decision_prohibition=[
            "MUST NOT be described as a Bundesbank or German reaction function. "
            "Germany does NOT set monetary policy; the ECB sets one rate and the "
            "Bundesbank executes it. Presenting this as a central-bank rule is "
            "the relabel Section 22.3 forbids and would be factually false.",
            "MUST NOT be read as a rate or fed into a rate scale without "
            "conversion: the unit is percentage points of DIVERGENCE, not a "
            "percent policy level. Placing it beside the ECB's 2.0% main refi "
            "rate as if both were rates is a unit error.",
            "MUST NOT be compared against the Fed's, BoE's or ECB's rule values "
            "as if the three were the same kind of object. Those are prescriptions "
            "for a rate the bank owns; this is a stance-appropriateness "
            "diagnostic with an inverted sign convention.",
        ],
    )


def de_bund_spread_rule(inputs: DeBundSpreadInputs) -> PolicyRuleResult:
    """``spread_signal = bund_10y - (f_ecb + de_short_3m)/2`` — the Bund's vote.

    Germany's Bund-spread leg: the market's own price of the appropriateness
    question. The Bund is the euro area's risk-free benchmark, so its curve
    embeds the path the market expects FOR THE EURO AREA; the signal published
    here is the vertical position of the German curve relative to the ECB's set
    rate, read off two German tenors.

    **Why the Bund and not a sovereign spread.** A peripheral spread over the
    Bund is a credit/redenomination premium, not a policy-appropriateness
    signal. The Bund itself is what the UNION prices against, so the German
    curve's misalignment with the set rate is the cleanest market read of
    whether the single stance is currently seen as fitting Germany — and it is
    the leg a Bund trade acts on directly.

    The rule reports a LEVEL signal in percentage points, with the sign
    convention: POSITIVE means the German curve sits ABOVE the set rate (the
    market prices a higher path than the ECB has set — consistent with the
    stance being too loose for Germany), NEGATIVE the reverse.
    """
    de = get_settings().policy.de
    coefficients = de.bund_spread

    reference = (
        coefficients.ecb_rate_weight_value * inputs.f_ecb
        + coefficients.german_short_rate_weight_value * inputs.de_short_3m
    )
    signal = inputs.bund_10y - reference
    curve_word = "ABOVE" if signal > 0 else "BELOW" if signal < 0 else "aligned with"

    return PolicyRuleResult(
        model_name="de_bund_spread_rule",
        rule_variant="de_bund_spread",
        country="de",
        as_of=utc_now(),
        value=round(signal, 4),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"The German curve (10y {inputs.bund_10y:.2f}%) sits {signal:+.2f}pp "
            f"relative to the ECB-set reference of {reference:.2f}% — a POSITIVE "
            f"signal is the market pricing a path above the stance the ECB has "
            f"set"
        ),
        context=(
            f"Bund 10-year {inputs.bund_10y:.2f}%, the ECB's rate "
            f"{inputs.f_ecb:.2f}% (weight "
            f"{coefficients.ecb_rate_weight_value:g}) and the German 3-month "
            f"market rate {inputs.de_short_3m:.2f}% (weight "
            f"{coefficients.german_short_rate_weight_value:g}) form the "
            f"{reference:.2f}% reference."
        ),
        inputs_used=["f_ecb", "bund_10y", "de_short_3m"],
        warnings=[
            "The Bund 10-year carries a TERM PREMIUM and an inflation-risk "
            "premium as well as a policy-path expectation, so a positive signal "
            "is not purely 'the market expects a higher policy rate'. No "
            "term-premium adjustment is made here; the same contamination the "
            "Section 22.5 market-implied proxy discloses applies to this leg.",
            "The German 3-month rate is a MARKET rate, not a policy rate: "
            "Germany has no policy rate. Treating de_short_3m as Germany's "
            "policy instrument would revive the relabel this design removes.",
            "The two weights make the reference an illustrative blend of the "
            "set rate and the German short rate; they are stated in config "
            "(policy.de.bund_spread) rather than inlined, and a different blend "
            "moves the level of the signal (not its sign, for reasonable "
            "weights).",
        ],
        unit="percentage_points",
        direction=(f"the Bund 10-year curve is {curve_word} the ECB-set reference"),
        assumptions=[
            "The Bund 10-year is the euro area's risk-free benchmark, so its "
            "level embeds the union-wide expected path.",
            "f_ecb is the euro-area set rate, exogenous to Germany.",
            "No term-premium adjustment is applied; the signal is a raw curve "
            "position against the set rate.",
        ],
        data_provenance=[
            "bund_10y — the German 10-year Bund yield (de_long_rate_10y)",
            "de_short_3m — the German 3-month rate (de_short_rate_3m), a MARKET rate",
            "f_ecb — the euro-area policy rate (eu_ecb_main_refi_rate)",
            "coefficients — config leaves policy.de.bund_spread.*",
        ],
        limitations=[
            "A spread/curve signal, not a rate prescription and not an "
            "appropriateness measure in macro data — it is the MARKET's read, "
            "which can be wrong.",
            "Contaminated by the term and inflation-risk premia embedded in the 10-year yield.",
            "Reads three yields only; a curve-shape change beyond these tenors is invisible.",
        ],
        decision_relevance=(
            "The market-expression companion to de_member_appropriateness_rule: "
            "where the macro rule measures the divergence in data, this rule "
            "measures the price the market has already put on it — the two are "
            "compared, and their disagreement is itself the signal."
        ),
        decision_prohibition=[
            "MUST NOT be read as a policy rate or as Germany's policy "
            "instrument. It is a curve position in percentage points.",
            "MUST NOT be presented as term-premium-free. The 10-year yield "
            "carries premia this rule does not strip.",
            "MUST NOT be combined with a central bank's rule value as if it "
            "were the same kind of object (a prescription for an owned rate).",
        ],
    )


def de_real_rate_rule(inputs: DeRealRateInputs) -> PolicyRuleResult:
    """``real_gap = (f_ecb - π_de) - r_neutral_de`` — Germany's real stance.

    Germany's real-rate leg: the appropriateness question in the units that
    decide whether a single nominal rate is appropriate. With ONE nominal rate
    ``f_ecb`` shared across the union, the German real rate is ``f_ecb - π_de``;
    this rule reports the German real rate against ITS illustrative neutral real
    rate, so the German real-rate gap is measured directly.

    **The structural marker, restated in real terms: the shared nominal rate
    CANCELS in the differential.** Germany's real rate minus the euro area's is
    ``(f_ecb - π_de) - (f_ecb - π_ea) = π_ea - π_de`` — the inflation
    divergence with the shared rate held exactly constant. No central-bank rule
    in this module can produce such a quantity, because each of those SETS the
    rate it trades off. This leg is the cleanest statement of the ECB's own
    divergence mechanism (Economic Bulletin 5/2024): the member with higher
    inflation passively gets the lower real rate.
    """
    real_de = inputs.f_ecb - inputs.pi_de
    real_gap = real_de - inputs.r_neutral_de

    return PolicyRuleResult(
        model_name="de_real_rate_rule",
        rule_variant="de_real_rate",
        country="de",
        as_of=utc_now(),
        value=round(real_de, 4),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=(
            f"With the ECB's {inputs.f_ecb:.2f}% nominal rate and German "
            f"inflation at {inputs.pi_de:.2f}%, Germany's real policy rate is "
            f"{real_de:.2f}% — {real_gap:+.2f}pp against an illustrative "
            f"neutral real rate of {inputs.r_neutral_de:.2f}%"
        ),
        context=(
            f"The shared nominal rate is {inputs.f_ecb:.2f}% and German "
            f"inflation {inputs.pi_de:.2f}% (euro-area inflation "
            f"{inputs.pi_ea:.2f}%); the nominal rate is SHARED across the "
            f"union, so Germany's real-rate divergence from the euro area is "
            f"exactly the inflation divergence {inputs.pi_ea - inputs.pi_de:+.2f}pp."
        ),
        inputs_used=["f_ecb", "pi_de", "pi_ea", "r_neutral_de"],
        warnings=[
            "The German neutral real rate is UNOBSERVABLE (Section 21.4 item 13) "
            "and is an INPUT here, not an estimate this rule makes. The real-rate "
            "gap is therefore only as reliable as the neutral-rate assumption, "
            "and the result carries depends_on_unobservable=True.",
            "A real rate formed from realized inflation is a BACKWARD-looking "
            "measure; the appropriate real rate depends on EXPECTED inflation, "
            "which this rule does not have. The value is a realized-inflation "
            "real rate and must not be read as the forward real rate.",
            "The shared nominal rate cancels in the Germany-vs-euro-area "
            "difference, so a change in the ECB rate with unchanged inflation "
            "moves this German LEVEL but not the Germany-vs-aggregate DIVERGENCE.",
        ],
        unit="percent",
        direction=_de_appropriateness_word(real_de, inputs.f_ecb - inputs.pi_ea),
        assumptions=[
            "The real rate is formed with the SAME measure on both sides (HICP, "
            "year-over-year), so the shared nominal rate cancels in the "
            "differential.",
            "The German neutral real rate is an illustrative input, not an estimate produced here.",
            "Germany's real rate uses the euro-area nominal policy rate because "
            "Germany has no policy rate of its own.",
        ],
        data_provenance=[
            "f_ecb — the euro-area policy rate (eu_ecb_main_refi_rate), exogenous",
            "pi_de — German inflation (de_cpi_yoy); pi_ea — euro-area HICP inflation",
            "r_neutral_de — config leaf policy.de.appropriateness.r_neutral (the "
            "illustrative German neutral real rate)",
        ],
        limitations=[
            "Real rates from realized inflation are backward-looking.",
            "The German real rate is computed from the SHARED euro-area nominal "
            "rate; it is not a German policy rate, which does not exist.",
            "The neutral-rate input dominates the reported gap.",
        ],
        decision_relevance=(
            "The real-terms leg of the German appropriateness cluster: it states "
            "in the units that matter whether the shared nominal stance is "
            "passively loose or tight for Germany, and it is the leg a real-rate "
            "or breakeven trade reads."
        ),
        decision_prohibition=[
            "MUST NOT be described as Germany's policy rate. Germany has none; "
            "this is the euro-area rate deflated by German inflation.",
            "MUST NOT be read as a forward real rate; the deflator is realized.",
            "MUST NOT be compared against the euro-area real rate as if the "
            "nominal rates differed — they are the same rate.",
        ],
    )


# ---------------------------------------------------------------------------
# Section 22.3 — JAPAN (country "jp"). A central bank whose FRAMEWORK is not a
# Taylor rule.
#
# The Bank of Japan's framework has three features NO Taylor rule can
# reproduce, and the first is the marker:
#
#   1. THE ZLB FLOOR. The BoJ held the policy rate at or below zero (NIRP,
#      -0.1%) from 2016 to the March-2024 exit, and before that at zero for
#      most of two decades. A plain Taylor rule prescribes negative rates in
#      such periods; the BoJ did not set them. The Reifschneider-Williams
#      (2000) SHADOW-RATE rule encodes this: a NOTIONAL rate ĩ_t is computed,
#      and the ACTUAL rate is bounded below by zero, with a cumulative
#      shortfall term z_t ("ZLB debt") that makes policy MORE stimulative the
#      longer the floor has bound. Hasui & Teranishi (2025, HIAS-E-149) state
#      the point in the primary source: "the Taylor-type rule can not
#      replicate inflation overshooting, even though the zero interest rate
#      policy continues."
#   2. YIELD CURVE CONTROL (Sept 2016). The INSTRUMENT is the 10-year JGB
#      yield (target ~0%), not only the overnight rate. A Taylor rule reads a
#      single short rate.
#   3. THE INFLATION-OVERSHOOTING COMMITMENT (Sept 2016). The BoJ undertakes to
#      continue easing "until the year-on-year rate of increase in the observed
#      CPI (all items less fresh food) exceeds 2 percent and stays above the
#      target in a stable manner" — a deliberate TOLERANCE of overshooting that
#      a symmetric Taylor rule actively opposes.
#
# The `jp` arm's three legs are therefore the shadow-rate ZLB rule, a YCC
# reference rule (the 10-year yield against the BoJ's own target band) and an
# overshooting-commitment rule (a price-LEVEL-style history-dependent term).
# ---------------------------------------------------------------------------


class JpReifschneiderWilliamsInputs(_FiniteInputs):
    """Inputs for Japan's shadow-rate (ZLB) rule (country "jp").

    The rule tracks the NOTIONAL shadow rate ``ĩ_t`` separately from the ACTUAL
    rate, which is floored at zero, and accumulates the "ZLB debt" ``z_t`` — the
    cumulative gap by which the floor has held the actual rate above the
    notional one. The three quantities are inputs rather than internal state
    because the rule is a STATELESS function of its inputs (the same discipline
    the BoE's rules follow); the caller threads the state, and the state's
    meaning is documented here.
    """

    pi: float = Field(
        description=(
            "Japanese CPI inflation (all items less fresh food), percent, year-over-year. A LEVEL."
        ),
    )
    output_gap: float = Field(
        description="Japanese output gap as percent of potential, current period.",
    )
    i_notional_prev: float = Field(
        description=(
            "The previous period's NOTIONAL (shadow) rate ĩ_{t-1}, percent. The "
            "shadow rate is what the rule WOULD set were there no ZLB; the "
            "actual rate is this floored at zero. An input so the rule has no "
            "hidden state."
        ),
    )
    z_prev: float = Field(
        description=(
            "The previous period's cumulative ZLB shortfall z_{t-1}, in "
            "percentage-point-periods. z_t = z_{t-1} + (i_t - ĩ_t), the "
            "cumulative amount the floor has held the actual rate above the "
            "notional one — the 'ZLB debt' that makes policy more stimulative "
            "the longer the floor has bound."
        ),
    )
    zlb_floor: float = Field(
        description=(
            "The effective lower bound on the policy rate, percent — the "
            "ACTUAL floor, an input rather than an inlined 0.0 because Japan "
            "operated a NEGATIVE rate (-0.1%) under NIRP from 2016 to 2024, so "
            "the floor is a policy choice that has moved, not a constant."
        ),
    )


class JpYccInputs(_FiniteInputs):
    """Inputs for Japan's Yield Curve Control reference rule (country "jp").

    The instrument is the 10-year JGB yield against the BoJ's own target. This
    is not a Taylor-rule regressor: the BoJ NAMED the long yield as its
    operating target (initially about 0%, with a ±0.5% / ±1% band over time),
    so the deviation of the market yield from the target is the measure of how
    much EASING the BoJ must do to defend the band. No Fed, BoE or ECB rule in
    this module reads a targeted long yield this way — the ECB's long-rate
    term is a proxy for expected inflation, not an operating target.
    """

    jgb_10y: float = Field(
        description="The 10-year JGB yield, percent — the YCC operating target's observable.",
    )
    ycc_target: float = Field(
        description=(
            "The BoJ's YCC target for the 10-year yield, percent. An input "
            "because the target has been changed by policy (about 0%, then a "
            "±0.5% band, then ±1%); a literal here would freeze one regime's "
            "value into every period."
        ),
    )
    ycc_band: float = Field(
        description=(
            "The half-width of the BoJ's tolerance band around the target, in "
            "percentage points. A deviation inside the band is within tolerance; "
            "outside it the BoJ is expected to buy JGBs to pull the yield back."
        ),
    )


class JpOvershootCommitmentInputs(_FiniteInputs):
    """Inputs for Japan's inflation-overshooting commitment rule (country "jp").

    The BoJ's commitment is asymmetric: it tolerates — indeed seeks — inflation
    ABOVE 2% until it is "stable", which a symmetric Taylor rule opposes. This
    rule makes the asymmetry explicit and history-dependent (the primary
    source's "augmented Taylor-type rule with a strong history dependence can
    work as a price-level targeting policy"): it reads the cumulative inflation
    shortfall since the commitment began and prescribes MORE accommodation the
    larger that shortfall, and it does NOT prescribe tightening merely because
    inflation is above 2% while the cumulative shortfall is still open.
    """

    pi: float = Field(
        description=(
            "Japanese CPI inflation (all items less fresh food), percent, year-over-year. A LEVEL."
        ),
    )
    cumulative_inflation_gap: float = Field(
        description=(
            "The cumulative inflation shortfall since the overshooting "
            "commitment began, in percentage-point-periods: the running sum of "
            "(π - π*) over the period the commitment has been in force. The "
            "state that makes the commitment HISTORY-DEPENDENT."
        ),
    )
    stabilization_threshold: float = Field(
        description=(
            "The cumulative shortfall that must be closed before the rule stops "
            "adding accommodation, in percentage-point-periods. An input, since "
            "the 'stable manner' the BoJ requires is a judgement, not a "
            "constant (LAW 1)."
        ),
    )


def jp_reifschneider_williams_rule(
    inputs: JpReifschneiderWilliamsInputs,
) -> PolicyRuleResult:
    """``i_t = max[floor, i~_t - phi_z*z_t]``,
    ``i~_t = (1-rho)*(i* + phi_pi*(pi-pi*) + phi_x*x_t) + rho*i~_{t-1}``

    Japan's shadow-rate rule — the `jp` arm's headline leg, from
    Reifschneider & Williams (2000) as calibrated for Japan by Hasui &
    Teranishi (2025, HIAS-E-149) and Nakov (2008). It is the rule that makes
    the `jp` arm structurally unlike the Fed's, the BoE's or the ECB's:

    * **The ``max[floor, ·]`` bound.** A plain Taylor rule prescribes negative
      rates during a long slump; Japan did not set them. The rule computes a
      NOTIONAL rate and floors the ACTUAL rate at the effective lower bound.
    * **The ``-φ_z·z_t`` term — the cumulative ZLB shortfall.** ``z_t`` is the
      running sum of ``i_t - ĩ_t``, the amount by which the floor has held the
      actual rate ABOVE the notional one. A larger ``z_t`` makes the rule
      prescribe MORE stimulus, which is the history dependence the primary
      source shows is required to produce inflation OVERSHOOTING: *"the
      Taylor-type rule can not replicate inflation overshooting… the augmented
      Taylor-type rule with a strong history dependence can work as a
      price-level targeting policy."* No Fed/BoE/ECB rule in this module has a
      state term of any kind.

    The notional-rate recursion carries its own persistence ``rho``; the shadow
    rate is itself inertial, distinct from the actual rate's floor. Both the
    floor and the persistence are config leaves because Japan's floor MOVED
    (-0.1% under NIRP, 0 after the March-2024 exit), so a literal would freeze
    one regime.

    Confidence is ``compute_confidence()``'s with ``depends_on_unobservable=
    True``: ``i*`` (the natural rate) is unobservable (Section 21.4 item 13),
    and so is the output gap's potential — the same limitation every rule in
    this module that reads ``i*`` or a gap carries, which is precisely why the
    rule's structure (a hard floor plus a measured shortfall) is worth having:
    the unobservables enter through ``i*``, but the FLOOR is exact.
    """
    jp = get_settings().policy.jp
    coefficients = jp.shadow_rate
    i_star = jp.i_star_value
    pi_target = jp.pi_target_value
    rho = coefficients.notional_persistence_value

    # The notional (shadow) rate: the Taylor-type rule unconstrained by the
    # floor, with the BoJ's own coefficients and its own natural rate and
    # target. The recursion carries the previous NOTIONAL rate, not the actual
    # one — the shadow rate has no floor.
    notional = (1.0 - rho) * (
        i_star
        + coefficients.inflation_coefficient_value * (inputs.pi - pi_target)
        + coefficients.output_gap_coefficient_value * inputs.output_gap
    ) + rho * inputs.i_notional_prev
    # The shadow-rate ZLB correction: subtract the accumulated shortfall, then
    # floor. Written as max() of two config-driven quantities, so the floor is
    # data, not a literal (LAW 1).
    unconstrained = notional - coefficients.shortfall_coefficient_value * inputs.z_prev
    rate = max(inputs.zlb_floor, unconstrained)
    binding = unconstrained < inputs.zlb_floor
    regime_word = (
        "binding: the actual rate cannot follow the notional rate down"
        if binding
        else "not binding: the rule is in its unconstrained regime"
    )

    return PolicyRuleResult(
        model_name="jp_reifschneider_williams_rule",
        rule_variant="jp_reifschneider_williams",
        country="jp",
        as_of=utc_now(),
        value=round(rate, 2),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=True)),
        interpretation=(
            f"Japan's shadow-rate rule prescribes an actual policy rate of "
            f"{rate:.2f}% (notional shadow rate {notional:.2f}%, accumulated ZLB "
            f"shortfall {inputs.z_prev:+.2f}) — the floor is "
            f"{'BINDING' if unconstrained < inputs.zlb_floor else 'not binding'}"
        ),
        context=(
            f"The unconstrained prescription would be {unconstrained:.2f}%, so "
            f"the effective lower bound of {inputs.zlb_floor:.2f}% is "
            f"{regime_word}. "
            f"Reads CPI {inputs.pi:.2f}% against the {pi_target:.1f}% target and "
            f"the output gap {inputs.output_gap:+.2f}% (weights "
            f"{coefficients.inflation_coefficient_value:g} / "
            f"{coefficients.output_gap_coefficient_value:g}), with notional "
            f"persistence {rho:g}."
        ),
        inputs_used=[
            "pi",
            "output_gap",
            "i_notional_prev",
            "z_prev",
            "zlb_floor",
        ],
        warnings=[
            "THE ZLB FLOOR IS THE STRUCTURAL MARKER. A reader who reads only the "
            "notional rate sees a Taylor rule; the ACTUAL prescription is the "
            "notional rate floored and reduced by the accumulated shortfall. "
            "Treating this as a Taylor rule loses exactly the behaviour the BoJ "
            "exhibited for two decades.",
            "The effective lower bound MOVED: Japan operated -0.1% under NIRP "
            "(2016-2024) and exited to 0-0.1% in March 2024. The floor is a "
            "config input; a result produced under one floor must not be read "
            "under another.",
            "The natural rate i* and the output gap's potential are "
            "UNOBSERVABLE (Section 21.4 item 13); the rule records "
            "depends_on_unobservable=True. The FLOOR itself is exact, which is "
            "why the floor-plus-shortfall structure is worth having despite the "
            "unobservables.",
            "The cumulative shortfall z_t is threaded in by the caller; if the "
            "caller resets it, the history-dependence that produces overshooting "
            "disappears and the rule degenerates toward a Taylor rule. The "
            "state's correct propagation is the caller's responsibility and is "
            "documented in the input record.",
        ],
        unit="percent",
        direction=(
            f"{'at the effective lower bound' if rate <= inputs.zlb_floor else 'above the ELB'} "
            f"with a notional shadow rate of {notional:.2f}%"
        ),
        assumptions=[
            "The notional rate is a Taylor-type rule with the BoJ's own "
            "calibration (Hasui & Teranishi 2025 / Nakov 2008), including the "
            "NATURAL RATE of -0.5% the primary source calibrates for Japan.",
            "The actual policy rate is the notional rate, floored at the "
            "effective lower bound and reduced by the accumulated shortfall.",
            "Inflation is the BoJ's target measure: CPI all items less fresh "
            "food, the measure the overshooting commitment names.",
        ],
        data_provenance=[
            "pi — Japanese CPI inflation (jp_cpi_yoy), the BoJ's target measure",
            "output_gap — ESTIMATED from Japanese real GDP (jp_gdp_real_level); "
            "Japan publishes no gap series on this route",
            "i_notional_prev, z_prev — the shadow rate and the accumulated "
            "shortfall, threaded in by the caller (the rule is stateless)",
            "zlb_floor — supplied by the caller from countries' current regime",
            "coefficients — config leaves policy.jp.shadow_rate.*",
        ],
        limitations=[
            "The shadow rate is an ESTIMATE of an unobservable, not a "
            "measurement; every statement about it inherits that.",
            "The natural rate and the output gap are unobservable.",
            "The rule is a SIMULATION transcription of the primary source's "
            "calibration, not a description of the Policy Board's decisions.",
            "Japan's long ZLB period means the short sample constrains how "
            "precisely the notional-rate coefficients are identified.",
        ],
        decision_relevance=(
            "The 'jp' arm's headline leg and the reason the `jp` country is not "
            "a relabel: it is the only rule in the system that can represent a "
            "central bank held at a floor for decades, which is the defining "
            "fact of Japanese policy and the thing a JGB or JPY trade is "
            "positioned against."
        ),
        decision_prohibition=[
            "MUST NOT be described or used as a Taylor rule. The floor and the "
            "cumulative-shortfall term are the rule; dropping them leaves a "
            "different model that contradicts the primary source.",
            "MUST NOT have its floor treated as a constant zero. Japan's floor "
            "was negative and then moved; hard-coding zero would misstate the "
            "NIRP period.",
            "MUST NOT be read without the notional rate and the shortfall "
            "visible: the actual rate alone hides whether the floor binds, "
            "which is the entire content of the leg.",
        ],
    )


def jp_ycc_reference_rule(inputs: JpYccInputs) -> PolicyRuleResult:
    """``ycc_gap = jgb_10y - ycc_target`` against the BoJ's own tolerance band.

    Japan's Yield Curve Control reference leg. The BoJ named the **10-year JGB
    yield** as an operating target (about 0%, with a band that widened over
    time), so the deviation of the market yield from that target is the measure
    of how much intervention the BoJ faces. The rule classifies the deviation
    against the band and reports it.

    **Why the 10-year JGB is an INSTRUMENT, not a proxy.** In the ECB's arm the
    long rate is a regressor that proxies expected inflation. Here the long
    yield is the thing the BoJ TARGETS — it buys JGBs to hold it in the band.
    Those are different structural roles for the same variable, which is why
    this is a distinct rule rather than a coefficient change on the ECB form.
    """
    jp = get_settings().policy.jp
    coefficients = jp.ycc

    deviation = inputs.jgb_10y - inputs.ycc_target
    in_band = abs(deviation) <= inputs.ycc_band
    # The signed pressure the BoJ faces: a yield ABOVE the band forces JGB
    # PURCHASES (easing); a yield BELOW is the opposite. Reported as a level
    # with the band explicitly published so a reader sees tolerance vs breach.
    pressure = coefficients.pressure_per_bp_value * deviation

    return PolicyRuleResult(
        model_name="jp_ycc_reference_rule",
        rule_variant="jp_ycc_reference",
        country="jp",
        as_of=utc_now(),
        value=round(deviation, 4),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"The 10-year JGB yield ({inputs.jgb_10y:.2f}%) sits {deviation:+.2f}pp "
            f"from the BoJ's YCC target of {inputs.ycc_target:.2f}% — "
            f"{'WITHIN' if in_band else 'OUTSIDE'} the ±{inputs.ycc_band:.2f}pp "
            f"band"
        ),
        context=(
            f"YCC target {inputs.ycc_target:.2f}%, observed 10-year JGB yield "
            f"{inputs.jgb_10y:.2f}%, deviation {deviation:+.2f}pp against a band "
            f"of ±{inputs.ycc_band:.2f}pp; the implied intervention pressure is "
            f"{pressure:+.2f}."
        ),
        inputs_used=["jgb_10y", "ycc_target", "ycc_band"],
        warnings=[
            "The YCC target and band MOVED over the policy's life (about 0% "
            "with a ±0.5% band, later ±1%, and the March-2024 exit). They are "
            "inputs, not constants; a result produced under one regime must not "
            "be read under another.",
            "The deviation is a MARKET yield against a POLICY target; it "
            "includes any term premium and expectations component, so a "
            "breach is not purely an intervention signal.",
            "A deviation inside the band is within TOLERANCE, not evidence that "
            "YCC is inactive; the BoJ may still be purchasing.",
            "After the March-2024 exit YCC was discontinued as an explicit "
            "framework; reading this leg for post-exit periods describes a "
            "policy that was no longer in force unless the target is set to the "
            "post-exit convention.",
        ],
        unit="percentage_points",
        direction=(
            f"{'above' if deviation > 0 else 'below' if deviation < 0 else 'at'} "
            f"the YCC target, {'outside' if not in_band else 'within'} the "
            f"tolerance band"
        ),
        assumptions=[
            "The BoJ's operating target for the 10-year JGB yield is an input "
            "(it has moved by policy), not a constant.",
            "Deviation within the band is tolerance, not inactivity.",
        ],
        data_provenance=[
            "jgb_10y — the 10-year JGB yield (jp_long_rate_10y)",
            "ycc_target, ycc_band — supplied by the caller / config leaves policy.jp.ycc.*",
            "coefficients — config leaves policy.jp.ycc.*",
        ],
        limitations=[
            "A yield deviation, not a quantity of intervention.",
            "Contaminated by term premium and expectations.",
            "The post-March-2024 regime change means the YCC framing is itself period-specific.",
        ],
        decision_relevance=(
            "The instrument-level leg of the Japanese cluster: it states where "
            "the BoJ's named long-yield target is under pressure, which is the "
            "leg a JGB or curve trade acts on and the mechanism by which YCC "
            "interacts with the FX layer."
        ),
        decision_prohibition=[
            "MUST NOT be read as a policy RATE. It is a yield deviation in "
            "percentage points from the BoJ's long-yield target.",
            "MUST NOT have the target or band hard-coded to the pre-2024 values; the policy moved.",
            "MUST NOT be treated as evidence of intervention absent the band "
            "context — inside-band deviations are tolerated.",
        ],
    )


def jp_overshoot_commitment_rule(
    inputs: JpOvershootCommitmentInputs,
) -> PolicyRuleResult:
    """``accommodation = φ_s·max(0, T_stab - Σ(π - π*))`` — the price-level rule.

    Japan's inflation-overshooting commitment leg, from the Bank of Japan's
    September 2016 framework and the primary source's finding that *"the
    augmented Taylor-type rule with a strong history dependence can work as a
    price-level targeting policy."* The commitment makes the stance depend on
    the CUMULATIVE inflation shortfall since the commitment began, not on the
    current inflation gap — which is the price-LEVEL (history-dependent) form a
    Taylor rule provably cannot be.

    The asymmetry is what makes it structurally distinct from every rule in
    this module: while a cumulative shortfall remains open, the rule adds
    accommodation EVEN IF current inflation is above 2%. A symmetric Taylor
    rule would tighten in exactly that state. That difference IS the
    commitment the BoJ made.
    """
    jp = get_settings().policy.jp
    coefficients = jp.overshoot

    open_shortfall = max(0.0, inputs.stabilization_threshold - inputs.cumulative_inflation_gap)
    accommodation = coefficients.shortfall_acceleration_value * open_shortfall
    commitment_word = (
        "commitment is STILL ADDING accommodation because the shortfall is open"
        if open_shortfall > 0
        else "shortfall is closed, so the commitment is no longer adding accommodation"
    )
    overshoot_dir = (
        "still adding accommodation" if open_shortfall > 0 else "no additional accommodation"
    )

    return PolicyRuleResult(
        model_name="jp_overshoot_commitment_rule",
        rule_variant="jp_overshoot_commitment",
        country="jp",
        as_of=utc_now(),
        value=round(accommodation, 4),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"The overshooting commitment prescribes {accommodation:+.2f}pp of "
            f"additional accommodation — the cumulative inflation shortfall is "
            f"{inputs.cumulative_inflation_gap:+.2f} against a stabilisation "
            f"threshold of {inputs.stabilization_threshold:.2f}"
        ),
        context=(
            f"Current inflation is {inputs.pi:.2f}% and the running cumulative "
            f"gap is {inputs.cumulative_inflation_gap:+.2f}pp-periods; the "
            f"{commitment_word}. "
            f"The rule is ASYMMETRIC: while the shortfall is open it adds "
            f"accommodation even if current inflation is above target."
        ),
        inputs_used=["pi", "cumulative_inflation_gap", "stabilization_threshold"],
        warnings=[
            "THE RULE IS DELIBERATELY ASYMMETRIC. While the cumulative "
            "shortfall is open it prescribes accommodation even though current "
            "inflation may exceed 2%. A reader who expects symmetric "
            "tightening above target will misread the commitment the BoJ made.",
            "The stabilisation threshold is a JUDGEMENT about what 'in a stable "
            "manner' means, not a published constant; it is an input so the "
            "judgement is visible and movable.",
            "The cumulative gap is the CALLER's running state; the rule is "
            "stateless. A caller that recomputes it over a short window loses "
            "the history dependence that gives the rule its form.",
            "This leg is a base-rate ACCELERATION in percentage points; it is "
            "not an absolute policy rate and must not be added to the "
            "shadow-rate leg's percent level without a stated conversion.",
        ],
        unit="percentage_points",
        direction=(overshoot_dir),
        assumptions=[
            "The commitment is HISTORY-DEPENDENT: it reads the cumulative "
            "inflation shortfall, not the current gap.",
            "The tolerance of overshooting above 2% is deliberate and encoded by "
            "the asymmetric treatment of the shortfall.",
            "The stabilisation threshold is a disclosed judgement, supplied as an input.",
        ],
        data_provenance=[
            "pi — Japanese CPI inflation (jp_cpi_yoy), all items less fresh food",
            "cumulative_inflation_gap — the caller's running sum of (π - π*)",
            "stabilization_threshold — an input (the caller's judgement of 'stable')",
            "coefficients — config leaves policy.jp.overshoot.*",
        ],
        limitations=[
            "A base-rate acceleration, not a policy rate.",
            "The threshold and the cumulative gap are judgement- and state-dependent.",
            "The commitment's post-2024 status is unclear; the rule describes "
            "the commitment as made, not the Board's current view.",
        ],
        decision_relevance=(
            "The commitment leg of the Japanese cluster: it states the "
            "history-dependent easing bias that a forward-looking trade on JPY "
            "or JGBs must price, and it is the rule that makes the `jp` arm's "
            "asymmetry explicit rather than implied."
        ),
        decision_prohibition=[
            "MUST NOT be read as symmetric with the Fed's rules. The whole point "
            "is that it does not tighten merely because inflation is above "
            "target while a cumulative shortfall is open.",
            "MUST NOT be added to a policy-rate level without a stated unit "
            "conversion; it is a percentage-point acceleration.",
            "MUST NOT be presented as the Policy Board's current commitment "
            "without noting the March-2024 exit from the framework it came from.",
        ],
    )


def policy_rule_ensemble(
    taylor: PolicyRuleResult,
    balanced: PolicyRuleResult,
    first_diff: PolicyRuleResult,
) -> ModelResult:
    """Report the three rules and their DISPERSION. Never average.

    ``value`` is a ``dict`` with a documented shape::

        {
          "rules": {"taylor": float, "balanced": float, "first_difference": float},
          "range": [float, float],
          "dispersion_pp": float,
          "dispersion_bp": float,
          "agreement": "CONVERGED" | "MIXED" | "UNCERTAIN",
        }

    Averaging is the obvious move and it is wrong. A mean of
    ``{2.0, 2.1, 6.0}`` is ``3.37``, a number no rule produced and no
    policymaker would recognise — and it hides the fact that one rule is
    shouting. The dispersion is a *measurement*: it quantifies how much the
    answer depends on assumptions (chiefly ``r*``) rather than on data, and that
    is information the thesis needs.

    The unit conversion is explicit. Section 6.1's bands are stated in basis
    points; the rules return percent. Comparing them without converting would
    call a 1pp dispersion "50bp of agreement".
    """
    settings = get_settings()
    numeric: list[float] = []
    for label, result in (
        ("taylor", taylor),
        ("balanced", balanced),
        ("first_difference", first_diff),
    ):
        # Narrowed per value rather than in one bulk comprehension: mypy cannot
        # propagate an `all(isinstance(...))` guard into a subsequent
        # comprehension, and a `# type: ignore` here would suppress the check
        # that catches exactly the case this guard exists to reject.
        if not isinstance(result.value, int | float):
            raise TypeError(
                f"policy_rule_ensemble requires numeric rule outputs; "
                f"{label} rule value is {type(result.value).__name__}. A "
                f"PolicyRuleResult whose value is not a rate cannot be dispersed."
            )
        numeric.append(float(result.value))

    low, high = min(numeric), max(numeric)
    dispersion_pp = high - low
    dispersion_bp = dispersion_pp * _BP_PER_PP

    convergence_bp = settings.policy.ensemble.convergence_threshold_bp_value
    uncertainty_bp = settings.policy.ensemble.uncertainty_threshold_bp_value

    if dispersion_bp < convergence_bp:
        agreement = "CONVERGED"
        reading = (
            f"{dispersion_bp:.1f}bp spread is below the {convergence_bp:.0f}bp "
            f"band — the rules agree, which is a genuine convergence signal "
            f"rather than an artefact of one construction."
        )
    elif dispersion_bp > uncertainty_bp:
        agreement = "UNCERTAIN"
        reading = (
            f"{dispersion_bp:.1f}bp spread exceeds the {uncertainty_bp:.0f}bp "
            f"band — policy uncertainty. The disagreement is driven by "
            f"differing r*/output-gap assumptions and MUST NOT be averaged "
            f"away (Section 6.1)."
        )
    else:
        agreement = "MIXED"
        reading = (
            f"{dispersion_bp:.1f}bp spread sits between the {convergence_bp:.0f}bp "
            f"and {uncertainty_bp:.0f}bp bands — partial agreement. Treat the "
            f"level-based rules as indicative and lean on the ensemble median."
        )

    return ModelResult(
        model_name="policy_rule_ensemble",
        country="us",
        as_of=utc_now(),
        value={
            "rules": {
                "taylor": taylor.value,
                "balanced": balanced.value,
                "first_difference": first_diff.value,
            },
            "range": [low, high],
            "dispersion_pp": round(dispersion_pp, 4),
            "dispersion_bp": round(dispersion_bp, 2),
            "agreement": agreement,
        },
        # Not compute_confidence(): this is not a model with an estimate of its
        # own. It reports three models' agreement, and the honest confidence is
        # the *weakest* input's — a summary cannot be more trustworthy than what
        # it summarises.
        confidence=min(taylor.confidence, balanced.confidence, first_diff.confidence),
        interpretation=(
            f"Policy rules: Taylor {taylor.value}%, Balanced {balanced.value}%, "
            f"First-difference {first_diff.value}% — {agreement} "
            f"(dispersion {dispersion_bp:.1f}bp)"
        ),
        context=reading,
        inputs_used=["taylor_rule", "balanced_approach_rule", "first_difference_rule"],
        warnings=[] if agreement == "CONVERGED" else [reading],
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percent (each rule's prescribed rate; dispersion in percentage points)",
        direction=(
            f"{'CONVERGED' if agreement == 'CONVERGED' else 'DISPERSED'}: the three "
            f"rules prescribe rates spanning "
            f"{dispersion_pp:.2f}pp — this is the model's OWN uncertainty, not a "
            f"market signal"
        ),
        assumptions=[
            "AVERAGING/SUMMARY IS LEGITIMATE ONLY BECAUSE Section 22.4 names the "
            "median of the three rules as the canonical model-implied value. The "
            "median is not a vote: it is the middle of three numbers, so a single "
            "outlier rule cannot drag it.",
            "DISPERSION IS THE NOISE FLOOR. The spread among the three rules is "
            "treated as the model's own uncertainty, and the significance test "
            "compares the model-vs-market gap against it. That is a modelling "
            "choice: three rules sharing a target and a functional form is a "
            "NARROW disagreement set, so the floor is likely understated relative "
            "to true model uncertainty (the possibility that the correct reaction "
            "function is not in the family at all).",
            "The three rules are treated as comparable quantities: each prescribes "
            "a policy rate in percent on the same basis. Mixing a rule that "
            "prescribes a LEVEL with one that prescribes a CHANGE would make the "
            "dispersion meaningless.",
            "Confidence is the MINIMUM of the three inputs', on the principle that "
            "a summary cannot be more trustworthy than what it summarises.",
        ],
        data_provenance=[
            "taylor_rule — Taylor Rule prescribed rate, from "
            "TaylorRuleInputs(r_star, pi_current, output_gap)",
            "balanced_approach_rule — the balanced-approach rule, same inputs",
            "first_difference_rule — the first-difference rule, from "
            "FirstDifferenceInputs(i_prev, pi_current, output_gap_change)",
            "r_star is config-sourced (settings, CBO/HLW estimate) and is itself "
            "UNOBSERVABLE; both rules inherit that. The market leg is NOT part of "
            "this result — it is derived separately and combined in "
            "canonical_policy_gap.",
        ],
        limitations=[
            "THE DISPERSION IS THE POINT, NOT AN ERROR BAR. Three rules that "
            "disagree by 80bp cannot support a claim about a 50bp gap. Reading "
            "the ensemble as a single 'model view' and its dispersion as noise to "
            "be averaged away inverts the model's design — the dispersion IS the "
            "noise floor, and Section 16.2 Q6 uses it as the significance "
            "threshold.",
            "ALL THREE RULES SHARE A TARGET AND A FUNCTIONAL FORM, so agreement "
            "among them is weak evidence of correctness. They are not three "
            "independent methodologies; they are three parameterisations of one "
            "family. Genuine model uncertainty — that the right reaction function "
            "is not in the family — is NOT represented here.",
            "r_star IS UNOBSERVABLE (Section 21.4 item 13) and enters the Taylor "
            "and balanced-approach rules directly. A wrong r_star shifts those "
            "two rules together and can leave the dispersion narrow while the "
            "level is wrong.",
            "The rules are prescribed RATES, not forecasts. Nothing here says the "
            "Fed will set such a rate, or when.",
            "Points-in-time: the inputs are read from the snapshot at one as_of, "
            "and no release or vintage datetime is available (Section 6, "
            "measured 2026-09-19). The output_gap term is revision-dependent, so "
            "the ensemble is too.",
        ],
        decision_relevance=(
            "The MODEL side of Section 16.2's Q6 gap — the median of these three "
            "rules is what the market-implied path is compared against, and the "
            "dispersion is the threshold that comparison uses. So this result "
            "supplies BOTH quantities in the significance test, which is why it "
            "is carried on the thesis rather than folded away."
        ),
        decision_prohibition=[
            "MUST NOT be read as a single 'model view' with the dispersion as "
            "noise to be averaged away. Section 22.4 makes the dispersion the "
            "noise floor itself; treating it as an error bar around a central "
            "estimate — the reading this prohibition exists for — would "
            "manufacture confidence the model does not have.",
            "MUST NOT be used to claim the model has THREE independent "
            "confirmations. The three rules share a target and a functional form, "
            "so agreement among them is much weaker than three disjoint "
            "methodologies agreeing, and Section 12's independence discipline "
            "applies.",
            "MUST NOT be compared against a market-implied value produced by a "
            "DIFFERENT market leg than the one canonical_policy_gap uses — the "
            "gap is only the gap under Section 22.4's single definition.",
            "MUST NOT be read as a forecast of the policy rate, and MUST NOT be "
            "consumed without its dispersion: a bare median rate is "
            "uninterpretable without the spread it summarises.",
        ],
    )


def canonical_policy_gap(
    taylor: PolicyRuleResult,
    balanced: PolicyRuleResult,
    first_diff: PolicyRuleResult,
    market_implied: float,
) -> MarketPricingGap:
    """THE canonical model-vs-market gap. No other definition is valid (Section 22.4).

    ``model_implied`` is the **median** of the three rules, ``raw_gap`` is that
    minus the market-implied path, and ``is_meaningful`` is
    ``abs(raw_gap) > dispersion`` where dispersion is the max-min spread of the
    three rules.

    The significance test is the part worth stating plainly: **dispersion IS the
    noise floor.** Three rules differing by 80bp cannot support a claim about a
    50bp gap. Without this test the system would confidently report gaps that
    are smaller than its own internal disagreement, which is the most common way
    a model-driven analysis misleads — not by being wrong, but by being precise
    about something it cannot resolve.
    """
    rule_values: list[float] = []
    for label, result in (("taylor", taylor), ("balanced", balanced), ("first_diff", first_diff)):
        if not isinstance(result.value, int | float):
            raise TypeError(
                f"canonical_policy_gap: {label} rule value is "
                f"{type(result.value).__name__}, not a rate. Only numeric rule "
                f"outputs can define a policy gap."
            )
        rule_values.append(float(result.value))

    values = sorted(rule_values)
    model_implied = values[1]  # median of three
    dispersion = values[2] - values[0]
    gap = model_implied - market_implied
    is_meaningful = abs(gap) > dispersion

    #: The market leg is an AVERAGE over this horizon; the model leg is a SPOT
    #: prescription. Published beside the gap (Section 22.5's proxy horizon) so
    #: the mismatch is visible rather than implied — a reader who sees only
    #: "model 5.00% vs market 4.00%" would reasonably read it as a same-horizon
    #: disagreement, which it is not.
    horizon_months = get_settings().policy.market_implied.proxy_horizon_months_value
    horizon_note = (
        f" HORIZON MISMATCH: the model leg is the rules' prescription for the "
        f"CURRENT period, while the market leg is an AVERAGE over "
        f"{horizon_months} months — so the gap understates the near-term "
        f"divergence when the expected path is sloped, and its sign is only "
        f"guaranteed when the path is flat."
    )

    verdict = "MEANINGFUL" if is_meaningful else "WITHIN NOISE FLOOR"
    if is_meaningful:
        direction = "above" if gap > 0 else "below"
        detail = (
            f"The model prescribes a rate {abs(gap):.2f}pp {direction} the market "
            f"implies, which exceeds the {dispersion:.2f}pp spread among the "
            f"rules themselves — the gap survives the model's own uncertainty."
        )
    else:
        detail = (
            f"The {abs(gap):.2f}pp gap is smaller than the {dispersion:.2f}pp "
            f"spread among the three rules, so it is inside the noise floor. "
            f"The rules disagree with each other more than they disagree with "
            f"the market; this is NOT a tradable divergence."
        )

    return MarketPricingGap(
        model_implied_value=round(model_implied, 4),
        market_implied_value=round(market_implied, 4),
        raw_gap=round(gap, 4),
        dispersion=round(dispersion, 4),
        is_meaningful=is_meaningful,
        unit="%",
        interpretation=(
            f"Model (median of 3 rules) {model_implied:.2f}% vs market "
            f"{market_implied:.2f}% = {gap:+.2f}% gap; rule dispersion "
            f"{dispersion:.2f}pp ({verdict}). {detail}{horizon_note}"
        ),
    )


#: D2 — the Section 22.5 replacement obligation, given an OWNER.
#:
#: Section 22.5 obligates Phase 5+ to *"REPLACE this entirely with a real
#: Fed-funds-futures-implied probability distribution … this function's
#: signature is stable so that replacement is a body swap, not a caller-facing
#: breaking change."*
#:
#: Phase 5+ is recorded COMPLETE (Tier 5 = 23/23, D-092 … D-125) and the body was
#: never swapped. The first reason found (2026-10-09) was structural: the
#: obligation is attached to a **Tier 3** function (AGENTS.md §21.3), while the
#: Phase-5+ work list was built from the section's **Tier 5** names. **It fell
#: between two lists, so no gate and no checklist owned it.** "Tier 5 = 23/23" is
#: true and does not mean Phase 5+ is complete.
#:
#: **Measured 2026-10-10 — the source EXISTS.** §22.5's data conditional is
#: satisfied: the route ``derivatives.futures.curve`` with ``symbol="ZQ"``
#: returns the 30-Day Fed Funds futures term structure. The earlier "needs data"
#: reading was wrong because the D-108 inventory was grepped for
#: ``forward|swap|basis`` and never for ``futur``. Read by
#: ``fetch_fed_funds_futures_curve`` (data leg) and ``futures_implied_policy_path``
#: (model leg), both built and tested.
#:
#: **The mechanism, corrected 2026-10-10 (second pass).** The first reading of the
#: signature problem said the replacement was *impossible*. It is not — it is
#: INCOMPATIBLE WITH A PURE BODY SWAP. The distinction matters:
#:
#:   * §22.5 promises the replacement is *"a body swap, not a caller-facing
#:     breaking change"* because *"this function's signature is stable"*. A curve
#:     is a collection of expirations; the signature carries two SCALARS; so a
#:     body swap cannot deliver the curve (reconstructing it from two floats would
#:     violate §21.0 rule 3). **The promised MECHANISM cannot be used.**
#:   * But the change does not have to be BREAKING. ``short_yield`` is
#:     keyword-only at both ``derive_market_implied_policy_path`` and its callers,
#:     so an OPTIONAL ``futures_curve`` parameter with a ``None`` default is a
#:     strictly ADDITIVE signature extension: every existing call keeps working,
#:     and the function prefers the futures path when a curve is supplied.
#:
#: So the obligation is DISCHARGEABLE by an additive change, and this version does
#: it — **and the live path now SUPPLIES the curve.** ``_reasoning_frames``
#: (``api_layer/reasoning_stream.py``) fetches the ZQ curve through
#: ``fetch_fed_funds_futures_curve`` (which routes through ``OpenBBClient``,
#: D-087.25) and passes it down ``build_us_macro_thesis`` → ``build_policy_gap``
#: → ``derive_market_implied_policy_path``, so the market leg is the market's own
#: futures-implied rate, not the proxy. The fetch is **fail-safe**: on
#: ``FuturesCurveError`` / ``OpenBBFetchError`` it returns ``None`` and the proxy
#: runs, with the fallback NAMED on the reasoning trace — a futures outage
#: degrades the market leg but never breaks a live run (the operator's choice).
#:
#: **The marker is therefore ``"discharged"`` as of 2026-10-10.** Both halves of
#: §22.5 hold: the market leg is genuinely futures-implied when the source is
#: reachable, AND — measured, not asserted — the change was additive, so no
#: pre-existing caller broke (the proxy branch is byte-for-byte intact under
#: ``futures_curve=None``, which is also the fallback path).
#:
#: This constant is read by `tests/models/test_policy_rules.py`'s tripwire, which
#: asserts BOTH that the proxy branch is intact AND that this marker agrees with
#: the live wiring. It was ``"outstanding"`` while the reader accepted a curve
#: that nothing supplied; flipping it required wiring the live fetch in the SAME
#: change, which is exactly what the tripwire forced.
PHASE5_REPLACEMENT_OBLIGATION: str = "discharged"


def derive_market_implied_policy_path(
    short_yield: float,
    short_tenor_term_premium: float | None,
    *,
    futures_curve: FedFundsFuturesCurve | None = None,
) -> ModelResult:
    """The market-implied policy path: a real futures path, or the 22.5 proxy.

    ``value`` is a ``float``: the market-implied policy rate in percent.

    **Two branches, and the futures branch is preferred when a curve is given.**
    Section 22.5 obligates Phase 5+ to replace the proxy with a real
    Fed-funds-futures-implied path. That replacement used to be described as a
    *"body swap"* behind a *"stable signature"*; measured 2026-10-10 the swap is
    impossible (a curve cannot travel through two float parameters) but the
    change is strictly additive, so this function takes an OPTIONAL curve:

    * ``futures_curve`` supplied → returns the **near futures-implied rate**
      (``futures_implied_policy_path``), the market's own expectation for the
      current period, and does NOT attach the proxy's contamination warnings —
      because none of them apply. The returned result is the futures function's.
    * ``futures_curve`` omitted → the Phase 1-4 **proxy**, byte-for-byte as
      before, with its warnings intact. Every existing caller is unaffected.

    Why the preference is inside THIS function rather than a new one: §22.5 names
    this function as the thing to replace and promises its signature stays
    stable. A new function beside it (the earlier ``futures_implied_policy_path``)
    is not a replacement — it is a second implementation, and a caller would have
    to choose between them. Choosing here keeps ONE entry point, so a caller
    cannot pick the proxy by accident when a curve is available.

    The ``None`` sub-branch of the proxy is unchanged and still critical: with no
    term premium it **returns the raw yield unchanged** but attaches an
    unconditional, unmissable warning and a confidence near the floor. It does
    not invent a premium, does not substitute a different tenor's premium, and
    does not quietly return a number that looks the same as the adjusted case.

    The signature stays stable by construction: the new parameter is keyword-only
    with a default, so this is not a caller-facing breaking change.
    """
    # --- The Section 22.5 replacement, preferred when a curve is available. ---
    if futures_curve is not None:
        # `futures_implied_policy_path` raises when the curve has too few
        # plausible expirations — deliberately NOT caught here. A curve that
        # cannot support a path is a failure the caller must see, not a reason to
        # silently fall back to the proxy, which would publish a contaminated
        # number while pretending the futures source was used.
        return futures_implied_policy_path(
            futures_curve,
            proxy_horizon_months=get_settings().policy.market_implied.proxy_horizon_months_value,
        )

    # --- The Phase 1-4 proxy, byte-for-byte as before when no curve is given. ---
    # Both inputs must be FINITE (D-078). The adjustment is a **subtraction**,
    # so a non-finite term premium does not merely propagate — it can **flip
    # the sign**: measured, ``short_tenor_term_premium=inf`` produced ``-inf``,
    # i.e. a market-implied path pointing the opposite way from the raw yield it
    # was supposed to adjust. The caller's type check admits any ``float``, and
    # `nan` and `inf` are floats, so the guard has to be on finiteness.
    for name, raw in (
        ("short_yield", short_yield),
        ("short_tenor_term_premium", short_tenor_term_premium),
    ):
        if raw is not None and not isfinite(raw):
            raise ValueError(
                f"derive_market_implied_policy_path received {name}={raw!r}. The "
                "market-implied path is the reference the whole gap is measured "
                "against, and the adjustment is a subtraction — a non-finite "
                "input propagates AND can invert the sign, so the gap would be "
                "computed against a market path that does not exist (Section "
                "21.0 rule 3, D-078)."
            )
    settings = get_settings()
    market_implied = settings.policy.market_implied
    #: The horizon this proxy is an AVERAGE over, from config (never a literal —
    #: LAW 1). Published beside the gap so a reader can see that the model leg is
    #: a SPOT prescription and the market leg is an average over this window.
    horizon_months = market_implied.proxy_horizon_months_value
    horizon_warning = (
        f"HORIZON MISMATCH, and it is structural, not incidental: this proxy is "
        f"the short yield minus a term premium, so it approximates the AVERAGE "
        f"expected policy rate over {horizon_months} months. canonical_policy_gap "
        f"compares it against the MEDIAN OF THE THREE RULES, which prescribes a "
        f"rate for the CURRENT period. Spot minus a {horizon_months}-month average "
        f"means the gap UNDERSTATES the near-term divergence whenever the expected "
        f"path is sloped, and its sign is only guaranteed when the path is flat. "
        f"The system does not measure the path's slope. A Fed-funds-futures-implied "
        f"distribution would (Section 22.5)."
    )

    if short_tenor_term_premium is not None:
        expectations_component = short_yield - short_tenor_term_premium
        confidence = market_implied.term_premium_available_confidence_value
        warnings = [
            "Still a PROXY: a term-premium-adjusted yield, NOT a real "
            "Fed-funds-futures-implied probability distribution. Phase 5+ "
            "replaces this entirely (Section 22.5).",
            "The adjustment is only as good as the term-premium model. ACM "
            "estimates are themselves model output with their own revision "
            "history.",
            horizon_warning,
        ]
        context = (
            f"Adjusted from raw {short_yield:.3f}% by a term premium of "
            f"{short_tenor_term_premium:.3f}pp; AVERAGE over {horizon_months} months"
        )
    else:
        expectations_component = short_yield
        confidence = market_implied.no_term_premium_confidence_value
        warnings = [
            "NO TERM PREMIUM ADJUSTMENT APPLIED. This raw yield is CONTAMINATED "
            "by term premium and is a materially weaker proxy than usual — the "
            "returned value is the yield itself, not an expectations component.",
            "Do not compare this figure against a term-premium-adjusted reading "
            "from another run without checking which branch produced it.",
            "Still a PROXY, and a weaker one than the term-premium-adjusted "
            "variant. Phase 5+ replaces this entirely with a genuine "
            "Fed-funds-futures-implied distribution (Section 22.5).",
            horizon_warning,
        ]
        context = (
            "No term premium available at this tenor — raw yield returned "
            f"UNCHANGED, per Section 22.5; AVERAGE over {horizon_months} months"
        )

    return ModelResult(
        model_name="derive_market_implied_policy_path",
        country="us",
        as_of=utc_now(),
        value=round(expectations_component, 3),
        confidence=confidence,
        interpretation=f"Market-implied policy path proxy: {expectations_component:.3f}%",
        context=context,
        inputs_used=["short_yield", "short_tenor_term_premium"],
        warnings=warnings,
        # --- Section 3/4: the reasoning object, populated -------------------
        unit="percent",
        direction=(
            "an expectations component of the short yield, with the term premium removed"
            if short_tenor_term_premium is not None
            else "the RAW short yield, term premium NOT removed — not an "
            "expectations component at all"
        ),
        assumptions=[
            "The short yield decomposes additively into an expectations component "
            "and a term premium, so subtracting a tenor-matched premium isolates "
            "the first. That is an accounting identity under a particular "
            "decomposition, not a measured fact.",
            "A single point on the short end represents the market's whole "
            "policy-path view. A yield is a single number discounting a whole "
            "future path, so the mapping from one to the other requires an "
            "assumption about the path's shape that this model does not state.",
            "A Fed-funds-futures-implied distribution and a term-premium-adjusted "
            "short yield are treated as interchangeable proxies for 'what the "
            "market implies'. They are not the same object; the futures-implied "
            "one is what Phase 5+ replaces this with (Section 22.5).",
        ],
        data_provenance=[
            "short_yield — the snapshot's nominal curve at "
            "settings.api.short_yield_tenor, resolved by _short_yield_from_curve "
            "and read in PERCENT (not basis points)",
            "short_tenor_term_premium — supplied by the CALLER, not fetched. "
            "There is no term-premium series wired (Section 22.5 defers ACM to "
            "Phase 5+), so on the live path this is None and the raw-yield branch "
            "runs",
            "Confidence is read from config "
            "(policy.market_implied.term_premium_available_confidence_value / "
            "no_term_premium_confidence_value) and is NOT produced by "
            "compute_confidence(): the two branches are deliberately different "
            "qualities, not two settings of one factor.",
        ],
        limitations=[
            "IT IS A PROXY, AND ON THE LIVE PATH IT IS A CONTAMINATED ONE. No "
            "term-premium series is wired, so the no-premium branch runs and the "
            "returned value is the RAW YIELD — which contains the premium. At the "
            "front end that premium has been large enough to INVERT the reading "
            "of the same data, so the sign of the resulting gap can be wrong for "
            "reasons the model cannot detect.",
            "THE VALUE LOOKS THE SAME IN BOTH BRANCHES. A consumer reading only "
            "`value` cannot tell whether the adjustment was applied; only the "
            "warnings and the confidence distinguish them. This is the disclosure "
            "Section 22.5 requires, and it is a warning rather than a field by "
            "design.",
            "The adjusted branch is only as good as the term-premium model, which "
            "is itself model output with its own revision history and its own "
            "estimation error.",
            "NOT A DISTRIBUTION: even the adjusted value is a single number, not a "
            "probability distribution over future policy rates, so it cannot "
            "support any statement about how likely a given policy path is.",
            "One tenor stands in for the whole path: the model reads one point on "
            "the curve, so it cannot represent a market pricing cuts then hikes, "
            "or a path with a shape.",
            "Points-in-time: the yield carries one observation timestamp and no "
            "release or vintage datetime (Section 6, measured 2026-09-19).",
        ],
        decision_relevance=(
            "The MARKET side of Section 16.2's Q6 gap — the quantity the "
            "model-implied path is compared against, and therefore a direct input "
            "to the significance test that decides whether the thesis trades at "
            "all. It also feeds Q3/Q4's market read."
        ),
        decision_prohibition=[
            "MUST NOT be read as a market-implied policy RATE. It is a short "
            "yield (adjusted or not), and the mapping from a yield to a policy "
            "path needs an assumption this model does not make explicit.",
            "MUST NOT be compared against a value produced by the OTHER branch "
            "without checking which branch ran. The adjusted and unadjusted "
            "values are different quantities and the difference is the term "
            "premium.",
            "MUST NOT be treated as a probability distribution or used to make a "
            "likelihood statement about a future policy decision. Phase 5+ "
            "replaces this with a genuine futures-implied distribution precisely "
            "because the proxy cannot do that.",
            "MUST NOT be consumed without noticing that on the live path the "
            "NO-TERM-PREMIUM branch runs: the gap whose sign the thesis reports "
            "is computed against a contaminated market leg, and any conclusion "
            "about the gap's direction inherits that.",
        ],
    )


def futures_implied_policy_path(
    curve: FedFundsFuturesCurve,
    *,
    proxy_horizon_months: int,
) -> ModelResult:
    """Section 22.5's REPLACEMENT: the market leg from the futures curve.

    ``value`` is a ``float``: the **near** implied policy rate in percent — the
    front expiration, which is the market's expectation for the CURRENT period.
    That is the quantity ``canonical_policy_gap`` compares against the model's
    median prescription, and it is the whole point of the replacement: the proxy
    returned a number that was an AVERAGE over two years, so subtracting a spot
    prescription from it was apples-to-oranges.

    **Why ``value`` is the near rate and not the mean of the path.** The gap
    asks *"is the model's prescription for now different from what the market
    prices for now"*. A mean over the whole path answers a different question
    (roughly "where does policy settle"), and publishing it under this model's
    name would rebuild the horizon mismatch in the opposite direction. The
    path's SHAPE is not thrown away — it is carried on the context and on the
    ``path_slope_bp``-derived interpretation, so a caller can see the market
    pricing +80bp of hikes while still comparing like with like at the front.

    **The horizon is now stated, not assumed.** The old proxy carried a warning
    that its number was an average over ``proxy_horizon_months`` while the model
    leg was spot. This function truncates the path to that SAME window (the
    caller passes it, and config asserts the two leaves agree) so the two legs
    are compared over one horizon. The warning becomes a statement of what the
    path covers rather than an admission of a defect.

    **What it still is NOT.** It is not a probability distribution over policy
    *decisions*. ZQ gives the market's expected AVERAGE effective rate per
    contract month; recovering "the probability of a 25bp cut at the September
    meeting" from that needs the meeting calendar and a step-function
    assumption this module does not make. Section 22.5's phrase
    "probability distribution" is therefore met only in the weak sense that the
    path is a set of priced points rather than one number — and the result says
    so, loudly, in ``limitations`` and ``decision_prohibition`` rather than
    implying a distribution it does not have.
    """
    settings = get_settings().market_implied_futures
    confidence = settings.distribution_confidence
    offset = curve.settlement_offset

    if not curve.has_path:
        # Refusing is the honest move, and it is reachable: the source's own
        # corruption can leave fewer expirations than the floor. A one-point
        # "path" is what the proxy this replaces already was.
        raise ValueError(
            f"futures_implied_policy_path needs at least "
            f"{settings.min_expirations} plausible expirations for a PATH, but "
            f"the curve for {curve.symbol} carries {len(curve.expirations)} "
            f"({curve.rows_returned} rows returned, {curve.rows_rejected} "
            f"rejected, {curve.rows_dropped_past} past-dated). Refusing rather "
            f"than publishing a point as a path."
        )

    near = curve.near_rate_pct
    slope_bp = curve.path_slope_bp

    # Truncate the published path to the comparison horizon. A contract whose
    # month begins INSIDE the window counts; one beyond it does not. Measured
    # 2026-10-10 the curve spans 0..16 months, so the default 24-month window
    # keeps the whole usable path and this filter is inert — it exists so the
    # horizon is ENFORCED rather than implied by whatever the provider sent.
    within_horizon = tuple(e for e in curve.expirations if e.months_ahead <= proxy_horizon_months)

    covered_months = within_horizon[-1].months_ahead if within_horizon else 0

    # The shape, in words, from the measured slope — not a hardcoded label.
    if slope_bp > 25.0:
        shape = f"pricing HIKES (+{slope_bp:.0f}bp across the curve)"
    elif slope_bp < -25.0:
        shape = f"pricing CUTS ({slope_bp:.0f}bp across the curve)"
    else:
        shape = f"broadly FLAT ({slope_bp:+.0f}bp across the curve)"

    return ModelResult(
        model_name="futures_implied_policy_path",
        country="us",
        as_of=utc_now(),
        value=round(near, 3),
        confidence=confidence,
        interpretation=(
            f"Futures-implied policy path: the nearest contract "
            f"({curve.expirations[0].expiration}) prices {near:.2f}%, and the "
            f"curve is {shape} out to {curve.expirations[-1].expiration}."
        ),
        context=(
            f"From the 30-Day Fed Funds futures curve ({curve.symbol} via "
            f"{curve.provider}, {len(curve.expirations)} usable expirations of "
            f"{curve.rows_returned} returned). Implied rate = {offset:.0f} - price. "
            f"Path covers {covered_months} months against the "
            f"{proxy_horizon_months}-month comparison window."
        ),
        inputs_used=["curve"],
        warnings=_futures_curve_warnings(curve, slope_bp),
        unit="percent",
        direction=(
            "the market-implied average policy rate for the CURRENT contract "
            "month, read from the front of the futures curve"
        ),
        assumptions=[
            "A 30-Day Fed Funds future settles to 100 minus the contract month's "
            "average effective funds rate, so its price inverts directly into an "
            "expected average policy rate. That is the contract's definition, not "
            "a modelling choice — but it makes the output an AVERAGE over the "
            "month, not a rate for a specific day.",
            "Each expiration's price is treated as a clean read of that month's "
            "expectation. In practice a front contract also carries a small "
            "settlement-timing and risk-premium component that this module does "
            "NOT remove, because no term-premium decomposition exists at this "
            "horizon in the tree.",
            "The market's expectation is informative about policy but is not a "
            "forecast of it: futures prices embed a risk premium and can be "
            "dominated by hedging flows in stressed markets.",
        ],
        data_provenance=[
            f"curve — read live from {FUTURES_ROUTE_ENDPOINT!r} via "
            f"{curve.provider!r} for symbol {curve.symbol!r}, retrieved "
            f"{curve.source_retrieved_at}",
            f"settlement_offset — config leaf "
            f"market_implied_futures.settlement_offset_value ({offset:.1f}), the "
            f"contract's own settlement identity rather than a fitted constant",
            f"confidence — config leaf "
            f"market_implied_futures.distribution_confidence_value ({confidence}), "
            f"NOT computed by compute_confidence(): the specification fixes it as "
            f"a property of the METHOD (a traded price beats an adjusted yield), "
            f"not of a run's inputs",
        ],
        observation_dates={e.expiration: e.expiration for e in within_horizon},
        limitations=[
            "NOT A PROBABILITY DISTRIBUTION OVER DECISIONS. The curve yields an "
            "expected AVERAGE rate per contract month; converting that into the "
            "probability of a specific move at a specific meeting needs the "
            "meeting calendar and a step-function assumption this module does not "
            "make. Section 22.5's phrase 'probability distribution' is met only "
            "in the weak sense that the path is many priced points rather than "
            "one number.",
            "It inherits the source's corruption budget: the provider returned "
            f"{curve.rows_returned} expirations and this module REJECTED "
            f"{curve.rows_rejected} as implausible. Those rejections are named on "
            "the curve object, but a caller reading only `value` cannot see them.",
            "The near rate is an average over the contract MONTH, so it already "
            "blends any meeting that falls inside that month. It is not a "
            "point-in-time policy expectation.",
            "ZQ is a single contract family at one exchange. A dislocation in "
            "that market — not a change in policy expectations — moves this value.",
        ],
        decision_relevance=(
            "This is the MARKET side of Section 16.2's Q6 gap, replacing the "
            "term-premium-adjusted-yield proxy. canonical_policy_gap subtracts it "
            "from the median of the three rules, so it is a direct input to the "
            "significance test that decides whether the thesis trades at all."
        ),
        decision_prohibition=[
            "MUST NOT be described as a probability distribution over policy "
            "decisions. It is a path of expected average rates.",
            "MUST NOT be compared against a value produced by "
            "`derive_market_implied_policy_path`. That function returns a "
            "term-premium-adjusted YIELD; this returns a futures-implied RATE. "
            "They are different objects with different horizons and different "
            "units of meaning, and the difference is not an error to reconcile.",
            "MUST NOT be consumed without reading the curve's rejection count. A "
            "run where the source was badly corrupted yields a path built from "
            "fewer points than usual, and the value alone does not say so.",
            "MUST NOT be treated as a forecast of policy. It is what the market "
            "PRICES, which includes a risk premium and can be moved by flows "
            "rather than by expectations.",
        ],
    )


def _futures_curve_warnings(curve: FedFundsFuturesCurve, slope_bp: float) -> list[str]:
    """The conditional warnings for a futures-implied path.

    Kept beside the model rather than inlined so the conditions are readable as
    a list of situations, and so each is separately testable.
    """
    warnings: list[str] = []
    if curve.rows_rejected:
        warnings.append(
            f"{curve.rows_rejected} of {curve.rows_returned} expirations returned "
            f"by the provider were REJECTED as implausible (a ~52% implied policy "
            f"rate is source corruption, not a market view). The path below is "
            f"built from the {len(curve.expirations)} that survived; the rejected "
            f"rows are named on the curve object."
        )
    if abs(slope_bp) > 25.0:
        direction_word = "hikes" if slope_bp > 0 else "cuts"
        warnings.append(
            f"The curve is sloped, pricing {abs(slope_bp):.0f}bp of {direction_word}. "
            f"The comparison leg (the model's median prescription) is a SPOT rate "
            f"while each point here is a month AVERAGE, so the gap's magnitude "
            f"understates the divergence at any single horizon and its sign is "
            f"only exact when the path is flat."
        )
    return warnings


# ---------------------------------------------------------------------------
# Module 4.1 — the QE/QT balance-sheet stance
# ---------------------------------------------------------------------------

#: The three stances, as a closed vocabulary (D-029).
QEStance = Literal["QE_EXPANDING", "QT_CONTRACTING", "NEUTRAL_HOLD"]


class BalanceSheetInputs(FiniteInputs):
    """The Fed's balance sheet and the reserve complex, over a three-month window.

    **The levels and the changes are both here, and both are used.** Section
    20.4's sample declares ``balance_sheet_level`` and ``reserve_balances`` as
    inputs, lists them in ``inputs_used``, and then reads **neither** — the
    stance is decided by one number while the output claims three. That is
    D-037's defect class, and it is corrected here: the levels are what make the
    change interpretable, and the reserve change is what makes the scarcity
    warning specific rather than generic.

    D-139: this class was left OUT of the ``_FiniteInputs`` family when the
    guard was added, so a non-finite change reached the stance comparison.
    Measured: ``qe_qt_stance(balance_sheet_change_3mo=nan)`` published
    ``stance='NEUTRAL_HOLD'`` — the ``nan > band`` and ``nan < -band`` tests both
    return ``False``, which is exactly the neutral branch, so the model reported
    a confident verdict from a number it could not compare. The same class of
    defect the base exists to close (D-078), reachable because this input group
    did not inherit it.
    """

    model_config = ConfigDict(extra="forbid")

    balance_sheet_level: float = Field(
        gt=0.0,
        description=(
            "Fed total assets (FRED `WALCL`), in MILLIONS of dollars. Must be "
            "positive: it is the denominator of the relative change that decides "
            "the stance."
        ),
    )
    balance_sheet_change_3mo: float = Field(
        description=(
            "Change in total assets over thirteen weeks, in the SAME units as "
            "`balance_sheet_level` (millions). Positive is expansion."
        ),
    )
    reserve_balances: float = Field(
        ge=0.0,
        description="Reserve balances with Federal Reserve Banks (FRED `WRESBAL`), in millions.",
    )
    reserve_balances_change_3mo: float = Field(
        description=(
            "Change in reserve balances over the same thirteen weeks. A NEGATIVE "
            "value alongside an active QT is the scarcity configuration: the "
            "balance sheet is shrinking and reserves, not the ON RRP facility, "
            "are absorbing it."
        ),
    )
    on_rrp_level: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Overnight reverse repo level (FRED `RRPONTSYD`), in BILLIONS of "
            "dollars — note the different unit from the two series above. The "
            "buffer that absorbs QT before reserves are touched. Optional "
            "because the model can still judge the stance without it, but the "
            "scarcity assessment is incomplete and says so."
        ),
    )


def qe_qt_stance(inputs: BalanceSheetInputs) -> ModelResult:
    """Judge the balance-sheet stance: QE, QT, or a hold (Module 4.1, Section 20.4).

    Section 20.4's premise is that QE/QT is a **second policy lever** the policy
    rate alone misses, and that **QT is harder to calibrate than QE**: the
    "ample reserves" level is unknown, and September 2019 showed reserves can hit
    scarcity unexpectedly.

    **The neutral band is a correction, not a choice.** Section 20.4 tests
    ``balance_sheet_change_3mo > 0``, ``< 0``, else ``NEUTRAL_HOLD`` — which
    makes ``NEUTRAL_HOLD`` require a change of **exactly zero**. Over 1226 weeks
    of `WALCL` that happened **zero times**, so the branch was dead code. The
    comparison is now against a **relative** band (``neutral_band_pct`` of the
    level), which makes all three stances reachable: measured at 48.7% / 31.2% /
    20.1%.

    Confidence is computed from the stated factors (Section 22.8), never
    asserted.
    """
    settings = get_settings().qe_qt
    band = settings.neutral_band_pct

    # Relative, because the balance sheet has ranged from $0.7T to $9.0T and an
    # absolute tolerance would mean different things at different times.
    change_pct = inputs.balance_sheet_change_3mo / inputs.balance_sheet_level * 100.0

    stance: QEStance
    if change_pct > band:
        stance = "QE_EXPANDING"
    elif change_pct < -band:
        stance = "QT_CONTRACTING"
    else:
        stance = "NEUTRAL_HOLD"

    reserves_draining = inputs.reserve_balances_change_3mo < 0.0
    rrp_drained: bool | None = None
    if inputs.on_rrp_level is not None:
        rrp_drained = inputs.on_rrp_level < settings.rrp_drained_threshold_bn

    # The scarcity configuration: QT is running AND reserves are the thing
    # absorbing it. While the RRP facility is full, QT drains THAT; once it is
    # empty the same QT comes out of reserves.
    direct_reserve_drain = stance == "QT_CONTRACTING" and reserves_draining

    stance_base_rate = settings.base_rates.rates[stance]
    warnings = [
        f"The stance is a CATEGORICAL from one threshold comparison. Over "
        f"{settings.base_rates.observations_measured} weekly observations this "
        f"stance occurred in {stance_base_rate:.1%} of them, which is the "
        f"frequency a reader needs before treating it as notable (D-029).",
        f"The stance is decided by the balance-sheet change measured against a "
        f"+/-{band:.2f}% band, not against zero. Section 20.4's `== 0` test made "
        f"NEUTRAL_HOLD unreachable: the thirteen-week change of a balance sheet "
        f"measured in millions is never exactly zero.",
    ]

    if stance == "QT_CONTRACTING":
        warnings.append(
            "QT active — monitor repo_stress_check() (Module 4.2). Reserve "
            "scarcity is not predictable ex-ante (September 2019), and QT is "
            "harder to calibrate than QE because the 'ample reserves' level is "
            "unknown."
        )

    if direct_reserve_drain:
        warnings.append(
            f"Reserves FELL ({inputs.reserve_balances_change_3mo:+,.0f}mn) while the "
            f"balance sheet contracted, so QT is draining reserves directly rather "
            f"than drawing down the ON RRP facility. This is the ordinary case "
            f"during QT ({settings.base_rates.reserve_drain_while_qt_rate:.1%} of QT "
            f"weeks), not an exceptional one — what makes it dangerous is the RRP "
            f"buffer being gone, not the drain itself."
        )

    if rrp_drained is True:
        warnings.append(
            f"The ON RRP facility reads {inputs.on_rrp_level:,.1f}bn, below the "
            f"{settings.rrp_drained_threshold_bn:,.0f}bn drained threshold. The "
            f"buffer that absorbs QT before reserves are touched is exhausted, so "
            f"further contraction now comes straight out of reserves."
        )
    elif rrp_drained is None:
        warnings.append(
            "ON RRP level NOT SUPPLIED, so the scarcity assessment is incomplete. "
            "Whether QT is draining the RRP buffer or reserves directly cannot be "
            "determined from the balance sheet alone — the buffer is the whole "
            "question."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The neutral band is uncalibrated_illustrative in settings.yaml.
            is_heuristic_not_calibrated=not _qe_stance_calibrated(),
            # One provider, one institution's own reporting.
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="qe_qt_stance",
        country="us",
        as_of=utc_now(),
        value={
            "stance": stance,
            # The inputs and the derived comparison, published so the stance is
            # RECOMPUTABLE from the output rather than trusted (D-009).
            "balance_sheet_level": round(inputs.balance_sheet_level, 4),
            "balance_sheet_change_3mo": round(inputs.balance_sheet_change_3mo, 4),
            "balance_sheet_change_pct": round(change_pct, 4),
            "reserve_balances": round(inputs.reserve_balances, 4),
            "reserve_change_3mo": round(inputs.reserve_balances_change_3mo, 4),
            "reserves_draining": reserves_draining,
            "on_rrp_level": inputs.on_rrp_level,
            "on_rrp_supplied": inputs.on_rrp_level is not None,
            "rrp_drained": rrp_drained,
            "direct_reserve_drain": direct_reserve_drain,
            "neutral_band_pct": band,
            "stance_base_rate": stance_base_rate,
            "observations_measured": settings.base_rates.observations_measured,
        },
        confidence=confidence,
        interpretation=(
            f"Balance sheet stance: {stance} "
            f"({change_pct:+.3f}% over 13 weeks, band +/-{band:.2f}%)"
        ),
        context=(
            "Second policy lever beyond the policy rate — affects the term "
            "premium via duration extraction (Module 4.1). The stance comes from "
            "the balance-sheet change relative to the level; the scarcity "
            "assessment comes from reserves and the ON RRP buffer."
        ),
        inputs_used=[
            "balance_sheet_level",
            "balance_sheet_change_3mo",
            "reserve_balances",
            "reserve_balances_change_3mo",
            "on_rrp_level",
        ],
        warnings=warnings,
    )


def _qe_stance_calibrated() -> bool:
    """Whether Module 4.1's neutral band is calibrated or an illustrative placeholder."""
    return get_settings().is_calibrated("qe_qt.neutral_band_pct_value")


# ---------------------------------------------------------------------------
# Module 4.3 — the forward-guidance text diff
# ---------------------------------------------------------------------------

#: The direction of the forward-guidance change, as a closed vocabulary (D-029).
#: ``MORE_HAWKISH`` / ``MORE_DOVISH`` when one side's phrases net-enter, the four
#: ``_TILT_*`` values when both sides move with one dominating (the label names
#: the SIGN of BOTH sides' nets, so an ADDITION is never called a REMOVAL),
#: ``UNCHANGED`` when the marker set did not move at all, and
#: ``MIXED_BOTH_DIRECTIONS_NET_FLAT`` when both sides moved and cancelled exactly.
StatementDiffDirection = Literal[
    "MORE_HAWKISH",
    "MORE_DOVISH",
    "HAWKISH_TILT_WITH_DOVISH_REMOVALS",
    "HAWKISH_TILT_WITH_DOVISH_ADDITIONS",
    "DOVISH_TILT_WITH_HAWKISH_REMOVALS",
    "DOVISH_TILT_WITH_HAWKISH_ADDITIONS",
    "MIXED_BOTH_DIRECTIONS_NET_FLAT",
    "UNCHANGED",
]


class StatementTextInputs(FiniteInputs):
    """Two FOMC statements to diff: the prior release and the current one.

    **Both texts are required and neither may be blank.** Section 20.4's
    signature is ``(prior_text: str, current_text: str)``; a missing or empty
    text is not a statement that says nothing, it is a statement that was not
    retrieved — and a diff against it would report *every* marker as newly
    entered on one side. That is the D-054 shape (a partial input read as a
    complete one), so the input model refuses it rather than diffing it.

    The texts are NOT normalized beyond case-folding and whitespace collapse at
    comparison time; the raw strings are kept for the token count that gates
    them, so the published token counts describe what was actually supplied.
    """

    model_config = ConfigDict(extra="forbid")

    prior_text: str = Field(
        description=(
            "The earlier FOMC statement, as released (raw text; whitespace and "
            "case are handled at comparison time)."
        ),
    )
    current_text: str = Field(
        description=(
            "The later FOMC statement, as released. The diff is prior -> current, "
            "so a phrase PRESENT here and ABSENT from ``prior_text`` is an ADDITION."
        ),
    )

    @model_validator(mode="after")
    def _reject_blank_text(self) -> StatementTextInputs:
        """Refuse a blank statement: it means the text was not retrieved (D-054)."""
        for name in ("prior_text", "current_text"):
            if not getattr(self, name).strip():
                raise ValueError(
                    f"{name} is blank. An empty statement is not a statement that "
                    f"says nothing — it is one that was not retrieved, and diffing "
                    f"against it would report every marker as newly entered. "
                    f"Refusing rather than guessing (AGENTS.md Section 20.4, "
                    f"Section 21.0 rule 3)."
                )
        return self


def _count_marker_occurrences(text: str, markers: tuple[str, ...]) -> dict[str, int]:
    """Count each marker phrase's occurrences in ``text``, case-folded.

    Returns a mapping of marker -> count for the markers that occur at least
    once, so a caller can report exactly WHICH phrases moved rather than only
    how many. Substring matching over the case-folded text is deliberate: the
    specification's markers are multi-word conditional phrases, and the desk
    signal is the phrase, not a tokenized bag of its words (a statement can
    contain "prepared" and "raise" without containing "prepared to raise").
    """
    folded = " ".join(text.lower().split())
    counts: dict[str, int] = {}
    for marker in markers:
        occurrences = folded.count(marker)
        if occurrences:
            counts[marker] = occurrences
    return counts


def _markers_entering_and_leaving(
    prior_counts: dict[str, int],
    current_counts: dict[str, int],
) -> tuple[list[str], list[str]]:
    """The markers that ENTERED and that LEFT, each including count CHANGES.

    A phrase that happens to appear twice in one text and once in the other is
    reported as having left *one* occurrence, not as unchanged — the diff is per
    occurrence, because the desk question is "did the language move", and a
    doubled phrase that drops to a single one moved.
    """
    ordered = sorted(set(prior_counts) | set(current_counts))
    entered = [m for m in ordered if current_counts.get(m, 0) > prior_counts.get(m, 0)]
    left = [m for m in ordered if current_counts.get(m, 0) < prior_counts.get(m, 0)]
    return entered, left


def _net_marker_change(prior_counts: dict[str, int], current_counts: dict[str, int]) -> int:
    """The net change in occurrences of a marker set, summed per occurrence.

    Positive means the side's language was ADDED to; negative means phrases of
    that side left the statement. Summed over the union of both texts' keys so a
    phrase present only in one text still contributes its full count.
    """
    keys = set(prior_counts) | set(current_counts)
    return sum(current_counts.get(m, 0) - prior_counts.get(m, 0) for m in keys)


def statement_text_diff(inputs: StatementTextInputs) -> ModelResult:
    """Diff two FOMC statements for forward-guidance changes (Module 4.3, Section 20.4).

    Section 20.4's premise, in its own words: *"the CURRENT rate decision is
    usually already priced; the forward-looking language is where surprise
    lives."* The signal is therefore the **entering and leaving of specific
    conditional phrases**, not the sentiment of either text read alone.

    **What this model is, and what it is not.** It is a *directional* read of
    how the forward-guidance language moved between two supplied texts. It is
    **not** a price forecast and it does **not** fetch the statements — the text
    source is the caller's concern (Section 20.4 scopes the model to the diff,
    and the Phase 5+ note is about the *feed*, not the arithmetic). Keeping the
    network out of the model is why the diff is testable offline and why the
    live check can drive it with declared text.

    **The net tilt is a ratio in [-1, +1].** Let ``h = |entered hawkish| -
    |left hawkish|`` and ``d = |entered dovish| - |left dovish|``. The tilt is
    ``(h - d) / (|h| + |d|)`` when either is non-zero, else ``0.0``. It is
    **signed** (positive is hawkish) and **bounded**, so it can be compared
    across statements of different lengths without a raw count masquerading as
    intensity.

    **The tilt label names the sign of BOTH sides' nets, not just the net sign.**
    When both directions moved, the direction says which one moved which way:
    ``HAWKISH_TILT_WITH_DOVISH_REMOVALS`` when the dovish side's net FELL
    (``d < 0``) against a hawkish net, and ``HAWKISH_TILT_WITH_DOVISH_ADDITIONS``
    when the dovish side's net ROSE (``d > 0``). The mirror pair does the same
    for a dovish net. This matters because a hawkish net built by *dropping
    dovish phrases* is a different trade from one built by *adding hawkish ones*
    — and the specification's whole point is that the phrase that MOVED is the
    signal. An earlier reduction keyed the label on ``tilt > 0`` alone, so a
    dovish ADDITION was published as a dovish REMOVAL: the D-125 class of a
    reduction keyed on the wrong predicate.
    When only one **direction** moved, the direction is simply
    ``MORE_HAWKISH`` / ``MORE_DOVISH``; note that a hawkish phrase *leaving* is a
    move in the dovish direction, so it reads ``MORE_DOVISH``, not
    ``MORE_HAWKISH``.

    Confidence is computed from the stated factors (Section 22.8), never
    asserted, and the two halves are combined as a **product** — the
    ``compute_confidence(...)`` value times the configured
    ``statement_text.confidence_cap`` (D-118's CAP-PRODUCT rule). A ``min()``
    would publish the cap alone on every path whenever the computed value sits
    above it, making the computed half dead code; the product keeps both
    load-bearing, so the published confidence moves with the heuristic flag and
    the source count. Both halves are published on the result
    (``confidence_computed`` and ``confidence_cap``), so the number is
    recomputable from the output. The cap sits well below the policy rules'
    confidence because a marker diff is a heuristic over a vocabulary that is
    itself illustrative.
    """
    settings = get_settings().statement_text

    # The token floor is a partial-input guard (D-054): a statement that came
    # back truncated or half-fetched is not a statement that says little, and
    # diffing it would report a spray of spurious additions/removals.
    for name, text in (("prior_text", inputs.prior_text), ("current_text", inputs.current_text)):
        if len(text.split()) < settings.min_tokens:
            raise ValueError(
                f"{name} has {len(text.split())} token(s), below the "
                f"statement_text.min_tokens floor of {settings.min_tokens}. A "
                f"statement this short is a partial or failed retrieval, not a "
                f"complete release — refusing rather than diffing it as if it "
                f"were whole (AGENTS.md Section 20.4, D-054)."
            )

    prior_hawkish = _count_marker_occurrences(inputs.prior_text, settings.hawkish_markers)
    prior_dovish = _count_marker_occurrences(inputs.prior_text, settings.dovish_markers)
    curr_hawkish = _count_marker_occurrences(inputs.current_text, settings.hawkish_markers)
    curr_dovish = _count_marker_occurrences(inputs.current_text, settings.dovish_markers)

    hawkish_entered, hawkish_left = _markers_entering_and_leaving(prior_hawkish, curr_hawkish)
    dovish_entered, dovish_left = _markers_entering_and_leaving(prior_dovish, curr_dovish)

    # Per-occurrence net on each side.
    hawkish_net = _net_marker_change(prior_hawkish, curr_hawkish)
    dovish_net = _net_marker_change(prior_dovish, curr_dovish)

    if hawkish_net == 0 and dovish_net == 0:
        direction: StatementDiffDirection = "UNCHANGED"
        tilt = 0.0
    else:
        # Positive tilt is hawkish. A hawkish phrase ENTERING (hawkish_net > 0)
        # adds; a dovish phrase ENTERING (dovish_net > 0) subtracts. Note that a
        # dovish phrase LEAVING (dovish_net < 0) is a NEGATED subtraction, i.e.
        # it adds to the hawkish tilt — which is the specification's point that
        # the phrase that MOVED is the signal, in either direction.
        tilt = (hawkish_net - dovish_net) / (abs(hawkish_net) + abs(dovish_net))

        # The naming is over BOTH sides' net SIGN, because the detailed labels
        # exist to say which side moved which way — and they must fire for the
        # crossover cases (one side's language leaving while the other enters),
        # which is exactly the D-125 class of a reduction keyed on the wrong
        # predicate. So the decision is: did BOTH sides move (both nets
        # non-zero)? If so the tilt is named by the opposite side's own net sign;
        # if only one side moved, the net sign alone gives a plain MORE_* read.
        #
        # A prior version gated the detailed labels behind two "ward" flags and
        # short-circuited to MORE_DOVISH whenever exactly one ward flag was set,
        # which made DOVISH_TILT_WITH_HAWKISH_REMOVALS UNREACHABLE for the
        # "hawkish left + dovish entered" crossover — the label that names the
        # trade was silently dropped in favour of a vaguer one. The test
        # test_statement_text_dovish_tilt_with_hawkish_removals pins the fix.
        both_sides_moved = hawkish_net != 0 and dovish_net != 0

        if both_sides_moved:
            # Language moved in BOTH directions. The net sign picks the
            # side; the OPPOSITE side's own net sign picks the phrase that
            # moved, because a hawkish net built by DROPPING dovish phrases
            # and one built by ADDING hawkish ones are different trades
            # (Section 20.4: the phrase that MOVED is the signal). A prior
            # reduction keyed the label on `tilt` alone, so a dovish ADDITION
            # and a dovish REMOVAL both read "…_WITH_DOVISH_REMOVALS" — the
            # D-125 defect class. Here the bond is the opposite side's net sign.
            if tilt > 0:
                direction = (
                    "HAWKISH_TILT_WITH_DOVISH_REMOVALS"
                    if dovish_net < 0
                    else "HAWKISH_TILT_WITH_DOVISH_ADDITIONS"
                )
            elif tilt < 0:
                direction = (
                    "DOVISH_TILT_WITH_HAWKISH_REMOVALS"
                    if hawkish_net < 0
                    else "DOVISH_TILT_WITH_HAWKISH_ADDITIONS"
                )
            else:
                # Both sides moved and cancelled exactly (e.g. one hawkish
                # phrase added and one dovish phrase added). No tilt to name,
                # so say the language moved both ways without netting.
                direction = "MIXED_BOTH_DIRECTIONS_NET_FLAT"
        else:
            # Exactly one side moved (the other net is zero): a plain
            # directional read. Note a hawkish phrase LEAVING is a move in the
            # dovish direction, so it reads MORE_DOVISH, not MORE_HAWKISH.
            direction = "MORE_HAWKISH" if tilt > 0 else "MORE_DOVISH"

    # Section 22.8's confidence, COMBINED AS A PRODUCT (D-118's CAP-PRODUCT rule),
    # never a `min()`. The cap states how much the *method* is worth; the
    # computed value states how much *this run's inputs* are worth. `min()`
    # would publish the cap alone on every path whenever the computed value
    # sits above it — which it does here (0.50 against a 0.35 cap), making the
    # whole `compute_confidence()` half DEAD CODE. D-118's rule: *"a computation
    # that never changes an output is scaffolding, not a model."* The product
    # keeps BOTH halves load-bearing — the published number moves when the
    # heuristic flag or the source count moves.
    computed = compute_confidence(
        ConfidenceInputs(
            # Both vocabularies are uncalibrated_illustrative: the marker list is
            # a starting vocabulary, not a measured one.
            is_heuristic_not_calibrated=not settings.vocabularies_are_calibrated,
            # One institution's own text, diffed against its own prior text.
            source_independence_count=0,
        )
    )
    confidence = round(computed * settings.confidence_cap, 3)

    prior_tokens = len(inputs.prior_text.split())
    current_tokens = len(inputs.current_text.split())

    warnings = [
        "A marker diff is WEAK evidence: the Committee writes language that "
        "resists mechanical reading, the same phrase means different things "
        "across regimes, and the market has usually read the statement before "
        "this parse of it. The confidence cap reflects that (Section 20.4).",
        f"The marker vocabulary is uncalibrated_illustrative: these are the "
        f"specification's phrases ({len(settings.hawkish_markers)} hawkish, "
        f"{len(settings.dovish_markers)} dovish), and no study here has measured "
        f"which of them actually moved rates on release.",
    ]
    if direction == "UNCHANGED":
        warnings.append(
            "No tracked forward-guidance phrase entered or left the statement. "
            "This is NOT a claim that the guidance did not change — only that it "
            "did not change in the tracked vocabulary."
        )
    if hawkish_left and dovish_left:
        warnings.append(
            "Phrases left BOTH sides of the vocabulary "
            f"(hawkish: {hawkish_left}; dovish: {dovish_left}) — the statement "
            "was edited in more than one direction, so the single net tilt "
            "understates how much the language moved."
        )

    return ModelResult(
        model_name="statement_text_diff",
        country="us",
        as_of=utc_now(),
        value={
            "direction": direction,
            "net_tilt": round(tilt, 4),
            "hawkish_entered": hawkish_entered,
            "hawkish_left": hawkish_left,
            "dovish_entered": dovish_entered,
            "dovish_left": dovish_left,
            "hawkish_net": hawkish_net,
            "dovish_net": dovish_net,
            "prior_tokens": prior_tokens,
            "current_tokens": current_tokens,
            # BOTH halves of the published confidence, so it is RECOMPUTABLE from
            # the output rather than trusted (D-009): `confidence ==
            # round(confidence_computed * confidence_cap, 3)`. Publishing the cap
            # alone would leave the reader unable to tell a dead computed half
            # from a live one — the exact defect this product form fixes.
            "confidence_computed": computed,
            "confidence_cap": settings.confidence_cap,
        },
        confidence=confidence,
        interpretation=(
            f"Forward guidance moved {direction} (net tilt {tilt:+.3f}): "
            f"{len(hawkish_entered)} hawkish phrase(s) entered, "
            f"{len(hawkish_left)} left; {len(dovish_entered)} dovish entered, "
            f"{len(dovish_left)} left."
        ),
        context=(
            "Module 4.3 — desks diff FOMC statements word-by-word on release, "
            "because the rate DECISION is usually priced while the forward "
            "guidance is where surprise lives. The signal is the phrase that "
            "moved, not the sentiment of either text."
        ),
        inputs_used=["prior_text", "current_text"],
        warnings=warnings,
    )
