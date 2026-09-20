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
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = [
    "BalanceSheetInputs",
    "FirstDifferenceInputs",
    "MarketPricingGap",
    "PolicyRuleResult",
    "QEStance",
    "TaylorRuleInputs",
    "balanced_approach_rule",
    "canonical_policy_gap",
    "derive_market_implied_policy_path",
    "first_difference_rule",
    "policy_rule_ensemble",
    "qe_qt_stance",
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


class _FiniteInputs(BaseModel):
    """Base for the policy-rule input groups: every float must be FINITE.

    Placed here rather than on ``PolicyRuleResult`` because the failure is at
    the **input**: a prescription of ``nan`` is the symptom, and the rule's
    arithmetic has no way to distinguish "the arithmetic went wrong" from "the
    input was never a number". Guarding the input names the offending field in
    the error and stops the value before it can be mixed with real ones.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _reject_non_finite(self) -> _FiniteInputs:
        offenders: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, float) and not isfinite(value):
                offenders.append(f"{name}={value!r}")
        if offenders:
            raise ValueError(
                f"non-finite policy-rule input(s): {', '.join(offenders)}. {_NON_FINITE_REMEDY}"
            )
        return self


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
            f"{dispersion:.2f}pp ({verdict}). {detail}"
        ),
    )


def derive_market_implied_policy_path(
    short_yield: float,
    short_tenor_term_premium: float | None,
) -> ModelResult:
    """A PROXY for the market-implied policy path, corrected per Section 22.5.

    ``value`` is a ``float``: the expectations component in percent.

    The raw 2-year yield is not a policy-path estimate — it is a policy-path
    estimate plus a term premium, and at the front end that premium has been
    large enough to invert the reading of the same data. Section 22.5's
    correction: subtract a tenor-matched ACM term premium when one is available.

    The critical clause is the ``None`` branch. With no term premium the
    function **returns the raw yield unchanged** but attaches an unconditional,
    unmissable warning and a confidence near the floor. It does not invent a
    premium, does not substitute a different tenor's premium, and does not
    quietly return a number that looks the same as the adjusted case. Section
    22.5 requires the contamination be visible, because a consumer cannot tell
    from the value alone which branch produced it.

    The signature is stable by design so that Phase 5+ can swap the body for a
    genuine Fed-funds-futures-implied distribution without breaking a caller.

    Both inputs must be FINITE (D-078). The adjustment is a **subtraction**, so
    a non-finite term premium does not merely propagate — it can **flip the
    sign**: measured, ``short_tenor_term_premium=inf`` produced ``-inf``, i.e. a
    market-implied path pointing the opposite way from the raw yield it was
    supposed to adjust. The caller's type check admits any ``float``, and `nan`
    and `inf` are floats, so the guard has to be on finiteness.
    """
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
        ]
        context = (
            f"Adjusted from raw {short_yield:.3f}% by a term premium of "
            f"{short_tenor_term_premium:.3f}pp"
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
        ]
        context = (
            "No term premium available at this tenor — raw yield returned "
            "UNCHANGED, per Section 22.5"
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


# ---------------------------------------------------------------------------
# Module 4.1 — the QE/QT balance-sheet stance
# ---------------------------------------------------------------------------

#: The three stances, as a closed vocabulary (D-029).
QEStance = Literal["QE_EXPANDING", "QT_CONTRACTING", "NEUTRAL_HOLD"]


class BalanceSheetInputs(BaseModel):
    """The Fed's balance sheet and the reserve complex, over a three-month window.

    **The levels and the changes are both here, and both are used.** Section
    20.4's sample declares ``balance_sheet_level`` and ``reserve_balances`` as
    inputs, lists them in ``inputs_used``, and then reads **neither** — the
    stance is decided by one number while the output claims three. That is
    D-037's defect class, and it is corrected here: the levels are what make the
    change interpretable, and the reserve change is what makes the scarcity
    warning specific rather than generic.
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
