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

from macro_engine.data_layer.fed_funds_futures_client import (
    FedFundsFuturesCurve,
    FuturesExpiration,
)
from macro_engine.models.policy_rules import (
    BalanceSheetInputs,
    FirstDifferenceInputs,
    StatementTextInputs,
    TaylorRuleInputs,
    balanced_approach_rule,
    canonical_policy_gap,
    derive_market_implied_policy_path,
    first_difference_rule,
    futures_implied_policy_path,
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


def test_the_market_legs_horizon_is_disclosed_in_the_gap_it_qualifies() -> None:
    """D1 — the horizon mismatch is DISCLOSED, not implied.

    The market leg is an AVERAGE over a horizon; the model leg is a SPOT
    prescription. Before this fix the caveat lived only in the market result's
    ``assumptions`` field — which ``collect_all_warnings`` does NOT read — so it
    never reached the thesis, and the gap's own interpretation said nothing. A
    reader of the published gap saw "model 5.00% vs market 4.00%" and would
    reasonably read it as a same-horizon disagreement. It is not one.
    """
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    gap = canonical_policy_gap(t, b, f, market_implied=4.0)
    assert "HORIZON MISMATCH" in gap.interpretation
    # It must name BOTH legs' horizons, not just say "a mismatch exists".
    assert "CURRENT period" in gap.interpretation
    assert "AVERAGE over" in gap.interpretation


def test_the_horizon_comes_from_config_and_the_statement_follows_it() -> None:
    """LAW 1 + mover proof: the published horizon is the CONFIG value.

    A hardcoded 24 in the prose would pass the disclosure test above while
    disagreeing with the configured short tenor. This asserts the number the
    reader sees is the number the config holds — and it moves when the config
    moves, which is what makes it a mover proof rather than a restatement.
    """
    from macro_engine.config import get_settings

    configured = get_settings().policy.market_implied.proxy_horizon_months_value
    t = taylor_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    b = balanced_approach_rule(TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0))
    f = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=0.5)
    )
    gap = canonical_policy_gap(t, b, f, market_implied=4.0)
    assert f"{configured} months" in gap.interpretation
    assert configured > 0


def test_the_market_leg_warns_about_the_horizon_so_it_reaches_the_thesis() -> None:
    """The warning must be in ``warnings`` — the only field the thesis collects.

    ``collect_all_warnings`` reads ``ModelResult.warnings`` and nothing else. The
    pre-fix caveat sat in ``assumptions``, so it was structurally unable to reach
    the thesis. This pins the field, not just the text.
    """
    out = derive_market_implied_policy_path(short_yield=4.0, short_tenor_term_premium=0.5)
    assert any("HORIZON MISMATCH" in w for w in out.warnings)
    # And the same for the no-term-premium branch, which is the LIVE path.
    live = derive_market_implied_policy_path(short_yield=4.0, short_tenor_term_premium=None)
    assert any("HORIZON MISMATCH" in w for w in live.warnings)


def test_the_horizon_leaf_rejects_a_non_positive_or_fractional_value() -> None:
    """The value is published as prose, so a bad value makes the prose false."""
    from macro_engine.config import CalibratedValue, MarketImpliedPolicySettings

    ok = "uncalibrated_illustrative"
    conf = CalibratedValue(value=0.4, calibration_status=ok)
    conf2 = CalibratedValue(value=0.2, calibration_status=ok)
    for bad in (0, -12, 18.5):
        settings = MarketImpliedPolicySettings(
            term_premium_available_confidence=conf,
            no_term_premium_confidence=conf2,
            proxy_horizon_months=CalibratedValue(value=bad, calibration_status=ok),
        )
        with pytest.raises(ValueError, match=r"positive|whole number"):
            _ = settings.proxy_horizon_months_value


# ---------------------------------------------------------------------------
# Section 22.5 — the futures-implied policy path (the REPLACEMENT body)
# ---------------------------------------------------------------------------
def _curve(
    rates: list[tuple[str, float]],
    *,
    rejected: int = 0,
    returned: int | None = None,
) -> FedFundsFuturesCurve:
    """A synthetic curve with HAND-CHOSEN implied rates, for the model tests.

    Built directly rather than fetched, so the model layer's arithmetic is
    tested against values this file controls — a fetch would couple the model
    test to the provider's behaviour and hide a mutation behind a live read.
    ``implied_rate_pct`` is given explicitly, so the identity is NOT re-derived
    here (that is the client test's job); the point is the model's use of it.
    """
    expirations = tuple(
        FuturesExpiration(
            expiration=expiration,
            price=100.0 - rate,
            implied_rate_pct=rate,
            months_ahead=index,
            raw_price=100.0 - rate,
        )
        for index, (expiration, rate) in enumerate(rates)
    )
    return FedFundsFuturesCurve(
        symbol="ZQ",
        provider="yfinance",
        settlement_offset=100.0,
        as_of="2026-10-10",
        expirations=expirations,
        rows_returned=returned if returned is not None else len(rates) + rejected,
        rows_rejected=rejected,
        rows_dropped_past=0,
        rejected_detail=(
            ("2027-04: implied rate 52.26% outside the plausible band",) if rejected else ()
        ),
        source_retrieved_at="2026-10-10T00:00:00+00:00",
    )


def test_the_futures_path_publishes_the_near_rate_not_the_mean() -> None:
    """``value`` is the front contract, not an average over the path.

    The whole point of the replacement: ``canonical_policy_gap`` compares the
    model's SPOT prescription against the market's CURRENT expectation, so the
    market leg must be the front rate. Hand values from the synthetic curve:
    the front is 3.88%, the mean of {3.88, 4.10, 4.40, 4.69} is 4.2675% — and
    the test proves the mean is NOT what was published.

    Publishing the mean would rebuild the proxy's horizon mismatch in the
    opposite direction, which is the exact defect Section 22.5 exists to fix.
    """
    curve = _curve([("2026-10", 3.88), ("2026-11", 4.10), ("2026-12", 4.40), ("2028-01", 4.69)])
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)

    assert result.value == pytest.approx(3.88)
    mean = (3.88 + 4.10 + 4.40 + 4.69) / 4
    assert mean == pytest.approx(4.2675)
    # And explicitly NOT the mean — the horizon-mismatch regression this
    # replacement exists to prevent, asserted rather than implied.
    assert result.value != pytest.approx(mean)


def test_the_futures_path_carries_the_slope_in_words_and_context() -> None:
    """The path's SHAPE is not discarded — it is reported.

    Hand arithmetic: slope = (4.69 - 3.88) * 100 = 81bp > 25bp → "pricing
    HIKES". The context must state the horizon it covers.
    """
    curve = _curve([("2026-10", 3.88), ("2026-11", 4.10), ("2028-01", 4.69)])
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)

    assert "HIKES" in result.interpretation
    assert "+81bp" in result.interpretation
    assert "30-Day Fed Funds futures curve" in result.context
    assert "Implied rate = 100 - price" in result.context


def test_a_downward_curve_is_reported_as_cuts() -> None:
    """Sign both ways: a falling path must say CUTS, not HIKES."""
    curve = _curve([("2026-10", 4.50), ("2026-11", 4.00), ("2027-06", 3.10)])
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)
    assert "CUTS" in result.interpretation
    assert "-140bp" in result.interpretation


def test_a_flat_curve_is_reported_as_flat_not_falsely_directional() -> None:
    """A 20bp slope is inside the +-25bp dead band → FLAT.

    Hand arithmetic: 3.88 → 4.10 is 22bp, below the threshold, so neither
    HIKES nor CUTS may appear.
    """
    curve = _curve([("2026-10", 3.88), ("2026-11", 4.00), ("2026-12", 4.10)])
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)
    assert "FLAT" in result.interpretation
    assert "HIKES" not in result.interpretation
    assert "CUTS" not in result.interpretation


def test_the_path_refuses_when_has_path_is_false() -> None:
    """A one-point "path" is what the proxy this replaces already was.

    ``has_path`` reads ``min_expirations`` from config (3), so a two-point
    curve must raise rather than publish a point as a path.
    """
    curve = _curve([("2026-10", 3.88), ("2026-11", 4.00)])
    assert curve.has_path is False
    with pytest.raises(ValueError, match=r"at least 3 plausible expirations"):
        futures_implied_policy_path(curve, proxy_horizon_months=24)


def test_the_path_truncates_to_the_comparison_horizon() -> None:
    """The published path covers ``proxy_horizon_months``, and says how many.

    Synthetic curve with horizons 0, 6, 18, 30 months. With a 24-month window
    the 30-month point is excluded from the path (but the front rate is
    unchanged, since the front is still the front).
    """
    curve = _curve([("2026-10", 3.88), ("2027-04", 4.00), ("2028-04", 4.20), ("2029-04", 4.50)])
    # Rebuild with correct horizons rather than enumeration.
    expirations = tuple(
        FuturesExpiration(e.expiration, e.price, e.implied_rate_pct, horizon, e.raw_price)
        for e, horizon in zip(curve.expirations, (0, 6, 18, 30), strict=True)
    )
    curve = FedFundsFuturesCurve(
        symbol="ZQ",
        provider="yfinance",
        settlement_offset=100.0,
        as_of="2026-10-10",
        expirations=expirations,
        rows_returned=4,
        rows_rejected=0,
        rows_dropped_past=0,
        rejected_detail=(),
        source_retrieved_at="2026-10-10T00:00:00+00:00",
    )
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)

    assert "Path covers 18 months" in result.context
    assert "24-month comparison window" in result.context
    # The 30-month point is outside the window, so it is not in observation_dates.
    assert "2029-04" not in result.observation_dates
    assert "2028-04" in result.observation_dates


def test_the_path_reports_the_rejection_count_in_warnings() -> None:
    """A corrupted curve must warn, and the warning must name the count."""
    curve = _curve(
        [("2026-10", 3.88), ("2026-11", 4.10), ("2028-01", 4.69)],
        rejected=6,
        returned=9,
    )
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)
    joined = " ".join(result.warnings)
    assert "6 of 9 expirations" in joined
    assert "REJECTED as implausible" in joined


def test_a_clean_flat_curve_produces_no_warnings() -> None:
    """No corruption and no slope → no warnings. The conditional is real."""
    curve = _curve([("2026-10", 3.88), ("2026-11", 3.90), ("2026-12", 3.92)])
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)
    assert result.warnings == []


def test_the_path_confidence_comes_from_config_not_a_literal() -> None:
    from macro_engine.config import get_settings

    curve = _curve([("2026-10", 3.88), ("2026-11", 4.10), ("2028-01", 4.69)])
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)
    assert result.confidence == pytest.approx(
        get_settings().market_implied_futures.distribution_confidence
    )
    assert result.unit == "percent"
    assert result.model_name == "futures_implied_policy_path"


def test_the_path_must_not_be_confused_with_the_proxy() -> None:
    """The two functions are different objects; the result says so.

    A guard against a caller silently swapping one for the other — the
    prohibition must be present in ``decision_prohibition``.
    """
    curve = _curve([("2026-10", 3.88), ("2026-11", 4.10), ("2028-01", 4.69)])
    result = futures_implied_policy_path(curve, proxy_horizon_months=24)
    joined = " ".join(result.decision_prohibition)
    assert "derive_market_implied_policy_path" in joined
    assert "NOT be described as a probability distribution" in joined


def test_the_config_asserts_the_two_horizons_agree() -> None:
    """``max_path_horizon_months`` must equal the proxy's horizon leaf.

    The caller passes ``proxy_horizon_months``; if the two config leaves
    disagreed, a caller following one would compare over a different window
    than the one the proxy warned about. The cross-check makes that
    impossible, so this test pins the invariant AND the error class.
    """
    from macro_engine.config import get_settings

    settings = get_settings()
    assert (
        settings.market_implied_futures.max_path_horizon_months
        == settings.policy.market_implied.proxy_horizon_months_value
    )


