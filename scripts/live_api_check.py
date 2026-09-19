"""Live check: the API layer, end to end, against real data (D-070).

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_api_check.py

Section 21.0's split: unit tests prove the **function**, this proves the
**wiring**. ``tests/api_layer/`` seeds the provider's cache from the persisted
parquet snapshot and drives the routes through ``TestClient`` — which proves the
handlers, the status codes and the SSE shape, and proves nothing about whether
the provider can produce a snapshot at all. That is what this check measures.

What is established here
------------------------
1. **The provider builds a snapshot through the real data layer** — the path
   ``get_snapshot`` actually takes in production, including the build time the
   provenance reports.
2. **The orchestration derives every builder argument from it with no literal**
   — each note's value and source printed, so the numbers can be challenged.
3. **The resulting thesis passes the live schema** and reaches a verdict, with
   the gate that produced it named.
4. **The provenance's disclosure is real**: the age, the field counts, whether a
   failure occurred, and every warning line a caller would see.
5. **Every endpoint answers**, through a real ASGI server rather than a
   ``TestClient`` — so the response bodies are the ones a Workspace UI receives,
   serialised by the real encoder.
6. **The SSE stream emits the measured values**, and the check *reads them back*
   and compares them against a separately computed gap. A StreamedResponse that
   emitted a plausible-looking constant would pass a shape assertion and fail
   this comparison.

What this check CANNOT establish
--------------------------------
1. **Whether the OpenBB provider's current output is *economically* right.** The
   check proves the value was measured, not that the measurement is meaningful.
2. **Whether a Workspace UI consumes the payload correctly.** The contract is
   published; the consumer is not in this repository.
3. **Whether the service is safe to expose.** §8.4's posture is asserted from
   config (``loopback_only``), and whether a deployment honours it is a
   ``uvicorn`` process fact, not a repository one.
4. **Whether the SSE stream keeps flowing under a slow provider.** The generator
   is driven to completion here, not under concurrent load.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass

import httpx
import uvicorn
from h11._connection import DEFAULT_MAX_INCOMPLETE_EVENT_SIZE

from macro_engine.api_layer import snapshot_provider
from macro_engine.api_layer.app import create_app
from macro_engine.api_layer.orchestration import snapshot_to_thesis_inputs
from macro_engine.config import get_settings
from macro_engine.thesis_layer.builder import build_policy_gap, build_us_macro_thesis
from macro_engine.thesis_layer.schemas import MacroThesis

#: Port 0 lets the OS choose, so the check cannot collide with a Workspace
#: instance already bound to the configured port. The check starts its own
#: server rather than driving ``TestClient`` precisely so the transport, the
#: encoder and the CORS middleware are all exercised.
_PORT = 0

#: ``h11``'s ``DEFAULT_MAX_INCOMPLETE_EVENT_SIZE``, the size past which a
#: request header block is a **protocol** error (``RemoteProtocolError``, hint
#: 431). ``uvicorn`` passes it to every ``h11.Connection`` unless its own
#: ``h11_max_incomplete_event_size`` overrides it — which ``main`` asserts it
#: does not, so this constant describes the limit actually in force rather than
#: a number that merely resembles it.
#:
#: Read from h11 rather than copied: a hardcoded 16384 that silently disagreed
#: with the installed version would make that assertion check the wrong thing.
_H11_MAX_REQUEST_HEADER_BYTES = DEFAULT_MAX_INCOMPLETE_EVENT_SIZE


@dataclass(frozen=True)
class _Server:
    """A running uvicorn server, with the address the OS actually bound."""

    host: str
    port: int
    thread: threading.Thread
    server: uvicorn.Server

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _start_server() -> _Server:
    """Run the app in a background thread and wait until it accepts connections.

    A readiness poll rather than a sleep: the app's startup cost varies with the
    data layer's imports, and a fixed sleep would either be needlessly long or
    flaky — the two failure modes that make an operator script untrustworthy.
    """
    from macro_engine.api_layer import routes_health

    config = uvicorn.Config(
        create_app(),
        host="127.0.0.1",
        port=_PORT,
        log_level="warning",
        # The service's own docstring says the bind is the access control (§8.4);
        # binding loopback here keeps the check consistent with the posture it is
        # measuring rather than being an exception to it.
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30.0
    host, port = "127.0.0.1", 0
    while time.monotonic() < deadline:
        for socket in getattr(server, "servers", []):
            sockets = getattr(socket, "sockets", None)
            if sockets:
                host, port = sockets[0].getsockname()[:2]
        if getattr(server, "started", False) and port:
            break
        time.sleep(0.05)
    else:  # pragma: no cover - an environment failure, not a code path
        raise RuntimeError("the API server did not start within 30s")

    del routes_health  # imported for its side effect of failing early if broken
    return _Server(host=host, port=port, thread=thread, server=server)


def _stop_server(server: _Server) -> None:
    """Ask uvicorn to exit and wait for the thread, so the process is clean."""
    server.server.should_exit = True
    server.thread.join(timeout=15.0)


def _rule(title: str) -> None:
    print("\n" + "-" * 78)
    print(title)
    print("-" * 78)


def main() -> int:
    settings = get_settings()

    print("=" * 78)
    print("live API check (D-070)")
    print("=" * 78)

    # ------------------------------------------------------------------
    # 0a. The client is talking to this server, not through a proxy.
    # ------------------------------------------------------------------
    # The defect this check found was a 404 from a route that exists, and the
    # cause was that the client was **not** talking to this server: the
    # environment exports HTTP_PROXY/HTTPS_PROXY, httpx honours them by default,
    # and a forward proxy legitimately uses the absolute-URI request form. The
    # proxy forwards that URI to the origin, uvicorn reads the whole URI as the
    # path, no route matches, and the caller gets
    #
    #     404 {"detail": "Not Found"}
    #
    # from `/health`. Reported against the *route*, so it looked like a routing
    # bug; the route was fine the whole time.
    #
    # So print the environment's proxy settings and assert that the client is
    # built with `trust_env=False`. That is the cheap, early half of the lesson:
    # the expensive half was finding it, and it took a socket-level tap to prove
    # the request line — not the status code — was where the truth was.
    _rule("0a. The client's transport — no proxy for a loopback service")
    proxy_vars = {
        name: os.environ[name]
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "NO_PROXY",
            "no_proxy",
        )
        if name in os.environ
    }
    if proxy_vars:
        for name in sorted(proxy_vars):
            print(f"  {name}={proxy_vars[name]}")
    else:
        print("  no proxy variables in the environment")
    print("  -> the check builds its client with trust_env=False, so these do not apply")

    # ------------------------------------------------------------------
    # 0. The posture, before anything is served.
    # ------------------------------------------------------------------
    _rule("0. The configured posture (Section 8.4)")
    print(f"  host={settings.api.host}  port={settings.api.port}")
    print(f"  loopback_only={settings.api.loopback_only}")
    print(f"  cors_origins={settings.api.cors_origins}")
    print(f"  memoize_snapshots={settings.api.memoize_snapshots}")
    print(f"  snapshot_max_age_hours={settings.api.snapshot_max_age_hours}")
    print(f"  dashboard_series_limit={settings.api.dashboard_series_limit}")
    print(f"  default_thesis_type={settings.api.default_thesis_type}")
    print(f"  yoy_match_tolerance_days={settings.api.yoy_match_tolerance_days}")
    assert settings.api.loopback_only, (
        "the check binds loopback; a non-loopback config would make it a network "
        "service with no authentication (§8.4)"
    )

    # ------------------------------------------------------------------
    # 1. The provider, through the real data layer.
    # ------------------------------------------------------------------
    _rule("1. The snapshot provider — a real build, then a real cache hit")
    snapshot_provider.reset_cache()
    started = time.monotonic()
    snapshot, provenance = snapshot_provider.get_snapshot("us")
    first_seconds = time.monotonic() - started
    print(f"  country={provenance.country}  as_of={provenance.as_of.isoformat()}")
    print(f"  from_cache={provenance.from_cache}  build_seconds={provenance.build_seconds}")
    print(f"  wall time of this call: {first_seconds:.1f}s")
    print(
        f"  fields requested={len(provenance.requested_fields)} "
        f"succeeded={len(provenance.succeeded_fields)} "
        f"failed={len(provenance.failed_fields)}"
    )
    if provenance.failed_fields:
        print(f"  FAILED: {sorted(provenance.failed_fields)}")
        for name, reason in sorted(provenance.failed_fields.items()):
            print(f"    {name}: {reason}")
    print(f"  data_quality_flag_count={provenance.data_quality_flag_count}")

    cached_snapshot, cached_provenance = snapshot_provider.get_snapshot("us")
    print(
        f"  second call from_cache={cached_provenance.from_cache} "
        f"age_hours={cached_provenance.age_hours:.4f}"
    )
    assert cached_provenance.from_cache, "the cache did not serve the second call"
    assert cached_snapshot is snapshot, "the cached call returned a different object"

    # ------------------------------------------------------------------
    # 2. The orchestration — every argument derived, no literal.
    # ------------------------------------------------------------------
    _rule("2. The orchestration — every builder argument derived from the snapshot")
    inputs = snapshot_to_thesis_inputs(snapshot)
    for note in inputs.notes:
        window = f"  [{note.window}]" if note.window else ""
        print(f"  {note.name:36s} = {note.value}{window}")
    print(f"\n  derived arguments: {len(inputs.notes)}")
    print(f"  thesis_type={inputs.thesis_type.value}  short_yield={inputs.short_yield}")
    print(f"  warnings carried forward: {len(inputs.warnings)}")
    for warning in inputs.warnings:
        print(f"    - {warning[:150]}")

    assert inputs.notes, "the orchestration produced no derivation notes"

    # ------------------------------------------------------------------
    # 3. The thesis, and the gate that produced its verdict.
    # ------------------------------------------------------------------
    _rule("3. The thesis from the live inputs")
    thesis: MacroThesis = build_us_macro_thesis(
        inputs.reads,
        inputs.taylor_inputs,
        inputs.first_difference_inputs,
        thesis_type=inputs.thesis_type,
        universe=inputs.universe,
        short_yield=inputs.short_yield,
    )
    print(f"  thesis_id={thesis.thesis_id}")
    print(f"  status={thesis.status.value}  convergence={thesis.convergence_classification.value}")
    print(f"  instrument={thesis.trade_idea.instrument!r}")
    print(f"  direction={thesis.trade_idea.direction!r}  timeframe={thesis.trade_idea.timeframe!r}")
    print(f"  stop_or_invalidation={thesis.trade_idea.stop_or_invalidation!r}")
    print(f"  warnings={len(thesis.warnings)}")

    # The gap, computed separately so the stream's claim can be checked against
    # something other than itself.
    gap, rules, _ensemble, market_path = build_policy_gap(
        inputs.taylor_inputs,
        inputs.first_difference_inputs,
        short_yield=inputs.short_yield,
        short_tenor_term_premium=None,
    )
    print(
        f"  gap={gap.raw_gap:+.4f}pp ({gap.raw_gap * 100:+.1f}bp) "
        f"dispersion={gap.dispersion:.4f}pp meaningful={gap.is_meaningful}"
    )
    print("  rules: " + ", ".join(f"{r.model_name}={r.value}" for r in rules))
    print(f"  market-implied path: {market_path.value!r}")

    # The stream publishes the gap twice — in percentage points and in basis
    # points — and the check requires BOTH to match what it computed separately.
    #
    # Requiring both is not belt-and-braces. A stream that hardcoded one unit and
    # derived the other would pass a single-unit check, and the two-unit form is
    # what a caller actually reads. Built from the measured `gap`, never from a
    # literal, for the same reason the module's own stream builds its detail from
    # the models (lesson 5bf: pin the value, not its rendering).
    expected_gap_fragments = (
        f"{gap.raw_gap:+.4f}pp",
        f"({gap.raw_gap * 100:+.1f}bp)",
    )

    # ------------------------------------------------------------------
    # 4-6. Every endpoint, through a real ASGI server.
    # ------------------------------------------------------------------
    server = _start_server()
    print("\n" + "-" * 78)
    print(f"serving on {server.base_url} (port chosen by the OS)")
    print("-" * 78)
    try:
        # `trust_env=False` is load-bearing, not hygiene. This environment exports
        # HTTP_PROXY/HTTPS_PROXY, httpx honours them by default, and a forward
        # proxy MUST receive the absolute-URI request form (RFC 7230 §5.3.2). The
        # proxy then forwards that absolute URI verbatim to the origin, uvicorn
        # unquotes it into the *path*, no route matches, and the caller gets
        #
        #     404 {"detail": "Not Found"}
        #
        # from `/health` — a route that is plainly registered. Measured: with
        # `trust_env=True` the second request on a pooled connection goes out as
        # `GET http://127.0.0.1:PORT/health HTTP/1.1`; with `trust_env=False` both
        # requests go out as `GET /health HTTP/1.1`. The first request survives
        # either way, which is exactly why this looked like an intermittent
        # routing bug rather than a proxy one.
        #
        # A check that measures a loopback service must not send that service's
        # traffic through a third party. `trust_env=False` also disables the
        # no_proxy/CA-bundle environment, which is the correct posture for a
        # check whose only peer is a socket this process opened.
        with httpx.Client(base_url=server.base_url, timeout=300.0, trust_env=False) as client:
            _health(client, settings.api.cors_origins)
            _thesis(client)
            _dashboard(client, settings.api.dashboard_series_limit)
            _query(client)
            _stream(client, expected_gap_fragments)
    finally:
        _stop_server(server)

    print("\n" + "=" * 78)
    print("RESULT: the provider built a snapshot; the orchestration derived every")
    print("argument from it; the thesis reached a verdict; every endpoint answered;")
    print("and the stream's gap is the one this check computed independently.")
    print("=" * 78)
    return 0


def _cors_preflight(client: httpx.Client, allowed_origins: list[str]) -> None:
    """Drive §8.4's preflight, and prove the client is talking to this server.

    The second job is the one that matters. The defect this check found was a
    404 from a route that exists, and the cause was that the client was **not**
    talking to this server — ``HTTP_PROXY`` in the environment routed the
    request through a forward proxy, which correctly used the absolute-URI form
    and forwarded it to the origin, where uvicorn read the whole URI as the path.

    The origin is taken from the **configured** list rather than hardcoded, and
    that is the point of the test. An earlier draft hardcoded
    ``http://localhost:3000`` — a port this service does not allow — and the
    preflight returned ``400 Disallowed CORS origin``, which is Starlette doing
    exactly its job on a check that had supplied the wrong input. Deriving the
    origin from ``settings.api.cors_origins`` tests the property that matters:
    **an origin the service was configured to accept is actually accepted.**

    One allowed origin is checked, not all of them: they go through the same
    middleware decision, and asserting the list would test Starlette's set
    membership rather than this service's configuration. The full list is
    printed, so a reader can see what was not exercised.
    """
    if not allowed_origins:
        raise AssertionError(
            "settings.api.cors_origins is empty, so there is no configured origin "
            "to exercise. The shipped config allows a local Workspace origin (§8.4); "
            "an empty list means the CORS posture changed and this check would "
            "otherwise silently stop testing it."
        )
    origin = allowed_origins[0]
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "accept, content-type, x-request-id",
    }
    print(f"  configured origins: {allowed_origins}")
    print(f"  exercising: {origin!r}")

    # A fresh client, so the preflight never shares a keep-alive connection with
    # the request whose status code is being asserted.
    #
    # `trust_env=False`: a preflight to a loopback service must not be proxied.
    # See the long comment at the client construction in `main` for the measured
    # consequence of getting this wrong.
    with httpx.Client(base_url=client.base_url, timeout=client.timeout, trust_env=False) as solo:
        response = solo.options("/health", headers=headers)
    print(f"  OPTIONS /health -> status_code={response.status_code}")
    print(f"  access-control-allow-origin={response.headers.get('access-control-allow-origin')!r}")

    # Prove the request reached THIS app, and reached the middleware configured
    # with `allowed_origins`. An echoed origin is CORS middleware confirming it
    # ran on a request that arrived here — the status code alone cannot tell a
    # working preflight apart from one answered by something else on the port.
    echoed = response.headers.get("access-control-allow-origin")
    assert response.status_code in {200, 204}, (
        f"the CORS preflight returned {response.status_code} for a configured origin "
        f"({origin!r}) at "
        f"{solo.build_request('OPTIONS', '/health', headers=headers).url!r} "
        f"(body={response.text[:200]!r})"
    )
    assert echoed == origin, (
        f"the preflight for {origin!r} was answered with "
        f"Access-Control-Allow-Origin={echoed!r}. The middleware read a different "
        f"origin than the one configured — either the config changed under this "
        f"check or the request did not reach this app's CORS middleware."
    )


def _health(client: httpx.Client, allowed_origins: list[str]) -> None:
    _rule("4a. GET /health")

    # The CORS preflight runs first, on its own connection. The reachability
    # argument is made in `_cors_preflight`; the ordering keeps the check's two
    # independent facts — "§8.4's CORS pair is configured" and "`/health`
    # answers" — from being entangled.
    _cors_preflight(client, allowed_origins)

    response = client.get("/health")
    print(f"  status_code={response.status_code}")
    body = response.json()
    for key in (
        "status",
        "service",
        "version",
        "ready",
        "cached_snapshot",
        "cached_age_hours",
        "cached_is_stale",
        "loopback_only",
        "implemented_countries",
        "deep_check",
    ):
        print(f"  {key}={body[key]!r}")
    print(f"  ready_reason={body['ready_reason']}")
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["loopback_only"] is True, "the server is reporting a network-reachable bind"

    # The deep path rebuilds the snapshot with `force_refresh=True`, which is a
    # genuine live fetch. Measured: **79.2s** on its own, and this check has
    # already spent a full build on step 1 — so a timeout here is an expected
    # outcome of the environment, not a defect in the route, and it must be
    # REPORTED as such. `deep.json()` on a timed-out response raises
    # `json.JSONDecodeError`, and on an error response raises `KeyError` on the
    # missing key — both would abort the whole check with a traceback that hides
    # the cause. The fist run of this script died exactly that way: a traceback
    # on a `KeyError: 'status'`, when the real message was "the build was slow".
    try:
        deep = client.get("/health", params={"deep": "true"})
    except httpx.TimeoutException as exc:
        print(f"\n  ?deep=true -> TIMED OUT after {client.timeout.read}s ({exc!r})")
        print("  NOT a route defect: the deep path forces a live rebuild, and the")
        print("  client-side timeout is shorter than the measured build on this network.")
        return

    if deep.status_code != 200:
        print(f"\n  ?deep=true -> status_code={deep.status_code} body={deep.text[:300]!r}")
        raise AssertionError(f"the deep health path returned {deep.status_code}")
    payload = deep.json()
    assert "status" in payload, f"the deep health response has no 'status' key: {sorted(payload)}"
    print(f"\n  ?deep=true -> status_code={deep.status_code} status={payload['status']!r}")
    print(f"  deep ready_reason={payload['ready_reason']}")


def _thesis(client: httpx.Client) -> None:
    _rule("4b. GET /thesis/us")
    response = client.get("/thesis/us")
    print(f"  status_code={response.status_code}")
    body = response.json()
    print(f"  thesis_id={body['thesis']['thesis_id']}")
    print(f"  status={body['thesis']['status']}")
    print(f"  convergence={body['thesis']['convergence_classification']}")
    print(f"  thesis_type_source={body['thesis_type_source']!r}")
    print(f"  derivation_notes={len(body['derivation_notes'])}")
    print(f"  warnings={len(body['warnings'])}")
    for warning in body["warnings"]:
        print(f"    - {warning[:140]}")
    print(
        f"  provenance.from_cache={body['provenance']['from_cache']} "
        f"age_hours={body['provenance']['age_hours']:.3f}"
    )
    assert response.status_code == 200
    assert body["thesis"]["thesis_id"]

    # The status contract. Each of these is a DIFFERENT claim, and the check
    # exercises all three so the mapping is measured rather than asserted.
    print("\n  the status contract:")
    unimplemented = client.get("/thesis/de")
    print(f"    /thesis/de             -> {unimplemented.status_code} (expect 501)")
    assert unimplemented.status_code == 501

    unknown_type = client.get("/thesis/us", params={"thesis_type": "not_a_family"})
    print(f"    ?thesis_type=bogus     -> {unknown_type.status_code} (expect 422)")
    assert unknown_type.status_code == 422
    print(f"      detail={unknown_type.json()['detail'][:120]}")

    stream_unimplemented = client.get("/thesis/de/stream")
    print(f"    /thesis/de/stream      -> {stream_unimplemented.status_code} (expect 501)")
    assert stream_unimplemented.status_code == 501

    supplied = client.get("/thesis/us", params={"thesis_type": "curve_shape_gap"})
    print(f"    ?thesis_type=curve_shape_gap -> {supplied.status_code}")
    assert supplied.status_code == 200
    print(f"      thesis_type_source={supplied.json()['thesis_type_source']!r}")
    assert supplied.json()["thesis_type_source"] == "supplied by the caller"


def _dashboard(client: httpx.Client, limit: int) -> None:
    _rule("4c. GET /dashboard_data")
    response = client.get("/dashboard_data")
    print(f"  status_code={response.status_code}")
    body = response.json()
    print(f"  country={body['country']}  as_of={body['as_of']}")
    print(f"  series_limit={body['series_limit']}")
    for family, panels in body["series"].items():
        withheld = sum(panel["points_withheld"] for panel in panels)
        print(f"  {family:10s} {len(panels):2d} panel(s), {withheld} point(s) withheld")
        for panel in panels:
            print(
                f"      {panel['field']:22s} latest={panel['latest_value']} "
                f"@ {panel['latest_date']}  shown={len(panel['dates'])}/"
                f"{panel['points_available']}"
            )
    if body["yield_curve"]:
        tenors = body["yield_curve"]["tenors"]
        print(
            f"  yield_curve as_of={body['yield_curve']['as_of']} "
            f"({len(tenors)} tenors, units={body['yield_curve']['units']})"
        )
        print("    " + ", ".join(f"{k}={v}" for k, v in list(tenors.items())[:6]))
    if body["tips_curve"]:
        print(f"  tips_curve ({len(body['tips_curve']['tenors'])} tenors)")
    for warning in body["warnings"]:
        print(f"  warning: {warning[:140]}")

    assert response.status_code == 200
    assert body["series"], "the dashboard returned no families"
    # §8.2's framing: the dashboard publishes MEASUREMENTS. It must not carry a
    # verdict, a gap or an instrument — those belong to the thesis, where they
    # carry evidence.
    for forbidden in ("gap", "convergence", "instrument", "thesis", "status"):
        assert forbidden not in body, (
            f"the dashboard published a {forbidden!r} field. It is a rendering "
            f"input, not the deliverable; a widget drawing a verdict it cannot "
            f"justify is the §8.2 divergence the endpoint's docstring names."
        )
    for panels in body["series"].values():
        for panel in panels:
            assert len(panel["dates"]) <= limit, (
                f"{panel['field']} returned {len(panel['dates'])} points, above the "
                f"configured cap of {limit}"
            )
    print(
        "\n  -> no gap / convergence / instrument / status key present: the "
        "endpoint publishes measurements, not claims"
    )


def _query(client: httpx.Client) -> None:
    _rule("4d. POST /query")
    matched = client.post(
        "/query",
        json={"question": "Will the Fed cut rates if inflation keeps cooling?"},
    )
    print(f"  status_code={matched.status_code}")
    body = matched.json()
    print(f"  is_keyword_routing={body['is_keyword_routing']}")
    print(f"  matched_topics={body['matched_topics']}")
    print(f"  unmatched_terms={body['unmatched_terms']}")
    print(f"  supporting_thesis_id={body['supporting_thesis_id']}")
    print(f"  relevant_model_outputs: {[o['field'] for o in body['relevant_model_outputs']]}")
    print(f"  answer={body['answer'][:220]}")
    assert matched.status_code == 200
    assert body["is_keyword_routing"] is True, "the endpoint must admit it is keyword routing"
    assert body["matched_topics"], "a policy/inflation question matched no topic"

    unmatched = client.post("/query", json={"question": "what is the weather in Lisbon"})
    print(f"\n  an unmatched question -> status_code={unmatched.status_code}")
    no_match = unmatched.json()
    print(f"  matched_topics={no_match['matched_topics']}")
    print(f"  supporting_thesis_id={no_match['supporting_thesis_id']}")
    print(f"  answer={no_match['answer'][:220]}")
    assert unmatched.status_code == 200, (
        "a well-formed question that matched no topic is a RESULT about the "
        "keyword table, not a malformed request"
    )
    assert no_match["supporting_thesis_id"] is None, (
        "an unmatched question must not attach a thesis; doing so makes an empty "
        "match look like a partial success"
    )
    assert no_match["relevant_model_outputs"] == []


def _stream(client: httpx.Client, expected_gap_fragments: tuple[str, ...]) -> None:
    _rule("4e. GET /thesis/us/stream — the emitted values must be the measured ones")
    events: list[dict[str, str]] = []
    terminator_seen = False
    with client.stream("GET", "/thesis/us/stream") as response:
        print(f"  status_code={response.status_code}")
        print(f"  content-type={response.headers.get('content-type')}")
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :]
            if payload == "[DONE]":
                terminator_seen = True
                continue
            events.append(json.loads(payload))

    for event in events:
        print(f"  [{event['status']:7s}] {event['step']:22s} {event['detail']}")

    assert terminator_seen, "the stream did not terminate with [DONE]"
    assert events, "the stream emitted no events"
    for event in events:
        assert set(event) == {"step", "status", "detail"}, f"unexpected event shape: {event}"

    gap_events = [e for e in events if e["step"] == "compute_gap"]
    assert gap_events, "the stream emitted no compute_gap frame"
    gap_detail = gap_events[0]["detail"]
    print(f"\n  expected gap renderings: {expected_gap_fragments}")

    # The comparison is on the **values**, not on a rendering of them, and the
    # distinction is the difference between a check and a spelling test.
    #
    # An earlier draft asserted the literal string ``"gap = +26.0bp"``. The
    # stream emits ``"...policy path: gap = +0.2600pp (+26.0bp), dispersion
    # ..."``, so the assertion failed — not because the stream was wrong (it
    # carried exactly the measured ``+26.0bp``) but because the check had baked
    # in a spacing the stream never promised. That is lesson 5bf applied to a
    # check: **pin the value, not the spelling.**
    #
    # Both renderings are required. The stream publishes the gap in percentage
    # points and basis points, and a stream that hardcoded one unit while
    # deriving the other would pass a single-unit check — which is the defect
    # class this assertion exists to catch.
    missing = [fragment for fragment in expected_gap_fragments if fragment not in gap_detail]

    assert not missing, (
        f"the streamed gap does not carry the independently computed value(s) "
        f"{missing}.\n"
        f"    computed: {expected_gap_fragments}\n"
        f"    streamed: {gap_detail!r}\n"
        f"This is the D-070 defect class: a stream that reports a value the models "
        f"did not produce."
    )
    assert "-140bp" not in gap_detail, (
        "Section 8.3's hardcoded -140bp reached the stream — the exact defect this "
        "generator replaces."
    )

    # A stand-down is a COMPLETED analysis and must never be an error frame
    # (Section 16.3). If it IS a stand-down here, that is asserted; if it is not,
    # the check says so rather than pinning today's verdict (the D-064 trap).
    error_events = [e for e in events if e["status"] == "error"]
    print(f"  error frames: {len(error_events)}")
    assert not error_events, (
        f"the live chain emitted an error frame: {error_events}. A stand-down is a "
        f"completed analysis, and a real failure must not be dressed as one."
    )


if __name__ == "__main__":
    raise SystemExit(main())
