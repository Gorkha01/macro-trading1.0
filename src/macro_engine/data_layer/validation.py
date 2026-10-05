"""Sanity checks over fetched data (AGENTS.md Section 5.4).

Runs on every returned ``ObservationPoint`` list and on every
``YieldCurveSnapshot``. The governing principle is **flag, don't fix**: an
anomaly is appended to ``MacroDataSnapshot.data_quality_flags`` and reported,
never silently dropped and never silently corrected.

Why this matters more than it looks: a silently-dropped observation changes a
YoY calculation by making the wrong two points adjacent, and a silently-clamped
one fabricates a number. Both produce output that looks completely normal.

**What the flag list does and does not reach (re-measured 2026-10-05).** The
flags are what a reader sees; they are **not** a general confidence penalty. An
earlier version of this docstring claimed the flag list "is also what
``compute_confidence()`` reads — so a flagged snapshot *cannot* report high
confidence downstream." That was **false**: ``compute_confidence`` reads a
**per-model** boolean (``ConfidenceInputs.data_quality_flags_present``,
``models/contracts.py``) that most models set from **their own** inputs —
``commodities.py`` from ``fetched_legs < 2``, ``equity_macro.py`` from
``not has_prior``, ``convergence.py`` from its constituent signals.

**ONE model is the exception, and it is named here rather than left to a
grep.** ``gdp_nowcast.py`` DOES read ``snapshot.data_quality_flags`` and
re-prices its own result's confidence with ``data_quality_flags_present=True``
whenever any flag is present (``models/gdp_nowcast.py``, "a flagged snapshot
must not report unflagged confidence"). So the previous claim that "No model
reads ``snapshot.data_quality_flags`` into ``ConfidenceInputs``" — and that
"nothing here does it for them" — was **FALSE for that one function**, and the
``grep`` the old text cited is what finds it. For every OTHER model a snapshot
may carry flags while the model still reports full confidence; a consumer that
needs the flags to reduce confidence must apply that itself. (Audit finding
X-L2 / D-3, Class G — corrected 2026-10-05; the false claim was the reassuring
kind, since it told a reader the obligation was already discharged.)

Each check returns ``ValidationFinding`` records rather than raising, so a
single bad series degrades that series rather than the whole snapshot fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING

from macro_engine.config import get_registry, get_settings
from macro_engine.data_layer.schemas import (
    MacroDataSnapshot,
    ObservationPoint,
    YieldCurveSnapshot,
)

if TYPE_CHECKING:
    from macro_engine.config import RegistrySeries

__all__ = [
    "Severity",
    "ValidationFinding",
    "ValidationReport",
    "attach_flags",
    "registry_bounds",
    "validate_equity_index",
    "validate_observations",
    "validate_positive_index_level",
    "validate_registry_series",
    "validate_snapshot",
    "validate_unemployment_rate",
    "validate_yield_curve",
]


class Severity(str, Enum):
    """How much a finding should erode trust in the data."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ValidationFinding:
    """One anomaly, with enough context to investigate it.

    ``series_id`` + ``detail`` are the minimum needed to reproduce the problem;
    ``severity`` drives the flag string written to the snapshot.
    """

    series_id: str
    code: str
    severity: Severity
    detail: str
    observation_date: date | None = None

    def as_flag(self) -> str:
        """Render as a single ``data_quality_flags`` entry."""
        where = f" @{self.observation_date.isoformat()}" if self.observation_date else ""
        return (
            f"[{self.severity.value.upper()}] {self.series_id}{where}: {self.code} — {self.detail}"
        )


