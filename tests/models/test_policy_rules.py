"""Hand-computed verification tests for models/policy_rules.py.

Every expected value below is derived BY HAND from the formula and the
config values in config/settings.yaml (read, not assumed):

  taylor_output_gap_coefficient   = 0.5   (policy.rules)
  inflation_gap_coefficient       = 0.5   (policy.rules)
  balanced_approach gap coeff     = 1.0   (policy.balanced_approach)
  first_difference alpha/beta     = 0.5   (policy.rules)
  pi_target                       = 2.0
  ensemble convergence/uncertainty thresholds = 50bp / 100bp
  confidence base/penalties: 0.70 - 0.20 (heuristic) - 0.20 (unobservable)
      + 0.05/family, capped 0.25, floor 0.05, ceiling 0.95

These are REAL-WORLD checks: the Taylor/balanced/first-difference rules are
verified against their published algebraic forms, not against a mirror of the
code. If the code silently changes a coefficient, the hand value here fails.
"""

from __future__ import annotations

import pytest

from macro_engine.models.policy_rules import (
    BalanceSheetInputs,
    FirstDifferenceInputs,
    StatementTextInputs,
    TaylorRuleInputs,
    balanced_approach_rule,
    canonical_policy_gap,
    derive_market_implied_policy_path,
    first_difference_rule,
    policy_rule_ensemble,
    qe_qt_stance,
    statement_text_diff,
    taylor_rule,
)


# ---------------------------------------------------------------------------
# Taylor rule (Section 6.1, the mandated Section 11.1 example)
# ---------------------------------------------------------------------------
def test_taylor_rule_matches_hand_calculation() -> None:
    # r* = 0.5, pi = 3, target = 2, output_gap = +1
    # i = 0.5 + 3 + 0.5*(3-2) + 0.5*(1) = 0.5 + 3 + 0.5 + 0.5 = 4.5
    res = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    assert res.value == pytest.approx(4.5)
    assert res.rule_variant == "taylor_1993"
    # depends_on_unobservable=True -> confidence = 0.70 - 0.20 = 0.50
    assert res.confidence == pytest.approx(0.50)


def test_taylor_rule_inflation_gap_sign_is_correct() -> None:
    # Lower inflation than target must LOWER the prescribed rate.
    high = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=4.0, output_gap=0.0))
    low = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=1.0, output_gap=0.0))
    # i = r* + pi + 0.5*(pi - 2)
    # high: 0.5 + 4 + 0.5*2 = 5.5 ; low: 0.5 + 1 + 0.5*(-1) = 1.0
    assert high.value == pytest.approx(5.5)
    assert low.value == pytest.approx(1.0)
    assert high.value_float() > low.value_float()


# ---------------------------------------------------------------------------
# Balanced-approach rule — output-gap coefficient must be 1.0, not 0.5
# ---------------------------------------------------------------------------
def test_balanced_approach_rule_weights_output_gap_1x() -> None:
    # Same inputs as Taylor but the output-gap coefficient is 1.0:
    # i = 0.5 + 3 + 0.5*(1) + 1.0*(1) = 0.5 + 3 + 0.5 + 1.0 = 5.0
    res = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    assert res.value == pytest.approx(5.0)
    assert res.value == pytest.approx(
        taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0)).value_float()
        + 0.5
    )


# ---------------------------------------------------------------------------
# First-difference rule — prescribes a CHANGE from i_prev, not a level
# ---------------------------------------------------------------------------
def test_first_difference_rule_is_a_change_from_previous_rate() -> None:
    # i_t = i_{t-1} + alpha*(pi-pi_target) + beta*delta_gap
    #     = 4.0 + 0.5*(3-2) + 0.5*(0.5) = 4.0 + 0.5 + 0.25 = 4.75
    res = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    assert res.value == pytest.approx(4.75)
    # No r* dependence -> no unobservable penalty -> 0.70
    assert res.confidence == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# Ensemble — dispersion is the spread, never an average
# ---------------------------------------------------------------------------
def test_policy_rule_ensemble_reports_dispersion_not_mean() -> None:
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    out = policy_rule_ensemble(t, b, f)
    rules = out.value_dict()["rules"]
    assert rules["taylor"] == pytest.approx(4.5)
    assert rules["balanced"] == pytest.approx(5.0)
    assert rules["first_difference"] == pytest.approx(4.75)
    # dispersion = max - min = 5.0 - 4.5 = 0.5 pp = 50 bp
    assert out.value_dict()["dispersion_pp"] == pytest.approx(0.5)
    assert out.value_dict()["dispersion_bp"] == pytest.approx(50.0)
    # 50bp is exactly the convergence band edge -> strict '<' makes it MIXED
    assert out.value_dict()["agreement"] == "MIXED"
    # confidence is the MIN of the three inputs (0.5, 0.5, 0.7)
    assert out.confidence == pytest.approx(0.50)


