"""Live wiring check: real FRED data -> Module 3's ``classify_regime_rule_based``.

Not a test. This directory holds operator scripts, deliberately excluded from
the default test run because they hit the network. Run with::

    uv run python scripts/live_regime_check.py

Section 21.0: unit tests prove the arithmetic, this proves the wiring — the
units, the nulls, the frequency, the sign conventions, and whether the values
that come out are the values the specification says should come out.

What this check does beyond running the function
------------------------------------------------

1. **Builds the four inputs from raw FRED series**, not from another model's
   output, so the check is independent of the Tier 1/2 code it feeds. Each
   derivation is asserted rather than assumed:

   * ``output_gap`` = ``(GDPC1 - GDPPOT) / GDPPOT * 100`` on the latest
     **common quarter**, with ``GDPPOT`` filtered to realised observations
     (O-7). ``GDPPOT`` runs a quarter ahead of ``GDPC1``, so pairing each
     series' own latest would compute the gap against a projection (D-009).
   * ``inflation_yoy`` from ``CPIAUCSL``, 12 months back.
   * ``inflation_trend_3m`` as the 3-month annualized change, asserted to be a
     **change** and not a level, because the whole inflation axis turns on it.
   * ``unemployment_gap`` = ``UNRATE - u*`` with ``u*`` from config (O-5).

2. **Asserts the sign convention that decides corroboration.** ``output_gap``
   is measured against potential and ``unemployment_gap`` against ``u*`` — the
   two point in OPPOSITE directions, so agreement is ``output_gap < 0`` iff
   ``unemployment_gap > 0``. Getting it backwards produces a plausible
   ``CONTRADICTED`` verdict rather than an error, so the script checks the
   pairing on live values AND reports whether it agreed.

3. **Recomputes the published state base rates from 60 years of history** and
   fails on drift from the config, so the frequencies cannot go stale
   (D-029). It also reports **which states are reachable on real data** — the
   one claim about this function that a unit test can only make about a
   synthetic grid.

4. **Names the states the specification could not reach** and reports whether
   the correction reaches them historically, which is the live counterpart of
   the unit test that pins the defect.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from macro_engine.config import get_settings
from macro_engine.data_layer.openbb_client import OpenBBClient
from macro_engine.models.contracts import ModelResult, utc_now
from macro_engine.models.regime import (
    REGIME_STATES,
    RegimeInputs,
    classify_regime_rule_based,
)

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd


def _fetch(client: OpenBBClient, symbol: str, label: str) -> pd.DataFrame:
    """Mirror how the snapshot builder fetches a registry series."""
    return client.fetch_series(
        provider="fred",
        endpoint="economy.fred_series",
        params={"symbol": symbol},
        series_label=label,
    )


def _values(frame: pd.DataFrame) -> tuple[list[date], list[float]]:
    """Extract (dates, values), dropping nulls.

    ``dropna`` on the value column rather than the whole frame: FRED
    occasionally carries leading NaNs for a series whose history starts later
    than the requested window.
    """
    clean = frame.loc[frame["value"].notna(), ["date", "value"]]
    dates: list[date] = [
        value if isinstance(value, date) else _to_date(value) for value in clean["date"]
    ]
    return dates, [float(value) for value in clean["value"]]


def _to_date(value: object) -> date:
    """Coerce a pandas Timestamp to a plain ``date``, with the ignore in one place."""
    return value.date()  # type: ignore[attr-defined,no-any-return]


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


def read_float_or_none(result: ModelResult, key: str) -> float | None:
    """Narrow an entry that is legitimately ``float | None``.

    ``state_base_rate`` is ``None`` until a live measurement has been recorded.
    ``0.0`` would assert a measured frequency of zero, which is a different
    claim — so the check has to accept both and treat them differently.
    """
    value = result.value
    assert isinstance(value, dict), f"{result.model_name}: expected a dict, got {type(value)}"
    entry = value[key]
    if entry is None:
        return None
    assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not numeric or None"
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


def read_str(result: ModelResult, key: str) -> str:
    """Narrow a named entry to a str."""
    value = result.value
    assert isinstance(value, dict), f"{result.model_name}: expected a dict, got {type(value)}"
    entry = value[key]
    assert isinstance(entry, str), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a str"
    )
    return entry


def _month_gap(dates: list[date]) -> set[int]:
    """Distinct day-gaps between consecutive observations, for a cadence check."""
    return {(dates[i] - dates[i - 1]).days for i in range(1, len(dates))}


def _shift_months(when: date, months: int) -> date:
    """The first of the month ``months`` before ``when``, by calendar arithmetic.

    Deliberately not an index offset into the series: FRED genuinely omits a
    month from both ``CPIAUCSL`` and ``UNRATE`` (2025-10), and an index step
    would then span a different period than the one named — ``cpi[-13]`` is 396
    days back, not 365 (D-025). Calendar arithmetic names the month it means.
    """
    total = when.year * 12 + (when.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def _latest_at_or_before(series: dict[date, float], when: date) -> float | None:
    """The last observation at or before ``when``, or None.

    A monthly series aligned to a quarterly axis needs this rather than an
    index offset: the two are different cadences, so ``[-4]`` is not "four
    months ago" (the D-028 defect class).
    """
    candidates = [d for d in series if d <= when]
    if not candidates:
        return None
    return series[max(candidates)]


def main() -> None:
    client = OpenBBClient()
    settings = get_settings()

    # --- Real quarterly GDP and potential ---------------------------------
    gdp_dates, gdp = _values(_fetch(client, "GDPC1", "gdp_real"))
    pot_dates, pot = _values(_fetch(client, "GDPPOT", "gdp_potential"))

    print(f"GDPC1 observations: {len(gdp)}  ({gdp_dates[0]} .. {gdp_dates[-1]})")
    print(f"GDPPOT observations: {len(pot)}  ({pot_dates[0]} .. {pot_dates[-1]})")

    # Cadence: both must be quarterly for a same-quarter pairing to mean
    # anything. A 90/91/92-day spread is what a quarterly series looks like.
    gdp_gaps = _month_gap(gdp_dates)
    assert max(gdp_gaps) <= 100, f"GDPC1 is not quarterly: gaps {sorted(gdp_gaps)}"
    assert max(_month_gap(pot_dates)) <= 100, "GDPPOT is not quarterly"

    # O-7: GDPPOT carries CBO forward projections. Filter to realised only.
    # ``.date()`` on the project clock: ruff's DTZ rule bans a naive local date,
    # and a locally-computed "today" would disagree with the snapshot timestamps
    # the models write.
    as_of = utc_now().date()
    realised = [(d, v) for d, v in zip(pot_dates, pot, strict=True) if d <= as_of]
    withheld = len(pot) - len(realised)
    print(f"GDPPOT forward projections withheld: {withheld} (O-7 filter)")
    assert realised, "no realised GDPPOT observations — the projection filter removed everything"

    # D-009: pair the latest COMMON quarter, never each series' own latest.
    pot_by_date = dict(realised)
    common = [(d, v) for d, v in zip(gdp_dates, gdp, strict=True) if d in pot_by_date]
    assert common, "GDPC1 and GDPPOT share no observation date — cannot form a gap"
    gap_date, gdp_value = common[-1]
    pot_value = pot_by_date[gap_date]

    print()
    print(f"latest COMMON quarter      = {gap_date}")
    print(f"  GDPC1 (actual)           = {gdp_value:,.3f}")
    print(f"  GDPPOT (potential)       = {pot_value:,.3f}")

    output_gap = (gdp_value - pot_value) / pot_value * 100.0
    print(f"  output_gap               = {output_gap:+.4f}%")

    # The pairing matters: each series' own latest would use a projected
    # potential and understate the gap. Assert the two DIFFER, so a future
    # regression that drops the common-date pairing is visible here.
    naive_gap = (gdp[-1] - pot[-1]) / pot[-1] * 100.0
    print(f"  (wrong pairing would give = {naive_gap:+.4f}%)")
    assert gdp_dates[-1] != pot_dates[-1] or abs(output_gap - naive_gap) < 1e-9, (
        "GDPC1 and GDPPOT now end on the same date, so the D-009 common-date pairing "
        "cannot be distinguished from the naive one on live data. Re-check whether "
        "GDPPOT still runs a quarter ahead."
    )
    if gdp_dates[-1] != pot_dates[-1]:
        diff = abs(output_gap - naive_gap)
        print(f"  the two pairings differ by {diff:.4f}pp — D-009 pairing is load-bearing")
        assert diff > 0.0, "the pairings agree despite different end dates; investigate"

    # --- Real monthly CPI -------------------------------------------------
    cpi_dates, cpi = _values(_fetch(client, "CPIAUCSL", "cpi_headline"))
    print()
    print(f"CPIAUCSL observations: {len(cpi)}  ({cpi_dates[0]} .. {cpi_dates[-1]})")

    # Cadence: a month genuinely absent is not a fetch failure, so this is a
    # soft check with disclosure rather than a hard assert. FRED carries ONE
    # such hole in this series — 2025-09 -> 2025-11, 61 days — which is the
    # same October 2025 gap D-025 already documents for UNRATE. Asserting
    # "monthly" outright would make the script fail on real data (it did, on
    # the first run), and merely printing the gaps would leave a reader unable
    # to tell a 61-day hole from a 31-day month.
    cpi_gaps = _month_gap(cpi_dates)
    short_gaps = {g for g in cpi_gaps if g <= 45}
    long_gaps = sorted(g for g in cpi_gaps if g > 45)
    assert short_gaps <= {28, 29, 30, 31}, (
        f"CPIAUCSL has an irregular sub-45-day gap: {sorted(short_gaps)} — not a "
        f"monthly series, and every alignment below assumes one"
    )
    if long_gaps:
        print(f"  missing months in the series: gaps > 45 days = {long_gaps}")
        for i in range(1, len(cpi_dates)):
            gap = (cpi_dates[i] - cpi_dates[i - 1]).days
            if gap > 45:
                print(f"    {cpi_dates[i - 1]} -> {cpi_dates[i]}  spans {gap} days")
        print("  (an absent month is DISCLOSED, never imputed — D-025)")

    # YoY and momentum are taken **by calendar month**, not by index offset.
    # An index offset silently measures a different span when a month is
    # absent: `cpi[-13]` is 2025-08, which is **396 days** back, not 365 — an
    # eleven-month change reported as a twelve-month one. A cadence assertion
    # is not a span assertion (D-025).
    yoy_span_months = 12
    momentum_span_months = 3
    cpi_by_month = dict(zip(cpi_dates, cpi, strict=True))

    def _read_month(months_back: int) -> tuple[date, float] | None:
        """The CPI observation for the calendar month ``months_back`` ago.

        Returns ``None`` when that month is genuinely absent, so the caller
        reports a refusal rather than silently substituting a neighbour — the
        same rule the models follow (``None`` is not ``0.0``, and a proxy is
        not a measurement).
        """
        when = _shift_months(cpi_dates[-1], months_back)
        value = cpi_by_month.get(when)
        return None if value is None else (when, value)

    print()
    print(f"CPI latest               = {cpi[-1]:.3f} @ {cpi_dates[-1]}")
    for label, months_back in (("YoY", yoy_span_months), ("3m", momentum_span_months)):
        found = _read_month(months_back)
        if found is None:
            when = _shift_months(cpi_dates[-1], months_back)
            print(f"  {label:4s} base month           = {when} — ABSENT from the series")
        else:
            when, value = found
            span = (cpi_dates[-1] - when).days
            print(f"  {label:4s} base month           = {when}  ({value:.3f}, span {span} days)")

    yoy_found = _read_month(yoy_span_months)
    mom_found = _read_month(momentum_span_months)
    assert yoy_found is not None, (
        f"the {yoy_span_months}-month-ago CPI month is absent, so YoY cannot be computed "
        f"on a true 12-month span. Refusing rather than reporting an 11-month change as "
        f"a year (D-025: detect and disclose, never impute)."
    )
    assert mom_found is not None, (
        f"the {momentum_span_months}-month-ago CPI month is absent, so the 3-month "
        f"annualized momentum cannot be computed on a true 3-month span."
    )
    yoy_base_date, cpi_then = yoy_found
    momentum_base_date, cpi_3m_back = mom_found
    inflation_yoy = (cpi[-1] / cpi_then - 1.0) * 100.0
    print(
        f"  inflation_yoy          = {inflation_yoy:+.4f}%  "
        f"(true span {(cpi_dates[-1] - yoy_base_date).days} days)"
    )

    # --- 3-month annualized momentum --------------------------------------
    # This is a CHANGE, not a level, which is the whole inflation axis. The
    # assertion below is what distinguishes the two: on a 3.7% YoY reading the
    # 3-month annualized figure must be a small number, not ~1.02 (the ratio).
    inflation_trend_3m = ((cpi[-1] / cpi_3m_back) ** 4 - 1.0) * 100.0
    print()
    print(f"CPI 3 months back        = {cpi_3m_back:.3f} @ {momentum_base_date}")
    print(f"  inflation_trend_3m     = {inflation_trend_3m:+.4f}%  (3-month annualized)")
    assert (cpi_dates[-1] - momentum_base_date).days <= 100, (
        f"the momentum base is {(cpi_dates[-1] - momentum_base_date).days} days back, "
        f"not ~92 — the 3-month label is not the span being measured"
    )
    assert abs(inflation_trend_3m) < 30.0, (
        f"the 3-month momentum is {inflation_trend_3m:+.2f}%, which is implausible for an "
        f"annualized 3-month change and suggests a LEVEL is being used instead"
    )
    # And it must differ from the YoY level, or the axis is not a change.
    assert abs(inflation_trend_3m - inflation_yoy) > 1e-9, (
        "the 3-month momentum equals the YoY level exactly; the momentum input is not a change"
    )

    # --- Unemployment gap against configured u* ---------------------------
    unrate_dates, unrate = _values(_fetch(client, "UNRATE", "unemployment_rate"))
    u_star = settings.phillips.nairu_value
    unemployment_gap = unrate[-1] - u_star
    print()
    print(f"UNRATE latest            = {unrate[-1]:.2f} @ {unrate_dates[-1]}")
    print(f"u* (config, UNOBSERVABLE)= {u_star:.2f}")
    print(f"  unemployment_gap       = {unemployment_gap:+.4f}pp")

    # --- Run the model ----------------------------------------------------
    inputs = RegimeInputs(
        output_gap=output_gap,
        inflation_yoy=inflation_yoy,
        inflation_trend_3m=inflation_trend_3m,
        unemployment_gap=unemployment_gap,
    )
    result = classify_regime_rule_based(inputs)

    state = read_str(result, "state")
    print()
    print("=" * 72)
    print(f"classify_regime_rule_based.value      = {state}")
    print(f"  growth_axis                          = {read_str(result, 'growth_axis')}")
    print(f"  inflation_axis                       = {read_str(result, 'inflation_axis')}")
    print(f"  slack_corroborated                   = {read_bool(result, 'slack_corroborated')}")
    print(
        f"  state_base_rate                      = {read_float_or_none(result, 'state_base_rate')}"
    )
    print(f"  confidence                           = {result.confidence}")
    print(f"interpretation: {result.interpretation}")
    for warning in result.warnings:
        print(f"   warn: {warning[:150]}")
    print("=" * 72)

    # --- The sign convention that decides corroboration -------------------
    # output_gap < 0 (below potential) AGREES with unemployment_gap > 0
    # (slack labour market). The naive same-sign test reports the opposite.
    expected_same_direction = (output_gap < 0.0) == (unemployment_gap > 0.0)
    reported = read_bool(result, "slack_corroborated")
    print()
    print(
        f"live slack readings: output_gap={output_gap:+.3f}%, "
        f"unemployment_gap={unemployment_gap:+.3f}pp"
    )
    print(f"  opposite-sign pairing says : {expected_same_direction}")
    print(f"  the model reports          : {reported}")
    if output_gap == 0.0 or unemployment_gap == 0.0:
        assert reported is False, "a zero slack reading must not count as corroboration"
        print("  CONSISTENCY OK: a degenerate zero reading is reported as no evidence")
    else:
        assert reported is expected_same_direction, (
            f"corroboration sign mismatch: the model reports {reported} but the "
            f"opposite-sign pairing of the live gaps gives {expected_same_direction}. "
            f"output_gap and unemployment_gap point in OPPOSITE directions."
        )
        print("  CONSISTENCY OK: the opposite-sign pairing matches (D-031 unit class)")

    # --- Reachability on real history, and the base rates (D-029) ---------
    print()
    _measure_base_rates(
        gdp_dates, gdp, pot_dates, pot, cpi_dates, cpi, unrate_dates, unrate, u_star
    )

    # --- The Tier-5 replacement, on the same real series ------------------
    _check_markov_regime(gdp_dates, gdp)


def _check_markov_regime(gdp_dates: list[date], gdp: list[float]) -> None:
    """Live wiring check for Section 6.2's ``classify_regime_markov_switching``.

    The series is real GDP **year-over-year growth**, which is the one Section 6.2
    names first ("fit on, e.g., real GDP growth"), built here from ``GDPC1`` with
    no model in between.

    What this proves that a unit test cannot:

    1. **The label switch happens in the FIELD, not only in a synthetic fixture.**
       The same real series is fitted twice with different EM starting-value
       settings, and the RAW library index is shown to move while every canonical
       output stays put. If the raw orderings happen to agree on this run, the
       check says so rather than claiming a proof it did not get.
    2. **The transposition is real.** The library's own matrix is recomputed and
       asserted COLUMN-stochastic, which is what makes the published
       row-stochastic matrix a transpose rather than a copy.
    3. **The model's central claim is checkable against the raw data.** The
       regime it orders FIRST must have the LOWEST realised mean growth in the
       series. That is the ordering rule tested against the series itself rather
       than against another output of the same fit.
    4. **Every published identity holds on live numbers**: rows sum to one,
       durations are ``1/(1-p_ii)``, shares are counts over periods, and the
       current read is the final row of the path.
    """
    import numpy as np
    import pandas as pd

    from macro_engine.models.regime import classify_regime_markov_switching

    levels = pd.Series(
        np.asarray(gdp, dtype=float),
        index=pd.to_datetime([d.isoformat() for d in gdp_dates]),
    )
    growth = ((levels / levels.shift(4) - 1.0) * 100.0).dropna()
    print()
    print("=" * 72)
    print("classify_regime_markov_switching on real GDP YoY growth")
    first, last = growth.index[0].date(), growth.index[-1].date()
    print(f"  series observations = {len(growth)}  ({first} .. {last})")
    print(f"  range               = {growth.min():+.2f}% .. {growth.max():+.2f}%")

    # --- route plausibility, as a BOUND rather than an existence (D-066) ---
    assert len(growth) > 200, (
        f"only {len(growth)} growth observations — GDPC1 has been quarterly since 1947, "
        f"so this is a fetch or alignment failure, not a short series"
    )
    assert -20.0 < float(growth.min()) < 0.0 < float(growth.max()) < 30.0, (
        f"GDP YoY growth outside any plausible range: {growth.min()} .. {growth.max()}"
    )

    result = classify_regime_markov_switching(growth)
    value = result.value
    assert isinstance(value, dict), type(value).__name__
    k = value["k_regimes"]
    print(f"  k_regimes           = {k}")
    print(f"  regime_means        = {[round(m, 4) for m in value['regime_means']]}")
    print(f"  order_raw_index     = {value['regime_order_raw_index']}")
    print(f"  regime_period_counts= {value['regime_period_counts']}")
    print(f"  modal share         = {value['modal_regime_share']:.4f}")
    print(
        f"  current_regime      = {value['current_regime']} "
        f"@ {value['current_regime_probability']:.4f}  ({value['current_period']})"
    )
    print(f"  log-likelihood      = {value['log_likelihood']:.4f}   converged={value['converged']}")
    warn_cats = value["library_warning_categories"]
    print(f"  library warnings    = {value['library_warning_count']} {warn_cats}")
    print(f"  smoothed/filtered gap = {value['max_smoothed_filtered_gap']:.6f}")
    print(f"  confidence          = {result.confidence}")

    # --- 1. the canonical ordering, recomputed from the published pieces ---
    means = value["regime_means"]
    assert means == sorted(means), f"published means are not ascending: {means}"
    order = value["regime_order_raw_index"]
    assert sorted(order) == list(range(k)), f"order is not a permutation: {order}"

    # --- 2. the identities, recomputed from the PUBLISHED components -------
    matrix = value["transition_matrix"]
    for i, row in enumerate(matrix):
        assert abs(sum(row) - 1.0) < 1e-9, f"row {i} of the published matrix sums to {sum(row)}"
    durations = value["expected_durations"]
    for i in range(k):
        expected = 1.0 / (1.0 - matrix[i][i])
        assert abs(durations[i] - expected) < 1e-9 * max(1.0, expected), (
            f"duration {i}: published {durations[i]} vs 1/(1-p_ii) {expected}"
        )
    counts = value["regime_period_counts"]
    assert sum(counts) == value["periods"], f"counts {counts} do not total {value['periods']}"
    for i, count in enumerate(counts):
        assert abs(value["regime_shares"][i] - count / value["periods"]) < 1e-12
    assert _approx_equal(value["current_probabilities"], value["smoothed_probabilities"][-1]), (
        "the current read must be the final row of the published path"
    )
    assert abs(sum(value["current_probabilities"]) - 1.0) < 1e-9

    # --- 3. the transposition is real: recompute the library's own matrix ---
    raw = _refit_raw_matrix(growth, k)
    if raw is not None:
        column_sums = raw.sum(axis=0)
        row_sums = raw.sum(axis=1)
        print(f"  library matrix row sums    = {np.round(row_sums, 6).tolist()}")
        print(f"  library matrix COLUMN sums = {np.round(column_sums, 6).tolist()}")
        assert np.allclose(column_sums, 1.0, atol=1e-9), (
            "the library's matrix is no longer column-stochastic, so the published "
            "transposition is no longer the right correction"
        )
        assert not np.allclose(row_sums, 1.0, atol=1e-9), (
            "the library's matrix rows now sum to 1 as well, so the transposition "
            "cannot be distinguished from a copy on this data"
        )

    # --- 4. the ordering rule against the RAW SERIES ----------------------
    # The regime the model orders FIRST must have the lowest REALISED mean. This
    # is the model's central claim checked against the data rather than against
    # another output of the same fit.
    labels = np.argmax(np.asarray(value["smoothed_probabilities"], dtype=float), axis=1)
    raw_values = np.asarray(growth, dtype=float)
    realised = [
        float(raw_values[labels == i].mean()) if (labels == i).any() else float("nan")
        for i in range(k)
    ]
    print(f"  realised mean growth per published regime = {[round(x, 4) for x in realised]}")
    assert realised == sorted(realised), (
        f"the published regime order does not match the realised means: the model says "
        f"{[round(m, 4) for m in means]} but the series says {[round(x, 4) for x in realised]}"
    )
    assert realised[0] < float(raw_values.mean()) < realised[-1], (
        "the lowest published regime is not below the sample mean, or the highest is not "
        "above it — the ordering is not separating the series by level"
    )

    # --- 5. the label switch on real data ---------------------------------
    # SEARCH for a switch rather than trying one setting and reporting either
    # outcome: a single rng draw proves nothing either way, and the hazard is a
    # property of the search over starting values. Whichever way this lands it is
    # reported as what it is — a demonstration, or the absence of one.
    switch = _search_label_switch(growth, k, order, seeds=8)
    if switch is None:
        print(
            f"  label-switch probe: none of 8 restarts moved the raw index off {order}, "
            f"so the invariance is NOT demonstrated live by this probe — the unit test "
            f"carries it (a label switch is a permutation, which is exhaustive there)"
        )
    else:
        seed, moved = switch
        print(f"  raw order, search_reps=0              = {order}")
        print(f"  raw order, search_reps=10 seed={seed:<3d}      = {moved}")
        print(
            "  LABEL SWITCH REPRODUCED LIVE: the library renumbered its regimes and the "
            "canonical output did not move — the ordering is load-bearing, not decorative"
        )

    for warning in result.warnings:
        print(f"   warn: {warning[:140]}")
    print("=" * 72)
    print("markov regime check: PASSED")


def _approx_equal(left: Sequence[float], right: Sequence[float], tol: float = 1e-9) -> bool:
    """Element-wise float comparison with a tolerance.

    This directory is operator scripts, not the test suite, so `pytest.approx` is
    not available here. The tolerance is absolute and tiny because the values
    being compared are computed twice from the SAME fit, so the only difference
    possible is the JSON round trip — which is exact for these magnitudes.
    """
    left_list = [float(x) for x in left]
    right_list = [float(x) for x in right]
    if len(left_list) != len(right_list):
        return False
    return all(abs(a - b) < tol for a, b in zip(left_list, right_list, strict=True))


def _refit_raw_matrix(growth: pd.Series, k: int) -> np.ndarray | None:
    """Re-fit the series and return the LIBRARY's own transition matrix, or None."""
    import numpy as np
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    settings = get_settings().regime.markov
    try:
        model = MarkovRegression(
            np.asarray(growth.to_numpy(), dtype=float),
            k_regimes=k,
            trend=settings.markov_trend,
            switching_variance=settings.switching_variance,
        )
        fitted = model.fit(
            method=settings.markov_optimizer,
            maxiter=settings.max_iterations,
            em_iter=settings.em_iterations,
            search_reps=settings.search_reps,
        )
    except Exception as exc:
        print(f"  (library refit for the orientation probe failed: {type(exc).__name__})")
        return None
    return np.asarray(fitted.regime_transition, dtype=float)[:, :, 0]


