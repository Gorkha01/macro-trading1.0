"""Snapshot construction — the one place a ``MacroDataSnapshot`` is assembled.

AGENTS.md Section 5.2 + 5.3, Section 21.0, Section 21.1.

This module is the seam between the data layer and the models layer. Its whole
job is: *every model's input comes from here, and nothing enters a snapshot
without a registry-verified provenance.*

Design rules it enforces, and why
---------------------------------
**The registry is the only source of routing.** No provider, symbol, or
endpoint literal appears in this file. A series re-point after a source change
is a config edit, never a code change.

**An unverifiable series is omitted and flagged, never guessed.** Section 21.0
rule 1 makes live execution the test of a function; a series that cannot be
fetched is recorded in ``data_quality_flags`` as an explicit absence. Section
5.4's "flag, don't fix" then means the absence reaches
``compute_confidence()`` instead of being silently defaulted to zero — which
would look like a real observation of zero and quietly corrupt every model
downstream.

**One series failing does not kill the snapshot.** The alternative is that a
single transient FRED outage makes the entire thesis unbuildable. But a
partial snapshot must be *visibly* partial: every omission appends a flag, and
the returned report names which fields succeeded, so the caller can decide
whether the remainder is usable without inspecting the object by hand.
Graceful degradation with an audit trail, never silent degradation.

**The horizon is pinned once.** ``as_of`` is captured at the start, so a
snapshot assembled across several minutes of sequential HTTP calls is still a
single point-in-time object.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pandas as pd

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.alfred_client import (
    ROUTE_NAME,
    VintageUnavailableError,
    fetch_vintage_observations,
)
from macro_engine.data_layer.fx_client import FX_PAIRS, FxReadError, fetch_fx_spot
from macro_engine.data_layer.openbb_client import OpenBBClient, OpenBBFetchError
from macro_engine.data_layer.publication_dates import (
    PublicationDateError,
    fetch_publication_dates,
)
from macro_engine.data_layer.release_calendar import (
    ReleaseCalendarError,
    ReleaseDateIndex,
    fetch_release_dates,
)
from macro_engine.data_layer.schemas import ObservationPoint, YieldCurveSnapshot
from macro_engine.data_layer.validation import (
    ValidationReport,
    attach_flags,
    validate_registry_series,
    validate_yield_curve,
)
from macro_engine.models.contracts import utc_now

if TYPE_CHECKING:
    from macro_engine.config import RegistrySeries
    from macro_engine.data_layer.schemas import MacroDataSnapshot

__all__ = [
    "SnapshotBuildReport",
    "build_snapshot",
    "fetch_curve",
    "fetch_field",
    "fetch_field_vintage",
]

logger = logging.getLogger(__name__)

# Curve-shaped fields, identified structurally (the entry declares `tenors`)
# rather than by name, so a new curve added to config needs no code change.
CURVE_FIELDS: frozenset[str] = frozenset({"yield_curve", "tips_yields"})

#: Mapping-shaped fields the per-registry-entry loop can NEVER fill, whatever
#: config says: ``commodity_spot`` and ``equity_index`` have no fetch step of
#: their own, so an empty dict for them is structural rather than a data result.
#:
#: ``fx_spot`` is deliberately ABSENT. It is the same *shape* (a dict of series)
#: but it now HAS its own fetch step (:func:`_fetch_fx_spot_map`), so its
#: emptiness is a data result again. Keeping it in this set would re-introduce
#: exactly the un-re-measured claim the FX increment removed — the D-043 class.
FX_UNWIRED_ALWAYS: frozenset[str] = frozenset({"commodity_spot", "equity_index"})


class SnapshotBuildReport:
    """What happened while assembling a snapshot.

    Returned alongside the snapshot so a caller can distinguish "the data is
    clean" from "the data is missing in five places", which the snapshot's own
    field contents cannot express on their own.
    """

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.succeeded: list[str] = []
        self.failed: dict[str, str] = {}
        self.skipped_unverified: list[str] = []
        self.observation_counts: dict[str, int] = {}
        #: Mapping fields the SCHEMA declares but ``snapshot_fields`` can never
        #: fill, because they are not series — they are dicts of series
        #: (``fx_spot``, ``commodity_spot``, ``equity_index``). Reported
        #: separately from ``failed`` and ``skipped_unverified`` because the
        #: cause is different from both: nothing was asked for and nothing
        #: broke — the field is unreachable BY CONSTRUCTION.
        #:
        #: This exists because an empty mapping is indistinguishable from "no
        #: data this run", and that ambiguity is exactly the class the ``gdi``
        #: omission already produced once (a field declared in the registry, the
        #: schema, persistence AND the dashboard, and omitted from the one list
        #: the builder iterates, so it could never appear). Recording it here
        #: makes the omission a fact a caller can read rather than an absence
        #: they must infer.
        self.declared_not_wired: list[str] = []
        #: True when the Section 6 release calendar answered; False when it
        #: could not be read OR was never attempted. ``release_datetime`` being
        #: None everywhere is consistent with both, which is why this is
        #: recorded: "release timing unknown" and "nobody asked" must be
        #: distinguishable after the fact.
        self.release_calendar_read: bool | None = None
        #: Number of registry series the calendar supplied a date for.
        self.release_calendar_series: int = 0
        #: Set only when the calendar was enabled but misconfigured.
        self.release_calendar_note: str | None = None
        #: Which release-timing source went dark, when one did. Only set when
        #: ``release_calendar_read`` is False, i.e. a source was ASKED and could
        #: not be read. Recorded because "the calendar returned nothing" and
        #: "the per-series metadata route returned nothing" have completely
        #: different causes and fixes, and the flag alone cannot tell them apart.
        self.release_timing_outage_source: str | None = None
        #: Which source supplied the release index: "publication_dates"
        #: (primary, per-series metadata) or "release_calendar" (fallback,
        #: events join). None when neither answered or neither was enabled.
        self.release_source: str | None = None

    @property
    def is_complete(self) -> bool:
        """True only when nothing was skipped and nothing failed."""
        return not self.failed and not self.skipped_unverified

    def as_flags(self) -> list[str]:
        """Render the report as ``data_quality_flags`` entries.

        These are distinct from validation findings: validation flags describe
        data that arrived and looked wrong, whereas these describe data that
        never arrived at all. Both matter, and conflating them would hide the
        difference between "bad number" and "no number".
        """
        flags: list[str] = []
        for field, reason in sorted(self.failed.items()):
            flags.append(f"FETCH_FAILED:{field}:{reason}")
        for field in sorted(self.skipped_unverified):
            flags.append(f"UNVERIFIED_SERIES_SKIPPED:{field}")
        for field in sorted(self.declared_not_wired):
            # Distinct from EMPTY_SERIES below: that one means "asked and got
            # nothing", which can be a transient provider problem. This one
            # means "never asked, and never will be by this path" — a wiring
            # gap, which no retry will fix.
            flags.append(
                f"DECLARED_NOT_WIRED:{field}:declared on the schema but absent from "
                "snapshot_fields, so this path can never populate it — an empty "
                "value here is NOT evidence that no data exists"
            )
        for field in sorted(self.succeeded):
            if self.observation_counts.get(field, 0) == 0:
                # The detail sentence is carried HERE rather than left to
                # ``validate_observations(required=True)``, because this report is
                # the only layer that can own emptiness: it holds ``requested``,
                # so it can tell "asked and got nothing" from "not part of this
                # snapshot". Re-validation cannot (every field defaults to an
                # empty list), which is why it skips empty series instead of
                # flagging them. Emitting it from both produced two flags for one
                # condition on every build (F-SB-006).
                flags.append(
                    f"EMPTY_SERIES:{field}:requested but returned no observations — "
                    "downstream models must treat it as unavailable, not as zero"
                )
        # Section 6: make the release-timing gap visible in the flags rather
        # than only in the object. The three states are deliberately distinct:
        #   True  -> the calendar answered; release timing is known where matched.
        #   False -> it was asked and could not be read: release timing is UNKNOWN
        #            for every series, and a consumer reading only flags must be
        #            able to see that.
        #   None  -> it was never attempted (disabled, or an index was injected).
        #            That is a configuration choice, NOT a data-quality defect,
        #            so it raises no flag — flagging it would put a permanent
        #            INFO line on every snapshot and train readers to ignore the
        #            list, which is the failure mode the flag list exists to avoid.
        if self.release_calendar_read is False:
            # Name the source: an outage of the per-series metadata route and an
            # unreadable events calendar are the same *condition* (release
            # timing unknown) with different causes, and a flag that cannot say
            # which sent the reader to the wrong place.
            flags.append(
                f"RELEASE_TIMING_UNKNOWN:{self.release_timing_outage_source or 'source_unreadable'}"
            )
        if self.release_calendar_note is not None:
            flags.append(f"RELEASE_CALENDAR_MISCONFIGURED:{self.release_calendar_note}")
        return flags

    def summary(self) -> str:
        return (
            f"requested={len(self.requested)} succeeded={len(self.succeeded)} "
            f"failed={len(self.failed)} skipped_unverified={len(self.skipped_unverified)}"
        )


def _lookback_start() -> str:
    """Start date for the fetch window, from config — never an inline literal.

    A shared window across all series is deliberate: it keeps the snapshot's
    series mutually aligned in time. Series with shorter native history simply
    return what exists.
    """
    settings = get_settings()
    days = int(settings.data.lookback) * 365
    return (utc_now() - timedelta(days=days)).date().isoformat()


def resolve_snapshot_field(field_name: str, entry: RegistrySeries) -> str:
    """The ``MacroDataSnapshot`` attribute a registry entry populates.

    Registry keys and schema field names are not always identical — the key
    ``treasury_curve`` fills the schema's ``yield_curve``. Assuming they always
    matched silently discarded the entire Treasury curve on the first live
    build, so the mapping is now explicit (``snapshot_field``) with the key as
    the fallback.

    The fallback is what makes ``snapshot_field`` load-bearing rather than
    decorative, and it is also its one hazard: a registry entry that is NOT a
    snapshot field at all resolves to itself and then fails
    ``_assert_field_exists``. That is the intended outcome — a registry entry
    added for a model's own input provenance must declare that it is not part
    of the snapshot rather than being silently absorbed or silently ignored.
    """
    if entry.not_a_snapshot_field:
        raise OpenBBFetchError(
            f"registry entry '{field_name}' is declared "
            "`not_a_snapshot_field: true`, so it cannot be fetched into "
            "MacroDataSnapshot. It exists to document a model's input "
            "provenance. Use it directly in the model's live check, or remove "
            "the declaration if it genuinely should be part of the snapshot."
        )
    return entry.snapshot_field or field_name


def _assert_field_exists(field_name: str, target: str) -> None:
    """Fail loudly if the resolved target is not a real schema field.

    Without this, ``setattr`` on a Pydantic model with ``extra`` disallowed
    raises deep inside the loop and the reason is hard to see; with it, the
    registry and the schema are forced to agree at the point of use.
    """
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    if target not in MacroDataSnapshot.model_fields:
        raise OpenBBFetchError(
            f"registry field '{field_name}' resolves to snapshot attribute '{target}', "
            "which MacroDataSnapshot does not define. Fix `snapshot_field` in "
            "config/series_registry.yaml or add the field to the schema."
        )


def _points_from_frame(
    frame: pd.DataFrame,
    *,
    series_id: str,
    fallback_source: str,
    release_index: ReleaseDateIndex | None = None,
    unit_scale: float | None = None,
) -> list[ObservationPoint]:
    """Convert a normalized frame into ``ObservationPoint`` records.

    ``release_index`` (Section 6) attaches a publication datetime to each point
    **when the calendar supplied one for this series**. It is optional and
    defaults to ``None``, which means "no lookup was attempted" — and the
    resulting points carry ``release_datetime=None``, i.e. UNKNOWN. There is
    deliberately no fallback to ``observation_date``: those are different facts
    and conflating them is the exact defect Section 6 prohibits.

    One release datetime is applied to every point of the series, including
    historical ones. That is a **known, documented approximation**, not an
    oversight: the calendar window covers roughly the last 13 months, so for a
    series whose history is longer, older points receive a date that belongs to
    a *recent* release. It is defensible only in the direction that matters —
    the applied date is a real publication instant for this series, so an
    ``as_of`` filter cannot be fooled into admitting a value *earlier* than the
    true release. Callers that need exact per-observation timing must not treat
    this as vintage-accurate; ``vintage_datetime`` stays ``None`` throughout.

    ``unit_scale`` is the provider's declared scale relative to the registry's
    ``units`` (D-086), already derived on the registry entry. It is applied
    **here**, at the single place a raw provider value becomes an
    ``ObservationPoint``, so no caller can receive an unconverted value and no
    second conversion site can drift from this one. ``None`` means the provider
    and the registry agree, and the value passes through untouched.
    """
    if frame.empty:
        return []

    release_datetime = release_index.get(series_id) if release_index is not None else None
    scale = 1.0 if unit_scale is None else float(unit_scale)

    points: list[ObservationPoint] = []
    for _, row in frame.iterrows():
        raw_date = row["date"]
        if isinstance(raw_date, pd.Timestamp):
            observation_date: date = raw_date.date()
        elif isinstance(raw_date, date):
            observation_date = raw_date
        else:
            observation_date = pd.Timestamp(raw_date).date()
        points.append(
            ObservationPoint(
                observation_date=observation_date,
                value=float(row["value"]) * scale,
                series_id=series_id,
                source=str(row.get("source", fallback_source) or fallback_source),
                retrieved_at=pd.Timestamp(row["retrieved_at"]).to_pydatetime(),
                release_datetime=release_datetime,
            )
        )
    return points


def fetch_field(
    client: OpenBBClient,
    field_name: str,
    entry: RegistrySeries,
    *,
    start: str | None = None,
    release_index: ReleaseDateIndex | None = None,
) -> list[ObservationPoint]:
    """Fetch one scalar registry field and convert it to ``ObservationPoint``s.

    Raises ``OpenBBFetchError`` unchanged so the caller can record the failure
    per-field. It deliberately does not catch-and-return-empty, because an
    empty list is indistinguishable from a series that legitimately has no
    observations in the window — and that ambiguity is how a broken mapping
    masquerades as a quiet market.
    """
    if entry.endpoint is None:
        raise OpenBBFetchError(
            f"registry entry '{field_name}' has no endpoint configured; "
            "add one in config/series_registry.yaml"
        )
    if entry.symbol is None:
        raise OpenBBFetchError(
            f"registry entry '{field_name}' declares no symbol but is being fetched as a scalar"
        )

    # The route's own extra query parameters, merged UNDER the two the fetcher
    # owns. `extra_params` exists because a route may need a parameter the
    # fetcher cannot know about — measured 2026-10-10: `economy.indicators`
    # (provider `econdb`) requires `country=EU` for the euro-area unemployment
    # series, and the euro-area leg is unreachable on any symbol-only route.
    # The ordering is deliberate: the fetcher's own keys go LAST so a malformed
    # entry cannot shadow `symbol`/`start_date` even though the config validator
    # already rejects that combination. Belt and braces is cheap here and the
    # failure it prevents (reading a different series than the entry verifies)
    # is silent.
    params: dict[str, Any] = {
        **(entry.extra_params or {}),
        "symbol": entry.symbol,
        "start_date": start,
    }
    frame = client.fetch_series(
        provider=entry.provider,
        endpoint=entry.endpoint,
        params=params,
        series_label=field_name,
    )
    return _points_from_frame(
        frame,
        series_id=field_name,
        fallback_source=f"{entry.provider}:{entry.symbol}",
        release_index=release_index,
        unit_scale=entry.unit_scale_to_units,
    )


def fetch_field_vintage(
    field_name: str,
    entry: RegistrySeries,
    as_of: date,
    *,
    lookback_years: int | None = None,
    client: httpx.Client | None = None,
) -> list[ObservationPoint]:
    """Fetch one registry field **as it was known on ``as_of``**, not as it is now.

    The sibling of :func:`fetch_field`, and the only path in this module that
    fills ``vintage_datetime``. It is a separate function rather than a flag on
    ``fetch_field`` on purpose: the two have different failure contracts, and a
    flag would let a caller ask for a vintage and receive a latest-revision frame
    without noticing which one it got.

    **What makes this honest.** Every point returned carries
    ``vintage_datetime = as_of`` — the date the caller actually requested — rather
    than something inferred from the values. A vintage is a claim about *when a
    value was in force*, and the only non-inferring source for that claim is the
    as-of date that was asked for.

    ``release_datetime`` is deliberately **not** filled here. It is a different
    fact (when the value became public, versus which revision it is), it has its
    own working source in ``publication_dates``, and conflating the two is the
    exact substitution Section 6 prohibits. A caller that wants both should merge
    a :func:`fetch_field` result by ``observation_date`` rather than having this
    function guess.

    Raises ``VintageUnavailableError`` when no credential is reachable and
    ``VintageReadError`` when the read fails after its retries — both unchanged
    from the client, because a silent empty return here would be indistinguishable
    from a series with no revisions. That distinction is the whole point.

    An empty list IS a legitimate return when ``as_of`` precedes the series'
    first publication: nothing was known then, and the honest answer is nothing.
    The caller sees that as an empty window, which is a different observable from
    the raised errors above.
    """
    if not entry.vintage_eligible:
        raise VintageUnavailableError(
            f"registry entry '{field_name}' is not declared `vintage_eligible`, so a "
            "vintage read was not attempted. Set it in config/series_registry.yaml "
            "once the series is known to have an ALFRED record — this is declared "
            "rather than inferred so that 'no revisions exist' and 'nobody asked for "
            "this series' revisions' do not look identical."
        )

    config = get_registry().alfred_vintage
    if not config.enabled:
        raise VintageUnavailableError(
            "alfred_vintage is disabled in config/series_registry.yaml; enable it "
            "before requesting a vintage read"
        )

    lookback = lookback_years if lookback_years is not None else config.default_lookback_years
    start = date(as_of.year - lookback, as_of.month, as_of.day)

    rows = fetch_vintage_observations(
        entry.symbol or field_name,
        as_of,
        observation_start=start,
        observation_end=as_of,
        max_attempts=config.max_attempts,
        backoff_seconds=config.backoff_seconds,
        timeout_seconds=config.timeout_seconds,
        client=client,
    )

    scale = 1.0 if entry.unit_scale_to_units is None else float(entry.unit_scale_to_units)
    # ``retrieved_at`` is when THIS process read it — a third fact, and the only
    # one this process can state about itself. The vintage instant is the as_of
    # date, stamped identically on every point because it is a property of the
    # READ, not of the row.
    retrieved_at = utc_now()
    vintage_instant = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC)
    return [
        ObservationPoint(
            observation_date=row.observation_date,
            value=row.value * scale,
            series_id=field_name,
            source=f"{entry.provider}:{entry.symbol}@{ROUTE_NAME}",
            retrieved_at=retrieved_at,
            vintage_datetime=vintage_instant,
        )
        for row in rows
    ]


def fetch_curve(
    client: OpenBBClient,
    field_name: str,
    entry: RegistrySeries,
    *,
    start: str | None = None,
    as_of: datetime | None = None,
) -> YieldCurveSnapshot:
    """Fetch every tenor of a curve and assemble a ``YieldCurveSnapshot``.

    A missing tenor raises rather than being interpolated: a curve built partly
    from invented points is not a curve, and every downstream slope/curvature
    read would inherit the invention silently. The caller records the failure
    for the whole curve, which is the honest outcome — a half-observed curve
    cannot support a 2s10s read in the first place.

    **Every tenor is filtered to ``observation_date <= as_of`` before its latest
    point is read.** This is the O-7 discipline, and it belongs here for the
    same reason it lives in ``models/as_of.py`` for scalars: it is a property of
    *reading a series*, not of one model. A curve tenor that publishes forward
    projections — the shape ``GDPPOT`` has on the scalar path, where 41 of 62
    points were future-dated — would otherwise have its projection adopted as a
    **realised** yield, and every slope, curvature and breakeven read
    downstream would inherit it. ``frame.iloc[-1]`` is not "the latest
    observation"; it is "the last row the provider sent", and for a projection
    series those are different values.

    ``as_of`` defaults to now. The caller passes the snapshot's own ``as_of`` so
    a curve and the scalars beside it describe the same instant rather than two
    instants seconds apart.

    The truncation is **not** silent: the excluded count is reported through the
    returned ``YieldCurveSnapshot``'s companion warning path, and a tenor whose
    *entire* history is forward-dated raises rather than falling back to a
    projection.

    **Two wire shapes are supported (D-086).** If the registry entry declares
    ``tenor_labels``, the endpoint is the provider's *single-call* curve command
    — one request returning every tenor as a wide frame with a ``maturity``
    label column — and the loop below pivots that one response. Otherwise the
    historical one-request-per-tenor path is used unchanged.

    The single-call shape exists because the audit measured **11 separate
    requests where the provider offers one** (``docs/OPENBB_UTILIZATION_AUDIT.md``
    §3.1): ``fixedincome.government.yield_curve`` returns the whole Treasury
    curve in a single call, and the engine was issuing one request per tenor
    against ``economy.fred_series``. The two paths return **identical values**
    (live-verified 2026-09-21: 1mo 3.97, 10yr 4.94, 30yr 5.29 on both), so the
    change is a request-count change, not a value change.

    Three things the single-call path must get right, each of which is a silent
    failure if it does not:

    * **The label mapping is declared in config, not hardcoded.** The provider's
      labels (``month_1``, ``year_10``) are not the registry's tenors (``1mo``,
      ``10yr``), and a partial mapping is refused **before any request** rather
      than surfacing later as a missing-row error that blames the provider for
      the registry's own gap.
    * **The scale is applied on this path too.** The dedicated command returns
      the curve as a **decimal** (0.0494) where ``economy.fred_series`` returns
      **percent** (4.94) — measured. The conversion is therefore a declared,
      derived property of the registry entry (``source_units: decimal`` →
      ``unit_scale_to_units: 100.0``) applied at the one site that publishes a
      curve value, so the two paths cannot disagree about scale.
    * **Rows are attributed by the provider's label, never by position.** The
      pivot is keyed on ``maturity``; a response carrying no such column is
      refused rather than assigned in row order, because a positional read
      silently mis-assigns an entire curve.
    * **A window parameter the route ignores is not sent.** The single-call
      endpoint is latest-only (measured 2026-09-21: ``start_date`` changes
      nothing), so the registry declares ``window_filter_supported: false`` and
      the request omits ``start_date`` entirely. The O-7 forward-dated filter
      below still runs and is still correct, but on THIS route it is
      belt-and-braces rather than load-bearing: a latest-only response cannot
      carry a forward-dated row for it to catch. It remains the load-bearing
      guard on the one-request-per-tenor path, which can return a projection.
    """
    if not entry.tenors:
        raise OpenBBFetchError(f"curve '{field_name}' declares no tenors")

    endpoint = entry.endpoint or "economy.fred_series"
    cutoff = (as_of or utc_now()).date()
    tenors: dict[str, float] = {}
    latest_date: date | None = None
    withheld_by_tenor: dict[str, int] = {}

    single_call = bool(entry.tenor_labels)
    single_call_rows: dict[str, list[tuple[date, float]]] = {}

    if single_call:
        if set((entry.tenor_labels or {}).keys()) != set(entry.tenors.keys()):
            missing = sorted(set(entry.tenors) - set(entry.tenor_labels or {}))
            raise OpenBBFetchError(
                f"curve '{field_name}' declares tenor_labels that omits {missing}; "
                "the single-call shape needs one provider label per declared tenor, "
                "and a partial mapping would silently drop those tenors."
            )
        # Do not send a window parameter the route ignores. Measured live
        # 2026-09-21: `fixedincome/government/yield_curve` returns the same 11
        # rows for `start_date=2026-09-15` as for no `start_date` at all — it is
        # a latest-only snapshot endpoint. Sending the parameter anyway would
        # make this function claim a bounded window it does not have, and would
        # leave the O-7 forward-dated guard below unable to fire (a latest-only
        # response cannot contain a forward-dated row). The registry declares
        # `window_filter_supported: false` and this is where that declaration is
        # consumed rather than merely recorded.
        curve_params: dict[str, object] = (
            {"start_date": start} if entry.window_filter_supported else {}
        )
        wide = client.fetch_series(
            provider=entry.provider,
            endpoint=endpoint,
            params=curve_params,
            series_label=field_name,
        )
        if wide.empty:
            raise OpenBBFetchError(
                f"curve '{field_name}' single-call endpoint {endpoint} returned no observations"
            )
        # `_normalize` has already reduced the response to date/value, so the
        # maturity label has to survive that reduction for the pivot to work.
        # If it did not, the result is a wide frame whose rows cannot be
        # attributed to a tenor — refused rather than mis-assigned.
        if "maturity" not in wide.columns:
            raise OpenBBFetchError(
                f"curve '{field_name}' is configured for the single-call shape "
                f"(tenor_labels declared) but the normalized frame from {endpoint} "
                f"carries no 'maturity' column to pivot on; got {wide.columns.tolist()}. "
                "Refusing to attribute rows to tenors by position, which would "
                "silently mis-assign an entire curve."
            )
        for _, row in wide.iterrows():
            raw_date = row["date"]
            row_date = (
                raw_date.date()
                if isinstance(raw_date, pd.Timestamp)
                else pd.Timestamp(raw_date).date()
            )
            single_call_rows.setdefault(str(row["maturity"]).strip().lower(), []).append(
                (row_date, float(row["value"]))
            )

    for tenor, symbol in entry.tenors.items():
        if single_call:
            label = str((entry.tenor_labels or {})[tenor]).strip().lower()
            series_points = single_call_rows.get(label, [])
            if not series_points:
                raise OpenBBFetchError(
                    f"curve '{field_name}' tenor '{tenor}' (provider label "
                    f"'{label}', declared symbol {symbol}) has no row in the "
                    f"response from {endpoint}"
                )
            tenor_dates = [d for d, _ in series_points]
            tenor_values = [v for _, v in series_points]
        else:
            frame = client.fetch_series(
                provider=entry.provider,
                endpoint=endpoint,
                params={"symbol": symbol, "start_date": start},
                series_label=f"{field_name}.{tenor}",
            )
            if frame.empty:
                raise OpenBBFetchError(
                    f"curve '{field_name}' tenor '{tenor}' (symbol {symbol}) "
                    "returned no observations"
                )
            # The O-7 filter. Normalise the provider's date column to calendar
            # dates WITHOUT dropping rows, so the withheld count is measurable
            # rather than inferred from a row-count difference.
            tenor_dates = [
                raw.date() if isinstance(raw, pd.Timestamp) else pd.Timestamp(raw).date()
                for raw in frame["date"].tolist()
            ]
            tenor_values = [float(v) for v in frame["value"].tolist()]

        realised_positions = [i for i, d in enumerate(tenor_dates) if d <= cutoff]
        withheld = len(tenor_dates) - len(realised_positions)

        if not realised_positions:
            raise OpenBBFetchError(
                f"curve '{field_name}' tenor '{tenor}' (symbol {symbol}) has no "
                f"observation dated on or before {cutoff.isoformat()} — every point is "
                "forward-dated. A projection is not a realised yield (O-7); the curve "
                "is reported unavailable rather than built from a forecast."
            )

        # The latest REALISED row, by date. Not the last row in the frame.
        last_index = max(realised_positions, key=lambda i: tenor_dates[i])
        tenor_date = tenor_dates[last_index]
        if latest_date is None or tenor_date > latest_date:
            latest_date = tenor_date
        # The declared scale is applied here for the same reason it is applied in
        # `_points_from_frame`: one conversion site, so a curve cannot be scaled
        # on one path and left raw on another.
        scale = 1.0 if entry.unit_scale_to_units is None else float(entry.unit_scale_to_units)
        tenors[tenor] = tenor_values[last_index] * scale
        if withheld:
            withheld_by_tenor[tenor] = withheld

    if withheld_by_tenor:
        # Reported, never silent: a curve whose tenors disagree about how much
        # history was withheld is a warning sign in its own right, and the
        # numbers are what let a reader see it.
        logger.warning(
            "curve '%s': withheld forward-dated observation(s) per tenor %s "
            "(kept observation_date <= %s)",
            field_name,
            withheld_by_tenor,
            cutoff.isoformat(),
        )

    return YieldCurveSnapshot(
        as_of=latest_date or cutoff,
        tenors=tenors,
        retrieved_at=utc_now(),
    )


def _apply_validation(
    snapshot: MacroDataSnapshot,
    raw_by_field: dict[str, list[ObservationPoint]],
) -> MacroDataSnapshot:
    """Run per-series validation and return a snapshot carrying the findings.

    Every per-series rule — bounds, ``forward_looking``, the same-day tolerance —
    comes from :func:`validate_registry_series`, the SAME call the re-validation
    path (``validate_snapshot``) makes, so a new series is validated the moment
    it is registered rather than when someone remembers to add a rule here, and
    the two paths cannot disagree.

    They did disagree, twice, until this was unified (F-SB-001 / F-SB-002):
    this function applied the registry's LEVEL lower bound to ``signed_series``
    entries (reporting a legitimate negative spread change as
    ``VALUE_BELOW_MIN``), and it used ``unemployment_rate``'s narrower registry
    range ``(0.0, 25.0)`` instead of the configured ``(0.0, 100.0)``. Both were
    already correct in ``validate_snapshot``, which is why the suite was green:
    the tests exercised the re-validation path, and this is the path that runs.
    A third, latent drift went with them — this copy passed
    ``future_date_tolerance_days`` raw where the other cast it with ``int()``.

    Emptiness is deliberately NOT validated here. ``SnapshotBuildReport.as_flags``
    owns it, being the only layer that can tell "requested and empty" from "not
    part of this snapshot"; emitting it from both produced two flags for one
    condition on every build (F-SB-006).
    """
    registry = get_registry()
    aggregate = ValidationReport()

    for field_name, points in raw_by_field.items():
        entry = registry.series.get(field_name)
        # `required` is deliberately NOT passed: emptiness is owned by
        # `SnapshotBuildReport.as_flags`, the only layer that can distinguish
        # "requested and empty" from "not in this snapshot". Passing it here too
        # produced two flags for one condition (F-SB-006).
        aggregate.extend(validate_registry_series(points, entry, series_id=field_name))

    for curve_field in CURVE_FIELDS:
        curve = getattr(snapshot, curve_field, None)
        if curve is not None:
            aggregate.extend(validate_yield_curve(curve, series_id=curve_field))

    # attach_flags returns a COPY carrying the findings, because provenance is
    # immutable once built. Returning that copy IS the application of the flags
    # — and the caller must not append the findings a second time, which would
    # duplicate every validation flag on the snapshot.
    return attach_flags(snapshot, aggregate)


def _resolve_release_index(report: SnapshotBuildReport) -> ReleaseDateIndex | None:
    """Resolve release timing from the primary source, falling back to the calendar.

    Returns ``None`` only when no source is enabled — which is a configuration
    choice, not a failure, and is recorded as such. The two sources are merged
    with **primary winning on conflict**, because the primary is the provider's
    own statement for that series while the calendar is an inferred join; where
    both have an opinion, the direct one is the better fact.

    ``release_source`` on the report records which source supplied the index, so
    a reader can tell "43 series from metadata" apart from "3 from the events
    calendar" without re-running anything.

    The three report states are deliberately distinct, and the primary path used
    to collapse two of them
    ----------------------------------------
    ``release_calendar_read`` is tri-state, and ``as_flags`` relies on that:
    ``True`` means a source answered, ``False`` means a source was **asked and
    could not be read** (release timing is UNKNOWN everywhere, which a consumer
    reading only flags must be able to see), and ``None`` means **nobody asked**
    (disabled, or an index was injected), which is a config choice and raises no
    flag.

    The primary path only ever set ``True``. So when ``publication_dates`` was
    enabled and asked but came back with nothing — a total outage of the source
    that carries 42/42 coverage — the flag stayed ``None`` and the snapshot
    reported no release-timing problem at all. That is the exact conflation this
    module exists to prevent, one level up: a silent gap reading as a clean
    snapshot. A partial read is not an outage (``route_read`` is True when *any*
    series answered), so only the zero-of-42 case marks the flag False.
    """
    registry = get_registry()

    primary: ReleaseDateIndex | None = None
    if registry.publication_dates.enabled:
        try:
            primary = fetch_publication_dates()
        except PublicationDateError as exc:
            logger.error("publication-date source misconfigured: %s", exc)
            report.release_calendar_note = f"publication_dates misconfigured: {exc}"
        except Exception as exc:
            # An unexpected fault in an OPTIONAL enrichment must never take the
            # snapshot down with it. This is broader than the other handlers
            # here deliberately: the value of this source is real but not
            # load-bearing, so the blast radius of a bug in it is bounded to
            # "release timing unknown" rather than "no snapshot".
            logger.exception("publication-date source failed unexpectedly: %s", exc)
            report.release_calendar_note = f"publication_dates error: {type(exc).__name__}"

    if primary is not None and primary.route_read:
        report.release_source = "publication_dates"
        report.release_calendar_read = True
        report.release_calendar_series = len(primary.dates)
    elif primary is not None:
        # Enabled, asked, and not one series came back. This is an OUTAGE, and it
        # is the state that used to be invisible: no flag was raised, so a
        # snapshot whose release timing was unknown for all 42 series looked
        # exactly like one where the calendar was switched off on purpose.
        logger.warning(
            "publication_dates was enabled and queried but returned no series; "
            "release timing is UNKNOWN for every series (%s)",
            report.release_calendar_note or "no per-series reason recorded",
        )
        report.release_calendar_read = False
        report.release_timing_outage_source = "publication_dates"
        if report.release_calendar_note is None:
            report.release_calendar_note = "publication_dates returned no series"

    fallback: ReleaseDateIndex | None = None
    if registry.release_calendar.enabled:
        try:
            fallback = fetch_release_dates()
        except ReleaseCalendarError as exc:
            logger.error("release calendar misconfigured: %s", exc)
            report.release_calendar_note = f"release_calendar misconfigured: {exc}"
        else:
            if fallback.route_read and report.release_source is None:
                report.release_source = "release_calendar"
                report.release_calendar_read = True
                report.release_calendar_series = len(fallback.dates)
            elif not fallback.route_read and report.release_source is None:
                report.release_calendar_read = False
                report.release_timing_outage_source = "release_calendar"

    if primary is not None and fallback is not None and primary.route_read:
        # Primary wins per-series; the fallback fills only what it lacks.
        merged = {**fallback.dates, **primary.dates}
        return ReleaseDateIndex(
            dates=merged,
            match_counts={
                name: primary.match_counts.get(name, 0) or fallback.match_counts.get(name, 0)
                for name in merged
            },
            route_read=True,
        )
    if primary is not None and primary.route_read:
        return primary
    if fallback is not None:
        return fallback
    if primary is not None:
        return primary
    return None


def _fetch_fx_spot_map(
    client: OpenBBClient,
    report: SnapshotBuildReport,
    *,
    start: str,
) -> dict[str, list[ObservationPoint]]:
    """Fetch every configured FX pair into one ``{symbol: points}`` mapping.

    **Why this is a separate step and not part of the per-field loop.** The loop
    above sets one attribute per registry entry, and ``fx_spot`` is a *dict of
    series*. That structural mismatch is the entire reason the field has been
    declared on the schema and empty in every build (recorded as
    ``declared_not_wired`` immediately above). Providing the mapping here is what
    turns that disclosure into a fetch.

    Contract, chosen to match the loop it sits beside:

    * A **pair not in the catalogue** and a **fetch that failed** are different
      facts and are reported differently: the first appends to ``failed`` with a
      message naming the catalogue, the second with the resolved pair's error.
      Neither aborts the build — one pair failing must not cost every other pair,
      exactly as one scalar series failing does not cost the snapshot.
    * An **empty result is impossible**: ``fetch_fx_spot`` raises rather than
      returning an empty list, so there is no path by which a pair lands in the
      mapping with zero points. That is deliberate — a key present with an empty
      list would read downstream as "this pair was fetched and has no data",
      which is the ambiguity the module exists to remove.
    * A **disabled (empty) list** returns ``{}`` without a request. That is a
      configuration choice, not a failure, so nothing is appended to ``failed``.

    Returns
    -------
    dict[str, list[ObservationPoint]]
        ``{symbol: series}`` for the pairs that fetched, ready to assign to
        ``snapshot.fx_spot``.
    """
    settings = get_settings()
    configured = list(settings.fx_pairs.enabled)
    if not configured:
        return {}

    readings: dict[str, list[ObservationPoint]] = {}
    for symbol in configured:
        key = symbol.strip().upper().replace("/", "").replace("-", "")
        if key not in FX_PAIRS:
            # Named in config but absent from the catalogue. Reported rather than
            # derived as a cross: a chained leg carries a bid/ask and timing
            # convention the caller did not supply.
            report.failed[f"fx_spot.{key}"] = (
                f"not in the FX pair catalogue ({sorted(FX_PAIRS)}); a pair must be "
                "registered in fx_client.FX_PAIRS before a build can fetch it, "
                "and it is not derived as a cross"
            )
            logger.error("FX pair '%s' is not in the catalogue; skipping", key)
            continue
        try:
            reading = fetch_fx_spot(key, client=client, start_date=date.fromisoformat(start))
        except FxReadError as exc:
            report.failed[f"fx_spot.{key}"] = str(exc)[:200]
            logger.error("failed to fetch FX pair '%s': %s", key, exc)
            continue
        except Exception as exc:
            # Broad on purpose, and the same contract the per-field loop uses: a
            # bug in ONE pair must not cost every other pair or the snapshot. An
            # unexpected fault in an OPTIONAL enrichment still lands in `failed`
            # rather than escaping build_snapshot.
            report.failed[f"fx_spot.{key}"] = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("unexpected error fetching FX pair '%s'", key)
            continue
        if reading is None:  # pragma: no cover - guarded by the catalogue check above
            report.failed[f"fx_spot.{key}"] = "unregistered pair returned no reading"
            continue
        readings[reading.pair.symbol] = reading.pair.series
        report.observation_counts[f"fx_spot.{reading.pair.symbol}"] = reading.observation_count
        logger.info(
            "FX spot %s: %d observation(s) from %s",
            reading.pair.symbol,
            reading.observation_count,
            reading.source,
        )
    return readings


def build_snapshot(
    country: str = "us",
    *,
    client: OpenBBClient | None = None,
    fields: list[str] | None = None,
    persist: bool = False,
    release_index: ReleaseDateIndex | None = None,
) -> tuple[MacroDataSnapshot, SnapshotBuildReport]:
    """Assemble a ``MacroDataSnapshot`` from registry-verified series.

    Parameters
    ----------
    country:
        Only ``"us"`` is implemented (Section 22.3). Anything else raises.
    client:
        Injected for testability. Defaults to a freshly constructed client.
    fields:
        Override the configured field list. Defaults to
        ``settings.snapshot_fields.{country}``.
    persist:
        Write the snapshot to the parquet audit trail (Section 5.5).
    release_index:
        A pre-fetched Section 6 release calendar. When ``None`` AND the calendar
        is enabled in ``config/series_registry.yaml``, the calendar is read once
        here. Passing one explicitly (including an empty
        ``ReleaseDateIndex()``) skips the lookup entirely — which is how tests
        and offline callers keep a network read out of the build.

    Returns
    -------
    (snapshot, report)
        The report is not optional: a caller that ignores it cannot tell a
        complete snapshot from a half-empty one.
    """
    from macro_engine.data_layer import persistence as persistence_module
    from macro_engine.data_layer.schemas import MacroDataSnapshot

    settings = get_settings()

    # Section 22.3: no function may claim country-genericity it has not earned.
    if country not in settings.country.implemented:
        raise NotImplementedError(
            f"country '{country}' is not implemented. Implemented: "
            f"{sorted(settings.country.implemented)} (Section 22.3)."
        )

    client = client if client is not None else OpenBBClient()
    requested = (
        list(fields) if fields is not None else list(settings.snapshot_fields.get(country, []))
    )
    if not requested:
        raise ValueError(
            f"no snapshot fields configured for country '{country}'. "
            "Set snapshot_fields.us in config/settings.yaml."
        )

    report = SnapshotBuildReport()
    report.requested = list(requested)

    # D3 — the DECLARED-BUT-UNWIRED mapping fields. ``commodity_spot`` and
    # ``equity_index`` are declared on the schema, are validated, and round-trip
    # through persistence, but they are DICTS OF SERIES rather than series, so
    # the loop below — which sets one attribute per registry entry — can never
    # fill them. Nothing is asked for and nothing fails, so without this they are
    # invisible: an empty dict reads the same as "no data this run". The ``gdi``
    # omission was the same class (declared everywhere, absent from the one list
    # the builder iterates) and cost a series its data path for a whole phase.
    # Named here so it cannot recur silently.
    #
    # ``fx_spot`` LEFT this disclosure on 2026-10-10, when the FX layer landed.
    # It is the same *shape* as the other two, but it now has its own fetch step
    # (:func:`_fetch_fx_spot_map`) precisely BECAUSE the loop cannot reach it, so
    # disposing of the defect meant adding the step, not relabelling the field.
    # ``FX_UNWIRED_ALWAYS`` is the canonical list of the ones still unreachable;
    # the intersection with ``MAPPING_SERIES_FIELDS`` keeps the two declarations
    # from drifting (LAW 2).
    report.declared_not_wired = sorted(
        f
        for f in persistence_module.MAPPING_SERIES_FIELDS
        if f in FX_UNWIRED_ALWAYS and f not in requested
    )

    # Section 6: resolve release timing ONCE, before any series fetch, so every
    # point in the snapshot is labelled against a single read.
    #
    # Two sources, in a deliberate order. `publication_dates` is PRIMARY because
    # it is direct — the provider states `last_updated` on the series' own
    # metadata record, verified at 42/42 registry coverage — rather than
    # inferring a series' release from a scheduled events calendar through a
    # hand-maintained event-name join. `release_calendar` is the FALLBACK: it
    # covers series the metadata route misses, and it is the only source for
    # event-driven series with no provider symbol.
    #
    # A failure in either is tolerated rather than fatal — an unreadable source
    # leaves `release_datetime` None (UNKNOWN), and it must not cost the caller
    # the whole snapshot.
    if release_index is None:
        release_index = _resolve_release_index(report)

    start = _lookback_start()
    snapshot = MacroDataSnapshot(country=country, as_of=utc_now())
    raw_by_field: dict[str, list[ObservationPoint]] = {}

    for field_name in requested:
        entry = get_registry().series.get(field_name)
        if entry is None:
            report.failed[field_name] = "not_defined_in_registry"
            logger.error("snapshot field '%s' is not defined in the series registry", field_name)
            continue

        try:
            get_registry().require_verified(field_name)
        except NotImplementedError as exc:
            # Unverified / blocked: an explicit, reported absence — never a
            # silent substitution and never a guessed default.
            report.skipped_unverified.append(field_name)
            logger.warning("skipping unverified series '%s': %s", field_name, exc)
            continue

        try:
            target = resolve_snapshot_field(field_name, entry)
            _assert_field_exists(field_name, target)

            if field_name in CURVE_FIELDS or entry.tenors:
                # The snapshot's own as_of, so a curve and the scalars beside it
                # describe a single instant and the O-7 filter agrees with every
                # other series consumer.
                curve = fetch_curve(client, field_name, entry, start=start, as_of=snapshot.as_of)
                setattr(snapshot, target, curve)
                report.observation_counts[field_name] = len(curve.tenors)
            else:
                points = fetch_field(
                    client, field_name, entry, start=start, release_index=release_index
                )
                setattr(snapshot, target, points)
                # Keyed by the REGISTRY field name, not the snapshot attribute:
                # `_apply_validation` looks the bounds up with
                # `registry.series.get(...)`, and the two differ for any entry
                # declaring `snapshot_field` (treasury_curve -> yield_curve).
                # Keying by the attribute would silently find no entry and skip
                # that series' bounds.
                raw_by_field[field_name] = points
                report.observation_counts[field_name] = len(points)
                snapshot.field_sources[field_name] = f"{entry.provider}:{entry.symbol}"
            report.succeeded.append(field_name)
        except OpenBBFetchError as exc:
            report.failed[field_name] = str(exc)[:200]
            logger.error("failed to fetch '%s': %s", field_name, exc)
        except Exception as exc:
            report.failed[field_name] = f"{type(exc).__name__}: {exc}"[:200]
            logger.exception("unexpected error fetching '%s'", field_name)

    # Section 22.3's FX layer. ``fx_spot`` is a MAPPING of series, so the loop
    # above cannot reach it — the structural reason it was declared-but-empty for
    # the project's whole life. It is fetched here, after the scalars, because it
    # is not a registry field and follows a different contract (its own pair
    # catalogue, its own error type). This is the step that converts the D-137
    # disclosure into a fetch, which is why ``declared_not_wired`` above now
    # excludes it.
    fx_map = _fetch_fx_spot_map(client, report, start=start)
    if fx_map:
        snapshot.fx_spot = fx_map
        for symbol in fx_map:
            snapshot.field_sources[f"fx_spot.{symbol}"] = "openbb:currency.price.historical"

    # Validation flags are already merged by _apply_validation (attach_flags
    # returns a copy); only the build-report flags remain to add. Appending
    # findings again here would double every validation flag.
    snapshot = _apply_validation(snapshot, raw_by_field)
    snapshot.data_quality_flags = [*snapshot.data_quality_flags, *report.as_flags()]

    # Last line of defence before the snapshot leaves the data layer. Every
    # ObservationPoint built above passed field validation, but a snapshot can
    # also be assembled from a cache or a parquet round-trip, and this is the
    # only chokepoint every path shares. Raising is deliberate: a non-finite
    # value that reaches the models layer produces `nan` in an interpretation
    # string, which reads as a real number in prose (Section 21.0 rule 2).
    snapshot.assert_finite()

    if persist:
        persistence_module.write_snapshot(snapshot)

    logger.info("snapshot build complete: %s", report.summary())
    return snapshot, report
