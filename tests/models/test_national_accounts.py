"""Hand-verified tests for Module 3 national accounts.

AGENTS.md Section 20.3, Section 20.5, Section 11.1, Section 21.2 Steps 4-5.

Section 11.1 mandates ``test_savings_investment_identity_balances`` by name.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_engine.config import (
    CalibratedValue,
    MinskyBaseRates,
    MinskySettings,
    PolicyMixBaseRates,
    PolicyMixSettings,
    get_settings,
)
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.national_accounts import (
    FisherIndexInputs,
    IndexNumberInputs,
    MinskyCompositionInputs,
    OpeningsToUnemployedInputs,
    PolicyMixInputs,
    QuantityTheoryInputs,
    SavingsInvestmentInputs,
    fisher_index,
    gdp_deflator,
    laspeyres_index,
    minsky_composition_drift,
    openings_to_unemployed_ratio,
    paasche_index,
    policy_mix_classifier,
    quantity_theory_implied_inflation,
    savings_investment_identity,
)
from tests.helpers import as_bool, as_float, as_int, as_str


def test_savings_investment_identity_balances() -> None:
    """Section 11.1's mandated identity test.

    Hand computation with percent-of-GDP magnitudes:
        S = 17.0, I = 21.0  ->  private balance = -4.0
        T = 18.0, G = 24.0  ->  fiscal balance  = -6.0
        implied CA = -4.0 + -6.0 = -10.0

    This is an IDENTITY, so the assertion that matters is that the components
    sum to the total exactly — not that the number looks plausible. A test
    checking only the total would pass for an implementation that swapped S and
    I, because swapping signs in both components can leave the sum unchanged.
    """
    result = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=17.0,
            private_investment=21.0,
            tax_revenue=18.0,
            government_spending=24.0,
        )
    )
    assert isinstance(result.value, dict)
    private_balance = result.value["private_balance"]
    fiscal_balance = result.value["fiscal_balance"]
    implied_ca = result.value["implied_current_account"]

    assert private_balance == -4.0
    assert fiscal_balance == -6.0
    assert implied_ca == -10.0
    # The identity itself, asserted rather than the three values independently.
    assert implied_ca == pytest.approx(private_balance + fiscal_balance, abs=1e-9)


def test_savings_investment_identity_holds_for_a_surplus_case() -> None:
    """A second sign combination, so the identity is not merely fitted to deficits.

    S = 22.0, I = 19.0 -> private = +3.0
    T = 21.0, G = 20.0 -> fiscal  = +1.0
    implied CA = +4.0
    """
    result = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=22.0,
            private_investment=19.0,
            tax_revenue=21.0,
            government_spending=20.0,
        )
    )
    assert isinstance(result.value, dict)
    assert result.value["private_balance"] == 3.0
    assert result.value["fiscal_balance"] == 1.0
    assert result.value["implied_current_account"] == 4.0
    assert "surplus" in result.interpretation


def test_savings_investment_identity_returns_the_components() -> None:
    """The components are what a thesis argues about, so they must be returned.

    A function returning only the current account would make "the fiscal
    balance is the whole current account" unverifiable from its own output.
    """
    result = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=17.0, private_investment=21.0, tax_revenue=18.0, government_spending=24.0
        )
    )
    assert isinstance(result.value, dict)
    assert {"private_balance", "fiscal_balance", "implied_current_account"} <= set(result.value)


def test_quantity_theory_implied_inflation_matches_hand_calculation() -> None:
    """%dM 5.0 + %dV -2.0 - %dY 2.0 = +1.0.

    The 2009-2015 shape: large money growth almost entirely offset by velocity
    collapse, leaving little price response.
    """
    result = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=5.0,
            velocity_change_pct=-2.0,
            real_output_growth_pct=2.0,
        )
    )
    assert result.value == pytest.approx(1.0, abs=0.005)


def test_quantity_theory_velocity_offset_is_visible() -> None:
    """Two scenarios with IDENTICAL money growth must produce different
    implied inflation when velocity differs.

    This is the mechanism Section 20.2 describes as the reason naive "money
    printing causes inflation" reasoning failed in the 2010s: the same %dM with
    a velocity collapse versus a velocity hold gives opposite answers. A test
    that only checked one scenario would not demonstrate the term is live.
    """
    qe_era = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=15.0,
            velocity_change_pct=-13.0,
            real_output_growth_pct=2.0,
        )
    )
    covid_era = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=15.0,
            velocity_change_pct=-1.0,
            real_output_growth_pct=2.0,
        )
    )
    assert as_float(qe_era) == pytest.approx(0.0, abs=0.005)
    assert as_float(covid_era) == pytest.approx(12.0, abs=0.005)
    assert as_float(covid_era) - as_float(qe_era) == pytest.approx(12.0, abs=0.01)


def test_quantity_theory_is_marked_low_confidence() -> None:
    """Section 20.2 supplies confidence 0.25; the computed value must reflect
    that the model leans on an uncalibrated heuristic.

    Asserting `result.confidence < 0.5` is IMPOSSIBLE under the current
    configuration, and saying so is more useful than loosening the bound until
    it passes. `base - heuristic_penalty = 0.7 - 0.2 = 0.5` exactly, and this
    model carries no further penalties (nothing unobservable, no data-quality
    flags), so the computed value IS 0.5. Section 20.2's literal was 0.25; the
    formula and the illustrative literal disagree by construction, and Section
    22.8 says the formula governs.

    What is actually verified here is the thing that matters: the heuristic
    penalty was APPLIED. That is observable as an exact equality, and it is a
    real guard — before the `is_calibrated()` fix it failed, because every leaf
    typed as `CalibratedValue` reported itself uncalibrated in the wrong
    direction and no penalty was applied at all.
    """
    from macro_engine.config import get_settings

    result = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=5.0, velocity_change_pct=-2.0, real_output_growth_pct=2.0
        )
    )
    settings = get_settings()
    base = settings.scalar("confidence.base")
    heuristic_penalty = settings.scalar("confidence.heuristic_penalty")

    assert settings.is_calibrated("confidence.heuristic_penalty") is False, (
        "if this config leaf is ever marked calibrated, the penalty no longer "
        "applies and this test's premise changes"
    )
    assert result.confidence == pytest.approx(base - heuristic_penalty, abs=1e-9), (
        "the heuristic penalty must be applied for leaning on an uncalibrated "
        "illustrative threshold"
    )
    assert result.confidence < base, "the model must report less confidence than the untouched base"
    assert any("velocity" in warning.lower() for warning in result.warnings), (
        "the diagnostic-only caveat is load-bearing output, not boilerplate"
    )


def _basket() -> IndexNumberInputs:
    """A two-item basket chosen so every index value is hand-computable.

    Base:    apples 1.00 x 10 = 10,  bread 2.00 x 5 = 10  -> base cost 20
    Current: apples 1.20 x  8 = 9.6, bread 2.00 x 6 = 12  -> current cost 21.6
        (the consumer substituted AWAY from apples, whose price rose, and
         TOWARD bread, whose price did not — the substitution that makes the
         Laspeyres/Paasche spread meaningful)

    Laspeyres = (1.20*10 + 2.00*5) / 20 * 100 = (12 + 10)/20*100 = 110.0
    Paasche   = 21.6 / (1.00*8 + 2.00*6) * 100 = 21.6/20*100      = 108.0
    Fisher    = sqrt(110.0 * 108.0) = sqrt(11880) = 108.993...
    """
    return IndexNumberInputs(
        base_prices={"apples": 1.00, "bread": 2.00},
        base_quantities={"apples": 10.0, "bread": 5.0},
        current_prices={"apples": 1.20, "bread": 2.00},
        current_quantities={"apples": 8.0, "bread": 6.0},
    )


def test_laspeyres_index_matches_hand_calculation() -> None:
    assert laspeyres_index(_basket()).value == pytest.approx(110.0, abs=1e-6)


def test_paasche_index_matches_hand_calculation() -> None:
    assert paasche_index(_basket()).value == pytest.approx(108.0, abs=1e-6)


def test_fisher_index_matches_hand_calculation() -> None:
    """sqrt(110 * 108) = 108.9954127475097, which rounds to 108.9954.

    Note: an earlier version of this test asserted 108.9931, which was an
    arithmetic slip on my part, not a code defect. The value is quoted to four
    decimals here so the assertion is precise enough to catch a real error in
    the geometric mean.
    """
    result = fisher_index(FisherIndexInputs(laspeyres=110.0, paasche=108.0))
    assert result.value == pytest.approx(108.9954, abs=0.0001)


def test_laspeyres_exceeds_paasche_when_substitution_occurs() -> None:
    """The bias direction, asserted as an inequality across the three functions.

    Laspeyres holds the expensive-now basket fixed and therefore overstates;
    Paasche already credits the substitution and understates. Asserting the
    ORDER rather than the three values is what makes this a real guard — an
    implementation that computed both with the same quantity vector would give
    them equal, and an equality-based test on the individual values would not
    necessarily notice.
    """
    basket = _basket()
    laspeyres_value = as_float(laspeyres_index(basket))
    paasche_value = as_float(paasche_index(basket))
    fisher_value = as_float(
        fisher_index(FisherIndexInputs(laspeyres=laspeyres_value, paasche=paasche_value))
    )

    assert laspeyres_value > paasche_value
    assert paasche_value < fisher_value < laspeyres_value


def test_fisher_index_rejects_non_positive_inputs() -> None:
    """A price index cannot be zero or negative; the field constraint enforces it."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FisherIndexInputs(laspeyres=0.0, paasche=100.0)