@dataclass
class ValidationReport:
    """Accumulated findings for one snapshot."""

    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity in {Severity.WARNING, Severity.ERROR} for f in self.findings)

    def flags(self) -> list[str]:
        return [f.as_flag() for f in self.findings]

    def extend(self, other: ValidationReport) -> None:
        self.findings.extend(other.findings)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def validate_observations(
    points: list[ObservationPoint],
    *,
    series_id: str,
    min_value: float | None = None,
    max_value: float | None = None,
    required: bool = False,
    forward_looking: bool = False,
    future_date_tolerance_days: int = 0,
) -> ValidationReport:
    """Range, monotonicity-of-date, and future-dating checks for one series.

    ``min_value``/``max_value`` are optional bounds; when omitted only the
    universal checks run. Passing explicit bounds is how the per-series rules
    in Section 5.4 (e.g. unemployment in ``[0, 100]``) are expressed.

    ``required`` distinguishes "this series came back empty and that is a
    problem" from "this series was not requested in this snapshot". Without
    it, a deliberately partial snapshot produces a wall of identical
    EMPTY_SERIES flags, which trains a reader to ignore the flag list — the
    opposite of the intent.

    ``forward_looking`` marks series whose published values legitimately extend
    beyond today, because they are *estimates of the future* rather than
    measurements of the past. FRED ``GDPPOT`` (CBO potential output) is the
    canonical case: it carries projections roughly a decade ahead, and those
    projections are the entire reason the series is useful for the output-gap
    calculation. Treating them as faulty future-dated observations would flag
    41 legitimate data points as ERROR on every single snapshot — which is how
    a real signal gets trained out of a reader. Such points are reported once
    per series as INFO instead, so the horizon is still visible without being
    mislabelled as corruption.

    ``future_date_tolerance_days`` is the different, much smaller case: a
    *daily* series that FRED has already published for the current calendar day
    while the process clock is still on the previous UTC date. It is not a
    projection — the value is a real print — but ``observation_date >
    retrieved_at.date()`` is literally true for it. D-030 recorded three
    recurrences of `iorb @<tomorrow>: FUTURE_OBSERVATION_DATE` before this
    became a declared property of the series. Points inside the tolerance are
    reported once per series as INFO, so a genuine broken mapping (which
    typically lands far outside any tolerance) is still an ERROR while a
    wall-clock artifact is not.
    """
    report = ValidationReport()
    if not points:
        if required:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="EMPTY_SERIES",
                    severity=Severity.WARNING,
                    detail=(
                        "Series was requested but returned no observations — downstream "
                        "models must treat it as unavailable, not as zero."
                    ),
                )
            )
        return report

    seen_dates: set[date] = set()
    previous_date: date | None = None
    future_dates: list[date] = []
    tolerated_future_dates: list[date] = []

    for point in points:
        # --- finiteness ----------------------------------------------------
        # FIRST, because every following check is a comparison and a NaN
        # compares False against all of them: `nan < min`, `nan > max` and
        # `nan == any_date` are all False, so a NaN passes range, duplicate and
        # ordering checks unchallenged. `+inf`/`-inf` are caught by a bound
        # only when the relevant bound is supplied, and 2 of the registry's 45
        # series declare no `plausible_range` at all. Finiteness is therefore
        # the one property that must be checked directly rather than inferred
        # from a threshold (Section 21.0 rule 2).
        if not isfinite(point.value):
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="NON_FINITE_VALUE",
                    severity=Severity.ERROR,
                    detail=(
                        f"value {point.value!r} is not finite. A non-finite value is "
                        "not a missing value: it is present and testable, so no "
                        "downstream check rejects it and the model silently "
                        "propagates nan. The row must be dropped at the source or "
                        "the series reported unavailable."
                    ),
                    observation_date=point.observation_date,
                )
            )

        # --- future dating -------------------------------------------------
        # Compared in UTC-equivalent terms: observation_date is a calendar date
        # and retrieved_at is timezone-aware UTC. A provider stamping tomorrow's
        # date (a known artifact of some timezone-naive feeds) would otherwise
        # silently enter a YoY window.
        if point.observation_date > point.retrieved_at.date():
            lead_days = (point.observation_date - point.retrieved_at.date()).days
            if lead_days <= future_date_tolerance_days:
                tolerated_future_dates.append(point.observation_date)
            else:
                future_dates.append(point.observation_date)
                if not forward_looking:
                    report.findings.append(
                        ValidationFinding(
                            series_id=series_id,
                            code="FUTURE_OBSERVATION_DATE",
                            severity=Severity.ERROR,
                            detail=(
                                f"observation_date {point.observation_date} is after "
                                f"retrieval date {point.retrieved_at.date()} by "
                                f"{lead_days} day(s), beyond this series' declared "
                                f"tolerance of {future_date_tolerance_days}"
                            ),
                            observation_date=point.observation_date,
                        )
                    )

        # --- duplicates ----------------------------------------------------
        if point.observation_date in seen_dates:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="DUPLICATE_OBSERVATION_DATE",
                    severity=Severity.WARNING,
                    detail="Providers sometimes emit revised and original rows; a duplicate date "
                    "will silently double-count in a mean.",
                    observation_date=point.observation_date,
                )
            )
        seen_dates.add(point.observation_date)

        # --- ordering ------------------------------------------------------
        if previous_date is not None and point.observation_date < previous_date:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="NON_MONOTONIC_DATES",
                    severity=Severity.WARNING,
                    detail=f"{point.observation_date} follows {previous_date} out of order.",
                    observation_date=point.observation_date,
                )
            )
        previous_date = point.observation_date

        # --- range ---------------------------------------------------------
        # Each violation is reported per-point. An aggregate counter existed here
        # (``out_of_range``, incremented at both branches and never read) — a dead
        # variable with no consumer, removed 2026-09-29 (audit finding D-3, Class E).
        # Deleting it changes no behaviour: both branches already append their own
        # ERROR finding, so every out-of-range point is visible in ``report``.
        if min_value is not None and point.value < min_value:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="VALUE_BELOW_MIN",
                    severity=Severity.ERROR,
                    detail=f"value {point.value} < permitted minimum {min_value}",
                    observation_date=point.observation_date,
                )
            )
        if max_value is not None and point.value > max_value:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="VALUE_ABOVE_MAX",
                    severity=Severity.ERROR,
                    detail=f"value {point.value} > permitted maximum {max_value}",
                    observation_date=point.observation_date,
                )
            )

    # --- forward-looking horizon -------------------------------------------
    # Collapsed into ONE finding per series. A projection series contributes
    # dozens of forward points; emitting one finding each would bury every
    # other diagnostic under a wall of identical INFO lines.
    if forward_looking and future_dates:
        horizon = max(future_dates)
        report.findings.append(
            ValidationFinding(
                series_id=series_id,
                code="FORWARD_LOOKING_HORIZON",
                severity=Severity.INFO,
                detail=(
                    f"{len(future_dates)} projection(s) extend to {horizon}. Expected for an "
                    f"estimate series — downstream must filter to observation_date <= as_of "
                    f"before treating any value as realised data."
                ),
                observation_date=horizon,
            )
        )
    elif future_dates:
        # Not declared as forward-looking but future-dated points appeared:
        # this is the genuine data-fault path and is already reported per-point
        # above. Add one aggregate line so the scale of the fault is visible
        # even when the individual findings are truncated.
        report.findings.append(
            ValidationFinding(
                series_id=series_id,
                code="FUTURE_DATED_POINTS_SUMMARY",
                severity=Severity.ERROR,
                detail=(
                    f"{len(future_dates)} future-dated observation(s) in a series not declared "
                    f"forward_looking — this is a broken mapping or a bad provider stamp."
                ),
                observation_date=max(future_dates),
            )
        )

    # --- tolerated same-day publication ------------------------------------
    # A daily series the provider has already published for the current
    # calendar day, while the process clock is still on the previous UTC date.
    # The value is real; only the comparison `observation_date > utc_today` is
    # literally true. Reported at INFO so the condition stays visible — a
    # reader can see the feed ran ahead — without asserting a fault.
    if tolerated_future_dates and not forward_looking:
        lead = max(tolerated_future_dates)
        report.findings.append(
            ValidationFinding(
                series_id=series_id,
                code="SAME_DAY_PUBLICATION_AHEAD_OF_CLOCK",
                severity=Severity.INFO,
                detail=(
                    f"{len(tolerated_future_dates)} observation(s) dated {lead}, up to "
                    f"{future_date_tolerance_days} day(s) ahead of the retrieval date — "
                    f"within this series' declared tolerance. The provider published before "
                    f"midnight UTC; the print is real. Not a fault, and NOT an estimate: "
                    f"unlike a forward_looking series these points are realised data."
                ),
                observation_date=lead,
            )
        )

    # --- stale series ------------------------------------------------------
    latest = max(p.observation_date for p in points)
    reference = max(p.retrieved_at.date() for p in points)
    staleness_days = (reference - latest).days
    stale_threshold = get_settings().validation.stale_days
    if staleness_days > stale_threshold:
        report.findings.append(
            ValidationFinding(
                series_id=series_id,
                code="STALE_SERIES",
                severity=Severity.WARNING,
                detail=(
                    f"most recent observation is {staleness_days} days older than retrieval "
                    f"(threshold {stale_threshold}); for a quarterly series this is expected, "
                    f"for a daily series it is not"
                ),
                observation_date=latest,
            )
        )
    return report


