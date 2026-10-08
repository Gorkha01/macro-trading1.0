"""Phase 1 data-layer tests (AGENTS.md Section 11.1).

Section 11.1 names exactly three Phase 1 tests, and all three are here:

1. A **live** test proving ``OpenBBClient.fetch_series()`` returns a
   correctly-shaped frame for a real FRED-backed series and a real
   Treasury-yield series.
2. An **offline** test proving ``OpenBBFetchError`` is raised — not a raw
   provider exception — when both fetch paths fail.
3. A **validation** test proving an engineered "impossible value"
   (``unemployment_rate = 150``) is flagged in ``data_quality_flags``, not
   silently dropped and not silently accepted.

Test 1 is marked ``live`` and excluded from the default run, because a network
dependency in the default suite is how a test suite becomes something people
learn to ignore. Run it explicitly:

    uv run pytest -m live
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from macro_engine.data_layer.openbb_client import (
    _PATH_PACKAGE,
    NORMALIZED_COLUMNS,
    OpenBBClient,
    OpenBBClientConfig,
    OpenBBFetchError,
)
from macro_engine.data_layer.persistence import (
    parquet_path_for,
    parse_compact_timestamp,
)
from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)
from macro_engine.data_layer.validation import (
    Severity,
    attach_flags,
    validate_observations,
    validate_snapshot,
    validate_yield_curve,
)
from macro_engine.models.contracts import utc_now
from tests.conftest import make_curve, make_points, make_snapshot

# ---------------------------------------------------------------------------
# Test 1 — LIVE fetch shape (Section 11.1 Phase 1, requirement 1)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_fetch_returns_correctly_shaped_frame_for_fred_series() -> None:
    """A real FRED-backed series returns the normalized frame contract.

    Asserts the shape, not just "did it return something": the contract is what
    every downstream consumer depends on, and a frame with the right data in
    the wrong column names is a silent failure at the point of use.

    Uses CPI (``CPIAUCSL``) because it is monthly, long-historied and
    unambiguously FRED-backed.
    """
    client = OpenBBClient(OpenBBClientConfig(use_local_api_first=False))
    with client:
        frame = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": "CPIAUCSL"},
            series_label="cpi_headline",
        )

    assert list(frame.columns) == list(NORMALIZED_COLUMNS)
    assert not frame.empty
    assert frame["series_id"].iloc[0] == "cpi_headline"
    # A CPI index level is a positive number in the low hundreds. This catches
    # a units error (e.g. a percent-change column picked as the value).
    assert 50.0 < float(frame["value"].iloc[-1]) < 1000.0
    # Dates must be real dates and must ascend.
    assert isinstance(frame["date"].iloc[-1], date)
    assert frame["date"].is_monotonic_increasing
    # The retrieval stamp must be timezone-aware — a naive stamp makes the
    # future-dating check in validation.py ambiguous.
    assert frame["retrieved_at"].iloc[-1].tzinfo is not None


@pytest.mark.live
def test_live_fetch_returns_correctly_shaped_frame_for_treasury_series() -> None:
    """A real Treasury-yield series returns the normalized frame contract.

    Uses the 10yr constant-maturity yield. Asserts the value is plausible as a
    *yield in percent* — a different unit check from the CPI case above, and
    the one that catches a basis-point/percent mix-up.
    """
    client = OpenBBClient(OpenBBClientConfig(use_local_api_first=False))
    with client:
        frame = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": "DGS10"},
            series_label="yield_curve.10yr",
        )

    assert list(frame.columns) == list(NORMALIZED_COLUMNS)
    assert not frame.empty
    # 0 < 10yr yield < 25 percent. A value in the thousands would mean basis
    # points were returned where percent was expected.
    assert 0.0 < float(frame["value"].iloc[-1]) < 25.0


# ---------------------------------------------------------------------------
# Test 2 — OFFLINE failure raises the single typed exception (requirement 2)
# ---------------------------------------------------------------------------


def test_offline_raises_openbb_fetch_error_when_both_paths_fail() -> None:
    """Both fetch paths mocked to fail must raise ``OpenBBFetchError``.

    The point of the test is the *exception type*, not that an error occurred.
    Callers handle exactly one exception type; a raw ``httpx.ConnectError``
    escaping here would mean every caller needs to know about httpx, which is
    the coupling the client exists to prevent.
    """
    client = OpenBBClient(OpenBBClientConfig(max_retries=2, backoff_seconds=0.0))

    with (
        patch.object(client, "_fetch_via_local_api", side_effect=ConnectionError("api down")),
        patch.object(client, "_fetch_via_package", side_effect=ConnectionError("pkg down")),
        patch("time.sleep"),
        pytest.raises(OpenBBFetchError) as excinfo,
    ):
        client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": "CPIAUCSL"},
            series_label="cpi_headline",
        )

    message = str(excinfo.value)
    assert "cpi_headline" in message
    # The error must name both paths, so an operator knows both were tried.
    assert "local API" in message
    assert "package" in message
    client.close()


def test_offline_falls_back_to_package_when_local_api_fails() -> None:
    """A local-API failure must fall back, not fail outright.

    This is the resilience claim in Section 5.1. Without this test the
    fallback could be broken and every test would still pass whenever the
    local API happened to be running.
    """
    client = OpenBBClient(OpenBBClientConfig(max_retries=1, backoff_seconds=0.0))
    good_frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)],
            "value": [320.5],
            "series_id": ["cpi_headline"],
            "source": ["openbb:package"],
            "retrieved_at": [utc_now()],
        }
    )

    with (
        patch.object(client, "_fetch_via_local_api", side_effect=ConnectionError("api down")),
        patch.object(client, "_fetch_via_package", return_value=good_frame),
        patch("time.sleep"),
    ):
        frame = client.fetch_series(
            provider="fred",
            endpoint="economy.fred_series",
            params={"symbol": "CPIAUCSL"},
            series_label="cpi_headline",
        )

    assert not frame.empty
    assert float(frame["value"].iloc[0]) == 320.5
    client.close()


def test_normalize_rejects_frame_without_recognizable_date_column() -> None:
    """A shape change at the provider must raise, never silently mis-align.

    This is the anti-guessing guard: if OpenBB renames its date column, the
    client must refuse rather than pick "some column" and produce a frame whose
    dates are actually something else.
    """
    client = OpenBBClient()
    with pytest.raises(OpenBBFetchError, match="date column"):
        client._normalize(
            [{"period_ending": "2026-01-01", "amount": 1.0}],
            "test_series",
            served_by=_PATH_PACKAGE,
        )
    client.close()


def test_normalize_rejects_empty_frame() -> None:
    """An empty provider response is a failure, not an empty dataset."""
    client = OpenBBClient()
    with pytest.raises(OpenBBFetchError, match="empty frame"):
        client._normalize(pd.DataFrame(), "test_series", served_by=_PATH_PACKAGE)
    client.close()


# ---------------------------------------------------------------------------
# Test 3 — Engineered impossible value is FLAGGED (requirement 3)
# ---------------------------------------------------------------------------


def test_unemployment_rate_150_is_flagged_not_dropped() -> None:
    """``unemployment_rate = 150`` must be flagged, not dropped or accepted.

    Section 11.1 names this exact case. Three things are asserted, because
    "flagged" is not enough on its own:

    1. The finding exists and is an ERROR.
    2. The value is still **present** in the snapshot — "flag, don't fix" means
       dropping it is also a failure.
    3. The flag reaches ``data_quality_flags``, which is what makes it visible
       to ``compute_confidence()`` and to the thesis warnings.
    """
    points = make_points([3.8, 4.0, 150.0], series_id="unemployment_rate")
    snapshot = make_snapshot(unemployment_rate=points)

    report = validate_snapshot(snapshot)
    codes = {f.code for f in report.findings}
    assert "VALUE_ABOVE_MAX" in codes
    assert report.has_errors

    flagged = [f for f in report.findings if f.code == "VALUE_ABOVE_MAX"]
    assert flagged[0].severity is Severity.ERROR
    assert flagged[0].series_id == "unemployment_rate"
    # The finding names the date, so an operator can go and look at that row.
    assert flagged[0].observation_date is not None

    # (2) The value survives — nothing was silently dropped.
    assert any(p.value == 150.0 for p in snapshot.unemployment_rate)

    # (3) The flag is attached and human-readable.
    with_flags = attach_flags(snapshot, report)
    assert with_flags.data_quality_flags
    assert any("unemployment_rate" in flag for flag in with_flags.data_quality_flags)
    assert any("ERROR" in flag for flag in with_flags.data_quality_flags)


def test_negative_cpi_index_level_is_flagged() -> None:
    """A negative CPI *level* is a fault; a negative CPI *change* is not.

    The distinction is the reason the check is named after the level. Deflation
    is a real economic state and must not be flagged; a negative price index is
    not a state that exists.
    """
    bad = make_points([300.0, 305.0, -12.0], series_id="cpi_headline")
    report = validate_snapshot(make_snapshot(cpi_headline=bad))
    assert any(f.code == "VALUE_BELOW_MIN" for f in report.findings)

    # A falling but positive index must NOT be flagged.
    falling = make_points([305.0, 302.0, 299.0], series_id="cpi_headline")
    clean = validate_snapshot(make_snapshot(cpi_headline=falling))
    assert not clean.has_errors


def test_negative_credit_spread_change_is_not_flagged() -> None:
    """Spreads and changes are legitimately signed — no lower bound applies.

    The registry's ``plausible_range`` describes the OAS *level* (which has
    never been negative — verified 2026-09-19), but the same snapshot field is
    used to carry a spread *change*, and a narrowing spread is legitimately
    negative. ``signed_series: true`` on the registry entry suppresses the
    lower-bound check while the upper bound still applies, so this test guards
    the distinction: a widening beyond 40pp must still be an ERROR.
    """
    points = make_points([4.5, 3.9, -0.2], series_id="credit_spread_hy")
    report = validate_snapshot(make_snapshot(credit_spread_hy=points))
    assert not report.has_errors

    # The UPPER bound must still be enforced for a signed series.
    absurd = make_points([4.5, 3.9, 99.0], series_id="credit_spread_hy")
    upper = validate_snapshot(make_snapshot(credit_spread_hy=absurd))
    assert any(f.code == "VALUE_ABOVE_MAX" for f in upper.findings)


def test_future_observation_date_is_flagged() -> None:
    """An observation dated after retrieval is an ERROR.

    Timezone-naive provider feeds commonly stamp tomorrow's date. Left
    unflagged, that value enters a YoY window at the wrong end.
    """
    retrieval = utc_now()
    point_date = (retrieval + timedelta(days=3)).date()
    from macro_engine.data_layer.schemas import ObservationPoint

    points = [
        ObservationPoint(
            observation_date=point_date,
            value=3.9,
            series_id="unemployment_rate",
            retrieved_at=retrieval,
        )
    ]
    report = validate_observations(points, series_id="unemployment_rate")
    assert any(f.code == "FUTURE_OBSERVATION_DATE" for f in report.findings)
    assert report.has_errors


def test_duplicate_observation_dates_are_flagged() -> None:
    """Duplicate dates silently double-count in a mean — must be surfaced."""
    from macro_engine.data_layer.schemas import ObservationPoint

    same_day = date(2026, 3, 1)
    points = [
        ObservationPoint(
            observation_date=same_day,
            value=3.9,
            series_id="unemployment_rate",
            retrieved_at=utc_now(),
        ),
        ObservationPoint(
            observation_date=same_day,
            value=4.1,
            series_id="unemployment_rate",
            retrieved_at=utc_now(),
        ),
    ]
    report = validate_observations(points, series_id="unemployment_rate")
    assert any(f.code == "DUPLICATE_OBSERVATION_DATE" for f in report.findings)


def test_empty_snapshot_produces_no_findings() -> None:
    """A snapshot that requested nothing has nothing to be wrong with it.

    Without this, a deliberately partial snapshot produced a wall of identical
    EMPTY_SERIES flags — which trains a reader to ignore the flag list, the
    exact opposite of the intent.
    """
    report = validate_snapshot(MacroDataSnapshot())
    assert report.findings == []


# ---------------------------------------------------------------------------
# Yield-curve validation
# ---------------------------------------------------------------------------


def test_genuine_short_end_inversion_is_info_not_error() -> None:
    """A real 2s10s inversion is economically meaningful — INFO, not ERROR.

    Module 8.1: inversions happen at the short end and are a signal. Flagging
    them as errors would make the system blind to one of its own inputs.
    """
    inverted = make_curve({"2yr": 4.80, "5yr": 4.60, "10yr": 4.35, "30yr": 4.40})
    report = validate_yield_curve(inverted, series_id="yield_curve")
    codes = {f.code for f in report.findings}
    assert "CURVE_INVERTED_2S10S" in codes
    assert not report.has_errors

    info_only = [f for f in report.findings if f.code == "CURVE_INVERTED_2S10S"]
    assert info_only[0].severity is Severity.INFO


def test_implausible_long_end_inversion_is_error() -> None:
    """A 30yr far BELOW the 10yr is a data fault dressed as an inversion.

    Section 5.4 explicitly asks for this distinction: "flag (not silently fix)
    an inverted-looking value that's actually a data error".
    """
    broken = make_curve({"2yr": 4.00, "10yr": 4.50, "30yr": 0.50})
    report = validate_yield_curve(broken, series_id="yield_curve")
    assert any(f.code == "IMPLAUSIBLE_LONG_END_INVERSION" for f in report.findings)
    assert report.has_errors


def test_non_positive_yield_is_error() -> None:
    broken = make_curve({"2yr": 4.0, "10yr": 0.0})
    report = validate_yield_curve(broken, series_id="yield_curve")
    assert any(f.code == "NON_POSITIVE_YIELD" for f in report.findings)


def test_unknown_tenor_label_is_rejected_at_construction() -> None:
    """A typo'd tenor must fail loudly at build time, not vanish silently."""
    with pytest.raises(ValueError, match="Unrecognized tenor"):
        YieldCurveSnapshot(as_of=date(2026, 1, 1), tenors={"2yyyy": 4.0})


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


