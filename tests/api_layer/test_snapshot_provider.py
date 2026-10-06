"""``api_layer/snapshot_provider.py`` — the cache, the age, and the build failures.

``tests/api_layer/`` held only ``test_snapshot_provenance.py`` (the F-SNAP-001
disclosure guards), so the module's actual behaviour — the cache re-stamping, the
age floor, the three build-failure translations — was untested.

Two live defects were found BY this review and are pinned here:

* ``F-SNAP-002`` — ``_build``'s broad ``except Exception`` produced a message
  asserting "This is a data-source failure" for ANY exception, including a bug in
  the builder.
* ``F-SNAP-003`` — ``_build`` read the report duck-typed with ``[]`` defaults, so
  a report whose shape changed would silently SKIP the "did anything actually
  fetch?" guard and publish a wholly-empty snapshot as an available one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from macro_engine.api_layer import snapshot_provider as sp
from macro_engine.data_layer.schemas import MacroDataSnapshot
from macro_engine.data_layer.snapshot_builder import SnapshotBuildReport
from macro_engine.models.contracts import utc_now

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _snapshot(as_of: datetime = NOW, *, flags: list[str] | None = None) -> MacroDataSnapshot:
    return MacroDataSnapshot(as_of=as_of, data_quality_flags=flags or [])


def _report(*, requested: list[str], succeeded: list[str], failed: dict[str, str]) -> object:
    report = SnapshotBuildReport()
    report.requested = requested
    report.succeeded = succeeded
    report.failed = failed
    return report


def _stub_build(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    """Patch the lazily-imported ``build_snapshot`` at its own module."""
    from macro_engine.data_layer import snapshot_builder

    def fake(*, country: str) -> object:
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(snapshot_builder, "build_snapshot", fake)


def _stub_settings(
    monkeypatch: pytest.MonkeyPatch, *, memoize: bool = True, max_age: float = 24.0
) -> None:
    """A settings stub, because the real ``get_settings`` is ``lru_cache``d."""
    monkeypatch.setattr(
        sp,
        "get_settings",
        lambda: SimpleNamespace(
            api=SimpleNamespace(memoize_snapshots=memoize, snapshot_max_age_hours=max_age)
        ),
    )


@pytest.fixture(autouse=True)
def _clean_cache() -> object:
    sp.reset_cache()
    yield
    sp.reset_cache()


# ---------------------------------------------------------------------------
# the age, and its floor
# ---------------------------------------------------------------------------


def test_age_hours_floors_at_zero() -> None:
    """A clock skew ahead of ``now`` must not produce a negative age.

    A negative age silently passes ``age > max_age``, which is the exact
    comparison the staleness disclosure is built on.
    """
    assert sp._age_hours(NOW, NOW) == 0.0
    assert sp._age_hours(NOW + timedelta(hours=5), NOW) == 0.0
    assert sp._age_hours(NOW - timedelta(hours=30), NOW) == pytest.approx(30.0)


def test_age_hours_accepts_a_naive_timestamp() -> None:
    naive = datetime(2026, 10, 6, 11, 0)  # noqa: DTZ001 - deliberately naive
    assert sp._age_hours(naive, NOW) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# the build failures
# ---------------------------------------------------------------------------


def test_a_not_implemented_country_is_re_raised_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 22.3: a country-label failure is the caller's, and the API maps it to 501."""
    _stub_build(monkeypatch, NotImplementedError("only 'us' is implemented"))
    with pytest.raises(NotImplementedError):
        sp._build(country="de", now=NOW)


def test_an_unexpected_exception_names_its_type_and_does_not_claim_a_source_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-SNAP-002) The message asserted a cause the broad catch cannot know.

    A ``TypeError`` inside the builder is a BUG, not a provider outage — and the
    old message told the caller "This is a data-source failure", whose remedy
    (retry or inspect the provider) is the wrong one.
    """
    _stub_build(monkeypatch, TypeError("unsupported operand"))
    with pytest.raises(sp.SnapshotUnavailableError) as excinfo:
        sp._build(country="us", now=NOW)
    message = str(excinfo.value)
    assert "TypeError" in message  # the type is named, so the two can be told apart
    assert "bug in the builder" in message
    assert "This is a data-source failure" not in message


def test_a_report_without_the_expected_shape_is_refused_rather_than_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-SNAP-003) The duck-typed ``[]`` defaults silently disabled the guard.

    With ``requested=[]`` the emptiness check below is skipped AND the provenance
    shows no failures, so a wholly-empty snapshot would be served as an available
    one with a clean disclosure — the module's central failure mode.
    """
    _stub_build(monkeypatch, (_snapshot(), SimpleNamespace(no_shape="at all")))
    with pytest.raises(sp.SnapshotUnavailableError, match="carries no `requested`/`succeeded`"):
        sp._build(country="us", now=NOW)