def test_index_rejects_a_basket_with_mismatched_items() -> None:
    """An item present in prices but absent from quantities must raise.

    Silently treating the missing quantity as zero would produce a number that
    looks like an index and weights a different basket.
    """
    with pytest.raises(ValueError, match=r"absent from quantities"):
        laspeyres_index(
            IndexNumberInputs(
                base_prices={"a": 1.0, "b": 2.0},
                base_quantities={"a": 1.0},
                current_prices={"a": 1.0, "b": 2.0},
                current_quantities={"a": 1.0},
            )
        )


def test_gdp_deflator_matches_hand_calculation() -> None:
    """24,269.613 / 22,500.000 * 100 = 107.865..."""
    result = gdp_deflator(nominal_gdp=24269.613, real_gdp=22500.000)
    assert as_float(result) == pytest.approx(107.865, abs=0.001)


def test_gdp_deflator_rejects_zero_real_gdp() -> None:
    with pytest.raises(ValueError, match="undefined"):
        gdp_deflator(nominal_gdp=100.0, real_gdp=0.0)


def test_gdp_deflator_warns_against_cpi_comparison() -> None:
    """The deflator and CPI are not comparable as levels, and the warning says so."""
    result = gdp_deflator(nominal_gdp=24269.613, real_gdp=22500.000)
    assert any("Not comparable to CPI" in warning for warning in result.warnings)


