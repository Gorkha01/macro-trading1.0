"""Tests for Module 5.4 — ``ppi_pipeline_signal`` (AGENTS.md Section 20.5).

This module's tests divide into four groups:

1. **The specification's own behaviour** — the strict ordering test and the
   pass-through binary, asserted so the implementation can be checked against
   the document rather than against itself.
2. **The enumerated-input correction (D-029)** — a typo'd assessment must be a
   construction error, not a silent fall-through to the optimistic branch.
3. **The base-rate disclosure** — the flag must never be reported without the
   frequency that makes it interpretable.
4. **Boundary behaviour** — the dead band, on both sides, built from the config
   value so a recalibration moves the test with the code.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.ppi_pipeline import (
    DemandCondition,
    MarginTrend,
    PPIPipelineInputs,
    ppi_pipeline_signal,
)
from tests.helpers import as_bool, as_float, as_str

# The three live stage readings at 2026-08-01, measured from FRED via the
# registry symbols WPSID62 / WPSID61 / PPIFIS. Used as the realistic fixture so
# the tests exercise a case that actually occurs rather than a tidy one.
LIVE_CRUDE = 13.06
LIVE_INTERMEDIATE = 11.53
LIVE_FINAL = 5.41


def _inputs(
    *,
    crude: float = 1.0,
    intermediate: float = 2.0,
    final: float = 3.0,
    margin: MarginTrend = "stable",
    demand: DemandCondition = "neutral",
) -> PPIPipelineInputs:
    """Build inputs, defaulting to the REVERSED (downstream-passing) order.

    The default is deliberately the inverted gradient rather than the rising one
    the specification's prose starts from: a default that matches the headline
    case makes every test that forgets to override it assert the headline, and
    the inverted case is the one whose wording is easiest to get backwards.

    ``margin`` and ``demand`` are typed to the exported ``Literal`` aliases
    rather than to ``str``. Typing them as ``str`` makes the *helper* the place a
    typo can enter, which is the defect the module's ``Literal`` correction
    exists to prevent — and mypy rejects it, which is how this was caught. The
    negative tests below therefore call ``PPIPipelineInputs`` directly with an
    ignored type rather than routing an invalid value through this helper.
    """
    return PPIPipelineInputs(
        crude_stage_yoy_pct=crude,
        intermediate_stage_yoy_pct=intermediate,
        final_demand_yoy_pct=final,
        corporate_margin_trend=margin,
        demand_condition=demand,
    )


# --------------------------------------------------------------------------
# 1. The specification's own behaviour
# --------------------------------------------------------------------------


def test_strict_ordering_is_reported_as_upstream_building() -> None:
    """``crude > intermediate > final`` -> ``True``, as Section 20.5 specifies."""
    result = ppi_pipeline_signal(_inputs(crude=5.0, intermediate=3.0, final=1.0))
    assert as_bool(result, key="upstream_pressure_building") is True
    assert as_str(result, key="gradient_direction") == "building_upstream"


def test_reversed_ordering_is_not_upstream_building() -> None:
    """``crude < intermediate < final`` -> ``False``, and named as such.

    The specification only computes the boolean; asserting the *direction label*
    as well is what stops a sign error in the restatement from agreeing with the
    boolean by accident.
    """
    result = ppi_pipeline_signal(_inputs(crude=1.0, intermediate=2.0, final=3.0))
    assert as_bool(result, key="upstream_pressure_building") is False
    assert as_str(result, key="gradient_direction") == "passing_through_downstream"


def test_gradient_direction_never_contradicts_the_boolean() -> None:
    """``building_upstream`` implies the boolean is ``True`` — checked both ways.

    The two are computed independently, so this asserts they agree rather than
    assuming they must.
    """
    cases = [
        (5.0, 3.0, 1.0),
        (1.0, 2.0, 3.0),
        (3.0, 1.0, 2.0),
        (1.0, 3.0, 2.0),
        (2.0, 2.0, 2.0),
    ]
    for crude, intermediate, final in cases:
        result = ppi_pipeline_signal(_inputs(crude=crude, intermediate=intermediate, final=final))
        building = as_bool(result, key="upstream_pressure_building")
        direction = as_str(result, key="gradient_direction")
        assert (direction == "building_upstream") == building, (
            f"boolean {building} and direction {direction!r} disagree for "
            f"({crude}, {intermediate}, {final})"
        )


def test_stage_spread_is_crude_minus_final() -> None:
    """``stage_spread_pp`` is recomputed from the reported inputs."""
    result = ppi_pipeline_signal(_inputs(crude=5.0, intermediate=3.0, final=1.5))
    assert as_float(result, key="stage_spread_pp") == pytest.approx(3.5)


def test_stage_spread_can_be_negative() -> None:
    """A sign check on the spread, against a direction known before the call."""
    result = ppi_pipeline_signal(_inputs(crude=1.0, intermediate=2.0, final=6.5))
    assert as_float(result, key="stage_spread_pp") == pytest.approx(-5.5)


@pytest.mark.parametrize(
    ("margin", "demand", "expected"),
    [
        ("stable", "neutral", "fuller"),
        ("expanding", "strong", "fuller"),
        ("expanding", "neutral", "fuller"),
        ("stable", "strong", "fuller"),
        # Each absorbing condition alone is sufficient.
        ("compressing", "neutral", "muted"),
        ("stable", "weak", "muted"),
        ("compressing", "strong", "muted"),
        ("expanding", "weak", "muted"),
        ("compressing", "weak", "muted"),
    ],
)
def test_pass_through_binary_matches_the_specification(
    margin: MarginTrend, demand: DemandCondition, expected: str
) -> None:
    """Section 20.5: muted if demand weak OR margins compressing, else fuller."""
    result = ppi_pipeline_signal(_inputs(margin=margin, demand=demand))
    assert as_str(result, key="expected_pass_through") == expected


def test_pass_through_ignores_a_building_gradient() -> None:
    """Pass-through is the assessments' call, not the gradient's.

    Live regression case: a strongly rising gradient with weak demand must
    still report ``muted``. If pass-through ever starts reading the gradient,
    the margin-absorption mechanism the module exists to model is gone.
    """
    result = ppi_pipeline_signal(
        _inputs(
            crude=LIVE_CRUDE,
            intermediate=LIVE_INTERMEDIATE,
            final=LIVE_FINAL,
            margin="expanding",
            demand="weak",
        )
    )
    assert as_bool(result, key="upstream_pressure_building") is True
    assert as_str(result, key="expected_pass_through") == "muted"


def test_live_fixture_reproduces_the_measured_readings() -> None:
    """The 2026-08-01 live case, end to end."""
    result = ppi_pipeline_signal(
        _inputs(
            crude=LIVE_CRUDE,
            intermediate=LIVE_INTERMEDIATE,
            final=LIVE_FINAL,
            margin="expanding",
            demand="neutral",
        )
    )
    assert as_bool(result, key="upstream_pressure_building") is True
    assert as_str(result, key="gradient_direction") == "building_upstream"
    assert as_str(result, key="expected_pass_through") == "fuller"
    # 13.06 - 5.41 = 7.65
    assert as_float(result, key="stage_spread_pp") == pytest.approx(7.65)


# --------------------------------------------------------------------------
# 2. The enumerated-input correction (D-029)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["Compressing", "compress", "tight", " ", "MUTED"])
def test_unrecognised_margin_trend_is_rejected(bad: str) -> None:
    """A typo'd assessment must fail, not fall through to the optimistic branch.

    This is the whole point of the ``Literal`` correction. Under the
    specification's free ``str`` these values are *accepted* and land in the
    ``else`` clause, reporting ``fuller`` pass-through — an optimistic answer
    manufactured by a spelling mistake. Asserting the rejection is what makes
    the correction load-bearing rather than cosmetic.

    The ``type: ignore`` is the test. Passing a value the annotation forbids is
    exactly what is being checked, so the type checker must object and the
    ignore is part of the fixture — hence it is written inline rather than
    hidden behind a ``cast`` or an ``Any``-typed helper.
    """
    with pytest.raises(ValidationError) as exc:
        PPIPipelineInputs(
            crude_stage_yoy_pct=1.0,
            intermediate_stage_yoy_pct=2.0,
            final_demand_yoy_pct=3.0,
            corporate_margin_trend=bad,  # type: ignore[arg-type]
            demand_condition="neutral",
        )
    assert exc.value.errors()[0]["type"] == "literal_error"


@pytest.mark.parametrize("bad", ["Strong", "STRONG", "firm", "soft", ""])
def test_unrecognised_demand_condition_is_rejected(bad: str) -> None:
    """Same correction for the demand field, including a case-only typo."""
    with pytest.raises(ValidationError) as exc:
        PPIPipelineInputs(
            crude_stage_yoy_pct=1.0,
            intermediate_stage_yoy_pct=2.0,
            final_demand_yoy_pct=3.0,
            corporate_margin_trend="stable",
            demand_condition=bad,  # type: ignore[arg-type]
        )
    assert exc.value.errors()[0]["type"] == "literal_error"


def test_rejection_names_the_permitted_values() -> None:
    """The error must be actionable, not just a refusal.

    A construction error that does not say what *would* have been accepted
    trades one silent failure for one confusing failure.
    """
    with pytest.raises(ValidationError) as exc:
        PPIPipelineInputs(
            crude_stage_yoy_pct=1.0,
            intermediate_stage_yoy_pct=2.0,
            final_demand_yoy_pct=3.0,
            corporate_margin_trend="compress",  # type: ignore[arg-type]
            demand_condition="neutral",
        )
    message = str(exc.value)
    for permitted in ("expanding", "stable", "compressing"):
        assert permitted in message, f"error omits permitted value {permitted!r}"


def test_both_assessments_reject_rather_than_default() -> None:
    """The fields are required: omitting one is an error, not a default.

    A defaulted assessment would be a silent stand-in for a human judgement,
    which is the class of defect Section 21.0 rule 4 prohibits.
    """
    with pytest.raises(ValidationError):
        PPIPipelineInputs(  # type: ignore[call-arg]
            crude_stage_yoy_pct=1.0,
            intermediate_stage_yoy_pct=2.0,
            final_demand_yoy_pct=3.0,
            # corporate_margin_trend omitted
            demand_condition="neutral",
        )


def test_unknown_keyword_is_rejected() -> None:
    """``extra="forbid"`` still holds, alongside the ``Literal`` tightening."""
    with pytest.raises(ValidationError):
        PPIPipelineInputs(  # type: ignore[call-arg]
            crude_stage_yoy_pct=1.0,
            intermediate_stage_yoy_pct=2.0,
            final_demand_yoy_pct=3.0,
            corporate_margin_trend="stable",
            demand_condition="neutral",
            margin_trend="stable",
        )


# --------------------------------------------------------------------------
# 3. The base-rate disclosure (D-029)
# --------------------------------------------------------------------------


def test_both_base_rates_are_reported() -> None:
    """The measured frequencies travel with the flag they qualify.

    D-029's finding: the strict ordering holds 30.0% of months, so the boolean
    alone invites the reader to treat the less common outcome as evidence of an
    unusual state. The rates are part of the result, not documentation.
    """
    settings = get_settings()
    result = ppi_pipeline_signal(_inputs())
    assert as_float(result, key="base_rate_strict_descending") == pytest.approx(
        settings.inflation.pipeline_base_rate.strict_descending_rate
    )
    assert as_float(result, key="base_rate_crude_above_final") == pytest.approx(
        settings.inflation.pipeline_base_rate.crude_above_final_rate
    )


def test_base_rate_is_reported_on_both_flavours_of_the_answer() -> None:
    """A ``False`` reading needs the base rate as much as a ``True`` one.

    The temptation is to attach the caveat only to the positive case. But "no
    gradient" is what the model says 70% of the time, and a reader needs to know
    that is the common outcome, not a finding.
    """
    building = ppi_pipeline_signal(_inputs(crude=5.0, intermediate=3.0, final=1.0))
    not_building = ppi_pipeline_signal(_inputs(crude=1.0, intermediate=2.0, final=3.0))
    for result in (building, not_building):
        assert as_float(result, key="base_rate_strict_descending") > 0.0


def test_base_rate_warning_states_the_measured_frequency() -> None:
    """The warning must carry the number, not merely refer to one."""
    settings = get_settings()
    rate = settings.inflation.pipeline_base_rate.strict_descending_rate
    result = ppi_pipeline_signal(_inputs())

    matches = [w for w in result.warnings if "base rate" in w]
    assert len(matches) == 1, f"expected exactly one base-rate warning, got {len(matches)}"
    # The percentage as the warning renders it (one decimal place).
    assert f"{rate:.1%}" in matches[0]


def test_base_rates_are_fractions_not_percentages() -> None:
    """A units check: a base rate of ``30.0`` would be a plausible-looking defect.

    Both rates are shares in ``[0, 1]``. Storing ``30`` instead of ``0.30``
    would render as ``3000.0%`` and no range check on the *inputs* would notice,
    because this value never passes through an input model.
    """
    result = ppi_pipeline_signal(_inputs())
    for key in ("base_rate_strict_descending", "base_rate_crude_above_final"):
        rate = as_float(result, key=key)
        assert 0.0 < rate < 1.0, f"{key} = {rate} is not a share in (0, 1)"


def test_margin_assessment_warning_is_always_present() -> None:
    """The Loophole-Ledger disclosure is unconditional (Section 21.4 item 10)."""
    result = ppi_pipeline_signal(_inputs())
    matches = [w for w in result.warnings if "HUMAN ASSESSMENT" in w]
    assert len(matches) == 1


def test_ppi_not_one_to_one_warning_is_always_present() -> None:
    """Module 5.4's own caveat, required by Section 20.5's sample."""
    result = ppi_pipeline_signal(_inputs())
    matches = [w for w in result.warnings if "NOT a 1:1 CPI predictor" in w]
    assert len(matches) == 1


# --------------------------------------------------------------------------
# 4. Boundary behaviour and conditional warnings
# --------------------------------------------------------------------------


def test_exact_tie_is_no_clear_gradient() -> None:
    """All three stages equal -> the dead band suppresses a phantom ordering."""
    result = ppi_pipeline_signal(_inputs(crude=2.0, intermediate=2.0, final=2.0))
    assert as_bool(result, key="upstream_pressure_building") is False
    assert as_str(result, key="gradient_direction") == "no_clear_gradient"


def test_separation_exactly_at_the_tolerance_is_no_clear_gradient() -> None:
    """The band is inclusive at its edge — built from the config value.

    Reading the tolerance from config rather than hardcoding ``0.1`` means a
    recalibration moves this fixture with the code instead of silently leaving
    a test that no longer lands on the boundary.

    The fixture is built by **addition from 0**, not by subtracting from 2.0.
    ``2.0 - 0.1`` is ``1.9`` but the gap ``2.0 - 1.9`` evaluates to
    ``0.10000000000000009`` — nine orders of magnitude above the tolerance — so
    a fixture written as ``2.0 - tolerance`` tests a point *outside* the band
    while claiming to test its edge. Starting from 0.0 and adding the same
    tolerance to the other side keeps the arithmetic exact for the dyadic cases
    the config uses, and the assertion is about the comparison rather than about
    float representation.
    """
    tolerance = get_settings().inflation.pipeline_gradient_tolerance
    result = ppi_pipeline_signal(_inputs(crude=tolerance, intermediate=0.0, final=0.0))
    # |crude - intermediate| == tolerance and |intermediate - final| == 0.0
    assert as_str(result, key="gradient_direction") == "no_clear_gradient"


def test_separation_just_outside_the_tolerance_is_directional() -> None:
    """The other side of the same boundary — a strict ``>`` on the band.

    Both *adjacent* gaps must exceed the tolerance to leave the dead band, so
    the fixture separates the three stages by ``2 * tolerance`` rather than
    ``tolerance``: spacing them by exactly the tolerance puts each gap at the
    band's inclusive edge and correctly reports no gradient (which the preceding
    test asserts). Using 2x keeps this a test of ``>`` and not of ``>=``.
    """
    tolerance = get_settings().inflation.pipeline_gradient_tolerance
    gap = tolerance * 2.0
    result = ppi_pipeline_signal(_inputs(crude=gap * 2.0, intermediate=gap, final=0.0))
    assert as_str(result, key="gradient_direction") == "building_upstream"


def test_the_dead_band_requires_both_adjacent_gaps_inside_it() -> None:
    """A single pair inside the band is not enough to call the gradient absent.

    This is the case a mutation sweep found uncovered. The band is a conjunction
    over two adjacent gaps, and until this test existed, relaxing it to a single
    gap left the whole suite green.

    Fixture, with ``tolerance = t``::

        crude         = 2.5 * t
        intermediate  = 1.5 * t
        final         = 0.0

        |crude - intermediate| = 1.0 * t   -> INSIDE the band (inclusive edge)
        |intermediate - final| = 1.5 * t   -> OUTSIDE the band

    One pair sits exactly on the edge and the other is outside, so the gradient
    is real and must be reported. A one-gap band would see the first pair and
    wrongly report ``no_clear_gradient``.
    """
    tolerance = get_settings().inflation.pipeline_gradient_tolerance
    result = ppi_pipeline_signal(
        _inputs(crude=tolerance * 2.5, intermediate=tolerance * 1.5, final=0.0)
    )
    assert as_str(result, key="gradient_direction") == "building_upstream"
    # The boolean is unaffected by the band and must still say True.
    assert as_bool(result, key="upstream_pressure_building") is True


def test_the_dead_band_requires_the_first_adjacent_gap_inside_it() -> None:
    """The mirror case: the first pair outside, the second pair inside.

    Together with the preceding test this pins the conjunction from both sides,
    so neither ``and`` term can be dropped without a failure.

    The fixture must keep the gradient *monotonic* while putting the gaps on
    opposite sides of the band, which constrains it more than it first appears.
    Writing ``crude=3t, intermediate=0, final=0.5t`` puts the first gap outside
    and the second inside — but it also makes ``intermediate < final``, so the
    ordering is non-monotonic and the test would be asserting about the wrong
    branch. Both gaps outside-to-inside must therefore be expressed in the
    descending direction::

        crude         = 4.0 * t
        intermediate  = 1.0 * t
        final         = 0.4 * t

        |crude - intermediate| = 3.0 * t  -> OUTSIDE the band
        |intermediate - final| = 0.6 * t  -> INSIDE the band
        ordering: 4.0t > 1.0t > 0.4t      -> strictly descending
    """
    tolerance = get_settings().inflation.pipeline_gradient_tolerance
    result = ppi_pipeline_signal(
        _inputs(crude=tolerance * 4.0, intermediate=tolerance * 1.0, final=tolerance * 0.4)
    )
    assert as_str(result, key="gradient_direction") == "building_upstream"
    assert as_bool(result, key="upstream_pressure_building") is True


def test_float_subtraction_cannot_build_a_boundary_fixture() -> None:
    """Documents executably why the boundary fixture is built by addition.

    ``2.0 - 0.1`` renders as ``1.9`` but ``2.0 - 1.9`` is not ``0.1``. A test
    that constructs its own edge by subtraction is testing a point slightly
    outside the band and will report the model as wrong when it is right — which
    is exactly what happened on the first run of this file.
    """
    assert 2.0 - 0.1 == 1.9
    assert (2.0 - (2.0 - 0.1)) > 0.1, "subtraction must be shown to overshoot here"


def test_non_monotonic_ordering_is_named_not_forced_into_a_direction() -> None:
    """The most common real outcome gets its own label and its own warning.

    ``(3, 1, 2)`` satisfies neither the ascending nor the descending test. The
    specification's boolean would simply report ``False``, which is read as "no
    upstream gradient" — a different claim from "the stages disagree in
    direction".
    """
    result = ppi_pipeline_signal(_inputs(crude=3.0, intermediate=1.0, final=2.0))
    assert as_bool(result, key="upstream_pressure_building") is False
    assert as_str(result, key="gradient_direction") == "non_monotonic"
    matches = [w for w in result.warnings if "not monotonically ordered" in w]
    assert len(matches) == 1


def test_non_monotonic_warning_is_absent_when_the_order_is_monotonic() -> None:
    """Both-sided: the warning must be absent for a clean gradient."""
    for crude, intermediate, final in [(5.0, 3.0, 1.0), (1.0, 2.0, 3.0)]:
        result = ppi_pipeline_signal(_inputs(crude=crude, intermediate=intermediate, final=final))
        offenders = [w for w in result.warnings if "not monotonically ordered" in w]
        assert not offenders, f"non-monotonic warning fired for ({crude}, {intermediate}, {final})"


def test_passing_through_downstream_warning_fires_on_the_inverted_case() -> None:
    """The inverted gradient gets the downstream-arrival note."""
    result = ppi_pipeline_signal(_inputs(crude=1.0, intermediate=2.0, final=3.0))
    matches = [w for w in result.warnings if "gradient is inverted" in w]
    assert len(matches) == 1


def test_passing_through_downstream_warning_absent_otherwise() -> None:
    """Both-sided check for the inverted case's warning."""
    result = ppi_pipeline_signal(_inputs(crude=5.0, intermediate=3.0, final=1.0))
    offenders = [w for w in result.warnings if "gradient is inverted" in w]
    assert not offenders


