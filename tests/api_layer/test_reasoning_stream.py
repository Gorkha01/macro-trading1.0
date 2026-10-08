"""``api_layer/reasoning_stream.py`` — the trace frames, and three live defects.

The module exists so the reasoning trace emits **measured** values rather than
Section 8.3's hardcoded ones. It had no test file at all.

Live defects found BY this review:

* ``F-RSN-001`` — the ``compute_gap`` frame put the MARKET-implied path in the
  "Model-implied" slot and never showed the model-implied value at all.
* ``F-RSN-002`` — the terminator was yielded from a ``finally``, so a client
  disconnect raised ``RuntimeError: async generator ignored GeneratorExit``.
* ``F-RSN-003`` — the ``derive_inputs`` frame printed a count of every note
  followed by a five-name subset, as one clause.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from macro_engine.api_layer import reasoning_stream as rs
from macro_engine.models.contracts import ModelResult
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    ThesisStatus,
    TradeIdea,
)

AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


_ValueT = float | int | str | bool | dict[str, Any] | list[Any] | None


def _result(name: str, value: _ValueT) -> ModelResult:
    return ModelResult(
        model_name=name,
        country="us",
        as_of=AS_OF,
        value=value,
        confidence=0.5,
        interpretation="i",
        context="c",
        inputs_used=["x"],
    )


def _gap() -> MarketPricingGap:
    return MarketPricingGap(
        model_implied_value=3.10,
        market_implied_value=4.50,
        raw_gap=-1.40,
        dispersion=0.25,
        is_meaningful=True,
        interpretation="model below market",
    )


def _provenance(*, failed: dict[str, str] | None = None) -> object:
    from macro_engine.api_layer.snapshot_provider import SnapshotProvenance

    return SnapshotProvenance(
        country="us",
        as_of=AS_OF,
        generated_at=AS_OF,
        age_hours=0.5,
        age_exceeds_max=False,
        max_age_hours=24.0,
        from_cache=False,
        requested_fields=["a", "b"],
        succeeded_fields=["a"],
        failed_fields=failed or {},
        data_quality_flag_count=0,
        build_seconds=4.0,
    )


def _inputs() -> object:
    """A real ``ThesisInputs`` with the two rule records the frame needs."""
    from macro_engine.api_layer.orchestration import ThesisInputs
    from macro_engine.models.instrument_selection import ThesisType
    from macro_engine.models.policy_rules import FirstDifferenceInputs, TaylorRuleInputs
    from macro_engine.thesis_layer.builder import EconomyReads
    from macro_engine.thesis_layer.schemas import ProductionUniverse

    thesis_type: ThesisType = ThesisType.POLICY_PATH_GAP

    return ThesisInputs(
        reads=EconomyReads(
            growth=_result("output_gap", -1.0),
            inflation=_result("inflation_breadth_score", -0.5),
            labor=_result("labor_tightness_score", -0.8),
        ),
        taylor_inputs=TaylorRuleInputs(r_star=0.5, pi_current=3.0, output_gap=1.0),
        first_difference_inputs=FirstDifferenceInputs(
            i_prev=4.0, pi_current=3.0, output_gap_change=0.2
        ),
        short_yield=4.3,
        thesis_type=thesis_type,
        universe=ProductionUniverse(),
    )


def _thesis(*, warnings: list[str] | None = None) -> MacroThesis:
    return MacroThesis(
        thesis_id="us-2026-10-06-abcdef01",
        regime={"state": "late-cycle"},
        growth_view={"output_gap": -1.0},
        inflation_view={"breadth_score": -0.5},
        policy_view={"taylor": 3.2},
        market_pricing_gap=_gap(),
        convergence_classification=ConvergenceClassification.HIGH,
        trade_idea=TradeIdea(
            instrument="UST cash (2yr, 5yr, 10yr, 30yr)",
            direction="long",
            stop_or_invalidation="10y above 4.75%",
        ),
        status=ThesisStatus.DRAFT,
        warnings=warnings or [],
    )


def _stub_chain(monkeypatch: pytest.MonkeyPatch, thesis: MacroThesis) -> None:
    """Stub the four stages ``_reasoning_frames`` calls, keeping the frames real."""
    monkeypatch.setattr(rs, "get_snapshot", lambda country: (object(), _provenance()))
    monkeypatch.setattr(rs, "snapshot_to_thesis_inputs", lambda snapshot: _inputs())
    monkeypatch.setattr(
        rs,
        "build_policy_gap",
        lambda *a, **k: (
            _gap(),
            (
                _result("taylor_rule", 3.2),
                _result("balanced_approach_rule", 2.6),
                _result("first_difference_rule", 3.0),
            ),
            _result("policy_rule_ensemble", {"dispersion_pp": 0.25}),
            _result("derive_market_implied_policy_path", 4.5),
        ),
    )
    monkeypatch.setattr(rs, "build_us_macro_thesis", lambda *a, **k: thesis)


async def _drain(country: str = "us") -> list[str]:
    return [frame async for frame in rs.reasoning_step_generator(country)]


def _detail(frames: list[str], step: str, status: str = "done") -> str:
    """The detail of the LAST frame for ``step`` with ``status``.

    Last, not first: a step emits a ``started`` frame and then a ``done`` one, and
    the first match would return the placeholder text.
    """
    import json

    found: str | None = None
    for frame in frames:
        body = frame.removeprefix("data: ").strip()
        if not body.startswith("{"):  # the [DONE] terminator is not a JSON frame
            continue
        payload = json.loads(body)
        if payload["step"] == step and payload["status"] == status:
            found = str(payload["detail"])
    if found is None:
        raise AssertionError(f"no {step!r}/{status!r} frame in {frames}")
    return found


# ---------------------------------------------------------------------------
# (F-RSN-001) the compute_gap frame names the right side
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_gap_frame_labels_both_sides_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-RSN-001) ``market_path.value`` sat in the "Model-implied" slot.

    ``derive_market_implied_policy_path``'s own docstring calls it "A PROXY for
    the market-implied policy path", so the frame named the wrong side of the gap
    and never showed the model-implied value at all.
    """
    _stub_chain(monkeypatch, _thesis())
    frames = await _drain()
    detail = _detail(frames, "compute_gap")
    assert "Model-implied 3.1000pp" in detail, detail
    assert "market-implied 4.5000pp" in detail, detail
    assert "gap = -1.4000pp (-140.0bp)" in detail
    # The old wording, which showed the market side twice and the model side never.
    assert "vs market-implied policy path" not in detail


