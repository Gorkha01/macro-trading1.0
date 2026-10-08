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


def test_the_oil_table_path_uses_fetch_records_not_fetch_series() -> None:
    """The EIA MULTI-SYMBOL tables must go through ``fetch_records``.

    Measured 2026-09-29: the PPS ``stocks`` table returns 34 428 rows across 19
    symbols; ``fetch_series`` folds them into ONE date/value frame and the last
    row is total stocks, not the wanted crude level.

    ⚠️ SCOPED TO THE OIL PATH AT D-121. This test previously asserted the module
    called ``fetch_series`` NOWHERE, which was true while the module served only
    the EIA tables. The gold legs (``fetch_real_yield`` / ``fetch_vix_level``)
    legitimately use ``fetch_series`` — they are ONE-series-per-call FRED routes,
    the exact case ``fetch_series`` is correct for. Asserting on the module-level
    call set would now forbid the right thing, so the assertion is retargeted to
    the two OIL fetchers: their function bodies must call ``fetch_records`` and
    must NOT call ``fetch_series``.
    """
    tree = ast.parse(inspect.getsource(commodities_client))
    wanted = {"fetch_crude_inventories", "fetch_opec_spare_capacity"}
    checked: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            checked.add(node.name)
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            assert "fetch_records" in attrs, f"{node.name} must use fetch_records"
            assert "fetch_series" not in attrs, f"{node.name} must not use fetch_series"
    assert checked == wanted


def test_the_gold_legs_use_fetch_series_not_fetch_records() -> None:
    """The gold legs are one-series-per-call, so ``fetch_series`` is CORRECT.

    The inverse of the test above, and the reason that one had to be scoped: two
    households with two legitimate transports. A future edit that "unified" them
    onto one call would break one of the two — this pair pins which is which.
    """
    tree = ast.parse(inspect.getsource(commodities_client))
    wanted = {"fetch_real_yield", "fetch_vix_level"}
    checked: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            checked.add(node.name)
            attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            assert "fetch_series" in attrs, f"{node.name} must use fetch_series"
            assert "fetch_records" not in attrs, f"{node.name} must not use fetch_records"
    assert checked == wanted


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
    """Every commodity entry must parse against ``RegistrySeries`` (O-141).

    A registry key the schema forbids is a load-time failure, and the full-suite
    build is where it was caught last time — this test catches it incrementally.
    The D-121 gold entries are included, because the increment added two new keys
    to the same file and a typo there would redden the whole registry.
    """
    from pathlib import Path

    import yaml

    from macro_engine.config import RegistrySeries

    root = Path(__file__).resolve().parent.parent.parent
    raw = yaml.safe_load((root / "config" / "series_registry.yaml").read_text(encoding="utf-8"))
    for key in (
        "crude_inventory_weekly",
        "opec_spare_capacity",
        "gold_real_yield_10y",
        "gold_crisis_vix",
        "metals_copper",
        "metals_iron_ore",
        "metals_aluminum",
    ):
        entry = raw["series"][key]
        # Raises if any key is not a schema field.
        RegistrySeries(**entry)
        assert entry["not_a_snapshot_field"] is True


def test_the_blocked_gold_driver_has_no_registry_entry() -> None:
    """The CB-purchases trend is a MEASURED BLOCK, so it must have NO entry.

    A registry entry implies a source. Registering the blocked leg would be the
    inverse of the D-043 defect: a claim of a source that does not exist. The
    block is recorded as prose in the registry, and this test pins that there is
    no accidental ``central_bank_net_purchases_trend`` entry.
    """
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parent.parent.parent
    raw = yaml.safe_load((root / "config" / "series_registry.yaml").read_text(encoding="utf-8"))
    assert "central_bank_net_purchases_trend" not in raw["series"]
    assert "gold_cb_purchases" not in raw["series"]


