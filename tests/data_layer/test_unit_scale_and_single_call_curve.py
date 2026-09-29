"""D-086: the unit-scale declaration, and the single-call curve path.

Two independent defects this file exists to keep fixed, both of the
plausible-but-wrong class Section 21.0 forbids:

**1. The scale trap.** The SAME local OpenBB service serves the same rate in two
different scales depending on which route is called. Measured live 2026-09-21:

    economy.fred_series?symbol=SOFR        -> 3.85    (percent)
    fixedincome/rate/sofr                  -> 0.0385  (decimal)

Both are plausible-looking rates, so an endpoint swap that forgot the conversion
would publish a 100x error that no range check catches. Worse, the trap is
INCONSISTENT: `fixedincome/rate/iorb` returns 3.9 while `fred_series IORB`
returns 3.9 — the same value. So a swap swapped by eye looks CORRECT on one
field and is silently wrong on the next.

**2. The single-call curve.** `fixedincome/government/yield_curve` returns all
eleven tenors in one response, keyed by the provider's own maturity label
(`month_1`, `year_10`) rather than the registry's (`1mo`, `10yr`). Eleven calls
become one, but only if the join between the two naming schemes is declared
rather than inferred — a tenor matched by row position would mis-assign an
entire curve from one reordered response.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest

from macro_engine.config import RegistrySeries
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError
from macro_engine.data_layer.snapshot_builder import fetch_curve, fetch_field

_TENORS = {
    "1mo": "DGS1MO",
    "3mo": "DGS3MO",
    "1yr": "DGS1",
    "10yr": "DGS10",
}
_LABELS = {
    "1mo": "month_1",
    "3mo": "month_3",
    "1yr": "year_1",
    "10yr": "year_10",
}


# --------------------------------------------------------------------------
# 1. The scale declaration itself.
# --------------------------------------------------------------------------


def test_decimal_to_percent_derives_the_factor() -> None:
    """The factor is DERIVED from the declared pair, never written by hand."""
    entry = RegistrySeries(
        provider="federal_reserve",
        symbol="X",
        units="percent",
        source_units="decimal",
    )
    assert entry.unit_scale_to_units == 100.0


def test_absent_source_units_means_no_conversion() -> None:
    """`None` is 'the source already matches', which is the common case."""
    entry = RegistrySeries(provider="fred", symbol="CPIAUCSL", units="percent")
    assert entry.unit_scale_to_units is None


def test_identical_pair_is_a_factor_of_one() -> None:
    """Declaring the same unit on both sides is legal and is the identity."""
    entry = RegistrySeries(
        provider="fred",
        symbol="X",
        units="percent",
        source_units="percent",
    )
    assert entry.unit_scale_to_units == 1.0


def test_source_units_without_units_is_rejected() -> None:
    """'Convert to what?' has no answer, so the half-declaration is refused.

    A default here would be a guess about scale, which is the one thing this
    field exists to make unguessable.
    """
    with pytest.raises(ValueError, match="source_units without units"):
        RegistrySeries(provider="fred", symbol="X", source_units="decimal")


def test_unsupported_unit_pair_is_rejected() -> None:
    """An unnamed conversion must not pass through silently.

    Basis points <-> percent is a real conversion this system could want, but it
    is NOT `decimal`/`percent`, so it must be added by name rather than accepted
    as a no-op.
    """
    with pytest.raises(ValueError, match="unsupported conversion"):
        RegistrySeries(
            provider="fred",
            symbol="X",
            units="percent",
            source_units="basis_points",
        )


def test_the_curve_entry_declares_its_scale() -> None:
    """The live registry must declare the curve's decimal source, measured.

    This is the assertion that would have failed if D-086 had swapped the
    endpoint without the conversion: the command returns 0.0494 where the
    registry's `units` and its stored values say 4.94.
    """
    from macro_engine.config import get_registry

    entry = get_registry().series["treasury_curve"]
    assert entry.source_units == "decimal"
    assert entry.unit_scale_to_units == 100.0


def test_fetch_field_applies_the_declared_scale() -> None:
    """The conversion is applied on the SCALAR path."""
    frame = pd.DataFrame(
        {
            "date": [date(2026, 9, 17)],
            "value": [0.0385],
            "series_id": ["sofr"],
            "source": ["stub"],
            "retrieved_at": [datetime(2026, 9, 21, 12, 0, tzinfo=UTC)],
        }
    )
    client = _StubClient(single=frame)
    entry = RegistrySeries.model_construct(
        provider="federal_reserve",
        endpoint="fixedincome.rate.sofr",
        symbol="SOFR",
        units="percent",
        source_units="decimal",
        unit_scale_to_units=100.0,
    )
    points = fetch_field(client, "sofr", entry)
    assert points[0].value == pytest.approx(3.85)


def test_fetch_field_without_a_scale_leaves_the_value_alone() -> None:
    """The conversion is opt-in: an undeclared series must not be scaled."""
    frame = pd.DataFrame(
        {
            "date": [date(2026, 9, 17)],
            "value": [3.85],
            "series_id": ["sofr"],
            "source": ["stub"],
            "retrieved_at": [datetime(2026, 9, 21, 12, 0, tzinfo=UTC)],
        }
    )
    client = _StubClient(single=frame)
    entry = RegistrySeries.model_construct(
        provider="fred",
        endpoint="economy.fred_series",
        symbol="SOFR",
        units="percent",
        unit_scale_to_units=None,
    )
    points = fetch_field(client, "sofr", entry)
    assert points[0].value == pytest.approx(3.85)


# --------------------------------------------------------------------------
# 2. The single-call curve path.
# --------------------------------------------------------------------------


class _StubClient(OpenBBClient):
    """Serves one wide frame, or a per-symbol frame, so both shapes are testable.

    A genuine subclass (not a duck-typed stand-in) so the call sites type-check
    against `fetch_curve`'s real `OpenBBClient` parameter. The constructor is
    bypassed deliberately: `OpenBBClient.__init__` opens an HTTP client.
    """

    def __init__(self, *, single: pd.DataFrame | None = None) -> None:
        self._single = single
        self.calls: list[dict[str, Any]] = []

    def fetch_series(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        series_label: str,
    ) -> pd.DataFrame:
        self.calls.append({"provider": provider, "endpoint": endpoint, "params": params})
        assert self._single is not None, "this stub serves only the single-call shape"
        return self._single


def _wide_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    """A single-call curve response: one row per maturity label."""
    return pd.DataFrame(
        {
            "date": [date(2026, 9, 17)] * len(rows),
            "value": [r[1] for r in rows],
            "maturity": [r[0] for r in rows],
            "series_id": ["treasury_curve"] * len(rows),
            "source": ["stub"] * len(rows),
            "retrieved_at": [datetime(2026, 9, 21, 12, 0, tzinfo=UTC)] * len(rows),
        }
    )


def _single_call_entry() -> RegistrySeries:
    """The real registry shape for `treasury_curve`, including its window contract.

    `window_filter_supported=False` is stated rather than left to default,
    because this route measurably ignores `start_date` (see the registry
    comment) and the tests below assert the parameter is NOT sent.
    """
    return RegistrySeries.model_construct(
        provider="federal_reserve",
        endpoint="fixedincome.government.yield_curve",
        snapshot_field="yield_curve",
        units="percent",
        source_units="decimal",
        unit_scale_to_units=100.0,
        window_filter_supported=False,
        tenors=dict(_TENORS),
        tenor_labels=dict(_LABELS),
    )


def test_the_curve_entry_declares_its_window_contract() -> None:
    """The registry must not claim a bounded window on a latest-only route.

    Measured live 2026-09-21: `fixedincome/government/yield_curve` returned the
    same 11 rows dated 2026-09-17 with `start_date=2026-09-15` as with no
    `start_date` at all. A registry that omitted `window_filter_supported`
    would default to True and have the fetcher send a parameter the provider
    discards — claiming a window that does not exist.
    """
    from macro_engine.config import get_registry

    entry = get_registry().series["treasury_curve"]
    assert entry.window_filter_supported is False, (
        "this route ignores start_date; declaring True would make the fetcher "
        "send a window parameter the provider silently drops"
    )


def test_an_ignored_window_parameter_is_not_sent() -> None:
    """A declared-unsupported window must actually be omitted from the request.

    This is the consuming half of `window_filter_supported`. Declaring the field
    without acting on it would be the D-037 defect class — a flag that is
    declared and documented but never consumed, so it changes nothing.
    """
    client = _StubClient(single=_wide_frame([(label, 1.0) for label in _LABELS.values()]))
    fetch_curve(client, "treasury_curve", _single_call_entry(), start="2026-01-01")
    assert len(client.calls) == 1
    assert "start_date" not in client.calls[0]["params"], (
        "the route ignores start_date, so the fetcher must not send it"
    )


def test_a_supported_window_parameter_is_still_sent() -> None:
    """The negative control: on a route that DOES honour the window, send it.

    Without this, a fetcher that dropped `start_date` unconditionally would pass
    the test above while silently over-fetching every other registry entry.
    """
    entry = _single_call_entry()
    entry.window_filter_supported = True
    client = _StubClient(single=_wide_frame([(label, 1.0) for label in _LABELS.values()]))
    fetch_curve(client, "treasury_curve", entry, start="2026-01-01")
    assert client.calls[0]["params"]["start_date"] == "2026-01-01"


def test_single_call_curve_reads_one_request_for_all_tenors() -> None:
    """Eleven calls become one — the whole point of the change."""
    client = _StubClient(
        single=_wide_frame(
            [("month_1", 0.0397), ("month_3", 0.0412), ("year_1", 0.044), ("year_10", 0.0494)]
        )
    )
    curve = fetch_curve(client, "treasury_curve", _single_call_entry())
    assert len(client.calls) == 1, "the curve must be fetched in ONE call"
    assert curve.tenors["10yr"] == pytest.approx(4.94)


def test_single_call_curve_applies_the_declared_scale() -> None:
    """The 100x conversion is applied on the CURVE path too, not only scalar.

    A conversion wired into one path and not the other is the defect this
    asserts against: the curve would publish 0.0494 where every consumer
    expects 4.94.
    """
    # `_LABELS.items()` is (tenor_key, provider_label); the frame needs
    # (provider_label, decimal_rate), so the lookup goes the other way.
    client = _StubClient(single=_wide_frame([(label, 0.05) for label in _LABELS.values()]))
    curve = fetch_curve(client, "treasury_curve", _single_call_entry())
    assert curve.tenors["1mo"] == pytest.approx(5.0)
    assert curve.tenors["10yr"] == pytest.approx(5.0)


def test_single_call_curve_maps_every_declared_tenor() -> None:
    """The registry names and the provider labels are joined, not guessed."""
    rows = [(label, 1.0) for label in _LABELS.values()]
    client = _StubClient(single=_wide_frame(rows))
    curve = fetch_curve(client, "treasury_curve", _single_call_entry())
    assert set(curve.tenors) == set(_TENORS), "a declared tenor was dropped"


def test_tenors_are_attributed_by_label_even_when_the_rows_are_shuffled() -> None:
    """Attribution must be keyed by the provider's LABEL, never by row position.

    This is the test the refusal message promises exists ("Refusing to attribute
    rows to tenors by position, which would silently mis-assign an entire
    curve"). Every other curve test happens to serve its rows in the same order
    as the registry, so a positional implementation passes them all — verified
    by mutation: the positional mutant survived the suite until this test was
    added.

    Here the payload is deliberately in REVERSE registry order and each tenor
    carries a distinct rate, so a positional read assigns 1yr's rate to 1mo and
    every assertion below fails.
    """
    ordered = list(_LABELS.items())  # (tenor_key, provider_label), registry order
    rates = {tenor: float(i + 1) for i, (tenor, _) in enumerate(ordered)}
    rows = [(label, rates[tenor] * 0.01) for tenor, label in reversed(ordered)]

    client = _StubClient(single=_wide_frame(rows))
    curve = fetch_curve(client, "treasury_curve", _single_call_entry())

    for tenor, _ in ordered:
        # The scale (decimal -> percent) is applied on top, so the expected
        # published value is the rate x 100 = the rate index itself.
        assert curve.tenors[tenor] == pytest.approx(rates[tenor]), (
            f"tenor {tenor} received another tenor's rate — attribution is positional"
        )

    # And the identity of the extremes is pinned so a swap is unmistakable.
    assert curve.tenors["1mo"] == pytest.approx(1.0)
    assert curve.tenors["10yr"] == pytest.approx(4.0)


def test_missing_provider_label_raises_rather_than_interpolating() -> None:
    """A tenor absent from the response is an error, never a filled-in value.

    The existing contract already refuses to interpolate a missing tenor; this
    asserts that property survives the single-call path, where the absence is
    expressed as a missing LABEL rather than an empty frame.
    """
    rows = [(label, 1.0) for label in _LABELS.values() if label != "year_10"]
    client = _StubClient(single=_wide_frame(rows))
    with pytest.raises(OpenBBFetchError, match="no row in the response"):
        fetch_curve(client, "treasury_curve", _single_call_entry())


def test_incomplete_tenor_labels_are_rejected_before_any_request() -> None:
    """A partial label map must fail loudly, not silently drop tenors.

    Without this the omitted tenor would surface later as 'no row in the
    response', blaming the provider for the registry's own gap.
    """
    entry = _single_call_entry()
    partial = dict(_LABELS)
    del partial["10yr"]
    entry.tenor_labels = partial
    client = _StubClient(single=_wide_frame([(label, 1.0) for label in _LABELS.values()]))
    with pytest.raises(OpenBBFetchError, match="omits"):
        fetch_curve(client, "treasury_curve", entry)


def test_single_call_without_a_maturity_column_is_refused() -> None:
    """Row-order attribution is refused rather than risked.

    If the label column ever disappears, attributing rows to tenors by position
    would mis-assign the whole curve from one reordering — a silent
    wrong-number failure, which is the class this module exists to refuse.
    """
    frame = _wide_frame([(label, 1.0) for label in _LABELS.values()]).drop(columns=["maturity"])
    client = _StubClient(single=frame)
    with pytest.raises(OpenBBFetchError, match="no 'maturity' column"):
        fetch_curve(client, "treasury_curve", _single_call_entry())


def test_forward_dated_tenor_still_refused_on_the_single_call_path() -> None:
    """O-7 discipline survives the rewrite: a projection is not a realised yield."""
    future = date(2099, 1, 1)
    frame = pd.DataFrame(
        {
            "date": [future] * len(_LABELS),
            "value": [4.0] * len(_LABELS),
            "maturity": list(_LABELS.values()),
            "series_id": ["treasury_curve"] * len(_LABELS),
            "source": ["stub"] * len(_LABELS),
            "retrieved_at": [datetime(2026, 9, 21, 12, 0, tzinfo=UTC)] * len(_LABELS),
        }
    )
    client = _StubClient(single=frame)
    with pytest.raises(OpenBBFetchError, match="forward-dated"):
        fetch_curve(
            client,
            "treasury_curve",
            _single_call_entry(),
            as_of=datetime(2026, 9, 21, tzinfo=UTC),
        )


def test_a_label_column_is_never_picked_as_the_value_column() -> None:
    """The last-resort picker must not return a column that identifies the row.

    Measured reachable before this pin: on a two-column frame `['date',
    'maturity']`, `_pick_value_column` returned `'maturity'` — so `_normalize`
    would rename the provider's label column to `value` and cast maturity NAMES
    to numbers. That raises rather than publishing a wrong number, but the error
    points at the data instead of at the picker.
    """
    assert OpenBBClient._pick_value_column(["date", "maturity"], exclude={"date"}) is None
    assert OpenBBClient._pick_value_column(["date", "maturity_years"], exclude={"date"}) is None
    # Positive control: the live curve shape still resolves, via `rate`.
    assert (
        OpenBBClient._pick_value_column(
            ["date", "maturity", "rate", "maturity_years"], exclude={"date"}
        )
        == "rate"
    )
    # And a genuinely nameless single-remaining value column is still usable.
    assert OpenBBClient._pick_value_column(["date", "obs"], exclude={"date"}) == "obs"


# --------------------------------------------------------------------------
# 5. R-4 — `to_observation_date` must return a real `date`, never a leak.
# --------------------------------------------------------------------------
# `docs/CODE_REVIEW_PHASE0-4.md` item 3.10 named this as the classic
# `datetime`-is-a-`date` trap, and it was still live: the guard tested `date`
# FIRST, so a `datetime` or `pd.Timestamp` (both `date` subclasses) matched that
# branch and leaked through unchanged, violating the `-> date` annotation.
# MEASURED before the fix:
#
#     to_observation_date(datetime(2026, 9, 29, 13, 45)) -> datetime(...)
#     to_observation_date(pd.Timestamp("2026-09-29"))    -> Timestamp(...)
#
# `snapshot_builder._points_from_frame` gets this right by testing
# `pd.Timestamp` BEFORE `date`; these tests pin the same ordering here, and a
# test that only ever passed a plain `date` would have missed the defect
# entirely — which is why every case below asserts `type(...) is date`, not
# merely `isinstance`.


def test_to_observation_date_collapses_a_datetime_to_a_date() -> None:
    """A `datetime` is a `date` subclass; it must be collapsed, not passed on.

    This is the exact input the old guard let through. `type(out) is date` (not
    `isinstance`) is the assertion that matters: a `datetime` would satisfy
    `isinstance(x, date)` and hide the leak.
    """
    from macro_engine.data_layer.openbb_client import to_observation_date

    out = to_observation_date(datetime(2026, 9, 29, 13, 45, tzinfo=UTC))
    assert type(out) is date
    assert out == date(2026, 9, 29)


def test_to_observation_date_collapses_a_pandas_timestamp() -> None:
    """A `pd.Timestamp` is the shape `_normalize` actually produces downstream."""
    from macro_engine.data_layer.openbb_client import to_observation_date

    out = to_observation_date(pd.Timestamp("2026-09-29 13:45:00"))
    assert type(out) is date
    assert out == date(2026, 9, 29)


def test_to_observation_date_passes_a_plain_date_through_unchanged() -> None:
    """Positive control: the common case is untouched and is a real `date`."""
    from macro_engine.data_layer.openbb_client import to_observation_date

    original = date(2026, 9, 29)
    out = to_observation_date(original)
    assert type(out) is date
    assert out is original


def test_to_observation_date_parses_a_string_and_a_numpy_datetime() -> None:
    """The last-resort branch still handles anything else `pd.Timestamp` accepts.

    A string and a ``numpy.datetime64`` are the two shapes a provider JSON or a
    parquet round-trip can deliver; both must resolve to a genuine `date`, so
    the fallback cannot be a place a non-date slips through.
    """
    import numpy as np

    from macro_engine.data_layer.openbb_client import to_observation_date

    for raw in ("2026-09-29", np.datetime64("2026-09-29T13:45:00")):
        out = to_observation_date(raw)
        assert type(out) is date, f"{raw!r} leaked {type(out).__name__}"
        assert out == date(2026, 9, 29)


def test_to_observation_date_never_returns_a_time_bearing_value() -> None:
    """Invariant sweep: EVERY accepted shape yields a time-of-day-free `date`.

    The property the two live defects violated is not "handles datetime" or
    "handles Timestamp" but "the return carries no clock time". Asserting the
    invariant across all shapes at once is what catches a future third shape
    added without extending the explicit branches.
    """
    import numpy as np

    from macro_engine.data_layer.openbb_client import to_observation_date

    shapes: list[object] = [
        datetime(2026, 9, 29, 23, 59, 59, tzinfo=UTC),
        pd.Timestamp("2026-09-29 23:59:59"),
        np.datetime64("2026-09-29T23:59:59"),
        date(2026, 9, 29),
        "2026-09-29T23:59:59",
    ]
    for raw in shapes:
        out = to_observation_date(raw)
        assert type(out) is date, f"{raw!r} -> {type(out).__name__} (leak)"
        # A `date` has no `.hour`; a leaked `datetime` would. Belt and braces.
        assert not hasattr(out, "hour"), f"{raw!r} -> carries a clock time"
        assert out == date(2026, 9, 29)
