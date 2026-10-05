"""Fresh test suite for ``macro_engine.models.gdp_nowcast`` (Module 7 / 7.1 / 7.5).

Written from scratch after the deleted self-confirming suite. Every fixture is
hand-derived; no network fetch is attempted (all three public functions take
floats / dicts directly).

Locks in:
* F-GDP-002 — ``output_gap`` and ``gdp_gdi_divergence`` derive their
  ``relation`` / ``interpretation`` / ``direction`` from the PUBLISHED (rounded)
  value, not the raw float. The regression tests below fail if a future edit
  re-derives any of them from the raw number (value 0.0 next to "expansionary").
* F-GDP-001 — ``_quarter_annualized_mom`` scales by ``months_per_quarter`` (x3),
  NOT by 12. The shipped x3 form is what the recorded accuracy block
  (mean_abs_error 3.0261, correlation -0.0922, ratio 0.5052) was measured
  against (re-measured read-only on 137 quarters of live FRED data). The tests
  lock the x3 behaviour and the recorded stats so a silent "fix" to x12 is
  caught — changing to x12 would require a full re-measurement of the ``accuracy``
  block, not an isolated edit.
"""

from __future__ import annotations

import pytest

from macro_engine.config import get_settings
from macro_engine.models.gdp_nowcast import (
    GdpGdiInputs,
    OutputGapInputs,
    SimpleGDPNowcastInputs,
    _quarter_annualized_mom,
    gdp_gdi_divergence,
    output_gap,
    simple_gdp_nowcast,
)

# ---------------------------------------------------------------------------
# output_gap (Tier 1)
# ---------------------------------------------------------------------------


def test_output_gap_known_value() -> None:
    res = output_gap(OutputGapInputs(actual_gdp=24200.0, potential_gdp=24000.0))
    # (24200 - 24000) / 24000 * 100 = 0.8333... -> 0.83
    assert res.value == pytest.approx(0.83, abs=1e-9)
    assert (res.direction or "").startswith("expansionary")
    assert "0.83%" in res.interpretation


def test_output_gap_exact_zero_is_third_state() -> None:
    """F-GDP-002: a gap of exactly 0.0 reads 'at potential', not a direction."""
    res = output_gap(OutputGapInputs(actual_gdp=24200.0, potential_gdp=24200.0))
    assert res.value == 0.0
    assert res.direction == "neutral: at potential"
    assert res.interpretation == "Output gap: 0.00% (at potential)"


def test_output_gap_published_consistency_when_raw_rounds_to_zero() -> None:
    """F-GDP-002 regression: a tiny positive gap that rounds to 0.0 must NOT
    publish 'expansionary'. Before the fix, value=0.0 sat next to
    direction='expansionary: economy above sustainable capacity'."""
    res = output_gap(OutputGapInputs(actual_gdp=24200.1, potential_gdp=24200.0))
    # gap_pct = 0.1 / 24200 * 100 = 0.000413... -> rounds to 0.00
    assert res.value == 0.0
    assert res.direction == "neutral: at potential"
    # F-GDP-002: the reading MUST be derived from the *published* (rounded) value,
    # not the raw float. `relation` is not a ModelResult field; the consistency
    # shows up as "(at potential)" in the interpretation, never "(above/below)".
    assert res.interpretation == "Output gap: 0.00% (at potential)"


def test_output_gap_negative_gap_is_slack() -> None:
    res = output_gap(OutputGapInputs(actual_gdp=23800.0, potential_gdp=24000.0))
    # (23800 - 24000) / 24000 * 100 = -0.8333... -> -0.83
    assert res.value == pytest.approx(-0.83, abs=1e-9)
    assert (res.direction or "").startswith("slack")


def test_output_gap_rejects_nonpositive_potential() -> None:
    with pytest.raises(ValueError):
        OutputGapInputs(actual_gdp=100.0, potential_gdp=0.0)