def test_the_gold_legs_are_fred_not_eia() -> None:
    """The two live gold legs are FRED; the oil legs are EIA. Pinned so a route
    swap is caught — and because the model's independence count (1) DEPENDS on
    this being one provider."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parent.parent.parent
    raw = yaml.safe_load((root / "config" / "series_registry.yaml").read_text(encoding="utf-8"))
    for key in ("gold_real_yield_10y", "gold_crisis_vix"):
        entry = raw["series"][key]
        assert entry["provider"] == "fred"
        assert entry["endpoint"] == "economy.fred_series"


# =============================================================================
# The GOLD DRIVERS (Appendix D, D-121): two live FRED legs + one block
# =============================================================================


class _SeriesStubClient:
    """A stand-in supporting ``fetch_series`` for the two FRED gold legs.

    Distinct from ``_StubClient`` (which serves ``fetch_records`` for the EIA
    tables) because the gold legs go through the one-series-per-call FRED route
    and therefore need the tidy-frame transport, not the record-level one. Having
    both stubs is itself the assertion that the two households use different
    routes.
    """

    def __init__(self, frame: Any = None, error: Exception | None = None) -> None:
        self._frame = frame
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def fetch_series(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        import pandas as pd

        if self._frame is None:
            return pd.DataFrame({"date": [], "value": []})
        return self._frame

    def close(self) -> None:
        self.closed = True


def _fred_frame(pairs: list[tuple[date, float]]) -> Any:
    """A tidy FRED-shaped frame: ``date`` and ``value`` columns."""
    import pandas as pd

    return pd.DataFrame({"date": [d.isoformat() for d, _ in pairs], "value": [v for _, v in pairs]})


def test_the_real_yield_uses_the_fred_route_and_symbol() -> None:
    from macro_engine.data_layer.commodities_client import (
        REAL_YIELD_SYMBOL,
        fetch_real_yield,
    )

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 23), 2.76), (date(2026, 9, 24), 2.85)]))
    reading = fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert reading.symbol == REAL_YIELD_SYMBOL == "DFII10"
    assert reading.yield_percent == 2.85
    call = stub.calls[0]
    assert call["provider"] == "fred"
    assert call["endpoint"] == "economy.fred_series"
    assert call["params"]["symbol"] == "DFII10"


def test_the_vix_uses_the_fred_route_and_symbol() -> None:
    from macro_engine.data_layer.commodities_client import (
        VIX_SYMBOL,
        fetch_vix_level,
    )

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 22), 14.21)]))
    reading = fetch_vix_level(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert reading.symbol == VIX_SYMBOL == "VIXCLS"
    assert reading.level == 14.21
    assert stub.calls[0]["params"]["symbol"] == "VIXCLS"


def test_the_real_yield_reading_carries_the_prior_point() -> None:
    """Appendix D's input is a CHANGE, so the reading must carry two points."""
    from macro_engine.data_layer.commodities_client import fetch_real_yield

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 23), 2.76), (date(2026, 9, 24), 2.85)]))
    reading = fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert reading.prior_observation_date == "2026-09-23"
    assert reading.prior_yield_percent == 2.76


def test_a_single_point_yield_series_has_no_prior() -> None:
    """One observation cannot form a change — ``None``, never ``0.0`` (D-078)."""
    from macro_engine.data_layer.commodities_client import fetch_real_yield

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 24), 2.85)]))
    reading = fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert reading.prior_yield_percent is None
    assert reading.prior_observation_date is None


def test_the_change_in_bp_is_the_level_difference_times_one_hundred() -> None:
    """The conversion is a NAMED constant, not an inlined 100 (D-118's lesson)."""
    from macro_engine.data_layer.commodities_client import (
        BASIS_POINTS_PER_PERCENT,
        fetch_real_yield,
        real_yield_change_bp,
    )

    assert BASIS_POINTS_PER_PERCENT == 100.0
    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 23), 2.76), (date(2026, 9, 24), 2.85)]))
    reading = fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert real_yield_change_bp(reading) == pytest.approx(9.0)


def test_the_change_is_none_without_a_prior() -> None:
    from macro_engine.data_layer.commodities_client import (
        fetch_real_yield,
        real_yield_change_bp,
    )

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 24), 2.85)]))
    reading = fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert real_yield_change_bp(reading) is None


