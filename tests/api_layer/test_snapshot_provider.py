"""The snapshot provider's own contract — cache, age, and build outcome (D-070).

Why this file exists
--------------------
``test_routes.py`` seeds the provider's module-level cache directly and asserts
the *routes*' behaviour. That is the right split for the endpoints, and it left
the provider itself untested: the D-070 mutation sweep recorded **five
survivors** in ``snapshot_provider.py`` and ``config.py`` — ``M9.1`` (the age is
not re-stamped), ``M9.2`` (no floor on the age), ``M9.3`` (an empty build does not
raise), ``M9.5`` (``loopback_only`` is hardcoded) and ``M10.2`` (the version
string is duplicated) — every one of which is invisible to a test that writes
``_CACHE`` by hand.

That is the sweep doing its job: five survivors with no proof are five real
coverage gaps, and the honest response is to close them, not to label them inert.

The two failure modes this file is built around
-----------------------------------------------
Both are **silent**, which is why they need a test rather than a review:

1. **A cached answer with no age attached is a claim about the present made from
   the past** (the D-069 lesson, in the cache position). The payload is
   byte-identical whether the age is 0.1h or 30h, so nothing but an explicit
   assertion can see the difference.
2. **A build that fetched nothing is not an empty snapshot.** An empty snapshot
   flows downstream and produces a precise-looking ``OrchestrationError`` naming
   a *series* — which blames the data for what is a provider fact.

What this file CANNOT establish
-------------------------------
Whether a real ``build_snapshot`` produces the outcome the report claims. That is
``scripts/live_api_check.py``'s job (Section 21.0's split). Everything here drives
``_build`` through a **stubbed** report, so the prov, the guards and the
translation are exercised without a provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from macro_engine.api_layer import snapshot_provider
from macro_engine.api_layer.snapshot_provider import (
    SnapshotProvenance,
    SnapshotUnavailableError,
    cached_snapshot_provenance,
    get_snapshot,
    reset_cache,
)
from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """The cache is module-level by design, so every test starts empty."""
    reset_cache()


def _snapshot(*, as_of: datetime, country: str = "us") -> MacroDataSnapshot:
    """A minimal snapshot whose only interesting field is its timestamp."""
    return MacroDataSnapshot(
        country=country,
        as_of=as_of,
        gdp_real=[
            ObservationPoint(observation_date=as_of.date(), value=23000.0, series_id="gdp_real")
        ],
    )


def _report(
    *,
    requested: list[str] | None = None,
    succeeded: list[str] | None = None,
    failed: dict[str, str] | None = None,
    skipped: list[str] | None = None,
) -> SimpleNamespace:
    """The shape ``_provenance_from_report`` reads, duck-typed as it reads it."""
    return SimpleNamespace(
        requested=requested if requested is not None else ["gdp_real"],
        succeeded=succeeded if succeeded is not None else ["gdp_real"],
        failed=failed if failed is not None else {},
        skipped_unverified=skipped if skipped is not None else [],
    )


def _stub_build(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot: MacroDataSnapshot,
    report: SimpleNamespace,
) -> None:
    """Replace ``build_snapshot`` as ``_build`` imports it.

    ``_build`` imports the builder *inside the function* (so the app stays
    importable without OpenBB), which means the patch target is the module the
    import resolves against — ``macro_engine.data_layer.snapshot_builder`` — not
    ``snapshot_provider``.
    """
    import macro_engine.data_layer.snapshot_builder as builder

    def _fake(*, country: str, **_kwargs: object) -> tuple[MacroDataSnapshot, object]:
        del country
        return snapshot, report

    monkeypatch.setattr(builder, "build_snapshot", _fake)


# ---------------------------------------------------------------------------
# 1. The age — the disclosure this module exists for
# ---------------------------------------------------------------------------


def test_the_age_is_re_stamped_on_every_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``M9.1``'s kill: a cached entry must not freeze its build-time age.

    The mutant serves ``cached.provenance.age_hours`` — the age the entry had
    when it was *written*, which is zero by construction, for ever. The payload
    is byte-identical to the honest one, so only an explicit assertion can see
    it.

    The clock is moved by building with a **backdated as_of** rather than by
    patching ``utc_now``: the snapshot's own timestamp is the input the age is
    computed from, so backdating it is the realistic way to age a cache entry and
    patches nothing this test does not own.
    """
    built_at = datetime.now(UTC) - timedelta(hours=9)
    _stub_build(
        monkeypatch,
        snapshot=_snapshot(as_of=built_at),
        report=_report(),
    )

    snapshot, first = get_snapshot("us")
    assert first.from_cache is False
    assert first.age_hours == pytest.approx(9.0, abs=5e-2), (
        "a snapshot built 9 hours ago must report an age near 9h on the call "
        "that built it — the age is measured against the snapshot's own as_of, "
        "not against the moment the process started."
    )

    _again, second = get_snapshot("us")
    assert second.from_cache is True
    assert second.age_hours == pytest.approx(first.age_hours, abs=1e-3), (
        f"the cached serve reported age {second.age_hours}h against the fresh "
        f"build's {first.age_hours}h. M9.1 serves the STORED provenance, whose "
        f"age was zero when it was written — so a day-old snapshot reports zero "
        f"hours, for ever."
    )
    assert second.age_hours > 0.0, (
        "a cached serve reported exactly zero age, which is the mutant's "
        "signature: the entry was written with age 0 and the value was reused."
    )
    # The stored provenance is untouched; only the SERVED one is re-stamped.
    entry = snapshot_provider._CACHE["us"]
    assert entry.provenance.age_hours == pytest.approx(9.0, abs=5e-2)
    assert entry.snapshot is snapshot


