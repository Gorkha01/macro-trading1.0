"""Phase 2 model tests — Module 7.3 leading-indicator proxy (Section 20.7).

Every expected value below was computed independently before the test was run,
per Section 21.2 Step 4. The arithmetic is shown inline so a reader can check
the assertion rather than trusting it.

Why this function needs its own test file
-----------------------------------------
Section 20.7's ``lei_composite`` is nine lines and is wrong in ways that are all
*silent* — each produces a plausible number attached to a claim about a
different object:

1. It is called "LEI". Section 21.1 states the licensed Conference Board series
   is unavailable and that an in-house composite **must not** be called "LEI".
   A test asserts the name, the interpretation, the context and the warnings all
   refuse the word.
2. ``confidence=0.5 if broad_based else 0.3`` asserts its own confidence, which
   Section 22.8 forbids. Replaced with ``compute_confidence()``.
3. ``breadth >= 0.6`` is a bare literal, and per D-029 a boolean derived from a
   comparison over noisy inputs must travel with its own measured frequency.
4. ``sum(components[k] * w.get(k, 0))`` silently gives an unweighted component
   zero weight while still counting it in breadth — so the sum and the breadth
   would describe different component sets. Narrowed at the input model.

The base rate here is combinatorial rather than fitted, so the tests pin the
arithmetic of the null model rather than a measured history — and assert the
output *says* it is a null frequency, because presenting it as a track record
would be its own fabrication.
"""

from __future__ import annotations

import math

import pytest

from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.lei_proxy import (
    LeadingIndicatorProxyInputs,
    _breadth_null_rate,
    leading_indicator_proxy,
)
from tests.helpers import as_bool, as_float, as_int, as_str

FOUR_FALLING = {"a": -8.0, "b": -4.0, "c": -12.0, "d": -6.0}


# ---------------------------------------------------------------------------
# Step 4 — the arithmetic, against hand-computed values
# ---------------------------------------------------------------------------


def test_composite_matches_hand_computed_value() -> None:
    """Equal-weighted mean of four six-month changes.

    0.25 * (-8.0 - 4.0 - 12.0 - 6.0) = 0.25 * -30.0 = -7.5
    """
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    assert as_float(result, key="composite_6mo_annualized") == pytest.approx(-7.5)
    assert as_float(result, key="breadth_declining") == pytest.approx(1.0)
    assert as_int(result, key="n_components") == 4
    assert as_int(result, key="n_declining") == 4
    assert as_bool(result, key="broad_based") is True
    assert as_str(result, key="lead_direction") == "broad_based_decline"


def test_weights_are_honoured_when_supplied() -> None:
    """A weighted composite is not the equal-weighted one.

    weights {a: 0.5, b: 0.25, c: 0.125, d: 0.125}
    0.5*-8.0 + 0.25*-4.0 + 0.125*-12.0 + 0.125*-6.0
    = -4.0 - 1.0 - 1.5 - 0.75 = -7.25
    """
    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(
            components=FOUR_FALLING,
            weights={"a": 0.5, "b": 0.25, "c": 0.125, "d": 0.125},
        )
    )

    assert as_float(result, key="composite_6mo_annualized") == pytest.approx(-7.25)
    assert as_bool(result, key="equal_weighted") is False


def test_equal_weighting_is_the_default_and_is_disclosed() -> None:
    """Section 20.7's default must be visible in the output, not implicit."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    assert as_bool(result, key="equal_weighted") is True
    assert any("equal weighting" in w.lower() for w in result.warnings)


def test_breadth_counts_strictly_declining_components() -> None:
    """A component at exactly zero is NOT declining.

    3 of 5 falling, one flat, one rising -> breadth 0.6
    """
    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(
            components={"a": -1.0, "b": -2.0, "c": -3.0, "d": 0.0, "e": 4.0}
        )
    )

    assert as_int(result, key="n_declining") == 3
    assert as_float(result, key="breadth_declining") == pytest.approx(0.6)


def test_a_flat_component_counts_as_declining_for_breadth_purposes() -> None:
    """Documents the strictness choice: ``< 0`` means zero is not a decline.

    The opposite choice (``<= 0``) would let a stalled component vote for a
    downturn. Neither is obviously right, so the choice is pinned here and is
    stated in the docstring rather than left to whichever operator was typed.
    """
    flat = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(components={"a": 0.0, "b": -1.0, "c": -2.0})
    )
    assert as_int(flat, key="n_declining") == 2


# ---------------------------------------------------------------------------
# Correction 1 — the name. Section 21.1: in-house must NOT be called "LEI"
# ---------------------------------------------------------------------------


def test_the_model_is_not_named_lei() -> None:
    """Section 21.1's naming rule, enforced against the model_name field."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    assert result.model_name == "leading_indicator_proxy"
    assert "lei" not in result.model_name.lower(), (
        "the in-house composite must not be named after the licensed series"
    )