def test_the_change_reverses_sign_on_a_falling_yield() -> None:
    """A FALL is negative — the sign is the primary layer's whole content."""
    from macro_engine.data_layer.commodities_client import (
        fetch_real_yield,
        real_yield_change_bp,
    )

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 23), 2.85), (date(2026, 9, 24), 2.60)]))
    reading = fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert real_yield_change_bp(reading) == pytest.approx(-25.0)


def test_the_real_yield_clips_future_dated_rows() -> None:
    """An observation after ``as_of`` must be excluded (the O-134 discipline).

    A caller passing an as-of in the past must get the answer true then, not the
    newest row — the same clip the oil client applies to the STEO tail.
    """
    from macro_engine.data_layer.commodities_client import fetch_real_yield

    stub = _SeriesStubClient(
        _fred_frame(
            [
                (date(2026, 9, 20), 2.70),
                (date(2026, 9, 21), 2.80),
                (date(2026, 9, 25), 9.99),  # AFTER the as-of
            ]
        )
    )
    reading = fetch_real_yield(as_of=date(2026, 9, 22), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-09-21"
    assert reading.yield_percent == 2.80


def test_a_row_dated_exactly_on_the_as_of_is_kept() -> None:
    from macro_engine.data_layer.commodities_client import fetch_real_yield

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 22), 2.80)]))
    reading = fetch_real_yield(as_of=date(2026, 9, 22), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-09-22"


def test_an_empty_fred_frame_raises() -> None:
    from macro_engine.data_layer.commodities_client import fetch_real_yield

    stub = _SeriesStubClient(_fred_frame([]))
    with pytest.raises(CommodityReadError):
        fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]


def test_a_frame_without_the_tidy_columns_raises() -> None:
    """A missing ``value`` column must refuse, never guess which column is which."""
    import pandas as pd

    from macro_engine.data_layer.commodities_client import fetch_vix_level

    stub = _SeriesStubClient(pd.DataFrame({"date": ["2026-09-22"], "close": [14.21]}))
    with pytest.raises(CommodityReadError, match="unexpected frame shape"):
        fetch_vix_level(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]


def test_all_rows_after_the_as_of_raises() -> None:
    from macro_engine.data_layer.commodities_client import fetch_vix_level

    stub = _SeriesStubClient(_fred_frame([(date(2026, 10, 1), 20.0)]))
    with pytest.raises(CommodityReadError, match="no observation at or before"):
        fetch_vix_level(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]


