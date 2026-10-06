"""``api_layer/orchestration.py`` — the derivations, and two live defects.

The module is where a wrong number can look like a right one (its own words), and
it had **no test file at all** — ``snapshot_to_thesis_inputs`` was referenced by
three routers and zero tests.

Two live defects were found BY this review and are pinned here:

* ``F-ORC-001`` — the labor leg fed ``nfp_3m_avg=0.0`` (asserting "no payroll
  growth") while its warning claimed the NFP weight was "redistributed". Measured:
  the model applies the weight unconditionally, so the fabricated zero dragged the
  score down by 3.0 points on every thesis.
* ``F-ORC-002`` — the 3-month-annualized note's "N-month span" was the constant
  expression ``len(points) - 1 - (len(points) - 4)``, i.e. always 3.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from macro_engine.api_layer import orchestration as orch
from macro_engine.config import get_settings
from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)

AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


def _point(day: date | str, value: float, series: str = "x") -> ObservationPoint:
    d = day if isinstance(day, date) else date.fromisoformat(day)
    return ObservationPoint(observation_date=d, value=value, series_id=series)


def _series(
    values: list[float], *, start: str = "2024-01-01", step_days: int = 30, series: str = "x"
) -> list[ObservationPoint]:
    start_date = date.fromisoformat(start)
    return [
        _point(start_date + timedelta(days=i * step_days), v, series) for i, v in enumerate(values)
    ]


def _monthly(
    values: list[float], *, start_year: int = 2024, series: str = "x"
) -> list[ObservationPoint]:
    """A monthly series whose dates are real first-of-month dates."""
    out = []
    y, m = start_year, 1
    for v in values:
        out.append(_point(date(y, m, 1), v, series))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# ---------------------------------------------------------------------------
# (F-ORC-001) the labor leg's NFP block
# ---------------------------------------------------------------------------


def _labor_snapshot() -> MacroDataSnapshot:
    return MacroDataSnapshot(
        as_of=AS_OF,
        data_quality_flags=[],
        initial_claims=_series([200_000 + i for i in range(12)], series="initial_claims"),
        jolts_openings=_monthly([7000.0 + i for i in range(24)], series="jolts_openings"),
        jolts_quits=_monthly([2.0 + i * 0.01 for i in range(24)], series="jolts_quits"),
    )


def test_the_nfp_block_is_fed_the_neutral_pace_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-ORC-001) ``0.0`` asserts "no payroll growth" — a fabricated reading.

    The module's own docstring calls that out as the trap; the code did it
    anyway. Measured: ``weight_nfp * (0 - neutral) / divisor = 0.2 * -15 = -3.0``
    points, a systematic tilt toward "loosening" on every thesis.
    """
    from macro_engine.models.labor_synthesis import (
        LaborInputs,
    )
    from macro_engine.models.labor_synthesis import (
        labor_tightness_score as real,
    )

    seen: list[LaborInputs] = []

    def spy(inputs: LaborInputs) -> object:
        seen.append(inputs)
        return real(inputs)

    monkeypatch.setattr(orch, "labor_tightness_score", spy)
    result, _notes, warnings = orch._labor_leg(_labor_snapshot(), as_of=AS_OF)

    neutral = get_settings().labor.neutral_nfp_pace
    assert len(seen) == 1
    assert seen[0].nfp_3m_avg == pytest.approx(neutral), (
        "the NFP block must be fed the neutral pace, not a fabricated 0.0"
    )
    assert seen[0].nfp_3m_avg != 0.0
    assert result.value == real(seen[0]).value
    assert "COMPRESSED 20%" in " ".join(warnings)


def test_the_labor_warning_does_not_claim_a_redistribution() -> None:
    """(F-ORC-001) ``labor_tightness_score`` cannot redistribute a block's weight.

    It applies ``weight_nfp`` unconditionally, so the disclosure must say
    "compressed", not "redistributed" — a reader comparing this score against a
    3-block one needs to know it is on a narrower scale.
    """
    _result, _notes, warnings = orch._labor_leg(_labor_snapshot(), as_of=AS_OF)
    joined = " ".join(warnings)
    assert "redistributed" not in joined
    assert "NFP MISSING" in joined
    assert "2-of-3-block" in joined


