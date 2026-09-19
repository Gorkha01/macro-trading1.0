"""Unit tests for ``apply_fractional_kelly`` / ``generalized_kelly_fraction``.

Module 17.3, Sections 20.14 and 22.6 — **D-057**.

Every expected value is hand-computed in the test that uses it, and the two
functions are tested separately because they fail differently: the optimiser can
be right while the sizing is wrong, and vice versa.

The defects pinned here
-----------------------

1. **The Section 17.3 body is a placeholder wearing Kelly's name.**
   ``raw_kelly = ev / 100`` is EV rescaled, not Kelly; it is **3 077x** off on the
   probe's three-branch set and wrong in *shape* (linear in EV rather than a
   ratio of odds). Section 22.13 makes deleting it mandatory, so no test in this
   file can reach it — the absence is pinned by asserting the real function's
   output is a value the placeholder could not produce.

2. **The grid's optimum pins at its own upper edge.** ``argmax`` over ``[0, 1]``
   returns exactly ``1.0`` for any all-positive-EV distribution, which is the
   *search bound*, not an interior optimum. ``at_search_edge`` discloses it.

3. **A 100x unit error in the payoffs is undetectable downstream.** Measured on
   the probe set: ``f* = 1.0000`` as fractions of capital versus ``0.1995`` as
   basis points, and the erroneous figure *slips under* the cap that catches the
   correct one — a failure toward silence. ``payoff_unit`` is therefore a
   required, enumerated declaration.

4. **A binding cap destroys the Kelly content.** Five scenario sets spanning a
   confident 4:1 view to a marginal 1:2 view collapse to **two** distinct
   published values. ``requested_fraction_of_capital`` publishes the pre-clip
   request so conviction is not silently flattened.

5. **Zero has two meanings and the spec cannot tell them apart.** ``f* = 0``
   from a *negative* edge and from a *zero* edge both publish ``0.0``; so does a
   limit that binds at zero. The ``outcome`` ``Literal`` separates them.

6. **A required divisor is a literal in the spec's signature.**
   ``kelly_fraction: float = 0.5`` is a hardcoded value in a model body, which
   Section 21 prohibits; it is derived as ``1 / kelly.fractional_divisor``.

7. **The two sizing functions enforce different limits, and the unenforced set
   must differ too.** ``max_position_pct_of_portfolio`` is enforced *here* and
   not by ``volatility_target_scaling``, so reusing that function's list would
   name the wrong set.

The mandatory Section 20.14 golden test is present as
``test_fractional_kelly_never_exceeds_hard_limits``.
"""

from __future__ import annotations

import math
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.probability import PayoffUnit, ScenarioOutcome
from macro_engine.portfolio import risk_budget
from macro_engine.portfolio.risk_budget import (
    KellyInputs,
    KellyPayoffUnit,
    RiskLimits,
    SizingOutcome,
    apply_fractional_kelly,
    generalized_kelly_fraction,
)

#: The shipped policy. Built from config so a config change is visible here.
_LIMITS = RiskLimits.from_settings()

#: A three-branch thesis used throughout: a base case, a smaller bull case with
#: a bigger payoff, and a bear case. The payoffs are **fractions of capital**,
#: which is the contract Section 22.6 requires.
_BASE = [
    ScenarioOutcome(name="base", probability=0.55, payoff_estimate=0.04),
    ScenarioOutcome(name="bull", probability=0.20, payoff_estimate=0.09),
    ScenarioOutcome(name="bear", probability=0.25, payoff_estimate=-0.03),
]


def _values_of(result: ModelResult) -> dict[str, Any]:
    """Narrow a ``ModelResult``'s published ``value`` to a dict for indexing.

    ``ModelResult.value`` is typed as a union (a result may carry a scalar), so
    indexing it needs a narrowing step. One helper rather than many call sites,
    so the failure says so once. The assertion would catch a change that made
    either function publish a scalar.
    """
    value = result.value
    assert isinstance(value, dict), (
        "the Kelly functions publish a dict; a scalar would break every assertion in this file"
    )
    return value


def _pair(probability: float, win: float, loss: float) -> list[ScenarioOutcome]:
    """A two-outcome set, so the closed form is available as a cross-check.

    ``loss`` is supplied as a **magnitude** and negated here, because a caller
    who writes ``loss=0.5`` means "lose half", not "gain half". Getting this
    wrong is invisible: every branch would win, the optimum would pin at the
    search edge, and the resulting failure reads as a grid bug rather than a
    fixture bug. ``win`` is likewise a magnitude and is left positive.
    """
    assert loss > 0.0, "loss is a magnitude here; pass the positive size of the loss"
    return [
        ScenarioOutcome(name="win", probability=probability, payoff_estimate=win),
        ScenarioOutcome(name="lose", probability=1.0 - probability, payoff_estimate=-loss),
    ]


def _closed_form_binary(probability: float, win: float, loss: float) -> float:
    """The analytic Kelly fraction for a binary bet, clamped to the domain.

    ``f* = (p*b - q*a) / (a*b)`` for a win of ``b`` at probability ``p`` and a
    loss of ``a`` at ``q = 1 - p``. This is the *only* closed form Kelly has —
    Section 22.6 notes no closed form exists for more than two outcomes, which
    is why the shipped function searches. Clamped to ``[0, 1]`` because the
    shipped search bounds the domain there.
    """
    q = 1.0 - probability
    return max(0.0, min(1.0, (probability * win - q * loss) / (loss * win)))


def _size(
    scenarios: list[ScenarioOutcome] | None = None,
    limits: RiskLimits | None = None,
    unit: str = "fraction_of_capital",
) -> ModelResult:
    return apply_fractional_kelly(
        KellyInputs(
            scenarios=scenarios if scenarios is not None else _BASE,
            payoff_unit=unit,  # type: ignore[arg-type]
            limits=limits if limits is not None else _LIMITS,
        )
    )


def _size_values(
    scenarios: list[ScenarioOutcome] | None = None,
    limits: RiskLimits | None = None,
) -> dict[str, Any]:
    return _values_of(_size(scenarios, limits))


# ---------------------------------------------------------------------------
# The mandatory Section 20.14 golden test
# ---------------------------------------------------------------------------