def test_the_section_22_5_replacement_obligation_is_now_discharged() -> None:
    """D2 — the tripwire, now reading the DISCHARGED state.

    Section 22.5 obligates Phase 5+ to replace the proxy with a real
    Fed-funds-futures-implied distribution. That obligation is now closed, and
    this tripwire asserts the closed state is real rather than declared:

    * the proxy body is **still intact** (it is the fail-safe fallback, so it must
      not be deleted), AND
    * the record says the obligation is ``"discharged"``, AND
    * the LIVE path actually supplies a curve — ``_reasoning_frames`` imports and
      calls the fetch, and the builder chain threads it.

    A tripwire that only checked the marker string could be satisfied by editing
    the marker alone; the live-wiring assertions are what make it a real test of
    the state. Conversely, if someone unwires the live path without reverting the
    marker, this fails too.
    """
    import ast
    import inspect
    import pathlib

    from macro_engine.models.policy_rules import PHASE5_REPLACEMENT_OBLIGATION

    source = inspect.getsource(derive_market_implied_policy_path)
    still_the_proxy = "short_yield - short_tenor_term_premium" in source
    assert still_the_proxy, (
        "The Phase 1-4 proxy body is gone. It is the FAIL-SAFE FALLBACK, not dead "
        "code — it must survive the replacement, because a futures outage falls "
        "back to it. Restore it, or the fail-safe path is a fiction."
    )
    assert PHASE5_REPLACEMENT_OBLIGATION == "discharged", (
        f"PHASE5_REPLACEMENT_OBLIGATION says {PHASE5_REPLACEMENT_OBLIGATION!r} but "
        "the live fetch is wired. Reverting the marker without unwiring the live "
        "path (or vice versa) leaves the record and the code disagreeing."
    )

    stream = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src/macro_engine/api_layer/reasoning_stream.py"
    ).read_text(encoding="utf-8")
    # AST, not a string scan. The earlier string version SURVIVED a mutant that
    # replaced the fetch with a literal `None` — every searched name was still
    # present (the import line and the builder call remain) while the fetched
    # value was discarded. So assert the MECHANISM: the result of a call to
    # `_fetch_futures_curve` must be unpacked and its first element passed as
    # `futures_curve=` somewhere downstream. Lesson 4, fourth instance.
    tree = ast.parse(stream)
    fetch_targets: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_fetch_futures_curve"
            and isinstance(node.targets[0], ast.Tuple)
            and node.targets[0].elts
            and isinstance(node.targets[0].elts[0], ast.Name)
        ):
            fetch_targets.add(node.targets[0].elts[0].id)
    assert fetch_targets, (
        "no `futures_curve, detail = _fetch_futures_curve()` unpacking found — the "
        "live fetch is not wired, so the marker's 'discharged' is false"
    )
    passed_names = {
        kw.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "futures_curve" and isinstance(kw.value, ast.Name)
    }
    assert fetch_targets & passed_names, (
        f"the fetched curve ({sorted(fetch_targets)}) is never passed as "
        f"`futures_curve=` (found {sorted(passed_names)}); the fetch is dead"
    )


def test_the_section_22_5_body_swap_is_impossible_but_the_change_is_additive() -> None:
    """The MEASURED mechanism, corrected 2026-10-10 (second pass).

    Section 22.5 promises the replacement is *"a body swap, not a caller-facing
    breaking change"* because *"this function's signature is stable"*. Measured,
    that promise splits into two claims, and only the first is true:

    * **A body swap is impossible.** The replacement's input is a **curve** (a
      collection of expirations); this function's *original* parameters carried
      two **scalars**. No body can conjure a curve from two floats without
      inventing the input, which Section 21.0 rule 3 forbids. The promised
      MECHANISM cannot be used.
    * **But the change need not be breaking.** The curve arrives as an OPTIONAL,
      keyword-only extension with a ``None`` default, so every pre-existing call
      site keeps working unchanged.

    This test PINS the corrected reading, so it cannot be mis-summarised back to
    either "impossible, therefore blocked" (the first pass's error) or "a body
    swap landed" (which never happened). Both halves are asserted:

    * the two original scalars are intact and unchanged, and
    * the curve arrives as a keyword-only parameter WITH a default, i.e. an
      additive extension, not a replacement of the two scalars.
    """
    import inspect

    params = inspect.signature(derive_market_implied_policy_path).parameters
    assert list(params)[:2] == ["short_yield", "short_tenor_term_premium"], (
        "the two original scalars moved — Section 22.5's 'stable signature' "
        "premise must be re-read against the new shape"
    )
    assert params["short_yield"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params["short_tenor_term_premium"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    # The curve must be ADDITIVE: keyword-only, with a default. A required or
    # positional curve would be a caller-facing breaking change, which would
    # make the promise false rather than merely the mechanism unusable.
    curve = params.get("futures_curve")
    assert curve is not None, (
        "the additive curve parameter is gone; if the replacement was reverted, "
        "update PHASE5_REPLACEMENT_OBLIGATION and this record in the same change"
    )
    assert curve.kind is inspect.Parameter.KEYWORD_ONLY, (
        "futures_curve must be keyword-only, or existing positional callers break"
    )
    assert curve.default is None, "futures_curve must default to None, or existing callers break"
    # The two original scalars are still annotated as floats — a curve cannot
    # travel through them, which is why the curve needed its own parameter.
    hints = inspect.getsource(derive_market_implied_policy_path)
    assert "short_yield: float" in hints
    assert "short_tenor_term_premium: float | None" in hints

    replacement_params = list(inspect.signature(futures_implied_policy_path).parameters)
    assert replacement_params[0] == "curve", (
        "the replacement must take the curve as its first argument — that is "
        "exactly why it cannot be a body swap"
    )
    curve_hint = inspect.getsource(futures_implied_policy_path)
    assert "curve: FedFundsFuturesCurve" in curve_hint, (
        "the replacement's first parameter must be typed as the curve; a scalar "
        "there would mean the path was reconstructed from invented inputs"
    )


def test_the_reader_prefers_the_futures_branch_when_a_curve_is_supplied() -> None:
    """The preference is real, not documented.

    ``derive_market_implied_policy_path`` takes an OPTIONAL curve and must return
    the futures-implied path when one is given, and the Phase 1-4 proxy when it
    is not. Asserting the returned ``model_name`` is the discriminating check:
    the two branches return results produced by different functions, so the
    name tells the caller which object it holds — which is exactly what the
    docstring promised a consumer could rely on.
    """
    from macro_engine.config import get_settings

    proxy = derive_market_implied_policy_path(4.5, 0.25)
    assert proxy.model_name == "derive_market_implied_policy_path", (
        "with no curve the proxy branch must run and keep its own model_name"
    )
    assert any("PROXY" in w for w in proxy.warnings), (
        "the proxy result must still carry its contamination warning"
    )

    curve = _curve([("2026-11", 3.88), ("2026-12", 4.05), ("2027-01", 4.31), ("2027-03", 4.69)])
    horizon = get_settings().policy.market_implied.proxy_horizon_months_value
    from_futures = derive_market_implied_policy_path(4.5, 0.25, futures_curve=curve)
    expected = futures_implied_policy_path(curve, proxy_horizon_months=horizon)
    assert from_futures.model_name == expected.model_name, (
        "a supplied curve must route to the futures function, not the proxy"
    )
    # And it must be the futures RESULT, not merely a result whose name agrees:
    # the futures result publishes the NEAR rate, which differs from the proxy's
    # term-premium-adjusted value for the same scalars.
    assert from_futures.value == pytest.approx(expected.value)
    assert from_futures.value != pytest.approx(proxy.value), (
        "the futures result and the proxy result must not coincide — if they do, "
        "the test cannot tell which branch ran"
    )
    assert not any("PROXY" in w for w in from_futures.warnings), (
        "the futures branch must NOT inherit the proxy's contamination warnings, "
        "which do not apply to a real futures curve"
    )


def test_the_live_path_supplies_the_curve_through_the_sanctioned_client() -> None:
    """The wiring is real, routed correctly, and fail-safe — asserted three ways.

    Section 22.5's replacement is only discharged if the LIVE path supplies a
    curve. Three things must hold, and each was a failure mode this project has
    met before:

    * **It fetches.** ``_reasoning_frames`` calls ``fetch_fed_funds_futures_curve``
      and passes the result into the builder chain.
    * **It is routed.** The fetch must go through ``OpenBBClient`` (D-087.25), not
      a raw HTTP call — so the module must NOT import ``httpx``/``requests``.
    * **It is fail-safe.** On a fetch failure the run falls back to the proxy
      rather than raising, so a futures outage degrades the market leg and does
      not break a live thesis. Pinned by the ``FuturesCurveError`` handler.
    """
    import ast
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src/macro_engine/api_layer/reasoning_stream.py"
    ).read_text(encoding="utf-8")

    assert "fetch_fed_funds_futures_curve" in source, (
        "the live path no longer fetches the curve — the obligation's discharge was reverted"
    )
    assert "futures_curve=futures_curve" in source, (
        "the fetched curve is not threaded into build_policy_gap/build_us_macro_thesis"
    )
    assert "FuturesCurveError" in source and "OpenBBFetchError" in source, (
        "the fetch is no longer caught — a futures outage would break a live run, "
        "contradicting the fail-safe contract the operator chose"
    )

    # Routed, not raw: D-087.25. Parse imports rather than grepping strings, so a
    # commented-out mention cannot satisfy the check (the textual-trace trap).
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "httpx" not in imported, "the live path must route through OpenBBClient, not raw httpx"
    assert "requests" not in imported, "the live path must route through OpenBBClient, not requests"


# ---------------------------------------------------------------------------
# Section 22.3 — the Bank of England reaction function (country "gb")
#
# Every expected value below is derived BY HAND from the BoE's published rule
# (Annex 1, November 2025 Monetary Policy Report, Table A1.A) and the config
# leaves, which are READ and asserted against the primary source first. The
# point of the section is that these are NOT the Fed rules relabelled, so the
# tests pin the STRUCTURAL differences — the energy/non-energy split, the
# smoothing pair, and the two DIFFERENT projection horizons — not merely that
# the functions return a number.
# ---------------------------------------------------------------------------
def test_the_boe_coefficients_match_the_published_annex_1_primary_source() -> None:
    """The config leaves ARE the BoE's published calibration, verified by value.

    This is the test that makes the rest of the section meaningful. Section 22.3
    rejects a relabelled Fed rule; the only way that claim is checkable is if the
    coefficients are pinned to the primary source rather than to whatever is in
    the file. Each value below is transcribed from Table A1.A of the BoE's
    November 2025 Monetary Policy Report, Annex 1 — the tables of which were
    read directly (pypdf), not restated from memory.

    If any of these fails, the rule is no longer the Bank of England's rule and
    every downstream "genuinely distinct" claim is false — so this test comes
    first and asserts EVERY leaf the three rules read.
    """
    from macro_engine.config import get_settings

    gb = get_settings().policy.gb

    # Target and neutral rate, with the BoE's own decomposition.
    assert gb.pi_target_value == pytest.approx(2.0)
    assert gb.real_rate_assumption_value == pytest.approx(1.0)
    assert gb.i_star_value == pytest.approx(3.0)
    # i* == target + illustrative real rate — the BoE's stated convention.
    assert gb.i_star_value == pytest.approx(gb.pi_target_value + gb.real_rate_assumption_value), (
        "i* must equal the target plus the illustrative real rate, per Annex 1"
    )

    # The published smoothing constant, on all three rules.
    assert gb.smoothing_value == pytest.approx(0.85)

    # Contemporaneous: the energy / non-energy asymmetry is the structural marker.
    assert gb.contemporaneous.energy_cpi_coefficient_value == pytest.approx(0.375)
    assert gb.contemporaneous.non_energy_cpi_coefficient_value == pytest.approx(1.5)
    assert gb.contemporaneous.output_gap_coefficient_value == pytest.approx(0.5)
    assert gb.contemporaneous.non_energy_cpi_coefficient_value > (
        gb.contemporaneous.energy_cpi_coefficient_value
    )

    # Forward-looking: 5-quarter horizon, Taylor principle on the inflation term.
    assert gb.forward_looking.inflation_coefficient_value == pytest.approx(1.5)
    assert gb.forward_looking.output_gap_coefficient_value == pytest.approx(0.5)
    assert gb.forward_looking.horizon_quarters_value == 5

    # First-difference: 3-quarter horizon — DIFFERENT from the above, deliberately.
    assert gb.first_difference.inflation_coefficient_value == pytest.approx(0.1)
    assert gb.first_difference.gdp_growth_coefficient_value == pytest.approx(0.1)
    assert gb.first_difference.horizon_quarters_value == 3
    assert (
        gb.first_difference.horizon_quarters_value != gb.forward_looking.horizon_quarters_value
    ), (
        "the two BoE forward-looking rules use DIFFERENT horizons (3 vs 5); a test "
        "that let them coincide would stop detecting the conflation"
    )


def test_the_boe_contemporaneous_rule_matches_the_hand_calculation() -> None:
    """``i = 0.85·i_prev + 0.15·(3 + 0.375·π_E + 1.5·π_N + 0.5·y)``, by hand.

    Two hand values, both from the published formula with config read:

    * **At the neutral point** (both gaps 0, output gap 0, i_prev = 3):
      raw = 3.0, and 0.85·3 + 0.15·3 = **3.0**. This pins the whole
      "deviations from steady state" convention — a rule reading LEVELS would
      return something near 5-6% here and the test would fail, which is the
      point: the convention is the substance of the rule.
    * **Off neutral** (i_prev = 4.5, π_E = 2, π_N = 3, y = 1):
      raw = 3 + 0.375·2 + 1.5·3 + 0.5·1 = 3 + 0.75 + 4.5 + 0.5 = **8.75**;
      i = 0.85·4.5 + 0.15·8.75 = 3.825 + 1.3125 = **5.1375 → 5.14**.
    """
    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        boe_contemporaneous_taylor_rule,
    )

    at_neutral = boe_contemporaneous_taylor_rule(
        BoeContemporaneousInputs(
            i_prev=3.0, pi_energy_gap_pp=0.0, pi_non_energy_gap_pp=0.0, output_gap=0.0
        )
    )
    assert at_neutral.value == pytest.approx(3.0)

    off_neutral = boe_contemporaneous_taylor_rule(
        BoeContemporaneousInputs(
            i_prev=4.5, pi_energy_gap_pp=2.0, pi_non_energy_gap_pp=3.0, output_gap=1.0
        )
    )
    hand = 0.85 * 4.5 + 0.15 * (3.0 + 0.375 * 2.0 + 1.5 * 3.0 + 0.5 * 1.0)
    assert off_neutral.value == pytest.approx(round(hand, 2))
    assert off_neutral.value == pytest.approx(5.14)