def validate_unemployment_rate(points: list[ObservationPoint]) -> ValidationReport:
    """Unemployment must lie within the configured bounds (Section 5.4).

    A value of 150 is the specification's canonical engineered-failure case:
    it must be flagged, not dropped and not accepted.
    """
    low, high = get_settings().validation.unemployment_bounds
    return validate_observations(
        points, series_id="unemployment_rate", min_value=low, max_value=high, required=True
    )


def validate_positive_index_level(
    points: list[ObservationPoint], *, series_id: str
) -> ValidationReport:
    """Raw price-index *levels* cannot be negative (Section 5.4).

    The year-over-year *change* can be negative in deflation — that is a real
    economic state, not an error. Only the level is constrained here. This
    distinction is the whole reason the check is named after the level.
    """
    return validate_observations(points, series_id=series_id, min_value=0.0, required=True)


def validate_yield_curve(
    curve: YieldCurveSnapshot | None, *, series_id: str, required: bool = True
) -> ValidationReport:
    """Yield-curve consistency checks (Section 5.4).

    Two distinct failure modes, deliberately handled differently:

    * **Non-positive yield.** A zero or negative nominal Treasury yield is
      almost always a data fault. Flagged as ERROR.
    * **Implausible inversion.** A *real* inversion happens at the short end
      (Module 8.1) — 2s10s going negative is a genuine, meaningful state and is
      flagged only as INFO. But a 30yr yield far *below* the 10yr is not an
      inversion, it is a broken data point. That distinction is exactly what
      the specification asks this check to preserve: "flag (not silently fix)
      an inverted-looking value that's actually a data error".
    """
    report = ValidationReport()
    if curve is None:
        if required:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="NO_CURVE",
                    severity=Severity.WARNING,
                    detail=(
                        "Yield curve unavailable; curve-dependent models must degrade "
                        "explicitly rather than assuming a flat curve."
                    ),
                )
            )
        return report

    if not curve.tenors:
        report.findings.append(
            ValidationFinding(
                series_id=series_id,
                code="EMPTY_CURVE",
                severity=Severity.WARNING,
                detail="Curve present but carries no tenors.",
            )
        )
        return report

    # A yield of exactly 0.00 is NOT uniformly a fault. Measured against the
    # U.S. Treasury's own Daily Treasury Par Yield Curve Rates, the row for
    # 2020-03-25 reads 1 Mo = 0.00, 3 Mo = 0.00 with every tenor from 6 Mo
    # outward at 0.07 or above; no tenor printed below 0.00 on any 2020 date.
    # So the two cases are separated: a strictly NEGATIVE yield is a fault at
    # every tenor, and a ZERO yield is a fault only at tenors the official
    # series never reached zero on. The permitted set is config, not a literal
    # here, because it is a measured claim that has to be reviewable.
    zero_permitted = get_settings().validation.zero_yield_tenors
    for tenor, yld in curve.tenors.items():
        if yld < 0.0:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="NON_POSITIVE_YIELD",
                    severity=Severity.ERROR,
                    detail=(
                        f"{tenor} yield {yld}% is negative — no US Treasury tenor has "
                        "printed below zero in the official par yield curve, so this is "
                        "a data fault, not a market state."
                    ),
                )
            )
        elif yld == 0.0 and tenor not in zero_permitted:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="NON_POSITIVE_YIELD",
                    severity=Severity.ERROR,
                    detail=(
                        f"{tenor} yield is exactly 0.00%. A zero at this tenor is a data "
                        "fault: the official par yield curve has never printed zero here. "
                        f"(Zero IS a real market state at {sorted(zero_permitted)} — "
                        "measured 2020-03-25 — and is reported there as INFO, not ERROR.)"
                    ),
                )
            )
        elif yld == 0.0:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="ZERO_SHORT_END_YIELD",
                    severity=Severity.INFO,
                    detail=(
                        f"{tenor} yield is exactly 0.00%. This is a real published market "
                        "state at this tenor (the Treasury par curve printed 0.00 for "
                        "1 Mo and 3 Mo on 2020-03-25), not a data fault — so it is NOT "
                        "flagged as an error."
                    ),
                    observation_date=curve.as_of,
                )
            )
        if yld > get_settings().validation.max_yield:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="IMPLAUSIBLE_YIELD_LEVEL",
                    severity=Severity.ERROR,
                    detail=f"{tenor} yield {yld}% exceeds any plausible level.",
                )
            )

    tenors = curve.tenors
    if "2yr" in tenors and "10yr" in tenors:
        slope_bp = (tenors["10yr"] - tenors["2yr"]) * 100
        if slope_bp < 0:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="CURVE_INVERTED_2S10S",
                    severity=Severity.INFO,
                    detail=(
                        f"2s10s at {slope_bp:+.1f}bp — genuine inversion, economically meaningful."
                    ),
                    observation_date=curve.as_of,
                )
            )

    if "10yr" in tenors and "30yr" in tenors:
        long_slope_bp = (tenors["30yr"] - tenors["10yr"]) * 100
        # The long end inverting deeply is not a normal curve shape; it is the
        # canonical symptom of a mis-parsed data row.
        if long_slope_bp < get_settings().validation.long_end_inversion_floor:
            report.findings.append(
                ValidationFinding(
                    series_id=series_id,
                    code="IMPLAUSIBLE_LONG_END_INVERSION",
                    severity=Severity.ERROR,
                    detail=(
                        f"30yr is {abs(long_slope_bp):.0f}bp BELOW 10yr. A slight "
                        f"inversion can be real; one this deep indicates a data "
                        f"fault rather than a market state."
                    ),
                    observation_date=curve.as_of,
                )
            )
    return report