# ---------------------------------------------------------------------------
# gdp_gdi_divergence (Tier 2, Module 7.1)
# ---------------------------------------------------------------------------


def test_gdi_exact_zero_is_third_state() -> None:
    """F-GDP-002: GDP == GDI reads 'agree exactly', not a direction."""
    res = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=2.5, gdi_growth_pct=2.5))
    assert res.value_dict()["divergence_pp"] == 0.0
    assert (res.direction or "").startswith("the two estimates agree exactly")
    assert res.value_dict()["significant"] is False  # |0| > threshold is False


def test_gdi_near_zero_also_reads_as_agreement() -> None:
    """F-GDP-002: 2.5 vs 2.5000001 -> raw diff -1e-7, published rounds to -0.0,
    so direction is 'agree exactly', not 'GDI-side leads by -0.00pp'."""
    res = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=2.5, gdi_growth_pct=2.5000001))
    assert res.value_dict()["divergence_pp"] == -0.0
    assert (res.direction or "").startswith("the two estimates agree exactly")


def test_gdi_significant_uses_raw_diff_but_direction_uses_published() -> None:
    """F-GDP-002 design: `significant` is computed on the RAW diff (so the
    recorded 21.7% base rate is preserved), but `divergence_pp` and `direction`
    are from the PUBLISHED (rounded) value. Lock both."""
    settings = get_settings().gdp_gdi
    thr = settings.significance_threshold
    gdp, gdi = 3.7, 1.2  # raw diff = +2.5, clearly significant
    res = gdp_gdi_divergence(GdpGdiInputs(gdp_growth_pct=gdp, gdi_growth_pct=gdi))
    raw_diff = gdp - gdi
    assert res.value_dict()["significant"] is (abs(raw_diff) > thr)
    assert res.value_dict()["divergence_pp"] == round(raw_diff, 4)
    # direction is derived from the published (rounded) diff, i.e. +2.5 -> GDP-side
    assert (res.direction or "").startswith("GDP-side")


def test_gdi_rejects_nonfinite() -> None:
    with pytest.raises(ValueError):
        GdpGdiInputs(gdp_growth_pct=float("nan"), gdi_growth_pct=1.0)


# ---------------------------------------------------------------------------
# _quarter_annualized_mom — F-GDP-001 x3 lock
# ---------------------------------------------------------------------------


def test_quarter_annualized_mom_scales_by_months_per_quarter_not_12() -> None:
    """F-GDP-001: the function multiplies the averaged monthly change by
    `months_per_quarter` (config = 3), NOT by 12. A 0.5% monthly change yields
    1.5 (the quarter's summed monthly rate), not 6.0. The recorded accuracy
    stats were measured against this x3 form; an x12 change would invalidate them
    without a full re-measurement."""
    mpq = get_settings().gdp_nowcast.months_per_quarter
    assert mpq == 3
    out = _quarter_annualized_mom([0.5, 0.5, 0.5], mpq)
    assert out == pytest.approx(1.5, abs=1e-9)
    # Explicitly guard against the old docstring's claimed x12 behaviour:
    assert out != pytest.approx(6.0, abs=1e-9)


def test_quarter_annualized_mom_empty_raises() -> None:
    with pytest.raises(ValueError):
        _quarter_annualized_mom([], 3)


# ---------------------------------------------------------------------------
# simple_gdp_nowcast (Tier 2, Module 7.5)
# ---------------------------------------------------------------------------


def _valid_inputs(prior: float, trade_pct: float = 0.0) -> SimpleGDPNowcastInputs:
    return SimpleGDPNowcastInputs(
        retail_sales_mom={"2026-Q2": [0.0, 0.0, 0.0]},
        durable_goods_mom={"2026-Q2": [0.0, 0.0, 0.0]},
        trade_balance_mom={"2026-Q2": [trade_pct, trade_pct, trade_pct]},
        prior_quarter_annualized=prior,
    )