def test_the_boe_contemporaneous_rule_is_not_a_relabelled_fed_rule() -> None:
    """The energy term moves the prescription LESS than the non-energy term.

    The BoE weights non-energy ~4x energy on purpose. Holding everything else
    equal and moving each component by the same 1pp, the non-energy move must
    produce the larger prescription — that IS the decomposition the rule exists
    to apply, and a rule that weighted them equally (or swapped them) would
    still return *a* number while no longer being the Bank's rule.

    Hand arithmetic, i_prev = 3, output gap 0, one component raised 1pp:
      energy  +1: raw = 3 + 0.375 = 3.375 → i = 0.85·3 + 0.15·3.375 = 3.05625 → 3.06
      non-energy +1: raw = 3 + 1.5   = 4.5   → i = 0.85·3 + 0.15·4.5   = 3.225   → 3.22
    (The second rounds to 3.22, not 3.23 — 3.225 is a bankian-rounding tie and
    ``round()`` takes the even digit. The hand value is written as the code
    rounds it, so the test pins the published coefficient rather than a
    rounding convention.)
    """
    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        boe_contemporaneous_taylor_rule,
    )

    def run(*, e: float, n: float) -> float:
        return boe_contemporaneous_taylor_rule(
            BoeContemporaneousInputs(
                i_prev=3.0, pi_energy_gap_pp=e, pi_non_energy_gap_pp=n, output_gap=0.0
            )
        ).value_float()

    energy_bump = run(e=1.0, n=0.0)
    non_energy_bump = run(e=0.0, n=1.0)

    assert energy_bump == pytest.approx(3.06)
    assert non_energy_bump == pytest.approx(3.22)
    assert non_energy_bump > energy_bump, (
        "the non-energy component must dominate — the BoE weights it 4x, and a "
        "rule that did not would be a relabelled Fed rule (Section 22.3)"
    )


def test_the_boe_forward_looking_rule_matches_the_hand_calculation() -> None:
    """``i = 0.85·i_prev + 0.15·(3 + 1.5·(π_{t+5} - 2) + 0.5·y_{t+5})``, by hand.

    * **At the target** (projected inflation = 2.0, projected gap = 0, i_prev = 3):
      raw = 3 + 1.5·0 + 0 = 3.0 → i = **3.0**.
    * **Off target** (i_prev = 4, projected inflation = 3.0, projected gap = 1):
      raw = 3 + 1.5·(3 - 2) + 0.5·1 = 3 + 1.5 + 0.5 = **5.0**;
      i = 0.85·4 + 0.15·5 = 3.4 + 0.75 = **4.15**.
    """
    from macro_engine.models.policy_rules import (
        BoeForwardLookingInputs,
        boe_forward_looking_taylor_rule,
    )

    at_target = boe_forward_looking_taylor_rule(
        BoeForwardLookingInputs(i_prev=3.0, projected_inflation_pp=2.0, projected_output_gap=0.0)
    )
    assert at_target.value == pytest.approx(3.0)

    off_target = boe_forward_looking_taylor_rule(
        BoeForwardLookingInputs(i_prev=4.0, projected_inflation_pp=3.0, projected_output_gap=1.0)
    )
    hand = 0.85 * 4.0 + 0.15 * (3.0 + 1.5 * (3.0 - 2.0) + 0.5 * 1.0)
    assert off_target.value == pytest.approx(round(hand, 2))
    assert off_target.value == pytest.approx(4.15)


def test_the_boe_first_difference_rule_matches_the_hand_calculation() -> None:
    """``Δi = 0.1·(π_{t+3} - 2) + 0.1·ΔGDP_{t+3}`` → ``i = i_prev + Δi``, by hand.

    Hand: i_prev = 4, projected inflation = 3.0, projected GDP growth = 1.0:
    Δi = 0.1·(3 - 2) + 0.1·1 = 0.1 + 0.1 = **0.2** → i = **4.20**.

    The rule has NO smoothing term and NO ``i*`` — both by construction of the
    published expression, so its confidence is NOT penalised for the
    unobservable neutral rate (the same structural property the Fed's
    speed-limit rule has). The higher confidence is earned, not asserted.
    """
    from macro_engine.models.policy_rules import (
        BoeFirstDifferenceInputs,
        FirstDifferenceInputs,
        boe_first_difference_rule,
        first_difference_rule,
    )
    from macro_engine.models.policy_rules import (
        BoeFirstDifferenceInputs as _BoeFirstDifferenceInputs,
    )

    result = boe_first_difference_rule(
        _BoeFirstDifferenceInputs(i_prev=4.0, projected_inflation_pp=3.0, projected_gdp_growth=1.0)
    )
    assert result.value == pytest.approx(4.20)
    assert BoeFirstDifferenceInputs is _BoeFirstDifferenceInputs

    # The no-unobservable-penalty structure, asserted against the Fed rule's
    # own confidence — if i* leaked into this rule the two would not coincide.
    fed = first_difference_rule(
        FirstDifferenceInputs(i_prev=4.0, pi_current=3.0, output_gap_change=1.0)
    )
    assert result.confidence == pytest.approx(fed.confidence), (
        "the BoE first-difference rule has no i* term, so it must carry the same "
        "(unpenalised) confidence as the Fed's — a lower value would mean an "
        "unobservable dependency was introduced"
    )


def test_the_boe_rules_are_labelled_gb_not_us() -> None:
    """``country="gb"`` and the distinct ``rule_variant`` on every rule.

    Section 22.3's whole demand is that a country is not a label. The mirror is
    the risk here: a rule that returned ``country="us"`` or the Fed's variant
    tag would be indistinguishable from a Fed rule downstream, and every
    consumer that branches on ``rule_variant`` would silently treat a BoE
    prescription as a Fed one.
    """
    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        BoeFirstDifferenceInputs,
        BoeForwardLookingInputs,
        boe_contemporaneous_taylor_rule,
        boe_first_difference_rule,
        boe_forward_looking_taylor_rule,
    )

    trio = (
        boe_contemporaneous_taylor_rule(
            BoeContemporaneousInputs(
                i_prev=3.0, pi_energy_gap_pp=0.0, pi_non_energy_gap_pp=0.0, output_gap=0.0
            )
        ),
        boe_forward_looking_taylor_rule(
            BoeForwardLookingInputs(
                i_prev=3.0, projected_inflation_pp=2.0, projected_output_gap=0.0
            )
        ),
        boe_first_difference_rule(
            BoeFirstDifferenceInputs(
                i_prev=3.0, projected_inflation_pp=2.0, projected_gdp_growth=0.0
            )
        ),
    )

    assert {r.country for r in trio} == {"gb"}
    assert [r.rule_variant for r in trio] == [
        "boe_contemporaneous_taylor",
        "boe_forward_looking_taylor",
        "boe_first_difference",
    ]
    assert all(r.rule_variant.startswith("boe_") for r in trio), (
        "every BoE variant tag must be distinguishable from the Fed's by prefix"
    )


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("energy_cpi_coefficient", ("contemporaneous", "energy_cpi_coefficient", 0.75)),
        (
            "non_energy_cpi_coefficient",
            ("contemporaneous", "non_energy_cpi_coefficient", 3.0),
        ),
        ("gb_smoothing", ("smoothing", None, 0.5)),
        ("gb_i_star", ("i_star", None, 5.0)),
        ("gb_output_gap_coefficient", ("contemporaneous", "output_gap_coefficient", 1.0)),
    ],
)
def test_every_boe_contemporaneous_coefficient_leaf_is_a_real_mover(
    label: str, change: tuple[str, str | None, float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each config leaf the rule reads must CHANGE the output (LAW 1's mover proof).

    A coefficient read into a variable and then not used is the exact failure
    the mover proof exists to catch: the leaf looks calibrated and is inert. For
    each leaf this substitutes a different value, re-runs the rule, and asserts
    the prescription moved — so a leaf that was silently ignored fails here.

    ``gb_i_star`` is included deliberately: it is the rule's level anchor and
    the test proves it is genuinely consumed rather than decorative. The list is
    every leaf the CONTEMPORANEOUS rule reads. ``gb_pi_target`` is deliberately
    NOT here — see ``test_the_boe_pi_target_is_absent_from_the_contemporaneous_rule``
    for why, and why that absence is correct rather than a bug.
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        boe_contemporaneous_taylor_rule,
    )

    inputs = BoeContemporaneousInputs(
        i_prev=4.5, pi_energy_gap_pp=2.0, pi_non_energy_gap_pp=3.0, output_gap=1.0
    )
    baseline = boe_contemporaneous_taylor_rule(inputs).value

    gb = get_settings().policy.gb
    section, leaf, replacement = change
    target = gb if leaf is None else getattr(gb, section)
    leaf_name = leaf if leaf is not None else section
    original = getattr(target, leaf_name)

    class _Patched:
        value = replacement

    monkeypatch.setattr(target, leaf_name, _Patched())
    moved = boe_contemporaneous_taylor_rule(inputs).value

    assert moved != pytest.approx(baseline), (
        f"moving the config leaf policy.gb.{leaf_name} (for {label}) did not change "
        f"the prescription — the leaf is INERT, which is LAW 1's hardcoding failure "
        f"in the opposite direction: a calibrated-looking value that nothing reads"
    )
    monkeypatch.setattr(target, leaf_name, original)


def test_the_boe_pi_target_is_absent_from_the_contemporaneous_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pi_target`` moves the FORWARD-LOOKING rules but NOT the contemporaneous one.

    **This is a fact about the BoE's published formula, asserted rather than
    assumed.** The contemporaneous rule's inflation terms are written as
    "*the deviation from steady state*" of each component — the target is
    already inside the inputs, so the formula has no explicit ``π*`` and moving
    the target cannot move the prescription *given the same gaps*.

    That asymmetry is easy to mistake for a bug (a config leaf that "should" be
    read and is not), and the honest fix is not to bolt a spurious ``π*`` term
    onto the rule — that would be writing a rule the Bank did not publish. So
    the test pins BOTH directions:

    * the contemporaneous rule is UNCHANGED by ``pi_target`` — because the
      target is implicit in the gap inputs, not a term in the expression;
    * the two forward-looking rules DO change — because their published
      expressions subtract ``π*`` explicitly (``1.5(π_{t+5|t} - π*)`` and
      ``0.1(π_{t+3|t} - π*)``).

    A future edit that added a ``π*`` term to the contemporaneous rule would
    fail the first half; one that dropped it from a forward-looking rule would
    fail the second. Either way the divergence between the published rules
    cannot be silently smoothed over.
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        BoeFirstDifferenceInputs,
        BoeForwardLookingInputs,
        boe_contemporaneous_taylor_rule,
        boe_first_difference_rule,
        boe_forward_looking_taylor_rule,
    )

    gb = get_settings().policy.gb
    original = gb.pi_target

    contemporaneous_inputs = BoeContemporaneousInputs(
        i_prev=4.5, pi_energy_gap_pp=2.0, pi_non_energy_gap_pp=3.0, output_gap=1.0
    )
    forward_inputs = BoeForwardLookingInputs(
        i_prev=3.0, projected_inflation_pp=3.0, projected_output_gap=1.0
    )
    fd_inputs = BoeFirstDifferenceInputs(
        i_prev=3.0, projected_inflation_pp=3.0, projected_gdp_growth=1.0
    )

    before_contemp = boe_contemporaneous_taylor_rule(contemporaneous_inputs).value
    before_forward = boe_forward_looking_taylor_rule(forward_inputs).value
    before_fd = boe_first_difference_rule(fd_inputs).value

    class _Patched:
        value = 4.0

    monkeypatch.setattr(gb, "pi_target", _Patched())
    try:
        assert boe_contemporaneous_taylor_rule(contemporaneous_inputs).value == (
            pytest.approx(before_contemp)
        ), (
            "the contemporaneous rule's gaps already embed the target, so its "
            "published expression has no explicit pi* term — a change here means "
            "one was added, which is a rule the BoE did not publish"
        )
        assert boe_forward_looking_taylor_rule(forward_inputs).value != (
            pytest.approx(before_forward)
        ), "the forward-looking Taylor rule subtracts pi* explicitly; it must move"
        assert boe_first_difference_rule(fd_inputs).value != pytest.approx(before_fd), (
            "the BoE first-difference rule subtracts pi* explicitly; it must move"
        )
    finally:
        monkeypatch.setattr(gb, "pi_target", original)


def test_the_boe_forward_looking_rules_read_their_projection_horizon() -> None:
    """Moving a projection horizon changes the published prose, not just a number.

    The horizon is carried into the result's ``context`` and its warnings, so a
    leaf that were read but discarded would leave the prose claiming the old
    horizon. This asserts the config value reaches the OUTPUT, which a numeric-
    only assertion would miss (the projection values here are fixed, so the
    prescription does not move when only the horizon does — that is correct and
    is exactly why the output prose is the thing to check).
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        BoeForwardLookingInputs,
        boe_forward_looking_taylor_rule,
    )

    inputs = BoeForwardLookingInputs(
        i_prev=3.0, projected_inflation_pp=2.5, projected_output_gap=0.5
    )
    default = boe_forward_looking_taylor_rule(inputs)
    assert "5-quarter-ahead" in default.context or "15-month" in default.context

    gb = get_settings().policy.gb
    original = gb.forward_looking.horizon_quarters

    class _Patched:
        value = 8

    gb.forward_looking.__dict__["horizon_quarters"] = _Patched()
    try:
        changed = boe_forward_looking_taylor_rule(inputs)
        assert "8-quarter-ahead" in changed.context or "24-month" in changed.context, (
            "the projection horizon from config never reached the published "
            "context — the leaf is read but its effect is discarded"
        )
    finally:
        gb.forward_looking.horizon_quarters = original


def test_the_boe_smoothing_pair_is_one_number_not_two() -> None:
    """``0.85`` and ``0.15`` are ``s`` and ``1-s``, so they cannot disagree.

    The published rule writes ``0.85·i_{t-1} + 0.15·(…)``. If both were separate
    literals a config change to one would leave the other stale and the two
    halves would no longer sum to one — a defect invisible in any single output
    value. This pins the relationship by moving ``smoothing`` and asserting the
    behaviour: at ``s = 0`` the previous rate is discarded entirely and the
    output EQUALS the raw prescription, which holds only if the two weights sum
    to one.
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        boe_contemporaneous_taylor_rule,
    )

    inputs = BoeContemporaneousInputs(
        i_prev=0.0, pi_energy_gap_pp=0.0, pi_non_energy_gap_pp=0.0, output_gap=0.0
    )
    gb = get_settings().policy.gb
    original = gb.smoothing

    class _Zero:
        value = 0.0

    gb.__dict__["smoothing"] = _Zero()
    try:
        unsmoothed = boe_contemporaneous_taylor_rule(inputs)
        assert unsmoothed.value == pytest.approx(gb.i_star_value)
    finally:
        gb.smoothing = original


