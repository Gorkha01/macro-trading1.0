"""Tests for Module 3.6, the real policy rate.

Written as part of the 2026-09-19 ground-up audit's Part B experiment: this
module was added to measure how many files must change to add one new
indicator, and to prove the "new model = one new file returning ModelResult"
claim is true rather than aspirational.

The maths is one subtraction, so the tests that matter are the ones about the
CONTRACT: the returned shape, the confidence producer, the sign convention, and
the ex-post disclosure.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.models.contracts import ConfidenceInputs, ModelResult, compute_confidence
from macro_engine.models.real_policy_rate import RealPolicyRateInputs, real_policy_rate


def test_real_policy_rate_is_nominal_minus_inflation() -> None:
    """``r_real = i - pi`` — hand-verified on a worked example.

    A 5.00% nominal rate against 3.00% inflation is a +2.00% real rate.
    """
    result = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=5.0, inflation_rate=3.0))
    assert result.value == 2.0


def test_a_negative_real_rate_stays_negative() -> None:
    """The sign is the point of the indicator, so it must survive.

    A 2.00% nominal rate against 4.00% inflation is a -2.00% real rate:
    accommodative in real terms despite a positive nominal rate. A model that
    clamped or abs-ed this would destroy the only thing it adds.
    """
    result = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=2.0, inflation_rate=4.0))
    assert result.value == -2.0
    assert isinstance(result.value, float)
    assert result.value < 0


def test_returns_the_standard_contract() -> None:
    """A new model returns ``ModelResult`` — the pluggability requirement."""
    result = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=3.63, inflation_rate=2.45))
    assert isinstance(result, ModelResult)
    assert result.model_name == "real_policy_rate"
    assert result.country == "us"
    assert result.inputs_used == ["nominal_policy_rate", "inflation_rate"]
    # `as_of` is a timezone-aware UTC stamp — never naive (Section 22.8's rule
    # that makes the future-dating check unambiguous).
    assert result.as_of.tzinfo is not None


def test_confidence_comes_from_the_formula_not_a_literal() -> None:
    """Section 22.8: ``compute_confidence`` is the only producer.

    Both inputs are measurements, so no unobservable is declared. The expected
    value is computed by the same function rather than hardcoded, so this test
    fails if either side drifts.
    """
    result = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=3.63, inflation_rate=2.45))
    assert result.confidence == compute_confidence(ConfidenceInputs(depends_on_unobservable=False))


def test_the_ex_post_limitation_is_always_disclosed() -> None:
    """Subtracting realised inflation is not the same as subtracting expected.

    The warning must be unconditional: it is a property of the formula, not of
    a particular input pair, so there is no input for which it is absent.
    """
    result = real_policy_rate(RealPolicyRateInputs(nominal_policy_rate=3.63, inflation_rate=2.45))
    assert result.warnings
    assert any("Ex-post, not ex-ante" in w for w in result.warnings)


def test_extra_inputs_are_refused() -> None:
    """``extra="forbid"`` — a mistyped input fails loudly, not silently."""
    with pytest.raises(ValidationError):
        RealPolicyRateInputs(  # type: ignore[call-arg]
            nominal_policy_rate=3.63,
            inflation_rate=2.45,
            typo_field=1.0,
        )
