"""Data-layer Pydantic schemas (AGENTS.md Section 5.3).

The centrepiece is ``MacroDataSnapshot``: the **single object passed into
every model**. One snapshot = one point-in-time bundle of everything a model
might need, so models never fetch data themselves. That is a hard separation
of data from logic, not a convenience.

Two additions beyond the literal specification text, both explicitly
mandated elsewhere in the document:

* ``MacroDataSnapshot.data_quality_flags`` — required by Section 5.4: anomalies
  "are logged and attached to ``MacroDataSnapshot`` via an
  ``data_quality_flags: list[str]`` field (added to the schema above) — never
  silently dropped, matching the 'flag, don't fix' principle".
* ``retrieved_at`` is timezone-aware UTC throughout, per the system-wide
  replacement of ``datetime.utcnow()`` with ``datetime.now(timezone.utc)``.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from macro_engine.models.contracts import utc_now

__all__ = [
    "MacroDataSnapshot",
    "ObservationPoint",
    "YieldCurveSnapshot",
]

# Tenors required by Section 5.2: the full Treasury curve, 1mo through 30yr.
CANONICAL_TENORS: tuple[str, ...] = (
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


class ObservationPoint(BaseModel):
    """One dated observation of one series.

    ``series_id`` is the *internal field name* from ``series_registry.yaml``
    (e.g. ``cpi_headline``), not the provider's series code — the provider code
    lives in the registry so the two can be re-pointed independently.
    """

    model_config = ConfigDict(extra="forbid")

    observation_date: date
    value: float
    series_id: str
    source: str = "openbb"
    retrieved_at: datetime = Field(default_factory=utc_now)


class YieldCurveSnapshot(BaseModel):
    """A point-in-time curve, as a tenor -> yield-in-percent mapping.

    Units are **percent**, not basis points (e.g. ``4.35`` means 4.35%).
    Mixing the two is a real source of order-of-magnitude errors, so this is
    stated once here rather than assumed at each call site.
    """

    model_config = ConfigDict(extra="forbid")

    as_of: date
    tenors: dict[str, float] = Field(
        default_factory=dict,
        description="Tenor label -> yield in PERCENT. e.g. {'2yr': 4.35, '10yr': 4.12}",
    )
    retrieved_at: datetime = Field(default_factory=utc_now)

    @field_validator("tenors")
    @classmethod
    def _reject_unknown_tenors(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(v) - set(CANONICAL_TENORS))
        if unknown:
            raise ValueError(
                f"Unrecognized tenor label(s) {unknown}. Permitted: {list(CANONICAL_TENORS)}"
            )
        return v


class MacroDataSnapshot(BaseModel):
    """The single object passed into every model (Section 5.3).

    Every field defaults to empty rather than ``None`` so a partially-failed
    fetch still produces a usable, *inspectable* snapshot whose gaps are
    visible — accompanied by a ``data_quality_flags`` entry explaining each
    gap. A missing series is never conflated with a zero value.
    """

    model_config = ConfigDict(extra="forbid")

    country: str = Field(
        default="us",
        description=(
            'Only "us" is implemented through Phase 4 (Section 22.3 / Finding #3). '
            "This is a label, not a generalization."
        ),
    )
    as_of: datetime = Field(default_factory=utc_now)

    # --- National accounts (Module 7) ---
    gdp_real: list[ObservationPoint] = Field(default_factory=list)
    gdp_nominal: list[ObservationPoint] = Field(default_factory=list)
    gdi: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "FRED GDI (BEA Gross Domestic Income, nominal SAAR). The income-side "
            "estimate of the same aggregate gdp_nominal measures from the "
            "expenditure side. Kept separate from gdp_nominal rather than "
            "combined because Module 7.1's whole output IS their difference."
        ),
    )
    gdp_potential: list[ObservationPoint] = Field(
        default_factory=list,
        description="FRED GDPPOT (CBO). Preferred over computing Cobb-Douglas (Section 21.1).",
    )

    # --- Prices (Module 5) ---
    cpi_headline: list[ObservationPoint] = Field(default_factory=list)
    cpi_core: list[ObservationPoint] = Field(default_factory=list)
    pce_core: list[ObservationPoint] = Field(default_factory=list)
    ppi: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "PPI Final Demand (FRED PPIFIS) — Module 5.4's FINAL-DEMAND stage. "
            "Deliberately named 'ppi' rather than 'ppi_final_demand' because it is "
            "the headline PPI series; the two upstream stages are separate fields "
            "below so a consumer cannot accidentally use the final-demand rate as "
            "though it were the crude stage."
        ),
    )
    ppi_stage_crude: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "PPI unprocessed goods for intermediate demand (FRED WPSID62) — "
            "Module 5.4's CRUDE stage. Included as its own field rather than "
            "derived, because the pipeline signal is a comparison ACROSS stages "
            "and each stage is an independent publication with its own base year "
            "(this one is 1982=100, against Nov 2009=100 for the final-demand "
            "series). The three-stage gradient cannot be computed from 'ppi' "
            "alone, and rebuilding it from a single series is not possible."
        ),
    )
    ppi_stage_intermediate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "PPI processed goods for intermediate demand (FRED WPSID61) — "
            "Module 5.4's INTERMEDIATE stage. A distinct series from "
            "'ppi_stage_crude' despite the similar name: WPSID61 covers PROCESSED "
            "goods and WPSID62 UNPROCESSED. The one-word difference between the "
            "two series titles is why they are documented here rather than left "
            "to be inferred from the symbol."
        ),
    )

    # --- Labor (Module 6) ---
    unemployment_rate: list[ObservationPoint] = Field(default_factory=list)
    initial_claims: list[ObservationPoint] = Field(default_factory=list)
    continuing_claims: list[ObservationPoint] = Field(default_factory=list)
    jolts_openings: list[ObservationPoint] = Field(default_factory=list)
    jolts_quits: list[ObservationPoint] = Field(default_factory=list)

    # --- Rates (Modules 2, 4, 8) ---
    yield_curve: YieldCurveSnapshot | None = None
    tips_yields: YieldCurveSnapshot | None = None
    fed_funds_rate: list[ObservationPoint] = Field(default_factory=list)

    # --- Policy plumbing (Module 4) ---
    sofr: list[ObservationPoint] = Field(default_factory=list)
    iorb: list[ObservationPoint] = Field(default_factory=list)
    on_rrp_rate: list[ObservationPoint] = Field(default_factory=list)
    on_rrp_volume_bn: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "FRED RRPONTSYD — ON-RRP outstanding VOLUME in USD billions. Deliberately "
            "separate from ``on_rrp_rate`` (RRPONTSYAWARD, percent): one is a rate and one "
            "is a quantity, and Section 21.0 rule 4 forbids substituting one for the other. "
            "Supplies the ``repo_volume_change_pct`` corroboration that Section 22.11 "
            "requires before ``repo_stress_check`` may escalate to ACUTE_REPO_STRESS."
        ),
    )
    # NOTE: fed_funds_rate belongs to the Rates block above, not here. It was
    # briefly declared twice when on_rrp_volume_bn was added; mypy's no-redef
    # caught it, and a duplicate field is exactly the kind of silent shadowing
    # that would make one of the two declarations unreachable.

    # --- Cross-asset (Modules 9, 10, 11) ---
    fx_spot: dict[str, list[ObservationPoint]] = Field(default_factory=dict)
    commodity_spot: dict[str, list[ObservationPoint]] = Field(default_factory=dict)
    equity_index: dict[str, list[ObservationPoint]] = Field(default_factory=dict)

    # --- Credit (Modules 8, 17) ---
    credit_spread_hy: list[ObservationPoint] = Field(default_factory=list)
    credit_spread_ig: list[ObservationPoint] = Field(default_factory=list)

    # --- Data integrity ---
    data_quality_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Section 5.4, 'flag, don't fix'. Every anomaly found by "
            "data_layer/validation.py is appended here. Never silently dropped, "
            "never silently corrected. Fed into compute_confidence()."
        ),
    )
    field_sources: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "field name -> human-readable provenance, e.g. "
            "'cpi_headline': 'FRED CPIAUCSL via openbb'. Supports Section 21.0 "
            "Step 6 real-data validation records."
        ),
    )