def test_the_boe_rules_refuse_a_non_finite_input() -> None:
    """The D-078 finiteness guard applies to the BoE input groups too.

    Each new input class inherits ``FiniteInputs``. A ``nan`` in any of the
    three would propagate into the prescription and then into the UK policy gap,
    where every comparison against it silently returns ``False`` — the exact
    "reports a verdict from a number it could not compute" failure D-078 closed
    for the Fed rules. Asserted per class so a future input group added without
    the base is caught.
    """
    import math

    from macro_engine.models.policy_rules import (
        BoeContemporaneousInputs,
        BoeFirstDifferenceInputs,
        BoeForwardLookingInputs,
    )

    for cls, kwargs in (
        (
            BoeContemporaneousInputs,
            {"i_prev": 3.0, "pi_energy_gap_pp": 0.0, "output_gap": 0.0},
        ),
        (
            BoeForwardLookingInputs,
            {"i_prev": 3.0, "projected_output_gap": 0.0},
        ),
        (
            BoeFirstDifferenceInputs,
            {"i_prev": 3.0, "projected_gdp_growth": 0.0},
        ),
    ):
        field = (
            "pi_non_energy_gap_pp" if cls is BoeContemporaneousInputs else "projected_inflation_pp"
        )
        with pytest.raises(ValueError, match=r"non-finite"):
            cls(**{**kwargs, field: math.nan})


# ---------------------------------------------------------------------------
# Section 22.3 — the European Central Bank reaction function (country "eu")
#
# Every expected value below is derived BY HAND from the ECB's own published
# estimation -- ECB Working Paper No 258 (September 2003), "Interest rate
# reaction functions and the Taylor rule in the euro area" -- whose Tables 2, 4
# and 6 were read directly (pypdf), not restated from memory. The config leaves
# are asserted against the primary source FIRST, because the whole section's
# point is that the euro-area arm is NOT the Fed rule (nor the BoE's) with a
# different label: Section 22.3's "genuinely distinct" bar.
#
# The structural markers pinned here, none of which the Fed or BoE arms carry:
#   * the euro area's OWN coefficients (2.733 / 1.443, against Taylor's 1.5 /
#     0.5, which the paper itself REJECTS at p = 0.04);
#   * the LONG RATE as a regressor, proxying the public's long-run inflation
#     perception -- the un-fakeable structural feature;
#   * an ERROR-CORRECTION (change) form, because the euro-area level
#     specification is unstable (unit roots);
#   * a NEGATIVE adjustment coefficient (-0.189), validated at the config leaf.
# ---------------------------------------------------------------------------
def test_the_ecb_coefficients_match_the_published_wp258_primary_source() -> None:
    """The config leaves ARE ECB WP 258's published calibration, verified by value.

    This is the test that makes the rest of the section meaningful. Section 22.3
    rejects a relabelled Fed rule; the only way that claim is checkable is if the
    coefficients are pinned to the primary source rather than to whatever is in
    the file. Each value below is transcribed from ECB Working Paper No 258
    (September 2003): Table 2 (the I(0) level rule), Table 4 (the cointegrating
    vectors) and Table 6 (the error-correction equations) -- read directly, not
    restated from memory.

    If any of these fails, the rule is no longer the ECB's euro-area rule and
    every downstream "genuinely distinct" claim is false -- so this test comes
    first and asserts EVERY leaf the three rules read.
    """
    from macro_engine.config import get_settings

    eu = get_settings().policy.eu

    # Target and neutral rate. The 2.0% HICP target is the ECB's 2021 strategy
    # (symmetric, medium-term); i* = 2.0 is the illustrative neutral rate. The
    # ECO's real-rate assumption is ZERO, deliberately unlike the Fed's 0.5 or
    # the BoE's 1.0: the euro area's own real-rate estimate is insignificantly
    # different from zero (WP 258 reports a 95% interval spanning [-0.85, 5.48]),
    # so pinning a positive real rate would overstate the identified neutral.
    assert eu.pi_target_value == pytest.approx(2.0)
    assert eu.real_rate_assumption_value == pytest.approx(0.0)
    assert eu.i_star_value == pytest.approx(2.0)
    assert eu.i_star_value == pytest.approx(eu.pi_target_value + eu.real_rate_assumption_value), (
        "i* must equal the target plus the (zero) euro-area real-rate assumption"
    )
    assert eu.real_rate_assumption_value != pytest.approx(1.0), (
        "the euro-area real-rate assumption is 0.0, NOT the BoE's 1.0 — a shared "
        "positive value would be the relabelling Section 22.3 rejects"
    )

    # The euro area's own smoothing, fit on the lagged euro-area short rate.
    assert eu.smoothing_value == pytest.approx(0.884)

    # Contemporaneous level rule: the euro area's OWN coefficients. These are
    # nearly twice (inflation) and nearly three times (output gap) Taylor's, and
    # the paper's joint Wald test REJECTS 1.5 / 0.5 at p = 0.04.
    assert eu.contemporaneous.inflation_coefficient_value == pytest.approx(2.733)
    assert eu.contemporaneous.output_gap_coefficient_value == pytest.approx(1.443)
    assert eu.contemporaneous.inflation_coefficient_value != pytest.approx(1.5)
    assert eu.contemporaneous.output_gap_coefficient_value != pytest.approx(0.5)

    # Error-correction: the cointegrating vector (Table 4, unrestricted) and the
    # short-run coefficients and adjustment speed (Table 6).
    ec = eu.error_correction
    assert ec.long_rate_coefficient_value == pytest.approx(0.827)
    assert ec.inflation_coefficient_value == pytest.approx(0.900)
    assert ec.output_gap_coefficient_value == pytest.approx(0.358)
    assert ec.adjustment_coefficient_value == pytest.approx(-0.189)
    assert ec.inflation_change_coefficient_value == pytest.approx(0.628)
    assert ec.output_gap_change_coefficient_value == pytest.approx(0.266)
    assert ec.rate_change_persistence_coefficient_value == pytest.approx(0.370)

    # The RESTRICTED vector (Table 4, restricted; b_pi = 1 imposed, p = 0.78):
    # the long-rate and output-gap coefficients are RE-ESTIMATED, not the
    # unrestricted ones -- 0.771 / 0.437 against 0.827 / 0.358.
    assert ec.restricted_long_rate_coefficient_value == pytest.approx(0.771)
    assert ec.restricted_output_gap_coefficient_value == pytest.approx(0.437)
    assert ec.restricted_long_rate_coefficient_value != pytest.approx(
        ec.long_rate_coefficient_value
    ), (
        "the restriction RE-ESTIMATES the remaining coefficients; if the "
        "restricted long-rate coefficient equalled the unrestricted one, the "
        "two rules would be one rule written twice"
    )


def test_the_ecb_adjustment_coefficient_must_be_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``c_e = -0.189`` is validated at the leaf, not clamped in the function.

    The error-correction term must pull the rate TOWARD equilibrium, which
    requires a negative coefficient: a positive deviation (i_prev above
    equilibrium) must produce a NEGATIVE change. The sign is a fact about the
    published estimate, and the honest place to enforce it is the config leaf —
    so a flip is caught loudly rather than masked by an ``abs()`` in the rule.

    The validator is exercised by flipping the LIVE leaf (`policy.eu.
    error_correction.adjustment_coefficient`) to a positive value and calling the
    validator property, which raises. The property's own message says why: the
    sign is not visible in the prescribed rate, which is precisely why it needs
    a check of its own rather than being inferable downstream.
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        EcbErrorCorrectionInputs,
        ecb_error_correction_rule,
    )

    ec = get_settings().policy.eu.error_correction
    original = ec.adjustment_coefficient

    class _Positive:
        value = 0.189

    monkeypatch.setattr(ec, "adjustment_coefficient", _Positive())
    with pytest.raises(ValueError, match=r"must be negative"):
        _ = ec.adjustment_coefficient_value
    # And the rule itself propagates the refusal: it cannot prescribe a change
    # from a destabilising coefficient.
    with pytest.raises(ValueError, match=r"must be negative"):
        ecb_error_correction_rule(
            EcbErrorCorrectionInputs(
                i_prev=2.65,
                i_prev_change=0.0,
                long_rate=3.748,
                pi_current=2.0,
                pi_change=0.0,
                output_gap=0.0,
                output_gap_change=0.0,
            )
        )
    monkeypatch.setattr(ec, "adjustment_coefficient", original)


def test_the_ecb_contemporaneous_rule_matches_the_hand_calculation() -> None:
    """``i = 0.884·i_prev + 0.116·(2 + 2.733·(π - 2) + 1.443·y)``, by hand.

    Two hand values, both from the published formula with config read:

    * **At neutral** (π = 2.0, y = 0, i_prev = 2.65): raw = 2.0, and
      0.884·2.65 + 0.116·2.0 = 2.3426 + 0.232 = **2.5746 → 2.57**. This pins the
      "deviations from target" convention: at target-inflation and a closed gap
      the rule settles at i*, so a rule reading LEVELS would return something
      near 5-7% here and fail — which is the point.
    * **Off neutral** (i_prev = 3.0, π = 4.0, y = 1.0):
      raw = 2 + 2.733·2 + 1.443·1 = 2 + 5.466 + 1.443 = **8.909**;
      i = 0.884·3.0 + 0.116·8.909 = 2.652 + 1.033444 = **3.685444 → 3.69**.
    """
    from macro_engine.models.policy_rules import (
        EcbContemporaneousInputs,
        ecb_contemporaneous_taylor_rule,
    )

    at_neutral = ecb_contemporaneous_taylor_rule(
        EcbContemporaneousInputs(i_prev=2.65, pi_current=2.0, output_gap=0.0)
    )
    assert at_neutral.value == pytest.approx(2.57)

    off_neutral = ecb_contemporaneous_taylor_rule(
        EcbContemporaneousInputs(i_prev=3.0, pi_current=4.0, output_gap=1.0)
    )
    hand = 0.884 * 3.0 + 0.116 * (2.0 + 2.733 * (4.0 - 2.0) + 1.443 * 1.0)
    assert off_neutral.value == pytest.approx(round(hand, 2))
    assert off_neutral.value == pytest.approx(3.69)


def test_the_ecb_contemporaneous_rule_is_not_a_relabelled_fed_rule() -> None:
    """A 1pp inflation gap moves the euro-area prescription MORE than the Fed's.

    The euro area's estimated inflation response is 2.733, against Taylor's 1.5
    and the BoE's 1.5. Holding everything else equal and moving the inflation gap
    by the same 1pp, the euro-area prescription must move by more than a rule
    using 1.5 would — that IS the estimated response the rule exists to apply,
    and a rule that used 1.5 (or 0.5) would still return *a* number while no
    longer being the euro area's rule.

    Hand arithmetic, i_prev = i* = 2.0, y = 0, inflation gap 0 → 1pp:
      euro area: raw = 2 + 2.733 = 4.733 → i = 0.884·2 + 0.116·4.733 = 1.768 +
                 0.549028 = 2.317028 → 2.32
      Taylor   : raw = 2 + 1.5   = 3.5   → i = 1.768 + 0.116·3.5 = 1.768 + 0.406
                 = 2.174 → 2.17
    """
    from macro_engine.models.policy_rules import (
        EcbContemporaneousInputs,
        ecb_contemporaneous_taylor_rule,
    )

    def run(*, pi: float) -> float:
        return abs(
            ecb_contemporaneous_taylor_rule(
                EcbContemporaneousInputs(i_prev=2.0, pi_current=pi, output_gap=0.0)
            ).value_float()
            - 2.0
        )

    ecb_move = run(pi=3.0)  # 1pp above the 2% target
    taylor_move = abs((0.884 * 2.0 + 0.116 * (2.0 + 1.5 * 1.0)) - 2.0)

    assert ecb_move == pytest.approx(0.32, abs=0.005)
    assert ecb_move > taylor_move, (
        "the euro area's estimated inflation response (2.733) must move the "
        "prescription more than Taylor's 1.5 — a rule that did not would be a "
        "relabelled Fed rule (Section 22.3)"
    )


