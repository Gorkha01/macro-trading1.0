"""Hand-computed verification tests for models/auctions.py (Module 8.2).

Thresholds read from config/settings.yaml (verified by hand):
  weak_bid_to_cover_ratio = 0.95   (weak if btc < btc_avg * 0.95)
  tail_boundary_bp        = 0.0     (tailed if stop_through_bp < 0.0; NEGATIVE = tail)
  indirect_fade_threshold_pp = 3.0   (fading if ind_pct < ind_avg - 3.0)
Both decision thresholds are uncalibrated_illustrative -> confidence
= 0.70 - 0.20 (heuristic) = 0.50.

Sign convention (D-036 trap): stop_through_bp = (expected - clearing), so
NEGATIVE means cleared above expectations = a tail = weak.
"""

from __future__ import annotations

import pytest

from macro_engine.models.auctions import AuctionInputs, auction_demand_signal


def _auction(**kw) -> AuctionInputs:
    base = dict(
        bid_to_cover=3.0,
        bid_to_cover_trailing_avg=2.0,
        indirect_bidder_pct=50.0,
        indirect_bidder_trailing_avg=40.0,
        stop_through_bp=5.0,
    )
    base.update(kw)
    return AuctionInputs(**base)


def test_strong_auction():
    res = auction_demand_signal(_auction())
    assert res.value["verdict"] == "STRONG_AUCTION"
    assert res.value["weak_bid_to_cover"] is False
    assert res.value["tailed"] is False
    assert res.value["foreign_demand_fading"] is False
    assert res.confidence == 0.50


def test_weak_auction():
    res = auction_demand_signal(
        _auction(bid_to_cover=1.0, stop_through_bp=-5.0, indirect_bidder_pct=10.0)
    )
    assert res.value["verdict"] == "WEAK_AUCTION_term_premium_pressure"
    assert res.value["weak_bid_to_cover"] is True
    assert res.value["tailed"] is True
    assert res.value["foreign_demand_fading"] is True


def test_mixed_weak_only():
    res = auction_demand_signal(_auction(bid_to_cover=1.0, stop_through_bp=5.0))
    assert res.value["verdict"] == "MIXED"
    assert res.value["weak_bid_to_cover"] is True
    assert res.value["tailed"] is False


def test_mixed_tailed_only():
    res = auction_demand_signal(_auction(bid_to_cover=3.0, stop_through_bp=-5.0))
    assert res.value["verdict"] == "MIXED"
    assert res.value["weak_bid_to_cover"] is False
    assert res.value["tailed"] is True


def test_tail_boundary_zero_is_not_a_tail():
    # stop_through_bp == tail_boundary_bp (0.0) -> strict '<' means NOT tailed.
    res = auction_demand_signal(_auction(bid_to_cover=3.0, stop_through_bp=0.0))
    assert res.value["tailed"] is False


def test_strong_with_fading_appends_warning():
    res = auction_demand_signal(
        _auction(stop_through_bp=5.0, indirect_bidder_pct=10.0)
    )
    assert res.value["verdict"] == "STRONG_AUCTION"
    assert res.value["foreign_demand_fading"] is True
    assert any("STRONG on price" in w for w in res.warnings)


def test_manual_entry_and_window_in_value():
    res = auction_demand_signal(_auction())
    assert res.value["stop_through_is_manual_entry"] is True
    assert res.value["trailing_window_auctions"] == 6


def test_non_finite_stop_through_rejected():
    with pytest.raises(ValueError):
        AuctionInputs(
            bid_to_cover=3.0,
            bid_to_cover_trailing_avg=2.0,
            indirect_bidder_pct=50.0,
            indirect_bidder_trailing_avg=40.0,
            stop_through_bp=float("nan"),
        )
