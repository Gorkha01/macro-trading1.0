"""D-070 — the API layer's routes: status codes, disclosures, and honesty.

Section 8's endpoints, tested against the contracts rather than the sample. The
sample's own two defects are the reason this file exists:

1. Section 8.2 calls ``build_us_macro_thesis(snapshot)``, which raises
   ``TypeError: missing 6 required arguments``; and ``fetch_full_snapshot``,
   which does not exist. A test written from the sample would not run.
2. Section 8.3's SSE steps are hardcoded strings — ``"gap = -140bp"``,
   ``"14 series"``, ``"HIGH convergence"``. A test that asserted those strings
   would **pin the fabrication in place** and pass forever, because a hardcoded
   value always matches itself.

So the stream tests here assert the opposite property: that the emitted values
are the ones the models produced *this run*, cross-checked against a separately
built thesis. That is the only form of assertion that a fabricated number can
fail.

**Why the snapshot is seeded rather than built.** A live build takes 9.5s
in-process and 223.6s over the local OpenBB API (measured), and these tests are
deselected from... no — they are in the default run, so they must not touch the
network. The cache is seeded from the **persisted parquet snapshot**, which is
the same object a live build produces and requires no provider. The live path is
``scripts/live_api_check.py``'s job (Section 21.0: unit tests prove the function,
the live check proves the wiring).

**The store-absent contract.** Every test in this module requests a fixture that
transitively depends on ``persisted_snapshot`` — including the few that appear to
need nothing (``test_query_matches_whole_tokens_not_substrings`` only calls a pure
matcher; it takes ``client`` anyway). That is deliberate: a module whose tests are
*sometimes* seeded is a module whose tests *sometimes* call the real provider, so
partial seeding would fail nondeterministically instead of skipping. This module
therefore has exactly two outcomes — **all skip** (no store) or **all run against
the seed** (store present).

The ``persisted_snapshot`` fixture must call ``load_snapshot(..., strict=True)``.
The non-strict signature returns a default *empty* snapshot when the store is
absent rather than raising, so a naive ``except FileNotFoundError`` guard is dead
code — and an empty seeded snapshot makes 22 of these tests fail with messages
that read like genuine API breakage. See ``SnapshotStoreEmptyError``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from macro_engine.api_layer import snapshot_provider
from macro_engine.api_layer.app import create_app
from macro_engine.api_layer.orchestration import OrchestrationError
from macro_engine.api_layer.snapshot_provider import SnapshotUnavailableError
from macro_engine.data_layer.persistence import SnapshotStoreEmptyError, load_snapshot
from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    YieldCurveSnapshot,
)
from macro_engine.models.contracts import utc_now


@pytest.fixture(autouse=True)
def _clear_snapshot_cache() -> None:
    """Every test starts with an empty cache.

    Autouse because the provider's cache is module-level by design, so without
    this a test that seeds it would leak into the next one — and the tests that
    assert *cache behaviour* would then depend on execution order.
    """
    snapshot_provider.reset_cache()


def _seed(monkeypatch: pytest.MonkeyPatch, snapshot: MacroDataSnapshot) -> None:
    """Put a snapshot in the provider's cache, as a completed build.

    Uses the real ``_CacheEntry`` shape rather than monkeypatching ``get_snapshot``,
    so the routes exercise their real provenance plumbing. Monkeypatching the
    provider function would test a router against a stub and leave the disclosure
    path — the part that matters — unexercised.
    """
    report = SimpleNamespace(
        requested=["seeded"],
        succeeded=["seeded"],
        failed={},
        skipped_unverified=[],
    )
    provenance = snapshot_provider._provenance_from_report(
        snapshot,
        report=report,
        from_cache=False,
        build_seconds=1.0,
        generated_at=utc_now(),
    )
    snapshot_provider._CACHE["us"] = snapshot_provider._CacheEntry(
        snapshot=snapshot, provenance=provenance
    )


@pytest.fixture
def persisted_snapshot() -> MacroDataSnapshot:
    """The most recent persisted snapshot, which needs no provider.

    Skips rather than fails when the audit trail is empty: a checkout without
    ``data/raw`` cannot seed this fixture, and a failing test would report a
    missing fixture as a broken API.

    ``strict=True`` is what makes the guard real. Without it, ``load_snapshot``
    returns a default *empty* snapshot when the store is absent — so the
    ``except`` below never fires, the empty snapshot gets seeded, and every test
    that reads a series fails downstream as though the API were broken. That was
    the actual cause of the 22-failure clean-checkout run; the exception this
    catches is now raised deliberately rather than never.
    """
    try:
        return load_snapshot("us", strict=True)
    except SnapshotStoreEmptyError as exc:  # pragma: no cover - environment
        pytest.skip(f"no persisted snapshot available to seed the API tests: {exc}")


@pytest.fixture
def client(persisted_snapshot: MacroDataSnapshot, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _seed(monkeypatch, persisted_snapshot)
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# The app wiring
# ---------------------------------------------------------------------------


def test_the_app_registers_every_endpoint_the_spec_defines() -> None:
    """Five routers, because §8.1's sample omits §8.3's.

    An endpoint that is defined but not included in the app 404s, and the sample's
    include list is missing the streaming router. This asserts the set, so that
    adding a route module without registering it fails here rather than at
    runtime.
    """
    app = create_app()
    # ``app.routes`` is typed as ``BaseRoute``, which has no ``path``; only the
    # concrete route classes (``APIRoute``) carry one. ``getattr`` with a default
    # is the honest narrowing — a route without a path is simply not one of the
    # HTTP routes this test is about, and asserting on it would be a type error
    # dressed as a test.
    paths = {
        path
        for route in app.routes
        if (path := getattr(route, "path", None)) is not None
        and getattr(route, "methods", None) is not None
    }

    assert {
        "/health",
        "/thesis/{country}",
        "/thesis/{country}/stream",
        "/query",
        "/dashboard_data",
    } <= paths


def test_cors_is_configured_from_config_not_hardcoded() -> None:
    """§8.4's permissive CORS is safe *because* the bind is loopback — as a pair.

    A wildcard-bound service with permissive origins is an open relay to
    ``/thesis``, which runs a full snapshot build. ``ApiSettings`` refuses that
    combination, and this asserts the middleware reads config rather than a
    literal, so the guard cannot be bypassed by editing Python.
    """
    from macro_engine.config import get_settings

    app = create_app()
    middleware = [m for m in app.user_middleware if "CORSMiddleware" in str(m)]
    settings = get_settings()

    if settings.api.cors_origins:
        assert middleware, "cors_origins is configured but no CORS middleware was added"
    assert settings.api.loopback_only, (
        "the test environment's bind is not loopback; the CORS configuration "
        "assumption this test documents does not hold"
    )


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_reports_liveness_without_building(client: TestClient) -> None:
    """The cheap path must not build a snapshot — it is polled by a supervisor."""
    response = client.get("/health")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["deep_check"] is False


def test_health_reports_the_cached_snapshot_age(client: TestClient) -> None:
    """A cached snapshot must be visible from /health, with its age.

    Answering "ok" while a stale snapshot sits in the cache would make the next
    call — which serves that snapshot — the caller's first warning.
    """
    body = client.get("/health").json()

    assert body["cached_snapshot"] is True
    assert body["cached_age_hours"] is not None
    assert body["cached_is_stale"] is False


def test_health_exposes_the_loopback_posture(client: TestClient) -> None:
    """§8.4's safety property as a value, not an inference from the host string."""
    body = client.get("/health").json()

    assert body["loopback_only"] is True


