"""FX reserve stocks — the source behind ``intervention_capacity``.

What these tests are for
------------------------
Section 20.9 declares ``fx_reserves_usd_bn`` with **no source**, and the registry
had no entry for it, so under Section 21.1's default rule it read as BLOCKED.
Measured 2026-09-27 it is reachable, which makes this the **fourth FALSE BLOCK**
this repository has caught (D-043's class). Replacing a block with a source
introduces the same set of hazards D-117 recorded for the PPP legs, plus one of
its own, and each is asserted here:

(a) **The MILLIONS/BILLIONS conversion happens exactly once, and is visible.**
    ``TRESEGJPM052N`` reads 1083420.49 in MILLIONS; the model's contract is
    BILLIONS. The client deliberately returns the SOURCE unit so the conversion
    is a single line in the caller, and this file asserts both halves — that the
    client does NOT pre-divide, and that the model does.
(b) **An empty or malformed frame is a FAILURE, not zero reserves.** "No data"
    and "zero" are different facts and only one of them is a reserve position.
(c) **The latest OBSERVATION is selected, not the last row.** Row order is not a
    documented contract; a reversed response would otherwise turn "latest" into
    "oldest" silently.
(d) **The change is ``None``, never ``0.0``, when the series is too short.** A
    zero reads as "stable", which is an assertion the data does not make.
(e) **The module never opens its own HTTP connection.** It goes through the
    project's own ``OpenBBClient``, which owns the base URL, the retry policy and
    the pinned User-Agent (D-087.25). Asserted on the AST, because a second route
    to the same host is exactly what that lesson was written to prevent.
(f) **The registry entries declare only real schema fields** (O-141, which the
    full suite found rather than any incremental test).

The values used below are the real ones, captured live on 2026-09-27.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import macro_engine.data_layer.reserves_client as reserves_client
from macro_engine.data_layer.reserves_client import (
    RESERVE_SERIES,
    ReservesReadError,
    fetch_reserves,
)


def _frame(rows: list[tuple[Any, float]], *, label: str = "fx_reserves_jp") -> pd.DataFrame:
    """A real ``fetch_series`` return: the client's tidy 5-column shape.

    Measured live 2026-09-27: ``economy.fred_series`` returns one ROW per
    observation with ``date`` and ``value`` as COLUMNS — shape ``(843, 5)``,
    columns ``date``, ``value``, ``series_id``, ``source``, ``retrieved_at``.
    It is explicitly NOT a frame indexed by date, which is why the client selects
    its columns by name.
    """
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "value": [r[1] for r in rows],
            "series_id": [label] * len(rows),
            "source": ["openbb:package"] * len(rows),
            "retrieved_at": ["2026-09-27T01:18:19+00:00"] * len(rows),
        }
    )


class _StubClient:
    """An ``OpenBBClient`` stand-in returning a canned frame or raising."""

    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None) -> None:
        self._frame = frame
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def fetch_series(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._frame is not None
        return self._frame

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# (e) The route: no private HTTP, no second client.
# ---------------------------------------------------------------------------


def test_the_module_never_imports_httpx_or_requests_directly() -> None:
    """It must route through ``OpenBBClient``, not open its own connection.

    D-087.25's lesson: a second route to the same host carries a second,
    silently-divergent User-Agent and retry policy. Asserted on the AST so a
    future "helpful" direct call fails a test rather than review.
    """
    source = inspect.getsource(reserves_client)
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "httpx" not in imported
    assert "requests" not in imported
    assert "aiohttp" not in imported


def test_the_module_uses_the_projects_own_openbb_client() -> None:
    """The import is present and is the project's client, not a local shim."""
    source = inspect.getsource(reserves_client)
    assert "from macro_engine.data_layer.openbb_client import" in source
    assert "OpenBBClient" in source


def test_no_local_openbb_host_literal() -> None:
    """The base URL belongs to the client, never to this module."""
    source = inspect.getsource(reserves_client)
    assert "127.0.0.1" not in source
    assert "6900" not in source
    assert "6901" not in source


# ---------------------------------------------------------------------------
# (a) The unit: source unit is preserved, the conversion is the caller's.
# ---------------------------------------------------------------------------


