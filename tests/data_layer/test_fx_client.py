"""``data_layer/fx_client.py`` — the FX spot layer (Section 22.3's bridge).

What these tests are for
------------------------
The `fx_spot` schema field has always been declared and never populated. The D-137
disposition called that "a disclosure, not a fetch" and closed it — but the field
being unwired and the *data* being unavailable are two different facts, and only
the first was true. Measured 2026-10-10 the data is reachable, so this is the
**sixth FALSE BLOCK** of the D-043 class the repository has caught.

Replacing "no source" with a real one introduces a specific set of hazards, and
each is asserted here:

(a) **The frame shape is the CLIENT's, not the provider's.** ``fetch_series``
    normalises every route to a tidy 5-column frame (``date``/``value``/
    ``series_id``/``source``/``retrieved_at``) — measured live. A parser written
    against the route's *advertised* OHLC shape returns ``[]`` on real data and
    reports "no data" for data that is present. Tested with the real shape.
(b) **An unregistered pair returns ``None``, not an exception, and NOT a
    derived cross.** "This pair is not in the catalogue" and "the network broke"
    are different facts.
(c) **A fetch that returns no usable rows is a FAILURE, not an empty series.** An
    empty list reads as "no data this run"; the caller must not be able to make
    that mistake.
(d) **Non-positive and non-finite values are dropped, never zeroed.** A zero rate
    divides by zero; a ``nan`` passes every comparison (D-078).
(e) **No forward is ever returned.** The route family is spot-only (measured: no
    ``forward``/``swap``/``basis`` route in the live spec). A spot value under a
    forward's name is the exact defect ``CIPInputs`` guards against.
(f) **The ECB reference rate is EUR-based and refuses EUR itself.**
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pandas as pd
import pytest

from macro_engine.data_layer.fx_client import (
    FX_PAIRS,
    FxReadError,
    fetch_fx_spot,
    parse_ecb_reference_rate,
)


def _tidy_frame(rows: list[tuple[object, float]]) -> pd.DataFrame:
    """The REAL shape ``fetch_series`` returns: tidy, 5 columns, RangeIndex.

    Measured live 2026-10-10 for ``currency.price.historical`` / ``EURUSD``:
    shape ``(29, 5)``, columns ``date``, ``value``, ``series_id``, ``source``,
    ``retrieved_at``. It is explicitly NOT an OHLC-indexed frame, which is why
    the client selects columns by NAME.
    """
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "value": [r[1] for r in rows],
            "series_id": "fx_spot_eurusd",
            "source": "openbb:package",
            "retrieved_at": "2026-10-10T00:00:00+00:00",
        }
    )


class _StubClient:
    """A client that returns a prepared frame, so no network is touched.

    Its ``fetch_series`` mirrors the real signature exactly (keyword-only, with
    the same parameter names) so it satisfies ``fx_client.SeriesClient``
    structurally — no cast, and the test is checked against the same protocol the
    production client satisfies.
    """

    def __init__(self, frame: pd.DataFrame | None = None, *, boom: bool = False) -> None:
        self._frame = frame
        self._boom = boom
        self.closed = False
        self.calls: list[dict[str, object]] = []

    def fetch_series(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        series_label: str,
    ) -> pd.DataFrame:
        from macro_engine.data_layer.openbb_client import OpenBBFetchError

        self.calls.append(
            {
                "provider": provider,
                "endpoint": endpoint,
                "params": params,
                "series_label": series_label,
            }
        )
        if self._boom:
            raise OpenBBFetchError("transport down")
        assert self._frame is not None
        return self._frame

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# (a) the real tidy shape parses; the advertised OHLC shape is NOT what arrives
# ---------------------------------------------------------------------------


def test_the_tidy_frame_shape_parses_into_a_sorted_series() -> None:
    """The client's normalised shape is the contract, and it parses."""
    frame = _tidy_frame(
        [
            ("2026-10-09", 1.1206),
            ("2026-10-07", 1.1254),
            ("2026-10-08", 1.1201),
        ]
    )
    reading = fetch_fx_spot("EURUSD", client=_StubClient(frame))
    assert reading is not None
    assert reading.observation_count == 3
    # Sorted by date, so `latest` is genuinely the latest regardless of row order.
    dates = [p.observation_date for p in reading.pair.series]
    assert dates == sorted(dates)
    assert reading.pair.latest is not None
    assert reading.pair.latest.value == pytest.approx(1.1206)


