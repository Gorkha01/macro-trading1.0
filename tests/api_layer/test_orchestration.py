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


def _gb_snapshot() -> MacroDataSnapshot:
    """A UK snapshot carrying each of the six series the gb derivation reads.

    Built from the same point constructors as the US helpers, so the UK path is
    exercised through the real ``snapshot_to_thesis_inputs`` rather than a
    hand-written ``ThesisInputs`` — the point of the end-to-end wiring is that
    the derivation runs, not that a record can be constructed.

    The values are deliberately plausible rather than arbitrary: headline CPI
    a little above the 2% target, core below headline (so the derived energy leg
    is positive), Bank Rate near the short rate, and quarterly GDP growth
    varying so the mean-relative gap is a non-trivial number. A snapshot of
    constants would make the gap zero and the rule outputs coincide, hiding any
    dispatch error.
    """
    return MacroDataSnapshot(
        country="gb",
        as_of=AS_OF,
        data_quality_flags=[],
        gb_cpi_headline=_monthly([3.4, 3.6, 3.5, 3.7, 3.6, 3.8], series="gb_cpi_headline"),
        gb_cpi_core=_monthly([3.1, 3.2, 3.2, 3.3, 3.3, 3.4], series="gb_cpi_core"),
        gb_unemployment_rate=_monthly(
            [4.2, 4.3, 4.3, 4.4, 4.4, 4.4], series="gb_unemployment_rate"
        ),
        gb_gdp_growth_qoq=_series([0.1, 0.3, 0.2, 0.4, 0.2, 0.5], series="gb_gdp_growth_qoq"),
        gb_bank_rate=_series([5.0, 4.75, 4.5, 4.25], series="gb_bank_rate"),
        gb_short_rate_3m=_series([4.6, 4.5, 4.4, 4.35], series="gb_short_rate_3m"),
    )


def test_an_unimplemented_country_snapshot_is_refused() -> None:
    """(§22.3) a country NOT in ``implemented`` is refused; the message names the set.

    The guard no longer reads a literal ``"us"`` — it reads
    ``country.implemented``, so each multi-country increment is admitted as it
    lands while countries not yet built are still refused. ``fr`` (France) has
    no series set, no reaction function and no instrument universe — it is the
    honest example of "not implemented". The assertion is on the BEHAVIOUR (the
    code raises) and on the message naming the implemented set, not on any
    particular country literal, which would have made this test the thing that
    blocked an increment rather than the thing that guards the boundary.
    """
    snapshot = MacroDataSnapshot(country="fr", as_of=AS_OF, data_quality_flags=[])
    with pytest.raises(NotImplementedError, match="implemented for"):
        orch.snapshot_to_thesis_inputs(snapshot)


def test_de_and_jp_are_admitted_now_that_they_are_implemented() -> None:
    """(§22.3) de and jp are NOT refused any more — they reached their derivations.

    The counterpart to the refusal test above, extended to the third and fourth
    increments. ``de`` and ``jp`` are in ``country.implemented``, so a snapshot
    for either must reach its own derivation rather than the guard's
    ``NotImplementedError``. This is what would fail if the config and the
    dispatch ever drifted apart.
    """
    for code, attr in (("de", "de_inputs"), ("jp", "jp_inputs")):
        snapshot = _snapshot_for_country(code)
        inputs = orch.snapshot_to_thesis_inputs(snapshot)
        assert inputs.country == code
        assert getattr(inputs, attr) is not None, f"{code} derivation produced no {attr}"
        # The other countries' records must be None — one country's inputs only.
        assert inputs.boe_inputs is None
        assert inputs.eu_inputs is None


def test_an_implemented_country_snapshot_is_admitted() -> None:
    """(§22.3) gb is NOT refused by the country guard any more.

    The counterpart to the test above: a country in ``country.implemented``
    reaches its own derivation. If this fails with the guard's
    ``NotImplementedError``, the config and the guard have drifted apart.
    """
    snapshot = _gb_snapshot()
    inputs = orch.snapshot_to_thesis_inputs(snapshot)
    assert inputs.country == "gb"
    assert inputs.boe_inputs is not None
    assert inputs.taylor_inputs is None
    assert inputs.first_difference_inputs is None


def test_curve_legs_on_a_non_curve_thesis_are_reported_not_dropped() -> None:
    """D-037's inert-input class: a caller who set them expected them to matter."""
    result = orch.snapshot_to_thesis_inputs(
        _full_snapshot(), curve_short_tenor="2y", curve_long_tenor="10y"
    )
    assert any("CURVE LEGS IGNORED" in w for w in result.warnings)
    assert result.thesis_type.value == get_settings().api.default_thesis_type