def test_building_with_expanding_margins_is_flagged_as_a_contradiction() -> None:
    """A judgement that disagrees with the price data must be surfaced.

    Building upstream costs alongside expanding margins is the combination where
    the two halves of the input disagree about the same question.
    """
    result = ppi_pipeline_signal(
        _inputs(crude=5.0, intermediate=3.0, final=1.0, margin="expanding")
    )
    matches = [w for w in result.warnings if "pull in opposite" in w]
    assert len(matches) == 1


def test_expanding_margins_without_a_building_gradient_is_not_flagged() -> None:
    """The contradiction warning must not fire on the benign combination."""
    result = ppi_pipeline_signal(
        _inputs(crude=1.0, intermediate=2.0, final=3.0, margin="expanding")
    )
    offenders = [w for w in result.warnings if "pull in opposite" in w]
    assert not offenders


@pytest.mark.parametrize("margin", ["stable", "compressing"])
def test_building_gradient_with_a_non_expanding_margin_is_not_flagged(margin: MarginTrend) -> None:
    """The conjunction needs BOTH terms — a mutation sweep found this uncovered.

    The previous test uses the *inverted* gradient, where
    ``upstream_pressure_building`` is already ``False``, so it cannot tell
    "building AND expanding" apart from "building" alone. These cases keep the
    building gradient fixed and vary only the margin trend, which is the
    comparison that actually pins the second term of the conjunction.
    """
    result = ppi_pipeline_signal(_inputs(crude=5.0, intermediate=3.0, final=1.0, margin=margin))
    assert as_bool(result, key="upstream_pressure_building") is True
    offenders = [w for w in result.warnings if "pull in opposite" in w]
    assert not offenders, f"contradiction warning fired with margin trend {margin!r}"