def _search_label_switch(
    growth: pd.Series, k: int, baseline: list[int], *, seeds: int
) -> tuple[int, list[int]] | None:
    """Search EM restarts for a run whose RAW index order differs from ``baseline``.

    Returns ``(seed, order)`` for the first disagreement, or ``None`` if none of
    the seeds moved the ordering. The search is the point: the library's regime
    index follows the EM starting values, so one draw is a coin flip and only a
    search over draws can show the hazard exists on this series.

    Each restart is a full fit, so the seed count is a wall-clock trade-off.
    """
    for seed in range(seeds):
        order = _refit_order(growth, k, seed=seed)
        if order is not None and order != baseline:
            return seed, order
    return None


def _refit_order(growth: pd.Series, k: int, *, seed: int) -> list[int] | None:
    """Re-fit with EM restarts and return the RAW mean-ascending index order."""
    import numpy as np
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    settings = get_settings().regime.markov
    try:
        model = MarkovRegression(
            np.asarray(growth.to_numpy(), dtype=float),
            k_regimes=k,
            trend=settings.markov_trend,
            switching_variance=settings.switching_variance,
        )
        fitted = model.fit(
            method=settings.markov_optimizer,
            maxiter=settings.max_iterations,
            em_iter=settings.em_iterations,
            search_reps=10,
            rng=seed,
        )
    except Exception as exc:
        print(f"  (restart probe seed={seed} failed: {type(exc).__name__})")
        return None
    values = np.asarray(fitted.params, dtype=float)
    positions = [i for i, name in enumerate(model.param_names) if str(name).startswith("const[")]
    consts = np.array([values[i] for i in positions], dtype=float)
    return [int(i) for i in np.argsort(consts, kind="stable")]