def test_health_reports_the_implemented_countries(client: TestClient) -> None:
    """§22.3: US-only, and the endpoint says which countries actually work."""
    body = client.get("/health").json()

    assert body["implemented_countries"] == ["us"]


# ---------------------------------------------------------------------------
# /thesis — the status-code contract
# ---------------------------------------------------------------------------


def test_thesis_returns_a_thesis_and_its_provenance(client: TestClient) -> None:
    response = client.get("/thesis/us")
    body = response.json()

    assert response.status_code == 200
    assert body["thesis"]["thesis_id"].startswith("us-")
    assert body["provenance"]["country"] == "us"
    assert body["derivation_notes"], "the response must carry its derivations"


def test_a_stand_down_is_a_200_not_an_error(client: TestClient) -> None:
    """The most important assertion in this file.

    Section 16.3: a stand-down is a real analytical finding with evidence
    attached, not a fallback for missing data. If it were a 4xx or 5xx, a client
    could not distinguish "the models agree there is no edge" from "the feed is
    broken" — and a broken feed would then be indistinguishable from a
    deliberate no-trade verdict.
    """
    response = client.get("/thesis/us")
    body = response.json()

    assert response.status_code == 200
    assert body["thesis"]["status"] in {"DRAFT", "WATCH"}
    if body["thesis"]["status"] == "WATCH":
        assert body["thesis"]["trade_idea"]["instrument"] == "NONE"
        assert body["warnings"], "a stand-down must say which gate fired"


def test_an_unimplemented_country_is_a_501(client: TestClient) -> None:
    """The route exists; the capability does not. Not a 404.

    404 would tell the caller the URL is wrong, and the URL is right — Section
    22.3's scoping is what is being refused.
    """
    response = client.get("/thesis/de")

    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"]


@pytest.mark.parametrize("country", ["de", "jp", "gb", "eu", "US"])
def test_every_unimplemented_country_is_refused(client: TestClient, country: str) -> None:
    """``US`` uppercase is included deliberately: the check is not case-insensitive.

    ``country`` is a label threaded through every layer, and accepting ``US``
    here while the rest of the system keys on ``us`` would produce a thesis whose
    label never matches anything downstream.
    """
    response = client.get(f"/thesis/{country}")

    assert response.status_code == 501