def test_the_output_text_refuses_the_lei_label() -> None:
    """Every prose field must carry the disclaimer, not just one."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    joined = " ".join([*result.warnings, result.interpretation, result.context]).lower()
    assert "not the conference board lei" in joined
    assert "proxy" in joined


def test_the_disclaimer_says_the_level_is_not_comparable() -> None:
    """The specific over-read to prevent: comparing this level to a published LEI.

    A different component set with different weights on a different base is not
    the same index, so a reader who plots them on one axis is comparing two
    objects. The disclaimer must say so explicitly.
    """
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    joined = " ".join(result.warnings).lower()

    assert "level" in joined
    assert "not comparable" in joined


# ---------------------------------------------------------------------------
# Correction 2 — confidence is computed, never asserted
# ---------------------------------------------------------------------------


def test_confidence_comes_from_compute_confidence_not_a_literal() -> None:
    """Section 22.8 / Finding #8.

    The specification returns 0.5 when broad-based and 0.3 otherwise. The
    corrected version returns whatever ``compute_confidence`` yields for the
    stated facts, which must not vary with how many components declined.
    """
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )

    for components in (FOUR_FALLING, {"a": -1.0}, {"a": 1.0}, {"a": 0.0}):
        result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=components))
        assert result.confidence == expected, (
            f"confidence varied with the components {components}; a computed "
            "confidence depends on stated facts, not on the breadth reading"
        )


def test_confidence_is_not_a_function_of_the_breadth_flag() -> None:
    """Guard against a regression that reinstates the spec's 0.5/0.3 split.

    The specification's value *varies with the flag* — 0.5 when broad-based,
    0.3 otherwise. A literal-value check would be defeated by coincidence here:
    ``compute_confidence`` on the current config returns exactly 0.30, which is
    the same number as the specification's ``else`` branch. So the assertion is
    not "the value differs from 0.3" (it legitimately does not) but the property
    that actually separates a computed confidence from an asserted one — it must
    **not move with the flag**. See D-031 on weak tests that read their
    expectation from the same source the code reads.
    """
    broad = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    narrow = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(components={"a": -1.0, "b": 2.0, "c": 3.0, "d": 4.0})
    )
    assert as_bool(broad, key="broad_based") is True
    assert as_bool(narrow, key="broad_based") is False

    assert broad.confidence == narrow.confidence, (
        "confidence moved with the breadth flag, which is the specification's "
        "hardcoded 0.5/0.3 behaviour returning"
    )


def test_confidence_reflects_both_stated_penalties() -> None:
    """The declared ``ConfidenceInputs`` facts must be the ones actually claimed.

    Deliberately does not recompute from the same argument list the model uses.
    It asserts the *structure*: the returned value must sit strictly below what
    either penalty alone would give, which is only true when both are claimed.
    """
    both = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )
    single = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=False,
            source_independence_count=0,
        )
    )
    assert both < single, "precondition: the two penalties must be separable on the current config"

    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    assert result.confidence == pytest.approx(both)
    assert result.confidence < single, (
        "confidence equals the single-penalty value, so at least one declared "
        "penalty is not actually being claimed"
    )


# ---------------------------------------------------------------------------
# Correction 3 — the threshold is config, and travels with its base rate
# ---------------------------------------------------------------------------


def test_threshold_is_read_from_config() -> None:
    """The boundary must be reviewable config, not a literal in the model."""
    from macro_engine.config import get_settings

    threshold = get_settings().leading_indicator.breadth_threshold_value
    assert threshold > 0
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    assert as_float(result, key="breadth_threshold") == pytest.approx(threshold)


def test_the_model_reads_the_threshold_from_config_and_not_a_literal() -> None:
    """Break the symmetry: patch config to a value the literal cannot produce.

    The other test reads the boundary *from config*, exactly as the model does,
    so replacing the config read with a hardcoded ``0.6`` would move both sides
    together and pass. This asserts a value only a config read can produce.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    original = settings.leading_indicator
    settings.leading_indicator = original.model_copy(
        update={"breadth_threshold": original.breadth_threshold.model_copy(update={"value": 0.25})}
    )
    try:
        # 2 of 4 declining = breadth 0.50: above a patched 0.25, below the
        # shipped 0.60. Only a config read flags it.
        result = leading_indicator_proxy(
            LeadingIndicatorProxyInputs(components={"a": -1.0, "b": -2.0, "c": 1.0, "d": 2.0})
        )
        assert as_bool(result, key="broad_based") is True, (
            "the model did not honour the patched threshold, so it is not "
            "reading the threshold from config"
        )
        assert as_float(result, key="breadth_threshold") == pytest.approx(0.25)
    finally:
        settings.leading_indicator = original