def test_a_null_fred_value_is_dropped_not_repaired() -> None:
    """A null in the frame is DROPPED before ordering, never turned into zero."""
    import pandas as pd

    from macro_engine.data_layer.commodities_client import fetch_vix_level

    frame = pd.DataFrame({"date": ["2026-09-21", "2026-09-22"], "value": [None, 14.21]})
    stub = _SeriesStubClient(frame)
    reading = fetch_vix_level(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert reading.level == 14.21


def test_the_ordered_latest_wins_regardless_of_row_order() -> None:
    """FRED returns ascending, but a reversed response must not pick the oldest."""
    from macro_engine.data_layer.commodities_client import fetch_vix_level

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 22), 14.21), (date(2026, 9, 21), 14.87)]))
    reading = fetch_vix_level(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-09-22"
    assert reading.level == 14.21


def test_a_transport_failure_on_the_yield_is_wrapped() -> None:
    from macro_engine.data_layer.commodities_client import fetch_real_yield
    from macro_engine.data_layer.openbb_client import OpenBBFetchError

    stub = _SeriesStubClient(error=OpenBBFetchError("boom"))
    with pytest.raises(CommodityReadError, match="could not be read"):
        fetch_real_yield(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]


def test_a_transport_failure_on_the_vix_is_wrapped() -> None:
    from macro_engine.data_layer.commodities_client import fetch_vix_level
    from macro_engine.data_layer.openbb_client import OpenBBFetchError

    stub = _SeriesStubClient(error=OpenBBFetchError("boom"))
    with pytest.raises(CommodityReadError, match="could not be read"):
        fetch_vix_level(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]


def test_a_gold_series_stub_is_not_closed_when_caller_owns_it() -> None:
    from macro_engine.data_layer.commodities_client import fetch_vix_level

    stub = _SeriesStubClient(_fred_frame([(date(2026, 9, 22), 14.21)]))
    fetch_vix_level(as_of=date(2026, 9, 27), client=stub)  # type: ignore[arg-type]
    assert stub.closed is False


def test_the_two_gold_units_are_declared_distinctly() -> None:
    """Percent and index points are different units and must not be conflated."""
    from macro_engine.data_layer.commodities_client import (
        REAL_YIELD_SOURCE_UNIT,
        VIX_SOURCE_UNIT,
    )

    assert REAL_YIELD_SOURCE_UNIT == "percent"
    assert VIX_SOURCE_UNIT == "index_points"
    assert REAL_YIELD_SOURCE_UNIT != VIX_SOURCE_UNIT


# =============================================================================
# The METALS complex (Module 10.3, D-122): three live FRED legs
# =============================================================================
#
# The authority tags all three legs "LIVE/BLOCKED" and singles out iron ore as
# "no clean free source — likely BLOCKED" (Section 21.1, AGENTS.md:5395;
# repeated at Section 21.4's Loophole Ledger item 8). MEASURED 2026-09-27 all
# THREE are LIVE, which makes iron ore the repository's **seventh FALSE BLOCK**.
# These tests assert what replacing that tag obliges:
#
#   (a) the SYMBOL and the ROUTE (FRED, one series per call — not the EIA table
#       route the oil household uses),
#   (b) the UNIT read from the provider's metadata (USD per metric ton), which a
#       web search claiming "USD per pound" for copper gets WRONG,
#   (c) the CHANGE is DERIVED by differencing two consecutive monthly vintages,
#       never adopted from a published field,
#   (d) a ``prior`` of exactly zero REFUSES rather than publishing an infinity,
#   (e) a single-observation series reports ``None`` — never ``0.0`` — for both
#       the prior and the change (the D-078 class), and
#   (f) ``as_of`` clips future-dated rows so a past-dated call is deterministic.
#
# The values are real, captured live on 2026-09-27.


def _metals_frame(pairs: list[tuple[date, float]]) -> Any:
    """Three monthly vintages, as FRED serves them (ascending, tidy frame)."""
    return _fred_frame(pairs)


def test_the_copper_leg_uses_the_fred_route_and_symbol() -> None:
    from macro_engine.data_layer.commodities_client import (
        COPPER_SYMBOL,
        fetch_copper_change,
    )

    stub = _SeriesStubClient(
        _metals_frame([(date(2026, 5, 1), 9000.0), (date(2026, 6, 1), 9500.0)])
    )
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.symbol == COPPER_SYMBOL == "PCOPPUSDM"
    assert reading.level == 9500.0
    call = stub.calls[0]
    assert call["provider"] == "fred"
    assert call["endpoint"] == "economy.fred_series"
    assert call["params"]["symbol"] == "PCOPPUSDM"


def test_the_iron_ore_leg_uses_the_fred_route_and_symbol() -> None:
    """The leg the authority called BLOCKED has a working FRED route (the 7th)."""
    from macro_engine.data_layer.commodities_client import (
        IRON_ORE_SYMBOL,
        fetch_iron_ore_change,
    )

    stub = _SeriesStubClient(_metals_frame([(date(2026, 5, 1), 100.0), (date(2026, 6, 1), 92.0)]))
    reading = fetch_iron_ore_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.symbol == IRON_ORE_SYMBOL == "PIORECRUSDM"
    assert stub.calls[0]["params"]["symbol"] == "PIORECRUSDM"


def test_the_aluminum_leg_uses_the_fred_route_and_symbol() -> None:
    from macro_engine.data_layer.commodities_client import (
        ALUMINUM_SYMBOL,
        fetch_aluminum_change,
    )

    stub = _SeriesStubClient(
        _metals_frame([(date(2026, 5, 1), 2400.0), (date(2026, 6, 1), 2450.0)])
    )
    reading = fetch_aluminum_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.symbol == ALUMINUM_SYMBOL == "PALUMUSDM"
    assert stub.calls[0]["params"]["symbol"] == "PALUMUSDM"


def test_the_three_metal_symbols_are_distinct() -> None:
    """A copy-paste that gave two legs the same symbol would be invisible otherwise."""
    from macro_engine.data_layer.commodities_client import (
        ALUMINUM_SYMBOL,
        COPPER_SYMBOL,
        IRON_ORE_SYMBOL,
    )

    assert len({COPPER_SYMBOL, IRON_ORE_SYMBOL, ALUMINUM_SYMBOL}) == 3


def test_the_metal_reading_carries_the_source_unit() -> None:
    """The unit is USD per METRIC TON, from the provider — not a web guess."""
    from macro_engine.data_layer.commodities_client import (
        METALS_SOURCE_UNIT,
        fetch_copper_change,
    )

    stub = _SeriesStubClient(
        _metals_frame([(date(2026, 5, 1), 9000.0), (date(2026, 6, 1), 9500.0)])
    )
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.source_unit == METALS_SOURCE_UNIT == "usd_per_metric_ton"


def test_the_metal_change_is_the_difference_of_two_vintages() -> None:
    """The ``*_change_pct`` input is DERIVED, not a published field."""
    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(
        _metals_frame([(date(2026, 5, 1), 8000.0), (date(2026, 6, 1), 8400.0)])
    )
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.change_pct == pytest.approx(5.0)
    assert reading.prior_level == 8000.0
    assert reading.prior_observation_date == "2026-05-01"


def test_the_metal_change_reverses_sign_on_a_fall() -> None:
    """A FALL is negative — the sign is the whole content of the classification."""
    from macro_engine.data_layer.commodities_client import fetch_iron_ore_change

    stub = _SeriesStubClient(_metals_frame([(date(2026, 5, 1), 100.0), (date(2026, 6, 1), 90.0)]))
    reading = fetch_iron_ore_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.change_pct == pytest.approx(-10.0)


def test_a_single_point_metal_series_has_no_prior_and_no_change() -> None:
    """One vintage cannot form a change — ``None``, never ``0.0`` (D-078)."""
    from macro_engine.data_layer.commodities_client import fetch_aluminum_change

    stub = _SeriesStubClient(_metals_frame([(date(2026, 6, 1), 2450.0)]))
    reading = fetch_aluminum_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.prior_observation_date is None
    assert reading.prior_level is None
    assert reading.change_pct is None


def test_a_zero_prior_metal_price_yields_an_unknown_change_not_an_infinity() -> None:
    """F-COM-002: a ``0.0`` prior makes the percent undefined — but not the level.

    Returning ``inf`` would make every one of the classifier's comparisons false
    and the model would report MIXED — a claim about the PATTERN that is really a
    claim about a broken leg. So the change is UNKNOWN (``None``), the LEVEL is
    still published, and the CAUSE is named on the reading so a consumer's
    disclosure can state it rather than assume "too few observations".
    """
    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(_metals_frame([(date(2026, 5, 1), 0.0), (date(2026, 6, 1), 8400.0)]))
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]

    assert reading.change_pct is None
    assert reading.level == 8400.0  # the LEVEL survives the unknown change
    assert reading.prior_level == 0.0
    assert "exactly 0.0" in (reading.change_unavailable_reason or "")


