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
            "The guard is the `_reject_unknown_tenors` validator below, which "
            "runs `isfinite` over every VALUE. `Field(allow_inf_nan=False)` "
            "cannot express this: the constraint belongs to the dict's values "
            "and a field-level constraint applies to the mapping, not to its "
            "items (D-074.1's mechanism, applied to the curve)."
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
    fed_total_assets: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "FRED WALCL — Fed total assets, WEEKLY, in MILLIONS of dollars. Module 4.1's "
            "``balance_sheet_level`` and the denominator of the relative change that "
            "decides the QE/QT stance. Promoted from ``not_a_snapshot_field`` when the "
            "balance-sheet leg was wired into the thesis path: the registry justified the "
            "exclusion on the grounds that only ``qe_qt_stance``'s own live check fetched "
            "it, and that premise stopped holding once ``qe_qt_stance`` became reachable "
            "from the orchestration. UNIT TRAP: millions here, BILLIONS in "
            "``on_rrp_volume_bn`` — a 1000x error in either direction produces plausible "
            "numbers, so both are asserted at the point of combination."
        ),
    )
    reserve_balances: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "FRED WRESBAL — reserve balances with Federal Reserve Banks, WEEKLY, in "
            "MILLIONS of dollars (same unit as ``fed_total_assets``). The series that "
            "distinguishes a QT absorbed by the ON-RRP buffer from one draining reserves "
            "directly — the September 2019 configuration. A NEGATIVE 13-week change "
            "alongside an active QT is the scarcity signal ``qe_qt_stance`` discloses."
            "Promoted from ``not_a_snapshot_field`` with ``fed_total_assets``."
        ),
    )

    # --- United Kingdom (Section 22.3 — country "gb") ----------------------
    #
    # A DEDICATED block rather than reusing the US field names. Section 22.3
    # rejects a country as a relabel, and the sharpest form of the relabel is
    # exactly the reuse of ``cpi_headline`` for UK CPI: the schema would look
    # country-generic while every consumer silently read a UK number through a
    # field documented as FRED's US series. Separate names make the country
    # explicit at every read site, which is what makes the section's claim
    # checkable. The registry entries carry the ``gb_`` prefix for the same
    # reason (the registry is a flat namespace).
    #
    # Every field is fetched only when ``snapshot_fields.gb`` names it, so a US
    # build pays nothing for these being declared.
    gb_cpi_headline: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "UK CPI, all items, annual rate (%) — FRED CPALTT01GBM659N. The BoE's "
            "2% CPI target is defined against THIS measure, not PCE and not core: "
            "a different target measure from the Fed's is the first structural "
            "difference the gb reaction function encodes."
        ),
    )
    gb_cpi_core: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "UK CPI excluding energy and food, annual rate (%) — FRED "
            "CPGRLE01GBM659N. An INPUT to the BoE's contemporaneous rule (which "
            "splits energy from non-energy), not a cross-check."
        ),
    )
    gb_unemployment_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description="UK unemployment rate (%) — FRED LRHUTTTTGBM156S.",
    )
    gb_gdp_growth_qoq: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "UK real GDP, quarter-on-quarter growth (%) — FRED NAEXKP01GBQ657S. "
            "Supplies the demand side of the BoE's rules; note the UK has NO "
            "reachable OECD output-gap series (probed 2026-10-10: GBROUTPUTQUR "
            "does not exist), so the gap must be ESTIMATED from this and the "
            "unemployment rate rather than fetched."
        ),
    )
    gb_bank_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Bank Rate (%) — the BoE's policy rate, tracked via SONIA (FRED "
            "IUDSOIA), daily. The ``i_prev`` input to all three BoE rules."
        ),
    )
    gb_gilt_10y_yield: list[ObservationPoint] = Field(
        default_factory=list,
        description="UK 10-year gilt yield (%) — FRED IRLTLT01GBM156N.",
    )
    gb_short_rate_3m: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "UK 3-month interbank rate (%) — FRED IR3TIB01GBM156N. The UK analogue "
            "of the market leg's short yield, used the same way "
            "``derive_market_implied_policy_path`` uses the US curve's short tenor."
        ),
    )

    # --- Euro area (Section 22.3 — country "eu") ---------------------------
    #
    # A DEDICATED block, for the same reason the UK block is one. The euro area
    # is the ECB's currency union, and the sharpest form of the relabel Section
    # 22.3 rejects would be reusing ``cpi_headline`` for HICP: the schema would
    # look currency-generic while every consumer read a euro-area number through
    # a field documented as FRED's US series.
    #
    # The euro block's SHAPE differs from the UK's in one visible way: there is
    # no ``eu_hicp_yoy`` / ``eu_gdp_growth_qoq`` field, because neither is
    # published currently on a reachable route. The euro area's HICP rate and
    # GDP growth are DERIVED from the index and the level respectively — see
    # ``eu_hicp_index`` and ``eu_gdp_real_level`` — and a derived quantity
    # belongs to the model that derives it, not to the snapshot that carries
    # inputs. Declaring a field for it would be a field no fetch could ever
    # populate.
    eu_hicp_index: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Euro-area HICP (all items, harmonised), INDEX 2015=100 — FRED "
            "CP0000EZ19M086NEST, current through 2026-08. The INPUT from which "
            "the euro HICP inflation rate is derived; the euro area has no "
            "currently-published HICP rate on any reachable route."
        ),
    )
    eu_ecb_deposit_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "ECB deposit facility rate (%) — FRED ECBDFR, daily. The euro "
            "area's EFFECTIVE policy rate since 2014: the ``i_prev`` input to "
            "the ECB rules, and the euro analogue of ``iorb`` and "
            "``gb_bank_rate``."
        ),
    )
    eu_ecb_main_refi_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "ECB main refinancing operations rate (%) — FRED ECBMRRFR, daily. "
            "Carried alongside the deposit rate because the ECB runs a two-rate "
            "system and the two differ; which one a rule reads is declared, not "
            "assumed."
        ),
    )
    eu_estr: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "ESTR — the euro short-term rate (%) — FRED ECBESTRVOLWGTTRMDMNRT, "
            "daily. The euro area's risk-free overnight benchmark: the analogue "
            "of SOFR and SONIA. A MARKET rate, kept separate from the policy "
            "rates above."
        ),
    )
    eu_unemployment_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Euro-area unemployment rate (%) — econdb ``economy.indicators`` "
            "symbol URATE, country EU, monthly, current. The euro area's "
            "labour read. Reachable on no FRED route (every variant stops in "
            "<=2023), which is why this one series forced the registry's "
            "``extra_params`` surface."
        ),
    )
    eu_gdp_real_level: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Euro-area real GDP, LEVEL in millions of euro, SA — FRED "
            "CLVMNACSCAB1GQEA19, through 2026-Q2. The INPUT from which euro "
            "GDP growth is derived; the euro-area GDP growth series stop in "
            "2023 while the level does not."
        ),
    )
    eu_short_rate_3m: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Euro-area 3-month interbank rate (%) — FRED IR3TIB01EZM156N, "
            "monthly. The euro analogue of ``gb_short_rate_3m``, and the input "
            "the euro market-implied path is derived from."
        ),
    )
    eu_long_rate_10y: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Euro-area 10-year government bond yield (%) — econdb "
            "``economy.indicators`` symbol Y10YD, country EU, monthly, current "
            "through 2026-07. Served as a FRACTION by the route "
            "(``source_units: decimal``) and converted to percent by the "
            "fetcher, so this field is always percent."
        ),
    )

    # --- Germany (Section 22.3 — country "de") -----------------------------
    #
    # A DEDICATED block, for the same reason the UK and euro blocks are ones.
    #
    # NOTE what is ABSENT: no ``de_policy_rate``. Germany has no central bank
    # of its own for policy purposes — the ECB sets the single rate for the
    # currency union (the Bundesbank executes it), so a German policy-rate
    # series would be a fabrication. The ``de`` arm reads the ECB rate through
    # a documented stand-in, and its distinct content is the German NATIONAL
    # data below (see docs/DE_JP_DESIGN.md).
    de_cpi_yoy: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "German CPI, all items, year-over-year (%) — IMF via "
            "``economy.cpi``, current through 2026-08. The German national "
            "inflation the ECB's single stance maps onto; the member-state rule "
            "is built on its divergence from the euro-area aggregate."
        ),
    )
    de_unemployment_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "German unemployment rate (%) — OECD ``economy.unemployment``, "
            "monthly, current through 2026-08. The national labour read."
        ),
    )
    de_gdp_real_level: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "German real GDP, LEVEL — OECD ``economy.gdp.real``, quarterly, "
            "current through 2026-Q2. The INPUT from which the German output "
            "gap is derived."
        ),
    )
    de_short_rate_3m: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "German 3-month interbank rate (%) — FRED IR3TIB01DEM156N, monthly. "
            "The German short end, and the input the `de` market-implied path is "
            "derived from."
        ),
    )
    de_long_rate_10y: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "German 10-year Bund yield (%) — FRED IRLTLT01DEM156N, monthly. The "
            "national long rate; the member-state rule reads the Bund-vs-"
            "aggregate spread, which needs this AND ``eu_long_rate_10y``."
        ),
    )
    de_call_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "German call money / overnight interbank rate (%) — FRED "
            "IRSTCI01DEM156N, monthly. A MARKET rate (Germany has no policy "
            "rate); used as the `de` rule's previous-rate leg."
        ),
    )

    # --- Japan (Section 22.3 — country "jp") -------------------------------
    #
    # A DEDICATED block. Japan's distinguishing feature is that its central
    # bank's framework is NOT a Taylor rule: the BoJ used the 10-year JGB yield
    # as an instrument (Yield Curve Control) and an inflation-overshooting
    # commitment as guidance, under a ZLB that made the zero floor bind for
    # years. The fields below are exactly what that structure reads.
    jp_cpi_yoy: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Japan CPI, all items, year-over-year (%) — IMF via "
            "``economy.cpi``, current through 2026-08. THE SEVENTH FALSE BLOCK: "
            "the OECD route and the FRED series (JPNCPIALLMINMEI, "
            "CPALTT01JPM659N) all stop at 2021-06, but the IMF provider on the "
            "same route is current — so 'Japan CPI is unavailable' was wrong."
        ),
    )
    jp_unemployment_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Japan unemployment rate (%) — OECD ``economy.unemployment``, "
            "monthly, current through 2026-08. Structurally low (~2.5%), which "
            "is why the jp rule reads it against Japan's own norm."
        ),
    )
    jp_gdp_real_level: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Japanese real GDP, LEVEL — OECD ``economy.gdp.real``, quarterly, "
            "current through 2026-Q2. The INPUT from which the Japanese output "
            "gap is derived."
        ),
    )
    jp_short_rate_3m: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Japanese 3-month interbank rate (%) — FRED IR3TIB01JPM156N, monthly. "
            "The Japanese short end; its own history at/below zero is the ZLB "
            "evidence the jp rule encodes."
        ),
    )
    jp_long_rate_10y: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Japanese 10-year JGB yield (%) — FRED IRLTLT01JPM156N, monthly. THE "
            "STRUCTURAL SERIES: under YCC (2016-2024) this yield was a policy "
            "TARGET, not merely a market price, which is the fact that most "
            "distinguishes the BoJ's framework from a Taylor rule."
        ),
    )
    jp_call_rate: list[ObservationPoint] = Field(
        default_factory=list,
        description=(
            "Japanese call money / overnight rate (%) — FRED IRSTCI01JPM156N, "
            "monthly. The policy-sensitive overnight rate; the `jp` rule's "
            "previous-rate leg and the series whose NIRP-era values were negative."
        ),
    )

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
            "never silently corrected.\n\n"
            "IMPORTANT (re-measured 2026-10-05): this list is NOT what "
            "compute_confidence() reads. That function takes a per-model BOOLEAN "
            "(ConfidenceInputs.data_quality_flags_present) which MOST models set "
            "from their OWN inputs. ONE model is the exception: "
            "``gdp_nowcast.output_gap_from_snapshot`` reads THIS list and "
            "re-prices its result's confidence with "
            "``data_quality_flags_present=True`` whenever any flag is present, so "
            "a flagged snapshot DOES lower that model's confidence. For every "
            "other model it does not, and a consumer that must degrade "
            "confidence on a flagged snapshot has to do so explicitly. (A prior "
            "version of this description said 'Fed into compute_confidence()', "
            "which was false — audit finding X-L2. Its replacement then said no "
            "model reads this list at all, which was ALSO false, for "
            "gdp_nowcast — F-SCH-002.)"
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
