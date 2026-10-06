"""The API layer's strictness surfaces: the shared status mapping, and ``/query``.

``routes_query.py``'s comment names THIS FILE as the thing that exercises the
shared mapping: *"it is underscore-private by this package's convention and
already the single shared mapping — ``tests/api_layer/test_strictness.py``
exercises it directly"*. MEASURED 2026-10-06: the file did not exist, so the claim
was false and ``_http_status_for`` had no direct test at all — only two endpoints
that route through it. **Seventh instance of the named-artifact class in the
campaign** (F-SIG-003, F-INV-002, F-NT-003, F-SCN-001, F-BLD-002, F-RSN-*).

It also pins ``/query``'s keyword routing, including the whole-token rule its own
comment illustrates with a false example.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from macro_engine.api_layer import routes_query as rq
from macro_engine.api_layer.orchestration import OrchestrationError
from macro_engine.api_layer.routes_thesis import _http_status_for
from macro_engine.api_layer.snapshot_provider import SnapshotUnavailableError
from macro_engine.models.contracts import ModelResult
from macro_engine.models.policy_rules import MarketPricingGap
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    ThesisStatus,
    TradeIdea,
)

AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


# ---------------------------------------------------------------------------
# the shared status mapping (the file this comment named)
# ---------------------------------------------------------------------------


def test_an_unimplemented_country_is_a_501() -> None:
    mapped = _http_status_for(NotImplementedError("only 'us'"), country="de")
    assert mapped.status_code == 501
    assert "Section 22.3" in mapped.detail


def test_a_snapshot_failure_is_a_502_and_says_it_is_not_a_no_trade() -> None:
    mapped = _http_status_for(SnapshotUnavailableError("no source"), country="us")
    assert mapped.status_code == 502
    assert "NOT a no-trade verdict" in mapped.detail


def test_an_orchestration_failure_is_a_502_and_names_the_fields() -> None:
    """The distinction from the snapshot case is in the message, not the code."""
    mapped = _http_status_for(
        OrchestrationError("cpi_core is empty", fields=("cpi_core", "pce_core")),
        country="us",
    )
    assert mapped.status_code == 502
    assert "cpi_core" in mapped.detail and "pce_core" in mapped.detail
    assert "the models never ran" in mapped.detail


def test_an_unmapped_exception_is_re_raised_not_dressed_as_a_dependency_failure() -> None:
    """The fallback: a bug must not be reported as "the source did not answer"."""
    original = TypeError("a shape change")
    with pytest.raises(TypeError) as excinfo:
        _http_status_for(original, country="us")
    assert excinfo.value is original


# ---------------------------------------------------------------------------
# /query's keyword routing
# ---------------------------------------------------------------------------


def test_the_tokeniser_strips_punctuation_and_lowercases() -> None:
    assert rq._tokenise("Will the Fed CUT rates?!") == ["will", "the", "fed", "cut", "rates"]


def test_matching_is_whole_token_not_substring() -> None:
    """The rule the ``_TOPIC_KEYWORDS`` note illustrates.

    The illustration it used to carry — *"recession" contains "session"* — is
    FALSE (measured: the real substring is "cession"). The rule is still right,
    and these are the examples that hold: "rate" is inside "moderate" and "cut"
    inside "executive", so a substring match would route both to `policy_rules`.
    """
    assert "session" not in "recession"
    assert "cession" in "recession"
    assert "rate" in "moderate" and "cut" in "executive"

    matched, _unmatched = rq._match_topics(rq._tokenise("a moderate executive"))
    assert matched == [], "no whole token is a keyword"


def test_the_substring_note_does_not_cite_a_false_example() -> None:
    """(F-QRY-001) The note's illustration — *"recession" contains "session"* — is FALSE.

    MEASURED: "session" is not a substring of "recession" (the real substring is
    "cession"), so the example illustrated nothing. The rule it defends is right;
    the correction cites examples that hold.
    """
    import inspect
    from pathlib import Path

    source = Path(inspect.getfile(rq)).read_text(encoding="utf-8")
    assert "route an unrelated question about a trading session" not in source
    assert "cession" in source


def test_matched_topics_are_in_declaration_order() -> None:
    matched, unmatched = rq._match_topics(rq._tokenise("jobs and the yield curve"))
    assert matched == ["labor", "curve"]  # declaration order, not question order
    assert unmatched == ["and", "the"]


def test_a_question_matching_nothing_is_an_empty_result_not_a_404() -> None:
    """The route exists and the request was well-formed."""
    matched, unmatched = rq._match_topics(rq._tokenise("what colour is the sky"))
    assert matched == []
    assert "sky" in unmatched


def test_the_projection_skips_fields_the_thesis_does_not_carry() -> None:
    thesis = _thesis()
    projected = rq._project(thesis, ("trade_idea", "not_a_real_field"))
    assert [entry["field"] for entry in projected] == ["trade_idea"]


# ---------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------


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


def _thesis() -> MacroThesis:
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
    )


def _inputs() -> object:
    from macro_engine.api_layer.orchestration import DerivationNote, ThesisInputs
    from macro_engine.models.instrument_selection import ThesisType
    from macro_engine.models.policy_rules import FirstDifferenceInputs, TaylorRuleInputs
    from macro_engine.thesis_layer.builder import EconomyReads
    from macro_engine.thesis_layer.schemas import ProductionUniverse

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
        thesis_type=ThesisType.POLICY_PATH_GAP,
        universe=ProductionUniverse(),
        notes=(
            DerivationNote(
                name="thesis_type",
                value="policy_path_gap",
                source="assumed from api.default_thesis_type",
            ),
        ),
        warnings=("a curve leg was ignored",),
    )


def _stub_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    from macro_engine.api_layer.snapshot_provider import SnapshotProvenance

    provenance = SnapshotProvenance(
        country="us",
        as_of=AS_OF,
        generated_at=AS_OF,
        age_hours=0.5,
        age_exceeds_max=False,
        max_age_hours=24.0,
        from_cache=False,
        data_quality_flag_count=0,
        build_seconds=4.0,
    )
    monkeypatch.setattr(
        rq, "get_snapshot", lambda country, force_refresh=False: (object(), provenance)
    )
    monkeypatch.setattr(
        rq, "snapshot_to_thesis_inputs", lambda snapshot, thesis_type=None: _inputs()
    )
    monkeypatch.setattr(rq, "build_us_macro_thesis", lambda *a, **k: _thesis())


@pytest.mark.asyncio
async def test_a_matched_question_returns_the_thesis_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_chain(monkeypatch)
    response = await rq.query(rq.QueryRequest(question="will the fed cut rates"), False)
    assert response.is_keyword_routing is True
    assert response.matched_topics == ["policy_rules"]
    assert response.supporting_thesis_id == "us-2026-10-06-abcdef01"
    assert {entry["field"] for entry in response.relevant_model_outputs} == {
        "policy_view",
        "market_pricing_gap",
    }
    # The orchestration's disclosures are published, not withheld.
    assert "a curve leg was ignored" in response.warnings
    assert response.thesis_type_source == "assumed from api.default_thesis_type"


@pytest.mark.asyncio
async def test_an_unmatched_question_is_a_200_with_no_thesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No thesis is built for a question nobody matched — it would attach an unrelated object."""
    _stub_chain(monkeypatch)
    response = await rq.query(rq.QueryRequest(question="what colour is the sky"), False)
    assert response.matched_topics == []
    assert response.relevant_model_outputs == []
    assert response.supporting_thesis_id is None
    assert "No topic matched" in response.answer


@pytest.mark.asyncio
async def test_an_unknown_thesis_type_is_a_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_chain(monkeypatch)
    with pytest.raises(HTTPException) as excinfo:
        await rq.query(rq.QueryRequest(question="the fed", thesis_type="nonsense"), False)
    assert excinfo.value.status_code == 422
    assert "unknown thesis_type" in excinfo.value.detail


@pytest.mark.asyncio
async def test_the_unmatched_note_does_not_claim_partial_retrieval_for_function_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-QRY-003) A natural question ALWAYS leaves its function words unmatched.

    So "the retrieval is partial" fired unconditionally — a disclosure that fires
    every time says nothing. The note reports the tokens and says what they may be.
    """
    _stub_chain(monkeypatch)
    response = await rq.query(rq.QueryRequest(question="will the fed cut rates"), False)
    assert "the retrieval is partial" not in response.answer
    assert "function word" in response.answer
    assert "'will'" in response.answer  # the tokens are still reported
