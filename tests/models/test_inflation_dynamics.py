"""Module 3.3 tests — the expectations-augmented Phillips curve.

The centrepiece here is the **direction test**. ``pi = pi^e - beta*(u - u*)``
contains one minus sign whose placement decides whether a tight labor market is
inflationary or disinflationary. Both readings return plausible numbers on any
given input, so no shape assertion and no magnitude check can distinguish them.
What distinguishes them is asserting the sign on a case whose answer is known
before the code runs: **u below u-star must raise inflation above pi^e**.

This is the D-009 / D-024 discipline applied to a single equation — the same
lesson that took three successive wrong implementations to learn on
``claims_trend_signal``.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import (
    ConfidenceInputs,
    ModelResult,
    compute_confidence,
)
from macro_engine.models.inflation_dynamics import (
    PhillipsCurveInputs,
    phillips_curve_inflation,
)

# --------------------------------------------------------------------------
# Fixtures — hand-verified, from the module docstring's worked examples
# --------------------------------------------------------------------------


def _inputs(**overrides: float) -> PhillipsCurveInputs:
    """The Section 3.3 default case: tight labor market, u = 4.0 vs u* = 4.4."""
    base = {
        "inflation_expectations": 2.5,
        "unemployment_rate": 4.0,
        "nairu": 4.4,
    }
    base.update(overrides)
    return PhillipsCurveInputs(**base)


def _value(result: ModelResult) -> float:
    """Narrow ``value`` to a float, asserting rather than casting."""
    value = result.value
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"expected a numeric value, got {type(value).__name__}"
    )
    return float(value)


# --------------------------------------------------------------------------
# The direction test — the one that catches a misplaced minus sign
# --------------------------------------------------------------------------


def test_tight_labor_market_raises_inflation_above_expectations() -> None:
    """u BELOW u-star must produce inflation ABOVE pi^e.

    Hand calculation: pi^e = 2.5, u = 4.0, u* = 4.4, beta = 0.5.
        gap = 4.0 - 4.4 = -0.4
        pi  = 2.5 - 0.5*(-0.4) = 2.5 + 0.2 = 2.70

    The assertion that matters is the inequality, not the 2.70: it says the
    implied inflation exceeds the expectations term. Writing the equation as
    ``pi^e + beta*(u - u*)`` gives 2.30 here — below pi^e — and this test fails.
    """
    result = phillips_curve_inflation(_inputs())
    assert _value(result) > 2.5, (
        f"u below u* must RAISE inflation above pi^e; got {_value(result)} vs "
        f"pi^e 2.5 — the sign on the slack term is wrong"
    )
    assert _value(result) == pytest.approx(2.70)


def test_slack_labor_market_lowers_inflation_below_expectations() -> None:
    """u ABOVE u-star must produce inflation BELOW pi^e — the other direction.

    Hand calculation: u = 5.4, u* = 4.4 -> gap +1.0, pi = 2.5 - 0.5 = 2.00.

    Paired with the test above, this pins the direction as a *mapping* rather
    than a one-off: an implementation could return a value above pi^e for the
    tight case by accident and still be wrong here.
    """
    result = phillips_curve_inflation(_inputs(unemployment_rate=5.4))
    assert _value(result) < 2.5, f"u above u* must LOWER inflation below pi^e; got {_value(result)}"
    assert _value(result) == pytest.approx(2.00)


def test_inflation_is_monotonic_decreasing_in_unemployment() -> None:
    """Raising u while holding everything else fixed must lower the output.

    A stronger statement than either direction test: it checks the whole
    relationship's shape across several points, so an implementation that got
    both endpoints right by coincidence but reversed in the middle fails.
    """
    values = [
        _value(phillips_curve_inflation(_inputs(unemployment_rate=u)))
        for u in (3.0, 4.0, 5.0, 6.0, 7.0)
    ]
    assert values == sorted(values, reverse=True), (
        f"implied inflation should fall as unemployment rises; got {values}"
    )


def test_at_u_star_inflation_equals_expectations() -> None:
    """With no gap the slack term vanishes, so pi == pi^e exactly.

    This is the identity that makes the equation interpretable: u* is *defined*
    as the unemployment rate at which inflation is stable, so the model must
    return pi^e unchanged there. An implementation with an additive constant, a
    spurious intercept, or a mis-scaled beta fails this while possibly passing
    both direction tests.
    """
    result = phillips_curve_inflation(_inputs(unemployment_rate=4.4, nairu=4.4))
    assert _value(result) == pytest.approx(2.5)


# --------------------------------------------------------------------------
# The cross-field identity
# --------------------------------------------------------------------------


def test_gap_is_actual_minus_nairu_and_reported_value_reconciles() -> None:
    """Recompute the reported inflation from the reported gap and inputs.

    The identity: ``value == pi^e - beta * gap`` where ``gap = u - u*``. Both
    operands come from the caller, so this is a genuine arithmetic check on the
    function rather than a restatement of its branch structure.

    The gap itself is asserted through the interpretation string because it is
    reported there rather than as a separate field — and asserting it is what
    catches a swapped ``nairu - unemployment_rate``, which would invert the sign
    while leaving the magnitude identical.
    """
    beta = get_settings().phillips.beta_value
    for u, nairu in ((3.5, 4.4), (4.4, 4.4), (6.1, 4.4)):
        result = phillips_curve_inflation(_inputs(unemployment_rate=u, nairu=nairu))
        expected = round(2.5 - beta * (u - nairu), 2)
        assert _value(result) == pytest.approx(expected), (
            f"u={u}, u*={nairu}: expected {expected}, got {_value(result)}"
        )
        expected_gap = f"{u - nairu:+.2f}pp"
        assert expected_gap in result.interpretation, (
            f"the reported gap should be {expected_gap} (u - u*); "
            f"interpretation reads {result.interpretation!r}"
        )


def test_gap_sign_is_u_minus_nairu_not_the_reverse() -> None:
    """The gap's SIGN must be negative when u is below u*.

    A swapped subtraction leaves ``abs(gap)`` unchanged and, with the leading
    minus in the equation, can produce the right *magnitude* of adjustment while
    labelling a tight market as slack. The interpretation is the only place the
    gap is surfaced, so it is asserted directly.
    """
    tight = phillips_curve_inflation(_inputs(unemployment_rate=4.0, nairu=4.4))
    assert "-0.40pp" in tight.interpretation, tight.interpretation
    assert "tight" in tight.interpretation, tight.interpretation

    slack = phillips_curve_inflation(_inputs(unemployment_rate=4.8, nairu=4.4))
    assert "+0.40pp" in slack.interpretation, slack.interpretation
    assert "slack" in slack.interpretation, slack.interpretation


# --------------------------------------------------------------------------
# beta comes from config, not the signature
# --------------------------------------------------------------------------


def test_beta_is_read_from_config_and_appears_in_context() -> None:
    """``beta`` is config-driven; the specification's signature default is not used.

    The spec's sample declares ``beta: float = 0.5``. Honouring that as a
    signature default would create a second source of truth that silently wins
    when the argument is omitted. This test asserts the config value is what the
    model uses and reports.
    """
    beta = get_settings().phillips.beta_value
    result = phillips_curve_inflation(_inputs())
    assert f"beta={beta}" in result.context, result.context


def test_beta_is_not_an_input_field() -> None:
    """``beta`` must not be settable per-call — one source of truth.

    Asserted structurally on the model's fields so a future change that
    re-introduces the parameter is visible rather than silently creating a
    shadowing argument.
    """
    assert set(PhillipsCurveInputs.model_fields) == {
        "inflation_expectations",
        "unemployment_rate",
        "nairu",
    }, set(PhillipsCurveInputs.model_fields)


def test_beta_scales_the_slack_term_by_the_configured_amount() -> None:
    """The adjustment from pi^e equals ``-beta * gap`` at the config beta.

    Measured behaviourally rather than read from the code, so a hardcoded 0.5
    that happens to match today's config fails as soon as config moves.
    """
    beta = get_settings().phillips.beta_value
    assert beta > 0, "beta must be positive for the slope to have the right sign"
    result = phillips_curve_inflation(_inputs(unemployment_rate=5.4, nairu=4.4))
    adjustment = _value(result) - 2.5
    assert adjustment == pytest.approx(-beta * 1.0, abs=1e-9)


# --------------------------------------------------------------------------
# Confidence — the unobservability penalty must be applied
# --------------------------------------------------------------------------


def test_confidence_includes_the_unobservable_penalty() -> None:
    """u* is unobservable, so ``depends_on_unobservable`` must be set.

    Asserted by *comparing* against ``compute_confidence`` with and without the
    flag, rather than against a literal. The literal would be uncalibrated until
    Phase 5+, so comparing to it would prove nothing; the difference between the
    two computed values proves the flag is actually being passed.
    """
    with_penalty = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, depends_on_unobservable=True)
    )
    without_penalty = compute_confidence(ConfidenceInputs(is_heuristic_not_calibrated=True))
    assert with_penalty < without_penalty, (
        "the unobservable penalty should reduce confidence — check that "
        "confidence.parameters.unobservable_penalty is positive"
    )
    assert phillips_curve_inflation(_inputs()).confidence == with_penalty


def test_confidence_comes_from_the_shared_producer_not_a_literal() -> None:
    """Section 22.8: no model hardcodes its confidence.

    Two different input sets must return the SAME confidence, because the
    confidence is a function of the computation's stated risks, not of the
    numbers. A hardcoded literal and a computed value are indistinguishable
    from one input set — only varying the inputs while holding the risks fixed
    separates them.
    """
    tight = phillips_curve_inflation(_inputs(unemployment_rate=3.0))
    slack = phillips_curve_inflation(_inputs(unemployment_rate=8.0))
    assert tight.confidence == slack.confidence


# --------------------------------------------------------------------------
# Warning paths
# --------------------------------------------------------------------------


def test_u_star_unobservability_warning_is_unconditional() -> None:
    """Every result must disclose it — it is a property of the equation.

    Asserted on the case with NO u-gap, deliberately: an implementation that
    made the warning conditional on a large gap would pass a test that used only
    a big-gap fixture.
    """
    result = phillips_curve_inflation(_inputs(unemployment_rate=4.4, nairu=4.4))
    assert any("UNOBSERVABLE" in w for w in result.warnings), result.warnings


def test_unanchored_expectations_warning_is_unconditional() -> None:
    """The 1970s dominance caveat is also a property of the equation."""
    result = phillips_curve_inflation(_inputs(unemployment_rate=4.4, nairu=4.4))
    assert any("UNANCHORED" in w for w in result.warnings), result.warnings


def test_negligible_slack_contribution_is_disclosed() -> None:
    """When the slack term contributes ~nothing, say so.

    At u = u* the slack term is exactly zero, so the output is pi^e relabelled.
    A reader who assumed the model had incorporated some information about the
    labor market would be wrong, and the warning is what tells them.
    """
    result = phillips_curve_inflation(_inputs(unemployment_rate=4.4, nairu=4.4))
    assert any("slack term contributes only" in w for w in result.warnings), result.warnings


def test_negligible_slack_warning_does_not_fire_on_a_meaningful_gap() -> None:
    """The complement: a real gap must NOT trigger the negligible-term warning.

    Without this, a warning that fired unconditionally would pass the test
    above. The pair is what pins the condition.
    """
    result = phillips_curve_inflation(_inputs(unemployment_rate=6.4, nairu=4.4))
    assert not any("slack term contributes only" in w for w in result.warnings), result.warnings


def test_negative_implied_inflation_is_flagged() -> None:
    """A negative implied rate requires a large gap or small beta — flag it.

    Hand calculation: pi^e = 1.0, u = 9.0, u* = 4.4, beta = 0.5.
        pi = 1.0 - 0.5*(4.6) = 1.0 - 2.3 = -1.30
    """
    result = phillips_curve_inflation(
        _inputs(inflation_expectations=1.0, unemployment_rate=9.0, nairu=4.4)
    )
    assert _value(result) < 0
    assert any("NEGATIVE" in w for w in result.warnings), result.warnings


def test_negative_inflation_warning_does_not_fire_on_a_positive_result() -> None:
    """The complement of the test above."""
    result = phillips_curve_inflation(_inputs())
    assert not any("NEGATIVE" in w for w in result.warnings), result.warnings


def test_unobservability_warning_states_the_beta_scaled_sensitivity() -> None:
    """The warning quantifies how much a u* error moves the answer.

    A warning saying "u* is uncertain" is not actionable. One saying "a 0.5pp
    error in u* moves inflation by X pp at the current beta" tells a reader how
    much to discount the output — and must track config, since it is derived
    from beta.
    """
    beta = get_settings().phillips.beta_value
    result = phillips_curve_inflation(_inputs())
    expected = f"{abs(beta) * 0.5:.2f}pp"
    assert any(expected in w for w in result.warnings), (
        f"expected the beta-scaled sensitivity {expected} in a warning; got {result.warnings}"
    )


def test_expectations_choice_warning_is_ranked_first() -> None:
    """D-026: the pi^e-measure warning must be FIRST and must say it dominates.

    The specification calls u* "the dominant uncertainty". Live data contradicts
    that: the choice of pi^e measure moved the output ~1.8pp while a 0.5pp u*
    revision moved it ``beta * 0.5``. Both warnings are true, so no test that
    merely *finds* a warning can tell the correct ordering from the incorrect
    one — the ordering must be asserted positionally.

    This test fails if the warnings are reordered back, which is exactly the
    regression it exists to prevent.
    """
    result = phillips_curve_inflation(_inputs())
    assert "largest single source of variation" in result.warnings[0], (
        f"the expectations-measure warning must be emitted FIRST (D-026); "
        f"warnings[0] is {result.warnings[0][:90]!r}"
    )
    # And the u* warning must be explicitly demoted, not left claiming dominance.
    u_star_warning = next(w for w in result.warnings if "UNOBSERVABLE" in w)
    assert "SECOND-ORDER" in u_star_warning, (
        f"the u* warning must say it is second-order to the pi^e choice "
        f"(D-026); got {u_star_warning[:120]!r}"
    )
    assert "dominant uncertainty" not in u_star_warning, (
        "the u* warning must no longer claim to be the dominant uncertainty"
    )


def test_expectations_ratio_exceeds_the_u_star_sensitivity() -> None:
    """The ranking claim in the warning must be arithmetically true, not asserted.

    The warnings say the pi^e choice dominates u*. That is a numeric claim, so
    it is checked numerically: the live-observed pi^e spread (1.83pp, from D-026)
    must exceed the u* sensitivity at the config beta. If a recalibration makes
    beta large enough to reverse the ranking, this test fails and the
    documentation gets revisited rather than going quietly stale.
    """
    beta = get_settings().phillips.beta_value
    observed_pi_e_spread_pp = 1.83  # D-026: 4.20% Michigan vs 2.37% breakeven
    u_star_sensitivity_pp = abs(beta) * 0.5
    assert observed_pi_e_spread_pp > u_star_sensitivity_pp, (
        f"the D-026 ranking assumed the pi^e spread ({observed_pi_e_spread_pp}pp) "
        f"exceeds the u* sensitivity ({u_star_sensitivity_pp:.2f}pp); at "
        f"beta={beta} it does not — the warning ordering now needs revisiting"
    )


# --------------------------------------------------------------------------
# Contract conformance and input validation
# --------------------------------------------------------------------------


def test_result_conforms_to_the_contract() -> None:
    """Section 22.9's value union, and the fields every result must carry."""
    result = phillips_curve_inflation(_inputs())
    assert isinstance(result, ModelResult)
    assert result.model_name == "phillips_curve_inflation"
    assert result.country == "us"
    assert result.as_of.tzinfo is not None
    assert result.as_of.utcoffset() is not None
    assert 0.0 <= result.confidence <= 1.0
    assert result.interpretation
    assert result.context
    assert result.inputs_used == [
        "inflation_expectations",
        "unemployment_rate",
        "nairu",
    ]
    assert result.warnings
    assert isinstance(result.value, (int, float)) and not isinstance(result.value, bool)
    assert math.isfinite(float(result.value))