def validate_equity_index(
    series: dict[str, list[ObservationPoint]],
) -> ValidationReport:
    """Equity indices cannot be non-positive."""
    report = ValidationReport()
    for symbol, points in series.items():
        sub = validate_observations(points, series_id=f"equity_index.{symbol}", min_value=0.0)
        report.extend(sub)
    return report


# ---------------------------------------------------------------------------
# Snapshot-level orchestration
# ---------------------------------------------------------------------------


def registry_bounds(
    entry: RegistrySeries | None, *, series_id: str
) -> tuple[float | None, float | None]:
    """The ``(min, max)`` bounds that apply to one series, derived in ONE place.

    Both callers use this — the BUILD path (``snapshot_builder._apply_validation``)
    and the RE-VALIDATION path (:func:`validate_snapshot`) — because two
    hand-copied derivations had already drifted, twice, in opposite directions:

    * ``unemployment_rate``'s configured bounds took precedence in
      ``validate_snapshot`` only, so the build path used the registry's narrower
      ``(0.0, 25.0)`` against a configured ``(0.0, 100.0)``. A reading of 30 was
      an ERROR when built and clean when re-validated.
    * the LEVEL lower bound was suppressed for ``signed_series`` in
      ``validate_snapshot`` only, so the build path reported a legitimate
      negative spread CHANGE as ``VALUE_BELOW_MIN`` — the AUDIT-001 defect
      surviving on the path that actually runs (F-SB-001/F-SB-002).

    A duplicate rule is a rule that can drift; the existing test suite could not
    catch either drift because it exercised ``validate_snapshot`` alone.
    """
    if series_id == "unemployment_rate":
        low, high = get_settings().validation.unemployment_bounds
        return float(low), float(high)
    if entry is None or entry.plausible_range is None:
        return None, None
    low, high = entry.plausible_range
    # A signed field (spread, change, net balance) may legitimately go below the
    # LEVEL range's lower bound. `credit_spread_hy`'s OAS LEVEL has never been
    # negative, so [0.1, 40.0] is the right LEVEL bound — but the same field
    # carries spread CHANGES, and -0.2 is a valid narrowing. The UPPER bound
    # still applies (a spread cannot exceed 40pp); only the lower is suppressed.
    return (None if entry.signed_series else float(low)), float(high)


