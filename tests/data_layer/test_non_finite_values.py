"""Non-finite values must never enter the data path (Section 21.0 rule 2).

Why this file exists
--------------------
An audit against the Phase 0-4 directive found that a **non-finite float is
reachable from the provider into ``MacroDataSnapshot``**, because:

1. ``openbb_client._normalise_frame`` calls ``dropna`` then ``pd.to_numeric``.
   ``dropna`` removes nulls; it does **not** remove ``inf`` or ``nan`` produced
   by coercion, and ``pd.to_numeric`` preserves both.
2. ``ObservationPoint.value: float`` is a bare float. Pydantic v2 accepts
   ``nan`` / ``inf`` for a plain ``float`` unless ``allow_inf_nan=False`` is
   set, and it was not set here.
3. ``validate_observations`` checks *ranges*, not finiteness. A range check is
   written as ``value < min`` / ``value > max``, and **every comparison against
   ``nan`` is False**, so a NaN is reported CLEAN by the quality gate for every
   series under every bound. (``+inf``/``-inf`` are caught only when the
   relevant bound is supplied — and 2 of the registry's 45 series declare no
   ``plausible_range`` at all.)

Why that is the defect the directive names
-------------------------------------------
The directive's CRITICAL RULE is that missing data must never become ``0``,
``False``, neutral, unchanged, or an invented default. A NaN is **worse than a
missing value**, because it is not absent: every downstream guard sees a
`float` that is present and testable, so nothing degrades to
``INSUFFICIENT_DATA`` — the model proceeds, computes ``nan``, and formats it
into prose as the literal string ``"nan"``. That is fabricated reasoning built
on absent data, which is precisely the prohibited outcome.

What the fix must preserve
---------------------------
A **missing** value (``None``, null, absent row) must keep behaving as it does
today: ``dropna`` drops it, and a series that is empty raises
``OpenBBFetchError`` rather than returning an empty-but-successful frame. The
fix rejects only the *non-finite* case, which is a distinct and additional
failure mode.

These are regression tests: they are RED before the guards exist and must stay
GREEN afterwards.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint
from macro_engine.data_layer.validation import Severity, validate_observations

NON_FINITE = [float("nan"), float("inf"), float("-inf")]


# ---------------------------------------------------------------------------
# 1. The schema must refuse a non-finite value at construction.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", NON_FINITE)
def test_observation_point_rejects_non_finite_value(bad: float) -> None:
    """A non-finite observation value is not a value — it must be refused.

    Measured before the fix: ``nan``/``inf``/``-inf`` were all ACCEPTED, because
    ``value: float`` carries no finiteness constraint in Pydantic v2.
    """
    with pytest.raises(ValidationError):
        ObservationPoint(
            observation_date=date(2026, 8, 1),
            value=bad,
            series_id="CPIAUCSL",
        )


def test_observation_point_still_accepts_finite_values() -> None:
    """The guard must not reject legitimate data, including negatives and zero.

    A signed series (spread, change, net balance) legitimately carries negative
    and zero values, so finiteness is the only rejection criterion that is
    correct here.
    """
    for good in (334.131, 0.0, -0.52, -1200.0):
        point = ObservationPoint(
            observation_date=date(2026, 8, 1), value=good, series_id="CPIAUCSL"
        )
        assert point.value == good


# ---------------------------------------------------------------------------
# 2. A snapshot must not transport a non-finite value even if one is smuggled
#    in by bypassing the constructor (model_construct), which is how a cached
#    or unpickled payload could carry one.
# ---------------------------------------------------------------------------


def test_snapshot_cannot_transport_non_finite_via_model_construct() -> None:
    """`model_construct` skips validation, so the snapshot needs its own guard.

    This is the belt-and-braces case: a value arriving from a cache, a parquet
    round-trip, or a deserialisation path never passes the field validator, so
    validation at the point-of-use must not be the only line of defence.
    """
    smuggled = ObservationPoint.model_construct(
        observation_date=date(2026, 8, 1),
        value=float("nan"),
        series_id="CPIAUCSL",
        source="openbb",
        retrieved_at=datetime(2026, 9, 20, tzinfo=UTC),
        release_datetime=None,
        vintage_datetime=None,
    )
    snapshot = MacroDataSnapshot.model_construct(country="us", cpi_headline=[smuggled])
    with pytest.raises(ValueError, match=r"(?i)non-finite|finite|nan"):
        snapshot.assert_finite()


def test_snapshot_assert_finite_passes_a_clean_snapshot() -> None:
    """The guard must be a no-op on ordinary, finite data."""
    snapshot = MacroDataSnapshot(
        country="us",
        cpi_headline=[
            ObservationPoint(observation_date=date(2026, 8, 1), value=334.131, series_id="CPIAUCSL")
        ],
    )
    snapshot.assert_finite()


# ---------------------------------------------------------------------------
# 3. The validation gate must FLAG a non-finite value rather than pass it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", NON_FINITE)
def test_validation_flags_non_finite_value(bad: float) -> None:
    """A non-finite value must produce a finding, not a clean report.

    Measured before the fix: ``nan`` -> CLEAN under any bounds. That false
    negative is what lets a poisoned value reach the thesis layer unannounced.
    """
    points = [
        ObservationPoint.model_construct(
            observation_date=date(2026, 8, 1),
            value=bad,
            series_id="CPIAUCSL",
            source="openbb",
            retrieved_at=datetime(2026, 9, 20, tzinfo=UTC),
            release_datetime=None,
            vintage_datetime=None,
        )
    ]
    report = validate_observations(
        points, series_id="CPIAUCSL", min_value=0.0, max_value=500.0, required=True
    )
    codes = {finding.code for finding in report.findings}
    assert "NON_FINITE_VALUE" in codes, (
        f"a non-finite value ({bad!r}) produced no NON_FINITE_VALUE finding; "
        f"got {sorted(codes)} — the gate cannot see it"
    )
    non_finite = [f for f in report.findings if f.code == "NON_FINITE_VALUE"]
    assert non_finite[0].severity is Severity.ERROR, (
        "a non-finite value is not a warning state: no model can consume it, so it must be an ERROR"
    )


def test_validation_nan_is_flagged_even_without_bounds() -> None:
    """The NaN case is bound-independent, which is why it needed its own check.

    With no ``min_value``/``max_value`` supplied, the range checks cannot fire
    at all, so a NaN previously passed every universal check in the gate.
    """
    points = [
        ObservationPoint.model_construct(
            observation_date=date(2026, 8, 1),
            value=float("nan"),
            series_id="CPIAUCSL",
            source="openbb",
            retrieved_at=datetime(2026, 9, 20, tzinfo=UTC),
            release_datetime=None,
            vintage_datetime=None,
        )
    ]
    report = validate_observations(points, series_id="CPIAUCSL")
    codes = {finding.code for finding in report.findings}
    assert "NON_FINITE_VALUE" in codes, (
        "with no bounds supplied the NaN passed every check — the universal "
        "finiteness check is the only thing that can catch it"
    )


def test_validation_still_reports_clean_for_finite_data() -> None:
    """No regression: ordinary data must remain CLEAN (no false positives)."""
    points = [
        ObservationPoint(observation_date=date(2026, 8, 1), value=334.131, series_id="CPIAUCSL")
    ]
    report = validate_observations(
        points, series_id="CPIAUCSL", min_value=0.0, max_value=500.0, required=True
    )
    assert report.findings == [], f"finite data produced findings: {report.findings}"


# ---------------------------------------------------------------------------
# 4. The normalisation layer must drop a non-finite row, not transport it.
# ---------------------------------------------------------------------------


def _normalise(values: list[Any]) -> pd.DataFrame:
    """The exact column hygiene `openbb_client._normalise_frame` performs.

    Reproduced here rather than imported because the method is coupled to a
    live client; the *transformation* is what the audit is about, and it is the
    same lines. If those lines change, this test's premise must be revisited —
    which is the point: it pins the contract.
    """
    from macro_engine.data_layer.openbb_client import _is_non_finite

    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-06-01", periods=len(values), freq="MS").date,
            "value": values,
        }
    )
    frame = frame.dropna(subset=["value"])
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["value"])
    # THE FIX: a coerced `inf` is not a null and survives dropna, so finiteness
    # must be enforced explicitly by the same predicate the client ships.
    frame = frame[~frame["value"].map(_is_non_finite)]
    return frame


def test_nan_is_not_merely_null_so_dropna_alone_is_insufficient() -> None:
    """Pin the REASON the fix is needed: `inf` is not null.

    This is the load-bearing observation. If a future contributor removes the
    finiteness filter believing ``dropna`` covers it, this test explains why it
    does not.
    """
    frame = pd.DataFrame({"value": [1.0, float("inf"), float("nan"), 2.0]})
    after_dropna = frame.dropna(subset=["value"])
    assert len(after_dropna) == 3, "dropna removes nan but NOT inf"
    assert float("inf") in after_dropna["value"].to_numpy()


def test_normalisation_drops_non_finite_rows_and_keeps_finite_ones() -> None:
    """The shipped normalisation must keep finite rows and drop poisoned ones."""
    frame = _normalise([332.568, float("inf"), float("nan"), 334.131])
    kept = frame["value"].tolist()
    assert kept == [332.568, 334.131], f"non-finite values survived: {kept}"


def test_normalisation_of_only_non_finite_values_yields_empty_frame() -> None:
    """All-poisoned input must become EMPTY, so the caller raises.

    An empty frame is what makes ``_normalise_frame`` raise
    ``OpenBBFetchError`` — the correct outcome, because it distinguishes
    "no usable data" from "data that arrived and is unusable" without
    inventing a value for either.
    """
    frame = _normalise([float("nan"), float("inf")])
    assert frame.empty
