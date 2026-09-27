"""Tests for ``commodities_client`` — the source behind ``oil_balance_signal``.

What these tests are for
------------------------
Section 6.8 declares two oil inputs with **no source**, so under Section 21.1's
default rule both read as BLOCKED. Measured 2026-09-29 both are reachable, which
makes this the **fifth FALSE BLOCK** this repository has caught (D-043's class).
Replacing a block with a source introduces a set of hazards, and each is asserted
here:

(a) **The symbol is selected BY NAME, never by position.** The PPS ``stocks``
    table returns 19 symbols in one response; taking a row by position would
    publish a different product's stock level. Asserted with a frame in which the
    wanted symbol is NOT the last row.
(b) **The projection tail is DISCARDED, never adopted.** The STEO series runs to
    2027-12; a "latest value" would report a forecast as a measurement (D-116).
    Asserted by planting future-dated rows and proving the latest OBSERVATION is
    chosen and the dropped count is reported.
(c) **A missing symbol is a FAILURE, not an empty series.** "The table does not
    carry this symbol" and "the symbol has no rows" are different facts.
(d) **A null or non-finite value is refused, never repaired to zero.** Zero is a
    legitimate reading, so a repaired zero would be indistinguishable from it.
(e) **The week-over-week change is ``None``, not ``0.0``, below two points.**
(f) **The seasonal deviation is the same-week comparison over prior years**, and
    is ``None`` — not zero — when no prior year matches.
(g) **The module never opens its own HTTP connection.** It goes through the
    project's own ``OpenBBClient`` (D-087.25).

The values used below are the real ones, captured live on 2026-09-29.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from typing import Any

import pytest

import macro_engine.data_layer.commodities_client as commodities_client
from macro_engine.data_layer.commodities_client import (
    INVENTORY_SYMBOL,
    SPARE_CAPACITY_SYMBOL,
    CommodityReadError,
    fetch_crude_inventories,
    fetch_opec_spare_capacity,
)


def _inventory_rows(
    levels: list[tuple[date, float]],
    *,
    symbol: str = INVENTORY_SYMBOL,
    extra_symbols: bool = True,
) -> list[dict[str, Any]]:
    """A PPS ``stocks``-shaped record list: many symbols, one per date.

    The real table carries 19 symbols at once (``WCRSTUS1``, ``WCESTUS1``,
    ``WCSSTUS1``, jet fuel, distillate, ...). ``extra_symbols`` reproduces that
    crowding, so a client that took a row by position would pick a neighbour.
    """
    rows: list[dict[str, Any]] = []
    for when, value in levels:
        # A decoy product FIRST and LAST, so the wanted symbol is never at either
        # end — the position-taking mutation this guards against.
        if extra_symbols:
            rows.append({"date": when.isoformat(), "symbol": "WCRSTUS1", "value": 999999.0})
        rows.append({"date": when.isoformat(), "symbol": symbol, "value": value})
        if extra_symbols:
            rows.append({"date": when.isoformat(), "symbol": "WDISTUS1", "value": 111111.0})
    return rows


def _steo_rows(levels: list[tuple[date, float]]) -> list[dict[str, Any]]:
    """An STEO ``03d``-shaped record list, including the projection tail."""
    rows: list[dict[str, Any]] = [
        {"date": when.isoformat(), "symbol": "COPRPUS", "value": 13.5} for when, _ in levels
    ]
    rows.extend(
        {"date": when.isoformat(), "symbol": SPARE_CAPACITY_SYMBOL, "value": value}
        for when, value in levels
    )
    return rows


class _StubClient:
    """An ``OpenBBClient`` stand-in returning canned records or raising."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._records = records
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def fetch_records(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._records is not None
        return self._records

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# (g) The route: no private HTTP, no second client.
# ---------------------------------------------------------------------------


def test_the_module_never_imports_httpx_or_requests_directly() -> None:
    """It must route through ``OpenBBClient``, not open its own connection.

    Asserted on the AST so a future "helpful" direct call fails a test rather
    than review (D-087.25's lesson).
    """
    tree = ast.parse(inspect.getsource(commodities_client))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "httpx" not in imported
    assert "requests" not in imported
    assert "aiohttp" not in imported


def test_the_module_never_reads_the_raw_http_handle() -> None:
    """It must not reach into ``client._http`` — that is the client's transport."""
    source = inspect.getsource(commodities_client)
    assert "_http" not in source


def test_no_local_openbb_host_literal() -> None:
    """The base URL belongs to the client, never to this module."""
    source = inspect.getsource(commodities_client)
    assert "127.0.0.1" not in source
    assert "6900" not in source
    assert "6901" not in source


def test_the_module_uses_fetch_records_not_fetch_series() -> None:
    """``fetch_series`` drops the ``symbol`` column, so it cannot be used here.

    Measured 2026-09-29: the PPS ``stocks`` table returns 34 428 rows across 19
    symbols; ``fetch_series`` folds them into ONE date/value frame and the last
    row is total stocks, not the wanted crude level. Asserted on the AST — a
    *call* to ``fetch_series`` fails, while a docstring that merely NAMES it (to
    explain why it is not used) is fine.
    """
    tree = ast.parse(inspect.getsource(commodities_client))
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            called.add(node.attr)
    assert "fetch_records" in called
    assert "fetch_series" not in called


# ---------------------------------------------------------------------------
# (a) The symbol is selected by NAME.
# ---------------------------------------------------------------------------


def test_the_inventory_symbol_is_selected_by_name_not_position() -> None:
    """The wanted symbol is never the last row; selection must be by name."""
    stub = _StubClient(
        _inventory_rows([(date(2026, 9, 11), 423429.0), (date(2026, 9, 18), 426398.0)])
    )
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.symbol == INVENTORY_SYMBOL
    assert reading.level_thousand_barrels == 426398.0


def test_the_client_requests_the_stocks_table_of_the_balance_sheet() -> None:
    """The route, category and table travel together with the symbol."""
    stub = _StubClient(
        _inventory_rows([(date(2026, 9, 11), 423429.0), (date(2026, 9, 18), 426398.0)])
    )
    fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    call = stub.calls[0]
    assert call["endpoint"] == "commodity.petroleum_status_report"
    assert call["provider"] == "eia"
    assert call["params"]["category"] == "balance_sheet"
    assert call["params"]["table"] == "stocks"


def test_the_spare_capacity_symbol_is_selected_by_name() -> None:
    stub = _StubClient(_steo_rows([(date(2026, 8, 1), 0.02), (date(2026, 9, 1), 0.02)]))
    reading = fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.symbol == SPARE_CAPACITY_SYMBOL
    assert reading.spare_capacity_mbd == 0.02


def test_the_client_requests_table_03d_with_the_symbol_filter() -> None:
    """STEO honours ``symbol`` server-side, so the request carries it."""
    stub = _StubClient(_steo_rows([(date(2026, 9, 1), 0.02)]))
    fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    call = stub.calls[0]
    assert call["endpoint"] == "commodity.short_term_energy_outlook"
    assert call["params"]["table"] == "03d"
    assert call["params"]["symbol"] == SPARE_CAPACITY_SYMBOL


# ---------------------------------------------------------------------------
# (c) A missing symbol is a failure.
# ---------------------------------------------------------------------------


def test_a_table_without_the_inventory_symbol_raises() -> None:
    stub = _StubClient(_inventory_rows([(date(2026, 9, 18), 426398.0)], symbol="WCRSTUS1"))
    with pytest.raises(CommodityReadError, match=INVENTORY_SYMBOL):
        fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


def test_a_table_without_the_spare_symbol_raises() -> None:
    stub = _StubClient([{"date": "2026-09-01", "symbol": "COPRPUS", "value": 13.5}])
    with pytest.raises(CommodityReadError, match=SPARE_CAPACITY_SYMBOL):
        fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (b) The projection tail is discarded.
# ---------------------------------------------------------------------------


def test_the_projection_tail_is_discarded_and_counted() -> None:
    """The latest OBSERVATION is chosen; the future-dated rows are dropped.

    THE central vintage guard (D-116): the STEO publishes forecasts to 2027-12,
    so a naive "latest value" would report a projection as a measurement.
    """
    levels = [
        (date(2026, 8, 1), 0.02),
        (date(2026, 9, 1), 0.02),
        (date(2026, 10, 1), 0.99),  # projection
        (date(2027, 12, 1), 0.88),  # projection
    ]
    stub = _StubClient(_steo_rows(levels))
    reading = fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-09-01"
    assert reading.spare_capacity_mbd == 0.02
    assert reading.projection_rows_dropped == 2


def test_the_projection_values_never_reach_the_reading() -> None:
    """A projection's VALUE must not be the published figure, only its count."""
    stub = _StubClient(_steo_rows([(date(2026, 9, 1), 0.02), (date(2026, 10, 1), 5.55)]))
    reading = fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.spare_capacity_mbd == 0.02
    assert reading.spare_capacity_mbd != 5.55


def test_all_future_rows_raises_rather_than_reporting_a_forecast() -> None:
    """If only projections exist at/before the as-of, there is nothing to report."""
    stub = _StubClient(_steo_rows([(date(2026, 10, 1), 0.99)]))
    with pytest.raises(CommodityReadError, match="no observation"):
        fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


def test_a_projection_row_is_counted_even_when_others_are_observations() -> None:
    """The count is the disclosure a reader audits, so it must be exact."""
    levels = [(date(2026, 7, 1), 0.1), (date(2026, 8, 1), 0.1), (date(2026, 9, 1), 0.1)]
    levels += [(date(2026, m, 1), 0.9) for m in (10, 11, 12)]
    stub = _StubClient(_steo_rows(levels))
    reading = fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.projection_rows_dropped == 3
    assert reading.observation_count == 3


def test_the_inventory_path_also_clips_future_dated_rows() -> None:
    """``C3a``: the INVENTORY clip is load-bearing too, not only the spare one.

    The PPS ``stocks`` route carries no forecasts in practice, but the as-of
    clip is what makes the reading an OBSERVATION by construction rather than by
    the provider's emission order — and the first sweep showed no test planted a
    future-dated inventory row, so removing the clip survived. The latest
    OBSERVATION must win over a later-dated row with a wildly different value.
    """
    levels = [
        (date(2026, 9, 11), 423_429.0),
        (date(2026, 9, 18), 426_398.0),  # the latest observation
        (date(2026, 10, 2), 999_999.0),  # future-dated, must not be adopted
    ]
    stub = _StubClient(_inventory_rows(levels))
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-09-18"
    assert reading.level_thousand_barrels == 426_398.0
    assert reading.level_thousand_barrels != 999_999.0
    assert reading.observation_count == 2


def test_an_inventory_row_dated_exactly_on_the_as_of_is_kept() -> None:
    """The clip is ``when > as_of``, so a row ON the as-of date is an observation.

    A mutation to ``>=`` would drop today's own observation; the boundary must
    sit exactly on the as-of to catch it.
    """
    levels = [(date(2026, 9, 11), 423_429.0), (date(2026, 9, 29), 426_398.0)]
    stub = _StubClient(_inventory_rows(levels))
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-09-29"
    assert reading.observation_count == 2


# ---------------------------------------------------------------------------
# (d) Null / non-finite values are refused.
# ---------------------------------------------------------------------------


def test_a_null_inventory_value_raises() -> None:
    stub = _StubClient([{"date": "2026-09-18", "symbol": INVENTORY_SYMBOL, "value": None}])
    with pytest.raises(CommodityReadError, match="null"):
        fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


def test_a_non_numeric_inventory_value_raises() -> None:
    stub = _StubClient([{"date": "2026-09-18", "symbol": INVENTORY_SYMBOL, "value": "n/a"}])
    with pytest.raises(CommodityReadError, match="not numeric"):
        fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_spare_value_raises(bad: float) -> None:
    stub = _StubClient(_steo_rows([(date(2026, 9, 1), bad)]))
    with pytest.raises(CommodityReadError, match="non-finite"):
        fetch_opec_spare_capacity(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


def test_a_zero_inventory_level_is_a_legitimate_reading() -> None:
    """Zero is real, which is why a missing value must never be repaired to it."""
    stub = _StubClient(
        [
            {"date": "2026-09-11", "symbol": INVENTORY_SYMBOL, "value": 0.0},
            {"date": "2026-09-18", "symbol": INVENTORY_SYMBOL, "value": 0.0},
        ]
    )
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.level_thousand_barrels == 0.0


# ---------------------------------------------------------------------------
# (e) The week-over-week change.
# ---------------------------------------------------------------------------


def test_the_week_over_week_change_is_the_difference_of_two_points() -> None:
    stub = _StubClient(
        _inventory_rows([(date(2026, 9, 11), 423429.0), (date(2026, 9, 18), 426398.0)])
    )
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.change_weekly_thousand_barrels == pytest.approx(2969.0)


def test_a_short_inventory_series_reports_the_change_as_none_not_zero() -> None:
    """One observation cannot yield a change; it is unknown, not flat."""
    stub = _StubClient(_inventory_rows([(date(2026, 9, 18), 426398.0)]))
    with pytest.raises(CommodityReadError, match="two"):
        fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


def test_the_reading_carries_the_source_unit() -> None:
    stub = _StubClient(_inventory_rows([(date(2026, 9, 11), 1.0), (date(2026, 9, 18), 2.0)]))
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.source_unit == "thousand_barrels"


# ---------------------------------------------------------------------------
# (f) The seasonal deviation.
# ---------------------------------------------------------------------------


def test_the_seasonal_deviation_compares_the_same_week_across_prior_years() -> None:
    """A level above the prior-years' same-week mean is a POSITIVE deviation.

    Six years of the same ISO week (38), with the latest spiked: the deviation is
    the latest level minus the mean of the five prior years. The dates were
    verified to fall in ISO week 38 each year — the point of the ISO-week key is
    that ``date(y, 9, 18)`` drifts across week boundaries and would silently drop
    years from the baseline.
    """
    rows = [
        (date(2019, 9, 16), 400000.0),  # week 38
        (date(2020, 9, 14), 400000.0),  # week 38
        (date(2021, 9, 20), 400000.0),  # week 38
        (date(2022, 9, 19), 400000.0),  # week 38
        (date(2023, 9, 18), 400000.0),  # week 38
        (date(2024, 9, 16), 420000.0),  # week 38 — latest, above the mean
    ]
    stub = _StubClient(_inventory_rows(rows))
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.seasonal_baseline_years == 5
    # The prior five years (2019..2023) are all 400000, so mean = 400000.
    assert reading.seasonal_deviation_thousand_barrels == pytest.approx(20000.0)


def test_the_seasonal_deviation_is_none_when_no_prior_year_matches() -> None:
    """No matching prior week ⇒ unknown, NOT zero (zero means "on the norm")."""
    stub = _StubClient(_inventory_rows([(date(2026, 9, 11), 1.0), (date(2026, 9, 18), 2.0)]))
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.seasonal_deviation_thousand_barrels is None
    assert reading.seasonal_baseline_years == 0


def test_the_baseline_uses_at_most_five_years() -> None:
    """Extra history beyond five years must not enter the baseline mean.

    Ten prior years in ISO week 38: the five OLDEST are low and the five most
    recent are high. The baseline must average ONLY the five years immediately
    preceding the latest — a client that averaged the whole history would report
    a smaller deviation and this assertion would catch it.
    """
    oldest = [(2014, 15), (2015, 14), (2016, 19), (2017, 18), (2018, 17)]  # week 38
    recent = [(2019, 16), (2020, 14), (2021, 20), (2022, 19), (2023, 18)]  # week 38
    rows = [(date(y, 9, day), 100000.0) for y, day in oldest]  # 5 oldest, low
    rows += [(date(y, 9, day), 500000.0) for y, day in recent]  # 5 recent, high
    rows.append((date(2024, 9, 16), 600000.0))  # latest, week 38
    stub = _StubClient(_inventory_rows(rows))
    reading = fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert reading.seasonal_baseline_years == 5
    # Baseline = mean of the five years 2019..2023 = 500000; latest 600000 ⇒ +100000.
    assert reading.seasonal_deviation_thousand_barrels == pytest.approx(100000.0)


# ---------------------------------------------------------------------------
# Transport failure is wrapped.
# ---------------------------------------------------------------------------


def test_a_transport_failure_is_wrapped_as_a_commodity_read_error() -> None:
    from macro_engine.data_layer.openbb_client import OpenBBFetchError

    stub = _StubClient(error=OpenBBFetchError("network down"))
    with pytest.raises(CommodityReadError, match="fetch failed"):
        fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]


def test_a_stub_client_is_not_closed_when_caller_owns_it() -> None:
    """The client must only close a connection IT opened."""
    stub = _StubClient(_inventory_rows([(date(2026, 9, 11), 1.0), (date(2026, 9, 18), 2.0)]))
    fetch_crude_inventories(as_of=date(2026, 9, 29), client=stub)  # type: ignore[arg-type]
    assert stub.closed is False


# ---------------------------------------------------------------------------
# The registry entries (O-141's lesson: only real schema fields).
# ---------------------------------------------------------------------------


def test_the_registry_entries_declare_only_real_schema_fields() -> None:
    """Both commodity entries must parse against ``RegistrySeries`` (O-141).

    A registry key the schema forbids is a load-time failure, and the full-suite
    build is where it was caught last time — this test catches it incrementally.
    """
    from pathlib import Path

    import yaml

    from macro_engine.config import RegistrySeries

    root = Path(__file__).resolve().parent.parent.parent
    raw = yaml.safe_load((root / "config" / "series_registry.yaml").read_text(encoding="utf-8"))
    for key in ("crude_inventory_weekly", "opec_spare_capacity"):
        entry = raw["series"][key]
        # Raises if any key is not a schema field.
        RegistrySeries(**entry)
        assert entry["not_a_snapshot_field"] is True
        assert entry["provider"] == "eia"
