"""Hand-verified tests for Module 4 policy rules, the canonical gap, the proxy.

AGENTS.md Section 6.1, Section 22.4, Section 22.5, Section 11.1,
Section 21.2 Steps 4-5.

Section 11.1 mandates three of these by name:

* ``test_taylor_rule_matches_hand_calculation`` — reproducing
  ``r* = 0.5, pi = 3%, target = 2%, output_gap = +1% -> i = 4.5%``
* ``test_policy_rule_ensemble_never_averages``
* (the confidence-comes-from-the-formula check, which Section 11.1 states as a
  cross-cutting requirement rather than a named test)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from macro_engine.config import (
    CalibratedValue,
    QEStanceBaseRates,
    QEStanceSettings,
    get_settings,
)
from macro_engine.models.contracts import ConfidenceInputs, compute_confidence
from macro_engine.models.policy_rules import (
    BalanceSheetInputs,
    FirstDifferenceInputs,
    PolicyRuleResult,
    TaylorRuleInputs,
    balanced_approach_rule,
    canonical_policy_gap,
    derive_market_implied_policy_path,
    first_difference_rule,
    policy_rule_ensemble,
    qe_qt_stance,
    taylor_rule,
)
from tests.helpers import as_bool, as_float, as_int, as_str


def _taylor(
    r_star: float = 0.5,
    pi_current: float = 3.0,
    pi_target: float = 2.0,
    output_gap: float = 1.0,
) -> PolicyRuleResult:
    return taylor_rule(
        TaylorRuleInputs(
            r_star=r_star,
            pi_current=pi_current,
            pi_target=pi_target,
            output_gap=output_gap,
        )
    )


# ---------------------------------------------------------------------------
# Section 11.1 mandated: test_taylor_rule_matches_hand_calculation
# ---------------------------------------------------------------------------


def test_taylor_rule_matches_hand_calculation() -> None:
    """Section 11.1's mandated case, reproduced digit for digit.

    Hand calculation:
        i = r* + pi + 0.5(pi - pi_target) + 0.5(output_gap)
          = 0.5 + 3.0 + 0.5(3.0 - 2.0) + 0.5(1.0)
          = 0.5 + 3.0 + 0.5 + 0.5
          = 4.5
    """
    result = _taylor()
    assert result.value == pytest.approx(4.5)
    assert result.rule_variant == "taylor_1993"
    assert result.model_name == "taylor_rule"


def test_taylor_rule_zero_gaps_prescribes_r_star_plus_inflation() -> None:
    """At target and at potential the rule collapses to the Fisher relation.

    With pi = target and output_gap = 0, i = r* + pi. This is the identity that
    makes the rule interpretable: the neutral nominal rate is the neutral real
    rate plus inflation, and the rule only departs from it when a gap exists.
    """
    result = _taylor(pi_current=2.0, output_gap=0.0)
    assert result.value == pytest.approx(0.5 + 2.0)


def test_taylor_rule_responds_one_for_one_to_r_star() -> None:
    """A 1pp error in r* moves the prescription by exactly 1pp.

    This is why the rule carries the unobservable penalty: the model's largest
    uncertainty passes through undamped.
    """
    low = _taylor(r_star=0.5)
    high = _taylor(r_star=1.5)
    assert isinstance(low.value, int | float)
    assert isinstance(high.value, int | float)
    assert as_float(high) - as_float(low) == pytest.approx(1.0)


def test_taylor_rule_upholds_the_taylor_principle() -> None:
    """Coefficient on inflation must exceed 1 in total for stability.

    Total response to a 1pp inflation move is the direct term (1.0) plus the
    inflation-gap term (0.5), i.e. 1.5. Below 1.0 the real rate FALLS as
    inflation rises, which is destabilising — so this is a genuine constraint
    on the configured coefficients, not a stylistic preference.
    """
    base = _taylor(pi_current=2.0, output_gap=0.0)
    shocked = _taylor(pi_current=3.0, output_gap=0.0)
    assert isinstance(base.value, int | float)
    assert isinstance(shocked.value, int | float)
    assert as_float(shocked) - as_float(base) > 1.0


def test_taylor_rule_reads_pi_target_from_config_when_unset() -> None:
    """The default is the configured FOMC objective, not a hardcoded 2.0."""
    configured = get_settings().policy.pi_target_value
    explicit = taylor_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=3.0, pi_target=configured, output_gap=1.0)
    )
    implicit = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    assert implicit.value == explicit.value


def test_taylor_rule_warns_about_r_star() -> None:
    """Section 21.4 item 13 — the unobservable must be flagged, not assumed."""
    result = _taylor()
    assert any("r* is a model-dependent estimate" in warning for warning in result.warnings)


def test_taylor_rule_confidence_comes_from_the_formula() -> None:
    """Section 22.8: no hardcoded confidence. r* makes this unobservable-dependent."""
    expected = compute_confidence(ConfidenceInputs(depends_on_unobservable=True))
    assert _taylor().confidence == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# Balanced-approach rule
# ---------------------------------------------------------------------------


def test_balanced_approach_doubles_the_output_gap_weighting() -> None:
    """Hand calculation at r*=0.5, pi=3, target=2, gap=+1:
        0.5 + 3.0 + 0.5(1) + 1.0(1) = 5.0
    versus Taylor's 4.5 — the 0.5pp difference is exactly 0.5 x output_gap.
    """
    result = balanced_approach_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=3.0, pi_target=2.0, output_gap=1.0)
    )
    assert result.value == pytest.approx(5.0)
    assert result.rule_variant == "balanced_approach"


def test_balanced_approach_agrees_with_taylor_at_zero_output_gap() -> None:
    """The rules differ ONLY in the output-gap coefficient.

    At a zero gap they must coincide exactly. If they did not, the ensemble
    dispersion would contain a spurious constant component, inflating the noise
    floor and masking real disagreement.
    """
    taylor_result = _taylor(output_gap=0.0)
    balanced_result = balanced_approach_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=3.0, pi_target=2.0, output_gap=0.0)
    )
    assert balanced_result.value == taylor_result.value


def test_balanced_approach_divergence_is_derived_from_the_coefficients() -> None:
    """The stated context must reflect configured coefficients, not literals."""
    result = balanced_approach_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=3.0, pi_target=2.0, output_gap=2.0)
    )
    # coefficient delta (1.0 - 0.5) x output_gap (2.0) = +1.00pp
    # Note the numbers are formatted with %g, so an integral coefficient prints
    # as "1" rather than "1.0". The assertion targets the derived divergence,
    # which is the part that actually depends on config.
    assert "0.5 x output_gap = +1.00pp" in result.context
    assert result.value == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# First-difference (speed-limit) rule
# ---------------------------------------------------------------------------


def test_first_difference_rule_matches_hand_calculation() -> None:
    """Hand calculation:
    delta = 0.5(3.0 - 2.0) + 0.5(0.4) = 0.5 + 0.2 = 0.7
    i     = 4.25 + 0.7 = 4.95  -> 4.95
    """
    result = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.25, pi_current=3.0, pi_target=2.0, output_gap_change=0.4)
    )
    assert result.value == pytest.approx(4.95)
    assert result.rule_variant == "first_difference"


def test_first_difference_rule_is_invariant_to_r_star() -> None:
    """The entire justification for this variant: r* does not appear.

    Since ``FirstDifferenceInputs`` has no ``r_star`` field at all
    (``extra="forbid"``), the invariance is structural rather than merely
    numeric — there is no input through which an r* assumption could enter.
    """
    with pytest.raises(ValueError, match=r"r_star"):
        FirstDifferenceInputs.model_validate(
            {
                "i_prev": 4.25,
                "pi_current": 3.0,
                "pi_target": 2.0,
                "output_gap_change": 0.4,
                "r_star": 0.5,
            }
        )


def test_first_difference_rule_confidence_exceeds_the_level_based_rules() -> None:
    """The higher confidence is EARNED by construction, not asserted.

    The speed-limit rule carries no ``depends_on_unobservable`` penalty, so
    ``compute_confidence()`` returns a higher figure. If both were hardcoded the
    ordering would be a claim; because both are computed it is a consequence.
    """
    level_based = _taylor()
    difference_based = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.25, pi_current=3.0, pi_target=2.0, output_gap_change=0.4)
    )
    assert difference_based.confidence > level_based.confidence
    assert difference_based.confidence == pytest.approx(
        compute_confidence(ConfidenceInputs(depends_on_unobservable=False)), abs=1e-9
    )


def test_first_difference_rule_warns_that_it_cannot_detect_a_wrong_level() -> None:
    result = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.25, pi_current=3.0, pi_target=2.0, output_gap_change=0.4)
    )
    assert any("prescribes a CHANGE" in warning for warning in result.warnings)


def test_first_difference_rule_uses_configured_coefficients() -> None:
    """Explicit coefficients must override config; config must be the default."""
    config = get_settings().policy.rules
    assert config.first_difference_alpha_value == pytest.approx(0.5)
    assert config.first_difference_beta_value == pytest.approx(0.5)

    overridden = first_difference_rule(
        FirstDifferenceInputs(
            i_prev=4.0,
            pi_current=3.0,
            pi_target=2.0,
            output_gap_change=1.0,
            alpha=1.0,
            beta=0.0,
        )
    )
    # alpha*(1.0) + beta*(1.0) = 1.0 exactly
    assert overridden.value == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Section 11.1 mandated: test_policy_rule_ensemble_never_averages
# ---------------------------------------------------------------------------


def test_policy_rule_ensemble_never_averages() -> None:
    """Section 11.1's mandated test, and Section 6.1's explicit prohibition.

    The trap this guards against is a mean: the average of {2.0, 2.1, 6.0} is
    3.3666..., a rate no rule prescribed. If the ensemble ever returned that
    figure, the system would be reporting a number whose only justification is
    arithmetic convenience — and it would hide the fact that one rule is
    shouting while two agree.

    So the assertion is two-sided: the mean must NOT appear anywhere in the
    output, AND the dispersion must be reported.
    """
    consensus_a = _taylor(r_star=0.0, pi_current=2.0, pi_target=2.0, output_gap=0.0)
    consensus_b = PolicyRuleResult(
        **{
            **consensus_a.model_dump(),
            "model_name": "balanced_approach_rule",
            "rule_variant": "balanced_approach",
            "value": 2.1,
        }
    )
    outlier = PolicyRuleResult(
        **{
            **consensus_a.model_dump(),
            "model_name": "first_difference_rule",
            "rule_variant": "first_difference",
            "value": 6.0,
        }
    )

    result = policy_rule_ensemble(consensus_a, consensus_b, outlier)
    assert isinstance(result.value, dict)

    values = [2.0, 2.1, 6.0]
    mean = sum(values) / len(values)

    # The mean must not appear as the reported value or inside the payload.
    serialised = str(result.value)
    assert str(result.value.get("rules")) != str(mean)
    assert f"{mean:.4f}" not in serialised

    # The report must be the three rules, their range, and the dispersion.
    assert result.value["rules"] == {
        "taylor": 2.0,
        "balanced": 2.1,
        "first_difference": 6.0,
    }
    assert result.value["range"] == [2.0, 6.0]
    assert result.value["dispersion_pp"] == pytest.approx(4.0)
    assert result.value["dispersion_bp"] == pytest.approx(400.0)


def test_policy_rule_ensemble_classifies_high_dispersion_as_uncertain() -> None:
    """A 4pp spread is 400bp, which exceeds the 100bp band -> UNCERTAIN."""
    base = _taylor(r_star=0.0, pi_current=2.0, pi_target=2.0, output_gap=0.0)
    low = PolicyRuleResult(
        **{
            **base.model_dump(),
            "model_name": "balanced_approach_rule",
            "rule_variant": "balanced_approach",
            "value": 2.0,
        }
    )
    high = PolicyRuleResult(
        **{
            **base.model_dump(),
            "model_name": "first_difference_rule",
            "rule_variant": "first_difference",
            "value": 6.0,
        }
    )
    result = policy_rule_ensemble(base, low, high)
    assert isinstance(result.value, dict)
    assert result.value["agreement"] == "UNCERTAIN"
    assert result.warnings, "a high-dispersion ensemble must carry a warning"


def test_policy_rule_ensemble_classifies_low_dispersion_as_converged() -> None:
    """Under 50bp spread -> CONVERGED, and no warning."""
    base = _taylor(r_star=0.0, pi_current=2.0, pi_target=2.0, output_gap=0.0)
    variants = [
        PolicyRuleResult(
            **{
                **base.model_dump(),
                "model_name": name,
                "rule_variant": variant,
                "value": value,
            }
        )
        for name, variant, value in (
            ("taylor_rule", "taylor_1993", 4.00),
            ("balanced_approach_rule", "balanced_approach", 4.10),
            ("first_difference_rule", "first_difference", 4.20),
        )
    ]
    result = policy_rule_ensemble(*variants)
    assert isinstance(result.value, dict)
    assert result.value["dispersion_bp"] == pytest.approx(20.0)
    assert result.value["agreement"] == "CONVERGED"
    assert result.warnings == []


def test_policy_rule_ensemble_reports_the_middle_band_as_mixed() -> None:
    """Between 50bp and 100bp -> MIXED, with a warning but no false alarm."""
    base = _taylor(r_star=0.0, pi_current=2.0, pi_target=2.0, output_gap=0.0)
    variants = [
        PolicyRuleResult(
            **{**base.model_dump(), "model_name": name, "rule_variant": variant, "value": value}
        )
        for name, variant, value in (
            ("taylor_rule", "taylor_1993", 4.00),
            ("balanced_approach_rule", "balanced_approach", 4.30),
            ("first_difference_rule", "first_difference", 4.80),
        )
    ]
    result = policy_rule_ensemble(*variants)
    assert isinstance(result.value, dict)
    assert result.value["dispersion_bp"] == pytest.approx(80.0)
    assert result.value["agreement"] == "MIXED"


def test_policy_rule_ensemble_compares_bp_against_percent_correctly() -> None:
    """The unit trap: 1pp of dispersion is 100bp, not 1bp.

    If the bands were compared against the percentage figure directly,
    a 1pp spread would read as "1bp", fall under the 50bp convergence band,
    and be reported as agreement. That is a silent factor-of-100 error in the
    one place the system judges whether policy rules agree.
    """
    base = _taylor(r_star=0.0, pi_current=2.0, pi_target=2.0, output_gap=0.0)
    variants = [
        PolicyRuleResult(
            **{**base.model_dump(), "model_name": name, "rule_variant": variant, "value": value}
        )
        for name, variant, value in (
            ("taylor_rule", "taylor_1993", 4.0),
            ("balanced_approach_rule", "balanced_approach", 4.5),
            ("first_difference_rule", "first_difference", 5.0),
        )
    ]
    result = policy_rule_ensemble(*variants)
    assert isinstance(result.value, dict)
    assert result.value["dispersion_pp"] == pytest.approx(1.0)
    assert result.value["dispersion_bp"] == pytest.approx(100.0)
    # 100bp is NOT below the 50bp band, so this must not read as converged.
    assert result.value["agreement"] == "MIXED"


def test_policy_rule_ensemble_confidence_is_the_weakest_input() -> None:
    """A summary cannot be more trustworthy than what it summarises."""
    weak = PolicyRuleResult(**{**_taylor().model_dump(), "confidence": 0.3})
    strong = PolicyRuleResult(**{**_taylor().model_dump(), "confidence": 0.9})
    result = policy_rule_ensemble(_taylor(), weak, strong)
    assert result.confidence == pytest.approx(0.3)


def test_policy_rule_ensemble_rejects_a_non_numeric_rule_value() -> None:
    """A rule whose value is not a rate cannot be dispersed."""
    broken = PolicyRuleResult(**{**_taylor().model_dump(), "value": "not a rate"})
    with pytest.raises(TypeError, match=r"requires numeric rule outputs"):
        policy_rule_ensemble(_taylor(), _taylor(), broken)


# ---------------------------------------------------------------------------
# Section 22.4 — the canonical gap
# ---------------------------------------------------------------------------


def _rule(value: float, variant: str, model_name: str) -> PolicyRuleResult:
    return PolicyRuleResult(
        **{
            **_taylor().model_dump(),
            "model_name": model_name,
            "rule_variant": variant,
            "value": value,
        }
    )


def test_canonical_gap_uses_the_median_not_the_mean() -> None:
    """Section 22.4: median of the three rules, robust to one outlier.

    Hand calculation with values {2.0, 4.0, 6.0} and market 3.0:
        median      = 4.0        (the mean would be 4.0 too — chosen so the
                                  two agree here and the DISPERSION test is
                                  what distinguishes the cases below)
        raw_gap     = 4.0 - 3.0 = +1.0
        dispersion  = 6.0 - 2.0 = 4.0
        is_meaningful = |1.0| > 4.0 -> False
    """
    gap = canonical_policy_gap(
        _rule(2.0, "taylor_1993", "taylor_rule"),
        _rule(4.0, "balanced_approach", "balanced_approach_rule"),
        _rule(6.0, "first_difference", "first_difference_rule"),
        market_implied=3.0,
    )
    assert gap.model_implied_value == pytest.approx(4.0)
    assert gap.raw_gap == pytest.approx(1.0)
    assert gap.dispersion == pytest.approx(4.0)
    assert gap.is_meaningful is False
    assert "WITHIN NOISE FLOOR" in gap.interpretation


def test_canonical_gap_is_robust_to_an_outlier_where_a_mean_is_not() -> None:
    """The median's whole justification, demonstrated.

    With {2.0, 4.0, 20.0} the median is 4.0; the mean would be 8.67. A single
    rule computing a nonsense rate (an unrealistic r* input, say) moves the mean
    by 4.67pp and the median by nothing at all — and it is precisely when one
    rule has gone wrong that the summary must stay stable.
    """
    gap = canonical_policy_gap(
        _rule(2.0, "taylor_1993", "taylor_rule"),
        _rule(4.0, "balanced_approach", "balanced_approach_rule"),
        _rule(20.0, "first_difference", "first_difference_rule"),
        market_implied=3.0,
    )
    assert gap.model_implied_value == pytest.approx(4.0)


def test_canonical_gap_reports_a_meaningful_divergence() -> None:
    """A gap larger than the dispersion IS signal.

    Hand calculation: rules {4.0, 4.5, 5.0}, market 2.0
        median = 4.5, raw_gap = +2.5, dispersion = 1.0
        |2.5| > 1.0 -> meaningful
    """
    gap = canonical_policy_gap(
        _rule(4.0, "taylor_1993", "taylor_rule"),
        _rule(4.5, "balanced_approach", "balanced_approach_rule"),
        _rule(5.0, "first_difference", "first_difference_rule"),
        market_implied=2.0,
    )
    assert gap.raw_gap == pytest.approx(2.5)
    assert gap.dispersion == pytest.approx(1.0)
    assert gap.is_meaningful is True
    assert "MEANINGFUL" in gap.interpretation
    assert "above" in gap.interpretation


def test_canonical_gap_sign_is_model_minus_market() -> None:
    """A negative gap means the model prescribes less tightening than priced."""
    gap = canonical_policy_gap(
        _rule(4.0, "taylor_1993", "taylor_rule"),
        _rule(4.5, "balanced_approach", "balanced_approach_rule"),
        _rule(5.0, "first_difference", "first_difference_rule"),
        market_implied=8.0,
    )
    assert gap.raw_gap == pytest.approx(-3.5)
    assert gap.is_meaningful is True
    assert "below" in gap.interpretation


def test_canonical_gap_boundary_is_strictly_greater_than() -> None:
    """Section 22.4 states ``abs(raw_gap) > dispersion`` — strictly greater.

    At exact equality the gap is NOT meaningful. Asserting the boundary
    explicitly matters because ``>=`` would be a plausible-looking
    implementation with the opposite behaviour in the marginal case that
    determines the thesis.
    """
    # rules {4.0, 5.0, 6.0} -> median 5.0, dispersion 2.0, market 3.0 -> gap 2.0
    gap = canonical_policy_gap(
        _rule(4.0, "taylor_1993", "taylor_rule"),
        _rule(5.0, "balanced_approach", "balanced_approach_rule"),
        _rule(6.0, "first_difference", "first_difference_rule"),
        market_implied=3.0,
    )
    assert gap.raw_gap == pytest.approx(2.0)
    assert gap.dispersion == pytest.approx(2.0)
    assert gap.is_meaningful is False


def test_canonical_gap_rejects_a_non_numeric_rule_value() -> None:
    broken = PolicyRuleResult(**{**_taylor().model_dump(), "value": {"oops": True}})
    with pytest.raises(TypeError, match=r"not a rate"):
        canonical_policy_gap(_taylor(), _taylor(), broken, market_implied=3.0)


# ---------------------------------------------------------------------------
# Section 22.5 — the market-implied proxy
# ---------------------------------------------------------------------------


def test_market_implied_adjusts_when_a_term_premium_exists() -> None:
    """Hand calculation: 4.250 - 0.750 = 3.500."""
    result = derive_market_implied_policy_path(4.250, 0.750)
    assert result.value == pytest.approx(3.5)


def test_market_implied_returns_the_raw_yield_unchanged_without_a_premium() -> None:
    """Section 22.5: return the raw yield, but warn LOUDLY and drop confidence.

    The requirement is not that the function refuse to answer — it is that the
    contamination be impossible to miss. So the value is exactly the input, and
    the differentiation lives in the warning and the confidence.
    """
    result = derive_market_implied_policy_path(4.250, None)
    assert result.value == pytest.approx(4.250)
    assert any("NO TERM PREMIUM ADJUSTMENT APPLIED" in warning for warning in result.warnings)
    assert any("CONTAMINATED" in warning for warning in result.warnings)


def test_market_implied_confidence_is_lower_without_a_term_premium() -> None:
    """The unadjusted branch must be measurably less trusted, not just flagged."""
    adjusted = derive_market_implied_policy_path(4.250, 0.750)
    unadjusted = derive_market_implied_policy_path(4.250, None)
    assert unadjusted.confidence < adjusted.confidence


def test_market_implied_always_warns_that_it_is_a_proxy() -> None:
    """Both branches carry the Phase 5+ replacement caveat.

    Asserted case-insensitively against the shared caveat phrase. An earlier
    version of this test looked for the uppercase token ``PROXY`` and passed
    only on the adjusted branch, because the unadjusted branch's first warning
    spells it lowercase. The behaviour was correct; the assertion was too
    narrow to see both branches.
    """
    for premium in (0.750, None):
        result = derive_market_implied_policy_path(4.250, premium)
        joined = " ".join(result.warnings).lower()
        assert "proxy" in joined, f"missing proxy caveat for premium={premium}"
        assert "phase 5+" in joined, f"missing Phase 5+ caveat for premium={premium}"


def test_market_implied_confidence_levels_match_config() -> None:
    """Section 22.5's confidences are read from config, not written in code.

    These two values deliberately bypass ``compute_confidence()`` because
    Section 22.5 states them as literals tied to a methodological weakness
    rather than as a function of factor states. Keeping them in config makes
    that deviation inspectable instead of looking like an oversight.
    """
    market_implied = get_settings().policy.market_implied
    adjusted = derive_market_implied_policy_path(4.250, 0.750)
    unadjusted = derive_market_implied_policy_path(4.250, None)
    assert adjusted.confidence == pytest.approx(
        market_implied.term_premium_available_confidence_value
    )
    assert unadjusted.confidence == pytest.approx(market_implied.no_term_premium_confidence_value)


def test_market_implied_a_zero_premium_is_not_the_same_as_no_premium() -> None:
    """``0.0`` is a real premium observation; ``None`` is its absence.

    Collapsing these is the classic three-states-into-two error: a genuine
    zero-premium reading would be reported with the contaminated-yield warning
    and the floor confidence, making a clean input look like a dirty one.
    """
    explicit_zero = derive_market_implied_policy_path(4.250, 0.0)
    absent = derive_market_implied_policy_path(4.250, None)
    assert explicit_zero.value == absent.value == pytest.approx(4.250)
    assert explicit_zero.confidence > absent.confidence
    assert not any("NO TERM PREMIUM ADJUSTMENT" in warning for warning in explicit_zero.warnings)


# ---------------------------------------------------------------------------
# Module 4.1 — qe_qt_stance
# ---------------------------------------------------------------------------

#: A level in the same units as FRED `WALCL` (millions), near its last reading.
_QE_LEVEL = 6_740_619.0


def _qe_leaf(value: float | int) -> CalibratedValue:
    """A synthetic config leaf whose value this test chose."""
    return CalibratedValue(
        value=value,
        calibration_status="fitted_assumption",
        note="synthetic — chosen by this test to be distinct from every other leaf",
    )


def _qe_settings() -> QEStanceSettings:
    return get_settings().qe_qt


def _bs(
    *,
    level: float = _QE_LEVEL,
    change_pct: float = 1.0,
    reserves: float = 2_991_310.0,
    reserve_change: float = -89_000.0,
    rrp: float | None = 5.4,
) -> BalanceSheetInputs:
    """Inputs whose stance is known by construction.

    The change is given as a PERCENTAGE of the level and converted here, so the
    fixture states the thing the band is actually about.
    """
    return BalanceSheetInputs(
        balance_sheet_level=level,
        balance_sheet_change_3mo=level * change_pct / 100.0,
        reserve_balances=reserves,
        reserve_balances_change_3mo=reserve_change,
        on_rrp_level=rrp,
    )


def test_the_three_stances_are_placed_correctly() -> None:
    cases = [
        (1.0, "QE_EXPANDING"),
        (-1.0, "QT_CONTRACTING"),
        (0.2, "NEUTRAL_HOLD"),
        (0.0, "NEUTRAL_HOLD"),
        (-0.2, "NEUTRAL_HOLD"),
    ]
    for change_pct, expected in cases:
        result = qe_qt_stance(_bs(change_pct=change_pct))
        assert as_str(result, key="stance") == expected, f"change {change_pct}%"


def test_all_three_stances_are_reachable() -> None:
    """D-040: Section 20.4's ``== 0`` test made NEUTRAL_HOLD dead code.

    Over 1226 weeks of `WALCL` the thirteen-week change was exactly zero on
    **zero** occasions, so the branch could never fire. This enumerates the
    implementation over a range of changes and asserts all three are reachable —
    the same technique that found the defect, kept as the regression guard.
    """
    reachable = {
        as_str(qe_qt_stance(_bs(change_pct=pct)), key="stance")
        for pct in (-3.0, -1.0, -0.6, -0.4, 0.0, 0.4, 0.6, 1.0, 3.0)
    }
    assert reachable == {"QE_EXPANDING", "QT_CONTRACTING", "NEUTRAL_HOLD"}, (
        f"every stance must be reachable; got {sorted(reachable)}. If NEUTRAL_HOLD "
        f"is missing, the `== 0` comparison has been restored."
    )


def test_the_band_boundary_is_inclusive() -> None:
    """A change EXACTLY at the band is NEUTRAL_HOLD, not QE.

    The shipped band is 0.5%, and the fixture is built by multiplying the level
    by exactly 0.005, so the point under test sits on the boundary rather than
    near it.
    """
    band = _qe_settings().neutral_band_pct
    at = qe_qt_stance(_bs(change_pct=band))
    outside = qe_qt_stance(_bs(change_pct=band + 0.05))
    assert as_str(at, key="stance") == "NEUTRAL_HOLD", (
        "a change exactly at the band is inside it — the comparison is inclusive"
    )
    assert as_str(outside, key="stance") == "QE_EXPANDING"
    assert as_float(at, key="balance_sheet_change_pct") == pytest.approx(band)


def test_the_band_is_relative_not_absolute() -> None:
    """The SAME absolute change means different things at different levels.

    A $34bn change is 0.5% of a $6.7T balance sheet and 5% of a $0.7T one. An
    absolute tolerance would call both the same; a relative one calls the first
    flat and the second a large expansion. The balance sheet has ranged from
    $0.7T to $9.0T over the sample, so this distinction is load-bearing.
    """
    # 20,000mn is 0.297% of a 6.74tn balance sheet and 2.81% of a 0.71tn one.
    # The first version used 34,000 — which is 0.5044% of 6.74tn, i.e. just
    # OUTSIDE the 0.5% band, so the "flat" case was not flat and the test failed.
    small = qe_qt_stance(
        BalanceSheetInputs(
            balance_sheet_level=6_740_619.0,
            balance_sheet_change_3mo=20_000.0,
            reserve_balances=2_991_310.0,
            reserve_balances_change_3mo=-89_000.0,
        )
    )
    large = qe_qt_stance(
        BalanceSheetInputs(
            balance_sheet_level=713_000.0,
            balance_sheet_change_3mo=20_000.0,
            reserve_balances=100_000.0,
            reserve_balances_change_3mo=-1_000.0,
        )
    )
    assert as_str(small, key="stance") == "NEUTRAL_HOLD", "20bn on 6.74tn is flat"
    assert as_str(large, key="stance") == "QE_EXPANDING", "20bn on 0.71tn is not"


def test_the_stance_is_recomputable_from_its_published_components() -> None:
    """The cross-field identity (D-009)."""
    for pct in (-2.0, -0.5, 0.0, 0.5, 2.0):
        result = qe_qt_stance(_bs(change_pct=pct))
        reported = as_float(result, key="balance_sheet_change_pct")
        level = as_float(result, key="balance_sheet_level")
        change = as_float(result, key="balance_sheet_change_3mo")
        band = as_float(result, key="neutral_band_pct")
        assert reported == pytest.approx(change / level * 100.0, abs=1e-3)
        expected = (
            "QE_EXPANDING"
            if reported > band
            else "QT_CONTRACTING"
            if reported < -band
            else "NEUTRAL_HOLD"
        )
        assert as_str(result, key="stance") == expected


# --- the scarcity assessment ----------------------------------------------


def test_qt_with_falling_reserves_is_the_scarcity_configuration() -> None:
    """The flag the specification's warning is about, made specific.

    `reserve_balances_change_3mo` is published by Section 20.4 but never read by
    it — the same inert-input defect as D-037. Here it decides whether QT is
    draining the RRP buffer or reserves directly.
    """
    draining = qe_qt_stance(_bs(change_pct=-1.0, reserve_change=-89_000.0))
    assert as_bool(draining, key="direct_reserve_drain") is True
    assert any("draining reserves directly" in w for w in draining.warnings)

    not_draining = qe_qt_stance(_bs(change_pct=-1.0, reserve_change=+50_000.0))
    assert as_bool(not_draining, key="direct_reserve_drain") is False
    assert not any("draining reserves directly" in w for w in not_draining.warnings)


def test_the_scarcity_flag_needs_qt_not_merely_falling_reserves() -> None:
    """Reserves falling during QE is not the scarcity case."""
    qe = qe_qt_stance(_bs(change_pct=1.0, reserve_change=-89_000.0))
    assert as_bool(qe, key="reserves_draining") is True
    assert as_bool(qe, key="direct_reserve_drain") is False, (
        "the flag is about QT draining reserves, not about reserves falling"
    )


def test_a_drained_rrp_buffer_is_reported() -> None:
    result = qe_qt_stance(_bs(change_pct=-1.0, rrp=5.4))
    assert as_bool(result, key="rrp_drained") is True
    assert any("exhausted" in w for w in result.warnings)


def test_a_full_rrp_buffer_is_not_reported_as_drained() -> None:
    """The absence half: a full facility must not raise the alarm."""
    result = qe_qt_stance(_bs(change_pct=-1.0, rrp=800.0))
    assert as_bool(result, key="rrp_drained") is False
    assert not any("exhausted" in w for w in result.warnings)


def test_an_absent_rrp_is_disclosed_as_incomplete() -> None:
    """Silence must not read as reassurance."""
    result = qe_qt_stance(_bs(change_pct=-1.0, rrp=None))
    assert as_bool(result, key="on_rrp_supplied") is False
    assert result.value is not None
    assert isinstance(result.value, dict)
    assert result.value["rrp_drained"] is None
    matches = [w for w in result.warnings if "NOT SUPPLIED" in w]
    assert len(matches) == 1, "the absent buffer level must be disclosed exactly once"


def test_the_rrp_threshold_comes_from_config() -> None:
    """Patched BELOW any plausible level, so nothing can count as drained.

    The first version patched the threshold UP to 9999 — which makes every
    facility drained, the opposite of the intent, so the assertion failed. The
    direction matters: `rrp_drained = level < threshold`, so lowering the
    threshold is what stops anything qualifying.
    """
    shipped = qe_qt_stance(_bs(change_pct=-1.0, rrp=5.4))
    assert as_bool(shipped, key="rrp_drained") is True, (
        "the shipped 50bn threshold must classify 5.4bn as drained, or the patch "
        "below proves nothing"
    )
    patched = _qe_settings().model_copy(update={"rrp_drained_threshold_bn_value": _qe_leaf(0.0)})
    with patch("macro_engine.models.policy_rules.get_settings") as mock:
        mock.return_value.qe_qt = patched
        result = qe_qt_stance(_bs(change_pct=-1.0, rrp=5.4))
    assert as_bool(result, key="rrp_drained") is False
    assert _qe_settings().rrp_drained_threshold_bn != 0.0


# --- the disclosures -------------------------------------------------------


def test_every_stance_travels_with_its_own_base_rate() -> None:
    """D-029, with the rates patched to DISTINCT values so a swap cannot hide."""
    patched = _qe_settings().model_copy(
        update={
            "base_rates": QEStanceBaseRates(
                observations_measured_value=_qe_leaf(4321),
                qe_expanding_rate_value=_qe_leaf(0.1111),
                qt_contracting_rate_value=_qe_leaf(0.2222),
                neutral_hold_rate_value=_qe_leaf(0.3333),
                reserve_drain_while_qt_rate_value=_qe_leaf(0.4444),
            )
        }
    )
    expected = {"QE_EXPANDING": 0.1111, "QT_CONTRACTING": 0.2222, "NEUTRAL_HOLD": 0.3333}
    with patch("macro_engine.models.policy_rules.get_settings") as mock:
        mock.return_value.qe_qt = patched
        for pct, name in ((-1.0, "QT_CONTRACTING"), (0.0, "NEUTRAL_HOLD"), (1.0, "QE_EXPANDING")):
            result = qe_qt_stance(_bs(change_pct=pct))
            assert as_str(result, key="stance") == name
            assert as_float(result, key="stance_base_rate") == pytest.approx(expected[name])
            assert as_int(result, key="observations_measured") == 4321
            assert any(f"{expected[name]:.1%}" in w for w in result.warnings)
    assert _qe_settings().base_rates.observations_measured != 4321


def test_the_qt_warning_fires_only_on_qt() -> None:
    """Exactly one of the three stances carries the repo-stress instruction."""
    firing = []
    for pct, expected in ((-1.0, "QT_CONTRACTING"), (0.0, "NEUTRAL_HOLD"), (1.0, "QE_EXPANDING")):
        result = qe_qt_stance(_bs(change_pct=pct))
        assert as_str(result, key="stance") == expected
        firing.append(any("repo_stress_check" in w for w in result.warnings))
    assert firing == [True, False, False], "only the QT stance must point at repo_stress_check()"


def test_the_band_correction_is_disclosed() -> None:
    """A reader must know the band exists, or they will read the stance as absolute."""
    result = qe_qt_stance(_bs(change_pct=0.0))
    matches = [w for w in result.warnings if "not against zero" in w]
    assert len(matches) == 1
    assert "unreachable" in matches[0], "the warning must say why the band exists"


# --- confidence ------------------------------------------------------------


def test_confidence_is_computed_from_the_stated_factors() -> None:
    result = qe_qt_stance(_bs())
    expected = compute_confidence(
        ConfidenceInputs(
            is_heuristic_not_calibrated=not _qe_calibrated_today(),
            source_independence_count=0,
        )
    )
    assert result.confidence == pytest.approx(expected)


def test_confidence_rises_when_the_band_is_calibrated() -> None:
    with patch("macro_engine.models.policy_rules._qe_stance_calibrated", return_value=True):
        calibrated = qe_qt_stance(_bs())
    illustrative = qe_qt_stance(_bs())
    assert calibrated.confidence > illustrative.confidence


def _qe_calibrated_today() -> bool:
    from macro_engine.models.policy_rules import _qe_stance_calibrated

    return _qe_stance_calibrated()


# --- the input contract ----------------------------------------------------


def test_a_non_positive_balance_sheet_level_is_refused() -> None:
    """It is the denominator of the relative change."""
    for bad in (0.0, -1.0):
        with pytest.raises(Exception, match="balance_sheet_level"):
            _bs(level=bad)


def test_the_input_contract_forbids_extra_fields() -> None:
    with pytest.raises(Exception, match="reserve"):
        BalanceSheetInputs(  # type: ignore[call-arg]
            balance_sheet_level=_QE_LEVEL,
            balance_sheet_change_3mo=1000.0,
            reserve_balances=2_991_310.0,
            reserve_balances_change_3mo=-89_000.0,
            reserve_balance=-89_000.0,
        )


def test_every_input_used_is_declared() -> None:
    """Section 20.4 lists three inputs while declaring four it never reads.

    All five are declared here — including the two levels, which the
    specification declares, lists in `inputs_used`, and then ignores.
    """
    result = qe_qt_stance(_bs())
    assert set(result.inputs_used) == {
        "balance_sheet_level",
        "balance_sheet_change_3mo",
        "reserve_balances",
        "reserve_balances_change_3mo",
        "on_rrp_level",
    }


def test_the_levels_are_published_and_not_merely_declared() -> None:
    """The defect D-037 found: inputs declared, listed, and never read.

    Section 20.4's `value` dict carries neither level. A consumer cannot check
    that a 0.5% band was applied without the level it is a percentage OF.
    """
    result = qe_qt_stance(_bs(level=6_740_619.0, reserves=2_991_310.0))
    assert as_float(result, key="balance_sheet_level") == pytest.approx(6_740_619.0)
    assert as_float(result, key="reserve_balances") == pytest.approx(2_991_310.0)
