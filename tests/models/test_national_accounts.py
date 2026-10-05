"""Module 3 / 20.3 / 20.5 tests — national accounts, index numbers, policy mix, Minsky.

Written fresh for this review campaign. Every expected value is hand-computed
from the formula and the config, then asserted as a literal — never read back
out of the function under test.

Config in force, quoted so the arithmetic below is checkable by hand:

    labor.openings_ratio.very_tight_threshold = 1.5
    labor.openings_ratio.tight_threshold      = 1.0
    labor.openings_ratio.balanced_threshold   = 0.7
    policy_mix.fiscal_deficit_avg             = 4.5
    policy_mix.deficit_mismatch_tolerance     = 0.5
    policy_mix.quadrant_base_rates            = {MAX_STIMULUS: 0.22807,
                                                 MIXED_FISCAL_LOOSE_MONETARY_TIGHT: 0.31579,
                                                 MIXED_FISCAL_TIGHT_MONETARY_LOOSE: 0.19298,
                                                 MAX_RESTRAINT: 0.26316}
    minsky.drift_margin_pct                   = 0.2
    confidence                                = base 0.70, dq 0.25, heuristic 0.20,
                                                unobservable 0.20, floor 0.05, ceiling 0.95

Confidence, hand-derived
------------------------
    savings_investment_identity   ConfidenceInputs()                  -> 0.70
    quantity_theory               heuristic only                       -> 0.50
    laspeyres / paasche / fisher  ConfidenceInputs()                  -> 0.70
    gdp_deflator                  ConfidenceInputs()                  -> 0.70
    openings_to_unemployed        ConfidenceInputs()                  -> 0.70
    policy_mix_classifier         heuristic (uncalibrated leaf) + unobservable -> 0.30
    minsky_composition_drift      heuristic + data-quality flag         -> 0.25

The index-number arithmetic
---------------------------
    base  prices {A:1.0, B:2.0}  quantities {A:10, B:5}
    curr  prices {A:3.0, B:2.5}  quantities {A:4,  B:8}   (substituted AWAY from A)

    base basket cost            = 1.0*10 + 2.0*5   = 20.0
    Laspeyres numerator         = 3.0*10 + 2.5*5   = 42.5   -> L = 212.5
    Paasche numerator           = 3.0*4  + 2.5*8   = 32.0
    Paasche denominator         = 1.0*4  + 2.0*8   = 20.0   -> P = 160.0
    Fisher = sqrt(212.5 * 160.0) = sqrt(34000)     = 184.390889...

    L (212.5) > F (184.39) > P (160.0): the substitution bias is visible, which
    is the whole reason the Fisher index exists.
"""

from __future__ import annotations

import math

import pytest

from macro_engine.config import get_settings
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

_S = get_settings()

# The shared two-item basket, chosen so L != P (see the module docstring).
_BASE_PRICES = {"A": 1.0, "B": 2.0}
_BASE_QTY = {"A": 10.0, "B": 5.0}
_CUR_PRICES = {"A": 3.0, "B": 2.5}
_CUR_QTY = {"A": 4.0, "B": 8.0}


def _basket(**over):
    kw = dict(
        base_prices=dict(_BASE_PRICES),
        base_quantities=dict(_BASE_QTY),
        current_prices=dict(_CUR_PRICES),
        current_quantities=dict(_CUR_QTY),
    )
    kw.update(over)
    return IndexNumberInputs(**kw)


def test_config_values_this_file_hand_computed_against():
    """Pin the leaves the arithmetic depends on. A failure here means this file
    is stale, not that the model is wrong — naming that distinction stops a
    recalibration from being read as a defect."""
    assert _S.scalar("labor.openings_ratio.very_tight_threshold") == 1.5
    assert _S.scalar("labor.openings_ratio.tight_threshold") == 1.0
    assert _S.scalar("labor.openings_ratio.balanced_threshold") == 0.7
    assert _S.policy_mix.fiscal_deficit_avg == 4.5
    assert _S.policy_mix.deficit_mismatch_tolerance == 0.5
    assert _S.minsky.drift_margin_pct == 0.2


# --------------------------------------------------------------------------
# savings_investment_identity — an accounting identity, not a forecast
# --------------------------------------------------------------------------