def test_the_metal_reading_reports_the_observation_count() -> None:
    """The count lets a caller see how deep the series behind the change is."""
    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(
        _metals_frame(
            [
                (date(2026, 3, 1), 8000.0),
                (date(2026, 4, 1), 8100.0),
                (date(2026, 5, 1), 8200.0),
                (date(2026, 6, 1), 8400.0),
            ]
        )
    )
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.observation_count == 4


def test_the_metal_change_clips_future_dated_rows() -> None:
    """An observation after ``as_of`` must be excluded (the O-134 discipline)."""
    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(
        _metals_frame(
            [
                (date(2026, 5, 1), 8000.0),
                (date(2026, 6, 1), 8400.0),
                (date(2026, 8, 1), 9999.0),  # AFTER the as-of
            ]
        )
    )
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-06-01"
    assert reading.level == 8400.0
    assert reading.observation_count == 2


def test_a_metal_row_dated_exactly_on_the_as_of_is_kept() -> None:
    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(
        _metals_frame([(date(2026, 6, 30), 8400.0), (date(2026, 5, 1), 8000.0)])
    )
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-06-30"


def test_an_empty_metal_frame_raises() -> None:
    """An empty frame dies in the shared observation helper, naming the series."""
    from macro_engine.data_layer.commodities_client import fetch_aluminum_change

    stub = _SeriesStubClient(_metals_frame([]))
    with pytest.raises(CommodityReadError, match="no observations"):
        fetch_aluminum_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]