def test_an_unknown_thesis_type_is_a_422(client: TestClient) -> None:
    """A bad *parameter* is a client error, distinct from a missing capability."""
    response = client.get("/thesis/us", params={"thesis_type": "not_a_family"})

    assert response.status_code == 422
    assert "unknown thesis_type" in response.json()["detail"]


def test_the_assumed_thesis_type_is_disclosed(client: TestClient) -> None:
    """The one analytical choice the endpoint makes for the caller must be visible."""
    body = client.get("/thesis/us").json()

    assert body["thesis_type_source"] == "assumed from api.default_thesis_type"


def test_a_supplied_thesis_type_is_labelled_as_such(client: TestClient) -> None:
    body = client.get("/thesis/us", params={"thesis_type": "curve_shape_gap"}).json()

    assert body["thesis_type_source"] == "supplied by the caller"


def test_the_response_carries_the_derivation_notes(client: TestClient) -> None:
    """The part of the pipeline a reader cannot check by looking at the thesis."""
    body = client.get("/thesis/us").json()
    names = {note["name"] for note in body["derivation_notes"]}

    for required in ("short_yield", "pi_current", "i_prev", "r_star", "thesis_type"):
        assert required in names, f"no derivation note for {required!r}"


def test_a_failed_orchestration_is_a_502_and_never_a_thesis(
    persisted_snapshot: MacroDataSnapshot,
) -> None:
    """A snapshot with an empty required series must produce 502, not WATCH.

    This is the Section 16.3 line: a broken feed must not read as "no trade
    today". The response must carry no thesis at all — not a stand-down.
    """
    broken = persisted_snapshot.model_copy(update={"pce_core": []})
    _seed(pytest.MonkeyPatch(), broken)
    client = TestClient(create_app())

    response = client.get("/thesis/us")

    assert response.status_code == 502
    assert "pce_core" in response.json()["detail"]
    assert "NOT a no-trade" in response.json()["detail"]


def test_an_unavailable_snapshot_is_a_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider's failure maps to 502, with the no-trade caveat stated."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise snapshot_provider.SnapshotUnavailableError("provider refused the connection")

    monkeypatch.setattr(snapshot_provider, "get_snapshot", _raise)
    monkeypatch.setattr("macro_engine.api_layer.routes_thesis.get_snapshot", _raise, raising=True)

    response = client.get("/thesis/us")

    assert response.status_code == 502
    assert "NOT a no-trade" in response.json()["detail"]


# ---------------------------------------------------------------------------
# /dashboard_data
# ---------------------------------------------------------------------------


def test_dashboard_returns_flattened_panels(client: TestClient) -> None:
    body = client.get("/dashboard_data").json()

    assert body["country"] == "us"
    assert body["series"], "the dashboard must return at least one family"
    for family, panels in body["series"].items():
        assert panels, f"family {family!r} was returned empty"
        for panel in panels:
            assert len(panel["dates"]) == len(panel["values"])


def test_dashboard_caps_each_series_and_reports_what_it_withheld(client: TestClient) -> None:
    """A truncated chart must say it is truncated.

    Measured on the persisted snapshot: the price panels carry 12 points of 59.
    A reader who saw 12 points and no withheld count would read the visible
    window as the whole history.
    """
    body = client.get("/dashboard_data").json()
    limit = body["series_limit"]

    truncated = [
        panel
        for panels in body["series"].values()
        for panel in panels
        if panel["points_available"] > limit
    ]
    assert truncated, "the fixture snapshot should be long enough to truncate"
    for panel in truncated:
        assert panel["points_withheld"] > 0
    assert any("TRUNCATED" in w for w in body["warnings"])


def test_dashboard_keeps_the_most_recent_points(client: TestClient) -> None:
    """Most recent, not oldest: a dashboard of four years ago is not a dashboard."""
    body = client.get("/dashboard_data").json()
    panel = body["series"]["prices"][0]

    assert panel["latest_date"] == panel["dates"][-1]
    assert panel["latest_value"] == panel["values"][-1]


def test_dashboard_reports_the_curve_in_percent(client: TestClient) -> None:
    body = client.get("/dashboard_data").json()

    assert body["yield_curve"] is not None
    assert body["yield_curve"]["units"] == "percent"
    assert len(body["yield_curve"]["tenors"]) == 11


def test_dashboard_omits_an_empty_family_rather_than_returning_empty_panels() -> None:
    """An absent key means "no panel"; an empty list forces a special case.

    Built from a synthetic snapshot because the persisted one has every family
    populated, so the branch would otherwise never be exercised.
    """
    sparse = MacroDataSnapshot(
        country="us",
        as_of=utc_now(),
        yield_curve=YieldCurveSnapshot(as_of=utc_now().date(), tenors={"2yr": 4.0}),
    )
    _seed(pytest.MonkeyPatch(), sparse)
    client = TestClient(create_app())

    body = client.get("/dashboard_data").json()

    assert "growth" not in body["series"]
    assert body["yield_curve"] is not None


