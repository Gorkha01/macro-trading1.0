"""Module 3.6 — the real policy rate (Part B pluggability experiment).

``real_policy_rate`` = the nominal policy rate minus a year-over-year inflation
rate. A standard macro indicator that the system does not currently compute.

This file exists to answer one question concretely: **how many files must change
to add a new indicator?** It is written as a normal Tier-1 model — pure
arithmetic over two scalars, returning the project's ``ModelResult`` contract,
with no knowledge of where its inputs came from (models do not fetch data).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import ConfidenceInputs, ModelResult, compute_confidence, utc_now

__all__ = ["RealPolicyRateInputs", "real_policy_rate"]


class RealPolicyRateInputs(BaseModel):
    """Two observed scalars. Both real, neither defaulted."""

    model_config = ConfigDict(extra="forbid")

    nominal_policy_rate: float = Field(description="The policy rate, percent. Observed.")
    inflation_rate: float = Field(
        description=(
            "YoY inflation, percent. Observed — and it must be the SAME measure "
            "year-over-year, not a month-over-month figure annualised."
        )
    )


def real_policy_rate(inputs: RealPolicyRateInputs) -> ModelResult:
    """The ex-post real policy rate, in percent.

    ``r_real = i - pi``. Fisher (1930); the ex-post form, because both terms are
    observed rather than expected.

    The sign convention is the whole point of the indicator: a *negative* real
    policy rate means the policy stance is accommodative in real terms, which is
    a different statement from a low nominal rate. Publishing only the nominal
    rate would lose that.

    Confidence is ``compute_confidence``'s to produce, and both inputs are
    measurements here — the arithmetic is exact and neither term is a model
    estimate — so no unobservable is declared and no heuristic flag is set.
    """
    value = inputs.nominal_policy_rate - inputs.inflation_rate

    return ModelResult(
        model_name="real_policy_rate",
        country="us",
        as_of=utc_now(),
        value=round(value, 3),
        confidence=compute_confidence(ConfidenceInputs(depends_on_unobservable=False)),
        interpretation=(
            f"The real policy rate is {value:+.2f}%: a nominal {inputs.nominal_policy_rate:.2f}% "
            f"policy rate against {inputs.inflation_rate:.2f}% inflation."
        ),
        context=(
            f"Ex-post Fisher decomposition: {inputs.nominal_policy_rate:.2f}% nominal "
            f"minus {inputs.inflation_rate:.2f}% inflation. Both terms observed."
        ),
        inputs_used=["nominal_policy_rate", "inflation_rate"],
        warnings=[
            "Ex-post, not ex-ante: this subtracts REALISED inflation, whereas the "
            "policy stance that matters for decisions depends on EXPECTED inflation. "
            "The two diverge exactly when it matters most. Section 21's standing note "
            f"on {get_settings().policy.pi_target_value:.1f}% as the target is a "
            "target, not a forecast.",
        ],
    )
