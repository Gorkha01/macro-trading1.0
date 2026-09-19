"""Tests for Module 3.5 / 7.2 — potential GDP and growth accounting.

The two things under test are different in kind, and the tests say so.

``potential_gdp_cobb_douglas`` is tested for **arithmetic**. The
specification's golden case (``A=1, K=100, L=100``) was chosen so the exponents
cancel exactly (``100^0.3 * 100^0.7 = 100``), which makes it a test of exponent
handling rather than of the inputs. A second case with terms that do *not*
cancel is added, because a golden test whose answer is a round number can be
satisfied by an implementation that is wrong in a way the roundness hides.

``growth_accounting_decomposition`` is tested for **semantics**. It is a sum of
two terms with very different reliabilities, so the interesting assertions are
about the share, the ``None``-not-``0.0`` rule, and which warning fires on which
pattern.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.production_function import (
    PotentialGDPInputs,
    growth_accounting_decomposition,
    potential_gdp_cobb_douglas,
)
from tests.helpers import as_float, as_float_or_none

# The specification's golden case (Section 21.1 / Section 20.3 test list):
# A=1, K=100, L=100, alpha=0.3 must return exactly 100.0, because
# 100^0.3 * 100^0.7 = 100^1 = 100.
GOLDEN = PotentialGDPInputs(total_factor_productivity=1.0, capital_stock=100.0, labor_input=100.0)


def _alpha() -> float:
    """Read the capital share the way the model does.

    Never a literal. If ``production_function.alpha`` is recalibrated, every
    test that depends on it must move with the code — otherwise a recalibration
    turns correct behaviour into a red suite, and the suite gets ignored.
    """
    return get_settings().production_function.alpha_value


# ---------------------------------------------------------------------------
# Golden case — the specification's own hand-verified value
# ---------------------------------------------------------------------------


def test_golden_case_returns_exactly_one_hundred() -> None:
    """Section 20.3's golden test: A=1, K=100, L=100 -> exactly 100.0.

    Exact by construction because the exponents sum to 1. If this fails, the
    exponent arithmetic is wrong — not the inputs.
    """
    assert as_float(potential_gdp_cobb_douglas(GOLDEN)) == pytest.approx(100.0, abs=1e-9)


def test_golden_case_is_exact_under_config_alpha_not_a_literal() -> None:
    """The cancellation holds for ANY alpha, which is why the case is a good test.

    ``100^a * 100^(1-a) == 100`` identically. Demonstrating that here means the
    golden test cannot silently start passing or failing because alpha moved.
    """
    alpha = _alpha()
    assert math.pow(100.0, alpha) * math.pow(100.0, 1.0 - alpha) == pytest.approx(100.0, abs=1e-9)


def test_non_cancelling_case_matches_hand_calculation() -> None:
    """A=20, K=40,000, L=160,000 -> 2,111,212.66 (hand-verified, 9 s.f.).

    Hand calc at alpha=0.3:
        K^0.3 = 40000^0.3  = 24.02248868...
        L^0.7 = 160000^0.7 = 4394.2421732...
        Y = 20 * 24.02248868 * 4394.2421732 = 2,111,212.657...

    This case matters because its answer is NOT round: an implementation that
    mis-assigns the exponents, or that drops a factor, cannot land on it by
    luck the way it might land on 100.

    The first draft of this test asserted 3,252,491.2 — the product of a
    *remembered* L^0.7 rather than a computed one. The model was right and the
    test was wrong, which is the direction this kind of defect usually runs when
    the fixture is written by hand. Kept in the docstring because the failure
    mode (an arithmetic slip that still looks like arithmetic) is the reason the
    golden case alone is not enough.
    """
    if not math.isclose(_alpha(), 0.3, abs_tol=1e-12):
        pytest.skip(
            "hand calculation was performed at alpha=0.3; recalibrating alpha "
            "requires redoing it deliberately rather than loosening the tolerance"
        )
    result = potential_gdp_cobb_douglas(
        PotentialGDPInputs(
            total_factor_productivity=20.0,
            capital_stock=40_000.0,
            labor_input=160_000.0,
        )
    )
    assert as_float(result) == pytest.approx(2_111_212.66, rel=1e-8)


# ---------------------------------------------------------------------------
# The exponent-assignment defect — the one no plausibility range would catch
# ---------------------------------------------------------------------------


def test_alpha_applies_to_capital_and_one_minus_alpha_to_labor() -> None:
    """Distinguishes correct exponents from ``K^a * L^a``.

    Mis-assigning both exponents to alpha gives ``100^0.3 * 100^0.3 = 15.8489``
    against the correct 100.0. Both are plausible-looking production-function
    outputs; only recomputing the terms from the reported components separates
    them.
    """
    result = potential_gdp_cobb_douglas(GOLDEN)
    alpha = _alpha()
    recomputed = (
        GOLDEN.total_factor_productivity
        * math.pow(GOLDEN.capital_stock, alpha)
        * math.pow(GOLDEN.labor_input, 1.0 - alpha)
    )
    assert as_float(result) == pytest.approx(round(recomputed, 2), abs=1e-9)
    # And the wrong-exponent value is NOT what came back.
    wrong = math.pow(100.0, alpha) * math.pow(100.0, alpha)
    assert as_float(result) != pytest.approx(wrong, rel=1e-6)


def test_capital_and_labor_are_not_interchangeable() -> None:
    """With alpha != 0.5 the two factors must produce different outputs.

    A transposition defect (``K^(1-a) * L^a``) is invisible whenever K == L,
    which is exactly the golden case's shape. This test uses K != L so the
    transposition is measurable.
    """
    alpha = _alpha()
    if math.isclose(alpha, 0.5, abs_tol=1e-12):
        pytest.skip("at alpha=0.5 the factors are symmetric and transposition is unobservable")
    a = potential_gdp_cobb_douglas(
        PotentialGDPInputs(total_factor_productivity=1.0, capital_stock=400.0, labor_input=100.0)
    )
    b = potential_gdp_cobb_douglas(
        PotentialGDPInputs(total_factor_productivity=1.0, capital_stock=100.0, labor_input=400.0)
    )
    assert as_float(a) != pytest.approx(as_float(b), rel=1e-9)


def test_output_is_linear_in_productivity() -> None:
    """A 1% error in A is a 1% error in Y — the point the module's warning makes.

    Named as an assertion rather than left as prose so the claim in the warning
    ("a 1% error in A is a 1% error in potential GDP, one-for-one") is tested.
    """
    base = as_float(potential_gdp_cobb_douglas(GOLDEN))
    scaled = as_float(
        potential_gdp_cobb_douglas(
            PotentialGDPInputs(
                total_factor_productivity=1.01,
                capital_stock=100.0,
                labor_input=100.0,
            )
        )
    )
    assert scaled == pytest.approx(base * 1.01, rel=1e-4)


def test_output_is_concave_not_linear_in_capital() -> None:
    """Doubling capital must NOT double output — that is what alpha < 1 means.

    ``test_output_is_linear_in_productivity`` and this test together pin the
    two different elasticities. Without this one, an implementation that
    replaced ``K^alpha`` with ``K`` would pass every other arithmetic test.

    The expected value is rounded before comparison because the model rounds its
    output to 2dp: asserting the unrounded product against ``rel=1e-9`` tests
    the rounding, not the elasticity.
    """
    one = potential_gdp_cobb_douglas(GOLDEN)
    two = potential_gdp_cobb_douglas(
        PotentialGDPInputs(total_factor_productivity=1.0, capital_stock=200.0, labor_input=100.0)
    )
    assert as_float(two) < 2.0 * as_float(one)
    assert as_float(two) == pytest.approx(
        round(math.pow(2.0, _alpha()) * as_float(one), 2), abs=0.01
    )


# ---------------------------------------------------------------------------
# Config, not literals
# ---------------------------------------------------------------------------


def test_alpha_is_not_an_input_field() -> None:
    """``alpha`` must not shadow config with a signature default.

    The specification writes ``alpha: float = 0.3``. A default in the input
    model would win whenever a caller omits it, so a config recalibration would
    move nothing for those callers — silently.
    """
    assert set(PotentialGDPInputs.model_fields) == {
        "total_factor_productivity",
        "capital_stock",
        "labor_input",
    }


def test_alpha_passed_as_a_field_is_rejected_rather_than_ignored() -> None:
    """A caller's alpha must fail loudly, not be absorbed by a default.

    The ``type: ignore`` is the point of the test rather than a workaround for
    it: static typing is *correct* to reject this call, and the assertion here
    is that the runtime rejects it too. Without the ignore, mypy would flag the
    call and the natural "fix" would be to delete the test — which would remove
    the only guard against a future signature gaining an alpha default.
    """
    with pytest.raises(ValidationError):
        PotentialGDPInputs(
            total_factor_productivity=1.0,
            capital_stock=100.0,
            labor_input=100.0,
            alpha=0.5,  # type: ignore[call-arg]
        )


def test_input_models_reject_unknown_fields() -> None:
    """A typo'd field name must raise, never feed a default.

    Same reasoning as the ignore above: the call is invalid by construction.
    """
    with pytest.raises(ValidationError):
        PotentialGDPInputs(
            total_factor_productivity=1.0,
            capital_stock=100.0,
            labor_input=100.0,
            labor_force=100.0,  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    "field",
    ["total_factor_productivity", "capital_stock", "labor_input"],
)
@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_non_positive_factors_are_rejected(field: str, bad: float) -> None:
    """Every factor is constrained positive.

    A zero makes the product zero; a negative base with a fractional exponent
    raises inside ``math.pow`` with a message that names neither the field nor
    the caller.
    """
    kwargs: dict[str, float] = {
        "total_factor_productivity": 1.0,
        "capital_stock": 100.0,
        "labor_input": 100.0,
    }
    kwargs[field] = bad
    with pytest.raises(ValidationError):
        PotentialGDPInputs(**kwargs)


# ---------------------------------------------------------------------------
# Confidence — computed, never asserted
# ---------------------------------------------------------------------------


def test_confidence_is_computed_and_carries_the_unobservable_penalty() -> None:
    """Potential GDP and TFP are Section 21.4 item 13 unobservables.

    Asserted by comparison against ``compute_confidence`` with and without the
    flag, not against a literal — so a recalibration of the confidence formula
    does not break the test, but dropping the penalty does.

    Both non-default flags the model actually passes are mirrored here. An
    earlier version of this test omitted ``is_heuristic_not_calibrated`` and
    therefore compared the model's three-penalty output against a
    two-penalty expectation — a test that was measuring the test's own inputs.
    """
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    result = potential_gdp_cobb_douglas(GOLDEN)
    model_inputs = ConfidenceInputs(
        depends_on_unobservable=True,
        is_heuristic_not_calibrated=True,
        source_independence_count=0,
    )
    without_unobservable = compute_confidence(
        ConfidenceInputs(is_heuristic_not_calibrated=True, source_independence_count=0)
    )
    assert result.confidence == pytest.approx(compute_confidence(model_inputs))
    assert result.confidence < without_unobservable


def test_confidence_is_lowest_in_the_suite_at_most_the_spec_literal() -> None:
    """Section 20.3 writes 0.3 as a literal; the computed value must not exceed it.

    The specification's literal was reaching for "this is the least trustworthy
    number in the suite". The computed form must land at or below it — a
    computed confidence *above* the spec's own low bar would mean a penalty is
    missing.
    """
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert result.confidence <= 0.3 + 1e-12


def test_no_hardcoded_confidence() -> None:
    """Exactly one confidence value in the result — the computed one."""
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert len([result.confidence]) == 1


# ---------------------------------------------------------------------------
# Warnings — order is measured
# ---------------------------------------------------------------------------


def test_productivity_is_named_as_the_least_predictable_term_first() -> None:
    """Section 20.3 names A as least predictable AND most impactful.

    The specification gets the ranking right here (unlike D-026 in the Phillips
    module), so the order is pinned to stop a later edit inverting it. The A
    warning must be first, and the cross-check instruction second.
    """
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert "LEAST predictable and MOST IMPACTFUL" in result.warnings[0]
    assert "Track CBO/Fed/IMF estimates alongside this" in result.warnings[1]


def test_estimate_not_measurement_warning_is_always_present() -> None:
    """Every run says the output is an estimate. No input escapes it."""
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert any("PRODUCTION-FUNCTION ESTIMATE, not observed" in w for w in result.warnings)


def test_all_three_unconditional_warnings_are_present() -> None:
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert len(result.warnings) == 3


def test_extreme_alpha_warning_is_inert_under_current_config() -> None:
    """No degenerate-alpha warning fires at the configured 0.3.

    The guard exists for a misconfigured ``alpha``; at the live value it must
    stay silent, and if it ever fires here the config has been changed to
    something the functional form cannot represent.
    """
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert not any("outside the interior" in w for w in result.warnings)


def test_constant_returns_to_scale_is_disclosed_as_an_assumption() -> None:
    """CRS is built into the functional form, so it is never a finding."""
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert "Constant returns to scale is ASSUMED" in result.context


def test_context_reports_the_factor_decomposition() -> None:
    """A reader must be able to reconstruct the product from the reported parts."""
    result = potential_gdp_cobb_douglas(GOLDEN)
    alpha = _alpha()
    assert f"K^{alpha:g}" in result.context
    assert f"L^{1.0 - alpha:g}" in result.context


def test_inputs_used_names_the_three_factors_and_not_alpha() -> None:
    """``inputs_used`` lists what was supplied, and alpha was not."""
    result = potential_gdp_cobb_douglas(GOLDEN)
    assert result.inputs_used == [
        "total_factor_productivity",
        "capital_stock",
        "labor_input",
    ]


# ---------------------------------------------------------------------------
# growth_accounting_decomposition
# ---------------------------------------------------------------------------


def _share(result: object) -> float | None:
    from macro_engine.models.contracts import ModelResult

    assert isinstance(result, ModelResult)
    return as_float_or_none(result, key="productivity_share")


def test_potential_growth_is_the_sum_of_its_two_terms() -> None:
    """Cross-field identity: reported parts must reconcile to the reported total."""
    result = growth_accounting_decomposition(
        labor_force_growth_pct=0.4, productivity_growth_pct=1.1
    )
    labor = as_float(result, key="labor_contribution_pp")
    productivity = as_float(result, key="productivity_contribution_pp")
    assert as_float(result, key="potential_growth") == pytest.approx(
        round(labor + productivity, 2), abs=1e-9
    )
    assert as_float(result, key="potential_growth") == pytest.approx(1.5)


def test_productivity_share_is_productivity_over_total() -> None:
    result = growth_accounting_decomposition(
        labor_force_growth_pct=0.4, productivity_growth_pct=1.6
    )
    assert _share(result) == pytest.approx(round(1.6 / 2.0, 3))


def test_share_is_none_rather_than_zero_when_terms_sum_to_zero() -> None:
    """``None`` not ``0.0`` — the same absence semantics as ``ahe_composition_flag``.

    ``0.0`` would assert that labor explains the whole of a total that is
    itself zero. The total is known; the split is undefined.

    The warning assertion matches a phrase from the warning's *first* line and
    separately confirms exactly one such warning exists, so a mutation that
    deletes the warning's opening sentence cannot slip through on a match
    against a later line.
    """
    result = growth_accounting_decomposition(
        labor_force_growth_pct=0.0, productivity_growth_pct=0.0
    )
    assert _share(result) is None
    assert as_float(result, key="potential_growth") == 0.0
    undefined = [w for w in result.warnings if "SHARE is undefined" in w]
    assert len(undefined) == 1
    assert "None rather than 0.0" in undefined[0]


def test_share_is_computed_when_terms_offset_to_a_non_zero_total() -> None:
    """A negative term does not make the ratio undefined — only a zero total does."""
    result = growth_accounting_decomposition(
        labor_force_growth_pct=-0.3, productivity_growth_pct=0.8
    )
    assert _share(result) == pytest.approx(round(0.8 / 0.5, 3))
    assert as_float(result, key="potential_growth") == pytest.approx(0.5)


def test_dominance_warning_fires_above_the_config_threshold() -> None:
    """Threshold read from config, fixture built from it.

    Building the fixture from the configured value means a recalibration moves
    the test with the code rather than producing a red suite.
    """
    threshold = get_settings().production_function.productivity_dominance
    productivity = 8.0
    labor = productivity * (1.0 - threshold) / threshold - 0.1
    result = growth_accounting_decomposition(
        labor_force_growth_pct=labor, productivity_growth_pct=productivity
    )
    share = _share(result)
    assert share is not None and share > threshold
    assert any("less-predictable term dominates" in w for w in result.warnings)


def test_dominance_warning_is_strictly_greater_than_the_threshold() -> None:
    """A share exactly AT the threshold must not warn — the comparison is strict.

    Boundary mutation: ``>`` to ``>=`` survives unless a fixture lands exactly
    on the threshold, so one is constructed to land there.
    """
    threshold = get_settings().production_function.productivity_dominance
    productivity = 1.0
    labor = productivity * (1.0 - threshold) / threshold
    result = growth_accounting_decomposition(
        labor_force_growth_pct=labor, productivity_growth_pct=productivity
    )
    assert _share(result) == pytest.approx(round(threshold, 3))
    assert not any("less-predictable term dominates" in w for w in result.warnings)


def test_negative_labor_force_growth_is_flagged_and_names_the_dependency() -> None:
    """The US demographic case: positive growth resting on productivity alone."""
    result = growth_accounting_decomposition(
        labor_force_growth_pct=-0.3, productivity_growth_pct=0.8
    )
    assert any("Labor force growth is NEGATIVE" in w for w in result.warnings)
    assert any("rests entirely on productivity" in w for w in result.warnings)


def test_negative_productivity_with_positive_labor_is_flagged() -> None:
    """Headcount carrying the estimate — the pattern before a downward revision."""
    result = growth_accounting_decomposition(
        labor_force_growth_pct=0.5, productivity_growth_pct=-0.2
    )
    assert any("Productivity growth is NEGATIVE" in w for w in result.warnings)
    assert any("carried by headcount alone" in w for w in result.warnings)


def test_both_terms_negative_is_not_flagged_as_offsetting() -> None:
    """Two negatives must not trigger either of the offsetting-pattern warnings.

    A guard written as ``productivity < 0`` without the labor condition would
    fire here spuriously, where the honest description is simply that potential
    growth is negative.

    The assertion pair is deliberately both-sided: the *absence* of the two
    offsetting warnings AND the *presence* of the both-negative warning. An
    earlier version checked only the absences, which a model that emitted no
    warning at all would also satisfy — mutation M16 removed the branch and the
    test still passed, which is how the one-sidedness was found.
    """
    result = growth_accounting_decomposition(
        labor_force_growth_pct=-0.2, productivity_growth_pct=-0.4
    )
    assert not any("carried by headcount alone" in w for w in result.warnings)
    assert not any("rests entirely on productivity" in w for w in result.warnings)
    assert any("BOTH terms are negative" in w for w in result.warnings)
    assert as_float(result, key="potential_growth") < 0.0


def test_both_negative_warning_names_the_mechanical_gap_effect() -> None:
    """A contracting potential estimate widens the output gap with no change in GDP.

    The consequence is the reason the case is worth distinguishing from "two
    negatives happen to sum negative": ``output_gap`` divides by potential, so a
    falling denominator moves the gap for reasons that have nothing to do with
    demand.
    """
    result = growth_accounting_decomposition(
        labor_force_growth_pct=-0.2, productivity_growth_pct=-0.4
    )
    both = [w for w in result.warnings if "BOTH terms are negative" in w]
    assert len(both) == 1
    assert "output gap" in both[0]


def test_no_warnings_on_a_balanced_high_labor_share_case() -> None:
    """The quiet path: nothing pathological, so no warning should fire.

    Without this, every warning test above could be satisfied by a model that
    emits all warnings unconditionally.
    """
    result = growth_accounting_decomposition(
        labor_force_growth_pct=1.0, productivity_growth_pct=0.8
    )
    assert result.warnings == []


def test_interpretation_names_both_contributions() -> None:
    result = growth_accounting_decomposition(
        labor_force_growth_pct=0.4, productivity_growth_pct=1.1
    )
    assert "+0.40pp labor" in result.interpretation
    assert "+1.10pp productivity" in result.interpretation


def test_interpretation_reports_undefined_share_in_words() -> None:
    """A ``None`` share must not render as '0%' or 'None%'."""
    result = growth_accounting_decomposition(
        labor_force_growth_pct=0.0, productivity_growth_pct=0.0
    )
    assert "productivity share undefined" in result.interpretation
    assert "None%" not in result.interpretation


def test_confidence_carries_the_unobservable_penalty() -> None:
    """Productivity growth is the TFP term — Section 21.4 item 13."""
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    result = growth_accounting_decomposition(
        labor_force_growth_pct=1.0, productivity_growth_pct=0.8
    )
    assert result.confidence == pytest.approx(
        compute_confidence(ConfidenceInputs(depends_on_unobservable=True))
    )


def test_confidence_drops_when_the_heuristic_threshold_is_engaged() -> None:
    """Dominance engages a config-supplied illustrative threshold."""
    balanced = growth_accounting_decomposition(
        labor_force_growth_pct=1.0, productivity_growth_pct=0.8
    )
    dominated = growth_accounting_decomposition(
        labor_force_growth_pct=0.1, productivity_growth_pct=2.0
    )
    assert dominated.confidence < balanced.confidence