def test_sectoral_balances_identity_hand_computed():
    """S=18, I=21, T=17, G=24 (same unit).

    private = 18 - 21 = -3
    fiscal  = 17 - 24 = -7
    implied CA = -3 + -7 = -10  -> deficit
    """
    r = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=18.0,
            private_investment=21.0,
            tax_revenue=17.0,
            government_spending=24.0,
        )
    )
    assert r.value == {
        "private_balance": -3.0,
        "fiscal_balance": -7.0,
        "implied_current_account": -10.0,
    }
    assert "deficit" in r.interpretation


def test_identity_holds_for_a_surplus_and_for_exact_balance():
    """+2 and 0 must both be described correctly, and the components must sum."""
    surplus = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=25.0,
            private_investment=20.0,
            tax_revenue=22.0,
            government_spending=19.0,
        )
    )
    assert surplus.value["implied_current_account"] == 8.0
    assert "surplus" in surplus.interpretation

    balanced = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=20.0,
            private_investment=22.0,
            tax_revenue=20.0,
            government_spending=18.0,
        )
    )
    assert balanced.value["implied_current_account"] == 0.0
    assert "balanced" in balanced.interpretation


def test_identity_components_always_sum_to_the_current_account():
    """The D-009 cross-field identity: a reader must be able to recompute the
    total from the two published components."""
    for s, i, t, g in [(18.0, 21.0, 17.0, 24.0), (30.0, 10.0, 5.0, 40.0), (1.0, 1.0, 1.0, 1.0)]:
        r = savings_investment_identity(
            SavingsInvestmentInputs(
                private_saving=s, private_investment=i, tax_revenue=t, government_spending=g
            )
        )
        v = r.value
        assert v["private_balance"] + v["fiscal_balance"] == v["implied_current_account"]


def test_identity_confidence_is_the_unpenalised_base():
    """Exact arithmetic over four observed flows -> no penalty -> 0.70."""
    r = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=18.0, private_investment=21.0, tax_revenue=17.0, government_spending=24.0
        )
    )
    assert r.confidence == 0.70


def test_identity_warns_about_unit_mixing_unconditionally():
    """The identity is homogeneous, so a unit mismatch still balances — which is
    why the caveat is a property of the form and is always present."""
    r = savings_investment_identity(
        SavingsInvestmentInputs(
            private_saving=18.0, private_investment=21.0, tax_revenue=17.0, government_spending=24.0
        )
    )
    assert any("one unit" in w for w in r.warnings)


# --------------------------------------------------------------------------
# quantity_theory_implied_inflation — a diagnostic, not a forecast
# --------------------------------------------------------------------------


def test_quantity_theory_arithmetic_hand_computed():
    """%dP ~= %dM + %dV - %dY.  10 + (-6) - 2 = 2."""
    r = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=10.0,
            velocity_change_pct=-6.0,
            real_output_growth_pct=2.0,
        )
    )
    assert r.value == 2.0


def test_quantity_theory_the_qe_case_money_growth_with_collapsing_velocity():
    """The 2009-2015 episode in numbers: M up hard, V down hard, P barely moves.

    %dM=25, %dV=-22, %dY=2 -> 25 - 22 - 2 = 1. The naive "money printing"
    reading would have said +23.
    """
    r = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=25.0,
            velocity_change_pct=-22.0,
            real_output_growth_pct=2.0,
        )
    )
    assert r.value == 1.0


def test_quantity_theory_confidence_carries_the_heuristic_penalty():
    """It is explicitly a heuristic diagnostic: 0.70 - 0.20 = 0.50."""
    r = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=10.0, velocity_change_pct=-6.0, real_output_growth_pct=2.0
        )
    )
    assert r.confidence == 0.50


def test_quantity_theory_warning_names_velocity_instability():
    """The warning IS the substance here — the module says so."""
    r = quantity_theory_implied_inflation(
        QuantityTheoryInputs(
            money_supply_growth_pct=10.0, velocity_change_pct=-6.0, real_output_growth_pct=2.0
        )
    )
    w = " ".join(r.warnings)
    assert "DIAGNOSTIC" in w
    assert "Velocity" in w


# --------------------------------------------------------------------------
# Index numbers — hand-computed, plus the substitution-bias ordering
# --------------------------------------------------------------------------


def test_laspeyres_index_hand_computed():
    """L = SUM[p_t q_0] / SUM[p_0 q_0] * 100 = 42.5 / 20.0 * 100 = 212.5."""
    r = laspeyres_index(_basket())
    assert r.value == 212.5