# ---------------------------------------------------------------------------
# (F-ORC-002) the annualized-momentum note's span
# ---------------------------------------------------------------------------


def test_the_momentum_note_reports_the_actual_span_not_a_constant() -> None:
    """(F-ORC-002) The old expression was a constant 3 for every input.

    A series with a missing month therefore reported "a 3-month span" over a
    four-month gap — the mislabelled window the sibling ``_trailing_percentile``
    avoids by reporting what it actually used.
    """
    contiguous = _monthly([100.0, 101.0, 102.0, 103.0])
    snapshot = MacroDataSnapshot(as_of=AS_OF, data_quality_flags=[], cpi_headline=contiguous)
    _momentum, described = orch._inflation_momentum_3m(snapshot, as_of=AS_OF)
    assert "a 3-month span" in described

    # Drop a month from the middle: points[-4] is now four months back.
    gapped = _monthly([100.0, 101.0, 102.0, 103.0])
    gapped = [gapped[0], gapped[1], gapped[3]]  # Jan, Feb, Apr
    gapped.append(_point(date(2024, 5, 1), 104.0))
    snapshot = MacroDataSnapshot(as_of=AS_OF, data_quality_flags=[], cpi_headline=gapped)
    _momentum, described = orch._inflation_momentum_3m(snapshot, as_of=AS_OF)
    assert "a 4-month span" in described, described


# ---------------------------------------------------------------------------
# the series primitives
# ---------------------------------------------------------------------------


def test_mom_percent_divides_by_the_prior_observation() -> None:
    """The divisor is the PRIOR point; getting it backwards flips an acceleration."""
    change, described = orch._mom_percent(_series([100.0, 110.0]), field="f")
    assert change == pytest.approx(10.0)
    assert "110" in described and "100" in described


def test_mom_percent_refuses_a_zero_prior() -> None:
    with pytest.raises(orch.OrchestrationError, match="zero prior observation"):
        orch._mom_percent(_series([0.0, 110.0]), field="f")


def test_yoy_percent_pairs_the_anniversary_not_a_neighbouring_month() -> None:
    """A 29-day comparison must not be labelled year-over-year."""
    points = _monthly([100.0] * 12 + [110.0])  # Jan..Dec 2024 then Jan 2025
    change, described = orch._yoy_percent(points, field="f")
    assert change == pytest.approx(10.0)
    assert "0 day(s) off the anniversary" in described


def test_yoy_percent_refuses_when_the_anniversary_is_too_far_away() -> None:
    """The tolerance is what makes the "year-over-year" label honest."""
    # The latest is 2025-06-01, whose anniversary is 2024-06-01. The closest
    # point at or before it is 2024-05-01 — 31 days away, well beyond the 5-day
    # tolerance, so the ratio would compare May against June and call it annual.
    points = [
        _point(date(2024, 5, 1), 100.0),
        _point(date(2025, 1, 1), 101.0),
        _point(date(2025, 3, 1), 102.0),
        _point(date(2025, 5, 1), 103.0),
        _point(date(2025, 6, 1), 104.0),
    ]
    with pytest.raises(orch.OrchestrationError, match="beyond the"):
        orch._yoy_percent(points, field="f")


def test_minus_one_year_clamps_a_leap_day() -> None:
    assert orch._minus_one_year(date(2024, 2, 29)) == date(2023, 2, 28)
    assert orch._minus_one_year(date(2024, 3, 1)) == date(2023, 3, 1)