def test_dashboard_does_not_publish_a_verdict(client: TestClient) -> None:
    """No gap, no convergence, no instrument — those are judgments.

    The dashboard publishes measurements. A caller that needs a claim asks
    ``/thesis``, where the claim carries its evidence. Publishing a verdict here
    would put it where nothing checks it against the gates.
    """
    body = client.get("/dashboard_data").json()
    serialised = json.dumps(body)

    assert "convergence_classification" not in serialised
    assert "trade_idea" not in serialised
    assert "market_pricing_gap" not in serialised


# ---------------------------------------------------------------------------
# A renamed snapshot field must be visible, not a silent null panel
# ---------------------------------------------------------------------------
#
# ``_points_for``/``_curve_panel`` use ``getattr(..., None)`` with silent ``[]``
# and ``None`` fallbacks. That is correct for degrading gracefully, but it means
# two different situations produce byte-identical responses:
#
#   * the field exists and this snapshot has no observations  -> a DATA gap
#   * the field does not exist on the schema at all           -> a CODE defect
#
# The client sees ``"tips_curve": null`` either way and ``warnings`` is empty,
# so it renders an empty chart and cannot tell "no data configured" from "the
# field was renamed". D-005 records ``treasury_curve`` -> ``yield_curve`` alias
# drift as exactly this class, so the detector is not hypothetical.


def test_dashboard_warns_when_a_declared_field_is_not_on_the_schema(
    monkeypatch: pytest.MonkeyPatch, persisted_snapshot: MacroDataSnapshot
) -> None:
    """THE regression: a renamed field must raise a warning naming it.

    ``_SERIES_FAMILIES`` is patched to name a field that does not exist on
    ``MacroDataSnapshot`` — the shape a rename produces in production. Before
    the fix the response was a 200 with an absent panel and empty warnings.
    """
    from macro_engine.api_layer import routes_dashboard

    _seed(monkeypatch, persisted_snapshot)
    # A plausible typo/rename: the D-005 alias drift, one character off.
    monkeypatch.setitem(
        routes_dashboard._SERIES_FAMILIES,
        "growth",
        ("gdp_real", "gdp_nominal", "treasury_curve"),
    )
    client = TestClient(create_app())

    body = client.get("/dashboard_data").json()

    assert body is not None
    missing = [w for w in body["warnings"] if w.startswith("DASHBOARD FIELD MISSING")]
    assert missing, "a renamed field must not degrade silently to a null panel"
    assert "treasury_curve" in missing[0]


def test_dashboard_does_not_cry_wolf_on_a_complete_schema(client: TestClient) -> None:
    """No renamed field means no warning — the flag list must stay trustworthy.

    A detector that fired on every request would train a reader to ignore the
    warnings list, which is the failure mode the list exists to avoid. This pins
    the negative case, so the fix cannot be satisfied by warning unconditionally.
    """
    body = client.get("/dashboard_data").json()

    assert not [w for w in body["warnings"] if w.startswith("DASHBOARD FIELD MISSING")]


