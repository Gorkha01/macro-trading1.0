"""A non-finite input must be REFUSED, never classified (D-078).

D-074.2 established the mechanism for the FCI: ``nan`` is not null, it is a
*passing* value, and **every comparison a plausibility check is made of returns
``False`` for ``NaN``**. D-074's fix hardened the data layer and the FCI
composite. It did not reach the two models that produce the thesis's headline
verdict — the regime classifier and the Taylor rule — and this module is the
RED test for that gap.

What the hole does, measured before the fix (2026-09-20):

* ``_growth_axis`` is a **bare fallthrough** — ``if gap < recession`` /
  ``if gap < weak`` / ``return "above_trend"``. With ``gap = nan`` both
  comparisons are ``False``, so **absent data lands in the highest-growth
  bucket**. The classifier did not merely fail to notice a missing input; it
  *invented an expansion*.
* ``_inflation_axis`` has the same shape, so ``nan`` momentum became a
  measured **"flat"** and ``inf`` momentum became **"rising"**.
* Together those produced ``state='reflation'`` from an entirely absent
  output gap, and ``state='late_expansion'`` from an infinite momentum.
* ``taylor_rule`` returned a policy-rate prescription of ``nan``.

The rule these tests pin is §21.0 rule 3: a missing input is **not** zero, not
neutral, and not a fallthrough — it is the absence of an answer, and a
classifier asked to label an economy it cannot see must say so.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.models.policy_rules import (
    MarketPricingGap,
    PolicyRuleResult,
    TaylorRuleInputs,
    derive_market_implied_policy_path,
    taylor_rule,
)
from macro_engine.models.regime import (
    RegimeInputs,
    classify_regime_rule_based,
)

_NAN = float("nan")
_INF = float("inf")

# Every non-finite shape a float can take. `-inf` matters separately: a sign
# comparison against `-inf` succeeds, so it takes a DIFFERENT branch from `nan`
# and cannot be covered by testing `inf` alone.
_NON_FINITE = (_NAN, _INF, -_INF)


def _regime_inputs(**overrides: float) -> RegimeInputs:
    """A complete, economically ordinary baseline; one axis is overridden.

    Built as explicit keywords rather than a splatted dict so `mypy --strict`
    can check each argument against its own field type (`RegimeInputs` carries a
    `bool` field, which a `dict[str, float]` cannot express).
    """
    kwargs: dict[str, float | bool] = {
        "output_gap": 0.5,
        "inflation_yoy": 2.5,
        "inflation_trend_3m": 0.1,
        "unemployment_gap": 0.0,
    }
    kwargs.update(overrides)
    return RegimeInputs(
        output_gap=float(kwargs["output_gap"]),
        inflation_yoy=float(kwargs["inflation_yoy"]),
        inflation_trend_3m=float(kwargs["inflation_trend_3m"]),
        unemployment_gap=float(kwargs["unemployment_gap"]),
        output_gap_change=(
            None if kwargs.get("output_gap_change") is None else float(kwargs["output_gap_change"])
        ),
    )


# ---------------------------------------------------------------------------
# The regime classifier: a label must not be manufactured from an absent axis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_output_gap_is_refused_not_classified(bad: float) -> None:
    """The headline defect: `nan` gap was labelled `above_trend`.

    ``_growth_axis`` is a fallthrough, so a gap that satisfies no comparison
    does not fall into a "not measured" state — it falls into the LAST bucket,
    which is the most expansionary one. The classifier therefore reported
    ``growth_axis='above_trend'`` and, with a rising inflation momentum,
    ``state='reflation'``: a bullish regime label built from no observation.
    """
    with pytest.raises((ValidationError, ValueError)):
        classify_regime_rule_based(_regime_inputs(output_gap=bad))


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_inflation_trend_is_refused_not_classified(bad: float) -> None:
    """`nan` momentum was published as `flat`; `inf` as `rising`.

    Both are substantive economic claims. "Flat" asserts the price level is
    neither accelerating nor decelerating, which is a *measurement*; the code
    reached it because ``nan > band`` and ``nan < -band`` are both ``False``.
    """
    with pytest.raises((ValidationError, ValueError)):
        classify_regime_rule_based(_regime_inputs(inflation_trend_3m=bad))


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_inflation_level_is_refused(bad: float) -> None:
    """The level is read (it makes the momentum interpretable), so it is checked."""
    with pytest.raises((ValidationError, ValueError)):
        classify_regime_rule_based(_regime_inputs(inflation_yoy=bad))


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_unemployment_gap_is_refused(bad: float) -> None:
    """`unemployment_gap` feeds `slack_corroborated`, a sign comparison.

    ``(nan < 0.0) == (nan > 0.0)`` is ``False == False``, i.e. ``True`` — so a
    non-finite gap could *satisfy* the corroboration test and raise confidence
    in a label it gave no evidence for.
    """
    with pytest.raises((ValidationError, ValueError)):
        classify_regime_rule_based(_regime_inputs(unemployment_gap=bad))


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_output_gap_change_is_refused(bad: float) -> None:
    """`output_gap_change` is the only route to `recovery`; it is read signed."""
    with pytest.raises((ValidationError, ValueError)):
        classify_regime_rule_based(_regime_inputs(output_gap_change=bad))


def test_a_finite_regime_still_classifies_unchanged() -> None:
    """The guard must not disturb a legitimate reading (no over-reach).

    Pinned to the exact state the probe measured *before* the guard, so the
    fix is proven to reject only the absent value and to leave the real one
    bit-identical.
    """
    result = classify_regime_rule_based(_regime_inputs(output_gap=0.5))
    value = result.value
    assert isinstance(value, dict)
    assert value["state"] == "reflation"
    assert value["growth_axis"] == "above_trend"


# ---------------------------------------------------------------------------
# The Taylor rule: a prescription must be a number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_policy_prescription_is_refused(bad: float) -> None:
    """`taylor_rule(pi_current=nan)` returned ``value=nan`` and pydantic kept it.

    A prescription of ``nan`` is worse than an error: every consumer that asks
    "is the prescribed rate above the actual one?" gets ``False`` — so the rule
    reports *"the Fed is not behind the curve"* **on the strength of a value it
    could not compute**. The `nan` must not survive construction.
    """
    with pytest.raises((ValidationError, ValueError)):
        taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=bad, output_gap=0.5))


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_r_star_or_gap_is_refused(bad: float) -> None:
    """Every scalar the rule reads is checked, not only the headline input."""
    with pytest.raises((ValidationError, ValueError)):
        taylor_rule(TaylorRuleInputs(r_star=bad, pi_current=2.5, output_gap=0.5))
    with pytest.raises((ValidationError, ValueError)):
        taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=2.5, output_gap=bad))


def test_a_finite_policy_prescription_is_unchanged() -> None:
    """A real input still yields a real, finite prescription."""
    result = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=2.5, output_gap=0.5))
    assert isinstance(result, PolicyRuleResult)
    # `PolicyRuleResult.value` is a `float` by the class's own contract; assert
    # the type so `isfinite` receives a `SupportsFloat` rather than the
    # `ModelResult.value` union.
    assert isinstance(result.value, float)
    assert math.isfinite(result.value)


# ---------------------------------------------------------------------------
# The model-vs-market gap: the most consequential place to report a false
# agreement (this class exists to detect a DISAGREEMENT)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_gap_is_refused_not_reported_as_aligned(bad: float) -> None:
    """`direction` returned ``'aligned'`` for a `nan` gap — a fabricated no-trade.

    ``MarketPricingGap.direction`` is a fallthrough on ``raw_gap``: ``> 0`` →
    ``model_above_market``, ``< 0`` → ``model_below_market``, else ``aligned``.
    A `nan` satisfies neither comparison, so it fell to the last branch and the
    class reported **"the model and the market agree."**

    ``is_meaningful`` failed the same way: ``abs(nan) > dispersion`` is
    ``False``, which is documented to mean *"the gap is inside the noise
    floor."* So the two fields agreed on a story — agree, and insignificantly —
    that was drawn entirely from absent data, in the one class the whole thesis
    pipeline exists to build a *disagreement* from.
    """
    with pytest.raises((ValidationError, ValueError)):
        MarketPricingGap(
            model_implied_value=4.0,
            market_implied_value=3.0,
            raw_gap=bad,
            dispersion=0.5,
            is_meaningful=False,
            interpretation="x",
        )


@pytest.mark.parametrize("field", ("model_implied_value", "market_implied_value", "dispersion"))
@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_gap_component_is_refused(field: str, bad: float) -> None:
    """The gap's components are guarded too: `raw_gap` is derived from them.

    Guarding only ``raw_gap`` would leave the class constructible with finite
    components and an inconsistent ``raw_gap``, and — more to the point — the
    components are what the thesis layer publishes as
    ``model_implied_value``/``market_implied_value``. A non-finite one is a
    fabricated model or market path.

    Parametrized per field rather than built as a ``**kwargs`` dict, so each
    case is a literal keyword call and the field under test is named in the
    test ID rather than hidden inside a loop.
    """
    model_implied = 4.0
    market_implied = 3.0
    raw_gap = 1.0
    dispersion = 0.5

    def construct() -> MarketPricingGap:
        if field == "model_implied_value":
            return MarketPricingGap(
                model_implied_value=bad,
                market_implied_value=market_implied,
                raw_gap=raw_gap,
                dispersion=dispersion,
                is_meaningful=True,
                interpretation="x",
            )
        if field == "market_implied_value":
            return MarketPricingGap(
                model_implied_value=model_implied,
                market_implied_value=bad,
                raw_gap=raw_gap,
                dispersion=dispersion,
                is_meaningful=True,
                interpretation="x",
            )
        return MarketPricingGap(
            model_implied_value=model_implied,
            market_implied_value=market_implied,
            raw_gap=raw_gap,
            dispersion=bad,
            is_meaningful=True,
            interpretation="x",
        )

    with pytest.raises((ValidationError, ValueError)):
        construct()


def test_a_finite_gap_still_reports_its_direction() -> None:
    """Both branches of the sign test still work on real values."""
    above = MarketPricingGap(
        model_implied_value=4.0,
        market_implied_value=3.0,
        raw_gap=1.0,
        dispersion=0.5,
        is_meaningful=True,
        interpretation="x",
    )
    assert above.direction == "model_above_market"
    below = MarketPricingGap(
        model_implied_value=2.0,
        market_implied_value=3.0,
        raw_gap=-1.0,
        dispersion=0.5,
        is_meaningful=True,
        interpretation="x",
    )
    assert below.direction == "model_below_market"
    exact = MarketPricingGap(
        model_implied_value=3.0,
        market_implied_value=3.0,
        raw_gap=0.0,
        dispersion=0.5,
        is_meaningful=False,
        interpretation="x",
    )
    assert exact.direction == "aligned"


# ---------------------------------------------------------------------------
# The market-implied path: a NON-FINITE term premium INVERTS the sign
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_short_yield_is_refused(bad: float) -> None:
    """The market path is the reference the entire gap is measured against."""
    with pytest.raises(ValueError):
        derive_market_implied_policy_path(short_yield=bad, short_tenor_term_premium=0.0)


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_a_non_finite_term_premium_is_refused(bad: float) -> None:
    """The adjustment is a SUBTRACTION, so a non-finite premium flips the sign.

    Measured before the fix: ``short_tenor_term_premium=inf`` produced
    ``value=-inf`` — a market-implied path pointing the **opposite way** from
    the raw yield it was meant to adjust. The caller's ``isinstance(x, int |
    float)`` check admits it, because `inf` is a float. A gap computed against
    such a path is a gap against a market that does not exist.
    """
    with pytest.raises(ValueError):
        derive_market_implied_policy_path(short_yield=3.0, short_tenor_term_premium=bad)


def test_a_finite_market_path_is_unchanged() -> None:
    """Both branches still compute on real values (no over-reach)."""
    adjusted = derive_market_implied_policy_path(short_yield=5.0, short_tenor_term_premium=1.5)
    assert adjusted.value == pytest.approx(3.5)
    raw = derive_market_implied_policy_path(short_yield=3.0, short_tenor_term_premium=None)
    assert raw.value == pytest.approx(3.0)
