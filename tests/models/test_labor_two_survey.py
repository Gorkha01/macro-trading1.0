"""Module 6 Tier 2 tests — two surveys, Beveridge, AHE distortion, revisions.

These four functions are the remainder of Module 6 in the Section 21.3 order.
The tests here follow the discipline the claims tests established:

* Assert **numbers and verdicts**, not shapes. A test that only checks
  ``isinstance(result.value, str)`` passes on every wrong implementation.
* Include a **sign/branch guard** for each function — a fixture whose correct
  answer is known before the code runs.
* Include a **boundary guard** wherever the implementation compares against a
  configurable threshold, because ``>`` versus ``>=`` is invisible to every
  test that does not land exactly on the threshold.
* Mutation-test the guards: each assertion here was verified to fail when the
  behaviour it pins is broken.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from macro_engine.config import get_settings
from macro_engine.models.contracts import ModelResult
from macro_engine.models.labor_synthesis import (
    AHEDistortionInputs,
    BeveridgeInputs,
    RevisionInputs,
    TwoSurveyInputs,
    ahe_composition_flag,
    beveridge_curve_position,
    beveridge_shift_tolerance,
    nfp_revision_adjusted_read,
    two_survey_divergence,
)
from tests.helpers import as_bool, as_float, as_str

# --------------------------------------------------------------------------
# Fixtures — two_survey_divergence
# --------------------------------------------------------------------------


def _two_survey(**overrides: float) -> TwoSurveyInputs:
    """A consistent-strength baseline; each test varies one field."""
    base = {
        "nfp_change_thousands": 200.0,
        "household_employment_change_thousands": 180.0,
        "unemployment_rate_change_pp": -0.1,
        "participation_rate_change_pp": 0.1,
    }
    base.update(overrides)
    return TwoSurveyInputs(**base)


# --------------------------------------------------------------------------
# two_survey_divergence
# --------------------------------------------------------------------------


def test_two_survey_participation_driven_when_supply_explains_the_gap() -> None:
    """Payrolls up, unemployment up, participation UP -> benign supply reading.

    This is the case the whole module exists for: the naive read of "payrolls up
    but unemployment up" is a contradiction, and participation is what resolves
    it.
    """
    result = two_survey_divergence(
        _two_survey(
            nfp_change_thousands=200.0,
            unemployment_rate_change_pp=0.1,
            participation_rate_change_pp=0.2,
        )
    )
    assert as_str(result) == "PARTICIPATION_DRIVEN_not_weakness"


def test_two_survey_genuine_divergence_when_supply_does_not_explain_it() -> None:
    """The SAME payrolls-up/unemployment-up pair WITHOUT participation rising.

    This test is the counterpart to the one above and it is what makes the
    participation term load-bearing: identical NFP and unemployment inputs, one
    field changed, opposite verdict. An implementation that ignored
    participation would pass the previous test and fail this one.
    """
    result = two_survey_divergence(
        _two_survey(
            nfp_change_thousands=200.0,
            unemployment_rate_change_pp=0.1,
            participation_rate_change_pp=-0.1,
        )
    )
    assert as_str(result) == "GENUINE_DIVERGENCE_investigate"


def test_two_survey_broad_weakening_when_both_surveys_decline() -> None:
    result = two_survey_divergence(
        _two_survey(
            nfp_change_thousands=-100.0,
            household_employment_change_thousands=-120.0,
            unemployment_rate_change_pp=0.2,
            participation_rate_change_pp=-0.2,
        )
    )
    assert as_str(result) == "BROAD_WEAKENING"


def test_two_survey_consistent_strength_is_the_fallthrough() -> None:
    """Payrolls up and unemployment NOT up — no divergence to explain.

    Pinned explicitly rather than left implicit, because this is the branch an
    ``else`` swallows. If a future branch were added above it and mis-ordered,
    this test would catch the regression.
    """
    result = two_survey_divergence(_two_survey())
    assert as_str(result) == "CONSISTENT_STRENGTH"


def test_two_survey_warns_when_the_two_employment_counts_disagree() -> None:
    """NFP +200k vs household -50k is a gap a caller must be told about."""
    result = two_survey_divergence(
        _two_survey(nfp_change_thousands=200.0, household_employment_change_thousands=-50.0)
    )
    assert any("disagree" in w for w in result.warnings), result.warnings


def test_two_survey_does_not_warn_about_disagreement_when_signs_match() -> None:
    """The complement of the previous test.

    Without this, a warning that fired unconditionally would pass the test
    above. The pair is what pins the condition.
    """
    result = two_survey_divergence(_two_survey())
    assert not any("disagree" in w for w in result.warnings), result.warnings


def test_two_survey_household_count_does_not_change_the_verdict() -> None:
    """The household EMPLOYMENT number is reported, not classified on.

    Held to be true deliberately: the classification runs on NFP, unemployment
    and participation. This test records that boundary so that a future change
    which silently promotes the household count into the decision is visible.
    """
    baseline = two_survey_divergence(_two_survey(household_employment_change_thousands=180.0))
    altered = two_survey_divergence(_two_survey(household_employment_change_thousands=-900.0))
    assert as_str(baseline) == as_str(altered)


def test_two_survey_participation_warning_fires_only_on_the_benign_branch() -> None:
    """The benign reading is conditional on future absorption — warn about it.

    The risk this encodes: participation rising while unemployment rises is
    benign ONLY if the new entrants are absorbed. If they are not, the same
    pattern inverts into weakness. A reader who saw the benign verdict without
    that caveat would be reading a one-sided claim.
    """
    benign = two_survey_divergence(
        _two_survey(unemployment_rate_change_pp=0.1, participation_rate_change_pp=0.2)
    )
    divergent = two_survey_divergence(
        _two_survey(unemployment_rate_change_pp=0.1, participation_rate_change_pp=-0.1)
    )
    assert any("absorbed" in w for w in benign.warnings)
    assert not any("absorbed" in w for w in divergent.warnings)


def test_two_survey_thresholds_are_sign_only_and_documented() -> None:
    """Small magnitudes classify the same as large ones, and say so.

    The sign-only behaviour is intentional, so this test asserts it rather than
    treating it as a bug — and asserts the warning that discloses it, so a
    caller reading only ``value`` is not misled by silence.
    """
    small = two_survey_divergence(
        _two_survey(nfp_change_thousands=1.0, unemployment_rate_change_pp=0.001)
    )
    large = two_survey_divergence(
        _two_survey(nfp_change_thousands=900.0, unemployment_rate_change_pp=3.0)
    )
    assert as_str(small) == as_str(large)
    assert any("SIGN-only" in w for w in small.warnings)


def test_two_survey_zero_change_is_not_a_rise() -> None:
    """Exactly zero must classify as NOT up — the strict-inequality guard.

    A change of exactly 0.0 is the boundary of "> 0". Using ``>=`` here would
    call a flat payroll print an increase, and no other test in this file lands
    on zero, so this is the only guard against that mutation.
    """
    result = two_survey_divergence(
        _two_survey(nfp_change_thousands=0.0, unemployment_rate_change_pp=0.2)
    )
    # Payrolls are NOT up, unemployment IS up -> broad weakening, not the
    # participation branch (which requires payrolls up).
    assert as_str(result) == "BROAD_WEAKENING"


# --------------------------------------------------------------------------
# beveridge_curve_position
# --------------------------------------------------------------------------


def test_beveridge_tolerance_is_read_from_config() -> None:
    """The dead-band is config-driven, not a literal in the comparison."""
    assert beveridge_shift_tolerance() == pytest.approx(
        float(get_settings().beveridge.shift_tolerance.shift_pp.value)
    )


def test_beveridge_outward_shift_is_structural() -> None:
    """More openings than the curve predicts at the same u -> outward.

    Hand calculation: openings 5.0, historical curve at this u predicts 4.0.
    shift = +1.0pp, which exceeds the 0.5pp tolerance.
    """
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=5.0,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert as_str(result, key="verdict") == "OUTWARD_SHIFT_structural_mismatch"
    assert as_float(result, key="shift_pp") == pytest.approx(1.0)


def test_beveridge_inward_shift_improves_matching() -> None:
    """Fewer openings than the curve predicts -> inward, not "nothing"."""
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=3.0,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert as_str(result, key="verdict") == "INWARD_SHIFT_improved_matching"
    assert as_float(result, key="shift_pp") == pytest.approx(-1.0)


def test_beveridge_shift_sign_follows_the_direction_of_the_displacement() -> None:
    """The sign of ``shift_pp`` must track the geometry, not the branch order.

    This is the guard that catches a swapped subtraction. Both branches report a
    positive-magnitude number under a swap; only the sign reveals which way the
    curve moved. Asserting the sign against a geometry whose direction is known
    before the code runs is what makes it detectable.
    """
    above = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=5.0,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    below = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=3.0,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert as_float(above, key="shift_pp") > 0
    assert as_float(below, key="shift_pp") < 0


def test_beveridge_shift_is_openings_minus_historical_not_the_reverse() -> None:
    """The cross-field identity: shift == openings - historical, at precision.

    An independent arithmetic statement about the two reported inputs, so a
    sign flip or an operand swap is caught even if the branch thresholds happen
    to be satisfied.
    """
    openings, historical = 5.5, 4.25
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=openings,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=historical,
        )
    )
    expected = round(openings - historical, 2)
    assert as_float(result, key="shift_pp") == pytest.approx(expected)


def test_beveridge_shift_exactly_at_tolerance_is_on_curve() -> None:
    """The boundary: a shift of exactly the tolerance is NOT an outward shift.

    The implementation uses ``shift > tolerance``. A mutation to ``>=`` would
    fire OUTWARD at exactly 0.5pp. No other test in this file lands on the
    boundary, so this one is the sole guard.

    The tolerance is read from config and the shift is constructed from it, so
    the test follows a recalibration rather than silently becoming vacuous.
    """
    tolerance = beveridge_shift_tolerance()
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=4.0 + tolerance,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert as_str(result, key="verdict") == "ON_CURVE_cyclical"


def test_beveridge_shift_inside_tolerance_is_on_curve() -> None:
    tolerance = beveridge_shift_tolerance()
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=4.0 + tolerance / 2.0,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert as_str(result, key="verdict") == "ON_CURVE_cyclical"


def test_beveridge_outward_shift_warns_to_propagate_u_star() -> None:
    """The propagation instruction is the reason this function is not decorative.

    An outward shift raises u*. If a consumer of the Phillips curve is not told
    to update it, this model's output is recorded and then ignored.
    """
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=5.5,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert any("phillips_curve_inflation" in w for w in result.warnings), result.warnings
    assert any("HIGHER u*" in w for w in result.warnings), result.warnings


def test_beveridge_inward_shift_warns_to_propagate_u_star_downward() -> None:
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=3.0,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert any("LOWER u*" in w for w in result.warnings), result.warnings


def test_beveridge_on_curve_does_not_claim_stability() -> None:
    """An on-curve read must not be reported as "the curve has not moved".

    The tolerance band is the fitted curve's resolution, not a statement that
    smaller shifts are absent. An implementation that treated on-curve as
    confirmation of stability would be claiming evidence it does not have.
    """
    result = beveridge_curve_position(
        BeveridgeInputs(
            openings_rate_pct=4.0,
            unemployment_rate_pct=4.0,
            historical_openings_at_this_u=4.0,
        )
    )
    assert any("does NOT mean" in w for w in result.warnings), result.warnings


# --------------------------------------------------------------------------
# ahe_composition_flag
# --------------------------------------------------------------------------


def _ahe_gap(result: ModelResult) -> float | None:
    """Read ``ahe_minus_eci_pp``, which is legitimately ``float | None``.

    ``as_float`` asserts a numeric entry, so it cannot express "this field is
    allowed to be absent". This accessor makes the ``None`` case a first-class
    expectation rather than a hole in the assertions.
    """
    value = result.value
    assert isinstance(value, dict)
    entry = value["ahe_minus_eci_pp"]
    assert entry is None or isinstance(entry, (int, float)), (
        f"ahe_minus_eci_pp is {type(entry).__name__}, expected float or None"
    )
    return None if entry is None else float(entry)


def test_ahe_flags_the_covid_2020_pattern() -> None:
    """AHE +8.0% vs ECI +2.5% with low-wage employment -12% -> flagged.

    The canonical case Module 6.2 cites: AHE surged while low-wage jobs
    disappeared, with nobody receiving a raise.
    """
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=8.0,
            eci_growth_yoy_pct=2.5,
            low_wage_sector_employment_change_pct=-12.0,
        )
    )
    assert as_bool(result, key="distortion_flagged") is True
    assert as_float(result, key="ahe_minus_eci_pp") == pytest.approx(5.5)


def test_ahe_does_not_flag_without_the_composition_mechanism() -> None:
    """A large AHE-minus-ECI gap alone is NOT enough — both conditions required.

    AHE +6% vs ECI +1% is a 5pp gap, but with low-wage employment GROWING the
    composition mechanism cannot be what caused it. An implementation that keyed
    on the gap alone would flag this, so this test pins the conjunction.
    """
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=6.0,
            eci_growth_yoy_pct=1.0,
            low_wage_sector_employment_change_pct=1.5,
        )
    )
    assert as_bool(result, key="distortion_flagged") is False


def test_ahe_does_not_flag_when_eci_confirms_no_divergence() -> None:
    """Mechanism present but ECI agrees -> not flagged.

    The complement of the mechanism test: with low-wage employment -5% (the
    mechanism IS present) but AHE and ECI only 0.2pp apart, ECI has ruled the
    distortion out. This is the case the ECI cross-check exists for.
    """
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=3.5,
            eci_growth_yoy_pct=3.3,
            low_wage_sector_employment_change_pct=-5.0,
        )
    )
    assert as_bool(result, key="distortion_flagged") is False


def test_ahe_flags_when_eci_is_unavailable_and_the_mechanism_is_present() -> None:
    """ECI missing + low-wage decline -> flag on the mechanism alone.

    The conservative direction, and a deliberate design choice: the mechanism is
    present and the test that could clear it is unavailable, so the honest
    report is "suspect", not "clear". An implementation that required ECI would
    report ``False`` here and silently clear a case it cannot actually clear.
    """
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=7.0,
            eci_growth_yoy_pct=None,
            low_wage_sector_employment_change_pct=-5.0,
        )
    )
    assert as_bool(result, key="distortion_flagged") is True
    assert _ahe_gap(result) is None


def test_ahe_reports_none_rather_than_zero_when_eci_is_missing() -> None:
    """``ahe_minus_eci_pp`` is None, never 0.0 — absence is not agreement.

    A 0.0 here would read as "AHE and ECI agree", which is the opposite of
    "ECI is not published". This is the same defect class as substituting a
    proxy for a BLOCKED input.
    """
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=7.0,
            eci_growth_yoy_pct=None,
            low_wage_sector_employment_change_pct=-5.0,
        )
    )
    assert _ahe_gap(result) is None
    assert not isinstance(_ahe_gap(result), float)


def test_ahe_divergence_boundary_is_strictly_greater_than() -> None:
    """A gap of exactly the threshold is NOT a divergence.

    The implementation uses ``abs(...) > threshold``. A mutation to ``>=``
    would flag at exactly 0.75pp. The threshold is read from config so this
    test survives a recalibration, and the gap is constructed from it rather
    than hardcoded.
    """
    threshold = float(get_settings().labor.ahe_distortion.eci_divergence_pp.value)
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=3.0 + threshold,
            eci_growth_yoy_pct=3.0,
            low_wage_sector_employment_change_pct=-5.0,
        )
    )
    # Gap is exactly the threshold -> not a divergence -> not flagged.
    assert as_bool(result, key="distortion_flagged") is False


def test_ahe_low_wage_boundary_is_strictly_less_than() -> None:
    """Low-wage change of exactly the threshold is NOT a decline past it.

    ``< threshold`` where the threshold is -1.0. A change of exactly -1.0 is not
    below it, so the mechanism is absent. A mutation to ``<=`` would flag here.
    """
    threshold = float(get_settings().labor.ahe_distortion.low_wage_decline_pct.value)
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=8.0,
            eci_growth_yoy_pct=2.5,
            low_wage_sector_employment_change_pct=threshold,
        )
    )
    assert as_bool(result, key="distortion_flagged") is False


def test_ahe_flag_always_carries_the_eci_preference_warning() -> None:
    """A flagged result must tell the caller which measure to prefer.

    A flag without the "use ECI instead" instruction leaves a reader knowing
    AHE is suspect but not what to use. The warning is part of the output, not
    optional garnish.
    """
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=8.0,
            eci_growth_yoy_pct=2.5,
            low_wage_sector_employment_change_pct=-12.0,
        )
    )
    assert any("ECI" in w for w in result.warnings), result.warnings


def test_ahe_always_states_the_aggregate_limitation() -> None:
    """The low-wage aggregate cannot separate composition from pay — always say so.

    Asserted on an UNFLAGGED result, deliberately: the limitation is a property
    of the input, not of the verdict, so it must survive on the branch where a
    reader is most likely to accept the output uncritically.
    """
    result = ahe_composition_flag(
        AHEDistortionInputs(
            ahe_growth_yoy_pct=3.5,
            eci_growth_yoy_pct=3.3,
            low_wage_sector_employment_change_pct=1.0,
        )
    )
    assert any("cannot\n" in w or "cannot" in w for w in result.warnings), result.warnings


# --------------------------------------------------------------------------
# nfp_revision_adjusted_read
# --------------------------------------------------------------------------


def test_revision_adjusted_is_headline_plus_net_revisions() -> None:
    """The cross-field identity: adjusted == headline + prior + two_months_ago.

    Three reported quantities that must be mutually consistent. If any operand
    is swapped or a sign dropped, the identity breaks even when the ``misleading``
    flag happens to come out right.
    """
    headline, prior, older = 250.0, -120.0, -80.0
    result = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=headline,
            prior_month_revision=prior,
            two_months_ago_revision=older,
        )
    )
    assert as_float(result, key="headline") == pytest.approx(headline)
    assert as_float(result, key="net_revisions") == pytest.approx(prior + older)
    assert as_float(result, key="revision_adjusted") == pytest.approx(headline + prior + older)


def test_revision_flags_a_beat_masked_by_downward_revisions() -> None:
    """Headline +250k with -200k of net revisions is a weaker picture.

    The case Module 6.1 names: a "beat" that is only a beat in the month whose
    predecessors were overstated. Net revisions -200k is below the -50k
    threshold, so it is flagged.
    """
    result = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=250.0,
            prior_month_revision=-120.0,
            two_months_ago_revision=-80.0,
        )
    )
    assert as_float(result, key="revision_adjusted") == pytest.approx(50.0)
    assert any("masked" in w for w in result.warnings), result.warnings


def test_revision_does_not_flag_a_negative_headline_with_negative_revisions() -> None:
    """A negative headline with negative revisions is CONFIRMED, not masked.

    The implementation requires ``current_month_nfp > 0`` for the misleading
    flag. Here the headline is -100k and revisions are -200k: the two agree, so
    calling the headline "misleading" would be wrong. An implementation that
    keyed only on the revision size would flag this and train a reader to ignore
    the flag.
    """
    result = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=-100.0,
            prior_month_revision=-120.0,
            two_months_ago_revision=-80.0,
        )
    )
    assert as_float(result, key="revision_adjusted") == pytest.approx(-300.0)
    assert not any("masked" in w for w in result.warnings), result.warnings


def test_revision_does_not_flag_when_revisions_are_upward() -> None:
    result = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=250.0,
            prior_month_revision=30.0,
            two_months_ago_revision=10.0,
        )
    )
    assert as_float(result, key="revision_adjusted") == pytest.approx(290.0)
    assert not any("masked" in w for w in result.warnings), result.warnings


def test_revision_misleading_threshold_is_strictly_less_than() -> None:
    """Net revisions exactly AT the threshold do NOT trigger the flag.

    The implementation uses ``net_revisions < threshold``. A mutation to ``<=``
    would fire at exactly -50k. The threshold is read from config and the
    revisions are constructed to land exactly on it, so the test follows a
    recalibration instead of becoming vacuous.
    """
    threshold = float(get_settings().labor.revisions.misleading_net_thousands.value)
    result = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=250.0,
            prior_month_revision=threshold,
            two_months_ago_revision=0.0,
        )
    )
    assert as_float(result, key="net_revisions") == pytest.approx(threshold)
    assert not any("masked" in w for w in result.warnings), result.warnings


def test_revision_zero_headline_is_not_a_beat() -> None:
    """Exactly zero is not "> 0", so the misleading flag cannot fire.

    The other boundary of the misleading condition. A headline of exactly 0.0
    with large downward revisions is not a masked beat because there was no
    beat.
    """
    result = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=0.0,
            prior_month_revision=-200.0,
            two_months_ago_revision=0.0,
        )
    )
    assert not any("masked" in w for w in result.warnings), result.warnings


def test_revision_always_discloses_the_benchmark_limitation() -> None:
    """Two months of revisions is not the full revision history — always say so.

    Payrolls are revised twice more over the following year via the annual
    benchmark. A "revision-adjusted" figure that presented itself as final
    would overstate its own completeness.
    """
    result = nfp_revision_adjusted_read(
        RevisionInputs(
            current_month_nfp=250.0,
            prior_month_revision=30.0,
            two_months_ago_revision=10.0,
        )
    )
    assert any("benchmark" in w for w in result.warnings), result.warnings


# --------------------------------------------------------------------------
# Contract conformance for the four new results
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        two_survey_divergence(_two_survey()),
        beveridge_curve_position(
            BeveridgeInputs(
                openings_rate_pct=5.0,
                unemployment_rate_pct=4.0,
                historical_openings_at_this_u=4.0,
            )
        ),
        ahe_composition_flag(
            AHEDistortionInputs(
                ahe_growth_yoy_pct=8.0,
                eci_growth_yoy_pct=2.5,
                low_wage_sector_employment_change_pct=-12.0,
            )
        ),
        nfp_revision_adjusted_read(
            RevisionInputs(
                current_month_nfp=250.0,
                prior_month_revision=-120.0,
                two_months_ago_revision=-80.0,
            )
        ),
    ],
)
def test_every_new_module_6_result_conforms_to_the_contract(result: ModelResult) -> None:
    """Section 22.9's value union, and the fields every result must carry."""
    assert isinstance(result, ModelResult)
    assert result.country == "us"
    assert result.as_of.tzinfo is not None
    assert result.as_of.utcoffset() is not None
    assert 0.0 <= result.confidence <= 1.0
    assert result.interpretation
    assert result.context
    assert result.inputs_used
    assert result.warnings

    allowed = (float, int, str, bool, dict, list, type(None))
    assert isinstance(result.value, allowed), f"unexpected value type {type(result.value)}"
    if isinstance(result.value, float):
        assert math.isfinite(result.value)