def test_flat_ends_warning_fires_when_crude_and_final_coincide() -> None:
    """A gradient needs separated ends, whatever the intermediate stage does."""
    result = ppi_pipeline_signal(_inputs(crude=2.0, intermediate=5.0, final=2.0))
    matches = [w for w in result.warnings if "effectively no gradient" in w]
    assert len(matches) == 1


def test_flat_ends_warning_absent_when_the_ends_are_separated() -> None:
    """Both-sided check on the flat-ends warning."""
    result = ppi_pipeline_signal(_inputs(crude=9.0, intermediate=2.0, final=1.0))
    offenders = [w for w in result.warnings if "effectively no gradient" in w]
    assert not offenders


# --------------------------------------------------------------------------
# Contract conformance
# --------------------------------------------------------------------------


def test_confidence_is_computed_not_hardcoded() -> None:
    """Section 22.8: no ``confidence=0.X`` literal.

    The specification's sample asserts 0.4. The model passes
    ``is_heuristic_not_calibrated=True`` and ``depends_on_unobservable=True``,
    which the formula turns into the configured floor — a different number, and
    one that changes if the penalties are recalibrated.
    """
    settings = get_settings()
    result = ppi_pipeline_signal(_inputs())
    expected = max(
        settings.confidence.values["floor"],
        min(
            settings.confidence.values["ceiling"],
            settings.confidence.values["base"]
            - settings.confidence.values["heuristic_penalty"]
            - settings.confidence.values["unobservable_penalty"],
        ),
    )
    assert result.confidence == pytest.approx(round(expected, 3))
    assert result.confidence != 0.4, "confidence still equals the specification's literal"


