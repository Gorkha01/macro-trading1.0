"""Parity between the BUILD path and the RE-VALIDATION path (F-SB-001 / F-SB-002).

Why this file exists
--------------------
``validate_snapshot`` (re-validation) and ``snapshot_builder._apply_validation``
(build) each derived a series' ``[min, max]`` bounds independently, and the two
derivations had drifted **twice** — both times in ``validate_snapshot``'s
favour:

* the LEVEL lower bound was suppressed for ``signed_series`` in
  ``validate_snapshot`` only, so the BUILD path reported a legitimate negative
  spread change as ``VALUE_BELOW_MIN`` ERROR (F-SB-001);
* ``unemployment_rate``'s configured ``(0.0, 100.0)`` took precedence in
  ``validate_snapshot`` only, so the BUILD path used the registry's narrower
  ``(0.0, 25.0)`` (F-SB-002).

Both are now derived once, in ``validation.registry_bounds``. The existing suite
could not catch either drift because it exercised ``validate_snapshot`` alone —
which is the path that does NOT run in production. So these tests assert the two
paths agree, case by case, rather than asserting one path's behaviour.

Expected values come from the shipped ``config/series_registry.yaml`` and
``config/settings.yaml`` (read, not assumed):

  credit_spread_hy  plausible_range (0.1, 40.0)   signed_series: true
  unemployment_rate registry (0.0, 25.0)          configured (0.0, 100.0)
  cpi_headline      plausible_range (50.0, ...)   signed_series: false
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint
from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport, _apply_validation
from macro_engine.data_layer.validation import registry_bounds, validate_snapshot

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
TODAY = date(2026, 10, 5)
BOUND_CODES = ("VALUE_BELOW_MIN", "VALUE_ABOVE_MAX")


def _paths(name: str, value: float) -> tuple[set[str], set[str]]:
    """The bound findings each path produces for one (series, value)."""
    point = ObservationPoint(observation_date=TODAY, value=value, series_id=name, retrieved_at=NOW)
    snapshot = MacroDataSnapshot(country="us", as_of=NOW)
    setattr(snapshot, name, [point])

    build_flags = _apply_validation(snapshot, {name: [point]}).data_quality_flags
    build = {code for code in BOUND_CODES if any(code in flag for flag in build_flags)}
    reval = {f.code for f in validate_snapshot(snapshot).findings if f.code in BOUND_CODES}
    return build, reval


@pytest.mark.parametrize(
    ("name", "value"),
    [
        # A narrowing spread CHANGE is legitimate: the LEVEL floor does not apply.
        ("credit_spread_hy", -0.2),
        ("credit_spread_ig", -0.2),
        # The configured unemployment ceiling is 100, not the registry's 25.
        ("unemployment_rate", 30.0),
        # An ordinary in-range value on an unsigned level series.
        ("cpi_headline", 300.0),
        # ...and the violations that must STILL fire, on both paths.
        ("credit_spread_hy", 99.0),
        ("unemployment_rate", 150.0),
        ("cpi_headline", -5.0),
    ],
)
def test_build_and_revalidation_paths_agree(name: str, value: float) -> None:
    build, reval = _paths(name, value)
    assert build == reval, f"{name}={value}: build={build} revalidation={reval}"


def test_a_signed_series_still_enforces_its_upper_bound() -> None:
    """Suppressing the LOWER bound must not disarm the upper one."""
    build, reval = _paths("credit_spread_hy", 99.0)
    assert build == reval == {"VALUE_ABOVE_MAX"}


def test_a_narrowing_spread_is_clean_on_the_build_path_too() -> None:
    build, reval = _paths("credit_spread_hy", -0.2)
    assert build == set()
    assert reval == set()


def test_registry_bounds_applies_the_signed_series_rule() -> None:
    entry = get_registry().series["credit_spread_hy"]
    low, high = registry_bounds(entry, series_id="credit_spread_hy")
    assert low is None  # lower suppressed for a declared-signed series
    assert high == 40.0  # upper still applies


def test_registry_bounds_prefers_the_configured_unemployment_bounds() -> None:
    entry = get_registry().series["unemployment_rate"]
    low, high = registry_bounds(entry, series_id="unemployment_rate")
    configured = get_settings().validation.unemployment_bounds
    assert (low, high) == (float(configured[0]), float(configured[1]))
    assert high == 100.0  # NOT the registry's 25.0
    assert entry is not None and entry.plausible_range == (0.0, 25.0)


def test_registry_bounds_is_none_none_without_a_range() -> None:
    assert registry_bounds(None, series_id="anything") == (None, None)


def test_both_paths_use_the_one_derivation() -> None:
    """The structural fix: neither path may re-derive the per-series rules.

    The CALL is asserted, not the name — both docstrings mention the helper, so
    a bare substring check would pass even with the call replaced by a local
    re-derivation (measured: it did).
    """
    import inspect

    import macro_engine.data_layer.snapshot_builder as builder
    import macro_engine.data_layer.validation as validation

    assert "registry_bounds" in validation.__all__
    assert "validate_registry_series" in validation.__all__

    for fn in (builder._apply_validation, validation.validate_snapshot):
        src = inspect.getsource(fn)
        assert "validate_registry_series(" in src
        # ...and no local re-derivation of ANY per-series rule survives.
        assert "entry.plausible_range" not in src
        assert "forward_looking=bool(entry" not in src
        assert "future_date_tolerance_days=" not in src

    # The derivation itself lives in exactly one function.
    derived = inspect.getsource(validation.validate_registry_series)
    assert "registry_bounds(" in derived
    assert "future_date_tolerance_days=" in derived


def test_emptiness_is_owned_by_the_build_report_only() -> None:
    """F-SB-006, resolved: ONE producer, and it is the layer that can know.

    ``SnapshotBuildReport`` holds ``requested``, so it can tell "asked and got
    nothing" from "not part of this snapshot". ``validate_snapshot`` cannot —
    every snapshot field defaults to ``[]`` — which is why it skips empty
    series. Emitting the finding from both produced two flags for one condition.
    """
    import inspect

    import macro_engine.data_layer.snapshot_builder as builder
    import macro_engine.data_layer.validation as validation

    # The shared derivation no longer carries emptiness at all.
    sig = inspect.signature(validation.validate_registry_series)
    assert "required" not in sig.parameters
    assert "required=" not in inspect.getsource(builder._apply_validation)

    # ...and the report's flag carries the sentence the validation one used to.
    report = builder.SnapshotBuildReport()
    report.requested = ["cpi_headline"]
    report.succeeded = ["cpi_headline"]
    report.observation_counts = {"cpi_headline": 0}
    flags = [f for f in report.as_flags() if f.startswith("EMPTY_SERIES")]
    assert len(flags) == 1
    assert "not as zero" in flags[0]


def test_one_empty_series_produces_exactly_one_flag() -> None:
    """The duplicate, measured end-to-end: it used to be 2 flags for 1 condition."""
    snapshot = MacroDataSnapshot(country="us", as_of=NOW)
    snapshot.cpi_headline = []
    snapshot = _apply_validation(snapshot, {"cpi_headline": []})

    report = SnapshotBuildReport()
    report.requested = ["cpi_headline"]
    report.succeeded = ["cpi_headline"]
    report.observation_counts = {"cpi_headline": 0}
    snapshot.data_quality_flags = [*snapshot.data_quality_flags, *report.as_flags()]

    empty = [f for f in snapshot.data_quality_flags if "EMPTY_SERIES" in f]
    assert len(empty) == 1, empty
    assert empty[0].startswith("EMPTY_SERIES:cpi_headline:")