def test_snapshot_round_trips_through_long_frame() -> None:
    """A snapshot survives a write/read cycle without distortion.

    The round-trip is what Section 21.1's revision analysis depends on: if
    values shift by a float cast or dates lose a day, the vintage comparison
    silently compares the wrong things.
    """
    from macro_engine.data_layer.persistence import (
        long_frame_from_snapshot,
        snapshot_from_long_frame,
    )

    original = make_snapshot(
        cpi_headline=make_points([300.0, 305.5, 310.25], series_id="cpi_headline"),
        unemployment_rate=make_points([3.7, 3.8, 3.9], series_id="unemployment_rate"),
        yield_curve=make_curve({"2yr": 4.55, "10yr": 4.35}),
    )
    frame = long_frame_from_snapshot(original)
    assert not frame.empty

    restored = snapshot_from_long_frame(frame)
    assert restored.country == original.country
    assert [p.value for p in restored.cpi_headline] == [300.0, 305.5, 310.25]
    assert [p.value for p in restored.unemployment_rate] == [3.7, 3.8, 3.9]
    # Curve tenors are stored under field="yield_curve" with the tenor in
    # series_id ("yield_curve.2yr"), so the field name stays stable while the
    # tenor varies. Asserting on field would miss every tenor row.
    curve_rows = frame[frame["field"] == "yield_curve"]
    assert not curve_rows.empty
    assert set(curve_rows["series_id"]) == {"yield_curve.2yr", "yield_curve.10yr"}
    assert set(curve_rows["value"]) == {4.55, 4.35}


def test_empty_snapshot_still_produces_a_frame() -> None:
    """An empty fetch is an audit fact, not a missing record."""
    from macro_engine.data_layer.persistence import _LONG_COLUMNS, long_frame_from_snapshot

    frame = long_frame_from_snapshot(make_snapshot())
    assert frame.empty
    # Read the expected columns from the module's own schema constant rather than
    # hardcoding them again. The previous version restated the list here, so
    # adding the two Section 6 release-side columns made an *empty-snapshot* test
    # fail — the assertion was pinning a duplicate of the schema, not the
    # behaviour under test. D-035: a test's expectation must not be a second copy
    # of the thing it is checking.
    assert list(frame.columns) == list(_LONG_COLUMNS)
    # And the two release-side columns must actually be part of the schema, since
    # their absence is the defect this increment fixes.
    assert "release_datetime" in _LONG_COLUMNS
    assert "vintage_datetime" in _LONG_COLUMNS


# ---------------------------------------------------------------------------
# Config / registry enforcement
# ---------------------------------------------------------------------------


def test_blocked_series_raises_not_implemented() -> None:
    """Section 21.4: a BLOCKED input must fail loudly, never be proxied.

    The condition is **constructed** rather than borrowed from the live registry.
    The earlier version asserted against `risky_credit_growth_pct`, and D-043
    lifted that block — so this test failed for a reason unrelated to the rule
    under test. That is precisely the coupling the neighbouring
    `test_unverified_series_is_refused` docstring diagnoses: a rule test must not
    depend on which entries happen to be blocked today, or lifting a block breaks
    a test of the rule rather than of the registry's contents.
    """
    from macro_engine.config import BlockedSeries, RegistrySeries, SeriesRegistry

    registry = SeriesRegistry(
        version=1,
        defaults={"provider": "fred", "endpoint": "economy.fred_series"},
        # A blocked field has NO series entry — that is what `require_verified`
        # keys on. A present-but-unverified entry takes the other branch and
        # reports 'unverified' rather than 'BLOCKED', so the two conditions are
        # genuinely different and this fixture must produce the second.
        series={
            "made_up_present": RegistrySeries(
                provider="fred",
                symbol="NOTREAL",
                status="verified",
                verified_on=date(2026, 1, 1),
                verified_value=1.0,
            )
        },
        blocked=[
            BlockedSeries(
                field="made_up_blocked",
                reason="constructed by this test, so the rule is tested and not the registry",
            )
        ],
    )
    with pytest.raises(NotImplementedError, match="BLOCKED"):
        registry.require_verified("made_up_blocked")


def test_unverified_series_is_refused() -> None:
    """Section 21.1: a route must be verified in Phase 0 before use.

    This constructs the unverified condition rather than relying on some
    registry entry happening to be unverified. The earlier version asserted
    against a live entry, so verifying all series in Phase 0 made the test fail
    for the wrong reason — it was coupled to registry state instead of to the
    rule under test.
    """
    from macro_engine.config import RegistrySeries, SeriesRegistry

    registry = SeriesRegistry(
        version=1,
        defaults={"provider": "fred", "endpoint": "economy.fred_series"},
        series={
            "made_up_series": RegistrySeries(
                provider="fred",
                symbol="NOTREAL",
                status="unverified",
            )
        },
    )
    with pytest.raises(NotImplementedError, match="verified"):
        registry.require_verified("made_up_series")


def test_verified_series_requires_recorded_evidence() -> None:
    """Section 21.0 rule 5: real-data validation must be RECORDED.

    A bare ``status: verified`` is an unbacked claim, and it is the exact
    shortcut an agent would take to unblock a downstream model. Requiring the
    observed value and date makes the claim checkable.
    """
    from macro_engine.config import RegistrySeries

    with pytest.raises(ValueError, match="verified_on / verified_value"):
        RegistrySeries(
            provider="fred",
            symbol="CPIAUCSL",
            status="verified",
            # no verified_on / verified_value
        )


def test_verified_value_must_satisfy_its_own_plausible_range() -> None:
    """If the bounds and the observation disagree, one of them is wrong.

    This is the check that would have caught a mis-mapped series being marked
    verified with a value that could not possibly belong to it.
    """
    from macro_engine.config import RegistrySeries

    with pytest.raises(ValueError, match="plausible_range"):
        RegistrySeries(
            provider="fred",
            symbol="CPIAUCSL",
            status="verified",
            verified_on=date(2026, 9, 16),
            verified_value=99_999.0,
            plausible_range=(50.0, 1000.0),
        )


def test_forward_looking_verification_must_name_a_realised_observation_date() -> None:
    """DECISIONS.md D-010: a projection is not evidence of a current value.

    The defect D-010 records — ``gdp_potential`` verified against its Q4 2036
    projection — passed every check that existed at the time, because the
    projection sits inside the declared ``plausible_range``. A value being
    *plausible for the series* is not the same as that value being *the
    observation the verification should record*, and only a date makes the
    difference visible.
    """
    from macro_engine.config import RegistrySeries

    with pytest.raises(ValueError, match="verified_observation_date"):
        RegistrySeries(
            provider="fred",
            symbol="GDPPOT",
            status="verified",
            forward_looking=True,
            verified_on=date(2026, 9, 16),
            verified_value=29_443.0227,  # the Q4 2036 projection
            # no verified_observation_date — nothing says when this belongs
            plausible_range=(1000.0, 40_000.0),
        )


def test_forward_looking_verification_cannot_cite_a_projection_as_evidence() -> None:
    """The sharp version: the date must fall OUTSIDE the projection block."""
    from macro_engine.config import RegistrySeries

    with pytest.raises(ValueError, match="inside its own projection block"):
        RegistrySeries(
            provider="fred",
            symbol="GDPPOT",
            status="verified",
            forward_looking=True,
            verified_on=date(2026, 9, 16),
            verified_value=29_443.0227,
            verified_observation_date=date(2036, 10, 1),  # inside the block
            verified_curve={"projection_block_starts": date(2026, 10, 1)},
            plausible_range=(1000.0, 40_000.0),
        )


def test_forward_looking_verification_accepts_a_realised_observation() -> None:
    """And the correct shape passes — the constraint is not merely obstructive."""
    from macro_engine.config import RegistrySeries

    entry = RegistrySeries(
        provider="fred",
        symbol="GDPPOT",
        status="verified",
        forward_looking=True,
        verified_on=date(2026, 9, 16),
        verified_value=24_070.9386484,
        verified_observation_date=date(2026, 4, 1),
        verified_curve={"projection_block_starts": date(2026, 10, 1)},
        plausible_range=(1000.0, 40_000.0),
    )
    assert entry.verified_observation_date == date(2026, 4, 1)


def test_the_live_registry_entry_for_gdp_potential_records_a_realised_value() -> None:
    """Guards the actual shipped entry, not just the validator's shape.

    A validator proves the rule *can* be enforced. This proves the config as
    committed satisfies it — the failure mode being that someone edits the
    entry to make a test pass and the enforcement quietly stops applying to the
    series it was written for.
    """
    from macro_engine.config import get_registry

    entry = get_registry().series["gdp_potential"]
    assert entry.forward_looking is True
    assert entry.verified_observation_date is not None
    assert entry.verified_value == 24_070.9386484
    assert entry.verified_observation_date == date(2026, 4, 1)

    curve = entry.verified_curve
    assert curve is not None
    assert (
        date.fromisoformat(str(curve["projection_block_starts"])) > entry.verified_observation_date
    )
    # The live series is mostly projections: 41 of 62 points. If that ratio ever
    # inverts, the forward_looking flag and this whole guard need revisiting.
    assert curve["forward_dated_count"] < curve["observation_count"]