def test_input_model_rejects_unknown_fields() -> None:
    """``extra="forbid"`` — a typo must not silently fall back to a default."""
    with pytest.raises(ValidationError):
        PhillipsCurveInputs(  # type: ignore[call-arg]
            inflation_expectations=2.5,
            unemployment_rate=4.0,
            nairu=4.4,
            beta=0.5,
        )


def test_beta_passed_as_a_field_is_rejected_rather_than_ignored() -> None:
    """Explicitly: the spec's ``beta`` keyword must fail loudly, not be dropped.

    This is the same test as above stated as its own case, because the failure
    mode is specific and worth naming: a caller transcribing the specification's
    sample will pass ``beta=0.5``. Silently ignoring it would leave them
    believing they had overridden the config value.
    """
    with pytest.raises(ValidationError):
        PhillipsCurveInputs(  # type: ignore[call-arg]
            inflation_expectations=2.5, unemployment_rate=4.0, nairu=4.4, beta=0.9
        )


def test_impossible_unemployment_rate_is_rejected() -> None:
    """An impossible rate fails at the boundary, not downstream.

    The Phase 1 validation discipline applied to model inputs: unemployment of
    150% should never reach the arithmetic and produce a plausible-looking
    inflation number.
    """
    with pytest.raises(ValidationError):
        _inputs(unemployment_rate=150.0)


def test_negative_unemployment_rate_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _inputs(unemployment_rate=-1.0)


def test_negative_nairu_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _inputs(nairu=-0.5)