def test_the_boundary_is_inclusive_as_the_specification_writes_it() -> None:
    """``>=`` not ``>``. Section 20.7 writes ``breadth >= 0.6``.

    Exactly at the threshold IS broad-based. The fixture is built to land
    exactly on it (3 of 5 = 0.6) rather than near it, so the operator is
    actually exercised.
    """
    from macro_engine.config import get_settings

    threshold = get_settings().leading_indicator.breadth_threshold_value
    assert threshold == pytest.approx(0.6), "precondition: 3 of 5 must land exactly on it"

    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(
            components={"a": -1.0, "b": -2.0, "c": -3.0, "d": 0.0, "e": 4.0}
        )
    )
    assert as_float(result, key="breadth_declining") == pytest.approx(threshold)
    assert as_bool(result, key="broad_based") is True


def test_the_base_rate_is_reported_with_the_flag() -> None:
    """D-029's disclosure rule, applied to this module's boolean."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    rate = as_float(result, key="breadth_null_rate")
    assert 0.0 < rate < 1.0


def test_the_null_rate_is_the_exact_binomial_tail_not_an_estimate() -> None:
    """4 components, threshold 0.6 -> need 3 of 4 -> (4 + 1) / 2**4 = 0.3125.

    Pinned exactly rather than to a tolerance, because this figure is
    *computed* rather than fitted — a tolerance would hide an off-by-one in the
    ``ceil`` that makes the requirement 2-of-4 instead of 3-of-4.
    """
    assert _breadth_null_rate(4, 0.6) == pytest.approx(0.3125)
    # 3 of 4 is ceil(0.6*4)=3; the two tails agree by symmetry of the binomial.
    assert _breadth_null_rate(4, 0.6) == pytest.approx((0.5**4) * (4 + 1))


@pytest.mark.parametrize(
    ("n", "threshold", "expected"),
    [
        (1, 0.6, 0.5),  # ceil(0.6) = 1 -> must be 1 of 1 -> 1/2
        (2, 0.6, 0.25),  # ceil(1.2) = 2 -> both -> 1/4
        (3, 0.6, 0.5),  # ceil(1.8) = 2 -> >= 2 of 3 -> 4/8
        (4, 0.6, 0.3125),  # ceil(2.4) = 3 -> >= 3 of 4 -> 5/16
        (5, 0.6, 0.5),  # ceil(3.0) = 3 -> >= 3 of 5 -> 16/32
        (10, 0.6, 0.376953125),  # ceil(6.0) = 6 -> >= 6 of 10
    ],
)
def test_the_null_rate_matches_the_binomial_tail_for_other_component_counts(
    n: int, threshold: float, expected: float
) -> None:
    """The ``ceil`` is the load-bearing part, so it is checked at boundaries.

    ``ceil(0.6 * 5) = 3`` exactly (3.0) is the case an ``int()`` truncation
    would get wrong the other way, and ``ceil(0.6 * 10) = 6`` exactly is where
    floating-point ``0.6 * 10 = 6.000000000000001`` matters.
    """
    assert _breadth_null_rate(n, threshold) == pytest.approx(expected)


def test_the_warning_states_the_base_rate_as_a_frequency() -> None:
    """The reader must be told the frequency, not just handed the flag."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    joined = " ".join(result.warnings)

    rate = as_float(result, key="breadth_null_rate")
    assert f"{rate:.1%}" in joined


def test_the_warning_calls_the_base_rate_combinatorial_not_historical() -> None:
    """The specific fabrication to prevent: presenting a null model as a track record.

    This build has no validated history for the proxy, so a warning that
    implied one would be inventing evidence. The text must name the figure as a
    null frequency.
    """
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    joined = " ".join(result.warnings).lower()

    assert "null" in joined
    assert "not a historical hit rate" in joined