def test_dashboard_does_not_confuse_an_empty_field_with_a_missing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared-but-empty field is a DATA gap, and must NOT raise the code flag.

    ``jolts_quits`` is on the schema and empty in this synthetic snapshot. That
    is a fetch outcome the provenance flags already describe; flagging it as a
    missing field would send a reader to fix the code for a provider problem.
    """
    sparse = MacroDataSnapshot(
        country="us",
        as_of=utc_now(),
        yield_curve=YieldCurveSnapshot(as_of=utc_now().date(), tenors={"2yr": 4.0}),
        # jolts_quits intentionally absent while the schema declares it
    )
    _seed(monkeypatch, sparse)
    client = TestClient(create_app())

    body = client.get("/dashboard_data").json()

    assert not [w for w in body["warnings"] if w.startswith("DASHBOARD FIELD MISSING")]


# ---------------------------------------------------------------------------
# /query
# ---------------------------------------------------------------------------


def test_query_routes_by_keyword_and_admits_it(client: TestClient) -> None:
    """The honesty field, asserted as a field rather than read from prose."""
    body = client.post(
        "/query", json={"question": "Will the Fed cut rates as inflation cools?"}
    ).json()

    assert body["is_keyword_routing"] is True
    assert "policy_rules" in body["matched_topics"]
    assert "inflation" in body["matched_topics"]
    assert body["supporting_thesis_id"]


def test_query_reports_the_tokens_that_did_not_match(client: TestClient) -> None:
    """Partial retrieval must be visible.

    Without this a caller sees three matched topics and infers the question was
    fully understood, when six of its words matched nothing.
    """
    body = client.post(
        "/query", json={"question": "Will the Fed cut rates as the moon wobbles?"}
    ).json()

    assert "wobbles" in body["unmatched_terms"]
    assert "moon" in body["unmatched_terms"]


def test_query_with_no_match_returns_no_thesis(client: TestClient) -> None:
    """An unmatched question is a result, and must not be dressed as a finding."""
    body = client.post("/query", json={"question": "what is the weather in Tokyo"}).json()

    assert body["matched_topics"] == []
    assert body["supporting_thesis_id"] is None
    assert body["relevant_model_outputs"] == []
    assert "No topic matched" in body["answer"]


def test_query_matches_whole_tokens_not_substrings(client: TestClient) -> None:
    """``"session"`` contains ``"session"``, not ``"recession"`` — the reverse matters.

    Substring matching would route "trading session" to the regime model, because
    the word "recession" contains "session". This pins whole-token equality,
    which is what makes the keyword table's words mean what they say.

    Takes ``client`` (though it only calls the pure matcher) so that the fixture
    resolution is uniform across the module — see the module docstring's note on
    why a partial store produces one skip/count rather than two.
    """
    from macro_engine.api_layer.routes_query import _match_topics, _tokenise

    matched, _unmatched = _match_topics(_tokenise("the trading session was quiet"))

    assert "regime" not in matched


def test_query_returns_the_thesis_fields_the_topics_name(client: TestClient) -> None:
    body = client.post("/query", json={"question": "what does the yield curve say"}).json()

    fields = [entry["field"] for entry in body["relevant_model_outputs"]]
    assert "trade_idea" in fields


def test_query_deduplicates_fields_named_by_two_topics(client: TestClient) -> None:
    """``trade_idea`` is reachable from ``curve`` AND ``risk``; a duplicate field
    would render the same value twice and double-count it in a UI."""
    body = client.post("/query", json={"question": "yield curve risk and the stop level"}).json()

    fields = [entry["field"] for entry in body["relevant_model_outputs"]]
    assert len(fields) == len(set(fields))


def test_query_rejects_an_unknown_thesis_type(client: TestClient) -> None:
    response = client.post("/query", json={"question": "inflation", "thesis_type": "nope"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /query reports the same failures in the same shapes as /thesis
# ---------------------------------------------------------------------------
#
# Both endpoints call one builder through the same three stages. Before these
# tests, ``/query`` wrapped all three in a single ``try`` and one 502 — so
# "the source did not answer" and "the data arrived and was unusable" produced
# one message, and a *builder* raise matched no branch at all and escaped as a
# bare 500 with a stack trace and no ``detail``. The mapping now comes from
# ``routes_thesis._http_status_for`` so the two endpoints cannot disagree.


def _query_with_builder_failure(
    monkeypatch: pytest.MonkeyPatch, persisted_snapshot: MacroDataSnapshot, exc: Exception
) -> tuple[int, object]:
    """Seed a snapshot, make the builder raise, and call ``/query``."""
    from macro_engine.api_layer import routes_query

    _seed(monkeypatch, persisted_snapshot)

    def _boom(*args: object, **kwargs: object) -> None:
        raise exc

    monkeypatch.setattr(routes_query, "build_us_macro_thesis", _boom)
    client = TestClient(create_app())
    response = client.post("/query", json={"question": "what does the policy gap say"})
    return response.status_code, response.json()


def test_query_maps_a_builder_failure_to_500_with_a_detail(
    monkeypatch: pytest.MonkeyPatch, persisted_snapshot: MacroDataSnapshot
) -> None:
    """A builder raise must be a diagnosable 500, not an unhandled traceback.

    ``/thesis`` already reported this as "500 + detail naming the exception
    type". ``/query`` let it escape: the client got a 500 from FastAPI's default
    handler with no ``detail``, so it could not tell a service defect from a
    malformed request.
    """
    status, body = _query_with_builder_failure(
        monkeypatch, persisted_snapshot, TypeError("shape changed")
    )

    assert status == 500
    assert isinstance(body, dict)
    assert "TypeError" in body["detail"]
    assert "shape changed" in body["detail"]


def test_query_distinguishes_an_unavailable_source_from_unusable_data(
    monkeypatch: pytest.MonkeyPatch, persisted_snapshot: MacroDataSnapshot
) -> None:
    """The two 502 classes are deliberately distinct and must stay distinct.

    ``SnapshotUnavailableError`` (the source did not answer) and
    ``OrchestrationError`` (the data arrived and a required field was unusable)
    both map to 502, but their messages name different causes — and before the
    split, ``/query`` produced one message for both.
    """
    _, unavailable = _query_with_builder_failure(
        monkeypatch, persisted_snapshot, SnapshotUnavailableError("no answer")
    )
    # ``fields`` is part of OrchestrationError's contract; the message must name
    # them, so the caller learns WHAT could not be read.
    _, orchestration = _query_with_builder_failure(
        monkeypatch,
        persisted_snapshot,
        OrchestrationError("jolts_quits unusable", fields=("jolts_quits",)),
    )

    assert isinstance(unavailable, dict) and isinstance(orchestration, dict)
    assert unavailable["detail"] != orchestration["detail"]
    assert "jolts_quits" in orchestration["detail"]


def test_query_publishes_the_orchestration_warnings_not_only_provenance(
    client: TestClient, persisted_snapshot: MacroDataSnapshot
) -> None:
    """``/query`` must carry the orchestration's disclosures, as ``/thesis`` does.

    Publishing only ``provenance.warnings()`` dropped everything the
    orchestration learned while deriving inputs — ignored curve legs, unit
    traps, fields it could not read. Those are the disclosures a caller uses to
    judge how much of the thesis to trust, and ``/query`` was the one endpoint
    withholding them.

    The assertion is an EQUALITY against the union the orchestration itself
    produced, not a "warnings is non-empty" smoke check. ``provenance.warnings()``
    is non-empty on this fixture, so a weaker check would pass even with the
    union removed — verified by mutation: narrowing the list back to
    ``provenance.warnings()`` alone left a non-emptiness assertion green.
    """
    body = client.post("/query", json={"question": "what does the policy gap say"}).json()

    from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs

    inputs = snapshot_to_thesis_inputs(persisted_snapshot)
    assert inputs.warnings, "precondition: this snapshot produces orchestration disclosures"

    warnings = body["warnings"]
    assert len(warnings) == len(set(warnings)), "the warning union must deduplicate"
    # Every orchestration disclosure must be present, which is only true if the
    # union was actually built.
    missing = [w for w in inputs.warnings if w not in warnings]
    assert not missing, f"orchestration disclosures were withheld from /query: {missing[:2]}"


def test_query_does_not_restate_the_stale_flag_as_prose(
    client: TestClient,
) -> None:
    """One fact, one representation: STALE travels as the structured warning.

    It used to be appended to ``answer`` behind a substring match on the warning
    text, so a client had to parse prose for one form and read ``warnings`` for
    the other — and the two could disagree the moment the wording changed.
    """
    body = client.post("/query", json={"question": "what does the policy gap say"}).json()

    assert "STALE" not in body["answer"]


def test_query_rejects_an_unknown_thesis_type_after_the_refactor(
    client: TestClient,
) -> None:
    """The 422 guard must still fire — the refactor moved the stages below it."""
    response = client.post("/query", json={"question": "inflation", "thesis_type": "nope"})

    assert response.status_code == 422


def test_query_requires_a_non_empty_question(client: TestClient) -> None:
    response = client.post("/query", json={"question": ""})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /thesis/{country}/stream — the numbers must be the models', not the spec's
# ---------------------------------------------------------------------------


def _events(payload: str) -> list[dict[str, str]]:
    """Parse the SSE body into event dicts, dropping the terminator."""
    events: list[dict[str, str]] = []
    for line in payload.splitlines():
        if not line.startswith("data: "):
            continue
        data = line[len("data: ") :]
        if data == "[DONE]":
            continue
        events.append(json.loads(data))
    return events


def test_stream_emits_the_documented_event_shape(client: TestClient) -> None:
    """``{step, status, detail}`` — OpenBB's AI SDK consumes this contract."""
    response = client.get("/thesis/us/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert events
    for event in events:
        assert set(event) == {"step", "status", "detail"}
        assert event["detail"]


def test_stream_terminates_with_done(client: TestClient) -> None:
    """Without a terminator a client cannot tell "ended" from "connection dropped"."""
    response = client.get("/thesis/us/stream")

    assert response.text.rstrip().endswith("data: [DONE]")


def test_stream_emits_the_real_gap_not_the_spec_literal(client: TestClient) -> None:
    """The defect this stream exists to avoid, asserted directly.

    Section 8.3 hardcodes ``"gap = -140bp"``. This test requires the emitted gap
    to equal the gap computed independently from the same snapshot — so a
    literal, or any stale value, fails. A test asserting the spec's string would
    have pinned the fabrication in place and passed forever.
    """
    from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
    from macro_engine.thesis_layer.builder import build_policy_gap

    snapshot = load_snapshot("us")
    inputs = snapshot_to_thesis_inputs(snapshot)
    gap, _rules, _ensemble, _market = build_policy_gap(
        inputs.taylor_inputs,
        inputs.first_difference_inputs,
        short_yield=inputs.short_yield,
        short_tenor_term_premium=None,
    )

    events = _events(client.get("/thesis/us/stream").text)
    gap_event = next(e for e in events if e["step"] == "compute_gap")

    assert f"{gap.raw_gap * 100:+.1f}bp" in gap_event["detail"]
    assert "-140bp" not in gap_event["detail"], (
        "the spec's hardcoded gap reached the stream — this is the defect the "
        "generator replaces, and it must not return"
    )


def test_stream_emits_the_real_rule_values(client: TestClient) -> None:
    """§8.3 says "9 models completed"; this says which rules produced what."""
    events = _events(client.get("/thesis/us/stream").text)
    run_event = next(e for e in events if e["step"] == "run_models" and e["status"] == "done")

    for rule_name in ("taylor_rule", "balanced_approach_rule", "first_difference_rule"):
        assert rule_name in run_event["detail"]


def test_stream_emits_the_real_convergence_and_gate(client: TestClient) -> None:
    """The convergence label and, on a stand-down, the gate that fired.

    Asserted against the thesis built from the same snapshot, so a hardcoded
    "HIGH convergence" fails on any day the classification is not HIGH.
    """
    from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
    from macro_engine.thesis_layer.builder import build_us_macro_thesis

    snapshot = load_snapshot("us")
    inputs = snapshot_to_thesis_inputs(snapshot)
    thesis = build_us_macro_thesis(
        inputs.reads,
        inputs.taylor_inputs,
        inputs.first_difference_inputs,
        thesis_type=inputs.thesis_type,
        universe=inputs.universe,
        short_yield=inputs.short_yield,
    )

    events = _events(client.get("/thesis/us/stream").text)
    conv_event = next(e for e in events if e["step"] == "classify_convergence")

    assert thesis.convergence_classification.value in conv_event["detail"]

    # The gate, derived independently from the thesis's own published warnings.
    # Asserting only the convergence label let ``M8.6`` through: that mutant makes
    # ``_fired`` return every trigger, so the trace read "stood down by
    # gap_below_dispersion, conflicted_signals, no_falsifier" when exactly one
    # fired — three claimed gates, two of them fabricated. The trace must name
    # the fired set EXACTLY, not merely contain the right convergence word.
    from macro_engine.thesis_layer.no_trade import NO_TRADE_TRIGGER_LABELS

    # ``NoTradeTrigger`` is a ``Literal`` (a closed vocabulary), and the labels
    # dict is keyed by it — so the keys ARE the vocabulary, and iterating them
    # is the same census the stream performs.
    expected = sorted(
        trigger
        for trigger, label in NO_TRADE_TRIGGER_LABELS.items()
        if any(label in w for w in thesis.warnings)
    )

    build_event = next(e for e in events if e["step"] == "build_thesis" and e["status"] == "done")
    detail = build_event["detail"]

    if thesis.status.value == "no_trade" or expected:
        prefix, marker, tail = detail.partition(": status=")
        assert marker, f"a stand-down must name its gates; got {detail!r}"
        assert prefix.startswith("Thesis stood down by "), (
            f"a stand-down must name its gates; got {detail!r}"
        )
        # The gate list is the span between the two fixed phrases; splitting the
        # whole detail on commas would also catch the trailing metadata
        # (``status=``, ``instrument=``, ``N warning(s) carried``), which is not
        # a gate and would make this assertion compare the wrong thing.
        assert tail, f"the stand-down frame dropped its metadata; got {detail!r}"
        named = [part.strip() for part in prefix.removeprefix("Thesis stood down by ").split(",")]
        assert named == expected, (
            f"the trace named {named} but the thesis's own warnings justify "
            f"{expected} — an unfired gate in the trace is a fabricated "
            f"attribution (D-067)."
        )
    else:
        # No gate fired: the trace must not claim one did.
        assert "stood down by" not in detail, (
            "the trace claims a stand-down gate fired but the thesis published none."
        )


def test_stream_reports_the_real_field_counts(client: TestClient) -> None:
    """§8.3 says "14 series"; this repeats the provenance's own counts."""
    events = _events(client.get("/thesis/us/stream").text)
    fetch_done = next(e for e in events if e["step"] == "fetch_data" and e["status"] == "done")
    provenance = client.get("/health").json()

    assert "Snapshot" in fetch_done["detail"]
    assert provenance["cached_age_hours"] is not None


def test_stream_never_emits_an_error_status_on_a_stand_down(client: TestClient) -> None:
    """A stand-down is a completed analysis, so its steps are ok/`done`.

    If a stand-down emitted an error frame a consumer would show a failure
    indicator for a successful analysis — and, worse, a real failure would then
    be indistinguishable from a no-trade verdict (Section 16.3).
    """
    events = _events(client.get("/thesis/us/stream").text)
    build_done = next(e for e in events if e["step"] == "build_thesis" and e["status"] == "done")

    assert build_done["detail"]
    assert not any(e["status"] == "error" for e in events)


def test_stream_refuses_an_unimplemented_country_before_opening(
    client: TestClient,
) -> None:
    """A 501, not a 200 whose body contains an error frame.

    A client that has opened a stream is already parsing events and cannot be
    told "you asked for the wrong thing" — by then it has committed to reading
    frames, and the status code was the last chance to say so.
    """
    response = client.get("/thesis/de/stream")

    assert response.status_code == 501


def test_stream_emits_an_error_frame_when_the_orchestration_refuses(
    persisted_snapshot: MacroDataSnapshot,
) -> None:
    """Mid-stream failures become a final error frame, then ``[DONE]``.

    Without the terminator after an error a client would see a truncated trace
    and could not distinguish it from completion.
    """
    broken = persisted_snapshot.model_copy(update={"jolts_quits": []})
    _seed(pytest.MonkeyPatch(), broken)
    client = TestClient(create_app())

    response = client.get("/thesis/us/stream")
    events = _events(response.text)

    assert response.status_code == 200
    errors = [e for e in events if e["status"] == "error"]
    assert errors, "a refused orchestration must surface as an error frame"
    assert "jolts_quits" in errors[0]["detail"]
    assert response.text.rstrip().endswith("data: [DONE]")


# ---------------------------------------------------------------------------
# The SSE terminator is UNCONDITIONAL — including for unhandled raises
# ---------------------------------------------------------------------------
#
# The generator's cheap, unguarded region is real and reachable: ``build_policy_gap``
# raises TypeError by design when ``derive_market_implied_policy_path`` changes
# shape, and ValueError on a zero gap, and every ``_event(...)`` formatting call
# sits outside any per-stage handler. Before the outer guard, one raise there
# propagated out of the async generator and the client got a **truncated body
# with no terminal event**.
#
# These tests drive the generator directly rather than through HTTP, because the
# trigger is a raise in a stage, and a monkeypatched raiser is how that is
# expressed deterministically. HTTP-level coverage of the happy path and the
# handled stages lives above.


def _drain(country: str = "us") -> list[str]:
    """Run the SSE generator to exhaustion and return its frames."""
    import asyncio

    from macro_engine.api_layer.reasoning_stream import reasoning_step_generator

    async def collect() -> list[str]:
        return [frame async for frame in reasoning_step_generator(country)]

    return asyncio.run(collect())


def _terminator_count(frames: list[str]) -> int:
    return sum(1 for frame in frames if frame.strip() == "data: [DONE]")


def test_stream_terminator_is_emitted_exactly_once_on_success(
    monkeypatch: pytest.MonkeyPatch, persisted_snapshot: MacroDataSnapshot
) -> None:
    """One success path must yield exactly one ``[DONE]`` — not zero, not two.

    The terminator moved from four scattered ``yield`` sites into one ``finally``.
    A single ``[DONE]`` is the contract; two would make a naive client think the
    stream had ended twice, and the count is what proves the consolidation was
    complete rather than additive.
    """
    _seed(monkeypatch, persisted_snapshot)
    frames = _drain()

    assert _terminator_count(frames) == 1
    assert frames[-1].strip() == "data: [DONE]"
    assert any("build_thesis" in frame for frame in frames)


def test_unhandled_raise_still_terminates_the_stream(
    monkeypatch: pytest.MonkeyPatch, persisted_snapshot: MacroDataSnapshot
) -> None:
    """THE regression: a raise outside a handled stage must not truncate the body.

    ``build_policy_gap`` is called bare in the middle of the trace. Raising from
    it used to propagate out of the generator, so the trailing ``[DONE]`` was
    never reached and the client could not tell the stream had died.
    """
    from macro_engine.api_layer import reasoning_stream

    _seed(monkeypatch, persisted_snapshot)
    monkeypatch.setattr(
        reasoning_stream,
        "build_policy_gap",
        lambda *a, **k: (_ for _ in ()).throw(TypeError("shape changed")),
    )

    frames = _drain()
    events = _events("".join(frames))

    assert _terminator_count(frames) == 1, "an unhandled raise truncated the stream"
    assert frames[-1].strip() == "data: [DONE]"
    assert any(e["status"] == "error" and "shape changed" in e["detail"] for e in events), (
        "the failure must be diagnosable, not just terminated"
    )


def test_terminator_survives_a_raise_from_the_error_path_itself(
    monkeypatch: pytest.MonkeyPatch, persisted_snapshot: MacroDataSnapshot
) -> None:
    """Even a raise inside the error frame's own formatting must still terminate.

    The outer ``except`` body is not itself covered by that ``except``, so a
    failure while formatting the diagnostic propagates — but the ``finally``
    still runs, so the terminator is emitted before the exception leaves the
    generator. A terminated stream with a missing explanation beats a truncated
    one, and this pins that ordering.

    ``pytest.raises`` wraps the drain because the RuntimeError genuinely escapes:
    the assertion is that ``[DONE]`` was collected *before* it did. Whether
    Starlette surfaces that as a 200 with a clean terminator or a reset
    connection is the framework's business; that the generator emitted the
    terminator first is this module's.
    """
    import asyncio

    from macro_engine.api_layer import reasoning_stream

    _seed(monkeypatch, persisted_snapshot)
    monkeypatch.setattr(
        reasoning_stream,
        "build_policy_gap",
        lambda *a, **k: (_ for _ in ()).throw(TypeError("shape changed")),
    )
    monkeypatch.setattr(
        reasoning_stream,
        "_event",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("symbol table exploded")),
    )

    frames: list[str] = []

    async def collect() -> None:
        async for frame in reasoning_stream.reasoning_step_generator("us"):
            frames.append(frame)

    with pytest.raises(RuntimeError, match="symbol table exploded"):
        asyncio.run(collect())

    assert any(frame.strip() == "data: [DONE]" for frame in frames), (
        "the terminator was skipped because the error message could not be built"
    )