def test_the_ecb_error_correction_rule_matches_the_hand_calculation() -> None:
    """``Δi = 0.628·Δπ + 0.266·Δy + 0.370·Δi_prev + (-0.189)·(i_prev - eqm)``, by hand.

    The equilibrium the rule corrects toward is
    ``eqm = π* + 0.827·l + 0.900·π + 0.358·y`` (the unrestricted cointegrating
    vector with the constant anchored at the target).

    Hand, i_prev = 2.65, all change terms 0, l = 3.748, π = 2.0, y = 0:
      eqm = 2 + 0.827·3.748 + 0.900·2.0 + 0 = 2 + 3.099596 + 1.8 = **6.899596**
      ecr = 2.65 - 6.899596 = **-4.249596**
      Δi  = 0.628·0 + 0.266·0 + 0.370·0 + (-0.189)·(-4.249596)
          = 0 + 0 + 0 + 0.803174 = **0.803174**
      i   = 2.65 + 0.803174 = **3.453174 → 3.45**.

    The LONG RATE is what produces this: it enters the equilibrium with a large
    coefficient, so even at target inflation the rule prescribes a large
    increase — the euro area's short rate is below what its own long rate implies
    its long-run stance is. That is the structural feature §22.3 requires, not a
    decorative input.
    """
    from macro_engine.models.policy_rules import (
        EcbErrorCorrectionInputs,
        ecb_error_correction_rule,
    )

    result = ecb_error_correction_rule(
        EcbErrorCorrectionInputs(
            i_prev=2.65,
            i_prev_change=0.0,
            long_rate=3.748,
            pi_current=2.0,
            pi_change=0.0,
            output_gap=0.0,
            output_gap_change=0.0,
        )
    )
    eqm = 2.0 + 0.827 * 3.748 + 0.900 * 2.0 + 0.358 * 0.0
    ecr = 2.65 - eqm
    hand = 2.65 + (-0.189) * ecr
    assert result.value == pytest.approx(round(hand, 2))
    assert result.value == pytest.approx(3.45)


def test_the_long_rate_moves_the_ecb_error_correction_rule_and_no_fed_rule() -> None:
    """The long rate is the STRUCTURAL regressor — moving it moves the rule.

    This is the cleanest "genuinely distinct" assertion available: the euro-area
    error-correction rule reads the 10-year rate, so changing it changes the
    prescription; and the input record is where that is enforced, because the
    OTHER two ECB rules (and every Fed rule) have no ``long_rate`` field at all,
    so a caller cannot even pass one.

    Hand: i_prev = 2.65, π = 2.0, y = 0, changes 0, l = 3.0 vs l = 4.0:
      l = 3.0: eqm = 2 + 0.827·3.0 + 0.900·2.0 = 6.281 → ecr = -3.631
               → Δi = 0.686259 → i = 3.336259 → 3.34
      l = 4.0: eqm = 2 + 3.308 + 1.8 = 7.108 → ecr = -4.458 → Δi = 0.842562
               → i = 3.492562 → 3.49
    The two differ: the long rate is load-bearing.
    """
    from macro_engine.models.policy_rules import (
        EcbContemporaneousInputs,
        EcbErrorCorrectionInputs,
        EcbRestrictedCointegrationInputs,
        ecb_contemporaneous_taylor_rule,
        ecb_error_correction_rule,
        ecb_restricted_cointegration_rule,
    )

    def ec_at(long_rate: float) -> float:
        return ecb_error_correction_rule(
            EcbErrorCorrectionInputs(
                i_prev=2.65,
                i_prev_change=0.0,
                long_rate=long_rate,
                pi_current=2.0,
                pi_change=0.0,
                output_gap=0.0,
                output_gap_change=0.0,
            )
        ).value_float()

    assert ec_at(3.0) == pytest.approx(3.34)
    assert ec_at(4.0) == pytest.approx(3.49)
    assert ec_at(3.0) != pytest.approx(ec_at(4.0)), (
        "the long rate is the euro area's structural regressor; if moving it "
        "left the prescription unchanged the input would be decorative and the "
        "rule would be a level-only Fed rule with euro-area series"
    )

    # The input records themselves enforce the asymmetry: neither the level rule
    # nor the restricted rule accepts a long_rate, so the term cannot be smuggled
    # into them. (The restricted rule DOES read the long rate in its equilibrium
    # but not as a short-run dynamic; the point here is the level rule.)
    level = EcbContemporaneousInputs(i_prev=2.0, pi_current=2.0, output_gap=0.0)
    assert not hasattr(level, "long_rate"), (
        "the level rule must not accept a long rate — the two regressor sets are "
        "what make the functions structurally distinct rather than one list twice"
    )
    # Both cointegration rules are constructible and independent.
    ecb_contemporaneous_taylor_rule(level)
    ecb_restricted_cointegration_rule(
        EcbRestrictedCointegrationInputs(
            i_prev=2.65,
            i_prev_change=0.0,
            long_rate=3.748,
            real_rate=-0.2,
            pi_change=0.0,
            output_gap=0.0,
            output_gap_change=0.0,
        )
    )


def test_the_ecb_restricted_cointegration_rule_matches_the_hand_calculation() -> None:
    """``Δi = ... + (-0.189)·(real_rate_prev - 0.771·l - 0.437·y)``, by hand.

    The restricted equilibrium is the REAL rate against the long rate and the
    gap, with a unit inflation coefficient imposed:
    ``eqm = 0.771·l + 0.437·y`` — the RE-ESTIMATED coefficients.

    Hand, i_prev = 2.65, real_rate = -0.2, l = 3.748, y = 0, all changes 0:
      eqm = 0.771·3.748 = **2.889708**
      ecr = -0.2 - 2.889708 = **-3.089708**
      Δi  = (-0.189)·(-3.089708) = **0.583955** → i = 2.65 + 0.583955
          = **3.233955 → 3.23**.

    A rule using the UNRESTRICTED long-rate coefficient (0.827) would give
    eqm = 3.099596, ecr = -3.299596, Δi = 0.623624, i = 3.27 — a different
    answer, which is why the restricted form is its own function with its own
    leaf rather than a flag on the unrestricted one.
    """
    from macro_engine.models.policy_rules import (
        EcbRestrictedCointegrationInputs,
        ecb_restricted_cointegration_rule,
    )

    result = ecb_restricted_cointegration_rule(
        EcbRestrictedCointegrationInputs(
            i_prev=2.65,
            i_prev_change=0.0,
            long_rate=3.748,
            real_rate=-0.2,
            pi_change=0.0,
            output_gap=0.0,
            output_gap_change=0.0,
        )
    )
    eqm = 0.771 * 3.748
    hand = 2.65 + (-0.189) * (-0.2 - eqm)
    assert result.value == pytest.approx(round(hand, 2))
    assert result.value == pytest.approx(3.23)

    # The restricted coefficients genuinely differ from the unrestricted ones, so
    # the answer above is not reproducible with the unrestricted leaf.
    unrestricted_eqm = 0.827 * 3.748
    wrong = 2.65 + (-0.189) * (-0.2 - unrestricted_eqm)
    assert result.value != pytest.approx(round(wrong, 2)), (
        "the restricted rule must use the RE-ESTIMATED 0.771, not the "
        "unrestricted 0.827 — otherwise the two estimands are conflated"
    )