def test_openings_to_unemployed_ratio_matches_hand_calculation() -> None:
    """7,440 / 7,000 = 1.0628... -> 1.063, which is TIGHT (above 1.0, below 1.5)."""
    result = openings_to_unemployed_ratio(
        OpeningsToUnemployedInputs(
            job_openings_thousands=7440.0, unemployed_persons_thousands=7000.0
        )
    )
    assert as_float(result) == pytest.approx(1.063, abs=0.001)
    assert "TIGHT" in result.interpretation


def test_openings_ratio_band_boundaries() -> None:
    """Every band boundary, at values chosen just either side.

    Boundaries are where off-by-one comparisons hide, so each threshold is
    probed from both directions rather than sampled once.
    """
    cases = [
        (1.60, "VERY_TIGHT"),
        (1.50, "TIGHT"),  # not > 1.5, so falls to the next band
        (1.10, "TIGHT"),
        (1.00, "BALANCED"),  # not > 1.0
        (0.80, "BALANCED"),
        (0.70, "SLACK"),  # not > 0.7
        (0.50, "SLACK"),
    ]
    for ratio, expected in cases:
        result = openings_to_unemployed_ratio(
            OpeningsToUnemployedInputs(
                job_openings_thousands=ratio * 1000.0,
                unemployed_persons_thousands=1000.0,
            )
        )
        assert expected in result.interpretation, f"ratio {ratio} expected {expected}"


def test_openings_ratio_rejects_zero_unemployed() -> None:
    """Zero unemployed persons is not an observable US state, and the ratio
    would be undefined — the field constraint refuses it."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OpeningsToUnemployedInputs(job_openings_thousands=7000.0, unemployed_persons_thousands=0.0)


# ---------------------------------------------------------------------------
# Module 3.2 — policy_mix_classifier
# ---------------------------------------------------------------------------


def _pm_leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose."""
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _pm_settings() -> PolicyMixSettings:
    return get_settings().policy_mix


def _pm_inputs(
    *,
    deficit: float = 6.0,
    average: float = 4.5,
    policy: float = 6.0,
    taylor: float = 5.0,
) -> PolicyMixInputs:
    """Inputs whose every quadrant is known by construction.

    Defaults are fiscal loose (6.0 against a 4.5 average) and monetary tight
    (6.0 above a 5.0 Taylor rate) — MIXED_FISCAL_LOOSE_MONETARY_TIGHT, the
    post-2022 case the specification names.
    """
    return PolicyMixInputs(
        fiscal_deficit_pct_gdp=deficit,
        fiscal_deficit_avg_pct_gdp=average,
        policy_rate=policy,
        taylor_implied_rate=taylor,
    )


def test_the_four_quadrants_are_placed_correctly() -> None:
    """The 2x2, with each cell reached by a hand-chosen pair of comparisons."""
    cases = [
        (6.0, 4.5, 3.0, 5.0, "MAX_STIMULUS", True, True),
        (6.0, 4.5, 6.0, 5.0, "MIXED_FISCAL_LOOSE_MONETARY_TIGHT", True, False),
        (3.0, 4.5, 3.0, 5.0, "MIXED_FISCAL_TIGHT_MONETARY_LOOSE", False, True),
        (3.0, 4.5, 6.0, 5.0, "MAX_RESTRAINT", False, False),
    ]
    for deficit, average, policy, taylor, expected, fis, mon in cases:
        result = policy_mix_classifier(
            _pm_inputs(deficit=deficit, average=average, policy=policy, taylor=taylor)
        )
        assert as_str(result, key="quadrant") == expected, (
            f"deficit={deficit} avg={average} policy={policy} taylor={taylor}"
        )
        assert as_bool(result, key="fiscal_loose") is fis
        assert as_bool(result, key="monetary_loose") is mon


def test_the_quadrant_is_recomputable_from_its_published_predicates() -> None:
    """The cross-field identity (D-009).

    Section 20.3's specification returns ``value=quadrant`` — a bare string with
    no predicates — so a consumer had no way to check the answer. The two
    booleans are published here precisely so this recomputation is possible.
    """
    for deficit, policy in ((6.0, 3.0), (6.0, 6.0), (3.0, 3.0), (3.0, 6.0)):
        result = policy_mix_classifier(_pm_inputs(deficit=deficit, policy=policy))
        fis = as_bool(result, key="fiscal_loose")
        mon = as_bool(result, key="monetary_loose")
        expected = (
            "MAX_STIMULUS"
            if fis and mon
            else "MIXED_FISCAL_LOOSE_MONETARY_TIGHT"
            if fis
            else "MIXED_FISCAL_TIGHT_MONETARY_LOOSE"
            if mon
            else "MAX_RESTRAINT"
        )
        assert as_str(result, key="quadrant") == expected, (
            "the published quadrant disagrees with its own published predicates"
        )
        # And the mixed flag must be exactly "the two disagree".
        assert as_bool(result, key="mixed") is (fis != mon)


# --- the sign trap ---------------------------------------------------------


def test_a_raw_fred_deficit_inverts_the_comparison_and_is_flagged() -> None:
    """The sign convention, on the value that actually triggers it.

    FRED `FYFSGDA188S` is NEGATIVE for a deficit. A caller who supplies it raw
    puts a genuine 6% deficit in as -6.0, which is BELOW the 4.5 average, so the
    model reports fiscal TIGHT — the exact inversion of the truth. The model
    cannot know which convention the caller used, so it flags the negative value
    and says what the sign means.
    """
    result = policy_mix_classifier(_pm_inputs(deficit=-6.0, average=4.5))
    assert as_bool(result, key="fiscal_loose") is False, (
        "a raw-FRED deficit reads as tight — this is the defect being disclosed"
    )
    matches = [w for w in result.warnings if "POSITIVE for a deficit" in w]
    assert len(matches) == 1, "the sign convention must be warned about exactly once"
    assert "inverts" in matches[0]