def test_all_metal_rows_after_the_as_of_raises() -> None:
    from macro_engine.data_layer.commodities_client import fetch_iron_ore_change

    stub = _SeriesStubClient(_metals_frame([(date(2026, 8, 1), 92.0)]))
    with pytest.raises(CommodityReadError, match="no observation at or before"):
        fetch_iron_ore_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]


def test_a_null_metal_value_is_dropped_not_repaired() -> None:
    """A null in the frame is DROPPED before ordering, never turned into zero."""
    import pandas as pd

    from macro_engine.data_layer.commodities_client import fetch_copper_change

    frame = pd.DataFrame({"date": ["2026-05-01", "2026-06-01"], "value": [None, 8400.0]})
    stub = _SeriesStubClient(frame)
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.level == 8400.0
    assert reading.observation_count == 1


def test_the_metal_latest_wins_regardless_of_row_order() -> None:
    """FRED returns ascending, but a reversed response must not pick the oldest."""
    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(
        _metals_frame([(date(2026, 6, 1), 8400.0), (date(2026, 5, 1), 8000.0)])
    )
    reading = fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-06-01"
    assert reading.change_pct == pytest.approx(5.0)


def test_a_transport_failure_on_any_metal_is_wrapped_and_names_the_metal() -> None:
    """The message must say WHICH leg died, not just print a bare symbol."""
    from macro_engine.data_layer.commodities_client import fetch_iron_ore_change
    from macro_engine.data_layer.openbb_client import OpenBBFetchError

    stub = _SeriesStubClient(error=OpenBBFetchError("boom"))
    with pytest.raises(CommodityReadError, match="iron_ore"):
        fetch_iron_ore_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]


def test_a_frame_without_the_tidy_metal_columns_raises() -> None:
    import pandas as pd

    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(pd.DataFrame({"date": ["2026-06-01"], "close": [8400.0]}))
    with pytest.raises(CommodityReadError, match="unexpected frame shape"):
        fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]


def test_a_metal_series_stub_is_not_closed_when_caller_owns_it() -> None:
    from macro_engine.data_layer.commodities_client import fetch_copper_change

    stub = _SeriesStubClient(
        _metals_frame([(date(2026, 5, 1), 8000.0), (date(2026, 6, 1), 8400.0)])
    )
    fetch_copper_change(as_of=date(2026, 6, 30), client=stub)  # type: ignore[arg-type]
    assert stub.closed is False


def test_percent_change_is_public_and_returns_none_for_a_zero_prior() -> None:
    """F-COM-002: the helper is unit-testable directly, so its contract is asserted ON it.

    A zero prior yields ``None`` — the shape this module already uses for an
    unknown change — rather than raising, so the LEVEL survives and the two
    clients agree on what a zero prior means.
    """
    from macro_engine.data_layer.commodities_client import _percent_change

    assert _percent_change(110.0, 100.0) == pytest.approx(10.0)
    assert _percent_change(110.0, 0.0) is None


