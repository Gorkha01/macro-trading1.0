"""Module 3.6 — the real policy rate (Part B pluggability experiment).

``real_policy_rate`` = the nominal policy rate minus a year-over-year inflation
rate. A standard macro indicator that the system does not currently compute.

This file exists to answer one question concretely: **how many files must change
to add a new indicator?** It is written as a normal Tier-1 model — pure
arithmetic over two scalars, returning the project's ``ModelResult`` contract,
with no knowledge of where its inputs came from (models do not fetch data).
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    FiniteInputs,
    ModelResult,
    compute_confidence,
    utc_now,
)

__all__ = ["RealPolicyRateInputs", "real_policy_rate"]


class RealPolicyRateInputs(FiniteInputs):
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
    Both flags are stated rather than defaulted, because the number alone cannot
    distinguish "no penalty" from "the heuristic penalty" (they are both 0.20).

    Two caveats are published, and the second is the one a reader is most likely
    to get wrong: this function takes **any** year-over-year inflation measure,
    but the FOMC's objective it is naturally compared against is defined on PCE
    specifically. A CPI-based input and a PCE-based input give two different
    "real policy rates" from the same nominal rate, so the measure has to be
    recorded alongside the result.
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
            "The two diverge exactly when it matters most — a real rate that looks "
            "restrictive on realised data can be accommodative on the expectations "
            "the central bank is actually reacting to.",
            "The inflation measure is the caller's, and it changes the answer "
            "materially. This function accepts any year-over-year rate: CPI, core "
            "CPI, PCE and core PCE are separate upstream surveys that disagree by "
            "tenths of a point, and the same nominal policy rate against a CPI-based "
            "and a PCE-based rate yields two different 'real policy rates'. The FOMC's "
            f"{get_settings().policy.pi_target_value:.1f}% objective is defined on PCE "
            "specifically, so it is NOT a reference point for a CPI-based input — and "
            "it is a TARGET, not a forecast of inflation, so it cannot stand in for "
            "the expected-inflation term this function omits. Record which measure was "
            "passed; the number alone does not say.",
        ],
    )