def test_policy_rule_ensemble_converged_when_tight() -> None:
    # taylor 4.5 (gap=1), balanced 4.6 (gap=0.6 -> 0.5+3+0.5+0.6=4.6),
    # first 4.55 (i_prev=4.0, pi=3 -> 0.5*1=0.5, delta_gap=0.1 -> 0.05).
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=0.6))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.1)
    )
    # rules: 4.5, 4.6, 4.55 -> spread 0.1pp = 10bp < 50bp convergence band
    out = policy_rule_ensemble(t, b, f)
    assert out.value_dict()["dispersion_pp"] == pytest.approx(0.1)
    assert out.value_dict()["dispersion_bp"] == pytest.approx(10.0)
    assert out.value_dict()["agreement"] == "CONVERGED"


def test_policy_rule_ensemble_rejects_non_numeric_value() -> None:
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    f.value = "not a rate"
    with pytest.raises(TypeError):
        policy_rule_ensemble(t, b, f)


# ---------------------------------------------------------------------------
# Canonical gap (Section 22.4): median, and significance vs dispersion
# ---------------------------------------------------------------------------
def test_canonical_policy_gap_median_and_significance() -> None:
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    # median of [4.5, 5.0, 4.75] = 4.75 ; dispersion = 5.0 - 4.5 = 0.5
    gap = canonical_policy_gap(t, b, f, market_implied=4.0)
    assert gap.model_implied_value == pytest.approx(4.75)
    assert gap.dispersion == pytest.approx(0.5)
    assert gap.raw_gap == pytest.approx(0.75)
    # |0.75| > 0.5 -> meaningful
    assert gap.is_meaningful is True
    assert gap.direction == "model_above_market"


def test_canonical_policy_gap_within_noise_floor_is_not_meaningful() -> None:
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    # market = 4.6: gap = 4.75 - 4.6 = 0.15 ; |0.15| not > 0.5
    gap = canonical_policy_gap(t, b, f, market_implied=4.6)
    assert gap.is_meaningful is False
    assert gap.direction == "model_above_market"


def test_canonical_policy_gap_rejects_non_numeric_market() -> None:
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    with pytest.raises(TypeError):
        canonical_policy_gap(t, b, f, market_implied="4.0")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Market-implied proxy (Section 22.5): premium subtracted; raw returned if none
# ---------------------------------------------------------------------------
def test_derive_market_implied_subtracts_term_premium() -> None:
    out = derive_market_implied_policy_path(short_yield=4.5, short_tenor_term_premium=0.3)
    assert out.value == pytest.approx(4.2)  # 4.5 - 0.3
    assert out.confidence == pytest.approx(0.40)


def test_derive_market_implied_without_premium_returns_raw_yield() -> None:
    out = derive_market_implied_policy_path(short_yield=4.5, short_tenor_term_premium=None)
    assert out.value == pytest.approx(4.5)
    # No premium -> raw contaminated yield, confidence near floor
    assert out.confidence == pytest.approx(0.20)
    assert any("NO TERM PREMIUM" in w for w in out.warnings)


def test_derive_market_implied_rejects_nonfinite_inputs() -> None:
    with pytest.raises(ValueError):
        derive_market_implied_policy_path(short_yield=float("inf"), short_tenor_term_premium=None)
    with pytest.raises(ValueError):
        derive_market_implied_policy_path(short_yield=4.5, short_tenor_term_premium=float("nan"))


# ---------------------------------------------------------------------------
# QE/QT balance-sheet stance (Module 4.1)
# ---------------------------------------------------------------------------
def test_qe_qt_stance_qe_expanding_when_change_exceeds_band() -> None:
    inp = BalanceSheetInputs(
        balance_sheet_level=8_000_000.0,  # $8T
        balance_sheet_change_3mo=200_000.0,  # +$200bn
        reserve_balances=3_000_000.0,
        reserve_balances_change_3mo=50_000.0,
        on_rrp_level=None,
    )
    out = qe_qt_stance(inp)
    # change_pct = 200000/8000000*100 = 2.5% > 0.5% band
    assert out.value_dict()["stance"] == "QE_EXPANDING"
    assert out.value_dict()["balance_sheet_change_pct"] == pytest.approx(2.5)
    assert out.confidence == pytest.approx(0.50)