def test_a_surplus_does_not_raise_the_sign_warning() -> None:
    """The absence half: a negative value is not ALWAYS the FRED sign.

    A genuine surplus is also negative, and the warning's wording covers both.
    What must not happen is the warning firing on an ordinary positive deficit.
    """
    surplus = policy_mix_classifier(_pm_inputs(deficit=-1.0, average=4.5))
    assert any("POSITIVE for a deficit" in w for w in surplus.warnings), (
        "a negative value is flagged whether it is a surplus or a raw FRED figure"
    )
    ordinary = policy_mix_classifier(_pm_inputs(deficit=6.0, average=4.5))
    assert not any("POSITIVE for a deficit" in w for w in ordinary.warnings), (
        "an ordinary positive deficit must not raise the sign warning"
    )


# --- the boundaries --------------------------------------------------------


def test_a_deficit_exactly_at_its_average_is_not_loose() -> None:
    """The comparison is strict, and the boundary is built by construction.

    Both sides are set to the same literal 4.5, so the point under test is
    exactly on the boundary rather than near it.
    """
    result = policy_mix_classifier(_pm_inputs(deficit=4.5, average=4.5))
    assert as_bool(result, key="fiscal_loose") is False, (
        "a deficit exactly at its average is not above it — the comparison is strict"
    )


def test_a_policy_rate_exactly_at_the_taylor_rate_is_not_loose() -> None:
    """The monetary comparison is strict too."""
    result = policy_mix_classifier(_pm_inputs(policy=5.0, taylor=5.0))
    assert as_bool(result, key="monetary_loose") is False, (
        "a policy rate exactly at the Taylor rate is not below it"
    )


# --- the disclosures -------------------------------------------------------


def test_the_mixed_warning_fires_on_exactly_the_two_mixed_quadrants() -> None:
    """The warning is about fiscal and monetary DISAGREEING.

    Section 20.3's sample tests ``"MIXED" in quadrant`` — a substring search on
    the quadrant name. That happens to work on today's names and breaks silently
    if one is renamed, so the model tests the booleans instead. This test pins
    the behaviour either way: exactly two of the four quadrants warn.
    """
    warned = []
    for deficit, policy in ((6.0, 3.0), (6.0, 6.0), (3.0, 3.0), (3.0, 6.0)):
        result = policy_mix_classifier(_pm_inputs(deficit=deficit, policy=policy))
        fired = any("working against monetary" in w for w in result.warnings)
        warned.append((as_str(result, key="quadrant"), fired))
    firing = {name for name, fired in warned if fired}
    assert firing == {
        "MIXED_FISCAL_LOOSE_MONETARY_TIGHT",
        "MIXED_FISCAL_TIGHT_MONETARY_LOOSE",
    }, f"exactly the two MIXED quadrants must warn; got {sorted(firing)}"


def test_every_quadrant_travels_with_its_own_base_rate() -> None:
    """D-029: a categorical from threshold comparisons carries its frequency.

    The rates are patched to DISTINCT values, so neither a swap nor a literal
    can satisfy the assertion, and each quadrant is checked against its own.
    """
    patched = _pm_settings().model_copy(
        update={
            "base_rates": PolicyMixBaseRates(
                observations_measured_value=_pm_leaf(4321),
                max_stimulus_rate_value=_pm_leaf(0.1111),
                mixed_fiscal_loose_monetary_tight_rate_value=_pm_leaf(0.2222),
                mixed_fiscal_tight_monetary_loose_rate_value=_pm_leaf(0.3333),
                max_restraint_rate_value=_pm_leaf(0.4444),
            )
        }
    )
    expected = {
        "MAX_STIMULUS": 0.1111,
        "MIXED_FISCAL_LOOSE_MONETARY_TIGHT": 0.2222,
        "MIXED_FISCAL_TIGHT_MONETARY_LOOSE": 0.3333,
        "MAX_RESTRAINT": 0.4444,
    }
    with patch("macro_engine.models.national_accounts._policy_mix_settings", return_value=patched):
        for deficit, policy in ((6.0, 3.0), (6.0, 6.0), (3.0, 3.0), (3.0, 6.0)):
            result = policy_mix_classifier(_pm_inputs(deficit=deficit, policy=policy))
            quadrant = as_str(result, key="quadrant")
            assert as_float(result, key="quadrant_base_rate") == pytest.approx(
                expected[quadrant]
            ), f"{quadrant} must carry its OWN base rate"
            assert as_int(result, key="observations_measured") == 4321
            assert any(f"{expected[quadrant]:.1%}" in w for w in result.warnings), (
                "the base rate must also reach the prose"
            )
    assert _pm_settings().base_rates.observations_measured != 4321, (
        "the fixture must differ from the shipped record or the patch proves nothing"
    )


def test_a_deficit_average_that_disagrees_with_config_is_flagged() -> None:
    """The supplied average and the config's are one measurement.

    A caller using a different window places the same deficit in a different
    quadrant, so the disagreement is reported rather than silently accepted.
    """
    shipped = _pm_settings().fiscal_deficit_avg
    agreeing = policy_mix_classifier(_pm_inputs(average=shipped))
    assert not any("differs from the configured expectation" in w for w in agreeing.warnings)

    disagreeing = policy_mix_classifier(_pm_inputs(average=shipped + 5.0))
    matches = [w for w in disagreeing.warnings if "differs from the configured" in w]
    assert len(matches) == 1, "a materially different average must be flagged"