def validate_registry_series(
    points: list[ObservationPoint],
    entry: RegistrySeries | None,
    *,
    series_id: str,
) -> ValidationReport:
    """Validate one series with EVERY per-series rule derived in one place.

    The single call site for both paths — the build path
    (``snapshot_builder._apply_validation``) and the re-validation path
    (:func:`validate_snapshot`) — because two hand-copied derivations had
    already drifted, and the drift is invisible until it changes a verdict:

    * the LEVEL lower bound was suppressed for ``signed_series`` in one copy
      only (F-SB-001);
    * ``unemployment_rate``'s configured bounds took precedence in one copy only
      (F-SB-002);
    * ``future_date_tolerance_days`` was cast with ``int()`` in one copy and
      passed raw in the other — harmless today (every registry value is an
      ``int``: 57x0, 1x1, 1x3) and wrong the moment one is not (F-SB-005).

    **``required`` is deliberately not a parameter here.** Emptiness is owned by
    ``SnapshotBuildReport.as_flags``, which is the only layer that can
    distinguish "requested and empty" from "not part of this snapshot": a
    snapshot's fields all default to ``[]``, so :func:`validate_snapshot` cannot
    tell them apart and skips empty series. Passing ``required=True`` on the
    build path as well emitted two flags for one condition (F-SB-006); the
    explanatory sentence now travels on the report's flag.
    ``validate_observations(required=True)`` remains reachable through
    :func:`validate_unemployment_rate` / :func:`validate_positive_index_level`.
    """
    min_value, max_value = registry_bounds(entry, series_id=series_id)
    return validate_observations(
        points,
        series_id=series_id,
        min_value=min_value,
        max_value=max_value,
        forward_looking=bool(entry.forward_looking) if entry is not None else False,
        future_date_tolerance_days=(
            int(entry.future_date_tolerance_days) if entry is not None else 0
        ),
    )


