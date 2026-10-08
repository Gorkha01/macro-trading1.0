"""Fresh test suite for ``data_layer/schemas.py``.

The module had no dedicated test file; its behaviour was covered only in pieces
(``test_phase1_data_layer.py``, ``test_non_finite_values.py``,
``test_curve_finiteness_guard.py``). This pins the parts nothing else does:
the two schema *selectors* (``iter_scalar_series`` / ``iter_curves``), the
aggregate shape of ``assert_finite``'s error, ``extra="forbid"`` on all three
models, and the two corrected docstring claims.

Findings guarded here:
  * F-SCH-001 — ``YieldCurveSnapshot.tenors``'s description claimed
    ``allow_inf_nan=False`` "is expressed on the ANNOTATED ITEM type". There is
    no ``Annotated`` anywhere in the module and no ``allow_inf_nan`` on that
    field: the real guard is the ``_reject_unknown_tenors`` validator. A reader
    following the description would look for a constraint that does not exist.
  * F-SCH-002 — ``MacroDataSnapshot.data_quality_flags``'s description claimed
    "no model populates it from this snapshot-level list". False: ``gdp_nowcast``
    does. The SAME error as F-VAL-001, in a second place.
  * F-SCH-003 — ``decision_cutoff`` is declared, documented and tested but no
    ``src/`` code path reads it (recorded, not changed).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import macro_engine.data_layer.schemas as schemas
from macro_engine.data_layer.schemas import (
    CANONICAL_TENORS,
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)

TODAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _pt(d: date, v: float, series_id: str = "x") -> ObservationPoint:
    return ObservationPoint(observation_date=d, value=v, series_id=series_id, retrieved_at=NOW)


def _constructed(**overrides: object) -> MacroDataSnapshot:
    """A snapshot with non-finite values FORCED past field validation."""
    base: dict[str, object] = {"country": "us", "as_of": NOW}
    base.update(overrides)
    return MacroDataSnapshot.model_construct(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Construction contracts
# ---------------------------------------------------------------------------
def test_all_three_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ObservationPoint(observation_date=TODAY, value=1.0, series_id="x", nope=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        YieldCurveSnapshot(as_of=TODAY, tenors={"10yr": 4.0}, nope=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MacroDataSnapshot(country="us", nope=1)  # type: ignore[call-arg]


def test_observation_point_refuses_a_non_finite_value_at_construction() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError, match="finite number"):
            ObservationPoint(observation_date=TODAY, value=bad, series_id="x")


def test_release_timing_is_unknown_by_default_and_known_once_set() -> None:
    unknown = _pt(TODAY, 1.0)
    assert unknown.release_datetime is None
    assert unknown.has_known_release_timing is False
    known = ObservationPoint(observation_date=TODAY, value=1.0, series_id="x", release_datetime=NOW)
    assert known.has_known_release_timing is True


def test_canonical_tenors_is_the_full_curve_from_1mo_to_30yr() -> None:
    assert CANONICAL_TENORS == (
        "1mo",
        "3mo",
        "6mo",
        "1yr",
        "2yr",
        "3yr",
        "5yr",
        "7yr",
        "10yr",
        "20yr",
        "30yr",
    )
    assert CANONICAL_TENORS[0] == "1mo" and CANONICAL_TENORS[-1] == "30yr"
    assert len(set(CANONICAL_TENORS)) == len(CANONICAL_TENORS)


def test_curve_refuses_an_unknown_tenor_and_a_non_finite_yield() -> None:
    with pytest.raises(ValidationError, match="Unrecognized tenor"):
        YieldCurveSnapshot(as_of=TODAY, tenors={"99yr": 4.0})
    with pytest.raises(ValidationError, match="Non-finite yield"):
        YieldCurveSnapshot(as_of=TODAY, tenors={"10yr": float("nan")})


def test_snapshot_fields_default_to_empty_not_none() -> None:
    snap = MacroDataSnapshot(country="us")
    assert snap.cpi_headline == [] and snap.fx_spot == {} and snap.data_quality_flags == []
    assert snap.yield_curve is None and snap.decision_cutoff is None


# ---------------------------------------------------------------------------
# The two selectors
# ---------------------------------------------------------------------------
def test_iter_scalar_series_returns_populated_list_fields_only() -> None:
    snap = MacroDataSnapshot(
        country="us",
        cpi_headline=[_pt(TODAY, 300.0)],
        cpi_core=[],  # empty -> excluded
        fx_spot={"eur": [_pt(TODAY, 1.1)]},  # dict-valued -> excluded
        yield_curve=YieldCurveSnapshot(as_of=TODAY, tenors={"10yr": 4.0}),  # curve -> excluded
    )
    assert [name for name, _ in snap.iter_scalar_series()] == ["cpi_headline"]


def test_iter_curves_returns_curve_fields_only() -> None:
    curve = YieldCurveSnapshot(as_of=TODAY, tenors={"10yr": 4.0})
    snap = MacroDataSnapshot(country="us", yield_curve=curve, cpi_headline=[_pt(TODAY, 1.0)])
    assert snap.iter_curves() == [("yield_curve", curve)]
    assert MacroDataSnapshot(country="us").iter_curves() == []


def test_iter_scalar_series_covers_every_field_the_schema_declares() -> None:
    """The pluggability contract: a new list field is picked up automatically."""
    non_list = {
        "country",
        "as_of",
        "decision_cutoff",
        "data_quality_flags",
        "field_sources",
        "yield_curve",
        "tips_yields",
        "fx_spot",
        "commodity_spot",
        "equity_index",
    }
    declared = {name for name in MacroDataSnapshot.model_fields if name not in non_list}
    snap = MacroDataSnapshot.model_construct(
        country="us",
        **{name: [_pt(TODAY, 1.0)] for name in declared},  # type: ignore[arg-type]
    )
    assert {name for name, _ in snap.iter_scalar_series()} == declared


# ---------------------------------------------------------------------------
# assert_finite
# ---------------------------------------------------------------------------
def test_assert_finite_passes_a_clean_snapshot() -> None:
    MacroDataSnapshot(
        country="us",
        cpi_headline=[_pt(TODAY, 300.0)],
        yield_curve=YieldCurveSnapshot(as_of=TODAY, tenors={"10yr": 4.0}),
    ).assert_finite()


def test_assert_finite_names_every_offender_not_just_the_first() -> None:
    snap = _constructed(
        cpi_headline=[
            ObservationPoint.model_construct(
                observation_date=TODAY,
                value=float("nan"),
                series_id="cpi_headline",
                retrieved_at=NOW,
            )
        ],
        cpi_core=[
            ObservationPoint.model_construct(
                observation_date=TODAY,
                value=float("inf"),
                series_id="cpi_core",
                retrieved_at=NOW,
            )
        ],
    )
    with pytest.raises(ValueError) as exc:
        snap.assert_finite()
    msg = str(exc.value)
    assert "2 non-finite observation(s)" in msg
    assert "cpi_headline" in msg and "cpi_core" in msg


def test_assert_finite_covers_the_curve_shape_too() -> None:
    """A nan tenor is the case validate_yield_curve cannot reject."""
    curve = YieldCurveSnapshot.model_construct(as_of=TODAY, tenors={"10yr": float("nan")})
    snap = _constructed(yield_curve=curve)
    with pytest.raises(ValueError, match="tenors\\[10yr\\]"):
        snap.assert_finite()


# ---------------------------------------------------------------------------
# F-SCH-001 / F-SCH-002 / F-SCH-003
# ---------------------------------------------------------------------------
def test_curve_tenors_description_does_not_claim_an_annotated_item_constraint() -> None:
    desc = YieldCurveSnapshot.model_fields["tenors"].description or ""
    assert "ANNOTATED ITEM" not in desc
    assert "_reject_unknown_tenors" in desc
    # The mechanism it names must actually exist in the module source.
    text = Path(schemas.__file__).read_text(encoding="utf-8")
    assert "_reject_unknown_tenors" in text
    assert "Annotated" not in text


def test_data_quality_flags_description_no_longer_claims_nothing_reads_it() -> None:
    desc = MacroDataSnapshot.model_fields["data_quality_flags"].description or ""
    assert "no model populates it" not in desc
    assert "gdp_nowcast" in desc


def test_the_two_places_that_describe_the_flag_penalty_agree() -> None:
    """F-VAL-001 and F-SCH-002 are the same claim in two files; both must name it."""
    import macro_engine.data_layer.validation as validation

    desc = MacroDataSnapshot.model_fields["data_quality_flags"].description or ""
    assert "gdp_nowcast" in desc
    assert "gdp_nowcast" in (validation.__doc__ or "")


def test_schemas_all_lists_the_three_models() -> None:
    assert schemas.__all__ == ["MacroDataSnapshot", "ObservationPoint", "YieldCurveSnapshot"]