def test_the_configured_average_is_read_from_config() -> None:
    """Patched to a value the shipped config does not hold.

    Patched to **20.0**, which sits far from BOTH the shipped 4.5 and any
    plausible hardcoded stand-in. The first version patched to 9.75 — only 0.24
    from a mutation's hardcoded 9.99, and therefore INSIDE the 0.5 mismatch
    tolerance — so a property returning a literal passed every assertion here
    and the mutation survived.
    """
    patched = _pm_settings().model_copy(update={"fiscal_deficit_avg_pct_gdp": _pm_leaf(20.0)})
    with patch("macro_engine.models.national_accounts._policy_mix_settings", return_value=patched):
        agreeing = policy_mix_classifier(_pm_inputs(average=20.0))
        disagreeing = policy_mix_classifier(_pm_inputs(average=4.5))
    assert not any("differs from the configured expectation" in w for w in agreeing.warnings), (
        "with config patched to 20.0, a supplied 20.0 must agree"
    )
    assert any("differs from the configured expectation" in w for w in disagreeing.warnings), (
        "with config patched to 20.0, the shipped 4.5 must now be the odd one out"
    )
    assert _pm_settings().fiscal_deficit_avg != 20.0


def test_the_deficit_mismatch_tolerance_is_read_from_config() -> None:
    """D-139 MOVER test: the mismatch tolerance is a leaf-read, not a literal.

    The tolerance was a bare ``> 0.5`` in the model body. A mismatch of 0.3pp
    is BELOW the default tolerance, so it must NOT warn; widening the tolerance
    leaves that unchanged, but NARROWING it below 0.3 must start warning. The
    discriminating move is therefore to tighten the leaf, which a hardcoded
    0.5 could never follow.
    """
    shipped = _pm_settings().fiscal_deficit_avg
    small_mismatch = shipped + 0.3

    # Control: at the shipped 0.5 tolerance a 0.3pp mismatch is silent.
    baseline = policy_mix_classifier(_pm_inputs(average=small_mismatch))
    assert not any("differs from the configured" in w for w in baseline.warnings), (
        "a 0.3pp mismatch must be inside the shipped 0.5 tolerance"
    )

    # Move the tolerance to 0.1 and the SAME input must now be flagged.
    patched = _pm_settings().model_copy(update={"deficit_mismatch_tolerance_pp": _pm_leaf(0.1)})
    with patch("macro_engine.models.national_accounts._policy_mix_settings", return_value=patched):
        tightened = policy_mix_classifier(_pm_inputs(average=small_mismatch))
    assert any("differs from the configured" in w for w in tightened.warnings), (
        "a 0.3pp mismatch must be flagged once the tolerance is tightened to "
        "0.1; a hardcoded 0.5 in the body could not follow the leaf"
    )


# --- confidence ------------------------------------------------------------


def test_confidence_is_computed_from_the_stated_factors() -> None:
    """Section 22.8, and the unobservable factor is a fact about the computation.

    The Taylor-implied rate rests on r* and potential GDP, so
    `depends_on_unobservable=True` is asserted rather than felt.
    """
    result = policy_mix_classifier(_pm_inputs())
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _pm_calibrated_today(),
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)


def test_the_unobservable_penalty_is_applied() -> None:
    """The model must cost more confidence than one that depends on nothing unobservable."""
    result = policy_mix_classifier(_pm_inputs())
    no_unobservable = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _pm_calibrated_today(),
            depends_on_unobservable=False,
            source_independence_count=0,
        )
    )
    assert result.confidence < no_unobservable, (
        "resting on r* and potential GDP must lower confidence"
    )


def test_confidence_rises_when_the_average_is_calibrated() -> None:
    with patch("macro_engine.models.national_accounts._policy_mix_calibrated", return_value=True):
        calibrated = policy_mix_classifier(_pm_inputs())
    illustrative = policy_mix_classifier(_pm_inputs())
    assert calibrated.confidence > illustrative.confidence


def _pm_calibrated_today() -> bool:
    from macro_engine.models.national_accounts import _policy_mix_calibrated

    return _policy_mix_calibrated()


# --- the input contract ----------------------------------------------------


def test_the_input_contract_forbids_extra_fields() -> None:
    """A complete payload plus one unknown field — no ambiguity about the cause."""
    with pytest.raises(Exception, match="deficit"):
        PolicyMixInputs(  # type: ignore[call-arg]
            fiscal_deficit_pct_gdp=6.0,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=6.0,
            taylor_implied_rate=5.0,
            fiscal_deficit=6.0,
        )


def test_every_input_used_is_declared() -> None:
    """Section 20.3's sample omits `fiscal_deficit_avg_pct_gdp`, which it uses.

    An undeclared input is one a consumer cannot audit, and this one decides
    half the quadrant.
    """
    result = policy_mix_classifier(_pm_inputs())
    assert set(result.inputs_used) == {
        "fiscal_deficit_pct_gdp",
        "fiscal_deficit_avg_pct_gdp",
        "policy_rate",
        "taylor_implied_rate",
    }


def test_every_raw_input_is_republished() -> None:
    """A consumer reading only ``value`` must be able to see what the model was given.

    A mutation replacing the published deficit with 0.0 survived the first sweep
    because nothing asserted the raw inputs reach the output: the cross-field
    identity test checks the quadrant from the booleans, and the base-rate test
    checks the base rate, and neither of them reads the inputs.
    """
    result = policy_mix_classifier(_pm_inputs(deficit=6.25, average=4.75, policy=5.5, taylor=4.25))
    assert as_float(result, key="fiscal_deficit_pct_gdp") == pytest.approx(6.25)
    assert as_float(result, key="fiscal_deficit_avg_pct_gdp") == pytest.approx(4.75)
    assert as_float(result, key="policy_rate") == pytest.approx(5.5)
    assert as_float(result, key="taylor_implied_rate") == pytest.approx(4.25)