# ---------------------------------------------------------------------------
# Section 22.3 — the euro-area derivation's UNITS (two real defects repaired)
#
# Both defects returned a plausible-looking number of the WRONG quantity, which
# is why neither was caught by a "does it run" probe. These tests pin the units,
# not merely the presence of a value.
# ---------------------------------------------------------------------------
def _eu_snapshot() -> MacroDataSnapshot:
    """A euro-area snapshot carrying every series the eu derivation reads.

    The HICP series is a monthly INDEX (values near 103), because that is what
    the euro area publishes and what the real snapshot carries — the whole point
    of the two unit tests below is that a series of INDEX levels must NOT have its
    raw one-step difference fed to a rule expecting a rate change.

    The GDP series is at REAL national-accounts magnitude — MILLIONS of chained
    euros, ~3,000,000 — because that magnitude is what makes the two unit defects
    distinguishable. A synthetic series near 100 would make the GDP-level change
    and the gap change both small, so the level-defect would pass the bound
    below; the live defect only blew up because real GDP levels are of order
    10^6-10^7 and their one-step difference is therefore of order 10^4. The
    fixture reproduces the CONDITIONS, not just the shape.

    The qoq growth VARIES, so the estimated output gap and its change are
    non-trivial (a constant-growth series would make the gap change zero).
    """
    return MacroDataSnapshot(
        country="eu",
        as_of=AS_OF,
        data_quality_flags=[],
        eu_hicp_index=_monthly(
            [
                100.0,
                100.2,
                100.4,
                100.6,
                100.9,
                101.2,
                101.5,
                101.8,
                102.1,
                102.4,
                102.8,
                103.1,
                103.0,
                103.22,
                103.66,
            ],
            series="eu_hicp_index",
        ),
        # Real national-accounts magnitude: a one-step LEVEL change is ~10^4,
        # whereas the GAP change (a percentage-point quantity) is of order 0.1-1.
        eu_gdp_real_level=_series(
            [2_950_000.0, 2_975_000.0, 2_998_000.0, 3_041_000.0, 3_070_000.0, 3_130_000.0],
            start="2025-09-01",
            step_days=91,
            series="eu_gdp_real_level",
        ),
        eu_ecb_main_refi_rate=_series(
            [3.15, 2.90, 2.65], start="2025-09-01", step_days=91, series="eu_ecb_main_refi_rate"
        ),
        eu_unemployment_rate=_monthly(
            [6.4, 6.3, 6.2, 6.2, 6.1, 6.1], series="eu_unemployment_rate"
        ),
        eu_short_rate_3m=_series(
            [2.10, 2.05, 2.0277], start="2025-09-01", step_days=91, series="eu_short_rate_3m"
        ),
        eu_long_rate_10y=_series(
            [3.60, 3.70, 3.748], start="2025-09-01", step_days=91, series="eu_long_rate_10y"
        ),
    )


def _de_snapshot() -> MacroDataSnapshot:
    """A German snapshot carrying every series the de derivation reads.

    Germany's rules read BOTH its own data and the euro-area aggregate (the ECB
    rate IS Germany's policy rate; the aggregate is the comparator it diverges
    from), so this fixture carries ``de_*`` AND the ``eu_*`` comparators. The
    German values are set to diverge from the euro-area ones — German inflation
    above, unemployment below — so the appropriateness gap is a non-trivial
    signed number rather than a coincidence of equal series.
    """
    return MacroDataSnapshot(
        country="de",
        as_of=AS_OF,
        data_quality_flags=[],
        de_cpi_yoy=_monthly([2.6, 2.7, 2.8, 2.9, 2.86], series="de_cpi_yoy"),
        de_unemployment_rate=_monthly([4.5, 4.4, 4.4, 4.3, 4.3], series="de_unemployment_rate"),
        de_gdp_real_level=_series(
            [5_180_000.0, 5_210_000.0, 5_228_000.0, 5_240_000.0],
            start="2025-06-01",
            step_days=91,
            series="de_gdp_real_level",
        ),
        de_short_rate_3m=_series(
            [2.45, 2.51, 2.513], start="2025-09-01", step_days=91, series="de_short_rate_3m"
        ),
        de_long_rate_10y=_series(
            [3.05, 3.12, 3.18], start="2025-09-01", step_days=91, series="de_long_rate_10y"
        ),
        de_call_rate=_series(
            [2.15, 2.19, 2.187], start="2025-09-01", step_days=91, series="de_call_rate"
        ),
        # The euro-area comparator (Germany's policy inputs, not another country's).
        eu_ecb_main_refi_rate=_series(
            [2.40, 2.25, 2.15], start="2025-09-01", step_days=91, series="eu_ecb_main_refi_rate"
        ),
        eu_hicp_index=_monthly(
            [
                100.0,
                100.2,
                100.4,
                100.6,
                100.9,
                101.2,
                101.5,
                101.7,
                101.9,
                102.0,
                102.1,
                102.2,
                102.2,
                102.3,
                102.35,
                102.4,
            ],
            series="eu_hicp_index",
        ),
        eu_unemployment_rate=_monthly(
            [6.4, 6.3, 6.2, 6.2, 6.1, 6.1], series="eu_unemployment_rate"
        ),
        eu_gdp_real_level=_series(
            [2_950_000.0, 2_975_000.0, 2_998_000.0, 3_041_000.0],
            start="2025-06-01",
            step_days=91,
            series="eu_gdp_real_level",
        ),
    )


