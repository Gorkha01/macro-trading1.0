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
from math import isfinite

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

    **Point-in-time provenance (Section 6).** Four distinct timestamps matter
    to a point-in-time reasoning system and they are NOT interchangeable:

    * ``observation_date`` — what period the value *describes* (2026-08 CPI).
    * ``release_datetime`` — when the value became public.
    * ``vintage_datetime`` — which revision of the value this is.
    * ``retrieved_at`` — when *this process* read it.

    ``observation_date`` and ``retrieved_at`` are always present. The two
    release-side fields are **optional and default to ``None``, which means
    UNKNOWN — never "same as observation_date"**.

    ``release_datetime`` IS populated, from the most direct source available:
    ``publication_dates`` reads each series' own ``last_updated`` metadata —
    verified at 42/42 registry coverage, 0 transport errors — so it needs no
    event-name join and is the primary source. (An earlier audit concluded no
    route returned release dates at all; that was wrong twice over. First
    ``economy.calendar`` was tried with only one of its four providers, and
    ``provider=nasdaq`` works. Then enumerating all 278 live OpenAPI operations
    found ``economy.fred_search``, whose ``search_type=series_id`` lookup
    returns the publication stamp directly. See ``publication_dates.py``.)

    The consequence is that ``has_known_release_timing`` is now True on every
    point for which the metadata route resolved a series, rather than False
    everywhere. Where it is still False, timing is UNKNOWN — which is a
    different statement from "published at the observation date".

    ``vintage_datetime`` remains unpopulated, and this is now established rather
    than assumed. The same route returns ``realtime_start`` / ``realtime_end``,
    but for every series both equal *today*: they describe the vintage window in
    force now, not which revisions existed before. Passing ``realtime_start`` as
    a query parameter is silently ignored (A/B tested). So "when did this become
    public" is answerable and "which revision is this" is not — different
    questions, and only the first can be filled here.
    """

    model_config = ConfigDict(extra="forbid")

    observation_date: date
    value: float = Field(
        allow_inf_nan=False,
        description=(
            "The observed value. MUST be finite: a `nan` or `inf` is not a "
            "missing value, it is a poisoned one — every downstream guard sees "
            "a present, testable float, so nothing degrades to "
            "INSUFFICIENT_DATA and the model silently computes `nan`. Missing "
            "data is represented by the row being ABSENT, never by a non-finite "
            "sentinel (Section 21.0 rule 2)."
        ),
    )
    series_id: str
    source: str = "openbb"
    retrieved_at: datetime = Field(default_factory=utc_now)

    release_datetime: datetime | None = Field(
        default=None,
        description=(
            "When the value became public. None = UNKNOWN (not 'equal to "
            "observation_date'). Populated from the series' own `last_updated` "
            "metadata (primary) or the release calendar (fallback); when both "
            "are unavailable it stays None rather than being guessed (Section 6)."
        ),
    )
    vintage_datetime: datetime | None = Field(
        default=None,
        description=(
            "Which revision of the value this is (ALFRED-style realtime_start). "
            "None = UNKNOWN, i.e. the value is treated as the latest vintage only. "
            "No reachable route distinguishes past revisions from the current "
            "one, so this is always None today (Section 6)."
        ),
    )

    @property
    def has_known_release_timing(self) -> bool:
        """Whether this point's publication time is actually known.

        True when the release calendar supplied a datetime for this series, and
        False otherwise — including when the calendar was unreadable. Exists so
        a consumer can *ask* rather than assume: the failure mode Section 6
        prohibits is a system that silently treats ``observation_date`` as the
        release date, and a bare ``release_datetime`` check invites exactly
        that inference at each call site.
        """
        return self.release_datetime is not None


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
        description=(
            "Tenor label -> yield in PERCENT. e.g. {'2yr': 4.35, '10yr': 4.12}. "
            "Every value MUST be finite: pydantic's `float` accepts `nan` and "
            "`inf` by default, and `validate_yield_curve`'s checks are all "
            "comparisons (`yld <= 0.0`, `yld > max`), every one of which is "
            "False for `nan` — so a poisoned tenor would report the curve CLEAN. "
            "`allow_inf_nan=False` is expressed on the ANNOTATED ITEM type "
            "because the constraint belongs to the dict's values, not to the "
            "mapping (D-074.1's mechanism, applied to the curve)."
        ),
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
        non_finite = sorted(name for name, yld in v.items() if not isfinite(float(yld)))
        if non_finite:
            raise ValueError(
                f"Non-finite yield(s) for tenor(s) {non_finite}. A `nan`/`inf` is "
                "not a missing tenor: it is present and testable, so no range "
                "check rejects it (`nan <= 0.0` and `nan > max` are both False) "
                "and the curve reports CLEAN. A missing tenor is represented by "
                "the tenor being ABSENT, never by a non-finite value "
                "(Section 21.0 rule 2, D-074.1)."
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
    decision_cutoff: datetime | None = Field(
        default=None,
        description=(
            "The instant the decision this snapshot feeds is being made. "
            "``as_of`` says when the data was ASSEMBLED; ``decision_cutoff`` says "
            "what must have been KNOWABLE. They are usually close but are "
            "conceptually distinct: a snapshot rebuilt from a cache has an "
            "``as_of`` of the rebuild and a ``decision_cutoff`` of the original "
            "decision. None = the decision is happening now, i.e. ``retrieved_at`` "
            "of the latest point (Section 6)."
        ),
    )

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

    def iter_scalar_series(self) -> list[tuple[str, list[ObservationPoint]]]:
        """Every populated ``ObservationPoint`` list, with its field name.

        Used by the finiteness guard so it covers **every** series the schema
        declares, rather than a hand-maintained subset — the same
        pluggability contract ``validate_observations`` follows. Adding a
        series field to this schema puts it under the guard automatically.
        """
        out: list[tuple[str, list[ObservationPoint]]] = []
        for name in type(self).model_fields:
            points = getattr(self, name)
            if (
                isinstance(points, list)
                and points
                and all(isinstance(p, ObservationPoint) for p in points)
            ):
                out.append((name, points))
        return out

    def iter_curves(self) -> list[tuple[str, YieldCurveSnapshot]]:
        """Every populated curve field, with its field name.

        The companion to ``iter_scalar_series``. Curve fields hold a
        ``YieldCurveSnapshot`` rather than a list, so they are invisible to a
        selector written for lists — which is exactly how they escaped
        ``assert_finite`` until now. Derived from the schema rather than named,
        so a new curve field is covered the moment it is declared.
        """
        out: list[tuple[str, YieldCurveSnapshot]] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, YieldCurveSnapshot):
                out.append((name, value))
        return out

    def assert_finite(self) -> None:
        """Raise if any observation or curve tenor carries a non-finite value.

        A belt-and-braces guard, deliberately *not* the only line of defence.
        ``ObservationPoint.value`` and ``YieldCurveSnapshot.tenors`` both refuse
        a non-finite value at construction, but a snapshot can also arrive from a
        path that never runs field validation — ``model_construct``, a pickle, a
        parquet round-trip, or a cache read. Those paths are exactly where a
        poisoned sentinel would survive, so finiteness is re-checked at the point
        of use.

        **Both shapes are covered.** An earlier version iterated only the
        scalar lists, so a ``nan`` tenor — which ``validate_yield_curve`` cannot
        reject, because every one of its comparisons is False for ``nan`` —
        passed the guard and reported the curve CLEAN. A guard that covers one
        of two shapes is a guard with a hole exactly where the second shape is.

        Raises ``ValueError`` naming **every** offending field:point so a
        reader can see the full extent rather than the first failure.
        """
        offenders: list[str] = []
        for field_name, points in self.iter_scalar_series():
            for point in points:
                if not isfinite(point.value):
                    offenders.append(
                        f"{field_name}[{point.observation_date}]={point.value!r} "
                        f"({point.series_id})"
                    )
        for curve_name, curve in self.iter_curves():
            for tenor, yld in curve.tenors.items():
                if not isfinite(float(yld)):
                    offenders.append(f"{curve_name}.tenors[{tenor}]={yld!r} @{curve.as_of}")
        if offenders:
            detail = "; ".join(offenders)
            raise ValueError(
                f"Snapshot carries {len(offenders)} non-finite observation(s): {detail}. "
                "A non-finite value is not missing data — a missing value is an "
                "absent row (or an absent tenor). It must be dropped at the source "
                "or the series reported unavailable, never carried as a float "
                "(Section 21.0 rule 2, Section 21.4)."
            )