def test_an_ohlc_shaped_frame_is_not_accepted() -> None:
    """A parser written for the ADVERTISED shape must not silently pass.

    The route advertises OHLC; the client returns tidy. This pins that the
    client's parser keys on the client's columns: handing it an OHLC frame
    yields no points and therefore raises, rather than inventing a series from
    the wrong column.
    """
    ohlc = pd.DataFrame(
        {"open": [1.1], "high": [1.2], "low": [1.0], "close": [1.15], "volume": [0.0]},
        index=pd.to_datetime(["2026-10-09"]),
    )
    with pytest.raises(FxReadError, match="no usable observations"):
        fetch_fx_spot("EURUSD", client=_StubClient(ohlc))


# ---------------------------------------------------------------------------
# (b) an unregistered pair is None, not a derived cross
# ---------------------------------------------------------------------------


def test_an_unregistered_pair_returns_none() -> None:
    assert fetch_fx_spot("XXXYYY", client=_StubClient()) is None


def test_the_pair_is_parsed_case_insensitively_and_with_separators() -> None:
    for symbol in ("eurusd", "EUR/USD", "eur-usd"):
        reading = fetch_fx_spot(symbol, client=_StubClient(_tidy_frame([("2026-10-09", 1.12)])))
        assert reading is not None
        assert reading.pair.symbol == "EURUSD"
        assert reading.pair.base == "EUR"
        assert reading.pair.quote == "USD"


def test_the_quote_convention_is_stated_on_the_pair() -> None:
    """A rate is unintelligible without its direction — so it travels with it."""
    reading = fetch_fx_spot("USDJPY", client=_StubClient(_tidy_frame([("2026-10-09", 158.0)])))
    assert reading is not None
    assert reading.pair.convention == "JPY per 1 USD"


def test_every_registered_pair_has_two_distinct_alpha3_codes() -> None:
    for symbol, (base, quote) in FX_PAIRS.items():
        assert base != quote, symbol
        assert len(base) == 3 and base.isalpha() and base.isupper(), symbol
        assert len(quote) == 3 and quote.isalpha() and quote.isupper(), symbol
        assert symbol == f"{base}{quote}", symbol


# ---------------------------------------------------------------------------
# (c) an empty usable series is a FAILURE, not an empty list
# ---------------------------------------------------------------------------


def test_a_frame_with_no_usable_rows_raises() -> None:
    with pytest.raises(FxReadError, match="no usable observations"):
        fetch_fx_spot("EURUSD", client=_StubClient(_tidy_frame([])))


def test_a_transport_failure_raises_fx_read_error() -> None:
    with pytest.raises(FxReadError, match="could not be read"):
        fetch_fx_spot("EURUSD", client=_StubClient(boom=True))


# ---------------------------------------------------------------------------
# (d) non-positive / non-finite values are DROPPED, not zeroed
# ---------------------------------------------------------------------------


def test_zero_negative_and_nan_rates_are_dropped_not_zeroed() -> None:
    """A 0.0 rate divides by zero; a nan passes every comparison (D-078)."""
    frame = _tidy_frame(
        [
            ("2026-10-01", 1.10),
            ("2026-10-02", 0.0),
            ("2026-10-03", -1.20),
            ("2026-10-04", float("nan")),
            ("2026-10-05", 1.12),
        ]
    )
    reading = fetch_fx_spot("EURUSD", client=_StubClient(frame))
    assert reading is not None
    assert reading.observation_count == 2
    assert [p.value for p in reading.pair.series] == [1.10, 1.12]
    assert all(p.value > 0 for p in reading.pair.series)


