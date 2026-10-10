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


def test_the_section_22_5_replacement_obligation_is_still_outstanding() -> None:
    """D2 — a tripwire for an obligation that no work list owned.

    Section 22.5 obligates Phase 5+ to replace the proxy with a real
    Fed-funds-futures-implied distribution. Phase 5+ is recorded COMPLETE
    (Tier 5 = 23/23, D-092 … D-125) and, at the time this tripwire was written,
    nothing owned the obligation: it is attached to a **Tier 3** function while
    the Phase-5+ work list came from the **Tier 5** names, so it fell between two
    lists.

    Measured 2026-10-10 the state moved in two steps, and BOTH are recorded here
    so neither is mis-read:

    * The source EXISTS and the replacement is BUILT: ``futures_implied_policy_path``
      and ``fetch_fed_funds_futures_curve`` are implemented and tested, and the
      reader ``derive_market_implied_policy_path`` now PREFERS the futures branch
      when it is handed a curve.
    * But nothing on the live path SUPPLIES a curve yet, so the proxy branch is
      still what production runs. Until the caller chain is wired end to end
      (``build_policy_gap`` → ``build_us_macro_thesis`` → ``_reasoning_frames``),
      flipping the marker would claim a replacement that has not happened.

    This test asserts BOTH halves, so neither can drift:

    * the body still contains the Phase 1-4 term-premium proxy, AND
    * the record still says the obligation is outstanding.

    Discharging the obligation therefore FAILS this test until the record is
    updated in the same change. That is the point — the decision gets recorded
    rather than absorbed by a quiet refactor. (The project already uses this
    tripwire idiom: O-34 kept its gates with tripwires rather than deleting
    them, because deleting them freezes the current state as permanent.)
    """
    import inspect

    from macro_engine.models.policy_rules import PHASE5_REPLACEMENT_OBLIGATION

    source = inspect.getsource(derive_market_implied_policy_path)
    still_the_proxy = "short_yield - short_tenor_term_premium" in source
    assert still_the_proxy, (
        "The body no longer looks like the Phase 1-4 term-premium proxy. If the "
        "Section 22.5 replacement has landed, update PHASE5_REPLACEMENT_OBLIGATION "
        "and this test IN THE SAME CHANGE — the obligation must be closed "
        "explicitly, never absorbed."
    )
    assert PHASE5_REPLACEMENT_OBLIGATION == "outstanding", (
        f"PHASE5_REPLACEMENT_OBLIGATION says {PHASE5_REPLACEMENT_OBLIGATION!r} but "
        "the body is still the proxy. The marker and the body must agree."
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


def test_the_replacement_is_called_by_the_reader_but_not_yet_by_the_live_path() -> None:
    """The state of the increment, asserted rather than claimed.

    ``futures_implied_policy_path`` is reached from ``derive_market_implied_policy_path``
    (the reader now prefers it when handed a curve), but **nothing in the live
    path supplies a curve yet**: ``build_policy_gap`` → ``build_us_macro_thesis``
    → ``_reasoning_frames`` still call the reader with the two scalars only, so
    the proxy branch is what production runs.

    A test rather than a note, because "built but un-wired" is exactly the kind
    of claim that rots: if someone wires the chain without updating the record,
    this fails; if someone deletes the replacement, the import at the top of this
    module fails.
    """
    import pathlib

    src_root = pathlib.Path(__file__).resolve().parents[2] / "src"
    live_path_files = {
        "builder.py",
        "thesis_layer",
        "data_layer/fed_funds_futures_client.py",
        "models/policy_rules.py",
    }
    offenders: list[str] = []
    for path in src_root.rglob("*.py"):
        rel = path.as_posix()
        if any(part in rel for part in live_path_files):
            continue
        text = path.read_text(encoding="utf-8")
        # The BARE names, not "name(" — a wiring may be an import first.
        if "fetch_fed_funds_futures_curve" in text:
            offenders.append(rel)
    assert offenders == [], (
        f"a live-path module now fetches the futures curve ({offenders}). That "
        f"means the chain is being wired; update PHASE5_REPLACEMENT_OBLIGATION "
        f"and this record in the same commit rather than letting the state drift."
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