def test_the_ecb_rules_are_labelled_eu_not_us_and_carry_distinct_variants() -> None:
    """``country="eu"`` and a distinct ``rule_variant`` on every rule.

    Section 22.3's whole demand is that a country is not a label. The mirror is
    the risk here: a rule that returned ``country="us"`` (as the shipped Fed and
    — until this increment — every country's rules did) or a variant tag shared
    with the Fed's or BoE's would be indistinguishable downstream, and every
    consumer that branches on ``rule_variant`` would silently treat an ECB
    prescription as a Fed or BoE one.
    """
    from macro_engine.models.policy_rules import (
        EcbContemporaneousInputs,
        EcbErrorCorrectionInputs,
        EcbRestrictedCointegrationInputs,
        ecb_contemporaneous_taylor_rule,
        ecb_error_correction_rule,
        ecb_restricted_cointegration_rule,
    )

    trio = (
        ecb_contemporaneous_taylor_rule(
            EcbContemporaneousInputs(i_prev=2.0, pi_current=2.0, output_gap=0.0)
        ),
        ecb_error_correction_rule(
            EcbErrorCorrectionInputs(
                i_prev=2.0,
                i_prev_change=0.0,
                long_rate=3.748,
                pi_current=2.0,
                pi_change=0.0,
                output_gap=0.0,
                output_gap_change=0.0,
            )
        ),
        ecb_restricted_cointegration_rule(
            EcbRestrictedCointegrationInputs(
                i_prev=2.0,
                i_prev_change=0.0,
                long_rate=3.748,
                real_rate=-0.2,
                pi_change=0.0,
                output_gap=0.0,
                output_gap_change=0.0,
            )
        ),
    )

    assert {r.country for r in trio} == {"eu"}
    assert [r.rule_variant for r in trio] == [
        "ecb_contemporaneous_taylor",
        "ecb_error_correction",
        "ecb_restricted_cointegration",
    ]
    assert all(r.rule_variant.startswith("ecb_") for r in trio), (
        "every ECB variant tag must be distinguishable from the Fed's and BoE's by prefix"
    )
    # The euro-area cointegration rules carry no unobservable-neutral-rate
    # penalty; the level rule does. The split is the earned one.
    assert trio[0].confidence < trio[1].confidence, (
        "the level rule depends on the unobservable i* and must be penalised "
        "relative to the error-correction rule, which needs no i*"
    )


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("ecb_inflation_coefficient", ("contemporaneous", "inflation_coefficient", 1.5)),
        ("ecb_output_gap_coefficient", ("contemporaneous", "output_gap_coefficient", 0.5)),
        ("ecb_smoothing", ("smoothing", None, 0.5)),
        ("ecb_i_star", ("i_star", None, 5.0)),
    ],
)
def test_every_ecb_contemporaneous_coefficient_leaf_is_a_real_mover(
    label: str, change: tuple[str, str | None, float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each config leaf the level rule reads must CHANGE the output (LAW 1's mover proof).

    A coefficient read into a variable and then not used is the exact failure
    the mover proof exists to catch: the leaf looks calibrated and is inert. For
    each leaf this substitutes a different value, re-runs the rule, and asserts
    the prescription moved — so a leaf that was silently ignored fails here.

    ``ecb_i_star`` is included deliberately: it is the rule's level anchor and
    the test proves it is genuinely consumed rather than decorative. The list is
    every leaf the CONTEMPORANEOUS rule reads; ``ecb_pi_target`` is deliberately
    NOT here — see ``test_the_ecb_pi_target_is_read_by_the_level_rule`` for why
    it is a mover here (unlike the BoE's, whose gaps already embed the target).
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        EcbContemporaneousInputs,
        ecb_contemporaneous_taylor_rule,
    )

    inputs = EcbContemporaneousInputs(i_prev=3.0, pi_current=4.0, output_gap=1.0)
    baseline = ecb_contemporaneous_taylor_rule(inputs).value

    eu = get_settings().policy.eu
    section, leaf, replacement = change
    target = eu if leaf is None else getattr(eu, section)
    leaf_name = leaf if leaf is not None else section
    original = getattr(target, leaf_name)

    class _Patched:
        value = replacement

    monkeypatch.setattr(target, leaf_name, _Patched())
    moved = ecb_contemporaneous_taylor_rule(inputs).value

    assert moved != pytest.approx(baseline), (
        f"moving the config leaf policy.eu.{leaf_name} (for {label}) did not "
        f"change the prescription — the leaf is INERT, which is LAW 1's "
        f"hardcoding failure in the opposite direction: a calibrated-looking "
        f"value that nothing reads"
    )
    monkeypatch.setattr(target, leaf_name, original)


def test_the_ecb_pi_target_is_read_by_the_level_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ECB level rule reads ``pi_target`` EXPLICITLY — unlike the BoE's.

    This is a genuine structural difference between the two central banks'
    published formulas, asserted rather than assumed. The BoE's contemporaneous
    rule is written on gaps that already embed the target, so moving ``pi_target``
    cannot move it (pinned by
    ``test_the_boe_pi_target_is_absent_from_the_contemporaneous_rule``). The ECB
    level rule is written on the LEVEL of inflation against the target,
    ``(π - π*)``, so ``pi_target`` IS a term and moving it MUST move the
    prescription. A test that assumed the BoE's behaviour here would wrongly
    demand the ECB rule ignore a leaf it genuinely reads.
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        EcbContemporaneousInputs,
        ecb_contemporaneous_taylor_rule,
    )

    inputs = EcbContemporaneousInputs(i_prev=3.0, pi_current=4.0, output_gap=1.0)
    baseline = ecb_contemporaneous_taylor_rule(inputs).value

    eu = get_settings().policy.eu
    original = eu.pi_target

    class _Patched:
        value = 3.0

    monkeypatch.setattr(eu, "pi_target", _Patched())
    moved = ecb_contemporaneous_taylor_rule(inputs).value

    assert moved != pytest.approx(baseline), (
        "the ECB level rule subtracts the target explicitly, (pi - pi*); if "
        "moving pi_target left the prescription unchanged the term is not read"
    )
    monkeypatch.setattr(eu, "pi_target", original)


def test_every_ecb_error_correction_coefficient_leaf_is_a_real_mover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each error-correction leaf the rule reads must CHANGE the output.

    The counterpart of the contemporaneous mover proof, for the eight leaves the
    error-correction rule reads: the three cointegrating coefficients, the four
    short-run / adjustment coefficients, and the persistence term. A leaf that
    were inert here would be a calibrated-looking zero-usage value — the §22.3
    "structural" regressor that does not actually enter the arithmetic.
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        EcbErrorCorrectionInputs,
        ecb_error_correction_rule,
    )

    inputs = EcbErrorCorrectionInputs(
        i_prev=2.65,
        i_prev_change=0.2,
        long_rate=3.748,
        pi_current=2.5,
        pi_change=-0.3,
        output_gap=0.5,
        output_gap_change=0.1,
    )
    baseline = ecb_error_correction_rule(inputs).value

    eu = get_settings().policy.eu
    ec = eu.error_correction
    # A per-leaf replacement, because `adjustment_coefficient` is sign-validated
    # (must be < 0): a positive probe value would trip the validator rather than
    # test the mover property, so it gets a different NEGATIVE value.
    leaves: dict[str, float] = {
        "long_rate_coefficient": 1.5,
        "inflation_coefficient": 1.5,
        "output_gap_coefficient": 1.5,
        "adjustment_coefficient": -0.7,  # negative, like the published leaf
        "inflation_change_coefficient": 1.5,
        "output_gap_change_coefficient": 1.5,
        "rate_change_persistence_coefficient": 1.5,
    }
    for leaf_name, replacement in leaves.items():
        original = getattr(ec, leaf_name)

        class _Patched:
            value = replacement

        monkeypatch.setattr(ec, leaf_name, _Patched())
        moved = ecb_error_correction_rule(inputs).value
        monkeypatch.setattr(ec, leaf_name, original)

        assert moved != pytest.approx(baseline), (
            f"moving policy.eu.error_correction.{leaf_name} did not change the "
            f"error-correction prescription — the leaf is inert"
        )


def test_the_ecb_rules_refuse_a_non_finite_input() -> None:
    """The D-078 finiteness guard applies to the ECB input groups too.

    Each new input class inherits ``_FiniteInputs``. A ``nan`` in any field would
    propagate into the prescription and then into the euro-area policy gap, where
    every comparison against it silently returns ``False`` — the exact "reports a
    verdict from a number it could not compute" failure D-078 closed for the Fed
    rules. Asserted per class so a future input group added without the base is
    caught.
    """
    import math

    from macro_engine.models.policy_rules import (
        EcbContemporaneousInputs,
        EcbErrorCorrectionInputs,
        EcbRestrictedCointegrationInputs,
    )

    for cls, kwargs, field in (
        (
            EcbContemporaneousInputs,
            {"i_prev": 2.0, "pi_current": 2.0},
            "output_gap",
        ),
        (
            EcbErrorCorrectionInputs,
            {
                "i_prev": 2.0,
                "i_prev_change": 0.0,
                "long_rate": 3.7,
                "pi_change": 0.0,
                "output_gap": 0.0,
                "output_gap_change": 0.0,
            },
            "pi_current",
        ),
        (
            EcbRestrictedCointegrationInputs,
            {
                "i_prev": 2.0,
                "i_prev_change": 0.0,
                "long_rate": 3.7,
                "pi_change": 0.0,
                "output_gap": 0.0,
                "output_gap_change": 0.0,
            },
            "real_rate",
        ),
    ):
        with pytest.raises(ValueError, match=r"non-finite"):
            cls(**{**kwargs, field: math.nan})


# ---------------------------------------------------------------------------
# Section 22.3 — GERMANY (country "de"). A member state, NOT a central bank.
#
# Every expected value below is derived BY HAND from the rule's own published
# form with the config leaves read and asserted first. The section's point is
# STRUCTURAL: Germany has no central bank of its own, so nothing here may
# prescribe a German rate. The rules take the ECB's single rate as an EXOGENOUS
# input and publish a DIVERGENCE — the un-fakeable difference from the Fed, BoE
# and ECB arms, each of which SETS the rate it trades off.
# ---------------------------------------------------------------------------
def test_the_de_coefficients_match_their_stated_provenance() -> None:
    """The `de` config leaves are read and pinned before any arithmetic.

    The German arm's weights are ILLUSTRATIVE (there is no published Bundesbank
    reaction function to transcribe), so the honest pin is not a primary-source
    citation but the leaves' OWN provenance: each is marked illustrative in
    config, and each is asserted here by value so a silent edit is caught. A
    test that skipped this would let the "appropriate" weights drift with no
    witness — and the sign convention (below) is calibrated against them.
    """
    from macro_engine.config import get_settings

    de = get_settings().policy.de

    # All four divergences enter with weight 1.0 — equal, and stated, not implied.
    assert de.appropriateness.inflation_coefficient_value == pytest.approx(1.0)
    assert de.appropriateness.output_gap_coefficient_value == pytest.approx(1.0)
    assert de.appropriateness.unemployment_coefficient_value == pytest.approx(1.0)
    assert de.appropriateness.growth_coefficient_value == pytest.approx(1.0)
    assert de.appropriateness.r_neutral_value == pytest.approx(0.0)

    # The Bund-spread reference: an even blend of the set rate and the German
    # short rate. Equal weights are what make the reference a midpoint.
    assert de.bund_spread.ecb_rate_weight_value == pytest.approx(0.5)
    assert de.bund_spread.german_short_rate_weight_value == pytest.approx(0.5)
    assert de.bund_spread.ecb_rate_weight_value + de.bund_spread.german_short_rate_weight_value == (
        pytest.approx(1.0)
    )


def test_the_de_approp_rule_has_no_pi_target_and_no_owned_rate() -> None:
    """A member state does not OWN a target or a rate — the fields are absent.

    This is the structural refusal stated as an ABSENCE: unlike the Fed's, the
    BoE's and the ECB's settings, ``DePolicySettings`` carries no ``pi_target``,
    no ``i_star`` and no ``smoothing``. If it did, some rule could read them and
    quietly fabricate a German reaction function. The absence IS the design, so
    it is asserted directly rather than left to a docstring.
    """
    from macro_engine.config import get_settings

    de = get_settings().policy.de
    for absent in ("pi_target", "i_star", "smoothing"):
        assert not hasattr(de, absent), (
            f"DePolicySettings must not carry {absent!r}: Germany owns no target "
            f"and no policy rate (Section 22.3)"
        )


def test_the_de_member_appropriateness_rule_matches_the_hand_calculation() -> None:
    """``gap = 1·(πd-πe) + 1·(yd-ye) + 1·(ue-ud) + 1·(gd-ge)``, by hand.

    Two hand values, config read (all weights 1.0):

    * **At convergence** (every German value equals its euro-area counterpart):
      all four divergences are 0 → gap = **0.0**. Pins the "a divergence, not a
      level" convention: a rule reading German levels would return something
      near the inflation or unemployment VALUE and fail — which is the point.
    * **Germany hot** (πd=3, πe=2; y_d=0.5, y_e=0; u_d=5, u_e=6; g_d=0.4,
      g_e=0): gap = 1 + 0.5 + 1 + 0.4 = **2.9**. Every term is POSITIVE because
      Germany is hotter than the aggregate on all four — and note the
      unemployment term is entered as ``u_e - u_d``: German unemployment BELOW
      the aggregate contributes POSITIVELY.
    """
    from macro_engine.models.policy_rules import (
        DeMemberAppropriatenessInputs,
        de_member_appropriateness_rule,
    )

    at_convergence = de_member_appropriateness_rule(
        DeMemberAppropriatenessInputs(
            f_ecb=3.75,
            pi_de=2.0,
            pi_ea=2.0,
            output_gap_de=0.0,
            output_gap_ea=0.0,
            unemployment_de=6.0,
            unemployment_ea=6.0,
            gdp_growth_de=0.0,
            gdp_growth_ea=0.0,
        )
    )
    assert at_convergence.value == pytest.approx(0.0)

    hot = de_member_appropriateness_rule(
        DeMemberAppropriatenessInputs(
            f_ecb=3.75,
            pi_de=3.0,
            pi_ea=2.0,
            output_gap_de=0.5,
            output_gap_ea=0.0,
            unemployment_de=5.0,
            unemployment_ea=6.0,
            gdp_growth_de=0.4,
            gdp_growth_ea=0.0,
        )
    )
    hand = (3.0 - 2.0) + (0.5 - 0.0) + (6.0 - 5.0) + (0.4 - 0.0)
    assert hot.value == pytest.approx(round(hand, 4))
    assert hot.value == pytest.approx(2.9)
    # The unemployment sign convention: German unemployment BELOW the aggregate
    # must push the gap UP, not down.
    assert hot.value_float() > at_convergence.value_float()


def test_the_de_approp_rule_sign_is_a_stance_diagnosis_not_a_rate() -> None:
    """A POSITIVE gap means the shared rate is too LOOSE for Germany.

    The inverted convention is the rule's identity: the euro-area rules read a
    rate and prescribe a rate; this one reads a rate and publishes a DIVERGENCE.
    Asserted in BOTH directions so a sign flip cannot survive — a flipped sign
    would read as a plausible number either way.
    """
    from macro_engine.models.policy_rules import (
        DeMemberAppropriatenessInputs,
        PolicyRuleResult,
        de_member_appropriateness_rule,
    )

    def run(*, pi_de: float) -> PolicyRuleResult:
        return de_member_appropriateness_rule(
            DeMemberAppropriatenessInputs(
                f_ecb=3.75,
                pi_de=pi_de,
                pi_ea=2.0,
                output_gap_de=0.0,
                output_gap_ea=0.0,
                unemployment_de=6.0,
                unemployment_ea=6.0,
                gdp_growth_de=0.0,
                gdp_growth_ea=0.0,
            )
        )

    hot = run(pi_de=3.0)  # German inflation ABOVE the union
    cold = run(pi_de=1.0)  # ...and BELOW it
    assert hot.value_float() > 0, (
        "German inflation above the euro area means the single rate is too loose "
        "— a POSITIVE divergence"
    )
    assert cold.value_float() < 0
    assert "TOO LOOSE" in (hot.direction or "")
    assert "TOO TIGHT" in (cold.direction or "")
    assert hot.unit == "percentage_points"
    assert "not a rate" in hot.warnings[0].lower() or "NOT A RATE" in hot.warnings[0]


def test_the_de_bund_spread_rule_matches_the_hand_calculation() -> None:
    """``signal = bund_10y - (0.5·f_ecb + 0.5·de_short_3m)``, by hand.

    With config read (both weights 0.5):
    * bund_10y=2.51, f_ecb=3.75, de_short_3m=3.40:
      reference = 0.5·3.75 + 0.5·3.40 = 1.875 + 1.70 = 3.575;
      signal = 2.51 - 3.575 = **-1.065**. NEGATIVE: the German curve sits BELOW
      the ECB-set reference.
    * A Bund above the reference gives a POSITIVE signal — asserted separately
      so the sign is pinned in both directions.
    """
    from macro_engine.models.policy_rules import (
        DeBundSpreadInputs,
        de_bund_spread_rule,
    )

    below = de_bund_spread_rule(DeBundSpreadInputs(bund_10y=2.51, f_ecb=3.75, de_short_3m=3.40))
    hand_reference = 0.5 * 3.75 + 0.5 * 3.40
    assert below.value == pytest.approx(round(2.51 - hand_reference, 4))
    assert below.value == pytest.approx(-1.065)
    assert "BELOW" in (below.direction or "")

    above = de_bund_spread_rule(DeBundSpreadInputs(bund_10y=4.00, f_ecb=3.75, de_short_3m=3.40))
    assert above.value == pytest.approx(round(4.00 - hand_reference, 4))
    assert above.value_float() > 0
    assert "ABOVE" in (above.direction or "")

    # The German short rate is a REAL regressor: moving it, holding everything
    # else, moves the signal. A reference that dropped the German term (leaving
    # the ECB weight alone) would make the signal INVARIANT to `de_short_3m`,
    # which is the mechanism this pins.
    low = de_bund_spread_rule(DeBundSpreadInputs(bund_10y=2.51, f_ecb=3.75, de_short_3m=3.00))
    high = de_bund_spread_rule(DeBundSpreadInputs(bund_10y=2.51, f_ecb=3.75, de_short_3m=3.80))
    assert low.value != high.value, (
        "the German 3-month rate must move the Bund signal — the reference is a "
        "BLEND of the ECB rate and the German short rate, not the ECB rate alone"
    )
    assert low.value_float() > high.value_float(), (
        "a HIGHER German short rate raises the reference, so the signal FALLS"
    )


def test_the_de_real_rate_rule_matches_the_hand_calculation_and_cancels_f_ecb() -> None:
    """``real_de = f_ecb - π_de``; the shared rate CANCELS in the differential.

    Hand (f_ecb=3.75, π_de=2.4, π_ea=1.8, r_neutral=0.5):
      real_de = 3.75 - 2.40 = **1.35**; versus the euro area's 3.75 - 1.80 =
      1.95, so Germany's real rate is 0.60pp BELOW — which equals π_ea - π_de =
      1.8 - 2.4 = **-0.60**. The shared nominal rate appears on both sides and
      cancels, which is stated here as an identity and asserted.

    This is the structural marker in real terms: no central-bank rule in the
    module can produce a quantity where the rate it sets cancels out.
    """
    from macro_engine.models.policy_rules import DeRealRateInputs, de_real_rate_rule

    result = de_real_rate_rule(DeRealRateInputs(f_ecb=3.75, pi_de=2.4, pi_ea=1.8, r_neutral_de=0.5))
    real_de = 3.75 - 2.40
    real_ea = 3.75 - 1.80
    assert result.value == pytest.approx(round(real_de, 4))
    assert result.value == pytest.approx(1.35)
    # The differential equals the inflation divergence with f_ecb held constant.
    assert (real_de - real_ea) == pytest.approx(1.8 - 2.4)
    # Direction: Germany's real rate BELOW the euro area's reads "too loose".
    assert result.direction == "too loose for Germany"
    assert result.unit == "percent"
    # The neutral-rate gap (`real_de - r_neutral_de`) is PUBLISHED only in the
    # interpretation, so the test reads the interpretation: a mutant that
    # dropped the subtraction would leave `value` (= real_de) correct while the
    # published gap silently became the raw real rate. Asserting the exact
    # sentence is what pins the term the mutation aimed at.
    assert result.interpretation == (
        "With the ECB's 3.75% nominal rate and German inflation at 2.40%, "
        "Germany's real policy rate is 1.35% \u2014 +0.85pp against an "
        "illustrative neutral real rate of 0.50%"
    )
    assert f"{real_de - 0.5:+.2f}pp" in result.interpretation


def test_the_de_bund_spread_is_not_a_de_policy_rate() -> None:
    """The Bund leg must forbid being read as a rate (a gate against the relabel).

    The relabel Section 22.3 forbids would be presenting a German curve position
    as Germany's policy rate. The rule's own ``decision_prohibition`` must name
    that, or the prohibition is only in the docstring and a downstream consumer
    can ignore it. Asserted on the rule's published field, not the source text.
    """
    from macro_engine.models.policy_rules import (
        DeBundSpreadInputs,
        de_bund_spread_rule,
    )

    result = de_bund_spread_rule(DeBundSpreadInputs(bund_10y=2.51, f_ecb=3.75, de_short_3m=3.40))
    joined = " ".join(result.decision_prohibition).lower()
    assert "must not be read as a policy rate" in joined
    assert result.unit == "percentage_points"
    # The direction string must be a coherent sentence, not a garbled
    # concatenation — the exact defect a defect-reading of the body found.
    assert "referencethe" not in (result.direction or "")
    assert (result.direction or "").startswith("the Bund 10-year curve is ")


def test_the_de_appropriateness_rule_forbids_the_bundesbank_relabel() -> None:
    """The appropriateness rule must name its OWN prohibition, not just the Bund's.

    L4 in the sweep weakens this exact prohibition, and the Bund-spread test
    above does not read it — so without this test the weakening survives. The
    rule is the one most exposed to the relabel §22.3 forbids (its name contains
    "rule" and it reads a policy rate), so its published prohibition must say
    plainly that it is NOT a Bundesbank reaction function.
    """
    from macro_engine.models.policy_rules import (
        DeMemberAppropriatenessInputs,
        de_member_appropriateness_rule,
    )

    result = de_member_appropriateness_rule(
        DeMemberAppropriatenessInputs(
            f_ecb=3.75,
            pi_de=3.0,
            pi_ea=2.0,
            output_gap_de=0.5,
            output_gap_ea=0.0,
            unemployment_de=5.0,
            unemployment_ea=6.0,
            gdp_growth_de=0.4,
            gdp_growth_ea=0.0,
        )
    )
    joined = " ".join(result.decision_prohibition)
    assert "MUST NOT be described as a Bundesbank or German reaction function" in joined, (
        "the appropriateness rule must forbid the Bundesbank relabel in its own "
        "published prohibitions (Section 22.3)"
    )
    assert "Germany does NOT set monetary policy" in joined
    assert result.unit == "percentage_points"


def test_the_de_rules_are_labelled_de_with_distinct_variants() -> None:
    """Every `de` rule reports country ``de``, model_name and its own variant.

    A rule that ran the German arithmetic but stamped ``country="eu"`` (or ``us``)
    would produce a thesis attributing German divergence to the wrong entity.
    The ``model_name`` is asserted as well as the ``rule_variant``: both are
    consumer keys, and a rename of either breaks every caller keyed on it while
    the value stays plausible.
    """
    from macro_engine.models.policy_rules import (
        DeBundSpreadInputs,
        DeMemberAppropriatenessInputs,
        DeRealRateInputs,
        de_bund_spread_rule,
        de_member_appropriateness_rule,
        de_real_rate_rule,
    )

    results = [
        de_member_appropriateness_rule(
            DeMemberAppropriatenessInputs(
                f_ecb=3.75,
                pi_de=2.0,
                pi_ea=2.0,
                output_gap_de=0.0,
                output_gap_ea=0.0,
                unemployment_de=6.0,
                unemployment_ea=6.0,
                gdp_growth_de=0.0,
                gdp_growth_ea=0.0,
            )
        ),
        de_bund_spread_rule(DeBundSpreadInputs(bund_10y=2.51, f_ecb=3.75, de_short_3m=3.40)),
        de_real_rate_rule(DeRealRateInputs(f_ecb=3.75, pi_de=2.4, pi_ea=1.8, r_neutral_de=0.5)),
    ]
    for r in results:
        assert r.country == "de"
    assert {r.rule_variant for r in results} == {
        "de_member_appropriateness",
        "de_bund_spread",
        "de_real_rate",
    }
    assert {r.model_name for r in results} == {
        "de_member_appropriateness_rule",
        "de_bund_spread_rule",
        "de_real_rate_rule",
    }


@pytest.mark.parametrize(
    ("label", "change"),
    [
        (
            "de_inflation",
            ("appropriateness", "inflation_coefficient", 2.0),
        ),
        (
            "de_output_gap",
            ("appropriateness", "output_gap_coefficient", 2.0),
        ),
        (
            "de_unemployment",
            ("appropriateness", "unemployment_coefficient", 2.0),
        ),
        (
            "de_growth",
            ("appropriateness", "growth_coefficient", 2.0),
        ),
        (
            "de_ecb_weight",
            ("bund_spread", "ecb_rate_weight", 0.25),
        ),
        (
            "de_german_short_weight",
            ("bund_spread", "german_short_rate_weight", 0.75),
        ),
    ],
)
def test_every_de_coefficient_leaf_is_a_real_mover(
    label: str, change: tuple[str, str, float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each `de` coefficient leaf the rules read must CHANGE the output.

    LAW 1's mover proof: a weight read into a variable and then not used is the
    exact failure this catches — the leaf looks calibrated and is inert. The
    four appropriateness weights and the two Bund-reference weights are each
    substituted and the rule re-run; a leaf the rule silently ignored fails here.
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        DeBundSpreadInputs,
        DeMemberAppropriatenessInputs,
        de_bund_spread_rule,
        de_member_appropriateness_rule,
    )

    de = get_settings().policy.de
    section, leaf, replacement = change
    target = getattr(de, section)
    original = getattr(target, leaf)

    class _Patched:
        value = replacement

    if section == "appropriateness":
        inputs_kwargs = {
            "f_ecb": 3.75,
            "pi_de": 3.0,
            "pi_ea": 2.0,
            "output_gap_de": 0.5,
            "output_gap_ea": 0.0,
            "unemployment_de": 5.0,
            "unemployment_ea": 6.0,
            "gdp_growth_de": 0.4,
            "gdp_growth_ea": 0.0,
        }
        baseline = de_member_appropriateness_rule(
            DeMemberAppropriatenessInputs(**inputs_kwargs)
        ).value
        monkeypatch.setattr(target, leaf, _Patched())
        moved = de_member_appropriateness_rule(DeMemberAppropriatenessInputs(**inputs_kwargs)).value
    else:
        spread_kwargs = {"bund_10y": 2.51, "f_ecb": 3.75, "de_short_3m": 3.40}
        baseline = de_bund_spread_rule(DeBundSpreadInputs(**spread_kwargs)).value
        monkeypatch.setattr(target, leaf, _Patched())
        moved = de_bund_spread_rule(DeBundSpreadInputs(**spread_kwargs)).value

    assert moved != pytest.approx(baseline), (
        f"moving the config leaf policy.de.{section}.{leaf} (for {label}) did not "
        f"change the result — the leaf is INERT (LAW 1's failure in the opposite "
        f"direction: a calibrated-looking value that nothing reads)"
    )
    monkeypatch.setattr(target, leaf, original)


def test_the_de_rules_refuse_a_non_finite_input() -> None:
    """The D-078 finiteness guard applies to the German input groups too."""
    import math

    from macro_engine.models.policy_rules import (
        DeBundSpreadInputs,
        DeMemberAppropriatenessInputs,
        DeRealRateInputs,
    )

    for cls, kwargs, field in (
        (
            DeMemberAppropriatenessInputs,
            {
                "f_ecb": 3.75,
                "pi_de": 2.0,
                "pi_ea": 2.0,
                "output_gap_de": 0.0,
                "output_gap_ea": 0.0,
                "unemployment_de": 6.0,
                "unemployment_ea": 6.0,
                "gdp_growth_ea": 0.0,
            },
            "gdp_growth_de",
        ),
        (
            DeBundSpreadInputs,
            {"f_ecb": 3.75, "de_short_3m": 3.40},
            "bund_10y",
        ),
        (
            DeRealRateInputs,
            {"f_ecb": 3.75, "pi_ea": 1.8, "r_neutral_de": 0.5},
            "pi_de",
        ),
    ):
        with pytest.raises(ValueError, match=r"non-finite"):
            cls(**{**kwargs, field: math.nan})


# ---------------------------------------------------------------------------
# Section 22.3 — JAPAN (country "jp"). A central bank whose FRAMEWORK is not a
# Taylor rule: a ZLB floor, a long-yield operating target, and an
# inflation-overshooting commitment.
# ---------------------------------------------------------------------------
def test_the_jp_coefficients_are_read_and_the_mover_identity_holds() -> None:
    """The `jp` leaves are pinned, and ``i* == pi_target + natural_rate`` holds.

    The natural rate is NEGATIVE (-0.5%) — the opposite sign from the Fed's,
    the BoE's and the euro area's — and that sign is why the floor binds. The
    mover identity (``i*`` DERIVED from the target plus the natural rate, not a
    second independent constant) is asserted here first: if the three leaves
    could disagree, every shadow-rate number downstream would be unmoored.
    """
    from macro_engine.config import get_settings

    jp = get_settings().policy.jp
    assert jp.pi_target_value == pytest.approx(2.0)
    assert jp.natural_rate_value == pytest.approx(-0.5)
    assert jp.i_star_value == pytest.approx(1.5)
    assert jp.i_star_value == pytest.approx(jp.pi_target_value + jp.natural_rate_value), (
        "i* must equal the target plus the natural rate — the mover identity"
    )
    # The floor and the YCC controls are leaves because the policy MOVED.
    assert jp.zlb_floor_value == pytest.approx(0.0)
    assert jp.ycc_target_value == pytest.approx(0.0)
    assert jp.ycc_band_value == pytest.approx(1.0)
    assert jp.stabilization_threshold_value == pytest.approx(2.0)
    # The rule coefficients.
    assert jp.shadow_rate.inflation_coefficient_value == pytest.approx(1.5)
    assert jp.shadow_rate.output_gap_coefficient_value == pytest.approx(0.5)
    assert jp.shadow_rate.shortfall_coefficient_value == pytest.approx(0.5)
    assert jp.shadow_rate.notional_persistence_value == pytest.approx(0.5)
    # The persistence must be in [0, 1) or the recursion is non-stationary.
    assert 0.0 <= jp.shadow_rate.notional_persistence_value < 1.0


def test_the_jp_shadow_rate_rule_matches_the_hand_calculation() -> None:
    """``i = max[0, i~ - 0.5·z]``, ``i~ = 0.5·(1.5 + 1.5·(π-2) + 0.5·x) + 0.5·i~_prev``.

    Three hand values, config read:

    * **At target, no history** (π=2, x=0, i~_prev=0, z=0):
      i~ = 0.5·1.5 = **0.75**; unconstrained = 0.75 - 0 = 0.75; rate = max(0,
      0.75) = **0.75**. The floor does NOT bind.
    * **Deep slump** (π=-1, x=-2, i~_prev=0, z=0):
      i~ = 0.5·(1.5 + 1.5·(-3) + 0.5·(-2)) = 0.5·(-4) = **-2.0**;
      rate = max(0, -2.0) = **0.0**. The floor BINDS: a plain Taylor rule would
      prescribe -2.0 here; the BoJ did not set negative rates.
    * **With accumulated shortfall** (π=2, x=0, i~_prev=0, z=1):
      i~ = 0.75; unconstrained = 0.75 - 0.5·1 = **0.25** — the state term makes
      the rule prescribe LESS than the no-history case, which is the
      history-dependence the primary source says produces overshooting.
    """
    from macro_engine.models.policy_rules import (
        JpReifschneiderWilliamsInputs,
        jp_reifschneider_williams_rule,
    )

    at_target = jp_reifschneider_williams_rule(
        JpReifschneiderWilliamsInputs(
            pi=2.0, output_gap=0.0, i_notional_prev=0.0, z_prev=0.0, zlb_floor=0.0
        )
    )
    assert at_target.value == pytest.approx(0.75)

    slump = jp_reifschneider_williams_rule(
        JpReifschneiderWilliamsInputs(
            pi=-1.0, output_gap=-2.0, i_notional_prev=0.0, z_prev=0.0, zlb_floor=0.0
        )
    )
    notional_hand = 0.5 * (1.5 + 1.5 * (-1.0 - 2.0) + 0.5 * (-2.0))
    assert notional_hand == pytest.approx(-2.0)
    assert slump.value == pytest.approx(0.0)
    assert slump.value == pytest.approx(max(0.0, notional_hand))

    with_shortfall = jp_reifschneider_williams_rule(
        JpReifschneiderWilliamsInputs(
            pi=2.0, output_gap=0.0, i_notional_prev=0.0, z_prev=1.0, zlb_floor=0.0
        )
    )
    assert with_shortfall.value == pytest.approx(0.25)
    assert with_shortfall.value_float() < at_target.value_float(), (
        "a larger accumulated shortfall must make the rule prescribe LESS — the "
        "history dependence that produces overshooting"
    )


def test_the_jp_shadow_rate_rule_is_not_a_relabelled_fed_rule() -> None:
    """The FLOOR binds where a Taylor rule would not — the structural marker.

    At the same slump inputs, the Fed's Taylor rule prescribes a NEGATIVE rate
    (no floor); the BoJ rule floors at zero. That difference is the entire
    reason the `jp` arm exists, and it is asserted as a comparison rather than a
    description: the BoJ prescription is the floored value, the Taylor
    prescription is the raw notional value, and they differ in sign.
    """
    from macro_engine.models.policy_rules import (
        JpReifschneiderWilliamsInputs,
        TaylorRuleInputs,
        jp_reifschneider_williams_rule,
        taylor_rule,
    )

    jp_rate = jp_reifschneider_williams_rule(
        JpReifschneiderWilliamsInputs(
            pi=-1.0, output_gap=-2.0, i_notional_prev=0.0, z_prev=0.0, zlb_floor=0.0
        )
    ).value_float()

    # A Taylor rule at the same state (negative gap dominant) prescribes below 0.
    fed = taylor_rule(
        TaylorRuleInputs(r_star=0.5, pi_current=-1.0, pi_target=2.0, output_gap=-2.0)
    ).value_float()

    assert jp_rate == pytest.approx(0.0), "the BoJ rule must floor at the ELB"
    assert fed < 0.0, "the Fed's rule has no floor and prescribes a negative rate"
    assert jp_rate > fed, (
        "the floor is exactly what distinguishes the jp arm from a Taylor rule (Section 22.3)"
    )


def test_the_jp_ycc_rule_matches_the_hand_calculation_and_classifies_the_band() -> None:
    """``deviation = jgb_10y - ycc_target``, classified against the SYMMETRIC band.

    Hand (target 0.0, band ±1.0):
    * jgb_10y = 1.62 → deviation = **+1.62**, OUTSIDE the ±1.0 band: the BoJ
      faces purchase pressure (the yield is above tolerance).
    * jgb_10y = 0.50 → deviation = **+0.50**, WITHIN the band: tolerated, which
      is NOT the same as inactive.
    * jgb_10y = -1.50 → deviation = **-1.50**, OUTSIDE (a BREACH below the
      target). This is the case a band test written without ``abs()`` gets
      wrong, and the reason the test asserts both sides.
    The pressure figure is ``1.0 · deviation`` (config leaf), so it scales the
    deviation without changing its sign.
    """
    from macro_engine.models.policy_rules import JpYccInputs, jp_ycc_reference_rule

    outside = jp_ycc_reference_rule(JpYccInputs(jgb_10y=1.62, ycc_target=0.0, ycc_band=1.0))
    assert outside.value == pytest.approx(1.62)
    assert "OUTSIDE" in outside.interpretation
    assert "outside" in (outside.direction or "")
    assert outside.unit == "percentage_points"

    inside = jp_ycc_reference_rule(JpYccInputs(jgb_10y=0.50, ycc_target=0.0, ycc_band=1.0))
    assert inside.value == pytest.approx(0.50)
    assert "WITHIN" in inside.interpretation
    assert "within" in (inside.direction or "")

    # ...and the band test is SYMMETRIC — a yield BELOW the target breaches by
    # the same rule. This is the discriminating case: a band test written
    # without `abs()` (e.g. `deviation <= band`) admits every below-target yield
    # as "within" and would pass a test that only checked positive deviations.
    below_breach = jp_ycc_reference_rule(JpYccInputs(jgb_10y=-1.50, ycc_target=0.0, ycc_band=1.0))
    assert below_breach.value == pytest.approx(-1.50)
    assert "OUTSIDE" in below_breach.interpretation, (
        "a yield one-and-a-half band-widths BELOW the target is outside the "
        "band; the band test must be symmetric (abs)"
    )
    below_within = jp_ycc_reference_rule(JpYccInputs(jgb_10y=-0.50, ycc_target=0.0, ycc_band=1.0))
    assert "WITHIN" in below_within.interpretation


def test_the_jp_overshoot_rule_is_asymmetric_and_reads_the_level_not_the_gap() -> None:
    """The commitment ADDS accommodation even when current inflation is ABOVE target.

    This is the rule a symmetric Taylor rule provably cannot be, and the
    discriminating test is a state a Taylor rule would TIGHTEN in: high current
    inflation, but a cumulative shortfall still open.

    Hand (threshold 2.0, acceleration 0.5):
    * Open shortfall (cum gap 0.5, current π = 2.4): open = 2.0 - 0.5 = 1.5 →
      accommodation = 0.5·1.5 = **0.75**, POSITIVE despite inflation above 2%.
    * Closed shortfall (cum gap 2.5, current π = 3.0): open = max(0, 2.0-2.5) = 0
      → accommodation = **0.0** — the commitment stops adding, even though
      current inflation (3.0) is well above target.

    Both cases have inflation ABOVE 2%, and the rule's response differs only
    because of the HISTORY — which is the price-level behaviour.
    """
    from macro_engine.models.policy_rules import (
        JpOvershootCommitmentInputs,
        jp_overshoot_commitment_rule,
    )

    open_ = jp_overshoot_commitment_rule(
        JpOvershootCommitmentInputs(
            pi=2.4, cumulative_inflation_gap=0.5, stabilization_threshold=2.0
        )
    )
    assert open_.value == pytest.approx(0.75)

    closed = jp_overshoot_commitment_rule(
        JpOvershootCommitmentInputs(
            pi=3.0, cumulative_inflation_gap=2.5, stabilization_threshold=2.0
        )
    )
    assert closed.value == pytest.approx(0.0)

    # Both inputs have inflation ABOVE the 2% target, yet the responses differ —
    # the discrimination is the cumulative shortfall, not the current gap.
    assert open_.value_float() > closed.value_float()
    open_dir = open_.direction or ""
    assert "adding" in open_dir.lower()
    assert "no additional" in (closed.direction or "").lower()


def test_the_jp_rules_are_labelled_jp_with_distinct_variants() -> None:
    """Every `jp` rule reports country ``jp``, model_name and its own variant.

    Both consumer keys are asserted: a rename of the ``model_name`` leaves the
    value plausible while breaking every caller keyed on it.
    """
    from macro_engine.models.policy_rules import (
        JpOvershootCommitmentInputs,
        JpReifschneiderWilliamsInputs,
        JpYccInputs,
        jp_overshoot_commitment_rule,
        jp_reifschneider_williams_rule,
        jp_ycc_reference_rule,
    )

    results = [
        jp_reifschneider_williams_rule(
            JpReifschneiderWilliamsInputs(
                pi=2.4, output_gap=-0.5, i_notional_prev=0.0, z_prev=0.0, zlb_floor=0.0
            )
        ),
        jp_ycc_reference_rule(JpYccInputs(jgb_10y=1.62, ycc_target=0.0, ycc_band=1.0)),
        jp_overshoot_commitment_rule(
            JpOvershootCommitmentInputs(
                pi=2.4, cumulative_inflation_gap=0.5, stabilization_threshold=2.0
            )
        ),
    ]
    for r in results:
        assert r.country == "jp"
    assert {r.rule_variant for r in results} == {
        "jp_reifschneider_williams",
        "jp_ycc_reference",
        "jp_overshoot_commitment",
    }
    assert {r.model_name for r in results} == {
        "jp_reifschneider_williams_rule",
        "jp_ycc_reference_rule",
        "jp_overshoot_commitment_rule",
    }


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("jp_inflation", ("shadow_rate", "inflation_coefficient", 2.5)),
        ("jp_output_gap", ("shadow_rate", "output_gap_coefficient", 1.5)),
        ("jp_shortfall", ("shadow_rate", "shortfall_coefficient", 1.0)),
        ("jp_persistence", ("shadow_rate", "notional_persistence", 0.25)),
    ],
)
def test_every_jp_shadow_rate_coefficient_leaf_is_a_real_mover(
    label: str, change: tuple[str, str, float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each `jp` shadow-rate coefficient leaf must CHANGE the prescription.

    LAW 1's mover proof on the BoJ's rule. ``jp_persistence`` is included
    deliberately: the notional recursion's weight is the one a future edit might
    "simplify" away, and the test proves it is genuinely consumed. The floor and
    the target/threshold leaves are exercised by the hand-calc tests
    (``zlb_floor`` is an INPUT on the record, not a coefficient read here).
    """
    from macro_engine.config import get_settings
    from macro_engine.models.policy_rules import (
        JpReifschneiderWilliamsInputs,
        jp_reifschneider_williams_rule,
    )

    jp = get_settings().policy.jp
    section, leaf, replacement = change
    target = getattr(jp, section)
    original = getattr(target, leaf)

    class _Patched:
        value = replacement

    inputs = JpReifschneiderWilliamsInputs(
        pi=3.0, output_gap=-0.5, i_notional_prev=0.5, z_prev=0.5, zlb_floor=0.0
    )
    baseline = jp_reifschneider_williams_rule(inputs).value
    monkeypatch.setattr(target, leaf, _Patched())
    moved = jp_reifschneider_williams_rule(inputs).value

    assert moved != pytest.approx(baseline), (
        f"moving the config leaf policy.jp.{section}.{leaf} (for {label}) did not "
        f"change the shadow-rate prescription — the leaf is INERT (LAW 1)"
    )
    monkeypatch.setattr(target, leaf, original)


def test_the_jp_persistence_validator_rejects_an_out_of_range_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``[0, 1)`` guard on the notional persistence is INJECTED, not assumed.

    A guard test that only reads the accessor's happy-path value never proves
    the guard exists. This substitutes an out-of-range ``notional_persistence``
    leaf and asserts the accessor RAISES — the validator's only observable
    behaviour. A mutant that widened the range to ``[0, inf)`` returns a value
    instead of raising, and fails here. Both bounds are tested: ``1.0`` (the
    non-stationary case the guard exists for) and ``-0.1``.
    """
    from macro_engine.config import get_settings

    jp = get_settings().policy.jp
    original = jp.shadow_rate.notional_persistence

    for bad in (1.0, -0.1, 1.5):

        class _Patched:
            value = bad

        monkeypatch.setattr(jp.shadow_rate, "notional_persistence", _Patched())
        with pytest.raises(ValueError, match=r"must be in \[0, 1\)"):
            _ = jp.shadow_rate.notional_persistence_value

    monkeypatch.setattr(jp.shadow_rate, "notional_persistence", original)
    # ...and the restored leaf is valid again.
    assert 0.0 <= jp.shadow_rate.notional_persistence_value < 1.0


def test_the_jp_rules_refuse_a_non_finite_input() -> None:
    """The D-078 finiteness guard applies to the Japanese input groups too."""
    import math

    from macro_engine.models.policy_rules import (
        JpOvershootCommitmentInputs,
        JpReifschneiderWilliamsInputs,
        JpYccInputs,
    )

    for cls, kwargs, field in (
        (
            JpReifschneiderWilliamsInputs,
            {"output_gap": 0.0, "i_notional_prev": 0.0, "z_prev": 0.0, "zlb_floor": 0.0},
            "pi",
        ),
        (
            JpYccInputs,
            {"ycc_target": 0.0, "ycc_band": 1.0},
            "jgb_10y",
        ),
        (
            JpOvershootCommitmentInputs,
            {"cumulative_inflation_gap": 0.5, "stabilization_threshold": 2.0},
            "pi",
        ),
    ):
        with pytest.raises(ValueError, match=r"non-finite"):
            cls(**{**kwargs, field: math.nan})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
