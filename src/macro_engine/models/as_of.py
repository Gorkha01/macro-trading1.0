"""Point-in-time discipline for model inputs (AGENTS.md Section 5.5, O-7).

Why this module exists
----------------------
`gdp_potential` is FRED ``GDPPOT`` — CBO's Real Potential GDP. A live snapshot
retrieved 62 observations of it, **41 of which were dated after the retrieval
date**. CBO does not publish only history in that series; it publishes the
projection path alongside it, roughly a decade ahead.

A naive ``points[-1]`` read therefore computes the current output gap against a
**2036 projection**. That is the worst kind of defect this system can carry:
the arithmetic is correct, the number is plausible, and it is meaningless —
``(GDPC1 now - GDPPOT 2036) / GDPPOT 2036`` is not an output gap, it is a
subtraction across eleven years of assumed growth.

Section 21.2 Step 6 is what surfaced this; O-7 is the standing obligation it
created. Rather than fixing it inside `output_gap()` alone, it is fixed here
and used by every model that consumes a series, so the discipline is a property
of the models layer rather than a habit each function has to remember.

Design choices
--------------
**The filter is by ``observation_date``, not by ``retrieved_at``.** A model
describes a state of the world at a point in time; the observation date is what
dates the economic fact. Two snapshots built a minute apart with different
retrieval stamps describe the same quarter of GDP, and the arithmetic must
agree.

**This filter is SUFFICIENT but not SOUND (Section 6).** Excluding points dated
after ``as_of`` is necessary and is done. It is not *sufficient* to guarantee
that everything retained was knowable at ``as_of``, because publication lags
the observation: a month's CPI is stamped the 1st of that month but published
around mid-*following*-month, so an ``as_of`` equal to the observation date
admits a value that had not been released yet. Closing that gap requires
``release_datetime``, which no route reachable from this installation returns
(measured 2026-09-19 — see ``ObservationPoint``). The consequence is stated
plainly rather than hidden: **an ``as_of`` inside one reporting lag of the
newest observation may include not-yet-public data.** The honest use of this
module today is backtesting *at or after* the release, not replaying a decision
made before it.

**No silent truncation.** ``observation_as_of`` returns a report naming how
many points were withheld and the horizon they extended to. A model can then
either disclose the truncation in its ``warnings`` or refuse to compute. What
it cannot do is quietly discard eleven years of data and present the remainder
as the whole series.

**Empty is a hard stop, not an empty default.** A series whose every point is
future-dated has no realised value at all. Returning ``None`` — never ``0.0``,
never the first projection — forces the caller to handle absence explicitly,
which is Section 21.4's whole point: a system that cannot say "I don't know"
will fabricate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from macro_engine.data_layer.schemas import ObservationPoint
from macro_engine.models.contracts import utc_now

__all__ = [
    "AsOfSeries",
    "latest_observation",
    "observation_as_of",
    "observation_on_or_before",
]


@dataclass(frozen=True)
class AsOfSeries:
    """The realised portion of a series, plus what was withheld.

    ``points`` contains only observations dated on or before the as-of instant,
    sorted oldest-first. ``withheld`` is how many later-dated points existed —
    for ``gdp_potential`` on a live snapshot that is 41, and its presence is
    itself informative: it confirms the projection block is still attached and
    that the filter is doing work rather than trivially passing everything
    through.
    """

    points: list[ObservationPoint]
    as_of: datetime
    series_id: str
    withheld: int = 0
    withheld_horizon: date | None = None

    @property
    def is_empty(self) -> bool:
        """True when the series had no realised observations at all.

        Distinct from "the caller passed an empty list": that is a fetch
        failure, whereas an empty ``AsOfSeries`` means the series exists but is
        entirely forward-dated. The two produce different messages because they
        are different problems.
        """
        return not self.points

    @property
    def latest(self) -> ObservationPoint | None:
        """The most recent realised observation, or None if there is none."""
        return self.points[-1] if self.points else None

    @property
    def was_truncated(self) -> bool:
        return self.withheld > 0

    def truncation_warning(self, *, series_label: str | None = None) -> str | None:
        """A warning string describing the withheld forward points, or None.

        Returned rather than appended so the caller controls the wording and
        decides whether the truncation matters for its own conclusion. A model
        whose result is *about* a forward horizon (a projection, not a
        measurement) would be wrong to warn about it.
        """
        if not self.was_truncated:
            return None
        label = series_label or self.series_id
        horizon = f" to {self.withheld_horizon.isoformat()}" if self.withheld_horizon else ""
        return (
            f"{label}: {self.withheld} forward-dated observation(s){horizon} withheld — "
            f"only data as of {self.as_of.date().isoformat()} was used."
        )


def observation_as_of(
    points: Sequence[ObservationPoint],
    *,
    as_of: datetime | None = None,
    series_id: str | None = None,
) -> AsOfSeries:
    """Restrict a series to the observations that existed at ``as_of``.

    Parameters
    ----------
    points:
        Observations, in any order. Sorted internally — a provider's ordering is
        not a contract, and ``[-1]`` on an unsorted list silently picks an
        arbitrary point rather than the latest one.
    as_of:
        The point in time to evaluate at. Defaults to now. Pass the snapshot's
        ``as_of`` when reproducing a historical snapshot, so the filter and the
        snapshot agree about what "now" means.
    series_id:
        Overrides the identifier recorded on the result. Useful when a series is
        constructed by the caller (e.g. a derived series) or when a snapshot
        field holds points whose own ``series_id`` differs from the field name.

    Returns
    -------
    AsOfSeries
        ``.points`` filtered and sorted; ``.withheld`` / ``.withheld_horizon``
        describing what was excluded.

    Notes
    -----
    Comparison is by calendar date. An observation dated today is included when
    ``as_of`` is any instant today: a quarterly national-accounts figure is
    stamped with a date, not a timestamp, and excluding it because ``as_of`` is
    06:00 on the stamp date would be a false exclusion. The timezone of
    ``as_of`` is never in question — ``utc_now()`` and every snapshot timestamp
    in this codebase are UTC-aware.
    """
    moment = as_of or utc_now()
    cutoff = moment.date()

    realised = [p for p in points if p.observation_date <= cutoff]
    withheld_points = [p for p in points if p.observation_date > cutoff]

    realised.sort(key=lambda p: p.observation_date)

    return AsOfSeries(
        points=realised,
        as_of=moment,
        series_id=series_id or (points[0].series_id if points else "unknown"),
        withheld=len(withheld_points),
        withheld_horizon=max((p.observation_date for p in withheld_points), default=None),
    )


def latest_observation(
    points: Sequence[ObservationPoint],
    *,
    as_of: datetime | None = None,
) -> ObservationPoint | None:
    """The most recent realised observation, or None.

    The one-line form of ``observation_as_of(points, as_of=...).latest``, for
    callers that need the value and nothing else. Returning ``None`` rather
    than raising keeps the "series unavailable" decision with the caller, in
    line with Section 21.4.
    """
    return observation_as_of(points, as_of=as_of).latest


def observation_on_or_before(
    points: Sequence[ObservationPoint],
    target: date,
) -> ObservationPoint | None:
    """The most recent observation dated on or before ``target``.

    Deliberately *not* routed through ``observation_as_of``: this answers "what
    did the series say at date X in its own history", which is used to pair a
    quarterly series with a monthly one (e.g. comparing a Q2 GDP print against
    the CPI reading of that same quarter). Applying today's cutoff there would
    be right by accident and wrong for a historical snapshot.
    """
    eligible = sorted(
        (p for p in points if p.observation_date <= target),
        key=lambda p: p.observation_date,
    )
    return eligible[-1] if eligible else None
