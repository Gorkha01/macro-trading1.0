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
from macro_engine.models.instrument_selection import ThesisType

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
    """A UK snapshot carrying each series the gb derivation reads, plus its gilt.

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

    ``gb_gilt_10y_yield`` is carried even though the *gb thesis derivation* does
    not read it as its short leg (it reads ``gb_short_rate_3m``): the series is in
    the production GB fetch plan (``config/settings.yaml`` ``snapshot_fields.gb``)
    and the 10-year gilt is the leg the cross-country join reads for the UK. A
    fixture missing a series the PRODUCTION snapshot carries would let the join's
    GB leg pass here against a snapshot no deployment ever produces.
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
        gb_gilt_10y_yield=_series([4.35, 4.28, 4.22, 4.18], series="gb_gilt_10y_yield"),
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


# ---------------------------------------------------------------------------
# The two-snapshot orchestration (Section 22.3 layer 4, docs/PHASE5_DEFERRED.md 2.4.2)
# ---------------------------------------------------------------------------


def _us_cross_snapshot(*, policy: float = 4.30, cpi_last: float = 330.0) -> MacroDataSnapshot:
    """A US snapshot usable as a cross-country leg (D-152/D-154).

    Reuses :func:`_full_snapshot`'s shape but pins the two quantities the join
    reads — the effective policy rate (``iorb``) and headline inflation — so a
    test can place the US on a known side of a divergence. ``cpi_last`` sets the
    final CPI level; the monthly series steps by 1.0, so the YoY rate is a known
    function of it.
    """
    snap = _full_snapshot()
    return snap.model_copy(
        update={
            "iorb": _monthly([policy] * 24, series="iorb"),
            "cpi_headline": _monthly(
                [cpi_last - 23.0 + i for i in range(24)], series="cpi_headline"
            ),
        }
    )


def test_the_two_snapshot_join_produces_a_divergence_record() -> None:
    """The join measures the divergence and returns it on the inputs.

    A ``CROSS_COUNTRY_DIVERGENCE`` thesis carries ``cross_country`` — the
    ``value`` dict of ``cross_country_divergence`` — so the builder computes the
    divergence ONCE (LAW 2) and the selector reads a measured number.

    USD/GBP is a cross-currency pair, so the caller must attest
    ``fx_converted=True`` (the model refuses an unattested cross-currency
    difference — the archetypal fake spread). Passing the attestation here is
    what a real caller does after routing both legs through the FX bridge.
    """
    result = orch.cross_country_thesis_inputs(
        _us_cross_snapshot(),
        _gb_snapshot(),
        thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
        fx_converted=True,
    )
    assert result.cross_country is not None
    assert result.cross_country["verdict"] in {
        "MEANINGFUL_DIVERGENCE",
        "NO_MEANINGFUL_DIVERGENCE",
    }
    assert "divergence_bp" in result.cross_country
    # Leg A is the country the THESIS is about; the divergence names both.
    assert result.country == "us"
    assert result.cross_country["long_leg_country"] in {"us", "gb"}
    assert result.cross_country["short_leg_country"] in {"us", "gb"}
    assert result.cross_country["long_leg_country"] != result.cross_country["short_leg_country"], (
        "the two legs must be different countries"
    )


def test_the_join_refuses_the_same_country_twice() -> None:
    """Passing one country's snapshot twice is refused BEFORE any arithmetic.

    The model also refuses it, but the error here names the two SNAPSHOTS a
    caller actually passed, which is the diagnosis a caller needs.
    """
    with pytest.raises(orch.OrchestrationError, match="against itself"):
        orch.cross_country_thesis_inputs(
            _us_cross_snapshot(),
            _us_cross_snapshot(),
            thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
        )


def test_the_join_refuses_a_non_cross_country_thesis_type() -> None:
    """A divergence for any other family is a category error.

    Refused here so the builder's own validator never has to be the one to say
    it, and so the message can name the family that was asked for.
    """
    with pytest.raises(orch.OrchestrationError, match="CROSS_COUNTRY_DIVERGENCE"):
        orch.cross_country_thesis_inputs(
            _us_cross_snapshot(),
            _gb_snapshot(),
            thesis_type=ThesisType.POLICY_PATH_GAP,
        )


def test_the_sign_convention_follows_the_argument_order() -> None:
    """Swapping the two snapshots flips the SIGN, but NOT which country is long.

    Two different invariants live here and an earlier version of this test
    conflated them — which is exactly what it was written to prevent, one level
    up.

    * **The divergence is antisymmetric in the leg order.** ``(A - B)`` negates
      when the arguments swap. This the test asserts, and it is the caller-facing
      contract the docstring states.
    * **The long leg is NOT order-dependent.** ``long_leg_country`` is *the
      country with the higher real rate* — a property of the two economies, not
      of how the caller listed them. In this fixture the US real rate
      (4.30 - 3.77 = +0.53) exceeds the UK's (4.25 - 3.80 = +0.45), so the RV
      trade is LONG US regardless of argument order. Asserting that the long leg
      *swaps* would be asserting a defect: it would mean the long leg tracked the
      argument order rather than the measured differential, which is the
      caller-flag error the model's own comment forbids ("never a caller flag — a
      flag would let a caller name the wrong leg on a correct number").

    Both calls carry ``fx_converted=True`` because USD/GBP is cross-currency.
    """
    us_gb = orch.cross_country_thesis_inputs(
        _us_cross_snapshot(),
        _gb_snapshot(),
        thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
        fx_converted=True,
    )
    gb_us = orch.cross_country_thesis_inputs(
        _gb_snapshot(),
        _us_cross_snapshot(),
        thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
        fx_converted=True,
    )
    a = us_gb.cross_country
    b = gb_us.cross_country
    assert a is not None and b is not None
    # 1. The sign is antisymmetric in the leg order.
    assert a["divergence_bp"] == pytest.approx(-b["divergence_bp"]), (
        "the divergence is antisymmetric in the leg order"
    )
    # 2. The long/short assignment is a property of the ECONOMIES, not the order:
    #    the higher-real-rate country is long in BOTH listings.
    assert a["long_leg_country"] == b["long_leg_country"], (
        "the long leg is the higher-real-rate country, independent of argument order"
    )
    assert a["short_leg_country"] == b["short_leg_country"]
    assert a["long_leg_country"] != a["short_leg_country"]
    # 3. And it tracks the measured real rate, not the argument order: the US
    #    fixture's real rate exceeds the UK's, so the US is the long leg here.
    assert a["long_leg_country"] == "us"


def test_the_join_reads_the_shared_tenor_and_horizon_from_config() -> None:
    """The comparability basis is the CONFIG's, not each leg's own choice.

    The model validates both legs against ``cross_country.comparable_horizon_quarters``
    and the join against ``cross_country.shared_tenor_value``; this pins that the
    join actually consults them, by moving the leaf and observing the refusal.
    ``fx_converted=True`` because the fixture pair is USD/GBP (cross-currency).
    """
    settings = get_settings()
    tenor = settings.cross_country.shared_tenor
    assert tenor, "the shared tenor leaf must be populated"
    # The basis is reported on the derivation note, so a reader can see which
    # basis the two numbers were compared on.
    result = orch.cross_country_thesis_inputs(
        _us_cross_snapshot(),
        _gb_snapshot(),
        thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
        fx_converted=True,
    )
    basis = next((n for n in result.notes if n.name == "cross_country basis"), None)
    assert basis is not None, "the comparability basis must travel with the inputs"
    assert tenor in basis.value


def test_a_same_currency_pair_needs_no_fx_attestation() -> None:
    """eu/de share EUR, so the pair is exempt from the FX bridge — correctly.

    The two legs really are on one currency; requiring an attestation for them
    would be demanding a conversion of a no-op. This is the one same-currency
    pair among the five modelled countries, and it is exercised here so the
    exemption is a tested property rather than an untried branch.
    """
    result = orch.cross_country_thesis_inputs(
        _eu_snapshot(),
        _de_snapshot(),
        thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
    )
    assert result.cross_country is not None
    basis = next(n for n in result.notes if n.name == "cross_country basis")
    assert "EUR/EUR" in basis.value
    assert "same currency" in basis.value


def test_a_cross_currency_pair_without_the_attestation_is_refused() -> None:
    """us/gb are USD vs GBP: the model refuses an unattested cross-currency pair.

    The default of ``fx_converted`` is ``False``, and this asserts the default is
    the SAFE one — an unattested cross-currency call must not pass.
    """
    with pytest.raises(ValueError, match="fx_converted is False"):
        orch.cross_country_thesis_inputs(
            _us_cross_snapshot(),
            _gb_snapshot(),
            thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
        )


def test_a_cross_currency_pair_passes_with_the_attestation() -> None:
    """With the attestation, the same pair measures a divergence."""
    result = orch.cross_country_thesis_inputs(
        _us_cross_snapshot(),
        _gb_snapshot(),
        thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
        fx_converted=True,
    )
    assert result.cross_country is not None
    basis = next(n for n in result.notes if n.name == "cross_country basis")
    assert "fx_converted=True" in basis.value


def test_every_implemented_country_has_a_leg_currency_and_label() -> None:
    """Every country the system can run must be nameable as a leg.

    The leg label (for the instrument) and the leg currency (for the
    comparability check) are both config surfaces keyed by country. A country in
    ``country.implemented`` but absent from either map would be runnable as a
    thesis yet unrunnable as a cross-country leg — a gap that would only surface
    the first time someone asked for that pair.
    """
    settings = get_settings()
    for country in settings.country.implemented:
        assert country in settings.cross_country.labels, f"{country} has no leg label"
        assert country in settings.cross_country.leg_currencies, f"{country} has no leg currency"


def test_the_join_maps_each_country_to_its_own_policy_series() -> None:
    """The policy-rate table names a real field per country, and a real series.

    A leg's policy rate must be its OWN effective rate, not a proxy. This asserts
    the table resolves for every implemented country and that the resolved series
    is one the schema declares — so a typo in the table is a test failure rather
    than a runtime ``AttributeError`` on the first cross-country call.
    """
    from macro_engine.data_layer.schemas import MacroDataSnapshot as S

    declared = set(S.model_fields)
    for country in get_settings().country.implemented:
        snap = _snapshot_for_country(country) if country != "us" else _us_cross_snapshot()
        leg = orch._leg_levels(
            snap,
            thesis_type=ThesisType.CROSS_COUNTRY_DIVERGENCE,
            universe=None,
            short_yield_tenor=None,
            curve_short_tenor=None,
            curve_long_tenor=None,
            short_tenor_term_premium=None,
        )
        assert isinstance(leg.policy_rate, float)
        assert isinstance(leg.inflation, float)
        assert isinstance(leg.long_rate, float)
        # The values are PERCENT levels, not bp: a bp value would be ~1000x.
        assert -20.0 < leg.long_rate < 40.0, f"{country} long rate looks like bp, not percent"
        assert -20.0 < leg.inflation < 100.0, f"{country} inflation out of plausible range"
    assert "iorb" in declared and "cpi_headline" in declared