def test_registry_defaults_are_inherited_by_series() -> None:
    """The ``defaults:`` block must actually be applied to each entry.

    Found by live execution: the config parsed cleanly and every entry *looked*
    correct, because provider/endpoint were present in the file's defaults
    block — but they were absent from the parsed objects, so every scalar fetch
    failed with "no endpoint configured". A parsed-but-unapplied defaults block
    is invisible to inspection and only surfaces at runtime.
    """
    from macro_engine.config import get_registry

    registry = get_registry()
    entry = registry.series["cpi_headline"]
    assert entry.provider == registry.defaults["provider"]
    assert entry.endpoint == registry.defaults["endpoint"]


def test_snapshot_field_alias_is_resolvable() -> None:
    """The registry key and the schema attribute must agree somewhere explicit.

    ``treasury_curve`` (key) populates ``yield_curve`` (schema). Assuming they
    matched silently dropped the entire Treasury curve from the first live
    snapshot build.

    A registry entry has exactly two legitimate resolutions: it populates a
    real ``MacroDataSnapshot`` field, or it declares ``not_a_snapshot_field``
    and is documentation-only. A third state — resolving to a name the schema
    does not define, via the ``snapshot_field or field_name`` fallback — is the
    silent-mismatch bug this test exists for, and it must stay impossible.
    """
    from macro_engine.config import get_registry
    from macro_engine.data_layer.openbb_client import OpenBBFetchError
    from macro_engine.data_layer.schemas import MacroDataSnapshot
    from macro_engine.data_layer.snapshot_builder import resolve_snapshot_field

    registry = get_registry()
    declared_off_schema: list[str] = []
    for name, entry in registry.series.items():
        try:
            target = resolve_snapshot_field(name, entry)
        except OpenBBFetchError:
            declared_off_schema.append(name)
            continue
        assert target in MacroDataSnapshot.model_fields, (
            f"registry '{name}' resolves to '{target}', absent from MacroDataSnapshot"
        )

    # The escape hatch must be used, not merely available. If every entry
    # resolved into the schema the no-op branch above would pass silently.
    assert declared_off_schema, (
        "no registry entry declares `not_a_snapshot_field`; either Module 7.3's "
        "components were removed or the guard stopped being exercised"
    )


def test_persistence_field_lists_match_schema() -> None:
    """Every persisted field must exist on the schema — AND every schema series
    field must be persisted.

    The write and read paths previously held two parallel literal tuples; a
    field added to one and forgotten in the other would vanish from every
    snapshot with no error at all.

    **BOTH directions are asserted (added 2026-09-29, audit finding P-1).** The
    original test checked only ``declared - schema`` — that nothing persisted is
    absent from the schema. It never checked the direction that loses data:
    a *schema* field omitted from these tuples is silently erased, because
    ``long_frame_from_snapshot`` iterates the tuples and nothing else. Measured
    on the pre-fix tree: ``fed_total_assets``, ``reserve_balances``,
    ``ppi_stage_crude`` and ``ppi_stage_intermediate`` were all declared,
    populated and dropped — a snapshot carrying all four round-tripped to ZERO
    rows, and no gate noticed.
    """
    from macro_engine.data_layer.persistence import (
        CURVE_SERIES_FIELDS,
        MAPPING_SERIES_FIELDS,
        SCALAR_SERIES_FIELDS,
    )
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    declared = set(SCALAR_SERIES_FIELDS) | set(CURVE_SERIES_FIELDS) | set(MAPPING_SERIES_FIELDS)
    fields = set(MacroDataSnapshot.model_fields)

    absent_from_schema = sorted(declared - fields)
    assert not absent_from_schema, (
        f"persistence declares fields absent from the schema: {absent_from_schema}"
    )

    # The direction that catches silent data loss. Metadata fields are not
    # series and are legitimately not persisted (they are snapshot-level, not
    # observations), so they are excluded BY NAME — a blanket "everything must be
    # persisted" would be wrong and would force a metadata field into the long
    # frame.
    non_series_fields = {
        "country",
        "as_of",
        "decision_cutoff",
        "data_quality_flags",
        "field_sources",
    }
    series_fields = fields - non_series_fields
    never_persisted = sorted(series_fields - declared)
    assert not never_persisted, (
        f"these schema series fields are absent from every persistence tuple and "
        f"are therefore SILENTLY ERASED from every snapshot: {never_persisted}. "
        f"Add each to SCALAR_SERIES_FIELDS / CURVE_SERIES_FIELDS / "
        f"MAPPING_SERIES_FIELDS (or to the non-series exclusion set if it is "
        f"genuinely metadata)."
    )


def test_every_scalar_series_field_survives_a_persistence_round_trip() -> None:
    """A populated scalar field must come back populated (audit finding P-1).

    The tuple-coverage test above is a *name* check; this one is an *effect*
    check. It exists because a name check can be satisfied by a list that is
    wrong in a way no name comparison sees, and because the pre-fix defect was
    measured as total erasure (zero rows), not a partial one — every field in
    ``SCALAR_SERIES_FIELDS`` is populated here and must return.
    """
    from datetime import UTC, date, datetime

    from macro_engine.data_layer.persistence import (
        SCALAR_SERIES_FIELDS,
        long_frame_from_snapshot,
        snapshot_from_long_frame,
    )
    from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint

    snapshot = MacroDataSnapshot(as_of=datetime(2026, 9, 29, tzinfo=UTC))
    for name in SCALAR_SERIES_FIELDS:
        setattr(
            snapshot,
            name,
            [
                ObservationPoint(
                    observation_date=date(2026, 8, 1),
                    value=123.0,
                    series_id=name,
                )
            ],
        )

    frame = long_frame_from_snapshot(snapshot)
    assert not frame.empty, (
        "a snapshot with every scalar field populated persisted ZERO rows — the "
        "persistence tuples do not cover the schema"
    )

    restored = snapshot_from_long_frame(frame)
    for name in SCALAR_SERIES_FIELDS:
        got = getattr(restored, name)
        assert len(got) == 1, f"{name} was dropped by the persistence round-trip"
        assert got[0].value == 123.0


def test_every_scalar_snapshot_field_is_in_the_bootstrap_fetch_list() -> None:
    """A schema field that is never fetched is a field that is always empty.

    This is the guard for a real defect (2026-09-19): ``gdi`` had a registry
    entry with ``status: verified``, a ``MacroDataSnapshot`` field, a slot in
    ``persistence.SCALAR_SERIES_FIELDS``, and a place in the dashboard's
    ``growth`` panel — but was **absent from ``snapshot_fields.us``**, the list
    the snapshot builder actually fetches from. Consequence: 0 observations on
    every build, the only empty scalar series, and Module 7.1's
    ``gdp_gdi_divergence`` (implemented, tested, mutation-tested) had no data
    path. Nothing failed; the dashboard simply requested a series that could
    never appear.

    The reverse direction is not asserted, and deliberately so:
    ``snapshot_fields`` legitimately names curve fields (``treasury_curve``,
    ``tips_yields``) whose names are registry-level rather than schema-level, so
    a strict equality would be wrong. What must hold is that no *scalar* schema
    field is unreachable — that is the asymmetry that produced the bug.
    """
    from macro_engine.config import get_settings
    from macro_engine.data_layer.persistence import SCALAR_SERIES_FIELDS

    fetched = set(get_settings().snapshot_fields["us"])
    unfetched = sorted(set(SCALAR_SERIES_FIELDS) - fetched)

    assert not unfetched, (
        f"scalar series declared in the schema and in persistence but never "
        f"fetched by the snapshot builder: {unfetched}. Either add them to "
        f"snapshot_fields.us in config/settings.yaml or remove them from "
        f"SCALAR_SERIES_FIELDS."
    )


def test_every_snapshot_field_registry_entry_is_actually_fetched() -> None:
    """A registry entry that populates a snapshot field must be in the fetch list.

    **Registry-driven companion to the test above (added 2026-09-29, audit
    finding P-2).** The test above iterates ``SCALAR_SERIES_FIELDS`` — the
    *persistence* tuple. That is the wrong direction to catch this defect class,
    and the measurement proves it: ``ppi_stage_crude`` and
    ``ppi_stage_intermediate`` were absent from *both* the persistence tuple and
    ``snapshot_fields.us``, so the test's iteration set did not contain them and
    it could not see them at all. The P-1 fix (adding them to
    ``SCALAR_SERIES_FIELDS``) is what made the test above able to fail — a
    genuine fix exposing a second defect behind it, not a regression.

    The registry is the only complete enumeration. Every entry that resolves
    into a real ``MacroDataSnapshot`` field is, by declaration, a series the
    snapshot is *supposed* to carry; if it is not in ``snapshot_fields`` then no
    build will ever ``setattr`` it, and its schema field stays empty forever.
    The three states that make this legitimate are excluded, and each is a
    declaration rather than an omission:

    * ``not_a_snapshot_field: true`` — documentation-only (Module 7.3).
    * a ``not_a_snapshot_field`` resolution that raises — same, at the
      ``resolve_snapshot_field`` boundary.
    * ``status`` other than ``verified`` — ``build_snapshot`` calls
      ``require_verified`` and reports it as ``skipped_unverified``, which is an
      explicit, visible absence. An *unverified* series is allowed to be
      unfetched; a *verified* one is not.

    Curve fields (``entry.tenors``) and explicit ``snapshot_field`` aliases are
    included: they resolve to real schema attributes and are fetched from the
    same list, so the same rule applies. The membership test is on the registry
    KEY, because that is what the list holds — measured: a version comparing the
    resolved target instead flagged ``treasury_curve`` (key) -> ``yield_curve``
    (schema), which is fetched under its key.
    """
    from macro_engine.config import get_registry, get_settings
    from macro_engine.data_layer.openbb_client import OpenBBFetchError
    from macro_engine.data_layer.schemas import MacroDataSnapshot
    from macro_engine.data_layer.snapshot_builder import resolve_snapshot_field

    registry = get_registry()
    fetched = set(get_settings().snapshot_fields["us"])

    unaccounted: list[str] = []
    for name, entry in registry.series.items():
        if entry.not_a_snapshot_field or entry.status != "verified":
            continue
        try:
            target = resolve_snapshot_field(name, entry)
        except OpenBBFetchError:
            # A not_a_snapshot_field boundary refusal: provenance-only.
            continue
        if target not in MacroDataSnapshot.model_fields:
            # Belongs to test_snapshot_field_alias_is_resolvable, not here.
            continue
        # ``snapshot_fields`` names REGISTRY KEYS, not schema attributes:
        # build_snapshot does ``get_registry().series.get(field_name)`` for each
        # entry. ``treasury_curve`` (key) -> ``yield_curve`` (schema), and it is
        # the key that must appear in the list. Comparing the resolved target
        # instead would report every aliased entry as unaccounted — measured:
        # it flagged ``treasury_curve`` even though it IS fetched.
        if name not in fetched:
            unaccounted.append(f"{name} (-> {target})")

    assert not unaccounted, (
        f"these registry entries are `verified`, resolve into a real "
        f"MacroDataSnapshot field, and are NOT `not_a_snapshot_field`, yet are "
        f"absent from snapshot_fields.us — so no snapshot build will ever "
        f"populate them and their schema fields stay empty forever: "
        f"{sorted(unaccounted)}. Either add each to snapshot_fields.us in "
        f"config/settings.yaml, or declare it `not_a_snapshot_field: true` if it "
        f"is genuinely provenance-only."
    )