def test_the_client_returns_the_source_unit_without_converting() -> None:
    """``reserves_usd_mn`` is MILLIONS — the client must not pre-divide.

    The real Japan reading is 1083420.490020889 mn. A client that "helpfully"
    returned billions would make the conversion invisible; keeping the source
    unit makes the 1000x step a single auditable line in the model.
    """
    stub = _StubClient(_frame([(date(2026, 8, 1), 1083420.490020889)]))
    reading = fetch_reserves("jp", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.reserves_usd_mn == pytest.approx(1083420.490020889, rel=1e-12)
    assert reading.source_unit == "millions of USD"


def test_the_pass_through_does_not_scale_the_value() -> None:
    """A round number survives unchanged, pinning the absence of any division."""
    stub = _StubClient(_frame([(date(2026, 8, 1), 1000.0)]))
    reading = fetch_reserves("jp", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.reserves_usd_mn == 1000.0


# ---------------------------------------------------------------------------
# (b) A failure is never an empty frame.
# ---------------------------------------------------------------------------


def test_an_empty_frame_raises_rather_than_reading_as_zero() -> None:
    """An empty response is a failed read, not a depleted reserve position."""
    columns = ["date", "value", "series_id", "source", "retrieved_at"]
    stub = _StubClient(pd.DataFrame(columns=columns))
    with pytest.raises(ReservesReadError, match="no observations"):
        fetch_reserves("jp", client=stub)  # type: ignore[arg-type]


def test_an_all_null_series_raises() -> None:
    """Only missing values is the same failure as empty."""
    frame = _frame([(date(2026, 7, 1), float("nan")), (date(2026, 8, 1), float("nan"))])
    stub = _StubClient(frame)
    with pytest.raises(ReservesReadError, match="only missing"):
        fetch_reserves("jp", client=stub)  # type: ignore[arg-type]


def test_a_frame_without_the_expected_columns_raises() -> None:
    """An unexpected shape is refused, not guessed at.

    The dangerous near-miss this guards: a frame indexed by date with one value
    column would make ``frame.iloc[:, 0]`` the DATE column, and a route that
    returned dates as integer epochs would then publish a reserve stock from
    1970 — a plausible-looking number of the wrong kind entirely.
    """
    stub = _StubClient(pd.DataFrame({"observation": [1.0, 2.0]}))
    with pytest.raises(ReservesReadError, match="unexpected"):
        fetch_reserves("jp", client=stub)  # type: ignore[arg-type]


def test_a_transport_failure_is_wrapped_as_a_reserves_read_error() -> None:
    """A client failure is re-raised in this module's own vocabulary."""
    from macro_engine.data_layer.openbb_client import OpenBBFetchError

    stub = _StubClient(error=OpenBBFetchError("boom"))
    with pytest.raises(ReservesReadError, match="could not be read"):
        fetch_reserves("jp", client=stub)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (c) The latest OBSERVATION is selected, not the last row.
# ---------------------------------------------------------------------------


def test_the_latest_observation_is_selected_regardless_of_row_order() -> None:
    """Row order is not a documented contract.

    The fixture is deliberately DESCENDING, so a client that took ``iloc[-1]``
    would return the OLDEST value. The observation date must follow the value it
    belongs to.
    """
    frame = _frame(
        [
            (date(2026, 8, 1), 1083420.49),
            (date(2026, 7, 1), 1177579.0),
            (date(2026, 6, 1), 1177971.0),
        ]
    )
    stub = _StubClient(frame)
    reading = fetch_reserves("jp", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.reserves_usd_mn == pytest.approx(1083420.49)
    assert reading.observation_date == "2026-08-01"


def test_a_null_value_in_the_middle_does_not_become_the_latest() -> None:
    """A suppressed observation is skipped, not read as the newest."""
    frame = _frame(
        [
            (date(2026, 6, 1), 1177971.0),
            (date(2026, 7, 1), float("nan")),
            (date(2026, 8, 1), 1083420.49),
        ]
    )
    stub = _StubClient(frame)
    reading = fetch_reserves("jp", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.observation_date == "2026-08-01"


# ---------------------------------------------------------------------------
# (d) The twelve-month change: measured, or None — never zero.
# ---------------------------------------------------------------------------


def test_the_twelve_month_change_is_the_ratio_of_thirteen_points() -> None:
    """The change is the last point against the one TWELVE steps back.

    The client is given thirteen monthly points so the lag is exactly one year,
    and the expected value is computed here from the two endpoints rather than
    reusing the client's own expression.
    """
    # Thirteen consecutive months ending 2026-08; the first is the base and the
    # last is +10% on it.
    months = [(2025, 8), (2025, 9), (2025, 10), (2025, 11), (2025, 12)]
    months += [(2026, m) for m in range(1, 9)]
    assert len(months) == 13
    rows = [(date(y, m, 1), 1000.0) for (y, m) in months[:-1]]
    rows.append((date(2026, 8, 1), 1100.0))
    stub = _StubClient(_frame(rows))
    reading = fetch_reserves("jp", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.change_12m_pct == pytest.approx((1100.0 - 1000.0) / 1000.0 * 100.0, rel=1e-12)


def test_a_short_series_reports_the_change_as_none_not_zero() -> None:
    """Twelve points cannot yield a twelve-month change; ``None`` is the truth."""
    rows = [(date(2026, m, 1), 1000.0 + m) for m in range(1, 13)]
    stub = _StubClient(_frame(rows))
    reading = fetch_reserves("jp", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.change_12m_pct is None


def test_a_zero_prior_is_reported_as_none_not_an_infinite_percentage() -> None:
    """A zero base is not a basis for a percentage change."""
    rows = (
        [(date(2025, 8, 1), 0.0)]
        + [(date(2025, m, 1), 0.0) for m in range(9, 13)]
        + [(date(2026, m, 1), 0.0) for m in range(1, 9)]
    )
    assert len(rows) == 13
    stub = _StubClient(_frame(rows))
    reading = fetch_reserves("jp", client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.change_12m_pct is None


# ---------------------------------------------------------------------------
# The country map.
# ---------------------------------------------------------------------------


def test_an_unregistered_country_returns_none_rather_than_guessing() -> None:
    """No series → ``None``, never a neighbouring country's series.

    *"Not registered"* and *"the network is down"* are different facts, and only
    one of them is an exception.
    """
    assert fetch_reserves("de", client=_StubClient(_frame([]))) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("code", ["JP", "jp", " jp ", "JPN", "jpn"])
def test_the_country_lookup_is_case_and_whitespace_insensitive(code: str) -> None:
    """Alpha-2 and alpha-3 both resolve, in any case."""
    stub = _StubClient(_frame([(date(2026, 8, 1), 1.0)]))
    reading = fetch_reserves(code, client=stub)  # type: ignore[arg-type]
    assert reading is not None
    assert reading.symbol == "TRESEGJPM052N"


def test_the_three_registered_countries_map_to_the_measured_symbols() -> None:
    """The symbols are the ones measured live on 2026-09-27."""
    assert RESERVE_SERIES["jp"][0] == "TRESEGJPM052N"
    assert RESERVE_SERIES["gb"][0] == "TRESEGGBM052N"
    assert RESERVE_SERIES["cn"][0] == "TRESEGCNM052N"


def test_the_client_passes_the_symbol_to_the_ecosystem_endpoint() -> None:
    """The request names the FRED route and the resolved symbol."""
    stub = _StubClient(_frame([(date(2026, 8, 1), 1.0)]))
    fetch_reserves("gb", client=stub)  # type: ignore[arg-type]
    assert stub.calls[0]["provider"] == "fred"
    assert stub.calls[0]["endpoint"] == "economy.fred_series"
    assert stub.calls[0]["params"] == {"symbol": "TRESEGGBM052N"}


# ---------------------------------------------------------------------------
# (f) The registry entries declare only real schema fields (O-141).
# ---------------------------------------------------------------------------


def test_the_registry_entries_declare_only_real_schema_fields() -> None:
    """The reserve legs must not carry a key ``RegistrySeries`` does not declare.

    This is O-141's guard applied to this increment's entries. ``RegistrySeries``
    is ``extra="forbid"`` and every entry parses as part of ``SeriesRegistry``,
    so ONE undeclared key on ONE entry makes the WHOLE FILE unparseable — D-117
    reddened 33 tests across 7 unrelated modules that way while the new module's
    own tests stayed green, because none of them loads the registry.

    Two assertions, different in kind: the structural one catches ANY undeclared
    key, and the behavioural one catches a declared key whose value a validator
    rejects. The field list is read from the MODEL, not hardcoded, so it cannot
    drift.
    """
    import yaml

    from macro_engine.config import RegistrySeries

    declared = set(RegistrySeries.model_fields)

    registry_path = Path(__file__).resolve().parents[2] / "config" / "series_registry.yaml"
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))

    reserve_entries = {
        name: entry for name, entry in raw["series"].items() if name.startswith("fx_reserves_")
    }
    assert reserve_entries, "the fx_reserves_* entries are missing from the registry"

    for name, entry in reserve_entries.items():
        undeclared = set(entry) - declared
        assert not undeclared, (
            f"{name} carries keys RegistrySeries does not declare: {sorted(undeclared)}. "
            f"extra='forbid' makes this reject the ENTIRE registry file."
        )

    # The behavioural half: the whole file still parses.
    from macro_engine.config import get_registry

    registry = get_registry()
    for name in reserve_entries:
        assert name in registry.series


def test_the_reserve_entries_record_the_source_unit_as_millions() -> None:
    """The registry's ``units`` is the SOURCE's unit, and it must say millions.

    The registry's ``units`` field is documented as the engine's working unit,
    but for these entries the client preserves the source's unit and the model
    converts — so the registry must record what the SERIES publishes, and the
    description carries the conversion. A ``units: usd_billions`` here would
    misdescribe the series by 1000x.
    """
    from macro_engine.config import get_registry

    registry = get_registry()
    for name in ("fx_reserves_japan", "fx_reserves_uk", "fx_reserves_china"):
        assert registry.series[name].units == "millions_of_usd"


# ===========================================================================
# R-6 — `_as_iso_date` must render a BARE date, never a time-bearing string
# ===========================================================================
# The third transcription of the `datetime`-is-a-`date` trap this increment
# fixed (after `openbb_client.to_observation_date` R-4 and
# `commodities_client._parse_date` R-5). Here the failure mode is different: the
# function returns a STRING, and the original guard led with
# `if isinstance(index_value, date): return index_value.isoformat()` — so a
# `pd.Timestamp` (a `date` subclass) took that branch and `.isoformat()` produced
# `'2026-09-18T00:00:00'`. MEASURED, not assumed.
#
# That is precisely the string the function's own docstring says it exists to
# avoid ("a ``str()`` of a Timestamp carries a time and a timezone, which would
# make two dates for the same observation compare unequal") — so the code
# contradicted its own stated intent, which is why it is a defect even though it
# is not reachable through today's `fetch_series` wiring (the normalized `date`
# column holds real `datetime.date` objects; `sort_values`/`tolist` preserve
# them). A latent defect is fixed at the same standard as a live one when the fix
# is cheap and the intent is documented.


def test_as_iso_date_renders_a_bare_date_for_a_plain_date() -> None:
    """Positive control: the common case is already a bare ISO string."""
    assert reserves_client._as_iso_date(date(2026, 9, 18)) == "2026-09-18"


def test_as_iso_date_drops_the_time_from_a_timestamp() -> None:
    """A `pd.Timestamp` must not carry its `T00:00:00` into the published date.

    The pre-fix code returned `'2026-09-18T00:00:00'` here. Two observations for
    the same calendar day rendered through different carriers would then compare
    unequal, which is the inequality the docstring names.
    """
    assert reserves_client._as_iso_date(pd.Timestamp("2026-09-18")) == "2026-09-18"
    assert reserves_client._as_iso_date(pd.Timestamp("2026-09-18 13:45:00")) == "2026-09-18"


def test_as_iso_date_drops_the_time_and_zone_from_an_aware_timestamp() -> None:
    """An aware Timestamp must not leak its offset either."""
    assert (
        reserves_client._as_iso_date(pd.Timestamp("2026-09-18 13:45:00", tz="UTC")) == "2026-09-18"
    )


def test_as_iso_date_drops_the_time_from_a_datetime() -> None:
    """A bare `datetime` is the same trap and must collapse the same way."""
    from datetime import UTC, datetime

    assert reserves_client._as_iso_date(datetime(2026, 9, 18, 13, 45, tzinfo=UTC)) == "2026-09-18"


def test_as_iso_date_accepts_an_iso_string_unchanged() -> None:
    """A string carrier is passed through as-is (the defensive fallback)."""
    assert reserves_client._as_iso_date("2026-09-18") == "2026-09-18"


def test_as_iso_date_never_emits_a_time_component_for_any_carrier() -> None:
    """Invariant sweep: no accepted carrier yields a ``T``-bearing string.

    The property the defect violated is not "handles Timestamp" but "the result
    is a bare ``YYYY-MM-DD``". Asserting the invariant across every carrier
    catches a future fourth carrier added without extending the branches.
    ``numpy.datetime64`` is included because it has neither ``.date()`` nor
    ``.year`` -- it reaches the string fallback, where an incomplete fix would
    have leaked ``'2026-09-18T23:59:59'`` (measured before the fallback was
      completed).
    """
    from datetime import UTC, datetime

    import numpy as np

    carriers: list[object] = [
        date(2026, 9, 18),
        datetime(2026, 9, 18, 23, 59, 59, tzinfo=UTC),
        pd.Timestamp("2026-09-18 23:59:59"),
        pd.Timestamp("2026-09-18 23:59:59", tz="UTC"),
        np.datetime64("2026-09-18T23:59:59"),
        "2026-09-18",
        "2026-09-18T23:59:59",
    ]
    for carrier in carriers:
        rendered = reserves_client._as_iso_date(carrier)
        assert "T" not in rendered, f"{carrier!r} -> {rendered!r} carries a time"
        assert rendered == "2026-09-18", f"{carrier!r} -> {rendered!r}"
