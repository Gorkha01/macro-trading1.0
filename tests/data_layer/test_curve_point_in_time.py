"""RED->GREEN: the curve fetch path applies no point-in-time discipline.

`fetch_curve` reads `frame.iloc[-1]` for every tenor. The scalar path routes
through `models.as_of.observation_as_of`, and O-7's resolution claims the
discipline is "shared by every series consumer". A curve tenor that publishes
forward-dated points — which `GDPPOT` does for the scalar path, 41 points a
decade out — would be silently adopted as a *realised* yield.

No tenor is forward-dated on the live deployment today, so the defect is latent.
A latent defect of this class is exactly what D-074 forbade leaving unrecorded:
`+inf` was caught "only when the series carried a plausible_range, and 2 of 45
carry none" — the *shape* was known and the instance was not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from macro_engine.config import RegistrySeries
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError
from macro_engine.data_layer.snapshot_builder import fetch_curve

#: The point-in-time cutoff these fixtures are written against.
#:
#: **The four tests below used to leave `as_of` unset, which made the cutoff the
#: WALL CLOCK while the fixture dates were hardcoded to 2026-09-20.** That is a
#: time bomb, not a test: `test_the_curve_reads_the_latest_realised_row_not_the_
#: last_row` plants its "projection" at `today + 5 days`, and on 2026-09-25 that
#: row became TODAY — no longer in the future, so the filter correctly kept it and
#: the test failed against untouched code (measured: it fails on a clean tree with
#: every edit of the increment stashed). The other two fixture sets carry the same
#: bomb at `+10` and `+100` days, so they would have detonated on 2026-09-30 and
#: 2026-12-29.
#:
#: Passing `as_of` explicitly makes the cutoff a property of the FIXTURE rather
#: than of the day the suite runs, which is what these tests always meant: their
#: whole subject is the relationship between a date and a cutoff. The production
#: default is untouched — `fetch_curve` still falls back to `utc_now()` when the
#: caller supplies nothing, which is the behaviour the live path depends on.
_FIXTURE_AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class _StubClient(OpenBBClient):
    """Serves a fixed frame per symbol, so a forward-dated point can be planted.

    A genuine subclass rather than a duck-typed stand-in, so the call sites in
    this file pass `mypy --strict` against `fetch_curve`'s real `OpenBBClient`
    parameter — a stub that only *looks* like the client would type-check as an
    unrelated class and the signature being tested would go unverified. The
    constructor is bypassed deliberately: `OpenBBClient.__init__` opens an HTTP
    client and reads config, none of which this test needs.
    """

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames
        self.requested: list[str] = []

    def fetch_series(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any],
        series_label: str,
    ) -> pd.DataFrame:
        symbol = str(params["symbol"])
        self.requested.append(symbol)
        return self._frames[symbol]


def _frame(rows: list[tuple[date, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "value": [r[1] for r in rows],
            "series_id": ["stub"] * len(rows),
            "source": ["stub"] * len(rows),
            "retrieved_at": [datetime(2026, 9, 20, 12, 0, tzinfo=UTC)] * len(rows),
        }
    )


def _entry(tenors: dict[str, str]) -> RegistrySeries:
    return RegistrySeries.model_construct(
        provider="fred",
        endpoint="economy.fred_series",
        tenors=tenors,
        symbol=None,
        not_a_snapshot_field=False,
        snapshot_field=None,
    )


def test_a_forward_dated_tenor_is_not_adopted_as_a_realised_yield() -> None:
    """A tenor whose latest point is a projection must not become the curve.

    The realised point is 4.00 on 2026-09-17. A projection sits at 2027-01-01
    with a deliberately different value (9.99) so the two are distinguishable
    in the output rather than merely by date.
    """
    today = _FIXTURE_AS_OF.date()
    realised = today - timedelta(days=3)
    projection = today + timedelta(days=100)

    client = _StubClient(
        {"DGS2": _frame([(realised, 4.00), (projection, 9.99)])},
    )
    curve = fetch_curve(client, "treasury_curve", _entry({"2yr": "DGS2"}), as_of=_FIXTURE_AS_OF)

    assert curve.tenors["2yr"] == pytest.approx(4.00), (
        "the curve adopted a forward-dated point as a realised yield; "
        "fetch_curve must filter to observation_date <= as_of like every "
        "other series consumer (O-7)"
    )


def test_a_tenor_that_is_entirely_forward_dated_is_refused_not_forecast() -> None:
    """Every point forward-dated ⇒ refuse, never fall back to a projection.

    This is the same distinction `AsOfSeries.is_empty` draws for scalars: a
    series that exists but has no realised observation is a hard stop, not an
    empty default. Falling back to the projection would fabricate a yield.
    """
    today = _FIXTURE_AS_OF.date()
    client = _StubClient(
        {
            "DGS2": _frame(
                [
                    (today + timedelta(days=10), 4.00),
                    (today + timedelta(days=100), 9.99),
                ]
            )
        }
    )

    with pytest.raises(OpenBBFetchError, match="every point is"):
        fetch_curve(client, "treasury_curve", _entry({"2yr": "DGS2"}), as_of=_FIXTURE_AS_OF)


def test_the_curve_reads_the_latest_realised_row_not_the_last_row() -> None:
    """An out-of-order frame must not defeat the filter.

    The frame's final row is a projection but an earlier row is a *later*
    realised date. Reading `iloc[-1]` and reading "the latest realised" are
    different operations, and only the second is correct.
    """
    today = _FIXTURE_AS_OF.date()
    client = _StubClient(
        {
            "DGS2": _frame(
                [
                    (today - timedelta(days=30), 3.00),
                    (today - timedelta(days=1), 4.25),
                    (today + timedelta(days=5), 9.99),  # projection, LAST row
                ]
            )
        }
    )

    curve = fetch_curve(client, "treasury_curve", _entry({"2yr": "DGS2"}), as_of=_FIXTURE_AS_OF)

    assert curve.tenors["2yr"] == pytest.approx(4.25)
    assert curve.as_of == today - timedelta(days=1)


def test_a_fully_realised_curve_is_unchanged_by_the_filter() -> None:
    """The absence half: a curve with nothing to withhold reads as before.

    A guard that alters the ordinary case is a new defect. This pins that the
    filter is inert on clean data.
    """
    today = _FIXTURE_AS_OF.date()
    client = _StubClient(
        {
            "DGS2": _frame([(today - timedelta(days=3), 4.00)]),
            "DGS10": _frame([(today - timedelta(days=3), 4.50)]),
        }
    )

    curve = fetch_curve(
        client,
        "treasury_curve",
        _entry({"2yr": "DGS2", "10yr": "DGS10"}),
        as_of=_FIXTURE_AS_OF,
    )

    assert curve.tenors == {"2yr": pytest.approx(4.00), "10yr": pytest.approx(4.50)}
    assert curve.as_of == today - timedelta(days=3)