def test_the_served_age_is_a_fresh_computation_not_a_stored_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stronger form: the served age must track a *changing* clock.

    ``M9.1`` stores the age at write time. This test makes the stored value
    *deliberately wrong* — 100 hours, a number nothing would compute — and
    requires the served provenance to ignore it entirely. A mutant that serves
    the stored value passes the test above only if it happens to write zero; this
    one cannot be passed by any stored value.
    """
    now = datetime.now(UTC)
    snapshot = _snapshot(as_of=now - timedelta(hours=2))
    poisoned = SnapshotProvenance(
        country="us",
        as_of=snapshot.as_of,
        generated_at=now,
        age_hours=100.0,  # nothing would compute this
        age_exceeds_max=True,
        max_age_hours=24.0,
        from_cache=False,
        data_quality_flag_count=0,
    )
    snapshot_provider._CACHE["us"] = snapshot_provider._CacheEntry(
        snapshot=snapshot, provenance=poisoned
    )

    _snapshot_out, served = get_snapshot("us")

    assert served.age_hours == pytest.approx(2.0, abs=5e-2), (
        f"the cached serve reported age {served.age_hours}h against a stored "
        f"100.0h and a true 2h. The served age must be RECOMPUTED from the "
        f"snapshot's as_of, never read off the entry."
    )
    assert served.age_exceeds_max is False, (
        "age_exceeds_max must be recomputed alongside the age; serving the "
        "stored True reports a fresh snapshot as stale."
    )


def test_the_age_is_floored_at_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """``M9.2``'s kill: a negative age passes every ``age > max`` check.

    A clock skew that puts ``as_of`` slightly ahead of ``now`` yields a negative
    age — and a negative number is below every threshold, so the staleness
    disclosure silently reports "not stale" for a snapshot from the future. That
    is the exact comparison the disclosure is built on, disabled by a sign.
    """
    ahead = datetime.now(UTC) + timedelta(hours=3)
    _stub_build(
        monkeypatch,
        snapshot=_snapshot(as_of=ahead),
        report=_report(),
    )

    _snapshot_out, provenance = get_snapshot("us")

    assert provenance.age_hours == 0.0, (
        f"a snapshot timestamped 3h in the FUTURE reported an age of "
        f"{provenance.age_hours}. Without the floor it is negative, and a "
        f"negative age is below every max_age threshold."
    )
    assert provenance.age_hours >= 0.0
    assert provenance.age_exceeds_max is False


def test_a_stale_snapshot_is_disclosed_rather_than_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale is REPORTED, not refused — and the warning names the age.

    Refusing would make a day-old snapshot unusable, when the honest thing is to
    serve it with its age attached. The distinction matters because the caller's
    remedy differs: a refusal means "retry", a disclosure means "decide whether
    yesterday's read is good enough".
    """
    old = datetime.now(UTC) - timedelta(hours=48)
    _stub_build(
        monkeypatch,
        snapshot=_snapshot(as_of=old),
        report=_report(),
    )

    _snapshot_out, provenance = get_snapshot("us")

    assert provenance.age_exceeds_max is True
    warnings = provenance.warnings()
    assert any("SNAPSHOT STALE" in w for w in warnings), (
        f"a 48h-old snapshot against a 24h limit produced no STALE warning: {warnings}"
    )
    stale = next(w for w in warnings if "SNAPSHOT STALE" in w)
    assert f"{provenance.age_hours:.1f}h" in stale, (
        "the STALE warning must carry the measured age, or the reader cannot judge how stale."
    )