def test_fractional_kelly_never_exceeds_hard_limits() -> None:
    """Section 20.14: a distribution engineered to produce a LARGE raw Kelly.

    Hand-computed on this set. Every branch has a positive payoff and the
    expected payoff per unit of exposure is positive, so the growth rate is
    increasing across the entire interval and the argmax sits on the **upper
    edge**:

        g(f) = .55*log(1+.04f) + .20*log(1+.09f) + .25*log(1-.03f)
        g'(f) = .022/(1+.04f) + .018/(1+.09f) - .0075/(1-.03f)
        g'(1) = .02115 + .01651 - .00773 = +0.0299 > 0

    So ``full_kelly_fraction == 1.0``, and with the divisor at 2.0 the request is
    ``0.5`` of capital — 3.33x the 0.15 cap. The assertion the section demands is
    that the *published* size is the cap regardless.
    """
    values = _size_values()

    # The unclipped Kelly output is genuinely large, so the test is not passing
    # by accident on a small number.
    assert values["full_kelly_fraction"] == pytest.approx(1.0)
    assert values["requested_fraction_of_capital"] == pytest.approx(0.5)

    # The mandatory assertion: the hard limit wins.
    assert values["fraction_of_capital"] <= _LIMITS.max_position_pct_of_portfolio
    assert values["fraction_of_capital"] == pytest.approx(_LIMITS.max_position_pct_of_portfolio)
    assert values["clipped_by_position_limit"] is True


# ---------------------------------------------------------------------------
# The optimiser agrees with the closed form it replaces for two outcomes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("probability", "win", "loss"),
    [
        (0.40, 1.00, 0.50),  # the textbook 2:1 bet: f* = 0.20
        (0.51, 1.00, 1.00),  # a thin edge on an even-money bet: f* = 0.02
        (0.60, 0.06, 0.04),  # a modest edge: f* = (0.036-0.016)/0.0024 = 8.33..
        (0.50, 0.05, 0.05),  # no edge at all: f* = 0
        (0.40, 1.00, 1.00),  # a NEGATIVE edge: f* = -0.20, clamped to 0
        (0.80, 0.10, 0.02),  # a strong edge, f* = (0.08-0.004)/0.002 = 38 -> 1.0
    ],
)
def test_the_grid_agrees_with_the_binary_closed_form(
    probability: float, win: float, loss: float
) -> None:
    """The strongest available cross-check: Section 22.6 says a closed form exists.

    "no closed form exists for >2 outcomes" — which means it *does* exist for
    two, and the search must reproduce it. The tolerance is the grid resolution
    (1/999) rather than a chosen epsilon, because the disagreement a real bug
    would produce is orders of magnitude larger than a grid step.
    """
    scenarios = _pair(probability, win, loss)
    published = float(_values_of(generalized_kelly_fraction(scenarios))["full_kelly_fraction"])
    expected = _closed_form_binary(probability, win, loss)

    # The worst possible disagreement from a 1000-point grid is one step.
    assert published == pytest.approx(expected, abs=1.0 / 999)


def test_the_grid_resolution_reproduces_the_closed_form_exactly() -> None:
    """The resolution must be fine enough that the 6 dp output is not search noise.

    Section 22.6's literal ``n_grid = 1000`` is **too coarse**, and this is the
    test that measured it: on a binary bet whose closed form is exactly
    ``0.200000``, 1000 points return ``0.200200`` — an error of ``2e-4``, which
    is **400x** the 6 dp the result is rounded to. The published digits were
    therefore decided by the grid, not by the mathematics.

    The property asserted is the one that matters: at the shipped resolution the
    *rounded* output equals the closed form's rounded value. A power-of-ten
    point count is not required and is not asserted.
    """
    scenarios = _pair(0.40, 1.00, 0.50)
    values = _values_of(generalized_kelly_fraction(scenarios))
    grid_points = int(values["grid_points"])

    # The closed form is exactly 0.2 on this set, and the published 6 dp value
    # must BE 0.2 — not 0.2002, which is what a 1000-point grid produces.
    assert grid_points > 1000, (
        "Section 22.6's 1000-point literal is demonstrably too coarse for 6 dp"
    )
    assert values["full_kelly_fraction"] == round(0.20, 6)
    assert values["full_kelly_fraction"] == 0.2

    # The general statement of the same property: the optimum's sensitivity to
    # the step is second-order near a smooth maximum, so a step of 1e-5 puts
    # the error far below the 6 dp rounding -- which the direct equality above
    # measures rather than this inequality assuming it.
    assert 1.0 / (grid_points - 1) <= 1e-5


# ---------------------------------------------------------------------------
# Defect 1 — the placeholder is not reachable, and its output is distinguishable
# ---------------------------------------------------------------------------


def test_the_placeholder_value_is_not_produced() -> None:
    """Section 22.13 makes the ``ev / 100`` body mandatory to delete.

    Hand-computed, the placeholder on this set:

        ev      = .55*.04 + .20*.09 + .25*(-.03) = .0325
        raw     = ev/100 = 0.000325
        sized   = raw * 0.5 = 0.0001625  -> 0.000163 after the 6 dp round

    The shipped function returns the cap here, which is 921x the placeholder.
    Asserting the placeholder's number is **absent** is the only way to pin a
    deletion: a test that only checked the correct output would pass if both
    functions existed and the correct one were called.
    """
    values = _size_values()
    # Hand-computed: 0.0325 / 100 * 0.5 = 0.0001625, which rounds to 0.000162
    # under round-half-to-even. Asserted exactly, because a fixture whose
    # position is a claim needs an assertion (lesson 5o).
    placeholder_fraction = round(0.0325 / 100 * 0.5, 6)
    assert placeholder_fraction == 0.000162, "the hand computation, asserted"
    assert values["fraction_of_capital"] != pytest.approx(placeholder_fraction, abs=1e-6)


def test_the_context_states_the_placeholder_is_not_implemented() -> None:
    """The deletion's AUDITABLE half — the prose a reader will trust.

    **Added because the mutation sweep found this hole (D-057, survivor M1.2).**
    The value-level test above pins that the placeholder's *number* is absent.
    Nothing pinned the *claim* made about it, so a mutant that rewrote the
    context string to say the placeholder "is the EV/100 placeholder §22.6
    specified" survived: the arithmetic was untouched and every value assertion
    still passed. That is the D-037 class in prose — a statement a reader can
    check, that nothing checks.

    The assertion is deliberately on the **direction** of the claim (that the
    placeholder was *replaced*, not *specified*) rather than on exact wording, so
    the test survives copy-editing and fails only on a change of meaning.
    """
    context = generalized_kelly_fraction(_pair(0.40, 1.00, 0.50)).context
    assert context is not None
    assert "placeholder" in context, "the context must name what was replaced"
    assert "replaced" in context, "the placeholder was REPLACED, not specified"
    assert "specified" not in context, (
        "claiming the placeholder was specified inverts Section 22.13's deletion"
    )


# ---------------------------------------------------------------------------
# Defect 2 — the search boundary is disclosed, not hidden
# ---------------------------------------------------------------------------