def test_paasche_index_hand_computed():
    """P = SUM[p_t q_t] / SUM[p_0 q_t] * 100 = 32.0 / 20.0 * 100 = 160.0."""
    r = paasche_index(_basket())
    assert r.value == 160.0


def test_fisher_index_hand_computed_and_between_the_two():
    """F = sqrt(212.5 * 160.0) = sqrt(34000) = 184.390889..."""
    r = fisher_index(FisherIndexInputs(laspeyres=212.5, paasche=160.0))
    assert r.value == round(math.sqrt(34000.0), 4)
    assert math.isclose(r.value, 184.3909, abs_tol=1e-4)


def test_laspeyres_ge_fisher_ge_paasche_for_a_substituting_basket():
    """The bias ordering, asserted as an inequality rather than a shape.

    This is the module's stated reason for computing all three: Laspeyres holds
    the old basket (upward bias), Paasche already assumes the substitution
    (downward bias), and Fisher sits between.
    """
    l = laspeyres_index(_basket()).value
    p = paasche_index(_basket()).value
    f = fisher_index(FisherIndexInputs(laspeyres=l, paasche=p)).value
    assert l > f > p, (l, f, p)


def test_no_substitution_makes_all_three_indices_agree():
    """When quantities do not move, L == P == F: the bias is zero.

    Hand: base {A:1,B:2} q {A:10,B:5}; current {A:3,B:4} q {A:10,B:5}
        base cost = 20, L numerator = 3*10+4*5 = 50 -> L = 250
        P numerator = 50, P denominator = 20 -> P = 250
        F = sqrt(250*250) = 250
    """
    same_qty = _basket(current_prices={"A": 3.0, "B": 4.0}, current_quantities={"A": 10.0, "B": 5.0})
    l = laspeyres_index(same_qty).value
    p = paasche_index(same_qty).value
    f = fisher_index(FisherIndexInputs(laspeyres=l, paasche=p)).value
    assert (l, p, f) == (250.0, 250.0, 250.0)


def test_index_functions_confidence_is_the_unpenalised_base():
    """Exact arithmetic on supplied vectors -> 0.70, no penalty."""
    assert laspeyres_index(_basket()).confidence == 0.70
    assert paasche_index(_basket()).confidence == 0.70
    assert fisher_index(FisherIndexInputs(laspeyres=212.5, paasche=160.0)).confidence == 0.70


def test_fisher_requires_positive_inputs():
    """gt=0.0 on both fields: a zero or negative index has no geometric mean."""
    with pytest.raises(ValueError):
        FisherIndexInputs(laspeyres=0.0, paasche=100.0)
    with pytest.raises(ValueError):
        FisherIndexInputs(laspeyres=100.0, paasche=-1.0)


# --------------------------------------------------------------------------
# F-NA-001 — cross-period basket alignment
# --------------------------------------------------------------------------


def test_laspeyres_refuses_a_current_price_missing_a_base_item():
    """Before the fix this was a bare `KeyError: 'B'` — a dict-key error, not a
    statement about the baskets."""
    with pytest.raises(ValueError) as exc:
        laspeyres_index(
            _basket(current_prices={"A": 3.0}, current_quantities={"A": 10.0})
        )
    msg = str(exc.value)
    assert "different item sets" in msg
    assert "only in base" in msg


def test_laspeyres_refuses_a_current_price_with_an_extra_item():
    """THE SILENT CASE. Before the fix this returned 250.0 with item C simply
    dropped from the sum — a published number from a basket the caller did not
    supply. This is the failure the module's own docstring says must not happen.
    """
    with pytest.raises(ValueError) as exc:
        laspeyres_index(
            _basket(
                current_prices={"A": 3.0, "B": 4.0, "C": 9.0},
                current_quantities={"A": 10.0, "B": 5.0, "C": 1.0},
            )
        )
    msg = str(exc.value)
    assert "different item sets" in msg
    assert "only in current" in msg
    assert "C" in msg


def test_paasche_refuses_a_base_price_missing_a_current_item():
    """Mirror case: Paasche iterates current_prices and indexes base_prices."""
    with pytest.raises(ValueError) as exc:
        paasche_index(
            _basket(base_prices={"A": 1.0}, base_quantities={"A": 10.0})
        )
    assert "different item sets" in str(exc.value)


