"""``/thesis/{country}/stream`` — the reasoning trace, with real numbers (Section 8.3).

What the spec's sample does, and why it cannot ship
---------------------------------------------------
Section 8.3 writes the steps as a literal list::

    {"step": "fetch_data", "status": "done", "detail": "Snapshot retrieved, 14 series"}
    {"step": "compute_gap", "status": "done", "detail": "... gap = -140bp"}
    {"step": "classify_convergence", "status": "done", "detail": "HIGH convergence ..."}
    {"step": "build_thesis", "status": "done", "detail": "Thesis assembled: long UST 2yr, ..."}

Every one of those four details is a number the models produce, typed into a
string. The stream would therefore **emitted identical text on every run** — a
live "thinking" trace that says the gap is -140bp on a day it is +38bp, and
"HIGH convergence" on a day the builder stood the sentence down.

This is the same defect class as the literals ``live_builder_check.py`` carried
(``0.2 / 0.3 / 0.1 / -0.4``): a plausible, precise, fabricated number that no
type checker and no schema can catch, because a string is a valid string. The
difference is that a streaming trace is *designed* to look live, which makes the
fabrication worse — the format itself asserts that these values were just
measured.

So the generator here runs the real chain and emits what it measured. Where the
spec's sample states a value, this states the same **kind** of value, computed:

==================================  ==============================================
spec's sample                       emitted here
==================================  ==============================================
``"14 series"``                     the real requested/succeeded/failed counts
``"9 models completed"``            the real count of reads + rules
``"gap = -140bp"``                  ``gap.raw_gap``, both of its sides and the
                                    dispersion, in bp
``"HIGH convergence"``              the real ``ConvergenceClassification``
``"long UST 2yr"``                  the real instrument and direction
==================================  ==============================================

The event shape is unchanged — ``{"step", "status", "detail"}`` — because that is
what OpenBB's AI SDK consumes, and the contract is the format, not the numbers.

Two additions the sample needs
------------------------------
* **A terminal ``error`` event.** The sample has no failure path at all; its
  generator cannot fail because it does nothing. A real generator that raised
  mid-stream would leave the client with a truncated trace and no way to tell
  truncation from completion, so every failure becomes a final event with
  ``status="error"`` followed by ``[DONE]``.
* **``[DONE]``.** An SSE client needs a terminator to distinguish "the stream
  ended" from "the connection dropped". Every event list ends with it.

Section 16.3 applies here too: a stand-down emits ``status="ok"`` steps
describing the gate that fired. It is not an error event, because "the models
agree there is no edge" is a completed analysis, not a failure.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from macro_engine.api_layer.orchestration import (
    OrchestrationError,
    snapshot_to_thesis_inputs,
)
from macro_engine.api_layer.snapshot_provider import SnapshotUnavailableError, get_snapshot
from macro_engine.config import get_settings
from macro_engine.data_layer.fed_funds_futures_client import (
    FedFundsFuturesCurve,
    FuturesCurveError,
    fetch_fed_funds_futures_curve,
)
from macro_engine.data_layer.openbb_client import OpenBBFetchError
from macro_engine.models.contracts import utc_now
from macro_engine.thesis_layer.builder import build_policy_gap, build_us_macro_thesis
from macro_engine.thesis_layer.no_trade import NO_TRADE_TRIGGER_LABELS, NoTradeTrigger

router = APIRouter(tags=["streaming"])

#: The SSE terminator. One definition, because the contract is that exactly one
#: reaches every stream that ended DELIBERATELY — and a test can bind it.
_TERMINATOR = "data: [DONE]\n\n"

#: The gates that can actually stand a thesis down in this pipeline. ``caller`` is
#: deliberately absent: it exists so a stand-down outside the three documented
#: gates is *sayable* (see ``no_trade.NoTradeTrigger``), but ``build_us_macro_thesis``
#: only ever emits these three, and this trace reads the builder's output.
_TRIGGERS: tuple[NoTradeTrigger, ...] = (
    "gap_below_dispersion",
    "conflicted_signals",
    "no_falsifier",
)


def _event(step: str, status: str, detail: str) -> str:
    """One SSE frame. ``data: <json>\\n\\n`` — the format the spec fixes."""
    return f"data: {json.dumps({'step': step, 'status': status, 'detail': detail})}\n\n"


def _fired(thesis_warnings: list[str]) -> list[NoTradeTrigger]:
    """Which stand-down gate fired, read off the published warnings.

    Read from the thesis rather than recomputed from the gate objects, so the
    trace cannot disagree with the thesis it is describing: if the builder said
    Q7, the trace says Q7. A second computation would be a second definition of
    the same fact, which is the D-067 attribution defect in the trace position.
    """
    return [
        trigger
        for trigger in _TRIGGERS
        if any(NO_TRADE_TRIGGER_LABELS[trigger] in w for w in thesis_warnings)
    ]


def _fetch_futures_curve() -> tuple[FedFundsFuturesCurve | None, str]:
    """Fetch the ZQ curve for the market leg — FAIL-SAFE, never raises.

    Section 22.5's replacement: the market leg should be the market's own
    Fed-funds-futures-implied rate, not the Phase 1-4 term-premium proxy. This
    is the LIVE SUPPLY of that curve — the step the reader and the builder chain
    were built to accept (``derive_market_implied_policy_path``,
    ``build_policy_gap``, ``build_us_macro_thesis`` all take an optional curve).

    **Why it returns a status string instead of raising.** A network read can
    fail for reasons that say nothing about the thesis (the provider is down, a
    rate limit, a cold socket). The chosen behaviour is the operator's: use the
    futures curve when it is available, and **fall back to the proxy with a loud,
    on-trace warning** when it is not — so a futures outage degrades the market
    leg but never breaks a live thesis run. The status is returned rather than
    logged so the reasoning trace can name which leg the run actually used; a
    silent fallback would publish a proxy number the client believed was a
    futures-implied one (the "field describing a computation that did not
    happen" failure, one layer up).

    ``OpenBBFetchError`` and ``FuturesCurveError`` are caught specifically, not
    ``Exception``: the first is a transport failure, the second is the client's
    own refusal (empty curve, too few plausible expirations). Any OTHER exception
    is a bug in the client and should surface, not be papered over as "no data".
    """
    as_of = utc_now().date()
    try:
        curve = fetch_fed_funds_futures_curve(as_of=as_of)
    except (FuturesCurveError, OpenBBFetchError) as exc:
        return None, (
            f"fed-funds-futures curve unavailable ({type(exc).__name__}); the "
            f"market leg falls back to the Section 22.5 term-premium PROXY: {exc}"
        )
    return curve, (
        f"fed-funds-futures curve supplied ({len(curve.expirations)} usable "
        f"expiration(s), front {curve.expirations[0].implied_rate_pct:.3f}%"
        + (f", {curve.rows_rejected} row(s) rejected" if curve.rows_rejected else "")
        + ")"
    )


async def reasoning_step_generator(country: str) -> AsyncGenerator[str, None]:
    """Run the real chain, emitting what each stage actually measured.

    The steps are yielded as the work happens rather than pre-computed and
    replayed: ``build_snapshot`` is synchronous and slow (measured D-087.19:
    a FIRST build is ~46-81s because cold start dominates, a SUBSEQUENT build
    ~4s), so the ``fetch_data``
    ``started`` event is emitted *before* the call and the client sees motion
    during the wait. Pre-computing would make the trace an animation over a
    frozen result — the same fabrication as the hardcoded literals, one layer up.

    The outer guard, and why the per-step handlers are not enough
    -------------------------------------------------------------
    Each slow stage (``get_snapshot``, ``snapshot_to_thesis_inputs``,
    ``build_us_macro_thesis``) has its own ``except`` that yields an ``error``
    frame. Between and after them sit calls that were **not** guarded:
    ``build_policy_gap`` (which raises ``TypeError`` by design when
    ``derive_market_implied_policy_path`` changes shape and ``ValueError`` on a
    zero gap), every ``_event(...)`` frame-formatting call, and the attribute
    reads that build each ``detail`` string. If any of those raises, the async
    generator propagates mid-stream and the client receives a **truncated SSE
    body with no terminal event** — contradicting this module's own contract
    that ``[DONE]`` always ends the stream.

    So the whole body runs inside one outer ``try``. The terminator is emitted on
    the normal path and on the handled-error path — **not** from a ``finally``:
    ``yield`` inside a ``finally`` is unsafe here, because a client disconnect
    makes the server call ``aclose()``, which throws ``GeneratorExit`` into the
    generator, and a ``yield`` in response raises
    ``RuntimeError: async generator ignored GeneratorExit`` (measured
    2026-10-06). ``GeneratorExit`` derives from ``BaseException``, so the
    ``except Exception`` backstop does not catch it and the ``else`` clause does
    not run — the generator then closes cleanly, with no terminator, because
    there is no longer a client to receive one.

    The per-stage handlers stay because they produce *specific* messages
    ("country not implemented", "field X could not be read"); the outer handler is
    the backstop for failures nobody enumerated.

    What the guard does and does not cover. An exception raised inside
    ``_reasoning_frames`` is caught here and becomes an ``internal/error`` frame.
    An exception raised *inside the ``except`` body itself* — i.e. by the
    ``_event(...)`` call that formats the failure message — would not be, and in
    that case no terminator is emitted at all, so the client sees a truncated
    stream. That is the residual risk, stated rather than papered over: the
    alternative (a ``finally``) is the thing that provably cannot work.

    A note on the heartbeat: no keepalive frame is emitted here. An SSE
    ``: comment`` line would keep an intermediary from dropping an idle
    connection, but it cannot be sent while the synchronous build holds the
    event loop — the frame would be buffered, not flushed. Fixing that is a
    concurrency change (move the build off the loop), not a formatting one, and
    adding a heartbeat that provably cannot flush would be a comment asserting a
    guarantee the code does not provide.
    """
    try:
        async for frame in _reasoning_frames(country):
            yield frame
    except Exception as exc:  # the contract backstop, see docstring
        # Reaching here means a stage failed that no per-stage handler covered.
        # The message names the exception type because a bare repr can be huge
        # (pydantic ValidationErrors) and this frame must stay a single line.
        yield _event(
            "internal",
            "error",
            f"the reasoning chain failed outside a handled stage: "
            f"{type(exc).__name__}: {str(exc)[:300]}",
        )
        yield _TERMINATOR
    else:
        # The deliberate end. NOT a `finally`: see the docstring — a `yield` in a
        # `finally` raises `RuntimeError: async generator ignored GeneratorExit`
        # when the server closes the generator because the client disconnected
        # (measured 2026-10-06). `GeneratorExit` is a `BaseException`, so it skips
        # both this `else` and the `except` above and the generator closes cleanly.
        yield _TERMINATOR


async def _reasoning_frames(country: str) -> AsyncGenerator[str, None]:
    """The per-stage trace. Split out so the outer guard can wrap it whole."""
    yield _event("fetch_data", "started", f"Loading the {country} macro snapshot via OpenBB")

    try:
        snapshot, provenance = get_snapshot(country)
    except NotImplementedError as exc:
        yield _event("fetch_data", "error", f"country '{country}' is not implemented: {exc}")
        return
    except SnapshotUnavailableError as exc:
        yield _event("fetch_data", "error", f"the snapshot could not be built: {exc}")
        return

    if provenance.from_cache:
        detail = (
            f"Snapshot reused from cache, {provenance.age_hours:.1f}h old "
            f"({len(provenance.succeeded_fields)} fields)"
        )
    else:
        seconds = provenance.build_seconds or 0.0
        detail = (
            f"Snapshot built in {seconds:.1f}s — "
            f"{len(provenance.succeeded_fields)} field(s) fetched, "
            f"{len(provenance.failed_fields)} failed"
        )
    yield _event("fetch_data", "done", detail)

    if provenance.failed_fields:
        yield _event(
            "fetch_data",
            "warning",
            f"{len(provenance.failed_fields)} field(s) unavailable: "
            f"{sorted(provenance.failed_fields)} — models reading them will refuse "
            f"rather than substitute",
        )
    if provenance.age_exceeds_max:
        yield _event(
            "fetch_data",
            "warning",
            f"Snapshot is STALE: {provenance.age_hours:.1f}h old, beyond the "
            f"{provenance.max_age_hours:.1f}h limit",
        )

    yield _event(
        "derive_inputs",
        "started",
        "Deriving the builder's inputs from the snapshot (no literals)",
    )
    try:
        inputs = snapshot_to_thesis_inputs(snapshot)
    except OrchestrationError as exc:
        yield _event(
            "derive_inputs",
            "error",
            f"a required series could not be read (fields={list(exc.fields)}): {exc}",
        )
        return
    yield _event(
        "derive_inputs",
        "done",
        # The COUNT is every note; the list is the five a reader most wants to
        # check. The frame used to print them as one clause — "N input(s)
        # derived: a, b, c" — so the count and the list disagreed and the list
        # read as if it were complete (measured 2026-10-06).
        f"{len(inputs.notes)} input(s) derived; key measurements: "
        + ", ".join(
            f"{n.name}={n.value}"
            for n in inputs.notes
            if n.name
            in {
                "short_yield",
                "pi_current",
                "initial_claims_4wk_avg_change_pct",
                "jolts_openings_yoy_pct",
                "jolts_quits_level_percentile",
            }
        ),
    )

    yield _event("run_models", "started", "Running the policy rules and the gap")
    # Section 22.5: supply the market leg with a real Fed-funds-futures curve,
    # failing safe to the term-premium proxy on any fetch trouble. The status is
    # emitted on the trace so the client can see WHICH leg this run used — a
    # silent fallback would let a proxy number pass for a futures-implied one.
    futures_curve, curve_detail = _fetch_futures_curve()
    yield _event(
        "run_models",
        "done" if futures_curve is not None else "warning",
        curve_detail,
    )
    gap, rules, _ensemble, _market_path = build_policy_gap(
        inputs.taylor_inputs,
        inputs.first_difference_inputs,
        short_yield=inputs.short_yield,
        short_tenor_term_premium=None,
        futures_curve=futures_curve,
    )
    rule_values = {rule.model_name: rule.value for rule in rules}
    yield _event(
        "run_models",
        "done",
        f"{len(rules)} policy rule(s) evaluated: "
        + ", ".join(f"{name}={value}" for name, value in rule_values.items()),
    )
    yield _event(
        "compute_gap",
        "done",
        # Both sides come from the GAP's own fields, which is what the gap was
        # built from. `market_path.value` used to sit in the "Model-implied" slot
        # — and it IS the market-implied path (its own docstring: "A PROXY for the
        # market-implied policy path") — so the frame named the wrong side of the
        # gap and never showed the model-implied value at all (measured
        # 2026-10-06). A trace that mislabels a live number does the same harm as
        # one that fabricates it.
        f"Model-implied {gap.model_implied_value:.4f}pp vs market-implied "
        f"{gap.market_implied_value:.4f}pp: gap = {gap.raw_gap:+.4f}pp "
        f"({gap.raw_gap * 100:+.1f}bp), dispersion {gap.dispersion:.4f}pp, "
        f"meaningful={gap.is_meaningful}",
    )

    yield _event("build_thesis", "started", "Running the gate chain and building the thesis")
    try:
        thesis = build_us_macro_thesis(
            inputs.reads,
            inputs.taylor_inputs,
            inputs.first_difference_inputs,
            thesis_type=inputs.thesis_type,
            universe=inputs.universe,
            country=inputs.country,
            boe_inputs=inputs.boe_inputs,
            eu_inputs=inputs.eu_inputs,
            short_yield=inputs.short_yield,
            futures_curve=futures_curve,
            regime=inputs.regime,
        )
    except Exception as exc:
        yield _event("build_thesis", "error", f"the builder raised {type(exc).__name__}: {exc}")
        return

    fired = _fired(thesis.warnings)
    if fired:
        # A stand-down is a COMPLETED analysis, so its steps are ok/`done` with
        # the gate named — never an error event (Section 16.3).
        yield _event(
            "classify_convergence",
            "done",
            f"convergence={thesis.convergence_classification.value}",
        )
        yield _event(
            "build_thesis",
            "done",
            f"Thesis stood down by {', '.join(fired)}: status={thesis.status.value}, "
            f"instrument={thesis.trade_idea.instrument!r}, "
            f"{len(thesis.warnings)} warning(s) carried",
        )
    else:
        yield _event(
            "classify_convergence",
            "done",
            f"convergence={thesis.convergence_classification.value}",
        )
        yield _event(
            "build_thesis",
            "done",
            f"Thesis assembled: status={thesis.status.value}, "
            f"instrument={thesis.trade_idea.instrument!r}, "
            f"direction={thesis.trade_idea.direction!r}, "
            f"timeframe={thesis.trade_idea.timeframe!r}, "
            f"thesis_id={thesis.thesis_id}",
        )

    # No trailing ``[DONE]`` here: ``reasoning_step_generator``'s ``finally``
    # emits exactly one terminator on every exit path. Yielding it here as well
    # would put two on the success path.


@router.get("/{country}/stream")
async def stream_thesis_reasoning(country: str) -> StreamingResponse:
    """The reasoning trace as SSE, running the real chain.

    Country validation happens **before** the stream starts, so an unimplemented
    country gets a 501 rather than a 200 whose body contains one error event. A
    client that has already opened a stream and is parsing frames cannot be told
    "you asked for the wrong thing" — by then it has committed to reading events.

    The check reads ``settings.country.implemented`` (the same list the snapshot
    builder and ``snapshot_to_thesis_inputs`` gate on) rather than a literal
    ``"us"``, so a country that has earned the label — gb, added by the first
    multi-country increment — streams, while de/jp still refuse here.
    """
    if country not in get_settings().country.implemented:
        raise HTTPException(
            status_code=501,
            detail=(
                f"country '{country}' is not implemented (Section 22.3); implemented: "
                f"{sorted(get_settings().country.implemented)}. Validated before the "
                f"stream opens so the caller gets a status code rather than an error "
                f"frame."
            ),
        )
    return StreamingResponse(
        reasoning_step_generator(country),
        media_type="text/event-stream",
    )