def test_simple_nowcast_refuses_nonfinite_prior() -> None:
    with pytest.raises(ValueError):
        SimpleGDPNowcastInputs(
            retail_sales_mom={"2026-Q2": [0.0, 0.0, 0.0]},
            durable_goods_mom={"2026-Q2": [0.0, 0.0, 0.0]},
            trade_balance_mom={"2026-Q2": [0.0, 0.0, 0.0]},
            prior_quarter_annualized=float("nan"),
        )


def test_simple_nowcast_refuses_incomplete_quarter() -> None:
    with pytest.raises(ValueError, match="complete set"):
        simple_gdp_nowcast(
            SimpleGDPNowcastInputs(
                retail_sales_mom={"2026-Q2": [1.0, 2.0]},  # only 2 of 3 months
                durable_goods_mom={"2026-Q2": [0.0, 0.0, 0.0]},
                trade_balance_mom={"2026-Q2": [0.0, 0.0, 0.0]},
                prior_quarter_annualized=2.0,
            )
        )


def test_simple_nowcast_publishes_recorded_accuracy_record() -> None:
    """F-GDP-001 lock: the model must keep publishing the MEASURED record, not a
    recomputed one. If a future edit alters the annualization factor or the
    weights, this test fails loudly instead of silently changing the published
    accuracy. Values are read from config (the single source of the record)."""
    acc = get_settings().gdp_nowcast.accuracy
    res = simple_gdp_nowcast(_valid_inputs(prior=2.0))
    v = res.value_dict()
    assert v["mean_abs_error_pp"] == acc.mean_abs_error
    assert v["persistence_mean_abs_error_pp"] == acc.persistence_mean_abs_error
    assert v["correlation_with_realised"] == acc.correlation
    assert v["quarters_measured"] == acc.quarters
    assert v["realised_positive_share"] == acc.realised_positive_share
    assert v["delta_overweighting_ratio"] == acc.delta_overweighting_ratio
    # The shipped form does NOT beat persistence (D-034/D-035 finding).
    assert v["beats_persistence"] is False


def test_simple_nowcast_net_exports_sign_correction() -> None:
    """D-034 correction: a widening trade deficit (positive pct change of the
    all-negative BOPGSTB balance) must LOWER the nowcast. The negative
    net-exports weight makes the contribution negative even though the input
    percent change is positive."""
    res = simple_gdp_nowcast(_valid_inputs(prior=2.0, trade_pct=1.0))
    v = res.value_dict()
    assert v["net_exports_contribution"] < 0.0
    assert v["nowcast_annualized"] < 2.0  # nowcast fell below the prior print


def test_simple_nowcast_published_gdpnow_cross_check() -> None:
    res = simple_gdp_nowcast(
        SimpleGDPNowcastInputs(
            retail_sales_mom={"2026-Q2": [0.0, 0.0, 0.0]},
            durable_goods_mom={"2026-Q2": [0.0, 0.0, 0.0]},
            trade_balance_mom={"2026-Q2": [0.0, 0.0, 0.0]},
            prior_quarter_annualized=2.0,
            published_gdpnow=1.5,
        )
    )
    v = res.value_dict()
    assert "gdpnow_cross_check_pp" in v
    assert v["gdpnow_cross_check_pp"] == pytest.approx(v["nowcast_annualized"] - 1.5, abs=1e-9)


def test_simple_nowcast_persistence_benchmark_is_reported() -> None:
    """The nowcast with zero monthly movement equals the prior quarter (delta 0),
    confirming the delta is additive on top of `prior_quarter_annualized`."""
    res = simple_gdp_nowcast(_valid_inputs(prior=2.0))
    v = res.value_dict()
    assert v["delta"] == pytest.approx(0.0, abs=1e-9)
    assert v["nowcast_annualized"] == pytest.approx(2.0, abs=1e-9)