def test_documented_only_registry_entry_is_refused_by_the_snapshot_builder() -> None:
    """A provenance-only entry must fail loudly, not resolve to a wrong name.

    Module 7.3's components live in the registry so their routes are
    verified and recorded, but they have no ``MacroDataSnapshot`` field. The
    ``snapshot_field or field_name`` fallback would resolve ``building_permits``
    to itself and then fail ``_assert_field_exists`` with a message telling the
    author to "fix snapshot_field in config/series_registry.yaml" — advice that
    is wrong for an entry that was never meant to be in the snapshot. The
    declaration makes the failure name the actual situation.
    """
    from macro_engine.config import get_registry
    from macro_engine.data_layer.openbb_client import OpenBBFetchError
    from macro_engine.data_layer.snapshot_builder import resolve_snapshot_field

    registry = get_registry()
    entry = registry.series["building_permits"]
    assert entry.not_a_snapshot_field is True
    assert entry.snapshot_field is None, (
        "a not_a_snapshot_field entry must not also declare a snapshot_field; "
        "the two are contradictory and the guard would mask the mistake"
    )

    with pytest.raises(OpenBBFetchError, match="not_a_snapshot_field"):
        resolve_snapshot_field("building_permits", entry)


def test_a_snapshot_field_entry_is_still_resolved_normally() -> None:
    """The guard must be conditional, not a blanket refusal.

    Symmetry-breaking companion to the test above: a mutation making
    ``resolve_snapshot_field`` raise unconditionally would be killed here and
    nowhere else.
    """
    from macro_engine.config import get_registry
    from macro_engine.data_layer.snapshot_builder import resolve_snapshot_field

    registry = get_registry()
    assert resolve_snapshot_field("cpi_headline", registry.series["cpi_headline"]) == (
        "cpi_headline"
    )
    # The genuine alias path must survive too — this is the D-0xx Treasury bug.
    assert resolve_snapshot_field("treasury_curve", registry.series["treasury_curve"]) == (
        "yield_curve"
    )


def test_forward_looking_series_reports_horizon_as_info() -> None:
    """A projection series must not be flagged as faulty future-dated data.

    CBO potential output carries ~10 years of forward projections, which are
    required for the output-gap calculation. Flagging 41 legitimate points as
    ERROR on every snapshot is how a real diagnostic gets trained out of a
    reader, so those points collapse to ONE INFO finding.
    """
    from macro_engine.data_layer.validation import Severity, validate_observations

    future = date(2030, 1, 1)
    points = [
        ObservationPoint(
            observation_date=future, value=100.0, series_id="gdp_potential", retrieved_at=utc_now()
        )
    ]
    report = validate_observations(points, series_id="gdp_potential", forward_looking=True)
    codes = [f.code for f in report.findings]
    assert "FORWARD_LOOKING_HORIZON" in codes
    assert "FUTURE_OBSERVATION_DATE" not in codes
    horizon = next(f for f in report.findings if f.code == "FORWARD_LOOKING_HORIZON")
    assert horizon.severity is Severity.INFO

    # And the same points WITHOUT the flag must still be an ERROR.
    strict = validate_observations(points, series_id="gdp_potential", forward_looking=False)
    assert any(f.code == "FUTURE_OBSERVATION_DATE" for f in strict.findings)
    assert strict.has_errors


def test_same_day_publication_within_tolerance_is_info_not_error() -> None:
    """A daily series published for tomorrow's UTC date is a clock artifact.

    D-030: FRED published IORB dated `2026-09-17` while the process clock read
    `2026-09-16 20:49 UTC`. The validator's comparison was correct and the
    premise — that no observation can post-date `utc_now()` — was false for a
    daily series in the window between publication and midnight UTC.

    The point is REAL data, so it must be disclosed (a reader needs to know the
    feed ran ahead) but must not be reported as corruption. This test pins all
    three properties: no ERROR, an INFO finding present, and the aggregate
    FUTURE_DATED_POINTS_SUMMARY absent.
    """
    from macro_engine.data_layer.validation import Severity, validate_observations

    retrieve = datetime(2026, 9, 16, 20, 49, tzinfo=UTC)
    points = [
        ObservationPoint(
            observation_date=date(2026, 9, 16), value=3.65, series_id="iorb", retrieved_at=retrieve
        ),
        ObservationPoint(
            observation_date=date(2026, 9, 17), value=3.90, series_id="iorb", retrieved_at=retrieve
        ),
    ]
    report = validate_observations(points, series_id="iorb", future_date_tolerance_days=1)
    codes = [f.code for f in report.findings]
    assert "FUTURE_OBSERVATION_DATE" not in codes
    assert "FUTURE_DATED_POINTS_SUMMARY" not in codes
    assert "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK" in codes
    disclosed = next(f for f in report.findings if f.code == "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK")
    assert disclosed.severity is Severity.INFO
    assert not report.has_errors


def test_tolerance_boundary_is_exact() -> None:
    """A mutation widening the comparison to ``<`` or shifting the boundary
    must be killed, so the test straddles the declared tolerance exactly.

    Tolerance 1 admits a 1-day lead and rejects 2 — the boundary is the whole
    behaviour. Testing only a 1-day lead would pass for any tolerance >= 1.
    """
    from macro_engine.data_layer.validation import validate_observations

    retrieve = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

    def _report(lead_days: int, tolerance: int) -> list[str]:
        points = [
            ObservationPoint(
                observation_date=date(2026, 9, 16 + lead_days),
                value=3.90,
                series_id="iorb",
                retrieved_at=retrieve,
            )
        ]
        return [
            f.code
            for f in validate_observations(
                points, series_id="iorb", future_date_tolerance_days=tolerance
            ).findings
        ]

    assert "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK" in _report(1, 1)
    assert "FUTURE_OBSERVATION_DATE" not in _report(1, 1)

    # One day beyond the declaration is a fault again.
    beyond = _report(2, 1)
    assert "FUTURE_OBSERVATION_DATE" in beyond
    assert "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK" not in beyond

    # Zero tolerance (the default) refuses even a one-day lead.
    assert "FUTURE_OBSERVATION_DATE" in _report(1, 0)

    # The tolerance must not confer projection status: a tolerated point is
    # realised data, so FORWARD_LOOKING_HORIZON must not appear for it.
    assert "FORWARD_LOOKING_HORIZON" not in _report(1, 1)


def test_a_broken_mapping_is_not_hidden_by_the_tolerance() -> None:
    """The tolerance must not become a general amnesty for future dates.

    A genuine broken mapping or bad provider stamp lands far outside any small
    tolerance. This is the guard that keeps the D-030 fix from disarming the
    diagnostic it was carved out of.
    """
    from macro_engine.data_layer.validation import validate_observations

    retrieve = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    points = [
        ObservationPoint(
            observation_date=date(2027, 6, 1), value=3.90, series_id="iorb", retrieved_at=retrieve
        )
    ]
    report = validate_observations(points, series_id="iorb", future_date_tolerance_days=7)
    codes = [f.code for f in report.findings]
    assert "FUTURE_OBSERVATION_DATE" in codes
    assert "FUTURE_DATED_POINTS_SUMMARY" in codes
    assert report.has_errors
    # The message must name the tolerance, so a reader can tell a genuine
    # excess from a misconfigured threshold.
    detail = next(f for f in report.findings if f.code == "FUTURE_OBSERVATION_DATE").detail
    assert "tolerance" in detail


def test_the_tolerance_defaults_to_zero_and_the_registry_declares_it() -> None:
    """The default must refuse, and only the series that need a lead may opt in.

    A mutation widening the default from 0 to a large number would otherwise
    survive every test in this file, because each one passes the tolerance
    *explicitly* — a test suite that only ever supplies a value cannot see what
    the value is when nobody supplies one. This closes that gap by exercising
    the default path, and by asserting the registry's actual declarations.

    The declaration matters as much as the default: if the default were 1, a
    genuinely broken mapping one day out would be silently tolerated for every
    series in the project, not just the two whose provider publishes early.
    """
    from macro_engine.config import RegistrySeries, get_registry
    from macro_engine.data_layer.validation import validate_observations

    # --- the field default --------------------------------------------------
    assert RegistrySeries.model_fields["future_date_tolerance_days"].default == 0, (
        "the tolerance must default to zero; a non-zero default tolerates a "
        "future-dated point for every series that never asked for it"
    )

    retrieve = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    points = [
        ObservationPoint(
            observation_date=date(2026, 9, 17), value=3.90, series_id="x", retrieved_at=retrieve
        )
    ]
    # No tolerance passed at all — the default must apply.
    codes = [f.code for f in validate_observations(points, series_id="x").findings]
    assert "FUTURE_OBSERVATION_DATE" in codes
    assert "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK" not in codes

    # --- the registry declarations -----------------------------------------
    registry = get_registry()
    declared = {
        name: entry.future_date_tolerance_days
        for name, entry in registry.series.items()
        if entry.future_date_tolerance_days > 0
    }
    # Exactly the series whose provider publishes ahead of the UTC clock.
    # iorb is 3, not 1: live re-verification on 2026-09-19 (AUDIT-002) showed
    # IORB publishing TWO days ahead (retrieval 2026-09-19 returned points
    # dated 2026-09-20 and 2026-09-21), because it is an ADMINISTERED rate
    # the Fed schedules in advance rather than a market print. The old
    # declaration of 1 armed the ERROR path against a legitimate print and
    # produced a standing failure (O-84). sofr stays at 1 because SOFR IS a
    # prior-business-day market print. A third series opting in, or either
    # value moving, is a decision that needs its own justification rather
    # than a quiet config edit.
    assert declared == {"iorb": 3, "sofr": 1}, (
        f"unexpected tolerance declarations: {declared}. A third series opting in "
        "is a decision that needs its own justification, not a quiet config edit."
    )


def test_the_tolerance_is_not_applied_to_forward_looking_series() -> None:
    """The two conditions must stay separate; one must not subsume the other.

    A projection series and a same-day publication are both
    ``observation_date > today`` and mean opposite things: the first is an
    *estimate of the future*, the second is *realised data* the provider
    happened to publish early. A mutation making the tolerated branch fire for
    a forward-looking series would report a decade-ahead CBO projection as a
    clock artifact — labelling real projections as ordinary same-day prints,
    and destroying the distinction the output depends on.

    **This is the far case: the point is BEYOND the tolerance.** It lands in
    ``future_dates``, not ``tolerated_future_dates``, so it exercises the
    ``forward_looking and future_dates`` branch. Its sibling
    :func:`test_the_tolerance_is_not_applied_to_a_TOLERATED_forward_looking_point`
    covers the near case, which is the one the guard actually protects.
    """
    from macro_engine.data_layer.validation import Severity, validate_observations

    retrieve = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    points = [
        ObservationPoint(
            observation_date=date(2030, 1, 1),
            value=27000.0,
            series_id="gdp_potential",
            retrieved_at=retrieve,
        )
    ]
    report = validate_observations(
        points,
        series_id="gdp_potential",
        forward_looking=True,
        future_date_tolerance_days=1,
    )
    codes = [f.code for f in report.findings]
    assert "FORWARD_LOOKING_HORIZON" in codes
    assert "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK" not in codes, (
        "a forward-looking series fell into the tolerance branch and was reported "
        "as a same-day publication rather than as an estimate"
    )
    horizon = next(f for f in report.findings if f.code == "FORWARD_LOOKING_HORIZON")
    assert horizon.severity is Severity.INFO
    assert not report.has_errors