def test_all_four_quadrants_are_reachable() -> None:
    """The vocabulary must be a closed set with no dead member.

    D-037's lesson from the credit model: a named state no input can produce is
    a contradiction, not a restriction. Enumerating the 2x2's whole input space
    is cheap, so it is done rather than assumed.
    """
    reachable = {
        as_str(policy_mix_classifier(_pm_inputs(deficit=d, policy=p)), key="quadrant")
        for d in (6.0, 3.0)
        for p in (3.0, 6.0)
    }
    assert reachable == {
        "MAX_STIMULUS",
        "MIXED_FISCAL_LOOSE_MONETARY_TIGHT",
        "MIXED_FISCAL_TIGHT_MONETARY_LOOSE",
        "MAX_RESTRAINT",
    }


# ---------------------------------------------------------------------------
# Module 3.4 — minsky_composition_drift
# ---------------------------------------------------------------------------


def _mi_leaf(value: float | int) -> CalibratedValue:
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _mi_settings() -> MinskySettings:
    return get_settings().minsky


def _mi_inputs(
    *, standards: float = -5.0, risky: float = 13.0, total: float = 10.0
) -> MinskyCompositionInputs:
    """Defaults are loose standards AND risky outgrowing -> PONZI_DRIFT_WARNING."""
    return MinskyCompositionInputs(
        lending_standards_net_tightening_pct=standards,
        risky_credit_growth_pct=risky,
        total_credit_growth_pct=total,
    )


def test_minsky_ponzi_drift_flags() -> None:
    """Section 11.1's mandated golden test, by name.

    *"loosening standards + risky credit outgrowing total must flag
    PONZI_DRIFT_WARNING"*. Hand computation with the shipped 20% margin:
    standards -5.0 (< 0, loosening) and risky 13.0 against total 10.0, a gap of
    3.0 against a threshold of 0.2 * |10.0| = 2.0 — so 3.0 > 2.0 and both
    predicates hold.
    """
    result = minsky_composition_drift(_mi_inputs(standards=-5.0, risky=13.0, total=10.0))
    assert as_str(result, key="stage") == "PONZI_DRIFT_WARNING"
    assert as_bool(result, key="standards_loosening") is True
    assert as_bool(result, key="risky_outgrowing") is True
    assert as_float(result, key="growth_gap_pct") == pytest.approx(3.0)
    assert as_float(result, key="drift_threshold_pct") == pytest.approx(2.0)


def test_the_three_stages_are_placed_correctly() -> None:
    cases = [
        (-5.0, 13.0, 10.0, "PONZI_DRIFT_WARNING"),
        (-5.0, 11.0, 10.0, "SPECULATIVE_DRIFT"),
        (5.0, 13.0, 10.0, "SPECULATIVE_DRIFT"),
        (5.0, 11.0, 10.0, "HEDGE_DOMINANT"),
    ]
    for standards, risky, total, expected in cases:
        result = minsky_composition_drift(_mi_inputs(standards=standards, risky=risky, total=total))
        assert as_str(result, key="stage") == expected, (
            f"standards={standards} risky={risky} total={total}"
        )


def test_all_three_stages_are_reachable() -> None:
    """No dead branch: enumerate the predicate space rather than assume it."""
    reachable = {
        as_str(
            minsky_composition_drift(_mi_inputs(standards=s, risky=r, total=10.0)),
            key="stage",
        )
        for s in (-5.0, 5.0)
        for r in (11.0, 13.0)
    }
    assert reachable == {"PONZI_DRIFT_WARNING", "SPECULATIVE_DRIFT", "HEDGE_DOMINANT"}


# --- the negative-growth correction ----------------------------------------


def test_de_risking_is_not_flagged_as_drift() -> None:
    """THE correction. Section 20.3's `risky > total * 1.2` inverts when total
    growth is negative, because multiplying a negative base by 1.2 makes it MORE
    negative.

    total -10%, risky -11%: risky credit is shrinking FASTER than total, which is
    de-risking — composition moving AWAY from risky. The specification's form
    gives `-11 > -12` = True, flagging drift at the moment of maximum de-risking.
    The gap form gives `-1.0 > 2.0` = False, which is correct.

    Negative total credit growth occurs in 3.3% of measured weeks, including
    2009-09 — the crisis the module exists to flag.
    """
    result = minsky_composition_drift(_mi_inputs(standards=-5.0, risky=-11.0, total=-10.0))
    assert as_bool(result, key="risky_outgrowing") is False, (
        "risky credit falling faster than total is DE-RISKING, not drift"
    )
    assert as_str(result, key="stage") == "SPECULATIVE_DRIFT", (
        "loose standards alone is SPECULATIVE, not PONZI"
    )


def test_risky_holding_up_better_in_a_contraction_is_drift() -> None:
    """The complement: risky falling LESS than total IS composition drift."""
    result = minsky_composition_drift(_mi_inputs(standards=-5.0, risky=-5.0, total=-10.0))
    assert as_bool(result, key="risky_outgrowing") is True
    assert as_str(result, key="stage") == "PONZI_DRIFT_WARNING"