def test_the_registry_carries_the_three_metal_series_as_fred() -> None:
    """The registry entries must name the FRED route and the metric-ton unit."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parent.parent.parent
    registry = yaml.safe_load(
        (root / "config" / "series_registry.yaml").read_text(encoding="utf-8")
    )
    series = registry["series"]
    for key, symbol in (
        ("metals_copper", "PCOPPUSDM"),
        ("metals_iron_ore", "PIORECRUSDM"),
        ("metals_aluminum", "PALUMUSDM"),
    ):
        entry = series[key]
        assert entry["provider"] == "fred"
        assert entry["endpoint"] == "economy.fred_series"
        assert entry["symbol"] == symbol
        assert entry["units"] == "usd_per_metric_ton"
        assert entry["frequency"] == "monthly"


# ===========================================================================
# R-5 — `_parse_date` must return a real `date`, never a leaked datetime
# ===========================================================================
# The SAME `datetime`-is-a-`date` trap fixed in `openbb_client.to_observation_date`
# (R-4), repeated in this module's own date parser. The original guard led with
# `if isinstance(raw, date): return raw`, and because `pd.Timestamp` and
# `datetime` are both `date` subclasses, that branch returned them UNCHANGED.
#
# It is reachable rather than theoretical. MEASURED: `OpenBBClient._coerce_records`
# converts a DataFrame-shaped payload with `to_dict(orient="records")`, and a
# datetime column becomes `pd.Timestamp` values; those rows reach `_parse_date`
# at the two `fetch_records` call sites (inventories at line 278, spare capacity
# at line 405). The name collision with R-4 is not a coincidence — it is one
# defect class, transcribed twice, which is why the fix uses the same
# most-derived-type-first ordering.
#
# The two live consequences, both measured against the pre-fix code: a
# `Timestamp > date` comparison raises `TypeError` and escapes as an uncaught
# crash instead of `CommodityReadError`; and `observation_date=when.isoformat()`
# publishes `'2026-09-18T00:00:00'` instead of `'2026-09-18'`.


def test_parse_date_collapses_a_datetime_to_a_date() -> None:
    """A `datetime` must be collapsed, not passed through (the R-5 defect)."""
    from datetime import UTC, datetime

    out = commodities_client._parse_date(datetime(2026, 9, 18, 13, 45, tzinfo=UTC), context="probe")
    assert type(out) is date
    assert out == date(2026, 9, 18)


def test_parse_date_collapses_a_pandas_timestamp() -> None:
    """A `pd.Timestamp` is the shape `_coerce_records` actually produces.

    This is the reachable input: a table endpoint that returns a DataFrame has
    its datetime column converted to `Timestamp` by `to_dict(orient="records")`,
    and the inventory/spare-capacity paths then parse it here.
    """
    import pandas as pd

    out = commodities_client._parse_date(pd.Timestamp("2026-09-18 13:45:00"), context="probe")
    assert type(out) is date
    assert out == date(2026, 9, 18)


def test_parse_date_collapses_a_numpy_datetime64() -> None:
    """A `numpy.datetime64` is a legal frame cell after a pandas round-trip."""
    import numpy as np

    out = commodities_client._parse_date(np.datetime64("2026-09-18T13:45:00"), context="probe")
    assert type(out) is date
    assert out == date(2026, 9, 18)


def test_parse_date_passes_a_plain_date_through_unchanged() -> None:
    """Positive control: the common case is untouched and is a real `date`."""
    original = date(2026, 9, 18)
    out = commodities_client._parse_date(original, context="probe")
    assert type(out) is date
    assert out is original


def test_parse_date_handles_strings_with_and_without_a_time_part() -> None:
    """The string branch still accepts both shapes the routes were measured sending."""
    for raw in ("2026-09-18", "2026-09-18T00:00:00", "2026-09-18 00:00:00"):
        out = commodities_client._parse_date(raw, context="probe")
        assert type(out) is date, f"{raw!r} -> {type(out).__name__} (leak)"
        assert out == date(2026, 9, 18)


def test_parse_date_still_refuses_empty_and_unparseable_values() -> None:
    """The fix must not weaken the refusal contract while widening the accept set."""
    for bad in ("", "   ", "not-a-date"):
        with pytest.raises(CommodityReadError):
            commodities_client._parse_date(bad, context="probe")


def test_a_timestamp_dated_row_does_not_crash_the_inventory_as_of_clip() -> None:
    """End-to-end: a `Timestamp`-dated row must clip cleanly, not raise `TypeError`.

    This is the defect's live blast radius reproduced through the real fetch
    path. `_parse_date` returning a `Timestamp` made `when > as_of` raise
    `TypeError: Cannot compare Timestamp with datetime.date`, which is not a
    `CommodityReadError` and would escape the model's handler. With the fix the
    comparison is between two `date`s and the row clips normally.
    """
    import pandas as pd

    rows = _inventory_rows([(date(2026, 9, 18), 426_398.0), (date(2026, 9, 11), 423_429.0)])
    # Replace the ISO date strings with `Timestamp`s, as a DataFrame-shaped
    # payload would arrive after `_coerce_records`.
    for row in rows:
        if row.get("symbol") == INVENTORY_SYMBOL:
            row["date"] = pd.Timestamp(row["date"])

    client = _StubClient(rows)
    # ``_StubClient`` is a structural stand-in, not an ``OpenBBClient``; the
    # ignore is the same one every other stub call site in this file carries.
    reading = fetch_crude_inventories(as_of=date(2026, 9, 22), client=client)  # type: ignore[arg-type]
    assert reading.observation_date == "2026-09-18"
    assert reading.level_thousand_barrels == 426_398.0


# ---------------------------------------------------------------------------
# F-COM-001 — the `.date()` branch must not be mis-described
# ---------------------------------------------------------------------------
def test_the_datetime64_carrier_is_not_a_dot_date_carrier() -> None:
    """F-COM-001: a comment named ``np.datetime64`` as a ``.date()`` example.

    Measured: ``np.datetime64`` exposes **no** ``.date`` attribute, so it reaches
    the STRING parse instead. The function's OUTCOME is right either way — which
    is why the existing test asserts the outcome rather than the branch — but the
    stated mechanism would have sent a reader looking for a branch that never
    runs for the carrier it named.
    """
    from pathlib import Path

    import numpy as np

    assert not hasattr(np.datetime64("2026-09-18"), "date"), "the premise changed"

    src = Path(commodities_client.__file__).read_text(encoding="utf-8")
    assert "np.datetime64 and friends) exposes" not in src, "the false claim is back"
    assert "is NOT one of them" in src


# ---------------------------------------------------------------------------
# F-COM-002 — the two READ-not-tested behaviours, now pinned
# ---------------------------------------------------------------------------
def test_a_duplicate_row_in_one_iso_week_is_counted_once() -> None:
    """The seasonal baseline takes ONE point per ISO year, not one per row.

    The match is on the ISO WEEK NUMBER and ISO year — **not** the weekday — so a
    year carrying two rows in the same week contributes the LATER value and one
    year of baseline. Note the two 2025 rows below are ISO weekdays 2 and 5: if
    the match required the same weekday, neither would qualify.
    """
    from macro_engine.data_layer.commodities_client import _seasonal_deviation

    latest = date(2026, 9, 18)  # ISO 2026-W38
    assert latest.isocalendar().week == 38
    parsed = [
        (date(2025, 9, 16), 100.0),  # 2025-W38, weekday 2
        (date(2025, 9, 19), 200.0),  # 2025-W38, weekday 5  <- the later one wins
        (date(2026, 9, 18), 300.0),  # the latest itself, excluded from its own baseline
    ]
    deviation, years_used = _seasonal_deviation(parsed, latest, 300.0, years=5)

    assert years_used == 1, "one ISO year contributed, not two"
    assert deviation == pytest.approx(300.0 - 200.0), "the LATER same-week row did not win"


def test_observed_pairs_returns_empty_when_every_row_is_clipped() -> None:
    """The helper returns ``[]``; judging that is the CALLER's job.

    Every caller raises on an empty list (two call sites assert it), because only
    the caller knows whether an all-clipped series is fatal. Pinning the helper's
    own contract here keeps that split explicit rather than implied.
    """
    from macro_engine.data_layer.commodities_client import _observed_pairs

    frame = _metals_frame([(date(2026, 5, 1), 8400.0), (date(2026, 6, 1), 8500.0)])
    pairs = _observed_pairs(frame, symbol="PCOPPUSDM", as_of=date(2026, 1, 1), label="copper price")
    assert pairs == []