def test_cached_snapshot_provenance_reports_the_age_without_building(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/health``'s cheap path: a real age, no build.

    The hazard is the obvious implementation — return the stored provenance —
    which reports a day-old entry as zero hours old, because it was zero hours
    old when it was written. The function exists to make ``/health`` answerable
    without paying the build cost, and it must not pay for that with a false age.
    """
    built_at = datetime.now(UTC) - timedelta(hours=6)
    _stub_build(
        monkeypatch,
        snapshot=_snapshot(as_of=built_at),
        report=_report(),
    )
    get_snapshot("us")

    cached = cached_snapshot_provenance("us")

    assert cached is not None
    assert cached.from_cache is True
    assert cached.age_hours == pytest.approx(6.0, abs=5e-2)
    assert cached.generated_at > built_at, (
        "generated_at must be the moment of THIS serve, not of the build."
    )


def test_cached_snapshot_provenance_is_none_before_anything_is_built() -> None:
    """``None`` rather than a zero-age stub: 'nothing cached' is not 'fresh'."""
    assert cached_snapshot_provenance("us") is None


def test_a_narrow_max_age_can_be_set_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``snapshot_max_age_hours`` is read from config, not hardcoded.

    The boundary is the interesting part: a one-hour snapshot against a
    one-hour limit must be judged by the measured value, not by a literal the
    module remembered. The setting is patched on the cached ``Settings`` object
    the whole tree shares, so the assertion is against the same value the code
    reads.
    """
    from macro_engine.config import get_settings

    built_at = datetime.now(UTC) - timedelta(hours=3)
    _stub_build(
        monkeypatch,
        snapshot=_snapshot(as_of=built_at),
        report=_report(),
    )

    settings = get_settings()
    original = settings.api.snapshot_max_age_hours_value
    monkeypatch.setattr(
        settings.api,
        "snapshot_max_age_hours_value",
        original.model_copy(update={"value": 1.0}),
    )

    _snapshot_out, provenance = get_snapshot("us")

    assert provenance.max_age_hours == 1.0
    assert provenance.age_exceeds_max is True, (
        "a 3h-old snapshot against a configured 1h limit must be reported stale; "
        "a hardcoded 24 would call it fresh."
    )


# ---------------------------------------------------------------------------
# 2. The build outcome — partial is not failure, empty IS
# ---------------------------------------------------------------------------


def test_a_partial_build_does_not_raise_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snapshot missing fields is still a snapshot; the provenance is the report.

    Deliberate, and the same judgement ``output_gap_from_snapshot`` makes: the
    orchestration will refuse at the specific field it needs. Raising here would
    replace a precise refusal ("``pce_core`` is empty") with a vague one ("the
    snapshot is unavailable").
    """
    now = datetime.now(UTC)
    _stub_build(
        monkeypatch,
        snapshot=_snapshot(as_of=now),
        report=_report(
            requested=["gdp_real", "pce_core", "iorb"],
            succeeded=["gdp_real"],
            failed={"pce_core": "no data", "iorb": "timeout"},
        ),
    )

    _snapshot_out, provenance = get_snapshot("us")

    assert len(provenance.failed_fields) == 2
    warnings = provenance.warnings()
    assert any("SNAPSHOT PARTIAL" in w for w in warnings), (
        f"a build with 2 of 3 fields failed produced no PARTIAL warning: {warnings}"
    )
    partial = next(w for w in warnings if "SNAPSHOT PARTIAL" in w)
    assert "2 of 3" in partial, (
        "the PARTIAL warning must carry both counts, or the reader cannot tell a "
        "nearly-complete snapshot from a half-empty one."
    )


def test_a_wholly_failed_build_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``M9.3``'s kill: nothing fetched at all is a provider failure.

    Removing the guard lets an empty snapshot flow downstream, where the
    orchestration refuses with ``OrchestrationError`` naming a *series* — precise
    in form, wrong in substance: it blames the data for what is a provider fact,
    and the caller inspects the wrong thing.
    """
    now = datetime.now(UTC)
    _stub_build(
        monkeypatch,
        snapshot=_snapshot(as_of=now),
        report=_report(
            requested=["gdp_real", "pce_core"],
            succeeded=[],
            failed={"gdp_real": "no data", "pce_core": "no data"},
        ),
    )

    with pytest.raises(SnapshotUnavailableError) as caught:
        get_snapshot("us")

    message = str(caught.value)
    assert "fetched no usable series" in message
    assert "gdp_real" in message and "pce_core" in message, (
        "the failure must name the fields that failed, so the caller can inspect "
        "the provider rather than the series."
    )


def test_a_raising_build_becomes_snapshot_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception from the provider is translated, and the cause is preserved.

    ``from exc`` matters: without it the traceback ends at ``_build`` and the
    OpenBB error — the only thing that says *why* the provider failed — is lost.
    """
    import macro_engine.data_layer.snapshot_builder as builder

    def _boom(*, country: str, **_kwargs: object) -> object:
        raise ConnectionError(f"provider refused the connection for {country}")

    monkeypatch.setattr(builder, "build_snapshot", _boom)

    with pytest.raises(SnapshotUnavailableError) as caught:
        get_snapshot("us")

    assert isinstance(caught.value.__cause__, ConnectionError), (
        "the original provider exception must survive as __cause__, or the "
        "diagnosis is lost at the translation boundary."
    )
    assert "Section 16.3" in str(caught.value), (
        "the message must state that this is NOT a no-trade verdict — the "
        "distinction the API's 502 depends on."
    )


def test_an_unimplemented_country_is_not_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``NotImplementedError`` must survive so the API can map it to 501.

    ``_build`` catches ``Exception``; if the country branch were not re-raised
    untouched, a 501 would become a 502 and every unimplemented country would be
    reported as a provider outage.
    """
    import macro_engine.data_layer.snapshot_builder as builder

    def _not_implemented(*, country: str, **_kwargs: object) -> object:
        raise NotImplementedError(f"country {country!r} is not implemented")

    monkeypatch.setattr(builder, "build_snapshot", _not_implemented)

    with pytest.raises(NotImplementedError):
        get_snapshot("de")


def test_a_failed_build_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure must not poison the cache for ``snapshot_max_age_hours``.

    The failure raises before the cache write, so the next call retries. Caching
    an unavailable result would turn one provider hiccup into a 24-hour outage —
    and the caller's only remedy (``force_refresh``) is not something a Workspace
    UI would ever send.
    """
    import macro_engine.data_layer.snapshot_builder as builder

    monkeypatch.setattr(
        builder,
        "build_snapshot",
        lambda *, country, **kw: (_ for _ in ()).throw(ConnectionError("down")),
    )

    with pytest.raises(SnapshotUnavailableError):
        get_snapshot("us")

    assert snapshot_provider._CACHE == {}, "a failed build was written to the cache"


def test_force_refresh_bypasses_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's escape hatch: rebuild without restarting the service."""
    now = datetime.now(UTC)
    calls: list[str] = []
    import macro_engine.data_layer.snapshot_builder as builder

    def _fake(*, country: str, **_kwargs: object) -> tuple[MacroDataSnapshot, object]:
        calls.append(country)
        return _snapshot(as_of=now), _report()

    monkeypatch.setattr(builder, "build_snapshot", _fake)

    _snap1, first = get_snapshot("us")
    assert first.from_cache is False
    _snap2, cached = get_snapshot("us")
    assert cached.from_cache is True
    _snap3, refreshed = get_snapshot("us", force_refresh=True)

    assert len(calls) == 2, f"expected two builds, got {len(calls)}"
    assert refreshed.from_cache is False


# ---------------------------------------------------------------------------
# 3. The provenance's warnings — every condition, and only when true
# ---------------------------------------------------------------------------


def test_no_warnings_when_nothing_is_wrong() -> None:
    """A provenance with nothing to disclose says nothing.

    The other half of every warning test: a ``warnings()`` that always returned
    something would pass each individual assertion above and make the whole
    disclosure useless — a reader who sees a warning on every response stops
    reading them.
    """
    now = datetime.now(UTC)
    clean = SnapshotProvenance(
        country="us",
        as_of=now,
        generated_at=now,
        age_hours=0.5,
        age_exceeds_max=False,
        max_age_hours=24.0,
        from_cache=False,
        requested_fields=["gdp_real"],
        succeeded_fields=["gdp_real"],
        failed_fields={},
        skipped_unverified_fields=[],
        data_quality_flag_count=0,
    )

    assert clean.warnings() == []


def test_every_disclosure_condition_has_its_own_line() -> None:
    """Five conditions, five messages — including the two that are easy to omit.

    ``skipped_unverified`` and ``data_quality_flag_count`` are the subtle ones: a
    field skipped for being registry-unverified is not a *failure*, so it would
    never appear in ``failed_fields``, and a snapshot can be complete and flagged.
    Both change how much weight the thesis can carry.
    """
    now = datetime.now(UTC)
    flagged = SnapshotProvenance(
        country="us",
        as_of=now - timedelta(hours=30),
        generated_at=now,
        age_hours=30.0,
        age_exceeds_max=True,
        max_age_hours=24.0,
        from_cache=True,
        requested_fields=["a", "b", "c", "d"],
        succeeded_fields=["a"],
        failed_fields={"b": "x", "c": "y"},
        skipped_unverified_fields=["d"],
        data_quality_flag_count=3,
    )

    warnings = flagged.warnings()

    assert len(warnings) == 5, f"expected five disclosures, got {len(warnings)}: {warnings}"
    for marker in (
        "SNAPSHOT PARTIAL",
        "SNAPSHOT SKIPPED",
        "SNAPSHOT STALE",
        "SNAPSHOT FLAGGED",
        "SNAPSHOT REUSED",
    ):
        assert any(marker in w for w in warnings), f"no {marker} line in {warnings}"

    reused = next(w for w in warnings if "SNAPSHOT REUSED" in w)
    assert "without its age" in reused, (
        "the REUSED line must say WHY it is attached: a cached answer with no age "
        "is indistinguishable from a fresh one."
    )