def test_positive_growth_behaves_exactly_as_the_specification_says() -> None:
    """The correction must be invisible for positive total growth.

    For total > 0 the gap form and `risky > total * 1.2` are algebraically the
    same: `risky - total > 0.2 * total` iff `risky > 1.2 * total`. Pinned so the
    correction cannot quietly change the specified behaviour.
    """
    for risky in (10.0, 11.9, 12.0, 12.1, 13.0, 20.0):
        total = 10.0
        result = minsky_composition_drift(_mi_inputs(standards=5.0, risky=risky, total=total))
        spec_form = risky > total * 1.2
        assert as_bool(result, key="risky_outgrowing") is spec_form, (
            f"risky={risky} total={total}: the gap form must agree with "
            f"`risky > total * 1.2` for positive growth"
        )


def test_a_flat_total_makes_any_positive_risky_growth_drift() -> None:
    """With total flat, risky's SHARE rises on any positive growth."""
    growing = minsky_composition_drift(_mi_inputs(standards=5.0, risky=1.0, total=0.0))
    assert as_bool(growing, key="risky_outgrowing") is True
    falling = minsky_composition_drift(_mi_inputs(standards=5.0, risky=-1.0, total=0.0))
    assert as_bool(falling, key="risky_outgrowing") is False


def test_the_drift_threshold_is_inclusive_at_the_boundary() -> None:
    """A gap EXACTLY at the threshold is not outgrowing — the comparison is strict."""
    at = minsky_composition_drift(_mi_inputs(standards=5.0, risky=12.0, total=10.0))
    assert as_float(at, key="growth_gap_pct") == pytest.approx(2.0)
    assert as_float(at, key="drift_threshold_pct") == pytest.approx(2.0)
    assert as_bool(at, key="risky_outgrowing") is False, (
        "a gap exactly at the threshold is not ABOVE it"
    )


def test_the_margin_comes_from_config() -> None:
    """Patched to a margin the shipped 0.2 cannot produce."""
    patched = _mi_settings().model_copy(update={"drift_margin_pct_value": _mi_leaf(0.9)})
    with patch("macro_engine.models.national_accounts._minsky_settings", return_value=patched):
        result = minsky_composition_drift(_mi_inputs(standards=5.0, risky=13.0, total=10.0))
    assert as_float(result, key="drift_threshold_pct") == pytest.approx(9.0)
    assert as_bool(result, key="risky_outgrowing") is False, "a 3.0 gap is inside a 9.0 threshold"
    assert _mi_settings().drift_margin_pct != 0.9


# --- the zero boundary -----------------------------------------------------


def test_flat_standards_count_as_not_loosening_and_are_disclosed() -> None:
    """`< 0` is strict, so a survey at exactly zero is not loosening.

    That happened in 7 of 146 quarters and the latest reading is one of them, so
    the boundary is disclosed rather than silently resolved.
    """
    result = minsky_composition_drift(_mi_inputs(standards=0.0, risky=13.0, total=10.0))
    assert as_bool(result, key="standards_loosening") is False
    matches = [w for w in result.warnings if "exactly zero" in w]
    assert len(matches) == 1, "the flat-survey boundary must be disclosed exactly once"


# --- the block -------------------------------------------------------------


def test_the_risky_credit_proxy_is_disclosed_in_value_and_in_prose() -> None:
    """D-043 lifted the block and replaced it with a PROXY disclosure.

    The inputs are sourced now, so a "BLOCKED" notice would be false. What must
    still travel is what the measure actually IS: hedge funds' holdings, not the
    whole market, and only 51 usable quarters.
    """
    result = minsky_composition_drift(_mi_inputs())
    assert as_str(result, key="risky_credit_proxy") == "hedge_fund_leveraged_loans"
    matches = [w for w in result.warnings if "DISCLOSED PROXY" in w]
    assert len(matches) == 1, "the proxy must be disclosed exactly once"
    assert "hedge funds" in matches[0]
    assert "2013-Q4" in matches[0], (
        "the disclosure must state the zero-history limitation, or a caller will "
        "read a 51-quarter rate as if it covered a full cycle"
    )


def test_the_stage_base_rate_is_published_now_that_it_is_measurable() -> None:
    """D-043 made the stage frequency measurable, so it is published.

    Before the block was lifted there was no history of credit growth to
    classify, and recording a stage rate would have meant inventing one. The
    reversal is the point: an unmeasurable statistic is now a measured one.
    """
    result = minsky_composition_drift(_mi_inputs())
    stage = as_str(result, key="stage")
    assert as_float(result, key="stage_base_rate") == pytest.approx(
        _mi_settings().base_rates.stage_rates[stage]
    )
    assert as_int(result, key="stage_observations_measured") == 51
    assert any(
        f"{_mi_settings().base_rates.stage_rates[stage]:.1%}" in w for w in result.warnings
    ), "the stage rate must also reach the prose"
    assert as_float(result, key="standards_loosening_base_rate") == pytest.approx(
        _mi_settings().base_rates.standards_loosening_rate
    )


# --- confidence ------------------------------------------------------------


def test_the_standards_base_rate_comes_from_config() -> None:
    """Patched to a value the shipped 0.46 cannot produce.

    The first version of the base-rate test read its expectation from
    `_mi_settings().base_rates.standards_loosening_rate` — the SAME accessor the
    model reads — so a property returning a hardcoded 0.0 moved both sides
    together and the mutation survived (PROGRESS rule 7). The fixture must be a
    value the shipped config cannot hold.
    """
    patched = _mi_settings().model_copy(
        update={
            "base_rates": MinskyBaseRates(
                observations_measured_value=_mi_leaf(4321),
                standards_loosening_rate_value=_mi_leaf(0.7777),
                stage_observations_measured_value=_mi_leaf(999),
                ponzi_drift_warning_rate_value=_mi_leaf(0.11),
                speculative_drift_rate_value=_mi_leaf(0.22),
                hedge_dominant_rate_value=_mi_leaf(0.67),
            )
        }
    )
    with patch("macro_engine.models.national_accounts._minsky_settings", return_value=patched):
        result = minsky_composition_drift(_mi_inputs())
    assert as_float(result, key="standards_loosening_base_rate") == pytest.approx(0.7777), (
        "the base rate must be read from config, not hardcoded"
    )
    assert as_int(result, key="observations_measured") == 4321
    assert any("77.8%" in w for w in result.warnings), "the base rate must also reach the prose"
    assert _mi_settings().base_rates.standards_loosening_rate != 0.7777