def _validated_scalar_series(
    snapshot: MacroDataSnapshot,
) -> list[tuple[str, list[ObservationPoint]]]:
    """The snapshot's populated scalar series, in the order the schema declares.

    Derived from the snapshot schema and the **series registry**, never from a
    hand-maintained list. This is the pluggability contract: a new series
    becomes validated by adding one registry entry and one schema field, with
    no edit to this module (Part B of the 2026-09-19 audit).

    Why that matters, concretely. Before this function existed,
    ``validate_snapshot`` named four hardcoded tuples covering 18 of the
    registry's 45 entries. A series outside those tuples received **no
    validation at all** — no range check, no future-dating check, no staleness
    check — and nothing said so. Worse, the two hardcoded tuples that *did*
    name a series omitted its declared registry properties, so the same
    snapshot was clean when built and error-smeared when re-validated
    (AUDIT-001). Driving from the registry removes both failure modes at once.

    ``not_a_snapshot_field`` entries are skipped: they document a model's input
    provenance and are not part of ``MacroDataSnapshot`` (see
    ``resolve_snapshot_field``).
    """
    registry = get_registry().series
    out: list[tuple[str, list[ObservationPoint]]] = []
    for name in type(snapshot).model_fields:
        points = getattr(snapshot, name)
        if not isinstance(points, list) or not points:
            continue
        if not all(isinstance(p, ObservationPoint) for p in points):
            # Dict-valued fields (fx_spot, commodity_spot, equity_index) and the
            # flag/source lists are handled separately below.
            continue
        entry = registry.get(name)
        if entry is not None and entry.not_a_snapshot_field:
            continue
        out.append((name, points))
    return out