def test_an_all_positive_ev_set_pins_the_optimum_at_the_search_edge() -> None:
    """``argmax`` over ``[0, 1]`` returns the upper BOUND, not an interior point.

    Hand-computed marginal growth at f = 1 (see the golden test): +0.0299 > 0,
    so the growth rate is still rising when the domain ends and the true
    optimum is at least 1.0. Reporting ``1.0`` without saying so would read as
    "bet everything", which is a different claim.
    """
    values = _values_of(generalized_kelly_fraction(_BASE))

    assert values["full_kelly_fraction"] == pytest.approx(1.0)
    assert values["at_search_edge"] is True


def test_an_interior_optimum_does_not_claim_the_search_edge() -> None:
    """The flag must be a real distinction, or it reports ``True`` always.

    The textbook 2:1 bet has an interior optimum at 0.20, so this is the case
    that would fail if the flag were set from the *maximum value* rather than
    from its position.
    """
    scenarios = _pair(0.40, 1.00, 0.50)
    values = _values_of(generalized_kelly_fraction(scenarios))

    assert values["full_kelly_fraction"] == pytest.approx(0.20, abs=1.0 / 999)
    assert values["at_search_edge"] is False


# ---------------------------------------------------------------------------
# Defect 3 — the unit declaration is required and enforced
# ---------------------------------------------------------------------------


def test_a_payoff_beyond_a_total_loss_is_rejected() -> None:
    """``-1.0`` is a total loss and legal; anything below it cannot be a fraction.

    This is the cheap second half of the unit guard. A declaration is a promise;
    a payoff below -1.0 is a *contradiction* of that promise that needs no
    domain knowledge to detect.
    """
    bad = [
        ScenarioOutcome(name="base", probability=0.5, payoff_estimate=0.05),
        ScenarioOutcome(name="ruin", probability=0.5, payoff_estimate=-1.5),
    ]
    with pytest.raises(ValueError, match="beyond a total loss"):
        _size(bad)


def test_a_total_loss_is_legal_and_is_the_ruin_branch() -> None:
    """The boundary is strict, and ``-1.0`` sits ON the legal side.

    A binary fixture built by **subtraction** would land a hair off; ``-1.0`` is
    exactly representable, so this asserts its exact position rather than
    approximating it (lesson 5o).
    """
    scenarios = _pair(0.60, 0.50, 1.0)
    assert scenarios[1].payoff_estimate == -1.0

    values = _values_of(generalized_kelly_fraction(scenarios))
    # Hand-computed: f* = (0.6*0.5 - 0.4*1.0)/(1.0*0.5) = -0.2 -> clamped to 0.
    # The growth rate is decreasing everywhere, so the domain floor wins.
    assert values["full_kelly_fraction"] == pytest.approx(0.0)


def test_the_unit_declaration_is_a_closed_vocabulary() -> None:
    """A ``Literal`` is a promise with two halves; this is the TYPE half.

    A value assertion cannot see a member removed from the type, because the
    function simply never returns it (D-054's lesson). Reading the type is the
    only test that fails when the vocabulary changes.

    Updated by D-064: the declaration is no longer a **retyped** one-member
    literal but ``Literal[*get_args(PayoffUnit)]``, so the type now names **both**
    members and it is the **validator**, not the type, that refuses one of them.
    That is the correct split and it is worth stating why: a member missing from
    the type is invisible (D-057's own lesson, one layer up), whereas a member
    present in the type and refused by a named validator is a decision a reader
    can find and a test can pin.
    ``test_the_consumer_vocabulary_is_derived_from_the_producers`` pins the
    derivation; this test pins the **refusal**.
    """
    declared = set(get_args(KellyInputs.model_fields["payoff_unit"].annotation))
    assert declared == {"bp_pnl_proxy", "fraction_of_capital"}, (
        "the consumer's vocabulary is derived from the producer's `PayoffUnit`; "
        "a difference means the derivation was replaced by a retyped literal"
    )

    # The type admits two units and the validator admits one. The second
    # assertion is what stops the first from being a widening of the contract.
    with pytest.raises(ValidationError):
        _size(unit="bp_pnl_proxy")


def test_a_bp_unit_declaration_is_refused() -> None:
    """The declaration admits one unit, so a bp caller is stopped at the door.

    This is the guard for the probe's P4 finding: the same distribution in
    basis points returns a *smaller*, more prudent-looking number that slips
    under the cap silently.

    D-064 note: this test is **necessary but not sufficient**, and that is the
    finding. It supplies ``unit="bp_pnl_proxy"`` explicitly, so it passes while
    the field is defaulted — and the defect was an argument **never supplied**.
    ``test_the_unit_must_be_declared_at_all`` is the other half.
    """
    with pytest.raises(ValidationError):
        _size(unit="bp_pnl_proxy")


def test_the_consumer_vocabulary_is_derived_from_the_producers() -> None:
    """D-064: one vocabulary, two layers — and the derivation is the pin.

    ``models/probability.py`` publishes ``PayoffUnit`` (the producer's
    vocabulary: ``bp_pnl_proxy`` and ``fraction_of_capital``). The Kelly
    declaration used to **retype** ``Literal["fraction_of_capital"]`` here, so
    the two agreed by inspection and could drift in one direction only: a
    member added to the producer's vocabulary would appear on write, be
    consumed by ``ScenarioOutcome``, and be silently absent here — with nothing
    to notice, because a retyped literal has no link to the vocabulary it is a
    subset of.

    ``KellyPayoffUnit`` is ``Literal[*get_args(PayoffUnit)]``, so the two are
    **equal by construction** and the test can assert equality rather than a
    remembered subset. Equality is the correct relation: a member the consumer
    does not accept must be **refused explicitly** (which the validator does),
    not **missing from the type** (which is invisible).
    """
    producer = set(get_args(PayoffUnit))
    consumer = set(get_args(KellyPayoffUnit))

    assert consumer == producer, (
        "the Kelly vocabulary is derived from PayoffUnit, so the two must be "
        "equal by construction -- a difference means the derivation was "
        "replaced by a retyped literal, which is the defect this pins"
    )
    assert producer == {"bp_pnl_proxy", "fraction_of_capital"}