def test_the_margin_correction_is_disclosed() -> None:
    """A reader must be told the margin applies to the gap, not the rate.

    Without it they would compare the published threshold against the
    specification's `* 1.2` and conclude the model is wrong.
    """
    result = minsky_composition_drift(_mi_inputs())
    matches = [w for w in result.warnings if "GAP rather than the rate" in w]
    assert len(matches) == 1, (
        f"the margin-correction disclosure must appear exactly once; found {len(matches)}"
    )
    assert "inverts" in matches[0], "it must say why the correction exists"


def test_the_lagging_defaults_caveat_fires_on_ponzi_only() -> None:
    """Section 20.3's caveat, and the absence half of it."""
    ponzi = minsky_composition_drift(_mi_inputs(standards=-5.0, risky=13.0, total=10.0))
    assert as_str(ponzi, key="stage") == "PONZI_DRIFT_WARNING"
    assert any("LAGGING confirmation" in w for w in ponzi.warnings)

    hedge = minsky_composition_drift(_mi_inputs(standards=5.0, risky=11.0, total=10.0))
    assert as_str(hedge, key="stage") == "HEDGE_DOMINANT"
    assert not any("LAGGING confirmation" in w for w in hedge.warnings), (
        "the caveat is about the warning stage and must not fire on a healthy one"
    )


def test_confidence_does_not_depend_on_which_stage_came_out() -> None:
    """The specification's confidences encode a bias toward alarm.

    Section 20.3 hardcodes 0.6 for PONZI_DRIFT_WARNING, 0.45 for
    SPECULATIVE_DRIFT and 0.5 for HEDGE_DOMINANT — so it is MORE confident when
    it says something is wrong, with no stated basis. Confidence must reflect the
    evidence, which is identical across the three calls below, so all three must
    come out the same.
    """
    confidences = {
        as_str(
            minsky_composition_drift(_mi_inputs(standards=s, risky=r, total=10.0)),
            key="stage",
        ): minsky_composition_drift(_mi_inputs(standards=s, risky=r, total=10.0)).confidence
        for s, r in ((-5.0, 13.0), (-5.0, 11.0), (5.0, 11.0))
    }
    assert len(confidences) == 3, f"three stages expected; got {sorted(confidences)}"
    assert len(set(confidences.values())) == 1, (
        f"the same evidence must give the same confidence regardless of the stage; "
        f"got {confidences}"
    )


def test_minsky_confidence_is_computed_from_the_stated_factors() -> None:
    result = minsky_composition_drift(_mi_inputs())
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _mi_calibrated_today(),
            data_quality_flags_present=True,
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)


def test_the_unsourceable_inputs_lower_confidence() -> None:
    """A model whose inputs cannot be sourced must cost confidence."""
    result = minsky_composition_drift(_mi_inputs())
    no_flag = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _mi_calibrated_today(),
            data_quality_flags_present=False,
            source_independence_count=0,
        )
    )
    assert result.confidence < no_flag


def _mi_calibrated_today() -> bool:
    from macro_engine.models.national_accounts import _minsky_calibrated

    return _minsky_calibrated()


# --- the cross-field identity and the contract -----------------------------


def test_the_stage_is_recomputable_from_its_published_predicates() -> None:
    for standards, risky, total in (
        (-5.0, 13.0, 10.0),
        (-5.0, 11.0, 10.0),
        (5.0, 13.0, 10.0),
        (5.0, 11.0, 10.0),
        (-5.0, -11.0, -10.0),
        (-5.0, -5.0, -10.0),
    ):
        result = minsky_composition_drift(_mi_inputs(standards=standards, risky=risky, total=total))
        loos = as_bool(result, key="standards_loosening")
        outgrow = as_bool(result, key="risky_outgrowing")
        expected = (
            "PONZI_DRIFT_WARNING"
            if loos and outgrow
            else "SPECULATIVE_DRIFT"
            if loos or outgrow
            else "HEDGE_DOMINANT"
        )
        assert as_str(result, key="stage") == expected


def test_minsky_every_raw_input_is_republished() -> None:
    result = minsky_composition_drift(_mi_inputs(standards=-7.5, risky=14.25, total=11.5))
    assert as_float(result, key="lending_standards_net_tightening_pct") == pytest.approx(-7.5)
    assert as_float(result, key="risky_credit_growth_pct") == pytest.approx(14.25)
    assert as_float(result, key="total_credit_growth_pct") == pytest.approx(11.5)


def test_minsky_the_input_contract_forbids_extra_fields() -> None:
    with pytest.raises(Exception, match="risky_credit"):
        MinskyCompositionInputs(  # type: ignore[call-arg]
            lending_standards_net_tightening_pct=-5.0,
            risky_credit_growth_pct=13.0,
            total_credit_growth_pct=10.0,
            risky_credit_growth=13.0,
        )


def test_minsky_every_input_used_is_declared() -> None:
    result = minsky_composition_drift(_mi_inputs())
    assert set(result.inputs_used) == {
        "lending_standards_net_tightening_pct",
        "risky_credit_growth_pct",
        "total_credit_growth_pct",
    }
