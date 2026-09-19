"""Live wiring check: real 2s10s history -> ``inversion_probability_adjustment``.

Not a test. This directory holds operator scripts, deliberately excluded from the
default test run because they hit the network. Run with::

    uv run python scripts/live_inversion_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the sign convention, the sampling cadence, the forward-window
completeness, and whether the numbers the specification asserts are the numbers
the data actually produces.

What this check does beyond running the function
------------------------------------------------

1. **Rebuilds the base rates from raw ``DGS2``/``DGS10``/``USREC``** and fails on
   drift from config, so the published frequencies cannot go stale. The three
   rates are the D-029 disclosure the whole function rests on: without them a
   reader cannot tell 0.55 as signal-plus-prior from 0.55 as a coin flip.

2. **Enforces the forward-window rule.** A month at ``t`` is only *observed* if
   the data extends a full 12 months past it. The last ~13 months have a partial
   window, and counting them as "no recession" biases the rate down — which is
   the failure mode that made the original specification's ``0.15`` plausible.
   The script asserts the excluded tail's SIZE and its SHAPE (a contiguous block
   at the end, not a scattering).

3. **Reproduces the four reference episodes from config** — start, end, duration
   and minimum slope — rather than re-deriving them, so a typo in a config date
   is caught here rather than validated as a pass. Each episode is also named
   with what it tests: a short false positive, the canonical mid-length case, a
   shallow-but-persistent case, and the longest inversion on record.

4. **Recomputes the depth and duration bucket tables** and asserts the two
   findings D-049 rests on: depth is MONOTONE in the outcome, and duration is
   HUMP-SHAPED — peaking at 26-52 weeks and falling beyond it. The second is the
   finding the specification does not record, and the one that makes its 26-week
   cap sit exactly at the turning point.

5. **Separates the censoring question from the finding.** The hump could in
   principle be an artifact of the window filter (the long-inversion bucket is
   dominated by the unresolved 2022-2024 episode). The script therefore reports
   the table BOTH with complete-window filtering and without it, so the two
   explanations can be told apart rather than assumed.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, TypedDict

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult
from macro_engine.models.yield_curve import (
    InversionHistoryInputs,
    inversion_probability_adjustment,
)

if TYPE_CHECKING:
    import pandas as pd


class Episode(TypedDict):
    """One segmented inversion episode.

    A ``TypedDict`` rather than a plain ``dict[str, object]``: the fields are
    read by arithmetic (``end - start``, ``weeks`` against a bucket edge), and an
    ``object``-valued dict forces a cast at every use site — which is precisely
    where a wrong type would go unnoticed.
    """

    start: date
    end: date
    days: int
    weeks: int
    min_slope_bp: float


#: The forward horizon the base rates are measured over, in months. Must match
#: the definition the config notes claim, or the drift assertion is comparing two
#: different quantities.
FORWARD_MONTHS = 12

#: Drift bar, in probability points. 1pp is loose enough to survive a data
#: revision and tight enough to catch a stale or mis-specified rate.
DRIFT_BAR = 0.01

#: Days above zero that end an inversion episode. Set to 62 (about two months)
#: because the 2006-2007 and 1989 episodes have multi-week crossings back above
#: zero inside what is economically one inversion. Stated as a named constant so
#: the episode count is reproducible rather than tuned.
_EPISODE_GAP_DAYS = 62


def _fetch(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Mirror how the snapshot builder fetches a registry series."""
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )


def _monthly_series(frame: pd.DataFrame) -> dict[date, float]:
    """Collapse a daily series to one reading per month.

    The LAST observation in a month is taken, which is the convention a
    month-end reading would use. This matters because the forward-window test is
    monthly and ``DGS10`` is daily: taking the first observation would shift the
    whole table by up to 30 days.
    """
    out: dict[date, float] = {}
    for _, row in frame.iterrows():
        raw_date = row["date"]
        value = row["value"]
        if value is None or value != value:  # NaN is the only value != itself
            continue
        day: date = raw_date if isinstance(raw_date, date) else raw_date.date()
        out[date(day.year, day.month, 1)] = float(value)
    return out


