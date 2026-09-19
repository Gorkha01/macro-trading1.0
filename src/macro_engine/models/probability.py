"""Module 12.3/12.4 — Bayesian updating and expected value.

Two functions that exist to make a thesis's reasoning **explicit and auditable**
rather than implicit:

* :func:`bayesian_update` forces a stated prior and a stated likelihood ratio,
  which is what prevents confirmation bias and over-reaction to weak evidence.
  *A strong prior REQUIRES a high likelihood ratio to move meaningfully — that is
  the math, not a disposition.*
* :func:`expected_value` computes the probability-weighted payoff, and says on
  every tail that **positive EV is necessary but not sufficient** — sizing is
  governed by survivability of the tail, not by the average (the LTCM lesson).

Section 20.11 supplies both, and three literals plus two hardcoded confidences
that are corrected here. See **D-042**:

**1. The confidence values are hardcoded (0.8 and 0.6) and, in the Bayesian
case, are wrong in a specific way.** The posterior's reliability depends on the
*inputs* — a prior of 0.5 with an uninformative likelihood ratio is not the same
claim as a prior of 0.9 with a decisive one — but a constant says the opposite.
Confidence now comes from ``compute_confidence()``.

**2. The likelihood-ratio band is asymmetric by accident.** Section 20.11 writes
``0.8 < lr < 1.25``, which treats 0.8 and 1.25 as different distances from
uninformative when they are the same distance in log-space. The band is now
symmetric, ``|lr - 1| < 0.25``, and externalized.

**3. Neither function validated its inputs.** ``BayesInputs`` accepted a prior of
1.5 or a likelihood of -0.2, and ``ScenarioOutcome`` accepted a **negative
probability** — which passes a sum-to-one check whenever another scenario is
over one (``1.5 + (-0.5) = 1.0``). The sum test is not a per-value test, and
relying on it was the gap.
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
    from macro_engine.config import ProbabilitySettings

__all__ = [
    "BayesInputs",
    "PayoffUnit",
    "ScenarioOutcome",
    "bayesian_update",
    "expected_value",
]


class BayesInputs(BaseModel):
    """A prior and the two likelihoods that update it.

    Every field is bounded to ``[0, 1]`` because all three are probabilities.
    Section 20.11's sample applies **no bounds at all**, so a prior of 1.5 or a
    likelihood of -0.2 flows straight into the arithmetic and produces a
    posterior that is not a probability — silently, and with the same shape as a
    correct answer.
    """

    model_config = ConfigDict(extra="forbid")

    prior: float = Field(
        ge=0.0,
        le=1.0,
        description="P(A) before the evidence, as a fraction. Bounded to [0, 1].",
    )
    likelihood_given_true: float = Field(
        ge=0.0,
        le=1.0,
        description="P(B|A) — the probability of observing the evidence if A holds.",
    )
    likelihood_given_false: float = Field(
        ge=0.0,
        le=1.0,
        description="P(B|¬A) — the probability of observing it if A does not hold.",
    )


def bayesian_update(inputs: BayesInputs) -> ModelResult:
    """Update a prior with one piece of evidence (Module 12.3, Section 20.11).

    ``P(A|B) = P(B|A)P(A) / [P(B|A)P(A) + P(B|~A)P(~A)]``

    The value of forcing the inputs explicitly is that **a strong prior cannot be
    moved by weak evidence**, and the output shows the likelihood ratio that
    would be required. That is arithmetic, not a disposition.

    Confidence is computed from the stated factors (Section 22.8), never
    asserted.
    """
    settings = _probability_settings()

    p_a = inputs.prior
    p_not_a = 1.0 - p_a
    p_b = inputs.likelihood_given_true * p_a + inputs.likelihood_given_false * p_not_a
    if p_b <= 0.0:
        raise ValueError(
            "P(B) is zero: the evidence is impossible under both hypotheses, so it "
            "carries no information and no posterior exists. Supply an observation "
            "that at least one hypothesis can produce."
        )

    posterior = (inputs.likelihood_given_true * p_a) / p_b

    # The likelihood ratio is the whole point of the module: it states how much
    # the evidence SHOULD move a belief, independently of the prior.
    if inputs.likelihood_given_false > 0.0:
        likelihood_ratio: float | None = (
            inputs.likelihood_given_true / inputs.likelihood_given_false
        )
    else:
        # P(B|~A) = 0 means the evidence is impossible without A — decisive, so
        # the ratio is unbounded. Reported as None rather than `inf`, which would
        # not survive serialisation and reads as a number.
        likelihood_ratio = None

    uninformative = (
        likelihood_ratio is not None
        and abs(likelihood_ratio - 1.0) < settings.uninformative_lr_band
    )
    shift_pp = (posterior - p_a) * 100.0

    warnings = [
        "The posterior is only as good as the two likelihoods, and those are "
        "usually the least defensible numbers in a thesis. A prior stated to two "
        "decimals does not make the answer precise (Module 12.3).",
    ]
    if uninformative:
        warnings.append(
            f"The likelihood ratio is {likelihood_ratio:.2f}, within "
            f"{settings.uninformative_lr_band:.2f} of 1.0 — this evidence barely "
            f"distinguishes the two hypotheses, and the {shift_pp:+.1f}pp shift is "
            f"noise rather than an update. Do not report the posterior as a finding."
        )
    if p_a in (0.0, 1.0):
        warnings.append(
            f"The prior is exactly {p_a:.0%}, which no evidence can move: a "
            f"probability of 0 or 1 is a statement that no observation could "
            f"change it, so the posterior equals the prior by construction."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The two likelihoods are caller-supplied judgements with no
            # calibration behind them, and this build has no data to fit them.
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="bayesian_update",
        country="us",
        as_of=utc_now(),
        value={
            "prior": round(p_a, 6),
            "posterior": round(posterior, 4),
            "likelihood_ratio": None if likelihood_ratio is None else round(likelihood_ratio, 4),
            "shift_pp": round(shift_pp, 4),
            # The denominator, published so the posterior is RECOMPUTABLE from
            # the output rather than trusted (the D-009 cross-field identity).
            "p_evidence": round(p_b, 6),
            "evidence_informative": not uninformative,
            "likelihood_given_true": inputs.likelihood_given_true,
            "likelihood_given_false": inputs.likelihood_given_false,
            "uninformative_lr_band": settings.uninformative_lr_band,
        },
        confidence=confidence,
        interpretation=(
            f"Prior {p_a:.0%} -> posterior {posterior:.0%} "
            f"(LR {'unbounded' if likelihood_ratio is None else f'{likelihood_ratio:.2f}'})"
        ),
        context=(
            "Explicit prior + likelihood ratio — prevents confirmation bias and "
            "noise over-reaction (Module 12.3). A strong prior requires a high "
            "likelihood ratio to move; that is the arithmetic, not a disposition."
        ),
        inputs_used=["prior", "likelihood_given_true", "likelihood_given_false"],
        warnings=warnings,
    )


#: The unit of a scenario's ``payoff_estimate``. Two members, because the
#: producer and the consumer disagree BY DESIGN and the disagreement must be
#: representable: Phase 1 publishes an illustrative ``bp_pnl_proxy``
#: distribution (Section 16.4), and ``apply_fractional_kelly`` accepts only
#: ``fraction_of_capital`` because its arithmetic is a growth rate over
#: capital. A distribution carrying ``bp_pnl_proxy`` is therefore **not**
#: Kelly-sizable, which is a fact about the distribution and not an error in
#: it (O-50).
PayoffUnit = Literal["bp_pnl_proxy", "fraction_of_capital"]


class ScenarioOutcome(BaseModel):
    """One branch of a scenario set: a probability and the payoff it produces.

    **This is the single definition of ``ScenarioOutcome`` in the tree.** Until
    D-064 there were two — this one and a structurally different one in
    ``thesis_layer/schemas.py`` — and the collision was **silent**: an import
    typo resolved to *a* valid class, ``mypy --strict`` accepted both (they are
    both types), ``ruff`` saw a legal name in both modules, and any test that
    imported only one of them saw nothing wrong. D-057 recorded it as **O-51**;
    D-064 closed it, because ``build_scenario_distribution`` is the **producer**
    whose output ``apply_fractional_kelly`` consumes, and it could not satisfy
    both classes at once.

    The thesis layer now **re-exports** this class, which is the same pattern
    ``EvidenceSourceFamily`` already uses: the vocabulary lives in the lower
    layer because both layers consume it, and the upper layer re-exports rather
    than redeclares.

    ``probability`` is bounded to ``[0, 1]`` per scenario, which Section 20.11
    does **not** do. That omission is not cosmetic: a **negative** probability
    passes the sum-to-one check whenever another scenario exceeds one
    (``1.5 + (-0.5) = 1.0``), so the set validates while describing something
    impossible. A per-value bound is the only thing that catches it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        description=(
            "A label for the branch, so the output is readable and the worst case can be named."
        ),
    )
    probability: float = Field(
        ge=0.0,
        le=1.0,
        description="Probability of this branch, as a fraction in [0, 1].",
    )
    payoff_estimate: float = Field(
        description="The payoff if this branch occurs, in the caller's units. May be negative.",
    )
    unit: PayoffUnit = Field(
        default="bp_pnl_proxy",
        description=(
            "The unit of ``payoff_estimate``. **Enumerated, and load-bearing:** "
            "``apply_fractional_kelly`` accepts only ``'fraction_of_capital'`` "
            "and raises on anything else, because its arithmetic is a growth rate "
            "over capital and a bp payload is a 100x-class error no downstream "
            "check can detect. A distribution published in ``bp_pnl_proxy`` is "
            "therefore **not** Kelly-sizable, and saying so is the point of the "
            "field — D-057 recorded the mismatch as O-50 and this is the "
            "producer's half of it."
        ),
    )
    description: str = Field(
        default="",
        description="Optional plain-language note on this branch.",
    )