def validate_snapshot(snapshot: MacroDataSnapshot) -> ValidationReport:
    """Run every applicable check and return a combined report.

    Mutates nothing. The caller attaches ``report.flags()`` to
    ``snapshot.data_quality_flags`` — keeping detection and recording separate
    so the report can also be surfaced to an operator without being persisted.

    Absent series are skipped rather than flagged: a snapshot legitimately
    covers whatever was fetched, and a snapshot that requests nothing has
    nothing to be wrong with it. A series that *is* present but violates a
    bound is always flagged.

    **Every bound and every declared property comes from the registry entry**,
    not from a literal in this module. :func:`registry_bounds` supplies the
    ``[min, max]`` pair — including ``unemployment_rate``'s configured-bounds
    precedence and the ``signed_series`` lower-bound suppression —
    ``forward_looking`` selects the INFO horizon branch over the ERROR
    future-dating branch, and ``future_date_tolerance_days`` supplies the
    same-day-publication tolerance.

    ``registry_bounds`` is SHARED with the build path
    (``snapshot_builder._apply_validation``) rather than re-derived here, because
    two hand-copied derivations drifted twice — each time in this function's
    favour, so the suite stayed green while the path that actually runs was
    wrong (F-SB-001 / F-SB-002).

    This makes ``validate_snapshot`` agree with the build path by construction.
    They disagreed before (AUDIT-001): ``build_snapshot`` read the registry and
    correctly reported ``gdp_potential``'s 41 CBO projections as one INFO,
    while this function re-derived from the raw snapshot with no registry
    properties and reported them as 30 ERRORs — the same data, two verdicts,
    and the ERROR verdict was the false one.
    """
    report = ValidationReport()

    for name, points in _validated_scalar_series(snapshot):
        entry = get_registry().series.get(name)
        # ONE derivation for every per-series rule, shared with the build path
        # (see `validate_registry_series`), so the two cannot disagree again.
        report.extend(validate_registry_series(points, entry, series_id=name))

    if snapshot.yield_curve is not None:
        report.extend(validate_yield_curve(snapshot.yield_curve, series_id="yield_curve"))
    if snapshot.tips_yields is not None:
        report.extend(validate_yield_curve(snapshot.tips_yields, series_id="tips_yields"))

    if snapshot.equity_index:
        report.extend(validate_equity_index(snapshot.equity_index))

    for symbol, points in snapshot.fx_spot.items():
        report.extend(validate_observations(points, series_id=f"fx_spot.{symbol}", min_value=0.0))
    for symbol, points in snapshot.commodity_spot.items():
        report.extend(
            validate_observations(points, series_id=f"commodity_spot.{symbol}", min_value=0.0)
        )

    return report


def attach_flags(snapshot: MacroDataSnapshot, report: ValidationReport) -> MacroDataSnapshot:
    """Return a copy of the snapshot carrying the report's flags.

    Copies rather than mutates so that a snapshot's provenance is immutable
    once constructed — the flags a thesis was built on are the flags it
    reports, even if validation is re-run later against fresh data.
    """
    updated = snapshot.model_copy(deep=True)
    updated.data_quality_flags = [*snapshot.data_quality_flags, *report.flags()]
    return updated