def test_aligned_baskets_still_compute():
    """The guard must not reject a legitimate call."""
    assert laspeyres_index(_basket()).value == 212.5
    assert paasche_index(_basket()).value == 160.0


def test_within_period_mismatch_is_still_caught():
    """The pre-existing check must not have been weakened: prices and quantities
    within one period must still describe the same items."""
    with pytest.raises(ValueError) as exc:
        laspeyres_index(_basket(base_quantities={"A": 10.0, "B": 5.0, "Z": 1.0}))
    assert "absent from prices" in str(exc.value)


def test_empty_baskets_are_refused():
    with pytest.raises(ValueError):
        laspeyres_index(_basket(base_prices={}, base_quantities={}))
    with pytest.raises(ValueError):
        paasche_index(_basket(current_prices={}, current_quantities={}))


# --------------------------------------------------------------------------
# gdp_deflator — bare-float signature, so the non-finite guard is explicit
# --------------------------------------------------------------------------


def test_gdp_deflator_hand_computed():
    """nominal / real * 100.  110 / 100 * 100 = 110.0;  25000 / 20000 * 100 = 125.0."""
    assert gdp_deflator(110.0, 100.0).value == 110.0
    assert gdp_deflator(25000.0, 20000.0).value == 125.0


def test_gdp_deflator_refuses_zero_real_gdp():
    with pytest.raises(ValueError):
        gdp_deflator(110.0, 0.0)


@pytest.mark.parametrize(
    ("nominal", "real"),
    [
        (float("nan"), 100.0),
        (100.0, float("nan")),
        (float("inf"), 100.0),
        (100.0, float("inf")),
        (float("-inf"), 100.0),
        (100.0, float("-inf")),
    ],
)
def test_gdp_deflator_refuses_non_finite_inputs(nominal, real):
    """F-NA-002. Before the fix: (nan, 100) -> value=nan; (100, inf) -> 0.0.

    The second is the dangerous one — 0.0 is a plausible-looking deflator
    derived from an infinite real GDP, and every downstream comparison would
    accept it as a real number.
    """
    with pytest.raises(ValueError) as exc:
        gdp_deflator(nominal, real)
    assert "non-finite" in str(exc.value)


def test_gdp_deflator_error_names_the_offending_argument():
    """The guard reuses FiniteInputs' formatter, so the message names the
    argument rather than merely reporting that something was wrong."""
    with pytest.raises(ValueError) as exc:
        gdp_deflator(100.0, float("nan"))
    assert "real_gdp" in str(exc.value)


def test_gdp_deflator_confidence_is_the_unpenalised_base():
    assert gdp_deflator(110.0, 100.0).confidence == 0.70


def test_gdp_deflator_warns_it_is_not_comparable_to_cpi_as_a_level():
    r = gdp_deflator(110.0, 100.0)
    assert any("Not comparable to CPI" in w for w in r.warnings)


# --------------------------------------------------------------------------
# openings_to_unemployed_ratio — band boundaries pinned
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("openings", "unemployed", "ratio", "band"),
    [
        (9000.0, 5000.0, 1.8, "VERY_TIGHT"),
        (7500.0, 5000.0, 1.5, "TIGHT"),        # exactly the very-tight threshold
        (6000.0, 5000.0, 1.2, "TIGHT"),
        (5000.0, 5000.0, 1.0, "BALANCED"),     # exactly the tight threshold
        (4000.0, 5000.0, 0.8, "BALANCED"),
        (3500.0, 5000.0, 0.7, "SLACK"),        # exactly the balanced threshold
        (3000.0, 5000.0, 0.6, "SLACK"),
    ],
)
def test_openings_ratio_bands_and_their_boundaries(openings, unemployed, ratio, band):
    """The comparisons are strict `>`, so an exact threshold falls to the LOWER
    band. Without pinning that, a `<` -> `<=` change would be unobservable."""
    r = openings_to_unemployed_ratio(
        OpeningsToUnemployedInputs(
            job_openings_thousands=openings, unemployed_persons_thousands=unemployed
        )
    )
    assert r.value == round(ratio, 3)
    assert band in r.interpretation


