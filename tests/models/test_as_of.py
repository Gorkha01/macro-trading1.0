"""Point-in-time discipline tests (AGENTS.md Section 5.5, O-7) — Card 4.

Why this file exists
--------------------
An audit of the Phase 0-4 tree found that ``models/as_of.py`` was a
**load-bearing module no test imported**: `grep -rn "from macro_engine.models.as_of
import" tests/` was empty. Its four documented contracts — the same-day-inclusion
boundary, the sufficient-but-not-sound lag caveat, the
``observation_on_or_before``-vs-``observation_as_of`` asymmetry, and the "empty is
a hard stop, never 0.0" rule — were asserted nowhere. The module was exercised
only indirectly through consumers, which is the O-133 shape (a name-grep is not a
coverage proxy; a module can be imported by five consumers and still have its own
contracts untested).

The code was measured *correct* on every case in this file before the file was
written. These tests are therefore a **registry of the contracts**, not a bug
hunt: each one names a documented promise and shows it holds. If a future edit
breaks one, this is where it fails.

Every expected value is a date or a count computed independently of the code,
per Section 21.2 Step 4.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from macro_engine.data_layer.schemas import ObservationPoint
from macro_engine.models.as_of import (
    AsOfSeries,
    latest_observation,
    observation_as_of,
    observation_on_or_before,
)
from macro_engine.models.contracts import utc_now

# ---------------------------------------------------------------------------
# Fixtures — hand-built points, so every date in an assertion is one the test
# chose rather than one a helper derived.
# ---------------------------------------------------------------------------


def _point(day: date, value: float, series_id: str = "test_series") -> ObservationPoint:
    """One observation stamped at midnight UTC on ``day``.

    ``retrieved_at`` is set to the observation date plus one day — the ordinary
    "we read it after it was stamped" case. It is deliberately NOT the as-of
    cutoff: ``observation_as_of`` filters on ``observation_date``, and a test
    that let the two coincide would not distinguish the two clocks.
    """
    return ObservationPoint(
        observation_date=day,
        value=value,
        series_id=series_id,
        retrieved_at=datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1),
    )


#: A fixed as-of instant, so no assertion depends on the wall clock.
_AS_OF = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Contract 1 — the same-day inclusion boundary (Class A / date boundary)
# ---------------------------------------------------------------------------


def test_an_observation_dated_exactly_on_the_as_of_day_is_included() -> None:
    """The cutoff is by CALENDAR DATE, so a same-day stamp is retained.

    The module docstring states the rule: "An observation dated today is
    included when ``as_of`` is any instant today: a quarterly national-accounts
    figure is stamped with a date, not a timestamp, and excluding it because
    ``as_of`` is 06:00 on the stamp date would be a false exclusion." This pins
    it, and pins the other half too — a point dated the NEXT day is excluded, so
    the boundary is shown to be a real edge rather than a filter that admits
    everything.

    Measured in the audit as PASS; the point of the test is that it now fails
    loudly if the comparison ever flips to a strict ``<`` or to a timestamp
    comparison.
    """
    same_day = _point(_AS_OF.date(), 1.0)
    next_day = _point(_AS_OF.date() + timedelta(days=1), 2.0)

    report = observation_as_of([same_day, next_day], as_of=_AS_OF)

    assert [p.value for p in report.points] == [1.0]
    assert report.withheld == 1, "the next-day point must be withheld"
    assert report.withheld_horizon == _AS_OF.date() + timedelta(days=1)


def test_the_as_of_instant_within_the_day_does_not_shift_the_boundary() -> None:
    """Two as-of instants on the same calendar day admit the same points.

    The comparison uses ``moment.date()``, so 00:00:01 and 23:59:59 on the same
    day are the same cutoff. This is what makes the previous test's "06:00 on
    the stamp date" example correct, and it is the specific half of the rule a
    timestamp comparison would violate.
    """
    point = _point(date(2026, 6, 15), 1.0)
    start_of_day = datetime(2026, 6, 15, 0, 0, 1, tzinfo=UTC)
    end_of_day = datetime(2026, 6, 15, 23, 59, 59, tzinfo=UTC)

    assert observation_as_of([point], as_of=start_of_day).points
    assert observation_as_of([point], as_of=end_of_day).points


# ---------------------------------------------------------------------------
# Contract 2 — the sufficient-but-not-sound lag caveat (Class B / E)
# ---------------------------------------------------------------------------


def test_an_observation_stamped_just_before_as_of_is_retained_even_within_one_lag() -> None:
    """The filter is SUFFICIENT but not SOUND, and this pins the admitted case.

    A month's CPI is stamped the 1st but published around mid the *following*
    month. So an ``as_of`` one day after a stamp date admits a value that had
    not been released yet. The module discloses this rather than hiding it.

    The test asserts the **disclosed behaviour**, not a fix: the point dated the
    day before ``as_of`` is RETAINED. This is the caveat made executable — a
    future reader cannot mistake "as_of-filtered" for "knowable at as_of", and a
    future attempt to close the gap (should ``release_datetime`` become
    available) will fail this test and be forced to update the docstring with
    it, which is exactly where such a change belongs.
    """
    stamped_just_before = _point(_AS_OF.date() - timedelta(days=1), 3.0)

    report = observation_as_of([stamped_just_before], as_of=_AS_OF)

    assert [p.value for p in report.points] == [3.0], (
        "the not-yet-released-but-not-forward-dated point is retained; that is the "
        "documented SUFFICIENT-not-SOUND limitation, not a bug this test hides"
    )
    assert report.withheld == 0


def test_a_forward_dated_point_is_the_only_thing_the_filter_removes() -> None:
    """The filter removes by DATE ONLY — it is not a release-timing filter.

    The complement of the previous test: the module's entire effect is the
    ``observation_date > cutoff`` split. Nothing else is removed. This is what
    makes the caveat precise — the filter cannot be blamed for, or credited
    with, anything beyond forward-dating.
    """
    points = [
        _point(date(2026, 1, 1), 1.0),
        _point(date(2026, 3, 1), 2.0),
        _point(_AS_OF.date() - timedelta(days=1), 3.0),  # recent, possibly unreleased
        _point(_AS_OF.date() + timedelta(days=1), 4.0),  # forward-dated
        _point(date(2036, 1, 1), 5.0),  # the GDPPOT-style projection block
    ]

    report = observation_as_of(points, as_of=_AS_OF)

    assert [p.value for p in report.points] == [1.0, 2.0, 3.0]
    assert report.withheld == 2
    assert report.withheld_horizon == date(2036, 1, 1)


# ---------------------------------------------------------------------------
# Contract 3 — on_or_before vs as_of asymmetry (Class E / B)
# ---------------------------------------------------------------------------


def test_on_or_before_answers_a_historical_question_not_todays_cutoff() -> None:
    """``observation_on_or_before`` must NOT route through the as-of cutoff.

    The docstring says it is "Deliberately *not* routed through
    ``observation_as_of``: this answers 'what did the series say at date X in
    its own history' ... Applying today's cutoff there would be right by
    accident and wrong for a historical snapshot."

    The asymmetry is only visible when the two would DISAGREE, so the fixture is
    built for that: a series running to well past the historical target. Asking
    for a 2025-12-31 read must return the 2025 point, while today's as-of read
    returns the latest. If someone rerouted ``on_or_before`` through
    ``observation_as_of`` (which defaults ``as_of`` to now), the historical
    query would return the 2026 point instead — and this test fails.
    """
    points = [
        _point(date(2025, 9, 30), 10.0),
        _point(date(2025, 12, 31), 20.0),
        _point(date(2026, 3, 31), 30.0),
        _point(date(2026, 6, 30), 40.0),
    ]

    historical = observation_on_or_before(points, date(2025, 12, 31))
    assert historical is not None
    assert historical.value == 20.0, (
        "the historical read must return the 2025-12-31 point, not the latest — this is "
        "the asymmetry between on_or_before and as_of"
    )

    # And the as-of read, given an as_of of 'now', is a DIFFERENT question with a
    # different answer. Comparing them makes the asymmetry an asserted fact.
    today = observation_as_of(points, as_of=utc_now()).latest
    assert today is not None
    assert today.value == 40.0
    assert historical.value != today.value


def test_on_or_before_returns_none_when_nothing_precedes_the_target() -> None:
    """A target earlier than the whole series yields ``None``, never a guess."""
    points = [_point(date(2026, 1, 1), 1.0), _point(date(2026, 2, 1), 2.0)]
    assert observation_on_or_before(points, date(2025, 12, 31)) is None


def test_on_or_before_selects_the_latest_qualifying_point_not_the_first() -> None:
    """Multiple points precede the target; the most recent one is returned.

    The obvious off-by-one — returning the first match instead of the last —
    would be invisible on the two-point fixture above, so this one supplies
    three qualifying points and checks the boundary one is chosen.
    """
    points = [
        _point(date(2026, 1, 1), 1.0),
        _point(date(2026, 2, 1), 2.0),
        _point(date(2026, 3, 1), 3.0),
        _point(date(2026, 4, 1), 4.0),  # after the target
    ]
    chosen = observation_on_or_before(points, date(2026, 3, 15))
    assert chosen is not None
    assert chosen.value == 3.0


# ---------------------------------------------------------------------------
# Contract 4 — empty is a hard stop, never 0.0 (Class B / Section 21.4)
# ---------------------------------------------------------------------------


def test_a_wholly_forward_dated_series_reports_empty_and_latest_none() -> None:
    """The GDPPOT failure mode: every point is future-dated.

    "Returning ``None`` — never ``0.0``, never the first projection — forces the
    caller to handle absence explicitly." The test asserts ``is_empty`` is True,
    ``latest`` is ``None``, and the count/horizon are still reported — because
    the caller must be able to say *why* it is empty, not merely that it is.
    """
    points = [
        _point(date(2026, 9, 30), 100.0),
        _point(date(2036, 1, 1), 200.0),
    ]

    report = observation_as_of(points, as_of=_AS_OF)

    assert report.is_empty is True
    assert report.latest is None
    assert report.points == []
    assert report.withheld == 2
    assert report.withheld_horizon == date(2036, 1, 1)


def test_an_empty_input_is_distinguished_from_a_wholly_withheld_series() -> None:
    """An empty input and an all-forward-dated series look alike but differ.

    The docstring: "Distinct from 'the caller passed an empty list': that is a
    fetch failure, whereas an empty ``AsOfSeries`` means the series exists but is
    entirely forward-dated." Both have ``is_empty`` True (by construction — both
    have no realised points), but they differ in ``withheld``: zero for the
    fetch failure, positive for the projection block. This asserts that the two
    are distinguishable from the report, which is what lets a caller emit the
    right message.
    """
    fetch_failure = observation_as_of([], as_of=_AS_OF)
    projection_block = observation_as_of([_point(date(2036, 1, 1), 200.0)], as_of=_AS_OF)

    assert fetch_failure.is_empty and projection_block.is_empty
    assert fetch_failure.withheld == 0
    assert projection_block.withheld == 1
    assert fetch_failure.series_id == "unknown"
    assert projection_block.series_id == "test_series"


def test_latest_observation_returns_none_rather_than_zero() -> None:
    """The one-line helper inherits the hard stop.

    ``latest_observation`` is ``observation_as_of(...).latest``. Its contract is
    "``None`` rather than raising keeps the 'series unavailable' decision with
    the caller". The failure mode this guards is a caller doing
    ``latest_observation(points) or 0.0`` and silently reasoning on a zero that
    was never observed — so the helper must return ``None``, and the test says so
    explicitly.
    """
    assert latest_observation([], as_of=_AS_OF) is None
    assert latest_observation([_point(date(2036, 1, 1), 5.0)], as_of=_AS_OF) is None

    real = latest_observation(
        [_point(date(2026, 1, 1), 1.0), _point(date(2026, 2, 1), 2.0)], as_of=_AS_OF
    )
    assert real is not None and real.value == 2.0


# ---------------------------------------------------------------------------
# Contract 5 — no silent truncation; points sorted oldest-first
# ---------------------------------------------------------------------------


def test_points_are_sorted_oldest_first_regardless_of_input_order() -> None:
    """A provider's ordering is not a contract; the report imposes one.

    "``[-1]`` on an unsorted list silently picks an arbitrary point rather than
    the latest one." The fixture is deliberately shuffled so a pass-through
    implementation (no sort) returns the wrong ``latest``.
    """
    points = [
        _point(date(2026, 3, 1), 3.0),
        _point(date(2026, 1, 1), 1.0),
        _point(date(2026, 2, 1), 2.0),
    ]

    report = observation_as_of(points, as_of=_AS_OF)

    assert [p.value for p in report.points] == [1.0, 2.0, 3.0]
    assert report.latest is not None and report.latest.value == 3.0


def test_truncation_is_reported_not_silent() -> None:
    """``truncation_warning`` names the count and the horizon, or is ``None``.

    "No silent truncation." The warning is returned rather than appended so the
    caller decides whether the truncation matters; this asserts both halves —
    the string when there is truncation, and ``None`` when there is not (an
    unconditional warning would cry wolf on every clean series).
    """
    truncated = observation_as_of(
        [_point(date(2026, 1, 1), 1.0), _point(date(2036, 1, 1), 2.0)], as_of=_AS_OF
    )
    warning = truncated.truncation_warning(series_label="gdp_potential")
    assert warning is not None
    assert "1 forward-dated observation(s)" in warning
    assert "2036-01-01" in warning
    assert "2026-06-15" in warning

    clean = observation_as_of([_point(date(2026, 1, 1), 1.0)], as_of=_AS_OF)
    assert clean.truncation_warning() is None
    assert clean.was_truncated is False


def test_the_report_records_the_as_of_it_was_evaluated_at() -> None:
    """``as_of`` round-trips onto the report, so the read is reproducible.

    A report that did not carry its own cutoff could not be audited later: the
    caller's "now" is gone by the time anyone reads the result.
    """
    report = observation_as_of([_point(date(2026, 1, 1), 1.0)], as_of=_AS_OF)
    assert report.as_of == _AS_OF
    assert isinstance(report, AsOfSeries)


def test_series_id_defaults_from_the_points_and_can_be_overridden() -> None:
    """``series_id`` comes from the points, or from the argument when given.

    The override exists for a caller-built (derived) series, whose points'
    ``series_id`` would otherwise name the source rather than the derived field.
    """
    points = [_point(date(2026, 1, 1), 1.0, series_id="cpi_headline")]

    assert observation_as_of(points, as_of=_AS_OF).series_id == "cpi_headline"
    assert (
        observation_as_of(points, as_of=_AS_OF, series_id="derived_inflation").series_id
        == "derived_inflation"
    )


def test_as_of_defaults_to_now_when_omitted() -> None:
    """Omitting ``as_of`` evaluates at the current instant.

    The default is ``utc_now()``, so a point dated today is retained and a
    point dated far in the future is not. The test uses today's date (not a
    fixture constant) precisely because the default is about *now*.
    """
    today = _point(utc_now().date(), 1.0)
    far_future = _point(utc_now().date() + timedelta(days=365 * 10), 2.0)

    report = observation_as_of([today, far_future])

    assert [p.value for p in report.points] == [1.0]
    assert report.withheld == 1


@pytest.mark.parametrize("bad_target", [date(2025, 1, 1)])
def test_on_or_before_handles_a_target_outside_the_series(bad_target: date) -> None:
    """A target before the earliest point returns ``None`` (parametrised edge).

    Kept as a parametrised case so the edge is a named row rather than an
    inline assertion: the intent is "boundary behaviour on an out-of-range
    target", which is the kind of thing that deserves to be enumerable.
    """
    points = [_point(date(2026, 1, 1), 1.0)]
    assert observation_on_or_before(points, bad_target) is None