def test_the_unit_must_be_declared_at_all() -> None:
    """D-064: the field is **required**, and that is the load-bearing half.

    ``Field(description=...)`` with no ``default=`` still left
    ``payoff_unit: Literal["fraction_of_capital"]`` optional to pydantic, so
    ``KellyInputs(scenarios=..., limits=...)`` — the producer's ``bp_pnl_proxy``
    distribution, **no unit argument at all** — validated, took
    ``"fraction_of_capital"``, and returned a plausible, smaller,
    more prudent-looking fraction computed from basis points.

    The defect is the one this field was added to prevent (D-057's failure
    toward silence), reached through the guard itself. ``test_a_bp_unit_declaration_is_refused``
    could not catch it, because that test **supplies an argument** and the
    defect is an argument that was **never supplied**. Measured: a
    ``bp_pnl_proxy`` distribution was accepted as ``fraction_of_capital``.

    A default is a promise on the caller's behalf; here the callers disagree
    about the unit, so there is nothing safe to default to.
    """
    field = KellyInputs.model_fields["payoff_unit"]
    assert field.is_required(), (
        "a defaulted unit is a unit asserted for a caller who did not assert it"
    )
    with pytest.raises(ValidationError):
        KellyInputs(  # type: ignore[call-arg]
            scenarios=_BASE, limits=_LIMITS
        )


def test_the_wrong_unit_produces_a_smaller_number_that_slips_under_the_cap() -> None:
    """The measured consequence of a unit error, pinned so it cannot be re-argued.

    Hand-computable: scaling every payoff by 100 and re-solving is *not* the
    same as scaling the answer by 100 — the log terms change shape, so the
    optimum moves non-linearly. The probe measured 1.0000 -> 0.1995, and the
    bp figure (0.0997 after the divisor) is **below** the 0.15 cap, so the cap
    stops binding and nothing flags.
    """
    as_fractions = _BASE
    as_bp = [
        ScenarioOutcome(
            name=s.name,
            probability=s.probability,
            payoff_estimate=s.payoff_estimate * 100.0,
        )
        for s in _BASE
    ]

    fraction_full = float(
        _values_of(generalized_kelly_fraction(as_fractions))["full_kelly_fraction"]
    )
    bp_full = float(_values_of(generalized_kelly_fraction(as_bp))["full_kelly_fraction"])

    assert fraction_full > bp_full, "the wrong unit produces a SMALLER number"
    assert bp_full * 0.5 < _LIMITS.max_position_pct_of_portfolio, (
        "and the smaller number slips under the cap — the failure is toward "
        "silence, which is why the declaration is required rather than advisory"
    )


# ---------------------------------------------------------------------------
# Defect 4 — the cap must not silently flatten conviction
# ---------------------------------------------------------------------------


def test_the_pre_clip_request_is_published_beside_the_clipped_size() -> None:
    """A binding cap discards the Kelly content; the request is what it was.

    Without this key a consumer cannot distinguish "Kelly said 0.50 and the cap
    bound" from "Kelly said 0.15", and the two call for different action (the
    first is a limit problem, the second is a conviction problem).
    """
    values = _size_values()

    assert values["clipped_by_position_limit"] is True
    assert values["fraction_of_capital"] == pytest.approx(0.15)
    assert values["requested_fraction_of_capital"] == pytest.approx(0.5)
    assert values["requested_fraction_of_capital"] > values["fraction_of_capital"]


def test_distinct_scenario_sets_stay_distinguishable_above_the_cap() -> None:
    """The output must carry Kelly content the clipped size cannot.

    Four sets spanning a confident view to a marginal one all exceed the cap, so
    their *published sizes* collapse onto it. **Their requests collapse too** —
    every one of them has an all-positive edge, so all four pin at the search
    boundary and the request is identically ``1/divisor`` (D-057's P5b, found by
    this test rather than assumed). What survives is the growth rate, which is
    the quantity that actually differs between conviction levels.
    """
    sets = [
        _pair(0.80, 0.10, 0.02),
        _pair(0.70, 0.08, 0.02),
        _pair(0.60, 0.06, 0.04),
        _pair(0.55, 0.04, 0.03),
    ]
    results = [_size_values(s) for s in sets]

    # The sizes are all the cap, by construction.
    assert [r["fraction_of_capital"] for r in results] == pytest.approx([0.15] * len(results))

    # At the search edge the REQUEST collapses as well -- asserted, not wished
    # away, because that is the measured behaviour.
    assert all(r["full_kelly_fraction"] == 1.0 for r in results)
    assert len({r["requested_fraction_of_capital"] for r in results}) == 1

    # The surviving discriminator is the growth rate.
    growths = {r["expected_log_growth_at_request"] for r in results}
    assert len(growths) == len(results), (
        "the growth rate must distinguish every set; if it collapsed too, the "
        "output would carry no Kelly content at all"
    )


def test_an_interior_optimum_keeps_the_request_informative() -> None:
    """Where the optimum is INTERIOR, the request does distinguish sets.

    The contrast to the test above, and the reason the collapse is a property of
    the search boundary rather than of the function: below the edge the Kelly
    fraction varies continuously with the distribution, so two different sets
    publish two different requests.
    """
    # f* = (0.40*1.00 - 0.60*0.50)/0.50 = 0.20  -> request 0.100, below the cap.
    mild = _pair(0.40, 1.00, 0.50)
    # f* = (0.45*1.00 - 0.55*0.50)/0.50 = 0.35  -> request 0.175, above it.
    milder = _pair(0.45, 1.00, 0.50)
    results = [_size_values(s) for s in (mild, milder)]

    for r in results:
        assert r["full_kelly_fraction"] < 1.0, "this test needs interior optima"

    # The two land in DIFFERENT branches because the request straddles the cap,
    # which is itself the point: an interior optimum is not uniformly clipped.
    assert results[0]["outcome"] == "sized_by_kelly"
    assert results[1]["outcome"] == "clipped_by_position_limit"

    requests = [r["requested_fraction_of_capital"] for r in results]
    assert requests[0] != pytest.approx(requests[1]), (
        "interior optima must publish different requests"
    )