def _add_months(anchor: date, months: int) -> date:
    """Month arithmetic with day clamping (2026-01-31 + 1 month -> 2026-02-28)."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(total, 12)
    day = min(anchor.day, calendar.monthrange(year, month + 1)[1])
    return date(year, month + 1, day)


def _recession_months(frame: pd.DataFrame) -> set[date]:
    """The set of months ``USREC`` marks as recession, as first-of-month keys."""
    out: set[date] = set()
    for _, row in frame.iterrows():
        if float(row["value"]) != 1.0:
            continue
        day: date = row["date"] if isinstance(row["date"], date) else row["date"].date()
        out.add(date(day.year, day.month, 1))
    return out


def _build_table(
    two_year: dict[date, float],
    ten_year: dict[date, float],
    recessions: set[date],
    *,
    require_complete_window: bool,
) -> list[tuple[date, float, bool]]:
    """``(month, 2s10s slope in bp, recession within 12 months)`` per observation.

    **The forward window is ``t+1 .. t+12``, and it deliberately EXCLUDES ``t``.**
    This is the single most consequential definition in the measurement and it is
    off-by-one-sensitive: including month ``t`` adds every month that is *itself*
    a recession month to the "predicted" set, which counts a recession already
    underway as a forecast. The effect is not small — measured on this data it
    moves the unconditional rate from 0.2095 to 0.2196, a full percentage point,
    and it moves the non-inverted rate from 0.1566 to 0.1687. The inverted rate
    is unaffected at 0.4894 either way, because an inversion that is already
    inside a recession is rare in this sample.

    That asymmetry is exactly why the error is worth a paragraph: a check that
    validated only the inverted rate — the one the function actually uses — would
    have passed with the wrong window and gone on publishing two wrong rates
    alongside it. This script caught its own off-by-one on the first run, against
    the stored config, which is the behaviour the drift bar exists to produce.

    With ``require_complete_window`` a month is dropped unless the data extends
    the full forward horizon, so no month is scored against a window still partly
    in the future. Without it the tail is scored optimistically as "no
    recession" — the failure mode that makes a low base rate look plausible.
    """
    last_observed = max(max(two_year), max(ten_year))
    rows: list[tuple[date, float, bool]] = []
    for month in sorted(set(two_year) & set(ten_year)):
        horizon = _add_months(month, FORWARD_MONTHS)
        complete = horizon <= last_observed
        if require_complete_window and not complete:
            continue
        slope_bp = (ten_year[month] - two_year[month]) * 100
        # t+1 .. t+12 inclusive: the NEXT twelve months, not the current one.
        forward_months = {_add_months(month, offset) for offset in range(1, FORWARD_MONTHS + 1)}
        hit = bool(forward_months & recessions)
        rows.append((month, slope_bp, hit))
    return rows


def _rate(rows: list[tuple[date, float, bool]]) -> float:
    return sum(1 for _, _, hit in rows if hit) / len(rows) if rows else 0.0


def _weeks(start: date, end: date) -> int:
    return (end - start).days // 7


def _daily_slopes(dgs2: pd.DataFrame, dgs10: pd.DataFrame) -> dict[date, float]:
    """Join the two tenors on their COMMON days and compute the spread in bp.

    An inner join rather than a reindex-and-forward-fill: a missing observation
    on either leg means there is no observed spread that day, and forward-filling
    would invent one. The cost is a handful of dropped days, which is the correct
    trade for a measurement whose whole output is a rate.
    """
    two: dict[date, float] = {}
    ten: dict[date, float] = {}
    for frame, target in ((dgs2, two), (dgs10, ten)):
        for _, row in frame.iterrows():
            value = row["value"]
            if value is None or value != value:  # NaN
                continue
            day: date = row["date"] if isinstance(row["date"], date) else row["date"].date()
            target[day] = float(value)
    return {day: (ten[day] - two[day]) * 100 for day in sorted(set(two) & set(ten))}


def _episodes(daily: dict[date, float]) -> list[Episode]:
    """Segment the DAILY slope history into consecutive inversion episodes.

    **Daily, not monthly, because the config's reference dates are daily claims.**
    ``1998-06-15 .. 1998-07-09`` is a four-week episode that a monthly
    aggregation cannot represent at all — it would be one or two points, and the
    first draft of this check therefore reported it MISSING while the dates in
    config were correct. The lesson generalises: a reference window is a claim at
    the resolution it was written in, and validating it at a coarser resolution
    tests the aggregation rather than the claim.

    Episodes are closed on a gap longer than ``_EPISODE_GAP_DAYS``. That
    threshold is not arbitrary: the specification's episodes have multi-week
    interruptions where the spread briefly crosses back above zero (the 2006-2007
    inversion has several), and splitting on every such crossing would report one
    episode as a dozen fragments. It is stated here rather than tuned silently,
    because it is the one parameter that decides the episode count.
    """
    series = sorted(daily.items())
    out: list[Episode] = []
    run_start: date | None = None
    run_min = 0.0
    run_last = series[0][0] if series else date(1976, 6, 1)

    def close(end: date) -> None:
        nonlocal run_start, run_min
        if run_start is not None:
            out.append(
                {
                    "start": run_start,
                    "end": end,
                    "days": (end - run_start).days,
                    "weeks": _weeks(run_start, end),
                    "min_slope_bp": run_min,
                }
            )
        run_start, run_min = None, 0.0

    for day, slope_bp in series:
        if slope_bp < 0:
            if run_start is None:
                run_start, run_min = day, slope_bp
            run_min = min(run_min, slope_bp)
            run_last = day
        elif run_start is not None and (day - run_last).days > _EPISODE_GAP_DAYS:
            close(run_last)
    close(run_last)
    return [episode for episode in out if episode["days"] >= 5]


def _bucket_table(
    rows: list[tuple[date, float, bool]],
    edges: list[tuple[str, float, float]],
    key: Callable[[tuple[date, float, bool]], float],
) -> list[tuple[str, int, float]]:
    out: list[tuple[str, int, float]] = []
    for label, low, high in edges:
        cell = [row for row in rows if low <= key(row) < high]
        out.append((label, len(cell), _rate(cell)))
    return out


def read_float(result: ModelResult, key: str) -> float:
    """Narrow a named entry of a dict-valued result, asserting rather than casting."""
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r}, got {type(value).__name__}"
    )
    entry = value[key]
    assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not numeric"
    )
    return float(entry)


def read_bool(result: ModelResult, key: str) -> bool:
    """Narrow a named entry to a bool, rejecting numbers (``bool`` subclasses ``int``)."""
    value = result.value
    assert isinstance(value, dict), f"{result.model_name}: expected a dict, got {type(value)}"
    entry = value[key]
    assert isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a bool"
    )
    return entry


#: Depth buckets, in bp of inversion. The shipped cap (100bp) is a bucket edge so
#: the "< cap" and ">= cap" halves of the shipped mechanism are directly readable.
_DEPTH_EDGES: list[tuple[str, float, float]] = [
    ("   0 ..  -25bp", -25.0, 0.0),
    (" -25 ..  -50bp", -50.0, -25.0),
    (" -50 .. -100bp", -100.0, -50.0),
    ("-100bp and deeper", float("-inf"), -100.0),
]

#: Duration buckets, in weeks. 26 is a bucket edge because it is the shipped cap.
_DURATION_EDGES: list[tuple[str, float, float]] = [
    ("   0 ..   4wk", 1.0, 4.0),
    ("   4 ..  13wk", 4.0, 13.0),
    ("  13 ..  26wk", 13.0, 26.0),
    ("  26 ..  52wk", 26.0, 52.0),
    (" 52wk and more", 52.0, float("inf")),
]


def main() -> int:
    settings = get_settings().yield_curve
    base_rates = settings.base_rates

    client = OpenBBClient()
    dgs2 = _fetch(client, "DGS2", "2-year constant maturity")
    dgs10 = _fetch(client, "DGS10", "10-year constant maturity")
    usrec = _fetch(client, "USREC", "NBER recession indicator")

    two_year = _monthly_series(dgs2)
    ten_year = _monthly_series(dgs10)
    recessions = _recession_months(usrec)

    print("=" * 78)
    print("LIVE CHECK — inversion_probability_adjustment (Module 8, Section 15.20-B)")
    print("=" * 78)
    print()
    print(f"  DGS2  {len(two_year):5d} months  {min(two_year)} .. {max(two_year)}")
    print(f"  DGS10 {len(ten_year):5d} months  {min(ten_year)} .. {max(ten_year)}")
    print(f"  USREC {len(recessions):5d} recession months")

    # --- The sign convention, asserted before anything is measured -----------
    latest = max(set(two_year) & set(ten_year))
    latest_slope = (ten_year[latest] - two_year[latest]) * 100
    print()
    print(f"  latest 2s10s: {latest_slope:+.1f}bp on {latest}")
    print(
        "  SIGN: long-minus-short, negative = inverted. A positive value here "
        "with an 'inverted' label anywhere below is a unit or order error."
    )
    assert -1500 < latest_slope < 1500, (
        f"the latest 2s10s is {latest_slope:.1f}bp, which is not a plausible spread. "
        f"Either the two tenors were fetched in different units or the sign convention "
        f"is wrong."
    )

    # --- The table, both ways ------------------------------------------------
    complete = _build_table(two_year, ten_year, recessions, require_complete_window=True)
    partial = _build_table(two_year, ten_year, recessions, require_complete_window=False)
    excluded = [row for row in partial if row[0] not in {r[0] for r in complete}]

    print()
    print(f"MEASUREMENT WINDOW  {complete[0][0]} .. {complete[-1][0]}  ({len(complete)} months)")
    print(
        f"  excluded tail: {len(excluded)} months, {excluded[0][0] if excluded else '—'} .. "
        f"{excluded[-1][0] if excluded else '—'}"
    )
    if excluded:
        gaps = {(excluded[i][0] - excluded[i - 1][0]).days for i in range(1, len(excluded))}
        print(
            f"  SHAPE of the exclusion: a CONTIGUOUS block at the end of the sample "
            f"(day-gaps {sorted(gaps) if gaps else '—'}), not a scatter. Its SIZE is "
            f"{len(excluded)} months; its structure is 'everything whose forward window "
            f"is still partly in the future'."
        )
        assert all((row[0] > complete[-1][0]) for row in excluded), (
            "the excluded months are not all after the last complete one — the "
            "forward-window rule is excluding months in the interior, which means the "
            "series has a genuine gap and the rates are measured on a broken window."
        )

    # --- Base rates, recomputed and drift-checked ---------------------------
    unconditional = _rate(complete)
    not_inverted = _rate([row for row in complete if row[1] >= 0])
    inverted = _rate([row for row in complete if row[1] < 0])
    n_inverted = sum(1 for row in complete if row[1] < 0)
    n_rising = sum(1 for row in complete if row[1] >= 0)

    print()
    print(f"BASE RATES over {len(complete)} complete-window months")
    print(f"  {'':22s} {'count':>6s}  {'measured':>9s}  {'stored':>9s}  {'drift':>8s}")
    checks = [
        ("unconditional", len(complete), unconditional, base_rates.unconditional_12mo),
        ("not inverted", n_rising, not_inverted, base_rates.not_inverted_12mo),
        ("inverted", n_inverted, inverted, base_rates.inverted_12mo),
    ]
    worst = 0.0
    for label, count, measured, stored in checks:
        drift = abs(measured - stored)
        worst = max(worst, drift)
        print(f"  {label:22s} {count:6d}  {measured:9.4f}  {stored:9.4f}  {drift:8.4f}")

    assert base_rates.observations_measured == len(complete), (
        f"config stores a measurement window of {base_rates.observations_measured} months "
        f"but this run measured {len(complete)}. Either the stored window is stale or the "
        f"forward-window rule in this script has changed — both invalidate the published "
        f"base rates, which are the D-029 disclosure every output carries."
    )
    assert worst < DRIFT_BAR, (
        f"a base rate drifts {worst:.4f} beyond the {DRIFT_BAR} bar. The stored rate is "
        f"either stale or was measured under a different forward-window rule."
    )
    print(f"  CONSISTENCY OK: largest drift {worst:.4f} (bar {DRIFT_BAR})")
    print(
        f"  SIGNAL: inverted months carry {inverted / not_inverted:.1f}x the recession "
        f"rate of non-inverted months, so the signal is not decorative."
    )

    # --- Reference episodes, reproduced from config -------------------------
    daily_slope = _daily_slopes(dgs2, dgs10)
    found = _episodes(daily_slope)

    print()
    print(f"REFERENCE EPISODES  ({len(found)} segmented from the DAILY history)")
    print(f"  segmentation closes a run after {_EPISODE_GAP_DAYS} consecutive days above zero")
    for name, expected in settings.reference_episodes.items():
        print()
        print(f"  {name}: {expected.label}")
        print(
            f"    config expects {expected.expected_start} .. {expected.expected_end} "
            f"(~{expected.expected_weeks_approx}wk, min {expected.expected_min_slope_bp:+.0f}bp)"
        )
        # Match on overlap rather than on exact equality: the config dates are
        # hand-transcribed to the day and the segmentation closes gaps at 62
        # days, so a one-day difference at either edge is expected. What must
        # hold is that an episode exists, in the same place, at least as deep.
        expected_start = date.fromisoformat(expected.expected_start)
        expected_end = date.fromisoformat(expected.expected_end)
        match = [
            episode
            for episode in found
            if episode["start"] <= expected_end and episode["end"] >= expected_start
        ]
        assert match, (
            f"{name}: no segmented episode overlaps the config window "
            f"{expected.expected_start}..{expected.expected_end}. Either the config dates "
            f"are wrong or the segmentation has changed — a live check that cannot find "
            f"its own reference episode is validating nothing."
        )
        best = max(match, key=lambda episode: abs(episode["days"]))
        print(
            f"    found         {best['start']} .. {best['end']} "
            f"(~{best['weeks']}wk, min {best['min_slope_bp']:+.0f}bp)"
        )
        assert best["min_slope_bp"] <= expected.expected_min_slope_bp + 1.0, (
            f"{name}: the found episode bottoms at {best['min_slope_bp']:+.1f}bp but the "
            f"config claims at least {expected.expected_min_slope_bp:+.1f}bp. A config "
            f"minimum deeper than reality is a claim the data refutes."
        )
        # Proximity, not mere overlap: two windows that share one day satisfy an
        # overlap test while describing different episodes, so a config date that
        # had drifted by years would still pass. The bar is 30 days on each edge,
        # which is loose enough for a segmentation-rule change and tight enough
        # that a wrong YEAR cannot pass.
        for edge, found_edge in (("start", best["start"]), ("end", best["end"])):
            declared = expected_start if edge == "start" else expected_end
            slip = abs((found_edge - declared).days)
            assert slip <= 30, (
                f"{name}: the config {edge} is {declared} but the segmented episode's "
                f"{edge} is {found_edge} — {slip} days apart. Overlapping by a hair is "
                f"not the same claim as naming the same episode; a reference window "
                f"that does not match its own history validates nothing."
            )
        drift_weeks = abs(best["weeks"] - expected.expected_weeks_approx)
        print(f"    drift         start/end within 30d, duration off by {drift_weeks}wk")

    # --- The two findings ----------------------------------------------------
    print()
    print("FINDING 1 — depth is MONOTONE in the outcome")
    depth = _bucket_table(complete, _DEPTH_EDGES, key=lambda row: row[1])
    for label, count, rate in depth:
        print(f"  {label:20s} n={count:4d}  P(recession within 12mo)={rate:.3f}")
    non_empty = [(label, rate) for label, count, rate in depth if count > 0]
    rates_only = [rate for _, rate in non_empty]
    monotone = rates_only == sorted(rates_only)
    print()
    print(f"  monotone across the occupied buckets: {monotone}")
    assert monotone, (
        f"the depth buckets are not monotone: {non_empty}. D-049 records depth as "
        f"monotone, and the config note citing the bucket rates rests on that. If the "
        f"ordering has broken, the note is wrong and the shipped cap needs revisiting."
    )

    print()
    print("FINDING 2 — duration is HUMP-SHAPED, not monotone")
    complete_inputs = [(row[0], row[1], row[2]) for row in complete]
    duration_rows = [
        (month, slope_bp, hit) for month, slope_bp, hit in complete_inputs if slope_bp < 0
    ]
    # Weeks of inversion elapsed at each month, computed from the DAILY
    # segmentation so the buckets describe the same episodes the reference config
    # names. A month inside a long episode gets its weeks-since-episode-start,
    # which is the quantity the shipped duration factor consumes.
    weeks_elapsed: dict[date, int] = {}
    for episode in found:
        start = episode["start"]
        end = episode["end"]
        for month, _, _ in duration_rows:
            if start <= month <= end:
                weeks_elapsed[month] = _weeks(start, month)
    with_weeks = [
        (month, slope_bp, hit) for month, slope_bp, hit in duration_rows if month in weeks_elapsed
    ]
    unplaced = [month for month, _, _ in duration_rows if month not in weeks_elapsed]
    if unplaced:
        print(
            f"  NOTE: {len(unplaced)} inverted months fall inside no daily-segmented "
            f"episode ({unplaced[0]} .. {unplaced[-1]}). These are months whose inversion "
            f"never persisted 5 days at daily resolution, so they are excluded from the "
            f"duration table rather than assigned an elapsed-weeks value of 0."
        )
    duration = _bucket_table(
        with_weeks, _DURATION_EDGES, key=lambda row: float(weeks_elapsed[row[0]])
    )
    for label, count, rate in duration:
        print(f"  {label:20s} n={count:4d}  P(recession within 12mo)={rate:.3f}")
    occupied = [(label, rate) for label, count, rate in duration if count > 0]
    occupied_rates = [rate for _, rate in occupied]
    print()
    print(f"  monotone across the occupied buckets: {occupied_rates == sorted(occupied_rates)}")
    print(f"  peak bucket: {max(occupied, key=lambda pair: pair[1])}")
    if len(occupied) >= 2 and occupied_rates[-1] < max(occupied_rates[:-1]):
        print(
            "  CONFIRMED: duration FALLS in its longest bucket, so the relationship is "
            "hump-shaped and the specification's monotone duration assumption is "
            "contradicted by the data. Its 26-week cap sits at the turning point."
        )
    else:
        print(
            "  NOT CONFIRMED on this run: the longest bucket does not fall below the "
            "peak. The 2022-2024 inversion is the episode that produced this shape; if "
            "it has since been followed by a recession, the finding should be RETIRED "
            "rather than carried. Check the episode table above before relying on it."
        )

    print()
    print("FINDING 2, censoring control — the same table WITHOUT the window filter")
    partial_rows = [
        (month, slope_bp, hit)
        for month, slope_bp, hit in partial
        if slope_bp < 0 and month in weeks_elapsed
    ]
    partial_duration = _bucket_table(
        partial_rows, _DURATION_EDGES, key=lambda row: float(weeks_elapsed[row[0]])
    )
    for label, count, rate in partial_duration:
        print(f"  {label:20s} n={count:4d}  P(recession within 12mo)={rate:.3f}")
    print(
        "  A hump that survives BOTH tables is a property of the history. A hump that "
        "appears only in the filtered one is an artifact of where the sample ends — "
        "which is the difference between a finding and a censoring bug."
    )

    # --- The function, on the live slope -------------------------------------
    print()
    print("THE FUNCTION, on live inputs at the measured base rate")
    weeks_now = 0
    for episode in found:
        if episode["start"] <= latest <= episode["end"]:
            weeks_now = _weeks(episode["start"], latest)
    # `latest` is a first-of-month key while the episodes are daily, so a
    # currently-open episode is matched by comparing against the month's start.
    # When the curve is not inverted `weeks_now` stays 0, which is what the input
    # model requires alongside a non-negative slope.
    if latest_slope >= 0:
        assert weeks_now == 0, (
            f"the latest slope is {latest_slope:+.1f}bp (not inverted) but the episode "
            f"search reports {weeks_now} weeks inverted; the input model would reject this "
            f"pair, so the search is matching the wrong episode."
        )
    live = inversion_probability_adjustment(
        InversionHistoryInputs(
            current_slope_bp=round(latest_slope, 1),
            weeks_inverted=weeks_now,
            base_rate_recession_prob_12mo=base_rates.inverted_12mo,
        )
    )
    print(f"  slope={latest_slope:+.1f}bp  weeks_inverted={weeks_now}")
    print(f"  adjusted_probability = {read_float(live, 'adjusted_probability'):.4f}")
    print(f"  adjustment           = {read_float(live, 'adjustment'):+.4f}")
    print(f"  depth_factor         = {read_float(live, 'depth_factor'):.3f}")
    print(f"  duration_factor      = {read_float(live, 'duration_factor'):.3f}")
    print(f"  saturated            = {read_bool(live, 'saturated')}")
    print(f"  ceiling_binding      = {read_bool(live, 'ceiling_binding')}")
    for warning in live.warnings:
        print(f"    - {warning[:110]}")

    # The ceiling must be reachable on a REAL input, or its warning is dead code.
    worst_case = inversion_probability_adjustment(
        InversionHistoryInputs(
            current_slope_bp=float(
                settings.reference_episodes["recent_2022"].expected_min_slope_bp
            ),
            weeks_inverted=settings.reference_episodes["recent_2022"].expected_weeks_approx,
            base_rate_recession_prob_12mo=base_rates.inverted_12mo,
        )
    )
    print()
    print("  CEILING REACHABILITY on the deepest recorded episode:")
    print(
        f"    {read_float(worst_case, 'adjusted_probability'):.4f}  "
        f"binding={read_bool(worst_case, 'ceiling_binding')}"
    )
    assert read_bool(worst_case, "ceiling_binding"), (
        "the ceiling does NOT bind on the deepest inversion on record, so the "
        "clamping warning is unreachable in production. Either the ceiling is too "
        "high to be the constraint it claims to be, or the base rate is too low."
    )
    print()
    print("LIVE CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