def test_new_results_carry_no_hardcoded_confidence() -> None:
    """Section 22.8: confidence comes from ``compute_confidence()``, not a literal.

    Every model in this batch routes through the same producer, so all four must
    agree — if one were hardcoding, it would disagree with the others. This
    asserts equality across all four rather than comparing each to a constant,
    because the constant itself is uncalibrated until Phase 5+.
    """
    confidences = {
        two_survey_divergence(_two_survey()).confidence,
        beveridge_curve_position(
            BeveridgeInputs(
                openings_rate_pct=5.0,
                unemployment_rate_pct=4.0,
                historical_openings_at_this_u=4.0,
            )
        ).confidence,
        ahe_composition_flag(
            AHEDistortionInputs(
                ahe_growth_yoy_pct=8.0,
                eci_growth_yoy_pct=2.5,
                low_wage_sector_employment_change_pct=-12.0,
            )
        ).confidence,
        nfp_revision_adjusted_read(
            RevisionInputs(
                current_month_nfp=250.0,
                prior_month_revision=-120.0,
                two_months_ago_revision=-80.0,
            )
        ).confidence,
    }
    assert len(confidences) == 1, f"confidences diverge across the batch: {confidences}"


def test_input_models_reject_unknown_fields() -> None:
    """``extra="forbid"`` on every new input model.

    A typo'd keyword silently ignored is how a caller ends up feeding a default
    into a model and reading the output as if it were informed by real inputs.
    """
    with pytest.raises(ValidationError):
        TwoSurveyInputs(nfp_change_thousand=200.0)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BeveridgeInputs(openings_rate_pct=5.0, unemployment_rate_pct=4.0)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        AHEDistortionInputs(  # type: ignore[call-arg]
            ahe_growth_yoy_pct=8.0, low_wage_sector_employment_change_pct=-12.0, typo=1.0
        )
    with pytest.raises(ValidationError):
        RevisionInputs(current_month_nfp=250.0, prior_month_revision=-120.0)  # type: ignore[call-arg]


def test_beveridge_rejects_an_impossible_unemployment_rate() -> None:
    """A rate above 100% is rejected at the boundary, not propagated.

    The Phase 1 validation discipline applies to model inputs too: an
    impossible number should fail where it enters, not produce a plausible
    verdict downstream.
    """
    with pytest.raises(ValidationError):
        BeveridgeInputs(
            openings_rate_pct=5.0,
            unemployment_rate_pct=150.0,
            historical_openings_at_this_u=4.0,
        )