def _jp_snapshot() -> MacroDataSnapshot:
    """A Japanese snapshot carrying every series the jp derivation reads.

    The BoJ's CPI measure is all items less fresh food; the shadow-rate rule
    reads it against the 2% target, and the YCC leg reads the 10-year JGB yield
    against the BoJ's target. The Japanese values are plausible for the
    post-2024 regime (a small positive policy rate, a JGB yield well above the
    YCC target) so the floor is NOT binding by default — the binding case is
    exercised by a dedicated unit test on the rule itself.
    """
    return MacroDataSnapshot(
        country="jp",
        as_of=AS_OF,
        data_quality_flags=[],
        jp_cpi_yoy=_monthly([2.8, 2.7, 2.5, 2.2, 1.96], series="jp_cpi_yoy"),
        jp_unemployment_rate=_monthly([2.5, 2.5, 2.6, 2.6, 2.6], series="jp_unemployment_rate"),
        jp_gdp_real_level=_series(
            [5_900_000.0, 5_920_000.0, 5_943_000.0, 5_950_000.0],
            start="2025-06-01",
            step_days=91,
            series="jp_gdp_real_level",
        ),
        jp_short_rate_3m=_series(
            [1.35, 1.44, 1.458], start="2025-09-01", step_days=91, series="jp_short_rate_3m"
        ),
        jp_long_rate_10y=_series(
            [2.70, 2.85, 2.94], start="2025-09-01", step_days=91, series="jp_long_rate_10y"
        ),
        jp_call_rate=_series(
            [0.50, 0.75, 0.977], start="2025-09-01", step_days=91, series="jp_call_rate"
        ),
    )


def _snapshot_for_country(country: str) -> MacroDataSnapshot:
    """The fixture snapshot for an implemented multi-country code."""
    builders = {"gb": _gb_snapshot, "eu": _eu_snapshot, "de": _de_snapshot, "jp": _jp_snapshot}
    return builders[country]()


def test_the_eu_output_gap_change_is_a_gap_change_not_a_gdp_level_change() -> None:
    """(§22.3, unit defect) ``output_gap_change`` is in PERCENTAGE POINTS of the gap.

    This was a real defect: the eu derivation fed ``output_gap_change`` the raw
    one-step difference of ``eu_gdp_real_level`` — a national-accounts index whose
    step is of order 10^4 in its own units — which the error-correction rules
    multiplied by their 0.266 gap coefficient, producing a prescription near
    4885% and a dispersion near 4882pp. The wrong number is PLAUSIBLE-LOOKING in
    the sense that nothing raises; a reader cannot distinguish it from a genuine
    regime call.

    The gap is a percentage-point quantity (qoq growth minus its window mean), so
    its change is bounded by the series' own growth variability — a few pp at
    most for this fixture — NOT by the GDP level's magnitude. The bound below is
    the test: a defect of the original kind gives a value in the thousands.
    """
    inputs = orch.snapshot_to_thesis_inputs(_eu_snapshot())
    assert inputs.eu_inputs is not None
    change = inputs.eu_inputs.error_correction.output_gap_change
    assert abs(change) < 100.0, (
        f"output_gap_change is {change}; a gap change in percentage points cannot "
        f"be of this magnitude. A value in the thousands means the change was "
        f"taken on the raw GDP LEVEL rather than on the gap."
    )
    # And it is genuinely the gap's change, i.e. small and of the growth series'
    # own order — not zero (the fixture's growth varies on purpose).
    assert change != 0.0


def test_the_eu_pi_change_is_a_rate_change_not_a_price_index_change() -> None:
    """(§22.3, unit defect) ``pi_change`` is the change in the YoY RATE, in pp.

    The second unit defect, same class as the first: ``pi_change`` was computed
    as the raw one-step difference of the HICP INDEX (a monthly index near 103),
    giving an index-point change of order +0.4 — a quantity in neither the rule's
    units nor a rate's. The rule's input is documented as ``pi_t - pi_{t-1}``, the
    change between two YEAR-OVER-YEAR RATES.

    Both are of order 0.1-0.5, so the value alone cannot distinguish them; the
    test therefore pins the DERIVATION by checking the change against the two
    YoY rates the canonical ``_yoy_percent`` produces from the same series — a
    price-index change would not equal their difference.
    """
    from macro_engine.api_layer.orchestration import _yoy_percent

    snapshot = _eu_snapshot()
    inputs = orch.snapshot_to_thesis_inputs(snapshot)
    assert inputs.eu_inputs is not None
    change = inputs.eu_inputs.error_correction.pi_change

    points = snapshot.eu_hicp_index
    current, _ = _yoy_percent(points, field="eu_hicp_index")
    prior, _ = _yoy_percent(points[:-1], field="eu_hicp_index")
    assert change == pytest.approx(current - prior)

    # It must NOT equal the raw index-level change, which is the defect.
    index_change = float(points[-1].value) - float(points[-2].value)
    assert change != pytest.approx(index_change), (
        "pi_change equals the raw HICP index-level change — the price-index defect is back"
    )


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