def test_the_tolerance_is_not_applied_to_a_tolerated_forward_looking_point() -> None:
    """The NEAR case — the one the ``not forward_looking`` guard actually protects.

    Written because a mutation sweep survivor exposed a gap: the sibling test
    above asserts the right *property* but supplies a point **beyond** the
    tolerance, so it lands in ``future_dates`` and never reaches the tolerated
    branch. A mutant that deletes ``and not forward_looking`` from the
    ``SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK`` guard therefore survived the whole
    suite — a test asserting the property while being unable to reach the
    branch is O-29's mis-target class.

    The failure it hides is not cosmetic. That finding's own text reads *"Not a
    fault, and NOT an estimate: unlike a forward_looking series these points
    are realised data."* Attached to a **projection** series, that sentence is
    **false about the object it describes** — the system would publish a
    forward estimate, at INFO severity, wearing a code that declares it
    realised, with no ``FORWARD_LOOKING_HORIZON`` line to contradict it. The
    downstream PIT filter keys on exactly this distinction.

    Note the tolerance is **smaller than the lead**: this is the only shape that
    populates ``tolerated_future_dates``, and covered by the no-tolerance
    default is the only other way to reach the branch.

    **The measured behaviour of this cell is SILENCE, and that is recorded here
    rather than asserted away.** A forward-looking series with a tolerated point
    emits *no finding at all*: ``FORWARD_LOOKING_HORIZON`` keys on
    ``future_dates``, which this point never enters, and the same-day path is
    correctly suppressed by the guard under test. The cell is therefore
    composite — two independently-correct branches that jointly produce
    suppression — and it is **unreachable in the current registry** (only
    ``sofr``/``iorb`` declare a non-zero tolerance and both are
    ``forward_looking=False``), so this is a **latent** silence, not a live
    leak. It is asserted as silence so that arming it later fails loudly: see
    O-101.
    """
    from macro_engine.data_layer.validation import validate_observations

    retrieve = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    # ONE day ahead against a tolerance of THREE: strictly inside the
    # tolerance, so this is a tolerated point, not a projection.
    points = [
        ObservationPoint(
            observation_date=date(2026, 9, 17),
            value=27000.0,
            series_id="gdp_potential",
            retrieved_at=retrieve,
        )
    ]
    report = validate_observations(
        points,
        series_id="gdp_potential",
        forward_looking=True,
        future_date_tolerance_days=3,
    )
    codes = [f.code for f in report.findings]

    assert "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK" not in codes, (
        "a tolerated point in a FORWARD-LOOKING series was reported as a "
        "same-day publication. That finding asserts the points are realised "
        "data, which is false for a projection series — a forward estimate "
        "would be published at INFO wearing a code that declares it observed."
    )
    # The measured cell is silence. Pinned explicitly: if a later change starts
    # disclosing this state, this assertion fails and whoever armed the cell
    # must decide the disclosure deliberately rather than inherit it (O-101).
    assert codes == [], (
        f"this cell is currently silent and is pinned as such; it now reports "
        f"{codes}. A tolerated point in a forward-looking series needs a "
        f"deliberate disclosure decision (O-101), not an inherited one."
    )
    assert not report.has_errors

    # The control: the SAME point in the SAME series, with forward_looking
    # flipped, MUST take the tolerated route and be disclosed. Without this the
    # assertions above cannot distinguish "the guard works" from "the branch is
    # dead" — a vacuous absence assertion.
    disclosed = validate_observations(
        points,
        series_id="gdp_potential",
        forward_looking=False,
        future_date_tolerance_days=3,
    )
    assert "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK" in [f.code for f in disclosed.findings], (
        "a not-forward-looking series with a point inside its declared "
        "tolerance must be disclosed as a same-day publication; if this fails "
        "the tolerated branch is unreachable and the absence assertion above "
        "is vacuous"
    )


def test_snapshot_build_reports_unverified_fields_rather_than_failing() -> None:
    """A series that cannot be verified is reported, never silently omitted.

    The builder must distinguish "the data is clean" from "the data is missing
    in five places". An omitted field with no flag is indistinguishable from a
    genuinely quiet series, which is how a broken mapping passes as a market
    observation.
    """
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    report = SnapshotBuildReport()
    report.requested = ["a", "b"]
    report.skipped_unverified = ["b"]
    report.succeeded = ["a"]
    report.observation_counts = {"a": 10}

    flags = report.as_flags()
    assert any("UNVERIFIED_SERIES_SKIPPED:b" in f for f in flags)
    assert not report.is_complete


def test_unknown_series_names_the_missing_source() -> None:
    """An undefined input must produce an actionable message."""
    from macro_engine.config import get_registry

    registry = get_registry()
    with pytest.raises(KeyError, match="no input may be invented"):
        registry.require_verified("some_series_nobody_defined")


def test_fractional_kelly_floor_is_enforced() -> None:
    """Section 22.6: a Kelly divisor below the floor must be rejected.

    Full-Kelly sizing assumes the probability estimates are exact, which they
    never are. This must fail at config load, not at sizing time.
    """
    from macro_engine.config import KellySettings

    payload: dict[str, Any] = {
        "fractional_divisor": {"value": 1.0, "calibration_status": "institutional_convention"},
        "min_fractional_divisor": {"value": 2.0, "calibration_status": "institutional_convention"},
        # D-057 added the argmax grid resolution. It is required, so the payload
        # must be COMPLETE for the floor validator to be what refuses — otherwise
        # this test would pass on a missing-field error and guard nothing.
        "grid_points": {"value": 100001, "calibration_status": "mechanical_rule"},
    }
    with pytest.raises(ValueError, match="Full-Kelly sizing is prohibited"):
        KellySettings.model_validate(payload)


def test_enabled_country_must_be_implemented() -> None:
    """Section 22.3: no function may claim genericity it has not earned."""
    from macro_engine.config import CountrySettings

    with pytest.raises(ValueError, match="genericity it has not earned"):
        CountrySettings.model_validate({"enabled": ["us", "de"], "implemented": ["us"]})


def test_bayesian_update_refuses_to_invent_likelihoods() -> None:
    """An empty likelihood table must raise, not default to an uninformative prior.

    A silent 0.5/0.5 default would render every Bayesian update a no-op while
    appearing to work — the single most dangerous failure mode available.
    """
    from macro_engine.config import get_settings

    with pytest.raises(NotImplementedError, match="Refusing to invent"):
        get_settings().bayesian.require_likelihoods("cpi_surprise")


# ---------------------------------------------------------------------------
# Contract-level tests
# ---------------------------------------------------------------------------


def test_confidence_is_computed_not_asserted() -> None:
    """compute_confidence reads its constants from config (Section 22.8)."""
    from macro_engine.config import get_settings
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    settings = get_settings()
    clean = compute_confidence(ConfidenceInputs(source_independence_count=3))
    base = float(settings.confidence.base.value)
    bonus = float(settings.confidence.source_independence_bonus.value)
    cap = float(settings.confidence.source_independence_bonus_cap.value)

    # Hand check: base + min(3 * bonus, cap).
    expected = round(base + min(3 * bonus, cap), 3)
    assert clean == expected

    # Every penalty present must reduce confidence below the clean case.
    worst = compute_confidence(
        ConfidenceInputs(
            data_quality_flags_present=True,
            is_heuristic_not_calibrated=True,
            depends_on_unobservable=True,
            source_independence_count=0,
        )
    )
    assert worst < clean
    assert worst >= float(settings.confidence.floor.value)


def test_confidence_never_reaches_certainty() -> None:
    """The ceiling is load-bearing: this system never claims near-certainty."""
    from macro_engine.config import get_settings
    from macro_engine.models.contracts import ConfidenceInputs, compute_confidence

    ceiling = float(get_settings().confidence.ceiling.value)
    perfect = compute_confidence(ConfidenceInputs(source_independence_count=1000))
    assert perfect == ceiling
    assert perfect < 1.0


def test_utc_now_is_timezone_aware() -> None:
    """A naive datetime makes the future-dating check ambiguous."""
    assert utc_now().tzinfo is not None


def test_model_result_rejects_out_of_range_confidence() -> None:
    """The confidence bound is enforced by the schema, not only by convention."""
    from pydantic import ValidationError

    from macro_engine.models.contracts import ModelResult

    with pytest.raises(ValidationError):
        ModelResult(
            model_name="x",
            country="us",
            as_of=utc_now(),
            value=1.0,
            confidence=1.5,
            interpretation="",
            context="",
            inputs_used=[],
        )


def test_model_result_accepts_every_documented_value_type() -> None:
    """The corrected union (Section 22.9) must accept all real return shapes."""
    from macro_engine.models.contracts import ModelResult

    for value in (1.0, 1, "text", True, {"a": 1}, [1, 2, 3], None):
        result = ModelResult(
            model_name="x",
            country="us",
            as_of=utc_now(),
            value=value,
            confidence=0.5,
            interpretation="",
            context="",
            inputs_used=[],
        )
        assert result.value == value


def test_client_config_defaults_come_from_settings() -> None:
    """No URL, port, timeout or retry count is hardcoded in Python."""
    from macro_engine.config import get_settings

    settings = get_settings()
    client = OpenBBClient()
    assert client.config.local_api_base_url == settings.openbb.base_url
    assert client.config.max_retries == settings.openbb.retries
    assert client.config.timeout_seconds == settings.openbb.timeout
    assert client.config.backoff_seconds == settings.openbb.backoff
    client.close()


def test_openbb_url_is_overridable_by_environment() -> None:
    """A deployment can redirect the client without editing a committed file."""
    from macro_engine.config import get_settings

    with patch.dict("os.environ", {"OPENBB_API_URL": "http://10.0.0.5:9999"}):
        get_settings.cache_clear()
        try:
            assert get_settings().openbb.base_url == "http://10.0.0.5:9999"
        finally:
            get_settings.cache_clear()


def test_missing_config_file_raises_rather_than_defaulting(tmp_path: Any) -> None:
    """Settings are never defaulted in code (Section 21.0 rule 3)."""
    from macro_engine.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(FileNotFoundError, match="Required config file missing"):
        get_settings(config_dir=tmp_path)
    get_settings.cache_clear()


def test_http_client_is_reused_across_calls() -> None:
    """Connection pooling is the reason for a shared client; assert it holds."""
    client = OpenBBClient()
    http = client._http
    assert client._http is http  # same object, not reconstructed per call
    client.close()


def test_close_releases_the_http_client() -> None:
    client = OpenBBClient()
    client.close()
    assert client._http.is_closed


def test_magicmock_is_not_used_for_validation_paths() -> None:
    """Guard: validation tests must exercise real logic, not mocks.

    A mocked validation report would let a regression in the real checks pass
    silently. This test asserts the report type is the real one.
    """
    report = validate_snapshot(make_snapshot())
    assert not isinstance(report, MagicMock)
    assert isinstance(report.findings, list)


# ---------------------------------------------------------------------------
# AUDIT-001 guards (2026-09-19 ground-up audit)
#
# `validate_snapshot` used to hardcode four tuples of series names covering 18
# of the registry's 45 entries, and it called `validate_observations` without
# passing the registry's declared `forward_looking` /
# `future_date_tolerance_days`. Two consequences, both measured live:
#
#   1. The build path read the registry and reported gdp_potential's 41 CBO
#      projections as ONE INFO; a standalone `validate_snapshot()` call
#      reported 30 ERRORs for the same snapshot. Same data, two verdicts, and
#      the ERROR verdict was the false one.
#   2. A newly registered series received NO validation at all unless a
#      developer also edited validation.py — a direct contradiction of the
#      Part B pluggability requirement.
#
# These tests fail if either regresses.
# ---------------------------------------------------------------------------