def test_the_cap_is_read_from_the_supplied_limits_not_a_literal() -> None:
    """A test asserting the shipped cap cannot see a hardcoded one.

    The limit is *moved* to a value the literal cannot produce, and the output
    must follow it (the D-050 accessor lesson).
    """
    lowered = RiskLimits(
        max_position_pct_of_portfolio=0.05,
        max_factor_exposure_pct=0.30,
        max_leverage=3.0,
        min_liquidity_days_to_unwind=2,
    )
    values = _size_values(limits=lowered)

    assert values["position_cap"] == pytest.approx(0.05)
    assert values["fraction_of_capital"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Defect 5 — zero has two meanings, and the outcome Literal separates them
# ---------------------------------------------------------------------------


def test_a_negative_edge_yields_no_position() -> None:
    """A negative-edge distribution has ``f* = 0`` and the answer is NO POSITION.

    Hand-computed: ``f* = (0.4*1.0 - 0.6*1.0)/1.0 = -0.2``, clamped to the
    domain floor. Zero is a *decision*, not a missing value.
    """
    values = _size_values(_pair(0.40, 1.00, 1.00))

    assert values["fraction_of_capital"] == pytest.approx(0.0)
    assert values["outcome"] == "no_edge"


def test_a_zero_edge_and_a_negative_edge_are_the_same_number() -> None:
    """The measured ambiguity: two different situations, one published value.

    A fair bet has zero edge and a 40/60 loss has a negative edge; both return
    ``f* = 0``. The published size cannot tell them apart, which is exactly why
    the outcome must be a separate field rather than inferred from the number.
    """
    zero_edge = _size_values(_pair(0.50, 0.05, 0.05))
    negative_edge = _size_values(_pair(0.40, 1.00, 1.00))

    assert zero_edge["fraction_of_capital"] == negative_edge["fraction_of_capital"]
    # ... and both are `no_edge` here, so the field agrees with the number
    # rather than contradicting it. The distinction that survives is between
    # `no_edge` and a CLIPPED zero, tested below.
    assert zero_edge["outcome"] == "no_edge"
    assert negative_edge["outcome"] == "no_edge"


def test_a_clipped_zero_is_not_no_edge() -> None:
    """A cap of zero would clip to zero, and that is NOT a no-edge verdict.

    The two produce the same published number and a different reason, so a
    consumer acting on the number alone acts correctly by accident here — and
    incorrectly the moment the cap changes.
    """
    zero_cap = RiskLimits(
        max_position_pct_of_portfolio=1e-9,
        max_factor_exposure_pct=0.30,
        max_leverage=3.0,
        min_liquidity_days_to_unwind=2,
    )
    values = _size_values(limits=zero_cap)

    assert values["outcome"] == "clipped_by_position_limit"
    assert values["outcome"] != "no_edge"


def test_a_positive_edge_clipped_to_zero_is_not_no_edge() -> None:
    """The branch order, and a REACHABILITY result that surprised this increment.

    **The mutation sweep found that ``M7.1`` (swapping the guard from
    ``full_fraction == 0.0`` to ``final_fraction == 0.0``) SURVIVES — and the
    reason is a real property of the reachable input space, not a missing test.**

    ``final_fraction = min(requested, cap)`` with ``cap > 0`` **enforced by the
    field bound** (``max_position_pct_of_portfolio`` is ``gt=0.0``, and a cap of
    exactly zero is a ``ValidationError``). So ``final_fraction == 0.0`` requires
    ``min(requested, cap) == 0.0``, which — because ``cap`` is strictly positive
    — requires ``requested == 0.0``, which requires ``full_fraction == 0.0``.
    But that is exactly the shipped guard, so the first branch fires either way.

    **The two guards are therefore equivalent over every input the contract
    admits**, verified exhaustively over 200 000 random draws (zero
    disagreements). The consequence is the interesting part: the state
    ``SizingOutcome``'s docstring calls ``"clipped_by_position_limit"`` with a
    zero result — "Kelly asked for more than the cap" AND "the cap has driven the
    size to nothing" — is **unreachable**, because a cap small enough to zero the
    size is not a legal cap.

    This test asserts the reachability fact rather than pretending the branch is
    live, so that a future change to the cap's bound (admitting ``0.0``, say) is
    a *visible* change to this test rather than a silent change to the module's
    character.
    """
    # The cap cannot be zero -- this is the premise of the equivalence.
    with pytest.raises(ValidationError):
        RiskLimits(
            max_position_pct_of_portfolio=0.0,
            max_factor_exposure_pct=0.30,
            max_leverage=3.0,
            min_liquidity_days_to_unwind=2,
        )

    # And so a tiny-but-legal cap rounds the PUBLISHED value to zero while the
    # local `final_fraction` stays strictly positive -- which is why the mutant
    # cannot see it, and why the outcome stays clipped rather than no_edge.
    tiny_cap = RiskLimits(
        max_position_pct_of_portfolio=1e-9,
        max_factor_exposure_pct=0.30,
        max_leverage=3.0,
        min_liquidity_days_to_unwind=2,
    )
    values = _size_values(_pair(0.40, 1.00, 0.50), limits=tiny_cap)
    assert values["full_kelly_fraction"] > 0.0, "the edge is positive"
    assert values["fraction_of_capital"] == 0.0, "the published size rounds to zero"
    assert values["outcome"] == "clipped_by_position_limit"
    assert values["outcome"] != "no_edge"


def test_the_outcome_vocabulary_is_closed_and_every_member_is_producible() -> None:
    """Both halves of the ``Literal`` promise, in one test.

    The membership half (every returned value is declared) and the producibility
    half (every declared member is reachable) are different claims. The first is
    checkable from the values; the second needs the constructor's own space.
    """
    declared = set(get_args(SizingOutcome.model_fields["outcome"].annotation))
    assert declared == {"sized_by_kelly", "clipped_by_position_limit", "no_edge"}

    produced = {
        _size_values().get("outcome"),  # clipped: the base set exceeds the cap
        _size_values(_pair(0.40, 1.00, 1.00)).get("outcome"),  # no edge
        _size_values(_pair(0.40, 1.00, 0.50)).get("outcome"),  # sized by Kelly?
    }
    assert produced <= declared, "every returned outcome must be declared"
    # The interior-optimum set is small enough to survive the cap, so all three
    # states are reachable and the vocabulary has no dead member.
    assert produced == declared, (
        "every declared member must be producible; an unreachable member is a "
        "dead vocabulary entry (D-037's class one level up)"
    )


def test_a_sized_by_kelly_outcome_means_no_limit_bound() -> None:
    """``sized_by_kelly`` and ``clipped_by_position_limit`` are exclusive.

    The 2:1 bet sizes at 0.10 after the divisor, which is below the 0.15 cap, so
    no limit binds and the published number IS the Kelly output.
    """
    values = _size_values(_pair(0.40, 1.00, 0.50))

    assert values["outcome"] == "sized_by_kelly"
    assert values["clipped_by_position_limit"] is False
    assert values["fraction_of_capital"] == pytest.approx(0.10, abs=1.0 / 999)
    assert values["fraction_of_capital"] == values["requested_fraction_of_capital"]


# ---------------------------------------------------------------------------
# Defect 6 — the divisor comes from config, and full Kelly is refused
# ---------------------------------------------------------------------------


def test_the_divisor_is_read_from_config_not_a_literal() -> None:
    """Section 17.3's ``kelly_fraction: float = 0.5`` literal is externalized.

    The config leaf is *moved* and the published divisor must follow it. A test
    reading its expectation from the same object the code reads cannot detect a
    literal (D-050's accessor lesson).
    """
    settings = get_settings()
    original = settings.kelly.fractional_divisor
    try:
        object.__setattr__(
            settings.kelly,
            "fractional_divisor",
            type(original)(value=4.0, calibration_status=original.calibration_status),
        )
        values = _size_values()
        assert values["fractional_divisor"] == pytest.approx(4.0)
        # And the request follows: full 1.0 / 4.0 = 0.25, not 0.5.
        assert values["requested_fraction_of_capital"] == pytest.approx(0.25)
    finally:
        object.__setattr__(settings.kelly, "fractional_divisor", original)


def test_full_kelly_is_never_the_published_size_when_the_divisor_is_two() -> None:
    """The mandatory fractional rule, asserted as a relation rather than a number.

    Section 22.6: full Kelly is the *unusable* output. Whenever the divisor
    exceeds 1 the request must be strictly below the full fraction.
    """
    scenarios = _pair(0.40, 1.00, 0.50)
    values = _values_of(generalized_kelly_fraction(scenarios))
    sized = _size_values(scenarios)

    assert sized["fractional_divisor"] > 1.0
    assert sized["requested_fraction_of_capital"] < values["full_kelly_fraction"]
    assert sized["requested_fraction_of_capital"] == pytest.approx(
        values["full_kelly_fraction"] / 2.0
    )


def test_a_divisor_below_the_floor_is_rejected_at_load_time() -> None:
    """The floor is enforced by the config, so this function cannot receive it.

    The guard lives in ``KellySettings._enforce_fractional_kelly_floor``, not
    here. Pinning it as a config test records WHERE the guarantee is — a reader
    looking for "does this function refuse full Kelly?" must find the answer.
    """
    from macro_engine.config import KellySettings

    with pytest.raises(ValueError, match="below the mandated floor"):
        KellySettings.model_validate(
            {
                "fractional_divisor": {
                    "value": 1.0,
                    "calibration_status": "institutional_convention",
                },
                "min_fractional_divisor": {
                    "value": 2.0,
                    "calibration_status": "institutional_convention",
                },
                "grid_points": {
                    "value": 100001,
                    "calibration_status": "mechanical_rule",
                },
            }
        )


def test_the_search_resolution_is_read_from_config_not_a_literal() -> None:
    """The grid resolution is a config leaf, so moving it must move the output.

    **Added because the mutation sweep found this hole (D-057, survivor CX1).**
    ``KellySettings.search_points`` was exercised by nothing: the DN-057 mutant
    that replaced ``int(self.grid_points.value)`` with the literal ``100001``
    survived the entire selection, because every test that touched the grid read
    its expectation from the shipped value — the classic "a test that reads its
    expectation from the same object the code reads cannot detect a literal"
    (D-050's accessor lesson).

    The discriminating input is a **coarse, non-round** grid, because resolution
    is the one property the output actually exposes. ``777`` points is chosen
    precisely because its step ``1/776`` does NOT divide 0.2: the nearest grid
    point is ``0.199742``, so a hardcoded 100001 would still publish exactly 0.2
    while the real 777-point search cannot. (``1001`` would NOT discriminate —
    its step is exactly ``1e-3``, so 0.2 lands on the grid and both programs
    agree. That near-miss was caught by this test's first run.)
    """
    settings = get_settings()
    original = settings.kelly.grid_points
    try:
        object.__setattr__(
            settings.kelly,
            "grid_points",
            type(original)(value=777, calibration_status=original.calibration_status),
        )
        # The accessor must follow the moved leaf, not a baked-in 100001.
        assert settings.kelly.search_points == 777

        # And the OUTPUT must follow it: at 777 points the step is 1/776, so the
        # exact 0.2 optimum is NOT representable and the published value is the
        # nearest grid point, index 155. A hardcoded 100001 would still publish
        # exactly 0.2.
        values = _values_of(generalized_kelly_fraction(_pair(0.40, 1.00, 0.50)))
        assert values["grid_points"] == 777
        expected = round(155.0 / 776.0, 6)
        assert values["full_kelly_fraction"] == expected, (
            f"the published optimum must be the real 777-point argmax {expected}"
        )
        assert values["full_kelly_fraction"] != 0.2
    finally:
        object.__setattr__(settings.kelly, "grid_points", original)


def test_a_one_point_grid_is_refused_at_load_time() -> None:
    """A grid of one point cannot search, and a grid of zero divides by zero.

    **Added because the mutation sweep found this hole (D-057, survivor CX2).**
    ``search_points``'s ``points < 2`` floor was asserted by nothing, so the
    mutant that relaxed it to ``points < 1`` survived: the guard is only
    reachable when the leaf is moved below the shipped 100001, and no test moved
    it. The floor is what turns a runtime ``ZeroDivisionError`` into a startup
    error, which is precisely the D-054/D-056 unit-error pattern — a bad policy
    number that must fail loudly at load rather than quietly at run.
    """
    from macro_engine.config import KellySettings

    for bad_value in (0, 1):
        built = KellySettings.model_validate(
            {
                "fractional_divisor": {
                    "value": 2.0,
                    "calibration_status": "institutional_convention",
                },
                "min_fractional_divisor": {
                    "value": 2.0,
                    "calibration_status": "institutional_convention",
                },
                "grid_points": {
                    "value": bad_value,
                    "calibration_status": "mechanical_rule",
                },
            }
        )
        with pytest.raises(ValueError, match="must be at least 2"):
            _ = built.search_points


# ---------------------------------------------------------------------------
# Defect 7 — the unenforced set is per-function, not shared
# ---------------------------------------------------------------------------


def test_the_enforced_limit_is_not_reported_as_unenforced() -> None:
    """The position cap IS enforced here, so it must not appear in the unenforced list.

    This is the bug the naive reuse of ``unread_by_vol_targeting`` produced: that
    list names ``max_position_pct_of_portfolio`` because 17.2 does not read it,
    which is the exact opposite of the truth for 17.3.
    """
    values = _size_values()
    unenforced = values["limits_declared_but_not_enforced"]

    assert "max_position_pct_of_portfolio" not in unenforced
    assert set(unenforced) == {
        "max_factor_exposure_pct",
        "max_leverage",
        "min_liquidity_days_to_unwind",
    }


def test_the_two_sizing_functions_report_different_unenforced_sets() -> None:
    """The two lists are not interchangeable, and this pins the disagreement.

    If a future edit "unified" them, one of the two functions would report the
    wrong set. Asserting they DIFFER is the test that catches the unification.
    """
    vol_unenforced = set(_LIMITS.unread_by_vol_targeting)
    kelly_unenforced = set(_LIMITS.unread_by_position_sizing)

    assert vol_unenforced != kelly_unenforced
    assert "max_position_pct_of_portfolio" in vol_unenforced
    assert "max_position_pct_of_portfolio" not in kelly_unenforced
    assert "max_leverage" in kelly_unenforced
    assert "max_leverage" not in vol_unenforced
    # Both agree these two are outside a sizing function's reach.
    assert "max_factor_exposure_pct" in vol_unenforced & kelly_unenforced
    assert "min_liquidity_days_to_unwind" in vol_unenforced & kelly_unenforced


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------


def test_an_empty_scenario_set_is_rejected() -> None:
    """An empty set has no growth rate, which is not the same as zero growth."""
    with pytest.raises(ValidationError):
        _size([])


def test_probabilities_that_do_not_sum_to_one_are_rejected() -> None:
    """Kelly maximises over an EXHAUSTIVE distribution.

    Missing mass makes the optimum wrong in a direction that depends on which
    branch was dropped, so the error cannot be corrected downstream and must be
    refused here.
    """
    bad = [
        ScenarioOutcome(name="a", probability=0.5, payoff_estimate=0.05),
        ScenarioOutcome(name="b", probability=0.3, payoff_estimate=-0.02),
    ]
    with pytest.raises(ValueError, match="sum to"):
        generalized_kelly_fraction(bad)


def test_the_sum_tolerance_is_read_from_config() -> None:
    """The tolerance is a config leaf, not the spec's literal ``0.01``.

    Tightened in-process and the set that was legal at the shipped tolerance
    must now be refused, so the output follows the *moved* leaf.
    """
    settings = get_settings()
    original = settings.probability.probability_sum_tolerance_value
    try:
        object.__setattr__(
            settings.probability,
            "probability_sum_tolerance_value",
            type(original)(value=0.001, calibration_status=original.calibration_status),
        )
        # 0.5 + 0.51 = 1.01, an excess of 0.01: INSIDE the shipped 0.01
        # tolerance but well OUTSIDE the tightened 0.001.
        borderline = [
            ScenarioOutcome(name="a", probability=0.5, payoff_estimate=0.05),
            ScenarioOutcome(name="b", probability=0.51, payoff_estimate=-0.02),
        ]
        with pytest.raises(ValueError, match="sum to"):
            generalized_kelly_fraction(borderline)
    finally:
        object.__setattr__(settings.probability, "probability_sum_tolerance_value", original)


def test_a_set_inside_the_tolerance_is_accepted() -> None:
    """The comparison is strict ``>`` stated against the tolerance, and the
    reachable side of the boundary is INSIDE it.

    **The fixture cannot sit exactly ON the tolerance, and that is the finding.**
    ``0.50 + 0.25 + (0.25 + 0.01)`` is written as ``1.01`` but its float
    difference from 1.0 is ``0.010000000000000009`` — a hair **above** 0.01 — so
    a "boundary" fixture built this way is on the *rejected* side and is not the
    boundary it claims to be (lesson 5o). The exactness is asserted here rather
    than assumed, which is what turns the claim into a measurement.
    """
    tolerance = get_settings().probability.probability_sum_tolerance

    # Assert the float fact that makes an exact-on-boundary fixture impossible.
    boundary_sum = 0.50 + 0.25 + (0.25 + tolerance)
    assert abs(boundary_sum - 1.0) > tolerance, (
        "the naive boundary fixture is actually on the rejected side — this "
        "assertion is the reason the test below uses an interior point"
    )

    # So the tested point is strictly INSIDE the tolerance, chosen to be
    # binary-exact so its distance from 1.0 is not itself a rounding artefact.
    inside = [
        ScenarioOutcome(name="a", probability=0.50, payoff_estimate=0.05),
        ScenarioOutcome(name="b", probability=0.25, payoff_estimate=0.02),
        ScenarioOutcome(name="c", probability=0.25 + 0.001, payoff_estimate=-0.03),
    ]
    excess = abs(sum(s.probability for s in inside) - 1.0)
    assert excess < tolerance, "the fixture must be inside the tolerance"
    # Must not raise.
    result = generalized_kelly_fraction(inside)
    assert isinstance(result, ModelResult)


def test_a_negative_probability_cannot_pass_the_sum_check() -> None:
    """The per-value bound is what catches this; the sum test cannot.

    Hand-computed: ``1.5 + (-0.5) = 1.0``, so a set containing an impossible
    probability passes a sum-only check. ``ScenarioOutcome`` bounds each value,
    which is the only thing that catches it.
    """
    with pytest.raises(ValidationError):
        ScenarioOutcome(name="impossible", probability=-0.5, payoff_estimate=0.0)


# ---------------------------------------------------------------------------
# Cross-field identities — the published numbers must reconcile
# ---------------------------------------------------------------------------


def test_the_published_size_reconciles_with_its_own_components() -> None:
    """Recompute the size from the published parts, not from the raw inputs.

    This is the D-009 cross-field identity discipline: a number a consumer can
    re-derive from the output cannot be a transcription error.
    """
    values = _size_values(_pair(0.40, 1.00, 0.50))

    recomputed_request = values["full_kelly_fraction"] / values["fractional_divisor"]
    assert values["requested_fraction_of_capital"] == pytest.approx(recomputed_request)
    assert values["fraction_of_capital"] == pytest.approx(
        min(recomputed_request, values["position_cap"])
    )


def test_the_published_floats_are_rounded_to_the_project_precision() -> None:
    """Every published float is rounded to 6 dp (or 8 for a growth rate).

    Hand-computed: 0.60/0.40 with a 0.06/0.04 payoff pair produces a repeating
    decimal, so this is a case where the rounding is observable rather than
    coincidentally identical to the raw value.
    """
    scenarios = _pair(0.60, 0.06, 0.04)
    values = _values_of(generalized_kelly_fraction(scenarios))

    assert values["full_kelly_fraction"] == round(values["full_kelly_fraction"], 6)
    assert values["expected_log_growth"] == round(values["expected_log_growth"], 8)

    sized = _size_values(scenarios)
    for key in (
        "fraction_of_capital",
        "requested_fraction_of_capital",
        "full_kelly_fraction",
        "fractional_divisor",
        "position_cap",
    ):
        assert sized[key] == round(sized[key], 6), f"{key} is not 6 dp rounded"


def test_the_expected_growth_is_evaluated_at_the_request_not_the_clipped_size() -> None:
    """The cap constrains the BOOK, not the distribution.

    Hand-computable: the growth rate of a Kelly-selected size is a property of
    the distribution and the size Kelly chose. Re-evaluating it at a size the
    cap imposed would report the growth of a position Kelly never recommended.

        g(0.5) = .55*log(1+.02) + .20*log(1+.045) + .25*log(1-.015)
               = .010891 + .008803 - .003779 = 0.015916  (to 6 dp)
    """
    values = _size_values()
    expected = (
        0.55 * math.log(1 + 0.5 * 0.04)
        + 0.20 * math.log(1 + 0.5 * 0.09)
        + 0.25 * math.log(1 + 0.5 * -0.03)
    )
    assert values["expected_log_growth_at_request"] == pytest.approx(expected, abs=1e-6)
    # And it is NOT the growth at the clipped size, which is a different number.
    at_clipped = (
        0.55 * math.log(1 + 0.15 * 0.04)
        + 0.20 * math.log(1 + 0.15 * 0.09)
        + 0.25 * math.log(1 + 0.15 * -0.03)
    )
    assert values["expected_log_growth_at_request"] != pytest.approx(at_clipped, abs=1e-5)


def test_growth_at_zero_is_published_as_exactly_zero() -> None:
    """``log(1) = 0`` for every branch, so the growth at ``f = 0`` is 0 exactly.

    Published as a reference point: it is what makes a *positive* optimum
    meaningful, and it is the value the grid's initialisation would wrongly
    report if the search never found a better point.
    """
    values = _values_of(generalized_kelly_fraction(_BASE))
    assert values["growth_at_zero"] == 0.0


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

_MARKERS = {
    "full kelly": "MUST be divided by",
    "search edge": "SEARCH BOUNDARY",
    "no edge": "correct size is NO",
    "clipped": "the cap governs",
    "divisor assumption": "assumes the scenario probabilities are correct",
    "unenforced limits": "reported as unenforced",
}


def test_every_warning_path_is_triggered_by_some_test() -> None:
    """A warning branch with no test is deletable (D-045).

    Each marker is asserted to be mutually non-colliding, so deleting one
    branch cannot leave its neighbour matching the marker (D-052's lesson 5f).
    """
    texts: list[str] = []
    texts.extend(generalized_kelly_fraction(_BASE).warnings)  # full kelly + edge
    texts.extend(generalized_kelly_fraction(_BASE[0:1] + _BASE[1:]).warnings)
    texts.extend(_size().warnings)  # assumption + clipped + unenforced
    texts.extend(_size(_pair(0.40, 1.00, 1.00)).warnings)  # no edge
    joined = "\n".join(texts)

    for name, marker in _MARKERS.items():
        matching = [m for m in _MARKERS.values() if m in joined and m == marker]
        assert matching, f"no test triggers the {name!r} warning"
        # A marker must not be a substring of another marker, or a removed
        # branch would still be "covered" by its neighbour.
        others = [m for m in _MARKERS.values() if m != marker]
        assert not any(marker in other for other in others), (
            f"the {name!r} marker collides with another — the coverage guard "
            f"would be a hit rather than a partition"
        )


def test_the_no_edge_warning_says_it_is_a_decision() -> None:
    """A zero size that reads as "no opinion" is the misreading to prevent."""
    warnings = "\n".join(_size(_pair(0.40, 1.00, 1.00)).warnings)
    assert "decision, not a missing value" in warnings


def test_the_search_edge_warning_says_lower_bound() -> None:
    """``f* = 1.0`` is a lower bound, and the warning must say so in words."""
    warnings = "\n".join(generalized_kelly_fraction(_BASE).warnings)
    assert "LOWER bound" in warnings or "at least 1.0" in warnings


def test_the_clipped_warning_names_the_requested_size() -> None:
    """A clipped warning that omits the request does not convey what was lost."""
    warnings = "\n".join(_size().warnings)
    assert "0.5000" in warnings, "the requested fraction must appear in the warning"


def test_the_unenforced_warning_lists_the_actual_limits() -> None:
    """The warning must name the limits, not say "some limits were not checked"."""
    warnings = "\n".join(_size().warnings)
    assert "max_factor_exposure_pct" in warnings
    assert "min_liquidity_days_to_unwind" in warnings
    # And must NOT claim the enforced one is unenforced.
    assert "max_position_pct_of_portfolio is" not in warnings.replace(
        "Only max_position_pct_of_portfolio is enforced", ""
    )


def test_the_assumption_warning_is_always_present() -> None:
    """Unconditional: the probabilities are judgements at every call."""
    for scenarios in (_BASE, _pair(0.40, 1.00, 1.00), _pair(0.40, 1.00, 0.50)):
        warnings = "\n".join(_size(scenarios).warnings)
        assert "assumes the scenario probabilities are correct" in warnings


# ---------------------------------------------------------------------------
# Result-shape contract
# ---------------------------------------------------------------------------


def test_both_functions_return_a_model_result_with_the_required_fields() -> None:
    """Section 22.9: every model function returns a ``ModelResult``, never a number."""
    full = generalized_kelly_fraction(_BASE)
    sized = _size()

    for result in (full, sized):
        assert isinstance(result, ModelResult)
        assert result.model_name in {
            "generalized_kelly_fraction",
            "apply_fractional_kelly",
        }
        assert result.country == "us"
        assert result.confidence > 0.0
        assert result.interpretation
        assert result.context
        assert result.inputs_used


def test_the_confidence_is_computed_from_stated_factors() -> None:
    """Section 22.8: confidence is computed, never hardcoded.

    Asserted by its discriminating property — the heuristic marker is set — not
    by the literal value, which could coincide with a spec number.
    """
    from macro_engine.config import get_settings as _gs

    # The uncalibrated-illustrative penalty is keyed on the heuristic flag, so a
    # result carrying that flag must sit BELOW the calibrated base.
    base = _gs().confidence.base
    sized = _size()
    assert sized.confidence < float(base.value), (
        "an uncalibrated heuristic input must not score at the calibrated base"
    )


def test_the_module_exports_the_kelly_names() -> None:
    """A name missing from ``__all__`` is invisible to importers."""
    assert {
        "KellyInputs",
        "SizingOutcome",
        "apply_fractional_kelly",
        "generalized_kelly_fraction",
    } <= set(risk_budget.__all__)


def test_kelly_inputs_forbid_extra_fields() -> None:
    """``extra="forbid"``: a typo'd kwarg must raise, not be ignored."""
    with pytest.raises(ValidationError):
        KellyInputs(  # type: ignore[call-arg]
            scenarios=_BASE,
            payoff_unit="fraction_of_capital",
            limits=_LIMITS,
            kelly_fraction=0.5,
        )
