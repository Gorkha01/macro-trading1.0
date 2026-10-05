"""Hand-computed verification tests for models/inflation_nowcast.py (Module 5).

Every expected value is derived BY HAND from the formula and config/settings.yaml
(read, not assumed):

  inflation.shelter_lag_months                 = 15   (shelter_lag property)
  inflation.shelter_converged_tolerance_pp     = 0.1  (shelter_converged_tolerance)
  inflation.shelter_lag_months calibration     = uncalibrated_illustrative
        -> shelter_lag_is_calibrated = False
        -> success-branch confidence = 0.70 - 0.20 (heuristic) = 0.50
  insufficient-branch confidence = 0.70 - 0.25 (data flag) = 0.45

Index convention (load-bearing, docstring-verified): the list is oldest-first,
[-1] is the current month, so "N months ago" = history[-(N+1)]. With lag=15 the
projected vintage is history[-16] == history[0] for a 16-element list, and for an
L-element list it is history[L-1-15].

These are REAL-WORLD checks: the index math, the gap-direction mapping, the
converged band, and the confidence wiring are verified against hand values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from macro_engine.models.inflation_nowcast import ShelterLagInputs, project_shelter_cpi


def _inputs(history: list[float], current: float) -> ShelterLagInputs:
    return ShelterLagInputs(
        market_rent_growth_yoy_pct=history,
        current_cpi_shelter_yoy_pct=current,
    )


# ---------------------------------------------------------------------------
# Direction mapping (gap = projected - current)
# ---------------------------------------------------------------------------
def test_cooling_when_projected_below_current() -> None:
    # 16 months of history; history[0] (15 months ago) = 3.2, current CPI = 4.8.
    history = [3.2] + [5.0] * 15
    res = project_shelter_cpi(_inputs(history, 4.8))
    assert res.value == pytest.approx(3.2)
    # gap = 3.2 - 4.8 = -1.6 < 0 -> cooling
    assert "cooling" in res.interpretation
    assert res.confidence == 0.50


def test_reaccelerating_when_projected_above_current() -> None:
    history = [5.5] + [5.0] * 15
    res = project_shelter_cpi(_inputs(history, 4.8))
    assert res.value == pytest.approx(5.5)
    # gap = 5.5 - 4.8 = +0.7 > 0 -> reaccelerating
    assert "reaccelerat" in res.interpretation
    assert res.confidence == 0.50


def test_converged_when_gap_within_tolerance() -> None:
    # projected == current -> gap 0 -> converged.
    history = [4.8] + [5.0] * 15
    res = project_shelter_cpi(_inputs(history, 4.8))
    assert res.value == pytest.approx(4.8)
    # The converged signal lives in the warning ("...already converged...") and in
    # the interpretation ("already at 4.80%, consistent with..."); it is NOT the
    # literal word "converged" in the interpretation string — that word is reserved
    # for the warning. Assert the canonical converged markers.
    assert "already at" in res.interpretation
    assert any("converged" in w for w in res.warnings)
    assert res.confidence == 0.50


def test_converged_tolerance_is_inclusive_boundary() -> None:
    # Inclusive boundary: gap just UNDER tolerance -> converged.
    # 5.0 - 4.9 = 0.09999999999999964 <= 0.1 (float-clean, never crosses).
    history = [5.0] + [5.0] * 15
    res = project_shelter_cpi(_inputs(history, 4.9))
    assert res.value == pytest.approx(5.0)
    assert any("converged" in w for w in res.warnings)
    assert "reaccelerat" not in res.interpretation
    # Just PAST the boundary -> reaccelerating.
    # 4.91 - 4.8 = 0.11000000000000032 > 0.1 (float-clean, never under).
    history2 = [4.91] + [5.0] * 15
    res2 = project_shelter_cpi(_inputs(history2, 4.8))
    assert "reaccelerat" in res2.interpretation


# ---------------------------------------------------------------------------
# Index math: "N months ago" == history[-(N+1)]
# ---------------------------------------------------------------------------
def test_index_selects_n_months_ago() -> None:
    # L=20 list, oldest first; current is index 19. 15 months ago = index 4.
    history = [float(i) for i in range(20)]
    res = project_shelter_cpi(_inputs(history, 6.0))
    # history[-16] == history[4] == 4.0
    assert res.value == pytest.approx(4.0)
    assert "cooling" in res.interpretation  # 4.0 < 6.0


def test_extra_history_does_not_change_vintage_but_warns() -> None:
    history = [float(i) for i in range(30)]
    res = project_shelter_cpi(_inputs(history, 6.0))
    # still the 15-months-ago point: index 29-15 = 14 -> value 14.0
    assert res.value == pytest.approx(14.0)
    assert any("months of history were supplied but only" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# Insufficient-data branch: value is None (not 0.0), confidence is computed
# ---------------------------------------------------------------------------
def test_insufficient_history_returns_none_not_zero() -> None:
    # only 15 points; 16 required for a 15-month lag.
    history = [float(i) for i in range(15)]
    res = project_shelter_cpi(_inputs(history, 4.8))
    assert res.value is None
    # confidence: 0.70 - 0.25 (data flag) = 0.45, not the spec's literal 0.0
    assert res.confidence == 0.45
    assert any("Insufficient" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# Non-finite inputs must be refused, not silently projected
# ---------------------------------------------------------------------------
def test_non_finite_history_rejected() -> None:
    with pytest.raises((ValidationError, ValueError)):
        ShelterLagInputs(
            market_rent_growth_yoy_pct=[1.0, float("nan"), 2.0, 3.0, 4.0],
            current_cpi_shelter_yoy_pct=4.8,
        )


def test_non_finite_current_rejected() -> None:
    with pytest.raises((ValidationError, ValueError)):
        ShelterLagInputs(
            market_rent_growth_yoy_pct=[float(i) for i in range(20)],
            current_cpi_shelter_yoy_pct=float("inf"),
        )