def test_openings_ratio_confidence_is_the_unpenalised_base():
    r = openings_to_unemployed_ratio(
        OpeningsToUnemployedInputs(
            job_openings_thousands=6000.0, unemployed_persons_thousands=5000.0
        )
    )
    assert r.confidence == 0.70


def test_openings_ratio_refuses_zero_unemployed():
    """The denominator is gt=0: zero unemployed persons is not observable."""
    with pytest.raises(ValueError):
        OpeningsToUnemployedInputs(
            job_openings_thousands=6000.0, unemployed_persons_thousands=0.0
        )


# --------------------------------------------------------------------------
# policy_mix_classifier — the 2x2, and the sign trap
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("deficit", "rate", "quadrant", "mixed"),
    [
        (6.0, 3.0, "MAX_STIMULUS", False),                            # loose & loose
        (6.0, 6.0, "MIXED_FISCAL_LOOSE_MONETARY_TIGHT", True),        # loose & tight
        (3.0, 3.0, "MIXED_FISCAL_TIGHT_MONETARY_LOOSE", True),        # tight & loose
        (3.0, 6.0, "MAX_RESTRAINT", False),                           # tight & tight
    ],
)
def test_policy_mix_quadrants_hand_computed(deficit, rate, quadrant, mixed):
    """avg deficit 4.5, so `fiscal_loose` is `deficit > 4.5`; `monetary_loose`
    is `policy_rate < taylor_implied_rate` (here 5.0)."""
    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=deficit,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=rate,
            taylor_implied_rate=5.0,
        )
    )
    assert r.value["quadrant"] == quadrant
    assert r.value["mixed"] is mixed


def test_policy_mix_publishes_both_predicates_so_the_quadrant_is_recomputable():
    """The D-009 cross-field identity: the verdict must be reproducible from the
    output, not trusted."""
    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=6.0,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=3.0,
            taylor_implied_rate=5.0,
        )
    )
    v = r.value
    assert v["fiscal_loose"] is True
    assert v["monetary_loose"] is True
    assert v["quadrant"] == "MAX_STIMULUS"
    assert v["mixed"] is (v["fiscal_loose"] != v["monetary_loose"])


def test_policy_mix_boundary_is_strict_so_equality_is_not_loose():
    """`deficit > average` and `rate < taylor`: equality is NOT loose on either."""
    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=4.5,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=5.0,
            taylor_implied_rate=5.0,
        )
    )
    assert r.value["fiscal_loose"] is False
    assert r.value["monetary_loose"] is False
    assert r.value["quadrant"] == "MAX_RESTRAINT"


def test_policy_mix_confidence_hand_derived():
    """heuristic (the deficit average is uncalibrated_illustrative) + unobservable
    (the Taylor rate rests on r* and potential GDP): 0.70 - 0.20 - 0.20 = 0.30."""
    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=6.0,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=3.0,
            taylor_implied_rate=5.0,
        )
    )
    assert r.confidence == 0.30


def test_policy_mix_warns_on_a_negative_deficit_which_is_the_sign_trap():
    """FRED FYFSGDA188S is negative for a deficit; supplying it raw inverts every
    comparison, so the model names it at the point of use."""
    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=-5.77,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=3.0,
            taylor_implied_rate=5.0,
        )
    )
    assert any("POSITIVE for a deficit" in w for w in r.warnings)


def test_policy_mix_warns_when_the_supplied_average_disagrees_with_config():
    """Tolerance 0.5: 4.5 vs 3.0 differs by 1.5 -> warn."""
    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=6.0,
            fiscal_deficit_avg_pct_gdp=3.0,
            policy_rate=3.0,
            taylor_implied_rate=5.0,
        )
    )
    assert any("differs from the configured expectation" in w for w in r.warnings)


def test_policy_mix_no_average_mismatch_warning_within_tolerance():
    """4.5 vs 4.8 differs by 0.3 <= 0.5 -> no warning."""
    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=6.0,
            fiscal_deficit_avg_pct_gdp=4.8,
            policy_rate=3.0,
            taylor_implied_rate=5.0,
        )
    )
    assert not any("differs from the configured expectation" in w for w in r.warnings)