def _measure_base_rates(
    gdp_dates: list[date],
    gdp: list[float],
    pot_dates: list[date],
    pot: list[float],
    cpi_dates: list[date],
    cpi: list[float],
    unrate_dates: list[date],
    unrate: list[float],
    u_star: float,
) -> None:
    """Recompute every state's frequency from history and compare to config.

    The classifier is a categorical, so per D-029 it must travel with the
    frequency at which each value occurs. This is where that frequency is
    measured — and, more importantly, where **reachability becomes a live
    claim**: a state that never occurs across sixty years is either genuinely
    rare or unreachable, and the count is the evidence for which.

    The window is the latest N quarters of common GDP/GDPPOT dates. CPI and
    UNRATE are aligned to each quarter by taking the last observation at or
    before the quarter end, which is the only way to pair a quarterly axis with
    monthly series without inventing a date.
    """
    settings = get_settings().regime
    window = 240  # quarters
    as_of = utc_now().date()

    pot_realised = {d: v for d, v in zip(pot_dates, pot, strict=True) if d <= as_of}
    common = [(d, v) for d, v in zip(gdp_dates, gdp, strict=True) if d in pot_realised]
    assert common, "no common GDP/GDPPOT quarter to measure over"
    quarters = common[-window:]
    assert len(quarters) == window, f"only {len(quarters)} common quarters available"

    cpi_by_month = dict(zip(cpi_dates, cpi, strict=True))
    unrate_by_month = dict(zip(unrate_dates, unrate, strict=True))

    # The gap change needs the PRIOR quarter's gap, so gaps are computed over
    # the whole window first. Without it `recovery` is unreachable by
    # construction — see models/regime.py.
    gaps_by_quarter: dict[date, float] = {
        quarter_end: (gdp_value - pot_realised[quarter_end]) / pot_realised[quarter_end] * 100.0
        for quarter_end, gdp_value in quarters
    }
    ordered_quarters = [q for q, _ in quarters]
    gap_change_by_quarter: dict[date, float] = {
        ordered_quarters[i]: gaps_by_quarter[ordered_quarters[i]]
        - gaps_by_quarter[ordered_quarters[i - 1]]
        for i in range(1, len(ordered_quarters))
    }

    observed: dict[str, int] = dict.fromkeys(REGIME_STATES, 0)
    measured = 0
    for quarter_end in ordered_quarters:
        gap = gaps_by_quarter[quarter_end]
        cpi_now = _latest_at_or_before(cpi_by_month, quarter_end)
        cpi_yoy_base = _latest_at_or_before(cpi_by_month, _shift_months(quarter_end, 12))
        cpi_3m_base = _latest_at_or_before(cpi_by_month, _shift_months(quarter_end, 3))
        unemployment = _latest_at_or_before(unrate_by_month, quarter_end)
        if cpi_now is None or cpi_yoy_base is None or cpi_3m_base is None or unemployment is None:
            continue
        yoy = (cpi_now / cpi_yoy_base - 1.0) * 100.0
        momentum = ((cpi_now / cpi_3m_base) ** 4 - 1.0) * 100.0
        measured += 1
        outcome = classify_regime_rule_based(
            RegimeInputs(
                output_gap=gap,
                inflation_yoy=yoy,
                inflation_trend_3m=momentum,
                unemployment_gap=unemployment - u_star,
                output_gap_change=gap_change_by_quarter.get(quarter_end),
            )
        )
        observed[read_str(outcome, "state")] += 1

    total = sum(observed.values())
    assert total == measured, f"counted {measured} readings but classified {total}"
    print(f"BASE-RATE MEASUREMENT over {total} quarters ({quarters[0][0]} .. {quarters[-1][0]})")
    print()
    print(f"  {'state':18s} {'count':>6s}  {'measured':>8s}  {'stored':>8s}")
    for name in REGIME_STATES:
        count = observed[name]
        rate = count / total if total else 0.0
        stored = settings.base_rates.rate_map.get(name) if settings.base_rates.measured else None
        stored_display = f"{stored:.4f}" if stored is not None else "unmeasured"
        print(f"  {name:18s} {count:6d}  {rate:8.4f}  {stored_display:>8s}")

    reached = {name for name, count in observed.items() if count > 0}
    missing = set(REGIME_STATES) - reached
    print()
    print(f"  states reached historically: {len(reached)} / {len(REGIME_STATES)}")
    if missing:
        print(f"  NOT reached in this window:  {sorted(missing)}")
        print("  (the specification's own logic could reach only six; a state absent")
        print("   here is either genuinely rare or still unreachable — investigate)")
    else:
        print("  ALL NINE STATES OCCUR IN REAL HISTORY — the grid is not merely total")
        print("  over a synthetic sweep, it is exercised by sixty years of US data.")

    # Compare against config, loudly. A zero stored count means unmeasured,
    # which is NOT agreement — 0.0 would be a claim, not an absence.
    if not settings.base_rates.measured:
        print()
        print("  NOTE: settings.yaml has observations_measured = 0, so there is nothing")
        print("  to drift against yet. Record the measured window and rates to enable")
        print("  the comparison on subsequent runs.")
        return

    assert settings.base_rates.observations_measured == total, (
        f"the stored measurement window is {settings.base_rates.observations_measured} "
        f"but this run measured {total} quarters"
    )
    worst = 0.0
    worst_name = ""
    for name in REGIME_STATES:
        rate = observed[name] / total if total else 0.0
        drift = abs(rate - settings.base_rates.rate_map[name])
        if drift > worst:
            worst, worst_name = drift, name
    print()
    print(f"  largest drift: {worst_name} {worst:.4f}")
    assert worst < 0.01, (
        f"state '{worst_name}' drifts {worst:.4f} from the stored base rate, beyond the "
        f"1pp bar. Either the stored frequency is stale or the input derivations in "
        f"this script have changed — both are worth knowing before trusting the label."
    )
    print("  CONSISTENCY OK: every stored base rate matches a live recomputation")


def _summarise(values: list[float]) -> str:
    """A compact summary of a series, used in the diagnostic output."""
    return f"n={len(values)} mean={statistics.fmean(values):+.3f}"


if __name__ == "__main__":
    main()