def expected_value(scenarios: list[ScenarioOutcome]) -> ModelResult:
    """Probability-weighted payoff over a scenario set (Module 12.4, Section 20.11).

    **Necessary but NOT sufficient.** A positive expected value says nothing
    about whether a position survives its own tail — LTCM's trades were
    positive-EV. The model therefore reports the worst case and its probability
    alongside the mean, and warns when the tail dwarfs the average.

    Confidence is computed from the stated factors (Section 22.8), never
    asserted.
    """
    settings = _probability_settings()

    if not scenarios:
        raise ValueError(
            "A scenario set with no scenarios has no expected value. Section "
            "20.11's sum check would pass on an empty list, because the sum of "
            "nothing is 0 and 0 is not within tolerance of 1 — but the error would "
            "then be about the sum rather than about the emptiness."
        )

    total_probability = sum(scenario.probability for scenario in scenarios)
    if abs(total_probability - 1.0) > settings.probability_sum_tolerance:
        raise ValueError(
            f"Scenario probabilities sum to {total_probability!r}, which is more than "
            f"{settings.probability_sum_tolerance} from 1.0. An exhaustive scenario set "
            f"must account for all of the probability mass."
        )

    ev = sum(scenario.probability * scenario.payoff_estimate for scenario in scenarios)
    worst = min(scenarios, key=lambda scenario: scenario.payoff_estimate)
    tail_dominates = ev > 0.0 and worst.payoff_estimate < -settings.tail_loss_multiple * abs(ev)

    warnings = [
        f"Expected value is an average over branches, and an average says nothing "
        f"about any single path. The worst case here is "
        f"{worst.payoff_estimate:+.2f} at {worst.probability:.1%}.",
    ]
    if tail_dominates:
        warnings.append(
            f"Positive EV ({ev:+.2f}) with a tail loss of "
            f"{worst.payoff_estimate:+.2f} — more than "
            f"{settings.tail_loss_multiple:.0f}x the average. Size for SURVIVAL of "
            f"the tail, not for the average: a strategy that is right on average "
            f"and insolvent in the tail never collects the average (LTCM)."
        )
    if ev <= 0.0:
        warnings.append(
            "Expected value is non-positive, so no sizing rule rescues it. A "
            "negative-EV position is not made acceptable by being small."
        )

    confidence = compute_confidence(
        ConfidenceInputs(
            # The scenario probabilities are caller-supplied judgements with no
            # calibration behind them.
            is_heuristic_not_calibrated=True,
            source_independence_count=0,
        )
    )

    return ModelResult(
        model_name="expected_value",
        country="us",
        as_of=utc_now(),
        value={
            "ev": round(ev, 4),
            # The contributions, published so the EV is RECOMPUTABLE from the
            # output rather than trusted (the D-009 cross-field identity).
            "contributions": {
                scenario.name: round(scenario.probability * scenario.payoff_estimate, 6)
                for scenario in scenarios
            },
            "worst_case_payoff": worst.payoff_estimate,
            "worst_case_probability": worst.probability,
            "worst_case_name": worst.name,
            "total_probability": round(total_probability, 6),
            "n_scenarios": len(scenarios),
            "tail_dominates": tail_dominates,
            "tail_loss_multiple": settings.tail_loss_multiple,
        },
        confidence=confidence,
        interpretation=(
            f"EV {ev:+.2f}, worst case {worst.payoff_estimate:+.2f} "
            f"({worst.name}) at {worst.probability:.0%}"
        ),
        context=(
            "Positive EV is necessary but NOT sufficient — survivability of the "
            "tail governs sizing (Module 12.4, LTCM)."
        ),
        inputs_used=["scenarios"],
        warnings=warnings,
    )


def _probability_settings() -> ProbabilitySettings:
    """Read Module 12's probability thresholds. Lazy, to avoid a config cycle."""
    from macro_engine.config import get_settings

    return get_settings().probability