def test_qe_qt_stance_qt_contracting_when_change_below_negative_band() -> None:
    inp = BalanceSheetInputs(
        balance_sheet_level=8_000_000.0,
        balance_sheet_change_3mo=-200_000.0,
        reserve_balances=3_000_000.0,
        reserve_balances_change_3mo=-50_000.0,
        on_rrp_level=None,
    )
    out = qe_qt_stance(inp)
    assert out.value_dict()["stance"] == "QT_CONTRACTING"
    assert out.value_dict()["balance_sheet_change_pct"] == pytest.approx(-2.5)
    assert out.value_dict()["direct_reserve_drain"] is True


def test_qe_qt_stance_neutral_within_band() -> None:
    inp = BalanceSheetInputs(
        balance_sheet_level=8_000_000.0,
        balance_sheet_change_3mo=1_000.0,  # 0.0125% < 0.5% band
        reserve_balances=3_000_000.0,
        reserve_balances_change_3mo=0.0,
        on_rrp_level=None,
    )
    out = qe_qt_stance(inp)
    assert out.value_dict()["stance"] == "NEUTRAL_HOLD"


def test_qe_qt_stance_rejects_nonpositive_level() -> None:
    with pytest.raises(ValueError):
        BalanceSheetInputs(
            balance_sheet_level=0.0,
            balance_sheet_change_3mo=1_000.0,
            reserve_balances=3_000_000.0,
            reserve_balances_change_3mo=0.0,
        )


# ---------------------------------------------------------------------------
# Statement text diff (Module 4.3)
# ---------------------------------------------------------------------------
def test_statement_text_more_hawkish() -> None:
    prior = "the committee remains elevated. prepared to raise."
    current = "the committee remains elevated. additional policy firming. further tightening."
    out = statement_text_diff(StatementTextInputs(prior_text=prior, current_text=current))
    assert out.value_dict()["direction"] == "MORE_HAWKISH"
    assert out.value_dict()["net_tilt"] == pytest.approx(1.0)


def test_statement_text_dovish_tilt_with_hawkish_removals() -> None:
    # Hawkish language LEFT; dovish language ENTERED -> dovish net, hawkish removed.
    prior = "prepared to raise rates. additional policy firming expected."
    current = "has eased policy. prepared to adjust."
    out = statement_text_diff(StatementTextInputs(prior_text=prior, current_text=current))
    assert out.value_dict()["direction"] == "DOVISH_TILT_WITH_HAWKISH_REMOVALS"
    assert out.value_dict()["net_tilt"] == pytest.approx(-1.0)
    # confidence = round(computed * cap, 3); computed=0.70-0.20=0.50, cap=0.35 -> 0.175
    assert out.confidence == pytest.approx(0.175)


def test_statement_text_unchanged_when_no_markers_move() -> None:
    prior = "the committee will monitor developments carefully."
    current = "the committee will monitor developments carefully and patiently."
    out = statement_text_diff(StatementTextInputs(prior_text=prior, current_text=current))
    assert out.value_dict()["direction"] == "UNCHANGED"
    assert out.value_dict()["net_tilt"] == pytest.approx(0.0)


def test_statement_text_rejects_blank_statement() -> None:
    with pytest.raises(ValueError):
        statement_text_diff(
            StatementTextInputs(prior_text="", current_text="prepared to raise rates.")
        )


def test_statement_text_min_tokens_floor_is_one_token() -> None:
    # config min_tokens_value = 1, so a blank (0-token) statement is rejected by
    # the blank guard, and any real token-count is accepted. The min_tokens
    # ValueError can only trigger for a 0-token string, which the blank check
    # already rejects first.
    out = statement_text_diff(
        StatementTextInputs(
            prior_text="the committee met.", current_text="the committee met today."
        )
    )
    assert out.value_dict()["prior_tokens"] == 3
    with pytest.raises(ValueError):
        statement_text_diff(
            StatementTextInputs(prior_text="   ", current_text="the committee met.")
        )


def test_statement_text_net_tilt_ratio_is_bounded() -> None:
    # Both sides move and cancel exactly -> MIXED_BOTH_DIRECTIONS_NET_FLAT.
    # prior hawkish=1; current adds another hawkish AND a dovish -> h=+1, d=+1.
    prior = "prepared to raise rates."
    current = "prepared to raise rates. additional policy firming. sustainable progress noted."
    out = statement_text_diff(StatementTextInputs(prior_text=prior, current_text=current))
    assert out.value_dict()["direction"] == "MIXED_BOTH_DIRECTIONS_NET_FLAT"
    assert out.value_dict()["net_tilt"] == pytest.approx(0.0)
    assert -1.0 <= out.value_dict()["net_tilt"] <= 1.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