def test_a_build_that_fetched_nothing_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _report(requested=["a", "b"], succeeded=[], failed={"a": "x", "b": "y"})
    _stub_build(monkeypatch, (_snapshot(), report))
    with pytest.raises(sp.SnapshotUnavailableError, match="fetched no usable series"):
        sp._build(country="us", now=NOW)


def test_a_partial_build_does_not_raise_and_the_provenance_carries_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snapshot missing four series is still a real snapshot (the documented call)."""
    report = _report(requested=["a", "b"], succeeded=["a"], failed={"b": "provider timeout"})
    _stub_build(monkeypatch, (_snapshot(), report))
    _snapshot_obj, provenance = sp._build(country="us", now=NOW)
    assert provenance.failed_fields == {"b": "provider timeout"}
    assert provenance.succeeded_fields == ["a"]
    assert any("SNAPSHOT PARTIAL" in w for w in provenance.warnings())


# ---------------------------------------------------------------------------
# the cache, and the re-stamping
# ---------------------------------------------------------------------------


def test_a_cached_serve_re_stamps_the_age(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored provenance describes the BUILD; a served one must describe the SERVE.

    Reusing it would freeze the age at zero forever, which is the "stale served
    as fresh" failure the module exists to prevent.
    """
    _stub_settings(monkeypatch)
    built_at = utc_now() - timedelta(hours=30)
    report = _report(requested=["a"], succeeded=["a"], failed={})
    _stub_build(monkeypatch, (_snapshot(built_at), report))

    first_snapshot, first = sp.get_snapshot()
    assert first.from_cache is False

    second_snapshot, second = sp.get_snapshot()
    assert second_snapshot is first_snapshot  # the same cached object
    assert second.from_cache is True
    assert second.age_hours >= 29.9  # re-aged, not frozen at the build
    assert second.age_exceeds_max is True  # 30h > the 24h limit
    assert "SNAPSHOT REUSED" in " ".join(second.warnings())


def test_force_refresh_bypasses_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch)
    report = _report(requested=["a"], succeeded=["a"], failed={})
    _stub_build(monkeypatch, (_snapshot(), report))
    sp.get_snapshot()
    _, refreshed = sp.get_snapshot(force_refresh=True)
    assert refreshed.from_cache is False


def test_memoize_off_never_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch, memoize=False)
    report = _report(requested=["a"], succeeded=["a"], failed={})
    _stub_build(monkeypatch, (_snapshot(), report))
    sp.get_snapshot()
    assert sp.cached_snapshot_provenance() is None


def test_cached_provenance_is_none_when_nothing_is_cached() -> None:
    assert sp.cached_snapshot_provenance() is None


def test_cached_provenance_re_ages_without_building(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/health`` asks "is anything cached, and is it stale" without building."""
    _stub_settings(monkeypatch)
    report = _report(requested=["a"], succeeded=["a"], failed={})
    _stub_build(monkeypatch, (_snapshot(utc_now() - timedelta(hours=48)), report))
    sp.get_snapshot()

    provenance = sp.cached_snapshot_provenance()
    assert provenance is not None
    assert provenance.from_cache is True
    assert provenance.age_hours >= 47.9
    assert provenance.age_exceeds_max is True


def test_reset_cache_drops_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch)
    report = _report(requested=["a"], succeeded=["a"], failed={})
    _stub_build(monkeypatch, (_snapshot(), report))
    sp.get_snapshot()
    sp.reset_cache()
    assert sp.cached_snapshot_provenance() is None


# ---------------------------------------------------------------------------
# the disclosure order
# ---------------------------------------------------------------------------


def test_the_disclosure_lines_come_in_severity_order() -> None:
    """Partial first, then skipped, stale, flagged, reused — worst news first."""
    provenance = sp.SnapshotProvenance(
        country="us",
        as_of=NOW,
        generated_at=NOW,
        age_hours=30.0,
        age_exceeds_max=True,
        max_age_hours=24.0,
        from_cache=True,
        requested_fields=["a", "b"],
        succeeded_fields=["a"],
        failed_fields={"b": "timeout"},
        skipped_unverified_fields=["c"],
        data_quality_flag_count=2,
    )
    prefixes = [w.split(":")[0] for w in provenance.warnings()]
    assert prefixes == [
        "SNAPSHOT PARTIAL",
        "SNAPSHOT SKIPPED",
        "SNAPSHOT STALE",
        "SNAPSHOT FLAGGED",
        "SNAPSHOT REUSED",
    ]


def test_a_clean_fresh_snapshot_emits_nothing() -> None:
    provenance = sp.SnapshotProvenance(
        country="us",
        as_of=NOW,
        generated_at=NOW,
        age_hours=0.5,
        age_exceeds_max=False,
        max_age_hours=24.0,
        from_cache=False,
        data_quality_flag_count=0,
    )
    assert provenance.warnings() == []