# ---------------------------------------------------------------------------
# (e) the module returns spot only, and never opens its own HTTP connection
# ---------------------------------------------------------------------------


def test_the_client_is_never_asked_for_a_forward_route() -> None:
    """The endpoint this module calls must be a SPOT route.

    Asserted on the call, because the hazard is a future edit pointing this at a
    route whose name sounds right — the D-043 class this whole module exists to
    avoid repeating.
    """
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12)]))
    fetch_fx_spot("EURUSD", client=stub)
    assert len(stub.calls) == 1
    endpoint = str(stub.calls[0]["endpoint"])
    assert endpoint == "currency.price.historical"
    for forbidden in ("forward", "swap", "basis"):
        assert forbidden not in endpoint


def test_the_module_does_not_open_its_own_http_connection() -> None:
    """It must go through ``OpenBBClient`` (base URL, retries, pinned UA).

    Asserted on the AST rather than the text: a ``httpx.get`` hidden behind a
    helper would satisfy a text scan. (The project's own lesson — assert the
    mechanism, not its textual trace.)
    """
    import ast
    import inspect
    import pathlib

    import macro_engine.data_layer.fx_client as mod

    tree = ast.parse(pathlib.Path(inspect.getfile(mod)).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "httpx" not in imported
    assert "requests" not in imported


# ---------------------------------------------------------------------------
# (f) the ECB reference rate is EUR-based and refuses EUR itself
# ---------------------------------------------------------------------------


def test_the_ecb_reference_rate_is_eur_based() -> None:
    """ECB publishes EUR-based rates, so `USD: 1.12` is USD per EUR."""
    point = parse_ecb_reference_rate({"USD": 1.1206, "JPY": 177.34}, currency="USD")
    assert point is not None
    assert point.value == pytest.approx(1.1206)
    assert point.series_id == "fx_spot_eurusd"


def test_the_ecb_reference_rate_refuses_eur_and_absent_currencies() -> None:
    payload = {"USD": 1.12, "JPY": 177.3}
    assert parse_ecb_reference_rate(payload, currency="EUR") is None
    assert parse_ecb_reference_rate(payload, currency="GBP") is None


def test_the_ecb_reference_rate_rejects_a_non_positive_rate() -> None:
    assert parse_ecb_reference_rate({"USD": 0.0}, currency="USD") is None
    assert parse_ecb_reference_rate({"USD": -1.0}, currency="USD") is None


# ---------------------------------------------------------------------------
# the source string distinguishes the two routes (a vendor close vs a fixing)
# ---------------------------------------------------------------------------


def test_the_reading_names_its_source() -> None:
    reading = fetch_fx_spot("EURUSD", client=_StubClient(_tidy_frame([("2026-10-09", 1.12)])))
    assert reading is not None
    assert "currency.price.historical" in reading.source
    assert reading.retrieved_at is not None
    assert isinstance(reading.retrieved_at.year, int)


def test_the_default_start_date_is_about_five_years_back() -> None:
    """Long enough for a 12m change with margin, short enough to return fast."""
    stub = _StubClient(_tidy_frame([("2026-10-09", 1.12)]))
    fetch_fx_spot("EURUSD", client=stub)
    params = cast("dict[str, Any]", stub.calls[0]["params"])
    assert date.fromisoformat(str(params["start_date"])) == date(2021, 1, 1)


# ---------------------------------------------------------------------------
# (g) the WIRING — `build_snapshot` actually fills `snapshot.fx_spot`
# ---------------------------------------------------------------------------
#
# The module above can be perfect and the field still empty: the defect being
# disposed of here was never "no client", it was "no CALLER". `build_snapshot`
# sets one attribute per registry entry, and `fx_spot` is a dict of series, so
# unless a step is added that assigns the mapping, every test above passes and
# `snapshot.fx_spot` stays `{}` in every real build. These tests exist for that
# half — the same lesson the unwired-mapping test recorded ("the population, not
# just the rendering").


def _builder_stub(pairs: dict[str, float]) -> object:
    """A client stub returning one row per requested pair, keyed by symbol.

    ``build_snapshot`` fetches FX pairs through ``fetch_fx_spot``, which calls
    ``client.fetch_series(..., params={'symbol': <PAIR>})``. This maps that symbol
    back to a prepared rate so each pair yields a distinct, checkable value.
    """

    class _PerSymbol:
        """Satisfies ``fx_client.SeriesClient`` structurally (same signature)."""

        def __init__(self) -> None:
            self.symbols: list[str] = []

        def fetch_series(
            self,
            *,
            provider: str,
            endpoint: str,
            params: dict[str, Any],
            series_label: str,
        ) -> pd.DataFrame:
            del provider, endpoint, series_label  # unused; the symbol is the key
            symbol = str(params["symbol"])
            self.symbols.append(symbol)
            rate = pairs.get(symbol)
            if rate is None:
                from macro_engine.data_layer.openbb_client import OpenBBFetchError

                raise OpenBBFetchError(f"no prepared rate for {symbol}")
            return _tidy_frame([("2026-10-09", rate)])

        def close(self) -> None:  # pragma: no cover - builder-owned client never
            pass

    return _PerSymbol()


def test_build_snapshot_populates_the_fx_spot_mapping() -> None:
    """The END-TO-END assertion: the field is filled, not merely fetchable."""
    from typing import cast

    from macro_engine.config import get_settings
    from macro_engine.data_layer.openbb_client import OpenBBClient
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    enabled = list(get_settings().fx_pairs.enabled)
    assert enabled, "no fx pairs enabled in config; the wiring test would be vacuous"
    prepared = {symbol: 1.0 + 0.01 * i for i, symbol in enumerate(enabled)}

    snapshot, report = build_snapshot(
        country="us",
        fields=["gdp_real"],
        client=cast("OpenBBClient", _builder_stub(prepared)),
        release_index=ReleaseDateIndex(),
    )

    assert snapshot.fx_spot, "fx_spot is still empty — the wiring step did not run"
    for symbol in enabled:
        assert symbol in snapshot.fx_spot, symbol
        assert snapshot.fx_spot[symbol][0].value == pytest.approx(prepared[symbol])
    # The disclosure must not contradict the fetch: a build that fetched the
    # mapping must not also be told the field is structurally unreachable.
    assert "fx_spot" not in report.declared_not_wired
    for symbol in enabled:
        assert report.observation_counts[f"fx_spot.{symbol}"] == 1


def test_an_unregistered_configured_pair_is_reported_not_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pair named in config but absent from the catalogue is a REPORTED skip.

    It must not be derived as a cross, and it must not abort the build — the
    other pairs still land. The catalogue is the authority on the quote
    convention, and inventing a leg from two unrelated ones is a third
    convention.
    """
    from typing import cast

    from macro_engine.config import FxPairsSettings, get_settings
    from macro_engine.data_layer.openbb_client import OpenBBClient
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "fx_pairs",
        FxPairsSettings.model_construct(
            calibration_status=settings.fx_pairs.calibration_status,
            note=settings.fx_pairs.note,
            enabled=["EURUSD", "ZZZYYY"],
        ),
    )

    snapshot, report = build_snapshot(
        country="us",
        fields=["gdp_real"],
        client=cast("OpenBBClient", _builder_stub({"EURUSD": 1.12})),
        release_index=ReleaseDateIndex(),
    )

    assert "EURUSD" in snapshot.fx_spot  # the good pair still landed
    assert "ZZZYYY" not in snapshot.fx_spot
    assert any(k == "fx_spot.ZZZYYY" for k in report.failed), report.failed
    assert "catalogue" in report.failed["fx_spot.ZZZYYY"]


def test_a_pair_whose_fetch_fails_does_not_abort_the_others() -> None:
    """One pair failing costs that pair, not the mapping — and not the snapshot.

    This mirrors the per-scalar contract: graceful degradation with an audit
    trail, never silent degradation. The failure is named in ``report.failed``
    so the missing key is distinguishable from "that pair was never configured".
    """
    from typing import cast

    from macro_engine.config import get_settings
    from macro_engine.data_layer.openbb_client import OpenBBClient
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    enabled = list(get_settings().fx_pairs.enabled)
    assert len(enabled) >= 2, "need at least two pairs to prove one failing spares the rest"
    # Prepare every pair EXCEPT the first, which the stub will refuse.
    broken = enabled[0]
    prepared = {symbol: 1.05 + 0.01 * i for i, symbol in enumerate(enabled[1:], start=1)}

    snapshot, report = build_snapshot(
        country="us",
        fields=["gdp_real"],
        client=cast("OpenBBClient", _builder_stub(prepared)),
        release_index=ReleaseDateIndex(),
    )

    assert broken not in snapshot.fx_spot
    assert snapshot.fx_spot, "the surviving pairs must still be present"
    assert f"fx_spot.{broken}" in report.failed


def test_the_fx_spot_mapping_survives_the_persistence_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A fetched ``fx_spot`` must come back out of the audit trail.

    The project has hit "declared, fetched, and then silently discarded on load"
    once already (curves: written correctly, rebuilt by a read path that handled
    only scalars). ``fx_spot`` is covered by the generic ``MAPPING_SERIES_FIELDS``
    loop, so this asserts that coverage rather than assuming it — a keyed mapping
    that does not round-trip makes every historical FX comparison read a
    different picture than the thesis was built on.
    """
    import pandas as pd

    from macro_engine.data_layer import persistence

    monkeypatch.setattr(persistence, "_raw_root", lambda _country: tmp_path)
    monkeypatch.setattr(
        persistence,
        "get_settings",
        lambda: type(
            "S",
            (),
            {"data": type("D", (), {"persist_parquet": True, "raw_store_path": tmp_path})()},
        )(),
    )

    from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint
    from macro_engine.models.contracts import utc_now

    snapshot = MacroDataSnapshot(country="us", as_of=utc_now())
    snapshot.fx_spot = {
        "EURUSD": [
            ObservationPoint(
                observation_date=date(2026, 10, 9),
                value=1.1206,
                series_id="fx_spot_eurusd",
                source="openbb:currency.price.historical",
            )
        ],
        "GBPUSD": [
            ObservationPoint(
                observation_date=date(2026, 10, 9),
                value=1.3233,
                series_id="fx_spot_gbpusd",
                source="openbb:currency.price.historical",
            )
        ],
    }

    path = persistence.write_snapshot(snapshot)
    assert path is not None and path.exists()
    frame = persistence.long_frame_from_snapshot(snapshot)
    assert not frame.empty
    assert set(frame.loc[frame["field"].str.startswith("fx_spot."), "field"]) == {
        "fx_spot.EURUSD",
        "fx_spot.GBPUSD",
    }

    restored = persistence.load_snapshot(country="us")
    assert set(restored.fx_spot) == {"EURUSD", "GBPUSD"}
    assert restored.fx_spot["EURUSD"][0].value == pytest.approx(1.1206)
    assert restored.fx_spot["GBPUSD"][-1].value == pytest.approx(1.3233)
    # Ensure the frame really was written to disk (not merely built in memory).
    assert any(tmp_path.rglob("*.parquet"))
    _ = pd  # imported for the assertion above; keeps the round-trip honest