def test_result_is_a_model_result_with_the_contract_fields() -> None:
    """No model returns a bare number; every field is populated."""
    result = ppi_pipeline_signal(_inputs())
    assert isinstance(result, ModelResult)
    assert result.model_name == "ppi_pipeline_signal"
    assert result.country == "us"
    assert result.as_of.tzinfo is not None, "as_of must be timezone-aware"
    assert result.interpretation
    assert result.context
    assert result.warnings


def test_inputs_used_lists_exactly_the_declared_inputs() -> None:
    """The provenance list must match the model's actual inputs.

    A field added to the input model but not to ``inputs_used`` is invisible to
    the thesis's audit trail, which is the thing the field exists for.
    """
    result = ppi_pipeline_signal(_inputs())
    assert sorted(result.inputs_used) == sorted(PPIPipelineInputs.model_fields.keys())


def test_interpretation_states_the_three_stage_readings() -> None:
    """The interpretation must carry the numbers, not only the verdict."""
    result = ppi_pipeline_signal(
        _inputs(crude=LIVE_CRUDE, intermediate=LIVE_INTERMEDIATE, final=LIVE_FINAL)
    )
    for value in (LIVE_CRUDE, LIVE_INTERMEDIATE, LIVE_FINAL):
        assert f"{value}" in result.interpretation
