"""``/dashboard_data`` — a flattened view for UI rendering (Section 8.2, D-070).

The spec's own framing, kept verbatim because it is the design: *"Flattened,
UI-friendly view of the latest snapshot + model outputs — designed for eventual
Workspace widget rendering, not the full MacroThesis object (which is
richer/nested for programmatic consumers)."*

So this endpoint is deliberately **not** a thinner ``/thesis``. The two serve
different consumers and should not converge:

===================  ==========================================================
``/thesis``          one nested, complete, schema-validated object. A program
                     reads it. It is the deliverable.
``/dashboard_data``  a flat table of series and scalars. A widget draws it. It
                     is a rendering input, and it is **not** the deliverable.
===================  ==========================================================

The consequence worth stating: nothing here is a claim. The dashboard does not
publish a gap, a convergence verdict or an instrument — those are judgments, and
they belong to the thesis where they carry evidence. This endpoint publishes the
**measurements** those judgments were made from, plus a pointer to the thesis.

Why the series are capped
-------------------------
``api.dashboard_series_limit`` (default 12) bounds each family. The payload is
each series' full history, so an unbounded response is kilobytes per series
times seventeen — a denial of service against the caller's own browser, and a
response too large to render is a response that does not do its job. The cap is
config, and the response reports **how many points it withheld**, so a truncated
chart says it is truncated rather than silently drawing a shorter history.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from macro_engine.api_layer.snapshot_provider import (
    SnapshotProvenance,
    SnapshotUnavailableError,
    get_snapshot,
)
from macro_engine.data_layer.schemas import MacroDataSnapshot, ObservationPoint

router = APIRouter(tags=["dashboard"])

#: The families this endpoint exposes, and the snapshot fields in each. Grouped
#: because a flat list of seventeen names is not a dashboard — a widget renders
#: a panel, and the panels are the economic blocks.
_SERIES_FAMILIES: dict[str, tuple[str, ...]] = {
    "growth": ("gdp_real", "gdp_nominal", "gdp_potential", "gdi"),
    "prices": ("cpi_headline", "cpi_core", "pce_core", "ppi"),
    "labor": (
        "unemployment_rate",
        "initial_claims",
        "continuing_claims",
        "jolts_openings",
        "jolts_quits",
    ),
    "policy": ("iorb", "sofr", "fed_funds_rate", "on_rrp_rate", "on_rrp_volume_bn"),
    "credit": ("credit_spread_hy", "credit_spread_ig"),
}


class SeriesPanel(BaseModel):
    """One series, flattened to the two arrays a chart actually needs."""

    model_config = ConfigDict(extra="forbid")

    field: str
    label: str = Field(description="Human-readable name for a widget legend.")
    dates: list[str] = Field(description="ISO dates, oldest first.")
    values: list[float]
    latest_value: float | None = None
    latest_date: str | None = None
    points_available: int = Field(ge=0)
    points_withheld: int = Field(
        ge=0,
        description=(
            "Points dropped by api.dashboard_series_limit. Non-zero means the chart "
            "shows a TRUNCATED history, and a reader who does not know that will "
            "read the visible window as the whole series."
        ),
    )


class CurvePanel(BaseModel):
    """The yield curve, which is a mapping rather than a time series."""

    model_config = ConfigDict(extra="forbid")

    as_of: str
    tenors: dict[str, float] = Field(description="Tenor label -> yield in PERCENT.")
    units: str = Field(
        default="percent",
        description=(
            "Always 'percent'. This is a SCHEMA INVARIANT, not a measurement: "
            "``YieldCurveSnapshot.tenors`` is documented and validated as "
            "percent (4.35 means 4.35%), and the snapshot carries no per-curve "
            "unit field to read. Declaring it here is honest labelling of a "
            "fixed convention; reading it from the snapshot would require a "
            "field that does not exist. If a basis-point curve is ever added, "
            "that curve needs its own panel type with its own units — not a "
            "second value in this string."
        ),
    )


class DashboardData(BaseModel):
    """The flattened snapshot plus the provenance that dates it."""

    model_config = ConfigDict(extra="forbid")

    country: str
    as_of: datetime
    provenance: SnapshotProvenance
    series: dict[str, list[SeriesPanel]] = Field(
        description="Family name -> its series panels, in the order declared above."
    )
    yield_curve: CurvePanel | None = None
    tips_curve: CurvePanel | None = None
    series_limit: int
    warnings: list[str] = Field(default_factory=list)


def _panel(
    field: str,
    points: list[ObservationPoint],
    *,
    label: str,
    limit: int,
) -> SeriesPanel:
    """Flatten one series, keeping the MOST RECENT ``limit`` points.

    Most recent, not first: a dashboard's whole purpose is the current state, and
    a truncated chart that showed the oldest twelve points would be a chart of
    four years ago. The withheld count is reported so the truncation is visible
    either way.
    """
    available = len(points)
    kept = points[-limit:] if available > limit else list(points)
    return SeriesPanel(
        field=field,
        label=label,
        dates=[p.observation_date.isoformat() for p in kept],
        values=[p.value for p in kept],
        latest_value=points[-1].value if points else None,
        latest_date=points[-1].observation_date.isoformat() if points else None,
        points_available=available,
        points_withheld=available - len(kept),
    )


def _label(field: str) -> str:
    """``initial_claims`` -> ``Initial Claims``. Cosmetic, and stated as such."""
    return field.replace("_", " ").title()


@router.get("/dashboard_data", response_model=DashboardData)
async def dashboard_data(
    country: str = Query(default="us"),
    fresh: bool = Query(
        default=False,
        description="Rebuild the snapshot rather than serving the cached one.",
    ),
) -> DashboardData:
    """Flatten the snapshot for widget rendering. Publishes measurements, not claims."""
    from macro_engine.config import get_settings

    settings = get_settings()
    limit = settings.api.dashboard_series_limit

    try:
        snapshot, provenance = get_snapshot(country, force_refresh=fresh)
    except SnapshotUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=501,
            detail=f"country '{country}' is not implemented (Section 22.3). {exc}",
        ) from exc

    families: dict[str, list[SeriesPanel]] = {}
    for family, fields in _SERIES_FAMILIES.items():
        panels = [
            _panel(field, _points_for(snapshot, field), label=_label(field), limit=limit)
            for field in fields
        ]
        # An empty family is omitted rather than returned as a list of empty
        # panels: a widget that receives `{"growth": []}` must special-case the
        # empty list, whereas an absent key is simply "no panel here".
        if any(panel.points_available for panel in panels):
            families[family] = panels

    warnings = list(provenance.warnings())

    # A field the family table names but the schema does not carry is a CODE
    # defect, not a data gap: the panel can never render whatever the provider
    # returns, and the two look identical to a client that only sees
    # ``"tips_curve": null``. Naming them is what turns a silently-missing panel
    # into a fixable one.
    absent_fields = _declared_but_absent(snapshot)
    if absent_fields:
        warnings.append(
            f"DASHBOARD FIELD MISSING: {len(absent_fields)} field(s) named by the "
            f"family table are not on the snapshot schema ({absent_fields}) — these "
            f"panels cannot render regardless of what the provider returns, which "
            f"means the field was renamed or removed and this table was not updated."
        )

    truncated = sorted(
        panel.field for panels in families.values() for panel in panels if panel.points_withheld
    )
    if truncated:
        warnings.append(
            f"DASHBOARD TRUNCATED: {len(truncated)} series capped at {limit} points "
            f"({truncated}). Each panel reports its own points_withheld; the charts "
            f"show the most recent window, not the whole history."
        )

    return DashboardData(
        country=snapshot.country,
        as_of=snapshot.as_of,
        provenance=provenance,
        series=families,
        yield_curve=_curve_panel(snapshot, "yield_curve"),
        tips_curve=_curve_panel(snapshot, "tips_yields"),
        series_limit=limit,
        warnings=warnings,
    )


def _points_for(snapshot: MacroDataSnapshot, field: str) -> list[ObservationPoint]:
    """The snapshot's observations for one field, or ``[]``.

    ``getattr`` with a default rather than a mapping to each attribute, because
    the family table above names fields as *strings* — which is what makes the
    grouping declarative — and a renamed snapshot field must degrade to an
    absent panel rather than an ``AttributeError`` on a dashboard request.

    Degrading silently is only half the contract, though. ``[]`` is returned for
    two very different situations — "the field is declared and has no data in
    this snapshot" and "there is no such field on the schema at all" — and the
    caller cannot tell them apart from the return value. The second is a code
    defect: the family table above names a field that no longer exists, which
    D-005 records as exactly how ``treasury_curve`` → ``yield_curve`` alias drift
    happened. So ``_missing_fields`` reports the second case separately, and the
    handler turns it into a warning.
    """
    value = getattr(snapshot, field, None)
    if isinstance(value, list):
        return value
    return []


def _declared_but_absent(snapshot: MacroDataSnapshot) -> list[str]:
    """Fields named by the family table that the snapshot schema does not carry.

    This is the renamed-field detector. ``hasattr`` on the *model* — not on the
    instance's populated values — is the right test: a field the schema declares
    and the fetch left empty is a data gap, which the existing
    ``EMPTY_SERIES``/provenance flags already describe, whereas a field the
    schema does not declare at all means the panel can never appear no matter
    what the provider does, and only the code can fix it.
    """
    missing: list[str] = []
    for field in _all_declared_fields():
        if not hasattr(snapshot, field):
            missing.append(field)
    for curve_field in ("yield_curve", "tips_yields"):
        if not hasattr(snapshot, curve_field):
            missing.append(curve_field)
    return sorted(set(missing))


def _all_declared_fields() -> list[str]:
    """Every series field the family table names, in declaration order."""
    return [field for fields in _SERIES_FAMILIES.values() for field in fields]


def _curve_panel(snapshot: MacroDataSnapshot, field: str) -> CurvePanel | None:
    curve = getattr(snapshot, field, None)
    if curve is None:
        return None
    return CurvePanel(as_of=curve.as_of.isoformat(), tenors=dict(curve.tenors))