def test_minus_months_clamps_the_day_of_month() -> None:
    assert orch._minus_months(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert orch._minus_months(date(2026, 5, 31), 3) == date(2026, 2, 28)
    assert orch._minus_months(date(2026, 10, 6), 12) == date(2025, 10, 6)


def test_trailing_percentile_reports_the_window_it_used() -> None:
    """A narrowed window makes an ordinary reading look extreme — so it is reported."""
    points = _monthly([float(v) for v in range(1, 13)])
    percentile, window = orch._trailing_percentile(points, field="f")
    assert percentile == 100.0  # the latest is the series high
    assert window == len(points)  # shorter than the 36-month intent, and said so


def test_trailing_percentile_low_is_not_zero() -> None:
    points = _monthly([float(v) for v in range(12, 0, -1)])
    percentile, _window = orch._trailing_percentile(points, field="f")
    assert percentile == pytest.approx(100.0 / 12.0)  # 100/n, not 0.0


def test_claims_change_uses_non_overlapping_windows() -> None:
    """``avg(last4)/avg(-3:-7)`` shares three points and compresses the change."""
    points = _series([100.0] * 4 + [200.0] * 4, series="initial_claims")
    change, described = orch._claims_4wk_change(points, field="initial_claims")
    assert change == pytest.approx(100.0)  # 200 vs 100, not a compressed figure
    assert "4wk avg" in described


def test_claims_change_needs_eight_points() -> None:
    with pytest.raises(orch.OrchestrationError, match="needs 8"):
        orch._claims_4wk_change(_series([1.0] * 7), field="initial_claims")


def test_latest_on_or_before_is_inclusive_and_none_when_too_early() -> None:
    dates = [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1)]
    assert orch._latest_on_or_before(dates, date(2026, 4, 1)) == date(2026, 4, 1)
    assert orch._latest_on_or_before(dates, date(2026, 5, 1)) == date(2026, 4, 1)
    assert orch._latest_on_or_before(dates, date(2025, 12, 31)) is None


# ---------------------------------------------------------------------------
# the entry point's boundary
# ---------------------------------------------------------------------------


def test_a_non_us_snapshot_is_refused() -> None:
    snapshot = MacroDataSnapshot(country="de", as_of=AS_OF, data_quality_flags=[])
    with pytest.raises(NotImplementedError, match="implemented for country 'us' only"):
        orch.snapshot_to_thesis_inputs(snapshot)


def test_curve_legs_on_a_non_curve_thesis_are_reported_not_dropped() -> None:
    """D-037's inert-input class: a caller who set them expected them to matter."""
    result = orch.snapshot_to_thesis_inputs(
        _full_snapshot(), curve_short_tenor="2y", curve_long_tenor="10y"
    )
    assert any("CURVE LEGS IGNORED" in w for w in result.warnings)
    assert result.thesis_type.value == get_settings().api.default_thesis_type


def _full_snapshot() -> MacroDataSnapshot:
    """A snapshot with every required series populated, for the entry-point tests."""
    return MacroDataSnapshot(
        as_of=AS_OF,
        data_quality_flags=[],
        gdp_real=_monthly([20_000.0 + i for i in range(24)], series="gdp_real"),
        gdp_potential=_monthly([20_500.0 + i for i in range(24)], series="gdp_potential"),
        cpi_headline=_monthly([300.0 + i for i in range(24)], series="cpi_headline"),
        cpi_core=_monthly([310.0 + i for i in range(24)], series="cpi_core"),
        pce_core=_monthly([120.0 + i for i in range(24)], series="pce_core"),
        initial_claims=_series([200_000 + i for i in range(12)], series="initial_claims"),
        jolts_openings=_monthly([7000.0 + i for i in range(24)], series="jolts_openings"),
        jolts_quits=_monthly([2.0 + i * 0.01 for i in range(24)], series="jolts_quits"),
        iorb=_monthly([4.3] * 24, series="iorb"),
        yield_curve=YieldCurveSnapshot(
            as_of=AS_OF.date(),
            tenors={"2yr": 4.3, "10yr": 4.5, "30yr": 4.7},
        ),
    )


def test_the_entry_point_derives_every_required_argument() -> None:
    result = orch.snapshot_to_thesis_inputs(_full_snapshot())
    assert result.reads.growth.model_name
    assert result.reads.inflation.model_name
    assert result.reads.labor.model_name
    assert isinstance(result.short_yield, float)
    assert result.thesis_type.value == get_settings().api.default_thesis_type
    assert result.notes, "the derivation must travel with the inputs"
    assert any(n.name == "thesis_type" for n in result.notes)
