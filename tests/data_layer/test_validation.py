"""Fresh test suite for ``data_layer/validation.py``.

Written from scratch for the module-by-module review: the module had **no
dedicated test file** — its behaviour was only partly covered from
``test_phase1_data_layer.py`` / ``test_non_finite_values.py`` /
``test_yield_zero_boundary.py``.

Every expected value is derived from the documented rule and the shipped
``config/settings.yaml`` (read, not assumed):

  validation.stale_days              = 500
  validation.unemployment_bounds     = (0.0, 100.0)
  validation.zero_yield_tenors       = {'1mo', '3mo'}
  validation.max_yield               = 25.0
  validation.long_end_inversion_floor = -50.0

Findings guarded here:
  * F-VAL-001 — the module docstring claimed "No model reads
    ``snapshot.data_quality_flags`` into ``ConfidenceInputs``" and that "nothing
    here does it for them". FALSE: ``gdp_nowcast.output_gap_from_snapshot`` does
    exactly that. The claim is corrected AND the behaviour is pinned below, which
    is what was missing (nothing tested it, so nothing could falsify the claim).
  * F-VAL-002 — ``ValidationReport`` and ``attach_flags`` were missing from
    ``__all__`` while every sibling public name was listed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import macro_engine.data_layer.validation as validation
from macro_engine.config import get_settings
from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)
from macro_engine.data_layer.validation import (
    Severity,
    ValidationFinding,
    ValidationReport,
    attach_flags,
    validate_equity_index,
    validate_observations,
    validate_positive_index_level,
    validate_unemployment_rate,
    validate_yield_curve,
)

TODAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _pt(d: date, v: float, *, retrieved: datetime = NOW) -> ObservationPoint:
    return ObservationPoint(observation_date=d, value=v, series_id="x", retrieved_at=retrieved)


def _codes(rep: ValidationReport) -> list[str]:
    return [f.code for f in rep.findings]


# ---------------------------------------------------------------------------
# Date integrity
# ---------------------------------------------------------------------------
def test_non_monotonic_dates_are_a_warning_not_an_error() -> None:
    rep = validate_observations(
        [_pt(date(2026, 1, 10), 1.0), _pt(date(2026, 1, 5), 1.1)], series_id="x"
    )
    assert _codes(rep) == ["NON_MONOTONIC_DATES"]
    assert rep.findings[0].severity is Severity.WARNING
    assert rep.has_warnings and not rep.has_errors


def test_duplicate_dates_are_flagged_and_not_dropped() -> None:
    rep = validate_observations(
        [_pt(date(2026, 1, 5), 1.0), _pt(date(2026, 1, 5), 2.0)], series_id="x"
    )
    assert "DUPLICATE_OBSERVATION_DATE" in _codes(rep)
    # Equal dates are duplicates, NOT out-of-order.
    assert "NON_MONOTONIC_DATES" not in _codes(rep)


def test_a_clean_ordered_series_produces_no_findings() -> None:
    rep = validate_observations(
        [_pt(date(2026, 1, 5), 1.0), _pt(date(2026, 1, 10), 1.1)], series_id="x"
    )
    assert rep.findings == []


# ---------------------------------------------------------------------------
# Staleness — the boundary is the CONFIGURED threshold, strictly greater
# ---------------------------------------------------------------------------
def test_stale_series_boundary_is_exactly_the_configured_threshold() -> None:
    threshold = get_settings().validation.stale_days
    at = validate_observations([_pt(TODAY - timedelta(days=int(threshold)), 1.0)], series_id="x")
    over = validate_observations(
        [_pt(TODAY - timedelta(days=int(threshold) + 1), 1.0)], series_id="x"
    )
    assert "STALE_SERIES" not in _codes(at)  # equal to the threshold is NOT stale
    assert "STALE_SERIES" in _codes(over)
    assert over.findings[0].severity is Severity.WARNING


# ---------------------------------------------------------------------------
# Future dating: tolerance, forward-looking, and the ERROR summary
# ---------------------------------------------------------------------------
def _future(days: int) -> list[ObservationPoint]:
    return [_pt(TODAY + timedelta(days=days), 1.0)]


def test_future_point_beyond_tolerance_is_an_error_plus_a_summary() -> None:
    rep = validate_observations(_future(30), series_id="x")
    codes = _codes(rep)
    assert codes.count("FUTURE_OBSERVATION_DATE") == 1
    assert "FUTURE_DATED_POINTS_SUMMARY" in codes
    assert rep.has_errors


def test_forward_looking_series_reports_one_info_horizon_instead_of_errors() -> None:
    # FRED GDPPOT carries ~a decade of projections; those are the series' point.
    rep = validate_observations(_future(30) + _future(400), series_id="x", forward_looking=True)
    assert _codes(rep) == ["FORWARD_LOOKING_HORIZON"]
    assert rep.findings[0].severity is Severity.INFO
    assert not rep.has_errors and not rep.has_warnings


def test_same_day_publication_within_tolerance_is_info_not_error() -> None:
    rep = validate_observations(_future(1), series_id="x", future_date_tolerance_days=1)
    assert _codes(rep) == ["SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK"]
    assert rep.findings[0].severity is Severity.INFO
    # ...and WITHOUT the tolerance the same point is the genuine fault path.
    strict = validate_observations(_future(1), series_id="x")
    assert "FUTURE_OBSERVATION_DATE" in _codes(strict)


# ---------------------------------------------------------------------------
# Emptiness, bounds, and the dedicated validators
# ---------------------------------------------------------------------------
def test_empty_series_is_flagged_only_when_required() -> None:
    assert _codes(validate_observations([], series_id="x", required=True)) == ["EMPTY_SERIES"]
    assert validate_observations([], series_id="x", required=False).findings == []


def test_bounds_flag_below_and_above_per_point() -> None:
    # Dates ASCENDING, so the only findings are the two bound violations.
    rep = validate_observations(
        [_pt(TODAY - timedelta(days=1), -1.0), _pt(TODAY, 101.0)],
        series_id="x",
        min_value=0.0,
        max_value=100.0,
    )
    assert _codes(rep) == ["VALUE_BELOW_MIN", "VALUE_ABOVE_MAX"]
    assert rep.has_errors


def test_unemployment_150_is_flagged_against_the_configured_bounds() -> None:
    rep = validate_unemployment_rate([_pt(TODAY, 150.0)])
    assert "VALUE_ABOVE_MAX" in _codes(rep)
    assert rep.has_errors


def test_positive_index_level_flags_negative_but_permits_zero() -> None:
    """F-VAL-003: the NAME says "positive" but the rule is "not negative".

    AGENTS.md §5.4 states it as *"No negative CPI/PCE index level"*, and the
    docstring agrees ("cannot be negative") — so the code (`min_value=0.0`,
    which flags ``value < 0``) follows the specification and a level of exactly
    ``0.0`` passes. The name overstates the check; a caller reading only the
    name would expect zero to be refused.
    """
    assert "VALUE_BELOW_MIN" in _codes(
        validate_positive_index_level([_pt(TODAY, -1.0)], series_id="i")
    )
    # Zero is permitted — the documented rule is "not negative", not "positive".
    assert validate_positive_index_level([_pt(TODAY, 0.0)], series_id="i").findings == []
    assert validate_positive_index_level([_pt(TODAY, 100.0)], series_id="i").findings == []


def test_equity_index_is_validated_per_symbol() -> None:
    rep = validate_equity_index({"spx": [_pt(TODAY, -5.0)], "ndx": [_pt(TODAY, 100.0)]})
    assert _codes(rep) == ["VALUE_BELOW_MIN"]
    assert rep.findings[0].series_id == "equity_index.spx"


# ---------------------------------------------------------------------------
# Yield curve
# ---------------------------------------------------------------------------
def test_absent_and_empty_curve_are_distinct_warnings() -> None:
    assert _codes(validate_yield_curve(None, series_id="yc")) == ["NO_CURVE"]
    assert validate_yield_curve(None, series_id="yc", required=False).findings == []
    empty = YieldCurveSnapshot(as_of=TODAY, tenors={})
    assert _codes(validate_yield_curve(empty, series_id="yc")) == ["EMPTY_CURVE"]


def test_2s10s_inversion_is_info_but_a_deep_30yr_inversion_is_an_error() -> None:
    floor = get_settings().validation.long_end_inversion_floor  # -50.0
    info = validate_yield_curve(
        YieldCurveSnapshot(as_of=TODAY, tenors={"2yr": 4.5, "10yr": 4.0}), series_id="yc"
    )
    assert _codes(info) == ["CURVE_INVERTED_2S10S"]
    assert info.findings[0].severity is Severity.INFO

    # 30yr 100bp below 10yr is deeper than the -50bp floor -> a data fault.
    deep_bp = -100.0
    assert deep_bp < floor
    bad = validate_yield_curve(
        YieldCurveSnapshot(as_of=TODAY, tenors={"10yr": 4.0, "30yr": 4.0 + deep_bp / 100}),
        series_id="yc",
    )
    assert _codes(bad) == ["IMPLAUSIBLE_LONG_END_INVERSION"]
    assert bad.has_errors


def test_yield_above_the_configured_maximum_is_implausible() -> None:
    top = get_settings().validation.max_yield  # 25.0
    rep = validate_yield_curve(
        YieldCurveSnapshot(as_of=TODAY, tenors={"10yr": top + 1.0}), series_id="yc"
    )
    assert _codes(rep) == ["IMPLAUSIBLE_YIELD_LEVEL"]


# ---------------------------------------------------------------------------
# Report plumbing
# ---------------------------------------------------------------------------
def test_report_severity_helpers_distinguish_error_from_warning() -> None:
    info = ValidationReport([ValidationFinding("s", "C", Severity.INFO, "d")])
    warn = ValidationReport([ValidationFinding("s", "C", Severity.WARNING, "d")])
    err = ValidationReport([ValidationFinding("s", "C", Severity.ERROR, "d")])
    assert not info.has_warnings and not info.has_errors
    assert warn.has_warnings and not warn.has_errors
    assert err.has_warnings and err.has_errors


def test_finding_as_flag_renders_severity_code_and_date() -> None:
    f = ValidationFinding("cpi_headline", "VALUE_ABOVE_MAX", Severity.ERROR, "too big", TODAY)
    assert f.as_flag() == "[ERROR] cpi_headline @2026-10-05: VALUE_ABOVE_MAX — too big"
    no_date = ValidationFinding("x", "CODE", Severity.INFO, "detail")
    assert no_date.as_flag() == "[INFO] x: CODE — detail"


def test_attach_flags_copies_and_never_mutates_the_original() -> None:
    snap = MacroDataSnapshot(country="us", as_of=NOW)
    rep = validate_observations([_pt(TODAY - timedelta(days=700), 1.0)], series_id="x")
    out = attach_flags(snap, rep)
    assert out is not snap
    assert snap.data_quality_flags == []  # provenance is immutable
    assert out.data_quality_flags == rep.flags()
    assert "STALE_SERIES" in out.data_quality_flags[0]


# ---------------------------------------------------------------------------
# F-VAL-001 / F-VAL-002
# ---------------------------------------------------------------------------
def test_validation_report_and_attach_flags_are_exported() -> None:
    assert "ValidationReport" in validation.__all__
    assert "attach_flags" in validation.__all__


def test_module_docstring_no_longer_claims_no_model_reads_the_snapshot_flags() -> None:
    doc = validation.__doc__ or ""
    assert "No model reads" not in doc
    assert "gdp_nowcast" in doc


def test_gdp_nowcast_really_does_price_the_snapshot_flags() -> None:
    """F-VAL-001's behavioural half: the claim was false because nothing tested it."""
    from macro_engine.models.gdp_nowcast import output_gap_from_snapshot

    q1, q2 = date(2026, 1, 1), date(2026, 4, 1)
    real = [_pt(q1, 23000.0), _pt(q2, 23100.0)]
    potential = [_pt(q1, 23200.0), _pt(q2, 23250.0)]
    clean, _ = output_gap_from_snapshot(
        MacroDataSnapshot(country="us", as_of=NOW, gdp_real=real, gdp_potential=potential)
    )
    flagged, _ = output_gap_from_snapshot(
        MacroDataSnapshot(
            country="us",
            as_of=NOW,
            gdp_real=real,
            gdp_potential=potential,
            data_quality_flags=["[WARNING] synthetic"],
        )
    )
    assert flagged.confidence < clean.confidence
    # base 0.70 - data_quality 0.25 - unobservable 0.20 = 0.25
    assert flagged.confidence == pytest.approx(0.25, abs=1e-9)