def test_policy_mix_mixed_share_is_derived_from_config_not_hardcoded():
    """F-NA-003. The warning used to hardcode "50.9%".

    That figure is exactly the sum of the two MIXED quadrant rates
    (0.31579 + 0.19298 = 0.50877 -> 50.9%), so it was a config-derived number
    written as a literal — it would have gone stale on any recalibration while
    still reading as a measured figure.
    """
    q = _S.policy_mix.quadrant_base_rates
    expected = q["MIXED_FISCAL_LOOSE_MONETARY_TIGHT"] + q["MIXED_FISCAL_TIGHT_MONETARY_LOOSE"]
    assert f"{expected:.1%}" == "50.9%"

    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=6.0,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=6.0,
            taylor_implied_rate=5.0,
        )
    )
    assert r.value["quadrant"] == "MIXED_FISCAL_LOOSE_MONETARY_TIGHT"
    assert any(f"{expected:.1%}" in w for w in r.warnings)


def test_policy_mix_mixed_share_follows_config_and_is_not_a_literal(monkeypatch):
    """F-NA-003 proved by PATCHING the config.

    Asserting the warning contains "50.9%" would pass against the old hardcoded
    literal too, because the literal and the derived value happen to agree. The
    only test that distinguishes them moves the config and checks the warning
    moves with it.
    """
    real = _S.policy_mix

    class _Stub:
        def __init__(self, rates):
            self.quadrant_base_rates = rates
            self.base_rates = real.base_rates
            self.fiscal_deficit_avg = real.fiscal_deficit_avg
            self.deficit_mismatch_tolerance = real.deficit_mismatch_tolerance

    rates = dict(real.quadrant_base_rates)
    rates["MIXED_FISCAL_LOOSE_MONETARY_TIGHT"] = 0.40
    rates["MIXED_FISCAL_TIGHT_MONETARY_LOOSE"] = 0.10

    monkeypatch.setattr(
        "macro_engine.models.national_accounts._policy_mix_settings", lambda: _Stub(rates)
    )

    r = policy_mix_classifier(
        PolicyMixInputs(
            fiscal_deficit_pct_gdp=6.0,
            fiscal_deficit_avg_pct_gdp=4.5,
            policy_rate=6.0,
            taylor_implied_rate=5.0,
        )
    )
    text = " ".join(r.warnings)
    assert r.value["quadrant"] == "MIXED_FISCAL_LOOSE_MONETARY_TIGHT"
    assert "50.0%" in text, "the mixed share must be recomputed from config"
    assert "50.9%" not in text, "the old hardcoded literal must not survive"


def test_policy_mix_every_warning_quotes_the_quadrant_base_rate():
    """D-029: a categorical verdict must publish its own measured frequency."""
    for deficit, rate in [(6.0, 3.0), (6.0, 6.0), (3.0, 3.0), (3.0, 6.0)]:
        r = policy_mix_classifier(
            PolicyMixInputs(
                fiscal_deficit_pct_gdp=deficit,
                fiscal_deficit_avg_pct_gdp=4.5,
                policy_rate=rate,
                taylor_implied_rate=5.0,
            )
        )
        rate_here = _S.policy_mix.quadrant_base_rates[r.value["quadrant"]]
        assert any(f"{rate_here:.1%}" in w for w in r.warnings), r.value["quadrant"]


# --------------------------------------------------------------------------
# minsky_composition_drift — the sign-safe margin, and the blocked inputs
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("standards", "risky", "total", "stage"),
    [
        (-5.0, 10.0, 5.0, "PONZI_DRIFT_WARNING"),   # loosening AND outgrowing
        (5.0, 10.0, 5.0, "SPECULATIVE_DRIFT"),      # outgrowing only
        (-5.0, 4.0, 5.0, "SPECULATIVE_DRIFT"),      # loosening only
        (5.0, 4.0, 5.0, "HEDGE_DOMINANT"),          # neither
    ],
)
def test_minsky_stages_hand_computed(standards, risky, total, stage):
    """margin 0.2; gap = risky - total; threshold = 0.2 * |total|; flag is gap > threshold.

    (10-5)=5 > 0.2*5=1  -> outgrowing.   (4-5)=-1 > 1 is False -> not outgrowing.
    """
    r = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=standards,
            risky_credit_growth_pct=risky,
            total_credit_growth_pct=total,
        )
    )
    assert r.value["stage"] == stage


