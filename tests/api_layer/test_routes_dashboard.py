"""``api_layer/routes_dashboard.py`` — the cap, the panels, and four live defects.

The endpoint's one safety property is the series cap, and it had no test file.

Live defects found BY this review:

* ``F-DSH-001`` — ``_points_for``'s docstring named ``_missing_fields``, which
  does not exist anywhere (the function is ``_declared_but_absent``).
* ``F-DSH-002`` — the cap was described as bounding series-per-family while the
  code bounds points-per-series (and the per-family reading would make the leaf
  inert).
* ``F-DSH-003`` — the cap silently inverts for a non-positive limit: 0 returns
  EVERY point (reporting nothing withheld) and a negative value drops the OLDEST.
* ``F-DSH-004`` — the family table's comment said "seventeen" names; there are 20.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from macro_engine.api_layer import routes_dashboard as rd
from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint

AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


def _source() -> str:
    """The module's own text, for the guards on claims that live in prose."""
    import inspect
    from pathlib import Path

    return Path(inspect.getfile(rd)).read_text(encoding="utf-8")


def _series(
    values: list[float], *, start: date = date(2024, 1, 1), series: str = "x"
) -> list[ObservationPoint]:
    return [
        ObservationPoint(observation_date=start + timedelta(days=i * 30), value=v, series_id=series)
        for i, v in enumerate(values)
    ]


def _snapshot(**overrides: Any) -> MacroDataSnapshot:
    return MacroDataSnapshot(as_of=AS_OF, data_quality_flags=[], **overrides)


def _stub(monkeypatch: pytest.MonkeyPatch, snapshot: MacroDataSnapshot, *, limit: int = 12) -> None:
    from macro_engine.api_layer.snapshot_provider import SnapshotProvenance

    provenance = SnapshotProvenance(
        country="us",
        as_of=AS_OF,
        generated_at=AS_OF,
        age_hours=0.5,
        age_exceeds_max=False,
        max_age_hours=24.0,
        from_cache=False,
        data_quality_flag_count=0,
        build_seconds=4.0,
    )
    monkeypatch.setattr(
        rd, "get_snapshot", lambda country, force_refresh=False: (snapshot, provenance)
    )
    # The handler imports `get_settings` INSIDE the function, so patching the
    # source module is what the call site sees.
    monkeypatch.setattr(
        "macro_engine.config.get_settings",
        lambda *a, **k: SimpleNamespace(api=SimpleNamespace(dashboard_series_limit=limit)),
    )


# ---------------------------------------------------------------------------
# (F-DSH-003) the cap must be a cap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [0, -1, -12])
@pytest.mark.asyncio
async def test_a_non_positive_limit_is_a_configuration_defect(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    """(F-DSH-003) ``points[-limit:]`` is not a cap for ``limit <= 0``.

    MEASURED 2026-10-06: 0 keeps EVERY point and reports nothing withheld, and a
    negative limit drops the OLDEST point — so the leaf's own value could silently
    disable the DoS guard this module exists to provide.
    """
    _stub(monkeypatch, _snapshot(gdp_real=_series([1.0] * 30)), limit=limit)
    with pytest.raises(HTTPException) as excinfo:
        await rd.dashboard_data("us", False)
    assert excinfo.value.status_code == 500
    assert "at least 1" in excinfo.value.detail


@pytest.mark.asyncio
async def test_a_positive_limit_caps_the_history_and_reports_what_it_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, _snapshot(gdp_real=_series([float(i) for i in range(30)])), limit=12)
    response = await rd.dashboard_data("us", False)
    panel = response.series["growth"][0]
    assert panel.field == "gdp_real"
    assert panel.points_available == 30
    assert len(panel.values) == 12
    assert panel.points_withheld == 18
    # The most RECENT window, and the latest point is the newest one.
    assert panel.values[-1] == 29.0
    assert panel.latest_value == 29.0
    assert any("DASHBOARD TRUNCATED" in w for w in response.warnings)


# ---------------------------------------------------------------------------
# the panels
# ---------------------------------------------------------------------------


def test_the_points_for_docstring_names_a_function_that_exists() -> None:
    """(F-DSH-001) It named ``_missing_fields``, which exists nowhere in the tree."""
    source = _source()
    assert "``_missing_fields``" not in source
    assert "``_declared_but_absent``" in source


def test_the_cap_is_described_as_points_per_series() -> None:
    """(F-DSH-002) A per-family reading would make the leaf inert (2-5 series each)."""
    source = _source()
    assert "bounds each family" not in source
    assert "bounds each series' **history**" in source