def test_validation_has_no_hardcoded_series_name_tuples() -> None:
    """The registry is the only source of which series get validated.

    Guard against a future contributor reinstating a hardcoded list: the
    validation module must not enumerate snapshot series by name. Checked by
    reading the source rather than by behaviour, because the failure mode is a
    *silent omission* — a series that is simply never validated produces no
    finding to assert on.
    """
    import re
    from pathlib import Path

    import macro_engine.data_layer.validation as validation_module

    source = Path(validation_module.__file__).read_text(encoding="utf-8")
    # Any tuple/list literal assigning two or more registry-style series names.
    offenders = re.findall(
        r"^[A-Z_]*SERIES[A-Z_]*\s*:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\([^)]*\)",
        source,
        flags=re.MULTILINE,
    )
    assert not offenders, (
        f"validation.py reintroduced hardcoded series tuples: {offenders}. "
        "Series membership must come from config/series_registry.yaml."
    )


def test_forward_looking_series_are_informational_not_errors() -> None:
    """A declared `forward_looking` series must never produce a future-date ERROR.

    ``gdp_potential`` is the canonical case: CBO publishes ~40 projections
    running a decade ahead, and they are REQUIRED for the output-gap
    calculation. Flagging them as corrupt data would train a reader to ignore
    the flag list entirely.
    """
    from macro_engine.config import get_registry

    entry = get_registry().series["gdp_potential"]
    assert entry.forward_looking is True, "gdp_potential must stay forward_looking"

    retrieve = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    projection = ObservationPoint(
        observation_date=date(2030, 1, 1),
        value=25000.0,
        series_id="gdp_potential",
        retrieved_at=retrieve,
    )
    report = validate_observations(
        [projection],
        series_id="gdp_potential",
        forward_looking=entry.forward_looking,
        future_date_tolerance_days=entry.future_date_tolerance_days,
    )
    codes = [f.code for f in report.findings]
    assert "FUTURE_OBSERVATION_DATE" not in codes
    assert "FORWARD_LOOKING_HORIZON" in codes
    assert not report.has_errors


def test_validate_snapshot_passes_registry_properties_through() -> None:
    """The standalone path must agree with the build path on the same snapshot.

    This is the direct regression guard for the two-verdicts defect: a
    forward-looking series placed in a snapshot must validate WITHOUT errors,
    because the registry declares it forward-looking. Before the fix this test
    failed with 30 ERRORs on exactly this input.
    """
    from macro_engine.config import get_registry

    entry = get_registry().series["gdp_potential"]
    assert entry.forward_looking is True

    retrieve = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    points = [
        ObservationPoint(
            observation_date=date(2026, 4, 1),
            value=24070.0,
            series_id="gdp_potential",
            retrieved_at=retrieve,
        ),
        ObservationPoint(
            observation_date=date(2030, 1, 1),
            value=25000.0,
            series_id="gdp_potential",
            retrieved_at=retrieve,
        ),
    ]
    report = validate_snapshot(make_snapshot(gdp_potential=points))
    assert not report.has_errors, [f.as_flag() for f in report.findings]


# ---------------------------------------------------------------------------
# Live snapshot-builder tests (Section 21.0 rule 1)
#
# "No function may be marked complete until it has been executed against real
# data from its real source. Unit tests prove the arithmetic; live execution
# proves the wiring, the units, the nulls, the frequency, and the sign
# conventions."
#
# The snapshot builder is the one component where that rule bites hardest: its
# entire job is wiring config -> registry -> provider, and every bug found in
# it so far has been a wiring bug invisible to synthetic tests.
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_snapshot_build_produces_a_coherent_economic_picture() -> None:
    """A full live snapshot: every field present, no flags, coherent economics.

    This is the strongest available integration check. It asserts not just
    that 21 series arrived, but that they are *mutually consistent*, which is
    the only way to catch a mis-mapped symbol whose individual value looks
    perfectly plausible on its own.
    """
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    snapshot, report = build_snapshot(country="us")

    assert report.failed == {}, f"fields failed to fetch: {report.failed}"
    assert report.skipped_unverified == []
    assert len(report.succeeded) == len(report.requested)

    # --- the curve arrived in full, with the schema field actually populated
    # (a registry/schema name mismatch previously dropped it silently)
    assert snapshot.yield_curve is not None
    assert len(snapshot.yield_curve.tenors) == 11
    assert snapshot.tips_yields is not None
    assert len(snapshot.tips_yields.tenors) == 5

    # --- nominal = real + deflator identity -------------------------------
    # The three national-accounts series are independent FRED symbols. If any
    # one were mis-mapped, this identity would break. It is the single most
    # valuable cross-check in the whole snapshot.
    #
    # GDP is quarterly, so year-over-year is 4 periods back. Observations are
    # stored oldest-first (the client sorts ascending), so [-1] is newest and
    # [-5] is the same quarter one year earlier.
    gdp_real = snapshot.gdp_real
    gdp_nominal = snapshot.gdp_nominal
    assert len(gdp_real) >= 5 and len(gdp_nominal) >= 5

    real_yoy = gdp_real[-1].value / gdp_real[-5].value - 1
    nominal_yoy = gdp_nominal[-1].value / gdp_nominal[-5].value - 1
    deflator_implied = (1 + nominal_yoy) / (1 + real_yoy) - 1
    assert -0.02 < deflator_implied < 0.10, (
        f"implied GDP deflator {deflator_implied:.4f} is not economically plausible; "
        f"(real YoY {real_yoy:+.4f}, nominal YoY {nominal_yoy:+.4f}) — the "
        "nominal/real GDP pair is likely mis-mapped"
    )

    # --- floor-system corridor --------------------------------------------
    # SOFR should sit inside (ON RRP rate, IORB]. A breached corridor means
    # either genuine plumbing stress or (far more likely) a wrong series.
    # This check is what caught RRPONTSYD being a volume rather than a rate.
    sofr = snapshot.sofr[-1].value
    iorb = snapshot.iorb[-1].value
    on_rrp = snapshot.on_rrp_rate[-1].value
    assert on_rrp < iorb, (
        f"ON RRP rate {on_rrp} must sit below IORB {iorb} — otherwise the series "
        "mapped to on_rrp_rate is not an administered rate at all"
    )
    assert abs(sofr - iorb) < 1.0, (
        f"SOFR {sofr} and IORB {iorb} diverge by more than 100bp; in normal "
        "conditions they track closely"
    )

    # --- direction of the curve -------------------------------------------
    tenors = snapshot.yield_curve.tenors
    assert tenors["10yr"] > tenors["3mo"], "curve is inverted or mis-ordered"

    # --- every series carries its provenance ------------------------------
    for field in ("cpi_headline", "sofr", "on_rrp_rate"):
        assert field in snapshot.field_sources, f"{field} has no recorded source"

    # --- the expected flags are the documented INFO-severity conditions -----
    # Three are legitimate and all three are INFO, never ERROR:
    #   FORWARD_LOOKING_HORIZON      — CBO GDPPOT carries ~10y of projections
    #   SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK — a daily series FRED published for
    #     the current UTC day while the clock is still on the previous one
    #     (D-030; `iorb`). Both are declared per-series in the registry, so a
    #     series that should NOT lead still raises ERROR. Anything else in the
    #     flag list is a genuine fault and must fail this test.
    #   RELEASE_TIMING_UNKNOWN is NOT tolerated here any more. It was, while the
    #     only release source was an intermittent edge-blocked route. The
    #     `publication_dates` source (each series' own `last_updated` metadata)
    #     now covers 42/42 registry symbols with 0 transport errors, so a build
    #     in which release timing is unknown is a REGRESSION and must fail
    #     loudly rather than be quietly tolerated. Asserted positively below.
    expected_info = (
        "FORWARD_LOOKING_HORIZON",
        "SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK",
    )
    unexpected = [f for f in snapshot.data_quality_flags if not any(e in f for e in expected_info)]
    assert unexpected == [], f"unexpected data-quality flags: {unexpected}"

    # A tolerated future-dated point must never be silently dropped from the
    # flag list either — the condition is disclosed, just not as a fault.
    assert not any("[ERROR]" in f and "iorb" in f for f in snapshot.data_quality_flags), (
        "iorb raised an ERROR flag; the declared tolerance is not being applied"
    )

    # Section 6, asserted POSITIVELY: release timing must now be KNOWN.
    #
    # This is the strongest available check that the release-date work is
    # actually live rather than merely present. It asserts the observable
    # consequence — `has_known_release_timing` is True on every point — which is
    # what a consumer depends on, rather than that some field was assigned.
    assert report.release_source == "publication_dates", (
        f"release timing came from {report.release_source!r}, not the exact "
        "metadata source; the primary provider is not wired or is failing"
    )
    assert not any("RELEASE_TIMING_UNKNOWN" in f for f in snapshot.data_quality_flags), (
        "release timing is unknown on a build where the metadata source is expected to answer"
    )

    # Every point of every populated scalar series must carry a release date,
    # and it must be a genuinely different fact from the observation date —
    # never a substituted value.
    checked = 0
    for field in ("cpi_headline", "sofr", "unemployment_rate"):
        for point in getattr(snapshot, field, []):
            assert point.release_datetime is not None, (
                f"{field} @{point.observation_date} has no release_datetime"
            )
            assert point.has_known_release_timing is True
            checked += 1
    assert checked > 0, "no observations were checked; the fields resolved empty"

    # Section 6: whether or not the calendar answered, no point may carry a
    # release date that was invented when the calendar did not supply one. The
    # two states must be consistent: known dates only when the read succeeded,
    # and None everywhere when it did not.
    #
    # The release date must also be a DIFFERENT fact from the observation date.
    # A source that returned the observation period as a publication time would
    # satisfy "not None" while being exactly the substitution Section 6
    # prohibits, so the inequality is asserted rather than assumed.
    for field in ("cpi_headline", "unemployment_rate"):
        for point in getattr(snapshot, field, []):
            assert point.release_datetime != datetime.combine(
                point.observation_date, time.min
            ).replace(tzinfo=point.release_datetime.tzinfo), (
                f"{field} @{point.observation_date}: release_datetime equals the "
                "observation date — a publication time was substituted"
            )


@pytest.mark.live
def test_live_snapshot_persists_and_round_trips() -> None:
    """The snapshot survives a write/read cycle through the parquet trail.

    Section 5.5's audit trail is only an audit trail if it round-trips. A
    lossy write would mean every historical comparison silently reads back a
    different picture than the one the thesis was built on.
    """
    from macro_engine.data_layer.persistence import (
        load_snapshot,
        long_frame_from_snapshot,
        write_snapshot,
    )
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    snapshot, report = build_snapshot(country="us")
    assert report.is_complete

    path = write_snapshot(snapshot)
    assert path is not None and path.exists(), "snapshot was not persisted"

    frame = long_frame_from_snapshot(snapshot)
    assert not frame.empty
    assert set(frame["field"].unique()) >= {"cpi_headline", "yield_curve", "sofr"}

    restored = load_snapshot(country="us")
    assert restored.country == snapshot.country
    assert len(restored.cpi_headline) == len(snapshot.cpi_headline)
    assert restored.cpi_headline[-1].value == snapshot.cpi_headline[-1].value

    # The curve must survive the round trip. This assertion found a genuine
    # write/read asymmetry: curves were persisted correctly but the read path
    # only rebuilt scalar and mapping fields, so every curve was silently
    # discarded on load.
    source_curve = snapshot.yield_curve
    source_tips = snapshot.tips_yields
    assert source_curve is not None and source_tips is not None

    restored = load_snapshot(country="us")
    assert restored.yield_curve is not None, "yield_curve did not survive persistence"
    assert restored.yield_curve.tenors == source_curve.tenors
    assert restored.tips_yields is not None
    assert restored.tips_yields.tenors == source_tips.tenors

    # data_quality_flags is deliberately NOT round-tripped: flags describe a
    # validation run against a point in time, and restoring them stale would
    # misrepresent the data as validated when it has not been re-checked.
    assert restored.data_quality_flags == []