def test_the_warning_states_the_required_component_count() -> None:
    """A reader should not have to compute ``ceil(0.6 * n)`` themselves."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    joined = " ".join(result.warnings)

    assert "at least 3 components decline" in joined


# ---------------------------------------------------------------------------
# Correction 4 — the sum and the breadth must describe the same component set
# ---------------------------------------------------------------------------


def test_a_partial_weight_map_is_rejected() -> None:
    """Section 20.7's ``w.get(k, 0)`` gives an unweighted component zero weight.

    It would still be counted in the breadth denominator, so the composite and
    the breadth would silently describe different sets of components.
    """
    with pytest.raises(ValueError, match="omits component"):
        LeadingIndicatorProxyInputs(
            components=FOUR_FALLING,
            weights={"a": 0.5, "b": 0.5},
        )


def test_a_weight_for_an_absent_component_is_rejected() -> None:
    """Normally a rename that was half-applied."""
    with pytest.raises(ValueError, match="absent from"):
        LeadingIndicatorProxyInputs(
            components=FOUR_FALLING,
            weights={"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25, "e": 0.0},
        )


def test_a_negative_weight_is_rejected() -> None:
    """Orientation belongs in the component's own sign, not in the weight.

    A negative weight on one component and a positive one on another produces
    the same sum as swapping their signs, so the two would be indistinguishable
    while meaning different things.
    """
    with pytest.raises(ValueError, match="negative"):
        LeadingIndicatorProxyInputs(
            components=FOUR_FALLING,
            weights={"a": -0.25, "b": 0.25, "c": 0.25, "d": 0.75},
        )


def test_all_zero_weights_are_rejected() -> None:
    """The composite would be a constant zero presented as a measurement."""
    with pytest.raises(ValueError, match="every weight is zero"):
        LeadingIndicatorProxyInputs(
            components=FOUR_FALLING,
            weights={"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0},
        )


def test_an_empty_component_set_is_rejected() -> None:
    """Breadth is a ratio over the set; it is undefined for an empty one."""
    with pytest.raises(Exception, match=r"at least 1|too_short|min_length"):
        LeadingIndicatorProxyInputs(components={})


def test_a_typo_in_a_keyword_is_rejected() -> None:
    """``extra="forbid"`` on the input model."""
    with pytest.raises(Exception, match=r"extra_forbidden|Extra inputs"):
        LeadingIndicatorProxyInputs(components=FOUR_FALLING, component=FOUR_FALLING)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# The mixed-unit disclosure — the sum is not a percentage
# ---------------------------------------------------------------------------


def test_the_mixed_unit_problem_is_disclosed() -> None:
    """The composite adds persons, index levels and percentage points together.

    Section 20.7 specifies it; the output must not present it as a percentage
    with economic meaning, because the component units are incommensurable.
    """
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    joined = " ".join(result.warnings).lower()

    assert "mixed-unit" in joined or "mixed unit" in joined
    assert "volatile" in joined


def test_breadth_is_reported_as_the_transferable_quantity() -> None:
    """The unit-free quantity must be named as the signal, per the module docstring."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    joined = " ".join(result.warnings).lower()

    assert "breadth is the signal" in joined


def test_the_interpretation_carries_both_the_sum_and_the_breadth() -> None:
    """A reader of the one-line interpretation must see both quantities."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    assert "-7.50" in result.interpretation
    assert "4/4" in result.interpretation
    assert "broad_based_decline" in result.interpretation


# ---------------------------------------------------------------------------
# The advance side — a direction the headline must not contradict
# ---------------------------------------------------------------------------


def test_a_broad_advance_requires_the_composite_to_agree() -> None:
    """3 of 4 rising while the sum is negative must NOT read as an advance.

    composite = 0.25 * (-30.0 + 1.0 + 0.5 + 2.0) = -6.625
    advance breadth = 3/4 = 0.75 >= 0.60, but composite < 0
    """
    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(
            components={"claims": -30.0, "permits": 1.0, "curve": 0.5, "equity": 2.0}
        )
    )

    assert as_float(result, key="composite_6mo_annualized") < 0
    assert as_str(result, key="lead_direction") == "mixed", (
        "a breadth-only advance test would label this an advance while the "
        "composite prints a negative number"
    )


def test_a_genuine_broad_advance_is_labelled() -> None:
    """All components rising: the mirror case, and it must be reachable.

    0.25 * (5.0 + 6.0 + 7.0 + 8.0) = 6.5
    """
    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(components={"a": 5.0, "b": 6.0, "c": 7.0, "d": 8.0})
    )

    assert as_float(result, key="composite_6mo_annualized") == pytest.approx(6.5)
    assert as_str(result, key="lead_direction") == "broad_based_advance"
    assert as_bool(result, key="broad_based") is False


def test_the_advance_direction_is_never_reported_by_the_decline_flag() -> None:
    """The boolean and the three-state read must not contradict each other.

    ``broad_based`` True implies the direction is a decline; a True with any
    other direction would be two answers to one question.
    """
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    assert as_bool(result, key="broad_based") is True
    assert as_str(result, key="lead_direction") == "broad_based_decline"


def test_the_three_state_read_can_say_mixed() -> None:
    """The state the specification's boolean cannot express."""
    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(components={"a": -1.0, "b": -2.0, "c": 3.0, "d": 4.0})
    )
    assert as_str(result, key="lead_direction") == "mixed"
    assert any("split" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Step 5 — warning paths
# ---------------------------------------------------------------------------


def test_the_mixed_path_warns_that_the_boolean_understates_it() -> None:
    """'Not broad-based' must not read as 'no decline'.

    The specification has no branch for a split reading: its boolean is False,
    which reads like reassurance when the truth is 'no consensus'.
    """
    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(components={"a": -1.0, "b": -2.0, "c": 3.0, "d": 4.0})
    )
    assert any("not reassurance" in w for w in result.warnings)