def test_minsky_negative_total_growth_does_not_invert_the_flag():
    """THE CORRECTION. The spec's `risky > total * 1.2` inverts when total < 0:
    risky -11% vs total -10% gives -11 > -12 -> a false "outgrowing" verdict on
    the fastest DE-RISKING. The margin is applied to the GAP instead.

    Hand: gap = -11 - (-10) = -1; threshold = 0.2 * 10 = 2.0; -1 > 2.0 is False
    -> not outgrowing, so with standards tightening the stage is HEDGE_DOMINANT.
    """
    r = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=5.0,
            risky_credit_growth_pct=-11.0,
            total_credit_growth_pct=-10.0,
        )
    )
    assert r.value["risky_outgrowing"] is False
    assert r.value["stage"] == "HEDGE_DOMINANT"
    assert r.value["growth_gap_pct"] == -1.0
    assert r.value["drift_threshold_pct"] == 2.0


def test_minsky_margin_is_equivalent_to_the_specs_form_when_total_is_positive():
    """The docstring's claim: `(risky - total) > margin*|total|` is identical to
    `risky > total * 1.2` whenever total > 0.

    Hand: total=5, margin=0.2 -> threshold 1.0, so risky must exceed 6.0.
    Spec form: risky > 5 * 1.2 = 6.0. Identical.
    """
    boundary_below = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=5.0,
            risky_credit_growth_pct=6.0,
            total_credit_growth_pct=5.0,
        )
    )
    assert boundary_below.value["risky_outgrowing"] is False, "6.0 is not > 6.0"

    boundary_above = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=5.0,
            risky_credit_growth_pct=6.000001,
            total_credit_growth_pct=5.0,
        )
    )
    assert boundary_above.value["risky_outgrowing"] is True


def test_minsky_confidence_hand_derived():
    """heuristic (uncalibrated margin) + data-quality flag (disclosed proxy):
    0.70 - 0.20 - 0.25 = 0.25."""
    r = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=-5.0,
            risky_credit_growth_pct=10.0,
            total_credit_growth_pct=5.0,
        )
    )
    assert r.confidence == 0.25


def test_minsky_confidence_does_not_depend_on_the_stage():
    """The spec hardcoded 0.6/0.45/0.5 BY STAGE, i.e. it was more confident when
    it said something was wrong. Confidence must reflect input quality only."""
    confidences = set()
    for standards, risky, total in [
        (-5.0, 10.0, 5.0),
        (5.0, 10.0, 5.0),
        (5.0, 4.0, 5.0),
    ]:
        r = minsky_composition_drift(
            MinskyCompositionInputs(
                lending_standards_net_tightening_pct=standards,
                risky_credit_growth_pct=risky,
                total_credit_growth_pct=total,
            )
        )
        confidences.add(r.confidence)
    assert confidences == {0.25}


def test_minsky_always_discloses_the_proxy_and_the_block():
    """Two of the three inputs are BLOCKED by Section 21.1 / lifted by D-043 as a
    disclosed proxy. A consumer must be told on every call."""
    r = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=-5.0,
            risky_credit_growth_pct=10.0,
            total_credit_growth_pct=5.0,
        )
    )
    assert r.value["risky_credit_proxy"] == "hedge_fund_leveraged_loans"
    w = " ".join(r.warnings)
    assert "DISCLOSED PROXY" in w


def test_minsky_flat_standards_warn_they_count_as_not_loosening():
    """`< 0.0` is strict, so exactly zero is NOT loosening — and it happened in
    7 of 146 quarters, so the boundary is a convention worth naming."""
    r = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=0.0,
            risky_credit_growth_pct=10.0,
            total_credit_growth_pct=5.0,
        )
    )
    assert r.value["standards_loosening"] is False
    assert any("exactly zero" in w for w in r.warnings)


def test_minsky_ponzi_stage_names_defaults_as_a_lagging_confirmation():
    r = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=-5.0,
            risky_credit_growth_pct=10.0,
            total_credit_growth_pct=5.0,
        )
    )
    assert any("LAGGING confirmation" in w for w in r.warnings)


def test_minsky_publishes_the_predicates_so_the_stage_is_recomputable():
    r = minsky_composition_drift(
        MinskyCompositionInputs(
            lending_standards_net_tightening_pct=-5.0,
            risky_credit_growth_pct=10.0,
            total_credit_growth_pct=5.0,
        )
    )
    v = r.value
    assert v["standards_loosening"] is True
    assert v["risky_outgrowing"] is True
    assert v["stage"] == "PONZI_DRIFT_WARNING"