def test_curve_survives_the_persistence_round_trip() -> None:
    """A curve written to the long frame must come back as a curve.

    Regression test for a genuine write/read asymmetry: ``long_frame_from_snapshot``
    emitted curve rows under ``field="yield_curve"``, but
    ``snapshot_from_long_frame`` only rebuilt the scalar and mapping fields. The
    curve was therefore persisted correctly and then silently discarded on every
    load — invisible until a round-trip assertion checked for it, because the
    write and read paths were each individually "working".

    Offline on purpose: this must run in CI, and it needs no network to prove the
    symmetry holds.
    """
    from macro_engine.data_layer.persistence import (
        long_frame_from_snapshot,
        snapshot_from_long_frame,
    )

    snapshot = make_snapshot()
    snapshot.yield_curve = YieldCurveSnapshot(
        as_of=date(2026, 9, 14),
        tenors={"2yr": 4.65, "5yr": 4.80, "10yr": 4.97, "30yr": 5.34},
    )
    snapshot.tips_yields = YieldCurveSnapshot(
        as_of=date(2026, 9, 14),
        tenors={"5yr": 2.40, "10yr": 2.60, "30yr": 3.05},
    )

    frame = long_frame_from_snapshot(snapshot)
    assert "yield_curve.10yr" in set(frame["series_id"]), "curve rows were not written"

    restored = snapshot_from_long_frame(frame)
    assert restored.yield_curve is not None, "yield_curve lost on load"
    assert restored.yield_curve.tenors == snapshot.yield_curve.tenors
    assert restored.tips_yields is not None
    assert restored.tips_yields.tenors == snapshot.tips_yields.tenors


def test_an_absent_store_is_distinguishable_from_an_empty_snapshot(tmp_path: Path) -> None:
    """``strict=True`` raises on an absent store; the default returns empty.

    The two states have genuinely different meanings and previously collapsed
    into one:

    * **absent store** — a deployment/checkout state. ``data/raw/`` is
      git-ignored, so a fresh clone has none. Nothing has been fetched yet.
    * **empty snapshot** — an audit fact. ``long_frame_from_snapshot`` writes a
      file even for a snapshot with no observations, on the grounds that "we
      fetched and got nothing" is itself worth recording.

    Because ``load_snapshot`` returned an empty snapshot for *both*, a caller
    writing ``except FileNotFoundError`` to detect "nothing persisted" caught
    nothing, seeded the empty snapshot, and then reported its own downstream
    failure as a data-layer defect. That is the mechanism behind the 22-failure
    clean-checkout run in ``tests/api_layer``. This test pins the distinction so
    the guard cannot silently become dead code again.
    """
    from macro_engine.data_layer.persistence import (
        SnapshotStoreEmptyError,
        has_persisted_snapshot,
        load_snapshot,
    )

    monkeypatch = pytest.MonkeyPatch()
    # Point the store at an empty directory. ``_raw_root`` resolves through
    # ``project_root() / settings.data.raw_store_path``, so patch the setting.
    monkeypatch.setattr(
        "macro_engine.data_layer.persistence.get_settings",
        lambda: SimpleNamespace(data=SimpleNamespace(raw_store_path=tmp_path)),
    )
    try:
        assert has_persisted_snapshot("us") is False

        with pytest.raises(SnapshotStoreEmptyError):
            load_snapshot("us", strict=True)

        # The permissive default still returns an empty snapshot, not an error:
        # callers that can legitimately act on "nothing yet" must keep working.
        permissive = load_snapshot("us")
        assert permissive.country == "us"
        assert permissive.cpi_headline == []
    finally:
        monkeypatch.undo()


def test_snapshot_store_empty_error_is_a_file_not_found_error() -> None:
    """The exception subclasses ``FileNotFoundError`` so existing handlers work.

    Callers throughout the codebase already guard persistence reads with
    ``except FileNotFoundError``. Making the new signal a sibling of that class
    rather than an unrelated one means those handlers become correct instead of
    needing to be found and updated one at a time.
    """
    from macro_engine.data_layer.persistence import SnapshotStoreEmptyError

    assert issubclass(SnapshotStoreEmptyError, FileNotFoundError)


def test_has_persisted_snapshot_agrees_with_what_the_loader_finds() -> None:
    """The predicate and the loader must not disagree.

    ``has_persisted_snapshot`` exists so callers can branch without catching an
    exception. If it ever returned ``False`` while a file was present, a caller
    would skip work it should have done — a silent under-fetch rather than a
    loud failure.
    """
    from macro_engine.data_layer.persistence import (
        has_persisted_snapshot,
        load_latest_snapshot_frame,
    )

    found = has_persisted_snapshot("us")
    frame_is_empty = load_latest_snapshot_frame("us").empty

    # Either there is no file (predicate False), or there is one (predicate True).
    # A stored file that is itself empty is possible — see the module docstring —
    # so the predicate must key on file existence, not on row count.
    if found:
        assert not frame_is_empty, (
            "has_persisted_snapshot reported a file but the loader read no rows; "
            "the repository may hold an empty parquet file"
        )


def test_local_api_liveness_does_not_treat_404_as_healthy() -> None:
    """A 404 must NOT be reported as an available server.

    The original probe hit ``/api/v1/health`` (which the OpenBB Platform API
    does not serve) and tested ``status_code < 500``, so a completely absent
    route made a running-but-misconfigured server look healthy. A liveness
    check that returns True for a non-existent endpoint is worse than none.
    """
    client = OpenBBClient(OpenBBClientConfig(use_local_api_first=True))

    not_found = MagicMock()
    not_found.status_code = 404
    with patch.object(client._http, "get", return_value=not_found):
        assert client.is_local_api_available() is False

    ok = MagicMock()
    ok.status_code = 200
    with patch.object(client._http, "get", return_value=ok):
        assert client.is_local_api_available() is True

    import httpx

    with patch.object(client._http, "get", side_effect=httpx.ConnectError("refused")):
        assert client.is_local_api_available() is False


# ---------------------------------------------------------------------------
# Phase 2 — live validation of the first implemented model (Section 21.2 Step 6)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_output_gap_is_computed_from_same_quarter_realised_data() -> None:
    """The first Phase 2 model, executed against real data.

    Section 21.2 Step 6 requires the function be run against its real sources,
    and the two defects this module now guards against were both **invisible to
    synthetic testing**:

    * O-7 — 41 of ``gdp_potential``'s 62 points are CBO projections to 2036, so
      a naive ``[-1]`` read computes the gap against the Q4 2036 figure.
    * D-009 — ``GDPPOT`` runs one quarter ahead of ``GDPC1``, so reading each
      series' own latest point pairs Q2 actual output against Q3 capacity and
      inverts the sign of the answer.

    So this test asserts the *shape of the correction*, not merely that a
    number came back: the pair must be same-quarter, the projections must be
    accounted for, and the resulting gap must sit inside the range its own
    recent history occupies.
    """
    from macro_engine.data_layer.snapshot_builder import build_snapshot
    from macro_engine.models.gdp_nowcast import output_gap_from_snapshot

    snapshot, report = build_snapshot(country="us", fields=["gdp_real", "gdp_potential"])
    assert report.failed == {}, f"fields failed to fetch: {report.failed}"

    result, series_report = output_gap_from_snapshot(snapshot)

    # --- the pairing correction actually applied (D-009) -------------------
    assert series_report.actual_date == series_report.potential_date, (
        "the output gap must be a same-quarter comparison; paired "
        f"{series_report.actual_date} actual against {series_report.potential_date} potential"
    )

    # --- the horizon correction actually applied (O-7) ---------------------
    assert series_report.withheld_forward_points > 0, (
        "gdp_potential carries CBO projections; if none were withheld the series shape "
        "has changed and this test's premise no longer holds"
    )
    assert series_report.withheld_horizon is not None
    assert int(series_report.withheld_horizon[:4]) > snapshot.as_of.year, (
        "the withheld horizon must be in the future"
    )
    # A realised-but-unpaired quarter is expected (GDPPOT's head start), and it
    # must be the normal single quarter rather than a stale-fetch signal.
    assert series_report.withheld_unpaired_points == 1
    assert series_report.staleness_quarters == 1

    # --- the values are the realised pair, not projections -----------------
    realised_potential = {
        p.observation_date: p.value
        for p in snapshot.gdp_potential
        if p.observation_date <= snapshot.as_of.date()
    }
    assert (
        series_report.potential_value == realised_potential[max(realised_potential)]
        or series_report.potential_value in realised_potential.values()
    )

    # --- the answer is economically coherent -------------------------------
    # Plausibility assertion, not a tautology: an output gap outside a few
    # percent of potential has never been observed in the post-war US without
    # a severe recession attached, and this snapshot's other signals (4.10%
    # unemployment, slowing payrolls) describe an economy near capacity.
    value = float(result.value)  # type: ignore[arg-type]
    assert -8.0 < value < 8.0, f"output gap {value}% is outside any plausible range"

    # --- the uncertainty is disclosed, not hidden --------------------------
    joined = " ".join(result.warnings)
    assert "ESTIMATE, not observed" in joined
    assert "withheld" in joined, "the projection truncation must be reported to the caller"
    assert "same" in joined or "BOTH series" in joined, (
        "the pairing correction must be reported, since it changes the answer"
    )

    # --- confidence reflects the unobservable input ------------------------
    assert 0.0 < result.confidence <= 0.5


# ---------------------------------------------------------------------------
# Section 6 of the economic-integrity directive: point-in-time provenance
# ---------------------------------------------------------------------------