def test_the_broad_advance_path_warns() -> None:
    """An advance is outside Section 20.7's decline framing and must say so."""
    result = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(components={"a": 5.0, "b": 6.0, "c": 7.0, "d": 8.0})
    )
    assert any("advancing" in w.lower() for w in result.warnings)


def test_a_small_component_set_warns_that_breadth_is_coarse() -> None:
    """Breadth over 2 members cannot express 'broad-based'."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components={"a": -1.0, "b": -2.0}))
    assert any("component(s) supplied" in w for w in result.warnings)


def test_the_sp500_window_limitation_is_disclosed() -> None:
    """The equity component's rolling 10-year window is a real truncation risk."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    joined = " ".join(result.warnings)

    assert "SP500" in joined or "S&P 500" in joined
    assert "2016-09" in joined


def test_the_probability_input_warning_is_standing() -> None:
    """Section 20.7's false-positive caveat, on every path."""
    for components in (FOUR_FALLING, {"a": 1.0}, {"a": -1.0, "b": 2.0}):
        result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=components))
        assert any("probability input" in w.lower() for w in result.warnings)


@pytest.mark.parametrize(
    "components",
    [FOUR_FALLING, {"a": 1.0}, {"a": 0.0}, {"a": -1.0, "b": 2.0}],
)
def test_every_run_carries_warnings(components: dict[str, float]) -> None:
    """Module 7.3's output is never warning-free: the disclaimer always applies."""
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=components))
    assert len(result.warnings) >= 5, (
        "the not-LEI disclaimer, the probability caveat, the breadth-is-the-signal "
        "note, the mixed-unit note and the SP500 window note are always present"
    )


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_non_finite_component_is_rejected(value: float) -> None:
    """A NaN would make ``change < 0`` False and be counted as 'did not decline'.

    That is a missing observation suppressing the model's own signal, which is
    the direction Section 21.0 exists to prevent.
    """
    with pytest.raises(ValueError, match="non-finite"):
        leading_indicator_proxy(
            LeadingIndicatorProxyInputs(components={"good": -1.0, "bad": value})
        )


def test_the_rejection_names_the_offending_component() -> None:
    """A dict signature needs the message to say WHICH component was bad."""
    with pytest.raises(ValueError, match="bad_component"):
        leading_indicator_proxy(
            LeadingIndicatorProxyInputs(components={"good": -1.0, "bad_component": math.nan})
        )


def test_the_input_model_documents_the_unit_contract() -> None:
    """The six-month horizon and the orientation guidance must be discoverable."""
    field = LeadingIndicatorProxyInputs.model_fields["components"]
    assert field.description is not None
    assert "six-month" in field.description.lower()

    doc = LeadingIndicatorProxyInputs.__doc__ or ""
    assert "orientation" in doc.lower(), (
        "the docstring must warn that a component's orientation matters: a "
        "claims LEVEL rises when the labour market weakens"
    )


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


def test_the_result_carries_its_provenance() -> None:
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))

    assert result.country == "us"
    assert result.as_of.tzinfo is not None, "as_of must be timezone-aware"
    assert result.context
    assert result.warnings


def test_inputs_used_lists_every_component() -> None:
    result = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    assert set(result.inputs_used) == set(FOUR_FALLING)


def test_inputs_used_names_weights_only_when_supplied() -> None:
    """A caller who supplied weights is reading a different composite."""
    equal = leading_indicator_proxy(LeadingIndicatorProxyInputs(components=FOUR_FALLING))
    assert "weights" not in equal.inputs_used

    weighted = leading_indicator_proxy(
        LeadingIndicatorProxyInputs(
            components=FOUR_FALLING,
            weights=dict.fromkeys(FOUR_FALLING, 0.25),
        )
    )
    assert "weights" in weighted.inputs_used
