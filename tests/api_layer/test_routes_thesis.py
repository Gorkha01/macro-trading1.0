"""``api_layer/routes_thesis.py`` — the thesis route, and one live defect.

``_http_status_for`` lives here and is exercised by ``test_strictness.py`` (the
file whose absence it named). The ROUTE — ``get_thesis`` and ``ThesisResponse`` —
had no test at all.

Live defect found BY this review:

* ``F-THS-001`` — ``thesis_type_source`` fell back to ``"supplied by the caller"``
  when the orchestration's derivation note was missing, crediting the caller with
  an analytical choice the API may have made. The sibling ``/query`` returns
  ``None`` for the same situation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from macro_engine.api_layer import routes_thesis as rt
from macro_engine.api_layer.orchestration import DerivationNote, OrchestrationError, ThesisInputs
from macro_engine.api_layer.snapshot_provider import (
    SnapshotProvenance,
    SnapshotUnavailableError,
)
from macro_engine.models.contracts import ModelResult
from macro_engine.models.instrument_selection import ThesisType
from macro_engine.models.policy_rules import (
    FirstDifferenceInputs,
    MarketPricingGap,
    TaylorRuleInputs,
)
from macro_engine.thesis_layer.builder import EconomyReads
from macro_engine.thesis_layer.schemas import (
    ConvergenceClassification,
    MacroThesis,
    ProductionUniverse,
    ThesisStatus,
    TradeIdea,
)

AS_OF = datetime(2026, 10, 6, tzinfo=UTC)


def _result(name: str, value: float | str) -> ModelResult:
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
        warnings=["a model warning"],
    )


def _provenance() -> SnapshotProvenance:
    return SnapshotProvenance(
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


def _inputs(*, type_note: bool = True, warnings: tuple[str, ...] = ()) -> ThesisInputs:
    notes = (
        (
            DerivationNote(
                name="thesis_type",
                value="policy_path_gap",
                source="assumed from api.default_thesis_type",
                window=None,
            ),
        )
        if type_note
        else ()
    )
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
        notes=notes,
        warnings=warnings,
    )


def _stub(monkeypatch: pytest.MonkeyPatch, inputs: ThesisInputs | None = None) -> None:
    monkeypatch.setattr(
        rt, "get_snapshot", lambda country, force_refresh=False: (object(), _provenance())
    )
    monkeypatch.setattr(
        rt, "snapshot_to_thesis_inputs", lambda snapshot, thesis_type=None: inputs or _inputs()
    )
    monkeypatch.setattr(rt, "build_us_macro_thesis", lambda *a, **k: _thesis())


# ---------------------------------------------------------------------------
# (F-THS-001) the type source must not be a guess
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_type_note_is_a_500_not_a_claim_about_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(F-THS-001) The fallback credited the caller with the API's own assumption.

    The orchestration appends the note unconditionally, so a missing one is a
    shape change — a defect in this service, which is what a 500 means here.
    """
    _stub(monkeypatch, _inputs(type_note=False))
    with pytest.raises(HTTPException) as excinfo:
        await rt.get_thesis("us", None, False)
    assert excinfo.value.status_code == 500
    assert "no 'thesis_type' derivation note" in excinfo.value.detail


@pytest.mark.asyncio
async def test_the_type_source_is_the_notes_own_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch)
    response = await rt.get_thesis("us", None, False)
    assert response.thesis_type_source == "assumed from api.default_thesis_type"


# ---------------------------------------------------------------------------
# the response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_response_carries_the_thesis_the_provenance_and_the_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, _inputs(warnings=("CURVE LEGS IGNORED",)))
    response = await rt.get_thesis("us", None, False)
    assert response.thesis.thesis_id == "us-2026-10-06-abcdef01"
    assert response.provenance.from_cache is False
    assert response.derivation_notes[0]["name"] == "thesis_type"
    assert set(response.derivation_notes[0]) == {"name", "value", "source", "window"}
    # The orchestration's disclosures travel on the wrapper.
    assert "CURVE LEGS IGNORED" in response.warnings


@pytest.mark.asyncio
async def test_the_warning_lists_are_deduplicated_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two lists overlap by design; a caller seeing a line twice would wonder what else was."""
    _stub(
        monkeypatch,
        _inputs(warnings=("SNAPSHOT PARTIAL: 1 of 2 field(s) failed to fetch (['b']).",)),
    )
    response = await rt.get_thesis("us", None, False)
    # Whatever the provenance emits, nothing appears twice.
    assert len(response.warnings) == len(set(response.warnings))


# ---------------------------------------------------------------------------
# the failure mapping, through the route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_thesis_type_is_a_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch)
    with pytest.raises(HTTPException) as excinfo:
        await rt.get_thesis("us", "nonsense", False)
    assert excinfo.value.status_code == 422
    assert "Section 22.3.1 defines" in excinfo.value.detail


@pytest.mark.asyncio
async def test_a_snapshot_failure_is_a_502(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(country: str, force_refresh: bool = False) -> object:
        raise SnapshotUnavailableError("no source answered")

    monkeypatch.setattr(rt, "get_snapshot", boom)
    with pytest.raises(HTTPException) as excinfo:
        await rt.get_thesis("us", None, False)
    assert excinfo.value.status_code == 502
    assert "NOT a no-trade verdict" in excinfo.value.detail


@pytest.mark.asyncio
async def test_an_unusable_series_is_a_502_naming_the_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(snapshot: object, thesis_type: object = None) -> object:
        raise OrchestrationError("pce_core is empty", fields=("pce_core",))

    _stub(monkeypatch)
    monkeypatch.setattr(rt, "snapshot_to_thesis_inputs", boom)
    with pytest.raises(HTTPException) as excinfo:
        await rt.get_thesis("us", None, False)
    assert excinfo.value.status_code == 502
    assert "pce_core" in excinfo.value.detail
    assert "the models never ran" in excinfo.value.detail


@pytest.mark.asyncio
async def test_a_builder_failure_is_a_500_not_a_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two 502 classes exist so that a 500 means what it says."""

    def boom(*a: object, **k: object) -> object:
        raise TypeError("the builder rejected its inputs")

    _stub(monkeypatch)
    monkeypatch.setattr(rt, "build_us_macro_thesis", boom)
    with pytest.raises(HTTPException) as excinfo:
        await rt.get_thesis("us", None, False)
    assert excinfo.value.status_code == 500
    assert "defect in this service" in excinfo.value.detail


@pytest.mark.asyncio
async def test_an_unmapped_exception_is_not_dressed_as_a_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(country: str, force_refresh: bool = False) -> object:
        raise KeyError("a shape change")

    monkeypatch.setattr(rt, "get_snapshot", boom)
    with pytest.raises(KeyError):
        await rt.get_thesis("us", None, False)


def test_the_mapping_docstring_states_that_it_raises() -> None:
    """(F-THS-002) The fallback is the load-bearing half, and it was undocumented.

    A reader of "Map an exception onto the status code that describes it" would
    assume a total function. The re-raise is what keeps a bug from being reported
    as a dependency failure, so it belongs in the docstring, not only in the code.
    """
    import inspect
    from pathlib import Path

    source = Path(inspect.getfile(rt)).read_text(encoding="utf-8")
    assert "It RAISES for an exception it does not map" in source
    assert "dressing it as a 502" in source