# ---------------------------------------------------------------------------
# (F-RSN-002) the terminator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_terminator_is_emitted_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_chain(monkeypatch, _thesis())
    frames = await _drain()
    assert frames[-1] == rs._TERMINATOR
    assert frames.count(rs._TERMINATOR) == 1


@pytest.mark.asyncio
async def test_a_client_disconnect_closes_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    """(F-RSN-002) A ``yield`` in a ``finally`` raises on ``aclose()``.

    MEASURED 2026-10-06: closing a suspended async generator that yields from a
    ``finally`` gives ``RuntimeError: async generator ignored GeneratorExit`` —
    and a client disconnect is exactly what makes the server call ``aclose()``.
    """
    _stub_chain(monkeypatch, _thesis())
    async with aclosing(rs.reasoning_step_generator("us")) as generator:
        first = await anext(generator)
        assert first.startswith("data: ")
    # `aclosing` calls `aclose()` on exit — which is what a client disconnect does.


@pytest.mark.asyncio
async def test_an_unhandled_stage_failure_still_terminates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer backstop: an error frame plus exactly one terminator."""
    _stub_chain(monkeypatch, _thesis())

    def boom(*a: object, **k: object) -> object:
        raise TypeError("a shape change nobody enumerated")

    monkeypatch.setattr(rs, "build_policy_gap", boom)
    frames = await _drain()
    assert any("internal" in f and "TypeError" in f for f in frames), frames
    assert frames[-1] == rs._TERMINATOR
    assert frames.count(rs._TERMINATOR) == 1


@pytest.mark.asyncio
async def test_a_handled_stage_failure_returns_without_a_second_terminator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-stage handler ``return``s; the terminator still comes from one place."""
    from macro_engine.api_layer.snapshot_provider import SnapshotUnavailableError

    _stub_chain(monkeypatch, _thesis())

    def boom(country: str) -> object:
        raise SnapshotUnavailableError("no source answered")

    monkeypatch.setattr(rs, "get_snapshot", boom)
    frames = await _drain()
    assert any("fetch_data" in f and "error" in f for f in frames)
    assert frames.count(rs._TERMINATOR) == 1


# ---------------------------------------------------------------------------
# (F-RSN-003) the derive_inputs count and list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_derived_count_and_the_list_are_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-RSN-003) "N input(s) derived: a, b, c" made the list read as complete."""
    _stub_chain(monkeypatch, _thesis())
    frames = await _drain()
    detail = _detail(frames, "derive_inputs")
    assert "input(s) derived; key measurements:" in detail, detail


# ---------------------------------------------------------------------------
# the stand-down path, and _fired
# ---------------------------------------------------------------------------


def test_fired_reads_the_trigger_off_the_published_warnings() -> None:
    """Read from the thesis, so the trace cannot disagree with what it describes."""
    from macro_engine.thesis_layer.no_trade import NO_TRADE_TRIGGER_LABELS

    warnings = [
        f"No trade [conflicted_signals] ({NO_TRADE_TRIGGER_LABELS['conflicted_signals']}): x"
    ]
    assert rs._fired(warnings) == ["conflicted_signals"]
    assert rs._fired(["an unrelated model warning"]) == []


@pytest.mark.asyncio
async def test_a_stand_down_is_a_done_frame_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 16.3: a stand-down is a COMPLETED analysis."""
    from macro_engine.thesis_layer.no_trade import NO_TRADE_TRIGGER_LABELS

    label = NO_TRADE_TRIGGER_LABELS["conflicted_signals"]
    thesis = _thesis(warnings=[f"No trade [conflicted_signals] ({label}): growth vs inflation"])
    _stub_chain(monkeypatch, thesis)
    frames = await _drain()
    assert "stood down by conflicted_signals" in _detail(frames, "build_thesis")
    assert not any('"status": "error"' in f for f in frames)


def test_the_triggers_are_the_ones_the_builder_can_emit() -> None:
    """``caller`` is deliberately absent: the builder only emits the three gates."""
    assert set(rs._TRIGGERS) == {"gap_below_dispersion", "conflicted_signals", "no_falsifier"}
    assert "caller" not in rs._TRIGGERS


# ---------------------------------------------------------------------------
# the route's boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unimplemented_country_is_a_501_before_the_stream_opens() -> None:
    """A client that has opened a stream cannot be told "wrong country"."""
    with pytest.raises(HTTPException) as excinfo:
        await rs.stream_thesis_reasoning("de")
    assert excinfo.value.status_code == 501


@pytest.mark.asyncio
async def test_us_returns_a_streaming_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = await rs.stream_thesis_reasoning("us")
    assert response.media_type == "text/event-stream"
    assert isinstance(response.body_iterator, AsyncIterator)