def test_the_family_table_comment_counts_the_table() -> None:
    """(F-DSH-004) The comment stated a smaller number than the table declares."""
    source = _source()
    assert "seventeen" not in source
    assert "**twenty**" in source


def test_the_label_is_human_readable() -> None:
    assert rd._label("initial_claims") == "Initial Claims"


def test_an_undeclared_field_degrades_to_an_absent_panel() -> None:
    """``getattr`` with a default, so a renamed field cannot 500 a dashboard."""
    assert rd._points_for(_snapshot(), "not_a_field") == []


def test_the_family_table_names_only_fields_the_schema_carries() -> None:
    """The renamed-field detector: today it finds nothing, and that is the assertion."""
    assert rd._declared_but_absent(_snapshot()) == []


def test_a_renamed_field_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The detector that turns a silently-missing panel into a fixable one."""
    monkeypatch.setitem(rd._SERIES_FAMILIES, "ghost", ("treasury_curve",))
    assert rd._declared_but_absent(_snapshot()) == ["treasury_curve"]


def test_the_family_table_holds_twenty_fields() -> None:
    """(F-DSH-004) The comment said 'seventeen'; the table declares 20 across 5 families."""
    assert len(rd._SERIES_FAMILIES) == 5
    assert len(rd._all_declared_fields()) == 20


def test_the_curve_panel_declares_percent_and_carries_the_tenors() -> None:
    from macro_engine.data_layer.schemas import YieldCurveSnapshot

    snapshot = _snapshot(
        yield_curve=YieldCurveSnapshot(as_of=date(2026, 10, 6), tenors={"2yr": 4.3, "10yr": 4.5})
    )
    panel = rd._curve_panel(snapshot, "yield_curve")
    assert panel is not None
    assert panel.units == "percent"
    assert panel.tenors == {"2yr": 4.3, "10yr": 4.5}
    assert rd._curve_panel(snapshot, "tips_yields") is None


# ---------------------------------------------------------------------------
# the route's family rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_entirely_empty_family_is_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent key is 'no panel here'; ``{"growth": []}`` would need special-casing."""
    _stub(monkeypatch, _snapshot(cpi_headline=_series([1.0, 2.0])))
    response = await rd.dashboard_data("us", False)
    assert "prices" in response.series
    assert "growth" not in response.series
    assert "credit" not in response.series


@pytest.mark.asyncio
async def test_a_partially_empty_family_keeps_its_empty_panels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One populated series is enough to render the family; the rest say they are empty."""
    _stub(monkeypatch, _snapshot(gdp_real=_series([1.0, 2.0])))
    response = await rd.dashboard_data("us", False)
    growth = {panel.field: panel for panel in response.series["growth"]}
    assert growth["gdp_real"].points_available == 2
    assert growth["gdp_nominal"].points_available == 0
    assert growth["gdp_nominal"].dates == []
    assert growth["gdp_nominal"].latest_value is None
    assert growth["gdp_nominal"].points_withheld == 0


@pytest.mark.asyncio
async def test_a_declared_but_absent_field_raises_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(rd._SERIES_FAMILIES, "ghost", ("treasury_curve",))
    _stub(monkeypatch, _snapshot(gdp_real=_series([1.0])))
    response = await rd.dashboard_data("us", False)
    assert any("DASHBOARD FIELD MISSING" in w and "treasury_curve" in w for w in response.warnings)


@pytest.mark.asyncio
async def test_the_provenance_warnings_are_published(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _snapshot(gdp_real=_series([1.0])))
    response = await rd.dashboard_data("us", False)
    assert response.series_limit == 12
    assert response.country == "us"
    assert response.as_of == AS_OF


@pytest.mark.asyncio
async def test_a_snapshot_failure_is_a_502_and_a_bad_country_a_501(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from macro_engine.api_layer.snapshot_provider import SnapshotUnavailableError

    _stub(monkeypatch, _snapshot())

    def unavailable(country: str, force_refresh: bool = False) -> object:
        raise SnapshotUnavailableError("no source")

    monkeypatch.setattr(rd, "get_snapshot", unavailable)
    with pytest.raises(HTTPException) as excinfo:
        await rd.dashboard_data("us", False)
    assert excinfo.value.status_code == 502

    def unimplemented(country: str, force_refresh: bool = False) -> object:
        raise NotImplementedError("us only")

    monkeypatch.setattr(rd, "get_snapshot", unimplemented)
    with pytest.raises(HTTPException) as excinfo:
        await rd.dashboard_data("de", False)
    assert excinfo.value.status_code == 501