class TestPointInTimeProvenance:
    """`ObservationPoint` must be able to say *when a value became public*.

    Section 6 requires the system to distinguish the four timestamps that
    matter to a point-in-time reasoning system: observation, release, vintage,
    and retrieval. Two of them are always present; the two release-side ones
    are modelled as **optional and defaulting to None**, because no route
    reachable from this installation returns them. The tests below pin that
    choice — in particular that None means UNKNOWN and is never quietly
    back-filled from `observation_date`, which is the exact fabrication
    Section 6 prohibits.
    """

    def test_release_and_vintage_default_to_unknown_not_to_observation(self) -> None:
        """Absent release timing must read as UNKNOWN, not as the observation date."""
        point = ObservationPoint(
            observation_date=date(2026, 8, 1),
            value=334.131,
            series_id="cpi_headline",
        )
        assert point.release_datetime is None
        assert point.vintage_datetime is None
        # The trap this guards: a system that sets release = observation would
        # make the CPI "public" on the 1st of a month it is actually published
        # mid-*following*-month. None is the honest value.
        assert point.release_datetime != datetime(2026, 8, 1, tzinfo=UTC)

    def test_has_known_release_timing_is_false_today_and_true_when_populated(self) -> None:
        """The predicate a consumer uses instead of assuming a release date."""
        unknown = ObservationPoint(
            observation_date=date(2026, 8, 1),
            value=1.0,
            series_id="cpi_headline",
        )
        assert unknown.has_known_release_timing is False

        known = ObservationPoint(
            observation_date=date(2026, 8, 1),
            value=1.0,
            series_id="cpi_headline",
            release_datetime=datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
            vintage_datetime=datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
        )
        assert known.has_known_release_timing is True

    def test_release_datetime_cannot_be_earlier_than_the_observation(self) -> None:
        """A value cannot be published before the period it describes exists.

        Not enforced by a validator — this asserts the *documented semantics*
        so that if a future edit back-fills release dates from the observation
        date by default, the equality is visible rather than silent. A release
        strictly *before* its observation date is a data error, and the schema
        allows it to be constructed so a caller that detects it can say so
        rather than have the model raise on genuinely odd (but real) revisions.
        """
        point = ObservationPoint(
            observation_date=date(2026, 8, 1),
            value=1.0,
            series_id="cpi_headline",
            release_datetime=datetime(2026, 9, 10, tzinfo=UTC),
        )
        assert point.release_datetime is not None
        assert point.release_datetime.date() > point.observation_date

    def test_decision_cutoff_defaults_to_none_meaning_now(self) -> None:
        """`as_of` (when assembled) and `decision_cutoff` (when knowable) differ."""
        snapshot = MacroDataSnapshot()
        assert snapshot.decision_cutoff is None
        # `as_of` is always populated; the cutoff is opt-in. Conflating the two
        # is what makes a replayed-backtest indistinguishable from a live run.
        assert snapshot.as_of is not None

    def test_decision_cutoff_can_be_set_independently_of_as_of(self) -> None:
        """A snapshot rebuilt from cache keeps the original decision's cutoff."""
        built = datetime(2026, 9, 19, 16, 28, tzinfo=UTC)
        decided = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
        snapshot = MacroDataSnapshot(as_of=built, decision_cutoff=decided)
        assert snapshot.as_of == built
        assert snapshot.decision_cutoff == decided
        assert snapshot.decision_cutoff < snapshot.as_of


def test_the_compact_timestamp_round_trips_through_the_real_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """D-134 — `parse_compact_timestamp` really IS `parquet_path_for`'s inverse.

    When this test was written, `parse_compact_timestamp` had **no production
    caller** (measured 2026-09-29) while its docstring claimed "Used by tools".
    It has since gained one: `load_snapshot` decodes the token to recover
    `as_of` for an EMPTY snapshot file (see the F-PER-001 test in
    test_phase1_data_layer), which is the only place that fact survives.
    Nothing else in the tree would therefore notice if the two halves of the
    token format drifted apart.

    This pins the round trip through the REAL writer rather than re-typing the
    format string — a test that re-typed `"%Y%m%dT%H%M%SZ"` would pass under any
    drift, which is the D-031 pinner failure.

    `parquet_path_for`'s docstring also CLAIMS the compaction makes
    lexicographic filename order match chronological order (what makes
    glob-and-sort the correct "latest" implementation). The second half asserts
    that claim instead of trusting it — the X-L1/X-L2 class, where a published
    statement was not in effect.
    """
    monkeypatch.setattr("macro_engine.data_layer.persistence._raw_root", lambda _country: tmp_path)

    stamp = datetime(2026, 9, 29, 14, 37, 5, tzinfo=UTC)
    # Named `compact`, not `token`: bandit's S105 reads any `token = "..."` as a
    # hardcoded credential, and this is a filename component.
    compact = parquet_path_for(MacroDataSnapshot(as_of=stamp)).stem
    assert compact == "20260929T143705Z", "the on-disk token format changed"
    assert parse_compact_timestamp(compact) == stamp

    earlier = parquet_path_for(
        MacroDataSnapshot(as_of=datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC))
    ).name
    later = parquet_path_for(
        MacroDataSnapshot(as_of=datetime(2026, 11, 5, 9, 0, 0, tzinfo=UTC))
    ).name
    assert earlier < later, (
        "the compaction no longer sorts chronologically, so glob-and-sort is wrong"
    )


# ---------------------------------------------------------------------------
# F-PER-001 — an empty snapshot must keep its recorded `as_of`
# ---------------------------------------------------------------------------
def test_an_empty_snapshot_round_trips_with_its_recorded_as_of(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F-PER-001: `as_of` used to be replaced by NOW on the way back.

    The write path deliberately persists an empty snapshot — "we fetched and got
    nothing" is an audit fact — but ``snapshot_from_long_frame`` returned a bare
    ``MacroDataSnapshot()`` for an empty frame, so the RECORDED instant became
    the LOAD instant. The filename was the only surviving copy of the truth,
    which is what ``parse_compact_timestamp`` now decodes.
    """
    from macro_engine.data_layer.persistence import (
        load_snapshot,
        write_snapshot,
    )

    monkeypatch.setattr("macro_engine.data_layer.persistence._raw_root", lambda _c: tmp_path)
    stamp = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)

    assert write_snapshot(MacroDataSnapshot(country="us", as_of=stamp)) is not None

    restored = load_snapshot("us")
    assert restored.as_of == stamp, "the recorded instant was replaced by the load instant"
    assert restored.country == "us"
    assert restored.cpi_headline == []


def test_an_empty_file_is_distinguishable_from_an_absent_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both read as "nothing", but only one has a recorded instant."""
    from macro_engine.data_layer.persistence import (
        has_persisted_snapshot,
        load_snapshot,
        write_snapshot,
    )

    monkeypatch.setattr("macro_engine.data_layer.persistence._raw_root", lambda _c: tmp_path)
    stamp = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)

    assert has_persisted_snapshot("us") is False
    assert load_snapshot("us").as_of != stamp  # absent store: nothing recorded

    write_snapshot(MacroDataSnapshot(country="us", as_of=stamp))
    assert has_persisted_snapshot("us") is True
    assert load_snapshot("us").as_of == stamp


def test_a_missing_store_echoes_the_requested_country(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A side-effect of the F-PER-001 restructure, pinned rather than left implicit.

    The old path went through ``snapshot_from_long_frame(empty_frame)``, which
    returned a bare ``MacroDataSnapshot()`` — so ``load_snapshot("de")`` on a
    missing store reported ``country="us"``. The restructured path returns
    ``MacroDataSnapshot(country=country)``, echoing what the caller asked for.
    That is the more consistent answer, and it is a behaviour change, so it gets
    a test instead of a mention.
    """
    from macro_engine.data_layer.persistence import load_snapshot

    monkeypatch.setattr("macro_engine.data_layer.persistence._raw_root", lambda _c: tmp_path)
    assert load_snapshot("de").country == "de"


def test_the_empty_frame_fallbacks_never_override_a_populated_frame() -> None:
    """The new parameters are consulted ONLY when there is no row to read."""
    from macro_engine.data_layer.persistence import (
        long_frame_from_snapshot,
        snapshot_from_long_frame,
    )

    stamp = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)
    frame = long_frame_from_snapshot(
        MacroDataSnapshot(
            country="us",
            as_of=stamp,
            cpi_headline=[
                ObservationPoint(
                    observation_date=date(2026, 9, 1),
                    value=300.0,
                    series_id="cpi_headline",
                    retrieved_at=stamp,
                )
            ],
        )
    )
    restored = snapshot_from_long_frame(
        frame, empty_country="de", empty_as_of=datetime(1999, 1, 1, tzinfo=UTC)
    )
    assert restored.country == "us"  # the frame wins
    assert restored.as_of == stamp


# ---------------------------------------------------------------------------
# D3 — the declared-but-unwired mapping fields must be DISCLOSED
# ---------------------------------------------------------------------------
def test_the_declared_but_unwired_mapping_fields_are_named_in_the_report() -> None:
    """An empty mapping must be distinguishable from "no data this run".

    ``fx_spot``, ``commodity_spot`` and ``equity_index`` are declared on the
    schema, validated, and round-tripped by persistence — but they are dicts of
    series rather than series, so the builder's one-attribute-per-registry-entry
    loop can never fill them. Nothing is requested and nothing fails, so before
    this fix they appeared NOWHERE: not in ``requested``, ``failed`` or
    ``skipped_unverified``. An empty dict therefore read exactly like a run that
    fetched nothing.

    This is the ``gdi`` class the project already hit once — a field declared in
    the registry, the schema, persistence AND the dashboard, and omitted from
    the one list the builder iterates, so it could never appear.
    """
    from macro_engine.data_layer import persistence
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    report = SnapshotBuildReport()
    report.requested = ["gdp_real"]
    report.succeeded = ["gdp_real"]
    report.observation_counts = {"gdp_real": 10}
    report.declared_not_wired = sorted(persistence.MAPPING_SERIES_FIELDS)

    flags = report.as_flags()
    for field in persistence.MAPPING_SERIES_FIELDS:
        assert any(f.startswith(f"DECLARED_NOT_WIRED:{field}:") for f in flags), field
    # The flag must say WHY, so a reader does not go looking for a provider fault.
    assert any("can never populate it" in f for f in flags)


def test_the_builder_itself_records_the_unwired_mapping_fields() -> None:
    """The POPULATION, not just the rendering — this is the half that was missing.

    An earlier version of this test built a ``SnapshotBuildReport`` by hand and
    checked ``as_flags``. That passes even if ``build_snapshot`` never populates
    ``declared_not_wired`` — measured: replacing the population with
    ``declared_not_wired = []`` left the hand-built test GREEN. So this calls the
    real builder with an injected client (no network needed: the field list is
    computed BEFORE the fetch loop, so a client that cannot fetch still proves
    the population ran).
    """
    from macro_engine.data_layer import persistence
    from macro_engine.data_layer.release_calendar import ReleaseDateIndex
    from macro_engine.data_layer.snapshot_builder import build_snapshot

    class _NoNetwork:
        """Fails every fetch; irrelevant to the assertion, which is about wiring."""

        def __getattr__(self, _name: str) -> object:
            def _boom(*_a: object, **_k: object) -> object:
                raise RuntimeError("no network in this test")

            return _boom

    # An empty release index is passed so the PRE-LOOP release resolution does
    # not touch the client — otherwise its RuntimeError escapes the per-field
    # try/except and the test fails for the wrong reason (measured: it did).
    _snapshot, report = build_snapshot(
        country="us",
        fields=["gdp_real"],
        # The stub is deliberately not an OpenBBClient: the assertion is about
        # wiring, and any object that raises on every fetch proves the point.
        client=cast("OpenBBClient", _NoNetwork()),
        release_index=ReleaseDateIndex(),
    )
    assert report.declared_not_wired == sorted(persistence.MAPPING_SERIES_FIELDS)


def test_the_unwired_fields_do_not_make_a_build_incomplete() -> None:
    """By design these are Tier-5 placeholders, not failures.

    D-137 calls them ``legitimate, not a defect`` (schema-only placeholders for
    Tier-5 multi-asset, US-only in Phases 0-4). ``PHASE5_DEFERRED.md`` §2.5.1
    calls the omission ``unfinished wiring``. Both can hold at once: the
    DECLARATION is by design, and the ABSENCE OF WIRING must be visible. So the
    flag is emitted without making every build report itself incomplete — which
    would be the opposite error, crying failure on a state the project chose.
    """
    from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport

    report = SnapshotBuildReport()
    report.declared_not_wired = ["fx_spot"]
    assert report.is_complete is True
    assert any(f.startswith("DECLARED_NOT_WIRED:fx_spot:") for f in report.as_flags())
